#!/usr/bin/env python
"""Construct a pre-seeded heterogeneous league pool for a selfplay run.

Builds, BEFORE training, the exact on-disk pool layout that the vendored
selfplay pool consumes (vendor/PufferLib/pufferlib/selfplay.py — all line
numbers refer to the 4.0 pin, vendor/PINS.md 9836f0d):

    <out>/pool/                    selfplay.py:169
                                     pool_dir = os.path.join(
                                         args['checkpoint_dir'],
                                         args['env_name'], run_id, 'pool')
    <out>/pool/{i:016d}.bin        selfplay.py:171 and :247 name every pool
                                     entry f'{pufferl.global_step:016d}.bin'.
                                     Seeds take steps 0..N-1: a warm-started
                                     run's global_step counter restarts at 0
                                     and the first interval snapshot lands at
                                     >= snapshot_interval, so these names can
                                     never collide with run snapshots.
    <out>/pool/league_seeds.json   manifest consumed by the league_preseed
                                     branch added by
                                     training/selfplay_league.patch.

Why a patch + manifest are needed at all: stock setup() keeps pool state in
MEMORY ONLY (selfplay.py:197-211 returns the pool list; nothing on disk
indexes it) and it UNCONDITIONALLY bootstraps — selfplay.py:171-175 saves
the learner's current weights as '{global_step:016d}.bin' and loads that one
file into every frozen bank. There is no upstream path that reads a
pre-existing pool, hence training/selfplay_league.patch (skips the bootstrap
and seeds each bank from this manifest when [selfplay] league_preseed names
this pool dir).

Seed files must be CUDA flat-fp32 weight blobs with eligible obs-v5/exact-action
lineage sidecars — the save_weights format
(vendor/PufferLib/src/bindings.cu:180: raw fwrite of master_weights, no
header). Semantic compatibility comes from the sidecar, not blob size.
pufferl_load_frozen_bank (vendor/PufferLib/src/pufferlib.cu:1830)
checks the byte size but only fprintf-warns and RETURNS on mismatch (the
bank silently keeps its previous weights), so this tool hard-verifies every
seed's size up front. 16,066,560 bytes = the current bloodbowl policy (obs
2782 = obs v5, heads {30,33,391}, hidden 512, 3 layers —
training/test_convert_checkpoint.py). Historical obs-v3 (13,670,400-byte) and
obs-v2 (12,072,960-byte) pools require both an explicit size and the
`--legacy-unlabeled` reconstruction mode; current launchers reject them.

Usage:
    tools/build_league.py --out <run-dir> --seeds name0=/path/a.bin \
        name1=/path/b.bin ... [--expect-bytes 16066560]

Seed order == frozen bank index (bank 0 = first --seeds entry). The patched
setup() also starts the opponent pool as exactly this list, oldest-first, so
sample_opponent's staleness weighting (selfplay.py:27-32) treats earlier
seeds as older history.
"""

import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys
import tempfile

from checkpoint_lineage import (
    LineageError, lineage_digest, sidecar_path, validate_lineage,
)

# Current Blood Bowl CUDA flat blob: 4,016,640 fp32 params (obs 2782 = obs
# v5 / heads {30,33,391} / hidden 512 / 3 layers). Size pinned by
# training/test_convert_checkpoint.py. Older obs-v3 (13,670,400 bytes) and
# obs-v2 (12,072,960 bytes) lineages require an explicit --expect-bytes.
DEFAULT_EXPECT_BYTES = 16_066_560

MANIFEST_NAME = 'league_seeds.json'


class LeagueError(RuntimeError):
    pass


def parse_seed_args(seed_args):
    '''['name=/path', ...] -> [(name, path), ...] preserving bank order.'''
    seeds = []
    names = set()
    for raw in seed_args:
        name, sep, path = raw.partition('=')
        if not sep or not name or not path:
            raise LeagueError(f'--seeds entry {raw!r} is not name=path')
        if name in names:
            raise LeagueError(f'duplicate seed name {name!r}')
        names.add(name)
        seeds.append((name, path))
    return seeds


