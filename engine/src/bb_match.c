// bb_match.c — match lifecycle, procedure-stack plumbing, board queries.
#include "bb/bb_match.h"
#include "bb/bb_proc.h"
#include "bb/gen_teams.h"
#include <string.h>

// --- Stack plumbing -----------------------------------------------------------

bb_frame* bb_top(bb_match* m) {
    return m->stack_top ? &m->stack[m->stack_top - 1] : 0;
}

bb_frame* bb_parent(bb_match* m) {
    return m->stack_top > 1 ? &m->stack[m->stack_top - 2] : 0;
}

void bb_push(bb_match* m, bb_proc proc, int a, int b, int x, int y) {
    if (m->stack_top >= BB_STACK_MAX) {
        m->status = BB_STATUS_ERROR;
        return;
    }
    bb_frame* f = &m->stack[m->stack_top++];
    f->proc = (uint8_t)proc;
    f->phase = 0;
    f->a = (uint8_t)a;
    f->b = (uint8_t)b;
    f->x = (uint8_t)x;
    f->y = (uint8_t)y;
    f->data = 0;
}

void bb_pop(bb_match* m) {
    if (m->stack_top) m->stack_top--;
}

void bb_need_decision(bb_match* m, int team) {
    m->status = BB_STATUS_DECISION;
    m->decision_team = (uint8_t)team;
}

// --- Board helpers ---------------------------------------------------------------

bool bb_adjacent(int x1, int y1, int x2, int y2) {
    int dx = x1 - x2, dy = y1 - y2;
    if (dx < 0) dx = -dx;
    if (dy < 0) dy = -dy;
    return (dx | dy) != 0 && dx <= 1 && dy <= 1;
}

void bb_place(bb_match* m, int slot, int x, int y) {
    bb_player* p = &m->players[slot];
    if (p->location == BB_LOC_ON_PITCH) {
        m->grid[p->x][p->y] = 0;
    }
    p->location = BB_LOC_ON_PITCH;
    p->x = (uint8_t)x;
    p->y = (uint8_t)y;
    m->grid[x][y] = (uint8_t)(slot + 1);
}

void bb_remove_from_pitch(bb_match* m, int slot, int new_location) {
    bb_player* p = &m->players[slot];
    if (p->location == BB_LOC_ON_PITCH) {
        m->grid[p->x][p->y] = 0;
    }
    p->location = (uint8_t)new_location;
    p->stance = BB_STANCE_STANDING;
    if (p->flags & BB_PF_HAS_BALL) {
        // Caller is responsible for bouncing the ball from the square first.
        p->flags &= (uint16_t)~BB_PF_HAS_BALL;
    }
}

void bb_ball_to(bb_match* m, int x, int y) {
    if (m->ball.carrier != BB_NO_PLAYER) { // enforce the single-carrier invariant
        m->players[m->ball.carrier].flags &= (uint16_t)~BB_PF_HAS_BALL;
    }
    m->ball.state = BB_BALL_ON_GROUND;
    m->ball.x = (uint8_t)x;
    m->ball.y = (uint8_t)y;
    m->ball.carrier = BB_NO_PLAYER;
}

void bb_give_ball(bb_match* m, int slot) {
    if (m->ball.carrier != BB_NO_PLAYER && m->ball.carrier != slot) {
        m->players[m->ball.carrier].flags &= (uint16_t)~BB_PF_HAS_BALL;
    }
    m->ball.state = BB_BALL_HELD;
    m->ball.carrier = (uint8_t)slot;
    m->ball.x = m->players[slot].x;
    m->ball.y = m->players[slot].y;
    m->players[slot].flags |= BB_PF_HAS_BALL;
}

void bb_drop_ball(bb_match* m) {
    if (m->ball.carrier != BB_NO_PLAYER) {
        m->players[m->ball.carrier].flags &= (uint16_t)~BB_PF_HAS_BALL;
        m->ball.carrier = BB_NO_PLAYER;
        m->ball.state = BB_BALL_ON_GROUND;
    }
}

void bb_turnover(bb_match* m) {
    m->turnover = 1;
}

bool bb_check_td(bb_match* m) {
    int c = m->ball.carrier;
    if (c == BB_NO_PLAYER) return false;
    const bb_player* p = &m->players[c];
    if (p->location != BB_LOC_ON_PITCH || p->stance != BB_STANCE_STANDING) return false;
    if (p->x != bb_endzone_x(BB_TEAM_OF(c))) return false;
    bb_push(m, BB_PROC_TOUCHDOWN, c, 0, 0, 0);
    return true;
}

