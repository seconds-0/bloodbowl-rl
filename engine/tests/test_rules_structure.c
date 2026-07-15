// test_rules_structure.c — RULEBOOK tests for GAME STRUCTURE (BB2025).
//
// Every test encodes what the rulebook mirror says, with the source sentence
// paraphrased in a comment above it. Mirror root:
//   docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/
// Abbreviations used in citations below:
//   GAME = core_rules/the_game_of_blood_bowl/index.html
//   RR   = core_rules/rules_and_regulations/index.html
//   FAQ  = core_rules/latest_faq/index.html (May 2026; current law)
//
// Tests whose body starts with "// ENGINE-DIVERGENCE:" assert the RULEBOOK
// behaviour and are expected to FAIL against the current engine; each is
// reported in the structured output of the test-writing task.
#include "bb/bb_match.h"
#include "bb/bb_proc.h"
#include "bb/bb_reachability.h"
#include "bb/gen_teams.h"
#include "bb_fixtures.h"
#include "bb_test.h"
#include <string.h>

// ---------------------------------------------------------------------------
// Local fixtures
// ---------------------------------------------------------------------------

// Blank match: empty pitch, all roster slots ABSENT, no procedures stacked.
static void stx_base(bb_match* m) {
    memset(m, 0, sizeof(*m));
    m->team_id[0] = BB_TEAM_HUMAN;
    m->team_id[1] = BB_TEAM_ORC;
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        m->players[s].location = BB_LOC_ABSENT;
    }
    m->half = 1;
    m->weather = BB_WEATHER_PERFECT;
    m->ball.state = BB_BALL_OFF_PITCH;
    m->ball.carrier = BB_NO_PLAYER;
    m->status = BB_STATUS_RUNNING;
}

// A lineman (6/3/3+/4+/9+) in the RESERVES box. Returns the slot.
static int stx_reserve(bb_match* m, int team, int idx) {
    int slot = team * BB_TEAM_SLOTS + idx;
    bb_player* p = &m->players[slot];
    memset(p, 0, sizeof(*p));
    p->ma = 6; p->st = 3; p->ag = 3; p->pa = 4; p->av = 9;
    p->stance = BB_STANCE_STANDING;
    p->location = BB_LOC_RESERVES;
    return slot;
}

// Match paused just before the start-of-drive SETUP (MATCH phase 1).
static void stx_setup_fixture(bb_match* m, int kicking, int avail_home, int avail_away) {
    stx_base(m);
    for (int i = 0; i < avail_home; i++) stx_reserve(m, BB_HOME, i);
    for (int i = 0; i < avail_away; i++) stx_reserve(m, BB_AWAY, i);
    m->kicking_team = (uint8_t)kicking;
    bb_push(m, BB_PROC_MATCH, 0, 0, 0, 0);
    bb_top(m)->phase = 1; // next advance pushes SETUP
}

// Match paused just before THE KICK-OFF (MATCH phase 2): teams are assumed
// already set up by the test (players placed directly on the grid).
static void stx_kickoff_fixture(bb_match* m, int kicking) {
    stx_base(m);
    m->kicking_team = (uint8_t)kicking;
    bb_push(m, BB_PROC_MATCH, 0, 0, 0, 0);
    bb_top(m)->phase = 2; // next advance pushes KICKOFF
}

static bb_action stx_act(int type, int arg, int x, int y) {
    bb_action a = {(uint8_t)type, (uint8_t)arg, (uint8_t)x, (uint8_t)y};
    return a;
}

// Count legal actions of a given type.
static int stx_count_type(const bb_match* m, int type) {
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions((bb_match*)m, legal);
    int c = 0;
    for (int i = 0; i < n; i++) {
        if (legal[i].type == type) c++;
    }
    return c;
}

// Is there any legal action of `type` with this `arg`?
static bool stx_has_type_arg(const bb_match* m, int type, int arg) {
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions((bb_match*)m, legal);
    for (int i = 0; i < n; i++) {
        if (legal[i].type == type && legal[i].arg == arg) return true;
    }
    return false;
}

static int stx_top_proc(const bb_match* m) {
    return m->stack_top ? m->stack[m->stack_top - 1].proc : -1;
}

// Activate `slot` and declare `kind` (the fixture must be at the TEAM_TURN
// decision of the slot's team).
static bb_status stx_activate(bb_match* m, int slot, int kind, bb_rng* rng) {
    bb_status st = fx_apply(m, stx_act(BB_A_ACTIVATE, slot, 0, 0), rng);
    if (st != BB_STATUS_DECISION) return st;
    return fx_apply(m, stx_act(BB_A_DECLARE, kind, 0, 0), rng);
}

// ===========================================================================
// SETUP — GAME "SET-UP":
//   "each team must select 11 players to take part in the Drive. If a team
//    has less than 11 players ... they must set up as many as they can."
//   "Players must be deployed in their own half, and not beyond the Line of
//    Scrimmage into their opponent's half."
//   "At least three players from each team must be deployed in the Centre
//    Field, directly adjacent to the Line of Scrimmage."
//   "No more than two players from each team may be deployed within each
//    Wide Zone."
//   "Should a team only be able to field three or fewer players, then they
//    must be deployed in the Centre Field directly adjacent to the Line of
//    Scrimmage."
//   "The kicking team must set up first followed by the receiving team."
// ===========================================================================

// GAME SET-UP: "The kicking team must set up first followed by the receiving
// team."
BB_TEST(struct_setup_kicking_team_sets_up_first) {
    bb_match m;
    stx_setup_fixture(&m, BB_AWAY, 11, 11);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_AWAY); // kicking coach first
    // Away (kicking) sets up a legal formation: 3 on the LoS centre (x=13),
    // the rest behind in the centre field.
    int base = BB_AWAY * BB_TEAM_SLOTS;
    st = fx_apply(&m, stx_act(BB_A_SETUP_PLACE, base + 0, 13, 5), &rng);
    st = fx_apply(&m, stx_act(BB_A_SETUP_PLACE, base + 1, 13, 6), &rng);
    st = fx_apply(&m, stx_act(BB_A_SETUP_PLACE, base + 2, 13, 7), &rng);
    for (int i = 3; i < 10; i++) {
        st = fx_apply(&m, stx_act(BB_A_SETUP_PLACE, base + i, 14, 4 + (i - 3)), &rng);
    }
    st = fx_apply(&m, stx_act(BB_A_SETUP_PLACE, base + 10, 15, 7), &rng);
    BB_CHECK(fx_find(&m, stx_act(BB_A_SETUP_DONE, 0, 0, 0)) >= 0);
    st = fx_apply(&m, stx_act(BB_A_SETUP_DONE, 0, 0, 0), &rng);
    // Now the receiving (home) coach must be on decision.
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_HOME);
}

// GAME SET-UP: "At least three players from each team must be deployed in the
// Centre Field, directly adjacent to the Line of Scrimmage."
BB_TEST(struct_setup_done_requires_three_on_los_centre) {
    bb_match m;
    stx_setup_fixture(&m, BB_HOME, 11, 0);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    // 11 placed but only TWO on the LoS centre (x=12, y 4..10).
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 0, 12, 5), &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 1, 12, 6), &rng);
    for (int i = 2; i < 9; i++) {
        fx_apply(&m, stx_act(BB_A_SETUP_PLACE, i, 11, 4 + (i - 2)), &rng);
    }
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 9, 10, 4), &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 10, 10, 5), &rng);
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_SETUP_DONE, 0, 0, 0)), -1);
    // Move one of the back players onto the LoS centre: now legal.
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 10, 12, 7), &rng);
    BB_CHECK(fx_find(&m, stx_act(BB_A_SETUP_DONE, 0, 0, 0)) >= 0);
}

// GAME SET-UP: "No more than two players from each team may be deployed
// within each Wide Zone." (Wide zones: y 0..3 and y 11..14.)
BB_TEST(struct_setup_max_two_per_wide_zone) {
    bb_match m;
    stx_setup_fixture(&m, BB_HOME, 11, 0);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 0, 12, 5), &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 1, 12, 6), &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 2, 12, 7), &rng);
    for (int i = 3; i < 8; i++) {
        fx_apply(&m, stx_act(BB_A_SETUP_PLACE, i, 11, 4 + (i - 3)), &rng);
    }
    // THREE players in the top wide zone -> illegal formation.
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 8, 11, 1), &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 9, 11, 2), &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 10, 11, 3), &rng);
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_SETUP_DONE, 0, 0, 0)), -1);
    // Pull one back into the centre field: two per wide zone is allowed.
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 10, 10, 6), &rng);
    BB_CHECK(fx_find(&m, stx_act(BB_A_SETUP_DONE, 0, 0, 0)) >= 0);
}

// GAME SET-UP: "each team must select 11 players to take part in the Drive"
// — never more; with 11 on the pitch no further reserve may be placed.
BB_TEST(struct_setup_max_eleven_no_twelfth_placement) {
    bb_match m;
    stx_setup_fixture(&m, BB_HOME, 13, 0); // 13 available, only 11 may deploy
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 0, 12, 4), &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 1, 12, 5), &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 2, 12, 6), &rng);
    for (int i = 3; i < 10; i++) {
        fx_apply(&m, stx_act(BB_A_SETUP_PLACE, i, 11, 4 + (i - 3)), &rng);
    }
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 10, 10, 7), &rng);
    // 11 on the pitch: a 12th (reserve slot 11) must have no placement action.
    BB_CHECK(!stx_has_type_arg(&m, BB_A_SETUP_PLACE, 11));
    BB_CHECK(!stx_has_type_arg(&m, BB_A_SETUP_PLACE, 12));
    // ... and the legal formation may be confirmed with exactly 11.
    BB_CHECK(fx_find(&m, stx_act(BB_A_SETUP_DONE, 0, 0, 0)) >= 0);
}

// GAME SET-UP: "Players must be deployed in their own half, and not beyond
// the Line of Scrimmage into their opponent's half." (Home half: x <= 12.)
BB_TEST(struct_setup_own_half_only) {
    bb_match m;
    stx_setup_fixture(&m, BB_HOME, 11, 0);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(&m, legal);
    bool any_own_half = false, any_opp_half = false;
    for (int i = 0; i < n; i++) {
        if (legal[i].type != BB_A_SETUP_PLACE) continue;
        if (legal[i].x <= 12) any_own_half = true;
        if (legal[i].x > 12) any_opp_half = true;
    }
    BB_CHECK(any_own_half);
    BB_CHECK(!any_opp_half);
}

// GAME SET-UP: "If a team has less than 11 players ... they must set up as
// many as they can." (7 available: DONE only once all 7 are deployed.)
BB_TEST(struct_setup_short_squad_fields_all_available) {
    bb_match m;
    stx_setup_fixture(&m, BB_HOME, 7, 0);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 0, 12, 5), &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 1, 12, 6), &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 2, 12, 7), &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 3, 11, 5), &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 4, 11, 6), &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 5, 11, 7), &rng);
    // Six of seven placed: confirming the formation must be illegal.
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_SETUP_DONE, 0, 0, 0)), -1);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 6, 10, 7), &rng);
    BB_CHECK(fx_find(&m, stx_act(BB_A_SETUP_DONE, 0, 0, 0)) >= 0);
}

// GAME SET-UP: "Should a team only be able to field three or fewer players,
// then they must be deployed in the Centre Field directly adjacent to the
// Line of Scrimmage."
BB_TEST(struct_setup_three_or_fewer_all_on_los) {
    bb_match m;
    stx_setup_fixture(&m, BB_HOME, 2, 0);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 0, 12, 5), &rng);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 1, 11, 5), &rng); // NOT on the LoS
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_SETUP_DONE, 0, 0, 0)), -1);
    fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 1, 12, 6), &rng); // both on LoS
    BB_CHECK(fx_find(&m, stx_act(BB_A_SETUP_DONE, 0, 0, 0)) >= 0);
}

// ===========================================================================
// PRE-GAME — GAME "DETERMINE KICKING TEAM": "The Coach who rolls highest
// decides which team is kicking and which team is receiving."
// ===========================================================================

BB_TEST(struct_pregame_toss_winner_chooses_kick_or_receive) {
    bb_match m;
    bb_match_init(&m, BB_TEAM_HUMAN, BB_TEAM_ORC);
    bb_rng rng;
    // weather 2d6 = 4+3 = 7 (Perfect Conditions), toss d2 = 2 (away wins).
    const uint8_t dice[] = {4, 3, 2};
    bb_rng_script(&rng, dice, 3);
    bb_status st = bb_advance(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.weather, BB_WEATHER_PERFECT);
    BB_CHECK_EQ(m.decision_team, BB_AWAY); // toss winner decides
    BB_CHECK_EQ(stx_count_type(&m, BB_A_CHOOSE_OPTION), 2); // kick / receive
    st = fx_apply(&m, stx_act(BB_A_CHOOSE_OPTION, 1, 0, 0), &rng); // receive
    BB_CHECK_EQ(m.kicking_team, BB_HOME); // so home kicks
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_HOME); // kicking team sets up first
}

// ===========================================================================
// THE KICK-OFF — GAME "PLACE THE KICK" / "THE KICK DEVIATES" /
// "WHAT GOES UP..." / "TOUCHBACKS"
// ===========================================================================

// GAME PLACE THE KICK: "The Coach of the kicking team places the ball in any
// square in the opponent's half." (Home kicks -> away half is x 13..25.)
BB_TEST(struct_kick_target_only_receiving_half) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    fx_lineman(&m, 1, 0, 20, 7);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_HOME); // kicking coach places the kick
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(&m, legal);
    int targets = 0;
    bool any_kicking_half = false;
    for (int i = 0; i < n; i++) {
        if (legal[i].type != BB_A_KICK_TARGET) continue;
        targets++;
        if (legal[i].x < 13) any_kicking_half = true;
    }
    BB_CHECK_EQ(targets, 13 * 15); // every square of the receiving half
    BB_CHECK(!any_kicking_half);
}

// RR DEVIATE: "roll a D6 and a D8. The object will move a number of squares
// equal to the roll on the D6 in the direction determined by the D8" + GAME
// WHAT GOES UP...: "If there isn't a player in the square then the ball will
// immediately Bounce from that square." + GAME ROUNDS: "the team that
// received the ball at the start of the half will have the first Turn".
BB_TEST(struct_kick_deviates_then_bounces_then_receiver_plays_first) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    fx_lineman(&m, 0, 0, 5, 5);
    fx_lineman(&m, 1, 0, 20, 10);
    bb_rng rng;
    // d8=2 -> (0,-1); d6=3: target (18,7) deviates to (18,4).
    // kickoff event 2d6 = 1+1 = 2 (Get the Ref — no board effect modelled).
    // Empty landing square -> bounce d8=1 -> (-1,-1) -> (17,3).
    const uint8_t dice[] = {2, 3, 1, 1, 1};
    bb_rng_script(&rng, dice, 5);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 17);
    BB_CHECK_EQ(m.ball.y, 3);
    // The receiving team (away) takes the first turn of the drive.
    BB_CHECK_EQ(m.active_team, BB_AWAY);
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
    BB_CHECK_EQ(m.turn[BB_AWAY], 1);
}

// GAME WHAT GOES UP...: "If there is a player in that square, they may
// immediately try to Catch the ball by making an Agility Test. If the test
// is passed, they will immediately gain possession of the ball."
BB_TEST(struct_kick_landing_on_receiver_is_caught) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    int catcher = fx_lineman(&m, 1, 0, 18, 4);
    fx_lineman(&m, 1, 1, 20, 10);
    bb_rng rng;
    // Deviate (18,7) by d8=2/(0,-1) d6=3 -> (18,4) = catcher's square.
    // Event 1+1; catch AG 3+ unmodified: die 3 passes.
    const uint8_t dice[] = {2, 3, 1, 1, 3};
    bb_rng_script(&rng, dice, 5);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(m.ball.carrier, catcher);
}

