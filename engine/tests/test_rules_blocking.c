// test_rules_blocking.c — RULEBOOK tests for Block Actions, block dice, pushes,
// chain pushes, crowd pushes, follow-up, blitzes and the team-reroll window.
//
// Every test encodes what the BB2025 rulebook mirror says (paraphrased; no
// verbatim GW text per repo policy). Primary sources, relative to
// docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/:
//   GB  = core_rules/the_game_of_blood_bowl/index.html   (BLOCK ACTIONS!,
//         PUSHED PLAYERS, CHAIN PUSHES, PUSHED INTO THE CROWD, FOLLOW-UP,
//         BLITZ ACTIONS!, INJURY BY THE CROWD, TOUCHDOWN!)
//   RR  = core_rules/rules_and_regulations/index.html    (RE-ROLLS, TEAM
//         RE-ROLLS, THE TURNOVER, PLAYER STATUS, KNOCKED DOWN)
//   SK  = core_rules/skills_and_traits/index.html        (Block, Dodge,
//         Tackle, Guard, Wrestle, Loner)
//   CS  = core_rules/cheat_sheet/index.html              (block dice counts)
//   FAQ = core_rules/latest_faq/index.html               (May 2026)
//
// Tests that the engine currently fails are marked with a leading
// "// ENGINE-DIVERGENCE:" comment and intentionally left failing.
#include "bb/bb_match.h"
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb_fixtures.h"
#include "bb_test.h"

static bb_action mk(int type, int arg, int x, int y) {
    bb_action a = {(uint8_t)type, (uint8_t)arg, (uint8_t)x, (uint8_t)y};
    return a;
}

// Count legal actions of one type at the current decision point.
static int count_type(const bb_match* m, int type) {
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(m, legal);
    int c = 0;
    for (int i = 0; i < n; i++) {
        if (legal[i].type == type) c++;
    }
    return c;
}

// Apply and require the engine to land on another coach decision.
static void apply_ok(bb_match* m, bb_rng* rng, bb_action a) {
    bb_status st = fx_apply(m, a, rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
}

// Run to the activation menu and declare a Block Action against (tx,ty).
// Leaves the engine at the next decision after the block dice are rolled
// (re-roll window if available, otherwise the choose-die decision).
static void start_block(bb_match* m, bb_rng* rng, int att, int tx, int ty) {
    bb_status st = fx_run(m, rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    apply_ok(m, rng, mk(BB_A_ACTIVATE, att, 0, 0));
    apply_ok(m, rng, mk(BB_A_DECLARE, BB_ACT_BLOCK, 0, 0));
    apply_ok(m, rng, mk(BB_A_BLOCK_TARGET, 0, tx, ty));
}

// ============================ BLOCK DICE COUNTS ==============================

// GB#PERFORMING A BLOCK ACTION + CS: equal modified ST -> roll one Block Die
// (the single result must be applied). GB#BLOCK ACTIONS!: the target must be a
// Standing opposition player the blocker is Marking; a plain Block Action has
// no movement (only Blitz combines Move + Block, GB#BLITZ ACTIONS!).
BB_TEST(blocking_basics_equal_st_one_die) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);
    int a2 = fx_lineman(&m, BB_AWAY, 1, 11, 6);
    m.players[a2].stance = BB_STANCE_PRONE; // prone: not a legal block target

    uint8_t script[] = {3};
    bb_rng rng;
    bb_rng_script(&rng, script, 1);

    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    apply_ok(&m, &rng, mk(BB_A_ACTIVATE, h1, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_DECLARE, BB_ACT_BLOCK, 0, 0));
    // A Block Action grants no movement.
    BB_CHECK(!fx_has_type(&m, BB_A_STEP));
    // Standing adjacent opponent is targetable; the prone one is not.
    BB_CHECK(fx_find(&m, mk(BB_A_BLOCK_TARGET, 0, 11, 7)) >= 0);
    BB_CHECK_EQ(fx_find(&m, mk(BB_A_BLOCK_TARGET, 0, 11, 6)), -1);
    apply_ok(&m, &rng, mk(BB_A_BLOCK_TARGET, 0, 11, 7));
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 1);
    BB_CHECK_EQ(m.decision_team, BB_HOME);
    BB_CHECK(!bb_rng_error(&rng));
}

// GB#PERFORMING A BLOCK ACTION: one player with higher modified ST -> two
// Block Dice, and the coach of the stronger player chooses the result.
BB_TEST(blocking_higher_st_two_dice_attacker_chooses) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_player(&m, BB_HOME, 0, 10, 7, 6, 4, 3, 4, 9); // ST4
    fx_lineman(&m, BB_AWAY, 0, 11, 7);                        // ST3

    uint8_t script[] = {3, 4};
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    start_block(&m, &rng, h1, 11, 7);
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 2);
    BB_CHECK_EQ(m.decision_team, BB_HOME);
    BB_CHECK(!bb_rng_error(&rng));
}

// ENGINE-DIVERGENCE: GB#PERFORMING A BLOCK ACTION and CS both require a ST
// OVER double the opponent's for three dice ("over double"); exactly double
// is only "higher" and rolls TWO dice. The engine (proc_block.c:52) uses
// `st_a >= 2 * st_d`, so ST6 vs ST3 wrongly rolls three dice.
BB_TEST(blocking_exactly_double_st_two_dice) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_player(&m, BB_HOME, 0, 10, 7, 6, 6, 3, 4, 9); // ST6
    fx_lineman(&m, BB_AWAY, 0, 11, 7);                        // ST3: exactly double

    uint8_t script[] = {3, 4, 3}; // third value only so the engine's bug
    bb_rng rng;                   // doesn't exhaust the script
    bb_rng_script(&rng, script, 3);
    start_block(&m, &rng, h1, 11, 7);
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 2); // rulebook: two dice
}

// GB#PERFORMING A BLOCK ACTION: ST over double the opponent's -> three Block
// Dice, stronger coach chooses.
BB_TEST(blocking_over_double_st_three_dice) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_player(&m, BB_HOME, 0, 10, 7, 6, 7, 3, 4, 9); // ST7 > 2*3
    fx_lineman(&m, BB_AWAY, 0, 11, 7);

    uint8_t script[] = {3, 4, 3};
    bb_rng rng;
    bb_rng_script(&rng, script, 3);
    start_block(&m, &rng, h1, 11, 7);
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 3);
    BB_CHECK_EQ(m.decision_team, BB_HOME);
    BB_CHECK(!bb_rng_error(&rng));
}

// GB#SELECT AND APPLY RESULT: with multiple dice it is always the coach of the
// STRONGER player who chooses — here the defender. GB#PLAYER DOWN: the blocker
// is Knocked Down as if blocked. RR#THE TURNOVER + RR#KNOCKED DOWN: an active-
// team player Knocked Down in their own turn causes a Turnover (armour rolled,
// turn ends).
BB_TEST(blocking_defender_stronger_chooses_skull_turnover) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);               // ST3
    int a1 = fx_player(&m, BB_AWAY, 0, 11, 7, 6, 4, 3, 4, 9); // ST4

    uint8_t script[] = {1, 2, /*attacker armour*/ 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 4);
    start_block(&m, &rng, h1, 11, 7);
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 2);
    BB_CHECK_EQ(m.decision_team, BB_AWAY); // defender's coach picks
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0)); // skull
    BB_CHECK_EQ(m.players[h1].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.active_team, BB_AWAY); // turnover: home turn ended
    BB_CHECK(!bb_rng_error(&rng));
}

// ================================ ASSISTS ====================================

// GB#OFFENSIVE ASSISTS: each team-mate Marking the target of the block and not
// Marked by any other opposition player adds +1 to the blocker's ST.
BB_TEST(blocking_offensive_assist_grants_second_die) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_lineman(&m, BB_HOME, 1, 11, 8); // marks the target, unmarked otherwise

    uint8_t script[] = {3, 4};
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    start_block(&m, &rng, h1, 11, 7); // 3+1 vs 3 -> two dice
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 2);
    BB_CHECK_EQ(m.decision_team, BB_HOME);
    BB_CHECK(!bb_rng_error(&rng));
}

