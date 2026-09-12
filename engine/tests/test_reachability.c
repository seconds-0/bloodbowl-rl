// test_reachability.c - R6v1 carrier-exposure reachability acceptance tests.
#include "bb_test.h"
#include "bb_fixtures.h"
#include "bb/bb_blockev.h"
#include "bb/bb_hooks.h"
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

// Stalling feasibility is a read-only query. In particular, checking an
// activation gate must not count the Skill as exercised before any action or
// die is actually resolved.
BB_TEST(reach_stalling_gate_query_has_no_coverage_side_effect) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int carrier = fx_lineman(&m, BB_HOME, 0, 24, 7);
    fx_give_skill(&m, carrier, BB_SK_BONE_HEAD);
    fx_ball_held(&m, carrier);

    uint64_t before = bb_skill_exercised[BB_SK_BONE_HEAD];
    BB_CHECK(!bb_can_score_without_dice(&m, carrier));
    BB_CHECK_EQ(bb_skill_exercised[BB_SK_BONE_HEAD], before);
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

static void threat_near(float got, float want) {
    float d = got - want;
    if (d < 0.0f) d = -d;
    BB_CHECK(d < 1e-5f);
}

static void threat_fixture(bb_match* m, int* carrier) {
    fx_match_midturn(m, BB_HOME, 0);
    *carrier = fx_lineman(m, BB_HOME, 0, 13, 7);
    fx_ball_held(m, *carrier);
}

static int threat_prone_lineman(bb_match* m, int team, int idx, int x, int y) {
    int slot = fx_lineman(m, team, idx, x, y);
    m->players[slot].stance = BB_STANCE_PRONE;
    return slot;
}

static float threat_block_p_def_down_at(const bb_match* m, int enemy,
                                        int carrier, int x, int y) {
    bb_match sim = *m;
    bb_place(&sim, enemy, x, y);
    bb_blockev ev;
    bb_block_ev(&sim, enemy, carrier, 1, NULL, &ev);
    return ev.p_def_down;
}

BB_TEST(carrier_threat_prone_stunned_enemies_zero) {
    bb_match m;
    int carrier;
    threat_fixture(&m, &carrier);
    (void)carrier;
    int prone = fx_lineman(&m, BB_AWAY, 0, 13, 8);
    int stunned = fx_lineman(&m, BB_AWAY, 1, 14, 7);
    m.players[prone].stance = BB_STANCE_PRONE;
    m.players[stunned].stance = BB_STANCE_STUNNED;

    bb_carrier_threat_breakdown th;
    float t = bb_carrier_threat_eval(&m, &th);
    threat_near(t, 0.0f);
    threat_near(th.uncapped_total, 0.0f);
    BB_CHECK_EQ(th.enemies_considered, 0);
}

BB_TEST(carrier_threat_adjacent_enemy_is_free_block_excess) {
    bb_match m;
    int carrier;
    threat_fixture(&m, &carrier);
    int enemy = fx_lineman(&m, BB_AWAY, 0, 13, 8);

    bb_blockev ev;
    bb_block_ev(&m, enemy, carrier, 0, NULL, &ev);
    float want = ev.p_def_down - bb_carrier_threat_baseline();
    if (want < 0.0f) want = 0.0f;

    bb_carrier_threat_breakdown th;
    float t = bb_carrier_threat_eval(&m, &th);
    threat_near(t, want);
    threat_near(th.adjacent_excess, want);
    threat_near(th.blitz_excess, 0.0f);
    BB_CHECK_EQ(th.adjacent_enemies, 1);
}

