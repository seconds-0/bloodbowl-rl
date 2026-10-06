#!/usr/bin/env python3
"""LADDER_NO_EARLY_END_TURN: the launcher knob for the env flag no_early_end_turn.

The flag is an env-layer training restriction, not a Blood Bowl rule
(docs/no-early-end-turn-2026-10-05.md). The knob travels chain_stage.sh ->
ladder_stage.sh -> launch_ladder_rung.sh -> run_reward_screen.sh ->
run_reward_ablation.sh -> trainer `--env.no-early-end-turn 1`, and the same
variable makes eval_vs_contact_bot.sh run an exam under the rule.

Two properties are pinned here. Unset (or 0), nothing changes: no trainer flag,
no run-manifest key, the screen contract's historical keys, no marker key, no
eval-manifest key, no verdict key. Set to 1, the rule is recorded at every one
of those places, and each later stage reads it from the record of what ran, not
from the variable alone.

These run the real scripts. Where a script needs a build, the stand-in checkout
of tools/test_ladder_rung_profile.py or the fake checkout of
tools/test_chain_stage.py supplies it.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from tools import test_chain_exam_verdict as verdict_tests  # noqa: E402
from tools import test_chain_stage as chain_tests  # noqa: E402
from tools import test_ladder_knobs as knob_tests  # noqa: E402
from tools import test_ladder_rung_profile as rung_tests  # noqa: E402
from tools import test_ladder_stage as stage_tests  # noqa: E402

LAUNCHER = ROOT / "tools/run_reward_ablation.sh"
SCREEN = ROOT / "tools/run_reward_screen.sh"
RUNG = ROOT / "tools/launch_ladder_rung.sh"
STAGE = ROOT / "tools/ladder_stage.sh"
CHAIN = ROOT / "tools/chain_stage.sh"
EVAL = ROOT / "tools/eval_vs_contact_bot.sh"
VERDICT = ROOT / "tools/chain_exam_verdict.py"
KNOB = "LADDER_NO_EARLY_END_TURN"
FLAG = ["--env.no-early-end-turn", "1"]
BAD_VALUES = ("2", "yes", "true", "01", "1 ", "-1")


def launcher_region(start: str, end: str) -> str:
    """The launcher's own text from `start` up to (not including) `end`."""
    source = LAUNCHER.read_text(encoding="utf-8")
    begin = source.index(start)
    return source[begin:source.index(end, begin)]


def render_full_trainer_argv(**values) -> list[str]:
    """Evaluate every CMD statement of the real launcher: the base block, the
    selfplay/pool and scripted-bank appends, and the rule's append."""
    region = launcher_region("\nCMD=(env PUFFER_CUDA_RUNTIME_MANIFEST=",
                             '\nif [ "${DRY_RUN:-0}" = "1" ]; then')
    values.setdefault("POOL_MODE", "1")
    values.setdefault("SCRIPTED_BANK_TAG", "4")
    values.setdefault("SCRIPTED_BOT_TYPE", "0")
    script = ("REWARD_ARGS=()\n"
              + "".join(f"{key}={shlex.quote(str(value))}\n"
                        for key, value in values.items())
              + region + "\nprintf '%s\\n' \"${CMD[@]}\"\n")
    out = subprocess.run(["bash", "-c", script], text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         check=True, timeout=60)
    return out.stdout.splitlines()


def render_full_run_manifest_pairs(**values) -> dict[str, str]:
    """Evaluate every META_ARGS statement of the real launcher."""
    region = launcher_region("\nMETA_ARGS=(\n",
                             '\n"$PYBIN" - "$RUN_MANIFEST" "${META_ARGS[@]}"')
    values.setdefault("BOOTSTRAP_MODE", "lineage-v6")
    script = ("".join(f"{key}={shlex.quote(str(value))}\n"
                      for key, value in values.items())
              + region + "\nprintf '%s\\n' \"${META_ARGS[@]}\"\n")
    out = subprocess.run(["bash", "-c", script], text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         check=True, timeout=60)
    pairs = out.stdout.split("\n")[:-1]
    assert len(pairs) % 2 == 0, "run-manifest metadata pairs misaligned"
    return dict(zip(pairs[::2], pairs[1::2]))


class EnvFlagContractTests(unittest.TestCase):
    """The three places that must agree for `--env.no-early-end-turn` to exist."""

    def test_config_binding_and_header_carry_the_flag_and_it_defaults_off(self):
        config = (ROOT / "puffer/config/bloodbowl.ini").read_text(encoding="utf-8")
        self.assertEqual(
            re.findall(r"^no_early_end_turn\s*=\s*(\S+)\s*$", config, re.M), ["0"])
        binding = (ROOT / "puffer/bloodbowl/binding.c").read_text(encoding="utf-8")
        self.assertIn('kw(kwargs, "no_early_end_turn", 0.0)', binding)
        self.assertIn("env->no_early_end_turn = (int)no_early_end_turn;", binding)
        header = (ROOT / "puffer/bloodbowl/bloodbowl.h").read_text(encoding="utf-8")
        self.assertIn("int no_early_end_turn;", header)

    def test_the_engine_knows_nothing_of_the_flag(self):
        # An env-layer restriction: the rules engine keeps offering END_TURN.
        for path in sorted((ROOT / "engine").rglob("*.[ch]")):
            self.assertNotIn("no_early_end_turn",
                             path.read_text(encoding="utf-8", errors="replace"),
                             str(path))


