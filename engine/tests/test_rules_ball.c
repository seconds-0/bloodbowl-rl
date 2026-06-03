// test_rules_ball.c — BB2025 rulebook tests: BALL HANDLING.
//
// Every test encodes what the RULEBOOK says, quoting the local mirror:
//   GAME = docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/core_rules/the_game_of_blood_bowl/index.html
//   RR   = .../core_rules/rules_and_regulations/index.html
//   ESS  = .../core_rules/game_essentials/index.html
//   FAQ  = .../core_rules/latest_faq/index.html (May 2026)
//
// Tests marked "// ENGINE-DIVERGENCE" assert the rulebook-required behaviour
// and are EXPECTED TO FAIL against the current engine; each comment explains
// the divergence. Do not "fix" these tests — fix the engine.
//
// Conventions used throughout:
//  * fx_match_midturn(.., rerolls=0) so failed tests never open re-roll
//    decision windows (scripted dice flow straight through).
//  * Team 0 (home) is the active team; team 1 (away) always has one far-away
//    player so a turnover hands the decision to team 1 (decision_team == 1
//    after fx_run is the observable for "a Turnover was caused"; the
//    m.turnover latch itself is cleared by the turn-end bookkeeping).
//  * D8 bounce/scatter directions: engine maps face f to DIR8[f-1] with
//    DIR8 = {-1,-1},{0,-1},{1,-1},{-1,0},{1,0},{-1,1},{0,1},{1,1}.
//    Face 5 = (+1,0), face 7 = (0,+1), face 4 = (-1,0), face 8 = (+1,+1).
#include "bb/bb_match.h"
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb_fixtures.h"
#include "bb_test.h"

static bb_action mk(int type, int arg, int x, int y) {
    bb_action a = {(uint8_t)type, (uint8_t)arg, (uint8_t)x, (uint8_t)y};
    return a;
}

// Activate `slot` and declare action `kind`; leaves the MOVE machine waiting.
static bb_status fx_activate(bb_match* m, bb_rng* rng, int slot, int kind) {
    fx_apply(m, mk(BB_A_ACTIVATE, slot, 0, 0), rng);
    return fx_apply(m, mk(BB_A_DECLARE, kind, 0, 0), rng);
}

// ============================================================================
// PASS — accuracy, range bands, fumbles  (GAME "PASS ACTIONS!")
// ============================================================================

// GAME/PERFORMING A PASS ACTION: "When a player declares a Pass Action they
// are first allowed to make a Move Action, though they cannot continue to
// move after the Pass Action has been attempted."
// GAME/ACCURATE PASS: "If the Passing Ability Test is successful ... the ball
// will land in the target square." GAME/CATCHING: accurate pass has no catch
// modifier. RR/THE TURNOVER: a completed pass to a team-mate is no turnover.
BB_TEST(ball_pass_move_then_quick_accurate_caught) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 3, 9); // PA 3+
    int receiver = fx_lineman(&m, 0, 1, 9, 7);              // AG 3+
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, thrower);
    uint8_t script[] = {3, 3}; // PA test 3 (quick, no mod, 3+) ; catch 3 (3+)
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    // Free Move Action first: one step to (6,7).
    fx_apply(&m, mk(BB_A_STEP, 0, 6, 7), &rng);
    // Quick pass from (6,7) to (9,7): dx=3, d^2=9 <= 3.5^2 -> Quick, mod 0.
    bb_status st = fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 9, 7), &rng);
    BB_CHECK(st == BB_STATUS_DECISION);
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(m.ball.carrier, receiver);
    BB_CHECK(m.players[receiver].flags & BB_PF_HAS_BALL);
    BB_CHECK(!(m.players[thrower].flags & BB_PF_HAS_BALL));
    BB_CHECK_EQ(m.pass_used, 1);
    // The pass ended the thrower's activation; no further movement offered —
    // we are back at the team-turn activation choice, no turnover.
    BB_CHECK(m.players[thrower].flags & BB_PF_USED);
    BB_CHECK(fx_has_type(&m, BB_A_ACTIVATE));
    BB_CHECK(!fx_has_type(&m, BB_A_STEP));
    BB_CHECK_EQ(m.decision_team, 0);
}

// GAME/MEASURE RANGE + TEST FOR ACCURACY: Quick Pass no modifier, Short Pass
// -1. The range-ruler band boundary is 3.5 squares: (3,1) (d^2=10) is Quick,
// (2,3) (d^2=13) is Short ("if the target square sits partially within two
// sections ... it is always considered to be in the further away").
BB_TEST(ball_pass_quick_short_boundary) {
    // (a) dx=3,dy=1 is Quick: PA 3+ rolls 3, no modifier -> Accurate.
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 3, 9);
        int receiver = fx_lineman(&m, 0, 1, 8, 8);
        fx_lineman(&m, 1, 0, 20, 2);
        fx_ball_held(&m, thrower);
        uint8_t script[] = {3, 3};
        bb_rng rng;
        bb_rng_script(&rng, script, 2);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, thrower, BB_ACT_PASS);
        fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 8), &rng);
        BB_CHECK_EQ(m.ball.carrier, receiver);
    }
    // (b) dx=2,dy=3 is Short: PA 3+ rolls 3, -1 -> modified 2 -> Inaccurate.
    // GAME/INACCURATE PASS: "The ball will Scatter (3) from the target square
    // before landing." GAME/RESOLVE PASS ACTION: an unoccupied landing square
    // means one final Bounce. Then RR/THE TURNOVER: pass that no active
    // player catches, ball comes to rest -> Turnover.
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 3, 9);
        fx_lineman(&m, 1, 0, 20, 2);
        fx_ball_held(&m, thrower);
        uint8_t script[] = {3, 5, 5, 5, 5}; // PA 3; scatter (+1,0) x3; bounce (+1,0)
        bb_rng rng;
        bb_rng_script(&rng, script, 5);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, thrower, BB_ACT_PASS);
        fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 7, 10), &rng);
        BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
        BB_CHECK_EQ(m.ball.x, 11);
        BB_CHECK_EQ(m.ball.y, 10);
        BB_CHECK_EQ(m.decision_team, 1); // turnover ended team 0's turn
    }
}