BB_TEST(carrier_threat_three_dodge_path_much_less_than_one_dodge) {
    bb_match one;
    int c1;
    threat_fixture(&one, &c1);
    int e1 = fx_lineman(&one, BB_AWAY, 0, 13, 2);
    fx_lineman(&one, BB_HOME, 1, 12, 2); // marks only the origin
    bb_reach_field f1;
    bb_reach_field_compute(&one, e1, &f1);
    BB_CHECK_EQ(f1.cost[13][6].dodges, 1);

    bb_match three;
    int c3;
    threat_fixture(&three, &c3);
    int e3 = fx_lineman(&three, BB_AWAY, 0, 13, 2);
    int idx = 1;
    for (int y = 2; y <= 5; y++) {
        fx_lineman(&three, BB_HOME, idx++, 12, y);
        fx_lineman(&three, BB_HOME, idx++, 14, y);
    }
    bb_reach_field f3;
    bb_reach_field_compute(&three, e3, &f3);
    BB_CHECK(f3.cost[13][6].dodges >= 3);

    bb_carrier_threat_breakdown th1, th3;
    bb_carrier_threat_eval(&one, &th1);
    bb_carrier_threat_eval(&three, &th3);
    BB_CHECK(th1.blitz_excess > 0.0f);
    BB_CHECK(th3.blitz_excess < th1.blitz_excess * 0.6f);
}

BB_TEST(carrier_threat_uses_max_of_cost_and_shortest_path_success) {
    bb_match m;
    int carrier;
    threat_fixture(&m, &carrier);
    int enemy = fx_player(&m, BB_AWAY, 0, 13, 2, 4, 3, 2, 4, 9);
    fx_give_skill(&m, enemy, BB_SK_DODGE);
    fx_give_skill(&m, enemy, BB_SK_TITCHY);

    fx_lineman(&m, BB_HOME, 1, 11, 5);
    fx_lineman(&m, BB_HOME, 2, 12, 4);
    threat_prone_lineman(&m, BB_HOME, 3, 13, 5);
    threat_prone_lineman(&m, BB_HOME, 4, 14, 3);
    threat_prone_lineman(&m, BB_HOME, 5, 14, 4);
    threat_prone_lineman(&m, BB_HOME, 6, 12, 6);
    threat_prone_lineman(&m, BB_HOME, 7, 14, 6);
    threat_prone_lineman(&m, BB_HOME, 8, 12, 7);
    threat_prone_lineman(&m, BB_HOME, 9, 14, 7);
    threat_prone_lineman(&m, BB_HOME, 10, 12, 8);
    threat_prone_lineman(&m, BB_HOME, 11, 13, 8);
    threat_prone_lineman(&m, BB_HOME, 12, 14, 8);

    bb_reach_field field;
    bb_reach_field_compute(&m, enemy, &field);
    BB_CHECK_EQ(field.cost[13][6].dodges, 0);
    BB_CHECK_EQ(field.cost[13][6].gfis, 1);

    float pkd = threat_block_p_def_down_at(&m, enemy, carrier, 13, 6);
    float want = (25.0f / 27.0f) * pkd - bb_carrier_threat_baseline();
    if (want < 0.0f) want = 0.0f;

    bb_carrier_threat_breakdown th;
    float t = bb_carrier_threat_eval(&m, &th);
    threat_near(th.blitz_excess, want);
    threat_near(t, want);
    BB_CHECK_EQ(th.reachable_enemies, 1);
}

BB_TEST(carrier_threat_checks_all_adjacent_squares_in_best_cost_tier) {
    bb_match m;
    int carrier;
    threat_fixture(&m, &carrier);
    int enemy = fx_lineman(&m, BB_AWAY, 0, 13, 3);

    fx_lineman(&m, BB_HOME, 1, 12, 7); // defensive assist vs north square only
    threat_prone_lineman(&m, BB_HOME, 2, 12, 6);
    threat_prone_lineman(&m, BB_HOME, 3, 14, 6);
    threat_prone_lineman(&m, BB_HOME, 4, 12, 8);
    threat_prone_lineman(&m, BB_HOME, 5, 13, 8);
    threat_prone_lineman(&m, BB_HOME, 6, 14, 8);

    bb_reach_field field;
    bb_reach_field_compute(&m, enemy, &field);
    BB_CHECK_EQ(field.cost[13][6].dodges, 0);
    BB_CHECK_EQ(field.cost[13][6].gfis, 0);
    BB_CHECK_EQ(field.cost[14][7].dodges, 0);
    BB_CHECK_EQ(field.cost[14][7].gfis, 0);
    BB_CHECK(field.len[14][7] > field.len[13][6]);

    float short_pkd = threat_block_p_def_down_at(&m, enemy, carrier, 13, 6);
    float long_pkd = threat_block_p_def_down_at(&m, enemy, carrier, 14, 7);
    BB_CHECK(long_pkd > short_pkd);
    float want = long_pkd - bb_carrier_threat_baseline();
    if (want < 0.0f) want = 0.0f;

    bb_carrier_threat_breakdown th;
    float t = bb_carrier_threat_eval(&m, &th);
    threat_near(th.blitz_excess, want);
    threat_near(t, want);
    BB_CHECK_EQ(th.reachable_enemies, 1);
}