void bb_knockdown(bb_match* m, int slot, int cause, int armour_mod) {
    bb_push(m, BB_PROC_KNOCKDOWN, slot, cause, armour_mod & 0xFF, 0);
}

void bb_knockdown2(bb_match* m, int slot, int cause, int armour_mod, int causer) {
    bb_push(m, BB_PROC_KNOCKDOWN, slot, cause, armour_mod & 0xFF, causer + 1);
}

int bb_test_target(int stat_target, int modifiers) {
    int needed = stat_target - modifiers;
    if (needed < 2) needed = 2;
    if (needed > 6) needed = 6;
    return needed;
}

// --- Tackle zones / marking -------------------------------------------------------

bool bb_exerts_tz(const bb_match* m, int slot) {
    const bb_player* p = &m->players[slot];
    if (p->location != BB_LOC_ON_PITCH) return false;
    if (p->stance != BB_STANCE_STANDING) return false;
    if (p->flags & (BB_PF_NO_TZ | BB_PF_DISTRACTED)) return false;
    return true;
}

int bb_tackle_zones(const bb_match* m, int team, int x, int y) {
    int n = 0;
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            if (!dx && !dy) continue;
            int nx = x + dx, ny = y + dy;
            if (!bb_on_pitch_xy(nx, ny)) continue;
            int s = m->grid[nx][ny] ? m->grid[nx][ny] - 1 : -1;
            if (s >= 0 && BB_TEAM_OF(s) != team && bb_exerts_tz(m, s)) n++;
        }
    }
    return n;
}

bool bb_can_catch(const bb_match* m, int slot) {
    const bb_player* p = &m->players[slot];
    if (p->location != BB_LOC_ON_PITCH) return false;
    if (p->stance != BB_STANCE_STANDING) return false;
    if (p->flags & (BB_PF_DISTRACTED | BB_PF_NO_TZ)) return false;
    return true;
}

bool bb_is_marked(const bb_match* m, int slot) {
    const bb_player* p = &m->players[slot];
    if (p->location != BB_LOC_ON_PITCH) return false;
    return bb_tackle_zones(m, BB_TEAM_OF(slot), p->x, p->y) > 0;
}

// --- Init ---------------------------------------------------------------------------

static void init_player_from_position(bb_player* p, const bb_position_def* pd, int position_id) {
    memset(p, 0, sizeof(*p));
    p->ma = pd->ma;
    p->st = pd->st;
    p->ag = pd->ag;
    p->pa = pd->pa;
    p->av = pd->av;
    p->position_id = (uint8_t)position_id;
    p->location = BB_LOC_RESERVES;
    p->stance = BB_STANCE_STANDING;
    p->p_loner = 4;
    p->p_bloodlust = 0;
    for (int s = 0; s < pd->num_skills; s++) {
        bb_add_skill(&p->skills, pd->skills[s]);
        int v = pd->skill_values[s];
        if (v > 0) { // per-player parameterized skill values from the roster
            if (pd->skills[s] == BB_SK_LONER) p->p_loner = (int8_t)v;
            if (pd->skills[s] == BB_SK_BLOODLUST) p->p_bloodlust = (int8_t)v;
        }
    }
}

// Default matchday squad: walk the roster positions, taking players up to each
// position's max, until 16 slots are filled or the roster runs out. Positional
// players (later-listed specials) are taken before topping up with the first
// position (linemen) to fill 11.
static void default_squad(bb_match* m, int team, int team_id) {
    const bb_team_def* td = &bb_team_defs[team_id];
    int base = team * BB_TEAM_SLOTS;
    int n = 0;
    // First pass: one of each non-lineman position (positions[1..]), respecting max.
    for (int pass = 0; pass < 2 && n < BB_TEAM_SLOTS; pass++) {
        for (int pi = 0; pi < td->num_positions && n < BB_TEAM_SLOTS; pi++) {
            const bb_position_def* pd = &td->positions[pi];
            int already = 0;
            for (int s = 0; s < n; s++) {
                if (m->players[base + s].position_id == pi) already++;
            }
            int want = pass == 0 ? (pd->qty_max < 2 ? pd->qty_max : 2) : pd->qty_max;
            while (already < want && n < BB_TEAM_SLOTS) {
                // Cap total to 11 + a small bench in pass 2.
                if (pass == 1 && n >= 13) break;
                init_player_from_position(&m->players[base + n], pd, pi);
                n++;
                already++;
            }
        }
        if (pass == 0 && n >= 11) break;
    }
    // Mark remaining slots absent.
    for (int s = n; s < BB_TEAM_SLOTS; s++) {
        memset(&m->players[base + s], 0, sizeof(bb_player));
        m->players[base + s].location = BB_LOC_ABSENT;
    }
}

