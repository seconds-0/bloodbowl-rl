// test_rules_movement.c — BB2025 RULEBOOK tests for the movement domain:
// MA budget, Rushing, Dodging, standing up, picking up the ball, and the
// re-roll surface of those tests (team re-roll, Loner gate, Dodge / Sure Feet
// skill re-rolls, Sprint).
//
// Every test encodes what the rulebook mirror says (tight paraphrase + page
// path cited above each test). Authoritative sources, all under
// docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/:
//   GAME  = core_rules/the_game_of_blood_bowl/index.html  (Move Actions!,
//           Standing Up, Dodging, Picking Up the Ball, Rushing, Weather)
//   RR    = core_rules/rules_and_regulations/index.html   (Natural Rolls,
//           Re-rolls, Turnover, Marked/Open, Prone & Stunned, Falls Over)
//   SK    = core_rules/skills_and_traits/index.html       (Dodge, Sure Feet,
//           Sprint, Loner)
//   FAQ   = core_rules/latest_faq/index.html              (May 2026)
//
// Scripted dice (bb_rng_script) choose every die face; block dice are not
// used here. Tests that the engine currently fails are marked
// // ENGINE-DIVERGENCE and intentionally left failing.
#include "bb/bb_match.h"
#include "bb/bb_skills.h"
#include "bb_fixtures.h"
#include "bb_test.h"

static bb_action act(int type, int arg, int x, int y) {
    bb_action a = {(uint8_t)type, (uint8_t)arg, (uint8_t)x, (uint8_t)y};
    return a;
}

// Drive the fixture to the mover's movement decision point:
// run -> ACTIVATE slot -> DECLARE Move.
static bb_status begin_move(bb_match* m, bb_rng* rng, int slot) {
    bb_status st = fx_run(m, rng);
    if (st != BB_STATUS_DECISION) return st;
    st = fx_apply(m, act(BB_A_ACTIVATE, slot, 0, 0), rng);
    if (st != BB_STATUS_DECISION) return st;
    return fx_apply(m, act(BB_A_DECLARE, BB_ACT_MOVE, 0, 0), rng);
}

static int count_steps(const bb_match* m) {
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(m, legal);
    int c = 0;
    for (int i = 0; i < n; i++) {
        if (legal[i].type == BB_A_STEP) c++;
    }
    return c;
}

// =============================================================================
// MA budget & basic movement
// =============================================================================

// GAME "Move Actions!": "they can move around the pitch a number of squares
// equal to their Move Allowance. Players may move in any direction, including
// diagonally, into any adjacent unoccupied square." Moving within MA with no
// marking opponents requires NO dice at all.
BB_TEST(movement_ma_budget_no_dice) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 5, 7); // MA 6
    fx_lineman(&m, 1, 9, 24, 1);            // far-away opponent bystander
    bb_rng rng;
    bb_rng_script(&rng, 0, 0); // empty script: any roll would be an error

    bb_status st = begin_move(&m, &rng, mover);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    // 6 steps, mixing orthogonal and diagonal — all free.
    int path[6][2] = {{6, 7}, {7, 8}, {8, 8}, {9, 9}, {10, 9}, {11, 10}};
    for (int i = 0; i < 6; i++) {
        st = fx_apply(&m, act(BB_A_STEP, 0, path[i][0], path[i][1]), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
    }
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].moved, 6);
    BB_CHECK_EQ(m.players[mover].x, 11);
    BB_CHECK_EQ(m.players[mover].y, 10);
    // Further squares are still offered (they would be Rushes).
    BB_CHECK(fx_has_type(&m, BB_A_STEP));
}

// GAME "Move Actions!": "Players are never obliged to use their full Move
// Allowance, and may move zero squares if they wish."
BB_TEST(movement_zero_squares_voluntary_end) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 5, 7);
    int mate = fx_lineman(&m, 0, 1, 3, 3);
    fx_lineman(&m, 1, 9, 24, 1);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);

    bb_status st = begin_move(&m, &rng, mover);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(fx_find(&m, act(BB_A_END_ACTIVATION, 0, 0, 0)) >= 0);
    st = fx_apply(&m, act(BB_A_END_ACTIVATION, 0, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].moved, 0);
    BB_CHECK(m.players[mover].flags & BB_PF_USED);
    // No turnover: same coach keeps acting (team-mate still activatable).
    BB_CHECK_EQ(m.active_team, BB_HOME);
    BB_CHECK(fx_find(&m, act(BB_A_ACTIVATE, mate, 0, 0)) >= 0);
}

// GAME "Move Actions!": "an occupied square is any square that does contain
// another player, regardless of whether they are Standing, Prone or Stunned.
// Players may not move through an occupied square." And: "An unoccupied
// square is any square that does not contain another player (even if it
// contains the ball)."
BB_TEST(movement_occupied_square_illegal_ball_square_legal) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    int mate = fx_lineman(&m, 0, 1, 11, 7);  // prone team-mate
    m.players[mate].stance = BB_STANCE_PRONE;
    int oppp = fx_lineman(&m, 1, 0, 9, 7);   // prone opponent
    m.players[oppp].stance = BB_STANCE_PRONE;
    fx_lineman(&m, 1, 1, 11, 8);             // standing opponent
    fx_ball_ground(&m, 10, 6);               // loose ball on an empty square
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);

    bb_status st = begin_move(&m, &rng, mover);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_find(&m, act(BB_A_STEP, 0, 11, 7)), -1); // prone team-mate
    BB_CHECK_EQ(fx_find(&m, act(BB_A_STEP, 0, 9, 7)), -1);  // prone opponent
    BB_CHECK_EQ(fx_find(&m, act(BB_A_STEP, 0, 11, 8)), -1); // standing opponent
    BB_CHECK(fx_find(&m, act(BB_A_STEP, 0, 10, 6)) >= 0);   // ball square is open
}

// GAME "Move Actions!": "Players can never voluntarily move off the pitch."
// A corner player has exactly 3 step destinations.
BB_TEST(movement_cannot_step_off_pitch) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 0, 0);
    fx_lineman(&m, 1, 9, 24, 14);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);

    bb_status st = begin_move(&m, &rng, mover);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(count_steps(&m), 3); // (1,0) (0,1) (1,1) only
}

// =============================================================================
// Rushing
// =============================================================================

