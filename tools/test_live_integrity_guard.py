import json
import math
import tempfile
import unittest
from pathlib import Path

from tools import live_integrity_guard as guard


def panel(**overrides):
    values = {key: 0.0 for key in guard.HARD_INTEGRITY_KEYS}
    values.update({
        "_puffer_schema": 2,
        "_puffer_agent_steps": 131072.0,
    })
    values.update(overrides)
    return "PUFFER_ENV_JSON " + json.dumps(values, allow_nan=True) + "\n"


class LiveIntegrityGuardTests(unittest.TestCase):
    def run_guard(self, root, text, *, append=False):
        log = Path(root) / "arm.log"
        state = Path(root) / "guard-state.json"
        failure = Path(root) / "guard-failure.json"
        with log.open("a" if append else "w", encoding="utf-8") as stream:
            stream.write(text)
        return guard.check_log(log, state, failure), state, failure

    def test_clean_panels_advance_incrementally_without_reparsing(self):
        with tempfile.TemporaryDirectory() as root:
            first, state, failure = self.run_guard(root, panel())
            self.assertEqual(first.new_panels, 1)
            self.assertEqual(first.total_panels, 1)
            self.assertFalse(failure.exists())

            second, _, _ = self.run_guard(root, panel(
                _puffer_agent_steps=262144.0), append=True)
            self.assertEqual(second.new_panels, 1)
            self.assertEqual(second.total_panels, 2)
            saved = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(saved["latest_agent_steps"], 262144.0)

    def test_partial_line_is_not_consumed_until_complete(self):
        with tempfile.TemporaryDirectory() as root:
            complete = panel()
            split = len(complete) // 2
            first, state, _ = self.run_guard(root, complete[:split])
            self.assertEqual(first.new_panels, 0)
            self.assertEqual(json.loads(state.read_text())["offset"], 0)

            second, _, _ = self.run_guard(root, complete[split:], append=True)
            self.assertEqual(second.new_panels, 1)
            self.assertEqual(second.total_panels, 1)

    def test_nonzero_hard_counter_fails_with_atomic_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(guard.IntegrityFailure, "illegal_frac"):
                self.run_guard(root, panel(illegal_frac=1e-12))
            failure = json.loads(
                (Path(root) / "guard-failure.json").read_text(encoding="utf-8"))
            self.assertEqual(failure["kind"], "hard_integrity_nonzero")
            self.assertEqual(failure["metrics"], {"illegal_frac": 1e-12})

    def test_missing_nonfinite_and_malformed_panels_fail_closed(self):
        cases = []
        missing = json.loads(panel().split(" ", 1)[1])
        del missing[guard.HARD_INTEGRITY_KEYS[0]]
        cases.append(("missing", "PUFFER_ENV_JSON " + json.dumps(missing) + "\n"))
        cases.append(("non-finite", panel(illegal_frac=math.nan)))
        cases.append(("malformed", "PUFFER_ENV_JSON {nope}\n"))
        for label, text in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as root:
                with self.assertRaises(guard.IntegrityFailure):
                    self.run_guard(root, text)
                self.assertTrue((Path(root) / "guard-failure.json").is_file())

    def test_log_replacement_or_truncation_fails_closed(self):
        for mode in ("replace", "truncate"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                self.run_guard(root, panel())
                log = Path(root) / "arm.log"
                if mode == "replace":
                    old = Path(root) / "old.log"
                    log.replace(old)
                    log.write_text(panel(), encoding="utf-8")
                else:
                    log.write_text("", encoding="utf-8")
                with self.assertRaises(guard.IntegrityFailure):
                    guard.check_log(
                        log,
                        Path(root) / "guard-state.json",
                        Path(root) / "guard-failure.json",
                    )

    def test_missing_machine_panels_exhausts_liveness_budget(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            log = root / "arm.log"
            state = root / "guard-state.json"
            failure = root / "guard-failure.json"
            log.write_text("trainer startup\n", encoding="utf-8")
            first = guard.check_log(
                log, state, failure, max_panel_silence_seconds=60, now=100)
            self.assertEqual(first.total_panels, 0)
            with self.assertRaisesRegex(
                    guard.IntegrityFailure, "no complete machine integrity panel"):
                guard.check_log(
                    log, state, failure,
                    max_panel_silence_seconds=60, now=161)
            payload = json.loads(failure.read_text(encoding="utf-8"))
            self.assertEqual(payload["kind"], "panel_liveness_exhausted")

    def test_completed_log_rescan_ignores_silence_but_live_mode_does_not(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            log = root / "arm.log"
            state = root / "guard-state.json"
            failure = root / "guard-failure.json"
            log.write_text(panel(), encoding="utf-8")
            guard.check_log(log, state, failure, now=1.0)

            result = guard.check_log(
                log, state, failure, now=10_000.0, enforce_liveness=False)
            self.assertEqual(result.new_panels, 0)
            self.assertEqual(result.total_panels, 1)
            self.assertFalse(failure.exists())

            with self.assertRaisesRegex(
                    guard.IntegrityFailure,
                    "no complete machine integrity panel"):
                guard.check_log(log, state, failure, now=10_000.0)

    def test_metadata_only_panel_is_consumed_without_resetting_liveness(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            log = root / "arm.log"
            state = root / "guard-state.json"
            failure = root / "guard-failure.json"
            metadata = {
                "_puffer_schema": 2,
                "_puffer_agent_steps": 0.0,
                "_puffer_phase_eval": 0,
            }
            log.write_text(
                "PUFFER_ENV_JSON " + json.dumps(metadata) + "\n",
                encoding="utf-8",
            )
            result = guard.check_log(log, state, failure, now=100.0)
            self.assertEqual(result.new_panels, 0)
            self.assertEqual(result.total_panels, 0)
            self.assertFalse(failure.exists())

            with self.assertRaisesRegex(
                    guard.IntegrityFailure,
                    "no complete machine integrity panel"):
                guard.check_log(log, state, failure, now=281.0)

    def test_completed_log_rejects_unterminated_tail(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            log = root / "arm.log"
            state = root / "guard-state.json"
            failure = root / "guard-failure.json"
            log.write_text(panel() + "PUFFER_ENV_JSON {", encoding="utf-8")
            with self.assertRaisesRegex(
                    guard.IntegrityFailure, "unterminated final log record"):
                guard.check_log(
                    log, state, failure, now=1.0, enforce_liveness=False)
            payload = json.loads(failure.read_text(encoding="utf-8"))
            self.assertEqual(payload["kind"], "log_incomplete_tail")


if __name__ == "__main__":
    unittest.main()