// GAME/TEST FOR ACCURACY: "Long Pass, apply a -2 modifier ... Long Bomb,
// apply a -3 modifier."
BB_TEST(ball_pass_long_and_bomb_band_modifiers) {
    // (a) Long (dx=7, d^2=49): PA 2+ rolls 3, -2 -> modified 1?? No: modified
    // result 1 after modifiers is a FUMBLE (covered separately); here roll 3
    // -2 = 1 would fumble, so use roll 3 against PA 2+ Long: 3-2=1 -> that IS
    // the fumble case. Use PA 2+ and roll 3 for Long Bomb instead.
    // Long with PA 2+: roll 4 -> 4-2=2 >= 2 -> Accurate (pins mod <= -2 via
    // the bomb case below; pins mod >= -2 because roll 3 fumbles, see
    // ball_pass_modified_one_fumble).
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9); // PA 2+
        int receiver = fx_lineman(&m, 0, 1, 12, 7);             // dx=7 Long
        fx_lineman(&m, 1, 0, 20, 2);
        fx_ball_held(&m, thrower);
        uint8_t script[] = {4, 3};
        bb_rng rng;
        bb_rng_script(&rng, script, 2);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, thrower, BB_ACT_PASS);
        fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 12, 7), &rng);
        BB_CHECK_EQ(m.ball.carrier, receiver);
    }
    // (b) Long Bomb (dx=10, d^2=100): PA 2+ rolls 4, -3 -> modified 1 is the
    // fumble edge again; roll 5 -> 2 -> Accurate; roll 4 fumbles. To pin -3
    // as "inaccurate, not accurate", use PA 2+ roll 4 vs Long (would be
    // accurate at -2) and Long Bomb roll 5 accurate here:
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9);
        int receiver = fx_lineman(&m, 0, 1, 15, 7); // dx=10 Long Bomb
        fx_lineman(&m, 1, 0, 20, 2);
        fx_ball_held(&m, thrower);
        uint8_t script[] = {5, 3};
        bb_rng rng;
        bb_rng_script(&rng, script, 2);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, thrower, BB_ACT_PASS);
        fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 15, 7), &rng);
        BB_CHECK_EQ(m.ball.carrier, receiver);
    }
    // (c) Long Bomb with PA 3+: roll 5 -> 5-3=2 < 3 -> Inaccurate (pins the
    // band as -3, since -2 would make it accurate).
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 3, 9);
        fx_lineman(&m, 1, 0, 20, 2);
        fx_ball_held(&m, thrower);
        uint8_t script[] = {5, 5, 5, 5, 5}; // PA 5; scatter (+1,0) x3; bounce (+1,0)
        bb_rng rng;
        bb_rng_script(&rng, script, 5);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, thrower, BB_ACT_PASS);
        fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 15, 7), &rng);
        BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
        BB_CHECK_EQ(m.ball.x, 19);
        BB_CHECK_EQ(m.ball.y, 7);
        BB_CHECK_EQ(m.decision_team, 1);
    }
}

// ENGINE-DIVERGENCE: maximum pass range. GAME/DECLARE TARGET SQUARE: "The
// declared square must be wholly underneath the maximum range of the Range
// Ruler" — the ruler is 13.5 squares long, so any square with
// d^2 <= 13.5^2 = 182.25 is a legal Long Bomb target (e.g. dx=12,dy=6,
// d^2=180). The engine gates pass targets at d^2 <= 169 (proc_move.c), which
// wrongly forbids (13,1),(13,2),(13,3),(12,6),(11,7),(10,9).
BB_TEST(ball_pass_max_range_legality) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_player(&m, 0, 0, 5, 4, 6, 3, 3, 3, 9);
    fx_lineman(&m, 1, 0, 24, 2);
    fx_ball_held(&m, thrower);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    // d^2 = 144+36 = 180 <= 182.25: rulebook-legal Long Bomb target.
    BB_CHECK(fx_find(&m, mk(BB_A_PASS_TARGET, 0, 17, 10)) >= 0); // FAILS (engine caps at 169)
    // d^2 = 169: legal in both.
    BB_CHECK(fx_find(&m, mk(BB_A_PASS_TARGET, 0, 18, 4)) >= 0);
    // d^2 = 196 > 182.25: beyond the ruler, illegal.
    BB_CHECK(fx_find(&m, mk(BB_A_PASS_TARGET, 0, 19, 4)) == -1);
}

// GAME/ACCURATE PASS: "If the Passing Ability Test is successful, or the roll
// is a natural 6, then the pass is an Accurate Pass."
BB_TEST(ball_pass_natural_six_accurate) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 5, 9); // PA 5+
    int receiver = fx_lineman(&m, 0, 1, 15, 7);             // Long Bomb, -3
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, thrower);
    uint8_t script[] = {6, 3}; // natural 6 beats PA 5+ -3; catch 3+
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 15, 7), &rng);
    BB_CHECK_EQ(m.ball.carrier, receiver);
    BB_CHECK_EQ(m.decision_team, 0);
}

// ENGINE-DIVERGENCE: fumbled pass. GAME/FUMBLED PASS: "If the Passing Ability
// Test is a 1 after modifiers, or the roll is a natural 1, then it will be a
// Fumbled Pass. The ball is dropped and will Bounce from the throwing
// player's square and a Turnover will be caused." The engine (proc_ball.c,
// TODO(phase3)) treats every failed pass as Inaccurate and Scatters (3) from
// the TARGET square instead of bouncing once from the thrower.
BB_TEST(ball_pass_fumble_bounces_from_thrower) {
    // (a) natural 1, Quick Pass.
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9); // PA 2+
        fx_lineman(&m, 1, 0, 20, 2);
        fx_ball_held(&m, thrower);
        uint8_t script[] = {1, 5}; // nat 1; one Bounce (+1,0) from thrower
        bb_rng rng;
        bb_rng_script(&rng, script, 2);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, thrower, BB_ACT_PASS);
        fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
        BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND); // FAILS (engine scatters from target)
        BB_CHECK_EQ(m.ball.x, 6);
        BB_CHECK_EQ(m.ball.y, 7);
        BB_CHECK_EQ(m.decision_team, 1); // turnover
    }
    // (b) modified result exactly 1: PA 4+ Short Pass (-1), roll 2 -> 1.
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 4, 9); // PA 4+
        fx_lineman(&m, 1, 0, 20, 2);
        fx_ball_held(&m, thrower);
        uint8_t script[] = {2, 5}; // 2 - 1 = 1 -> fumble; Bounce from thrower
        bb_rng rng;
        bb_rng_script(&rng, script, 2);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, thrower, BB_ACT_PASS);
        fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 10, 7), &rng); // dx=5 Short
        BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND); // FAILS
        BB_CHECK_EQ(m.ball.x, 6);
        BB_CHECK_EQ(m.ball.y, 7);
        BB_CHECK_EQ(m.decision_team, 1);
    }
}

// ENGINE-DIVERGENCE: a fumble is ALWAYS a turnover. RR/THE TURNOVER: "A
// player on the active team attempts a Pass Action and Fumbles the ball" —
// unconditional; the bounce-caught-by-team-mate carve-out applies only to the
// failed-CATCH bullet. The engine's possession check (proc_move.c
// MV_AWAIT_ACTION) would clear the turnover if a team-mate ends up holding
// the ball after the (mis-implemented) scatter.
BB_TEST(ball_pass_fumble_turnover_even_if_teammate_catches) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9);   // PA 2+
    int mate = fx_player(&m, 0, 1, 6, 7, 6, 3, 2, 3, 9);      // AG 2+
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, thrower);
    // nat 1 -> Bounce from (5,7) face 5 -> (6,7) = mate; catch of a Bounced
    // ball is -1 (GAME/CATCHING) -> AG 2+ needs 3; roll 3 catches.
    uint8_t script[] = {1, 5, 3};
    bb_rng rng;
    bb_rng_script(&rng, script, 3);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 9, 7), &rng);
    BB_CHECK_EQ(m.ball.carrier, mate);   // FAILS (engine scatters from target)
    BB_CHECK_EQ(m.decision_team, 1);     // FAILS: turnover despite possession
}