// GAME "Rushing": "On a 2+ the player successfully manages to Rush into the
// square" and "Players may attempt to Rush a maximum of two times during
// their activation." A roll of exactly 2 succeeds; after 2 rushes the player
// may not move further.
BB_TEST(movement_rush_two_per_activation_2plus) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 5, 7); // MA 6
    fx_lineman(&m, 1, 9, 24, 1);
    static const uint8_t dice[] = {2, 2};
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);

    bb_status st = begin_move(&m, &rng, mover);
    for (int x = 6; x <= 11; x++) { // 6 free squares
        st = fx_apply(&m, act(BB_A_STEP, 0, x, 7), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
    }
    st = fx_apply(&m, act(BB_A_STEP, 0, 12, 7), &rng); // rush 1: rolls 2
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    st = fx_apply(&m, act(BB_A_STEP, 0, 13, 7), &rng); // rush 2: rolls 2
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].x, 13);
    BB_CHECK_EQ(m.players[mover].moved, 8);
    BB_CHECK_EQ(m.players[mover].rushes, 2);
    BB_CHECK_EQ(m.active_team, BB_HOME); // no turnover
    // A third rush is not available.
    BB_CHECK(!fx_has_type(&m, BB_A_STEP));
    BB_CHECK(fx_find(&m, act(BB_A_END_ACTIVATION, 0, 0, 0)) >= 0);
}

// GAME "Rushing": "On a 1, the player trips and Falls Over in the square they
// were attempting to Rush into and their activation immediately ends."
// RR "Falls Over": Armour Roll is made; "If a player on the active team Falls
// Over then a Turnover is caused." RR "The Turnover": the turn ends.
BB_TEST(movement_rush_natural_one_falls_in_destination) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 5, 7);
    fx_lineman(&m, 1, 9, 24, 1);
    static const uint8_t dice[] = {1, 3, 3}; // rush nat 1; armour 6 vs 9+ holds
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);

    bb_status st = begin_move(&m, &rng, mover);
    for (int x = 6; x <= 11; x++) {
        st = fx_apply(&m, act(BB_A_STEP, 0, x, 7), &rng);
    }
    st = fx_apply(&m, act(BB_A_STEP, 0, 12, 7), &rng); // failed rush
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[mover].x, 12); // fell in the destination square
    BB_CHECK_EQ(m.players[mover].y, 7);
    BB_CHECK_EQ(m.players[mover].location, BB_LOC_ON_PITCH);
    // Turnover: the opposing coach is now the active team.
    BB_CHECK_EQ(m.active_team, BB_AWAY);
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
}

// RR "Falls Over": "If the player was holding the ball, it will Bounce from
// the square they are in." The ball bounces from the rush destination square
// (engine resolves armour before the bounce; d8 face 5 = +1,0).
BB_TEST(movement_rush_fail_ball_carrier_bounce) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 5, 7);
    fx_lineman(&m, 1, 9, 24, 1);
    fx_ball_held(&m, mover);
    static const uint8_t dice[] = {1, 3, 3, 5}; // rush 1, armour 3+3, bounce d8=5
    bb_rng rng;
    bb_rng_script(&rng, dice, 4);

    bb_status st = begin_move(&m, &rng, mover);
    for (int x = 6; x <= 11; x++) {
        st = fx_apply(&m, act(BB_A_STEP, 0, x, 7), &rng);
    }
    st = fx_apply(&m, act(BB_A_STEP, 0, 12, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[mover].x, 12);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.carrier, BB_NO_PLAYER);
    BB_CHECK_EQ(m.ball.x, 13); // bounced one square east of (12,7)
    BB_CHECK_EQ(m.ball.y, 7);
    BB_CHECK_EQ(m.active_team, BB_AWAY);
}

// ENGINE-DIVERGENCE: GAME "Weather table — BLIZZARD": "Whenever a player
// attempts to Rush, apply an additional -1 modifier to the roll." A rush roll
// of 2 in a Blizzard is modified to 1 and FAILS (2+ needed). The engine rolls
// every rush against a fixed unmodified 2+ (proc_move.c pushes BB_TEST_RUSH
// with target 2, no weather adjustment), so the 2 incorrectly succeeds.
BB_TEST(movement_rush_blizzard_minus1) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    m.weather = BB_WEATHER_BLIZZARD;
    int mover = fx_lineman(&m, 0, 0, 5, 7);
    fx_lineman(&m, 1, 9, 24, 1);
    static const uint8_t dice[] = {2, 3, 3}; // rush 2 (-1 -> 1: fail), armour holds
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);

    bb_status st = begin_move(&m, &rng, mover);
    for (int x = 6; x <= 11; x++) {
        st = fx_apply(&m, act(BB_A_STEP, 0, x, 7), &rng);
    }
    st = fx_apply(&m, act(BB_A_STEP, 0, 12, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    // Rulebook: the player Falls Over in the destination and a Turnover occurs.
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.active_team, BB_AWAY);
}

// =============================================================================
// Dodging
// =============================================================================

// GAME "Dodging": "When the active player wishes to move out of a square in
// which they are being Marked, they will need to Dodge ... each time they
// wish to leave a square in which they are Marked." Leaving an un-Marked
// square needs no roll. RR "Marked": within the Tackle Zone of a Standing
// opposing player.
BB_TEST(movement_dodge_only_when_leaving_marked_square) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 10, 7); // AG 3+
    fx_lineman(&m, 1, 0, 10, 8);             // marks (10,7)
    static const uint8_t dice[] = {3};       // dodge: exactly AG 3+ passes
    bb_rng rng;
    bb_rng_script(&rng, dice, 1);

    bb_status st = begin_move(&m, &rng, mover);
    BB_CHECK(bb_is_marked(&m, mover));
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng); // dodge (dest unmarked)
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].y, 6);
    // Now Open: the next step must consume no dice (script is exhausted).
    BB_CHECK(!bb_is_marked(&m, mover));
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 5), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].moved, 2);
}

// RR "Prone and Stunned Players": "any player that is Prone or Stunned will
// automatically lose its Tackle Zone." Leaving a square adjacent only to
// downed opponents is not a Dodge.
BB_TEST(movement_no_dodge_leaving_downed_opponents) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    int op1 = fx_lineman(&m, 1, 0, 10, 8);
    m.players[op1].stance = BB_STANCE_PRONE;
    int op2 = fx_lineman(&m, 1, 1, 9, 7);
    m.players[op2].stance = BB_STANCE_STUNNED;
    bb_rng rng;
    bb_rng_script(&rng, 0, 0); // no dice allowed

    bb_status st = begin_move(&m, &rng, mover);
    BB_CHECK(!bb_is_marked(&m, mover));
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].y, 6);
}

// GAME "Dodging": the modifier is "-1 ... for each opposition player that is
// Marking the square they are moving INTO"; "If there are no opposition
// players Marking the square a player is attempting to Dodge into, then there
// are no modifiers." Players marking the square being LEFT do not modify the
// roll: 3 origin markers, unmarked destination => unmodified AG 3+.
BB_TEST(movement_dodge_origin_markers_no_modifier) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 1, 0, 9, 6);
    fx_lineman(&m, 1, 1, 9, 7);
    fx_lineman(&m, 1, 2, 9, 8);
    static const uint8_t dice[] = {3}; // must pass on a bare 3
    bb_rng rng;
    bb_rng_script(&rng, dice, 1);

    bb_status st = begin_move(&m, &rng, mover);
    BB_CHECK_EQ(bb_tackle_zones(&m, BB_HOME, 10, 7), 3);
    // (11,7) is not adjacent to any opponent: no modifier.
    st = fx_apply(&m, act(BB_A_STEP, 0, 11, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].x, 11);
    BB_CHECK_EQ(m.active_team, BB_HOME);
}

