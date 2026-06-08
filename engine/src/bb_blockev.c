// bb_blockev.c — closed-form block outcome probabilities (see bb_blockev.h).
//
// Mirrors proc_block.c's resolution exactly, in expectation:
//   pool:    block_advance phase 0 (ST + assists, Horns, Cheering Fans latch,
//            Dauntless as a probability mixture over the two pools)
//   faces:   resolve_face (Juggernaut, Wrestle windows, Dodge-vs-Tackle,
//            Strip Ball on pushes, Frenzy's mandatory second block)
//   armour:  armour_advance (MB auto-policy: spent on armour only when it
//            converts a miss into a break; Claws unmodified 8+; IHS;
//            victim-side Chainsaw +3)
//   injury:  injury_advance (Thick Skull deterministic band shift, Stunty
//            bands; KO and CAS both count as removal — apothecary ignored)
//   saves:   Steady Footing (knockdown sticks with P 5/6)
// Choice nodes (die pick, D29 Wrestle windows) resolve by minimax over the
// utility in bb_blockev.h. Any change to proc_block.c's block semantics MUST
// be reflected here; tools/blockev_mc.c is the drift detector (Monte Carlo
// differential vs the real engine).
#include "bb/bb_blockev.h"
#include "bb/bb_skills.h"
#include <stddef.h>
#include "bb/bb_hooks.h"
#include "bb/bb_proc.h"
#include "bb/gen_tables.h"
#include "bb/gen_teams.h"

// --- outcome vector ----------------------------------------------------------
typedef struct {
    float def_down, att_down, def_rem, att_rem, ball_out, turnover;
} ev_vec;

static void vec_add_scaled(ev_vec* dst, const ev_vec* src, float p) {
    dst->def_down += p * src->def_down;
    dst->att_down += p * src->att_down;
    dst->def_rem += p * src->def_rem;
    dst->att_rem += p * src->att_rem;
    dst->ball_out += p * src->ball_out;
    dst->turnover += p * src->turnover;
}

bb_blockev_w bb_blockev_w_default(void) {
    return (bb_blockev_w){0.06f, 0.5f, 0.3f, 0.3f};
}

static float player_cost_100k(const bb_match* m, int slot) {
    // Bounds-clamped: demo-bank states carry raw FUMBBL-derived bytes
    // (panel: team_id/position_id are unvalidated record content — an
    // out-of-range byte must price as a lineman, not read out of bounds).
    int tid = m->team_id[BB_TEAM_OF(slot)];
    if (tid < 0 || tid >= BB_TEAM_COUNT) return 0.5f;
    const bb_team_def* td = &bb_team_defs[tid];
    int pid = m->players[slot].position_id;
    if (pid < 0 || pid >= BB_MAX_POSITIONS) return 0.5f;
    return (float)td->positions[pid].cost_k / 100.0f;
}

static float utility(const ev_vec* v, const bb_blockev_w* w, float cd, float ca) {
    return w->k_kd * (v->def_down - v->att_down) +
           w->k_value * (v->def_rem * cd - v->att_rem * ca) +
           w->k_ball * v->ball_out - w->k_to * v->turnover;
}

// --- armour / injury closed forms ---------------------------------------------

