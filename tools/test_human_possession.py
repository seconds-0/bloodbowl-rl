#!/usr/bin/env python3

import gzip
import json
import tempfile
import unittest
from pathlib import Path

import human_possession


class HumanPossessionTests(unittest.TestCase):
    def test_counts_only_started_regular_team_turns(self):
        replay = {
            "game": {
                "teamHome": {"playerArray": [{"playerId": 10}]},
                "teamAway": {"playerArray": [{"playerId": 20}]},
                "gameOptions": {"gameOptionArray": [
                    {"gameOptionId": "rulesVersion",
                     "gameOptionValue": "BB2025"}
                ]},
            },
            "gameLog": {"commandArray": [
                self.command([
                    self.change("fieldModelSetPlayerCoordinate", "10", [5, 5]),
                    self.change("fieldModelSetPlayerCoordinate", "20", [8, 8]),
                    self.change("fieldModelSetBallCoordinate", None, [5, 5]),
                    self.change("fieldModelSetBallInPlay", None, True),
                    self.change("fieldModelSetBallMoving", None, False),
                    self.change("gameSetHomePlaying", None, False),
                ], [self.report("turnEnd")]),
                self.command([
                    self.change("gameSetTurnMode", None, "regular"),
                    self.change("turnDataSetTurnStarted", "home", True),
                ]),
                # In-turn defensive choices toggle homePlaying repeatedly.
                self.command([
                    self.change("gameSetHomePlaying", None, False),
                    self.change("gameSetHomePlaying", None, True),
                ]),
                self.command([], [self.report("turnEnd")]),
                # A kickoff mini-turn must not enter the denominator.
                self.command([
                    self.change("gameSetTurnMode", None, "kickoffReturn"),
                    self.change("turnDataSetTurnStarted", "away", True),
                    self.change("gameSetHomePlaying", None, False),
                ], [self.report("turnEnd")]),
                self.command([
                    self.change("gameSetTurnMode", None, "regular"),
                    self.change("turnDataSetTurnStarted", "away", True),
                    self.change("fieldModelSetBallCoordinate", None, [6, 6]),
                ]),
                self.command([], [self.report("turnEnd")]),
                # Removed players must not remain phantom holders at their old
                # coordinate on a later turn.
                self.command([
                    self.change("fieldModelRemovePlayer", "10", [5, 5]),
                    self.change("turnDataSetTurnStarted", "home", True),
                    self.change("fieldModelSetBallCoordinate", None, [5, 5]),
                ]),
                self.command([], [self.report("turnEnd")]),
            ]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "replay_1.json.gz"
            with gzip.open(path, "wt", encoding="utf-8") as f:
                json.dump(replay, f)
            result = human_possession.replay_possession(path)

        self.assertEqual(result["turn_ends"], 3)
        self.assertEqual(result["held_ends"], 1)
        self.assertEqual(result["synthetic_turn_end_reports"], 2)
        self.assertEqual(result["rules_version"], "BB2025")

    def test_half_end_uses_pre_cleanup_possession_snapshot(self):
        replay = {
            "game": {
                "teamHome": {"playerArray": [{"playerId": 10}]},
                "teamAway": {"playerArray": [{"playerId": 20}]},
                "gameOptions": {"gameOptionArray": [
                    {"gameOptionId": "rulesVersion",
                     "gameOptionValue": "BB2025"}
                ]},
            },
            "gameLog": {"commandArray": [
                self.command([
                    self.change("fieldModelSetPlayerCoordinate", "10", [5, 5]),
                    self.change("fieldModelSetBallCoordinate", None, [5, 5]),
                    self.change("fieldModelSetBallInPlay", None, True),
                    self.change("fieldModelSetBallMoving", None, False),
                    self.change("gameSetTurnMode", None, "regular"),
                    self.change("turnDataSetTurnStarted", "home", True),
                ]),
                # FUMBBL reports turnEnd in the same command that removes the
                # pitch and ball at a half/match boundary.
                self.command([
                    self.change("gameSetTurnMode", None, "setup"),
                    self.change("fieldModelRemovePlayer", "10", [5, 5]),
                    self.change("fieldModelSetBallInPlay", None, False),
                ], [self.report("turnEnd"), self.report("startHalf")]),
            ]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "replay_2.json.gz"
            with gzip.open(path, "wt", encoding="utf-8") as f:
                json.dump(replay, f)
            result = human_possession.replay_possession(path)

        self.assertEqual(result["turn_ends"], 1)
        self.assertEqual(result["held_ends"], 1)

    def test_audit_fails_on_missing_cache_or_allowlisted_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(FileNotFoundError, "replay cache"):
                human_possession.audit(root / "missing")

            with gzip.open(root / "replay_1.json.gz", "wt", encoding="utf-8") as f:
                json.dump({}, f)
            with self.assertRaisesRegex(FileNotFoundError, "1 allowlisted replay"):
                human_possession.audit(root, replay_ids={1, 2})

            (root / "replay_1.json.gz").write_bytes(b"not gzip")
            with self.assertRaisesRegex(ValueError, "malformed allowlisted replay"):
                human_possession.audit(root, replay_ids={1})

    @staticmethod
    def change(change_id, key, value):
        return {"modelChangeId": change_id, "modelChangeKey": key,
                "modelChangeValue": value}

    @staticmethod
    def report(report_id, **kwargs):
        return {"reportId": report_id, **kwargs}

    @staticmethod
    def command(changes, reports=()):
        return {
            "modelChangeList": {"modelChangeArray": list(changes)},
            "reportList": {"reports": list(reports)},
        }


if __name__ == "__main__":
    unittest.main()