// RR "Team Re-rolls": "Team Re-rolls can only be used when the team is
// active" — the kick-off precedes the receiving team's turn 1, so a failed
// kick-off catch must NOT open a team re-roll window even with re-rolls in
// stock (the engine offered one because MATCH sets active_team to the
// receiver before pushing KICKOFF — adversarial review M4). The ball just
// bounces and the drive starts.
BB_TEST(struct_kickoff_catch_no_team_reroll_window) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    fx_lineman(&m, 1, 0, 18, 4); // receiver under the landing square, AG 3+
    fx_lineman(&m, 1, 1, 20, 10);
    m.rerolls[0] = m.rerolls[1] = 3; // re-rolls in stock for both sides
    m.rerolls_start[0] = m.rerolls_start[1] = 3;
    bb_rng rng;
    // Deviate (18,7) by d8=2/(0,-1) d6=3 -> (18,4); event 1+1 (Get the Ref);
    // catch 2 vs 3+ FAILS -> no re-roll window -> bounce d8=5 -> (19,4).
    const uint8_t dice[] = {2, 3, 1, 1, 2, 5};
    bb_rng_script(&rng, dice, 6);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng)); // dice flowed straight through the bounce
    // The next decision is the receiver's first activation, not a re-roll.
    BB_CHECK_EQ(stx_top_proc(&m), BB_PROC_TEAM_TURN);
    BB_CHECK(!fx_has_type(&m, BB_A_USE_REROLL));
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 19);
    BB_CHECK_EQ(m.ball.y, 4);
    BB_CHECK_EQ(m.rerolls[BB_AWAY], 3); // untouched
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
}

// SK "Catch (Active)": the skill re-roll is the player's own and is NOT
// turn-scoped like a Team Re-roll — a failed kick-off catch still offers it
// (and only it: no team re-roll alongside, per M4 above).
BB_TEST(struct_kickoff_catch_skill_reroll_still_offered) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    int catcher = fx_lineman(&m, 1, 0, 18, 4);
    fx_give_skill(&m, catcher, BB_SK_CATCH);
    fx_lineman(&m, 1, 1, 20, 10);
    m.rerolls[0] = m.rerolls[1] = 3;
    m.rerolls_start[0] = m.rerolls_start[1] = 3;
    bb_rng rng;
    // Deviate to (18,4); event 1+1; catch 2 fails -> Catch skill window;
    // re-rolled 4 passes.
    const uint8_t dice[] = {2, 3, 1, 1, 2, 4};
    bb_rng_script(&rng, dice, 6);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(fx_find(&m, stx_act(BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_CATCH, 0)) >= 0);
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0)), -1);
    st = fx_apply(&m, stx_act(BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_CATCH, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(m.ball.carrier, catcher);
    BB_CHECK_EQ(m.rerolls[BB_AWAY], 3); // team pool untouched
}

// GAME TOUCHBACKS: "The ball must land safely in the opposition half ... If
// the ball ends up exiting the pitch ... it will result in a Touchback. ...
// the Coach of the receiving team may give the ball to any of their Standing
// players on the pitch."
BB_TEST(struct_kick_touchback_when_ball_exits_pitch) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    int standing = fx_lineman(&m, 1, 0, 20, 7);
    int prone = fx_lineman(&m, 1, 1, 21, 7);
    int no_ball = fx_lineman(&m, 1, 2, 22, 7);
    m.players[prone].stance = BB_STANCE_PRONE;
    fx_give_skill(&m, no_ball, BB_SK_NO_BALL);
    bb_rng rng;
    // Target (13,0); d8=1 -> (-1,-1), d6=2 -> (11,-2): off the pitch.
    const uint8_t dice[] = {1, 2, 1, 1};
    bb_rng_script(&rng, dice, 4);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 13, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_AWAY); // receiving coach decides
    // Only eligible STANDING receivers may be given the ball.
    BB_CHECK(fx_find(&m, stx_act(BB_A_TOUCHBACK, standing, 0, 0)) >= 0);
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_TOUCHBACK, prone, 0, 0)), -1);
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_TOUCHBACK, no_ball, 0, 0)), -1);
    st = fx_apply(&m, stx_act(BB_A_TOUCHBACK, standing, 0, 0), &rng);
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(m.ball.carrier, standing);
}

// GAME TOUCHBACKS: "... or crosses the Line of Scrimmage into the kicking
// team's half ... it will result in a Touchback."
BB_TEST(struct_kick_touchback_when_ball_lands_in_kicking_half) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    int standing = fx_lineman(&m, 1, 0, 20, 7);
    bb_rng rng;
    // Target (13,7); d8=4 -> (-1,0), d6=3 -> (10,7): kicking (home) half.
    const uint8_t dice[] = {4, 3, 1, 1};
    bb_rng_script(&rng, dice, 4);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 13, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
    BB_CHECK(fx_find(&m, stx_act(BB_A_TOUCHBACK, standing, 0, 0)) >= 0);
}

// ENGINE-DIVERGENCE: GAME TOUCHBACKS says the touchback also applies when the
// ball ends up in the kicking half "regardless if this was down to a
// Deviation, Bounce, or another effect". The engine only checks the deviated
// square: a kick that lands in the receiving half and then BOUNCES across the
// LoS is left on the ground in the kicking half instead of being a touchback.
BB_TEST(struct_kick_touchback_after_bounce_across_los) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    fx_lineman(&m, 1, 0, 20, 7);
    bb_rng rng;
    // Target (13,7); d8=2 -> (0,-1), d6=1 -> lands (13,6) (receiving half),
    // event 1+1, then bounce d8=4 -> (-1,0) -> (12,6): the KICKING half.
    const uint8_t dice[] = {2, 1, 1, 1, 4};
    bb_rng_script(&rng, dice, 5);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 13, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    // Rulebook: this is a Touchback — the KICKOFF procedure must still be on
    // the stack awaiting the receiving coach's touchback choice.
    BB_CHECK_EQ(stx_top_proc(&m), BB_PROC_KICKOFF);
    BB_CHECK(fx_has_type(&m, BB_A_TOUCHBACK));
}

// GAME TOUCHBACKS: "If there are no Standing players for
// them to give it to, they may place it on any unoccupied square in their
// half instead."
BB_TEST(struct_kick_touchback_no_standing_receivers_places_ball) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    int prone = fx_lineman(&m, 1, 0, 20, 7);
    m.players[prone].stance = BB_STANCE_PRONE;
    bb_rng rng;
    const uint8_t dice[] = {1, 2, 1, 1}; // same off-pitch deviation as above
    bb_rng_script(&rng, dice, 4);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 13, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(&m, legal);
    // Rulebook: the receiving coach must be able to place the ball on an
    // unoccupied square of their half.
    BB_CHECK(n > 0);
}

// NO BALL players do not become eligible just because they are Standing. If
// every Standing receiver has the trait, Touchback uses square placement.
BB_TEST(struct_kick_touchback_only_no_ball_places_ball) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    int no_ball = fx_lineman(&m, 1, 0, 20, 7);
    fx_give_skill(&m, no_ball, BB_SK_NO_BALL);
    bb_rng rng;
    const uint8_t dice[] = {1, 2, 1, 1};
    bb_rng_script(&rng, dice, 4);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 13, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_TOUCHBACK, no_ball, 0, 0)), -1);
    BB_CHECK(fx_find(&m, stx_act(BB_A_TOUCHBACK, 0xFF, 13, 0)) >= 0);
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_TOUCHBACK, 0xFF, 20, 7)), -1);
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_TOUCHBACK, 0xFF, 12, 7)), -1);

    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(&m, legal);
    BB_CHECK_EQ(n, 13 * BB_PITCH_WID - 1); // receiving half minus No Ball square
    for (int i = 0; i < n; i++) {
        BB_CHECK_EQ(legal[i].type, BB_A_TOUCHBACK);
        BB_CHECK_EQ(legal[i].arg, 0xFF);
        BB_CHECK(legal[i].x >= 13 && legal[i].x < BB_PITCH_LEN);
        BB_CHECK(legal[i].y < BB_PITCH_WID);
        BB_CHECK_EQ(m.grid[legal[i].x][legal[i].y], 0);
    }

    int dice_before = rng.script_pos;
    st = fx_apply(&m, stx_act(BB_A_TOUCHBACK, 0xFF, 13, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(rng.script_pos, dice_before);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.carrier, BB_NO_PLAYER);
    BB_CHECK_EQ(m.ball.x, 13);
    BB_CHECK_EQ(m.ball.y, 0);
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        BB_CHECK_EQ(m.players[s].flags & BB_PF_HAS_BALL, 0);
    }
    BB_CHECK_EQ(m.active_team, BB_AWAY);
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
    BB_CHECK_EQ(stx_top_proc(&m), BB_PROC_TEAM_TURN);
}

// ===========================================================================
// KICK-OFF EVENTS — GAME "KICK-OFF EVENT TABLE"
// ===========================================================================

// GAME KICK-OFF EVENT 3 TIME-OUT!: "If the kicking team's Turn Marker is on
// turn 6, 7 or 8 for the half, move both teams' Turn Marker back one space.
// Otherwise, move both teams' Turn Marker forwards one space."
BB_TEST(struct_kickoff_event_time_out) {
    // Late half: markers move BACK.
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    fx_lineman(&m, 0, 0, 5, 5);
    fx_lineman(&m, 1, 0, 20, 10);
    m.turn[0] = m.turn[1] = 6;
    bb_rng rng;
    // d8=2,d6=3 -> (18,4); event 1+2=3 TIME-OUT; bounce d8=1.
    const uint8_t dice[] = {2, 3, 1, 2, 1};
    bb_rng_script(&rng, dice, 5);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.turn[BB_HOME], 5);       // 6 -> 5
    BB_CHECK_EQ(m.turn[BB_AWAY], 6);       // 6 -> 5, +1 for the new team turn
    // Early half: markers move FORWARD.
    bb_match m2;
    stx_kickoff_fixture(&m2, BB_HOME);
    fx_lineman(&m2, 0, 0, 5, 5);
    fx_lineman(&m2, 1, 0, 20, 10);
    m2.turn[0] = m2.turn[1] = 2;
    bb_rng rng2;
    const uint8_t dice2[] = {2, 3, 1, 2, 1};
    bb_rng_script(&rng2, dice2, 5);
    fx_run(&m2, &rng2);
    st = fx_apply(&m2, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng2);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m2.turn[BB_HOME], 3);      // 2 -> 3
    BB_CHECK_EQ(m2.turn[BB_AWAY], 4);      // 2 -> 3, +1 for the new team turn
}

// GAME KICK-OFF EVENT 7 BRILLIANT COACHING: "Both Coaches roll a D6 and add
// the number of Assistant Coaches ... The Coach with the highest total ...
// immediately gains a free Team Re-roll for the Drive ahead."
BB_TEST(struct_kickoff_event_brilliant_coaching) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    fx_lineman(&m, 0, 0, 5, 5);
    fx_lineman(&m, 1, 0, 20, 10);
    bb_rng rng;
    // d8=2,d6=3; event 3+4=7; home d6=5 vs away d6=2 -> home +1 re-roll;
    // bounce d8=1.
    const uint8_t dice[] = {2, 3, 3, 4, 5, 2, 1};
    bb_rng_script(&rng, dice, 7);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.rerolls[BB_HOME], 1);
    BB_CHECK_EQ(m.rerolls[BB_AWAY], 0);
}

// ENGINE-DIVERGENCE (TODO(phase3) in proc_match.c): GAME KICK-OFF EVENT 5
// HIGH KICK: "One Open player on the receiving team may immediately be placed
// in the square the ball is going to land in." The engine resolves the event
// as a no-op and never offers the receiving coach the placement decision.
BB_TEST(struct_kickoff_event_high_kick_offers_placement) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    fx_lineman(&m, 0, 0, 5, 5);
    int open_recv = fx_lineman(&m, 1, 0, 20, 10);
    (void)open_recv;
    bb_rng rng;
    // d8=2,d6=3 -> ball will land at (18,4); event 2+3=5 HIGH KICK.
    // Per the rulebook the next decision belongs to the RECEIVING coach,
    // with the kick-off still unresolved (ball in the air).
    const uint8_t dice[] = {2, 3, 2, 3, 1};
    bb_rng_script(&rng, dice, 5);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
    BB_CHECK_EQ(stx_top_proc(&m), BB_PROC_KICKOFF); // still inside the kick-off
}

// GAME KICK-OFF EVENT 8 CHANGING WEATHER: "Immediately make a new roll on
// the Weather Table. If the new result is Perfect Conditions, the ball will
// Scatter (3) in the air before it lands."
BB_TEST(struct_kickoff_event_changing_weather_scatters_three) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    fx_lineman(&m, 0, 0, 5, 5);
    fx_lineman(&m, 1, 0, 20, 10);
    bb_rng rng;
    // Target (18,7); d8=2 -> (0,-1), d6=2 -> (18,5). Event 4+4=8.
    // Weather 3+4=7 -> Perfect Conditions -> Scatter (3): d8=5,5,5 -> (21,5).
    // Empty square -> bounce d8=5 -> (22,5).
    const uint8_t dice[] = {2, 2, 4, 4, 3, 4, 5, 5, 5, 5};
    bb_rng_script(&rng, dice, 10);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.weather, BB_WEATHER_PERFECT);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 22);
    BB_CHECK_EQ(m.ball.y, 5);
}

// CHANGING WEATHER gust early stop (FFB StepApplyKickoffResult, validated
// against live FUMBBL dice logs): the Scatter (3) rolls one D8 at a time and
// STOPS the moment the ball leaves the receiving half or the pitch — the
// touchback is then certain and no further scatter dice are rolled.
BB_TEST(struct_kickoff_changing_weather_gust_stops_at_touchback) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    fx_lineman(&m, 0, 0, 5, 5);
    int recv = fx_lineman(&m, 1, 0, 20, 10);
    bb_rng rng;
    // Target (14,7); d8=4 -> (-1,0), d6=1 -> ball at (13,7). Event 4+4=8.
    // Weather 3+4=7 -> Perfect -> gust d8=4 -> (12,7): KICKING half. The
    // gust STOPS after ONE die; touchback decision for the receiving coach.
    const uint8_t dice[] = {4, 1, 4, 4, 3, 4, 4};
    bb_rng_script(&rng, dice, 7);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 14, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_AWAY); // touchback: receiving coach
    BB_CHECK(fx_has_type(&m, BB_A_TOUCHBACK));
    BB_CHECK(!bb_rng_error(&rng)); // exactly ONE gust die was consumed
    st = fx_apply(&m, stx_act(BB_A_TOUCHBACK, recv, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.ball.carrier, recv);
}

