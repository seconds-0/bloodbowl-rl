#!/usr/bin/env python3
"""The b3 stages: one campaign, a second checkout.

training/campaigns/longrun-20261002/b3/ holds the stage scripts that run the
no_early_end_turn arm from its own checkout while the campaign's supervisor,
plan and state stay with the long-run checkout
(docs/no-early-end-turn-2026-10-05.md). These tests pin what that arrangement
rests on:

* tools/campaign_supervisor.py takes absolute `success` and `progress` paths,
  so a stage's artifacts may live under another checkout;
* no script on the launch path names a checkout that `C` does not override;
* the b3 recipe is the long-run recipe, and its graft declaration is the two
  old builds that pool cc9b201e and chain 41 actually hold;
* the wrappers hand tools/chain_stage.sh exactly the paired rung;
* b3_identity.sh writes its pass marker only when every check passed.

The stage scripts run for real against fake checkouts in a temp dir. The two
probes are replaced by a stand-in that writes the files the real ones write.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import campaign_supervisor  # noqa: E402
import checkpoint_lineage  # noqa: E402

B3 = ROOT / "training/campaigns/longrun-20261002/b3"
LONGRUN_ENV = ROOT / "training/campaigns/longrun-20261002/common_env.sh"
ORIGINAL = ("3ed6899e121bbc084568d03687be79b8ce1bb0f375c5f9cdbcdc074b0eb0a68b",
            "d63498f6e49f1c0713cd55390e3df54e3ba43c7d11b6d8c2d1dfc081c75eee69",
            "de77f6c0a01304292dba21ada627d535f0ccb8629bc5a96d8ddc8df1d710a3ad")
LONGRUN = ("2ed3ffc2dcc33df0a2262cbe1f86b4742ece0983ee31d41a3b0e2cc462a01dc4",
           "3d8e5f72b8e27f3e92755383a33d626e76de6ae6827b5b810554d30e0c68cbc3",
           "c1174af6b4a6c6a6b91df353678c69846b5c66a2f08997d18a141a5062a60bda")
POOL_HASH = "cc9b201e619aab3dedb2577eeac273a3b70a346a5e87d30fa9ab432c068d3be6"
LAUNCH_PATH = ("chain_stage.sh", "ladder_stage.sh", "launch_ladder_rung.sh",
               "run_reward_screen.sh", "run_reward_ablation.sh",
               "eval_vs_contact_bot.sh")


def exports(path: Path) -> dict[str, str]:
    """NAME=value pairs from the `export` lines of a sourced env file."""
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("export "):
            continue
        for name, quoted, bare in re.findall(
                r'([A-Z0-9_]+)=(?:"([^"]*)"|(\S*))', line[len("export "):]):
            found[name] = quoted if quoted else bare
    return found


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SupervisorAcrossCheckoutsTests(unittest.TestCase):
    """One plan rooted in checkout A, a stage whose artifacts live in checkout B."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "longrun"
        self.other = base / "b3"
        (self.root / "runs").mkdir(parents=True)
        (self.other / "runs/stage").mkdir(parents=True)
        self.plan = campaign_supervisor.validate_plan({
            "schema_version": 1, "campaign_id": "two-checkouts",
            "root": str(self.root), "trainer_pgrep": "[z]zz-no-such-process-zzz",
            "stages": [
                {"name": "local", "launch": "true", "success": "runs/local/PASS.json"},
                {"name": "remote", "launch": "true",
                 "success": str(self.other / "runs/stage/PASS.json"),
                 "progress": str(self.other / "runs/stage/STATUS.json")},
            ]})

    def tearDown(self):
        self.tmp.cleanup()

    def tick(self):
        state = campaign_supervisor._blank_state(self.plan)
        return campaign_supervisor.tick(self.plan, state, dry_run=True)

    def test_absolute_success_and_progress_resolve_outside_the_plan_root(self):
        local, remote = self.plan["stages"]
        self.assertIn("WOULD-LAUNCH stage=local", self.tick())
        (self.root / "runs/local").mkdir()
        (self.root / "runs/local/PASS.json").write_text("{}")
        self.assertTrue(campaign_supervisor.stage_is_complete(self.root, local))
        # The remote stage is judged by the file in the OTHER checkout ...
        self.assertFalse(campaign_supervisor.stage_is_complete(self.root, remote))
        self.assertIn("WOULD-LAUNCH stage=remote", self.tick())
        # ... a same-named relative path under the plan root does not count ...
        decoy = self.root / str(self.other / "runs/stage/PASS.json").lstrip("/")
        decoy.parent.mkdir(parents=True)
        decoy.write_text("{}")
        self.assertFalse(campaign_supervisor.stage_is_complete(self.root, remote))
        # ... and its progress age is read from there too.
        self.assertIsNone(campaign_supervisor.stage_progress_age(self.root, remote))
        status = self.other / "runs/stage/STATUS.json"
        status.write_text("{}")
        old = time.time() - 500
        os.utime(status, (old, old))
        age = campaign_supervisor.stage_progress_age(self.root, remote)
        self.assertTrue(490 < age < 600, age)
        (self.other / "runs/stage/PASS.json").write_text("{}")
        self.assertTrue(campaign_supervisor.stage_is_complete(self.root, remote))
        self.assertTrue(self.tick().startswith("COMPLETE"))

    def test_what_still_follows_the_plan_root(self):
        # Recorded, not changed: the attempt logs and the launch cwd are the
        # plan root's. A stage in another checkout must not rely on its cwd.
        source = (ROOT / "tools/campaign_supervisor.py").read_text(encoding="utf-8")
        self.assertIn('log_dir = Path(plan.get("log_dir") or (root / "runs" / "campaign-logs"))',
                      source)
        self.assertIn("cwd=str(root),", source)
        for name in ("b3_identity.sh", "b3_canary54.sh", "b3_chain54.sh"):
            text = (B3 / name).read_text(encoding="utf-8")
            # Each stage finds its env file from its own location, not the cwd.
            self.assertIn('"$(cd "$(dirname "$0")" && pwd)', text, name)

    def test_liveness_is_one_host_wide_pattern_and_must_name_the_identity_stage(self):
        # trainer_is_alive is a pgrep over every process on the host, so a
        # stage in another checkout counts, but only if the pattern names it.
        pattern = ("[p]uffer_cuda_runtime.py train|[p]uffer train|[c]hain_stage.sh|"
                   "[l]adder_stage.sh|[r]un_reward_screen.sh|[e]val_vs_contact_bot.sh")
        long_run_plan = (ROOT / "training/campaigns/longrun-20261002/make_plan.py"
                         ).read_text(encoding="utf-8")
        self.assertIn('"[p]uffer_cuda_runtime.py train|[p]uffer train|[c]hain_stage.sh|"',
                      long_run_plan)
        identity = "bash /home/rache/longrun/b3/b3_identity.sh"
        self.assertIsNone(re.search(pattern, identity))
        self.assertIsNotNone(re.search(pattern + "|[b]3_identity.sh", identity))
        for name in ("b3_canary54.sh", "b3_chain54.sh"):
            self.assertIn('exec bash "$C/tools/chain_stage.sh"',
                          (B3 / name).read_text(encoding="utf-8"))
        self.assertIn("|[b]3_identity.sh", (B3 / "README.md").read_text(encoding="utf-8"))


