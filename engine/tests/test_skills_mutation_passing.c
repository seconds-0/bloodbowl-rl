// test_skills_mutation_passing.c — BB2025 rulebook tests for the MUTATION and
// PASSING category skills registered in skills_mutation_passing.c
// (Prehensile Tail, Very Long Legs).
//
// Every test encodes what the rulebook mirror says (tight quote above each
// test). Authoritative source, under docs/vendor/bloodbowlbase/
// bloodbowlbase.ru/bb2025/core_rules/:
//   SK  = skills_and_traits/index.html (Mutation, Passing)
//   FAQ = latest_faq/index.html (May 2026)
//
// Scripted dice (bb_rng_script) choose every die face, so each modifier is
// asserted exactly: a roll that only passes WITH the skill's modifier, and a
// roll that only fails WITHOUT it.
#include "bb/bb_match.h"
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb_fixtures.h"
#include "bb_test.h"

static bb_action mk(int type, int arg, int x, int y) {
    bb_action a = {(uint8_t)type, (uint8_t)arg, (uint8_t)x, (uint8_t)y};
    return a;
}

// Activate `slot` and declare action `kind`; leaves the action machine waiting.
static bb_status fx_activate(bb_match* m, bb_rng* rng, int slot, int kind) {
    fx_apply(m, mk(BB_A_ACTIVATE, slot, 0, 0), rng);
    return fx_apply(m, mk(BB_A_DECLARE, kind, 0, 0), rng);
}

// Drive the fixture to the mover's movement decision point.
static bb_status begin_move(bb_match* m, bb_rng* rng, int slot) {
    bb_status st = fx_run(m, rng);
    if (st != BB_STATUS_DECISION) return st;
    return fx_activate(m, rng, slot, BB_ACT_MOVE);
}

// =============================================================================
// PREHENSILE TAIL (Mutation)
// =============================================================================

// SK/PREHENSILE TAIL: "When an opposition player attempts to Dodge, Jump or
// Leap away from a square in this player's Tackle Zone, they apply an
// additional -1 modifier to the Agility Test." AG 3+ dodging out of a tail's
// Tackle Zone into an unmarked square needs a 4: a 4 succeeds, a 3 fails.
BB_TEST(skmp_prehensile_tail_dodge_minus_one) {
    { // (a) 4 passes: -1 is the ONLY extra modifier.
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int mover = fx_lineman(&m, 0, 0, 10, 7); // AG 3+
        int tail = fx_lineman(&m, 1, 0, 10, 8);  // marks (10,7)
        fx_give_skill(&m, tail, BB_SK_PREHENSILE_TAIL);
        static const uint8_t dice[] = {4};
        bb_rng rng;
        bb_rng_script(&rng, dice, 1);

        bb_status st = begin_move(&m, &rng, mover);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        st = fx_apply(&m, mk(BB_A_STEP, 0, 10, 6), &rng); // unmarked destination
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
        BB_CHECK_EQ(m.players[mover].y, 6);
        BB_CHECK_EQ(m.active_team, BB_HOME); // no turnover
    }
    { // (b) 3 fails (without the tail an unmodified 3+ would pass): the
      // player Falls Over in the destination and a Turnover is caused.
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int mover = fx_lineman(&m, 0, 0, 10, 7);
        int tail = fx_lineman(&m, 1, 0, 10, 8);
        fx_give_skill(&m, tail, BB_SK_PREHENSILE_TAIL);
        static const uint8_t dice[] = {3, 3, 3}; // dodge 3-1=2 < 3; armour holds
        bb_rng rng;
        bb_rng_script(&rng, dice, 3);

        bb_status st = begin_move(&m, &rng, mover);
        st = fx_apply(&m, mk(BB_A_STEP, 0, 10, 6), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_PRONE);
        BB_CHECK_EQ(m.players[mover].y, 6);
        BB_CHECK_EQ(m.active_team, BB_AWAY); // turnover
    }
}

// SK/PREHENSILE TAIL: "If a player tries to leave the Tackle Zone of multiple
// players with this Skill at the same time, only one of those players may use
// this Skill." Two tails marking the origin give -1 total (not -2): AG 3+
// needs a 4 and a 4 succeeds.
BB_TEST(skmp_prehensile_tail_only_one_applies) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    int t1 = fx_lineman(&m, 1, 0, 10, 8); // marks (10,7)
    int t2 = fx_lineman(&m, 1, 1, 9, 8);  // marks (10,7)
    fx_give_skill(&m, t1, BB_SK_PREHENSILE_TAIL);
    fx_give_skill(&m, t2, BB_SK_PREHENSILE_TAIL);
    static const uint8_t dice[] = {4}; // would fail against a double -2
    bb_rng rng;
    bb_rng_script(&rng, dice, 1);

    bb_status st = begin_move(&m, &rng, mover);
    BB_CHECK_EQ(bb_tackle_zones(&m, BB_HOME, 10, 7), 2);
    // (11,6) is adjacent to neither tail: no destination markers.
    st = fx_apply(&m, mk(BB_A_STEP, 0, 11, 6), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].x, 11);
    BB_CHECK_EQ(m.players[mover].y, 6);
    BB_CHECK_EQ(m.active_team, BB_HOME);
}

