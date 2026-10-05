#!/usr/bin/env python3
"""Tests for the turn-boundary re-seat prototype's Python side.

  ffb_fold        folding a model-change log, the dugout-box inference, the
                  self-check against the END-of-game snapshot
  lockstep_map    the seat payload on expect ops (cached replays, if present)
  provenance      a BBR1 (re-seated) shard is refused by every BBP reader
  reseat_report   record parsing, label-in-mask check, field naming

Run: python3 validation/test_reseat.py
"""
import glob
import json
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import extract_pairs  # noqa: E402
import ffb_fold  # noqa: E402
import lockstep_map  # noqa: E402
import reseat_report  # noqa: E402


def change(cid, key, value):
    return {"modelChangeId": cid, "modelChangeKey": key, "modelChangeValue": value}


def sync(nr, *changes):
    return {"netCommandId": "serverModelSync", "commandNr": nr,
            "modelChangeList": {"modelChangeArray": list(changes)}}


def tiny_replay():
    """Two players a side. p1 plays and is knocked out; p2 never appears in
    the log (sits in the Reserves box); a1 is Missing; a2 scores."""
    log = [
        sync(1, change("fieldModelSetPlayerCoordinate", "p1", [-1, 0]),
             change("fieldModelSetPlayerCoordinate", "a2", [30, 0])),
        sync(2, change("gameSetHalf", None, 1),
             change("turnDataSetReRolls", "home", 3),
             change("turnDataSetReRolls", "away", 2),
             change("turnDataSetApothecaries", "home", 1),
             change("inducementSetAddInducement", "away",
                    {"inducementType": "bribes", "value": 2, "uses": 0})),
        sync(3, change("fieldModelSetPlayerState", "p1", 0x101),
             change("fieldModelSetPlayerCoordinate", "p1", [12, 7]),
             change("fieldModelSetPlayerState", "a2", 0x101),
             change("fieldModelSetPlayerCoordinate", "a2", [13, 7]),
             change("fieldModelSetBallCoordinate", None, [13, 7]),
             change("fieldModelSetBallInPlay", None, True),
             change("gameSetTurnMode", None, "regular"),
             change("gameSetHomePlaying", None, True),
             change("turnDataSetTurnNr", "home", 1)),
        {"netCommandId": "serverZapPlayer", "commandNr": 0},
        sync(4, change("fieldModelSetBallMoving", None, True),
             change("turnDataSetReRolls", "home", 2),
             change("fieldModelSetPlayerState", "p1", 5),
             change("fieldModelSetPlayerCoordinate", "p1", [-2, 0]),
             change("inducementSetAddInducement", "away",
                    {"inducementType": "bribes", "value": 2, "uses": 1}),
             change("fieldModelSetWeather", None, "Pouring Rain")),
        sync(5, change("gameSetHomePlaying", None, False),
             change("turnDataSetTurnNr", "away", 1),
             change("teamResultSetScore", "away", 1),
             change("turnDataSetCoachBanned", "home", True)),
    ]
    team = lambda ids: {"playerArray": [{"playerId": i} for i in ids]}  # noqa: E731
    return {
        "gameLog": {"commandArray": log},
        "game": {
            "half": 1, "homePlaying": False, "turnMode": "regular",
            "teamHome": team(["p1", "p2"]), "teamAway": team(["a1", "a2"]),
            "fieldModel": {
                "weather": "Pouring Rain", "ballCoordinate": [13, 7],
                "ballInPlay": True, "ballMoving": True,
                "playerDataArray": [
                    {"playerId": "p1", "playerCoordinate": [-2, 0], "playerState": 5},
                    {"playerId": "p2", "playerCoordinate": [-1, 1], "playerState": 9},
                    {"playerId": "a1", "playerCoordinate": [36, 0], "playerState": 10},
                    {"playerId": "a2", "playerCoordinate": [13, 7], "playerState": 0x101},
                ]},
            "turnDataHome": {"turnNr": 1, "reRolls": 2, "apothecaries": 1,
                             "coachBanned": True, "inducementSet": {"inducementArray": []}},
            "turnDataAway": {"turnNr": 1, "reRolls": 2, "apothecaries": 0,
                             "coachBanned": False, "inducementSet": {"inducementArray": [
                                 {"inducementType": "bribes", "value": 2, "uses": 1}]}},
            "gameResult": {"teamResultHome": {"score": 0},
                           "teamResultAway": {"score": 1}},
        },
    }