def build_league(out_dir, seeds, expect_bytes=DEFAULT_EXPECT_BYTES,
                 allow_legacy_unlabeled=False):
    '''Create <out_dir>/pool with seed .bins + league_seeds.json.

    Returns the manifest dict. Raises LeagueError on any validation failure
    (missing seed, wrong size, pre-existing pool entries).
    '''
    if not seeds:
        raise LeagueError('at least one seed is required')

    # Validate sources before writing anything.
    sources = {}
    lineages = {}
    for name, path in seeds:
        if not os.path.isfile(path):
            raise LeagueError(f'seed {name!r}: {path} does not exist')
        size = os.path.getsize(path)
        if size != expect_bytes:
            raise LeagueError(
                f'seed {name!r}: {path} is {size} bytes, expected '
                f'{expect_bytes} (flat-fp32 save_weights blob — wrong arch '
                f'or a torch state_dict needing training/convert_checkpoint.py?)')
        real = os.path.realpath(path)
        if real in sources:
            print(f'warning: seed {name!r} duplicates source of '
                  f'{sources[real]!r} ({real})', file=sys.stderr)
        sources.setdefault(real, name)
        if not allow_legacy_unlabeled:
            lineage = sidecar_path(path)
            try:
                payload = validate_lineage(
                    path, lineage, require_eligible=True)
            except LineageError as exc:
                raise LeagueError(f'seed {name!r}: {exc}') from exc
            lineages[real] = (lineage, lineage_digest(payload))

    out_dir = os.path.abspath(out_dir)
    pool_dir = os.path.join(out_dir, 'pool')
    if os.path.isdir(pool_dir) and os.listdir(pool_dir):
        raise LeagueError(
            f'{pool_dir} already contains entries {sorted(os.listdir(pool_dir))} — '
            f'refusing to mix leagues; use a fresh --out dir')
    if os.path.exists(pool_dir) and not os.path.isdir(pool_dir):
        raise LeagueError(f'{pool_dir} exists and is not a directory')
    os.makedirs(out_dir, exist_ok=True)
    if os.path.isdir(pool_dir):
        os.rmdir(pool_dir)
    staging_dir = tempfile.mkdtemp(prefix='.pool.tmp.', dir=out_dir)

    try:
        entries = []
        for bank, (name, path) in enumerate(seeds):
            # Naming convention: selfplay.py:171/:247 f'{global_step:016d}.bin'.
            fname = f'{bank:016d}.bin'
            dest = os.path.join(staging_dir, fname)
            shutil.copyfile(path, dest)
            with open(dest, 'rb') as f:
                blob = f.read()
            if len(blob) != expect_bytes:
                raise LeagueError(f'copy of seed {name!r} is {len(blob)} bytes')
            entries.append({
                'bank': bank,
                'name': name,
                'file': fname,
                'source': os.path.abspath(path),
                'bytes': len(blob),
                'sha256': hashlib.sha256(blob).hexdigest(),
            })
            if not allow_legacy_unlabeled:
                source_lineage, source_lineage_sha = lineages[os.path.realpath(path)]
                lineage_name = fname + '.lineage.json'
                shutil.copyfile(
                    source_lineage, os.path.join(staging_dir, lineage_name))
                entries[-1].update({
                    'lineage_file': lineage_name,
                    'lineage_sha256': source_lineage_sha,
                })

        manifest = {
            'version': 1 if allow_legacy_unlabeled else 2,
            'lineage_required': not allow_legacy_unlabeled,
            'created': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'expected_bytes': expect_bytes,
            'seeds': entries,
        }
        with open(os.path.join(staging_dir, MANIFEST_NAME), 'w') as f:
            json.dump(manifest, f, indent=2)
            f.write('\n')
        os.replace(staging_dir, pool_dir)
        staging_dir = None
    except Exception as exc:
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)
        if isinstance(exc, LeagueError):
            raise
        raise LeagueError(f'could not publish league atomically: {exc}') from exc
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Build a pre-seeded heterogeneous selfplay league pool')
    ap.add_argument('--out', required=True,
        help='league run dir; pool/ is created inside it')
    ap.add_argument('--seeds', required=True, nargs='+', metavar='NAME=PATH',
        help='seed checkpoints in bank order (bank 0 first)')
    ap.add_argument('--expect-bytes', type=int, default=DEFAULT_EXPECT_BYTES,
        help='required size of every seed .bin (flat-fp32 blob; '
             f'default {DEFAULT_EXPECT_BYTES})')
    ap.add_argument('--legacy-unlabeled', action='store_true',
        help='historical reconstruction only: permit checkpoints without '
             'obs-v5/exact-action lineage; repaired launchers still reject it')
    args = ap.parse_args(argv)

    try:
        seeds = parse_seed_args(args.seeds)
        manifest = build_league(
            args.out, seeds, args.expect_bytes,
            allow_legacy_unlabeled=args.legacy_unlabeled)
    except LeagueError as e:
        print(f'build_league: {e}', file=sys.stderr)
        return 1

    pool_dir = os.path.join(args.out, 'pool')
    print(f'league pool: {pool_dir}')
    for s in manifest['seeds']:
        print(f"  bank {s['bank']}  {s['file']}  {s['name']}  "
              f"sha256 {s['sha256'][:12]}  <- {s['source']}")
    print(f"  {MANIFEST_NAME}  ({len(manifest['seeds'])} seeds, "
          f"{manifest['expected_bytes']} bytes each)")
    print('launch with: --selfplay.league-preseed ' + os.path.abspath(pool_dir)
          + f"  --vec.num-frozen-banks {len(manifest['seeds'])}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