// GAME KICK-OFF EVENT 12 PITCH INVASION: "Both Coaches roll a D6 and add
// their Fan Factor. The Coach that rolled lowest, or both Coaches in the
// result of a tie, randomly selects D3 of their players on the pitch. The
// selected players are immediately Placed Prone and become Stunned."
BB_TEST(struct_kickoff_event_pitch_invasion_rolloff) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    for (int i = 0; i < 4; i++) fx_lineman(&m, 0, i, 5, 4 + i);
    for (int i = 0; i < 4; i++) fx_lineman(&m, 1, i, 20, 4 + i);
    bb_rng rng;
    // d8=2,d6=3 -> (18,4); event 6+6=12 PITCH INVASION.
    // Rulebook dice: home d6=6, away d6=1 -> away (lowest) selects d3=2
    // players who become Stunned (each selection consumes a scripted roll
    // over the standing-candidate list — replay-faithful). Bounce d8=1.
    const uint8_t dice[] = {2, 3, 6, 6, 6, 1, 2, 1, 1, 1};
    bb_rng_script(&rng, dice, 10);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    int home_stunned = 0;
    for (int s = 0; s < BB_TEAM_SLOTS; s++) {
        if (m.players[s].location == BB_LOC_ON_PITCH &&
            m.players[s].stance == BB_STANCE_STUNNED) home_stunned++;
    }
    // Home rolled higher: no home player may be stunned by the invasion.
    BB_CHECK_EQ(home_stunned, 0);
}

// PITCH INVASION adds each team's FAN FACTOR to the roll-off: an away fan
// advantage flips the same raw dice — home (6+0=6) now loses to away
// (1+6=7) and must stun D3 of its own players instead.
BB_TEST(struct_kickoff_event_pitch_invasion_fan_factor) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    for (int i = 0; i < 4; i++) fx_lineman(&m, 0, i, 5, 4 + i);
    for (int i = 0; i < 4; i++) fx_lineman(&m, 1, i, 20, 4 + i);
    m.fan_factor[BB_AWAY] = 6;
    bb_rng rng;
    // Same dice as the roll-off test: home d6=6, away d6=1 — but away's +6
    // fans make home the loser; d3=2 home victims (picks 1,1), bounce d8=1.
    const uint8_t dice[] = {2, 3, 6, 6, 6, 1, 2, 1, 1, 1};
    bb_rng_script(&rng, dice, 10);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    int home_stunned = 0, away_stunned = 0;
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        if (m.players[s].location != BB_LOC_ON_PITCH) continue;
        if (m.players[s].stance != BB_STANCE_STUNNED) continue;
        if (s < BB_TEAM_SLOTS) home_stunned++;
        else away_stunned++;
    }
    BB_CHECK_EQ(home_stunned, 2);
    BB_CHECK_EQ(away_stunned, 0);
    BB_CHECK(!bb_rng_error(&rng));
}

// ===========================================================================
// TURNOVERS — RR "THE TURNOVER": "A Turnover will be caused if: ..."
// "When a Turnover occurs, the current player's activation ends and that
//  Coach's turn immediately ends."
// ===========================================================================

// After a turnover the engine unwinds to the next team's turn; these helpers
// assert "the turn ended": the opponent is now the active/deciding team.
static void stx_expect_turn_ended(const bb_match* m, int old_active) {
    BB_CHECK_EQ(m->status, BB_STATUS_DECISION);
    BB_CHECK_EQ(m->active_team, 1 - old_active);
    BB_CHECK_EQ(m->decision_team, 1 - old_active);
}

// RR THE TURNOVER: "A player on the active team Falls Over during their own
// activation." + RR FALLS OVER: "If a player on the active team Falls Over
// then a Turnover is caused" (failed Dodge -> Falls Over, Armour Roll).
BB_TEST(struct_turnover_failed_dodge) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int p = fx_lineman(&m, 0, 0, 10, 7);
    int mate = fx_lineman(&m, 0, 1, 3, 3);
    fx_lineman(&m, 1, 0, 10, 8); // marks p
    fx_lineman(&m, 1, 1, 20, 12);
    bb_rng rng;
    // Dodge (AG 3+, -1 marker on destination -> 4+): die 2 fails.
    // Armour 2d6 = 3+3 = 6 < 9+: holds.
    const uint8_t dice[] = {2, 3, 3};
    bb_rng_script(&rng, dice, 3);
    fx_run(&m, &rng);
    stx_activate(&m, p, BB_ACT_MOVE, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_STEP, 0, 9, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    // Falls Over in the destination square; armour was rolled; turn over.
    BB_CHECK_EQ(m.players[p].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[p].x, 9);
    BB_CHECK_EQ(m.players[p].y, 7);
    BB_CHECK(!(m.players[mate].flags & BB_PF_USED)); // mate never activated
    stx_expect_turn_ended(&m, 0);
}

// RR THE TURNOVER (Falls Over) + GAME RUSHING: "On a 1, the player trips and
// Falls Over in the square they were attempting to Rush into and their
// activation immediately ends."
BB_TEST(struct_turnover_failed_rush) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int p = fx_player(&m, 0, 0, 10, 7, 1, 3, 3, 4, 9); // MA 1
    fx_lineman(&m, 1, 0, 20, 12);
    bb_rng rng;
    // Step 1 free; step 2 is a Rush (2+): die 1 -> Falls Over. Armour 2+2.
    const uint8_t dice[] = {1, 2, 2};
    bb_rng_script(&rng, dice, 3);
    fx_run(&m, &rng);
    stx_activate(&m, p, BB_ACT_MOVE, &rng);
    fx_apply(&m, stx_act(BB_A_STEP, 0, 11, 7), &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_STEP, 0, 12, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[p].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[p].x, 12);
    BB_CHECK_EQ(m.players[p].y, 7);
    stx_expect_turn_ended(&m, 0);
}

// RR THE TURNOVER: "A player on the active team attempts to pick up the ball
// from the ground and fails." + GAME PICKING UP THE BALL: "If the test is
// failed ... a Turnover is caused - the ball will then Bounce from the
// player's square." (No knockdown: the player stays standing.)
BB_TEST(struct_turnover_failed_pickup) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int p = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 1, 0, 20, 12);
    fx_ball_ground(&m, 11, 7);
    bb_rng rng;
    // Pickup (AG 3+, unmarked): die 2 fails. Bounce d8=5 -> (1,0) -> (12,7).
    const uint8_t dice[] = {2, 5};
    bb_rng_script(&rng, dice, 2);
    fx_run(&m, &rng);
    stx_activate(&m, p, BB_ACT_MOVE, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_STEP, 0, 11, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[p].stance, BB_STANCE_STANDING); // no Armour Roll
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 12);
    BB_CHECK_EQ(m.ball.y, 7);
    stx_expect_turn_ended(&m, 0);
}

// RR THE TURNOVER: "A player on the active team is Knocked Down during their
// own team's turn." + GAME PLAYER DOWN: "The player performing the Block
// Action is immediately Knocked Down by the target player."
BB_TEST(struct_turnover_block_attacker_down) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int att = fx_lineman(&m, 0, 0, 10, 7);
    int def = fx_lineman(&m, 1, 0, 11, 7);
    fx_lineman(&m, 0, 1, 3, 3);
    bb_rng rng;
    // Block die 1 = PLAYER DOWN; attacker armour 2+2 holds.
    const uint8_t dice[] = {1, 2, 2};
    bb_rng_script(&rng, dice, 3);
    fx_run(&m, &rng);
    stx_activate(&m, att, BB_ACT_BLOCK, &rng);
    fx_apply(&m, stx_act(BB_A_BLOCK_TARGET, 0, 11, 7), &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_CHOOSE_DIE, 0, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[att].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[def].stance, BB_STANCE_STANDING);
    stx_expect_turn_ended(&m, 0);
}

// GAME BOTH DOWN: "Both the player that performed the Block Action and the
// target player are Knocked Down" — the attacker is on the active team, so a
// Turnover is caused (RR THE TURNOVER).
BB_TEST(struct_turnover_block_both_down) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int att = fx_lineman(&m, 0, 0, 10, 7);
    int def = fx_lineman(&m, 1, 0, 11, 7);
    fx_lineman(&m, 0, 1, 3, 3);
    bb_rng rng;
    // Block die 2 = BOTH DOWN; defender armour 2+2, attacker armour 2+2.
    const uint8_t dice[] = {2, 2, 2, 2, 2};
    bb_rng_script(&rng, dice, 5);
    fx_run(&m, &rng);
    stx_activate(&m, att, BB_ACT_BLOCK, &rng);
    fx_apply(&m, stx_act(BB_A_BLOCK_TARGET, 0, 11, 7), &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_CHOOSE_DIE, 0, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[att].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[def].stance, BB_STANCE_PRONE);
    stx_expect_turn_ended(&m, 0);
}

// RR THE TURNOVER lists only ACTIVE-team players being Knocked Down: knocking
// down an OPPONENT with a POW is not a Turnover — the active team continues.
// GAME POW: "after the Push Back result has been applied, the target player
// is immediately Knocked Down."
BB_TEST(struct_no_turnover_block_pow_defender_down) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int att = fx_lineman(&m, 0, 0, 10, 7);
    int def = fx_lineman(&m, 1, 0, 11, 7);
    int mate = fx_lineman(&m, 0, 1, 3, 3);
    bb_rng rng;
    // Block die 6 = POW; defender armour 2+2 holds.
    const uint8_t dice[] = {6, 2, 2};
    bb_rng_script(&rng, dice, 3);
    fx_run(&m, &rng);
    stx_activate(&m, att, BB_ACT_BLOCK, &rng);
    fx_apply(&m, stx_act(BB_A_BLOCK_TARGET, 0, 11, 7), &rng);
    fx_apply(&m, stx_act(BB_A_CHOOSE_DIE, 0, 0, 0), &rng);
    fx_apply(&m, stx_act(BB_A_PUSH_SQUARE, 0, 12, 7), &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_FOLLOW_UP, 0, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[def].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[def].x, 12);
    BB_CHECK_EQ(m.players[def].y, 7);
    // NOT a turnover: the active team keeps deciding.
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK_EQ(m.active_team, 0);
    BB_CHECK_EQ(m.decision_team, 0);
    fx_apply(&m, stx_act(BB_A_END_ACTIVATION, 0, 0, 0), &rng);
    BB_CHECK_EQ(m.decision_team, 0); // team 0's turn continues
    BB_CHECK(fx_find(&m, stx_act(BB_A_ACTIVATE, mate, 0, 0)) >= 0);
}

// GAME PUSH BACK: "The target player is Pushed Back one square" — nobody is
// Knocked Down, no Turnover (RR THE TURNOVER does not list pushes).
BB_TEST(struct_no_turnover_block_push_back) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int att = fx_lineman(&m, 0, 0, 10, 7);
    int def = fx_lineman(&m, 1, 0, 11, 7);
    fx_lineman(&m, 0, 1, 3, 3);
    bb_rng rng;
    const uint8_t dice[] = {3}; // PUSH BACK
    bb_rng_script(&rng, dice, 1);
    fx_run(&m, &rng);
    stx_activate(&m, att, BB_ACT_BLOCK, &rng);
    fx_apply(&m, stx_act(BB_A_BLOCK_TARGET, 0, 11, 7), &rng);
    fx_apply(&m, stx_act(BB_A_CHOOSE_DIE, 0, 0, 0), &rng);
    fx_apply(&m, stx_act(BB_A_PUSH_SQUARE, 0, 12, 7), &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_FOLLOW_UP, 1, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[def].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[def].x, 12);
    BB_CHECK_EQ(m.players[att].x, 11); // followed up into the vacated square
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK_EQ(m.decision_team, 0);
}

// RR THE TURNOVER: "A player on the active team is Sent-off for committing a
// Foul Action." + GAME BEING SENT-OFF: "if during a Foul Action a natural
// double is rolled for either the Armour Roll or Injury Roll, then the player
// performing the Foul Action is Sent-off ... a Turnover is caused."
BB_TEST(struct_turnover_foul_sent_off) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int fouler = fx_lineman(&m, 0, 0, 10, 7);
    int victim = fx_lineman(&m, 1, 0, 11, 7);
    m.players[victim].stance = BB_STANCE_PRONE;
    fx_lineman(&m, 1, 1, 20, 12);
    bb_rng rng;
    // Foul armour 4+4 = natural double (8 < 9+, armour even holds).
    const uint8_t dice[] = {4, 4};
    bb_rng_script(&rng, dice, 2);
    fx_run(&m, &rng);
    stx_activate(&m, fouler, BB_ACT_FOUL, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_FOUL_TARGET, 0, 11, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    // Argue the Call window (BB2025): the fouling coach accepts the call.
    BB_CHECK_EQ(m.decision_team, 0);
    st = fx_apply(&m, stx_act(BB_A_CHOOSE_OPTION, 0, 0, 0), &rng);
    BB_CHECK_EQ(m.players[fouler].location, BB_LOC_SENT_OFF);
    BB_CHECK_EQ(m.grid[10][7], 0); // removed from the pitch
    stx_expect_turn_ended(&m, 0);
}

// GAME BEING SENT-OFF (inverse): no natural double on the Armour or Injury
// Roll -> the fouler is not Sent-off and no Turnover is caused.
BB_TEST(struct_no_turnover_foul_unspotted) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int fouler = fx_lineman(&m, 0, 0, 10, 7);
    int victim = fx_lineman(&m, 1, 0, 11, 7);
    m.players[victim].stance = BB_STANCE_PRONE;
    int mate = fx_lineman(&m, 0, 1, 3, 3);
    bb_rng rng;
    const uint8_t dice[] = {2, 3}; // armour 5, no double, holds
    bb_rng_script(&rng, dice, 2);
    fx_run(&m, &rng);
    stx_activate(&m, fouler, BB_ACT_FOUL, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_FOUL_TARGET, 0, 11, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[fouler].location, BB_LOC_ON_PITCH);
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK_EQ(m.decision_team, 0); // turn continues
    BB_CHECK(fx_find(&m, stx_act(BB_A_ACTIVATE, mate, 0, 0)) >= 0);
}

// RR THE TURNOVER: "A player on the active team attempts a Pass Action and no
// player on the active team successfully Catches the ball, resulting in the
// ball hitting the ground and Bouncing or coming to a rest on the ground."
BB_TEST(struct_turnover_pass_incomplete) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 0, 1, 3, 3);
    fx_lineman(&m, 1, 0, 20, 12);
    fx_ball_held(&m, thrower);
    bb_rng rng;
    // Quick pass (PA 4+): die 5 accurate; empty target -> bounce d8=5 (1,0).
    const uint8_t dice[] = {5, 5};
    bb_rng_script(&rng, dice, 2);
    fx_run(&m, &rng);
    stx_activate(&m, thrower, BB_ACT_PASS, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_PASS_TARGET, 0, 13, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 14);
    BB_CHECK_EQ(m.ball.y, 7);
    stx_expect_turn_ended(&m, 0);
}

// RR THE TURNOVER (May 2026 errata text): "A player on the inactive team ends
// up in possession of the ball following an attempted Pass Action or Hand-off
// Action, or by successfully Intercepting the ball."
BB_TEST(struct_turnover_pass_caught_by_opponent) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 0, 1, 3, 3);
    int opp = fx_lineman(&m, 1, 0, 13, 7);
    fx_ball_held(&m, thrower);
    bb_rng rng;
    // Accurate quick pass onto the opponent's square; opponent catches (3+).
    const uint8_t dice[] = {5, 5};
    bb_rng_script(&rng, dice, 2);
    fx_run(&m, &rng);
    stx_activate(&m, thrower, BB_ACT_PASS, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_PASS_TARGET, 0, 13, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(m.ball.carrier, opp);
    stx_expect_turn_ended(&m, 0);
}