// GB#OFFENSIVE ASSISTS: a would-be assister who is Marked by another opposition
// player cannot assist. SK#GUARD: a player with Guard assists regardless of how
// many opponents Mark them.
BB_TEST(blocking_marked_assister_needs_guard) {
    // Without Guard: H2 marks the target but is Marked by A2 -> no assist.
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);
    int h2 = fx_lineman(&m, BB_HOME, 1, 11, 8);
    fx_lineman(&m, BB_AWAY, 1, 11, 9); // marks H2 only

    uint8_t script1[] = {3};
    bb_rng rng;
    bb_rng_script(&rng, script1, 1);
    start_block(&m, &rng, h1, 11, 7);
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 1);
    BB_CHECK(!bb_rng_error(&rng));

    // Same position but H2 has Guard -> the assist counts -> two dice.
    fx_match_midturn(&m, BB_HOME, 0);
    h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);
    h2 = fx_lineman(&m, BB_HOME, 1, 11, 8);
    fx_lineman(&m, BB_AWAY, 1, 11, 9);
    fx_give_skill(&m, h2, BB_SK_GUARD);

    uint8_t script2[] = {3, 4};
    bb_rng_script(&rng, script2, 2);
    start_block(&m, &rng, h1, 11, 7);
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 2);
    BB_CHECK(!bb_rng_error(&rng));
}

// GB#DEFENSIVE ASSISTS: each inactive-team player Marking the BLOCKER and not
// Marked by any other opposition player adds +1 to the target's ST; the
// defender becomes stronger, so the defender's coach chooses the die.
BB_TEST(blocking_defensive_assist_defender_chooses) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_lineman(&m, BB_AWAY, 1, 9, 7); // marks H1, unmarked itself

    uint8_t script[] = {3, 4};
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    start_block(&m, &rng, h1, 11, 7); // 3 vs 3+1 -> two dice, defender picks
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 2);
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
    BB_CHECK(!bb_rng_error(&rng));
}

// RR#TACKLE ZONES / RR#PRONE AND STUNNED PLAYERS: only Standing players have a
// Tackle Zone; Marking requires a TZ. So a Prone team-mate cannot assist, and
// a Prone opponent cannot deny an assist (it Marks nobody).
BB_TEST(blocking_prone_players_neither_assist_nor_deny) {
    // Prone team-mate adjacent to the target: no assist -> one die.
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);
    int h2 = fx_lineman(&m, BB_HOME, 1, 11, 8);
    m.players[h2].stance = BB_STANCE_PRONE;

    uint8_t script1[] = {3};
    bb_rng rng;
    bb_rng_script(&rng, script1, 1);
    start_block(&m, &rng, h1, 11, 7);
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 1);
    BB_CHECK(!bb_rng_error(&rng));

    // Standing assister "marked" only by a PRONE opponent still assists.
    fx_match_midturn(&m, BB_HOME, 0);
    h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_lineman(&m, BB_HOME, 1, 11, 8);
    int a2 = fx_lineman(&m, BB_AWAY, 1, 11, 9);
    m.players[a2].stance = BB_STANCE_PRONE;

    uint8_t script2[] = {3, 4};
    bb_rng_script(&rng, script2, 2);
    start_block(&m, &rng, h1, 11, 7);
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 2);
    BB_CHECK(!bb_rng_error(&rng));
}

// ENGINE-DIVERGENCE: RR#DISTRACTED — a Distracted player has no Tackle Zone,
// so it Marks nobody and cannot give an Offensive or Defensive Assist
// (GB#ASSISTING A BLOCK ACTION requires the assister to be Marking). The
// engine never consults the Distracted/no-TZ flags in bb_can_assist
// (bb_skills.c), so a Distracted team-mate still assists. Phase-3 territory
// (Distracted is not yet wired up anywhere).
BB_TEST(blocking_distracted_player_cannot_assist) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);
    int h2 = fx_lineman(&m, BB_HOME, 1, 11, 8);
    m.players[h2].flags |= BB_PF_DISTRACTED | BB_PF_NO_TZ;

    uint8_t script[] = {3, 4}; // 2nd value so the engine's extra die has fuel
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    start_block(&m, &rng, h1, 11, 7);
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 1); // rulebook: no assist
}

// ============================ BLOCK DICE FACES ===============================

// GB#BOTH DOWN: both players are Knocked Down by each other. The defender's
// knockdown resolves first (its armour/injury), then the attacker's. The
// attacker going down in his own turn is a Turnover (RR#THE TURNOVER).
BB_TEST(blocking_both_down_plain_defender_resolves_first) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_lineman(&m, BB_AWAY, 1, 20, 7); // away player for the post-turnover turn

    // die=BothDown; defender armour 6+6=12 breaks AV9 -> injury 2+2=Stunned;
    // attacker armour 2+2 holds. If the engine resolved the attacker first the
    // stances would come out differently.
    uint8_t script[] = {2, 6, 6, 2, 2, 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 7);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    BB_CHECK(fx_stunned(&m, a1)); // stunned (turn-start marker allowed)
    BB_CHECK_EQ(m.players[h1].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.active_team, BB_AWAY); // turnover ended the home turn
    BB_CHECK(!bb_rng_error(&rng));
}

// SK#BLOCK: a player with Block may choose not to be Knocked Down by a Both
// Down result. Attacker with Block: stays up, no turnover; only the defender
// goes down and rolls armour.
BB_TEST(blocking_both_down_attacker_block_stays_up) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, h1, BB_SK_BLOCK);

    uint8_t script[] = {2, /*defender armour*/ 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 3);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    BB_CHECK_EQ(m.players[h1].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.active_team, BB_HOME); // no turnover
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK(fx_has_type(&m, BB_A_END_ACTIVATION));
    BB_CHECK(!bb_rng_error(&rng));
}

// SK#BLOCK on the defender only: the defender opts out, the attacker is still
// Knocked Down -> armour for the attacker, Turnover.
BB_TEST(blocking_both_down_defender_block_only) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, a1, BB_SK_BLOCK);

    uint8_t script[] = {2, /*attacker armour*/ 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 3);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    BB_CHECK_EQ(m.players[h1].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.active_team, BB_AWAY); // turnover
    BB_CHECK(!bb_rng_error(&rng));
}

// SK#BLOCK on both: both opt out, nobody is Knocked Down, no armour dice, no
// turnover; the activation simply continues.
BB_TEST(blocking_both_down_both_block_nothing_happens) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, h1, BB_SK_BLOCK);
    fx_give_skill(&m, a1, BB_SK_BLOCK);

    uint8_t script[] = {2}; // exactly one die: any armour roll would error
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    BB_CHECK_EQ(m.players[h1].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK_EQ(m.active_team, BB_HOME);
    BB_CHECK(!bb_rng_error(&rng));
}

// SK#WRESTLE — when Both Down is applied, a player with Wrestle "may choose
// to use this Skill" (D29: a real USE_SKILL/DECLINE_SKILL window for the
// owner's coach). Using it: BOTH players are Placed Prone "regardless of any
// other Skills" (RR#PLACED PRONE: no Armour Roll; a non-carrier active player
// Placed Prone is NOT a Turnover).
BB_TEST(blocking_both_down_wrestle_defender_window_use_places_both_prone) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, a1, BB_SK_WRESTLE);

    uint8_t script[] = {2}; // Both Down; Wrestle used -> no armour dice at all
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    // The DEFENDER owns the skill: the decision is the away coach's.
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
    BB_CHECK(fx_find(&m, mk(BB_A_USE_SKILL, BB_SK_WRESTLE, 0, 0)) >= 0);
    BB_CHECK(fx_find(&m, mk(BB_A_DECLINE_SKILL, BB_SK_WRESTLE, 0, 0)) >= 0);
    bb_status st = fx_apply(&m, mk(BB_A_USE_SKILL, BB_SK_WRESTLE, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[h1].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_PRONE);
    BB_CHECK(!bb_rng_error(&rng));        // no Armour Rolls were made
    BB_CHECK_EQ(m.active_team, BB_HOME);  // Placed Prone w/o ball: no turnover
    BB_CHECK_EQ(m.turnover, 0);
}