// GAME/TEST FOR ACCURACY: "Apply a -1 modifier for each opposition player
// Marking the player performing the Pass Action."
BB_TEST(ball_pass_marked_thrower_modifier) {
    // (a) one marker, PA 3+ Quick, roll 4 -> 3 -> Accurate.
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 3, 9);
        int receiver = fx_lineman(&m, 0, 1, 8, 7);
        fx_lineman(&m, 1, 0, 5, 6); // marks the thrower
        fx_lineman(&m, 1, 1, 20, 2);
        fx_ball_held(&m, thrower);
        uint8_t script[] = {4, 3};
        bb_rng rng;
        bb_rng_script(&rng, script, 2);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, thrower, BB_ACT_PASS);
        fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
        BB_CHECK_EQ(m.ball.carrier, receiver);
    }
    // (b) one marker, roll 3 -> 2 -> Inaccurate (pins the -1).
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 3, 9);
        fx_lineman(&m, 0, 1, 8, 7);
        fx_lineman(&m, 1, 0, 5, 6);
        fx_lineman(&m, 1, 1, 20, 2);
        fx_ball_held(&m, thrower);
        uint8_t script[] = {3, 5, 5, 5, 5}; // scatter past the receiver; bounce
        bb_rng rng;
        bb_rng_script(&rng, script, 5);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, thrower, BB_ACT_PASS);
        fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
        BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
        BB_CHECK_EQ(m.ball.x, 12);
        BB_CHECK_EQ(m.ball.y, 7);
        BB_CHECK_EQ(m.decision_team, 1);
    }
}

// GAME/RESOLVE PASS ACTION: "If the ball lands in an unoccupied square, then
// it will Bounce from that square." + RR/THE TURNOVER bullet 7.
BB_TEST(ball_pass_accurate_to_empty_square_bounces) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9);
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, thrower);
    uint8_t script[] = {6, 5}; // accurate; Bounce (+1,0)
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 9);
    BB_CHECK_EQ(m.ball.y, 7);
    BB_CHECK_EQ(m.decision_team, 1); // no active player caught -> turnover
}

// GAME/RESOLVE PASS ACTION: "If the ball lands in an unoccupied square, then
// it will Bounce from that square" — this applies to an INACCURATE pass too:
// after the Scatter (3) the ball "lands", and an empty landing square takes
// one final Bounce. (Regression: adversarial review M7 — the engine used to
// let an inaccurate pass come to rest one D8 hop short.)
BB_TEST(ball_pass_inaccurate_to_empty_square_bounces) {
    // (a) Scatter (3) ends on an empty square -> exactly ONE final Bounce,
    // then the ball comes to rest -> turnover.
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 3, 9); // PA 3+
        fx_lineman(&m, 1, 0, 20, 2);
        fx_ball_held(&m, thrower);
        // Quick to empty (8,7): roll 2 -> failed, not a fumble -> Inaccurate.
        // Scatter (3): faces 5,5,5 -> (11,7) empty; final Bounce (+1,0) ->
        // (12,7) rest. Exactly 5 dice (a second bounce would exhaust the
        // script and error).
        uint8_t script[] = {2, 5, 5, 5, 5};
        bb_rng rng;
        bb_rng_script(&rng, script, 5);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, thrower, BB_ACT_PASS);
        bb_status st = fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
        BB_CHECK_EQ(m.ball.x, 12);
        BB_CHECK_EQ(m.ball.y, 7);
        BB_CHECK_EQ(m.decision_team, 1); // incomplete pass -> turnover
    }
    // (b) The final hop is a BOUNCE, not another pass-flight scatter: a
    // player in the bounce square catches at -1 (GAME/CATCHING "a ball that
    // has Bounced"), unlike the unmodified catch in the Scatter landing
    // square. AG 3+ needs 4; roll 3 FAILS (pins the -1) -> Bounce on -> rest.
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 3, 9); // PA 3+
        int mate = fx_lineman(&m, 0, 1, 12, 7);                 // AG 3+
        fx_lineman(&m, 1, 0, 20, 2);
        fx_ball_held(&m, thrower);
        // PA 2 -> Inaccurate; Scatter faces 5,5,5 -> (11,7) empty; final
        // Bounce (+1,0) onto the mate; Bounced catch -1 -> AG 3+ needs 4;
        // roll 3 fails; Bounce again (+1,0) -> (13,7) rest -> turnover.
        uint8_t script[] = {2, 5, 5, 5, 5, 3, 5};
        bb_rng rng;
        bb_rng_script(&rng, script, 7);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, thrower, BB_ACT_PASS);
        bb_status st = fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK(!(m.players[mate].flags & BB_PF_HAS_BALL));
        BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
        BB_CHECK_EQ(m.ball.x, 13);
        BB_CHECK_EQ(m.ball.y, 7);
        BB_CHECK_EQ(m.decision_team, 1);
    }
}

// ENGINE-DIVERGENCE: weather vs the PA test. GAME/WEATHER TABLE: POURING
// RAIN affects "pick up or Catch the ball, or Intercept" — NOT the Passing
// Ability Test. The engine applies a -1 to the PA test in rain
// (proc_ball.c pass_advance), which the rulebook reserves for Very Sunny.
BB_TEST(ball_pass_rain_does_not_modify_pa_test) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    m.weather = BB_WEATHER_RAIN;
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 3, 9); // PA 3+
    int receiver = fx_lineman(&m, 0, 1, 8, 7);              // AG 3+
    fx_lineman(&m, 0, 2, 15, 2);
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, thrower);
    // Rulebook: PA roll 3 vs 3+ unmodified -> Accurate; catch in rain is -1
    // (AG 3+ needs 4) -> roll 4 catches.
    uint8_t script[] = {3, 4};
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
    BB_CHECK_EQ(m.ball.carrier, receiver); // FAILS (engine: rain -1 on PA -> inaccurate)
    BB_CHECK_EQ(m.decision_team, 0);
}

// GAME/WEATHER TABLE / POURING RAIN: "Whenever a player attempts to pick up
// or Catch the ball ... they suffer a -1 modifier to the roll."
BB_TEST(ball_pass_rain_catch_minus_one) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    m.weather = BB_WEATHER_RAIN;
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9); // PA 2+
    fx_lineman(&m, 0, 1, 8, 7);                             // AG 3+ receiver
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, thrower);
    // nat 6 accurate (immune to any PA modifier dispute); catch roll 3 vs
    // AG 3+ -1 (rain) = needs 4 -> FAILS -> Bounce (+1,0) -> rest -> turnover.
    uint8_t script[] = {6, 3, 5};
    bb_rng rng;
    bb_rng_script(&rng, script, 3);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 9);
    BB_CHECK_EQ(m.ball.y, 7);
    BB_CHECK_EQ(m.decision_team, 1);
}

