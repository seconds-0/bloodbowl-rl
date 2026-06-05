// test_blockev.c — acceptance suite for the closed-form block-EV engine
// (bb_blockev.c). Every expected value below is hand-derived from the face
// tree; the Addendum-3 turnover inversion (docs/reward-audit-decision-time.md)
// is the mandatory case: 2d-with-Block must price LOWER turnover risk than
// 3d-without-Block — naive dice-count heuristics invert this.
#include "bb_test.h"
#include "bb_fixtures.h"
#include "bb/bb_blockev.h"

#define EV_NEAR(a, b) BB_CHECK((a) > (b) - 1e-5f && (a) < (b) + 1e-5f)

// Standard fixture: mid-turn, attacker = home slot 0 at (10,7), defender =
// away slot 0 at (11,7). Stats default to linemen (ST3 AV9); tweak after.
static void ev_fixture(bb_match* m, int* att, int* def) {
    fx_match_midturn(m, BB_HOME, 0);
    *att = fx_lineman(m, BB_HOME, 0, 10, 7);
    *def = fx_lineman(m, BB_AWAY, 0, 11, 7);
}

// --- Addendum 3: the turnover inversion (MANDATORY) ---------------------------

BB_TEST(blockev_addendum3_turnover_inversion) {
    bb_match m;
    int att, def;
    bb_blockev ev2, ev3;

    // 2d WITH Block vs a Block defender: only skull-skull turns over.
    ev_fixture(&m, &att, &def);
    m.players[att].st = 4; // 2 dice, attacker chooses
    fx_give_skill(&m, att, BB_SK_BLOCK);
    fx_give_skill(&m, def, BB_SK_BLOCK);
    bb_block_ev(&m, att, def, 0, NULL, &ev2);
    EV_NEAR(ev2.p_turnover, 1.0f / 36.0f); // 2.78%

    // 3d WITHOUT Block vs a Block defender: skull AND both-down turn over.
    ev_fixture(&m, &att, &def);
    m.players[att].st = 7; // > 2x ST3: 3 dice, attacker chooses
    fx_give_skill(&m, def, BB_SK_BLOCK);
    bb_block_ev(&m, att, def, 0, NULL, &ev3);
    EV_NEAR(ev3.p_turnover, 1.0f / 27.0f); // 3.70%

    // MORE dice, MORE turnover risk — the inversion the spec demands.
    BB_CHECK(ev3.p_turnover > ev2.p_turnover);
}

// --- core face arithmetic ------------------------------------------------------

BB_TEST(blockev_1d_no_skills) {
    bb_match m;
    int att, def;
    ev_fixture(&m, &att, &def);
    bb_blockev ev;
    bb_block_ev(&m, att, def, 0, NULL, &ev);
    // 1 die, no skills: def down on both-down/stumble/pow (3/6); att down on
    // skull/both-down (2/6); active attacker's knockdown = turnover.
    EV_NEAR(ev.p_def_down, 3.0f / 6.0f);
    EV_NEAR(ev.p_att_down, 2.0f / 6.0f);
    EV_NEAR(ev.p_turnover, 2.0f / 6.0f);
    EV_NEAR(ev.p_ball_out, 0.0f); // not carrying
}

BB_TEST(blockev_2d_chooser_dominance) {
    bb_match m;
    int att, def;
    ev_fixture(&m, &att, &def);
    m.players[att].st = 4; // 2d attacker chooses
    bb_blockev ev;
    bb_block_ev(&m, att, def, 0, NULL, &ev);
    // Chooser prefers stumble/pow (def down, 20/36 = any die in {5,6}); when
    // the pool is only {skull, both-down} it picks both-down — which ALSO
    // downs the skill-less defender: +(4-1)/36. Total 23/36.
    EV_NEAR(ev.p_def_down, 23.0f / 36.0f);
    // No Block: both-down still turns over, so turnover = P(both in {1,2}).
    EV_NEAR(ev.p_turnover, (2.0f / 6.0f) * (2.0f / 6.0f)); // 1/9
}

BB_TEST(blockev_def_chooses_minimizes) {
    bb_match m;
    int att, def;
    ev_fixture(&m, &att, &def);
    m.players[def].st = 4; // 2d defender chooses
    fx_give_skill(&m, att, BB_SK_BLOCK);
    fx_give_skill(&m, def, BB_SK_BLOCK);
    bb_blockev ev;
    bb_block_ev(&m, att, def, 0, NULL, &ev);
    // Defender picks any rolled skull: turnover = P(at least one skull).
    EV_NEAR(ev.p_turnover, 1.0f - (5.0f / 6.0f) * (5.0f / 6.0f)); // 11/36
    // Defender goes down only when forced: both dice in {stumble, pow}.
    EV_NEAR(ev.p_def_down, (2.0f / 6.0f) * (2.0f / 6.0f)); // 1/9
}

// --- skill transforms ----------------------------------------------------------

BB_TEST(blockev_dodge_vs_tackle) {
    bb_match m;
    int att, def;
    ev_fixture(&m, &att, &def);
    fx_give_skill(&m, def, BB_SK_DODGE);
    bb_blockev ev;
    bb_block_ev(&m, att, def, 0, NULL, &ev);
    // Dodge degrades stumble to push: def down on both-down/pow only.
    EV_NEAR(ev.p_def_down, 2.0f / 6.0f);

    fx_give_skill(&m, att, BB_SK_TACKLE); // cancels Dodge's save
    bb_block_ev(&m, att, def, 0, NULL, &ev);
    EV_NEAR(ev.p_def_down, 3.0f / 6.0f);
}

