// proc_test.c — the generic D6 test with reroll window.
//
// Frame layout: a = player slot, b = bb_test_kind, x = needed target (2..6,
// already including modifiers via bb_test_target), y = the test ctx's
// `other` slot + 1 (0 = none; interceptions carry the thrower so re-roll
// grants can tell them apart from catches — review M11), data bits:
//   bit0: team reroll consumed for this test
//   bit1: skill reroll consumed for this test
//   bit2: a reroll decision is pending
//   bit3: loner gate pending (rolled when team reroll chosen)
// Pops with m->ret = 1 (pass) or 0 (fail).
//
// Natural 1 always fails; natural 6 always succeeds (BB2025; the May 2026
// errata removed the "modified below 1" floor — only targets are clamped).
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb/bb_hooks.h"

enum {
    TF_TEAM_USED = 1 << 0,
    TF_SKILL_USED = 1 << 1,
    TF_WAITING = 1 << 2,
};

static bool test_pass(int die, int target) {
    if (die == 1) return false;
    if (die == 6) return true;
    return die >= target;
}

// Rebuild the re-roll-relevant test ctx (kind / player / other) from the
// frame; `other` is stashed in frame y as slot + 1 (0 = none).
static bb_ctx test_ctx(const bb_frame* f) {
    bb_ctx c = {f->b, f->a, (uint8_t)(f->y ? f->y - 1 : BB_NO_PLAYER), f->a,
                0, 0, 0, 0, -1, 0};
    return c;
}

static bool team_reroll_available(const bb_match* m, int team) {
    // BB2025: any number of team re-rolls per turn; only during your own team
    // turn, and never re-rolling the same die twice (per-frame TF_TEAM_USED).
    // The kick-off precedes turn 1: MATCH sets active_team to the receiver
    // BEFORE pushing KICKOFF, so without the bb_in_kickoff exclusion every
    // kick-off catch/bounce test offered the receiver a team re-roll
    // (review M4). Skill re-rolls remain available.
    return m->rerolls[team] > 0 && m->active_team == team && !bb_in_kickoff(m);
}

// PRO: "During this player's activation, they may attempt to re-roll a single
// dice. ... The Skill cannot be used to re-roll ... a roll made outside of
// the player's activation." Once per activation (BB_PF_USED_SKILL_B), and
// locked out once any other re-roll source has touched this die.
static bool pro_reroll_available(const bb_match* m, int slot, uint16_t fdata) {
    if (fdata & (TF_TEAM_USED | TF_SKILL_USED)) return false;
    const bb_player* p = &m->players[slot];
    if (!(p->flags & BB_PF_ACTIVATING)) return false;
    if (p->flags & BB_PF_USED_SKILL_B) return false;
    return bb_has_skill(&p->skills, BB_SK_PRO);
}

static void test_advance(bb_match* m, bb_rng* rng) {
    bb_frame* f = bb_top(m);
    int slot = f->a;
    int team = BB_TEAM_OF(slot);

    if (f->phase == 0) { // initial roll
        int die = bb_roll(rng, 6);
        f->phase = 1;
        f->data = (uint16_t)((f->data & 0x0FFF) | (die << 12)); // stash the die
        if (test_pass(die, f->x)) {
            bb_pop(m);
            m->ret = (uint16_t)(1 | (die << 8) | ((f->x & 7) << 12));
            return;
        }
        // Failed: offer rerolls if any are available.
        bb_ctx tc = test_ctx(f);
        bool team_rr = team_reroll_available(m, team) && !(f->data & TF_TEAM_USED);
        bool skill_rr = !(f->data & TF_SKILL_USED) && bb_hook_reroll(m, &tc) >= 0;
        bool pro_rr = pro_reroll_available(m, slot, f->data);
        if (team_rr || skill_rr || pro_rr) {
            f->data |= TF_WAITING;
            bb_need_decision(m, team);
            return;
        }
        bb_pop(m);
        m->ret = (uint16_t)(0 | (die << 8) | ((f->x & 7) << 12));
        return;
    }
    if (f->phase == 2) { // reroll the die after a reroll was used
        int die = bb_roll(rng, 6);
        if (test_pass(die, f->x)) {
            bb_pop(m);
            m->ret = (uint16_t)(1 | (die << 8) | ((f->x & 7) << 12));
            return;
        }
        // Each die may only be re-rolled once, by any means.
        bb_pop(m);
        m->ret = (uint16_t)(0 | (die << 8) | ((f->x & 7) << 12));
        return;
    }
    if (f->phase == 3) { // loner gate failed: reroll consumed, result stands
        int die = (f->data >> 12) & 0xF;
        bb_pop(m);
        m->ret = (uint16_t)(0 | (die << 8) | ((f->x & 7) << 12));
        return;
    }
    // phase 1 while waiting shouldn't advance; treat as error
    m->status = BB_STATUS_ERROR;
}