BB_TEST(carrier_threat_baseline_dive_yields_no_excess) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int carrier = fx_lineman(&m, BB_HOME, 0, 12, 7);
    m.players[carrier].st = 4;
    fx_ball_held(&m, carrier);
    int diver = fx_lineman(&m, BB_AWAY, 0, 10, 7);
    fx_give_skill(&m, diver, BB_SK_DODGE);

    fx_lineman(&m, BB_HOME, 1, 10, 6); // origin marker
    fx_lineman(&m, BB_HOME, 2, 11, 6); // destination marker + assist
    fx_lineman(&m, BB_HOME, 3, 11, 8); // destination marker + assist
    int b1 = fx_lineman(&m, BB_HOME, 4, 12, 6);
    int b2 = fx_lineman(&m, BB_HOME, 5, 13, 6);
    int b3 = fx_lineman(&m, BB_HOME, 6, 13, 7);
    int b4 = fx_lineman(&m, BB_HOME, 7, 12, 8);
    int b5 = fx_lineman(&m, BB_HOME, 8, 13, 8);
    m.players[b1].stance = BB_STANCE_PRONE;
    m.players[b2].stance = BB_STANCE_PRONE;
    m.players[b3].stance = BB_STANCE_PRONE;
    m.players[b4].stance = BB_STANCE_PRONE;
    m.players[b5].stance = BB_STANCE_PRONE;

    bb_carrier_threat_breakdown th;
    float t = bb_carrier_threat_eval(&m, &th);
    BB_CHECK(th.reachable_enemies == 1);
    BB_CHECK(t < 1e-5f);
    BB_CHECK(th.uncapped_total < 1e-5f);
}

BB_TEST(carrier_threat_caps_at_tmax) {
    bb_match m;
    int carrier;
    threat_fixture(&m, &carrier);
    m.players[carrier].st = 1;
    int idx = 0;
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            if (!dx && !dy) continue;
            int s = fx_player(&m, BB_AWAY, idx++, 13 + dx, 7 + dy,
                              6, 6, 3, 4, 9);
            fx_give_skill(&m, s, BB_SK_BLOCK);
        }
    }

    bb_carrier_threat_breakdown th;
    float t = bb_carrier_threat_eval(&m, &th);
    BB_CHECK(th.uncapped_total > BB_CARRIER_THREAT_T_MAX);
    threat_near(t, BB_CARRIER_THREAT_T_MAX);
    threat_near(th.capped_total, BB_CARRIER_THREAT_T_MAX);
}

// --- bb_reach_any_target: differential against the full reach field --------

static bool reach_any_reference(const bb_match* m, int mover,
                                const uint8_t target[BB_PITCH_LEN][BB_PITCH_WID]) {
    bb_reach_field field;
    bb_reach_field_compute(m, mover, &field);
    for (int x = 0; x < BB_PITCH_LEN; x++) {
        for (int y = 0; y < BB_PITCH_WID; y++) {
            if (target[x][y] && field.cost[x][y].dodges != BB_REACH_UNREACHABLE) {
                return true;
            }
        }
    }
    return false;
}

static int reach_rnd(bb_rng* r, int n) {
    return (int)(bb_rng_next(r) % (uint32_t)n);
}