// GAME "Dodging" example: a single opponent Marking the destination square
// gives -1, so AG 3+ needs a 4. A roll of 4 succeeds.
BB_TEST(movement_dodge_destination_marker_minus1) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 1, 0, 10, 8); // marks origin (10,7) only
    fx_lineman(&m, 1, 1, 8, 5);  // marks destination (9,6) only
    static const uint8_t dice[] = {4};
    bb_rng rng;
    bb_rng_script(&rng, dice, 1);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 9, 6), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].x, 9);
    BB_CHECK_EQ(m.players[mover].y, 6);
}

// GAME "Dodging": "If the test is failed ... The player is moved into the
// square they attempted to Dodge into and then Falls Over." RR: Falls Over =
// Armour Roll + Turnover for the active team.
BB_TEST(movement_dodge_fail_falls_in_destination) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0); // 0 team rerolls: no reroll window
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 1, 0, 10, 8);
    static const uint8_t dice[] = {2, 3, 3}; // dodge 2 < 3 fails; armour holds
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[mover].x, 10); // moved into the destination square
    BB_CHECK_EQ(m.players[mover].y, 6);
    BB_CHECK_EQ(m.active_team, BB_AWAY); // turnover
}

// RR "Natural Rolls": "should a player roll a natural 6 for any action or
// test, then that will always be a success even if the modifiers would make
// it seem impossible." AG 5+ into two destination markers (-2): a natural 6
// (modified 4 < 5) still succeeds.
BB_TEST(movement_dodge_natural_six_always_succeeds) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_player(&m, 0, 0, 10, 7, 6, 3, 5, 4, 9); // AG 5+
    fx_lineman(&m, 1, 0, 10, 8); // marks origin
    fx_lineman(&m, 1, 1, 8, 5);  // marks destination (9,6)
    fx_lineman(&m, 1, 2, 8, 7);  // marks destination (9,6)
    static const uint8_t dice[] = {6};
    bb_rng rng;
    bb_rng_script(&rng, dice, 1);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 9, 6), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].x, 9);
    BB_CHECK_EQ(m.active_team, BB_HOME);
}

// RR "Modifying Dice Rolls" (May 2026 errata: only the above-6 cap remains)
// + FAQ Designers' Note: results CAN be modified below the target. AG 5+ with
// -2 destination markers: a 5 is modified to 3 and fails.
BB_TEST(movement_dodge_marked_destination_fail) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_player(&m, 0, 0, 10, 7, 6, 3, 5, 4, 9); // AG 5+
    fx_lineman(&m, 1, 0, 10, 8);
    fx_lineman(&m, 1, 1, 8, 5);
    fx_lineman(&m, 1, 2, 8, 7);
    static const uint8_t dice[] = {5, 3, 3}; // 5-2=3 < 5 fails; armour holds
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 9, 6), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[mover].x, 9);
    BB_CHECK_EQ(m.players[mover].y, 6);
    BB_CHECK_EQ(m.active_team, BB_AWAY);
}

// GAME "Dodging": "If the Agility Test is passed, they will stay on their
// feet and may continue their movement, even Dodging again if they wish. A
// player must make a Dodge Roll each time they wish to leave a square in
// which they are Marked." Two chained dodges = two dice.
BB_TEST(movement_dodge_each_marked_square) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 1, 0, 10, 8); // marks (10,7)
    fx_lineman(&m, 1, 1, 11, 5); // marks (10,6)
    static const uint8_t dice[] = {4, 3}; // dodge1 needs 4+ (-1 dest), dodge2 3+
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng); // into B's TZ
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(bb_is_marked(&m, mover));
    st = fx_apply(&m, act(BB_A_STEP, 0, 9, 6), &rng);  // dodge again, unmarked dest
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].x, 9);
    BB_CHECK_EQ(m.players[mover].moved, 2);
}

// GAME "Rushing": "If, when a player attempts to Rush, there would be
// multiple rolls for moving into the square, such as having to Dodge, then
// the roll for attempt to Rush will always come first." MA 1 player rushes
// out of a marked square into a -1 destination: script {3,4} only works if
// the 3 is the rush (2+) and the 4 is the dodge (4+).
BB_TEST(movement_rush_roll_before_dodge_roll) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_player(&m, 0, 0, 10, 7, 1, 3, 3, 4, 9); // MA 1
    fx_lineman(&m, 1, 0, 11, 5); // marks (10,6) but not (10,7) nor (9,6)
    fx_lineman(&m, 1, 1, 8, 5);  // marks (9,6) only
    static const uint8_t dice[] = {3, 4};
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng); // free step, MA spent
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(bb_is_marked(&m, mover));
    // Rush + dodge out of (10,6): rush rolls 3 (2+ ok), dodge rolls 4 (4+ ok).
    // If the engine rolled the dodge first, the 3 would fail it.
    st = fx_apply(&m, act(BB_A_STEP, 0, 9, 6), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].x, 9);
    BB_CHECK_EQ(m.players[mover].rushes, 1);
    BB_CHECK_EQ(m.active_team, BB_HOME);
}

// GAME "Rushing" + "Jumping" analogue: when the Rush fails, the player Falls
// Over immediately — no Dodge roll is ever made for that square. Script holds
// exactly rush + armour dice; a stray dodge roll would exhaust it.
BB_TEST(movement_rush_fail_skips_dodge_roll) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_player(&m, 0, 0, 10, 7, 1, 3, 3, 4, 9); // MA 1
    fx_lineman(&m, 1, 0, 11, 5);
    fx_lineman(&m, 1, 1, 8, 5);
    static const uint8_t dice[] = {1, 3, 3}; // rush nat 1; armour 6 holds
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
    st = fx_apply(&m, act(BB_A_STEP, 0, 9, 6), &rng); // rush fails
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng)); // exactly 3 dice: no dodge was rolled
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[mover].x, 9); // fell in the rush destination
    BB_CHECK_EQ(m.players[mover].y, 6);
    BB_CHECK_EQ(m.active_team, BB_AWAY);
}

// =============================================================================
// Standing up
// =============================================================================

