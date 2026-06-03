// proc_turn.c — TEAM_TURN, ACTIVATION, TURNOVER.
#include "bb/bb_proc.h"

// ===== TEAM_TURN =============================================================
// a = team. phase 0: turn start bookkeeping. phase 1: activation loop.
// phase 2: turn end bookkeeping.

static void turn_start(bb_match* m, int team) {
    m->active_team = (uint8_t)team;
    m->turn[team]++;
    m->reroll_used_this_turn[team] = 0;
    m->blitz_used = 0;
    m->pass_used = 0;
    m->handoff_used = 0;
    m->foul_used = 0;
    m->ttm_used = 0;
    m->turnover = 0;
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        bb_player* p = &m->players[s];
        p->flags &= (uint16_t)~(BB_PF_USED | BB_PF_ACTIVATING | BB_PF_USED_SKILL_A |
                                BB_PF_USED_SKILL_B | BB_PF_BLITZED);
        p->moved = 0;
        p->rushes = 0;
    }
}

static void turn_end(bb_match* m, int team) {
    // Stunned players of the team whose turn is ending are turned face up.
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        bb_player* p = &m->players[s];
        if (p->location == BB_LOC_ON_PITCH && p->stance == BB_STANCE_STUNNED) {
            p->stance = BB_STANCE_PRONE;
        }
    }
    m->turnover = 0;
    // Next team takes over (MATCH reads active_team to alternate).
    m->active_team = (uint8_t)(1 - team);
}

static bool can_activate(const bb_match* m, int s) {
    const bb_player* p = &m->players[s];
    if (p->location != BB_LOC_ON_PITCH) return false;
    if (p->flags & BB_PF_USED) return false;
    if (p->stance == BB_STANCE_STUNNED) return false;
    return true;
}

static void team_turn_advance(bb_match* m, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    int team = f->a;
    if (f->phase == 0) {
        turn_start(m, team);
        f->phase = 1;
        return;
    }
    if (f->phase == 1) {
        if (m->turnover) {
            f->phase = 2;
            return;
        }
        bool any = false;
        for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
            if (can_activate(m, s)) {
                any = true;
                break;
            }
        }
        if (!any) {
            f->phase = 2;
            return;
        }
        bb_need_decision(m, team);
        return;
    }
    turn_end(m, team);
    bb_pop(m);
}

static int team_turn_legal(const bb_match* m, bb_action* out) {
    const bb_frame* f = &m->stack[m->stack_top - 1];
    int team = f->a;
    int n = 0;
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        if (can_activate(m, s)) {
            out[n++] = (bb_action){BB_A_ACTIVATE, (uint8_t)s, 0, 0};
        }
    }
    out[n++] = (bb_action){BB_A_END_TURN, 0, 0, 0};
    return n;
}

static void team_turn_apply(bb_match* m, bb_action a, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    if (a.type == BB_A_END_TURN) {
        f->phase = 2;
        return;
    }
    bb_push(m, BB_PROC_ACTIVATION, a.arg, 0, 0, 0);
}

// ===== ACTIVATION ============================================================
// a = player slot. phase 0: declare action kind. phase 1: child (MOVE machine)
// is running. phase 2: wrap up.

static bool has_adjacent_standing_opponent(const bb_match* m, int slot) {
    const bb_player* p = &m->players[slot];
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            if (!dx && !dy) continue;
            int nx = p->x + dx, ny = p->y + dy;
            if (!bb_on_pitch_xy(nx, ny)) continue;
            int s = bb_slot_at(m, nx, ny);
            if (s >= 0 && BB_TEAM_OF(s) != BB_TEAM_OF(slot) &&
                m->players[s].stance == BB_STANCE_STANDING) {
                return true;
            }
        }
    }
    return false;
}

static bool has_adjacent_downed_opponent(const bb_match* m, int slot) {
    const bb_player* p = &m->players[slot];
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            if (!dx && !dy) continue;
            int nx = p->x + dx, ny = p->y + dy;
            if (!bb_on_pitch_xy(nx, ny)) continue;
            int s = bb_slot_at(m, nx, ny);
            if (s >= 0 && BB_TEAM_OF(s) != BB_TEAM_OF(slot) &&
                m->players[s].stance != BB_STANCE_STANDING) {
                return true;
            }
        }
    }
    return false;
}

static void activation_advance(bb_match* m, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    int slot = f->a;
    if (f->phase == 0) {
        m->players[slot].flags |= BB_PF_ACTIVATING;
        bb_need_decision(m, BB_TEAM_OF(slot));
        return;
    }
    // Child finished (or turnover unwound it).
    bb_player* p = &m->players[slot];
    p->flags &= (uint16_t)~BB_PF_ACTIVATING;
    p->flags |= BB_PF_USED;
    bb_pop(m);
}

static int activation_legal(const bb_match* m, bb_action* out) {
    const bb_frame* f = &m->stack[m->stack_top - 1];
    int slot = f->a;
    const bb_player* p = &m->players[slot];
    int n = 0;
    out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_MOVE, 0, 0};
    if (p->stance == BB_STANCE_STANDING && has_adjacent_standing_opponent(m, slot)) {
        out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_BLOCK, 0, 0};
    }
    if (!m->blitz_used) {
        out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_BLITZ, 0, 0};
    }
    if (!m->pass_used && (p->flags & BB_PF_HAS_BALL)) {
        out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_PASS, 0, 0};
    }
    if (!m->handoff_used && (p->flags & BB_PF_HAS_BALL)) {
        out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_HANDOFF, 0, 0};
    }
    if (!m->foul_used && has_adjacent_downed_opponent(m, slot)) {
        out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_FOUL, 0, 0};
    }
    // TODO(phase3): TTM, SECURE_BALL declarations.
    return n;
}

static void activation_apply(bb_match* m, bb_action a, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    f->phase = 1;
    f->b = a.arg; // action kind
    bb_push(m, BB_PROC_MOVE, f->a, a.arg, 0, 0);
}

// ===== TURNOVER ==============================================================
// The latch in m->turnover is read by action procs (MOVE, TEAM_TURN); this
// dedicated proc exists for explicit unwinding when needed.

static void turnover_advance(bb_match* m, bb_rng* rng) {
    (void)rng;
    bb_turnover(m);
    bb_pop(m);
}

const bb_proc_vtable bb_proc_team_turn_vtable = {team_turn_advance, team_turn_legal, team_turn_apply};
const bb_proc_vtable bb_proc_activation_vtable = {activation_advance, activation_legal, activation_apply};
const bb_proc_vtable bb_proc_turnover_vtable = {turnover_advance, 0, 0};
