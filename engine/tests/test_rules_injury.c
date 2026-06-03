// test_rules_injury.c — RULEBOOK tests: ARMOUR / INJURY / CASUALTY / FOUL.
//
// Every test encodes what the BB2025 mirror says, with the source sentence
// paraphrased + cited above the test. Mirror root:
//   docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/
// Abbreviations used in citations:
//   [GAME] core_rules/the_game_of_blood_bowl/index.html
//   [RR]   core_rules/rules_and_regulations/index.html
//   [S&T]  core_rules/skills_and_traits/index.html
//   [FAQ]  core_rules/latest_faq/index.html (May 2026)
//
// All dice are scripted (bb_rng_script); rng.script_pos is asserted where the
// EXACT number of dice rolled is itself the rule being tested.
#include "bb/bb_match.h"
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb_fixtures.h"
#include "bb_test.h"

// Slot layout used by the fixtures below.
enum {
    ATT = 0,                       // team 0, idx 0 (attacker / fouler)
    SPARE0 = 1,                    // team 0, idx 1 (keeps team-0 turn alive)
    DEF = BB_TEAM_SLOTS + 0,       // team 1, idx 0 (victim)
    SPARE1 = BB_TEAM_SLOTS + 1,    // team 1, idx 1 (keeps team-1 turn alive)
};

static bb_status ap(bb_match* m, bb_rng* rng, int type, int arg, int x, int y) {
    bb_action a = {(uint8_t)type, (uint8_t)arg, (uint8_t)x, (uint8_t)y};
    return fx_apply(m, a, rng);
}

// Attacker (AV9+ lineman) at (10,5) team 0; victim lineman at (11,5) team 1;
// far-away spares on both teams so every team turn has a decision point.
static void build_block_fixture(bb_match* m) {
    fx_match_midturn(m, BB_HOME, 0);
    fx_lineman(m, 0, 0, 10, 5);
    fx_lineman(m, 1, 0, 11, 5);
    fx_lineman(m, 0, 1, 2, 2);
    fx_lineman(m, 1, 1, 23, 12);
}