// GAME "Standing Up": "Players that begin their activation Prone must declare
// an Action that includes a Move Action in order to first stand up" (so no
// plain Block Action), "it will cost them 3 squares of their Move Allowance",
// "they must stand up before attempting to do anything else."
BB_TEST(movement_prone_stand_first_costs_three) {
    // Part A: a Prone player adjacent to a standing opponent may not declare
    // a Block Action (Block includes no Move Action).
    {
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int mover = fx_lineman(&m, 0, 0, 10, 7);
        m.players[mover].stance = BB_STANCE_PRONE;
        fx_lineman(&m, 1, 0, 10, 8);
        bb_rng rng;
        bb_rng_script(&rng, 0, 0);
        bb_status st = fx_run(&m, &rng);
        st = fx_apply(&m, act(BB_A_ACTIVATE, mover, 0, 0), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(fx_find(&m, act(BB_A_DECLARE, BB_ACT_MOVE, 0, 0)) >= 0);
        BB_CHECK_EQ(fx_find(&m, act(BB_A_DECLARE, BB_ACT_BLOCK, 0, 0)), -1);
    }
    // Part B: stand-up costs 3 MA, no roll for MA 6; remaining 3 squares are
    // free, the 4th is a Rush.
    {
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int mover = fx_lineman(&m, 0, 0, 5, 7); // MA 6
        m.players[mover].stance = BB_STANCE_PRONE;
        fx_lineman(&m, 1, 9, 24, 1);
        static const uint8_t dice[] = {2}; // only the rush
        bb_rng rng;
        bb_rng_script(&rng, dice, 1);
        bb_status st = begin_move(&m, &rng, mover);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!fx_has_type(&m, BB_A_STEP)); // must stand up first
        BB_CHECK(fx_find(&m, act(BB_A_STAND_UP, 0, 0, 0)) >= 0);
        st = fx_apply(&m, act(BB_A_STAND_UP, 0, 0, 0), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
        BB_CHECK_EQ(m.players[mover].moved, 3); // 3 MA spent standing
        for (int x = 6; x <= 8; x++) { // 3 free squares left
            st = fx_apply(&m, act(BB_A_STEP, 0, x, 7), &rng);
            BB_CHECK_EQ(st, BB_STATUS_DECISION);
        }
        st = fx_apply(&m, act(BB_A_STEP, 0, 9, 7), &rng); // 4th square = rush (2)
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.players[mover].rushes, 1);
        BB_CHECK_EQ(m.players[mover].x, 9);
    }
}

// GAME "Standing Up": "If a player with a Move Allowance Characteristic of 2
// or less ... wishes to stand up, they must roll a D6. On a 4+, the player
// may stand up using their full Move Allowance to do so" — they stand, with
// no movement remaining.
BB_TEST(movement_standup_ma2_roll_4plus) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_player(&m, 0, 0, 10, 7, 2, 3, 3, 4, 9); // MA 2
    m.players[mover].stance = BB_STANCE_PRONE;
    fx_lineman(&m, 1, 9, 24, 1);
    static const uint8_t dice[] = {4};
    bb_rng rng;
    bb_rng_script(&rng, dice, 1);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STAND_UP, 0, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK(!fx_has_type(&m, BB_A_STEP)); // full MA consumed by standing up
    BB_CHECK_EQ(m.active_team, BB_HOME);
}

// GAME "Standing Up": "On a 1-3, the player remains Prone and their
// activation immediately ends." This is NOT a Fall Over, so no Armour Roll
// and no Turnover — the coach continues their turn.
BB_TEST(movement_standup_ma2_fail_no_turnover) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_player(&m, 0, 0, 10, 7, 2, 3, 3, 4, 9);
    m.players[mover].stance = BB_STANCE_PRONE;
    int mate = fx_lineman(&m, 0, 1, 3, 3);
    fx_lineman(&m, 1, 9, 24, 1);
    static const uint8_t dice[] = {3}; // 3 fails the 4+
    bb_rng rng;
    bb_rng_script(&rng, dice, 1);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STAND_UP, 0, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng)); // exactly one die: no armour roll
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_PRONE);
    BB_CHECK(m.players[mover].flags & BB_PF_USED); // activation over
    BB_CHECK_EQ(m.active_team, BB_HOME);           // no turnover
    BB_CHECK(fx_find(&m, act(BB_A_ACTIVATE, mate, 0, 0)) >= 0);
}

// GAME "Standing Up": the 4+ roll applies only to "Move Allowance
// Characteristic of 2 or less" — an MA 3 player stands without a roll, has 0
// normal movement left, and may still Rush.
BB_TEST(movement_standup_ma3_no_roll_then_rush) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_player(&m, 0, 0, 5, 7, 3, 3, 3, 4, 9); // MA 3
    m.players[mover].stance = BB_STANCE_PRONE;
    fx_lineman(&m, 1, 9, 24, 1);
    static const uint8_t dice[] = {2}; // only the rush roll
    bb_rng rng;
    bb_rng_script(&rng, dice, 1);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STAND_UP, 0, 0, 0), &rng); // no die
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].moved, 3);
    st = fx_apply(&m, act(BB_A_STEP, 0, 6, 7), &rng); // rush, rolls the 2
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].x, 6);
    BB_CHECK_EQ(m.players[mover].rushes, 1);
}

// =============================================================================
// Picking up the ball
// =============================================================================

// GAME "Picking Up the Ball": "Whenever a player voluntarily moves into a
// square containing the ball during their activation, they must immediately
// make an Agility Test ... If the test is passed, the player immediately
// gains possession of the ball and may continue their activation."
BB_TEST(movement_pickup_on_entering_ball_square) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 5, 7); // AG 3+
    fx_lineman(&m, 1, 9, 24, 1);
    fx_ball_ground(&m, 7, 7);
    static const uint8_t dice[] = {3}; // unmodified AG test
    bb_rng rng;
    bb_rng_script(&rng, dice, 1);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 6, 7), &rng);
    st = fx_apply(&m, act(BB_A_STEP, 0, 7, 7), &rng); // onto the ball
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(m.ball.carrier, mover);
    BB_CHECK(m.players[mover].flags & BB_PF_HAS_BALL);
    BB_CHECK_EQ(m.active_team, BB_HOME);
    BB_CHECK(fx_has_type(&m, BB_A_STEP)); // may continue the activation
    st = fx_apply(&m, act(BB_A_STEP, 0, 8, 7), &rng); // ball moves with carrier
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.ball.x, 8);
    BB_CHECK_EQ(m.ball.y, 7);
}