// Inverse of the pass turnovers: a pass caught by a TEAM-MATE of the active
// team is not in the RR THE TURNOVER list — the turn continues.
BB_TEST(struct_no_turnover_pass_caught_by_teammate) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_lineman(&m, 0, 0, 10, 7);
    int recv = fx_lineman(&m, 0, 1, 13, 7);
    fx_lineman(&m, 1, 0, 20, 12);
    fx_ball_held(&m, thrower);
    bb_rng rng;
    const uint8_t dice[] = {5, 5}; // accurate pass; catch passes
    bb_rng_script(&rng, dice, 2);
    fx_run(&m, &rng);
    stx_activate(&m, thrower, BB_ACT_PASS, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_PASS_TARGET, 0, 13, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.ball.carrier, recv);
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK_EQ(m.active_team, 0);
    BB_CHECK_EQ(m.decision_team, 0);
    BB_CHECK(fx_find(&m, stx_act(BB_A_ACTIVATE, recv, 0, 0)) >= 0);
}

// RR THE TURNOVER: "A player on the active team attempts to Catch the ball
// following a Pass Action or a Hand-off Action and fails, resulting in it
// coming to a rest on the ground."
BB_TEST(struct_turnover_handoff_dropped) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int carrier = fx_lineman(&m, 0, 0, 10, 7);
    int recv = fx_lineman(&m, 0, 1, 11, 7);
    fx_lineman(&m, 1, 0, 20, 12);
    fx_ball_held(&m, carrier);
    bb_rng rng;
    // Hand-off catch (AG 3+): die 2 fails; bounce d8=5 -> (12,7) ground.
    const uint8_t dice[] = {2, 5};
    bb_rng_script(&rng, dice, 2);
    fx_run(&m, &rng);
    stx_activate(&m, carrier, BB_ACT_HANDOFF, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_HANDOFF_TARGET, 0, 11, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[recv].flags & BB_PF_HAS_BALL, 0);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    stx_expect_turn_ended(&m, 0);
}

// RR THE TURNOVER carve-out: "if the ball Bounces from the player that failed
// to Catch the ball directly into a square containing a player from the
// active team who successfully Catches the ball, no Turnover is caused."
BB_TEST(struct_no_turnover_bounce_caught_by_teammate) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_lineman(&m, 0, 0, 10, 7);
    int t1 = fx_lineman(&m, 0, 1, 13, 7);
    int t2 = fx_lineman(&m, 0, 2, 14, 7);
    fx_lineman(&m, 1, 0, 20, 12);
    fx_ball_held(&m, thrower);
    bb_rng rng;
    // Accurate pass (5); t1 drops it (1); bounce d8=5 -> t2's square;
    // t2 catches the bouncing ball (AG 3+, -1 bounce -> 4+): die 6.
    const uint8_t dice[] = {5, 1, 5, 6};
    bb_rng_script(&rng, dice, 4);
    fx_run(&m, &rng);
    stx_activate(&m, thrower, BB_ACT_PASS, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_PASS_TARGET, 0, 13, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.ball.carrier, t2);
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK_EQ(m.decision_team, 0); // no turnover: team 0 keeps playing
    BB_CHECK(fx_find(&m, stx_act(BB_A_ACTIVATE, t1, 0, 0)) >= 0);
}

// RR KNOCKED DOWN: "If a player is Knocked Down during their team's turn,
// then a Turnover is caused" — the INACTIVE team's ball carrier being knocked
// down by a block is NOT a turnover for the active team; the ball bounces.
BB_TEST(struct_no_turnover_inactive_carrier_knocked_down) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int att = fx_lineman(&m, 0, 0, 10, 7);
    int def = fx_lineman(&m, 1, 0, 11, 7);
    fx_lineman(&m, 0, 1, 3, 3);
    fx_ball_held(&m, def); // the OPPONENT carries the ball
    bb_rng rng;
    // POW; armour 2+2 holds; ball bounces d8=3 -> (1,-1) from (12,7) -> (13,6).
    const uint8_t dice[] = {6, 2, 2, 3};
    bb_rng_script(&rng, dice, 4);
    fx_run(&m, &rng);
    stx_activate(&m, att, BB_ACT_BLOCK, &rng);
    fx_apply(&m, stx_act(BB_A_BLOCK_TARGET, 0, 11, 7), &rng);
    fx_apply(&m, stx_act(BB_A_CHOOSE_DIE, 0, 0, 0), &rng);
    fx_apply(&m, stx_act(BB_A_PUSH_SQUARE, 0, 12, 7), &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_FOLLOW_UP, 0, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[def].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(m.ball.x, 13);
    BB_CHECK_EQ(m.ball.y, 6);
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK_EQ(m.decision_team, 0); // active team plays on
}

// ENGINE-DIVERGENCE: RR THE TURNOVER: "A player on the active team that is
// carrying the ball is Placed Prone or forced to move off the pitch for any
// reason." + GAME PUSHED INTO THE CROWD: "if a player on the active team is
// Pushed into the Crowd then a Turnover is caused." A chain push that throws
// the active team's own ball carrier into the crowd must be a Turnover; the
// engine resolves the crowd injury and throw-in without latching one.
BB_TEST(struct_turnover_active_carrier_chain_pushed_into_crowd) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int att = fx_lineman(&m, 0, 0, 10, 2);
    int def = fx_lineman(&m, 1, 0, 10, 1);
    int carrier = fx_lineman(&m, 0, 1, 10, 0); // own carrier on the sideline
    fx_lineman(&m, 1, 1, 9, 0);  // fills the push candidates so the chain
    fx_lineman(&m, 1, 2, 11, 0); // through the carrier is forced
    fx_ball_held(&m, carrier);
    bb_rng rng;
    // Block die 3 (push). Chain: def -> carrier's square; carrier -> crowd.
    // Throw-in from (10,0): D6=3 -> straight in (template 1-2/3-4/5-6),
    // 2D6=2+2=4 counting the boundary square as first -> 3 steps -> (10,3),
    // an empty square: the ball comes to rest ((10,2) holds the attacker).
    // Crowd injury 2D6=1+1: Stunned band (player to the Reserves box).
    const uint8_t dice[] = {3, 3, 2, 2, 1, 1};
    bb_rng_script(&rng, dice, 6);
    fx_run(&m, &rng);
    stx_activate(&m, att, BB_ACT_BLOCK, &rng);
    fx_apply(&m, stx_act(BB_A_BLOCK_TARGET, 0, 10, 1), &rng);
    fx_apply(&m, stx_act(BB_A_CHOOSE_DIE, 0, 0, 0), &rng);
    fx_apply(&m, stx_act(BB_A_PUSH_SQUARE, 2, 10, 0), &rng); // chain into carrier
    fx_apply(&m, stx_act(BB_A_PUSH_SQUARE, 1, 10, 0), &rng); // carrier -> crowd
    bb_status st = fx_apply(&m, stx_act(BB_A_FOLLOW_UP, 0, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(m.players[carrier].location != BB_LOC_ON_PITCH);
    BB_CHECK_EQ(m.players[def].x, 10); // chain relocated the defender
    BB_CHECK_EQ(m.players[def].y, 0);
    // Rulebook: the active team's carrier went off the pitch -> Turnover.
    // The latch is consumed when the team turn ends, so observe the effect:
    // home's turn is over and away is on the clock.
    BB_CHECK_EQ(m.active_team, 1);
    BB_CHECK_EQ(m.decision_team, 1);
}

// ===========================================================================
// A TEAM'S TURN — GAME "PLAYER ACTIVATIONS" / action-per-turn limits
// ===========================================================================

// GAME BLITZ ACTIONS!: the declared target must be reachable by the Move
// Action portion of the Blitz, counting Rush squares.
BB_TEST(struct_blitz_declaration_requires_reachable_standing_target) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int att = fx_lineman(&m, BB_HOME, 0, 5, 7); // MA6, max 2 Rushes
    fx_lineman(&m, BB_AWAY, 0, 15, 7); // nearest adjacent square is 9 away
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);

    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    st = fx_apply(&m, stx_act(BB_A_ACTIVATE, att, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0)), -1);
    BB_CHECK(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_MOVE, 0, 0)) >= 0);
}

// Adjacent targets trivially qualify, and a target at the edge of MA + Rush
// qualifies even though the coach is not forced to perform the block.
BB_TEST(struct_blitz_declaration_allows_adjacent_and_rush_edge_targets) {
    {
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int att = fx_lineman(&m, BB_HOME, 0, 10, 7);
        fx_lineman(&m, BB_AWAY, 0, 11, 7);
        bb_rng rng;
        bb_rng_script(&rng, 0, 0);

        bb_status st = fx_run(&m, &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        st = fx_apply(&m, stx_act(BB_A_ACTIVATE, att, 0, 0), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0)) >= 0);
    }
    {
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int att = fx_lineman(&m, BB_HOME, 0, 5, 7); // reaches x=13 with 2 Rushes
        fx_lineman(&m, BB_AWAY, 0, 14, 7);
        bb_rng rng;
        bb_rng_script(&rng, 0, 0);

        bb_status st = fx_run(&m, &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        st = fx_apply(&m, stx_act(BB_A_ACTIVATE, att, 0, 0), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0)) >= 0);
        st = fx_apply(&m, stx_act(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(fx_find(&m, stx_act(BB_A_END_ACTIVATION, 0, 0, 0)) >= 0);
    }
}

BB_TEST(struct_blitz_declaration_still_hidden_after_blitz_used) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int att = fx_lineman(&m, BB_HOME, 0, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);

    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    m.blitz_used = 1;
    st = fx_apply(&m, stx_act(BB_A_ACTIVATE, att, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0)), -1);
    BB_CHECK(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_MOVE, 0, 0)) >= 0);
}

BB_TEST(struct_blitz_declaration_ignores_prone_and_stunned_targets) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int att = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int prone = fx_lineman(&m, BB_AWAY, 0, 11, 7);
    int stunned = fx_lineman(&m, BB_AWAY, 1, 12, 7);
    m.players[prone].stance = BB_STANCE_PRONE;
    m.players[stunned].stance = BB_STANCE_STUNNED;
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);

    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    st = fx_apply(&m, stx_act(BB_A_ACTIVATE, att, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0)), -1);
    BB_CHECK(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_MOVE, 0, 0)) >= 0);
}

// GAME BLITZ ACTION: "Only a single Blitz Action can be declared each Turn."
BB_TEST(struct_one_blitz_per_team_turn) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int att = fx_lineman(&m, 0, 0, 10, 7);
    int mate = fx_lineman(&m, 0, 1, 3, 3);
    fx_lineman(&m, 1, 0, 11, 7);
    bb_rng rng;
    const uint8_t dice[] = {3}; // blitz block: push
    bb_rng_script(&rng, dice, 1);
    fx_run(&m, &rng);
    stx_activate(&m, att, BB_ACT_BLITZ, &rng);
    fx_apply(&m, stx_act(BB_A_BLOCK_TARGET, 0, 11, 7), &rng);
    fx_apply(&m, stx_act(BB_A_CHOOSE_DIE, 0, 0, 0), &rng);
    fx_apply(&m, stx_act(BB_A_PUSH_SQUARE, 0, 12, 7), &rng);
    fx_apply(&m, stx_act(BB_A_FOLLOW_UP, 0, 0, 0), &rng);
    fx_apply(&m, stx_act(BB_A_END_ACTIVATION, 0, 0, 0), &rng);
    // Second player of the same turn: BLITZ must not be declarable.
    bb_status st = fx_apply(&m, stx_act(BB_A_ACTIVATE, mate, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0)), -1);
    BB_CHECK(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_MOVE, 0, 0)) >= 0);
}

// ENGINE-DIVERGENCE: GAME PLAYER ACTIVATIONS: "you are not obliged to
// complete the declared Action ... though the player will still count as
// having declared that Action even if they do not complete it. This is
// important as some Actions can only be declared once each Turn." (And GAME
// BLITZ ACTIONS!: "they will still count as having used their team's one
// Blitz Action for the Turn.") The engine only burns the team blitz when the
// block is PERFORMED, so a declared-but-abandoned Blitz lets a second player
// blitz in the same turn.
BB_TEST(struct_blitz_declaration_counts_even_if_not_performed) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int att = fx_lineman(&m, 0, 0, 10, 7);
    int mate = fx_lineman(&m, 0, 1, 3, 3);
    fx_lineman(&m, 1, 0, 11, 7);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    stx_activate(&m, att, BB_ACT_BLITZ, &rng); // declared...
    fx_apply(&m, stx_act(BB_A_END_ACTIVATION, 0, 0, 0), &rng); // ...abandoned
    bb_status st = fx_apply(&m, stx_act(BB_A_ACTIVATE, mate, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    // Rulebook: the team's single Blitz declaration is spent.
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0)), -1);
}

// GAME PASS ACTION: "Only a single Pass Action can be declared each Turn."
BB_TEST(struct_one_pass_per_team_turn) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int thrower = fx_lineman(&m, 0, 0, 10, 7);
    int recv = fx_lineman(&m, 0, 1, 13, 7);
    fx_lineman(&m, 1, 0, 20, 12);
    fx_ball_held(&m, thrower);
    bb_rng rng;
    const uint8_t dice[] = {5, 5}; // accurate quick pass, caught
    bb_rng_script(&rng, dice, 2);
    fx_run(&m, &rng);
    stx_activate(&m, thrower, BB_ACT_PASS, &rng);
    fx_apply(&m, stx_act(BB_A_PASS_TARGET, 0, 13, 7), &rng);
    // The receiver now holds the ball and has not activated yet.
    bb_status st = fx_apply(&m, stx_act(BB_A_ACTIVATE, recv, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_PASS, 0, 0)), -1);
    // The single Hand-off of the turn is still available (separate budget).
    BB_CHECK(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_HANDOFF, 0, 0)) >= 0);
}

// GAME HAND-OFF ACTION: "Only a single Hand-off Action can be declared each
// Turn."
BB_TEST(struct_one_handoff_per_team_turn) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int carrier = fx_lineman(&m, 0, 0, 10, 7);
    int recv = fx_lineman(&m, 0, 1, 11, 7);
    fx_lineman(&m, 1, 0, 20, 12);
    fx_ball_held(&m, carrier);
    bb_rng rng;
    const uint8_t dice[] = {5}; // hand-off caught
    bb_rng_script(&rng, dice, 1);
    fx_run(&m, &rng);
    stx_activate(&m, carrier, BB_ACT_HANDOFF, &rng);
    fx_apply(&m, stx_act(BB_A_HANDOFF_TARGET, 0, 11, 7), &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_ACTIVATE, recv, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_HANDOFF, 0, 0)), -1);
    BB_CHECK(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_PASS, 0, 0)) >= 0);
}

// GAME FOUL ACTION: "Only a single Foul Action can be declared each Turn."
BB_TEST(struct_one_foul_per_team_turn) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int f1 = fx_lineman(&m, 0, 0, 10, 7);
    int f2 = fx_lineman(&m, 0, 1, 12, 7);
    int v1 = fx_lineman(&m, 1, 0, 11, 7);
    int v2 = fx_lineman(&m, 1, 1, 12, 8);
    m.players[v1].stance = BB_STANCE_PRONE;
    m.players[v2].stance = BB_STANCE_PRONE;
    bb_rng rng;
    const uint8_t dice[] = {2, 3}; // foul armour: 5, no double, holds
    bb_rng_script(&rng, dice, 2);
    fx_run(&m, &rng);
    stx_activate(&m, f1, BB_ACT_FOUL, &rng);
    fx_apply(&m, stx_act(BB_A_FOUL_TARGET, 0, 11, 7), &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_ACTIVATE, f2, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_FOUL, 0, 0)), -1);
}