class FoldTests(unittest.TestCase):
    def test_fold_reproduces_the_end_snapshot(self):
        raw = tiny_replay()
        _, final = ffb_fold.fold(raw)
        self.assertEqual(ffb_fold.check_final(raw, final), [])

    def test_snapshots_are_states_after_each_command(self):
        snaps, _ = ffb_fold.fold(tiny_replay(), at_cmds={3, 4})
        s3, s4 = snaps[3], snaps[4]
        self.assertEqual(s3["players"]["p1"], {"xy": [12, 7], "state": 0x101})
        self.assertEqual(s3["turn"]["home"]["reRolls"], 3)
        self.assertEqual(s3["weather"], "Nice Weather")
        self.assertTrue(s3["homePlaying"])
        self.assertEqual(s4["players"]["p1"], {"xy": [-2, 0], "state": 5})
        self.assertEqual(s4["turn"]["home"]["reRolls"], 2)
        self.assertEqual(s4["inducements"]["away"]["bribes"], {"value": 2, "uses": 1})
        self.assertEqual(s4["weather"], "Pouring Rain")
        # a snapshot is a copy: the later command did not reach back into s3
        self.assertEqual(s3["inducements"]["away"]["bribes"], {"value": 2, "uses": 0})

    def test_untouched_players_take_the_snapshot_value(self):
        snaps, _ = ffb_fold.fold(tiny_replay(), at_cmds={1})
        # p2 and a1 never appear in the log: their end value is their value
        self.assertEqual(snaps[1]["players"]["p2"], {"xy": [-1, 1], "state": 9})
        self.assertEqual(snaps[1]["players"]["a1"], {"xy": [36, 0], "state": 10})
        # p1 IS touched: its first logged values stand, nothing is seeded
        self.assertEqual(snaps[1]["players"]["p1"], {"xy": [-1, 0], "state": 0})

    def test_box_names_the_state_before_the_log_does(self):
        snaps, _ = ffb_fold.fold(tiny_replay(), at_cmds={1})
        self.assertEqual(ffb_fold.base_of(snaps[1]["players"]["p1"]), 9)
        self.assertEqual(ffb_fold.box_base([-2, 3]), 5)    # home KO box
        self.assertEqual(ffb_fold.box_base([31, 0]), 5)    # away KO box
        self.assertEqual(ffb_fold.box_base([36, 0]), 10)   # away Missing box
        self.assertEqual(ffb_fold.box_base([12, 7]), 0)    # on the pitch
        self.assertEqual(ffb_fold.box_base(None), 0)

    def test_check_final_reports_a_log_that_does_not_explain_the_snapshot(self):
        raw = tiny_replay()
        raw["game"]["turnDataHome"]["reRolls"] = 1
        raw["game"]["fieldModel"]["playerDataArray"][0]["playerCoordinate"] = [-1, 0]
        _, final = ffb_fold.fold(raw)
        names = {d[0] for d in ffb_fold.check_final(raw, final)}
        self.assertIn("turn.home.reRolls", names)
        self.assertIn("player[p1].xy", names)
        self.assertIn("player[p1].box", names)   # Reserves box, but KO state

    def test_folder_finds_commands_by_position_not_by_number(self):
        raw = tiny_replay()
        log = raw["gameLog"]["commandArray"]
        # renumber the sync commands 1,2,30,20,40: not increasing
        syncs = [c for c in log if c["netCommandId"] == "serverModelSync"]
        for c, nr in zip(syncs, (1, 2, 30, 20, 40)):
            c["commandNr"] = nr
        want, _ = ffb_fold.fold(raw, at_cmds={30, 20})
        folder = ffb_fold.Folder(raw)
        self.assertEqual(folder.at(30), want[30])
        self.assertEqual(folder.at(30), want[30])     # asking again is fine
        self.assertEqual(folder.at(20), want[20])     # 20 comes AFTER 30
        with self.assertRaises(LookupError):
            folder.at(2)                              # behind: cannot go back
        with self.assertRaises(LookupError):
            folder.at(999)                            # not in the log at all

    def test_folder_refuses_a_number_that_occurs_twice(self):
        raw = tiny_replay()
        syncs = [c for c in raw["gameLog"]["commandArray"]
                 if c["netCommandId"] == "serverModelSync"]
        for c, nr in zip(syncs, (1, 2, 1, 3, 4)):
            c["commandNr"] = nr
        folder = ffb_fold.Folder(raw)
        with self.assertRaises(LookupError):
            folder.at(1)                              # which 1?
        before = json.dumps(folder.at(2), sort_keys=True)
        self.assertEqual(json.dumps(folder.at(2), sort_keys=True), before)
        self.assertEqual(folder.i, 2)                 # did not run ahead

    def test_streaming_folder_matches_fold(self):
        raw = tiny_replay()
        snaps, final = ffb_fold.fold(raw, at_cmds={1, 2, 3, 4, 5})
        folder = ffb_fold.Folder(raw)
        for nr in (1, 2, 3, 4, 5):
            self.assertEqual(folder.at(nr), snaps[nr], nr)
        self.assertEqual(folder.state, final)


