// test_reachability.c - R6v1 carrier-exposure reachability acceptance tests.
#include "bb_test.h"
#include "bb_fixtures.h"
#include "bb/bb_reachability.h"

static void reach_fixture(bb_match* m, int* carrier) {
    fx_match_midturn(m, BB_HOME, 0);
    *carrier = fx_lineman(m, BB_HOME, 0, 13, 7);
    fx_ball_held(m, *carrier);
}

static bb_reach_cost field_cost_to(const bb_match* m, int mover, int x, int y) {
    bb_reach_field field;
    bb_reach_field_compute(m, mover, &field);
    return field.cost[x][y];
}

BB_TEST(reach_open_field_free_adjacent_access) {
    bb_match m;
    int carrier;
    reach_fixture(&m, &carrier);
    (void)carrier;
    fx_lineman(&m, BB_AWAY, 0, 13, 3);

    bb_reach_access access = bb_min_access_cost(&m, BB_AWAY, 13, 7);
    BB_CHECK(access.any_free);
    bb_carrier_exposure ex = bb_carrier_exposure_eval(&m, BB_HOME);
    BB_CHECK(ex.full);
    BB_CHECK(!ex.soft);
}

BB_TEST(reach_cage_open_squares_require_dodge) {
    bb_match m;
    int carrier;
    reach_fixture(&m, &carrier);
    (void)carrier;
    int opp = fx_lineman(&m, BB_AWAY, 0, 13, 3);

    // Leave the carrier's adjacent squares open, but put a full-width screen
    // at y=5. Any northern approach to the adjacent row must leave marked
    // squares, so it is not a free walk-up.
    for (int i = 0; i < 13; i++) {
        fx_lineman(&m, BB_HOME, i + 1, i * 2, 5);
    }

    BB_CHECK(!bb_is_marked(&m, carrier));
    bb_reach_cost c = field_cost_to(&m, opp, 13, 6);
    BB_CHECK(c.dodges != BB_REACH_UNREACHABLE);
    BB_CHECK(c.dodges >= 1);
    bb_reach_access access = bb_min_access_cost(&m, BB_AWAY, 13, 7);
    BB_CHECK(!access.any_free);
}

BB_TEST(reach_marked_carrier_is_full_exposure) {
    bb_match m;
    int carrier;
    reach_fixture(&m, &carrier);
    fx_lineman(&m, BB_AWAY, 0, 13, 8);

    BB_CHECK(bb_is_marked(&m, carrier));
    bb_carrier_exposure ex = bb_carrier_exposure_eval(&m, BB_HOME);
    BB_CHECK(ex.full);
    BB_CHECK(!ex.soft);
}

BB_TEST(reach_one_dodge_buffer_is_soft) {
    bb_match m;
    int carrier;
    reach_fixture(&m, &carrier);
    int opp = fx_lineman(&m, BB_AWAY, 0, 13, 3);
    fx_lineman(&m, BB_HOME, 1, 12, 3); // marks the opponent's start square

    bb_reach_cost c = field_cost_to(&m, opp, 13, 6);
    BB_CHECK_EQ(c.dodges, 1);
    BB_CHECK_EQ(c.gfis, 0);
    bb_reach_access access = bb_min_access_cost(&m, BB_AWAY, 13, 7);
    BB_CHECK(!access.any_free);
    BB_CHECK(access.any_one_roll);
    bb_carrier_exposure ex = bb_carrier_exposure_eval(&m, BB_HOME);
    BB_CHECK(!ex.full);
    BB_CHECK(ex.soft);
}

BB_TEST(reach_one_gfi_gate_is_soft_not_free) {
    bb_match m;
    int carrier;
    reach_fixture(&m, &carrier);
    int opp = fx_lineman(&m, BB_AWAY, 0, 5, 7);

    bb_reach_cost c = field_cost_to(&m, opp, 12, 7);
    BB_CHECK_EQ(c.dodges, 0);
    BB_CHECK_EQ(c.gfis, 1);
    bb_reach_access access = bb_min_access_cost(&m, BB_AWAY, 13, 7);
    BB_CHECK(!access.any_free);
    BB_CHECK(access.any_one_roll);
}

BB_TEST(reach_aggregation_keeps_one_roll_when_other_path_is_two_gfi) {
    bb_match m;
    int carrier;
    reach_fixture(&m, &carrier);
    (void)carrier;
    fx_lineman(&m, BB_AWAY, 0, 4, 7); // two GFIs to the nearest adjacent square
    int dodger = fx_lineman(&m, BB_AWAY, 1, 13, 3);
    fx_lineman(&m, BB_HOME, 1, 12, 3);

    bb_reach_cost c0 = field_cost_to(&m, BB_AWAY * BB_TEAM_SLOTS + 0, 12, 7);
    BB_CHECK_EQ(c0.dodges, 0);
    BB_CHECK_EQ(c0.gfis, 2);
    bb_reach_cost c1 = field_cost_to(&m, dodger, 13, 6);
    BB_CHECK_EQ(c1.dodges, 1);
    BB_CHECK_EQ(c1.gfis, 0);
    bb_reach_access access = bb_min_access_cost(&m, BB_AWAY, 13, 7);
    BB_CHECK(!access.any_free);
    BB_CHECK(access.any_one_roll);
    bb_carrier_exposure ex = bb_carrier_exposure_eval(&m, BB_HOME);
    BB_CHECK(!ex.full);
    BB_CHECK(ex.soft);
}

