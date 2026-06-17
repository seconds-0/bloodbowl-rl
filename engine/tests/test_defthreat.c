// test_defthreat.c - R12v1 defensive scoring-lane threat acceptance tests
// (D133-A: per-player downfield reach, NOT a reachability Dijkstra).
//
// Geometry: pitch x in [0,25]. HOME scores at x=25 (bb_endzone_x(HOME)), AWAY
// scores at x=0 (bb_endzone_x(AWAY)). A standard lineman has MA 6 and
// bb_max_rushes 2, so reach_per_turn = 8.  bb_def_threat_eval(m, team) reports
// the threats the DEFENDING `team` faces from the OTHER team's deep movers
// reaching the OTHER team's scoring endzone (= our defensive endzone).
#include "bb_test.h"
#include "bb_fixtures.h"
#include "bb/bb_reachability.h"

// A standard lineman reach is 8 (MA 6 + 2 rushes). For an AWAY player at column
// x, distance to its scoring endzone (x=0) is x, so turns_to_score = ceil(x/8):
//   x<=8 -> 1 turn, 9..16 -> 2 turns, >=17 -> 3+ turns.

BB_TEST(defthreat_open_deep_fast_player_is_one_turn_threat) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    // AWAY lineman 8 squares from its endzone (x=0): exactly a 1-turn threat.
    fx_lineman(&m, BB_AWAY, 0, 8, 7);

    BB_CHECK_EQ(bb_def_threat_turns(&m, BB_AWAY * BB_TEAM_SLOTS + 0), 1);
    bb_def_threat dt = bb_def_threat_eval(&m, BB_HOME);
    BB_CHECK_EQ(dt.n_threats_1turn, 1);
    BB_CHECK_EQ(dt.n_threats_2turn, 1); // a 1-turn threat is also a 2-turn threat
}

BB_TEST(defthreat_marked_deep_player_is_mitigated) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int opp = fx_lineman(&m, BB_AWAY, 0, 8, 7); // 1-turn reach...
    fx_lineman(&m, BB_HOME, 0, 8, 8);           // ...but marked by a HOME body

    BB_CHECK(bb_is_marked(&m, opp));
    bb_def_threat dt = bb_def_threat_eval(&m, BB_HOME);
    BB_CHECK_EQ(dt.n_threats_1turn, 0); // mitigated -> not counted
    BB_CHECK_EQ(dt.n_threats_2turn, 0);
}

BB_TEST(defthreat_one_vs_two_turn_boundary) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    // x=8 -> 1 turn; x=9 -> 2 turns (just past the 1-turn budget).
    int near = fx_lineman(&m, BB_AWAY, 0, 8, 5);
    int far = fx_lineman(&m, BB_AWAY, 1, 9, 9);

    BB_CHECK_EQ(bb_def_threat_turns(&m, near), 1);
    BB_CHECK_EQ(bb_def_threat_turns(&m, far), 2);
    bb_def_threat dt = bb_def_threat_eval(&m, BB_HOME);
    BB_CHECK_EQ(dt.n_threats_1turn, 1); // only the x=8 player
    BB_CHECK_EQ(dt.n_threats_2turn, 2); // both within two turns
}

BB_TEST(defthreat_two_turn_outer_boundary) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int edge = fx_lineman(&m, BB_AWAY, 0, 16, 7); // ceil(16/8)=2
    int beyond = fx_lineman(&m, BB_AWAY, 1, 17, 9); // ceil(17/8)=3

    BB_CHECK_EQ(bb_def_threat_turns(&m, edge), 2);
    BB_CHECK_EQ(bb_def_threat_turns(&m, beyond), 3);
    bb_def_threat dt = bb_def_threat_eval(&m, BB_HOME);
    BB_CHECK_EQ(dt.n_threats_1turn, 0);
    BB_CHECK_EQ(dt.n_threats_2turn, 1); // only the x=16 player
}

// INVERSION GUARD: an AWAY player deep in its OWN half (near x=25, HOME's
// endzone) is FAR from its scoring endzone (x=0) and must NOT be a threat. If
// the distance were (wrongly) measured toward HOME's endzone, x=20 would read
// dist=5 -> a false 1-turn threat. Correct distance is 20 -> 3 turns.
BB_TEST(defthreat_endzone_direction_not_inverted) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int opp = fx_lineman(&m, BB_AWAY, 0, 20, 7);

    BB_CHECK_EQ(bb_def_threat_turns(&m, opp), 3); // dist 20 / reach 8 -> 3
    bb_def_threat dt = bb_def_threat_eval(&m, BB_HOME);
    BB_CHECK_EQ(dt.n_threats_1turn, 0);
    BB_CHECK_EQ(dt.n_threats_2turn, 0);
}