// SK#WRESTLE is OPTIONAL ("may choose"): a Wrestle DEFENDER facing a
// Block-less attacker should DECLINE — plain Both Down then Knocks the
// attacker Down (RR#THE TURNOVER: active player Knocked Down = Turnover) at
// the cost of mutual Armour Rolls. This is D29's motivating counterexample.
BB_TEST(blocking_both_down_wrestle_defender_declines_forces_turnover) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, a1, BB_SK_WRESTLE);

    // Block die (Both Down); decline -> defender armour (2,2) + attacker
    // armour (2,2).
    uint8_t script[] = {2, 2, 2, 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 5);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
    bb_status st = fx_apply(&m, mk(BB_A_DECLINE_SKILL, BB_SK_WRESTLE, 0, 0), &rng);
    BB_CHECK_EQ(m.players[h1].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_PRONE);
    BB_CHECK(!bb_rng_error(&rng)); // both armour rolls were made
    // Attacker (active team) Knocked Down: the team turn ends in a Turnover.
    BB_CHECK_EQ(m.active_team, BB_AWAY); // turnover advanced to the away turn
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
}

// SK#WRESTLE: the ATTACKER may own the window too; FFB (StepWrestle) asks the
// attacker first, then the defender. An attacker's decline hands the choice
// to a Wrestle defender; both declining resolves the plain Both Down (here
// both have Block, so nobody goes down and no armour is rolled).
BB_TEST(blocking_both_down_wrestle_attacker_window_then_defender) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, h1, BB_SK_WRESTLE);
    fx_give_skill(&m, h1, BB_SK_BLOCK);
    fx_give_skill(&m, a1, BB_SK_WRESTLE);
    fx_give_skill(&m, a1, BB_SK_BLOCK);

    uint8_t script[] = {2}; // Both Down; both decline; Block keeps both up
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    BB_CHECK_EQ(m.decision_team, BB_HOME); // attacker's window first
    apply_ok(&m, &rng, mk(BB_A_DECLINE_SKILL, BB_SK_WRESTLE, 0, 0));
    BB_CHECK_EQ(m.decision_team, BB_AWAY); // then the defender's
    apply_ok(&m, &rng, mk(BB_A_DECLINE_SKILL, BB_SK_WRESTLE, 0, 0));
    BB_CHECK_EQ(m.players[h1].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_STANDING);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.turnover, 0);
}

// RR#DISTRACTED: "they cannot use Active Skills or Traits" — a Distracted
// Wrestle defender gets NO window; the plain Both Down resolves directly.
BB_TEST(blocking_both_down_wrestle_distracted_defender_no_window) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, a1, BB_SK_WRESTLE);
    m.players[a1].flags |= BB_PF_DISTRACTED;

    uint8_t script[] = {2, 2, 2, 2, 2}; // Both Down + def armour + att armour
    bb_rng rng;
    bb_rng_script(&rng, script, 5);
    start_block(&m, &rng, h1, 11, 7);
    fx_apply(&m, mk(BB_A_CHOOSE_DIE, 0, 0, 0), &rng);
    // No Wrestle window: both Knocked Down immediately, armour rolled.
    BB_CHECK_EQ(m.players[h1].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.active_team, BB_AWAY); // attacker down: turnover
}

// SK#WRESTLE + RR#THE TURNOVER: an ACTIVE ball carrier Placed Prone by
// Wrestle drops the ball (bounce) and causes a Turnover.
BB_TEST(blocking_both_down_wrestle_active_carrier_turnover) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, a1, BB_SK_WRESTLE);
    fx_ball_held(&m, h1);

    uint8_t script[] = {2, /*bounce d8*/ 1};
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
    fx_apply(&m, mk(BB_A_USE_SKILL, BB_SK_WRESTLE, 0, 0), &rng);
    BB_CHECK_EQ(m.players[h1].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND); // dropped + bounced
    BB_CHECK_EQ(m.active_team, BB_AWAY);          // carrier prone: turnover
    BB_CHECK(!bb_rng_error(&rng));
}

// ============================== STAND FIRM ===================================

// SK#STAND FIRM: "When this player would be Pushed Back during a Block
// Action ... they can CHOOSE to not be Pushed Back and instead remain in
// their current square" — a USE_SKILL/DECLINE_SKILL window for the pushee's
// coach (D17 reversal; FFB allows the decline). Using it: not moved, and the
// attacker cannot Follow-up (no square was vacated).
BB_TEST(blocking_stand_firm_window_use_not_moved) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, a1, BB_SK_STAND_FIRM);

    uint8_t script[] = {3}; // Push Back
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    BB_CHECK_EQ(m.decision_team, BB_AWAY); // the pushee's coach decides
    BB_CHECK(fx_find(&m, mk(BB_A_USE_SKILL, BB_SK_STAND_FIRM, 0, 0)) >= 0);
    BB_CHECK(fx_find(&m, mk(BB_A_DECLINE_SKILL, BB_SK_STAND_FIRM, 0, 0)) >= 0);
    fx_apply(&m, mk(BB_A_USE_SKILL, BB_SK_STAND_FIRM, 0, 0), &rng);
    BB_CHECK_EQ(m.players[a1].x, 11); // not moved
    BB_CHECK_EQ(m.players[a1].y, 7);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[h1].x, 10); // no follow-up happened
    BB_CHECK(!bb_rng_error(&rng));
}

// SK#STAND FIRM is optional: declining resolves the push as normal (the
// usual three-square choice for the attacking coach, then the follow-up).
BB_TEST(blocking_stand_firm_window_decline_normal_push) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, a1, BB_SK_STAND_FIRM);

    uint8_t script[] = {3}; // Push Back
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_DECLINE_SKILL, BB_SK_STAND_FIRM, 0, 0));
    BB_CHECK_EQ(m.decision_team, BB_HOME); // attacker picks the square
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7));
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 1, 0, 0));
    BB_CHECK_EQ(m.players[a1].x, 12); // pushed normally
    BB_CHECK_EQ(m.players[h1].x, 11); // followed up
    BB_CHECK(!bb_rng_error(&rng));
}

// SK#STAND FIRM + POW: using the skill against a POW means the player is
// Knocked Down in the square they remained in (armour rolls follow).
BB_TEST(blocking_stand_firm_pow_use_knockdown_in_place) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, a1, BB_SK_STAND_FIRM);

    uint8_t script[] = {6, /*armour*/ 2, 2}; // POW, armour holds
    bb_rng rng;
    bb_rng_script(&rng, script, 3);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
    fx_apply(&m, mk(BB_A_USE_SKILL, BB_SK_STAND_FIRM, 0, 0), &rng);
    BB_CHECK_EQ(m.players[a1].x, 11); // down where they stood
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_PRONE);
    BB_CHECK(!bb_rng_error(&rng));
}

// SK#JUGGERNAUT: "when this player performs a Block Action as part of a
// Blitz Action, opposition players cannot use ... Stand Firm" -> no window.
BB_TEST(blocking_stand_firm_juggernaut_blitz_no_window) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, h1, BB_SK_JUGGERNAUT);
    fx_give_skill(&m, a1, BB_SK_STAND_FIRM);

    uint8_t script[] = {3}; // Push Back
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    apply_ok(&m, &rng, mk(BB_A_ACTIVATE, h1, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_BLOCK_TARGET, 0, 11, 7));
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    // No Stand Firm window: straight to the attacker's push-square choice.
    BB_CHECK_EQ(m.decision_team, BB_HOME);
    BB_CHECK(fx_has_type(&m, BB_A_PUSH_SQUARE));
    BB_CHECK(!bb_rng_error(&rng));
}

// RR#DISTRACTED: a Distracted player cannot use Active Skills — no Stand
// Firm window; the push resolves normally.
BB_TEST(blocking_stand_firm_distracted_no_window) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, a1, BB_SK_STAND_FIRM);
    m.players[a1].flags |= BB_PF_DISTRACTED;

    uint8_t script[] = {3};
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    BB_CHECK_EQ(m.decision_team, BB_HOME); // straight to the push squares
    BB_CHECK(fx_has_type(&m, BB_A_PUSH_SQUARE));
}

