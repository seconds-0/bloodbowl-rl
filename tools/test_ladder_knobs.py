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
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "tools" / "run_reward_ablation.sh"


def run(**knobs) -> subprocess.CompletedProcess:
    env = dict(os.environ)
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
        for value in ("5", "-1", "x", "1.0", "01"):
            out = run(SCRIPTED_BANK_TAG=value).stdout
            self.assertIn("SCRIPTED_BANK_TAG must be an integer in 0..4", out, value)

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


if __name__ == "__main__":
    unittest.main()