class ArmLauncherTests(unittest.TestCase):
    def test_bad_values_are_refused_before_any_preflight(self):
        for bad in BAD_VALUES:
            out = knob_tests.run(**{KNOB: bad}).stdout
            self.assertIn(f"{KNOB} must be 0 or 1", out, bad)
        for good in ("0", "1"):
            out = knob_tests.run(**{KNOB: good}).stdout
            self.assertNotIn(KNOB, out, good)
            self.assertIn("vendored Python missing", out, good)

    def test_unset_and_zero_add_nothing_to_the_trainer_command(self):
        base = knob_tests.render_trainer_argv()
        for values in ({}, {KNOB: "0"}, {KNOB: ""}):
            argv = render_full_trainer_argv(**values)
            self.assertNotIn("--env.no-early-end-turn", argv, values)
            # The base block is the prefix it always was; what follows it is
            # the selfplay/pool and scripted-bank tail, nothing else.
            self.assertEqual(argv[:len(base)], base, values)
        self.assertEqual(render_full_trainer_argv(),
                         render_full_trainer_argv(**{KNOB: "0"}))

    def test_one_appends_exactly_the_flag_and_nothing_else(self):
        off = render_full_trainer_argv()
        on = render_full_trainer_argv(**{KNOB: "1"})
        self.assertEqual(on, off + FLAG)
        # In the fresh modes too: the flag does not depend on a pool.
        off = render_full_trainer_argv(POOL_MODE="0")
        on = render_full_trainer_argv(POOL_MODE="0", **{KNOB: "1"})
        self.assertEqual(on, off + FLAG)

    def test_run_manifest_carries_the_key_only_when_the_rule_is_on(self):
        historical = knob_tests.render_run_manifest_pairs(
            BOOTSTRAP_MODE="lineage-v6")
        for values in ({}, {KNOB: "0"}):
            pairs = render_full_run_manifest_pairs(**values)
            self.assertNotIn("no_early_end_turn", pairs, values)
            self.assertEqual(pairs, historical, values)
        on = render_full_run_manifest_pairs(**{KNOB: "1"})
        self.assertEqual(on.pop("no_early_end_turn"), "1")
        self.assertEqual(on, historical)

    def test_launcher_refuses_a_config_that_turns_the_rule_on_by_itself(self):
        # "No key in the manifest" must mean "off", so the installed default
        # has to be 0. The check is the launcher's own text, run on configs.
        block = launcher_region(
            "if grep -Eq '^no_early_end_turn[[:space:]]*=' config/bloodbowl.ini",
            "grep -Fq 'Patch copy: training/selfplay_league.patch'")
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config/bloodbowl.ini"
            config.parent.mkdir()

            def check(text, knob):
                config.write_text(text, encoding="utf-8")
                return subprocess.run(
                    ["bash", "-c", f"{KNOB}={knob}\n{block}\necho PASSED\n"],
                    cwd=tmp, text=True, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, check=False, timeout=60)

            for knob in ("0", "1"):
                ok = check("[env]\nno_early_end_turn = 0\nmax_decisions = 4096\n", knob)
                self.assertIn("PASSED", ok.stdout, knob)
                for bad in ("no_early_end_turn = 1\n", "no_early_end_turn=1\n",
                            "no_early_end_turn = 01\n", "no_early_end_turn =\n"):
                    refused = check("[env]\n" + bad, knob)
                    self.assertNotIn("PASSED", refused.stdout, (knob, bad))
                    self.assertIn("its default must be 0", refused.stderr, (knob, bad))
            # A config from before the flag: fine while the rule is off, and a
            # clear refusal when it is asked for.
            old = "[env]\nmax_decisions = 4096\n"
            self.assertIn("PASSED", check(old, "0").stdout)
            refused = check(old, "1")
            self.assertNotIn("PASSED", refused.stdout)
            self.assertIn("needs an installed config with the no_early_end_turn key",
                          refused.stderr)


class ScreenPlanTests(unittest.TestCase):
    """The rung screen, whole, on the stand-in build."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root, self.warm, self.pool = rung_tests.stand_in_checkout(self.temp.name)
        self.dump = self.root / "arm.env"
        # The stand-in's arm launcher, extended to report the knob it was given.
        (self.root / "tools/run_reward_ablation.sh").write_text(
            "#!/bin/bash\n"
            f"printf '%s\\n' \"{KNOB}=${{{KNOB}-<unset>}}\" > \"$ARM_ENV_DUMP\"\n",
            encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def screen(self, out, **over):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("LADDER_", "SCRIPTED_", "GRAFT_", "BRIDGE_"))
               and k not in ("WARM", "POOL", "CANDIDATE_ARM", "STEPS",
                             "SCREEN_PROFILE", "EXPECTED_POOL_HASH", "PREFIX",
                             "OUT_DIR", "PLAN_ONLY", "NUM_FROZEN_BANKS",
                             "FROZEN_BANK_PCT", "TRANSFER_COMPLETE",
                             "EXPECTED_TRANSFER_SHA256", "ARM_DETACH",
                             "POLL_SECONDS", "NUM_THREADS")}
        env.update({
            "STEPS": "3000000000", "SCREEN_PROFILE": "ladder-rung",
            "WARM": str(self.warm), "POOL": str(self.pool),
            "EXPECTED_POOL_HASH": "d" * 64, "PREFIX": "rule-test",
            "OUT_DIR": str(self.root / out), "PLAN_ONLY": "1",
            "LADDER_ENDZONE_MAXDIST": "0", "LADDER_RESET_PCT": "0",
            "LADDER_SEED": "42", "LADDER_ARM": "r0_poss_half",
            "SCRIPTED_BANK_TAG": "4", "SCRIPTED_BOT_TYPE": "0",
            "FROZEN_BANK_PCT": "0.12", "POLL_SECONDS": "1",
            "ARM_ENV_DUMP": str(self.dump),
        })
        env.update(over)
        return subprocess.run(
            ["bash", str(self.root / "tools/run_reward_screen.sh")],
            cwd=self.root, env=env, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False, timeout=300)

    def contract(self, out):
        return json.loads(
            (self.root / out / "SCREEN_MANIFEST.json").read_text())["contract"]

    def planned(self, out, **over):
        result = self.screen(out, **over)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SCREEN PLAN VERIFIED", result.stdout)
        contract = self.contract(out)
        contract.pop("out_dir")
        return contract

    def test_plan_records_the_rule_only_when_it_is_on(self):
        plain = self.planned("plain")
        self.assertEqual(sorted(plain["ladder"]), rung_tests.HISTORICAL_LADDER_KEYS)
        self.assertNotIn("no_early_end_turn", json.dumps(plain))
        # Explicitly empty and explicitly 0 are the unset knob.
        self.assertEqual(self.planned("empty", **{KNOB: ""}), plain)
        self.assertEqual(self.planned("zero", **{KNOB: "0"}), plain)
        on = self.planned("on", **{KNOB: "1"})
        self.assertEqual(on["ladder"].pop("no_early_end_turn"), 1)
        self.assertEqual(on, plain)
        # Beside the other declared knobs of the long run's recipe.
        recipe = self.planned("recipe", LADDER_GAMMA="0.999",
                              LADDER_GAE_LAMBDA="0.95",
                              LADDER_REPLAY_RATIO="1.0", **{KNOB: "1"})
        self.assertEqual(sorted(recipe["ladder"]), sorted(
            rung_tests.HISTORICAL_LADDER_KEYS
            + ["gamma", "gae_lambda", "replay_ratio", "no_early_end_turn"]))

    def test_a_relaunch_cannot_switch_the_rule_under_one_plan(self):
        self.planned("same")
        result = self.screen("same", **{KNOB: "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists with a different contract", result.stderr)
        self.assertIn("ladder", result.stderr)
        self.planned("other", **{KNOB: "1"})
        result = self.screen("other")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists with a different contract", result.stderr)

    def test_bad_values_and_other_profiles_are_refused(self):
        for bad in BAD_VALUES:
            result = self.screen(f"bad-{bad.strip()}", **{KNOB: bad})
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn(f"{KNOB} must be 0 or 1", result.stderr, bad)
        for profile in ("control-final", "possession-gain-exact"):
            result = rung_tests.run(SCREEN, {
                "WARM": "missing.bin", "POOL": "missing-pool",
                "STEPS": "12000000000", "SCREEN_PROFILE": profile,
                "EXPECTED_POOL_HASH": "0" * 64, KNOB: "1"})
            self.assertNotEqual(result.returncode, 0, profile)
            self.assertIn(f"{KNOB} is only valid with SCREEN_PROFILE=ladder-rung, "
                          "graft or bridge", result.stderr, profile)
            # 0 is "off" everywhere, so an exported 0 does not break a profile
            # that has no such knob.
            result = rung_tests.run(SCREEN, {
                "WARM": "missing.bin", "POOL": "missing-pool",
                "STEPS": "12000000000", "SCREEN_PROFILE": profile,
                "EXPECTED_POOL_HASH": "0" * 64, KNOB: "0"})
            self.assertNotIn(KNOB, result.stderr, profile)

    def test_the_arm_launcher_is_handed_the_knob_explicitly(self):
        for knobs, received in (({}, ""), ({KNOB: "0"}, ""), ({KNOB: "1"}, "1")):
            if self.dump.exists():
                self.dump.unlink()
            result = self.screen(f"arm-{received or 'off'}-{len(knobs)}",
                                 PLAN_ONLY="0", **knobs)
            self.assertIn("missing process sidecar", result.stderr, knobs)
            self.assertEqual(self.dump.read_text().strip(), f"{KNOB}={received}",
                             knobs)

    def test_graft_and_bridge_take_the_knob_like_a_rung(self):
        source = SCREEN.read_text(encoding="utf-8")
        # One validation and one hand-off for all three rung-shaped profiles:
        # the knob is not in any per-profile LADDER_ENV list.
        self.assertEqual(source.count(
            f'        {KNOB}="${KNOB}" \\\n'
            '        /bin/bash "$ROOT/tools/run_reward_ablation.sh"'), 1)
        self.assertIn(f'if [ "$RUNG_LIKE" != "1" ] && [ -n "${KNOB}" ]; then', source)


def marker_run(tmp, run_manifest, **knobs):
    """Run the rung launcher's real marker block on a synthetic accepted arm."""
    tmp = Path(tmp)
    log = tmp / "arm.log"
    manifest_path = Path(str(log) + ".manifest.json")
    if run_manifest is None:
        if manifest_path.exists():
            manifest_path.unlink()
    else:
        manifest_path.write_text(json.dumps(run_manifest), encoding="utf-8")
    result_path = tmp / "r.json"
    result_path.write_text(json.dumps({
        "acceptance_pass": True, "tag": "t", "log": str(log),
        "checkpoint": "c", "checkpoint_sha256": "s",
        "checkpoint_lineage": "cl", "checkpoint_lineage_sha256": "cls",
        "eval_metrics": {"tds": 1.6, "perf": 0.57}}), encoding="utf-8")
    out = tmp / "m.json"
    if out.exists():
        out.unlink()
    env = {k: v for k, v in os.environ.items() if not k.startswith("LADDER_")}
    env.update(knobs)
    completed = subprocess.run(
        ["python3", "-", str(result_path), str(out), "0", "0", "3000000000",
         "42", "w", "p", "pfx", "", "0.5", "4", "0", "ladder-rung",
         "", "", "", "", "", "", ""],
        input=rung_tests.marker_block(), env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=60)
    return completed, (json.loads(out.read_text()) if out.exists() else None)