// SK#STAND FIRM "including during a Chain Push": a chained occupant gets the
// window too; if they remain, the player being chain-pushed into their square
// cannot move either — the push is absorbed with nobody relocated.
BB_TEST(blocking_stand_firm_chain_occupant_absorbs_push) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    int a2 = fx_lineman(&m, BB_AWAY, 1, 12, 7); // occupant with Stand Firm
    fx_lineman(&m, BB_AWAY, 2, 12, 6);          // block the other candidates
    fx_lineman(&m, BB_AWAY, 3, 12, 8);
    fx_give_skill(&m, a2, BB_SK_STAND_FIRM);

    uint8_t script[] = {3}; // Push Back
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    // All three candidates occupied: chain push into (12,7).
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 2, 12, 7));
    BB_CHECK_EQ(m.decision_team, BB_AWAY); // the chained occupant's window
    fx_apply(&m, mk(BB_A_USE_SKILL, BB_SK_STAND_FIRM, 0, 0), &rng);
    BB_CHECK_EQ(m.players[a2].x, 12); // occupant stayed
    BB_CHECK_EQ(m.players[a1].x, 11); // pushee absorbed in place
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[h1].x, 10); // no follow-up possible
    BB_CHECK(!bb_rng_error(&rng));
}

// ================================ STUMBLE ====================================

// GB#STUMBLE: if the target has Dodge, Stumble becomes Push Back — defender
// stays Standing, no armour roll. GB#PUSHED PLAYERS: a pushed ball carrier
// keeps the ball (only POW/knockdown makes it bounce).
BB_TEST(blocking_stumble_dodge_becomes_push_carrier_keeps_ball) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, a1, BB_SK_DODGE);
    fx_ball_held(&m, a1);

    uint8_t script[] = {5}; // Stumble; no other dice may be needed
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7));
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[a1].x, 12);
    BB_CHECK_EQ(m.players[a1].y, 7);
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD); // pushed carrier keeps the ball
    BB_CHECK_EQ(m.ball.carrier, a1);
    BB_CHECK_EQ(m.ball.x, 12);
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK(!bb_rng_error(&rng));
}

// SK#TACKLE: against a blocker with Tackle the target does not count as having
// Dodge when Stumble is selected -> resolved as POW (pushed, then Knocked
// Down in the square moved to).
BB_TEST(blocking_stumble_tackle_cancels_dodge) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, a1, BB_SK_DODGE);
    fx_give_skill(&m, h1, BB_SK_TACKLE);

    uint8_t script[] = {5, /*defender armour*/ 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 3);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7));
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[a1].x, 12); // knocked down in the new square
    BB_CHECK_EQ(m.turnover, 0);       // inactive player down: no turnover
    BB_CHECK(!bb_rng_error(&rng));
}

// GB#STUMBLE: without Dodge the result becomes POW — push back, then the
// target is Knocked Down in the square they are now in (armour rolled there).
BB_TEST(blocking_stumble_without_dodge_is_pow) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);

    uint8_t script[] = {5, 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 3);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7));
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[a1].x, 12);
    BB_CHECK_EQ(m.players[a1].y, 7);
    BB_CHECK_EQ(m.players[h1].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK(!bb_rng_error(&rng));
}

// Regression (adversarial review M5): a POW knockdown must carry the CAUSER
// so the attacker's armour/injury skills apply. SK#MIGHTY BLOW (+1): may be
// applied to the Armour Roll (auto-policy: when it converts a miss into a
// break, see DECISIONS.md D16). The engine's phase-5 POW used the no-causer
// bb_knockdown, so Mighty Blow/Claws/Saboteur were dead on the main path.
BB_TEST(blocking_pow_mighty_blow_converts_armour) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7); // AV9
    fx_give_skill(&m, h1, BB_SK_MIGHTY_BLOW);

    // POW; armour 4+4=8 < AV9 holds WITHOUT the causer — Mighty Blow +1
    // makes 9 and breaks; injury 2+2=4 -> Stunned (MB consumed on armour).
    uint8_t script[] = {6, 4, 4, 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 5);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7));
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    BB_CHECK(fx_stunned(&m, a1)); // armour broken only via Mighty Blow
    BB_CHECK_EQ(m.players[a1].x, 12);
    BB_CHECK_EQ(m.players[a1].y, 7);
    BB_CHECK_EQ(m.turnover, 0); // inactive player down: no turnover
    BB_CHECK_EQ(rng.script_pos, 5); // the injury roll really happened
    BB_CHECK(!bb_rng_error(&rng));
}

// Regression (adversarial review M5): SK#CLAWS — an unmodified Armour Roll of
// 8+ breaks armour regardless of the target's AV. Requires the causer to ride
// along on the POW knockdown.
BB_TEST(blocking_pow_claws_breaks_high_av) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_player(&m, BB_AWAY, 0, 11, 7, 6, 3, 3, 4, 10); // AV10
    fx_give_skill(&m, h1, BB_SK_CLAWS);

    // POW; armour 4+4 = natural 8 (< AV10, but Claws breaks on 8+);
    // injury 2+2 -> Stunned.
    uint8_t script[] = {6, 4, 4, 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 5);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7));
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    BB_CHECK(fx_stunned(&m, a1)); // armour broken only via Claws
    BB_CHECK_EQ(rng.script_pos, 5);
    BB_CHECK(!bb_rng_error(&rng));
}

// ENGINE-DIVERGENCE: FAQ (May 2026, pg.127 entry) — a Distracted player cannot
// use Dodge against a Stumble (Active skills are off while Distracted,
// RR#DISTRACTED), and likewise a Distracted player's Block does not save them
// from Both Down. The engine's bb_has_dodge_skill/bb_has_block ignore the
// Distracted/no-TZ flags, so the skills still apply.
BB_TEST(blocking_distracted_defender_active_skills_disabled) {
    // Stumble vs Distracted Dodge: rulebook resolves as POW.
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, a1, BB_SK_DODGE);
    m.players[a1].flags |= BB_PF_DISTRACTED | BB_PF_NO_TZ;

    uint8_t script1[] = {5, 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script1, 3);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7));
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_PRONE); // rulebook: POW

    // Both Down vs Distracted Block: rulebook knocks the defender down too.
    fx_match_midturn(&m, BB_HOME, 0);
    h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, a1, BB_SK_BLOCK);
    m.players[a1].flags |= BB_PF_DISTRACTED | BB_PF_NO_TZ;
    fx_lineman(&m, BB_AWAY, 1, 20, 7);

    uint8_t script2[] = {2, /*def armour*/ 2, 2, /*att armour*/ 2, 2};
    bb_rng_script(&rng, script2, 5);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_PRONE); // rulebook: down
    BB_CHECK_EQ(m.players[h1].stance, BB_STANCE_PRONE);
}

// ================================= PUSHES ====================================

// GB#PUSHED PLAYERS: a pushed player moves one square away from the blocker,
// into one of the three squares shown by the push diagrams (directly behind
// and the two 45-degree neighbours); the blocking coach chooses.
BB_TEST(blocking_push_candidate_squares) {
    // Straight push (east): candidates (12,6) (12,7) (12,8).
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);

    uint8_t script1[] = {3};
    bb_rng rng;
    bb_rng_script(&rng, script1, 1);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    BB_CHECK_EQ(count_type(&m, BB_A_PUSH_SQUARE), 3);
    BB_CHECK_EQ(m.decision_team, BB_HOME); // blocking coach chooses
    BB_CHECK(fx_find(&m, mk(BB_A_PUSH_SQUARE, 0, 12, 6)) >= 0);
    BB_CHECK(fx_find(&m, mk(BB_A_PUSH_SQUARE, 0, 12, 7)) >= 0);
    BB_CHECK(fx_find(&m, mk(BB_A_PUSH_SQUARE, 0, 12, 8)) >= 0);

    // Diagonal push (south-east): candidates (12,8) (12,9) (11,9).
    fx_match_midturn(&m, BB_HOME, 0);
    h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 8);

    uint8_t script2[] = {3};
    bb_rng_script(&rng, script2, 1);
    start_block(&m, &rng, h1, 11, 8);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    BB_CHECK_EQ(count_type(&m, BB_A_PUSH_SQUARE), 3);
    BB_CHECK(fx_find(&m, mk(BB_A_PUSH_SQUARE, 0, 12, 8)) >= 0);
    BB_CHECK(fx_find(&m, mk(BB_A_PUSH_SQUARE, 0, 12, 9)) >= 0);
    BB_CHECK(fx_find(&m, mk(BB_A_PUSH_SQUARE, 0, 11, 9)) >= 0);
}

