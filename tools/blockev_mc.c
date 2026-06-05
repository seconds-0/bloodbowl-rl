// blockev_mc.c — Monte Carlo differential between the REAL engine's block
// resolution (proc_block.c, random dice) and the closed-form declaration-time
// probabilities (bb_blockev.c). The drift detector for Profile C: any change
// to block semantics that bb_blockev doesn't mirror shows up as a frequency
// mismatch here long before it corrupts a training run.
//
// Method: for each battery matchup, query the closed form once, then resolve
// N real blocks where every choice node (die pick, Wrestle windows, Stand
// Firm) is decided by the SAME policy the closed form assumes
// (bb_block_ev_policy). Empirical frequencies must match the closed form
// within 5 sigma + 1e-3.
//
// Build/run: make blockev-mc   (exit 0 = all matchups agree)
#include "bb/bb_match.h"
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb/bb_blockev.h"
#include "bb_fixtures.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

#define TRIALS 100000

typedef struct {
    const char* name;
    int att_st, def_st;
    int att_skills[4], def_skills[4]; // 0-terminated
    int def_carries;
    int is_blitz;
    int helper; // extra home player adjacent to def (offensive assist)
} mc_case;

static const mc_case CASES[] = {
    {"1d_no_skills", 3, 3, {0}, {0}, 0, 0, 0},
    {"2d_no_skills", 4, 3, {0}, {0}, 0, 0, 0},
    {"2dB_vs_block", 4, 3, {BB_SK_BLOCK, 0}, {BB_SK_BLOCK, 0}, 0, 0, 0},
    {"3d_noB_vs_block", 7, 3, {0}, {BB_SK_BLOCK, 0}, 0, 0, 0},
    {"def_chooses_2d", 3, 4, {BB_SK_BLOCK, 0}, {BB_SK_BLOCK, 0}, 0, 0, 0},
    {"dodge_def", 3, 3, {0}, {BB_SK_DODGE, 0}, 0, 0, 0},
    {"dodge_vs_tackle", 3, 3, {BB_SK_TACKLE, 0}, {BB_SK_DODGE, 0}, 0, 0, 0},
    {"strip_ball_carrier", 3, 3, {BB_SK_STRIP_BALL, 0}, {0}, 1, 0, 0},
    {"wrestle_def_declines", 3, 3, {0}, {BB_SK_WRESTLE, 0}, 0, 0, 0},
    {"wrestle_def_uses", 3, 3, {BB_SK_BLOCK, 0}, {BB_SK_WRESTLE, 0}, 0, 0, 0},
    {"mighty_blow", 4, 3, {BB_SK_MIGHTY_BLOW, 0}, {0}, 0, 0, 0},
    {"claws_av9", 4, 3, {BB_SK_CLAWS, 0}, {0}, 0, 0, 0},
    {"thick_skull_def", 4, 3, {BB_SK_MIGHTY_BLOW, 0}, {BB_SK_THICK_SKULL, 0}, 0, 0, 0},
    {"dauntless_st3v5", 3, 5, {BB_SK_DAUNTLESS, 0}, {0}, 0, 0, 0},
    {"frenzy_1d", 3, 3, {BB_SK_FRENZY, 0}, {0}, 0, 0, 0},
    {"juggernaut_blitz_vs_wrestle", 4, 3, {BB_SK_JUGGERNAUT, 0}, {BB_SK_WRESTLE, 0}, 0, 1, 0},
    {"assist_2d", 3, 3, {0}, {0}, 0, 0, 1},
    {"steady_footing_def", 4, 3, {0}, {BB_SK_STEADY_FOOTING, 0}, 0, 0, 0},
    // Panel-fix batteries (adversarial review wf_13fb2bd1):
    {"mb_claws_av9", 4, 3, {BB_SK_MIGHTY_BLOW, BB_SK_CLAWS, 0}, {0}, 0, 0, 0},
    {"strip_vs_sure_hands", 3, 3, {BB_SK_STRIP_BALL, 0}, {BB_SK_SURE_HANDS, 0}, 1, 0, 0},
    {"jugg_blitz_strips_sf_carrier", 3, 3, {BB_SK_STRIP_BALL, BB_SK_JUGGERNAUT, 0}, {BB_SK_STAND_FIRM, 0}, 1, 1, 0},
    {"brawler_1d", 3, 3, {BB_SK_BRAWLER, 0}, {0}, 0, 0, 0},
    {"brawler_2d_vs_block", 4, 3, {BB_SK_BRAWLER, 0}, {BB_SK_BLOCK, 0}, 0, 0, 0},
    {"frenzy_vs_fend", 3, 3, {BB_SK_FRENZY, 0}, {BB_SK_FEND, 0}, 0, 0, 0},
    {"frenzy_2d", 4, 3, {BB_SK_FRENZY, 0}, {0}, 0, 0, 0},
};