class RungMarkerTests(unittest.TestCase):
    OFF = {"command": ["python", "train", "bloodbowl", "--tag", "t"]}
    ON = {"command": ["python", "train", "bloodbowl", "--tag", "t", *FLAG],
          "no_early_end_turn": "1"}

    def test_marker_records_the_rule_from_what_the_trainer_received(self):
        with tempfile.TemporaryDirectory() as tmp:
            done, plain = marker_run(tmp, self.OFF)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertNotIn("no_early_end_turn", plain)
            # A rung with no readable run manifest and no knob is the marker
            # this script always wrote.
            done, legacy = marker_run(tmp, None)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(legacy, plain)
            done, zero = marker_run(tmp, self.OFF, **{KNOB: "0"})
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(zero, plain)
            done, on = marker_run(tmp, self.ON, **{KNOB: "1"})
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(on.pop("no_early_end_turn"), 1)
            self.assertEqual(on, plain)

    def test_a_marker_is_refused_when_the_knob_and_the_run_disagree(self):
        with tempfile.TemporaryDirectory() as tmp:
            for manifest, knobs, message in (
                (self.OFF, {KNOB: "1"},
                 f"{KNOB}=1 but the run trained with no_early_end_turn off"),
                (self.ON, {},
                 f"{KNOB}=unset but the run trained with no_early_end_turn on"),
                (self.ON, {KNOB: "0"},
                 f"{KNOB}=unset but the run trained with no_early_end_turn on"),
                # Half a record: the key without the flag, or the reverse.
                ({"command": self.OFF["command"], "no_early_end_turn": "1"},
                 {KNOB: "1"}, "disagree"),
                ({"command": self.ON["command"]}, {KNOB: "1"}, "disagree"),
                ({"command": [*self.OFF["command"], "--env.no-early-end-turn", "0"],
                  "no_early_end_turn": "1"}, {KNOB: "1"}, "disagree"),
            ):
                done, marker = marker_run(tmp, manifest, **knobs)
                self.assertNotEqual(done.returncode, 0, (manifest, knobs))
                self.assertIn(message, done.stderr, (manifest, knobs))
                self.assertIsNone(marker, (manifest, knobs))
            # Declared with no run manifest to check it against: no marker.
            done, marker = marker_run(tmp, None, **{KNOB: "1"})
            self.assertNotEqual(done.returncode, 0)
            self.assertIsNone(marker)

    def test_rung_launcher_validates_and_forwards_the_knob(self):
        source = RUNG.read_text(encoding="utf-8")
        self.assertIn(f'      {KNOB}="${{{KNOB}:-}}" \\\n', source)
        with tempfile.TemporaryDirectory() as tmp:
            for bad in BAD_VALUES:
                result = rung_tests.run(RUNG, {
                    "C": tmp, "RUNG": "0", "WARM": "w.bin", "POOL": "pool",
                    "EXPECTED_POOL_HASH": "0" * 64, KNOB: bad})
                self.assertNotEqual(result.returncode, 0, bad)
                self.assertIn(f"{KNOB} must be 0 or 1", result.stderr, bad)


class LadderStageTests(unittest.TestCase):
    def test_knob_is_validated_before_a_pool_is_built_and_exported(self):
        source = STAGE.read_text(encoding="utf-8")
        self.assertIn(f'[ -z "${{{KNOB}:-}}" ] || export {KNOB}', source)
        base = {"RUNG": "0", "RESET_PCT": "0", "SEED": "42", "STAMP": "t"}
        with tempfile.TemporaryDirectory() as tmp:
            for bad in BAD_VALUES:
                result = stage_tests.run({"C": tmp, **base, KNOB: bad})
                self.assertNotEqual(result.returncode, 0, bad)
                self.assertIn(f"{KNOB} must be 0 or 1", result.stdout, bad)
                self.assertNotIn("drift check failed", result.stdout, bad)
            for good in ("0", "1", ""):
                result = stage_tests.run({"C": tmp, **base, KNOB: good})
                self.assertNotIn(f"{KNOB} must be", result.stdout, good)
                self.assertIn("drift check failed", result.stdout, good)