float bb_ev_armour_break(const bb_match* m, int victim, int causer,
                         float* mb_on_injury_out) {
    const bb_player* p = &m->players[victim];
    bool ihs = bb_has_skill(&p->skills, BB_SK_IRON_HARD_SKIN);
    int ext = ihs ? 0 : bb_hook_armour_mod(m, victim, causer);
    if (bb_has_skill(&p->skills, BB_SK_CHAINSAW)) ext += 3; // victim-side, always
    bool mb = !ihs && causer >= 0 &&
              bb_has_skill(&m->players[causer].skills, BB_SK_MIGHTY_BLOW);
    bool claws = !ihs && causer >= 0 &&
                 bb_has_skill(&m->players[causer].skills, BB_SK_CLAWS);
    int av = p->av;
    int n_break = 0, n_mb_unspent = 0;
    for (int d1 = 1; d1 <= 6; d1++) {
        for (int d2 = 1; d2 <= 6; d2++) {
            int total = d1 + d2 + ext;
            bool broken = total >= av;
            bool mb_used = false;
            // Claws BEFORE the MB spend, mirroring armour_advance: a natural
            // 8+ breaks for free and MB stays for the injury roll (panel
            // finding amending D16 — no stacking restriction in the mirror).
            if (!broken && claws && d1 + d2 >= 8) {
                broken = true;
            }
            if (!broken && mb && total + 1 >= av) {
                broken = true; // MB spent converting the miss into a break
                mb_used = true;
            }
            if (broken) {
                n_break++;
                if (mb && !mb_used) n_mb_unspent++;
            }
        }
    }
    if (mb_on_injury_out) {
        *mb_on_injury_out = n_break ? (float)n_mb_unspent / (float)n_break : 0.0f;
    }
    return (float)n_break / 36.0f;
}

// P(injury total leaves the pitch) for one (+0 or +1 MB) injury roll.
static float injury_removal(const bb_match* m, int victim, int causer,
                            int mb_plus) {
    const bb_player* p = &m->players[victim];
    int ext = bb_hook_injury_mod(m, victim, causer) + mb_plus;
    bool stunty = bb_is_stunty(m, victim);
    int stun_max = stunty ? BB_INJ_STUNTY_STUN_MAX : BB_INJ_STUN_MAX;
    int ko_max = stunty ? BB_INJ_STUNTY_KO_MAX : BB_INJ_KO_MAX;
    if (bb_has_skill(&p->skills, BB_SK_THICK_SKULL)) stun_max = ko_max - 1;
    int n_rem = 0;
    for (int d1 = 1; d1 <= 6; d1++) {
        for (int d2 = 1; d2 <= 6; d2++) {
            // KO, Stunty Badly Hurt, and Casualty bands all leave the pitch.
            if (d1 + d2 + ext > stun_max) n_rem++;
        }
    }
    return (float)n_rem / 36.0f;
}

float bb_ev_removal(const bb_match* m, int victim, int causer) {
    float mb_unspent = 0.0f;
    float p_break = bb_ev_armour_break(m, victim, causer, &mb_unspent);
    if (p_break <= 0.0f) return 0.0f;
    float inj = mb_unspent * injury_removal(m, victim, causer, 1) +
                (1.0f - mb_unspent) * injury_removal(m, victim, causer, 0);
    return p_break * inj;
}

// --- pool computation (mirrors block_advance phase 0) --------------------------

static void pool_dice(const bb_match* m, int att, int def, int is_blitz,
                      int dauntless_matched, int no_cheer, int* nd_out,
                      int* def_chooses_out) {
    int base_a = m->players[att].st;
    int base_d = m->players[def].st;
    int st_a = (dauntless_matched ? base_d : base_a) +
               bb_count_assists(m, att, def);
    int att_team = BB_TEAM_OF(att);
    // Cheering Fans is a once-per-turn latch the engine consumes on the
    // FIRST block (proc_block.c zeroes it before computing st_a); the pure
    // evaluator must not re-grant it to the Frenzy second block (panel).
    if (!no_cheer && m->cheer_assist[att_team] && att_team == m->active_team)
        st_a += 1;
    int st_d = base_d + bb_count_assists(m, def, att);
    if (is_blitz) st_a += bb_hook_st_mod_blitz(m, att); // Horns
    int nd = 1;
    int def_chooses = 0;
    if (st_a > st_d) {
        nd = st_a > 2 * st_d ? 3 : 2;
    } else if (st_d > st_a) {
        nd = st_d > 2 * st_a ? 3 : 2;
        def_chooses = 1;
    }
    *nd_out = nd;
    *def_chooses_out = def_chooses;
}