static int test_legal(const bb_match* m, bb_action* out) {
    const bb_frame* f = &m->stack[m->stack_top - 1];
    int slot = f->a;
    int team = BB_TEAM_OF(slot);
    int n = 0;
    if (team_reroll_available(m, team) && !(f->data & TF_TEAM_USED)) {
        out[n++] = (bb_action){BB_A_USE_REROLL, BB_RR_TEAM, 0, 0};
    }
    // PRO: own activation only, once per activation, 3+ to re-roll a single
    // die; using Pro locks out every other re-roll source for this roll.
    if (pro_reroll_available(m, slot, f->data)) {
        out[n++] = (bb_action){BB_A_USE_REROLL, BB_RR_PRO, 0, 0};
    }
    bb_ctx tc = test_ctx(f);
    int sk = (f->data & TF_SKILL_USED) ? -1 : bb_hook_reroll(m, &tc);
    if (sk >= 0) {
        out[n++] = (bb_action){BB_A_USE_REROLL, BB_RR_SKILL, (uint8_t)sk, 0};
    }
    out[n++] = (bb_action){BB_A_DECLINE_REROLL, 0, 0, 0};
    return n;
}

static void test_apply(bb_match* m, bb_action a, bb_rng* rng) {
    bb_frame* f = bb_top(m);
    int slot = f->a;
    int team = BB_TEAM_OF(slot);
    f->data &= (uint16_t)~TF_WAITING;

    if (a.type == BB_A_DECLINE_REROLL) {
        int die = (f->data >> 12) & 0xF;
        int target = f->x & 7;
        bb_pop(m);
        m->ret = (uint16_t)(0 | (die << 8) | (target << 12));
        return;
    }
    if (a.arg == BB_RR_PRO) {
        m->players[slot].flags |= BB_PF_USED_SKILL_B; // once per activation
        bb_cover(BB_SK_PRO);
        f->data |= TF_TEAM_USED | TF_SKILL_USED; // no other source after Pro
        if (bb_d6(rng) >= 3) {
            f->phase = 2; // may re-roll the die
        } else {
            f->phase = 3; // Pro failed: the result stands
        }
        return;
    }
    if (a.arg == BB_RR_TEAM) {
        m->rerolls[team]--;
        // Drive-scoped bonuses (Brilliant Coaching) are spent first — they
        // expire soonest (END_DRIVE), before the half-scoped Leader re-roll
        // and the purchased complement.
        if (m->bonus_rerolls[team]) m->bonus_rerolls[team]--;
        f->data |= TF_TEAM_USED;
        int loner = bb_loner_value(m, slot);
        if (loner > 0) {
            int die = bb_roll(rng, 6);
            if (die < loner) {
                f->phase = 3; // reroll wasted; result stands
                return;
            }
        }
        f->phase = 2;
        return;
    }
    // Skill reroll: once per TURN per player per skill kind.
    m->players[slot].skill_rr_used |= (uint16_t)(1u << f->b);
    f->data |= TF_SKILL_USED;
    bb_cover(a.x); // a.x = granting skill id (set by test_legal); the re-roll
                   // is consumed here, not at the legality query (review P3)
    f->phase = 2;
}

const bb_proc_vtable bb_proc_test_vtable = {test_advance, test_legal, test_apply};