// GAME PLAYER ACTIVATIONS: "During your Turn, you may activate each of your
// players once" — an activated player may not activate again, and the coach
// may always voluntarily end the turn (GAME FOREGO ACTIVATION / END_TURN).
BB_TEST(struct_players_activate_once_end_turn_available) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int p0 = fx_lineman(&m, 0, 0, 10, 7);
    int p1 = fx_lineman(&m, 0, 1, 3, 3);
    fx_lineman(&m, 1, 0, 20, 12);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    BB_CHECK(fx_has_type(&m, BB_A_END_TURN)); // available before anything
    stx_activate(&m, p0, BB_ACT_MOVE, &rng);
    fx_apply(&m, stx_act(BB_A_END_ACTIVATION, 0, 0, 0), &rng);
    // p0 already activated: only p1 remains; END_TURN still offered.
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_ACTIVATE, p0, 0, 0)), -1);
    BB_CHECK(fx_find(&m, stx_act(BB_A_ACTIVATE, p1, 0, 0)) >= 0);
    BB_CHECK(fx_has_type(&m, BB_A_END_TURN));
}

// GAME TURNS: "The first thing in each Turn that a team should do is to move
// their Turn Marker up one space." Ending a turn hands play to the opponent.
BB_TEST(struct_end_turn_passes_play_and_increments_marker) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 1, 0, 20, 12);
    m.turn[1] = 0; // away has not played a turn yet
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_END_TURN, 0, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.active_team, 1);
    BB_CHECK_EQ(m.decision_team, 1);
    BB_CHECK_EQ(m.turn[1], 1); // marker moved up at the start of the turn
}

// RR STUNNED: "A Stunned player cannot be activated during their team's
// turn. At the end of each team's turn, any players on their team that
// started that turn Stunned will automatically roll over and become Prone."
BB_TEST(struct_stunned_cannot_activate_and_flips_at_own_turn_end) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    fx_lineman(&m, 0, 0, 10, 7);
    int stunned = fx_lineman(&m, 0, 1, 5, 5);
    m.players[stunned].stance = BB_STANCE_STUNNED;
    int opp_stunned = fx_lineman(&m, 1, 0, 20, 12);
    m.players[opp_stunned].stance = BB_STANCE_STUNNED;
    int opp = fx_lineman(&m, 1, 1, 22, 12);
    (void)opp;
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    // Stunned players are not offered for activation.
    BB_CHECK_EQ(fx_find(&m, stx_act(BB_A_ACTIVATE, stunned, 0, 0)), -1);
    bb_status st = fx_apply(&m, stx_act(BB_A_END_TURN, 0, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    // Own team's turn ended: its stunned player rolls over to Prone...
    BB_CHECK_EQ(m.players[stunned].stance, BB_STANCE_PRONE);
    // ...but the OPPONENT's stunned player does not (not their turn end).
    BB_CHECK(fx_stunned(&m, opp_stunned)); // still stunned, not flipped
}

// ENGINE-DIVERGENCE: RR STUNNED: "any player that became Stunned during the
// course of their team's turn will not roll over as they did not start their
// team's turn as Stunned - they must wait until the end of their team's next
// turn to roll over." The engine flips EVERY stunned player of the team at
// its turn end, including ones stunned during that very turn.
BB_TEST(struct_stunned_during_own_turn_not_flipped_early) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int att = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 1, 0, 11, 7);
    fx_lineman(&m, 1, 1, 20, 12);
    bb_rng rng;
    // PLAYER DOWN; attacker armour 6+6 breaks 9+; injury 2+2 = Stunned.
    // The knockdown is a Turnover, so team 0's turn ends immediately.
    const uint8_t dice[] = {1, 6, 6, 2, 2};
    bb_rng_script(&rng, dice, 5);
    fx_run(&m, &rng);
    stx_activate(&m, att, BB_ACT_BLOCK, &rng);
    fx_apply(&m, stx_act(BB_A_BLOCK_TARGET, 0, 11, 7), &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_CHOOSE_DIE, 0, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.active_team, 1); // the turnover ended team 0's turn
    // Rulebook: att became Stunned DURING team 0's turn, so he must still be
    // Stunned now — he rolls over only at the end of team 0's NEXT turn.
    BB_CHECK_EQ(m.players[att].stance, BB_STANCE_STUNNED);
}

// ENGINE-DIVERGENCE: RR TEAM RE-ROLLS (BB2025): "A Coach may use as many Team
// Re-rolls as they want during their turn, though they may still never
// re-roll a re-roll." The engine still enforces the old one-team-re-roll-
// per-turn limit and does not offer a second re-roll in the same team turn.
BB_TEST(struct_multiple_team_rerolls_in_one_turn) {
    bb_match m;
    fx_match_midturn(&m, 0, 2); // two team re-rolls available
    int p0 = fx_lineman(&m, 0, 0, 10, 7);
    int p1 = fx_lineman(&m, 0, 1, 12, 7);
    fx_lineman(&m, 1, 0, 10, 8);  // marks p0
    fx_lineman(&m, 1, 1, 12, 8);  // marks p1
    bb_rng rng;
    // p0 dodge fails (1) -> team re-roll -> 6 passes.
    // p1 dodge fails (2) -> per the rulebook a second team re-roll offer.
    const uint8_t dice[] = {1, 6, 2};
    bb_rng_script(&rng, dice, 3);
    fx_run(&m, &rng);
    stx_activate(&m, p0, BB_ACT_MOVE, &rng);
    fx_apply(&m, stx_act(BB_A_STEP, 0, 9, 7), &rng);
    fx_apply(&m, stx_act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0), &rng);
    fx_apply(&m, stx_act(BB_A_END_ACTIVATION, 0, 0, 0), &rng);
    BB_CHECK_EQ(m.rerolls[0], 1); // one re-roll spent
    stx_activate(&m, p1, BB_ACT_MOVE, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_STEP, 0, 13, 7), &rng);
    // Rulebook: the failed dodge must pause on a re-roll offer again.
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(fx_find(&m, stx_act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0)) >= 0);
}

// ===========================================================================
// TOUCHDOWN! — GAME "SCORING A TOUCHDOWN" / "THE END OF A DRIVE!"
// ===========================================================================

// GAME SCORING A TOUCHDOWN: "a player must be in possession of the ball and
// must be Standing in a square in the opposition team's End Zone" (e.g. "a
// player holding the ball moving into the opposition End Zone during a Move
// Action"). "As soon as a Touchdown is scored, play stops as a Turnover
// occurs ... Scoring a Touchdown also marks the end of a Drive." + GAME
// RESTARTING THE GAME: "If the Drive ended with a Touchdown, then the team
// that scored will become the kicking team."
BB_TEST(struct_touchdown_move_into_end_zone) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int scorer = fx_lineman(&m, 0, 0, 24, 7);
    fx_lineman(&m, 0, 1, 3, 3);
    fx_lineman(&m, 1, 0, 10, 12);
    fx_ball_held(&m, scorer);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0); // no dice needed
    fx_run(&m, &rng);
    stx_activate(&m, scorer, BB_ACT_MOVE, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_STEP, 0, 25, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.score[0], 1);            // touchdown recorded
    BB_CHECK_EQ(m.score[1], 0);
    BB_CHECK_EQ(m.kicking_team, 0);        // scorer kicks the next drive
    BB_CHECK_EQ(stx_top_proc(&m), BB_PROC_SETUP); // drive ended, new set-up
    BB_CHECK_EQ(m.decision_team, 0);       // kicking team sets up first
    BB_CHECK_EQ(m.ball.state, BB_BALL_OFF_PITCH);
    BB_CHECK_EQ(m.players[scorer].location, BB_LOC_RESERVES); // pitch cleared
    BB_CHECK(!bb_rng_error(&rng)); // touchdown never falls through to Stalling
}

// GAME SCORING A TOUCHDOWN: "...a player picking up the ball in the
// opposition End Zone..." scores immediately.
BB_TEST(struct_touchdown_pickup_in_end_zone) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int scorer = fx_lineman(&m, 0, 0, 24, 7);
    fx_lineman(&m, 1, 0, 10, 12);
    fx_ball_ground(&m, 25, 7);
    bb_rng rng;
    const uint8_t dice[] = {3}; // pickup AG 3+ unmarked: passes
    bb_rng_script(&rng, dice, 1);
    fx_run(&m, &rng);
    stx_activate(&m, scorer, BB_ACT_MOVE, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_STEP, 0, 25, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.score[0], 1);
    BB_CHECK_EQ(stx_top_proc(&m), BB_PROC_SETUP);
}

// GAME SCORING A TOUCHDOWN: "should a player with the ball be Placed Prone,
// Fall Over, or be Knocked Down as they move into the opposition End Zone,
// then no Touchdown will be scored ... the player must be Standing."
BB_TEST(struct_no_touchdown_for_prone_carrier_in_end_zone) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int carrier = fx_player(&m, 0, 0, 23, 7, 1, 3, 3, 4, 9); // MA 1
    fx_lineman(&m, 1, 0, 10, 12);
    fx_ball_held(&m, carrier);
    bb_rng rng;
    // Step to (24,7) free; Rush into the end zone fails on a 1 -> Falls Over
    // in the end zone square. Armour 2+2 holds; ball bounces d8=4 -> (24,7).
    const uint8_t dice[] = {1, 2, 2, 4};
    bb_rng_script(&rng, dice, 4);
    fx_run(&m, &rng);
    stx_activate(&m, carrier, BB_ACT_MOVE, &rng);
    fx_apply(&m, stx_act(BB_A_STEP, 0, 24, 7), &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_STEP, 0, 25, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.score[0], 0); // no touchdown
    BB_CHECK_EQ(m.players[carrier].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.players[carrier].x, 25);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    stx_expect_turn_ended(&m, 0); // Falling Over with the ball is a Turnover
}

// GAME STALLING: a player who held the ball when activated, could score
// without dice, and ends the activation still carrying without scoring is
// Stalling. At activation end, D6 >= the current team turn means the crowd
// Knocks the player Down and causes a Turnover.
BB_TEST(struct_stalling_crowd_knocks_down_carrier_and_ends_turn) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int carrier = fx_lineman(&m, BB_HOME, 0, 24, 7);
    fx_lineman(&m, BB_AWAY, 0, 17, 7);
    fx_ball_held(&m, carrier);

    // Team turn 1: every crowd-action D6 succeeds. Armour 1+1 holds; the
    // dropped ball bounces back toward midfield.
    const uint8_t dice[] = {1, 1, 1, 4};
    bb_rng rng;
    bb_rng_script(&rng, dice, 4);
    BB_CHECK_EQ(fx_run(&m, &rng), BB_STATUS_DECISION);
    BB_CHECK_EQ(stx_activate(&m, carrier, BB_ACT_MOVE, &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_apply(&m, stx_act(BB_A_END_ACTIVATION, 0, 0, 0), &rng),
                BB_STATUS_DECISION);

    BB_CHECK_EQ(m.players[carrier].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(rng.script_pos, 4);
    BB_CHECK(!bb_rng_error(&rng));
    stx_expect_turn_ended(&m, BB_HOME);
}

// GAME STALLING: the crowd only acts when its D6 is at least the current
// team turn. The roll is still made when it cannot succeed.
BB_TEST(struct_stalling_crowd_threshold_uses_current_team_turn) {
    {
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        m.turn[BB_HOME] = 5; // turn_start advances this to turn 6
        int carrier = fx_lineman(&m, BB_HOME, 0, 24, 7);
        fx_lineman(&m, BB_HOME, 1, 3, 3); // keep the turn open
        fx_lineman(&m, BB_AWAY, 0, 17, 7);
        fx_ball_held(&m, carrier);
        const uint8_t dice[] = {5}; // 5 < turn 6: crowd does not act
        bb_rng rng;
        bb_rng_script(&rng, dice, 1);
        fx_run(&m, &rng);
        stx_activate(&m, carrier, BB_ACT_MOVE, &rng);
        fx_apply(&m, stx_act(BB_A_END_ACTIVATION, 0, 0, 0), &rng);
        BB_CHECK_EQ(m.active_team, BB_HOME);
        BB_CHECK_EQ(m.players[carrier].stance, BB_STANCE_STANDING);
        BB_CHECK_EQ(m.ball.carrier, carrier);
        BB_CHECK_EQ(rng.script_pos, 1);
        BB_CHECK(!bb_rng_error(&rng));
    }
    {
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        m.turn[BB_HOME] = 6; // current turn 7: even a 6 cannot succeed
        int carrier = fx_lineman(&m, BB_HOME, 0, 24, 7);
        fx_lineman(&m, BB_HOME, 1, 3, 3);
        fx_lineman(&m, BB_AWAY, 0, 17, 7);
        fx_ball_held(&m, carrier);
        const uint8_t dice[] = {6};
        bb_rng rng;
        bb_rng_script(&rng, dice, 1);
        fx_run(&m, &rng);
        stx_activate(&m, carrier, BB_ACT_MOVE, &rng);
        fx_apply(&m, stx_act(BB_A_END_ACTIVATION, 0, 0, 0), &rng);
        BB_CHECK_EQ(m.active_team, BB_HOME);
        BB_CHECK_EQ(m.players[carrier].stance, BB_STANCE_STANDING);
        BB_CHECK_EQ(rng.script_pos, 1);
        BB_CHECK(!bb_rng_error(&rng));
    }
}

// GAME STALLING: if reaching the end zone requires a Rush, the player is not
// Stalling when they remain in possession at activation end.
BB_TEST(struct_stalling_exempt_when_scoring_requires_rush) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int carrier = fx_player(&m, BB_HOME, 0, 23, 7, 1, 3, 3, 4, 9);
    fx_lineman(&m, BB_HOME, 1, 3, 3);
    fx_lineman(&m, BB_AWAY, 0, 17, 7);
    fx_ball_held(&m, carrier);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    BB_CHECK(!bb_can_score_without_dice(&m, carrier));
    stx_activate(&m, carrier, BB_ACT_MOVE, &rng);
    fx_apply(&m, stx_act(BB_A_END_ACTIVATION, 0, 0, 0), &rng);
    BB_CHECK_EQ(m.active_team, BB_HOME);
    BB_CHECK_EQ(m.players[carrier].stance, BB_STANCE_STANDING);
    BB_CHECK(!bb_rng_error(&rng)); // no crowd roll was attempted
}

// GAME STALLING: if every scoring path starts by leaving a Marked square,
// reaching the end zone requires a Dodge and the player is exempt.
BB_TEST(struct_stalling_exempt_when_scoring_requires_dodge) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int carrier = fx_lineman(&m, BB_HOME, 0, 24, 7);
    fx_lineman(&m, BB_HOME, 1, 3, 3);
    fx_lineman(&m, BB_AWAY, 0, 24, 8); // marks the carrier's origin
    fx_ball_held(&m, carrier);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    fx_run(&m, &rng);
    BB_CHECK(!bb_can_score_without_dice(&m, carrier));
    stx_activate(&m, carrier, BB_ACT_MOVE, &rng);
    fx_apply(&m, stx_act(BB_A_END_ACTIVATION, 0, 0, 0), &rng);
    BB_CHECK_EQ(m.active_team, BB_HOME);
    BB_CHECK_EQ(m.players[carrier].stance, BB_STANCE_STANDING);
    BB_CHECK(!bb_rng_error(&rng));
}

