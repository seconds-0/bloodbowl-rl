"""Action masks for a diagnostic copy of a policy, and the behaviour counts.

A masked seat (policy.MaskedPolicySeat) is the plain seat with a restricted
support: the same forward, recurrent state and generator, the policy's own
distribution renormalized over what is left. These tests hold that it

  - never removes the last legal action, and counts when that fallback fires;
  - removes exactly the action type each mask names, under its condition only;
  - leaves an unmasked game byte for byte what it was;
  - plays the same games batched and unbatched;
  - and that Match's behaviour counts agree with the actions applied.
"""
import json

import numpy as np
import pytest
import torch

from play_harness import engine as E
from play_harness import tournament as T
from play_harness.policy import (MASKS, MaskedPolicySeat, PolicySeat, check_masks,
                                 random_policy, restrict_support, select_joint)

A = E.A
NONE_ARG, NONE_SQ = E.ARG_NONE, E.SQ_NONE


def sup(*tuples):
    return np.asarray([E.pack_tuple(*t) for t in tuples], dtype=np.uint32)


def types_of(packed):
    return sorted(set(int(p) & 1023 for p in packed))


TURN = sup((A["ACTIVATE"], 3, NONE_SQ), (A["ACTIVATE"], 5, NONE_SQ),
           (A["END_TURN"], NONE_ARG, NONE_SQ))
ONLY_END_TURN = sup((A["END_TURN"], NONE_ARG, NONE_SQ))
MOVE = sup((A["STEP"], NONE_ARG, 10), (A["STEP"], NONE_ARG, 11),
           (A["END_ACTIVATION"], NONE_ARG, NONE_SQ))
ONLY_END_ACT = sup((A["END_ACTIVATION"], NONE_ARG, NONE_SQ))
BLOCK = sup((A["BLOCK_TARGET"], NONE_ARG, 40), (A["END_ACTIVATION"], NONE_ARG, NONE_SQ))
BLITZ = sup((A["STEP"], NONE_ARG, 10), (A["BLOCK_TARGET"], NONE_ARG, 40),
            (A["END_ACTIVATION"], NONE_ARG, NONE_SQ))


# ---- the support filter ---------------------------------------------------------------
def test_m1_removes_end_turn_only_while_a_player_can_be_activated():
    kept, events = restrict_support(TURN, ("m1",), after_declare=False)
    assert types_of(kept) == [A["ACTIVATE"]] and len(kept) == 2
    assert events == {"m1": (True, A["END_TURN"], False)}
    kept, events = restrict_support(ONLY_END_TURN, ("m1",), after_declare=False)
    assert list(kept) == list(ONLY_END_TURN) and events == {}     # nobody left to activate
    kept, events = restrict_support(MOVE, ("m1",), after_declare=True)
    assert list(kept) == list(MOVE) and events == {}


def test_m2_acts_only_on_the_first_decision_after_a_declaration():
    kept, events = restrict_support(MOVE, ("m2",), after_declare=True)
    assert types_of(kept) == [A["STEP"]]
    assert events == {"m2": (True, A["END_ACTIVATION"], False)}
    kept, events = restrict_support(MOVE, ("m2",), after_declare=False)
    assert list(kept) == list(MOVE) and events == {}


def test_m2_never_removes_the_last_legal_action():
    kept, events = restrict_support(ONLY_END_ACT, ("m2",), after_declare=True)
    assert list(kept) == list(ONLY_END_ACT)
    assert events == {"m2": (True, None, True)}


def test_m3_removes_end_activation_while_a_block_target_is_on_offer():
    for support, left in ((BLOCK, [A["BLOCK_TARGET"]]), (BLITZ, [A["STEP"], A["BLOCK_TARGET"]])):
        kept, events = restrict_support(support, ("m3",), after_declare=False)
        assert types_of(kept) == sorted(left)
        assert events == {"m3": (True, A["END_ACTIVATION"], False)}
    kept, events = restrict_support(MOVE, ("m3",), after_declare=False)
    assert list(kept) == list(MOVE) and events == {}