// GAME/WEATHER TABLE / VERY SUNNY: "Whenever a player makes a Passing
// Ability Test, apply a -1 modifier to the roll."
BB_TEST(ball_pass_very_sunny_minus_one) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    m.weather = BB_WEATHER_SUNNY;
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 3, 9); // PA 3+
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, thrower);
    // Rulebook: roll 3, -1 (sunny) -> 2 -> Inaccurate -> Scatter (3) from the
    // empty target (8,7): faces 5,5,5 -> (11,7), final Bounce (+1,0) ->
    // (12,7), rest, turnover.
    uint8_t script[] = {3, 5, 5, 5, 5};
    bb_rng rng;
    bb_rng_script(&rng, script, 5);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 12);
    BB_CHECK_EQ(m.ball.y, 7);
    BB_CHECK_EQ(m.decision_team, 1);
}

// ENGINE-DIVERGENCE: GAME/WEATHER TABLE / BLIZZARD: "when a player makes a
// Pass Action, they may only attempt to make a Quick Pass or a Short Pass."
// The engine offers all range bands regardless of weather (TODO(phase3)).
BB_TEST(ball_pass_blizzard_quick_short_only) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    m.weather = BB_WEATHER_BLIZZARD;
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 3, 9);
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, thrower);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    BB_CHECK(fx_find(&m, mk(BB_A_PASS_TARGET, 0, 8, 7)) >= 0);   // Quick: legal
    BB_CHECK(fx_find(&m, mk(BB_A_PASS_TARGET, 0, 10, 7)) >= 0);  // Short: legal
    BB_CHECK(fx_find(&m, mk(BB_A_PASS_TARGET, 0, 13, 7)) == -1); // FAILS: Long must be illegal
    BB_CHECK(fx_find(&m, mk(BB_A_PASS_TARGET, 0, 16, 7)) == -1); // FAILS: Long Bomb must be illegal
}

// ============================================================================
// INTERCEPTIONS  (GAME "INTERCEPTIONS")
// ============================================================================

// ENGINE-DIVERGENCE: interceptions are not implemented (proc_ball.c
// TODO(phase3)). GAME/INTERCEPTIONS: ruler from thrower to landing square;
// "If the Range Ruler overlaps any squares containing a Standing opposition
// player, then their Coach may choose one of them to attempt to Intercept";
// AG test, -3 vs an Accurate Pass (-2 vs Inaccurate), -1 per player Marking
// the interceptor; "if the Agility Test is successful, or a natural 6 is
// rolled ... The player immediately gains possession of the ball and a
// Turnover is caused." (The defending coach's pick should be a decision
// point for team 1; the engine never offers one.)
BB_TEST(ball_pass_interception_accurate_minus_three) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9);   // PA 2+
    fx_lineman(&m, 0, 1, 9, 7);                               // receiver
    int opp = fx_player(&m, 1, 0, 7, 7, 6, 3, 2, 3, 9);       // AG 2+, on the line
    fx_ball_held(&m, thrower);
    // Short pass (dx=4): PA 2+ -1, roll 5 -> Accurate. Interception: AG 2+
    // -3 -> needs 5; roll 5 -> intercepted, turnover.
    uint8_t script[] = {5, 5};
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 9, 7), &rng);
    BB_CHECK_EQ(m.ball.carrier, opp);            // FAILS (engine: receiver catches)
    BB_CHECK(m.players[opp].flags & BB_PF_HAS_BALL);
    BB_CHECK_EQ(m.decision_team, 1);             // FAILS: interception = turnover
}

// ============================================================================
// CATCHING  (GAME "CATCHING THE BALL")
// ============================================================================

// RR/THE TURNOVER: "A player on the inactive team ends up in possession of
// the ball following an attempted Pass Action ..." -> Turnover. An accurate
// pass may target an opponent's square; that player must attempt the catch.
BB_TEST(ball_pass_caught_by_opponent_is_turnover) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9);
    int opp = fx_player(&m, 1, 0, 8, 7, 6, 3, 2, 3, 9); // AG 2+ standing
    fx_ball_held(&m, thrower);
    uint8_t script[] = {6, 5}; // accurate; opponent catches (no modifier)
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
    BB_CHECK_EQ(m.ball.carrier, opp);
    BB_CHECK_EQ(m.decision_team, 1); // turnover
}

// GAME/CATCHING THE BALL: "Apply a -1 modifier for each opposition player
// that is Marking the player attempting to Catch the ball" and "If the
// Agility Test is failed, or a natural 1 is rolled, the player fails to
// Catch the ball and it will Bounce from the square they are in."
BB_TEST(ball_catch_marking_modifier_and_natural_one) {
    // (a) one marker: AG 3+ needs 4; roll 4 catches.
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9);
        int receiver = fx_lineman(&m, 0, 1, 8, 7);
        fx_lineman(&m, 1, 0, 8, 8); // marks the receiver
        fx_lineman(&m, 1, 1, 20, 2);
        fx_ball_held(&m, thrower);
        uint8_t script[] = {6, 4};
        bb_rng rng;
        bb_rng_script(&rng, script, 2);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, thrower, BB_ACT_PASS);
        fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
        BB_CHECK_EQ(m.ball.carrier, receiver);
        BB_CHECK_EQ(m.decision_team, 0);
    }
    // (b) one marker: roll 3 fails (pins the -1) -> Bounce -> rest -> turnover.
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9);
        fx_lineman(&m, 0, 1, 8, 7);
        fx_lineman(&m, 1, 0, 8, 8);
        fx_lineman(&m, 1, 1, 20, 2);
        fx_ball_held(&m, thrower);
        uint8_t script[] = {6, 3, 5}; // catch fails; Bounce (+1,0) -> (9,7)
        bb_rng rng;
        bb_rng_script(&rng, script, 3);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, thrower, BB_ACT_PASS);
        fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
        BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
        BB_CHECK_EQ(m.ball.x, 9);
        BB_CHECK_EQ(m.ball.y, 7);
        BB_CHECK_EQ(m.decision_team, 1);
    }
    // (c) natural 1 always fails, even for AG 2+ unmarked.
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9);
        fx_player(&m, 0, 1, 8, 7, 6, 3, 2, 3, 9); // AG 2+
        fx_lineman(&m, 1, 0, 20, 2);
        fx_ball_held(&m, thrower);
        uint8_t script[] = {6, 1, 5};
        bb_rng rng;
        bb_rng_script(&rng, script, 3);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, thrower, BB_ACT_PASS);
        fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
        BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
        BB_CHECK_EQ(m.ball.x, 9);
        BB_CHECK_EQ(m.ball.y, 7);
        BB_CHECK_EQ(m.decision_team, 1);
    }
}

// GAME/CATCHING THE BALL: "If the player is attempting to Catch a ball that
// has Bounced, apply a -1 modifier."
BB_TEST(ball_catch_bounced_minus_one) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9);
    fx_lineman(&m, 0, 1, 9, 7); // AG 3+, adjacent to the empty target
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, thrower);
    // Accurate to empty (8,7); Bounce (+1,0) onto the catcher; catch of a
    // Bounced ball is -1 -> AG 3+ needs 4 -> roll 3 FAILS (pins the -1) ->
    // Bounce again (+1,0) -> (10,7) rest -> turnover.
    uint8_t script[] = {6, 5, 3, 5};
    bb_rng rng;
    bb_rng_script(&rng, script, 4);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 10);
    BB_CHECK_EQ(m.ball.y, 7);
    BB_CHECK_EQ(m.decision_team, 1);
}