// Random crowded boards: mixed stances, NO_TZ/DISTRACTED markers (which do not
// mark squares), ROOTED movers, Sprint, partially spent movement and the
// 39-square budget cap, so dodge-vs-length trade-offs at the budget edge occur.
static int reach_random_board(bb_match* m, bb_rng* r, int placed[BB_NUM_PLAYERS]) {
    fx_match_midturn(m, reach_rnd(r, 2), 0);
    int count = reach_rnd(r, 23);
    int next_idx[2] = {0, 0};
    int n = 0;
    for (int i = 0; i < count; i++) {
        int team = reach_rnd(r, 2);
        if (next_idx[team] >= BB_TEAM_SLOTS) continue;
        int x, y;
        do {
            x = reach_rnd(r, BB_PITCH_LEN);
            y = reach_rnd(r, BB_PITCH_WID);
        } while (m->grid[x][y]);
        int ma = 1 + reach_rnd(r, 9);
        if (reach_rnd(r, 40) == 0) ma = 45;
        int slot = fx_player(m, team, next_idx[team]++, x, y, ma, 3, 3, 4, 9);
        bb_player* p = &m->players[slot];
        int st = reach_rnd(r, 10);
        if (st == 0) p->stance = BB_STANCE_PRONE;
        else if (st == 1) p->stance = BB_STANCE_STUNNED;
        if (reach_rnd(r, 8) == 0) p->flags |= BB_PF_NO_TZ;
        if (reach_rnd(r, 8) == 0) p->flags |= BB_PF_DISTRACTED;
        if (reach_rnd(r, 12) == 0) p->flags |= BB_PF_ROOTED;
        if (reach_rnd(r, 4) == 0) fx_give_skill(m, slot, BB_SK_SPRINT);
        p->moved = (uint8_t)reach_rnd(r, ma + 3);
        p->rushes = (uint8_t)reach_rnd(r, 4);
        placed[n++] = slot;
    }
    return n;
}

BB_TEST(reach_any_target_matches_field_per_square_on_random_boards) {
    bb_rng r;
    bb_rng_seed(&r, 0xB117Cull, 11);
    long mismatches = 0, reachable = 0, unreachable = 0;
    for (int b = 0; b < 400; b++) {
        bb_match m;
        int placed[BB_NUM_PLAYERS];
        int n = reach_random_board(&m, &r, placed);
        int mover = n > 0 && reach_rnd(&r, 16) ? placed[reach_rnd(&r, n)]
                                               : reach_rnd(&r, BB_NUM_PLAYERS + 2) - 1;
        bb_reach_field field;
        bb_reach_field_compute(&m, mover, &field);
        for (int x = 0; x < BB_PITCH_LEN; x++) {
            for (int y = 0; y < BB_PITCH_WID; y++) {
                uint8_t target[BB_PITCH_LEN][BB_PITCH_WID];
                memset(target, 0, sizeof target);
                target[x][y] = 1;
                bool want = field.cost[x][y].dodges != BB_REACH_UNREACHABLE;
                bool got = bb_reach_any_target(&m, mover, target);
                if (got != want) mismatches++;
                if (want) reachable++;
                else unreachable++;
            }
        }
    }
    BB_CHECK_EQ(mismatches, 0);
    BB_CHECK(reachable > 10000);
    BB_CHECK(unreachable > 10000);
}

