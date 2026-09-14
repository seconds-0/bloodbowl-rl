"""The backplay curriculum knobs must refuse every silent-no-op configuration.

These run the real launcher. The knob validation sits above the CUDA/venv
preflight precisely so it can be exercised off-box: a rejected configuration
exits with its own message, and an accepted one falls through to a later,
different failure. So each test asserts on the SPECIFIC message, never on the
exit status alone -- a test that only checked "non-zero" would pass for every
configuration on a machine with no GPU.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "tools" / "run_reward_ablation.sh"


def launcher_cmd_block() -> str:
    source = LAUNCHER.read_text(encoding="utf-8")
    match = re.search(
        r"\nCMD=\(env PUFFER_CUDA_RUNTIME_MANIFEST=.*?"
        r"--train\.eps 0\.000000000001\)\n", source, re.S)
    assert match, "launcher trainer command block not found"
    return match.group(0)


def render_trainer_argv(**values) -> list[str]:
    """Evaluate the launcher's real CMD=(...) block and return the trainer argv.

    Variables the block reads and the caller does not name render as empty
    strings, which is enough to locate a flag and the value beside it."""
    script = ("REWARD_ARGS=()\n"
              + "".join(f"{key}={shlex.quote(str(value))}\n"
                        for key, value in values.items())
              + launcher_cmd_block()
              + "printf '%s\\n' \"${CMD[@]}\"\n")
    out = subprocess.run(["bash", "-c", script], text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         check=True, timeout=60)
    return out.stdout.splitlines()


def render_run_manifest_pairs(**values) -> dict[str, str]:
    """Evaluate the launcher's real META_ARGS=(...) block and return the pairs
    the run-manifest writer turns into <log>.manifest.json keys."""
    source = LAUNCHER.read_text(encoding="utf-8")
    match = re.search(r"\nMETA_ARGS=\(\n.*?\n\)\n", source, re.S)
    assert match, "launcher run-manifest metadata block not found"
    script = ("".join(f"{key}={shlex.quote(str(value))}\n"
                      for key, value in values.items())
              + match.group(0)
              + "printf '%s\\n' \"${META_ARGS[@]}\"\n")
    out = subprocess.run(["bash", "-c", script], text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         check=True, timeout=60)
    pairs = out.stdout.split("\n")[:-1]
    assert len(pairs) % 2 == 0, "run-manifest metadata pairs misaligned"
    return dict(zip(pairs[::2], pairs[1::2]))


def run(**knobs) -> subprocess.CompletedProcess:
    # Scrub every launcher knob so an operator's shell cannot leak into a test.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("LADDER_", "SCRIPTED_", "GRAFT_"))
           and k not in ("WARM", "POOL", "BOOTSTRAP_MODE", "EXPECTED_POOL_HASH",
                         "TAG", "REWARD_MANIFEST", "STEPS", "SEED",
                         "NUM_FROZEN_BANKS", "FROZEN_BANK_PCT",
                         "GAMMA", "GAE_LAMBDA", "REPLAY_RATIO")}
    # Enough to get past the required-variable checks and reach the knobs.
    env.setdefault("TAG", "ladder-knob-test")
    env.setdefault("REWARD_MANIFEST", str(ROOT / "puffer/config/rewards/s0_both.json"))
    env.setdefault("BOOTSTRAP_MODE", "fresh-v6-genesis")
    env.setdefault("STEPS", "1000000")
    for key, value in knobs.items():
        env[key] = str(value)
    return subprocess.run(
        ["bash", str(LAUNCHER)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )


def pool_run(**knobs) -> subprocess.CompletedProcess:
    # lineage-v6 with every required input named, so the run reaches the knob
    # gates instead of stopping at "WARM is required".
    base = dict(BOOTSTRAP_MODE="lineage-v6", WARM="missing.bin",
                POOL="missing-pool", EXPECTED_POOL_HASH="0" * 64)
    base.update(knobs)
    return run(**base)


class LadderKnobTests(unittest.TestCase):
    def test_selector_without_reset_pct_is_refused_as_a_no_op(self):
        # The whole failure mode: a maxdist with reset_pct 0 means the env never
        # draws a banked state, so the "curriculum" run is a kickoff run.
        out = run(LADDER_ENDZONE_MAXDIST=6, LADDER_RESET_PCT=0).stdout
        self.assertIn("selector is a no-op", out)

    def test_two_selectors_are_refused_because_the_env_applies_only_the_first(self):
        out = run(
            LADDER_ENDZONE_MAXDIST=6,
            LADDER_PASS_MAXRANGE=6,
            LADDER_RESET_PCT="0.5",
        ).stdout
        self.assertIn("only one curriculum selector", out)

    def test_reset_pct_out_of_range_is_refused(self):
        out = run(LADDER_RESET_PCT="1.5").stdout
        self.assertIn("must be a fraction in [0,1]", out)

    def test_non_integer_selector_is_refused(self):
        out = run(LADDER_ENDZONE_MAXDIST="six", LADDER_RESET_PCT="0.5").stdout
        self.assertIn("must be a non-negative integer", out)

    def test_reset_pct_without_a_staged_bank_is_refused(self):
        # A Mac checkout has no staged bank, so this exercises the real path.
        bank = ROOT / "vendor/PufferLib/resources/bloodbowl/state_bank.bbs"
        if bank.exists():
            self.skipTest("this checkout has a staged bank; covered on the box")
        out = run(LADDER_RESET_PCT="0.5", LADDER_ENDZONE_MAXDIST=6).stdout
        self.assertIn("requires a staged state bank", out)

    def test_the_default_configuration_passes_the_knob_gate(self):
        # With no knobs set the run must reach a LATER failure, never a knob
        # complaint -- otherwise this change would have broken every ordinary
        # non-ladder arm.
        out = run().stdout
        for message in (
            "selector is a no-op",
            "only one curriculum selector",
            "must be a fraction in [0,1]",
            "must be a non-negative integer",
            "requires a staged state bank",
        ):
            self.assertNotIn(message, out, f"default config tripped: {message}")


class ScriptedBankKnobTests(unittest.TestCase):
    """SCRIPTED_BANK_TAG / SCRIPTED_BOT_TYPE: native training against a bot.

    The bot is only excluded from PPO when it sits in a frozen bank's row
    slice, so the knob is refused outside the pool-backed bootstrap mode, and
    every malformed value is refused before any preflight. Both knobs are
    recorded explicitly (0 is a value, not an omission)."""

    def test_default_zero_passes_the_gate(self):
        out = run().stdout
        self.assertNotIn("SCRIPTED_BANK_TAG", out)
        self.assertNotIn("SCRIPTED_BOT_TYPE", out)

    def test_tag_out_of_range_is_refused(self):
        # Default NUM_FROZEN_BANKS=4. One digit only, so '01' never aliases 1.
        for value in ("5", "9", "-1", "x", "1.0", "01"):
            out = run(SCRIPTED_BANK_TAG=value).stdout
            self.assertIn("SCRIPTED_BANK_TAG must be an integer in 0..4", out, value)

    def test_tag_domain_follows_the_bank_count(self):
        # The screen accepts 0..NUM_FROZEN_BANKS; a launcher still pinned to
        # 0..4 refused the staged chain 23 (tag 8 at 8 banks) before training,
        # after the PLAN_ONLY preflight had already verified the screen plan.
        for banks, value in (("4", "5"), ("1", "2"), ("7", "8"), ("8", "9"),
                             ("8", "08"), ("8", "10")):
            out = pool_run(SCRIPTED_BANK_TAG=value, NUM_FROZEN_BANKS=banks).stdout
            self.assertIn(f"SCRIPTED_BANK_TAG must be an integer in 0..{banks}",
                          out, (banks, value))

    def test_every_tag_up_to_the_bank_count_passes_the_gate(self):
        vendored = (ROOT / "vendor/PufferLib/.venv/bin/python").exists()
        for banks in ("1", "4", "8"):
            for tag in range(int(banks) + 1):
                out = pool_run(SCRIPTED_BANK_TAG=tag, NUM_FROZEN_BANKS=banks).stdout
                self.assertNotIn("SCRIPTED_BANK_TAG", out, (banks, tag))
                self.assertNotIn("NUM_FROZEN_BANKS must", out, (banks, tag))
                if not vendored:
                    self.assertIn("vendored Python missing", out, (banks, tag))

    def test_chain23_knobs_pass_the_launcher_gates(self):
        # The knob set /home/rache/r0chain23.sh exports, as the screen hands it
        # to this launcher. Off-box the run must reach the vendored-Python
        # preflight, i.e. clear every env gate above it.
        out = pool_run(NUM_FROZEN_BANKS=8, SCRIPTED_BANK_TAG=8, SCRIPTED_BOT_TYPE=0,
                       FROZEN_BANK_PCT="0.06", STEPS="3000000000", SEED=42).stdout
        self.assertNotIn("SCRIPTED_BANK_TAG", out)
        self.assertNotIn("SCRIPTED_BOT_TYPE", out)
        self.assertNotIn("NUM_FROZEN_BANKS must", out)
        self.assertNotIn("requires BOOTSTRAP_MODE", out)
        if (ROOT / "vendor/PufferLib/.venv/bin/python").exists():
            self.skipTest("vendored Python present; the later preflight differs")
        self.assertIn("vendored Python missing", out)

    def test_invalid_bank_count_is_refused_before_the_tag(self):
        out = pool_run(NUM_FROZEN_BANKS=9, SCRIPTED_BANK_TAG=1).stdout
        self.assertIn("NUM_FROZEN_BANKS must be an integer in 1..8", out)
        self.assertNotIn("SCRIPTED_BANK_TAG must", out)

    def test_bot_type_out_of_range_is_refused(self):
        for value in ("2", "-1", "contact", "0 "):
            out = run(SCRIPTED_BOT_TYPE=value).stdout
            self.assertIn("SCRIPTED_BOT_TYPE must be 0 (contact) or 1 (offense)",
                          out, value)

    def test_tag_requires_the_pool_backed_bootstrap_mode(self):
        # fresh-v6-genesis has no frozen banks: nowhere to hide the bot's rows.
        out = run(SCRIPTED_BANK_TAG="1").stdout
        self.assertIn("requires BOOTSTRAP_MODE=lineage-v6", out)
        # lineage-v6 gets past the knob gate and fails LATER on missing inputs.
        out = run(SCRIPTED_BANK_TAG="1", BOOTSTRAP_MODE="lineage-v6",
                  WARM="missing.bin", POOL="missing-pool",
                  EXPECTED_POOL_HASH="0" * 64).stdout
        self.assertNotIn("SCRIPTED_BANK_TAG", out)
        self.assertNotIn("requires BOOTSTRAP_MODE", out)

    def test_launcher_passes_the_flags_and_records_the_knobs(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        # Flags only in the pool-backed branch, and only when the tag is set;
        # tag 0 leaves the installed config default (scripted_opponent = 0).
        self.assertIn('if [ "$SCRIPTED_BANK_TAG" != "0" ]; then\n'
                      '    # Team 1 (AWAY)', source)
        self.assertIn('--env.scripted-opponent 1', source)
        self.assertIn('--env.scripted-opponent-type "$SCRIPTED_BOT_TYPE"', source)
        self.assertIn('--env.scripted-opponent-team 1', source)
        self.assertIn('--env.scripted-bank-tag "$SCRIPTED_BANK_TAG"', source)
        self.assertNotIn('--env.scripted-opponent 0', source)
        # Explicit record in the run manifest, unconditionally.
        self.assertIn('scripted_bank_tag "$SCRIPTED_BANK_TAG"', source)
        self.assertIn('scripted_bot_type "$SCRIPTED_BOT_TYPE"', source)
        # And in the launch banner.
        self.assertIn('echo "scripted_bank_tag=$SCRIPTED_BANK_TAG '
                      'scripted_bot_type=$SCRIPTED_BOT_TYPE"', source)


# Junk the horizon knobs must refuse at every layer: out of (0,1), not a plain
# decimal, or finer than six decimals.
BAD_HORIZON_VALUES = ("1", "1.0", "0", "0.0", "0.000", ".99", "0.99x", "9.9e-1",
                      "nan", "inf", "-0.5", "0.99 ", " 0.99", "0,99", "0.9999999")


class HorizonKnobTests(unittest.TestCase):
    """GAMMA / GAE_LAMBDA reach --train.gamma / --train.gae-lambda verbatim.

    The rung screen sets them from LADDER_GAMMA / LADDER_GAE_LAMBDA for a
    horizon arm. This launcher is the last gate before the trainer argv, so a
    malformed value is refused here, before any preflight, with its own
    message. That the screen's effective values reach the argv is covered end
    to end in tools/test_ladder_rung_profile.py."""

    def test_gamma_and_gae_lambda_are_validated_before_preflight(self):
        for knob in ("GAMMA", "GAE_LAMBDA"):
            for value in BAD_HORIZON_VALUES:
                out = run(**{knob: value}).stdout
                self.assertIn(
                    f"{knob} must be a decimal in (0,1) with at most six decimals",
                    out, (knob, value))
        vendored = (ROOT / "vendor/PufferLib/.venv/bin/python").exists()
        for gamma, lam in (("0.995", "0.85"), ("0.999", "0.95"),
                           ("0.9", "0.999999")):
            out = run(GAMMA=gamma, GAE_LAMBDA=lam).stdout
            self.assertNotIn("must be a decimal in (0,1)", out, (gamma, lam))
            if not vendored:
                self.assertIn("vendored Python missing", out, (gamma, lam))


# The update-budget knob's domain at every layer. The native trainer runs
# int(replay_ratio * batch / minibatch) minibatches per epoch
# (vendor/PufferLib/src/pufferlib.cu, total_minibatches), and the fixed contract
# batch is 2048 agents x horizon 64 = 131072 with minibatch 16384, so a ratio
# is exact only as a multiple of 0.125.
BAD_REPLAY_RATIO_VALUES = ("0", "0.0", "0.000", "4.001", "4.5", "5", "10", ".5",
                           "1.", "01", "1.0000", "0.0625", "1e0", "nan", "inf",
                           "-1", "1 ", " 1", "1,0", "0.25x")
TRUNCATING_REPLAY_RATIO_VALUES = ("0.1", "0.2", "0.3", "0.333", "0.9", "0.999",
                                  "1.1", "3.99")
# (value, whole minibatches per epoch under the fixed contract)
GOOD_REPLAY_RATIO_VALUES = (("0.125", 1), ("0.25", 2), ("0.5", 4), ("1", 8),
                            ("1.0", 8), ("2.375", 19), ("4", 32), ("4.000", 32))


class ReplayRatioKnobTests(unittest.TestCase):
    """REPLAY_RATIO reaches --train.replay-ratio verbatim, and the trainer
    truncates its minibatch count toward zero: 0.3 would train as 0.25 and 0.1
    would train nothing, under a label that says otherwise. This launcher is
    the last gate before the trainer argv, so it refuses both a malformed ratio
    and one whose count is not whole, before any preflight. That the rung
    screen's LADDER_REPLAY_RATIO reaches the argv is covered end to end in
    tools/test_ladder_rung_profile.py."""

    def test_malformed_or_out_of_range_ratio_is_refused_before_preflight(self):
        for value in BAD_REPLAY_RATIO_VALUES:
            out = run(REPLAY_RATIO=value).stdout
            self.assertIn(
                "REPLAY_RATIO must be a decimal in (0,4] with at most three decimals",
                out, value)
            self.assertNotIn("vendored Python missing", out, value)

    def test_truncating_ratio_is_refused_before_preflight(self):
        for value in TRUNCATING_REPLAY_RATIO_VALUES:
            out = run(REPLAY_RATIO=value).stdout
            self.assertIn(
                f"REPLAY_RATIO={value} does not give a whole number of minibatches "
                f"per epoch ({value} x 131072 / 16384)", out, value)
            self.assertNotIn("must be a decimal in (0,4]", out, value)
            self.assertNotIn("vendored Python missing", out, value)

    def test_exact_ratios_pass_the_gate(self):
        vendored = (ROOT / "vendor/PufferLib/.venv/bin/python").exists()
        for value, _ in GOOD_REPLAY_RATIO_VALUES:
            out = run(REPLAY_RATIO=value).stdout
            self.assertNotIn("REPLAY_RATIO", out, value)
            if not vendored:
                self.assertIn("vendored Python missing", out, value)

    def test_the_count_follows_the_batch_and_minibatch_it_is_launched_with(self):
        # Not a hardcoded 0.125 grid: at minibatch 32768 the batch holds four
        # minibatches, so 0.25 gives one and 0.125 gives half of one.
        vendored = (ROOT / "vendor/PufferLib/.venv/bin/python").exists()
        out = run(REPLAY_RATIO="0.125", MINIBATCH_SIZE="32768").stdout
        self.assertIn("REPLAY_RATIO=0.125 does not give a whole number of "
                      "minibatches per epoch (0.125 x 131072 / 32768)", out)
        out = run(REPLAY_RATIO="0.25", MINIBATCH_SIZE="32768").stdout
        self.assertNotIn("REPLAY_RATIO", out)
        if not vendored:
            self.assertIn("vendored Python missing", out)


if __name__ == "__main__":
    unittest.main()