// --- per-face outcome vectors ---------------------------------------------------

typedef struct {
    const bb_match* m;
    const bb_blockev_w* w;
    int att, def, is_blitz;
    int active;        // attacker's team is the active team
    float sf_att, sf_def; // P(knockdown sticks) under Steady Footing
    float rem_att, rem_def; // P(removal | knocked down)
    int att_carrying;
    float cost_att, cost_def; // /100k, for the utility
    int strip_fires;   // Strip Ball strips on any pushback of the carrier
    int dodge_saves;   // Stumble degrades to Push (Dodge minus Tackle)
    int frenzy;        // attacker must throw the mandatory second block
    bb_blockev_policy* cap; // optional choice-policy capture (MC differential)
} ev_ctx;

static int distracted(const bb_match* m, int slot) {
    return (m->players[slot].flags & BB_PF_DISTRACTED) != 0;
}

// Forward: evaluate one whole block (pool + faces) — used for the Frenzy
// second block. carrying: does the defender hold the ball at THIS block.
static void eval_block(const bb_match* m, const bb_blockev_w* w, int att,
                       int def, int is_blitz, int carrying, int frenzy_done,
                       ev_vec* out);

// Push-shaped result (PUSH face, dodged STUMBLE, Juggernaut'd Both Down):
// strip-ball exposure now, then the mandatory Frenzy second block.
static void face_push(const ev_ctx* c, int carrying, int frenzy_done,
                      ev_vec* out) {
    *out = (ev_vec){0};
    int stripped = carrying && c->strip_fires;
    if (stripped) out->ball_out = 1.0f;
    if (c->frenzy && !frenzy_done) {
        ev_vec second;
        eval_block(c->m, c->w, c->att, c->def, c->is_blitz,
                   carrying && !stripped, 1, &second);
        vec_add_scaled(out, &second, 1.0f);
    }
}

// POW-shaped result: pushback (strip exposure) + knockdown.
static void face_pow(const ev_ctx* c, int carrying, ev_vec* out) {
    *out = (ev_vec){0};
    out->def_down = c->sf_def;
    out->def_rem = c->sf_def * c->rem_def;
    if (carrying) {
        // Stripped at the pushback regardless of the knockdown save;
        // otherwise the ball drops only if the knockdown sticks.
        out->ball_out = c->strip_fires ? 1.0f : c->sf_def;
    }
}

static void face_skull(const ev_ctx* c, ev_vec* out) {
    *out = (ev_vec){0};
    out->att_down = c->sf_att;
    out->att_rem = c->sf_att * c->rem_att;
    if (c->active) out->turnover = c->sf_att;
}