// GAME STALLING: a compulsory activation-trait roll also means the player
// could not score without dice. The successful Bone Head roll is the only
// die consumed here; there is no subsequent crowd roll.
BB_TEST(struct_stalling_exempt_when_scoring_requires_activation_gate) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int carrier = fx_lineman(&m, BB_HOME, 0, 24, 7);
    fx_lineman(&m, BB_HOME, 1, 3, 3);
    fx_lineman(&m, BB_AWAY, 0, 17, 7);
    fx_give_skill(&m, carrier, BB_SK_BONE_HEAD);
    fx_ball_held(&m, carrier);
    const uint8_t dice[] = {6}; // Bone Head passes
    bb_rng rng;
    bb_rng_script(&rng, dice, 1);
    fx_run(&m, &rng);
    BB_CHECK(!bb_can_score_without_dice(&m, carrier));
    stx_activate(&m, carrier, BB_ACT_MOVE, &rng);
    fx_apply(&m, stx_act(BB_A_END_ACTIVATION, 0, 0, 0), &rng);
    BB_CHECK_EQ(m.active_team, BB_HOME);
    BB_CHECK_EQ(rng.script_pos, 1);
    BB_CHECK(!bb_rng_error(&rng));
}

// GAME STALLING: a successful Pass or Hand-off that leaves the activated
// player without the ball is explicitly exempt. This pins the Hand-off case.
BB_TEST(struct_stalling_exempt_after_successful_handoff) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int carrier = fx_lineman(&m, BB_HOME, 0, 24, 7);
    int receiver = fx_lineman(&m, BB_HOME, 1, 24, 8);
    fx_lineman(&m, BB_HOME, 2, 3, 3);
    fx_lineman(&m, BB_AWAY, 0, 17, 7);
    fx_ball_held(&m, carrier);
    const uint8_t dice[] = {5}; // receiver catches the Hand-off
    bb_rng rng;
    bb_rng_script(&rng, dice, 1);
    fx_run(&m, &rng);
    stx_activate(&m, carrier, BB_ACT_HANDOFF, &rng);
    fx_apply(&m, stx_act(BB_A_HANDOFF_TARGET, 0, 24, 8), &rng);
    BB_CHECK_EQ(m.active_team, BB_HOME);
    BB_CHECK_EQ(m.ball.carrier, receiver);
    BB_CHECK_EQ(rng.script_pos, 1);
    BB_CHECK(!bb_rng_error(&rng));
}

// GAME STALLING: choosing to end the team turn before activating an eligible
// carrier counts as foregoing that activation and still invokes the crowd.
BB_TEST(struct_stalling_forgone_carrier_invokes_crowd) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int carrier = fx_lineman(&m, BB_HOME, 0, 24, 7);
    fx_lineman(&m, BB_HOME, 1, 3, 3);
    fx_lineman(&m, BB_AWAY, 0, 17, 7);
    fx_ball_held(&m, carrier);
    const uint8_t dice[] = {1, 1, 1, 4}; // crowd, armour, bounce
    bb_rng rng;
    bb_rng_script(&rng, dice, 4);
    fx_run(&m, &rng);
    fx_apply(&m, stx_act(BB_A_END_TURN, 0, 0, 0), &rng);
    BB_CHECK_EQ(m.players[carrier].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(rng.script_pos, 4);
    BB_CHECK(!bb_rng_error(&rng));
    stx_expect_turn_ended(&m, BB_HOME);
}

// GAME STALLING: when some other activation causes a Turnover before the
// carrier can activate, the carrier had no opportunity and no crowd roll is
// made for them.
BB_TEST(struct_stalling_no_roll_after_earlier_turnover) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int carrier = fx_lineman(&m, BB_HOME, 0, 24, 7);
    int mover = fx_lineman(&m, BB_HOME, 1, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 10, 8); // marks mover
    fx_lineman(&m, BB_AWAY, 1, 17, 7);
    fx_ball_held(&m, carrier);
    const uint8_t dice[] = {2, 3, 3}; // failed Dodge, armour holds
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);
    fx_run(&m, &rng);
    stx_activate(&m, mover, BB_ACT_MOVE, &rng);
    fx_apply(&m, stx_act(BB_A_STEP, 0, 9, 7), &rng);
    BB_CHECK_EQ(m.ball.carrier, carrier);
    BB_CHECK_EQ(rng.script_pos, 3);
    BB_CHECK(!bb_rng_error(&rng));
    stx_expect_turn_ended(&m, BB_HOME);
}

// FAQ (May 2026): Steady Footing may prevent the crowd's Knocked Down result;
// on a 6 there is no Armour roll and no Turnover, so the team turn continues.
BB_TEST(struct_stalling_steady_footing_six_prevents_turnover) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int carrier = fx_lineman(&m, BB_HOME, 0, 24, 7);
    fx_lineman(&m, BB_HOME, 1, 3, 3);
    fx_lineman(&m, BB_AWAY, 0, 17, 7);
    fx_give_skill(&m, carrier, BB_SK_STEADY_FOOTING);
    fx_ball_held(&m, carrier);
    const uint8_t dice[] = {1, 6}; // crowd acts; Steady Footing prevents it
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);
    fx_run(&m, &rng);
    stx_activate(&m, carrier, BB_ACT_MOVE, &rng);
    fx_apply(&m, stx_act(BB_A_END_ACTIVATION, 0, 0, 0), &rng);
    BB_CHECK_EQ(m.active_team, BB_HOME);
    BB_CHECK_EQ(m.players[carrier].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.ball.carrier, carrier);
    BB_CHECK_EQ(rng.script_pos, 2);
    BB_CHECK(!bb_rng_error(&rng));
}

// Shared driver: the ACTIVE team (home) pushes the INACTIVE team's standing
// ball carrier into the carrier's own scoring end zone -> the inactive team
// scores during the opponent's turn (GAME SCORING DURING YOUR OPPONENT'S
// TURN). Leaves the match at the first decision after the touchdown.
static bb_status stx_drive_opponent_turn_td(bb_match* m, bb_rng* rng,
                                            int* att_out, int* carrier_out) {
    fx_match_midturn(m, 0, 0);
    int att = fx_lineman(m, 0, 0, 2, 7);
    fx_lineman(m, 0, 1, 5, 5);
    int carrier = fx_lineman(m, 1, 0, 1, 7); // away scores at x == 0
    fx_ball_held(m, carrier);
    fx_run(m, rng);
    stx_activate(m, att, BB_ACT_BLOCK, rng);
    fx_apply(m, stx_act(BB_A_BLOCK_TARGET, 0, 1, 7), rng);
    fx_apply(m, stx_act(BB_A_CHOOSE_DIE, 0, 0, 0), rng);   // PUSH BACK
    fx_apply(m, stx_act(BB_A_PUSH_SQUARE, 0, 0, 7), rng);  // into the end zone
    bb_status st = fx_apply(m, stx_act(BB_A_FOLLOW_UP, 0, 0, 0), rng);
    if (att_out) *att_out = att;
    if (carrier_out) *carrier_out = carrier;
    return st;
}

// GAME SCORING A TOUCHDOWN: "...a player holding the ball being Pushed or
// Chain Pushed into the opposition End Zone..." + GAME SCORING DURING YOUR
// OPPONENT'S TURN: "your opponent's Turn immediately ends."
BB_TEST(struct_touchdown_by_push_during_opponent_turn) {
    bb_match m;
    bb_rng rng;
    const uint8_t dice[] = {3}; // block die: PUSH BACK
    bb_rng_script(&rng, dice, 1);
    bb_status st = stx_drive_opponent_turn_td(&m, &rng, 0, 0);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.score[1], 1);        // the pushed carrier's team scored
    BB_CHECK_EQ(m.score[0], 0);
    BB_CHECK_EQ(m.kicking_team, 1);    // scorer kicks the next drive
    BB_CHECK_EQ(stx_top_proc(&m), BB_PROC_SETUP); // home turn ended, new drive
    BB_CHECK_EQ(m.decision_team, 1);
}

BB_TEST(struct_touchdown_books_pending_turnover_before_unwind) {
    bb_match m;
    bb_rng rng;
    fx_match_midturn(&m, BB_HOME, 0);
    fx_lineman(&m, BB_HOME, 0, 5, 5);
    int away_carrier = fx_lineman(&m, BB_AWAY, 0, 0, 7);
    fx_ball_held(&m, away_carrier);
    fx_run(&m, &rng);

    // Successful interception into the endzone follows this ordering:
    // bb_turnover(active team), then bb_check_td(opponent carrier).
    bb_turnover(&m);
    BB_CHECK(bb_check_td(&m));
    m.status = BB_STATUS_RUNNING;
    fx_run(&m, &rng);

    BB_CHECK_EQ(m.score[BB_AWAY], 1);
    BB_CHECK_EQ(m.turns_completed[BB_HOME], 1);
    BB_CHECK_EQ(m.turns_completed_held[BB_HOME], 0);
    BB_CHECK_EQ(m.turnovers_completed[BB_HOME], 1);
}

// ENGINE-DIVERGENCE: GAME SCORING DURING YOUR OPPONENT'S TURN: "the team that
// scored will skip their next Turn entirely ... play will resume with the
// team that conceded." After the re-kick the conceding team plays, and the
// scorer's turn marker must advance for the skipped turn. The engine resumes
// with the conceder but never skips the scorer's next turn (its marker stays
// behind, granting it a turn the rulebook denies).
BB_TEST(struct_opponent_turn_scorer_skips_next_turn) {
    bb_match m;
    bb_rng rng;
    // block push; then kick-off: deviate d8=2,d6=1; event 1+1; bounce d8=2.
    const uint8_t dice[] = {3, 2, 1, 1, 1, 2};
    bb_rng_script(&rng, dice, 6);
    bb_status st = stx_drive_opponent_turn_td(&m, &rng, 0, 0);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    // Set up the next drive: away (scorer) kicks, then home receives.
    int abase = BB_TEAM_SLOTS;
    st = fx_apply(&m, stx_act(BB_A_SETUP_PLACE, abase + 0, 13, 5), &rng);
    st = fx_apply(&m, stx_act(BB_A_SETUP_DONE, 0, 0, 0), &rng);
    st = fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 0, 12, 5), &rng);
    st = fx_apply(&m, stx_act(BB_A_SETUP_PLACE, 1, 12, 6), &rng);
    st = fx_apply(&m, stx_act(BB_A_SETUP_DONE, 0, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 6, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    // Play resumes with the team that conceded (home) — engine gets this far.
    BB_CHECK_EQ(m.active_team, 0);
    BB_CHECK_EQ(m.decision_team, 0);
    BB_CHECK_EQ(m.turn[0], 2);
    // Rulebook: away skip their next turn entirely — their turn marker must
    // have advanced past turn 2 without them playing it.
    BB_CHECK_EQ(m.turn[1], 2);
}

// ===========================================================================
// HALVES & DRIVES — GAME "A GAME OF TWO HALVES!" / "ROUNDS" /
// "END OF DRIVE SEQUENCE" / RR "TEAM RE-ROLLS"
// ===========================================================================

// MATCH frame private encoding (proc_match.c): data bit0 = TD-scored latch,
// bit1 = "H1 kicker latched", bit2 = the team that kicked first in half 1.
enum { STX_MD_TD = 1 << 0, STX_MD_H1_SET = 1 << 1, STX_MD_H1_AWAY = 1 << 2 };

// GAME ROUNDS: "At the start of the second half, the team that received the
// ball at the start of the first half will become the kicking team" (also
// GAME RESTARTING THE GAME). Turn markers restart for the new half.
BB_TEST(struct_second_half_kicker_is_first_half_receiver) {
    bb_match m;
    stx_base(&m);
    for (int i = 0; i < 11; i++) stx_reserve(&m, 0, i);
    for (int i = 0; i < 11; i++) stx_reserve(&m, 1, i);
    m.half = 1;
    m.turn[0] = m.turn[1] = 8; // half over
    m.kicking_team = 0;
    bb_push(&m, BB_PROC_MATCH, 0, 0, 0, 0);
    bb_top(&m)->phase = 4;            // half/drive transition
    bb_top(&m)->data = STX_MD_H1_SET; // home kicked first in half 1
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.half, 2);
    BB_CHECK_EQ(m.kicking_team, BB_AWAY); // H1 receiver kicks H2
    BB_CHECK_EQ(m.turn[0], 0);
    BB_CHECK_EQ(m.turn[1], 0);
    BB_CHECK_EQ(stx_top_proc(&m), BB_PROC_SETUP);
    BB_CHECK_EQ(m.decision_team, BB_AWAY); // and so sets up first
}

// GAME ENDING THE GAME: "If there are no more Turns to be played, then the
// final whistle is blown and the game comes to an end." (Two halves of eight
// rounds each — GAME A GAME OF TWO HALVES!)
BB_TEST(struct_match_over_after_two_halves) {
    bb_match m;
    stx_base(&m);
    stx_reserve(&m, 0, 0);
    stx_reserve(&m, 1, 0);
    m.half = 2;
    m.turn[0] = m.turn[1] = 8;
    bb_push(&m, BB_PROC_MATCH, 0, 0, 0, 0);
    bb_top(&m)->phase = 4;
    bb_top(&m)->data = STX_MD_H1_SET;
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_MATCH_OVER);
}

// GAME ROUNDS/TURNS: "each team will get eight Turns in each half" — when one
// team has used its eight turns and the other has not, the remaining team
// still takes its outstanding turn before the half ends.
BB_TEST(struct_each_team_gets_eight_turns_per_half) {
    bb_match m;
    stx_base(&m);
    fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 1, 0, 20, 7);
    m.turn[0] = 8;
    m.turn[1] = 7;
    m.active_team = 0; // would be home's "ninth" turn — must go to away
    bb_push(&m, BB_PROC_MATCH, 0, 0, 0, 0);
    bb_top(&m)->phase = 3; // turn-dispatch loop
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, 1); // away plays its 8th turn
    BB_CHECK_EQ(m.turn[1], 8);
    // After away's final turn the half is over: the second half begins.
    st = fx_apply(&m, stx_act(BB_A_END_TURN, 0, 0, 0), &rng);
    BB_CHECK_EQ(m.half, 2);
    // Match-level reward/telemetry counters survive the half-time reset of the
    // public turn markers and record this final genuine boundary exactly once.
    BB_CHECK_EQ(m.turns_completed[BB_HOME], 0);
    BB_CHECK_EQ(m.turns_completed[BB_AWAY], 1);
    BB_CHECK_EQ(m.turns_completed_held[BB_AWAY], 0);
    BB_CHECK_EQ(m.turnovers_completed[BB_AWAY], 0);
}

// GAME RECOVER KNOCKED-OUT PLAYERS: "Roll a D6 for each Knocked-out player.
// On a 4+ the player recovers and is moved to the Reserves Box ... On a 1-3,
// the player cannot be roused and is still Knocked-out."
BB_TEST(struct_ko_recovery_between_drives) {
    bb_match m;
    stx_base(&m);
    int ko_a = stx_reserve(&m, 0, 0);
    int ko_b = stx_reserve(&m, 0, 1);
    int ko_c = stx_reserve(&m, 1, 0);
    m.players[ko_a].location = BB_LOC_KO;
    m.players[ko_b].location = BB_LOC_KO;
    m.players[ko_c].location = BB_LOC_KO;
    int on_pitch = fx_lineman(&m, 0, 2, 10, 7);
    bb_push(&m, BB_PROC_END_DRIVE, 0, 0, 0, 0);
    bb_rng rng;
    const uint8_t dice[] = {4, 3, 6}; // slot order: ko_a, ko_b, ko_c
    bb_rng_script(&rng, dice, 3);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK(st == BB_STATUS_MATCH_OVER || st == BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[ko_a].location, BB_LOC_RESERVES); // 4+: recovered
    BB_CHECK_EQ(m.players[ko_b].location, BB_LOC_KO);       // 1-3: still KO
    BB_CHECK_EQ(m.players[ko_c].location, BB_LOC_RESERVES);
    // The pitch is cleared at the end of a drive (GAME THE DRIVE ENDS).
    BB_CHECK_EQ(m.players[on_pitch].location, BB_LOC_RESERVES);
}