// GB#PUSHED PLAYERS: the blocking coach must choose an UNOCCUPIED square if
// there is one — occupied candidates are not selectable then.
BB_TEST(blocking_push_must_choose_unoccupied) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_lineman(&m, BB_AWAY, 1, 12, 6); // occupies one candidate
    fx_lineman(&m, BB_AWAY, 2, 12, 8); // occupies another

    uint8_t script[] = {3};
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    BB_CHECK_EQ(count_type(&m, BB_A_PUSH_SQUARE), 1);
    BB_CHECK(fx_find(&m, mk(BB_A_PUSH_SQUARE, 0, 12, 7)) >= 0);
    BB_CHECK(!bb_rng_error(&rng));
}

// SK#SIDESTEP: a Pushed Back player with Side Step is moved to any adjacent
// unoccupied square chosen by THEIR coach instead of the usual three.
BB_TEST(blocking_side_step_defender_picks_any_free_square) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, a1, BB_SK_SIDESTEP);

    uint8_t script[] = {3};
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    // The DEFENDER's coach owns the choice: all 7 free adjacent squares.
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
    BB_CHECK_EQ(count_type(&m, BB_A_PUSH_SQUARE), 7);
    // Includes squares outside the normal push arc, e.g. beside the blocker.
    BB_CHECK(fx_find(&m, mk(BB_A_PUSH_SQUARE, 0, 10, 6)) >= 0);
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 10, 6));
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    BB_CHECK_EQ(m.players[a1].x, 10);
    BB_CHECK_EQ(m.players[a1].y, 6);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_STANDING);
    BB_CHECK(!bb_rng_error(&rng));
}

// Regression (adversarial review M8): SK#SIDESTEP — "If there are no adjacent
// unoccupied squares, then this Skill cannot be used." With every adjacent
// square occupied/off-pitch the normal candidates apply (here: chain pushes
// and a crowd push) and the choice belongs to the ATTACKING coach, not the
// defender's. The engine assigned ownership on skill possession alone.
BB_TEST(blocking_side_step_unusable_without_free_square) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 0); // blocker on the sideline row
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 0); // Side Step, fully boxed in
    fx_give_skill(&m, a1, BB_SK_SIDESTEP);
    fx_lineman(&m, BB_AWAY, 1, 12, 0);
    fx_lineman(&m, BB_AWAY, 2, 10, 1);
    fx_lineman(&m, BB_AWAY, 3, 11, 1);
    fx_lineman(&m, BB_AWAY, 4, 12, 1);

    // Two defensive assists -> two dice, defender's coach picks the die (that
    // ownership is unrelated to the push-square ownership under test).
    uint8_t script[] = {3, 4, /*crowd injury*/ 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 4);
    start_block(&m, &rng, h1, 11, 0);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0)); // push
    // No free adjacent square: Side Step is off. The ATTACKING coach owns
    // the chain/crowd choice among the normal three candidates.
    BB_CHECK_EQ(m.decision_team, BB_HOME);
    BB_CHECK_EQ(count_type(&m, BB_A_PUSH_SQUARE), 3);
    BB_CHECK(fx_find(&m, mk(BB_A_PUSH_SQUARE, 1, 12, 0)) >= 0); // crowd
    BB_CHECK(fx_find(&m, mk(BB_A_PUSH_SQUARE, 2, 12, 0)) >= 0); // chains
    BB_CHECK(fx_find(&m, mk(BB_A_PUSH_SQUARE, 2, 12, 1)) >= 0);
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 1, 12, 0)); // surf the defender
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    BB_CHECK_EQ(m.players[a1].location, BB_LOC_RESERVES); // crowd: stunned
    BB_CHECK_EQ(m.turnover, 0); // inactive player surfed: no turnover
    BB_CHECK(!bb_rng_error(&rng));
}

// GB#CHAIN PUSHES: with no unoccupied square the pushed player moves into an
// occupied one, chain-pushing its occupant as if pushed by the incoming
// player; the ORIGINAL blocking coach chooses every push direction in the
// chain; even Prone/Stunned players can be chain-pushed (and are NOT Knocked
// Down by it — no armour). GB#FOLLOW-UP still applies to the original block.
BB_TEST(blocking_chain_push_prone_not_knocked_down) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    int a2 = fx_lineman(&m, BB_AWAY, 1, 12, 6); // prone occupant
    m.players[a2].stance = BB_STANCE_PRONE;
    fx_lineman(&m, BB_AWAY, 2, 12, 7);
    fx_lineman(&m, BB_AWAY, 3, 12, 8);

    uint8_t script[] = {3}; // exactly one die: chain must not roll anything
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    // All three candidates occupied -> all offered as chain pushes.
    BB_CHECK_EQ(count_type(&m, BB_A_PUSH_SQUARE), 3);
    BB_CHECK(fx_find(&m, mk(BB_A_PUSH_SQUARE, 2, 12, 6)) >= 0);
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 2, 12, 6));
    // Chain: blocking coach picks where the prone occupant goes.
    BB_CHECK_EQ(m.decision_team, BB_HOME);
    BB_CHECK_EQ(count_type(&m, BB_A_PUSH_SQUARE), 3);
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 13, 5));
    // Follow-up offered for the original block.
    BB_CHECK(fx_has_type(&m, BB_A_FOLLOW_UP));
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));

    BB_CHECK_EQ(m.players[a2].x, 13);
    BB_CHECK_EQ(m.players[a2].y, 5);
    BB_CHECK_EQ(m.players[a2].stance, BB_STANCE_PRONE); // still just prone
    BB_CHECK_EQ(m.players[a1].x, 12);
    BB_CHECK_EQ(m.players[a1].y, 6);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_STANDING);
    BB_CHECK(!bb_rng_error(&rng)); // no armour dice anywhere in the chain
}

// GB#PUSHED INTO THE CROWD + GB#INJURY BY THE CROWD: at the pitch edge with no
// unoccupied square the player goes into the crowd: an immediate Injury Roll
// with NO Armour Roll; a Stunned result puts them in the Reserves box; other
// results follow the injury table (KO -> KO box).
BB_TEST(blocking_crowd_push_injury_no_armour) {
    // Stunned band -> Reserves box.
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 11, 1);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 0); // on the sideline

    uint8_t script1[] = {3, /*crowd injury only*/ 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script1, 3);
    start_block(&m, &rng, h1, 11, 0);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    // All push candidates are off-pitch -> crowd pushes (arg 1).
    BB_CHECK_EQ(count_type(&m, BB_A_PUSH_SQUARE), 3);
    BB_CHECK(fx_find(&m, mk(BB_A_PUSH_SQUARE, 1, 11, 0)) >= 0);
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 1, 11, 0));
    BB_CHECK_EQ(m.players[a1].location, BB_LOC_RESERVES);
    BB_CHECK_EQ(m.grid[11][0], 0);
    BB_CHECK(!bb_rng_error(&rng)); // exactly 2 injury dice: no armour rolled

    // KO band -> KO box.
    fx_match_midturn(&m, BB_HOME, 0);
    h1 = fx_lineman(&m, BB_HOME, 0, 11, 1);
    a1 = fx_lineman(&m, BB_AWAY, 0, 11, 0);

    uint8_t script2[] = {3, 4, 4};
    bb_rng_script(&rng, script2, 3);
    start_block(&m, &rng, h1, 11, 0);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 1, 11, 0));
    BB_CHECK_EQ(m.players[a1].location, BB_LOC_KO);
    BB_CHECK(!bb_rng_error(&rng));
}

