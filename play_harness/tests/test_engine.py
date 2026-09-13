import random

import numpy as np

from play_harness import engine as E


def test_library_abi_and_layout(lib):
    assert lib.bbp_abi_version() == E.ABI_VERSION
    assert lib.bbp_obs_size() == E.OBS_SIZE
    assert lib.bbp_obs_version() == 6
    assert lib.bbp_team_count() == 30


def test_random_matches_complete_naturally(lib):
    for seed in (3, 4):
        eng = E.Engine(seed)
        rng = random.Random(seed)
        while True:
            rc = eng.step(*rng.choice(eng.legal()).tuple)
            assert rc in (E.STEP_OK, E.STEP_TERMINAL)
            if rc == E.STEP_TERMINAL:
                break
        final = eng.final_match()
        c = eng.counters()
        assert final.status == E.STATUS_MATCH_OVER
        assert final.half == 2 and list(final.turn) == [8, 8]
        assert c["decisions_at_terminal"] < 4096
        assert c["illegal"] == c["projection_collision"] == c["error_episodes"] == 0
        assert c["rejected_submissions"] == 0


def test_out_of_support_tuple_is_refused_without_abort(lib):
    eng = E.Engine(11)
    before = eng.digest()
    legal = {la.tuple for la in eng.legal()}
    bogus = (E.A["END_TURN"], E.ARG_NONE, E.SQ_NONE)
    assert bogus not in legal
    assert eng.step(*bogus) == E.STEP_REJECTED
    assert eng.step(E.A["STEP"], 40, 999) == E.STEP_REJECTED
    assert eng.digest() == before
    c = eng.counters()
    assert c["rejected_submissions"] == 2 and c["illegal"] == 0
    assert eng.step(*eng.legal()[0].tuple) in (E.STEP_OK, E.STEP_TERMINAL)


def test_joint_support_is_the_projected_legal_set(lib):
    eng = E.Engine(21)
    rng = random.Random(0)
    for _ in range(300):
        dec = eng.decision_team
        support = {E.unpack_tuple(v) for v in eng.joint_support(dec)}
        assert support == {la.tuple for la in eng.legal()}
        waiting = eng.joint_support(1 - dec)
        assert [E.unpack_tuple(v) for v in waiting] == [(0, 32, 390)]
        obs_dec, obs_wait = eng.obs(dec), eng.obs(1 - dec)
        assert obs_dec[768 + 10] == 1 and obs_wait[768 + 10] == 0
        if eng.step(*rng.choice(eng.legal()).tuple) == E.STEP_TERMINAL:
            break


def test_names_and_state_are_readable(lib):
    eng = E.Engine(5, home_team=13, away_team=22)
    m = eng.match()
    assert eng.team_display(m.team_id[0]) == "Human"
    assert eng.team_display(m.team_id[1]) == "Orc"
    on_roster = [p for p in m.players if p.location != 5]
    assert len(on_roster) >= 22
    assert all(eng.position_display(m.team_id[i >> 4], m.players[i].position_id)
               for i in range(32) if m.players[i].location != 5)
    assert isinstance(eng.obs(0), np.ndarray)
