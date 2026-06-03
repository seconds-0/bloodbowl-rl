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

// =============================================================================
// Interceptions are not Catches (adversarial review M11)
// =============================================================================

// Regression (review M11): SK/CATCH "This player may re-roll any failed
// Agility Test when attempting to Catch the ball" — an interception attempt
// is NOT a Catch (DP/Extra Arms/Stunty all name Intercept separately), so a
// Catch-skill interceptor gets NO re-roll window after a failed attempt: the
// pass resolves straight through to the receiver.
BB_TEST(skmp_catch_skill_no_reroll_on_interception) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0); // zero team re-rolls on both sides
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9); // PA 2+
    int receiver = fx_lineman(&m, 0, 1, 9, 7);              // AG 3+
    int opp = fx_lineman(&m, 1, 0, 7, 7); // AG 3+, on the ruler
    fx_give_skill(&m, opp, BB_SK_CATCH);
    fx_ball_held(&m, thrower);
    // Short pass (dx=4): PA 2+ -1, roll 5 -> Accurate. Interception (auto:
    // single candidate): AG 3+ -3 -> needs 6; roll 5 FAILS. Pre-fix the Catch
    // skill opened a re-roll window here; post-fix the flight resolves and
    // the receiver catches unmodified (3+) on a 4.
    static const uint8_t dice[] = {5, 5, 4};
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);

    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    bb_status st = fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 9, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!fx_has_type(&m, BB_A_USE_REROLL)); // no re-roll window opened
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(m.ball.carrier, receiver);
    BB_CHECK_EQ(m.decision_team, BB_HOME); // no turnover, home still acting
}

// Control for M11: the Catch skill still grants its re-roll on an ordinary
// Catch — a failed catch of an accurate pass opens the window, and using the
// skill re-roll catches the ball.
BB_TEST(skmp_catch_skill_reroll_on_regular_catch) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9); // PA 2+
    int receiver = fx_lineman(&m, 0, 1, 8, 7);              // AG 3+
    fx_give_skill(&m, receiver, BB_SK_CATCH);
    fx_lineman(&m, 1, 9, 24, 1); // far-away opponent bystander
    fx_ball_held(&m, thrower);
    // Quick pass: nat 6 Accurate; catch (unmodified 3+) rolls 2 -> FAIL ->
    // Catch-skill re-roll window; re-roll 3 -> caught.
    static const uint8_t dice[] = {6, 2, 3};
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);

    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    bb_status st = fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    bb_action use = mk(BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_CATCH, 0);
    BB_CHECK(fx_find(&m, use) >= 0); // the window IS offered for a real catch
    st = fx_apply(&m, use, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(m.ball.carrier, receiver);
}

// Regression (review M11): SK/NERVES OF STEEL "may ignore any modifiers for
// being Marked when making an Agility Test to Catch the ball, or when making
// a Passing Ability Test to Pass the ball" — BB2025 has NO Intercept clause,
// so a Marked NoS interceptor keeps the marker's -1. AG 2+ vs an Accurate
// pass while Marked once: -3 -1 -> needs 6; a 5 must FAIL (pre-fix NoS
// wrongly refunded the marker and the 5 intercepted at 5+).
BB_TEST(skmp_nerves_of_steel_no_effect_on_interception) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9); // PA 2+
    int receiver = fx_lineman(&m, 0, 1, 9, 7);              // AG 3+
    int opp = fx_player(&m, 1, 0, 7, 7, 6, 3, 2, 4, 9);     // AG 2+, on the ruler
    fx_give_skill(&m, opp, BB_SK_NERVES_OF_STEEL);
    fx_lineman(&m, 0, 2, 7, 8); // Marks the interceptor (off the ruler)
    fx_ball_held(&m, thrower);
    // Short pass: PA 2+ -1, roll 5 -> Accurate. Interception: AG 2+ -3
    // (accurate) -1 (Marked, NOT ignored) -> needs 6; roll 5 FAILS. The
    // receiver then catches unmodified (3+) on a 3.
    static const uint8_t dice[] = {5, 5, 3};
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);

    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    bb_status st = fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 9, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK(!(m.players[opp].flags & BB_PF_HAS_BALL)); // no interception
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(m.ball.carrier, receiver);
    BB_CHECK_EQ(m.decision_team, BB_HOME); // no turnover
}

// Control for M11: Nerves of Steel still refunds the Marking -1 on an
// ordinary Catch. AG 3+ receiver Marked once catching an accurate pass:
// without NoS the target is 4+, with NoS a natural 3 catches.
BB_TEST(skmp_nerves_of_steel_still_ignores_markers_on_catch) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9); // PA 2+
    int receiver = fx_lineman(&m, 0, 1, 8, 7);              // AG 3+
    fx_give_skill(&m, receiver, BB_SK_NERVES_OF_STEEL);
    fx_lineman(&m, 1, 0, 8, 8); // Marks the receiver (not on the ruler)
    fx_ball_held(&m, thrower);
    // Quick pass: nat 6 Accurate (no interception candidate: the marker is
    // off the ruler). Catch: base 0, Marked -1, NoS +1 -> bare 3+; 3 catches.
    static const uint8_t dice[] = {6, 3};
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);

    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    bb_status st = fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(m.ball.carrier, receiver);
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