def test_masks_combine_and_each_removal_is_credited_once():
    kept, events = restrict_support(BLOCK, MASKS, after_declare=True)
    assert types_of(kept) == [A["BLOCK_TARGET"]]
    assert events == {"m2": (True, A["END_ACTIVATION"], False), "m3": (True, None, False)}
    for support in (TURN, ONLY_END_TURN, MOVE, ONLY_END_ACT, BLOCK, BLITZ):
        for after in (False, True):
            kept, _ = restrict_support(support, MASKS, after_declare=after)
            assert len(kept) >= 1 and set(kept) <= set(support)


def test_mask_names_are_checked():
    assert check_masks(None) == () and check_masks(["m3", "m1", "m1"]) == ("m1", "m3")
    with pytest.raises(ValueError):
        check_masks(["m4"])
    with pytest.raises(ValueError):
        MaskedPolicySeat(random_policy(seed=1), 0, masks=())
    with pytest.raises(ValueError):
        T.parse_masks("")
    assert T.parse_masks("m3,m1") == ("m1", "m3")


# ---- the seat ---------------------------------------------------------------------------
def test_masked_seat_renormalizes_the_policys_own_distribution():
    policy = random_policy(seed=3)
    logits = torch.zeros(sum(E.ACT_SIZES))
    logits[A["END_TURN"]] = 2.0                          # the policy wants to stop
    seat = MaskedPolicySeat(policy, 0, masks=("m1",), seed=5)
    seat.reset_match()
    picks = [seat.decide(logits, TURN, True) for _ in range(200)]
    assert all(action[0] == A["ACTIVATE"] for action, _ in picks)
    # Two ACTIVATE tuples with equal logits: each 0.5 once END_TURN is gone.
    assert all(abs(lp - np.log(0.5)) < 1e-6 for _, lp in picks)
    args = [action[1] for action, _ in picks]
    assert 60 < args.count(3) < 140
    stats = seat.mask_stats["m1"]
    assert stats["held"] == stats["applied"] == 200 and stats["fallback"] == 0
    p_end = float(np.exp(2.0) / (np.exp(2.0) + 1.0))     # type head: END_TURN against ACTIVATE
    assert abs(stats["mass"] / 200 - p_end) < 1e-5
    assert seat.forwards == seat.decisions == 200


def test_masked_seat_tracks_the_declaration_and_counts_fallbacks():
    policy = random_policy(seed=3)
    logits = torch.zeros(sum(E.ACT_SIZES))
    logits[A["END_ACTIVATION"]] = 50.0
    seat = MaskedPolicySeat(policy, 0, masks=("m2",), seed=1)
    seat.reset_match()
    declare = sup((A["DECLARE"], 0, NONE_SQ))
    assert seat.decide(logits, MOVE, True)[0][0] == A["END_ACTIVATION"]     # no declaration yet
    assert seat.decide(logits, declare, True)[0][0] == A["DECLARE"]
    assert seat.decide(logits, MOVE, True)[0][0] == A["STEP"]               # first decision after
    assert seat.decide(logits, MOVE, True)[0][0] == A["END_ACTIVATION"]     # second: free again
    assert seat.decide(logits, declare, True)[0][0] == A["DECLARE"]
    assert seat.decide(logits, ONLY_END_ACT, True)[0][0] == A["END_ACTIVATION"]
    assert seat.mask_stats["m2"] == {"held": 2, "applied": 1, "fallback": 1,
                                     "mass": pytest.approx(1.0)}
    # A waiting row never reaches the masks.
    waiting = np.asarray([E.pack_tuple(0, NONE_ARG, NONE_SQ)], dtype=np.uint32)
    assert seat.decide(logits, waiting, False) == ((0, NONE_ARG, NONE_SQ), 0.0)
    seat.reset_match()
    assert seat.mask_stats["m2"]["held"] == 0 and seat._after_declare is False


# ---- whole games ------------------------------------------------------------------------
@pytest.fixture(scope="module")
def policies():
    return {"plain": random_policy(seed=11, scale=0.05)}


def _essential(rec):
    return {k: v for k, v in rec.items() if k not in ("seconds", "pid")}


def test_an_unmasked_match_is_what_it_was(policies):
    """No mask set: the same seats, the same trail, and no mask in the record."""
    p = policies["plain"]
    plain, seats = T.play_match(p, p, 4242)
    again, _ = T.play_match(p, p, 4242, masks=(None, None))
    assert _essential(plain) == _essential(again)
    assert all(type(s) is PolicySeat for s in seats)
    assert plain["masks"] == [None, None] and plain["mask_stats"] == [None, None]