// Symmetric direction check for the other defending team: HOME scores at x=25,
// so a HOME player at x=17 is dist 8 -> a 1-turn threat to AWAY's defense, and
// bb_def_threat_eval(m, AWAY) must see it (and NOT the AWAY players).
BB_TEST(defthreat_mirrored_for_away_defense) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int home_deep = fx_lineman(&m, BB_HOME, 0, 17, 7); // dist to x=25 = 8 -> 1
    fx_lineman(&m, BB_AWAY, 0, 8, 7);                  // AWAY's own deep mover

    BB_CHECK_EQ(bb_def_threat_turns(&m, home_deep), 1);
    bb_def_threat dt_away = bb_def_threat_eval(&m, BB_AWAY); // AWAY on defense
    BB_CHECK_EQ(dt_away.n_threats_1turn, 1); // sees the HOME deep mover
    BB_CHECK_EQ(dt_away.n_threats_2turn, 1);
}

BB_TEST(defthreat_prone_stunned_offpitch_excluded) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int prone = fx_lineman(&m, BB_AWAY, 0, 8, 4);
    int stunned = fx_lineman(&m, BB_AWAY, 1, 8, 6);
    int reserve = fx_lineman(&m, BB_AWAY, 2, 8, 8);
    m.players[prone].stance = BB_STANCE_PRONE;
    m.players[stunned].stance = BB_STANCE_STUNNED;
    m.players[reserve].location = BB_LOC_RESERVES;

    BB_CHECK_EQ(bb_def_threat_turns(&m, prone), -1);
    BB_CHECK_EQ(bb_def_threat_turns(&m, stunned), -1);
    BB_CHECK_EQ(bb_def_threat_turns(&m, reserve), -1);
    bb_def_threat dt = bb_def_threat_eval(&m, BB_HOME);
    BB_CHECK_EQ(dt.n_threats_1turn, 0);
    BB_CHECK_EQ(dt.n_threats_2turn, 0);
}

BB_TEST(defthreat_rooted_player_excluded) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int opp = fx_lineman(&m, BB_AWAY, 0, 8, 7); // would be a 1-turn threat
    m.players[opp].flags |= BB_PF_ROOTED;       // ...but cannot move

    BB_CHECK_EQ(bb_def_threat_turns(&m, opp), -1);
    bb_def_threat dt = bb_def_threat_eval(&m, BB_HOME);
    BB_CHECK_EQ(dt.n_threats_1turn, 0);
    BB_CHECK_EQ(dt.n_threats_2turn, 0);
}

BB_TEST(defthreat_sprint_extends_reach) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    // x=9: lineman reach 8 -> 2 turns; with Sprint reach 9 -> 1 turn.
    int opp = fx_lineman(&m, BB_AWAY, 0, 9, 7);
    BB_CHECK_EQ(bb_def_threat_turns(&m, opp), 2);
    fx_give_skill(&m, opp, BB_SK_SPRINT);
    BB_CHECK_EQ(bb_def_threat_turns(&m, opp), 1);

    bb_def_threat dt = bb_def_threat_eval(&m, BB_HOME);
    BB_CHECK_EQ(dt.n_threats_1turn, 1);
}

BB_TEST(defthreat_counts_multiple_unmarked_movers) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    fx_lineman(&m, BB_AWAY, 0, 4, 3);  // 1 turn
    fx_lineman(&m, BB_AWAY, 1, 8, 7);  // 1 turn
    fx_lineman(&m, BB_AWAY, 2, 12, 11); // 2 turns
    fx_lineman(&m, BB_AWAY, 3, 24, 13); // 3 turns (not a threat)

    bb_def_threat dt = bb_def_threat_eval(&m, BB_HOME);
    BB_CHECK_EQ(dt.n_threats_1turn, 2);
    BB_CHECK_EQ(dt.n_threats_2turn, 3);
}

// Defending team's OWN players are never their own threat (only the opponent's
// deep movers are counted).
BB_TEST(defthreat_own_players_not_counted) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    fx_lineman(&m, BB_HOME, 0, 8, 7); // a HOME mover near AWAY's endzone

    bb_def_threat dt = bb_def_threat_eval(&m, BB_HOME); // HOME on defense
    BB_CHECK_EQ(dt.n_threats_1turn, 0);
    BB_CHECK_EQ(dt.n_threats_2turn, 0);
}

BB_TEST(defthreat_invalid_team_returns_zero) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    fx_lineman(&m, BB_AWAY, 0, 8, 7);

    bb_def_threat dt = bb_def_threat_eval(&m, 2); // not HOME/AWAY
    BB_CHECK_EQ(dt.n_threats_1turn, 0);
    BB_CHECK_EQ(dt.n_threats_2turn, 0);
}

// A player standing ON its own endzone column (dist 0) is trivially a 1-turn
// threat (turns_to_score = 0 -> counted at every horizon).
BB_TEST(defthreat_on_endzone_is_zero_turns) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int opp = fx_lineman(&m, BB_AWAY, 0, 0, 7); // already on x=0

    BB_CHECK_EQ(bb_def_threat_turns(&m, opp), 0); // dist 0 -> 0 turns
    bb_def_threat dt = bb_def_threat_eval(&m, BB_HOME);
    BB_CHECK_EQ(dt.n_threats_1turn, 1); // 0 <= 1
    BB_CHECK_EQ(dt.n_threats_2turn, 1);
}