# Stand-ins for the chain stage's two children that honour the knob the way the
# real scripts do: the rung marker and the eval manifest record the rule.
STUB_LADDER_RULE = chain_tests.STUB_LADDER.replace(
    'json.dump({"checkpoint": ckpt, "checkpoint_sha256": sha, "trainer_exit": 0,\n'
    '           "pool_hash": pool}, open(out + "/LADDER_RUNG_COMPLETE.json", "w"))',
    'import os\n'
    'marker = {"checkpoint": ckpt, "checkpoint_sha256": sha, "trainer_exit": 0,\n'
    '          "pool_hash": pool}\n'
    'rule = os.environ.get("STUB_MARKER_RULE", os.environ.get("' + KNOB + '", ""))\n'
    'if rule == "1":\n'
    '    marker["no_early_end_turn"] = 1\n'
    'json.dump(marker, open(out + "/LADDER_RUNG_COMPLETE.json", "w"))')
STUB_EVAL_RULE = chain_tests.STUB_EVAL.replace(
    'echo "$SEED $BOT_TYPE $BOT_TEAM $STEPS $LOG omp=',
    'echo "rule=${' + KNOB + '-<unset>}" >> "$ROOT/stub/eval_rule"\n'
    'echo "$SEED $BOT_TYPE $BOT_TEAM $STEPS $LOG omp=').replace(
    'echo "validated scripted eval: 2010 games; cumulative gate 2010"',
    'if [ "${STUB_EVAL_RULE-${' + KNOB + ':-0}}" = "1" ]; then\n'
    '  STUB_CELL="$SEED $BOT_TYPE $BOT_TEAM" python3 - "$LOG" <<\'PY\'\n'
    'import json, sys\n'
    'lines = open(sys.argv[1], encoding="utf-8").read().split("\\n", 1)\n'
    'prefix = "BB_EVAL_MANIFEST "\n'
    'manifest = json.loads(lines[0][len(prefix):])\n'
    'manifest["no_early_end_turn"] = 1\n'
    'manifest["command"] += ["--env.no-early-end-turn", "1"]\n'
    'import os\n'
    'cut = 0.01 if os.environ.get("STUB_EVAL_TRUNCATED") == os.environ["STUB_CELL"] else 0.0\n'
    'extra = \'"end_turn_removed": 250.0, \'\n'
    'if os.environ.get("STUB_EVAL_NO_COUNTER") != os.environ["STUB_CELL"]:\n'
    '    extra += \'"truncated_episodes": %r, \' % cut\n'
    'panels = lines[1].replace(\'"n": \', extra + \'"n": \')\n'
    'open(sys.argv[1], "w", encoding="utf-8").write(\n'
    '    prefix + json.dumps(manifest, sort_keys=True) + "\\n" + panels)\n'
    'PY\n'
    'fi\n'
    'echo "validated scripted eval: 2010 games; cumulative gate 2010"')
assert STUB_LADDER_RULE != chain_tests.STUB_LADDER, "ladder stub anchor moved"
assert STUB_EVAL_RULE.count(KNOB) == 2, "eval stub anchors moved"