class NoForeignCheckoutTests(unittest.TestCase):
    def test_no_launch_path_script_names_a_checkout_c_does_not_override(self):
        allowed = 'C="${C:-/home/rache/bloodbowl-rl-qualification-candidate-10619e2}"'
        for name in LAUNCH_PATH:
            text = (ROOT / "tools" / name).read_text(encoding="utf-8")
            for line in text.splitlines():
                if "/home/rache/bloodbowl-rl" in line and not line.lstrip().startswith("#"):
                    # The only checkout paths are defaults for an UNSET C.
                    self.assertEqual(line.strip(), allowed, (name, line))
        # chain_stage.sh has no default at all: it refuses to start without C.
        chain = (ROOT / "tools/chain_stage.sh").read_text(encoding="utf-8")
        self.assertIn("for name in C STAMP EXAM_RULE", chain)
        self.assertNotIn("C:-", chain)
        # The three scripts below chain_stage find their checkout from their
        # own location, so they follow whichever checkout's copy was invoked.
        for name in ("run_reward_screen.sh", "run_reward_ablation.sh",
                     "eval_vs_contact_bot.sh"):
            self.assertIn('ROOT="$(cd "$(dirname "$0")/.." && pwd)"',
                          (ROOT / "tools" / name).read_text(encoding="utf-8"), name)
        self.assertIn('bash "$C/tools/run_reward_screen.sh"',
                      (ROOT / "tools/launch_ladder_rung.sh").read_text(encoding="utf-8"))

    def test_what_is_shared_host_wide_is_a_lock_not_a_checkout(self):
        chain = (ROOT / "tools/chain_stage.sh").read_text(encoding="utf-8")
        self.assertIn('GPU_LOCK="${GPU_LOCK:-/home/rache/kt-e2e/kt-gpu.lock}"', chain)
        ablation = (ROOT / "tools/run_reward_ablation.sh").read_text(encoding="utf-8")
        self.assertIn("exec 9>/tmp/bloodbowl-rl-reward-ablation.lock", ablation)
        # An accepted checkpoint must still come out of the checkout that ran.
        screen = (ROOT / "tools/run_reward_screen.sh").read_text(encoding="utf-8")
        self.assertIn('checkpoint_root = (root / "vendor/PufferLib/checkpoints/bloodbowl").resolve()',
                      screen)


class B3RecipeTests(unittest.TestCase):
    def test_recipe_is_the_long_run_recipe_except_checkout_and_graft(self):
        b3 = exports(B3 / "b3_common_env.sh")
        long_run = exports(LONGRUN_ENV)
        differs = {"C", "GRAFT_FROM_SOURCE_SHA256", "GRAFT_FROM_PATCH_BUNDLE_SHA256",
                   "GRAFT_REASON"}
        for name, value in long_run.items():
            if name in differs or name == "OLD":
                continue
            self.assertEqual(b3.get(name), value, name)
        self.assertEqual(
            sorted(set(b3) - set(long_run)),
            ["B3_CANARY_STAMP", "B3_CHAIN41_MARKER", "B3_IDENTITY_PASS",
             "B3_POOL49_HASH", "B3_POOL_HASH", "B3_RUNG_STAMP", "LONGRUN"])
        self.assertEqual(b3["C"], "${B3_C:-/home/rache/bloodbowl-rl-b3-20261006}")
        self.assertEqual(b3["LONGRUN"],
                         "${B3_LONGRUN:-/home/rache/bloodbowl-rl-longrun-20261002}")
        self.assertEqual(b3["B3_RUNG_STAMP"], "r0chain54-noearlyend-from41-s42-20261006")
        self.assertEqual(b3["B3_POOL_HASH"], POOL_HASH)

    def test_graft_declares_the_original_and_long_run_builds_pairwise(self):
        b3 = exports(B3 / "b3_common_env.sh")
        builds = checkpoint_lineage.parse_graft_declaration(
            b3["GRAFT_FROM_SOURCE_SHA256"], b3["GRAFT_FROM_PATCH_BUNDLE_SHA256"])
        self.assertEqual(builds, [(ORIGINAL[0], ORIGINAL[2]), (LONGRUN[0], LONGRUN[2])])
        # The first pair is the one the long-run campaign already declares.
        long_run = exports(LONGRUN_ENV)
        self.assertEqual((long_run["GRAFT_FROM_SOURCE_SHA256"],
                          long_run["GRAFT_FROM_PATCH_BUNDLE_SHA256"]), builds[0])

    def test_two_pairs_is_what_chain_41_and_pool_cc9b201e_need_on_a_new_build(self):
        # The sidecars as they are on the rig: bank 0 (anchor) and bank 1
        # (chain 36) bind the original build, banks 2 and 3 (chains 40, 41) and
        # the warm start (chain 41) bind the long-run build. The b3 build has
        # a new env source AND a new patch-bundle digest (that digest hashes
        # absolute paths), so neither old build is "this build".
        def bound(build):
            return {"implementation": {"source_sha256": build[0],
                                       "compiled_module_sha256": build[1],
                                       "puffer_patch_bundle_sha256": build[2]}}
        sidecars = [("warm", bound(LONGRUN)), ("pool bank 0", bound(ORIGINAL)),
                    ("pool bank 1", bound(ORIGINAL)), ("pool bank 2", bound(LONGRUN)),
                    ("pool bank 3", bound(LONGRUN))]
        b3 = exports(B3 / "b3_common_env.sh")
        for label, current in (
            ("separate checkout", {"source_sha256": "7" * 64,
                                   "compiled_module_sha256": "8" * 64,
                                   "puffer_patch_bundle_sha256": "9" * 64}),
            # An in-place rebuild would keep the long-run patch bundle; the
            # same two pairs still hold, because the source differs.
            ("same patch bundle", {"source_sha256": "7" * 64,
                                   "compiled_module_sha256": "8" * 64,
                                   "puffer_patch_bundle_sha256": LONGRUN[2]}),
        ):
            modules = checkpoint_lineage.graft_bridge(
                sidecars, current=current,
                old_source_sha256=b3["GRAFT_FROM_SOURCE_SHA256"],
                old_patch_bundle_sha256=b3["GRAFT_FROM_PATCH_BUNDLE_SHA256"])
            self.assertEqual(modules, ORIGINAL[1] + "," + LONGRUN[1], label)
        current = {"source_sha256": "7" * 64, "compiled_module_sha256": "8" * 64,
                   "puffer_patch_bundle_sha256": "9" * 64}
        # The long-run campaign's single pair is not enough here ...
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "warm binds neither this build nor the declared old build"):
            checkpoint_lineage.graft_bridge(
                sidecars, current=current, old_source_sha256=ORIGINAL[0],
                old_patch_bundle_sha256=ORIGINAL[2])
        # ... and a third pair would be declared and absent.
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "no sidecar binds declared old build"):
            checkpoint_lineage.graft_bridge(
                sidecars, current=current,
                old_source_sha256=b3["GRAFT_FROM_SOURCE_SHA256"] + "," + "a" * 64,
                old_patch_bundle_sha256=b3["GRAFT_FROM_PATCH_BUNDLE_SHA256"] + "," + "b" * 64)