BB_TEST(blockev_strip_ball_prices_pushes) {
    bb_match m;
    int att, def;
    ev_fixture(&m, &att, &def);
    fx_ball_held(&m, def);
    bb_blockev ev;
    bb_block_ev(&m, att, def, 0, NULL, &ev);
    // No Strip Ball: the ball comes out only on a knockdown (BD/stumble/pow).
    EV_NEAR(ev.p_ball_out, 3.0f / 6.0f);

    fx_give_skill(&m, att, BB_SK_STRIP_BALL);
    bb_block_ev(&m, att, def, 0, NULL, &ev);
    // Strip Ball: pushes strip too — only the skull face keeps the ball.
    // "Roughly doubles dislodge odds with no knockdown required" (spec).
    EV_NEAR(ev.p_ball_out, 5.0f / 6.0f);
}

BB_TEST(blockev_wrestle_d29_decline_judgment) {
    bb_match m;
    int att, def;
    bb_blockev ev;

    // Wrestle defender vs Block-LESS attacker: declining forces the
    // attacker-down turnover — both-down stays a turnover face (D29).
    ev_fixture(&m, &att, &def);
    fx_give_skill(&m, def, BB_SK_WRESTLE);
    bb_block_ev(&m, att, def, 0, NULL, &ev);
    EV_NEAR(ev.p_turnover, 2.0f / 6.0f); // skull + declined both-down
    EV_NEAR(ev.p_def_down, 3.0f / 6.0f); // takes the mutual knockdown

    // Same defender vs a Block attacker: now plain both-down only hurts the
    // defender, so the owner USES Wrestle (no knockdown either side).
    ev_fixture(&m, &att, &def);
    fx_give_skill(&m, def, BB_SK_WRESTLE);
    fx_give_skill(&m, att, BB_SK_BLOCK);
    bb_block_ev(&m, att, def, 0, NULL, &ev);
    EV_NEAR(ev.p_def_down, 2.0f / 6.0f); // stumble/pow only — BD wrestled away
    EV_NEAR(ev.p_turnover, 1.0f / 6.0f); // skull only
}

// --- armour / removal closed forms -----------------------------------------------

BB_TEST(blockev_armour_break_av9) {
    bb_match m;
    int att, def;
    ev_fixture(&m, &att, &def);
    float mb_unspent = -1.0f;
    // Plain AV9: P(2d6 >= 9) = 10/36.
    EV_NEAR(bb_ev_armour_break(&m, def, att, &mb_unspent), 10.0f / 36.0f);
    EV_NEAR(mb_unspent, 0.0f); // no Mighty Blow in play

    // Mighty Blow attacker: 8-totals convert (MB spent), 9+ keep MB for
    // injury. P(break) = 15/36; P(MB unspent | break) = 10/15.
    fx_give_skill(&m, att, BB_SK_MIGHTY_BLOW);
    EV_NEAR(bb_ev_armour_break(&m, def, att, &mb_unspent), 15.0f / 36.0f);
    EV_NEAR(mb_unspent, 10.0f / 15.0f);
}

BB_TEST(blockev_removal_av9) {
    bb_match m;
    int att, def;
    ev_fixture(&m, &att, &def);
    // Plain: P(break 10/36) x P(injury > 7: 15/36) = 150/1296.
    EV_NEAR(bb_ev_removal(&m, def, att), 150.0f / 1296.0f);

    // Mighty Blow: (1/36)[10 * 21/36 + 5 * 15/36] = 285/1296.
    fx_give_skill(&m, att, BB_SK_MIGHTY_BLOW);
    EV_NEAR(bb_ev_removal(&m, def, att), 285.0f / 1296.0f);
}

BB_TEST(blockev_thick_skull_band) {
    bb_match m;
    int att, def;
    ev_fixture(&m, &att, &def);
    fx_give_skill(&m, def, BB_SK_THICK_SKULL);
    // Thick Skull: stun band extends to ko_max-1=8; removal = P(2d6 >= 9).
    EV_NEAR(bb_ev_removal(&m, def, att), (10.0f / 36.0f) * (10.0f / 36.0f));
}

// --- Frenzy and assists ----------------------------------------------------------

BB_TEST(blockev_frenzy_compounds) {
    bb_match m;
    int att, def;
    ev_fixture(&m, &att, &def);
    fx_give_skill(&m, att, BB_SK_FRENZY);
    bb_blockev ev;
    bb_block_ev(&m, att, def, 0, NULL, &ev);
    // Push (2/6) chains a mandatory second 1d block (same-pool approx):
    // def_down = 3/6 + (2/6)(3/6) = 2/3; att exposure compounds too.
    EV_NEAR(ev.p_def_down, 3.0f / 6.0f + (2.0f / 6.0f) * (3.0f / 6.0f));
    EV_NEAR(ev.p_att_down, 2.0f / 6.0f + (2.0f / 6.0f) * (2.0f / 6.0f));
}

BB_TEST(blockev_assists_shift_pool) {
    bb_match m;
    int att, def;
    ev_fixture(&m, &att, &def);
    // An unmarked teammate adjacent to the defender: offensive assist -> 2d.
    fx_lineman(&m, BB_HOME, 1, 11, 6);
    bb_blockev ev;
    bb_block_ev(&m, att, def, 0, NULL, &ev);
    // Same as the 2d no-skill case: turnover (both in {skull, BD}) = 1/9.
    EV_NEAR(ev.p_turnover, 1.0f / 9.0f);
    EV_NEAR(ev.p_def_down, 23.0f / 36.0f);
}