BB_TEST(reach_far_opponent_unreachable) {
    bb_match m;
    int carrier;
    reach_fixture(&m, &carrier);
    fx_lineman(&m, BB_AWAY, 0, 3, 7);

    bb_reach_access access = bb_min_access_cost(&m, BB_AWAY, 13, 7);
    BB_CHECK(!access.any_free);
    BB_CHECK(!access.any_one_roll);
}

BB_TEST(reach_endzone_exemption_suppresses_exposure) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int carrier = fx_lineman(&m, BB_HOME, 0, 24, 7);
    fx_ball_held(&m, carrier);
    fx_lineman(&m, BB_AWAY, 0, 24, 8);

    BB_CHECK(bb_is_marked(&m, carrier));
    BB_CHECK(bb_carrier_exposure_endzone_exempt(&m, carrier));
    bb_carrier_exposure ex = bb_carrier_exposure_eval(&m, BB_HOME);
    BB_CHECK(!ex.full);
    BB_CHECK(!ex.soft);
}

BB_TEST(reach_endzone_exemption_is_sprint_aware_and_not_rooted) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int carrier = fx_player(&m, BB_HOME, 0, 21, 7, 1, 3, 3, 4, 9);
    fx_ball_held(&m, carrier);

    BB_CHECK(!bb_carrier_exposure_endzone_exempt(&m, carrier));
    fx_give_skill(&m, carrier, BB_SK_SPRINT);
    BB_CHECK(bb_carrier_exposure_endzone_exempt(&m, carrier));
    m.players[carrier].flags |= BB_PF_ROOTED;
    BB_CHECK(!bb_carrier_exposure_endzone_exempt(&m, carrier));
}

BB_TEST(reach_prone_opponents_ignored) {
    bb_match m;
    int carrier;
    reach_fixture(&m, &carrier);
    (void)carrier;
    int opp = fx_lineman(&m, BB_AWAY, 0, 13, 3);
    m.players[opp].stance = BB_STANCE_PRONE;

    bb_reach_access access = bb_min_access_cost(&m, BB_AWAY, 13, 7);
    BB_CHECK(!access.any_free);
    BB_CHECK(!access.any_one_roll);
}

BB_TEST(reach_diagonal_adjacent_counts_as_marked) {
    bb_match m;
    int carrier;
    reach_fixture(&m, &carrier);
    fx_lineman(&m, BB_AWAY, 0, 14, 8);

    BB_CHECK(bb_is_marked(&m, carrier));
    bb_carrier_exposure ex = bb_carrier_exposure_eval(&m, BB_HOME);
    BB_CHECK(ex.full);
    BB_CHECK(!ex.soft);
}

BB_TEST(reach_prone_carrier_does_not_fire) {
    bb_match m;
    int carrier;
    reach_fixture(&m, &carrier);
    fx_lineman(&m, BB_AWAY, 0, 13, 8);
    m.players[carrier].stance = BB_STANCE_PRONE;

    BB_CHECK(bb_is_marked(&m, carrier));
    bb_carrier_exposure ex = bb_carrier_exposure_eval(&m, BB_HOME);
    BB_CHECK(!ex.full);
    BB_CHECK(!ex.soft);
}

BB_TEST(reach_rooted_adjacent_opponent_still_marks) {
    bb_match m;
    int carrier;
    reach_fixture(&m, &carrier);
    int opp = fx_lineman(&m, BB_AWAY, 0, 13, 8);
    m.players[opp].flags |= BB_PF_ROOTED;

    BB_CHECK(bb_is_marked(&m, carrier));
    bb_reach_access access = bb_min_access_cost(&m, BB_AWAY, 13, 7);
    BB_CHECK(!access.any_free);
    BB_CHECK(!access.any_one_roll);
    bb_carrier_exposure ex = bb_carrier_exposure_eval(&m, BB_HOME);
    BB_CHECK(ex.full);
}

BB_TEST(reach_rooted_non_adjacent_opponent_excluded) {
    bb_match m;
    int carrier;
    reach_fixture(&m, &carrier);
    (void)carrier;
    int opp = fx_lineman(&m, BB_AWAY, 0, 13, 5);
    m.players[opp].flags |= BB_PF_ROOTED;

    bb_reach_access access = bb_min_access_cost(&m, BB_AWAY, 13, 7);
    BB_CHECK(!access.any_free);
    BB_CHECK(!access.any_one_roll);
}
