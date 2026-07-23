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
    env.setdefault("BOOTSTRAP_MODE", "fresh-v5-genesis")
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


if __name__ == "__main__":
    unittest.main()