// ENGINE-DIVERGENCE: RR TEAM RE-ROLLS: "any [Team Re-rolls] used during the
// first half of a game will be replenished at half-time. This means that a
// team will always start each half of a game with its full complement of
// Team Re-rolls." The engine never resets the re-roll counters at half-time.
BB_TEST(struct_team_rerolls_replenish_at_half_time) {
    bb_match m;
    bb_match_init(&m, BB_TEAM_HUMAN, BB_TEAM_ORC); // 3 re-rolls per side
    BB_CHECK_EQ(m.rerolls[0], 3);
    m.rerolls[0] = 0; // home spent all three during the first half
    m.rerolls[1] = 1; // away spent two
    m.half = 1;
    m.turn[0] = m.turn[1] = 8;
    m.stack_top = 0;
    bb_push(&m, BB_PROC_MATCH, 0, 0, 0, 0);
    bb_top(&m)->phase = 4;
    bb_top(&m)->data = STX_MD_H1_SET;
    m.status = BB_STATUS_RUNNING;
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.half, 2);
    // Rulebook: both teams restart the half with their full complement.
    BB_CHECK_EQ(m.rerolls[0], 3);
    BB_CHECK_EQ(m.rerolls[1], 3);
}

// SK "Leader (Passive)": "A team that has one or more players with this
// Skill on the pitch at the start of a half may gain a single extra Team
// Re-roll" — HALF scope. A TD that ends a drive mid-half must not delete an
// unused Leader re-roll; the old END_DRIVE clamp to rerolls_start did
// (adversarial review M2).
BB_TEST(struct_leader_reroll_survives_mid_half_drive_end) {
    bb_match m;
    stx_base(&m);
    int leader = stx_reserve(&m, BB_HOME, 0);
    fx_give_skill(&m, leader, BB_SK_LEADER);
    stx_reserve(&m, BB_AWAY, 0);
    m.rerolls[0] = m.rerolls_start[0] = 3;
    m.rerolls[1] = m.rerolls_start[1] = 3;
    // PREGAME grants the Leader re-roll on top of the purchased complement
    // (rerolls_start untouched).
    bb_push(&m, BB_PROC_PREGAME, 0, 0, 0, 0);
    bb_rng rng;
    const uint8_t dice[] = {3, 4, 1}; // weather 2d6; toss: home wins
    bb_rng_script(&rng, dice, 3);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    fx_apply(&m, stx_act(BB_A_CHOOSE_OPTION, 0, 0, 0), &rng); // home kicks
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.rerolls[BB_HOME], 4); // 3 purchased + Leader
    BB_CHECK_EQ(m.rerolls_start[BB_HOME], 3);
    BB_CHECK_EQ(m.rerolls[BB_AWAY], 3); // no Leader: no bonus
    // Mid-half TD: the MATCH driver runs the end-of-drive sequence and starts
    // the next drive. The Leader re-roll must still be in the pool.
    m.stack_top = 0;
    m.status = BB_STATUS_RUNNING;
    m.half = 1;
    m.turn[0] = m.turn[1] = 3; // mid-half
    m.kicking_team = BB_HOME;  // the scorer kicks the next drive
    bb_push(&m, BB_PROC_MATCH, 0, 0, 0, 0);
    bb_top(&m)->phase = 3;
    bb_top(&m)->data = STX_MD_TD | STX_MD_H1_SET;
    bb_rng rng2;
    bb_rng_script(&rng2, 0, 0); // no KO'd players: no recovery dice
    st = fx_run(&m, &rng2);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(stx_top_proc(&m), BB_PROC_SETUP); // next drive of the SAME half
    BB_CHECK_EQ(m.half, 1);
    BB_CHECK_EQ(m.rerolls[BB_HOME], 4); // Leader re-roll survived (was wiped)
    BB_CHECK_EQ(m.rerolls[BB_AWAY], 3);
}

// GAME KICK-OFF EVENT 7 BRILLIANT COACHING: the winner "immediately gains a
// free Team Re-roll for the Drive ahead" — DRIVE scope: an unused bonus
// expires at the end of the drive; the purchased complement is untouched.
BB_TEST(struct_brilliant_coaching_reroll_expires_at_drive_end) {
    // Grant: tracked as a drive-scoped bonus on top of the pool.
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    fx_lineman(&m, 0, 0, 5, 5);
    fx_lineman(&m, 1, 0, 20, 10);
    m.rerolls[0] = m.rerolls[1] = 2;
    m.rerolls_start[0] = m.rerolls_start[1] = 2;
    bb_rng rng;
    // d8=2,d6=3; event 3+4=7; home d6=5 vs away d6=2 -> home +1; bounce d8=1.
    const uint8_t dice[] = {2, 3, 3, 4, 5, 2, 1};
    bb_rng_script(&rng, dice, 7);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.rerolls[BB_HOME], 3);
    BB_CHECK_EQ(m.bonus_rerolls[BB_HOME], 1);
    BB_CHECK_EQ(m.rerolls[BB_AWAY], 2);
    BB_CHECK_EQ(m.bonus_rerolls[BB_AWAY], 0);
    // Expiry: END_DRIVE removes the unused drive bonus, nothing else.
    bb_match m2;
    stx_base(&m2);
    m2.rerolls[0] = 3;
    m2.rerolls_start[0] = 2;
    m2.bonus_rerolls[0] = 1;
    m2.rerolls[1] = 2;
    m2.rerolls_start[1] = 2;
    bb_push(&m2, BB_PROC_END_DRIVE, 0, 0, 0, 0);
    bb_rng rng2;
    bb_rng_script(&rng2, 0, 0);
    st = fx_run(&m2, &rng2);
    BB_CHECK(st == BB_STATUS_MATCH_OVER || st == BB_STATUS_DECISION);
    BB_CHECK_EQ(m2.rerolls[0], 2);
    BB_CHECK_EQ(m2.bonus_rerolls[0], 0);
    BB_CHECK_EQ(m2.rerolls[1], 2);
}

// RR "Re-rolls" + SK "Leader": re-rolls are fungible in play, but their
// scopes differ — a coach spends the soonest-expiring one first. A team
// holding both a Brilliant Coaching bonus (drive) and a Leader re-roll
// (half) that uses ONE team re-roll has consumed the Brilliant Coaching
// bonus: the drive end must then leave the Leader re-roll in the pool.
BB_TEST(struct_bonus_reroll_spent_before_leader) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 3);
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 1, 0, 10, 8);
    // 3 purchased + 1 Leader (half scope) + 1 Brilliant Coaching (drive).
    m.rerolls[BB_HOME] = 5;
    m.bonus_rerolls[BB_HOME] = 1;
    static const uint8_t dice[] = {2, 4}; // dodge fails; re-rolled 4 passes
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);
    bb_status st = fx_run(&m, &rng);
    st = fx_apply(&m, stx_act(BB_A_ACTIVATE, mover, 0, 0), &rng);
    st = fx_apply(&m, stx_act(BB_A_DECLARE, BB_ACT_MOVE, 0, 0), &rng);
    st = fx_apply(&m, stx_act(BB_A_STEP, 0, 10, 6), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    st = fx_apply(&m, stx_act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.rerolls[BB_HOME], 4);
    BB_CHECK_EQ(m.bonus_rerolls[BB_HOME], 0); // the drive bonus was the one spent
    // At the drive end nothing more expires: the Leader re-roll survives.
    bb_match m2;
    stx_base(&m2);
    m2.rerolls[0] = 4;
    m2.rerolls_start[0] = 3;
    m2.bonus_rerolls[0] = 0;
    bb_push(&m2, BB_PROC_END_DRIVE, 0, 0, 0, 0);
    bb_rng rng2;
    bb_rng_script(&rng2, 0, 0);
    st = fx_run(&m2, &rng2);
    BB_CHECK(st == BB_STATUS_MATCH_OVER || st == BB_STATUS_DECISION);
    BB_CHECK_EQ(m2.rerolls[0], 4);
}

// ENGINE-DIVERGENCE: GAME ARGUE THE CALL: "When a player is Sent-off for any
// reason, their Coach may attempt to Argue the Call - roll a D6..." The
// engine sends the fouler off with no Argue the Call decision window.
BB_TEST(struct_sent_off_offers_argue_the_call) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int fouler = fx_lineman(&m, 0, 0, 10, 7);
    int victim = fx_lineman(&m, 1, 0, 11, 7);
    m.players[victim].stance = BB_STANCE_PRONE;
    fx_lineman(&m, 1, 1, 20, 12);
    bb_rng rng;
    // Foul armour 4+4: natural double -> Sent-off. Rulebook: before the
    // turnover resolves, the fouling coach gets the Argue the Call roll.
    const uint8_t dice[] = {4, 4};
    bb_rng_script(&rng, dice, 2);
    fx_run(&m, &rng);
    stx_activate(&m, fouler, BB_ACT_FOUL, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_FOUL_TARGET, 0, 11, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    // Rulebook: the decision after the double belongs to the fouling coach
    // (Argue the Call?); the engine has already ended the turn instead.
    BB_CHECK_EQ(m.decision_team, 0);
}

// KICK-OFF EVENT "Cheering Fans" (BB2025): the winner's FIRST Block "next
// turn" gets an extra offensive assist. The buff must not outlive that turn —
// it used to persist across turns, drives and halves until a block consumed
// it (review LOW).
BB_TEST(struct_cheering_fans_assist_expires_at_turn_end) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 1, 0, 20, 12);
    m.cheer_assist[0] = 1; // as granted by the kick-off event
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.cheer_assist[0], 1); // live during the team's turn
    st = fx_apply(&m, stx_act(BB_A_END_TURN, 0, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION); // opponent's turn begins
    BB_CHECK_EQ(m.cheer_assist[0], 0);   // unspent buff expired with the turn
}

BB_TEST(struct_cheering_fans_assist_expires_at_drive_end) {
    bb_match m;
    stx_base(&m);
    m.cheer_assist[0] = m.cheer_assist[1] = 1;
    bb_push(&m, BB_PROC_END_DRIVE, 0, 0, 0, 0);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0); // empty pitch/KO box: no dice consumed
    bb_status st = bb_advance(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_MATCH_OVER); // END_DRIVE was the only frame
    BB_CHECK_EQ(m.cheer_assist[0], 0);
    BB_CHECK_EQ(m.cheer_assist[1], 0);
}

// Setup placement discipline: until the line is filled, only fresh
// placements from Reserves are legal — no re-placing or removing already
// placed players (kills the one-player setup shuffle; any final formation
// stays reachable by placing 11 first, then rearranging).
BB_TEST(structure_setup_reserves_first_discipline) {
    bb_match m;
    bb_match_init(&m, BB_TEAM_HUMAN, BB_TEAM_ORC);
    bb_rng rng;
    bb_rng_seed(&rng, 99, 1);
    bb_status st = bb_advance(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);

    bb_action legal[BB_LEGAL_MAX];
    // Fast-forward through the pregame (coin toss, receive choice) until the
    // setup phase surfaces placement actions.
    int ff = 0;
    while (ff++ < 8) {
        int n = bb_legal_actions(&m, legal);
        bool in_setup = false;
        for (int i = 0; i < n; i++) {
            if (legal[i].type == BB_A_SETUP_PLACE) in_setup = true;
        }
        if (in_setup) break;
        st = bb_apply(&m, legal[0], &rng);
    }
    int placed = 0;
    int guard = 0;
    while (placed < 11 && guard++ < 64) {
        int n = bb_legal_actions(&m, legal);
        int n_remove = 0, n_replace = 0, pick = -1;
        for (int i = 0; i < n; i++) {
            if (legal[i].type == BB_A_SETUP_REMOVE) n_remove++;
            if (legal[i].type == BB_A_SETUP_PLACE) {
                if (m.players[legal[i].arg].location == BB_LOC_ON_PITCH) n_replace++;
                else if (pick < 0) pick = i;
            }
        }
        // Mid-fill: no removes, no re-placements offered.
        BB_CHECK_EQ(n_remove, 0);
        BB_CHECK_EQ(n_replace, 0);
        BB_CHECK(pick >= 0);
        st = bb_apply(&m, legal[pick], &rng);
        placed++;
    }
    // Line filled: rearrangement unlocks.
    int n = bb_legal_actions(&m, legal);
    int n_remove = 0, n_replace = 0;
    for (int i = 0; i < n; i++) {
        if (legal[i].type == BB_A_SETUP_REMOVE) n_remove++;
        if (legal[i].type == BB_A_SETUP_PLACE &&
            m.players[legal[i].arg].location == BB_LOC_ON_PITCH) n_replace++;
    }
    BB_CHECK(n_remove > 0);
    BB_CHECK(n_replace > 0);
}

// ===========================================================================
// PICK-ME-UP — SK#PICK-ME-UP: "At the end of each of the opposition's Turns,
// roll a D6 for each Prone team-mate within 3 squares of one or more
// Standing players with this Trait. On a 5+, the Prone player may
// immediately stand up. Should a player with this Trait stand up as a result
// of a team-mate using this Trait, they may not also use this Trait during
// the same Turn."
// ===========================================================================

// 5+ stands a prone team-mate within 3 squares at the end of the OPPONENT's
// turn; a 4 leaves them prone.
BB_TEST(struct_pick_me_up_5plus_stands_prone_teammate) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    fx_lineman(&m, 0, 0, 5, 5);
    int helper = fx_lineman(&m, 1, 0, 20, 7);
    int down = fx_lineman(&m, 1, 1, 22, 7); // within 3 of the helper
    fx_give_skill(&m, helper, BB_SK_PICK_ME_UP);
    m.players[down].stance = BB_STANCE_PRONE;
    uint8_t script[] = {5};
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    bb_status st = fx_run(&m, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    bb_action et = {BB_A_END_TURN, 0, 0, 0};
    st = fx_apply(&m, et, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[down].stance, BB_STANCE_STANDING);
    BB_CHECK(!bb_rng_error(&rng));
}

BB_TEST(struct_pick_me_up_4_fails_stays_prone) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    fx_lineman(&m, 0, 0, 5, 5);
    int helper = fx_lineman(&m, 1, 0, 20, 7);
    int down = fx_lineman(&m, 1, 1, 22, 7);
    fx_give_skill(&m, helper, BB_SK_PICK_ME_UP);
    m.players[down].stance = BB_STANCE_PRONE;
    uint8_t script[] = {4};
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    fx_run(&m, &rng);
    bb_action et = {BB_A_END_TURN, 0, 0, 0};
    fx_apply(&m, et, &rng);
    BB_CHECK_EQ(m.players[down].stance, BB_STANCE_PRONE);
    BB_CHECK(!bb_rng_error(&rng));
}

// FFB boundary order (validated against live replays, item 8): the incoming
// team's Stunned players roll over BEFORE the Pick-Me-Up rolls at the same
// boundary — a player stunned during the opponent's turn gets a Pick-Me-Up
// roll right away and can be stood up where the old engine kept them down.
BB_TEST(struct_pick_me_up_rolls_for_just_rolled_over_stunned) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    fx_lineman(&m, 0, 0, 5, 5);
    int helper = fx_lineman(&m, 1, 0, 20, 7);
    int down = fx_lineman(&m, 1, 1, 22, 7);
    fx_give_skill(&m, helper, BB_SK_PICK_ME_UP);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0);
    bb_status st = fx_run(&m, &rng); // home turn starts
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    m.players[down].stance = BB_STANCE_STUNNED; // stunned during home's turn
    uint8_t script[] = {5};
    bb_rng_script(&rng, script, 1);
    bb_action et = {BB_A_END_TURN, 0, 0, 0};
    st = fx_apply(&m, et, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[down].stance, BB_STANCE_STANDING);
    BB_CHECK(!bb_rng_error(&rng));
}

