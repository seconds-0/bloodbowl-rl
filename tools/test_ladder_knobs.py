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
    for key in (
        "LADDER_STATE_BANK_KIND",
        "EXPECTED_LADDER_STATE_BANK_SHA256",
        "EXPECTED_LADDER_STATE_BANK_PRODUCER_MANIFEST_SHA256",
        "EXPECTED_LADDER_STATE_BANK_CONTRACT_SHA256",
    ):
        env.pop(key, None)
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
    def assert_refused(
        self,
        result: subprocess.CompletedProcess,
        message: str,
    ) -> None:
        self.assertNotEqual(
            result.returncode,
            0,
            f"launcher warned but continued: {result.stdout}",
        )
        self.assertIn(message, result.stdout)

    def test_selector_without_reset_pct_is_refused_as_a_no_op(self):
        # The whole failure mode: a maxdist with reset_pct 0 means the env never
        # draws a banked state, so the "curriculum" run is a kickoff run.
        result = run(LADDER_ENDZONE_MAXDIST=6, LADDER_RESET_PCT=0)
        self.assert_refused(result, "selector is a no-op")

    def test_two_selectors_are_refused_as_ambiguous(self):
        result = run(
            LADDER_ENDZONE_MAXDIST=6,
            LADDER_PASS_MAXRANGE=6,
            LADDER_RESET_PCT="0.5",
        )
        self.assert_refused(result, "only one curriculum selector")

    def test_reset_pct_out_of_range_is_refused(self):
        result = run(LADDER_RESET_PCT="1.5")
        self.assert_refused(result, "must be a fraction in [0,1]")

    def test_reset_pct_with_numeric_prefix_and_junk_is_refused(self):
        result = run(LADDER_RESET_PCT="0.5oops")
        self.assert_refused(result, "must be a fraction in [0,1]")

    def test_decimal_zero_uses_the_inactive_contract(self):
        result = run(LADDER_RESET_PCT="0.00")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(
            "LADDER_STATE_BANK_KIND is required", result.stdout
        )

    def test_zero_reset_rejects_bank_authority_variables(self):
        result = run(
            LADDER_RESET_PCT="0",
            LADDER_STATE_BANK_KIND="strict-replay",
            EXPECTED_LADDER_STATE_BANK_SHA256="1" * 64,
            EXPECTED_LADDER_STATE_BANK_PRODUCER_MANIFEST_SHA256="2" * 64,
            EXPECTED_LADDER_STATE_BANK_CONTRACT_SHA256="3" * 64,
        )
        self.assert_refused(
            result,
            "state-bank authority variables require LADDER_RESET_PCT > 0",
        )

    def test_non_integer_selector_is_refused(self):
        result = run(
            LADDER_ENDZONE_MAXDIST="six", LADDER_RESET_PCT="0.5"
        )
        self.assert_refused(
            result, "must be a canonical non-negative integer"
        )

    def test_selector_rejects_noncanonical_leading_zero(self):
        result = run(
            LADDER_ENDZONE_MAXDIST="00", LADDER_RESET_PCT="0.5"
        )
        self.assert_refused(
            result, "must be a canonical non-negative integer"
        )

    def test_selector_rejects_value_larger_than_signed_c_int(self):
        result = run(
            LADDER_ENDZONE_MAXDIST="9" * 100,
            LADDER_RESET_PCT="0.5",
        )
        self.assert_refused(result, "must be at most 2147483647")
        self.assertNotIn("integer expression expected", result.stdout)

    def test_each_selector_rejects_its_first_out_of_range_value(self):
        for knob, value, maximum in (
            ("LADDER_ENDZONE_MAXDIST", 26, 25),
            ("LADDER_PICKUP_MAXDIST", 26, 25),
            ("LADDER_POSTKICK_MAXTURN", 9, 8),
            ("LADDER_PASS_MAXRANGE", 26, 25),
        ):
            with self.subTest(knob=knob):
                result = run(LADDER_RESET_PCT="0.5", **{knob: value})
                self.assert_refused(
                    result, f"{knob} must be at most {maximum}"
                )

    def test_reset_pct_without_external_authority_is_refused(self):
        # Artifact presence is not authority: the operator must supply the
        # independently reviewed kind and all three pins.
        result = run(
            LADDER_RESET_PCT="0.5", LADDER_ENDZONE_MAXDIST=6
        )
        self.assert_refused(result, "LADDER_STATE_BANK_KIND is required")

    def test_valid_selector_reaches_installed_contract_validation(self):
        launcher = LAUNCHER.read_text(encoding="utf-8")
        validate_call = launcher.split(" validate-installed \\", 1)[1]
        validate_call = validate_call.split(')" || exit $?', 1)[0]
        self.assertIn("--selector-family", validate_call)
        self.assertIn("--selector-threshold", validate_call)
        result = run(
            LADDER_RESET_PCT="0.5",
            LADDER_ENDZONE_MAXDIST=6,
            LADDER_STATE_BANK_KIND="strict-replay",
            EXPECTED_LADDER_STATE_BANK_SHA256="1" * 64,
            EXPECTED_LADDER_STATE_BANK_PRODUCER_MANIFEST_SHA256="2" * 64,
            EXPECTED_LADDER_STATE_BANK_CONTRACT_SHA256="3" * 64,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(
            "state-bank selectors require the reviewed pre-indexed-strata tranche",
            result.stdout,
        )
        self.assertIn("state-bank contract failed:", result.stdout)

    def test_the_default_configuration_passes_the_knob_gate(self):
        # With no knobs set the run must reach a LATER failure, never a knob
        # complaint -- otherwise this change would have broken every ordinary
        # non-ladder arm.
        result = run()
        self.assertNotEqual(
            result.returncode,
            0,
            "default config unexpectedly launched or returned success",
        )
        self.assertTrue(
            result.stdout.strip(),
            "default config did not reach a diagnosable later preflight",
        )
        for message in (
            "selector is a no-op",
            "only one curriculum selector",
            "must be a fraction in [0,1]",
            "must be a non-negative integer",
            "LADDER_STATE_BANK_KIND is required",
        ):
            self.assertNotIn(
                message,
                result.stdout,
                f"default config tripped: {message}",
            )


if __name__ == "__main__":
    unittest.main()