class ChainStageRuleTests(unittest.TestCase):
    """chain_stage.sh: a rung trained under the rule is examined under it.

    The fake checkout and its helpers are tools/test_chain_stage.py's own;
    only the two stubs differ."""

    env = chain_tests.ChainStageTests.env
    stage = chain_tests.ChainStageTests.stage
    calls = chain_tests.ChainStageTests.calls
    release_lock = chain_tests.ChainStageTests.release_lock

    def setUp(self):
        chain_tests.ChainStageTests.setUp(self)
        tools = self.checkout / "tools"
        (tools / "ladder_stage.sh").write_text(STUB_LADDER_RULE, encoding="utf-8")
        (tools / "eval_vs_contact_bot.sh").write_text(STUB_EVAL_RULE, encoding="utf-8")

    def tearDown(self):
        chain_tests.ChainStageTests.tearDown(self)

    def verdict(self):
        return json.loads((self.run_dir / "EXAM_VERDICT.json").read_text())

    def check_rule_off(self, **knobs):
        result = self.stage(**knobs)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.calls("eval_rule"), ["rule=0"] * 6)
        self.assertNotIn("no_early_end_turn", json.dumps(self.verdict()))
        self.assertNotIn("no_early_end_turn", result.stdout)
        self.assertTrue((self.run_dir / "EXAM_VERDICT_PASS.json").exists())
        marker = json.loads((self.run_dir / "LADDER_RUNG_COMPLETE.json").read_text())
        self.assertNotIn("no_early_end_turn", marker)

    def test_rule_unset_runs_the_exam_and_verdict_they_always_were(self):
        self.check_rule_off()

    def test_rule_zero_is_the_unset_rule(self):
        self.check_rule_off(**{KNOB: "0"})

    def test_rule_empty_is_the_unset_rule(self):
        self.check_rule_off(**{KNOB: ""})

    def test_rule_on_trains_examines_and_records_under_the_rule(self):
        result = self.stage(**{KNOB: "1"})
        self.assertEqual(result.returncode, 0, result.stdout)
        # The rung is handed the knob ...
        ladder_env = (self.stub / "ladder_env").read_text()
        self.assertIn(f"{KNOB}=1\n", ladder_env)
        # ... all six cells run under the rule ...
        self.assertEqual(self.calls("eval_rule"), ["rule=1"] * 6)
        # ... and the verdict says so, for the stage and for every cell.
        verdict = self.verdict()
        self.assertEqual(verdict["no_early_end_turn"], 1)
        self.assertEqual([cell.get("no_early_end_turn") for cell in verdict["cells"]],
                         [1] * 6)
        self.assertEqual(
            json.loads((self.run_dir / "EXAM_VERDICT_PASS.json").read_text()),
            verdict)
        self.assertIn("exam runs under no_early_end_turn=1", result.stdout)
        self.assertIn("rule: no_early_end_turn=1 for the rung and for its exam",
                      result.stdout)

    def test_the_marker_decides_the_exam_and_a_mismatch_stops_the_stage(self):
        # The rung trained under the rule; a relaunch whose environment lost
        # the knob must not examine it without the rule.
        result = self.stage(**{KNOB: "1", "STUB_MARKER_RULE": "1",
                               "STUB_EVAL_RULE": "1"})
        self.assertEqual(result.returncode, 0, result.stdout)
        (self.run_dir / "EXAM_VERDICT.json").unlink()
        (self.run_dir / "EXAM_VERDICT_PASS.json").unlink()
        evals_before = len(self.calls("eval_calls"))
        result = self.stage()
        self.assertEqual(result.returncode, 7, result.stdout)
        self.assertIn("LADDER_RUNG_COMPLETE.json records no_early_end_turn=1, "
                      "this stage declares 0", result.stdout)
        self.assertEqual(len(self.calls("eval_calls")), evals_before)
        self.assertFalse((self.run_dir / "EXAM_VERDICT.json").exists())

    def test_a_finished_stage_relaunched_under_the_other_rule_is_refused(self):
        # Nothing is left to run, and the launch still has to describe the
        # stage that ran: a registered verdict is not "success" for a wrapper
        # that declares the other rule.
        for first, second, recorded, declared in (({KNOB: "1"}, {}, 1, 0),
                                                  ({}, {KNOB: "1"}, 0, 1)):
            with self.subTest(first=first):
                self.tearDown()
                self.setUp()
                result = self.stage(**first)
                self.assertEqual(result.returncode, 0, result.stdout)
                evals = len(self.calls("eval_calls"))
                again = self.stage(**first)
                self.assertEqual(again.returncode, 0, again.stdout)
                self.assertIn("verdict already registered and passed", again.stdout)
                for extra in ({}, {"PLAN_ONLY": "1"}):
                    other = self.stage(**second, **extra)
                    self.assertEqual(other.returncode, 7, other.stdout)
                    self.assertIn(
                        f"LADDER_RUNG_COMPLETE.json records no_early_end_turn="
                        f"{recorded}, this stage declares {declared}", other.stdout)
                    self.assertNotIn("verdict already registered", other.stdout)
                # A verdict alone (its marker lost) is checked as well.
                (self.run_dir / "LADDER_RUNG_COMPLETE.json").unlink()
                other = self.stage(**second)
                self.assertEqual(other.returncode, 7, other.stdout)
                self.assertIn(f"EXAM_VERDICT.json records no_early_end_turn="
                              f"{recorded}, this stage declares {declared}",
                              other.stdout)
                self.assertEqual(len(self.calls("eval_calls")), evals)
                self.assertEqual(self.calls("ladder_calls"), ["train"])

    def test_a_rung_that_did_not_train_under_the_rule_is_not_examined_under_it(self):
        result = self.stage(**{KNOB: "1", "STUB_MARKER_RULE": "0"})
        self.assertEqual(result.returncode, 7, result.stdout)
        self.assertIn("LADDER_RUNG_COMPLETE.json records no_early_end_turn=0, "
                      "this stage declares 1", result.stdout)
        self.assertEqual(self.calls("eval_calls"), [])

    def test_cells_that_ignored_the_rule_register_no_verdict(self):
        # The eval ran without the rule although the stage asked for it (an
        # eval script from before the knob, say): the verdict tool refuses.
        result = self.stage(**{KNOB: "1", "STUB_EVAL_RULE": "0"})
        self.assertEqual(result.returncode, 8, result.stdout)
        self.assertIn("the cell ran with no_early_end_turn off, the stage needs it on",
                      result.stdout)
        self.assertFalse((self.run_dir / "EXAM_VERDICT.json").exists())
        self.assertFalse((self.run_dir / "EXAM_VERDICT_PASS.json").exists())

    def test_an_inherited_rule_cannot_reach_an_exam_the_stage_did_not_ask_for(self):
        # The stage sets the cells' knob itself, from the marker check.
        source = CHAIN.read_text(encoding="utf-8")
        self.assertIn(f'        {KNOB}="$NO_EARLY_END_TURN_SEEN" \\\n', source)
        result = self.stage(**{"STUB_EVAL_RULE": "1"})
        self.assertEqual(result.returncode, 8, result.stdout)
        self.assertIn("the cell ran with no_early_end_turn on, the stage needs it off",
                      result.stdout)

    def test_a_cut_game_in_one_exam_cell_registers_no_verdict(self):
        # D416 amendment: under the rule every exam cell must show zero
        # truncated_episodes, and the counter must be there.
        for knob, message in (
            ("STUB_EVAL_TRUNCATED", "truncated_episodes is 0.01"),
            ("STUB_EVAL_NO_COUNTER", "the panel has no truncated_episodes"),
        ):
            with self.subTest(knob=knob):
                self.tearDown()
                self.setUp()
                result = self.stage(**{KNOB: "1", knob: "43 1 1"})
                self.assertEqual(result.returncode, 8, result.stdout)
                self.assertIn("s43/offense_away.log: " + message, result.stdout)
                self.assertFalse((self.run_dir / "EXAM_VERDICT.json").exists())
                self.assertFalse((self.run_dir / "EXAM_VERDICT_PASS.json").exists())

    def test_bad_values_are_a_configuration_error(self):
        for bad in BAD_VALUES:
            result = self.stage(**{KNOB: bad})
            self.assertEqual(result.returncode, 2, (bad, result.stdout))
            self.assertIn(f"{KNOB} must be 0 or 1", result.stdout, bad)
        self.assertEqual(self.calls("ladder_calls"), [])


class ExamVerdictRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.exam = self.root / "exam-attempt1"
        self.out = self.root / "run"
        self.out.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rule_cells=(), command_cells=None, value=1,
              panel_cells=None, removed=250.0, counted_cells="all",
              truncated_cells=(), truncated=0.01):
        """Six valid cells; those named carry the rule in the manifest key,
        the command and the env panel (end_turn_removed). Every cell in
        `counted_cells` carries truncated_episodes: zero, or `truncated` for
        the cells in `truncated_cells`."""
        verdict_tests.write_exam(self.exam)
        command_cells = rule_cells if command_cells is None else command_cells
        panel_cells = rule_cells if panel_cells is None else panel_cells
        for log in sorted(self.exam.rglob("*.log")):
            name = f"{log.parent.name}/{log.stem}"
            head, rest = log.read_text(encoding="utf-8").split("\n", 1)
            manifest = json.loads(head[len("BB_EVAL_MANIFEST "):])
            if rule_cells == "all" or name in rule_cells:
                manifest["no_early_end_turn"] = value
            if command_cells == "all" or name in command_cells:
                manifest["command"] += FLAG
            if panel_cells == "all" or name in panel_cells:
                rest = rest.replace('"n": ', f'"end_turn_removed": {removed}, "n": ')
            if counted_cells == "all" or name in counted_cells:
                cut = truncated if (truncated_cells == "all"
                                    or name in truncated_cells) else 0.0
                rest = rest.replace('"n": ', f'"truncated_episodes": {cut}, "n": ')
            log.write_text("BB_EVAL_MANIFEST " + json.dumps(manifest, sort_keys=True)
                           + "\n" + rest, encoding="utf-8")

    def run_tool(self, *extra):
        return subprocess.run(
            [sys.executable, str(VERDICT), "--exam-dir", str(self.exam),
             "--seeds", "42", "43", "--output-dir", str(self.out),
             "--rule", "none", *extra],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=60)

    def assert_no_verdict(self, result, message):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(message, result.stderr)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), [])

    def test_without_the_rule_the_verdict_has_the_keys_it_always_had(self):
        self.write()
        for extra in ((), ("--no-early-end-turn", "0")):
            for path in self.out.iterdir():
                path.unlink()
            result = self.run_tool(*extra)
            self.assertEqual(result.returncode, 0, result.stderr)
            verdict = json.loads((self.out / "EXAM_VERDICT.json").read_text())
            self.assertEqual(sorted(verdict), [
                "cells", "checkpoint_sha256", "exam_dir", "guard", "min_games",
                "pass", "rule", "schema_version", "seeds", "tool", "written_utc"])
            self.assertEqual(sorted(verdict["cells"][0]), [
                "bot_score", "bot_tds", "bot_team", "bot_type", "cell",
                "champion_score", "champion_tds", "champion_team", "checkpoint",
                "checkpoint_sha256", "games", "log", "num_threads", "seed"])

    def test_with_the_rule_the_verdict_and_every_cell_record_it(self):
        self.write(rule_cells="all")
        result = self.run_tool("--no-early-end-turn", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        verdict = json.loads((self.out / "EXAM_VERDICT.json").read_text())
        self.assertEqual(verdict["no_early_end_turn"], 1)
        self.assertEqual({cell["no_early_end_turn"] for cell in verdict["cells"]}, {1})
        self.assertEqual({cell["end_turn_removed"] for cell in verdict["cells"]},
                         {250.0})
        self.assertEqual({cell["truncated_episodes"] for cell in verdict["cells"]},
                         {0.0})

    def test_under_the_rule_one_cut_game_in_one_cell_is_no_verdict(self):
        # D416 amendment. One cell out of six is enough.
        self.write(rule_cells="all", truncated_cells=("s42/contact_home",))
        self.assert_no_verdict(
            self.run_tool("--no-early-end-turn", "1"),
            "s42/contact_home.log: truncated_episodes is 0.01")
        # The counter missing from one cell is a failure too, not a zero.
        cells = [f"s{seed}/{name}" for seed in (42, 43)
                 for name, _, _ in verdict_tests.CELLS]
        self.write(rule_cells="all", counted_cells=cells[:-1])
        self.assert_no_verdict(
            self.run_tool("--no-early-end-turn", "1"),
            "s43/offense_away.log: the panel has no truncated_episodes")

    def test_without_the_rule_cut_games_change_nothing(self):
        # A run that does not declare the rule is accepted as it always was:
        # with the counter absent (a build from before it), zero, or not zero.
        outcomes = []
        for kwargs in ({"counted_cells": ()}, {}, {"truncated_cells": "all"}):
            for path in self.out.iterdir():
                path.unlink()
            self.write(**kwargs)
            result = self.run_tool()
            self.assertEqual(result.returncode, 0, result.stderr)
            verdict = json.loads((self.out / "EXAM_VERDICT.json").read_text())
            self.assertNotIn("truncated_episodes", json.dumps(verdict))
            verdict.pop("written_utc")
            outcomes.append(verdict)
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[0], outcomes[2])

    def test_cells_and_stage_must_agree_in_both_directions(self):
        self.write(rule_cells="all")
        self.assert_no_verdict(
            self.run_tool(),
            "ran with no_early_end_turn on, the stage needs it off")
        self.write()
        self.assert_no_verdict(
            self.run_tool("--no-early-end-turn", "1"),
            "ran with no_early_end_turn off, the stage needs it on")
        # One cell out of six without the rule is still no verdict.
        cells = [f"s{seed}/{name}" for seed in (42, 43)
                 for name, _, _ in verdict_tests.CELLS]
        self.write(rule_cells=cells[:-1])
        self.assert_no_verdict(
            self.run_tool("--no-early-end-turn", "1"),
            "s43/offense_away.log: the cell ran with no_early_end_turn off")

    def test_the_env_panel_must_agree_with_the_manifest(self):
        # Asked for and recorded, but the env never removed END_TURN: an env
        # module from before the flag reads the kwarg as nothing.
        self.write(rule_cells="all", panel_cells=())
        self.assert_no_verdict(self.run_tool("--no-early-end-turn", "1"),
                               "the panel has no end_turn_removed")
        self.write(rule_cells="all", removed=0.0)
        self.assert_no_verdict(self.run_tool("--no-early-end-turn", "1"),
                               "the env never removed END_TURN")
        # The reverse: the env removed END_TURN in an exam that says it did not.
        self.write(rule_cells=(), command_cells=(), panel_cells="all")
        self.assert_no_verdict(self.run_tool(),
                               "but no_early_end_turn was not declared")
        # A flag-off exam on a build that has the counter reads zero and passes.
        self.write(rule_cells=(), command_cells=(), panel_cells="all", removed=0.0)
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("end_turn_removed",
                         (self.out / "EXAM_VERDICT.json").read_text())

    def test_a_manifest_whose_key_and_command_disagree_is_refused(self):
        self.write(rule_cells="all", command_cells=())
        self.assert_no_verdict(self.run_tool("--no-early-end-turn", "1"),
                               "disagrees with its command")
        self.write(rule_cells=(), command_cells="all")
        self.assert_no_verdict(self.run_tool(), "disagrees with its command")
        for value in (2, "1", True):
            self.write(rule_cells="all", value=value)
            self.assert_no_verdict(self.run_tool("--no-early-end-turn", "1"),
                                   "is not 0 or 1")


class PanelEvidenceTests(unittest.TestCase):
    """game_stats.no_early_end_turn_evidence_failure, and where it is used."""

    def test_the_panel_decides_whether_the_rule_was_in_force(self):
        from game_stats import no_early_end_turn_evidence_failure as failure
        # Off: zero, or a build from before the counter.
        self.assertIsNone(failure({"n": 2000.0, "end_turn_removed": 0.0}, False))
        self.assertIsNone(failure({"n": 2000.0}, False))
        self.assertIn("was not declared",
                      failure({"end_turn_removed": 0.004}, False))
        # On: strictly above zero, and present.
        self.assertIsNone(failure({"end_turn_removed": 112.5}, True))
        self.assertIn("predates the flag", failure({"n": 2000.0}, True))
        for bad in (0.0, 0, -1.0, float("nan"), float("inf"), True, "112"):
            self.assertIn("never removed END_TURN",
                          failure({"end_turn_removed": bad}, True), repr(bad))

    def test_cut_games_fail_only_a_run_that_declares_the_rule(self):
        from game_stats import no_early_end_turn_truncation_failure as failure
        self.assertIsNone(failure({"truncated_episodes": 0.0}, True))
        self.assertIsNone(failure({"truncated_episodes": 0}, True))
        self.assertIn("has no truncated_episodes", failure({"n": 2000.0}, True))
        for bad in (0.004, 1, -0.5, float("nan"), float("inf"), True, "0"):
            self.assertIn("accepted only with none",
                          failure({"truncated_episodes": bad}, True), repr(bad))
        # Undeclared: never judged, whatever the panel says.
        for panel in ({}, {"truncated_episodes": 0.0}, {"truncated_episodes": 0.3},
                      {"truncated_episodes": float("nan")}):
            self.assertIsNone(failure(panel, False), panel)

    def test_screen_acceptance_and_exam_verdict_both_apply_it(self):
        screen = SCREEN.read_text(encoding="utf-8")
        self.assertIn(
            'rule_declared = bool(ladder and ladder.get("no_early_end_turn"))\n'
            "for phase, metrics in phase_metrics.items():\n"
            "    reason = no_early_end_turn_evidence_failure(metrics, rule_declared)\n"
            "    if reason:\n"
            "        failures.append({\n"
            '            "phase": phase, "kind": "no_early_end_turn_evidence",\n',
            screen)
        self.assertIn(
            "    reason = no_early_end_turn_truncation_failure(metrics, rule_declared)\n"
            "    if reason:\n"
            "        failures.append({\n"
            '            "phase": phase, "kind": "no_early_end_turn_truncated_episodes",\n',
            screen)
        verdict = VERDICT.read_text(encoding="utf-8")
        self.assertIn("reason = no_early_end_turn_evidence_failure(values, rule_on)",
                      verdict)
        self.assertIn("reason = no_early_end_turn_truncation_failure(values, rule_on)",
                      verdict)

    def test_the_env_emits_the_counter_on_the_machine_panel(self):
        binding = (ROOT / "puffer/bloodbowl/binding.c").read_text(encoding="utf-8")
        self.assertIn('dict_set(out, "end_turn_removed", log->end_turn_removed);',
                      binding)
        # Not an integrity counter: it is above zero by design under the rule.
        from live_integrity_guard import HARD_INTEGRITY_KEYS
        self.assertNotIn("end_turn_removed", HARD_INTEGRITY_KEYS)