typedef struct {
    double def_down, att_down, def_rem, att_rem, ball_out, turnover;
} tally;

static int run_case(const mc_case* tc) {
    bb_match base;
    fx_match_midturn(&base, BB_HOME, 0);
    int att = fx_player(&base, BB_HOME, 0, 10, 7, 6, tc->att_st, 3, 4, 9);
    int def = fx_player(&base, BB_AWAY, 0, 11, 7, 6, tc->def_st, 3, 4, 9);
    // Far-away home bystander: keeps the team turn alive after the block so
    // an active-team flip can only mean a turnover.
    fx_lineman(&base, BB_HOME, 2, 3, 3);
    if (tc->helper) fx_lineman(&base, BB_HOME, 1, 11, 6);
    for (int i = 0; tc->att_skills[i]; i++) fx_give_skill(&base, att, tc->att_skills[i]);
    for (int i = 0; tc->def_skills[i]; i++) fx_give_skill(&base, def, tc->def_skills[i]);
    if (tc->def_carries) fx_ball_held(&base, def);
    // Run TEAM_TURN's turn_start bookkeeping NOW: it clears the turnover
    // latch (proc_turn.c), so injecting a block before it runs would wipe
    // the very turnover evidence this differential measures.
    bb_rng r0;
    bb_rng_seed(&r0, 1, 1);
    if (fx_run(&base, &r0) != BB_STATUS_DECISION) {
        printf("FAIL %-28s fixture did not reach the activation decision\n",
               tc->name);
        return 1;
    }

    bb_blockev ev;
    bb_block_ev(&base, att, def, tc->is_blitz, NULL, &ev);

    tally t = {0};
    for (int trial = 0; trial < TRIALS; trial++) {
        bb_match m = base;
        bb_rng rng;
        bb_rng_seed(&rng, 0x5EEDu + (uint64_t)trial * 2654435761u, 9);
        int base_depth = m.stack_top;
        bb_push(&m, BB_PROC_BLOCK, att, def, 0, 0);
        if (tc->is_blitz) bb_top(&m)->data |= 1 << 13; // BLK_IS_BLITZ
        m.status = BB_STATUS_RUNNING; // clear the parked activation decision
        int wrestled = 0;
        int blocks_resolved = 0; // CHOOSE_DIE count: >=1 => frenzy 2nd block
        bb_status st = bb_advance(&m, &rng);
        while (st == BB_STATUS_DECISION && m.stack_top > base_depth) {
            const bb_frame* f = &m.stack[m.stack_top - 1];
            bb_action legal[BB_LEGAL_MAX];
            int n = bb_legal_actions(&m, legal);
            if (n <= 0) break;
            bb_action pick = legal[0];
            if (f->proc == BB_PROC_BLOCK &&
                (f->phase == 2 || f->phase == 4 || f->phase == 5)) {
                // Recompute the choice policy from the CURRENT state with the
                // matching frenzy_done — the second block's positions and
                // carrying state differ from declaration time (panel: reusing
                // the first block's utilities tested the wrong policy).
                bb_blockev_policy pol;
                bb_block_ev_policy(&m, att, def, tc->is_blitz,
                                   blocks_resolved >= 1, NULL, &pol);
                if (f->phase == 2) {
                    int def_chooses = (f->data >> 11) & 1;
                    float best = def_chooses ? 1e9f : -1e9f;
                    for (int i = 0; i < n; i++) {
                        int face = (f->data >> (3 * legal[i].arg)) & 7;
                        float u = pol.face_u[face];
                        if (def_chooses ? u < best : u > best) {
                            best = u;
                            pick = legal[i];
                        }
                    }
                    blocks_resolved++;
                } else {
                    int use =
                        f->phase == 4 ? pol.att_wrestles : pol.def_wrestles;
                    for (int i = 0; i < n; i++) {
                        if (legal[i].type ==
                            (use ? BB_A_USE_SKILL : BB_A_DECLINE_SKILL)) {
                            pick = legal[i];
                        }
                    }
                    if (use) wrestled = 1;
                }
            }
            // Everything else (push square, follow-up, Stand Firm windows the
            // battery never reaches): first legal action.
            st = bb_apply(&m, pick, &rng);
        }
        if (st == BB_STATUS_ERROR) {
            printf("FAIL %-28s trial %d: engine error state\n", tc->name, trial);
            return 1;
        }
        const bb_player* pa = &m.players[att];
        const bb_player* pd = &m.players[def];
        int def_off = pd->location == BB_LOC_KO || pd->location == BB_LOC_CAS;
        int att_off = pa->location == BB_LOC_KO || pa->location == BB_LOC_CAS;
        if (!wrestled) {
            t.def_down += def_off || pd->stance != BB_STANCE_STANDING;
            t.att_down += att_off || pa->stance != BB_STANCE_STANDING;
        }
        t.def_rem += def_off;
        t.att_rem += att_off;
        if (tc->def_carries) t.ball_out += m.ball.carrier != (uint8_t)def;
        // Turnover <=> the home turn ended: active flipped to the away team,
        // OR — when the lone away defender is stunned/removed and their turn
        // ends instantly with no activatable player — home's turn counter
        // advanced past 1 (the far bystander keeps home's turn alive through
        // anything except a turnover).
        t.turnover += m.turnover || m.active_team != BB_HOME ||
                      m.turn[BB_HOME] > 1;
    }

    struct {
        const char* what;
        double emp;
        float closed;
    } rows[] = {
        {"def_down", t.def_down / TRIALS, ev.p_def_down},
        {"att_down", t.att_down / TRIALS, ev.p_att_down},
        {"def_removed", t.def_rem / TRIALS, ev.p_def_removed},
        {"att_removed", t.att_rem / TRIALS, ev.p_att_removed},
        {"ball_out", t.ball_out / TRIALS, ev.p_ball_out},
        {"turnover", t.turnover / TRIALS, ev.p_turnover},
    };
    int fails = 0;
    for (int i = 0; i < 6; i++) {
        double p = rows[i].closed;
        double sigma = sqrt(p * (1.0 - p) / TRIALS);
        double tol = 5.0 * sigma + 1e-3;
        double diff = fabs(rows[i].emp - p);
        if (diff > tol) {
            printf("FAIL %-28s %-12s closed %.5f empirical %.5f (diff %.5f > tol %.5f)\n",
                   tc->name, rows[i].what, p, rows[i].emp, diff, tol);
            fails++;
        }
    }
    if (!fails) {
        printf("ok   %-28s (dd %.4f ad %.4f dr %.4f ar %.4f bo %.4f to %.4f)\n",
               tc->name, ev.p_def_down, ev.p_att_down, ev.p_def_removed,
               ev.p_att_removed, ev.p_ball_out, ev.p_turnover);
    }
    return fails;
}

int main(void) {
    int fails = 0;
    int n = (int)(sizeof(CASES) / sizeof(CASES[0]));
    for (int i = 0; i < n; i++) fails += run_case(&CASES[i]);
    printf("blockev_mc: %d matchups x %d trials, %d failures\n", n, TRIALS, fails);
    return fails ? 1 : 0;
}