static void face_both_down(const ev_ctx* c, int carrying, int frenzy_done,
                           ev_vec* out) {
    // Juggernaut (attacker, blitz): Both Down becomes a Push and cancels the
    // defender's Wrestle for this block.
    if (c->is_blitz &&
        bb_has_skill(&c->m->players[c->att].skills, BB_SK_JUGGERNAUT)) {
        face_push(c, carrying, frenzy_done, out);
        return;
    }
    // Plain Both Down (Block keeps a player up; both knockdowns resolve).
    ev_vec plain = {0};
    float att_down =
        (bb_has_block(c->m, c->att) && !distracted(c->m, c->att)) ? 0.0f
                                                                  : c->sf_att;
    float def_down =
        (bb_has_block(c->m, c->def) && !distracted(c->m, c->def)) ? 0.0f
                                                                  : c->sf_def;
    plain.att_down = att_down;
    plain.def_down = def_down;
    plain.att_rem = att_down * c->rem_att;
    plain.def_rem = def_down * c->rem_def;
    if (carrying) plain.ball_out = def_down; // no push: no Strip Ball
    if (c->active) plain.turnover = att_down;
    // Wrestle: both Placed Prone, no armour, no knockdown turnover. A
    // carrier placed prone drops the ball; an ACTIVE carrier placed prone IS
    // a turnover (both_down_wrestle).
    ev_vec wrestle = {0};
    if (carrying) wrestle.ball_out = 1.0f;
    if (c->att_carrying && c->active) wrestle.turnover = 1.0f;

    int att_w = bb_has_wrestle(c->m, c->att) && !distracted(c->m, c->att);
    int def_w = bb_has_wrestle(c->m, c->def) && !distracted(c->m, c->def);
    float u_plain = utility(&plain, c->w, c->cost_def, c->cost_att);
    float u_wrestle = utility(&wrestle, c->w, c->cost_def, c->cost_att);
    // FFB order (D29/D31): attacker's window first, then the defender's.
    // Defender (minimizer) picks between wrestle and plain.
    int def_uses = def_w && u_wrestle < u_plain;
    const ev_vec* def_choice = def_uses ? &wrestle : &plain;
    float u_def_choice = def_uses ? u_wrestle : u_plain;
    // Attacker (maximizer) picks between wrestle and the defender's line.
    int att_uses = att_w && u_wrestle > u_def_choice;
    if (c->cap) {
        c->cap->att_wrestles = att_uses;
        c->cap->def_wrestles = def_uses;
    }
    if (att_uses) {
        *out = wrestle;
    } else {
        *out = *def_choice;
    }
}

// --- whole-block evaluation -----------------------------------------------------

// Face indices follow bb_block_die: 1 skull, 2 both-down, 3/4 push,
// 5 stumble, 6 pow.
static void eval_pool(const ev_ctx* c, int nd, int def_chooses, int carrying,
                      int frenzy_done, ev_vec* out) {
    ev_vec fv[7];
    float fu[7];
    face_skull(c, &fv[BB_BD_ATTACKER_DOWN]);
    face_both_down(c, carrying, frenzy_done, &fv[BB_BD_BOTH_DOWN]);
    face_push(c, carrying, frenzy_done, &fv[BB_BD_PUSH_1]);
    fv[BB_BD_PUSH_2] = fv[BB_BD_PUSH_1];
    if (c->dodge_saves) {
        fv[BB_BD_STUMBLE] = fv[BB_BD_PUSH_1];
    } else {
        face_pow(c, carrying, &fv[BB_BD_STUMBLE]);
        if (c->frenzy && !frenzy_done) {
            // A non-dodged stumble still pushes back, but the defender is
            // down: no second block (Frenzy needs them standing). Nothing to
            // add — face_pow already excludes the chain.
        }
    }
    face_pow(c, carrying, &fv[BB_BD_POW]);
    for (int f = 1; f <= 6; f++) {
        fu[f] = utility(&fv[f], c->w, c->cost_def, c->cost_att);
    }
    // Exact enumeration over all 6^nd pools (max 216): the chooser takes the
    // best rolled face by utility (attacker max, defender min). Enumeration
    // (vs the closed-form rank formula it replaced) lets pool TRANSFORMS be
    // modeled exactly — Brawler's engine auto-policy (proc_block.c phase 0:
    // reroll the first Both Down when the pool has no push/stumble/pow,
    // regardless of who picks) becomes a 1/6-weighted redraw branch.
    int brawler =
        bb_has_skill(&c->m->players[c->att].skills, BB_SK_BRAWLER);
    int total = 1;
    for (int k = 0; k < nd; k++) total *= 6;
    *out = (ev_vec){0};
    float w = 1.0f / (float)total;
    for (int pool = 0; pool < total; pool++) {
        int d[3] = {0, 0, 0}; // gcc -Werror=maybe-uninitialized
        int rem = pool;
        for (int k = 0; k < nd; k++) {
            d[k] = rem % 6 + 1;
            rem /= 6;
        }
        int better = 0, bd_idx = -1;
        for (int k = 0; k < nd; k++) {
            if (d[k] >= BB_BD_PUSH_1) better = 1; // push/stumble/pow
            if (d[k] == BB_BD_BOTH_DOWN && bd_idx < 0) bd_idx = k;
        }
        if (brawler && bd_idx >= 0 && !better) {
            for (int r = 1; r <= 6; r++) { // redraw the first Both Down
                d[bd_idx] = r;
                int best = d[0];
                for (int k = 1; k < nd; k++) {
                    if (def_chooses ? fu[d[k]] < fu[best] : fu[d[k]] > fu[best])
                        best = d[k];
                }
                vec_add_scaled(out, &fv[best], w / 6.0f);
            }
            continue;
        }
        int best = d[0];
        for (int k = 1; k < nd; k++) {
            if (def_chooses ? fu[d[k]] < fu[best] : fu[d[k]] > fu[best])
                best = d[k];
        }
        vec_add_scaled(out, &fv[best], w);
    }
}