class ReaderRefusalTests(unittest.TestCase):
    """A re-seated shard must not be readable as a BBP shard by anything."""

    def shard(self, magic):
        rec = bytearray(reseat_report.REC)
        struct.pack_into("<II", rec, 0, 123, 7)
        rec[9] = 1                      # segment
        rec[11] = 1                     # span closed and matched
        mask0 = 12 + reseat_report.OBS
        rec[mask0 + 8] = 1              # END_TURN
        rec[mask0 + reseat_report.HEAD_TYPE + 32] = 1
        rec[mask0 + reseat_report.HEAD_TYPE + reseat_report.HEAD_ARG + 390] = 1
        rec[-4], rec[-3] = 8, 32
        struct.pack_into("<H", rec, len(rec) - 2, 390)
        return magic + struct.pack("<III", 4, reseat_report.OBS, reseat_report.MASK) + bytes(rec)

    def write(self, path, magic):
        with open(path, "wb") as f:
            f.write(self.shard(magic))

    def test_extract_pairs_refuses_bbr1(self):
        with tempfile.TemporaryDirectory() as d:
            good, bad = os.path.join(d, "a.bbp"), os.path.join(d, "a.bbr")
            self.write(good, b"BBP1")
            self.write(bad, b"BBR1")
            self.assertEqual(extract_pairs.validate_shard(good), 1)
            with self.assertRaises(ValueError):
                extract_pairs.validate_shard(bad)

    def test_bc_loader_refuses_bbr1(self):
        try:
            sys.path.insert(0, os.path.join(ROOT, "training"))
            import bc_pretrain
        except Exception as exc:  # numpy / torch absent on stock python3
            self.skipTest(f"bc_pretrain not importable here: {exc}")
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "a.bbr")
            self.write(bad, b"BBR1")
            with self.assertRaises(SystemExit):
                bc_pretrain._read_shard_info(bad, 123)

    def test_report_reader_wants_the_magic_it_was_asked_for(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.bbr")
            self.write(path, b"BBR1")
            recs = list(reseat_report.records(path, b"BBR1"))
            self.assertEqual(len(recs), 1)
            self.assertTrue(reseat_report.target_in_mask(recs[0]))
            with self.assertRaises(ValueError):
                list(reseat_report.records(path, b"BBP1"))
            broken = bytearray(recs[0])
            broken[12 + reseat_report.OBS + 8] = 0   # END_TURN no longer legal
            self.assertFalse(reseat_report.target_in_mask(bytes(broken)))


class ReportFieldTests(unittest.TestCase):
    def test_obs_field_names(self):
        f = reseat_report.obs_field
        self.assertEqual(f(0), "player.own.x")
        self.assertEqual(f(16 * 24 + 4), "player.opp.flags_lo")
        self.assertEqual(f(768), "ctx.ball_state")
        self.assertEqual(f(784 + 5), "scalar.rerolls_me")
        self.assertEqual(f(832), "tz_plane.mine")
        self.assertEqual(f(832 + 390), "tz_plane.theirs")
        self.assertEqual(f(2781), "plane.step_success")


CACHED = sorted(glob.glob(os.path.join(HERE, "replay_cache", "replay_*.json.gz")))
NORMALIZED = [p for p in (os.path.join(
    HERE, "normalized", os.path.basename(c)[7:-8] + ".jsonl") for c in CACHED[:40])
    if os.path.exists(p)][:6]


@unittest.skipUnless(NORMALIZED, "no cached + normalized replays in this checkout")
class SeatPayloadTests(unittest.TestCase):
    def test_every_boundary_gets_a_seat_the_engine_can_hold(self):
        seatable = 0
        for path in NORMALIZED:
            rid = os.path.basename(path)[:-6]
            with open(path, encoding="utf-8") as f:
                records = [json.loads(l) for l in f]
            raw = lockstep_map.load_raw(rid)
            ops = lockstep_map.Mapper(records, raw_replay=raw).run()
            bare = lockstep_map.Mapper(records, raw_replay=raw)
            bare.folder = None
            plain = bare.run()
            self.assertFalse(any("seat" in o for o in plain))

            # the seat is an addition. (Without the fold the mapper cannot
            # name the turn an END_TURN closes, so it neither tags them nor
            # emits the unrecorded "if still open" ones: the old behaviour.)
            def end_turn(o):
                return o["op"] == "act" and o["type"] == lockstep_map.A_END_TURN

            def core(seq):
                tags = ("seat", "team", "half", "turn")
                return [{k: v for k, v in o.items()
                         if k != "seat" and not (end_turn(o) and k in tags)}
                        for o in seq if not (end_turn(o) and o.get("auto"))]
            self.assertEqual(core(ops), core(plain), rid)
            self.assertFalse(any("team" in o for o in plain if end_turn(o)))
            self.assertTrue(any("turn" in o for o in ops if end_turn(o)))
            for o in ops:
                if o["op"] != "expect":
                    continue
                self.assertIn("seat", o)
                seat = o["seat"]
                if "refuse" in seat:
                    continue
                seatable += 1
                slots = [r[0] for r in seat["pl"]]
                self.assertEqual(len(slots), len(set(slots)))
                on = [r for r in seat["pl"] if r[1] == 0]
                self.assertEqual(len({(r[2], r[3]) for r in on}), len(on))
                for team in (0, 1):
                    self.assertLessEqual(sum(1 for r in on if r[0] // 16 == team), 11)
                x, y, held = seat["ball"]
                at = [r for r in on if (r[2], r[3]) == (x, y)]
                self.assertEqual(bool(held), bool(at))
                if at:
                    self.assertEqual(at[0][4], 0)   # the holder is Standing
                    self.assertTrue(at[0][5] & lockstep_map.PF_HAS_BALL)
                self.assertIn(seat["active"], (0, 1))
                self.assertTrue(1 <= seat["turn"][seat["active"]] <= 8)
                for r in on:   # the active team has no plain Stunned players
                    if r[0] // 16 == seat["active"]:
                        self.assertNotEqual(r[4], lockstep_map.STANCE_STUNNED)
        self.assertGreater(seatable, 20)


if __name__ == "__main__":
    unittest.main()