// ENGINE-DIVERGENCE: catching a SCATTERED ball is unmodified. GAME/CATCHING
// lists exactly three modifiers: Bounced -1, Thrown-in -1, -1 per marker. An
// inaccurate pass "will Scatter (3)" (GAME/INACCURATE PASS) — a Scatter is
// not a Bounce (RR/DEVIATE AND SCATTER vs RR/BOUNCING BALLS), so a player in
// the landing square catches with NO modifier. The engine routes every
// scatter landing through its bounce path with a hardwired -1 (proc_ball.c
// scatter_advance).
BB_TEST(ball_catch_scattered_inaccurate_pass_unmodified) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 3, 9); // PA 3+
    int mate = fx_lineman(&m, 0, 1, 11, 7);                 // AG 3+ at scatter end
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, thrower);
    // Quick to empty (8,7), roll 2 -> Inaccurate (2 != 1 modified, not nat 1).
    // Scatter (3): faces 5,5,5 -> (9,7),(10,7),(11,7) = mate's square.
    // Rulebook: unmodified catch, AG 3+ roll 3 -> caught, NO turnover.
    uint8_t script[] = {2, 5, 5, 5, 3};
    bb_rng rng;
    bb_rng_script(&rng, script, 5);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
    BB_CHECK_EQ(m.ball.carrier, mate);   // FAILS (engine: -1, roll 3 misses)
    BB_CHECK_EQ(m.decision_team, 0);     // FAILS
}

// ENGINE-DIVERGENCE: Distracted players cannot catch. RR/DISTRACTED: "Whilst
// a player is Distracted, they ... cannot attempt to Catch the ball." +
// GAME/CATCHING: "If a Prone or Stunned player, or a player that is
// Distracted, is required to Catch a ball, they will automatically fail the
// Agility Test and the ball will Bounce." The engine rolls a normal catch
// test for a Distracted player (proc_ball.c catch_advance never checks the
// flag).
BB_TEST(ball_catch_distracted_auto_fails) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9);
    int rec = fx_player(&m, 0, 1, 8, 7, 6, 3, 2, 3, 9); // AG 2+
    m.players[rec].flags |= BB_PF_DISTRACTED | BB_PF_NO_TZ;
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, thrower);
    // Accurate at the Distracted player: NO catch roll; ball Bounces (+1,0)
    // -> (9,7) rest -> turnover (no active player caught).
    uint8_t script[] = {6, 5};
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND); // FAILS (engine: catch rolled & made)
    BB_CHECK_EQ(m.ball.x, 9);
    BB_CHECK_EQ(m.ball.y, 7);
    BB_CHECK_EQ(m.decision_team, 1);
}

// GAME/CATCHING: a Prone player "will automatically fail the Agility Test
// and the ball will Bounce" — no dice are rolled for the attempt.
BB_TEST(ball_bounce_onto_prone_player_bounces_again) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9);
    int prone = fx_lineman(&m, 0, 1, 9, 7);
    m.players[prone].stance = BB_STANCE_PRONE;
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, thrower);
    // Accurate to empty (8,7); Bounce (+1,0) onto the prone player: NO catch
    // roll; Bounce again (+1,0) -> (10,7) rest -> turnover. Exactly 3 dice.
    uint8_t script[] = {6, 5, 5};
    bb_rng rng;
    bb_rng_script(&rng, script, 3);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    bb_status st = fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 8, 7), &rng);
    BB_CHECK(st == BB_STATUS_DECISION); // not ERROR: no extra die consumed
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 10);
    BB_CHECK_EQ(m.ball.y, 7);
    BB_CHECK_EQ(m.decision_team, 1);
}

// RR/THE TURNOVER (failed-catch carve-out): "if the ball Bounces from the
// player that failed to Catch the ball directly into a square containing a
// player from the active team who successfully Catches the ball, no Turnover
// is caused."
BB_TEST(ball_catch_fail_bounce_to_teammate_no_turnover) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 2, 9);
    fx_player(&m, 0, 1, 9, 7, 6, 3, 4, 3, 9);               // AG 4+ receiver
    int mate2 = fx_player(&m, 0, 2, 10, 7, 6, 3, 2, 3, 9);  // AG 2+
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, thrower);
    // Short pass nat 6 accurate; receiver rolls 2 vs AG 4+ -> fails; Bounce
    // (+1,0) onto mate2; Bounced catch -1: AG 2+ needs 3; roll 3 -> caught.
    uint8_t script[] = {6, 2, 5, 3};
    bb_rng rng;
    bb_rng_script(&rng, script, 4);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 9, 7), &rng);
    BB_CHECK_EQ(m.ball.carrier, mate2);
    BB_CHECK_EQ(m.decision_team, 0); // NO turnover
}

// ============================================================================
// HAND-OFF  (GAME "HAND-OFF ACTIONS!")
// ============================================================================

// GAME/PERFORMING A HAND-OFF: receiver "must then attempt to Catch the ball"
// — the catch modifier list has no entry for a hand-off, so it is an
// unmodified AG test. GAME/HAND-OFF ACTION: "Only a single Hand-off Action
// can be declared each Turn."
BB_TEST(ball_handoff_unmodified_catch_once_per_turn) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int carrier = fx_lineman(&m, 0, 0, 5, 7);
    int receiver = fx_lineman(&m, 0, 1, 6, 7); // AG 3+
    fx_lineman(&m, 0, 2, 15, 2);
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, carrier);
    uint8_t script[] = {3}; // catch 3 vs AG 3+ unmodified (pins mod == 0)
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, carrier, BB_ACT_HANDOFF);
    fx_apply(&m, mk(BB_A_HANDOFF_TARGET, 0, 6, 7), &rng);
    BB_CHECK_EQ(m.ball.carrier, receiver);
    BB_CHECK_EQ(m.handoff_used, 1);
    BB_CHECK(m.players[carrier].flags & BB_PF_USED);
    BB_CHECK_EQ(m.decision_team, 0); // no turnover
    // Second hand-off this turn must not be declarable (receiver now carries).
    fx_apply(&m, mk(BB_A_ACTIVATE, receiver, 0, 0), &rng);
    BB_CHECK(fx_find(&m, mk(BB_A_DECLARE, BB_ACT_HANDOFF, 0, 0)) == -1);
    // The Pass Action is a separate once-per-turn limit, still available.
    BB_CHECK(fx_find(&m, mk(BB_A_DECLARE, BB_ACT_PASS, 0, 0)) >= 0);
}