// Helper snapshot: an owner stood up by a team-mate's use of the Trait "may
// not also use this Trait during the same Turn" — a candidate only in range
// of the freshly-stood owner gets NO roll.
BB_TEST(struct_pick_me_up_stood_owner_cannot_help_same_turn) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    fx_lineman(&m, 0, 0, 5, 5);
    int a = fx_lineman(&m, 1, 0, 20, 7);  // prone OWNER, within 3 of b
    int b = fx_lineman(&m, 1, 1, 22, 7);  // standing owner (the helper)
    int c = fx_lineman(&m, 1, 2, 17, 7);  // prone, within 3 of a ONLY
    fx_give_skill(&m, a, BB_SK_PICK_ME_UP);
    fx_give_skill(&m, b, BB_SK_PICK_ME_UP);
    m.players[a].stance = BB_STANCE_PRONE;
    m.players[c].stance = BB_STANCE_PRONE;
    uint8_t script[] = {5}; // ONE roll: a stands; c gets no roll
    bb_rng rng;
    bb_rng_script(&rng, script, 1);
    fx_run(&m, &rng);
    bb_action et = {BB_A_END_TURN, 0, 0, 0};
    bb_status st = fx_apply(&m, et, &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[a].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[c].stance, BB_STANCE_PRONE); // no second die
    BB_CHECK(!bb_rng_error(&rng));
}

// ===========================================================================
// KICK-OFF EVENT 4 SOLID DEFENCE — "The Coach of the kicking team selects up
// to D3+3 Open players on their team. The selected players are then removed
// from the pitch and can be set up again following all the usual
// restrictions for setting up the team." (D21 window)
// ===========================================================================

BB_TEST(struct_kickoff_solid_defence_reposition_window) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    // Kicking (home) legal 3-man formation on the LoS centre.
    int h0 = fx_lineman(&m, 0, 0, 12, 5);
    fx_lineman(&m, 0, 1, 12, 6);
    fx_lineman(&m, 0, 2, 12, 7);
    fx_lineman(&m, 1, 0, 20, 10); // receiver, far away (home players Open)
    bb_rng rng;
    // d8=2,d6=3 -> ball (18,4); event 1+3=4 SOLID DEFENCE; D3=1 -> 4 players.
    const uint8_t dice[] = {2, 3, 1, 3, 1};
    bb_rng_script(&rng, dice, 5);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_HOME); // the KICKING coach repositions
    BB_CHECK(fx_has_type(&m, BB_A_SETUP_PLACE));
    BB_CHECK(fx_has_type(&m, BB_A_SETUP_DONE)); // formation legal: may pass
    // Move h0 off the LoS: only 2 remain there -> DONE must disappear.
    st = fx_apply(&m, stx_act(BB_A_SETUP_PLACE, h0, 10, 5), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[h0].x, 10);
    BB_CHECK(!fx_has_type(&m, BB_A_SETUP_DONE));
    // Put him back on the LoS (re-placing a selected player is free).
    st = fx_apply(&m, stx_act(BB_A_SETUP_PLACE, h0, 12, 4), &rng);
    BB_CHECK(fx_has_type(&m, BB_A_SETUP_DONE));
    // Confirm: the kick lands (bounce d8) and the kickoff settles.
    const uint8_t dice2[] = {1};
    bb_rng_script(&rng, dice2, 1);
    st = fx_apply(&m, stx_act(BB_A_SETUP_DONE, 0, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[h0].x, 12);
    BB_CHECK_EQ(m.players[h0].y, 4);
    BB_CHECK(!bb_rng_error(&rng));
}

// Solid Defence selects only OPEN players: a kicking player Marked across
// the line of scrimmage cannot be repositioned.
BB_TEST(struct_kickoff_solid_defence_marked_player_ineligible) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    int h0 = fx_lineman(&m, 0, 0, 12, 5); // marked by the away LoS player
    fx_lineman(&m, 0, 1, 12, 6);
    fx_lineman(&m, 0, 2, 12, 7);
    fx_lineman(&m, 1, 0, 13, 5); // away player marking h0
    bb_rng rng;
    const uint8_t dice[] = {2, 3, 1, 3, 1};
    bb_rng_script(&rng, dice, 5);
    fx_run(&m, &rng);
    fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(&m, legal);
    for (int i = 0; i < n; i++) {
        if (legal[i].type == BB_A_SETUP_PLACE) {
            BB_CHECK(legal[i].arg != (uint8_t)h0); // not Open: ineligible
        }
    }
}

// ===========================================================================
// KICK-OFF EVENT 9 QUICK SNAP! — "The Coach of the receiving team selects up
// to D3+3 Open players on their team. The selected players may immediately
// move one square in any direction, even if this takes them into the
// opposition's half." (D21 window)
// ===========================================================================

BB_TEST(struct_kickoff_quick_snap_one_square_each_any_direction) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    fx_lineman(&m, 0, 0, 5, 5);
    int a0 = fx_lineman(&m, 1, 0, 13, 7);  // receiving, on their LoS
    int a1 = fx_lineman(&m, 1, 1, 20, 10);
    bb_rng rng;
    // d8=2,d6=3 -> ball (18,4); event 4+5=9 QUICK SNAP; D3=1 -> 4 players.
    const uint8_t dice[] = {2, 3, 4, 5, 1};
    bb_rng_script(&rng, dice, 5);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_AWAY); // the RECEIVING coach moves
    // a0 steps ACROSS the halfway line into the kicking half (12,7).
    st = fx_apply(&m, stx_act(BB_A_SETUP_PLACE, a0, 12, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[a0].x, 12);
    // One square each: a0 may not move again.
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(&m, legal);
    for (int i = 0; i < n; i++) {
        if (legal[i].type == BB_A_SETUP_PLACE) {
            BB_CHECK(legal[i].arg != (uint8_t)a0);
        }
    }
    // a1 may still move (budget 4); a two-square jump is not offered.
    BB_CHECK(fx_find(&m, stx_act(BB_A_SETUP_PLACE, a1, 21, 10)) >= 0);
    BB_CHECK(fx_find(&m, stx_act(BB_A_SETUP_PLACE, a1, 22, 10)) < 0);
    const uint8_t dice2[] = {1};
    bb_rng_script(&rng, dice2, 1);
    st = fx_apply(&m, stx_act(BB_A_SETUP_DONE, 0, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng)); // landing bounce consumed
}

// Quick Snap honours the D3+3 player budget: with D3=1 only 4 distinct
// players may move; the fifth gets no placement actions.
BB_TEST(struct_kickoff_quick_snap_player_budget) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    fx_lineman(&m, 0, 0, 5, 5);
    int as[5];
    for (int i = 0; i < 5; i++) as[i] = fx_lineman(&m, 1, i, 20, 4 + 2 * i);
    bb_rng rng;
    const uint8_t dice[] = {2, 3, 4, 5, 1};
    bb_rng_script(&rng, dice, 5);
    fx_run(&m, &rng);
    fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    for (int i = 0; i < 4; i++) {
        bb_status st = fx_apply(&m,
            stx_act(BB_A_SETUP_PLACE, as[i], 19, 4 + 2 * i), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
    }
    BB_CHECK(!fx_has_type(&m, BB_A_SETUP_PLACE)); // budget exhausted
    BB_CHECK(fx_has_type(&m, BB_A_SETUP_DONE));
    (void)as;
}

// ===========================================================================
// KICK-OFF EVENT 10 CHARGE! — "The Coach of the kicking team selects up to
// D3+3 Open players on their team. The selected players may then be
// activated one at a time, exactly as if it was their team's Turn, and
// perform a free Move Action. One of the selected players may instead
// perform a free Blitz Action, one may perform a free Throw Team-mate
// Action, and one may perform a free Kick Team-mate Action. If a selected
// player Falls Over or is Knocked Down during their activation, no further
// selected players can be activated and the Charge ends." (D21 window)
// ===========================================================================

static void stx_apply_ok(bb_match* m, bb_rng* rng, bb_action a) {
    bb_status st = fx_apply(m, a, rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
}

BB_TEST(struct_kickoff_charge_move_and_single_blitz) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    int h0 = fx_lineman(&m, 0, 0, 10, 5);
    int h1 = fx_lineman(&m, 0, 1, 10, 9);
    fx_lineman(&m, 0, 2, 3, 3); // stays eligible so END_TURN is a choice
    int a0 = fx_lineman(&m, 1, 0, 13, 9); // blitz target on the away LoS
    (void)a0;
    bb_rng rng;
    // d8=2,d6=3 -> ball (18,4); event 5+5=10 CHARGE!; D3=1 -> 4 activations.
    const uint8_t dice[] = {2, 3, 5, 5, 1};
    bb_rng_script(&rng, dice, 5);
    fx_run(&m, &rng);
    bb_status st = fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_HOME);   // the KICKING coach activates
    BB_CHECK_EQ(m.active_team, BB_HOME);     // "as if it was their Turn"
    BB_CHECK(fx_has_type(&m, BB_A_ACTIVATE));
    BB_CHECK(fx_has_type(&m, BB_A_END_TURN));
    // First activation: a free MOVE (Block/Pass/Foul kinds must not exist).
    stx_apply_ok(&m, &rng, stx_act(BB_A_ACTIVATE, h0, 0, 0));
    BB_CHECK(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_MOVE, 0, 0)) >= 0);
    BB_CHECK(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0)) >= 0);
    BB_CHECK(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_PASS, 0, 0)) < 0);
    BB_CHECK(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_FOUL, 0, 0)) < 0);
    stx_apply_ok(&m, &rng, stx_act(BB_A_DECLARE, BB_ACT_MOVE, 0, 0));
    stx_apply_ok(&m, &rng, stx_act(BB_A_STEP, 0, 10, 6));
    stx_apply_ok(&m, &rng, stx_act(BB_A_END_ACTIVATION, 0, 0, 0));
    BB_CHECK_EQ(m.players[h0].y, 6); // the free move happened
    // h0 cannot be activated again; h1 may BLITZ (the one-of budget).
    BB_CHECK(fx_find(&m, stx_act(BB_A_ACTIVATE, h0, 0, 0)) < 0);
    stx_apply_ok(&m, &rng, stx_act(BB_A_ACTIVATE, h1, 0, 0));
    BB_CHECK(fx_find(&m, stx_act(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0)) >= 0);
    const uint8_t dice2[] = {/*1d block*/ 3};
    bb_rng_script(&rng, dice2, 1);
    stx_apply_ok(&m, &rng, stx_act(BB_A_DECLARE, BB_ACT_BLITZ, 0, 0));
    stx_apply_ok(&m, &rng, stx_act(BB_A_STEP, 0, 11, 9));
    stx_apply_ok(&m, &rng, stx_act(BB_A_STEP, 0, 12, 9));
    stx_apply_ok(&m, &rng, stx_act(BB_A_BLOCK_TARGET, 0, 13, 9));
    stx_apply_ok(&m, &rng, stx_act(BB_A_CHOOSE_DIE, 0, 0, 0));
    stx_apply_ok(&m, &rng, stx_act(BB_A_PUSH_SQUARE, 0, 14, 9));
    stx_apply_ok(&m, &rng, stx_act(BB_A_FOLLOW_UP, 0, 0, 0));
    stx_apply_ok(&m, &rng, stx_act(BB_A_END_ACTIVATION, 0, 0, 0));
    BB_CHECK_EQ(m.players[a0].x, 14); // pushed by the charge blitz
    // END_TURN closes the event: the kick lands (bounce) and the receiving
    // team is active again.
    const uint8_t dice3[] = {1};
    bb_rng_script(&rng, dice3, 1);
    bb_status st2 = fx_apply(&m, stx_act(BB_A_END_TURN, 0, 0, 0), &rng);
    BB_CHECK_EQ(st2, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.active_team, BB_AWAY);
    BB_CHECK(!bb_rng_error(&rng));
}

// "If a selected player Falls Over ... the Charge ends": a failed Rush
// knocks the charging player down and the event ends without further
// activations (and WITHOUT a real turnover for the receiving team's turn).
BB_TEST(struct_kickoff_charge_ends_when_player_falls) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    int h0 = fx_player(&m, 0, 0, 1, 5, 1, 3, 3, 4, 9); // MA 1: rush early
    fx_lineman(&m, 0, 1, 10, 9);
    fx_lineman(&m, 1, 0, 20, 10);
    bb_rng rng;
    const uint8_t dice[] = {2, 3, 5, 5, 1};
    bb_rng_script(&rng, dice, 5);
    fx_run(&m, &rng);
    fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    stx_apply_ok(&m, &rng, stx_act(BB_A_ACTIVATE, h0, 0, 0));
    stx_apply_ok(&m, &rng, stx_act(BB_A_DECLARE, BB_ACT_MOVE, 0, 0));
    stx_apply_ok(&m, &rng, stx_act(BB_A_STEP, 0, 2, 5));
    // Second step = Rush (MA 1): natural 1 -> falls. Armour 2,2 holds.
    // Charge ends; landing bounce d8=1; away turn 1 begins.
    const uint8_t dice2[] = {1, 2, 2, 1};
    bb_rng_script(&rng, dice2, 4);
    bb_status st = fx_apply(&m, stx_act(BB_A_STEP, 0, 3, 5), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[h0].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.active_team, BB_AWAY);  // event over, receiver active
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
    BB_CHECK_EQ(m.turnover, 0);           // the latch must not leak
    BB_CHECK(!bb_rng_error(&rng));
}

// "exactly as if it was their team's Turn": the charging team may spend
// TEAM RE-ROLLS on its charge dice (validated against live FUMBBL replays).
BB_TEST(struct_kickoff_charge_team_reroll_available) {
    bb_match m;
    stx_kickoff_fixture(&m, BB_HOME);
    m.rerolls[0] = m.rerolls_start[0] = 2;
    int h0 = fx_player(&m, 0, 0, 1, 5, 1, 3, 3, 4, 9);
    fx_lineman(&m, 0, 1, 10, 9);
    fx_lineman(&m, 1, 0, 20, 10);
    bb_rng rng;
    const uint8_t dice[] = {2, 3, 5, 5, 1};
    bb_rng_script(&rng, dice, 5);
    fx_run(&m, &rng);
    fx_apply(&m, stx_act(BB_A_KICK_TARGET, 0, 18, 7), &rng);
    stx_apply_ok(&m, &rng, stx_act(BB_A_ACTIVATE, h0, 0, 0));
    stx_apply_ok(&m, &rng, stx_act(BB_A_DECLARE, BB_ACT_MOVE, 0, 0));
    stx_apply_ok(&m, &rng, stx_act(BB_A_STEP, 0, 2, 5));
    const uint8_t dice2[] = {2 /*rush 2+: fail? no — 2 passes... use 1*/};
    (void)dice2;
    const uint8_t dice3[] = {1}; // rush natural 1: fail -> re-roll window
    bb_rng_script(&rng, dice3, 1);
    bb_status st = fx_apply(&m, stx_act(BB_A_STEP, 0, 3, 5), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(fx_find(&m, stx_act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0)) >= 0);
    const uint8_t dice4[] = {6}; // re-rolled rush passes
    bb_rng_script(&rng, dice4, 1);
    st = fx_apply(&m, stx_act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[h0].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[h0].x, 3);
    BB_CHECK_EQ(m.rerolls[0], 1);
    BB_CHECK(!bb_rng_error(&rng));
}
