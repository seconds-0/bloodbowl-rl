#!/usr/bin/env python
"""Validation for heterogeneous league seeding (no CUDA required).

Covers:
  1. tools/build_league.py writes exactly the layout the (patched)
     selfplay.setup() reads: <out>/pool/{i:016d}.bin + league_seeds.json,
     with hard size verification and refusal to clobber an existing pool.
  2. training/selfplay_league.patch applies cleanly to the pinned vendored
     pufferlib/selfplay.py (git apply --check).
  3. The PATCHED setup(), imported in plain python with a stubbed
     pufferlib._C backend, actually loads each seed into its bank index,
     skips the bootstrap save, starts every bank's opponent at its seed, and
     initializes the opponent pool as the ordered seed set — i.e. it WOULD
     load the seeds on the real backend.
  4. The patched bootstrap path (league_preseed empty) is behaviorally
     identical to upstream: one save, every bank loads it, pool of one.
  5. Failure modes raise: seed-count != num_frozen_banks, corrupted seed size.
  6. build_perm_tags routing for the run_league.sh numbers (5 banks,
     frozen_bank_pct 0.08, total_agents 4096, num_buffers 2): per-bank
     historical env counts and per-buffer permutation validity.

Run with any python that has numpy:
  python3 training/test_selfplay_league.py
PufferLib location: $PUFFERLIB_DIR, else <root>/vendor/PufferLib (also
resolved from a git worktree under .claude/worktrees/<x>/).
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PATCH = os.path.join(ROOT, 'training', 'selfplay_league.patch')

sys.path.insert(0, os.path.join(ROOT, 'tools'))
from build_league import (  # noqa: E402
    DEFAULT_EXPECT_BYTES, LeagueError, build_league, parse_seed_args)
from checkpoint_lineage import (  # noqa: E402
    lineage_from_run_manifest, sidecar_path, write_lineage)


def find_pufferlib():
    cands = [os.environ.get('PUFFERLIB_DIR', '')]
    cands.append(os.path.join(ROOT, 'vendor', 'PufferLib'))
    # Git worktrees live at <main>/.claude/worktrees/<x>; vendor/ is
    # gitignored so it only exists in the main checkout.
    main = os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))
    cands.append(os.path.join(main, 'vendor', 'PufferLib'))
    for c in cands:
        if c and os.path.isfile(os.path.join(c, 'pufferlib', 'selfplay.py')):
            return c
    raise unittest.SkipTest('vendor/PufferLib not found (set PUFFERLIB_DIR)')


class FakeBackend:
    '''Records the backend calls setup() makes (bindings.cu surface).'''

    def __init__(self, num_envs):
        self._num_envs = num_envs
        self.saves = []          # paths passed to save_weights
        self.bank_loads = []     # (bank_idx, path) passed to load_frozen_bank
        self.perm = None
        self.tags = None

    def num_envs(self, pufferl):
        return self._num_envs

    def set_agent_perm(self, pufferl, perm):
        self.perm = perm

    def set_env_tags(self, pufferl, tags):
        self.tags = tags

    def save_weights(self, pufferl, path):
        self.saves.append(path)
        with open(path, 'wb') as f:
            f.write(b'\0' * 16)  # content is irrelevant to setup()

    def load_frozen_bank(self, pufferl, bank_idx, path):
        self.bank_loads.append((bank_idx, path))


class FakePufferl:
    global_step = 0


def load_patched_selfplay(puffer_dir, backend):
    '''Copy the vendored selfplay.py, apply the league patch, import it with
    pufferlib stubbed so `from pufferlib import _C` resolves to `backend`.'''
    tmp = tempfile.mkdtemp(prefix='selfplay_league_')
    os.makedirs(os.path.join(tmp, 'pufferlib'))
    src = os.path.join(puffer_dir, 'pufferlib', 'selfplay.py')
    dst = os.path.join(tmp, 'pufferlib', 'selfplay.py')
    shutil.copyfile(src, dst)
    applicable = subprocess.run(
        ['git', 'apply', '--check', '--no-index', PATCH], cwd=tmp,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0
    applied = subprocess.run(
        ['git', 'apply', '--reverse', '--check', '--no-index', PATCH], cwd=tmp,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0
    if applicable:
        subprocess.run(['git', 'apply', '--no-index', PATCH], cwd=tmp, check=True)
    elif not applied:
        raise RuntimeError(
            'selfplay_league.patch is neither applicable nor already applied')

    fake_pkg = types.ModuleType('pufferlib')
    fake_pkg._C = backend
    saved = sys.modules.get('pufferlib')
    sys.modules['pufferlib'] = fake_pkg
    try:
        spec = importlib.util.spec_from_file_location('selfplay_patched', dst)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is None:
            del sys.modules['pufferlib']
        else:
            sys.modules['pufferlib'] = saved
    return mod, tmp


def league_args(checkpoint_dir, preseed='', num_banks=5, pct=0.08):
    return {
        'checkpoint_dir': checkpoint_dir,
        'env_name': 'bloodbowl',
        'vec': {
            'total_agents': 4096,
            'num_buffers': 2,
            'num_frozen_banks': num_banks,
            'frozen_bank_pct': pct,
        },
        'selfplay': {
            'enabled': 1,
            'max_size': 200,
            'min_games': 2048,
            'swap_winrate': 0.55,
            'snapshot_interval': 500_000_000,
            'opp_timeout_steps': 500_000_000,
            'league_preseed': preseed,
        },
    }


def make_seed(path, nbytes):
    with open(path, 'wb') as f:
        f.write(os.urandom(min(nbytes, 64)))
        if nbytes > 64:
            f.seek(nbytes - 1)
            f.write(b'\0')


class BuildLeagueTest(unittest.TestCase):
    EXPECT = 4096  # small synthetic blobs; size logic is size-agnostic

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='build_league_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.seeds = []
        for name in ('alpha', 'bravo', 'charlie'):
            p = os.path.join(self.tmp, f'{name}.bin')
            make_seed(p, self.EXPECT)
            self.seeds.append((name, p))

    def test_layout_matches_selfplay_conventions(self):
        out = os.path.join(self.tmp, 'league')
        manifest = build_league(
            out, self.seeds, self.EXPECT, allow_legacy_unlabeled=True)
        pool = os.path.join(out, 'pool')
        # File naming: f'{i:016d}.bin' (selfplay.py:171/:247 convention).
        for i, (name, src) in enumerate(self.seeds):
            f = os.path.join(pool, f'{i:016d}.bin')
            self.assertTrue(os.path.isfile(f), f)
            self.assertEqual(os.path.getsize(f), self.EXPECT)
            with open(f, 'rb') as a, open(src, 'rb') as b:
                self.assertEqual(a.read(), b.read())
        with open(os.path.join(pool, 'league_seeds.json')) as f:
            on_disk = json.load(f)
        self.assertEqual(on_disk, json.loads(json.dumps(manifest)))
        self.assertEqual(on_disk['expected_bytes'], self.EXPECT)
        self.assertEqual([s['bank'] for s in on_disk['seeds']], [0, 1, 2])
        self.assertEqual([s['name'] for s in on_disk['seeds']],
                         ['alpha', 'bravo', 'charlie'])
        self.assertEqual([s['file'] for s in on_disk['seeds']],
                         ['0000000000000000.bin', '0000000000000001.bin',
                          '0000000000000002.bin'])

    def test_default_expect_bytes_is_the_cuda_blob(self):
        # Historical obs-v4 flat-fp32 artifact (test_convert_checkpoint.py).
        self.assertEqual(DEFAULT_EXPECT_BYTES, 16_066_560)

    def test_rejects_wrong_size(self):
        bad = os.path.join(self.tmp, 'bad.bin')
        make_seed(bad, self.EXPECT - 1)
        with self.assertRaisesRegex(LeagueError, 'expected'):
            build_league(os.path.join(self.tmp, 'league2'),
                         self.seeds + [('bad', bad)], self.EXPECT,
                         allow_legacy_unlabeled=True)

    def test_rejects_missing_seed(self):
        with self.assertRaisesRegex(LeagueError, 'does not exist'):
            build_league(os.path.join(self.tmp, 'league3'),
                         [('ghost', os.path.join(self.tmp, 'ghost.bin'))],
                         self.EXPECT, allow_legacy_unlabeled=True)

    def test_rejects_duplicate_name(self):
        with self.assertRaisesRegex(LeagueError, 'duplicate'):
            parse_seed_args(['x=/a.bin', 'x=/b.bin'])

    def test_rejects_malformed_seed_arg(self):
        with self.assertRaisesRegex(LeagueError, 'name=path'):
            parse_seed_args(['just-a-path.bin'])

    def test_refuses_nonempty_pool(self):
        out = os.path.join(self.tmp, 'league4')
        build_league(
            out, self.seeds, self.EXPECT, allow_legacy_unlabeled=True)
        with self.assertRaisesRegex(LeagueError, 'refusing'):
            build_league(
                out, self.seeds, self.EXPECT, allow_legacy_unlabeled=True)

    def test_copy_failure_leaves_no_partial_pool_and_retry_succeeds(self):
        out = os.path.join(self.tmp, 'atomic-league')
        real_copy = shutil.copyfile
        calls = 0

        def fail_third_copy(source, destination):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError('synthetic copy failure')
            return real_copy(source, destination)

        with mock.patch('build_league.shutil.copyfile', side_effect=fail_third_copy):
            with self.assertRaisesRegex(LeagueError, 'atomically'):
                build_league(
                    out, self.seeds, self.EXPECT,
                    allow_legacy_unlabeled=True)
        self.assertFalse(os.path.exists(os.path.join(out, 'pool')))
        self.assertFalse(any(name.startswith('.pool.tmp.')
                             for name in os.listdir(out)))

        manifest = build_league(
            out, self.seeds, self.EXPECT, allow_legacy_unlabeled=True)
        self.assertEqual(len(manifest['seeds']), len(self.seeds))

    def test_current_pool_requires_and_copies_eligible_lineage(self):
        with self.assertRaisesRegex(LeagueError, 'lineage'):
            build_league(
                os.path.join(self.tmp, 'missing-lineage'),
                self.seeds, self.EXPECT)

        current_seeds = []
        for name, _ in self.seeds:
            checkpoint = os.path.join(self.tmp, f'current-{name}.bin')
            make_seed(checkpoint, DEFAULT_EXPECT_BYTES)
            current_seeds.append((name, checkpoint))

        for index, (_, checkpoint) in enumerate(current_seeds):
            manifest_path = os.path.join(self.tmp, f'run-{index}.json')
            with open(manifest_path, 'w') as handle:
                json.dump({
                    'schema_version': 1,
                    'mode': 'native_static_pool_reward_ablation',
                    'seed': str(index),
                    'observation_abi': 'obs-v6',
                    'observation_version': '6',
                    'action_abi': 'exact-joint-v1',
                    'initialization': 'lineage-v6',
                    'qualification_only': '0',
                    'policy_hidden_size': '512',
                    'policy_num_layers': '3',
                    'policy_expansion_factor': '1',
                    'expected_checkpoint_bytes': str(DEFAULT_EXPECT_BYTES),
                    'source_sha256': '1' * 64,
                    'compiled_module_sha256': '2' * 64,
                    'puffer_patch_bundle_sha256': '3' * 64,
                    'screen_manifest_sha256': '4' * 64,
                    'warm_lineage_sha256': '5' * 64,
                    'pool_lineage_bundle_sha256': '6' * 64,
                }, handle, sort_keys=True)
                handle.write('\n')
            payload = lineage_from_run_manifest(
                checkpoint, manifest_path, allow_eligible_publication=True)
            write_lineage(sidecar_path(checkpoint), payload)

        out = os.path.join(self.tmp, 'current-lineage')
        manifest = build_league(
            out, current_seeds, DEFAULT_EXPECT_BYTES)
        self.assertEqual(manifest['version'], 2)
        self.assertTrue(manifest['lineage_required'])
        for seed in manifest['seeds']:
            self.assertTrue(seed['lineage_file'].endswith('.lineage.json'))
            self.assertTrue(os.path.isfile(os.path.join(
                out, 'pool', seed['lineage_file'])))


class PatchedSetupTest(unittest.TestCase):
    EXPECT = 4096

    @classmethod
    def setUpClass(cls):
        cls.puffer = find_pufferlib()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='league_setup_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.backend = FakeBackend(num_envs=2048)
        self.sp, mod_tmp = load_patched_selfplay(self.puffer, self.backend)
        self.addCleanup(shutil.rmtree, mod_tmp, ignore_errors=True)

    def build_pool(self, names=('a', 'b', 'c', 'd', 'e')):
        seeds = []
        for n in names:
            p = os.path.join(self.tmp, f'{n}.bin')
            make_seed(p, self.EXPECT)
            seeds.append((n, p))
        out = os.path.join(self.tmp, 'league')
        build_league(
            out, seeds, self.EXPECT, allow_legacy_unlabeled=True)
        return os.path.join(out, 'pool')

    def test_patch_is_applicable_or_already_applied_to_vendor(self):
        applicable = subprocess.run(
            ['git', 'apply', '--check', '--no-index', PATCH], cwd=self.puffer,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0
        applied = subprocess.run(
            ['git', 'apply', '--reverse', '--check', '--no-index', PATCH],
            cwd=self.puffer,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0
        self.assertNotEqual(applicable, applied)

    def test_preseed_loads_each_bank_from_its_seed(self):
        pool = self.build_pool()
        args = league_args(self.tmp, preseed=pool)
        state = self.sp.setup(FakePufferl(), self.backend, args, 'runid')

        expect = [os.path.join(pool, f'{i:016d}.bin') for i in range(5)]
        self.assertEqual(self.backend.bank_loads, list(enumerate(expect)))
        # No bootstrap save: the learner's weights never overwrite the seeds.
        self.assertEqual(self.backend.saves, [])
        # Pool = ordered seed set; snapshots will accumulate in the same dir.
        self.assertEqual([e['path'] for e in state['pool']], expect)
        self.assertEqual(state['pool_dir'], pool)
        # Each bank's current opponent is its own seed.
        self.assertEqual([b['cur_opp_path'] for b in state['banks']], expect)
        self.assertEqual(state['num_banks'], 5)

    def test_preseed_pool_feeds_swap_sampling(self):
        pool = self.build_pool()
        args = league_args(self.tmp, preseed=pool)
        state = self.sp.setup(FakePufferl(), self.backend, args, 'runid')
        # sample_opponent over the seeded pool returns seed entries (the
        # heterogeneous set is what swaps draw from on day one).
        entry = self.sp.sample_opponent(state['pool'], state['rng'])
        self.assertIn(entry['path'],
                      [os.path.join(pool, f'{i:016d}.bin') for i in range(5)])

    def test_bootstrap_path_is_upstream_identical(self):
        args = league_args(self.tmp, preseed='')
        state = self.sp.setup(FakePufferl(), self.backend, args, 'runid')
        boot = os.path.join(self.tmp, 'bloodbowl', 'runid', 'pool',
                            '0000000000000000.bin')
        self.assertEqual(self.backend.saves, [boot])
        self.assertEqual(self.backend.bank_loads,
                         [(b, boot) for b in range(5)])
        self.assertEqual([e['path'] for e in state['pool']], [boot])
        self.assertEqual([b['cur_opp_path'] for b in state['banks']],
                         [boot] * 5)

    def test_seed_count_mismatch_raises(self):
        pool = self.build_pool()
        args = league_args(self.tmp, preseed=pool, num_banks=4)
        with self.assertRaisesRegex(RuntimeError, 'num_frozen_banks'):
            self.sp.setup(FakePufferl(), self.backend, args, 'runid')

    def test_corrupted_seed_size_raises(self):
        pool = self.build_pool()
        victim = os.path.join(pool, '0000000000000002.bin')
        with open(victim, 'ab') as f:
            f.write(b'\0')  # grow by one byte after the build
        args = league_args(self.tmp, preseed=pool)
        with self.assertRaisesRegex(RuntimeError, 'expected'):
            self.sp.setup(FakePufferl(), self.backend, args, 'runid')

    def test_perm_tags_math_for_league_numbers(self):
        # run_league.sh numbers: apb=2048, team_size=1, pct 0.08 -> 163/bank,
        # 815 total (< apb/2 = 1024), 326 hist envs/bank, 418 selfplay envs.
        frozen_size = int(2048 * 0.08)
        self.assertEqual(frozen_size, 163)
        self.assertLess(5 * frozen_size, 2048 // 2)
        perm, tags, hist = self.sp.build_perm_tags(
            num_buffers=2, agents_per_buffer=2048, agents_per_env=2,
            frozen_sizes=[frozen_size] * 5, num_envs=2048)
        self.assertEqual(hist, [326] * 5)
        counts = {t: int((tags == t).sum()) for t in range(6)}
        self.assertEqual(counts, {0: 418, 1: 326, 2: 326, 3: 326,
                                  4: 326, 5: 326})
        # Perm must be a permutation within each buffer's physical chunk
        # (pufferl_set_agent_perm rejects cross-buffer rows).
        for b in range(2):
            chunk = perm[b * 2048:(b + 1) * 2048]
            self.assertEqual(sorted(chunk.tolist()),
                             list(range(b * 2048, (b + 1) * 2048)))
        # setup() with the same numbers wires identical tags to the backend
        # and stores the per-bank historical env counts swap-alignment waits on.
        pool = self.build_pool()
        args = league_args(self.tmp, preseed=pool)
        state = self.sp.setup(FakePufferl(), self.backend, args, 'runid')
        self.assertTrue((self.backend.tags == tags).all())
        self.assertEqual([b['num_hist_envs'] for b in state['banks']], hist)


if __name__ == '__main__':
    unittest.main(verbosity=2)