// GB#PUSHED INTO THE CROWD: a ball carrier pushed into the crowd loses the
// ball, which is Thrown-in from the square they left. An INACTIVE-team player
// in the crowd is no Turnover — the blocker's turn continues.
BB_TEST(blocking_crowd_push_carrier_ball_thrown_in) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 11, 1);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 0);
    fx_ball_held(&m, a1);

    // die; throw-in dir D6=3 (template 1-2/3-4/5-6: straight in); distance
    // 2D6=3+3 counting the boundary square as first (5 steps -> (11,5), an
    // empty square: the thrown-in ball comes to rest); crowd injury 2+2.
    uint8_t script[] = {3, 3, 3, 3, 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 6);
    start_block(&m, &rng, h1, 11, 0);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 1, 11, 0));
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    BB_CHECK_EQ(m.players[a1].location, BB_LOC_RESERVES);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.carrier, BB_NO_PLAYER);
    BB_CHECK_EQ(m.ball.x, 11); // thrown in 5 squares to (11,5), comes to rest
    BB_CHECK_EQ(m.ball.y, 5);
    BB_CHECK_EQ(m.turnover, 0);             // inactive carrier: no turnover
    BB_CHECK_EQ(m.decision_team, BB_HOME);  // home turn continues
    BB_CHECK(!bb_rng_error(&rng));
}

// Regression (adversarial review H1): crowd-surfing a NON-carrier must not
// strip the ball from an unrelated carrier elsewhere on the pitch.
// bb_drop_ball operates on the global carrier; the crowd path called it
// unconditionally, orphaning the ball under the real carrier's feet.
BB_TEST(blocking_crowd_push_noncarrier_keeps_unrelated_carrier_ball) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 11, 1);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 0); // surfed, NOT carrying
    int a2 = fx_lineman(&m, BB_AWAY, 1, 20, 7); // carrier, far away
    fx_ball_held(&m, a2);

    uint8_t script[] = {3, /*crowd injury*/ 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 3);
    start_block(&m, &rng, h1, 11, 0);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 1, 11, 0));
    BB_CHECK_EQ(m.players[a1].location, BB_LOC_RESERVES);
    // The unrelated carrier still holds the ball.
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(m.ball.carrier, a2);
    BB_CHECK(m.players[a2].flags & BB_PF_HAS_BALL);
    BB_CHECK_EQ(m.ball.x, 20);
    BB_CHECK_EQ(m.ball.y, 7);
}

// ENGINE-DIVERGENCE: GB#PUSHED INTO THE CROWD — if a player on the ACTIVE team
// is pushed into the crowd (here: own team-mate removed via a chain push), a
// Turnover is caused and the active team's turn ends. The engine never latches
// a turnover on the crowd-push path (proc_block.c push_advance PSH_CROWD), so
// the home turn continues.
BB_TEST(blocking_active_team_chain_pushed_into_crowd_turnover) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 0); // blocker, on the sideline row
    int h2 = fx_lineman(&m, BB_HOME, 1, 12, 0); // team-mate, will be chained out
    fx_lineman(&m, BB_AWAY, 0, 11, 0);          // target
    fx_lineman(&m, BB_AWAY, 1, 12, 1);
    fx_lineman(&m, BB_AWAY, 2, 13, 0);
    fx_lineman(&m, BB_AWAY, 3, 13, 1);

    uint8_t script[] = {3, /*H2 crowd injury*/ 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 3);
    start_block(&m, &rng, h1, 11, 0);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    // Candidates: (12,-1) crowd, (12,0) H2 chain, (12,1) chain.
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 2, 12, 0));
    // Chain for H2: (13,-1) crowd, (13,0)/(13,1) occupied. Push own player out.
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 1, 13, 0));
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    BB_CHECK_EQ(m.players[h2].location, BB_LOC_RESERVES); // crowd injury: stun
    BB_CHECK_EQ(m.players[0 + 16].x, 12);                 // target chained on
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.decision_team, BB_AWAY); // rulebook: turnover ends home turn
}

// ENGINE-DIVERGENCE: GB#PUSHED PLAYERS — a player pushed onto the ball makes
// it bounce automatically (no Turnover). The engine relocates the pushed
// player but never bounces the ball (proc_block.c push_advance phase 2).
BB_TEST(blocking_push_onto_ball_bounces) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_ball_ground(&m, 12, 7);

    uint8_t script[] = {3, /*bounce d8*/ 8};
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7)); // onto the ball
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 13); // rulebook: bounced d8=8 -> (+1,+1) = (13,8)
    BB_CHECK_EQ(m.ball.y, 8);
    BB_CHECK_EQ(m.turnover, 0);
}

// =============================== FOLLOW-UP ===================================

// GB#FOLLOW-UP: after any push the blocker may move into the vacated square as
// a free move (no Rush/Dodge); declining leaves them in place. A following-up
// ball carrier brings the ball along.
BB_TEST(blocking_follow_up_choice) {
    // Accept: attacker (carrying the ball) occupies the vacated square.
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_ball_held(&m, h1);

    uint8_t script1[] = {3};
    bb_rng rng;
    bb_rng_script(&rng, script1, 1);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7));
    BB_CHECK(fx_has_type(&m, BB_A_FOLLOW_UP));
    BB_CHECK_EQ(m.decision_team, BB_HOME);
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 1, 0, 0));
    BB_CHECK_EQ(m.players[h1].x, 11);
    BB_CHECK_EQ(m.players[h1].y, 7);
    BB_CHECK_EQ(m.ball.x, 11); // ball moved with the carrier
    BB_CHECK_EQ(m.players[a1].x, 12);
    BB_CHECK(!bb_rng_error(&rng));

    // Decline: attacker stays put.
    fx_match_midturn(&m, BB_HOME, 0);
    h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);

    uint8_t script2[] = {3};
    bb_rng_script(&rng, script2, 1);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7));
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    BB_CHECK_EQ(m.players[h1].x, 10);
    BB_CHECK_EQ(m.players[h1].y, 7);
}

// GB#FOLLOW-UP: the follow-up decision must be made BEFORE any further dice
// are rolled, e.g. the Armour Roll for a player Knocked Down by POW.
BB_TEST(blocking_follow_up_decided_before_armour) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);

    uint8_t script[] = {6, /*armour after follow-up*/ 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 3);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0)); // POW
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7));
    BB_CHECK(fx_has_type(&m, BB_A_FOLLOW_UP));
    BB_CHECK_EQ(rng.script_pos, 1); // only the block die so far: no armour yet
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    BB_CHECK_EQ(rng.script_pos, 3); // armour rolled after the decision
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_PRONE);
    BB_CHECK(!bb_rng_error(&rng));
}

// GB#SCORING A TOUCHDOWN + GB#SCORING DURING YOUR OPPONENT'S TURN: a carrier
// pushed (still Standing) into the End Zone they attack scores immediately,
// even in the opponent's turn; the scorer's team kicks the next drive.
BB_TEST(blocking_push_carrier_into_endzone_scores) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 2, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 1, 7); // away scores at x == 0
    fx_ball_held(&m, a1);

    uint8_t script[] = {3};
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    start_block(&m, &rng, h1, 1, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 0, 7));
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    BB_CHECK_EQ(m.score[BB_AWAY], 1);
    BB_CHECK_EQ(m.score[BB_HOME], 0);
    BB_CHECK_EQ(m.kicking_team, BB_AWAY); // the scorer kicks the next drive
    BB_CHECK(!bb_rng_error(&rng));
}

// ================================= BLITZ =====================================

