#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import report_scenario_coverage as coverage


def row(
    index: int,
    replay_id: int,
    turn: int,
    *,
    active_team: int = 0,
    team_id_0: int = 10,
    team_id_1: int = 20,
    **flags: int,
) -> dict[str, int]:
    result = {
        "active_team": active_team,
        "ball_state": 1,
        "command": index + 1,
        "eligible_players": 6,
        "half": 1,
        "record_index": index,
        "replay_id": replay_id,
        "s1": 0,
        "s1_ball_tackle_zones": 0,
        "s1_cheapest_dodges": 255,
        "s1_cheapest_gfis": 255,
        "s1_has_sure_hands": 0,
        "s1_recoverers": 0,
        "s2": 0,
        "s2_cheapest_dodges": 255,
        "s2_cheapest_gfis": 255,
        "s2_opponent_reachers": 0,
        "s3": 0,
        "s3_risk_mask": 0,
        "s3_zero_roll_players": 2,
        "s4": 0,
        "s4_full": 0,
        "s4_r6v1_full": 0,
        "s4_r6v1_soft": 0,
        "s4_soft": 0,
        "s5": 0,
        "s5_carrier_marked": 0,
        "s5_horizon": -1,
        "s5_team_threats_1turn": 0,
        "s5_team_threats_2turn": 0,
        "s6": 0,
        "s6_class_changing_moves": 0,
        "s6_dynamic_blocks": 0,
        "s6_fixed_class_mask": 0,
        "s6a": 0,
        "s6b": 0,
        "team_id_0": team_id_0,
        "team_id_1": team_id_1,
        "turn": turn,
        "weather": 1,
    }
    result.update(flags)
    return result