class InheritedRuleFlagTests(unittest.TestCase):
    """A control rung must not train under the rule because the caller's environment had the flag set."""

    WANT = {"b3_chain55.sh": "unset", "b3_chain57.sh": "unset", "b3_chain56.sh": "1", "b3_canary54.sh": "1"}

    def flag_after_preamble(self, name: str) -> str:
        lines = (B3 / name).read_text(encoding="utf-8").splitlines()
        sets = [line for line in lines if line.startswith("export LADDER_NO_EARLY_END_TURN=")]
        source = [i for i, line in enumerate(lines) if "b3_common_env.sh" in line and line.startswith("source ")]
        self.assertEqual(len(source), 1, name)
        for line in sets:
            self.assertGreater(lines.index(line), source[0], f"{name} sets the flag before sourcing the shared env")
        script = "\n".join([f"source {B3 / 'b3_common_env.sh'}", *sets,
                            'echo "${LADDER_NO_EARLY_END_TURN:-unset}"'])
        out = subprocess.run(["bash", "-c", script], env={**os.environ, "LADDER_NO_EARLY_END_TURN": "1"},
                             capture_output=True, text=True, check=True)
        return out.stdout.strip().splitlines()[-1]

    def test_inherited_flag_reaches_only_the_rule_stages(self):
        for name, want in self.WANT.items():
            with self.subTest(stage=name):
                self.assertEqual(self.flag_after_preamble(name), want)


class TraceSizeTests(unittest.TestCase):
    """The trace probe copies each rollout off the GPU and the trainer refuses a copy over 64 MiB. The first
    real run asked for 512 agents x 64 steps (about 440 MiB) and the stand-in probe in these tests cannot see it."""

    def test_trace_rollout_fits_the_snapshot_cap_and_still_covers_whole_games(self):
        text = (B3 / "b3_identity.sh").read_text(encoding="utf-8")
        trace = re.search(r"^TRACE=\((.*)\)$", text, re.M).group(1).split()
        value = dict(zip(trace[::2], trace[1::2]))
        agents, horizon = int(value["--vec.total-agents"]), int(value["--train.horizon"])
        rollouts = int(re.search(r"^TRACE_ROLLOUTS=(\d+)$", text, re.M).group(1))
        self.assertLessEqual(agents * horizon, 512 * 8, "measured: 512 agents x 8 steps is about 55 MiB of 64")
        self.assertGreaterEqual(horizon * rollouts, 2048, "about 2,000 decisions an env, several whole games")
        self.assertIn('--rollouts "$TRACE_ROLLOUTS"', text)