void bb_match_init(bb_match* m, int home_team_id, int away_team_id) {
    memset(m, 0, sizeof(*m));
    // File-derived ids (replay INIT records, future FUMBBL/BC normalizers)
    // flow here; an out-of-range id would index bb_team_defs[] out of bounds
    // (review Hd1). Callers handle BB_STATUS_ERROR.
    if ((unsigned)home_team_id >= (unsigned)BB_TEAM_COUNT ||
        (unsigned)away_team_id >= (unsigned)BB_TEAM_COUNT) {
        m->status = BB_STATUS_ERROR;
        return;
    }
    m->team_id[BB_HOME] = (uint8_t)home_team_id;
    m->team_id[BB_AWAY] = (uint8_t)away_team_id;
    default_squad(m, BB_HOME, home_team_id);
    default_squad(m, BB_AWAY, away_team_id);
    m->rerolls[BB_HOME] = m->rerolls_start[BB_HOME] = 3; // baseline; team-value-
    m->rerolls[BB_AWAY] = m->rerolls_start[BB_AWAY] = 3; // driven builds in Phase 5
    m->apothecary[BB_HOME] = bb_team_defs[home_team_id].apothecary ? 1 : 0;
    m->apothecary[BB_AWAY] = bb_team_defs[away_team_id].apothecary ? 1 : 0;
    m->half = 1;
    m->ball.state = BB_BALL_OFF_PITCH;
    m->ball.carrier = BB_NO_PLAYER;
    m->status = BB_STATUS_RUNNING;
    bb_push(m, BB_PROC_MATCH, 0, 0, 0, 0);
}

// --- Engine loop ----------------------------------------------------------------------

bb_status bb_advance(bb_match* m, bb_rng* rng) {
    int guard = 0;
    while (m->status == BB_STATUS_RUNNING) {
        if (rng->mode == BB_RNG_SCRIPT && bb_rng_error(rng)) {
            m->status = BB_STATUS_ERROR;
            break;
        }
        bb_frame* top = bb_top(m);
        if (!top) {
            m->status = BB_STATUS_MATCH_OVER;
            break;
        }
        const bb_proc_vtable* vt = &bb_proc_table[top->proc];
        if (!vt->advance) {
            m->status = BB_STATUS_ERROR;
            break;
        }
        vt->advance(m, rng);
        if (++guard > 100000) { // runaway procedure safety
            m->status = BB_STATUS_ERROR;
            break;
        }
    }
    return (bb_status)m->status;
}

int bb_legal_actions(const bb_match* m, bb_action* out) {
    if (m->status != BB_STATUS_DECISION || !m->stack_top) return 0;
    const bb_frame* top = &m->stack[m->stack_top - 1];
    const bb_proc_vtable* vt = &bb_proc_table[top->proc];
    if (!vt->legal) return 0;
    return vt->legal(m, out);
}

bb_status bb_apply(bb_match* m, bb_action a, bb_rng* rng) {
    if (m->status != BB_STATUS_DECISION) {
        m->status = BB_STATUS_ERROR;
        return (bb_status)m->status;
    }
    // Validate against the legal set (mask-soundness invariant).
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(m, legal);
    bool ok = false;
    for (int i = 0; i < n; i++) {
        if (bb_action_eq(legal[i], a)) {
            ok = true;
            break;
        }
    }
    if (!ok) {
        m->status = BB_STATUS_ERROR;
        return (bb_status)m->status;
    }
    bb_frame* top = bb_top(m);
    const bb_proc_vtable* vt = &bb_proc_table[top->proc];
    m->status = BB_STATUS_RUNNING;
    m->step_count++;
    vt->apply(m, a, rng);
    return bb_advance(m, rng);
}