static void init_ctx(ev_ctx* cp, const bb_match* m, const bb_blockev_w* w,
                     int att, int def, int is_blitz);

static void eval_block(const bb_match* m, const bb_blockev_w* w, int att,
                       int def, int is_blitz, int carrying, int frenzy_done,
                       ev_vec* out) {
    ev_ctx c;
    init_ctx(&c, m, w, att, def, is_blitz);

    int base_a = m->players[att].st;
    int base_d = m->players[def].st;
    int dauntless = bb_has_skill(&m->players[att].skills, BB_SK_DAUNTLESS) &&
                    base_d > base_a;
    *out = (ev_vec){0};
    if (dauntless) {
        int diff = base_d - base_a; // d6 + base_a > base_d  <=>  d6 > diff
        float p_match = (float)(diff >= 6 ? 0 : 6 - diff) / 6.0f;
        int nd, dc;
        ev_vec v;
        pool_dice(m, att, def, is_blitz, 1, frenzy_done, &nd, &dc);
        eval_pool(&c, nd, dc, carrying, frenzy_done, &v);
        vec_add_scaled(out, &v, p_match);
        pool_dice(m, att, def, is_blitz, 0, frenzy_done, &nd, &dc);
        eval_pool(&c, nd, dc, carrying, frenzy_done, &v);
        vec_add_scaled(out, &v, 1.0f - p_match);
    } else {
        int nd, dc;
        pool_dice(m, att, def, is_blitz, 0, frenzy_done, &nd, &dc);
        eval_pool(&c, nd, dc, carrying, frenzy_done, out);
    }
}

