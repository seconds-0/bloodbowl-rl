"""Source-level guards for every legacy state-bank launch/transfer path."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class StateBankMigrationTests(unittest.TestCase):
    def test_selector_wrappers_are_retired_before_any_delegate(self):
        for relative in (
            "tools/launch_ladder_canary.sh",
            "tools/launch_ladder_rung.sh",
        ):
            text = source(relative)
            with self.subTest(path=relative):
                for variable in (
                    "LADDER_STATE_BANK_KIND",
                    "EXPECTED_LADDER_STATE_BANK_SHA256",
                    "EXPECTED_LADDER_STATE_BANK_PRODUCER_MANIFEST_SHA256",
                    "EXPECTED_LADDER_STATE_BANK_CONTRACT_SHA256",
                ):
                    self.assertIn(f"${{{variable}:?", text)
                retirement = text.index("retired:")
                stop = text.index("exit 2", retirement)
                delegate = text.index('bash "$C/tools/run_reward_ablation.sh"')
                self.assertLess(stop, delegate)
                self.assertIn(
                    "use tools/run_reward_ablation.sh with complete typed "
                    "state-bank authority",
                    text,
                )
                self.assertNotIn(
                    'sha256sum "$C/vendor/PufferLib/resources/bloodbowl/'
                    'state_bank.bbs"',
                    text,
                )

    def test_selector_wrapper_tombstones_have_no_local_side_effects(self):
        for relative in (
            "tools/launch_ladder_canary.sh",
            "tools/launch_ladder_rung.sh",
        ):
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as tmp:
                absent_checkout = Path(tmp) / "checkout-that-must-stay-absent"
                environment = dict(os.environ)
                environment["C"] = str(absent_checkout)
                result = subprocess.run(
                    ["bash", str(ROOT / relative)],
                    cwd=tmp,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn("retired:", result.stdout)
                self.assertIn(
                    "use tools/run_reward_ablation.sh with complete typed "
                    "state-bank authority",
                    result.stdout,
                )
                self.assertIn(
                    "no checkout was inspected and no Puffer process was started",
                    result.stdout,
                )
                self.assertFalse(absent_checkout.exists())
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_legacy_positive_reset_launchers_hard_fail_before_puffer(self):
        for relative in (
            "tools/run_synthesis_c.sh",
            "tools/run_native_asym.sh",
        ):
            text = source(relative)
            with self.subTest(path=relative):
                diagnostic = text.index("legacy raw state bank has no typed")
                stop = text.index("exit 2", diagnostic)
                launch = text.index("puffer train")
                self.assertLess(stop, launch)
                self.assertIn("no Puffer process was started", text)

    def test_setup_arm_never_transfers_a_raw_bank(self):
        text = source("tools/setup_arm.sh")
        self.assertNotIn("validation/states/bank.bbs", text)
        self.assertNotIn("resources/bloodbowl/state_bank.bbs", text)
        self.assertIn("pulling corpus + anchor", text)

    def test_setup_arm_stops_before_provisioning_or_remote_work(self):
        text = source("tools/setup_arm.sh")
        diagnostic = text.index("typed state-bank migration")
        stop = text.index("exit 2", diagnostic)
        for operation in ("vastai show instances", 'tools/fleet.sh"', "ssh -i"):
            with self.subTest(operation=operation):
                self.assertLess(stop, text.index(operation))
        self.assertIn("no instance was provisioned or contacted", text)

    def test_remote_setup_relies_on_explicit_no_bank_install(self):
        fleet = source("tools/fleet.sh")
        setup = source("tools/gpu_box_setup.sh")
        self.assertNotIn("state_bank.bbs", fleet)
        self.assertNotIn("state_bank.bbs", setup)
        self.assertIn('bash "$ROOT/tools/install_puffer_env.sh"', setup)

    def test_default_config_declares_no_bank_kind(self):
        config = source("puffer/config/bloodbowl.ini")
        self.assertIn("demo_reset_pct = 0.0", config)
        self.assertIn("state_bank_kind = 0", config)

    def test_primary_launcher_emits_complete_conditional_contract(self):
        text = source("tools/run_reward_ablation.sh")
        self.assertIn(
            '--env.state-bank-kind "$LADDER_STATE_BANK_KIND_VALUE"', text)
        for field in (
            "ladder_state_bank_contract_schema",
            "ladder_state_bank_producer_schema",
            "ladder_state_bank_kind",
            "ladder_state_bank_ruleset",
            "ladder_state_bank_sha256",
            "ladder_state_bank_producer_manifest_sha256",
            "ladder_state_bank_contract_sha256",
            "ladder_state_bank_producer_engine_source_sha256",
            "ladder_state_bank_loader_engine_source_sha256",
            "ladder_state_bank_records",
            "ladder_state_bank_bytes",
            "ladder_state_bank_strata_schema",
            "ladder_state_bank_strata_family",
            "ladder_state_bank_strata_threshold",
            "ladder_state_bank_strata_eligible_records",
            "ladder_state_bank_strata_sha256",
        ):
            self.assertIn(field, text)
        conversion = text.split(
            "manifest = dict(zip(pairs[::2], pairs[1::2]))", 1
        )[1].split("manifest.update({", 1)[0]
        for field in (
            "ladder_state_bank_records",
            "ladder_state_bank_bytes",
            "ladder_state_bank_strata_threshold",
            "ladder_state_bank_strata_eligible_records",
        ):
            self.assertIn(f'"{field}"', conversion)


if __name__ == "__main__":
    unittest.main()