// =============================================================================
// BIG HAND (Mutation)
// =============================================================================

// Regression (adversarial review M13): SK/BIG HAND "This player ignores ALL
// negative modifiers when attempting to pick up the ball" — Pouring Rain's
// -1 included, not just the Marking -1s. Double-Marked ball square in
// Pouring Rain: the pickup is a plain AG 3+ — a 3 picks up (pre-fix the rain
// -1 leaked through and the 3 failed at 4+), and a 2 still fails (the refund
// must net to exactly 0, never a bonus).
BB_TEST(skmp_big_hand_ignores_rain_and_markers_on_pickup) {
    { // (a) a natural 3 picks up: -2 (Marked) -1 (rain) fully refunded.
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        m.weather = BB_WEATHER_RAIN;
        int mover = fx_lineman(&m, 0, 0, 10, 7); // AG 3+
        fx_give_skill(&m, mover, BB_SK_BIG_HAND);
        fx_lineman(&m, 1, 0, 12, 6); // marks ball square (11,7), not (10,7)
        fx_lineman(&m, 1, 1, 12, 8); // marks ball square (11,7), not (10,7)
        fx_ball_ground(&m, 11, 7);
        static const uint8_t dice[] = {3};
        bb_rng rng;
        bb_rng_script(&rng, dice, 1);

        bb_status st = begin_move(&m, &rng, mover);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK_EQ(bb_tackle_zones(&m, BB_HOME, 11, 7), 2);
        st = fx_apply(&m, mk(BB_A_STEP, 0, 11, 7), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
        BB_CHECK_EQ(m.ball.carrier, mover);
        BB_CHECK_EQ(m.active_team, BB_HOME); // no turnover
    }
    { // (b) a natural 2 still fails: Big Hand cancels to 0, never past it.
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        m.weather = BB_WEATHER_RAIN;
        int mover = fx_lineman(&m, 0, 0, 10, 7);
        fx_give_skill(&m, mover, BB_SK_BIG_HAND);
        fx_lineman(&m, 1, 0, 12, 6);
        fx_lineman(&m, 1, 1, 12, 8);
        fx_ball_ground(&m, 11, 7);
        static const uint8_t dice[] = {2, 1}; // pickup fails; bounce d8
        bb_rng rng;
        bb_rng_script(&rng, dice, 2);

        bb_status st = begin_move(&m, &rng, mover);
        st = fx_apply(&m, mk(BB_A_STEP, 0, 11, 7), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
        BB_CHECK_EQ(m.active_team, BB_AWAY); // failed pickup = turnover
    }
}

// Control for M13: WEATHER "Pouring Rain" still applies to a pickup by a
// player WITHOUT Big Hand after the call-site restructure — an unmarked
// AG 3+ pickup in rain is a 4+, so a 3 fails and the ball bounces (turnover).
BB_TEST(skmp_rain_pickup_minus1_without_big_hand) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    m.weather = BB_WEATHER_RAIN;
    int mover = fx_lineman(&m, 0, 0, 10, 7); // AG 3+, no skills
    fx_lineman(&m, 1, 9, 24, 1);             // far-away opponent bystander
    fx_ball_ground(&m, 11, 7);
    static const uint8_t dice[] = {3, 1}; // 3 fails the 4+; bounce d8
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, mk(BB_A_STEP, 0, 11, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.active_team, BB_AWAY); // turnover
}

// Regression (review M13, second call site): the jump-landing pickup applies
// the same rule — Big Hand refunds Marking AND rain when landing on the ball
// after Jumping over a Prone player. Jump (AG 3+, -2 landing markers) on a
// 5, then pick up double-Marked in rain on a plain 3.
BB_TEST(skmp_big_hand_rain_pickup_after_jump) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    m.weather = BB_WEATHER_RAIN;
    int mover = fx_lineman(&m, 0, 0, 10, 7); // AG 3+
    fx_give_skill(&m, mover, BB_SK_BIG_HAND);
    int hurdle = fx_lineman(&m, 1, 2, 11, 7); // jumped over
    m.players[hurdle].stance = BB_STANCE_PRONE;
    fx_lineman(&m, 1, 0, 13, 6); // marks landing square (12,7) only
    fx_lineman(&m, 1, 1, 13, 8); // marks landing square (12,7) only
    fx_ball_ground(&m, 12, 7);
    static const uint8_t dice[] = {5, 3}; // jump 5 vs 5+; pickup 3 vs 3+
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);

    bb_status st = begin_move(&m, &rng, mover);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    bb_action jump = mk(BB_A_JUMP, 0, 12, 7);
    BB_CHECK(fx_find(&m, jump) >= 0);
    st = fx_apply(&m, jump, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].x, 12);
    BB_CHECK_EQ(m.players[mover].y, 7);
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(m.ball.carrier, mover);
    BB_CHECK_EQ(m.active_team, BB_HOME); // no turnover
}

