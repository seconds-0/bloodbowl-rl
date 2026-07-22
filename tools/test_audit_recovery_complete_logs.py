#!/usr/bin/env python3

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/audit_recovery_complete_logs.py"
SPEC = importlib.util.spec_from_file_location("audit_recovery_complete_logs", MODULE_PATH)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(audit)


def complete_panels():
    base = {
        "_puffer_schema": 2,
        "_puffer_agent_steps": 100.0,
        "_puffer_phase_eval": 0,
        "_puffer_env_cumulative": 0,
        "_puffer_final_reprint": 0,
        "_puffer_eval_episodes_completed": 0,
        "n": 5,
        "illegal_frac": 0.2,
        **{key: 0.0 for key in audit.HARD_INTEGRITY_KEYS},
    }
    train = dict(base)
    evaluation = dict(base)
    evaluation.update({
        "_puffer_agent_steps": 200.0,
        "_puffer_phase_eval": 1,
        "_puffer_env_cumulative": 1,
        "_puffer_eval_episodes_completed": 10000,
        "n": 10000,
    })
    final = dict(evaluation)
    final["_puffer_final_reprint"] = 1
    return [train, evaluation, final]


def write_log(path, panels):
    lines = [
        "PufferLib 4.0\nPUFFER_ENV_JSON "
        + json.dumps(panel, sort_keys=True, allow_nan=True)
        + "\n"
        for panel in panels
    ]
    path.write_text("".join(lines), encoding="utf-8")


class RecoveryCompleteLogAuditTests(unittest.TestCase):
    def test_accepts_exact_zero_recovery_panels_but_reports_historical_illegal(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "seed42.log"
            write_log(path, complete_panels())
            report = audit.scan_log(path, min_eval_games=10000)
        self.assertTrue(report["accepted"])
        self.assertEqual(report["machine_panels"], 3)
        self.assertEqual(report["train_panels"], 1)
        self.assertEqual(report["eval_panels"], 1)
        self.assertEqual(report["final_reprints"], 1)
        self.assertEqual(report["historical_diagnostics"]["illegal_frac"]["max"], 0.2)

    def test_allows_only_a_truly_empty_startup_panel_without_n(self):
        empty = {
            "_puffer_schema": 2,
            "_puffer_agent_steps": 0,
            "_puffer_phase_eval": 0,
            "_puffer_env_cumulative": 0,
            "_puffer_final_reprint": 0,
            "_puffer_eval_episodes_completed": 0,
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "seed42.log"
            write_log(path, [empty, *complete_panels()])
            report = audit.scan_log(path, min_eval_games=10000)
            self.assertEqual(report["machine_panels"], 4)
            self.assertEqual(report["empty_panels"], 1)

            partial = dict(empty)
            partial["reward_clip_frac"] = 0.0
            write_log(path, [partial, *complete_panels()])
            with self.assertRaisesRegex(audit.AuditError, "lacks panel n"):
                audit.scan_log(path, min_eval_games=10000)

    def test_rejects_each_nonzero_hard_integrity_field(self):
        for key in audit.HARD_INTEGRITY_KEYS:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                panels = complete_panels()
                panels[0][key] = 0.125
                path = Path(temporary) / "bad.log"
                write_log(path, panels)
                with self.assertRaisesRegex(audit.AuditError, key):
                    audit.scan_log(path, min_eval_games=10000)

    def test_rejects_missing_nonfinite_and_malformed_hard_telemetry(self):
        cases = []
        missing = complete_panels()
        del missing[0][audit.HARD_INTEGRITY_KEYS[0]]
        cases.append(("missing", missing, "missing hard-integrity"))
        nonfinite = complete_panels()
        nonfinite[0][audit.HARD_INTEGRITY_KEYS[0]] = float("nan")
        cases.append(("nonfinite", nonfinite, "invalid JSON constant"))
        for label, panels, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "bad.log"
                write_log(path, panels)
                with self.assertRaisesRegex(audit.AuditError, message):
                    audit.scan_log(path, min_eval_games=10000)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.log"
            path.write_text("PUFFER_ENV_JSON {bad json}\n", encoding="utf-8")
            with self.assertRaisesRegex(audit.AuditError, "invalid PUFFER_ENV_JSON"):
                audit.scan_log(path, min_eval_games=10000)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.log"
            payload = json.dumps(complete_panels()[0], sort_keys=True)
            payload = payload.replace(
                '"reward_clip_frac": 0.0',
                '"reward_clip_frac": 1.0, "reward_clip_frac": 0.0',
                1,
            )
            path.write_text("PUFFER_ENV_JSON " + payload + "\n", encoding="utf-8")
            with self.assertRaisesRegex(audit.AuditError, "duplicate JSON key"):
                audit.scan_log(path, min_eval_games=10000)

    def test_rejects_incomplete_or_invalid_phase_contracts(self):
        cases = []
        no_eval = complete_panels()[:1]
        cases.append(("no_eval", no_eval, "no independent eval panel"))
        no_final = complete_panels()[:2]
        cases.append(("no_final", no_final, "exactly one final reprint"))
        duplicate_final = complete_panels()
        duplicate_final.append(dict(duplicate_final[-1]))
        cases.append(("duplicate_final", duplicate_final, "found 2"))
        invalid_final = complete_panels()
        invalid_final[-1]["_puffer_phase_eval"] = 0
        cases.append(
            ("invalid_final", invalid_final, "populated cumulative eval panel")
        )
        fractional_n = complete_panels()
        fractional_n[0]["n"] = 1.5
        cases.append(("fractional_n", fractional_n, "panel n must be an integer"))
        fractional_steps = complete_panels()
        fractional_steps[0]["_puffer_agent_steps"] = 1.5
        cases.append(
            ("fractional_steps", fractional_steps, "agent steps must be an integer")
        )
        too_few = complete_panels()
        too_few[-2]["_puffer_eval_episodes_completed"] = 9999
        too_few[-1]["_puffer_eval_episodes_completed"] = 9999
        cases.append(("too_few", too_few, "evaluated only 9999"))
        old_schema = complete_panels()
        old_schema[0]["_puffer_schema"] = 1
        cases.append(("old_schema", old_schema, "schema 1"))
        reversed_steps = complete_panels()
        reversed_steps[1]["_puffer_agent_steps"] = 50
        reversed_steps[2]["_puffer_agent_steps"] = 50
        cases.append(("steps", reversed_steps, "steps regressed"))
        for label, panels, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "bad.log"
                write_log(path, panels)
                with self.assertRaisesRegex(audit.AuditError, message):
                    audit.scan_log(path, min_eval_games=10000)

    def test_rejects_a_log_that_changes_during_the_scan(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "seed42.log"
            write_log(path, complete_panels())
            with mock.patch.object(
                audit,
                "_file_identity",
                side_effect=[(1, 2, 100, 3), (1, 2, 101, 4)],
            ):
                with self.assertRaisesRegex(audit.AuditError, "changed during audit"):
                    audit.scan_log(path, min_eval_games=10000)

    def test_audit_requires_exact_unique_log_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "seed42.log"
            write_log(path, complete_panels())
            with self.assertRaisesRegex(audit.AuditError, "expected 3 logs"):
                audit.audit_logs([path], expected_count=3, min_eval_games=10000)
            with self.assertRaisesRegex(audit.AuditError, "duplicate log path"):
                audit.audit_logs([path, path], expected_count=2, min_eval_games=10000)


if __name__ == "__main__":
    unittest.main()