// GAME "Picking Up the Ball": "Apply a -1 modifier to this roll for each
// opposition player that is Marking the player attempting to pick up the
// ball." One marker: AG 3+ needs a 4; a 4 succeeds.
BB_TEST(movement_pickup_marked_minus1) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 5, 7);
    fx_lineman(&m, 1, 0, 8, 8); // marks the ball square (7,7), not the path
    fx_ball_ground(&m, 7, 7);
    static const uint8_t dice[] = {4};
    bb_rng rng;
    bb_rng_script(&rng, dice, 1);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 6, 7), &rng);
    st = fx_apply(&m, act(BB_A_STEP, 0, 7, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(m.ball.carrier, mover);
}

// GAME "Picking Up the Ball": "If the test is failed, the player fails to
// pick up the ball and a Turnover is caused - the ball will then Bounce from
// the player's square." The player stays standing and the turn ends even
// though Move Allowance remained.
BB_TEST(movement_pickup_fail_bounce_turnover) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 5, 7); // MA 6: 4 squares still unspent
    fx_lineman(&m, 1, 0, 8, 8);             // marks the ball square: 4+ needed
    fx_ball_ground(&m, 7, 7);
    static const uint8_t dice[] = {3, 5}; // pickup 3 fails (4+); bounce d8=5 -> +1,0
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 6, 7), &rng);
    st = fx_apply(&m, act(BB_A_STEP, 0, 7, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING); // no fall
    BB_CHECK_EQ(m.players[mover].moved, 2);                   // movement remained
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 8); // bounced east from (7,7)
    BB_CHECK_EQ(m.ball.y, 7);
    BB_CHECK_EQ(m.active_team, BB_AWAY); // turnover despite movement left
}

// GAME "Picking Up the Ball": "The roll to pick up the ball is always done
// after any rolls required to move into the square containing the ball, such
// as any rolls to Rush..." Script {2,3}: the 2 must be the rush (2+) and the
// 3 the pickup (3+); reversed order would fail the pickup.
BB_TEST(movement_pickup_after_rush_roll) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_player(&m, 0, 0, 5, 7, 1, 3, 3, 4, 9); // MA 1
    fx_lineman(&m, 1, 9, 24, 1);
    fx_ball_ground(&m, 7, 7);
    static const uint8_t dice[] = {2, 3};
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 6, 7), &rng); // free (MA 1)
    st = fx_apply(&m, act(BB_A_STEP, 0, 7, 7), &rng); // rush then pickup
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(m.ball.carrier, mover);
}

// GAME "Weather table — POURING RAIN": "Whenever a player attempts to pick up
// or Catch the ball ... they suffer a -1 modifier to the roll." AG 3+ in rain
// needs a 4: a 4 succeeds, a 3 fails (bounce + turnover).
BB_TEST(movement_pickup_rain_minus1) {
    { // 4 succeeds
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        m.weather = BB_WEATHER_RAIN;
        int mover = fx_lineman(&m, 0, 0, 5, 7);
        fx_lineman(&m, 1, 9, 24, 1);
        fx_ball_ground(&m, 6, 7);
        static const uint8_t dice[] = {4};
        bb_rng rng;
        bb_rng_script(&rng, dice, 1);
        bb_status st = begin_move(&m, &rng, mover);
        st = fx_apply(&m, act(BB_A_STEP, 0, 6, 7), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    }
    { // 3 fails
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        m.weather = BB_WEATHER_RAIN;
        int mover = fx_lineman(&m, 0, 0, 5, 7);
        fx_lineman(&m, 1, 9, 24, 1);
        fx_ball_ground(&m, 6, 7);
        static const uint8_t dice[] = {3, 5}; // fail; bounce east
        bb_rng rng;
        bb_rng_script(&rng, dice, 2);
        bb_status st = begin_move(&m, &rng, mover);
        st = fx_apply(&m, act(BB_A_STEP, 0, 6, 7), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
        BB_CHECK_EQ(m.ball.x, 7);
        BB_CHECK_EQ(m.active_team, BB_AWAY);
    }
}

// =============================================================================
// Re-rolls on movement tests
// =============================================================================

// RR "Team Re-rolls": "Team Re-rolls can only be used when the team is
// active" and a Dodge roll is not in the excluded list, so a failed Dodge may
// be re-rolled with a Team Re-roll, spending one from the pool.
BB_TEST(movement_team_reroll_on_failed_dodge) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 2);
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 1, 0, 10, 8);
    static const uint8_t dice[] = {2, 4}; // fail, then re-rolled 4 passes
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(fx_find(&m, act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0)) >= 0);
    BB_CHECK(fx_find(&m, act(BB_A_DECLINE_REROLL, 0, 0, 0)) >= 0);
    // No Dodge skill: no skill re-roll offer.
    BB_CHECK_EQ(fx_find(&m, act(BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_DODGE, 0)), -1);
    st = fx_apply(&m, act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].y, 6);
    BB_CHECK_EQ(m.rerolls[BB_HOME], 1); // one spent
    BB_CHECK_EQ(m.active_team, BB_HOME);
}

// RR "Re-rolls": a re-roll is optional. Declining keeps the failed result:
// the player Falls Over in the destination and the Team Re-roll is NOT spent.
BB_TEST(movement_decline_reroll_falls) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 1);
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 1, 0, 10, 8);
    static const uint8_t dice[] = {2, 3, 3}; // fail; armour holds
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    st = fx_apply(&m, act(BB_A_DECLINE_REROLL, 0, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[mover].y, 6);
    BB_CHECK_EQ(m.rerolls[BB_HOME], 1); // not spent
    BB_CHECK_EQ(m.active_team, BB_AWAY);
}

// ENGINE-DIVERGENCE: RR "Team Re-rolls" (BB2025): "A Coach may use as many
// Team Re-rolls as they want during their turn, though they may still never
// re-roll a re-roll." The BB2020 once-per-team-turn limit is GONE in BB2025
// (no <del> in the mirror — this is current law). The engine still latches
// m.reroll_used_this_turn (proc_test.c team_reroll_available), so a second
// failed test in the same turn is not offered the second Team Re-roll.
BB_TEST(movement_team_rerolls_not_limited_per_turn) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 2); // two team re-rolls in the pool
    int p1 = fx_lineman(&m, 0, 0, 10, 7);
    int p2 = fx_lineman(&m, 0, 1, 12, 7);
    fx_lineman(&m, 1, 0, 10, 8); // marks p1
    fx_lineman(&m, 1, 1, 13, 8); // marks p2
    // p1: dodge fails (2), team re-roll, 4 passes. p2: dodge fails (2) ->
    // rulebook: second team re-roll offered; re-rolled 3 passes. Trailing 3,3
    // feed the armour roll the engine wrongly performs instead.
    static const uint8_t dice[] = {2, 4, 2, 3, 3};
    bb_rng rng;
    bb_rng_script(&rng, dice, 5);

    bb_status st = begin_move(&m, &rng, p1);
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
    st = fx_apply(&m, act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[p1].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.rerolls[BB_HOME], 1);
    st = fx_apply(&m, act(BB_A_END_ACTIVATION, 0, 0, 0), &rng);
    // Second activation, same turn.
    st = fx_apply(&m, act(BB_A_ACTIVATE, p2, 0, 0), &rng);
    st = fx_apply(&m, act(BB_A_DECLARE, BB_ACT_MOVE, 0, 0), &rng);
    st = fx_apply(&m, act(BB_A_STEP, 0, 12, 6), &rng); // dodge fails on 2
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    // RULEBOOK: the remaining Team Re-roll must be offered again this turn.
    int idx = fx_find(&m, act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0));
    BB_CHECK(idx >= 0); // engine fails here (BB2020 once-per-turn holdover)
    if (idx >= 0) {
        st = fx_apply(&m, act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK_EQ(m.players[p2].stance, BB_STANCE_STANDING);
        BB_CHECK_EQ(m.rerolls[BB_HOME], 0);
    }
}