class ScenarioAggregationTests(unittest.TestCase):
    def test_counts_caps_turn_bands_subbuckets_and_overlaps(self) -> None:
        rows = [
            row(0, 10, 1, s1=1, s1_recoverers=1, s1_has_sure_hands=1),
            row(1, 10, 2, s1=1, s2=1, s1_ball_tackle_zones=2),
            row(2, 10, 3, s3=1, s3_risk_mask=4),
            row(3, 10, 5, s6=1, s6a=1, s6_fixed_class_mask=6),
            row(4, 20, 4, s4=1, s4_full=1, s4_r6v1_full=1),
            row(5, 20, 7, s5=1, s5_horizon=2),
        ]

        report = coverage.summarize_rows(rows, split_key="unit-test")

        self.assertEqual(
            report["denominators"],
            {"capped_records": 5, "records": 6, "replays": 2},
        )
        self.assertEqual(
            report["coverage"]["s1"]["overall"],
            {"capped_records": 2, "records": 2, "replays": 1},
        )
        self.assertEqual(
            report["coverage"]["s1_sure_hands"]["overall"]["records"], 1
        )
        self.assertEqual(
            report["coverage"]["s1_ball_tackle_zones"]["overall"]["records"],
            1,
        )
        self.assertEqual(
            report["coverage"]["s5_horizon_2"]["turn_bands"]["5-8"]["records"],
            1,
        )
        self.assertEqual(
            report["pairwise_overlaps"]["s1&s2"]["records"], 1
        )
        self.assertEqual(report["turn_bands"]["1-2"]["records"], 2)
        self.assertEqual(report["turn_bands"]["3-4"]["records"], 2)
        self.assertEqual(report["turn_bands"]["5-8"]["records"], 2)
        self.assertEqual(report["race_pairs"]["10-20"]["records"], 6)
        self.assertEqual(report["coverage"]["none"]["overall"]["records"], 0)

    def test_split_is_deterministic_and_replay_disjoint(self) -> None:
        rows = [row(index, 100 + index // 2, 1 + index % 8) for index in range(40)]
        first = coverage.summarize_rows(rows, split_key="stable-key")
        second = coverage.summarize_rows(list(rows), split_key="stable-key")
        self.assertEqual(first, second)

        replay_sets = {
            name: set(values["replay_id_values"])
            for name, values in first["splits"].items()
        }
        self.assertFalse(replay_sets["train"] & replay_sets["validation"])
        self.assertFalse(replay_sets["train"] & replay_sets["test"])
        self.assertFalse(replay_sets["validation"] & replay_sets["test"])
        self.assertEqual(set.union(*replay_sets.values()), set(range(100, 120)))

    def test_rejects_structural_and_source_order_violations(self) -> None:
        bad_cases = {
            "S2 without S1": [row(0, 10, 1, s2=1)],
            "S4 and S5 overlap": [row(0, 10, 1, s4=1, s5=1)],
            "record index": [row(1, 10, 1)],
            "S6 union": [row(0, 10, 1, s6=0, s6a=1)],
        }
        for message, rows in bad_cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(coverage.ScenarioCoverageError, message):
                    coverage.summarize_rows(rows, split_key="unit-test")


class ScenarioPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bank = self.root / "bank.bbs"
        self.filter_manifest = self.root / "filter-manifest.json"
        self.scanner = self.root / "fake-scanner"
        self.source = self.root / "scanner-source.c"
        self.records = self.root / "records.jsonl"
        self.report = self.root / "report.json"
        self.manifest = self.root / "manifest.json"
        self.rows = [
            row(0, 10, 1, s1=1),
            row(1, 10, 2, s1=1, s2=1),
            row(2, 20, 3, s5=1, s5_horizon=1),
        ]
        self.bank.write_bytes(b"test-bank\n")
        bank_sha = self.sha256(self.bank)
        self.filter_manifest.write_text(
            json.dumps(
                {
                    "format": {
                        "engine_fingerprint": "0x12345678",
                        "magic": "BBS1",
                        "match_size": 2240,
                        "version": 1,
                    },
                    "output": {
                        "half_histogram": {"1": 3},
                        "records": 3,
                        "replay_ids": 2,
                        "sha256": bank_sha,
                        "turn_histogram": {"1": 1, "2": 1, "3": 1},
                    },
                    "schema_version": 1,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        scanner_payload = "".join(
            json.dumps(item, separators=(",", ":"), sort_keys=True) + "\n"
            for item in self.rows
        )
        self.scanner.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            f"sys.stdout.write({scanner_payload!r})\n",
            encoding="utf-8",
        )
        self.scanner.chmod(0o700)
        self.source.write_text("/* pinned source */\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def generate(self, **overrides: object) -> dict[str, object]:
        arguments: dict[str, object] = {
            "bank_path": self.bank,
            "filter_manifest_path": self.filter_manifest,
            "scanner_path": self.scanner,
            "scanner_sources": {self.source: self.sha256(self.source)},
            "records_path": self.records,
            "report_path": self.report,
            "manifest_path": self.manifest,
            "expected_bank_sha256": self.sha256(self.bank),
            "expected_filter_manifest_sha256": self.sha256(self.filter_manifest),
            "expected_scanner_sha256": self.sha256(self.scanner),
            "expected_records": 3,
            "expected_replay_ids": 2,
            "expected_half_histogram": {1: 3},
            "expected_turn_histogram": {1: 1, 2: 1, 3: 1},
            "expected_ball_state_histogram": {1: 3},
            "command": ["report-scenario-coverage", "fixture"],
            "split_key": "unit-test",
        }
        arguments.update(overrides)
        return coverage.generate_scenario_report(**arguments)

    def test_hash_pinned_publication_is_bound_and_deterministic(self) -> None:
        result = self.generate()
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        report = json.loads(self.report.read_text(encoding="utf-8"))

        self.assertEqual(result, manifest)
        self.assertEqual(report["denominators"]["records"], 3)
        self.assertEqual(manifest["input"]["sha256"], self.sha256(self.bank))
        self.assertEqual(manifest["outputs"]["records"]["sha256"], self.sha256(self.records))
        self.assertEqual(manifest["outputs"]["report"]["sha256"], self.sha256(self.report))
        self.assertEqual(manifest["scanner"]["binary"]["sha256"], self.sha256(self.scanner))
        self.assertEqual(manifest["scanner"]["sources"][0]["sha256"], self.sha256(self.source))

        first = tuple(path.read_bytes() for path in (self.records, self.report, self.manifest))
        for path in (self.records, self.report, self.manifest):
            path.unlink()
        self.generate()
        second = tuple(path.read_bytes() for path in (self.records, self.report, self.manifest))
        self.assertEqual(first, second)

    def test_fails_closed_on_hash_drift_existing_output_and_bad_scanner_json(self) -> None:
        with self.assertRaisesRegex(coverage.ScenarioCoverageError, "bank SHA-256"):
            self.generate(expected_bank_sha256="0" * 64)
        self.assertFalse(self.records.exists())

        self.records.write_text("occupied\n", encoding="utf-8")
        with self.assertRaisesRegex(coverage.ScenarioCoverageError, "already exists"):
            self.generate()
        self.assertEqual(self.records.read_text(encoding="utf-8"), "occupied\n")
        self.records.unlink()

        self.scanner.write_text("#!/bin/sh\nprintf 'not-json\\n'\n", encoding="utf-8")
        self.scanner.chmod(0o700)
        with self.assertRaisesRegex(coverage.ScenarioCoverageError, "scanner JSON"):
            self.generate(expected_scanner_sha256=self.sha256(self.scanner))
        self.assertFalse(self.records.exists())
        self.assertFalse(self.report.exists())
        self.assertFalse(self.manifest.exists())

    def test_detects_bank_mutation_and_publish_failure_without_clobber(self) -> None:
        real_sha256 = coverage.sha256
        bank_hashes = 0

        def mutate_before_second_bank_hash(path: Path) -> str:
            nonlocal bank_hashes
            result = real_sha256(path)
            if path == self.bank.resolve():
                bank_hashes += 1
                if bank_hashes == 1:
                    self.bank.write_bytes(b"mutated!!\n")
            return result

        with mock.patch.object(coverage, "sha256", side_effect=mutate_before_second_bank_hash):
            with self.assertRaisesRegex(coverage.ScenarioCoverageError, "bank changed"):
                self.generate()
        self.assertFalse(self.records.exists())
        self.bank.write_bytes(b"test-bank\n")

        real_link = os.link
        calls = 0

        def fail_second_link(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected publish failure")
            real_link(source, destination)

        with mock.patch.object(coverage.os, "link", side_effect=fail_second_link):
            with self.assertRaisesRegex(OSError, "injected publish failure"):
                self.generate()
        self.assertFalse(self.records.exists())
        self.assertFalse(self.report.exists())
        self.assertFalse(self.manifest.exists())
        self.assertEqual(list(self.root.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