@pytest.mark.parametrize("masks", [("m1",), ("m2",), ("m3",), MASKS])
def test_a_masked_side_obeys_its_masks_for_a_whole_game(policies, masks):
    p = policies["plain"]
    rec, seats = T.play_match(p, p, 777, masks=(masks, None))
    assert rec["natural"] and not any(rec["integrity"].values())
    assert type(seats[0]) is MaskedPolicySeat and type(seats[1]) is PolicySeat
    assert rec["masks"] == [list(masks), None] and rec["mask_stats"][1] is None
    masked, plain = rec["behaviour"]
    stats = rec["mask_stats"][0]
    if "m1" in masks:
        assert masked["end_turn_with_player_left"] == 0
        assert stats["m1"]["fallback"] == 0
    if "m2" in masks:
        # An activation may end at once only where the mask had to give way.
        assert masked["ended_at_once"] == stats["m2"]["fallback"]
    if "m3" in masks:
        assert masked["ended_with_block_target_on_offer"] == 0
        assert stats["m3"]["fallback"] == 0
    for m in masks:
        assert stats[m]["applied"] + stats[m]["fallback"] <= stats[m]["held"]
        assert 0.0 <= stats[m]["mass"] <= stats[m]["applied"] + 1e-6
    # The other side is not touched: it keeps doing what the masks forbid.
    unmasked, _ = T.play_match(p, p, 777)
    assert plain["activations"] > 0
    if masks == ("m1",):
        assert unmasked["behaviour"][0]["end_turn_with_player_left"] > 0


def test_behaviour_counts_are_consistent(policies):
    p = policies["plain"]
    # The random test policy ends most turns at once; m1 on both sides makes it play.
    rec, seats = T.play_match(p, p, 31337, masks=(("m1",), ("m1",)))
    for side in (0, 1):
        b = rec["behaviour"][side]
        declared = sum(v for k, v in b.items() if k.startswith("declared_"))
        assert b["activations"] == declared > 0
        assert b["end_turn_with_player_left"] <= b["end_turn"] <= b["team_turns"]
        assert b["block_targets_block"] + b["block_targets_blitz"] <= b["block_targets"]
        assert b["ended_at_once"] <= b["activations"]
        assert b["turnovers"] <= b["team_turns"] and b["team_turns_holding_ball"] <= b["team_turns"]
        assert 8 <= b["team_turns"] <= 16
    assert set(T.BEHAVIOUR_KEYS) <= set(rec["behaviour"][0])


def test_bot_seats_are_counted_and_refuse_masks(policies):
    bot = T.ScriptedBot("contact")
    rec, _ = T.play_match(policies["plain"], bot, 99)
    assert rec["behaviour"][1]["activations"] > 0 and rec["behaviour"][1]["block_targets"] > 0
    with pytest.raises(ValueError):
        T.Match(policies["plain"], bot, 99, masks=(None, ("m1",)))
    with pytest.raises(ValueError):
        T.Match(policies["plain"], policies["plain"], 99, masks=(("m1",), None),
                seat_factory=lambda *a, **k: PolicySeat(*a, **k))


def test_masked_games_are_the_same_batched_and_unbatched():
    """Row-wise forwards remove float rounding, so the batch must not matter at all."""
    from .test_batched_tournament import RowwisePolicy
    inner = random_policy(seed=11, scale=0.05)
    players = {"m": RowwisePolicy(inner), "p": RowwisePolicy(inner)}
    specs = T.player_specs(["m", "p"], "sample", masks={"m": MASKS})
    tasks = [("m", "p", i, leg) for i in range(3) for leg in T.LEGS]
    solo = {t: _essential(T.pair_game(players, *t, seed0=500, specs=specs)) for t in tasks}
    batched = {(*r["pair"], r["game_index"], r["leg"]): _essential(r)
               for r in T.run_batched(players, tasks, 500, slots=4, specs=specs)}
    assert batched == solo
    for (a, b, i, leg), rec in solo.items():
        side = 0 if leg == "A_home" else 1               # where the masked player sat
        assert rec["masks"][side] == list(MASKS) and rec["masks"][1 - side] is None
        assert rec["behaviour"][side]["end_turn_with_player_left"] == 0