// SK "Loner (X+)* (Passive)": "Whenever this player wishes to use a Team
// Re-roll, they must roll a D6 ... If they roll lower than the number shown
// in brackets, then they may not re-roll the dice and the Team Re-roll is
// lost just as if it had been used." (Engine default Loner value: 4+.)
BB_TEST(movement_loner_gate_fail_wastes_reroll) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 1);
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    fx_give_skill(&m, mover, BB_SK_LONER);
    fx_lineman(&m, 1, 0, 10, 8);
    static const uint8_t dice[] = {2, 3, 3, 3}; // dodge 2; Loner 3 (<4); armour 6
    bb_rng rng;
    bb_rng_script(&rng, dice, 4);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    st = fx_apply(&m, act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.rerolls[BB_HOME], 0); // lost as if used
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_PRONE); // result stood
    BB_CHECK_EQ(m.players[mover].y, 6);
    BB_CHECK_EQ(m.active_team, BB_AWAY);
}

// SK "Loner (X+)*": "If they roll equal to or higher than the number shown in
// brackets, then they may use the Team Re-roll as normal."
BB_TEST(movement_loner_gate_pass) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 1);
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    fx_give_skill(&m, mover, BB_SK_LONER);
    fx_lineman(&m, 1, 0, 10, 8);
    static const uint8_t dice[] = {2, 4, 5}; // dodge 2; Loner 4 (>=4); re-roll 5
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
    st = fx_apply(&m, act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].y, 6);
    BB_CHECK_EQ(m.rerolls[BB_HOME], 0);
    BB_CHECK_EQ(m.active_team, BB_HOME);
}

// SK "Dodge (Active)": "Once per Turn, this player may re-roll a single
// Agility Test when attempting to Dodge." Works with zero Team Re-rolls.
BB_TEST(movement_dodge_skill_self_reroll) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0); // no team re-rolls at all
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    fx_give_skill(&m, mover, BB_SK_DODGE);
    fx_lineman(&m, 1, 0, 10, 8);
    static const uint8_t dice[] = {2, 4};
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_find(&m, act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0)), -1);
    BB_CHECK(fx_find(&m, act(BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_DODGE, 0)) >= 0);
    st = fx_apply(&m, act(BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_DODGE, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].y, 6);
}

// SK "Pro (Active)": "During this player's activation, they may attempt to
// re-roll a single dice. ... the player must roll a D6: on a 3+ the dice may
// be re-rolled, on a 1-2 the dice may not be re-rolled." Pro is its OWN
// re-roll source: with zero team re-rolls and no applicable skill re-roll the
// window must still open and offer BB_RR_PRO (it was unreachable as the sole
// source — adversarial review M1).
BB_TEST(movement_pro_reroll_sole_source) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0); // zero team re-rolls in the pool
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    fx_give_skill(&m, mover, BB_SK_PRO);
    fx_lineman(&m, 1, 0, 10, 8);
    static const uint8_t dice[] = {2, 3, 4}; // dodge 2 fails; Pro 3 (3+); re-roll 4
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(fx_find(&m, act(BB_A_USE_REROLL, BB_RR_PRO, 0, 0)) >= 0);
    BB_CHECK(fx_find(&m, act(BB_A_DECLINE_REROLL, 0, 0, 0)) >= 0);
    // Empty pool: no team re-roll offer.
    BB_CHECK_EQ(fx_find(&m, act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0)), -1);
    st = fx_apply(&m, act(BB_A_USE_REROLL, BB_RR_PRO, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].y, 6);
    BB_CHECK(m.players[mover].flags & BB_PF_USED_SKILL_B); // once per activation
}

// SK "Pro (Active)": "on a 1-2 the dice may not be re-rolled" — the Pro
// attempt is spent for the activation and the failed result stands (the
// player Falls Over; turnover).
BB_TEST(movement_pro_reroll_gate_fail_result_stands) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    fx_give_skill(&m, mover, BB_SK_PRO);
    fx_lineman(&m, 1, 0, 10, 8);
    static const uint8_t dice[] = {2, 2, 3, 3}; // dodge 2; Pro 2 (<3); armour holds
    bb_rng rng;
    bb_rng_script(&rng, dice, 4);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    st = fx_apply(&m, act(BB_A_USE_REROLL, BB_RR_PRO, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK(m.players[mover].flags & BB_PF_USED_SKILL_B);
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_PRONE); // fell in destination
    BB_CHECK_EQ(m.players[mover].y, 6);
    BB_CHECK_EQ(m.active_team, BB_AWAY); // turnover
}

// SK "Pro (Active)": Pro is once per ACTIVATION — after a Pro attempt
// (successful or not) a second failed test in the same activation must not
// offer it again; with no other source, no window opens at all.
BB_TEST(movement_pro_reroll_once_per_activation) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    fx_give_skill(&m, mover, BB_SK_PRO);
    fx_lineman(&m, 1, 0, 10, 8); // marks (10,7)
    fx_lineman(&m, 1, 1, 11, 5); // marks (10,6)
    // dodge1 (4+ for the dest marker): 2 fails, Pro 5 (3+), re-roll 4 passes.
    // dodge2 (3+): 2 fails -> Pro already used: no window; Falls Over; armour
    // 3,3 holds.
    static const uint8_t dice[] = {2, 5, 4, 2, 3, 3};
    bb_rng rng;
    bb_rng_script(&rng, dice, 6);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
    st = fx_apply(&m, act(BB_A_USE_REROLL, BB_RR_PRO, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    st = fx_apply(&m, act(BB_A_STEP, 0, 9, 6), &rng); // second dodge fails on 2
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK(!fx_has_type(&m, BB_A_USE_REROLL)); // no window: result stood
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.active_team, BB_AWAY); // turnover
}