// GAME/PERFORMING A HAND-OFF: "the player that declared the Hand-off must
// finish their Move Action adjacent to a Standing team-mate" — prone
// team-mates, opponents and non-adjacent team-mates are not legal targets.
BB_TEST(ball_handoff_target_legality) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int carrier = fx_lineman(&m, 0, 0, 5, 7);
    int prone_mate = fx_lineman(&m, 0, 1, 4, 7);
    m.players[prone_mate].stance = BB_STANCE_PRONE;
    fx_lineman(&m, 0, 2, 6, 8); // standing diagonal team-mate: legal
    fx_lineman(&m, 0, 3, 8, 7); // non-adjacent team-mate: illegal
    fx_lineman(&m, 1, 0, 5, 8); // adjacent standing opponent: illegal
    fx_lineman(&m, 1, 1, 20, 2);
    fx_ball_held(&m, carrier);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, carrier, BB_ACT_HANDOFF);
    BB_CHECK(fx_find(&m, mk(BB_A_HANDOFF_TARGET, 0, 6, 8)) >= 0);
    BB_CHECK(fx_find(&m, mk(BB_A_HANDOFF_TARGET, 0, 4, 7)) == -1);
    BB_CHECK(fx_find(&m, mk(BB_A_HANDOFF_TARGET, 0, 5, 8)) == -1);
    BB_CHECK(fx_find(&m, mk(BB_A_HANDOFF_TARGET, 0, 8, 7)) == -1);
}

// ENGINE-DIVERGENCE: GAME/PERFORMING A HAND-OFF: the receiver must be "a
// Standing team-mate who has not lost their Tackle Zone" — a Distracted
// team-mate (RR/DISTRACTED: "does not have a Tackle Zone") is not a legal
// hand-off target. The engine only checks stance (proc_move.c move_legal).
BB_TEST(ball_handoff_distracted_receiver_illegal) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int carrier = fx_lineman(&m, 0, 0, 5, 7);
    int distracted = fx_lineman(&m, 0, 1, 6, 7);
    m.players[distracted].flags |= BB_PF_DISTRACTED | BB_PF_NO_TZ;
    fx_lineman(&m, 0, 2, 4, 7); // a normal team-mate keeps the declaration legal
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, carrier);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, carrier, BB_ACT_HANDOFF);
    BB_CHECK(fx_find(&m, mk(BB_A_HANDOFF_TARGET, 0, 4, 7)) >= 0);
    BB_CHECK(fx_find(&m, mk(BB_A_HANDOFF_TARGET, 0, 6, 7)) == -1); // FAILS
}

// RR/THE TURNOVER: "attempts to Catch the ball following a ... Hand-off
// Action and fails, resulting in it coming to rest on the ground" -> Turnover.
BB_TEST(ball_handoff_failed_catch_rest_turnover) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int carrier = fx_lineman(&m, 0, 0, 5, 7);
    fx_lineman(&m, 0, 1, 6, 7); // AG 3+ receiver
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, carrier);
    uint8_t script[] = {2, 5}; // catch 2 vs 3+ fails; Bounce (+1,0) -> (7,7)
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, carrier, BB_ACT_HANDOFF);
    fx_apply(&m, mk(BB_A_HANDOFF_TARGET, 0, 6, 7), &rng);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 7);
    BB_CHECK_EQ(m.ball.y, 7);
    BB_CHECK_EQ(m.decision_team, 1); // turnover
}

// SK "Pro (Active)": "The Skill cannot be used to re-roll ... a roll made
// outside of the player's activation." A hand-off catch is the RECEIVER's
// roll during the THROWER's activation: the receiver's Pro must NOT be
// offered, even when the Catch skill re-roll opens the window (adversarial
// review M1 refuter caveat — the offer condition was over-broad).
BB_TEST(ball_handoff_catch_pro_not_offered_outside_own_activation) {
    bb_match m;
    fx_match_midturn(&m, 0, 0); // no team re-rolls
    int carrier = fx_lineman(&m, 0, 0, 5, 7);
    int receiver = fx_lineman(&m, 0, 1, 6, 7); // AG 3+
    fx_give_skill(&m, receiver, BB_SK_PRO);
    fx_give_skill(&m, receiver, BB_SK_CATCH);
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, carrier);
    uint8_t script[] = {2, 3}; // catch 2 fails; Catch skill re-roll 3 passes
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, carrier, BB_ACT_HANDOFF);
    bb_status st = fx_apply(&m, mk(BB_A_HANDOFF_TARGET, 0, 6, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    // The Catch skill re-roll IS offered; Pro is NOT (not their activation).
    BB_CHECK(fx_find(&m, mk(BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_CATCH, 0)) >= 0);
    BB_CHECK_EQ(fx_find(&m, mk(BB_A_USE_REROLL, BB_RR_PRO, 0, 0)), -1);
    st = fx_apply(&m, mk(BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_CATCH, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.ball.carrier, receiver);
    BB_CHECK_EQ(m.decision_team, 0); // no turnover
}

// ENGINE-DIVERGENCE: declaring Pass/Hand-off without the ball. GAME/
// PERFORMING A PASS ACTION: "A player does not have to be in possession of
// the ball to declare a Pass Action, and may attempt to pick up the ball as
// part of their Move Action." (Same sentence for Hand-off Actions.) The
// engine only offers BB_ACT_PASS / BB_ACT_HANDOFF to the current ball
// carrier (proc_turn.c activation_legal).
BB_TEST(ball_declare_pass_handoff_without_possession) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int player = fx_player(&m, 0, 0, 5, 7, 6, 3, 3, 3, 9);
    fx_lineman(&m, 0, 1, 10, 7); // standing team-mate (hand-off receiver-to-be)
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_ground(&m, 7, 7);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    fx_apply(&m, mk(BB_A_ACTIVATE, player, 0, 0), &rng);
    BB_CHECK(fx_find(&m, mk(BB_A_DECLARE, BB_ACT_PASS, 0, 0)) >= 0);    // FAILS
    BB_CHECK(fx_find(&m, mk(BB_A_DECLARE, BB_ACT_HANDOFF, 0, 0)) >= 0); // FAILS
}

// ============================================================================
// PICKING UP THE BALL  (GAME "PICKING UP THE BALL")
// ============================================================================

// GAME/PICKING UP THE BALL: "Whenever a player voluntarily moves into a
// square containing the ball during their activation, they must immediately
// make an Agility Test ... If the test is passed, the player immediately
// gains possession of the ball and may continue their activation."
BB_TEST(ball_pickup_success_continues_activation) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int player = fx_lineman(&m, 0, 0, 5, 7); // AG 3+, MA 6
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_ground(&m, 6, 7);
    uint8_t script[] = {3}; // pickup 3 vs AG 3+ unmodified
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, player, BB_ACT_MOVE);
    fx_apply(&m, mk(BB_A_STEP, 0, 6, 7), &rng);
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(m.ball.carrier, player);
    BB_CHECK(fx_has_type(&m, BB_A_STEP)); // may continue moving
    BB_CHECK_EQ(m.decision_team, 0);
}