// GB#BLITZ ACTIONS!: a Blitz combines a Move and a Block; only ONE Blitz per
// team per turn; the block itself costs one point of Move Allowance; the
// player may move both before and after the block.
BB_TEST(blocking_blitz_block_costs_ma_and_once_per_turn) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 5, 7); // MA6
    int h2 = fx_lineman(&m, BB_HOME, 1, 5, 5);
    fx_lineman(&m, BB_AWAY, 0, 8, 7);

    uint8_t script[] = {3};
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    apply_ok(&m, &rng, mk(BB_A_ACTIVATE, h1, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_STEP, 0, 6, 7));
    apply_ok(&m, &rng, mk(BB_A_STEP, 0, 7, 7));
    BB_CHECK_EQ(m.players[h1].moved, 2);
    apply_ok(&m, &rng, mk(BB_A_BLOCK_TARGET, 0, 8, 7));
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 9, 7));
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    BB_CHECK_EQ(m.players[h1].moved, 3);      // the block cost 1 MA
    BB_CHECK(fx_has_type(&m, BB_A_STEP));     // may keep moving after the block
    BB_CHECK_EQ(m.blitz_used, 1);
    apply_ok(&m, &rng, mk(BB_A_STEP, 0, 6, 7));
    BB_CHECK_EQ(m.players[h1].moved, 4);
    apply_ok(&m, &rng, mk(BB_A_END_ACTIVATION, 0, 0, 0));
    // Second player this turn: Blitz may no longer be declared.
    apply_ok(&m, &rng, mk(BB_A_ACTIVATE, h2, 0, 0));
    BB_CHECK_EQ(fx_find(&m, mk(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0)), -1);
    BB_CHECK(fx_find(&m, mk(BB_A_DECLARE, BB_ACT_MOVE, 0, 0)) >= 0);
    BB_CHECK(!bb_rng_error(&rng));
}

// ENGINE-DIVERGENCE: GB#BLITZ ACTIONS! — a blitzer who has used all Move
// Allowance may attempt to RUSH to gain the point needed for the block (the
// rulebook example does exactly this). The engine only offers the blitz block
// while movement_left > 0 (proc_move.c move_legal), never via a Rush.
BB_TEST(blocking_blitz_may_rush_for_the_block) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_player(&m, BB_HOME, 0, 6, 7, 1, 3, 3, 4, 9); // MA1
    fx_lineman(&m, BB_AWAY, 0, 8, 7);

    uint8_t script[] = {2, 3}; // would-be rush 2+, then the block die
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    apply_ok(&m, &rng, mk(BB_A_ACTIVATE, h1, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_STEP, 0, 7, 7)); // MA exhausted, now adjacent
    // Rulebook: the block must still be offered (performing it forces a Rush).
    BB_CHECK(fx_has_type(&m, BB_A_BLOCK_TARGET));
}

// ================================ FRENZY =====================================

// SK#FRENZY (review M6): when the target of a Block Action is Pushed Back the
// blocker must Follow-up if able; if the target is then still Standing, the
// blocker MUST perform a second Block Action against the same player (again
// following up on a push). There is never a third block.
BB_TEST(blocking_frenzy_second_block_after_push) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, h1, BB_SK_FRENZY);

    uint8_t script[] = {3, 3}; // one push die per block, nothing else
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7));
    // Frenzy: no follow-up decision (forced), and the second block's dice
    // pool was rolled immediately — the next decision is a die choice.
    BB_CHECK(!fx_has_type(&m, BB_A_FOLLOW_UP));
    BB_CHECK_EQ(m.players[h1].x, 11); // followed up automatically
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 1);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 13, 7));
    // Second forced follow-up — and NO third block.
    BB_CHECK(!fx_has_type(&m, BB_A_CHOOSE_DIE));
    BB_CHECK(fx_has_type(&m, BB_A_END_ACTIVATION));
    BB_CHECK_EQ(m.players[h1].x, 12);
    BB_CHECK_EQ(m.players[a1].x, 13);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK(!bb_rng_error(&rng));
}

// SK#FRENZY during a Blitz: performing the second Block Action also costs a
// square of movement (charged like the first block's square).
BB_TEST(blocking_frenzy_blitz_second_block_costs_movement) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 9, 7); // MA6
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, h1, BB_SK_FRENZY);

    uint8_t script[] = {3, /*2nd block POW*/ 6, /*armour holds*/ 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 4);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    apply_ok(&m, &rng, mk(BB_A_ACTIVATE, h1, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_STEP, 0, 10, 7));         // moved 1
    apply_ok(&m, &rng, mk(BB_A_BLOCK_TARGET, 0, 11, 7)); // moved 2
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));    // push
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7));  // forced follow-up
    // The second block was rolled and charged one square of movement.
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 1);
    BB_CHECK_EQ(m.players[h1].moved, 3);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0)); // POW
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 13, 7));
    BB_CHECK_EQ(m.players[h1].x, 12); // second forced follow-up
    BB_CHECK_EQ(m.players[a1].x, 13);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_PRONE); // POW knocked down
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK(fx_has_type(&m, BB_A_STEP)); // blitz continues (moved 3 of 6)
    BB_CHECK(!bb_rng_error(&rng));
}

// SK#FRENZY during a Blitz with no movement left: the player MUST Rush for
// the second block. Passing the Rush performs the block.
BB_TEST(blocking_frenzy_blitz_second_block_rush_pass) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_player(&m, BB_HOME, 0, 10, 7, 1, 3, 3, 4, 9); // MA1
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, h1, BB_SK_FRENZY);

    uint8_t script[] = {3, /*rush 2+*/ 2, /*2nd block die*/ 3};
    bb_rng rng;
    bb_rng_script(&rng, script, 3);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    apply_ok(&m, &rng, mk(BB_A_ACTIVATE, h1, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_BLOCK_TARGET, 0, 11, 7)); // moved 1 = MA
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));    // push
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7));  // forced follow-up
    // Out of MA: the Rush was rolled (and passed) for the second block.
    BB_CHECK_EQ(m.players[h1].rushes, 1);
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 1);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 13, 7));
    BB_CHECK_EQ(m.players[h1].x, 12);
    BB_CHECK_EQ(m.players[a1].x, 13);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK(!bb_rng_error(&rng));
}

// SK#FRENZY + RR#THE TURNOVER: failing the forced Rush for the second block
// knocks the blocker down in place — no second block, Turnover.
BB_TEST(blocking_frenzy_blitz_second_block_rush_fail) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_player(&m, BB_HOME, 0, 10, 7, 1, 3, 3, 4, 9); // MA1
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, h1, BB_SK_FRENZY);

    uint8_t script[] = {3, /*rush fails*/ 1, /*blocker armour holds*/ 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script, 4);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    apply_ok(&m, &rng, mk(BB_A_ACTIVATE, h1, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_BLOCK_TARGET, 0, 11, 7));
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));   // push
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7)); // follow-up, rush fails
    BB_CHECK_EQ(m.players[h1].stance, BB_STANCE_PRONE); // down in place
    BB_CHECK_EQ(m.players[h1].x, 11);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_STANDING); // never re-blocked
    BB_CHECK_EQ(m.players[a1].x, 12);
    BB_CHECK_EQ(m.active_team, BB_AWAY); // turnover ended the home turn
    BB_CHECK(!bb_rng_error(&rng));
}

// SK#FRENZY during a Blitz: "If this player cannot Rush then they cannot
// perform the second Block Action" — all Rushes already used: no second
// block, the activation simply continues.
BB_TEST(blocking_frenzy_blitz_second_block_cannot_rush) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_player(&m, BB_HOME, 0, 8, 7, 1, 3, 3, 4, 9); // MA1
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, h1, BB_SK_FRENZY);

    uint8_t script[] = {/*rush step*/ 2, /*rush for block*/ 2, /*die*/ 3};
    bb_rng rng;
    bb_rng_script(&rng, script, 3);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    apply_ok(&m, &rng, mk(BB_A_ACTIVATE, h1, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_STEP, 0, 9, 7));          // MA spent
    apply_ok(&m, &rng, mk(BB_A_STEP, 0, 10, 7));         // Rush #1
    apply_ok(&m, &rng, mk(BB_A_BLOCK_TARGET, 0, 11, 7)); // Rush #2 (for block)
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));    // push
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7));  // forced follow-up
    // Both Rushes used: the second block cannot be performed.
    BB_CHECK_EQ(m.players[h1].rushes, 2);
    BB_CHECK(!fx_has_type(&m, BB_A_CHOOSE_DIE));
    BB_CHECK(fx_has_type(&m, BB_A_END_ACTIVATION));
    BB_CHECK_EQ(m.players[h1].x, 11);
    BB_CHECK_EQ(m.players[a1].x, 12);
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK(!bb_rng_error(&rng));
}