// Drive a 1-die block (equal ST, no assists) from ATT into DEF, choose the
// single rolled die (script it POW=6 / PUSH=3), push straight back to (12,5),
// decline follow-up. Returns the status at the next decision point — by then
// the scripted armour/injury/casualty/bounce dice have been consumed.
static bb_status run_pow_block(bb_match* m, bb_rng* rng) {
    bb_status st = fx_run(m, rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    ap(m, rng, BB_A_ACTIVATE, ATT, 0, 0);
    ap(m, rng, BB_A_DECLARE, BB_ACT_BLOCK, 0, 0);
    ap(m, rng, BB_A_BLOCK_TARGET, 0, 11, 5);
    ap(m, rng, BB_A_CHOOSE_DIE, 0, 0, 0);
    ap(m, rng, BB_A_PUSH_SQUARE, 0, 12, 5);
    return ap(m, rng, BB_A_FOLLOW_UP, 0, 0, 0);
}

// ===== ARMOUR ROLLS ==========================================================

// [RR] "9. AV - ARMOUR VALUE": "the opposing Coach will roll 2D6 and compare
// the value to the player's Armour Value. If the Armour Roll is failed, then
// nothing further happens: the player's armour has saved them this time."
// AV is a target number (lineman 9+): 2D6 = 8 does not break, and NO injury
// dice are rolled (script_pos pins the dice count).
BB_TEST(rules_armour_2d6_below_av_holds) {
    bb_match m;
    build_block_fixture(&m);
    static const uint8_t dice[] = {6 /*POW*/, 4, 4 /*armour 8 < 9*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);
    bb_status st = run_pow_block(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);          // no script over-read
    BB_CHECK_EQ(rng.script_pos, 3);               // exactly 0 injury dice
    BB_CHECK_EQ(m.players[DEF].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[DEF].location, BB_LOC_ON_PITCH);
    BB_CHECK_EQ(m.turnover, 0);                   // inactive player KD: no TO
    BB_CHECK_EQ(m.decision_team, 0);
}

// [RR] "If the Armour Roll is successful, then the player's armour is
// 'broken' and they will risk injury." A target number "9+" succeeds on 9:
// 2D6 = 9 exactly breaks AV 9+ and an Injury Roll follows.
BB_TEST(rules_armour_2d6_at_av_breaks) {
    bb_match m;
    build_block_fixture(&m);
    static const uint8_t dice[] = {6, 4, 5 /*armour 9 >= 9*/, 1, 2 /*injury 3*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 5);
    bb_status st = run_pow_block(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 5);               // injury dice were rolled
    BB_CHECK_EQ(m.players[DEF].stance, BB_STANCE_STUNNED);
}

// ===== INJURY TABLE BANDS ====================================================

// [GAME] INJURY TABLE: "2-7 STUNNED: The player is immediately Stunned."
BB_TEST(rules_injury_2_to_7_stunned) {
    static const uint8_t rolls[2][2] = {{1, 1}, {3, 4}}; // 2 and 7
    for (int c = 0; c < 2; c++) {
        bb_match m;
        build_block_fixture(&m);
        uint8_t dice[] = {6, 5, 5, rolls[c][0], rolls[c][1]};
        bb_rng rng;
        bb_rng_script(&rng, dice, 5);
        bb_status st = run_pow_block(&m, &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK_EQ(rng.script_pos, 5);
        BB_CHECK_EQ(m.players[DEF].stance, BB_STANCE_STUNNED);
        BB_CHECK_EQ(m.players[DEF].location, BB_LOC_ON_PITCH);
    }
}

// [GAME] INJURY TABLE: "8-9 KNOCKED-OUT: ... Remove them from the pitch and
// place them in the Knocked-out box of their dugout."
BB_TEST(rules_injury_8_to_9_knocked_out) {
    static const uint8_t rolls[2][2] = {{4, 4}, {4, 5}}; // 8 and 9
    for (int c = 0; c < 2; c++) {
        bb_match m;
        build_block_fixture(&m);
        uint8_t dice[] = {6, 5, 5, rolls[c][0], rolls[c][1]};
        bb_rng rng;
        bb_rng_script(&rng, dice, 5);
        bb_status st = run_pow_block(&m, &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK_EQ(rng.script_pos, 5);           // no extra dice (no D16)
        BB_CHECK_EQ(m.players[DEF].location, BB_LOC_KO);
    }
}

// [GAME] INJURY TABLE: "10-12 CASUALTY: The player suffers a Casualty.
// Remove them from the pitch and place them in the Casualty box of their
// dugout. The Coach of the opposing team then makes a Casualty Roll."
BB_TEST(rules_injury_10_to_12_casualty) {
    static const uint8_t rolls[2][2] = {{5, 5}, {6, 6}}; // 10 and 12
    for (int c = 0; c < 2; c++) {
        bb_match m;
        build_block_fixture(&m);
        uint8_t dice[] = {6, 5, 5, rolls[c][0], rolls[c][1], 8 /*D16*/};
        bb_rng rng;
        bb_rng_script(&rng, dice, 6);
        bb_status st = run_pow_block(&m, &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK_EQ(rng.script_pos, 6);           // the D16 WAS rolled
        BB_CHECK_EQ(m.players[DEF].location, BB_LOC_CAS);
    }
}

// ===== CASUALTY TABLE ========================================================

// [GAME] CASUALTY ROLLS: "rolling a D16 ... In all instances the player will
// miss the rest of the current game". D16=1 (Badly Hurt, band 1-8), D16=9
// (Seriously Hurt, 9-10) and D16=16 (DEAD, 15-16) all leave the player in the
// Casualty box for match purposes.
BB_TEST(rules_casualty_d16_always_out_for_match) {
    static const uint8_t d16s[3] = {1, 9, 16};
    for (int c = 0; c < 3; c++) {
        bb_match m;
        build_block_fixture(&m);
        uint8_t dice[] = {6, 5, 5, 5, 5 /*injury 10*/, d16s[c]};
        bb_rng rng;
        bb_rng_script(&rng, dice, 6);
        bb_status st = run_pow_block(&m, &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK_EQ(rng.script_pos, 6);
        BB_CHECK_EQ(m.players[DEF].location, BB_LOC_CAS);
        BB_CHECK_EQ(m.players[DEF].flags & BB_PF_HAS_BALL, 0);
    }
}

// ===== STUNTY INJURY TABLE ===================================================

// [GAME] STUNTY INJURY TABLE: "2-6 STUNNED ... 7-8 KNOCKED-OUT". A roll of 6
// stuns; 7 — which on the standard table is still Stunned — KOs a Stunty
// player, as does 8.
BB_TEST(rules_stunty_bands_stun_6_ko_7_8) {
    static const struct { uint8_t d1, d2; int loc; int stance; } cases[] = {
        {2, 4, BB_LOC_ON_PITCH, BB_STANCE_STUNNED}, // 6: stunned
        {3, 4, BB_LOC_KO, -1},                      // 7: KO (stunty only)
        {4, 4, BB_LOC_KO, -1},                      // 8: KO
    };
    for (int c = 0; c < 3; c++) {
        bb_match m;
        build_block_fixture(&m);
        fx_give_skill(&m, DEF, BB_SK_STUNTY);
        uint8_t dice[] = {6, 5, 5, cases[c].d1, cases[c].d2};
        bb_rng rng;
        bb_rng_script(&rng, dice, 5);
        bb_status st = run_pow_block(&m, &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK_EQ(rng.script_pos, 5);
        BB_CHECK_EQ(m.players[DEF].location, cases[c].loc);
        if (cases[c].stance >= 0) {
            BB_CHECK_EQ(m.players[DEF].stance, cases[c].stance);
        }
    }
}

// [GAME] STUNTY INJURY TABLE: "9 BADLY HURT: The player suffers a Casualty...
// no Casualty Roll is made for them, instead they automatically suffer the
// Badly Hurt result." Injury 9 sends a Stunty player to the Casualty box and
// NO D16 is rolled (script_pos pins it).
BB_TEST(rules_stunty_9_badly_hurt_no_casualty_roll) {
    bb_match m;
    build_block_fixture(&m);
    fx_give_skill(&m, DEF, BB_SK_STUNTY);
    static const uint8_t dice[] = {6, 5, 5, 4, 5 /*injury 9*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 5);
    bb_status st = run_pow_block(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);          // would be ERROR if a D16
    BB_CHECK_EQ(rng.script_pos, 5);               // were drawn from the script
    BB_CHECK_EQ(m.players[DEF].location, BB_LOC_CAS);
}

// [GAME] STUNTY INJURY TABLE: "10-12 CASUALTY: ... The Coach of the opposing
// team then makes a Casualty Roll against them." Injury 10 on a Stunty DOES
// roll the D16.
BB_TEST(rules_stunty_10_casualty_rolls_d16) {
    bb_match m;
    build_block_fixture(&m);
    fx_give_skill(&m, DEF, BB_SK_STUNTY);
    static const uint8_t dice[] = {6, 5, 5, 5, 5 /*injury 10*/, 12 /*D16*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 6);
    bb_status st = run_pow_block(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 6);
    BB_CHECK_EQ(m.players[DEF].location, BB_LOC_CAS);
}

// ===== THICK SKULL (BB2025 — deterministic, NO 4+ saving roll) ===============

// ENGINE-DIVERGENCE: BB2025 Thick Skull is deterministic. [S&T] "THICK SKULL
// (PASSIVE): When an Injury Roll is made for this player, they will only be
// Knocked-out on the roll of a 9; a roll of an 8 will be treated as a Stunned
// result." No extra D6 is rolled. The engine implements the BB2020 version
// (extra D6, 4+ keeps the player stunned): on injury 8 it rolls an extra die
// and can still KO the player, which the BB2025 rule forbids.
BB_TEST(rules_thick_skull_injury_8_is_stunned) {
    bb_match m;
    build_block_fixture(&m);
    fx_give_skill(&m, DEF, BB_SK_THICK_SKULL);
    // Trailing 1 feeds the engine's (incorrect) extra die so the divergence is
    // observable as a wrong OUTCOME rather than a script error. A rulebook-
    // correct engine leaves it unconsumed.
    static const uint8_t dice[] = {6, 5, 5, 4, 4 /*injury 8*/, 1};
    bb_rng rng;
    bb_rng_script(&rng, dice, 6);
    run_pow_block(&m, &rng);
    BB_CHECK_EQ(m.players[DEF].stance, BB_STANCE_STUNNED);   // rulebook: Stunned
    BB_CHECK_EQ(m.players[DEF].location, BB_LOC_ON_PITCH);   // not KO'd
    BB_CHECK_EQ(rng.script_pos, 5);                          // no extra die
}

// ENGINE-DIVERGENCE: [S&T] Thick Skull — "they will only be Knocked-out on
// the roll of a 9": a 9 is ALWAYS a KO for a (non-Stunty) Thick Skull player;
// there is no save. The engine rolls a BB2020-style extra D6 and on 4+ keeps
// the player on the pitch stunned, which BB2025 does not allow.
BB_TEST(rules_thick_skull_injury_9_is_always_ko) {
    bb_match m;
    build_block_fixture(&m);
    fx_give_skill(&m, DEF, BB_SK_THICK_SKULL);
    static const uint8_t dice[] = {6, 5, 5, 4, 5 /*injury 9*/, 6};
    bb_rng rng;
    bb_rng_script(&rng, dice, 6);
    run_pow_block(&m, &rng);
    BB_CHECK_EQ(m.players[DEF].location, BB_LOC_KO);         // rulebook: KO
    BB_CHECK_EQ(rng.script_pos, 5);                          // no extra die
}

// ENGINE-DIVERGENCE: [S&T] Thick Skull — "If this player also has the Stunty
// Trait, then they will only be Knocked-out on the roll of an 8; a roll of a
// 7 will be treated as a Stunned result." Deterministic; no extra D6.
BB_TEST(rules_stunty_thick_skull_injury_7_is_stunned) {
    bb_match m;
    build_block_fixture(&m);
    fx_give_skill(&m, DEF, BB_SK_STUNTY);
    fx_give_skill(&m, DEF, BB_SK_THICK_SKULL);
    static const uint8_t dice[] = {6, 5, 5, 3, 4 /*injury 7*/, 1};
    bb_rng rng;
    bb_rng_script(&rng, dice, 6);
    run_pow_block(&m, &rng);
    BB_CHECK_EQ(m.players[DEF].stance, BB_STANCE_STUNNED);   // rulebook: Stunned
    BB_CHECK_EQ(m.players[DEF].location, BB_LOC_ON_PITCH);
    BB_CHECK_EQ(rng.script_pos, 5);
}

// ===== INJURY BY THE CROWD ===================================================

// Attacker at (10,1), victim on the sideline row at (10,0): every push square
// is off-pitch, so a Push Back result shoves the victim into the crowd.
static void build_crowd_fixture(bb_match* m) {
    fx_match_midturn(m, BB_HOME, 0);
    fx_lineman(m, 0, 0, 10, 1);
    fx_lineman(m, 1, 0, 10, 0);
    fx_lineman(m, 0, 1, 2, 7);
    fx_lineman(m, 1, 1, 23, 12);
}

static bb_status run_crowd_push(bb_match* m, bb_rng* rng) {
    bb_status st = fx_run(m, rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    ap(m, rng, BB_A_ACTIVATE, ATT, 0, 0);
    ap(m, rng, BB_A_DECLARE, BB_ACT_BLOCK, 0, 0);
    ap(m, rng, BB_A_BLOCK_TARGET, 0, 10, 0);
    ap(m, rng, BB_A_CHOOSE_DIE, 0, 0, 0);
    // All candidate squares are off-pitch: only crowd pushes (arg==1) legal.
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(m, legal);
    int idx = -1;
    for (int i = 0; i < n; i++) {
        if (legal[i].type == BB_A_PUSH_SQUARE) {
            BB_CHECK_EQ(legal[i].arg, 1);
            if (idx < 0) idx = i;
        }
    }
    BB_CHECK(idx >= 0);
    fx_apply(m, legal[idx], rng);  // crowd injury dice consumed here
    return ap(m, rng, BB_A_FOLLOW_UP, 0, 0, 0);
}

// [GAME] INJURY BY THE CROWD: "immediately make an Injury Roll for them ...
// If the player would be Stunned, place them in their team's Reserve Box
// instead." No Armour Roll is made (script: block die + exactly 2 injury
// dice), and the "Stunned" band sends the player to Reserves.
BB_TEST(rules_crowd_injury_stunned_goes_to_reserves) {
    bb_match m;
    build_crowd_fixture(&m);
    static const uint8_t dice[] = {3 /*PUSH*/, 2, 2 /*injury 4: stunned*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);
    bb_status st = run_crowd_push(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 3);               // no armour dice rolled
    BB_CHECK_EQ(m.players[DEF].location, BB_LOC_RESERVES);
}

// [GAME] INJURY BY THE CROWD: "Otherwise, follow the result as shown on the
// relevant Injury Table." Injury 8 against the crowd = Knocked-out box.
BB_TEST(rules_crowd_injury_ko_goes_to_ko_box) {
    bb_match m;
    build_crowd_fixture(&m);
    static const uint8_t dice[] = {3, 4, 4 /*injury 8: KO*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);
    bb_status st = run_crowd_push(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 3);
    BB_CHECK_EQ(m.players[DEF].location, BB_LOC_KO);
}

// [GAME] INJURY BY THE CROWD + CASUALTY ROLLS: injury 10 by the crowd is a
// Casualty: D16 rolled, player to the Casualty box.
BB_TEST(rules_crowd_injury_casualty) {
    bb_match m;
    build_crowd_fixture(&m);
    static const uint8_t dice[] = {3, 5, 5 /*injury 10*/, 16 /*D16: dead*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 4);
    bb_status st = run_crowd_push(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 4);
    BB_CHECK_EQ(m.players[DEF].location, BB_LOC_CAS);
}

// ===== KNOCKED-DOWN BALL CARRIER: armour/injury BEFORE the bounce ============

// [RR] KNOCKED DOWN: "place a Prone Marker next to them and then make an
// Armour Roll for the player. ... If the player was holding the ball, it will
// Bounce from the square they are in." The armour/injury sequence resolves
// before the bounce; the dice script encodes that order (armour 2D6, injury
// 2D6, then the D8 bounce). A wrong order would mis-map die types: D8=5 is
// direction (+1,0) so the ball must end at (13,5).
BB_TEST(rules_carrier_knockdown_armour_injury_then_bounce) {
    bb_match m;
    build_block_fixture(&m);
    fx_ball_held(&m, DEF);
    static const uint8_t dice[] = {6, 4, 5 /*armour 9*/, 3, 3 /*injury 6*/,
                                   5 /*D8 bounce -> (+1,0)*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 6);
    bb_status st = run_pow_block(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 6);
    BB_CHECK_EQ(m.players[DEF].stance, BB_STANCE_STUNNED);
    BB_CHECK_EQ(m.players[DEF].x, 12);            // pushed square
    BB_CHECK_EQ(m.players[DEF].flags & BB_PF_HAS_BALL, 0);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 13);                    // bounced from (12,5)
    BB_CHECK_EQ(m.ball.y, 5);
    // [RR] THE TURNOVER: knocking down an INACTIVE player is no turnover.
    BB_CHECK_EQ(m.decision_team, 0);
}

// [RR] FALLS OVER: "If a player on the active team Falls Over then a Turnover
// is caused. ... make an Armour Roll ... If the player was holding the ball,
// it will Bounce from the square they are in." An active carrier failing a
// Dodge falls in the destination square, drops the ball (bounce), armour is
// rolled (here it holds), and the team turn ends immediately.
BB_TEST(rules_active_carrier_falls_over_bounce_and_turnover) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int p = fx_lineman(&m, 0, 0, 10, 5);
    fx_ball_held(&m, p);
    fx_lineman(&m, 1, 0, 10, 6);                  // marks (10,5): dodge needed
    fx_lineman(&m, 0, 1, 2, 2);                   // unused team-mate
    fx_lineman(&m, 1, 1, 23, 12);
    static const uint8_t dice[] = {2 /*dodge fails vs 3+*/,
                                   2, 3 /*armour 5: holds*/,
                                   7 /*D8 bounce -> (0,+1)*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 4);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    ap(&m, &rng, BB_A_ACTIVATE, p, 0, 0);
    ap(&m, &rng, BB_A_DECLARE, BB_ACT_MOVE, 0, 0);
    st = ap(&m, &rng, BB_A_STEP, 0, 9, 4);        // destination has no TZs
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 4);
    BB_CHECK_EQ(m.players[p].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[p].x, 9);
    BB_CHECK_EQ(m.players[p].y, 4);
    BB_CHECK_EQ(m.players[p].flags & BB_PF_HAS_BALL, 0);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 9);
    BB_CHECK_EQ(m.ball.y, 5);                     // bounced from (9,4)
    // Turnover: the turn passed to team 1 even though SPARE0 never activated.
    BB_CHECK_EQ(m.decision_team, 1);
}

// ===== STUNNED RECOVERY ======================================================

// [RR] STUNNED: "At the end of each team's turn, any players on their team
// that started that turn Stunned will automatically roll over and become
// Prone" + "A Stunned player cannot be activated during their team's turn."
// Victim stunned during team 0's turn: still Stunned and unactivatable all
// through team 1's turn, flips to Prone at the END of team 1's (their own)
// turn.
BB_TEST(rules_stunned_flips_prone_at_end_of_own_team_turn) {
    bb_match m;
    build_block_fixture(&m);
    static const uint8_t dice[] = {6, 5, 5, 3, 4 /*injury 7: stunned*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 5);
    bb_status st = run_pow_block(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[DEF].stance, BB_STANCE_STUNNED);
    ap(&m, &rng, BB_A_END_ACTIVATION, 0, 0, 0);
    st = ap(&m, &rng, BB_A_END_TURN, 0, 0, 0);    // team 0's turn ends
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, 1);
    // End of team 0's turn does NOT flip a team-1 player.
    BB_CHECK(fx_stunned(&m, DEF)); // still stunned (may carry the turn-start flip marker)
    // "cannot be activated during their team's turn":
    BB_CHECK_EQ(fx_find(&m, (bb_action){BB_A_ACTIVATE, DEF, 0, 0}), -1);
    BB_CHECK(fx_find(&m, (bb_action){BB_A_ACTIVATE, SPARE1, 0, 0}) >= 0);
    st = ap(&m, &rng, BB_A_END_TURN, 0, 0, 0);    // team 1's turn ends
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, 0);
    BB_CHECK_EQ(m.players[DEF].stance, BB_STANCE_PRONE);   // rolled over
    BB_CHECK_EQ(m.players[DEF].location, BB_LOC_ON_PITCH);
}

// ENGINE-DIVERGENCE: [RR] STUNNED — "any player that became Stunned during
// the course of their team's turn will not roll over as they did not start
// their team's turn as Stunned - they must wait until the end of their team's
// NEXT turn to roll over." A team-0 player stunned during team 0's own turn
// (failed Dodge -> armour broken -> injury 2-7) must STILL be Stunned when the
// turn passes to team 1. The engine's turn_end flips every Stunned player of
// the ending team regardless of when they were stunned (the
// BB_STANCE_STUNNED_USED intermediate state exists but is never applied), so
// it shows Prone here.
BB_TEST(rules_stunned_during_own_turn_does_not_flip_same_turn) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int p = fx_lineman(&m, 0, 0, 10, 5);
    fx_lineman(&m, 1, 0, 10, 6);                  // marks (10,5)
    fx_lineman(&m, 0, 1, 2, 2);
    fx_lineman(&m, 1, 1, 23, 12);
    static const uint8_t dice[] = {2 /*dodge fails*/, 6, 5 /*armour 11*/,
                                   2, 3 /*injury 5: stunned*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 5);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    ap(&m, &rng, BB_A_ACTIVATE, p, 0, 0);
    ap(&m, &rng, BB_A_DECLARE, BB_ACT_MOVE, 0, 0);
    st = ap(&m, &rng, BB_A_STEP, 0, 9, 4);
    // Turnover ended team 0's turn; decision now with team 1.
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, 1);
    // Rulebook: p did not START team 0's turn Stunned, so p must still be
    // Stunned now (it flips only at the end of team 0's NEXT turn).
    BB_CHECK_EQ(m.players[p].stance, BB_STANCE_STUNNED);
}

// ===== KO RECOVERY AT THE END OF A DRIVE =====================================

// [GAME] RECOVER KNOCKED-OUT PLAYERS: "Roll a D6 for each Knocked-out player.
// On a 4+ the player recovers and is moved to the Reserves Box of their
// team's Dugout. On a 1-3, the player cannot be roused and is still
// Knocked-out." Rolled for BOTH teams during the End of Drive Sequence.
BB_TEST(rules_ko_recovery_4plus_at_end_of_drive) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    m.players[0].location = BB_LOC_KO;                    // team 0
    m.players[1].location = BB_LOC_KO;                    // team 0
    m.players[BB_TEAM_SLOTS + 0].location = BB_LOC_KO;    // team 1
    // Replace the fixture stack with a bare END_DRIVE frame.
    m.stack_top = 0;
    bb_push(&m, BB_PROC_END_DRIVE, 0, 0, 0, 0);
    static const uint8_t dice[] = {4 /*recovers*/, 3 /*stays KO*/, 6 /*recovers*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_MATCH_OVER);        // empty stack after pop
    BB_CHECK_EQ(rng.script_pos, 3);               // one D6 per KO'd player
    BB_CHECK_EQ(m.players[0].location, BB_LOC_RESERVES);
    BB_CHECK_EQ(m.players[1].location, BB_LOC_KO);
    BB_CHECK_EQ(m.players[BB_TEAM_SLOTS + 0].location, BB_LOC_RESERVES);
}

// ===== FOUL ACTIONS ==========================================================

// Fouler at (10,5) team 0; victim PRONE at (10,6) team 1; spares far away.
static void build_foul_fixture(bb_match* m) {
    fx_match_midturn(m, BB_HOME, 0);
    fx_lineman(m, 0, 0, 10, 5);
    int v = fx_lineman(m, 1, 0, 10, 6);
    m->players[v].stance = BB_STANCE_PRONE;
    fx_lineman(m, 0, 1, 2, 2);
    fx_lineman(m, 1, 1, 23, 12);
}

// Declare a Foul with ATT against the victim at (10,6); the scripted
// armour/injury dice are consumed by the final apply.
static bb_status run_foul(bb_match* m, bb_rng* rng) {
    bb_status st = fx_run(m, rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    ap(m, rng, BB_A_ACTIVATE, ATT, 0, 0);
    ap(m, rng, BB_A_DECLARE, BB_ACT_FOUL, 0, 0);
    return ap(m, rng, BB_A_FOUL_TARGET, 0, 10, 6);
}

// [GAME] PERFORMING A FOUL ACTION: "the player makes an Armour Roll for the
// target of the Foul Action" — a failed Armour Roll (no assists, 8 vs AV 9+)
// means no injury, and with no natural double the fouler is not Sent-off and
// no Turnover is caused: team 0 keeps playing.
BB_TEST(rules_foul_armour_holds_no_injury_no_sendoff) {
    bb_match m;
    build_foul_fixture(&m);
    static const uint8_t dice[] = {3, 5 /*armour 8 < 9, no double*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);
    bb_status st = run_foul(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 2);               // no injury dice
    BB_CHECK_EQ(m.players[DEF].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[DEF].location, BB_LOC_ON_PITCH);
    BB_CHECK_EQ(m.players[ATT].location, BB_LOC_ON_PITCH);
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK_EQ(m.decision_team, 0);              // turn continues
}

// [GAME] RISKING INJURY: "if the player's armour is broken then an Injury
// Roll must be made for them." Foul armour 10 breaks AV 9+; injury 3 stuns
// the (prone) victim. No doubles: fouler stays on, no Turnover.
BB_TEST(rules_foul_breaks_armour_injury_resolves) {
    bb_match m;
    build_foul_fixture(&m);
    static const uint8_t dice[] = {6, 4 /*armour 10*/, 2, 1 /*injury 3*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 4);
    bb_status st = run_foul(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 4);
    BB_CHECK_EQ(m.players[DEF].stance, BB_STANCE_STUNNED);
    BB_CHECK_EQ(m.players[ATT].location, BB_LOC_ON_PITCH);
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK_EQ(m.decision_team, 0);
}

// [GAME] PERFORMING A FOUL ACTION: "may apply a +1 modifier for each
// Offensive Assist". A team-mate Marking the victim and not Marked by any
// other opponent gives +1: armour 8+1 = 9 breaks AV 9+.
BB_TEST(rules_foul_offensive_assist_plus1) {
    bb_match m;
    build_foul_fixture(&m);
    fx_lineman(&m, 0, 2, 9, 6);   // marks the prone victim; unmarked itself
    static const uint8_t dice[] = {3, 5 /*armour 8 (+1 = 9)*/, 1, 2 /*injury 3*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 4);
    bb_status st = run_foul(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 4);               // injury rolled => broke
    BB_CHECK_EQ(m.players[DEF].stance, BB_STANCE_STUNNED);
}

// [GAME] PERFORMING A FOUL ACTION: "apply a -1 modifier for each Defensive
// Assist" (+ [FAQ pg.136]: "Defensive Assists modifiers are not a 'may' and
// so are always applied"). An opponent Marking the fouler and not Marked by
// any other team-0 player gives -1: armour 9-1 = 8 fails vs AV 9+.
BB_TEST(rules_foul_defensive_assist_minus1) {
    bb_match m;
    build_foul_fixture(&m);
    fx_lineman(&m, 1, 2, 11, 4);  // standing, marks the fouler, unmarked itself
    static const uint8_t dice[] = {4, 5 /*armour 9 (-1 = 8)*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);
    bb_status st = run_foul(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 2);               // armour held: no injury
    BB_CHECK_EQ(m.players[DEF].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.turnover, 0);
}

// [GAME] BEING SENT-OFF: "Regardless of the outcome, if during a Foul Action
// a natural double is rolled for either the Armour Roll or Injury Roll, then
// the player performing the Foul Action is Sent-off ... When a player on the
// active team is Sent-off, a Turnover is caused." Double 2s do NOT break AV
// 9+ but the fouler is Sent-off anyway and the turn ends.
BB_TEST(rules_foul_natural_double_on_unbroken_armour_sends_off) {
    bb_match m;
    build_foul_fixture(&m);
    static const uint8_t dice[] = {2, 2 /*armour 4: holds, natural double*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);
    bb_status st = run_foul(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 2);
    // BB2025: the send-off opens the Argue the Call window for the fouling
    // coach; accept the call (no argue) and the send-off resolves.
    BB_CHECK_EQ(m.decision_team, 0);
    st = ap(&m, &rng, BB_A_CHOOSE_OPTION, 0, 0, 0);
    BB_CHECK_EQ(m.players[ATT].location, BB_LOC_SENT_OFF);
    BB_CHECK_EQ(m.players[DEF].stance, BB_STANCE_PRONE);  // no injury roll
    BB_CHECK_EQ(m.decision_team, 1);              // turnover ended the turn
}

// [GAME] BEING SENT-OFF: the fouler is Sent-off "after the Foul Action has
// been completed" — a double that ALSO breaks armour still resolves the
// Injury Roll first (the victim suffers the result), then the send-off.
BB_TEST(rules_foul_double_breaks_armour_injury_still_resolves) {
    bb_match m;
    build_foul_fixture(&m);
    static const uint8_t dice[] = {5, 5 /*armour 10: breaks, double*/,
                                   1, 2 /*injury 3: stunned*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 4);
    bb_status st = run_foul(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 4);               // injury WAS rolled
    BB_CHECK(fx_stunned(&m, DEF));
    BB_CHECK_EQ(m.decision_team, 0); // Argue the Call window
    st = ap(&m, &rng, BB_A_CHOOSE_OPTION, 0, 0, 0);
    BB_CHECK_EQ(m.players[ATT].location, BB_LOC_SENT_OFF);
    BB_CHECK_EQ(m.decision_team, 1);
}

// [GAME] BEING SENT-OFF worked example: "rolling a 6 and a 3, which breaks
// their armour. They then make an Injury Roll and roll a double 2, causing
// the Tomb Kings Blitzer to be Sent-off and the Bretonnian Squire to be
// Stunned." A natural double on the INJURY roll alone sends the fouler off;
// the victim still takes the injury result.
BB_TEST(rules_foul_natural_double_on_injury_sends_off) {
    bb_match m;
    build_foul_fixture(&m);
    static const uint8_t dice[] = {6, 3 /*armour 9: breaks, no double*/,
                                   2, 2 /*injury 4: stunned, double*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 4);
    bb_status st = run_foul(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 4);
    BB_CHECK_EQ(m.players[DEF].stance, BB_STANCE_STUNNED);
    BB_CHECK_EQ(m.decision_team, 0); // Argue the Call window
    st = ap(&m, &rng, BB_A_CHOOSE_OPTION, 0, 0, 0);
    BB_CHECK_EQ(m.players[ATT].location, BB_LOC_SENT_OFF);
    BB_CHECK_EQ(m.decision_team, 1);
}

// [GAME] PERFORMING A FOUL ACTION: "a SINGLE player on the active team may
// declare a Foul Action each Turn." After one foul resolves, no other player
// may declare a Foul this team turn.
BB_TEST(rules_foul_once_per_team_turn) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    fx_lineman(&m, 0, 0, 10, 5);
    int v1 = fx_lineman(&m, 1, 0, 10, 6);
    m.players[v1].stance = BB_STANCE_PRONE;
    int f2 = fx_lineman(&m, 0, 1, 3, 5);          // second would-be fouler
    int v2 = fx_lineman(&m, 1, 1, 3, 6);
    m.players[v2].stance = BB_STANCE_PRONE;
    fx_lineman(&m, 1, 2, 23, 12);
    static const uint8_t dice[] = {3, 4 /*armour 7: holds, no double*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);
    bb_status st = run_foul(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, 0);
    st = ap(&m, &rng, BB_A_ACTIVATE, f2, 0, 0);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    // f2 is adjacent to a Prone opponent, but the team's Foul is spent.
    BB_CHECK_EQ(fx_find(&m, (bb_action){BB_A_DECLARE, BB_ACT_FOUL, 0, 0}), -1);
    BB_CHECK(fx_find(&m, (bb_action){BB_A_DECLARE, BB_ACT_MOVE, 0, 0}) >= 0);
}

// [GAME] PERFORMING A FOUL ACTION: "The player must finish their Move Action
// adjacent to a Prone or Stunned opposition player in order to perform the
// Foul Action." A Standing opponent is not a legal foul target.
BB_TEST(rules_foul_target_must_be_prone_or_stunned) {
    bb_match m;
    build_foul_fixture(&m);
    fx_lineman(&m, 1, 2, 11, 5);                  // standing opponent adjacent
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    ap(&m, &rng, BB_A_ACTIVATE, ATT, 0, 0);
    st = ap(&m, &rng, BB_A_DECLARE, BB_ACT_FOUL, 0, 0);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(fx_find(&m, (bb_action){BB_A_FOUL_TARGET, 0, 10, 6}) >= 0); // prone
    BB_CHECK_EQ(fx_find(&m, (bb_action){BB_A_FOUL_TARGET, 0, 11, 5}), -1); // standing
}

// [GAME] PERFORMING A FOUL ACTION: "they cannot continue to move after the
// Foul Action has been committed." After the foul, the fouler's activation is
// over (no further steps) and the fouler counts as activated.
BB_TEST(rules_foul_ends_activation_no_more_movement) {
    bb_match m;
    build_foul_fixture(&m);
    static const uint8_t dice[] = {3, 4 /*armour 7: holds*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);
    bb_status st = run_foul(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, 0);
    BB_CHECK(!fx_has_type(&m, BB_A_STEP));        // no movement offered
    BB_CHECK(m.players[ATT].flags & BB_PF_USED);  // activation consumed
    BB_CHECK_EQ(fx_find(&m, (bb_action){BB_A_ACTIVATE, ATT, 0, 0}), -1);
}

// ENGINE-DIVERGENCE: [GAME] ARGUE THE CALL — "When a player is Sent-off for
// any reason, their Coach may attempt to Argue the Call - roll a D6...
// 6: the player is placed back in the square they were in and is not
// Sent-off, though a Turnover is still caused." After a doubles foul the
// fouling coach must get the Argue-the-Call window (a decision for team 0)
// before play passes on. The engine has no Argue the Call at all (phase-3
// scope, like the Apothecary TODO): it sends the player off and hands the
// decision straight to team 1.
BB_TEST(rules_foul_sendoff_offers_argue_the_call) {
    bb_match m;
    build_foul_fixture(&m);
    static const uint8_t dice[] = {2, 2 /*armour double: sent off*/};
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);
    bb_status st = run_foul(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    // Rulebook: the next decision belongs to the fouling coach (Argue the
    // Call: roll the D6 or decline). Engine: decision_team is already 1.
    BB_CHECK_EQ(m.decision_team, 0);
}