// GAME/PICKING UP THE BALL: "If the test is failed, the player fails to pick
// up the ball and a Turnover is caused - the ball will then Bounce from the
// player's square. Apply a -1 modifier to this roll for each opposition
// player that is Marking the player attempting to pick up the ball."
// + WEATHER/POURING RAIN: -1 to pick up.
BB_TEST(ball_pickup_modifiers_and_failure_turnover) {
    // (a) one marker: AG 3+ needs 4; roll 4 succeeds.
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        int player = fx_lineman(&m, 0, 0, 5, 7);
        fx_lineman(&m, 1, 0, 7, 7); // marks the ball square (6,7)
        fx_lineman(&m, 1, 1, 20, 2);
        fx_ball_ground(&m, 6, 7);
        uint8_t script[] = {4};
        bb_rng rng;
        bb_rng_script(&rng, script, 1);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, player, BB_ACT_MOVE);
        fx_apply(&m, mk(BB_A_STEP, 0, 6, 7), &rng);
        BB_CHECK_EQ(m.ball.carrier, player);
    }
    // (b) one marker: roll 3 fails (pins -1) -> Bounce (-1,0) to the vacated
    // (5,7) -> rest -> Turnover, activation over.
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        int player = fx_lineman(&m, 0, 0, 5, 7);
        fx_lineman(&m, 1, 0, 7, 7);
        fx_lineman(&m, 1, 1, 20, 2);
        fx_ball_ground(&m, 6, 7);
        uint8_t script[] = {3, 4}; // pickup fails; Bounce face 4 = (-1,0)
        bb_rng rng;
        bb_rng_script(&rng, script, 2);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, player, BB_ACT_MOVE);
        fx_apply(&m, mk(BB_A_STEP, 0, 6, 7), &rng);
        BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
        BB_CHECK_EQ(m.ball.x, 5);
        BB_CHECK_EQ(m.ball.y, 7);
        BB_CHECK(!(m.players[player].flags & BB_PF_HAS_BALL));
        BB_CHECK_EQ(m.decision_team, 1); // turnover
    }
    // (c) Pouring Rain, unmarked: AG 3+ needs 4; roll 3 fails (pins rain -1).
    {
        bb_match m;
        fx_match_midturn(&m, 0, 0);
        m.weather = BB_WEATHER_RAIN;
        int player = fx_lineman(&m, 0, 0, 5, 7);
        fx_lineman(&m, 1, 0, 20, 2);
        fx_ball_ground(&m, 6, 7);
        uint8_t script[] = {3, 5}; // fails; Bounce (+1,0) -> (7,7)
        bb_rng rng;
        bb_rng_script(&rng, script, 2);
        fx_run(&m, &rng);
        fx_activate(&m, &rng, player, BB_ACT_MOVE);
        fx_apply(&m, mk(BB_A_STEP, 0, 6, 7), &rng);
        BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
        BB_CHECK_EQ(m.ball.x, 7);
        BB_CHECK_EQ(m.ball.y, 7);
        BB_CHECK_EQ(m.decision_team, 1);
    }
}

// ENGINE-DIVERGENCE: involuntary entry into the ball square. GAME/PICKING UP
// THE BALL: "If a player is ever involuntarily moved into a square
// containing the ball, such as being pushed ... they may not attempt to pick
// up the ball and it will Bounce; however, no Turnover will be caused." The
// engine's push relocation (proc_block.c push_advance phase 2) leaves a loose
// ball sitting in the square under the pushed player — no bounce.
BB_TEST(ball_pushed_onto_loose_ball_bounces_no_turnover) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int att = fx_player(&m, 0, 0, 5, 7, 6, 4, 3, 3, 9); // ST 4
    int def = fx_lineman(&m, 1, 0, 6, 7);               // ST 3
    fx_lineman(&m, 1, 1, 20, 2);
    fx_ball_ground(&m, 7, 7);
    // 2 block dice (attacker stronger, attacker picks): faces 3,3 = Push Back.
    // Push the defender into the ball square (7,7); decline follow-up.
    // Rulebook: ball Bounces (+1,0) -> (8,7); no pickup attempt; no turnover.
    uint8_t script[] = {3, 3, 5};
    bb_rng rng;
    bb_rng_script(&rng, script, 3);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, att, BB_ACT_BLOCK);
    fx_apply(&m, mk(BB_A_BLOCK_TARGET, 0, 6, 7), &rng);
    fx_apply(&m, mk(BB_A_CHOOSE_DIE, 0, 0, 0), &rng);
    fx_apply(&m, mk(BB_A_PUSH_SQUARE, 0, 7, 7), &rng);
    fx_apply(&m, mk(BB_A_FOLLOW_UP, 0, 0, 0), &rng);
    BB_CHECK_EQ(m.players[def].x, 7);
    BB_CHECK_EQ(m.players[def].y, 7);
    BB_CHECK(!(m.players[def].flags & BB_PF_HAS_BALL));
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 8); // FAILS (engine leaves the ball at (7,7))
    BB_CHECK_EQ(m.ball.y, 7);
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK_EQ(m.decision_team, 0);
}

// ============================================================================
// BALL CARRIER GOES DOWN  (RR "FALLS OVER" / "KNOCKED DOWN")
// ============================================================================

// RR/FALLS OVER: "If a player on the active team Falls Over then a Turnover
// is caused ... make an Armour Roll ... If the player was holding the ball,
// it will Bounce from the square they are in." (Failed Dodge: GAME/DODGING —
// the player is moved into the destination square and Falls Over there.)
BB_TEST(ball_carrier_falls_over_ball_bounces_turnover) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int carrier = fx_player(&m, 0, 0, 5, 7, 6, 3, 4, 3, 9); // AG 4+, AV 9+
    fx_lineman(&m, 0, 1, 15, 2);
    fx_lineman(&m, 1, 0, 5, 6); // marks the carrier -> dodging required
    fx_ball_held(&m, carrier);
    // Dodge to (6,8) (no markers there): AG 4+, roll 3 -> Falls Over at
    // (6,8); Armour 2+2=4 < 9 holds; ball Bounces (+1,0) -> (7,8).
    uint8_t script[] = {3, 2, 2, 5};
    bb_rng rng;
    bb_rng_script(&rng, script, 4);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, carrier, BB_ACT_MOVE);
    fx_apply(&m, mk(BB_A_STEP, 0, 6, 8), &rng);
    BB_CHECK_EQ(m.players[carrier].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[carrier].x, 6);
    BB_CHECK_EQ(m.players[carrier].y, 8);
    BB_CHECK(!(m.players[carrier].flags & BB_PF_HAS_BALL));
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 7);
    BB_CHECK_EQ(m.ball.y, 8);
    BB_CHECK_EQ(m.decision_team, 1); // turnover
}

