// bb_match.c — match lifecycle, procedure-stack plumbing, board queries.
#include "bb/bb_match.h"
#include "bb/bb_hooks.h"
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

static bool state_bank_common_valid(const bb_match* m) {
    if (m == NULL || m->status != BB_STATUS_DECISION ||
        m->half < 1 || m->half > 3 ||
        m->turn[0] > 8 || m->turn[1] > 8 ||
        m->active_team > BB_AWAY || m->kicking_team > BB_AWAY ||
        m->decision_team != m->active_team ||
        m->turn[m->active_team] < 1 ||
        m->team_id[0] >= BB_TEAM_COUNT || m->team_id[1] >= BB_TEAM_COUNT ||
        m->weather > BB_WEATHER_BLIZZARD || m->stack_top < 2 ||
        m->stack_top > BB_STACK_MAX) {
        return false;
    }

    // Raw BBS1 is not a general procedure-stack serialization. Every admitted
    // shape shares these exact lower frames; merely checking proc enums allowed
    // corrupt params (for example team=255) to index out of bounds.
    const bb_frame* root = &m->stack[0];
    const bb_frame* turn = &m->stack[1];
    if (root->proc != BB_PROC_MATCH || root->phase != 3 ||
        root->a != 0 || root->b != 0 || root->x != 0 || root->y != 0 ||
        (root->data & (uint16_t)~6u) != 0 ||
        turn->proc != BB_PROC_TEAM_TURN || turn->phase != 1 ||
        turn->a != m->active_team || turn->b != 0 ||
        turn->x != 0 || turn->y != 0 || turn->data != 0 || m->turnover) {
        return false;
    }

    int ball_flags = 0;
    for (int slot = 0; slot < BB_NUM_PLAYERS; slot++) {
        const bb_player* player = &m->players[slot];
        if (player->position_id >= BB_MAX_POSITIONS ||
            player->location > BB_LOC_ABSENT ||
            player->stance > BB_STANCE_STUNNED_USED ||
            (player->flags & (uint16_t)~0x0FFFu) != 0) {
            return false;
        }
        for (int word = 0; word < BB_SKILL_WORDS; word++) {
            int first_skill = word * 64;
            if (first_skill >= BB_SKILL_COUNT) {
                if (player->skills.w[word] != 0) return false;
            } else if (first_skill + 64 > BB_SKILL_COUNT) {
                int valid_bits = BB_SKILL_COUNT - first_skill;
                if (player->skills.w[word] & (~0ULL << valid_bits)) {
                    return false;
                }
            }
        }
        if (player->flags & BB_PF_HAS_BALL) ball_flags++;
        if (player->location == BB_LOC_ON_PITCH) {
            if (!bb_on_pitch_xy(player->x, player->y) ||
                m->grid[player->x][player->y] != slot + 1) return false;
        } else if (player->flags & BB_PF_HAS_BALL) {
            return false;
        }
    }

    for (int x = 0; x < BB_PITCH_LEN; x++) {
        for (int y = 0; y < BB_PITCH_WID; y++) {
            uint8_t value = m->grid[x][y];
            if (value == 0) continue;
            int slot = value - 1;
            if (slot >= BB_NUM_PLAYERS ||
                m->players[slot].location != BB_LOC_ON_PITCH ||
                m->players[slot].x != x || m->players[slot].y != y) {
                return false;
            }
        }
    }

    if (m->ball.state == BB_BALL_HELD) {
        if (m->ball.carrier >= BB_NUM_PLAYERS || ball_flags != 1) return false;
        const bb_player* carrier = &m->players[m->ball.carrier];
        if (carrier->location != BB_LOC_ON_PITCH ||
            !(carrier->flags & BB_PF_HAS_BALL) ||
            m->ball.x != carrier->x || m->ball.y != carrier->y) return false;
    } else {
        if (m->ball.state > BB_BALL_ON_GROUND ||
            m->ball.carrier != BB_NO_PLAYER || ball_flags != 0) return false;
        if (m->ball.state == BB_BALL_ON_GROUND &&
            !bb_on_pitch_xy(m->ball.x, m->ball.y)) return false;
    }
    return true;
}

bool bb_state_bank_boundary_valid(const bb_match* m) {
    return state_bank_common_valid(m) && m->stack_top == 2;
}