class ScreenAcceptanceTests(unittest.TestCase):
    """The screen's real acceptance step (materialize_result), run on a finished
    arm: a real trainer log, status, run manifest and final checkpoint."""

    FINAL_STEPS = 131072

    @classmethod
    def setUpClass(cls):
        source = SCREEN.read_text(encoding="utf-8")
        match = re.search(
            r'"\$MIN_TRAIN_GAMES" "\$MIN_EVAL_GAMES" "\$ARM_DETACH" <<\'PY\'\n(.*?)\nPY\n\}',
            source, re.S)
        assert match, "materialize_result heredoc not found"
        cls.block = match.group(1)
        from reward_manifest import load_manifest
        cls.reward = ROOT / "puffer/config/rewards/r0_poss_half.json"
        _, cls.reward_sha = load_manifest(cls.reward)

    def setUp(self):
        import checkpoint_lineage
        self.temp = tempfile.TemporaryDirectory()
        self.root, _, _ = rung_tests.stand_in_checkout(self.temp.name)
        self.run_dir = self.root / "vendor/PufferLib/checkpoints/bloodbowl/run1"
        self.run_dir.mkdir(parents=True)
        self.checkpoint = self.run_dir / f"{self.FINAL_STEPS:016d}.bin"
        with self.checkpoint.open("wb") as handle:
            handle.write(b"accepted arm")
            handle.truncate(checkpoint_lineage.EXPECTED_CHECKPOINT_BYTES)
        self.out = self.root / "screen"
        self.out.mkdir()
        self.log = self.out / "arm.log"
        self.result = self.out / "arm.result.json"
        self.build = {"source_sha256": "1" * 64, "compiled_module_sha256": "2" * 64,
                      "puffer_patch_bundle_sha256": "3" * 64}
        Path(str(self.log) + ".status.json").write_text(
            json.dumps({"exit_code": 0, "pid": 4321}))
        Path(str(self.log) + ".process.json").write_text(
            json.dumps({"pid": 4321, "process_group": 4321}))
        Path(str(self.log) + ".run_dir").write_text(str(self.run_dir) + "\n")
        Path(str(self.log) + ".manifest.json").write_text(json.dumps({
            "schema_version": 1, "mode": "native_static_pool_reward_ablation",
            "seed": "42", "observation_abi": "obs-v6", "observation_version": "6",
            "action_abi": "exact-joint-v1", "initialization": "lineage-v6",
            "qualification_only": "0", "policy_hidden_size": "512",
            "policy_num_layers": "3", "policy_expansion_factor": "1",
            "expected_checkpoint_bytes": str(checkpoint_lineage.EXPECTED_CHECKPOINT_BYTES),
            **self.build, "screen_manifest_sha256": "4" * 64,
            "warm_lineage_sha256": "5" * 64, "pool_lineage_bundle_sha256": "6" * 64,
            "reward_sha256": self.reward_sha, "final_steps": str(self.FINAL_STEPS),
        }, sort_keys=True) + "\n")

    def tearDown(self):
        self.temp.cleanup()

    def accept(self, *, declared, train=None, eval_=None, train_first=None):
        """Run acceptance. `train` and `eval_` are the extra panel metrics of
        the two phases; None leaves the phase without the two rule counters.
        `train_first` replaces them in the first of the two training intervals."""
        from live_integrity_guard import HARD_INTEGRITY_KEYS
        base = {"tds": 1.6, "perf": 0.6, "possession_rate": 0.4,
                "blocks_thrown": 9.0, "block_2d_frac": 0.5, "block_2dred_frac": 0.1,
                **{key: 0.0 for key in HARD_INTEGRITY_KEYS}}

        def panel(n, phase_eval, cumulative, final, extra):
            payload = {"_puffer_schema": 2, "_puffer_phase_eval": phase_eval,
                       "_puffer_env_cumulative": cumulative,
                       "_puffer_final_reprint": final, "n": float(n), **base,
                       **(extra or {})}
            return "PufferLib 4.0\nPUFFER_ENV_JSON " + json.dumps(payload) + "\n"

        clean = {"end_turn_removed": 120.0 if declared else 0.0,
                 "truncated_episodes": 0.0}
        train = clean if train == "clean" else train
        eval_ = clean if eval_ == "clean" else eval_
        train_first = clean if train_first == "clean" else (train_first or train)
        # Two training intervals: a cut game in one must not be averaged away.
        self.log.write_text(
            panel(500, 0, 0, 0, train_first)
            + panel(700, 0, 0, 0, train)
            + panel(6000, 1, 1, 0, eval_) + panel(12000, 1, 1, 0, eval_)
            + panel(12000, 1, 1, 1, eval_), encoding="utf-8")
        ladder = {"reset_pct": 0.0, "endzone_maxdist": 0}
        if declared:
            ladder["no_early_end_turn"] = 1
        manifest = self.out / "SCREEN_MANIFEST.json"
        manifest.write_text(json.dumps({"contract": {
            "final_steps": self.FINAL_STEPS, "qualification_only": False,
            "settings": {"expected_checkpoint_bytes": "16066560"},
            "implementation": self.build, "ladder": ladder}}))
        for stale in (self.result, Path(str(self.checkpoint) + ".lineage.json")):
            if stale.exists():
                stale.unlink()
        done = subprocess.run(
            [sys.executable, "-", str(self.root), "write", "r0_poss_half", "42", "arm",
             str(self.reward), str(self.log), str(self.result), str(manifest),
             "4" * 64, "1", "10000", "1"],
            input=self.block, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False, timeout=300)
        record = json.loads(self.result.read_text()) if self.result.exists() else None
        return done, record

    def assert_accepted(self, done, record):
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIs(record["acceptance_pass"], True)
        self.assertEqual(record["acceptance_failures"], [])
        self.assertTrue(Path(str(self.checkpoint) + ".lineage.json").exists())

    def assert_refused(self, done, record, phase, kind, message):
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("arm completed but failed screen acceptance", done.stderr)
        self.assertIs(record["acceptance_pass"], False)
        failures = [f for f in record["acceptance_failures"] if f["kind"] == kind]
        self.assertEqual([f["phase"] for f in failures], [phase], record)
        self.assertIn(message, failures[0]["reason"])
        # A refused arm publishes no lineage: it cannot warm-start anything.
        self.assertFalse(Path(str(self.checkpoint) + ".lineage.json").exists())

    def test_a_clean_rule_arm_is_accepted(self):
        self.assert_accepted(*self.accept(declared=True, train="clean", eval_="clean"))

    def test_a_cut_game_in_training_fails_a_rule_arm(self):
        # One game of 700 in the second interval; the first interval is clean.
        done, record = self.accept(
            declared=True, eval_="clean", train_first="clean",
            train={"end_turn_removed": 120.0, "truncated_episodes": 1 / 700})
        self.assert_refused(done, record, "train",
                            "no_early_end_turn_truncated_episodes",
                            "games were cut by the max_decisions cap")

    def test_a_cut_game_in_the_final_evaluation_fails_a_rule_arm(self):
        done, record = self.accept(
            declared=True, train="clean",
            eval_={"end_turn_removed": 120.0, "truncated_episodes": 1 / 12000})
        self.assert_refused(done, record, "eval",
                            "no_early_end_turn_truncated_episodes",
                            "games were cut by the max_decisions cap")

    def test_a_missing_counter_fails_a_rule_arm(self):
        for phase, kwargs in (
            ("train", {"train": {"end_turn_removed": 120.0}, "eval_": "clean"}),
            ("eval", {"train": "clean", "eval_": {"end_turn_removed": 120.0}}),
        ):
            done, record = self.accept(declared=True, **kwargs)
            self.assert_refused(done, record, phase,
                                "no_early_end_turn_truncated_episodes",
                                "the panel has no truncated_episodes")

    def test_an_arm_that_does_not_declare_the_rule_is_unaffected(self):
        # Counters absent (a build from before them), zero, or showing cut
        # games: acceptance is what it always was.
        cut = {"end_turn_removed": 0.0, "truncated_episodes": 0.02}
        for kwargs in ({"train": None, "eval_": None},
                       {"train": "clean", "eval_": "clean"},
                       {"train": cut, "eval_": cut}):
            self.assert_accepted(*self.accept(declared=False, **kwargs))