class FakeCheckouts(unittest.TestCase):
    """A b3 checkout and a long-run checkout, as far as the stages look."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.base = base
        self.c = base / "b3"
        self.longrun = base / "longrun"
        tools = self.c / "tools"
        tools.mkdir(parents=True)
        (tools / "chain_stage.sh").write_text(
            '#!/bin/bash\nenv > "$C/chain_stage.env"\necho "chain_stage ran"\n')
        (tools / "install_puffer_env.sh").write_text(
            '#!/bin/bash\n[ ! -f "$(dirname "$0")/../DRIFT" ] || { echo "drift check: STALE" >&2; exit 1; }\n')
        for name in ("probe_train_identity.py", "probe_scripted_bank_skip.py"):
            (tools / name).write_text("raise SystemExit('the stand-in runs instead')\n")
        venv = self.c / "vendor/PufferLib/.venv/bin"
        venv.mkdir(parents=True)
        self.stub = base / "probe_stand_in.py"
        self.stub.write_text(PROBE_STAND_IN, encoding="utf-8")
        python = venv / "python"
        python.write_text(
            "#!/bin/bash\n"
            'case "${1:-}" in\n'
            f'  */probe_train_identity.py|*/probe_scripted_bank_skip.py) exec python3 "{self.stub}" "$@" ;;\n'
            "esac\n"
            'exec python3 "$@"\n')
        python.chmod(0o755)
        self.entry = venv / "puffer"
        self.entry.write_text(f"#!{venv}/python\nprint('puffer')\n")
        self.entry.chmod(0o755)
        (self.c / "vendor/PufferLib/pufferlib").mkdir()
        self.module = self.c / "vendor/PufferLib/pufferlib/_C.cpython-311-x86_64-linux-gnu.so"
        self.module.write_bytes(b"b3 compiled module\n")
        (self.c / "vendor/PufferLib/ocean/bloodbowl").mkdir(parents=True)
        (self.c / "vendor/PufferLib/ocean/bloodbowl/.content_hash").write_text("7" * 64 + "\n")
        (self.c / "runs").mkdir()

        run42 = self.longrun / "runs/ladder-d0-r0chain42-cont41-rr1-20261003"
        (run42 / "screen-attempt1").mkdir(parents=True)
        (run42 / "screen-attempt1/ladder-d0-s42-r0chain42-cont41-rr1-20261003-r0_poss_half-s42"
                 ".log.manifest.json").write_text(json.dumps({"command": [
            "env", "python", "puffer_cuda_runtime.py", "train", "bloodbowl",
            "--tag", "chain42", "--seed", "42", "--eval-episodes", "10000",
            "--checkpoint-interval", "381", "--vec.total-agents", "2048",
            "--selfplay.league-preseed", "/pool", "--load-model-path", "/warm.bin",
            "--env.scripted-bank-tag", "4"]}))
        pool = run42 / "pool"
        pool.mkdir()
        seeds = []
        for bank in range(4):
            blob = f"bank {bank}".encode()
            (pool / f"{bank:016d}.bin").write_bytes(blob)
            seeds.append({"bank": bank, "name": f"seat{bank}", "file": f"{bank:016d}.bin",
                          "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()})
        (pool / "league_seeds.json").write_text(json.dumps({"seeds": seeds}))
        self.pool_identity = hashlib.sha256(json.dumps(
            [{"bank": s["bank"], "name": s["name"], "bytes": s["bytes"], "sha256": s["sha256"]}
             for s in seeds], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        ckpts = self.longrun / "vendor/PufferLib/checkpoints/bloodbowl"
        (ckpts / "1791097707780").mkdir(parents=True)
        (ckpts / "1791129357655").mkdir(parents=True)
        self.warm = ckpts / "1791097707780/0000002999975936.bin"
        self.warm.write_bytes(b"chain 41 weights")
        self.ref1 = ckpts / "1791129357655/0000000000131072.bin"
        self.ref1.write_bytes(b"chain 42 at epoch 1")
        self.ref382 = ckpts / "1791129357655/0000000050069504.bin"
        self.ref382.write_bytes(b"chain 42 at epoch 382")
        (self.longrun / "runs/ladder-d0-r0chain41-cont40-rr1-20261003").mkdir(parents=True)
        (base / "lock").mkdir()
        self.gpu_lock = base / "lock/kt-gpu.lock"
        self.out = self.c / "runs/b3-identity-20261006"
        self.calls = base / "probe_calls"

    def tearDown(self):
        self.tmp.cleanup()

    def env(self, **over):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("B3_", "STUB_", "LADDER_", "GRAFT_", "EXAM_",
                                    "SCRIPTED_"))
               and k not in ("C", "LONGRUN", "PLAN_ONLY", "STEPS", "SEED", "STAMP",
                             "PREV_COMPLETE", "EXPECTED_POOL_HASH", "GPU_LOCK")}
        env.update({
            "B3_C": str(self.c), "B3_LONGRUN": str(self.longrun),
            "GPU_LOCK": str(self.gpu_lock), "GPU_LOCK_WAIT_SECONDS": "1",
            "B3_TEST_WARM_SHA256": sha(self.warm),
            "B3_TEST_EPOCH1_SHA256": sha(self.ref1),
            "B3_TEST_EPOCH382_SHA256": sha(self.ref382),
            "B3_TEST_POOL_SHA256": self.pool_identity,
            "STUB_REF1": str(self.ref1), "STUB_REF382": str(self.ref382),
            "STUB_MODULE_SHA": sha(self.module), "STUB_CALLS": str(self.calls),
        })
        for key, value in over.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def run_script(self, name, **over):
        return subprocess.run(
            ["bash", str(B3 / name)], env=self.env(**over), cwd="/", text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=120)


# Stand-in for tools/probe_train_identity.py and tools/probe_scripted_bank_skip.py.
# It writes the output files the real probes write; STUB_MODE picks a defect.
PROBE_STAND_IN = r'''
import json, os, pathlib, shutil, sys
argv = sys.argv[1:]
tool = pathlib.Path(argv[0]).name
flag_on = any(argv[i:i + 2] == ["--env.no-early-end-turn", "1"] for i in range(len(argv)))
kind = "trace" if tool == "probe_scripted_bank_skip.py" else ("ppo" if flag_on else "identity")
mode = os.environ.get("STUB_MODE", "ok")
with open(os.environ["STUB_CALLS"], "a") as handle:
    handle.write(kind + "\n")
def value(flag):
    return argv[argv.index(flag) + 1]
if mode == f"crash-{kind}":
    raise SystemExit(9)
removed = 55.0 if flag_on else 0.0
if mode == "flag-ignored" and flag_on:
    removed = 0.0
if mode == "removed-with-flag-off" and not flag_on:
    removed = 3.0
env = {"n": 300.0, "end_turn_removed": removed, "truncated_episodes": 0.0}
if mode == "old-module-panel" and flag_on:
    env = {"n": 300.0}
if mode == "truncated" and kind == "trace":
    env["truncated_episodes"] = 0.25
if mode == "truncated-flag-off" and kind == "identity":
    env["truncated_episodes"] = 0.25
payload = {
    "identity": {"module_sha256": "f" * 64 if mode == f"foreign-module-{kind}"
                 else os.environ["STUB_MODULE_SHA"]},
    "skip": {"bank": 4, "routed": mode != f"unrouted-{kind}", "binding": True},
    "hard_integrity": {"zero": mode != f"integrity-{kind}"},
    "config": {"env": {"no_early_end_turn": 1 if flag_on else 0}},
    "env": env,
}
if kind != "trace":
    weights = pathlib.Path(value("--weights-dir"))
    weights.mkdir(parents=True, exist_ok=True)
    if kind == "identity":
        shutil.copyfile(os.environ["STUB_REF1"], weights / "epoch-0001.bin")
        shutil.copyfile(os.environ["STUB_REF382"], weights / "epoch-0382.bin")
        if mode == "weights-differ":
            (weights / "epoch-0382.bin").write_bytes(b"something else")
        payload["checkpoints"] = [{"epoch": 1, "agent_steps": 131072},
                                  {"epoch": 382, "agent_steps": 50069504}]
        if mode == "wrong-steps":
            payload["checkpoints"][1]["agent_steps"] = 50069504 + 131072
    else:
        (weights / "epoch-0024.bin").write_bytes(b"smoke")
        payload["checkpoints"] = [{"epoch": 24, "agent_steps": 3145728}]
if mode == "abort-message" and kind == "ppo":
    print("bloodbowl: policy supplied a tuple outside exact joint support (type=5 arg=32 square=390)")
pathlib.Path(value("--output")).write_text(json.dumps(payload))
print("stand-in", kind)
'''


class WrapperTests(FakeCheckouts):
    def handed(self):
        return dict(line.split("=", 1)
                    for line in (self.c / "chain_stage.env").read_text().splitlines()
                    if "=" in line)

    def pass_identity(self, **over):
        self.out.mkdir(parents=True, exist_ok=True)
        marker = {"pass": True, "reference_pinned": True, "source_sha256": "7" * 64,
                  "compiled_module_sha256": sha(self.module)}
        marker.update(over)
        (self.out / "B3_IDENTITY_PASS.json").write_text(json.dumps(marker))

    def pass_canary(self, rule=1, verdict_pass=True, train_cut=0.0, eval_cut=0.0,
                    cell_cut=0.0, accepted=True, cells=6,
                    result_checkpoint="c" * 64,
                    cell_names=("contact_away", "contact_home", "offense_away"),
                    **built):
        """The canary's records as the real stage leaves them. A *_cut of None
        leaves that truncation count out."""
        run = self.c / "runs/ladder-d0-canary54-noearlyend-from41-s42-20261006"
        run.mkdir(parents=True, exist_ok=True)
        lineage = run / "final.bin.lineage.json"
        implementation = {"source_sha256": "7" * 64,
                          "compiled_module_sha256": sha(self.module)}
        implementation.update(built)
        lineage.write_text(json.dumps({"implementation": implementation}))

        def panel(cut):
            return {"n": 12000.0} if cut is None else {"n": 12000.0,
                                                       "truncated_episodes": cut}
        result = run / "arm.result.json"
        result.write_text(json.dumps({"acceptance_pass": accepted,
                                      "checkpoint_sha256": result_checkpoint,
                                      "train_metrics": panel(train_cut),
                                      "eval_metrics": panel(eval_cut)}))
        exam = []
        for seed in (42, 43):
            for name in cell_names:
                cell = {"seed": seed, "cell": name, "no_early_end_turn": 1,
                        "truncated_episodes": 0.0}
                exam.append(cell)
        exam = exam[:cells]
        if cell_cut is None:
            exam[-1].pop("truncated_episodes")
        else:
            exam[-1]["truncated_episodes"] = cell_cut
        record = {"checkpoint_sha256": "c" * 64}
        if rule:
            record["no_early_end_turn"] = 1
        (run / "LADDER_RUNG_COMPLETE.json").write_text(json.dumps(
            {**record, "checkpoint_lineage": str(lineage), "result": str(result)}))
        (run / "EXAM_VERDICT_PASS.json").write_text(json.dumps(
            {**record, "pass": verdict_pass, "cells": exam}))

    def check_common(self, handed):
        marker = (self.longrun / "runs/ladder-d0-r0chain41-cont40-rr1-20261003"
                  / "LADDER_RUNG_COMPLETE.json")
        expected = {
            "C": str(self.c), "SEED": "42", "PREV_COMPLETE": str(marker),
            "EXPECTED_POOL_HASH": POOL_HASH, "LADDER_NO_EARLY_END_TURN": "1",
            "EXAM_RULE": "none", "SCRIPTED_BANK_TAG": "4", "SCRIPTED_BOT_TYPE": "0",
            "LADDER_ARM": "r0_poss_half", "RUNG": "0", "RESET_PCT": "0",
            "FROZEN_BANK_PCT": "0.12", "LADDER_GAMMA": "0.999",
            "LADDER_GAE_LAMBDA": "0.95", "LADDER_REPLAY_RATIO": "1.0",
            "LADDER_CHAIN_LR_SCALE": "1.0", "LADDER_CHAIN_ENT_SCALE": "1.0",
            "LADDER_PROFILE": "graft", "DEADLINE_HOURS": "16", "NUM_THREADS": "16",
            "GRAFT_FROM_SOURCE_SHA256": ORIGINAL[0] + "," + LONGRUN[0],
            "GRAFT_FROM_PATCH_BUNDLE_SHA256": ORIGINAL[2] + "," + LONGRUN[2],
            "PUFFER_SKIP_SCRIPTED_BANK_FORWARD": "1", "BBE_DECIDING_ROW_TELEMETRY": "1",
            "CUDA_VISIBLE_DEVICES": "0",
        }
        for key, value in expected.items():
            self.assertEqual(handed.get(key), value, key)
        self.assertNotIn("EXAM_GUARD_FLOOR_MEAN", handed)
        self.assertNotIn("LADDER_REGRESSION_FLOOR", handed)
        # Every variable tools/chain_stage.sh refuses to start without.
        chain = (ROOT / "tools/chain_stage.sh").read_text(encoding="utf-8")
        required = re.findall(r"for name in ((?:[A-Z_0-9]+[ \\\n]+)+?)do", chain)[:2]
        for name in " ".join(required).replace("\\", " ").split():
            self.assertIn(name, handed, name)

    def test_the_rung_wrapper_hands_chain_stage_the_paired_rung(self):
        self.pass_identity()
        self.pass_canary()
        result = self.run_script("b3_chain54.sh")
        self.assertEqual(result.returncode, 0, result.stdout)
        handed = self.handed()
        self.check_common(handed)
        self.assertEqual(handed["STAMP"], "r0chain54-noearlyend-from41-s42-20261006")
        self.assertEqual(handed["STEPS"], "3000000000")

    def test_the_canary_differs_from_the_rung_in_stamp_and_steps_only(self):
        self.pass_identity()
        self.assertEqual(self.run_script("b3_canary54.sh").returncode, 0)
        canary = self.handed()
        self.check_common(canary)
        self.assertEqual(canary["STAMP"], "canary54-noearlyend-from41-s42-20261006")
        self.assertEqual(canary["STEPS"], "50000000")
        self.pass_canary()
        self.assertEqual(self.run_script("b3_chain54.sh").returncode, 0)
        rung = self.handed()
        differing = sorted(key for key in set(canary) | set(rung)
                           if canary.get(key) != rung.get(key)
                           and key not in ("_", "SHLVL", "BASH_EXECUTION_STRING"))
        self.assertEqual(differing, ["STAMP", "STEPS"])

    def refused(self, name, message):
        result = self.run_script(name)
        self.assertEqual(result.returncode, 2, (name, result.stdout))
        self.assertIn(message, result.stdout, name)
        self.assertFalse((self.c / "chain_stage.env").exists(), name)

    def test_nothing_trains_before_the_gates_before_it_have_passed(self):
        for name in ("b3_canary54.sh", "b3_chain54.sh"):
            self.refused(name, "no usable identity pass marker")
            self.refused(name, "the identity stage has not passed on the installed build")
        self.pass_identity()
        self.refused("b3_chain54.sh", "the canary has no usable passing verdict")
        self.refused("b3_chain54.sh", "the canary has not passed on the installed build")
        # A result written under the unit-test overrides is not the marker.
        (self.out / "B3_IDENTITY_PASS.json").unlink()
        (self.out / "B3_IDENTITY_PASS.unpinned.json").write_text(json.dumps(
            {"pass": True, "reference_pinned": False}))
        self.refused("b3_canary54.sh", "no usable identity pass marker")

    def test_a_marker_file_is_not_a_gate_by_existing(self):
        # The supervisor only looks for the files. After a rebuild they are
        # still there, and the wrappers must not train on them.
        for marker, message in (
            ({"pass": False}, "is not a pass against the pinned digests"),
            ({"reference_pinned": False}, "is not a pass against the pinned digests"),
            ({"compiled_module_sha256": "e" * 64}, "the installed build is source"),
            ({"source_sha256": "e" * 64}, "the installed build is source"),
        ):
            self.pass_identity(**marker)
            for name in ("b3_canary54.sh", "b3_chain54.sh"):
                self.refused(name, message)
        self.pass_identity()
        for canary, message in (
            ({"compiled_module_sha256": "e" * 64}, "the canary under"),
            ({"source_sha256": "e" * 64}, "the canary under"),
            ({"rule": 0}, "did not pass under no_early_end_turn"),
            ({"verdict_pass": False}, "did not pass under no_early_end_turn"),
        ):
            self.pass_canary(**canary)
            self.refused("b3_chain54.sh", message)
        # D416 amendment: a game cut by the decision cap anywhere in the
        # canary, or a count that is not there, and chain 54 does not train.
        for canary, where in (
            ({"train_cut": 0.002}, "'training': 0.002"),
            ({"eval_cut": 0.0001}, "'end-of-run evaluation': 0.0001"),
            ({"cell_cut": 0.0005}, "'exam cell s43 offense_away': 0.0005"),
            ({"train_cut": None}, "'training': None"),
            ({"eval_cut": None}, "'end-of-run evaluation': None"),
            ({"cell_cut": None}, "'exam cell s43 offense_away': None"),
        ):
            self.pass_canary(**canary)
            self.refused("b3_chain54.sh", "does not record zero truncated_episodes everywhere")
            self.refused("b3_chain54.sh", where)
        self.pass_canary(accepted=False)
        self.refused("b3_chain54.sh", "is not an accepted arm with six exam cells")
        self.pass_canary(cells=5)
        self.refused("b3_chain54.sh", "is not an accepted arm with six exam cells")
        # Six entries that are not the six cells: a repeated cell could hide
        # a missing one.
        self.pass_canary(cell_names=("contact_away", "contact_home", "contact_home"))
        self.refused("b3_chain54.sh", "is not an accepted arm with six exam cells")
        # A result file that belongs to another checkpoint is not this canary's.
        self.pass_canary(result_checkpoint="d" * 64)
        self.refused("b3_chain54.sh", "is not an accepted arm with six exam cells")
        # The rebuild itself: both markers were good until the module changed.
        self.pass_canary()
        self.assertEqual(self.run_script("b3_chain54.sh").returncode, 0)
        (self.c / "chain_stage.env").unlink()
        self.module.write_bytes(b"rebuilt module\n")
        self.refused("b3_canary54.sh", "Run b3_identity.sh on this build")
        self.refused("b3_chain54.sh", "Run b3_identity.sh on this build")

    def test_a_plan_only_pass_may_run_before_the_gates(self):
        for name in ("b3_canary54.sh", "b3_chain54.sh"):
            result = self.run_script(name, PLAN_ONLY="1")
            self.assertEqual(result.returncode, 0, (name, result.stdout))
            self.assertEqual(self.handed()["PLAN_ONLY"], "1")
            (self.c / "chain_stage.env").unlink()


class IdentityStageTests(FakeCheckouts):
    PASS = "B3_IDENTITY_PASS.unpinned.json"   # these tests replace the pinned digests

    def identity(self, **over):
        return self.run_script("b3_identity.sh", **over)

    def probe_calls(self):
        return self.calls.read_text().split() if self.calls.exists() else []

    def assert_failed(self, result, message, code=1):
        self.assertEqual(result.returncode, code, result.stdout)
        self.assertIn(message, result.stdout)
        self.assertFalse((self.out / self.PASS).exists())
        self.assertFalse((self.out / "B3_IDENTITY_PASS.json").exists())

    def test_everything_passing_writes_the_marker_and_a_relaunch_does_nothing(self):
        result = self.identity()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.probe_calls(), ["identity", "trace", "ppo"])
        marker = json.loads((self.out / self.PASS).read_text())
        self.assertIs(marker["pass"], True)
        self.assertEqual(marker["failures"], [])
        self.assertEqual(marker["compiled_module_sha256"], sha(self.module))
        self.assertEqual(marker["source_sha256"], "7" * 64)
        self.assertIs(marker["reference_pinned"], False)
        weights = marker["checks"]["flag_off_identity"]["weights"]
        self.assertEqual(weights["131072"]["replicated_sha256"], sha(self.ref1))
        self.assertEqual(weights["50069504"]["replicated_sha256"], sha(self.ref382))
        self.assertEqual(marker["checks"]["flag_off_identity"]["end_turn_removed"], 0.0)
        self.assertEqual(marker["checks"]["flag_on_trace"]["end_turn_removed"], 55.0)
        self.assertEqual(marker["checks"]["flag_on_ppo"]["end_turn_removed"], 55.0)
        # With the test overrides set, the campaign's own marker is never written.
        self.assertFalse((self.out / "B3_IDENTITY_PASS.json").exists())
        # The GPU lock was taken and given back, as chain_stage.sh logs it.
        lock_log = Path(str(self.gpu_lock) + ".log").read_text()
        self.assertIn("acquired(lock=", lock_log)
        self.assertIn("released(probes done)", lock_log)
        with self.gpu_lock.open("a") as probe:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # The flag-off run got chain 42's arguments minus the five replaced
        # ones, the warm start and the private pool copy.
        args = (self.out / "attempt1/chain42-full.args").read_text().split()
        self.assertEqual(args, ["--seed", "42", "--vec.total-agents", "2048",
                                "--env.scripted-bank-tag", "4"])
        self.assertTrue((self.out / "pool-cc9b201e/league_seeds.json").exists())
        status = json.loads((self.out / "B3_IDENTITY_STATUS.json").read_text())
        self.assertEqual((status["phase"], status["exit_code"]), ("exited", 0))

        again = self.identity()
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertIn("already passed for this build", again.stdout)
        self.assertEqual(self.probe_calls(), ["identity", "trace", "ppo"])
        self.assertFalse((self.out / "attempt2").exists())

    def test_each_defect_fails_closed(self):
        for mode, message in (
            ("weights-differ", "weights at 50069504 steps differ from chain 42's"),
            ("wrong-steps", "saved epochs/steps are"),
            ("removed-with-flag-off", "with the flag off; it must be present and exactly 0"),
            ("flag-ignored", "with the flag on; the env did not apply the rule"),
            ("old-module-panel", "with the flag on; the env did not apply the rule"),
            ("foreign-module-identity", "replicate-c42: the probe imported module"),
            ("foreign-module-trace", "trace-flag-on: the probe imported module"),
            ("unrouted-trace", "trace-flag-on: the scripted-bank forward skip is not routed"),
            ("integrity-ppo", "smoke-flag-on: hard-integrity counters are not all zero"),
            ("truncated", "trace-flag-on: truncated_episodes is 0.25 with the flag on"),
            ("abort-message", "smoke-flag-on: the env aborted on a tuple outside exact joint support"),
            ("crash-identity", "replicate-c42: probe exit status 9"),
            ("crash-trace", "trace-flag-on: probe exit status 9"),
            ("crash-ppo", "smoke-flag-on: no readable output"),
        ):
            with self.subTest(mode=mode):
                self.tearDown()
                self.setUp()
                result = self.identity(STUB_MODE=mode)
                self.assert_failed(result, message)
                self.assertIn("NOT PASSED", result.stdout)
                record = json.loads(
                    (self.out / "attempt1/B3_IDENTITY_RESULT.json").read_text())
                self.assertIs(record["pass"], False)
                # The lock is released on failure too.
                with self.gpu_lock.open("a") as probe:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_cut_episodes_with_the_flag_off_are_reported_and_recorded_not_judged(self):
        # Chain 42's own play: the byte-equal weights settle that run.
        result = self.identity(STUB_MODE="truncated-flag-off")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("NOTE: replicate-c42: truncated_episodes is 0.25", result.stdout)
        marker = json.loads((self.out / self.PASS).read_text())
        self.assertEqual(marker["checks"]["flag_off_identity"]["truncated_episodes"], 0.25)

    def test_a_failure_is_retried_in_a_new_attempt_directory(self):
        self.assert_failed(self.identity(STUB_MODE="flag-ignored"), "did not apply the rule")
        result = self.identity()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue((self.out / "attempt1/B3_IDENTITY_RESULT.json").exists())
        self.assertTrue((self.out / "attempt2/B3_IDENTITY_RESULT.json").exists())
        self.assertEqual(json.loads((self.out / self.PASS).read_text())["attempt"], 2)

    def test_cpu_checks_stop_before_the_gpu_lock(self):
        (self.c / "DRIFT").write_text("x")
        self.assert_failed(self.identity(), "drift check failed")
        (self.c / "DRIFT").unlink()
        # A venv copied without repointing its entrypoints.
        self.entry.write_text("#!/home/rache/elsewhere/vendor/PufferLib/.venv/bin/python\n")
        self.assert_failed(self.identity(), "not this checkout's venv")
        self.entry.write_text(f"#!{self.entry.parent}/python\n")
        self.assert_failed(self.identity(B3_TEST_WARM_SHA256="0" * 64), "is not chain 41")
        self.assert_failed(self.identity(B3_TEST_EPOCH382_SHA256="0" * 64),
                           "is not chain 42's 50,069,504-step checkpoint")
        self.assert_failed(self.identity(B3_TEST_POOL_SHA256="0" * 64), "pool copy identity")
        self.assertEqual(self.probe_calls(), [])
        self.assertFalse(Path(str(self.gpu_lock) + ".log").exists())

    def test_the_pinned_digests_are_the_default_and_refuse_these_stand_ins(self):
        # Without the overrides the script holds the inputs to the real
        # chain 41 and chain 42 digests, which the stand-in files are not.
        result = self.identity(B3_TEST_WARM_SHA256=None, B3_TEST_EPOCH1_SHA256=None,
                               B3_TEST_EPOCH382_SHA256=None, B3_TEST_POOL_SHA256=None)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("is not chain 41 (b1830e2312a6252006de71f2835f3459f0a13f664d83ae"
                      "3128182c48cb0b303b)", result.stdout)
        text = (B3 / "b3_identity.sh").read_text(encoding="utf-8")
        for digest in ("a9efe0acbaa4794b7e830cef0e73a0bdc3af953d97caa39c129efd73d9b4ca73",
                       "6c079cdc60799cf176c040e344e8a899db8af563b21850c3303486076a72313f"):
            self.assertIn(digest, text)

    def test_missing_inputs_are_a_configuration_error(self):
        env = self.env()
        self.ref1.unlink()
        result = subprocess.run(
            ["bash", str(B3 / "b3_identity.sh")], env=env, cwd="/", text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=120)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("missing input", result.stdout)
        self.assertFalse(self.out.exists())

    def test_a_pass_marker_for_another_build_is_not_a_pass(self):
        self.assertEqual(self.identity().returncode, 0)
        self.module.write_bytes(b"rebuilt module\n")
        result = self.identity(STUB_MODULE_SHA=sha(self.module))
        self.assertEqual(result.returncode, 4, result.stdout)
        self.assertIn("a pass marker exists for a DIFFERENT build", result.stdout)
        self.assertEqual(self.probe_calls(), ["identity", "trace", "ppo"])

    def test_a_second_launch_beside_a_running_one_does_not_start(self):
        self.out.mkdir(parents=True)
        with (self.out / ".b3_identity.lock").open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            result = self.identity()
        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertIn("another b3_identity.sh holds", result.stdout)
        self.assertEqual(self.probe_calls(), [])

    def test_it_waits_for_the_gpu_lock_without_running_anything(self):
        with self.gpu_lock.open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            process = subprocess.Popen(
                ["bash", str(B3 / "b3_identity.sh")], env=self.env(), cwd="/",
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            time.sleep(3.5)
            self.assertIsNone(process.poll())
            self.assertEqual(self.probe_calls(), [])
            status = json.loads((self.out / "B3_IDENTITY_STATUS.json").read_text())
            self.assertEqual(status["phase"], "waiting-gpu-lock")
        output, _ = process.communicate(timeout=120)
        self.assertEqual(process.returncode, 0, output)
        self.assertIn("waiting on", output)
        self.assertEqual(self.probe_calls(), ["identity", "trace", "ppo"])


class CheckoutScriptTests(unittest.TestCase):
    def test_it_follows_the_long_run_recipe_and_repoints_the_entrypoints_too(self):
        text = (B3 / "make_b3_checkout.sh").read_text(encoding="utf-8")
        for step in (
            'if [ -e "$C2" ]; then echo "$C2 already exists; refusing"; exit 2; fi',
            'git clone -q "$S" "$C2"',
            "rsync -a --exclude build --exclude .venv --exclude checkpoints "
            "--exclude logs --exclude experiments",
            'cp -a "$S/vendor/PufferLib/.venv" "$C2/vendor/PufferLib/.venv"',
            "__editable___pufferlib_4_0_0_finder.py",
            'sed -i "s#${S}/#${C2}/#g" "$F"',
            'sed -i "s#${S}/vendor/PufferLib/.venv#${V}#g" "$file"',
            '[ "$(head -n 1 "$V/bin/puffer")" = "#!$V/bin/python" ]',
            "export PUFFER_SKIP_SCRIPTED_BANK_FORWARD=1 BBE_DECIDING_ROW_TELEMETRY=1",
            "bash tools/install_puffer_env.sh >",
            "./build.sh bloodbowl --float",
            "bash tools/install_puffer_env.sh --check",
            "\ncd /\n",
            "assert _C.environment_source_hash == installed",
        ):
            self.assertIn(step, text, step)
        self.assertLess(text.index("cp -a"), text.index("tools/install_puffer_env.sh >"))
        # Under `set -euo pipefail` a grep with nothing to show must not end
        # the script: an installer that had nothing left to apply prints no
        # "applied" line.
        self.assertIn('grep -E "^applied|^reversed" "$C2/runs/install_b3.log" | tail -4 || true',
                      text)
        for line in text.splitlines():
            if line.lstrip().startswith("grep ") and "|" in line and "-q" not in line:
                self.assertTrue(line.rstrip().endswith("|| true"), line)
        self.assertLess(text.index("./build.sh bloodbowl --float"),
                        text.index("install_puffer_env.sh --check"))
        self.assertIn("/home/rache/bloodbowl-rl-b3-20261006", text)

    def test_all_stage_scripts_parse(self):
        for path in sorted(B3.glob("*.sh")):
            done = subprocess.run(["bash", "-n", str(path)], text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(done.returncode, 0, (path.name, done.stdout))
        for path in sorted(B3.iterdir()):
            self.assertNotIn("—", path.read_text(encoding="utf-8"), path.name)


class EvalEntrypointTests(unittest.TestCase):
    """tools/eval_vs_contact_bot.sh: which interpreter the exam really runs under."""

    def block(self):
        source = (ROOT / "tools/eval_vs_contact_bot.sh").read_text(encoding="utf-8")
        start = source.index('ENTRY_INTERPRETER="$(head -n 1 "$PUFFER_BIN"')
        return source[start:source.index("esac\n", start) + len("esac\n")]

    def check(self, shebang, rule):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            venv = root / "vendor/PufferLib/.venv/bin"
            venv.mkdir(parents=True)
            entry = venv / "puffer"
            entry.write_text(shebang.replace("@VENV@", str(venv)) + "\nprint('x')\n")
            script = (f'ROOT="{root}"\nPUFFER_BIN="{entry}"\nNO_EARLY_END_TURN={rule}\n'
                      + self.block() + "echo CONTINUED\n")
            return subprocess.run(["bash", "-c", script], text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  check=False, timeout=60)

    def test_this_checkouts_venv_passes_silently(self):
        for shebang in ("#!@VENV@/python", "#!@VENV@/python3.11",
                        "#!/bin/sh\n'''exec' \"@VENV@/python\" \"$0\" \"$@\""):
            for rule in ("0", "1"):
                done = self.check(shebang, rule)
                self.assertIn("CONTINUED", done.stdout, (shebang, rule))
                self.assertEqual(done.stderr, "", (shebang, rule))

    def test_a_foreign_venv_is_refused_under_the_rule_and_reported_without_it(self):
        foreign = "#!/home/rache/bloodbowl-rl-qualification-candidate-10619e2/vendor/PufferLib/.venv/bin/python"
        refused = self.check(foreign, "1")
        self.assertNotIn("CONTINUED", refused.stdout)
        self.assertIn("LADDER_NO_EARLY_END_TURN=1 refused", refused.stderr)
        self.assertIn("is not this checkout's venv", refused.stderr)
        # Without the rule the exam runs as it always did, and says so.
        reported = self.check(foreign, "0")
        self.assertIn("CONTINUED", reported.stdout)
        self.assertIn("warning:", reported.stderr)
        self.assertIn("not this checkout's venv", reported.stderr)


if __name__ == "__main__":
    unittest.main()