// ENGINE-DIVERGENCE: SK "Dodge (Active)": "ONCE PER TURN, this player may
// re-roll a single Agility Test when attempting to Dodge." After the skill
// re-roll has been used, a second failed Dodge in the same turn must NOT be
// offered it again. The engine's once-only latch (TF_SKILL_USED in
// proc_test.c) lives in the per-test frame, so every new Dodge test offers
// the skill again — unlimited Dodge re-rolls per turn. (Sure Feet shares this
// code path and has the same defect.)
BB_TEST(movement_dodge_skill_once_per_turn) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    fx_give_skill(&m, mover, BB_SK_DODGE);
    fx_lineman(&m, 1, 0, 10, 8); // marks (10,7)
    fx_lineman(&m, 1, 1, 11, 5); // marks (10,6)
    // dodge1 (4+ for the dest marker): 2 fails, skill re-roll 4 passes.
    // dodge2 (3+): 2 fails -> rulebook: no re-roll left, Falls Over; armour 3,3.
    static const uint8_t dice[] = {2, 4, 2, 3, 3};
    bb_rng rng;
    bb_rng_script(&rng, dice, 5);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
    st = fx_apply(&m, act(BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_DODGE, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    st = fx_apply(&m, act(BB_A_STEP, 0, 9, 6), &rng); // second dodge fails on 2
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    // RULEBOOK: the Dodge skill re-roll was already used this turn, and there
    // are no team re-rolls — no re-roll window may appear; the player Falls
    // Over in (9,6) and a Turnover occurs.
    BB_CHECK(!fx_has_type(&m, BB_A_USE_REROLL)); // engine fails: offers it again
    if (!fx_has_type(&m, BB_A_USE_REROLL)) {
        BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_PRONE);
        BB_CHECK_EQ(m.players[mover].x, 9);
        BB_CHECK_EQ(m.active_team, BB_AWAY);
    }
}

// SK "Sure Feet (Active)": "Once per Turn, this player may re-roll a single
// D6 when attempting to Rush." A natural 1 on the Rush may be re-rolled
// before the Fall Over is applied.
BB_TEST(movement_sure_feet_reroll) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_player(&m, 0, 0, 5, 7, 1, 3, 3, 4, 9); // MA 1
    fx_give_skill(&m, mover, BB_SK_SURE_FEET);
    fx_lineman(&m, 1, 9, 24, 1);
    static const uint8_t dice[] = {1, 2}; // rush nat 1; Sure Feet re-roll 2 passes
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 6, 7), &rng); // free square
    st = fx_apply(&m, act(BB_A_STEP, 0, 7, 7), &rng); // rush fails on 1
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(fx_find(&m, act(BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_SURE_FEET, 0)) >= 0);
    st = fx_apply(&m, act(BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_SURE_FEET, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].x, 7);
    BB_CHECK_EQ(m.players[mover].rushes, 1);
    BB_CHECK_EQ(m.active_team, BB_HOME);
}

// SK "Sprint (Active)": "When this player performs a Move Action they may
// attempt to Rush one additional time than they would normally be allowed
// to" — i.e. three Rushes, then movement is exhausted.
BB_TEST(movement_sprint_third_rush) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_player(&m, 0, 0, 5, 7, 1, 3, 3, 4, 9); // MA 1
    fx_give_skill(&m, mover, BB_SK_SPRINT);
    fx_lineman(&m, 1, 9, 24, 1);
    static const uint8_t dice[] = {2, 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 6, 7), &rng); // free
    for (int x = 7; x <= 9; x++) {                    // three rushes
        st = fx_apply(&m, act(BB_A_STEP, 0, x, 7), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
    }
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].x, 9);
    BB_CHECK_EQ(m.players[mover].rushes, 3);
    BB_CHECK(!fx_has_type(&m, BB_A_STEP)); // no fourth rush
}

// ENGINE-DIVERGENCE: RR "Distracted": "A player that is Distracted does not
// have a Tackle Zone." A player adjacent only to a Distracted opponent is
// therefore Open (RR "Open Players") and may leave without a Dodge roll. The
// engine's bb_exerts_tz() (bb_match.c) checks only BB_PF_NO_TZ and ignores
// BB_PF_DISTRACTED, so the Distracted opponent still marks — the player reads
// as Marked and a Dodge is wrongly required. (Distracted *sources* are Phase
// 3 skills, but the status flag already exists and should suppress the TZ.)
BB_TEST(movement_distracted_opponent_not_marking) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    int opp = fx_lineman(&m, 1, 0, 10, 8);
    m.players[opp].flags |= BB_PF_DISTRACTED;
    bb_rng rng;
    bb_rng_script(&rng, 0, 0); // no dice may be consumed

    bb_status st = begin_move(&m, &rng, mover);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    // RULEBOOK: not Marked (Distracted opponent has no Tackle Zone).
    BB_CHECK(!bb_is_marked(&m, mover)); // engine fails here
    if (!bb_is_marked(&m, mover)) {
        st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
        BB_CHECK_EQ(m.players[mover].y, 6);
    }
}

// ====================== NEGATRAIT ACTIVATION GATES ===========================
// Mirror SK#BONE HEAD / REALLY STUPID / UNCHANNELLED FURY / TAKE ROOT: the
// D6 rolls "after declaring their Action"; failures confer Distracted (whose
// definition ends the activation, RR#DISTRACTED) or end it outright (UF), or
// Root the player (the declared Action continues in place). RR#TEAM RE-ROLLS:
// gate rolls are not on the no-re-roll list, so a failed gate offers the
// team re-roll window during the owner's turn.

// SK#BONE HEAD: 2+ passes; on a 1 the player becomes Distracted -> the
// activation immediately ends (RR#DISTRACTED) and the player counts as
// activated.
BB_TEST(gate_bone_head_fail_distracted_ends_activation) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 0, 1, 2, 2); // keeps the team turn alive
    fx_give_skill(&m, h1, BB_SK_BONE_HEAD);
    uint8_t script[] = {1};
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    bb_status st = begin_move(&m, &rng, h1);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(m.players[h1].flags & BB_PF_DISTRACTED);
    BB_CHECK(m.players[h1].flags & BB_PF_USED);
    BB_CHECK(!bb_rng_error(&rng));
}

// RR#YOUR TURN: declared once-per-turn actions are used even if never
// performed — the gate rolls AFTER the declaration, so a failed Bone Head
// still burns the team's Blitz.
BB_TEST(gate_rolls_after_declaration_burns_blitz) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 0, 1, 2, 2);
    fx_lineman(&m, 1, 0, 11, 7);
    fx_give_skill(&m, h1, BB_SK_BONE_HEAD);
    uint8_t script[] = {1};
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    fx_apply(&m, act(BB_A_ACTIVATE, h1, 0, 0), &rng);
    fx_apply(&m, act(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0), &rng);
    BB_CHECK(m.players[h1].flags & BB_PF_USED); // gate failed
    BB_CHECK_EQ(m.blitz_used, 1);               // the Blitz is spent anyway
}