class EvalScriptTests(unittest.TestCase):
    def run_eval(self, **env):
        merged = {k: v for k, v in os.environ.items()
                  if not k.startswith("LADDER_")}
        merged.update(env)
        return subprocess.run(
            ["bash", str(EVAL), "missing.bin", "1", "unused.log"], cwd=ROOT,
            env=merged, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=60)

    def test_bad_values_are_refused_first(self):
        for bad in BAD_VALUES:
            result = self.run_eval(**{KNOB: bad})
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn(f"{KNOB} must be 0 or 1", result.stderr, bad)
        for good in ("0", "1", ""):
            result = self.run_eval(**{KNOB: good})
            self.assertNotIn(KNOB, result.stderr, good)
            self.assertIn("checkpoint not found", result.stderr, good)

    def test_command_and_manifest_change_only_when_the_rule_is_on(self):
        source = EVAL.read_text(encoding="utf-8")
        # The trainer flag is appended after both backends' commands, and only
        # under the knob.
        self.assertIn('if [ "$NO_EARLY_END_TURN" = "1" ]; then\n'
                      '  CMD+=(--env.no-early-end-turn 1)\nfi\n', source)
        self.assertEqual(source.count("--env.no-early-end-turn"), 1)
        # The manifest writer, run for real with and without the rule.
        match = re.search(r'"\$NO_EARLY_END_TURN" "\$\{CMD\[@\]\}" <<\'PY\' > "\$LOG"\n'
                          r"(.*?)\nPY\n", source, re.S)
        self.assertIsNotNone(match, "eval manifest heredoc not found")
        block = match.group(1).replace(
            "from run_reward_candidate_transfer import implementation_identity",
            "implementation_identity = lambda root: {'source_sha256': 's'}")

        def manifest(rule, *command):
            out = subprocess.run(
                ["python3", "-", str(ROOT), "/c.bin", "ab" * 32, "12000000", "42",
                 "1", "1", "2000", "2000", rule, *command],
                input=block, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, check=True, timeout=60)
            self.assertTrue(out.stdout.startswith("BB_EVAL_MANIFEST "))
            return json.loads(out.stdout[len("BB_EVAL_MANIFEST "):])

        command = ["puffer", "train", "bloodbowl", "--seed", "42"]
        off = manifest("0", *command)
        self.assertEqual(sorted(off), [
            "backend", "bot_team", "bot_type", "checkpoint", "checkpoint_sha256",
            "command", "eval_episodes", "min_eval_games", "mode",
            "requested_train_steps", "schema_version", "seed", "source_sha256"])
        self.assertEqual(off["command"], command)
        on = manifest("1", *command, *FLAG)
        self.assertEqual(on.pop("no_early_end_turn"), 1)
        self.assertEqual(on.pop("command"), command + FLAG)
        off.pop("command")
        self.assertEqual(on, off)

    def test_the_rule_needs_a_module_built_from_the_installed_source(self):
        source = EVAL.read_text(encoding="utf-8")
        self.assertIn('getattr(_C, "environment_source_hash", "<missing>")', source)
        self.assertIn("requires the compiled env module to be built from the "
                      "installed source", source)
        self.assertIn("its default must be 0", source)


class DocumentationTests(unittest.TestCase):
    def test_the_doc_says_what_the_rule_is_and_is_not(self):
        doc = (ROOT / "docs/no-early-end-turn-2026-10-05.md").read_text(
            encoding="utf-8")
        for phrase in ("not a Blood Bowl rule", "--mask chain54=m1", KNOB,
                       "GRAFT_FROM_SOURCE_SHA256", "probe_train_identity.py",
                       "end_turn_removed", "truncated_episodes"):
            self.assertIn(phrase, doc, phrase)
        self.assertNotIn("\u2014", doc)

    def test_the_runbook_quotes_the_rule_as_the_header_has_it(self):
        # The doc's code block is the header's two functions, verbatim.
        doc = (ROOT / "docs/no-early-end-turn-2026-10-05.md").read_text(
            encoding="utf-8")
        header = (ROOT / "puffer/bloodbowl/bloodbowl.h").read_text(encoding="utf-8")
        quoted = doc.split("```c\n", 1)[1].split("```", 1)[0]
        for function in quoted.strip().split("\n\n"):
            self.assertIn(function, header, function.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