bool bb_state_bank_dodge_reroll_valid(const bb_match* m) {
    enum {
        MV_AWAIT_TEST = 1 << 4,
        TF_WAITING = 1 << 2,
    };
    if (!state_bank_common_valid(m) || m->stack_top != 5 || m->ret != 0) {
        return false;
    }

    const bb_frame* activation = &m->stack[2];
    const bb_frame* move = &m->stack[3];
    const bb_frame* test = &m->stack[4];
    if (activation->proc != BB_PROC_ACTIVATION || activation->phase != 1 ||
        activation->a >= BB_NUM_PLAYERS || activation->b != BB_ACT_MOVE ||
        activation->x != 0 || activation->y != 0 || activation->data != 0) {
        return false;
    }
    int mover = activation->a;
    const bb_player* player = &m->players[mover];
    if (BB_TEAM_OF(mover) != m->active_team ||
        player->location != BB_LOC_ON_PITCH ||
        player->stance != BB_STANCE_STANDING ||
        !(player->flags & BB_PF_ACTIVATING) ||
        (player->flags & (BB_PF_USED | BB_PF_ROOTED | BB_PF_DISTRACTED |
                          BB_PF_EYE_GOUGED)) ||
        player->moved != 0 || player->moved >= player->ma ||
        player->rushes != 0 ||
        (m->ball.state == BB_BALL_HELD && m->ball.carrier == mover)) {
        return false;
    }
    if (move->proc != BB_PROC_MOVE || move->phase != 0 ||
        move->a != mover || move->b != BB_ACT_MOVE ||
        move->data != MV_AWAIT_TEST ||
        !bb_on_pitch_xy(move->x, move->y) ||
        !bb_adjacent(player->x, player->y, move->x, move->y) ||
        m->grid[move->x][move->y] != 0 ||
        (m->ball.state == BB_BALL_ON_GROUND &&
         m->ball.x == move->x && m->ball.y == move->y) ||
        bb_tackle_zones(m, m->active_team, player->x, player->y) <= 0) {
        return false;
    }
    if (test->proc != BB_PROC_TEST || test->phase != 1 ||
        test->a != mover || test->b != BB_TEST_DODGE || test->y != 0 ||
        (test->data & 0x0FFFu) != TF_WAITING) {
        return false;
    }
    int failed_die = (test->data >> 12) & 0xF;
    if (failed_die < 1 || failed_die > 5 || failed_die >= test->x) {
        return false;
    }

    bb_ctx context = {
        BB_TEST_DODGE, (uint8_t)mover, BB_NO_PLAYER, (uint8_t)mover,
        (int8_t)player->x, (int8_t)player->y,
        (int8_t)move->x, (int8_t)move->y, -1, 0,
    };
    int modifiers = -bb_tackle_zones(m, m->active_team, move->x, move->y) +
                    bb_hook_mods(m, &context);
    if (test->x != bb_test_target(player->ag, modifiers)) return false;

    bb_action legal[BB_LEGAL_MAX];
    int count = bb_legal_actions(m, legal);
    bool has_use = false;
    bool has_decline = false;
    for (int i = 0; i < count; i++) {
        if (legal[i].type == BB_A_USE_REROLL) has_use = true;
        else if (legal[i].type == BB_A_DECLINE_REROLL) has_decline = true;
        else return false;
    }
    return has_use && has_decline;
}

bool bb_state_bank_resumable_valid(const bb_match* m) {
    return bb_state_bank_boundary_valid(m) ||
           bb_state_bank_dodge_reroll_valid(m);
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
    if (bb_has_skill(&p->skills, BB_SK_NO_BALL)) return false;
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
    return bb_apply_trusted(m, a, rng);
}

bb_status bb_apply_trusted(bb_match* m, bb_action a, bb_rng* rng) {
    // No legal-set membership check — see the bb_match.h contract. Keeps the
    // cheap structural guards so a misuse degrades to BB_STATUS_ERROR (the
    // binding's defensive-reset path) instead of indexing a stale frame.
    if (m->status != BB_STATUS_DECISION || !m->stack_top) {
        m->status = BB_STATUS_ERROR;
        return (bb_status)m->status;
    }
    bb_frame* top = bb_top(m);
    const bb_proc_vtable* vt = &bb_proc_table[top->proc];
    if (!vt->apply) {
        m->status = BB_STATUS_ERROR;
        return (bb_status)m->status;
    }
    m->status = BB_STATUS_RUNNING;
    m->step_count++;
    vt->apply(m, a, rng);
    return bb_advance(m, rng);
}