// SK#REALLY STUPID: 4+, with +2 when an adjacent Standing team-mate is not
// Distracted and not itself Really Stupid: a roll of 2 passes WITH a helper
// and the action proceeds.
BB_TEST(gate_really_stupid_helper_gives_plus2) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 0, 1, 10, 8); // adjacent standing helper
    fx_give_skill(&m, h1, BB_SK_REALLY_STUPID);
    uint8_t script[] = {2}; // 2 + 2 = 4 -> pass
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    bb_status st = begin_move(&m, &rng, h1);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!(m.players[h1].flags & BB_PF_USED));      // acting normally
    BB_CHECK(fx_has_type(&m, BB_A_STEP));               // movement offered
    BB_CHECK(!bb_rng_error(&rng));
}

// SK#REALLY STUPID: a Really Stupid team-mate does NOT help — the same roll
// of 2 fails without a valid helper and the player becomes Distracted.
BB_TEST(gate_really_stupid_rs_helper_does_not_count) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, 0, 0, 10, 7);
    int h2 = fx_lineman(&m, 0, 1, 10, 8);
    fx_lineman(&m, 0, 2, 2, 2);
    fx_give_skill(&m, h1, BB_SK_REALLY_STUPID);
    fx_give_skill(&m, h2, BB_SK_REALLY_STUPID);
    uint8_t script[] = {2}; // no +2: 2 < 4 -> fail
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    begin_move(&m, &rng, h1);
    BB_CHECK(m.players[h1].flags & BB_PF_DISTRACTED);
    BB_CHECK(m.players[h1].flags & BB_PF_USED);
}

// SK#UNCHANNELLED FURY: 4+ with +2 "if they have declared a Block Action or
// a Blitz Action" — a roll of 2 passes for a Block declaration...
BB_TEST(gate_unchannelled_fury_block_gets_plus2) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 0, 1, 2, 2);
    int a1 = fx_lineman(&m, 1, 0, 11, 7);
    (void)a1;
    fx_give_skill(&m, h1, BB_SK_UNCHANNELLED_FURY);
    uint8_t script[] = {2, /*1d block pool*/ 3};
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    fx_apply(&m, act(BB_A_ACTIVATE, h1, 0, 0), &rng);
    fx_apply(&m, act(BB_A_DECLARE, BB_ACT_BLOCK, 0, 0), &rng);
    BB_CHECK(!(m.players[h1].flags & BB_PF_USED));
    BB_CHECK(fx_has_type(&m, BB_A_BLOCK_TARGET));
}

// ... and the same roll of 2 FAILS for a plain Move declaration: "their
// activation immediately ends" (no Distracted condition for UF).
BB_TEST(gate_unchannelled_fury_move_no_bonus_fails) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 0, 1, 2, 2);
    fx_give_skill(&m, h1, BB_SK_UNCHANNELLED_FURY);
    uint8_t script[] = {2};
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    begin_move(&m, &rng, h1);
    BB_CHECK(m.players[h1].flags & BB_PF_USED);
    BB_CHECK(!(m.players[h1].flags & BB_PF_DISTRACTED)); // UF: no Distracted
}

// RR#TEAM RE-ROLLS on a failed gate: the owner's coach may re-roll the gate
// die with a team re-roll; a successful re-roll lets the action proceed.
BB_TEST(gate_failure_offers_team_reroll_window) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 2);
    int h1 = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 0, 1, 2, 2);
    fx_give_skill(&m, h1, BB_SK_BONE_HEAD);
    uint8_t script[] = {1, /*re-rolled gate die*/ 5};
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    bb_status st = begin_move(&m, &rng, h1);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_HOME);
    BB_CHECK(fx_find(&m, act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0)) >= 0);
    BB_CHECK(fx_find(&m, act(BB_A_DECLINE_REROLL, 0, 0, 0)) >= 0);
    fx_apply(&m, act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0), &rng);
    BB_CHECK_EQ(m.rerolls[0], 1);                    // spent
    BB_CHECK(!(m.players[h1].flags & BB_PF_USED));   // passed: acting
    BB_CHECK(fx_has_type(&m, BB_A_STEP));
    BB_CHECK(!bb_rng_error(&rng));
}

// Declining the gate re-roll applies the failure (and keeps the re-roll).
BB_TEST(gate_reroll_declined_failure_stands) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 2);
    int h1 = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 0, 1, 2, 2);
    fx_give_skill(&m, h1, BB_SK_BONE_HEAD);
    uint8_t script[] = {1};
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    begin_move(&m, &rng, h1);
    fx_apply(&m, act(BB_A_DECLINE_REROLL, 0, 0, 0), &rng);
    BB_CHECK(m.players[h1].flags & BB_PF_USED);
    BB_CHECK(m.players[h1].flags & BB_PF_DISTRACTED);
    BB_CHECK_EQ(m.rerolls[0], 2); // not spent
}

// SK#LONER (X+): a failed Loner roll wastes the team re-roll — the gate
// failure stands and the re-roll is spent.
BB_TEST(gate_reroll_loner_waste) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 2);
    int h1 = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 0, 1, 2, 2);
    fx_give_skill(&m, h1, BB_SK_BONE_HEAD);
    fx_give_skill(&m, h1, BB_SK_LONER);
    m.players[h1].p_loner = 4;
    uint8_t script[] = {1, /*loner*/ 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    begin_move(&m, &rng, h1);
    fx_apply(&m, act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0), &rng);
    BB_CHECK(m.players[h1].flags & BB_PF_USED); // failure stands
    BB_CHECK_EQ(m.rerolls[0], 1);               // re-roll wasted
    BB_CHECK(!bb_rng_error(&rng));
}

// SK#TAKE ROOT: the D6 is only rolled "if they are Standing" — a Prone
// treeman's stand-up activation consumes no gate die.
BB_TEST(gate_take_root_prone_no_roll) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 0, 1, 2, 2);
    fx_give_skill(&m, h1, BB_SK_TAKE_ROOT);
    m.players[h1].stance = BB_STANCE_PRONE;
    bb_rng rng;
    bb_rng_script(&rng, 0, 0); // no dice may be consumed
    bb_status st = begin_move(&m, &rng, h1);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK(fx_has_type(&m, BB_A_STAND_UP));
}

// SK#TAKE ROOT: on a 1 the player becomes Rooted but "may perform the
// declared Action as normal" otherwise — the activation CONTINUES in place
// (no movement offered; ending the activation stays legal).
BB_TEST(gate_take_root_fail_rooted_continues_in_place) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 0, 1, 2, 2);
    fx_give_skill(&m, h1, BB_SK_TAKE_ROOT);
    uint8_t script[] = {1};
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    bb_status st = begin_move(&m, &rng, h1);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(m.players[h1].flags & BB_PF_ROOTED);
    BB_CHECK(!(m.players[h1].flags & BB_PF_USED)); // still activating
    BB_CHECK(!fx_has_type(&m, BB_A_STEP));         // rooted: no movement
    BB_CHECK(fx_has_type(&m, BB_A_END_ACTIVATION));
}