static void init_ctx(ev_ctx* cp, const bb_match* m, const bb_blockev_w* w,
                     int att, int def, int is_blitz) {
    ev_ctx c;
    c.m = m;
    c.w = w;
    c.att = att;
    c.def = def;
    c.is_blitz = is_blitz;
    c.active = BB_TEAM_OF(att) == m->active_team;
    c.sf_att = bb_has_skill(&m->players[att].skills, BB_SK_STEADY_FOOTING)
                   ? 5.0f / 6.0f
                   : 1.0f;
    c.sf_def = bb_has_skill(&m->players[def].skills, BB_SK_STEADY_FOOTING)
                   ? 5.0f / 6.0f
                   : 1.0f;
    c.rem_att = bb_ev_removal(m, att, def);
    c.rem_def = bb_ev_removal(m, def, att);
    c.att_carrying = (m->players[att].flags & BB_PF_HAS_BALL) != 0;
    c.cost_att = player_cost_100k(m, att);
    c.cost_def = player_cost_100k(m, def);
    // Strip Ball strips on any pushback unless the carrier is immune
    // (Monstrous Mouth or Sure Hands — both carry the "cannot be used
    // against this player" clause) or can (and so will) Stand Firm the
    // pushback away. A Juggernaut BLITZ cancels Stand Firm (mirror text;
    // proc_block.c push_advance's !jugg gate), so the decline is off then.
    int sf_declines =
        bb_has_skill(&m->players[def].skills, BB_SK_STAND_FIRM) &&
        !distracted(m, def) &&
        !(is_blitz &&
          bb_has_skill(&m->players[att].skills, BB_SK_JUGGERNAUT));
    c.strip_fires =
        bb_has_skill(&m->players[att].skills, BB_SK_STRIP_BALL) &&
        !bb_has_skill(&m->players[def].skills, BB_SK_MONSTROUS_MOUTH) &&
        !bb_has_skill(&m->players[def].skills, BB_SK_SURE_HANDS) &&
        !sf_declines;
    c.dodge_saves = bb_has_dodge_skill(m, def) && !distracted(m, def) &&
                    !bb_has_skill(&m->players[att].skills, BB_SK_TACKLE);
    // Frenzy's mandatory second block requires post-push adjacency, which
    // the resolver only reaches via the forced follow-up (proc_block.c
    // phase 3/5): Fend forbids the follow-up (Juggernaut-on-blitz cancels
    // Fend; Frenzy does NOT), and a Rooted attacker can't move — either way
    // the second block never happens (panel: pricing it anyway inflated
    // p_def_down ~8pp on every Frenzy-vs-Fend matchup).
    int fend_stops =
        (bb_hook_push_flags(m, def) & BB_PUSHF_FEND) &&
        !(is_blitz &&
          bb_has_skill(&m->players[att].skills, BB_SK_JUGGERNAUT));
    c.frenzy = bb_has_skill(&m->players[att].skills, BB_SK_FRENZY) &&
               !fend_stops && !(m->players[att].flags & BB_PF_ROOTED);
    c.cap = NULL;
    *cp = c;
}

void bb_block_ev_policy(const bb_match* m, int att, int def, int is_blitz,
                        int frenzy_done, const bb_blockev_w* w,
                        bb_blockev_policy* out) {
    bb_blockev_w wd;
    if (!w) {
        wd = bb_blockev_w_default();
        w = &wd;
    }
    ev_ctx c;
    init_ctx(&c, m, w, att, def, is_blitz);
    out->att_wrestles = 0;
    out->def_wrestles = 0;
    c.cap = out; // face_both_down records the Wrestle-window minimax
    int carrying = (m->players[def].flags & BB_PF_HAS_BALL) != 0;
    ev_vec fv[7];
    face_skull(&c, &fv[BB_BD_ATTACKER_DOWN]);
    face_both_down(&c, carrying, frenzy_done, &fv[BB_BD_BOTH_DOWN]);
    face_push(&c, carrying, frenzy_done, &fv[BB_BD_PUSH_1]);
    fv[BB_BD_PUSH_2] = fv[BB_BD_PUSH_1];
    if (c.dodge_saves) {
        fv[BB_BD_STUMBLE] = fv[BB_BD_PUSH_1];
    } else {
        face_pow(&c, carrying, &fv[BB_BD_STUMBLE]);
    }
    face_pow(&c, carrying, &fv[BB_BD_POW]);
    out->face_u[0] = 0.0f;
    for (int f = 1; f <= 6; f++) {
        out->face_u[f] = utility(&fv[f], w, c.cost_def, c.cost_att);
    }
}

void bb_block_ev(const bb_match* m, int att, int def, int is_blitz,
                 const bb_blockev_w* w, bb_blockev* out) {
    bb_blockev_w wd;
    if (!w) {
        wd = bb_blockev_w_default();
        w = &wd;
    }
    int carrying = (m->players[def].flags & BB_PF_HAS_BALL) != 0;
    ev_vec v;
    eval_block(m, w, att, def, is_blitz, carrying, 0, &v);
    out->p_def_down = v.def_down;
    out->p_att_down = v.att_down;
    out->p_def_removed = v.def_rem;
    out->p_att_removed = v.att_rem;
    out->p_ball_out = v.ball_out;
    out->p_turnover = v.turnover;
}