// SK/PREHENSILE TAIL: the -1 applies only when dodging "away from a square in
// this player's Tackle Zone" — a tail Marking only the DESTINATION square
// adds nothing beyond the normal destination-marker -1, and a Prone tail has
// no Tackle Zone at all (RR "Prone and Stunned Players").
BB_TEST(skmp_prehensile_tail_inapplicable_squares) {
    { // (a) tail marks the destination only: plain -1 (marker), no tail -1.
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int mover = fx_lineman(&m, 0, 0, 10, 7);
        fx_lineman(&m, 1, 0, 10, 8);            // plain marker on origin
        int tail = fx_lineman(&m, 1, 1, 10, 5); // marks (10,6) only
        fx_give_skill(&m, tail, BB_SK_PREHENSILE_TAIL);
        static const uint8_t dice[] = {4}; // 4 passes the 4+; -2 would need 5
        bb_rng rng;
        bb_rng_script(&rng, dice, 1);

        bb_status st = begin_move(&m, &rng, mover);
        st = fx_apply(&m, mk(BB_A_STEP, 0, 10, 6), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
        BB_CHECK_EQ(m.players[mover].y, 6);
        BB_CHECK_EQ(m.active_team, BB_HOME);
    }
    { // (b) a Prone tail adjacent to the origin exerts no Tackle Zone: the
      // dodge (forced by a plain standing marker) is an unmodified 3+.
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int mover = fx_lineman(&m, 0, 0, 10, 7);
        fx_lineman(&m, 1, 0, 11, 8);            // plain marker on origin
        int tail = fx_lineman(&m, 1, 1, 10, 8); // adjacent but Prone
        m.players[tail].stance = BB_STANCE_PRONE;
        fx_give_skill(&m, tail, BB_SK_PREHENSILE_TAIL);
        static const uint8_t dice[] = {3}; // bare 3 must pass
        bb_rng rng;
        bb_rng_script(&rng, dice, 1);

        bb_status st = begin_move(&m, &rng, mover);
        st = fx_apply(&m, mk(BB_A_STEP, 0, 10, 6), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
        BB_CHECK_EQ(m.players[mover].y, 6);
        BB_CHECK_EQ(m.active_team, BB_HOME);
    }
}

// =============================================================================
// VERY LONG LEGS (Mutation)
// =============================================================================

// SK/VERY LONG LEGS: "may apply a +2 modifier to the Agility Test whenever
// they attempt to Intercept the ball." GAME "INTERCEPTIONS": AG test at -3 vs
// an Accurate Pass. AG 3+ at -3+2 = -1 needs a 4: a 4 intercepts (without the
// skill the target clamps to 6). Successful interception = Turnover.
BB_TEST(skmp_very_long_legs_intercept_plus_two) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9); // PA 2+
    fx_lineman(&m, 0, 1, 9, 7);                             // receiver
    int opp = fx_lineman(&m, 1, 0, 7, 7);                   // AG 3+, on the ruler
    fx_give_skill(&m, opp, BB_SK_VERY_LONG_LEGS);
    fx_ball_held(&m, thrower);
    // Short pass (dx=4): PA 2+ -1, roll 5 -> Accurate. Interception: AG 3+
    // -3 (accurate) +2 (VLL) -> needs 4; roll 4 -> intercepted.
    static const uint8_t dice[] = {5, 4};
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);

    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    bb_status st = fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 9, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(m.ball.carrier, opp);
    BB_CHECK(m.players[opp].flags & BB_PF_HAS_BALL);
    BB_CHECK_EQ(m.decision_team, BB_AWAY); // interception is always a turnover
}

// SK/VERY LONG LEGS: the +2 is for Intercepting only — an ordinary Catch
// (accurate pass to the VLL player) gets no bonus. AG 4+ catching an accurate
// pass (no modifier) rolls a 2: it must FAIL (with a stray +2 the target
// would clamp to 2 and the catch would succeed) and the ball Bounces.
BB_TEST(skmp_very_long_legs_no_bonus_on_regular_catch) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9);   // PA 2+
    int receiver = fx_player(&m, 0, 1, 8, 7, 6, 3, 4, 4, 9);  // AG 4+
    fx_give_skill(&m, receiver, BB_SK_VERY_LONG_LEGS);
    fx_lineman(&m, 1, 9, 24, 1); // far-away opponent bystander
    fx_ball_held(&m, thrower);
    // Quick pass: nat 6 Accurate; catch rolls 2 vs 4+ -> fail; Bounce d8
    // face 5 -> (9,7), comes to rest; incomplete pass -> Turnover.
    static const uint8_t dice[] = {6, 2, 5};
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);

    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    bb_status st = fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 9);
    BB_CHECK_EQ(m.ball.y, 7);
    BB_CHECK_EQ(m.decision_team, BB_AWAY); // turnover
}