// ============================ TEAM RE-ROLLS ==================================

// RR#TEAM RE-ROLLS: a team re-roll applied to a dice pool re-rolls ALL dice in
// the pool, only during the team's own turn; declining keeps the rolled pool;
// a die may never be re-rolled twice.
BB_TEST(blocking_team_reroll_rerolls_whole_pool) {
    // Use the re-roll: both block dice are replaced.
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 1);
    int h1 = fx_player(&m, BB_HOME, 0, 10, 7, 6, 4, 3, 4, 9);
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);

    uint8_t script1[] = {1, 1, /*rerolled pool*/ 3, 6, /*armour*/ 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script1, 6);
    start_block(&m, &rng, h1, 11, 7);
    BB_CHECK(fx_has_type(&m, BB_A_USE_REROLL));
    BB_CHECK(fx_has_type(&m, BB_A_DECLINE_REROLL));
    BB_CHECK_EQ(m.decision_team, BB_HOME);
    apply_ok(&m, &rng, mk(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0));
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 2);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 1, 0, 0)); // POW from the new pool
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7));
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    BB_CHECK_EQ(m.players[a1].stance, BB_STANCE_PRONE); // proves pool changed
    BB_CHECK_EQ(m.players[h1].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.rerolls[BB_HOME], 0);
    BB_CHECK(!bb_rng_error(&rng));

    // Decline: the original pool stands (both skulls -> attacker down).
    fx_match_midturn(&m, BB_HOME, 1);
    h1 = fx_player(&m, BB_HOME, 0, 10, 7, 6, 4, 3, 4, 9);
    a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);

    uint8_t script2[] = {1, 1, /*attacker armour*/ 2, 2};
    bb_rng_script(&rng, script2, 4);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_DECLINE_REROLL, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    BB_CHECK_EQ(m.players[h1].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.rerolls[BB_HOME], 1); // not spent
    BB_CHECK(!bb_rng_error(&rng));

    // No re-rolls left: the window is not offered at all.
    fx_match_midturn(&m, BB_HOME, 0);
    h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);

    uint8_t script3[] = {3};
    bb_rng_script(&rng, script3, 1);
    start_block(&m, &rng, h1, 11, 7);
    BB_CHECK(!fx_has_type(&m, BB_A_USE_REROLL));
    BB_CHECK(fx_has_type(&m, BB_A_CHOOSE_DIE));
}

// ENGINE-DIVERGENCE: RR#TEAM RE-ROLLS (BB2025) — a coach may use as many team
// re-rolls as they want during their turn (the BB2020 once-per-turn cap is
// gone; only "never re-roll a re-roll" remains). The engine still gates with
// reroll_used_this_turn (proc_block.c block_advance / proc_test.c
// team_reroll_available), so a second block in the same turn gets no window.
BB_TEST(blocking_second_team_reroll_in_same_turn_allowed) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 2);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int h2 = fx_lineman(&m, BB_HOME, 1, 10, 9);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_lineman(&m, BB_AWAY, 1, 11, 9);

    uint8_t script[] = {1, /*reroll*/ 3, /*second block die*/ 3};
    bb_rng rng;
    bb_rng_script(&rng, script, 3);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0)); // 1st re-roll
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_PUSH_SQUARE, 0, 12, 7));
    apply_ok(&m, &rng, mk(BB_A_FOLLOW_UP, 0, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_END_ACTIVATION, 0, 0, 0));
    // Second block this turn; one team re-roll still in stock.
    apply_ok(&m, &rng, mk(BB_A_ACTIVATE, h2, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_DECLARE, BB_ACT_BLOCK, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_BLOCK_TARGET, 0, 11, 9));
    BB_CHECK_EQ(m.rerolls[BB_HOME], 1);
    BB_CHECK(fx_has_type(&m, BB_A_USE_REROLL)); // rulebook: offered again
}

// SK#LONER (X+): to use a team re-roll the player rolls a D6; below X the
// re-roll is lost with no effect, at or above X it works normally.
BB_TEST(blocking_loner_gates_team_reroll) {
    // Gate fails (3 < 4): pool unchanged, re-roll still spent.
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 1);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, h1, BB_SK_LONER);

    uint8_t script1[] = {1, /*loner gate*/ 3, /*attacker armour*/ 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, script1, 4);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0));
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 1);
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0)); // still the skull
    BB_CHECK_EQ(m.players[h1].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.rerolls[BB_HOME], 0); // lost as if used
    BB_CHECK(!bb_rng_error(&rng));

    // Gate passes (4 >= 4): the pool is re-rolled.
    fx_match_midturn(&m, BB_HOME, 1);
    h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);
    fx_give_skill(&m, h1, BB_SK_LONER);

    uint8_t script2[] = {1, /*loner gate*/ 4, /*new pool*/ 3};
    bb_rng_script(&rng, script2, 3);
    start_block(&m, &rng, h1, 11, 7);
    apply_ok(&m, &rng, mk(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0));
    apply_ok(&m, &rng, mk(BB_A_CHOOSE_DIE, 0, 0, 0));
    BB_CHECK(fx_has_type(&m, BB_A_PUSH_SQUARE)); // skull became a push
    BB_CHECK_EQ(m.rerolls[BB_HOME], 0);
    BB_CHECK(!bb_rng_error(&rng));
}

// SK#DEFENSIVE: "During your opponent's Turns, opposition players Marked by
// this player cannot use the Guard or Put the Boot In Skills." The owner's
// "opponent's Turn" is when the GUARD player's team is active — an OFFENSIVE
// Guard assist by a player the Defensive owner Marks is cancelled. (Item 11
// regression: the inverted turn check granted the assist and rolled 3 dice
// where FFB rolled 2.)
BB_TEST(blocking_defensive_cancels_offensive_guard_assist) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);  // attacker ST3
    int h2 = fx_lineman(&m, BB_HOME, 1, 11, 8);  // Guard assister
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);  // block target ST3
    int a2 = fx_lineman(&m, BB_AWAY, 1, 12, 8);  // marks h2, has Defensive
    fx_give_skill(&m, h2, BB_SK_GUARD);
    fx_give_skill(&m, a2, BB_SK_DEFENSIVE);
    (void)a1;
    uint8_t script[] = {3}; // exactly ONE block die may be rolled
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    start_block(&m, &rng, h1, 11, 7);
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 1); // 3v3: assist cancelled
    BB_CHECK(!bb_rng_error(&rng));
}

// ... and the cancel does NOT apply on the Defensive owner's own turn: a
// DEFENSIVE Guard assist (inactive team) goes through even when the owner
// marks the assister.
BB_TEST(blocking_defensive_no_cancel_on_own_turn_guard_assist) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int h1 = fx_lineman(&m, BB_HOME, 0, 10, 7);  // attacker ST3 (active)
    int h2 = fx_lineman(&m, BB_HOME, 1, 9, 8);   // has Defensive, marks a2
    int a1 = fx_lineman(&m, BB_AWAY, 0, 11, 7);  // block target ST3
    int a2 = fx_lineman(&m, BB_AWAY, 1, 10, 8);  // Guard: defensive assist
    fx_give_skill(&m, a2, BB_SK_GUARD);
    fx_give_skill(&m, h2, BB_SK_DEFENSIVE);
    (void)a1;
    uint8_t script[] = {3, 3}; // defender stronger: TWO dice
    bb_rng rng;
    bb_rng_script(&rng, script, 2);
    start_block(&m, &rng, h1, 11, 7);
    // 3 vs 3+1: two dice, defender chooses.
    BB_CHECK_EQ(count_type(&m, BB_A_CHOOSE_DIE), 2);
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
    BB_CHECK(!bb_rng_error(&rng));
}