// =============================================================================
// DISTURBING PRESENCE (Mutation) on Throw Team-mate
// =============================================================================

// Regression (adversarial review M12): SK/DISTURBING PRESENCE "Any opposition
// player that performs a Pass Action, Throw Team-mate Action or a Throw Bomb
// Special Action ... applies a -1 modifier to their Passing Ability Test ...
// for each player on your team with this Skill within 3 squares of them."
// Pre-fix the TTM PA test was computed fully inline and NO aura could touch
// it. Same dice, PA 4+ thrower, Quick throw: with an opposing DP exactly 3
// squares away the 4 is one pip short (5+) -> Subpar -> the -1 landing fails
// and the mate Falls Over; without DP the same 4 is Superb and the mate lands
// on its feet.
BB_TEST(skmp_disturbing_presence_applies_to_ttm) {
    { // (a) DP within 3 squares of the thrower: 4 vs 5+ -> Subpar landing falls.
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int thrower = fx_lineman(&m, 0, 2, 10, 7); // PA 4+
        fx_give_skill(&m, thrower, BB_SK_THROW_TEAM_MATE);
        int mate = fx_lineman(&m, 0, 3, 10, 8); // adjacent Right Stuff mate
        fx_give_skill(&m, mate, BB_SK_RIGHT_STUFF);
        int dp = fx_lineman(&m, 1, 0, 13, 7); // Chebyshev 3 from thrower; not Marking
        fx_give_skill(&m, dp, BB_SK_DISTURBING_PRESENCE);
        // Dice: PA 4 (Subpar at 5+), scatter 3x d8=1 (NW: (12,7)->(9,4)),
        // landing d6=3 vs 4+ (-1 Subpar) FAILS, armour 2D6 = 2,2 holds.
        static const uint8_t dice[] = {4, 1, 1, 1, 3, 2, 2};
        bb_rng rng;
        bb_rng_script(&rng, dice, 7);

        bb_status st = fx_run(&m, &rng);
        st = fx_activate(&m, &rng, thrower, BB_ACT_TTM);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        st = fx_apply(&m, mk(BB_A_SPECIAL_TARGET, 7, 10, 8), &rng); // pick mate
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        st = fx_apply(&m, mk(BB_A_TTM_TARGET, 0, 12, 7), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.players[mate].x, 9);
        BB_CHECK_EQ(m.players[mate].y, 4);
        BB_CHECK_EQ(m.players[mate].stance, BB_STANCE_PRONE);
        BB_CHECK_EQ(m.active_team, BB_HOME); // no ball held: no turnover
    }
    { // (b) control, no DP: the same 4 is Superb (4+) and the landing is a
      // bare 3+ — the mate lands standing. Pins "exactly one pip worse".
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int thrower = fx_lineman(&m, 0, 2, 10, 7);
        fx_give_skill(&m, thrower, BB_SK_THROW_TEAM_MATE);
        int mate = fx_lineman(&m, 0, 3, 10, 8);
        fx_give_skill(&m, mate, BB_SK_RIGHT_STUFF);
        fx_lineman(&m, 1, 0, 24, 1); // far-away opponent bystander, no DP
        static const uint8_t dice[] = {4, 1, 1, 1, 3};
        bb_rng rng;
        bb_rng_script(&rng, dice, 5);

        bb_status st = fx_run(&m, &rng);
        st = fx_activate(&m, &rng, thrower, BB_ACT_TTM);
        st = fx_apply(&m, mk(BB_A_SPECIAL_TARGET, 7, 10, 8), &rng);
        st = fx_apply(&m, mk(BB_A_TTM_TARGET, 0, 12, 7), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.players[mate].x, 9);
        BB_CHECK_EQ(m.players[mate].y, 4);
        BB_CHECK_EQ(m.players[mate].stance, BB_STANCE_STANDING);
        BB_CHECK_EQ(m.active_team, BB_HOME);
    }
    { // (c) a DP player 4+ squares from the thrower contributes nothing:
      // identical to the control even though DP is on the pitch.
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int thrower = fx_lineman(&m, 0, 2, 10, 7);
        fx_give_skill(&m, thrower, BB_SK_THROW_TEAM_MATE);
        int mate = fx_lineman(&m, 0, 3, 10, 8);
        fx_give_skill(&m, mate, BB_SK_RIGHT_STUFF);
        int dp = fx_lineman(&m, 1, 0, 14, 7); // Chebyshev 4: out of range
        fx_give_skill(&m, dp, BB_SK_DISTURBING_PRESENCE);
        static const uint8_t dice[] = {4, 1, 1, 1, 3};
        bb_rng rng;
        bb_rng_script(&rng, dice, 5);

        bb_status st = fx_run(&m, &rng);
        st = fx_activate(&m, &rng, thrower, BB_ACT_TTM);
        st = fx_apply(&m, mk(BB_A_SPECIAL_TARGET, 7, 10, 8), &rng);
        st = fx_apply(&m, mk(BB_A_TTM_TARGET, 0, 12, 7), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.players[mate].stance, BB_STANCE_STANDING);
        BB_CHECK_EQ(m.active_team, BB_HOME);
    }
}