def test_player_specs_carry_masks_only_when_set():
    specs = T.player_specs(["a", "b", "bot"], "sample", bots={"bot": "contact"},
                           masks={"a": ("m3", "m1")})
    assert specs["a"]["masks"] == ["m1", "m3"]
    assert "masks" not in specs["b"] and specs["bot"] == {"bot": "contact"}
    assert T.pair_masks("a", "b", specs) == (["m1", "m3"], None)
    assert T.pair_masks("b", "a", specs) == (None, ["m1", "m3"])
    assert T.player_specs(["a", "b"], "sample") == T.player_specs(["a", "b"], "sample", masks={})
    with pytest.raises(ValueError):
        T.player_specs(["a", "bot"], "sample", bots={"bot": "contact"}, masks={"bot": ("m1",)})
    with pytest.raises(ValueError):
        T.player_specs(["a", "b"], "sample", masks={"zzz": ("m1",)})
    with pytest.raises(ValueError):
        T.player_specs(["a", "b"], "sample", masks={"a": ("m9",)})


def test_cli_refuses_a_mask_on_a_bot(tmp_path, monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    args = ["--bot", "c=contact", "--bot", "o=offense", "--pair", "c,o,2", "--seed0", "1",
            "--workers", "1", "--out-dir", str(tmp_path / "x"), "--mask", "c=m1"]
    with pytest.raises(SystemExit):
        T.main(args)


def test_cli_unmasked_manifest_has_no_mask_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.delenv(T.GAMES_PER_WORKER_ENV, raising=False)
    out = tmp_path / "bots"
    assert T.main(["--bot", "c=contact", "--bot", "o=offense", "--pair", "c,o,2",
                   "--seed0", "1", "--workers", "1", "--out-dir", str(out)]) == 0
    manifest = json.load(open(out / "manifest.json"))
    assert manifest["players"] == {"c": {"bot": "contact"}, "o": {"bot": "offense"}}
    recs = [json.loads(line) for line in open(out / "games.jsonl")]
    assert all(r["masks"] == [None, None] and len(r["behaviour"]) == 2 for r in recs)


# ---- the activation log and the sampling offset -------------------------------------------
def test_every_activation_is_filed_once_and_agrees_with_the_counts(policies):
    from play_harness import activations as AC
    p = policies["plain"]
    for masks in ((("m1",), ("m1",)), (MASKS, None)):
        rec, _ = T.play_match(p, p, 2024, masks=masks)
        for side in (0, 1):
            b = rec["behaviour"][side]
            assert sum(b["act_" + c] for c in AC.CLASSES) == b["activations"]
            # Same definition as the flat counter: END_ACTIVATION as the first choice.
            assert b["act_empty"] == b["ended_at_once"]
            assert b["act_block"] + b["act_blitz"] <= b["block_targets"]
            assert b["act_foul"] <= b["foul_targets"]
            assert b["act_pass_handoff"] <= b["pass_targets"] + b["handoff_targets"]
            assert 0 <= b["moved_measured"] <= b["act_moved"]
            assert b["act_turnover"] <= b["turnovers"]
            assert b["neg_failed"] + b["neg_empty"] <= 2 * b["neg_activations"] <= 2 * b["activations"]
            assert set(AC.KEYS) <= set(b)
    assert sum(rec["behaviour"][0]["act_" + c] for c in AC.CLASSES) > 20      # the m123 side played


def test_the_activation_log_reads_positions_and_traits():
    from play_harness import activations as AC

    class P:
        def __init__(self, x, y, location=AC.ON_PITCH, flags=0, skills=()):
            self.x, self.y, self.location, self.flags, self._skills = x, y, location, flags, skills

    class M:
        def __init__(self, players, ball, turnovers=(0, 0)):
            self.players, self.turnovers_completed = players, list(turnovers)
            self.ball = type("B", (), {"state": E.BALL_STATES.index("on_ground"),
                                       "x": ball[0], "y": ball[1], "carrier": 255})()

    class Eng:
        lib = E.load_library()

        def __init__(self):
            self.m = None
            self.slot = 0

        def match(self):
            return self.m

        def legal(self):
            return [type("L", (), {"arg": self.slot, "tuple": (A["ACTIVATE"], 0, NONE_SQ)})()]

    traits = sorted(AC.negative_trait_ids(Eng.lib))
    assert len(traits) == len(AC.NEGATIVE_TRAITS)
    real_skills_of = E.skills_of
    E.skills_of = lambda p: list(p._skills)
    try:
        eng = Eng()
        log = AC.ActivationLog(eng)
        activate = (A["ACTIVATE"], 0, NONE_SQ)
        # HOME player 0 walks from (5,5) to (8,5): 3 squares upfield, 3 nearer a ball at (12,5).
        eng.m = M({0: P(5, 5), 1: P(9, 9, skills=traits[:1])}, ball=(12, 5))
        log.on_action(0, "ACTIVATE", activate)
        log.on_action(0, "DECLARE", (A["DECLARE"], E.ACT_KINDS.index("MOVE"), NONE_SQ))
        log.on_action(0, "STEP", (A["STEP"], NONE_ARG, 1))
        log.on_action(0, "END_ACTIVATION", (A["END_ACTIVATION"], NONE_ARG, NONE_SQ))
        # Player 1 has a negative trait, ends at once and comes out Distracted.
        eng.m = M({0: P(8, 5), 1: P(9, 9, skills=traits[:1])}, ball=(12, 5))
        eng.slot = 1
        log.on_action(0, "ACTIVATE", activate)
        log.on_action(0, "DECLARE", (A["DECLARE"], E.ACT_KINDS.index("BLOCK"), NONE_SQ))
        log.on_action(0, "END_ACTIVATION", (A["END_ACTIVATION"], NONE_ARG, NONE_SQ))
        final = M({0: P(8, 5), 1: P(9, 9, flags=AC.FLAG["distracted"], skills=traits[:1])},
                  ball=(12, 5), turnovers=(1, 0))
        home, away = log.finish(final)
    finally:
        E.skills_of = real_skills_of
    assert home["act_moved"] == 1 and home["act_empty"] == 1 and home["moved_measured"] == 1
    assert home["moved_d_own_endzone"] == 3 and home["moved_d_ball"] == -3
    assert home["moved_displacement"] == 3
    assert (home["neg_activations"], home["neg_failed"], home["neg_empty"]) == (1, 1, 1)
    assert home["act_turnover"] == 1 and home["neg_turnover"] == 1    # the turn's last activation
    assert not any(away.values())


def test_a_sampling_offset_separates_the_legs_of_one_checkpoint():
    from .test_batched_tournament import RowwisePolicy
    inner = random_policy(seed=11, scale=0.05)
    players = {"a": RowwisePolicy(inner), "b": RowwisePolicy(inner)}
    tasks = [("a", "b", 0, leg) for leg in T.LEGS]
    forced = {"a": ("m1",), "b": ("m1",)}                 # m1 on both, so the games have play
    same = T.player_specs(["a", "b"], "sample", masks=forced)
    legs = [T.pair_game(players, *t, seed0=77, specs=same) for t in tasks]
    assert legs[0]["action_trail_sha256"] == legs[1]["action_trail_sha256"]
    assert legs[0]["seed_offsets"] == [0, 0] and "seed_offset" not in same["b"]
    shifted = T.player_specs(["a", "b"], "sample", masks=forced, seed_offsets={"b": 1})
    assert shifted["b"]["seed_offset"] == 1 and "seed_offset" not in shifted["a"]
    legs = [T.pair_game(players, *t, seed0=77, specs=shifted) for t in tasks]
    assert legs[0]["action_trail_sha256"] != legs[1]["action_trail_sha256"]
    assert legs[0]["seed_offsets"] == [0, 1] and legs[1]["seed_offsets"] == [1, 0]
    assert legs[0]["sampling_seeds"][1] - T.sampling_seed(77, 1) == T.SEED_OFFSET_STRIDE
    batched = {(r["leg"]): r["action_trail_sha256"]
               for r in T.run_batched(players, tasks, 77, slots=2, specs=shifted)}
    assert batched == {r["leg"]: r["action_trail_sha256"] for r in legs}
    with pytest.raises(ValueError):
        T.player_specs(["a", "bot"], "sample", bots={"bot": "contact"}, seed_offsets={"bot": 1})
    with pytest.raises(ValueError):
        T.player_specs(["a", "b"], "sample", seed_offsets={"a": -1})