// RR/KNOCKED DOWN: "If a player is Knocked Down during their team's turn,
// then a Turnover is caused" — knocking down the INACTIVE team's carrier is
// NOT a turnover for the active team. GAME/POW: "Apply the Push Back result
// ... The target player is then Knocked Down in the square they are now in"
// — so the ball bounces from the pushed-to square.
BB_TEST(ball_carrier_powed_in_opponents_turn_no_turnover) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int att = fx_player(&m, 0, 0, 5, 7, 6, 4, 3, 3, 9); // ST 4, team 0 active
    int def = fx_lineman(&m, 1, 0, 6, 7);               // ST 3 carrier, AV 9+
    fx_lineman(&m, 0, 1, 15, 2);
    fx_ball_held(&m, def);
    // 2 dice {6,6} = POW; push to (7,8); no follow-up; armour 2+2 holds;
    // ball Bounces from (7,8) face 5 -> (8,8).
    uint8_t script[] = {6, 6, 2, 2, 5};
    bb_rng rng;
    bb_rng_script(&rng, script, 5);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, att, BB_ACT_BLOCK);
    fx_apply(&m, mk(BB_A_BLOCK_TARGET, 0, 6, 7), &rng);
    fx_apply(&m, mk(BB_A_CHOOSE_DIE, 0, 0, 0), &rng);
    fx_apply(&m, mk(BB_A_PUSH_SQUARE, 0, 7, 8), &rng);
    fx_apply(&m, mk(BB_A_FOLLOW_UP, 0, 0, 0), &rng);
    BB_CHECK_EQ(m.players[def].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[def].x, 7);
    BB_CHECK_EQ(m.players[def].y, 8);
    BB_CHECK(!(m.players[def].flags & BB_PF_HAS_BALL));
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 8);
    BB_CHECK_EQ(m.ball.y, 8);
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK_EQ(m.decision_team, 0); // active team plays on
}

// ============================================================================
// THROW-INS  (GAME "THROW-INS" / "CORNER THROW-INS"; ESS "THROW-IN TEMPLATE")
// ============================================================================

// ENGINE-DIVERGENCE (three rules at once):
//  1. ESS/THROW-IN TEMPLATE: "roll a D6 to see which way the object will
//     move" — the direction die is a D6 read against the template's three
//     arrows (1-2 / 3-4 / 5-6); the engine rolls a D3.
//  2. GAME/THROW-INS: "The ball will then travel 2D6 squares ... counting
//     the square underneath the Blood Bowl logo of the Throw-in Template
//     [the last square the ball occupied] as the first square" — i.e. the
//     ball ends (2D6 - 1) steps beyond the boundary square; the engine moves
//     it a full 2D6 steps (off by one).
//  3. GAME/THROW-INS: after landing the ball does NOT bounce — "if after the
//     Throw-in is resolved the ball comes to a rest on the ground ... a
//     Turnover is caused" (and an occupied landing square means a direct
//     catch). The engine bounces the ball once on landing.
// Template-orientation assumption: direction face 3 (template arrow 3-4) is
// the centre arrow, perpendicular to the edge.
BB_TEST(ball_throw_in_distance_counts_boundary_square) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_player(&m, 0, 0, 10, 11, 6, 3, 3, 2, 9); // PA 2+
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, thrower);
    // Accurate quick pass to the empty edge square (10,14); Bounce face 7 =
    // (0,+1) -> off pitch; Throw-in from (10,14): direction d6=3 (straight
    // in, (0,-1)), distance 2D6 = 3+2 = 5 counting (10,14) as the first
    // square -> lands (10,10), comes to rest -> turnover (pass action ended
    // with the ball on the ground).
    uint8_t script[] = {6, 7, 3, 3, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 5);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 10, 14), &rng);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND); // FAILS (engine: extra bounce + off-by-one)
    BB_CHECK_EQ(m.ball.x, 10);
    BB_CHECK_EQ(m.ball.y, 10);
    BB_CHECK_EQ(m.decision_team, 1);
}

// ENGINE-DIVERGENCE: GAME/THROW-INS: "If the ball lands in an occupied
// square then the player must attempt to Catch the ball" + GAME/CATCHING:
// "If the player is attempting to Catch a ball that has been Thrown-in,
// apply a -1 modifier." Direct catch on landing — no bounce first. The
// engine instead bounces from the landing square (and would mislabel the
// modifier as a bounce).
BB_TEST(ball_throw_in_lands_on_player_direct_catch) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_player(&m, 0, 0, 10, 11, 6, 3, 3, 2, 9);
    int mate = fx_player(&m, 0, 1, 10, 10, 6, 3, 2, 3, 9); // AG 2+ at landing
    fx_lineman(&m, 1, 0, 20, 2);
    fx_ball_held(&m, thrower);
    // Same throw-in as above, landing on the team-mate at (10,10): catch of
    // a Thrown-in ball is -1 -> AG 2+ needs 3; roll 3 -> caught. The active
    // team holds the ball -> NO turnover.
    uint8_t script[] = {6, 7, 3, 3, 2, 3};
    bb_rng rng;
    bb_rng_script(&rng, script, 6);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 10, 14), &rng);
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD); // FAILS
    BB_CHECK_EQ(m.ball.carrier, mate);
    BB_CHECK_EQ(m.decision_team, 0);
}

// ENGINE-DIVERGENCE: GAME/CORNER THROW-INS: "Should the ball leave the pitch
// from a corner square, position the Random Direction Template as shown ...
// and roll a D3" — the three directions all point INTO the pitch (for the
// (25,14) corner: (-1,0), (-1,-1), (0,-1); d3=2 assumed to be the diagonal).
// The engine reuses its edge direction set, which at a corner includes
// directions pointing straight off the pitch, and keeps its off-by-one
// distance and landing bounce.
BB_TEST(ball_corner_throw_in_inward_directions) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_player(&m, 0, 0, 22, 12, 6, 3, 3, 2, 9); // PA 2+
    fx_lineman(&m, 1, 0, 5, 2);
    fx_ball_held(&m, thrower);
    // Pass to the empty corner (25,14) (dx=3,dy=2: Short; nat 6 accurate);
    // Bounce face 8 = (+1,+1) -> off pitch from the corner. Corner throw-in:
    // d3=2 -> diagonal (-1,-1); distance 3+2=5 counting the corner as the
    // first square -> 4 steps -> (21,10), at rest -> turnover.
    uint8_t script[] = {6, 8, 2, 3, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 5);
    fx_run(&m, &rng);
    fx_activate(&m, &rng, thrower, BB_ACT_PASS);
    fx_apply(&m, mk(BB_A_PASS_TARGET, 0, 25, 14), &rng);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND); // FAILS
    BB_CHECK_EQ(m.ball.x, 21);
    BB_CHECK_EQ(m.ball.y, 10);
    BB_CHECK_EQ(m.decision_team, 1);
}

// ============================================================================
// SECURE THE BALL  (GAME "SECURE THE BALL ACTIONS!")
// ============================================================================

// ENGINE-DIVERGENCE: the Secure the Ball Action is not declarable
// (TODO(phase3) in proc_turn.c). GAME/SECURE THE BALL ACTION: "A player may
// only declare a Secure the Ball Action if the ball is loose on the ground
// and is not within 2 squares of any Standing opposition players that are
// not Distracted" — here the ball is loose and the nearest opponent is 3
// squares away, so the declaration must be offered.
BB_TEST(ball_secure_the_ball_declarable) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int player = fx_lineman(&m, 0, 0, 9, 7);
    fx_lineman(&m, 1, 0, 13, 7); // 3 squares from the ball: far enough
    fx_ball_ground(&m, 10, 7);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    fx_apply(&m, mk(BB_A_ACTIVATE, player, 0, 0), &rng);
    BB_CHECK(fx_find(&m, mk(BB_A_DECLARE, BB_ACT_SECURE_BALL, 0, 0)) >= 0); // FAILS
}