BB_TEST(reach_any_target_matches_field_for_blitz_and_random_masks) {
    bb_rng r;
    bb_rng_seed(&r, 0xB117Dull, 12);
    long mismatches = 0, hits = 0, misses = 0;
    for (int b = 0; b < 1500; b++) {
        bb_match m;
        int placed[BB_NUM_PLAYERS];
        int n = reach_random_board(&m, &r, placed);
        for (int i = 0; i < n; i++) {
            int mover = placed[i];
            uint8_t blitz[BB_PITCH_LEN][BB_PITCH_WID];
            memset(blitz, 0, sizeof blitz);
            int opp = 1 - BB_TEAM_OF(mover);
            for (int s = opp * BB_TEAM_SLOTS; s < (opp + 1) * BB_TEAM_SLOTS; s++) {
                const bb_player* q = &m.players[s];
                if (q->location != BB_LOC_ON_PITCH) continue;
                if (q->stance != BB_STANCE_STANDING) continue;
                for (int dx = -1; dx <= 1; dx++) {
                    for (int dy = -1; dy <= 1; dy++) {
                        if (!dx && !dy) continue;
                        if (bb_on_pitch_xy(q->x + dx, q->y + dy)) {
                            blitz[q->x + dx][q->y + dy] = 1;
                        }
                    }
                }
            }
            uint8_t sparse[BB_PITCH_LEN][BB_PITCH_WID];
            int density = 1 + reach_rnd(&r, 60);
            for (int x = 0; x < BB_PITCH_LEN; x++) {
                for (int y = 0; y < BB_PITCH_WID; y++) {
                    sparse[x][y] = reach_rnd(&r, 400) < density;
                }
            }
            bool want = reach_any_reference(&m, mover, blitz);
            if (bb_reach_any_target(&m, mover, blitz) != want) mismatches++;
            if (want) hits++;
            else misses++;
            want = reach_any_reference(&m, mover, sparse);
            if (bb_reach_any_target(&m, mover, sparse) != want) mismatches++;
            if (want) hits++;
            else misses++;
        }
    }
    BB_CHECK_EQ(mismatches, 0);
    BB_CHECK(hits > 1000);
    BB_CHECK(misses > 1000);
}

// Pocket square (8,6) opens only onto u=(7,7). The mover reaches u in 2 steps
// through a marked square (1 dodge) or in 4 dodge-free steps. The field keeps
// the dodge-free label, which uses the whole 4-square budget, so u is never
// expanded and the pocket is unreachable although a step-count search reaches
// it in 3. One more rush opens it.
static void reach_budget_edge_fixture(bb_match* m, int* mover) {
    fx_match_midturn(m, BB_HOME, 0);
    *mover = fx_player(m, BB_HOME, 0, 5, 7, 4, 3, 3, 4, 9);
    m->players[*mover].rushes = 2;
    fx_lineman(m, BB_AWAY, 0, 7, 6); // marks (6,7) and u
    static const int blockers[7][2] = {
        {6, 8}, {7, 5}, {8, 5}, {9, 5}, {9, 6}, {8, 7}, {9, 7},
    };
    for (int i = 0; i < 7; i++) {
        fx_lineman(m, BB_HOME, 1 + i, blockers[i][0], blockers[i][1]);
    }
}

static long reach_any_target_square_mismatches(const bb_match* m, int mover) {
    bb_reach_field field;
    bb_reach_field_compute(m, mover, &field);
    long mismatches = 0;
    for (int x = 0; x < BB_PITCH_LEN; x++) {
        for (int y = 0; y < BB_PITCH_WID; y++) {
            uint8_t target[BB_PITCH_LEN][BB_PITCH_WID];
            memset(target, 0, sizeof target);
            target[x][y] = 1;
            bool want = field.cost[x][y].dodges != BB_REACH_UNREACHABLE;
            if (bb_reach_any_target(m, mover, target) != want) mismatches++;
        }
    }
    return mismatches;
}

BB_TEST(reach_any_target_keeps_dodge_first_budget_semantics) {
    bb_match m;
    int mover;
    reach_budget_edge_fixture(&m, &mover);
    uint8_t pocket[BB_PITCH_LEN][BB_PITCH_WID];
    memset(pocket, 0, sizeof pocket);
    pocket[8][6] = 1;

    bb_reach_field field;
    bb_reach_field_compute(&m, mover, &field);
    BB_CHECK_EQ(field.cost[7][7].dodges, 0);
    BB_CHECK_EQ(field.len[7][7], 4);
    BB_CHECK_EQ(field.cost[8][6].dodges, BB_REACH_UNREACHABLE);
    BB_CHECK(!bb_reach_any_target(&m, mover, pocket));
    BB_CHECK_EQ(reach_any_target_square_mismatches(&m, mover), 0);

    m.players[mover].rushes = 1;
    bb_reach_field_compute(&m, mover, &field);
    BB_CHECK_EQ(field.cost[8][6].dodges, 1);
    BB_CHECK_EQ(field.cost[8][6].gfis, 1);
    BB_CHECK(bb_reach_any_target(&m, mover, pocket));
    BB_CHECK_EQ(reach_any_target_square_mismatches(&m, mover), 0);
}
