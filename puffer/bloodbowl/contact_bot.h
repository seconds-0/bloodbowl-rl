// contact_bot.h -- deterministic scripted contact opponent for evaluation.
//
// The bot operates strictly on the engine decision surface: score the current
// bb_legal_actions list and return one of those exact actions. It is intentionally
// hand-coded, deterministic, and conservative about risk; its job is to create a
// contact-heavy opponent that still plays the ball.
#pragma once

#include "bb/bb_blockev.h"
#include "bb/bb_hooks.h"
#include "bb/bb_proc.h"
#include "bb/gen_skills.h"

typedef struct {
    int ndice;
    int defender_chooses;
} bbe_cb_pool;

static int bbe_cb_abs_i(int x) { return x < 0 ? -x : x; }
static int bbe_cb_min_i(int a, int b) { return a < b ? a : b; }

static int bbe_cb_cheb(int ax, int ay, int bx, int by) {
    int dx = bbe_cb_abs_i(ax - bx);
    int dy = bbe_cb_abs_i(ay - by);
    return dx > dy ? dx : dy;
}

static int bbe_cb_endzone_dist(int team, int x) {
    return bbe_cb_abs_i(x - bb_endzone_x(team));
}

static int bbe_cb_defensive_endzone_x(int team) {
    return team == BB_HOME ? 0 : BB_PITCH_LEN - 1;
}

static int bbe_cb_on_pitch_count(const bb_match* m, int team) {
    int n = 0;
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        n += m->players[s].location == BB_LOC_ON_PITCH;
    }
    return n;
}

static int bbe_cb_los_count(const bb_match* m, int team) {
    int n = 0;
    int los_x = team == BB_HOME ? 12 : 13;
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        const bb_player* p = &m->players[s];
        if (p->location == BB_LOC_ON_PITCH && p->x == los_x &&
            p->y >= 4 && p->y <= 10) {
            n++;
        }
    }
    return n;
}

static int bbe_cb_standing_on_pitch(const bb_match* m, int slot) {
    const bb_player* p = &m->players[slot];
    return p->location == BB_LOC_ON_PITCH && p->stance == BB_STANCE_STANDING;
}

static int bbe_cb_adjacent_friendlies(const bb_match* m, int team, int mover,
                                      int x, int y) {
    int n = 0;
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            if (!dx && !dy) continue;
            int nx = x + dx, ny = y + dy;
            if (!bb_on_pitch_xy(nx, ny)) continue;
            int s = bb_slot_at(m, nx, ny);
            if (s < 0 || s == mover || BB_TEAM_OF(s) != team) continue;
            n += bbe_cb_standing_on_pitch(m, s);
        }
    }
    return n;
}

static int bbe_cb_adjacent_enemy_carrier(const bb_match* m, int team, int x, int y) {
    if (m->ball.state != BB_BALL_HELD || m->ball.carrier == BB_NO_PLAYER) return 0;
    int c = m->ball.carrier;
    if (BB_TEAM_OF(c) == team) return 0;
    const bb_player* p = &m->players[c];
    return p->location == BB_LOC_ON_PITCH && bb_adjacent(x, y, p->x, p->y);
}

static int bbe_cb_enemy_carrier(const bb_match* m, int team, int slot) {
    return m->ball.state == BB_BALL_HELD && m->ball.carrier == slot &&
           BB_TEAM_OF(slot) != team;
}

static void bbe_cb_setup_target(int team, int idx, int* tx, int* ty) {
    static const int home_x[11] = {12, 12, 12, 10, 10, 10, 8, 8, 8, 5, 3};
    static const int y[11]      = { 6,  7,  8,  5,  7,  9, 4, 7,10, 7, 7};
    if (idx < 0) idx = 0;
    if (idx > 10) idx = 10;
    *tx = team == BB_HOME ? home_x[idx] : (BB_PITCH_LEN - 1 - home_x[idx]);
    *ty = y[idx];
}

// Public bb_blockev exposes the result probabilities but not the dice pool.
// This mirrors the ST+assist pool calculation closely enough for heuristic
// bonuses; the EV itself still comes from bb_block_ev.
static bbe_cb_pool bbe_cb_estimate_pool(const bb_match* m, int att, int def,
                                        int is_blitz) {
    int base_a = m->players[att].st;
    int base_d = m->players[def].st;
    if (bb_has_skill(&m->players[att].skills, BB_SK_DAUNTLESS) && base_d > base_a) {
        int diff = base_d - base_a;
        if (diff <= 3) base_a = base_d; // likely enough to matter; EV handles exact odds.
    }
    int st_a = base_a + bb_count_assists(m, att, def);
    if (BB_TEAM_OF(att) == m->active_team && m->cheer_assist[BB_TEAM_OF(att)]) {
        st_a++;
    }
    if (is_blitz) st_a += bb_hook_st_mod_blitz(m, att);
    int st_d = base_d + bb_count_assists(m, def, att);

    bbe_cb_pool p = {1, 0};
    if (st_a > st_d) {
        p.ndice = st_a > 2 * st_d ? 3 : 2;
    } else if (st_d > st_a) {
        p.ndice = st_d > 2 * st_a ? 3 : 2;
        p.defender_chooses = 1;
    }
    return p;
}

static float bbe_cb_block_score(const bb_match* m, int att, int def, int is_blitz) {
    if (att < 0 || att >= BB_NUM_PLAYERS || def < 0 || def >= BB_NUM_PLAYERS) {
        return -100000.0f;
    }
    if (!bbe_cb_standing_on_pitch(m, att) || !bbe_cb_standing_on_pitch(m, def)) {
        return -100000.0f;
    }
    bb_blockev ev;
    bb_block_ev(m, att, def, is_blitz, NULL, &ev);
    bbe_cb_pool pool = bbe_cb_estimate_pool(m, att, def, is_blitz);
    int team = BB_TEAM_OF(att);
    int carrier = bbe_cb_enemy_carrier(m, team, def);

    float score = 1200.0f * ev.p_def_down
                - 1550.0f * ev.p_att_down
                - 1250.0f * ev.p_turnover
                + 350.0f * ev.p_def_removed
                - 250.0f * ev.p_att_removed
                + 1000.0f * ev.p_ball_out;
    if (carrier) {
        score += 2400.0f + 1000.0f * ev.p_def_down + 2200.0f * ev.p_ball_out;
    }
    if (!pool.defender_chooses) {
        if (pool.ndice == 2) score += 180.0f;
        if (pool.ndice == 3) score += 300.0f;
    } else {
        score -= pool.ndice == 3 ? 1400.0f : 850.0f;
    }
    if (ev.p_att_down > ev.p_def_down + 0.08f) score -= 850.0f;
    if (ev.p_turnover > 0.22f && !carrier) score -= 550.0f;
    return score;
}

static float bbe_cb_best_adjacent_block(const bb_match* m, int slot, int is_blitz) {
    const bb_player* p = &m->players[slot];
    if (p->location != BB_LOC_ON_PITCH) return -100000.0f;
    float best = -100000.0f;
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            if (!dx && !dy) continue;
            int nx = p->x + dx, ny = p->y + dy;
            if (!bb_on_pitch_xy(nx, ny)) continue;
            int def = bb_slot_at(m, nx, ny);
            if (def < 0 || BB_TEAM_OF(def) == BB_TEAM_OF(slot)) continue;
            float s = bbe_cb_block_score(m, slot, def, is_blitz);
            if (s > best) best = s;
        }
    }
    return best;
}

static int bbe_cb_carrier_reachable_by_blitz(const bb_match* m, int slot) {
    if (m->ball.state != BB_BALL_HELD || m->ball.carrier == BB_NO_PLAYER) return 0;
    if (BB_TEAM_OF(m->ball.carrier) == BB_TEAM_OF(slot)) return 0;
    const bb_player* p = &m->players[slot];
    const bb_player* c = &m->players[m->ball.carrier];
    if (!bbe_cb_standing_on_pitch(m, slot) || !bbe_cb_standing_on_pitch(m, m->ball.carrier)) {
        return 0;
    }
    int reach = p->ma - p->moved;
    if (reach < 0) reach = 0;
    reach += bb_max_rushes(m, slot) - p->rushes;
    return bbe_cb_cheb(p->x, p->y, c->x, c->y) <= reach + 1;
}

static float bbe_cb_setup_score(const bb_match* m, bb_action a, int index) {
    int team = m->decision_team & 1;
    if (a.type == BB_A_SETUP_DONE) return 5000.0f - (float)index;
    if (a.type == BB_A_SETUP_REMOVE) return -500.0f;
    if (a.type != BB_A_SETUP_PLACE) return 0.0f;

    int on = bbe_cb_on_pitch_count(m, team);
    int target_idx = m->players[a.arg].location == BB_LOC_ON_PITCH
                         ? BB_SLOT_OF(a.arg)
                         : on;
    int tx, ty;
    bbe_cb_setup_target(team, target_idx, &tx, &ty);
    int dx = (int)a.x - tx;
    int dy = (int)a.y - ty;
    int dist2 = dx * dx + dy * dy;
    float score = 1200.0f - 14.0f * (float)dist2 - (float)index * 0.001f;

    int los_x = team == BB_HOME ? 12 : 13;
    int los = bbe_cb_los_count(m, team);
    if (los < 3) {
        if (a.x == los_x && a.y >= 4 && a.y <= 10) score += 900.0f;
        else score -= 700.0f;
    }
    if (a.y <= 3 || a.y >= 11) score -= 150.0f; // keep wide-zone count safe.
    if (m->players[a.arg].location == BB_LOC_RESERVES) score += 40.0f;
    return score;
}

static float bbe_cb_activate_score(const bb_match* m, bb_action a) {
    if (a.type == BB_A_END_TURN) return -1000.0f;
    if (a.type != BB_A_ACTIVATE || a.arg >= BB_NUM_PLAYERS) return 0.0f;
    int slot = a.arg;
    int team = BB_TEAM_OF(slot);
    const bb_player* p = &m->players[slot];
    float score = 100.0f;

    if (m->ball.state == BB_BALL_HELD && m->ball.carrier == slot) {
        return 5000.0f - 30.0f * (float)bbe_cb_endzone_dist(team, p->x);
    }
    if (m->ball.state == BB_BALL_ON_GROUND && p->location == BB_LOC_ON_PITCH) {
        int d = bbe_cb_cheb(p->x, p->y, m->ball.x, m->ball.y);
        int reach = p->ma + bb_max_rushes(m, slot);
        if (d <= reach) score += 3100.0f - 120.0f * (float)d;
        else score += 900.0f - 40.0f * (float)d;
    }

    float block = bbe_cb_best_adjacent_block(m, slot, 0);
    if (block > 180.0f) score += 900.0f + block;
    if (bbe_cb_carrier_reachable_by_blitz(m, slot)) score += 1100.0f;
    if (m->ball.state == BB_BALL_HELD &&
        BB_TEAM_OF(m->ball.carrier) != team && p->location == BB_LOC_ON_PITCH) {
        const bb_player* c = &m->players[m->ball.carrier];
        score += 500.0f - 35.0f * (float)bbe_cb_cheb(p->x, p->y, c->x, c->y);
    }
    if (p->stance == BB_STANCE_PRONE) score -= 80.0f;
    return score;
}

static float bbe_cb_declare_score(const bb_match* m, bb_action a) {
    const bb_frame* f = m->stack_top ? &m->stack[m->stack_top - 1] : NULL;
    int slot = f && f->proc == BB_PROC_ACTIVATION ? f->a : BB_NO_PLAYER;
    if (a.type != BB_A_DECLARE || slot >= BB_NUM_PLAYERS) return 0.0f;

    if (a.arg == BB_ACT_BLOCK) {
        float b = bbe_cb_best_adjacent_block(m, slot, 0);
        return b > 160.0f ? 2200.0f + b : -450.0f;
    }
    if (a.arg == BB_ACT_BLITZ) {
        float b = bbe_cb_best_adjacent_block(m, slot, 1);
        if (b > 160.0f) return 1900.0f + b;
        if (bbe_cb_carrier_reachable_by_blitz(m, slot)) return 1700.0f;
        return -100.0f;
    }
    if (a.arg == BB_ACT_SECURE_BALL && m->ball.state == BB_BALL_ON_GROUND) {
        return 1400.0f;
    }
    if (a.arg == BB_ACT_MOVE) return 900.0f;
    if (a.arg == BB_ACT_PASS || a.arg == BB_ACT_HANDOFF) return -700.0f;
    if (a.arg == BB_ACT_FOUL) return -250.0f;
    return 0.0f;
}

static float bbe_cb_step_like_score(const bb_match* m, bb_action a) {
    const bb_frame* f = m->stack_top ? &m->stack[m->stack_top - 1] : NULL;
    if (!f || f->proc != BB_PROC_MOVE || f->a >= BB_NUM_PLAYERS) return 0.0f;
    int slot = f->a;
    int team = BB_TEAM_OF(slot);
    const bb_player* p = &m->players[slot];
    int to_tz = bb_tackle_zones(m, team, a.x, a.y);
    int from_tz = p->location == BB_LOC_ON_PITCH ? bb_tackle_zones(m, team, p->x, p->y) : 0;
    int marks_carrier = bbe_cb_adjacent_enemy_carrier(m, team, a.x, a.y);
    float ps = (float)bb_step_success_p255(m, slot, a.x, a.y, f->b == BB_ACT_BLITZ) / 255.0f;
    float score = -15.0f + 60.0f * ps;

    if (m->ball.state == BB_BALL_ON_GROUND && m->ball.x == a.x && m->ball.y == a.y) {
        score += 5200.0f + 250.0f * ps - 170.0f * (float)to_tz;
        return score;
    }

    if (p->flags & BB_PF_HAS_BALL) {
        int before = bbe_cb_endzone_dist(team, p->x);
        int after = bbe_cb_endzone_dist(team, a.x);
        int progress = before - after;
        score += 900.0f + 270.0f * (float)progress - 18.0f * (float)after;
        if (a.x == bb_endzone_x(team)) score += 9000.0f;
        int friends = bbe_cb_adjacent_friendlies(m, team, slot, a.x, a.y);
        score += friends > 0 ? 520.0f + 80.0f * (float)bbe_cb_min_i(friends, 3)
                             : -360.0f;
        score -= 250.0f * (float)to_tz;
        if (from_tz) score -= 120.0f;
        return score;
    }

    if (marks_carrier) {
        score += 2500.0f - 50.0f * (float)to_tz;
        return score;
    }

    if (m->ball.state == BB_BALL_ON_GROUND) {
        int before = bbe_cb_cheb(p->x, p->y, m->ball.x, m->ball.y);
        int after = bbe_cb_cheb(a.x, a.y, m->ball.x, m->ball.y);
        score += 360.0f * (float)(before - after) - 20.0f * (float)after;
    } else if (m->ball.state == BB_BALL_HELD && m->ball.carrier != BB_NO_PLAYER &&
               BB_TEAM_OF(m->ball.carrier) != team) {
        const bb_player* c = &m->players[m->ball.carrier];
        int before = bbe_cb_cheb(p->x, p->y, c->x, c->y);
        int after = bbe_cb_cheb(a.x, a.y, c->x, c->y);
        score += 170.0f * (float)(before - after);
        int own_ez = bbe_cb_defensive_endzone_x(team);
        score += 25.0f * (float)(bbe_cb_abs_i(p->x - own_ez) -
                                  bbe_cb_abs_i((int)a.x - own_ez));
    } else {
        int target_x = team == BB_HOME ? 11 : 14;
        score += 25.0f * (float)(bbe_cb_abs_i(p->x - target_x) -
                                  bbe_cb_abs_i((int)a.x - target_x));
    }

    score -= 120.0f * (float)to_tz;
    if (from_tz) score -= 60.0f;
    return score;
}

static float bbe_cb_block_target_score(const bb_match* m, bb_action a) {
    const bb_frame* f = m->stack_top ? &m->stack[m->stack_top - 1] : NULL;
    if (!f || f->proc != BB_PROC_MOVE || f->a >= BB_NUM_PLAYERS) return -100000.0f;
    int def = bb_slot_at(m, a.x, a.y);
    return bbe_cb_block_score(m, f->a, def, f->b == BB_ACT_BLITZ);
}

static float bbe_cb_pass_handoff_score(const bb_match* m, bb_action a) {
    int team = m->decision_team & 1;
    int rec = bb_slot_at(m, a.x, a.y);
    if (rec >= 0 && BB_TEAM_OF(rec) == team && a.x == bb_endzone_x(team)) {
        return 4000.0f;
    }
    if (a.x == bb_endzone_x(team)) return 700.0f;
    return -900.0f;
}

static float bbe_cb_choose_die_score(const bb_match* m, bb_action a) {
    const bb_frame* f = m->stack_top ? &m->stack[m->stack_top - 1] : NULL;
    if (!f || f->proc != BB_PROC_BLOCK || a.arg > 2) return 0.0f;
    int face = (f->data >> (3 * a.arg)) & 7;
    int att = f->a, def = f->b;
    int attacker_choice = (m->decision_team & 1) == BB_TEAM_OF(att);
    int att_block = bb_has_block(m, att) && !(m->players[att].flags & BB_PF_DISTRACTED);
    int def_block = bb_has_block(m, def) && !(m->players[def].flags & BB_PF_DISTRACTED);
    if (attacker_choice) {
        switch (face) {
        case BB_BD_POW: return 900.0f;
        case BB_BD_STUMBLE: return 780.0f;
        case BB_BD_PUSH_1:
        case BB_BD_PUSH_2: return 360.0f;
        case BB_BD_BOTH_DOWN:
            return att_block ? (def_block ? 160.0f : 620.0f) : -700.0f;
        case BB_BD_ATTACKER_DOWN: return -1000.0f;
        default: return 0.0f;
        }
    }
    switch (face) {
    case BB_BD_ATTACKER_DOWN: return 900.0f;
    case BB_BD_BOTH_DOWN:
        return (!att_block || def_block) ? 760.0f : 120.0f;
    case BB_BD_PUSH_1:
    case BB_BD_PUSH_2: return 420.0f;
    case BB_BD_STUMBLE: return -420.0f;
    case BB_BD_POW: return -900.0f;
    default: return 0.0f;
    }
}

static float bbe_cb_reroll_score(const bb_match* m, bb_action a) {
    const bb_frame* f = m->stack_top ? &m->stack[m->stack_top - 1] : NULL;
    if (!f) return a.type == BB_A_DECLINE_REROLL ? 50.0f : 0.0f;
    float use = -100.0f;

    if (f->proc == BB_PROC_TEST && f->a < BB_NUM_PLAYERS) {
        const bb_player* p = &m->players[f->a];
        int kind = f->b;
        int important = 0;
        if (kind == BB_TEST_PICKUP) important = 1;
        if ((p->flags & BB_PF_HAS_BALL) &&
            (kind == BB_TEST_DODGE || kind == BB_TEST_RUSH || kind == BB_TEST_JUMP)) {
            important = 1;
        }
        if ((p->flags & BB_PF_HAS_BALL) && p->x == bb_endzone_x(BB_TEAM_OF(f->a))) {
            important = 1;
        }
        use = important ? 650.0f : -50.0f;
        if (a.arg == BB_RR_SKILL) use += 160.0f;
        if (a.arg == BB_RR_PRO) use -= 80.0f;
        if (f->x <= 3) use += 80.0f;
    } else if (f->proc == BB_PROC_BLOCK && f->a < BB_NUM_PLAYERS) {
        float best = -100000.0f;
        int nd = ((f->data >> 9) & 3) + 1;
        for (int i = 0; i < nd; i++) {
            bb_action die = {BB_A_CHOOSE_DIE, (uint8_t)i, 0, 0};
            float s = bbe_cb_choose_die_score(m, die);
            if (s > best) best = s;
        }
        int def_carrier = bbe_cb_enemy_carrier(m, BB_TEAM_OF(f->a), f->b);
        use = (best < 250.0f || def_carrier) ? 520.0f : -100.0f;
    } else if (f->proc == BB_PROC_ACTIVATION && f->a < BB_NUM_PLAYERS) {
        use = (m->players[f->a].flags & BB_PF_HAS_BALL) ? 450.0f : -100.0f;
    }

    if (a.type == BB_A_USE_REROLL) return use;
    return use > 0.0f ? 0.0f : 80.0f;
}

static float bbe_cb_skill_score(const bb_match* m, bb_action a) {
    const bb_frame* f = m->stack_top ? &m->stack[m->stack_top - 1] : NULL;
    if (a.type == BB_A_DECLINE_SKILL) return 0.0f;
    if (a.type != BB_A_USE_SKILL) return 0.0f;
    if (a.arg == BB_SK_WRESTLE && f && f->proc == BB_PROC_BLOCK) {
        int owner_team = m->decision_team & 1;
        int owner = owner_team == BB_TEAM_OF(f->a) ? f->a : f->b;
        if (m->players[owner].flags & BB_PF_HAS_BALL) return -250.0f;
        if (bbe_cb_enemy_carrier(m, owner_team, owner == f->a ? f->b : f->a)) {
            return 700.0f;
        }
        return 180.0f;
    }
    if (a.arg == BB_SK_DODGE || a.arg == BB_SK_SURE_HANDS || a.arg == BB_SK_BLOCK) {
        return 500.0f;
    }
    return 180.0f;
}

static float bbe_cb_push_square_score(const bb_match* m, bb_action a) {
    const bb_frame* f = m->stack_top ? &m->stack[m->stack_top - 1] : NULL;
    if (!f || f->proc != BB_PROC_PUSH || f->b >= BB_NUM_PLAYERS) return 0.0f;
    int pushee = f->b;
    int team = m->decision_team & 1;
    int pushee_team = BB_TEAM_OF(pushee);
    int toward_own_score = bbe_cb_abs_i((int)a.x - bbe_cb_defensive_endzone_x(pushee_team));
    float score = 0.0f;
    if (team != pushee_team) {
        score += 40.0f * (float)toward_own_score;
        int side = a.y < BB_PITCH_WID - 1 - a.y ? a.y : BB_PITCH_WID - 1 - a.y;
        score += 25.0f * (float)(7 - side);
        if (bbe_cb_enemy_carrier(m, team, pushee)) score += 1000.0f;
    } else {
        score -= 40.0f * (float)toward_own_score;
        score -= 80.0f * (float)bb_tackle_zones(m, team, a.x, a.y);
    }
    return score;
}

static float bbe_cb_score_action(const bb_match* m, const bb_action* legal,
                                 int n, int i) {
    (void)legal;
    (void)n;
    bb_action a = legal[i];
    switch (a.type) {
    case BB_A_SETUP_PLACE:
    case BB_A_SETUP_REMOVE:
    case BB_A_SETUP_DONE:
        return bbe_cb_setup_score(m, a, i);
    case BB_A_KICK_TARGET: {
        int team = m->decision_team & 1;
        int tx = team == BB_HOME ? 22 : 3;
        int ty = 7;
        int d = bbe_cb_cheb(a.x, a.y, tx, ty);
        return 1000.0f - 25.0f * (float)d;
    }
    case BB_A_TOUCHBACK: {
        if (a.arg < BB_NUM_PLAYERS) {
            const bb_player* p = &m->players[a.arg];
            return 1800.0f - 25.0f * (float)bbe_cb_endzone_dist(BB_TEAM_OF(a.arg), p->x)
                   + 20.0f * (float)p->ma;
        }
        return 500.0f;
    }
    case BB_A_ACTIVATE:
    case BB_A_END_TURN:
        return bbe_cb_activate_score(m, a);
    case BB_A_DECLARE:
        return bbe_cb_declare_score(m, a);
    case BB_A_STEP:
    case BB_A_JUMP:
        return bbe_cb_step_like_score(m, a) - (a.type == BB_A_JUMP ? 160.0f : 0.0f);
    case BB_A_STAND_UP:
        return 260.0f;
    case BB_A_BLOCK_TARGET:
        return bbe_cb_block_target_score(m, a);
    case BB_A_PASS_TARGET:
    case BB_A_HANDOFF_TARGET:
        return bbe_cb_pass_handoff_score(m, a);
    case BB_A_FOUL_TARGET:
    case BB_A_TTM_TARGET:
    case BB_A_SPECIAL_TARGET:
        return -350.0f;
    case BB_A_END_ACTIVATION:
        return 10.0f;
    case BB_A_CHOOSE_DIE:
        return bbe_cb_choose_die_score(m, a);
    case BB_A_PUSH_SQUARE:
        return bbe_cb_push_square_score(m, a);
    case BB_A_FOLLOW_UP:
        return a.arg ? 200.0f : 20.0f;
    case BB_A_USE_REROLL:
    case BB_A_DECLINE_REROLL:
        return bbe_cb_reroll_score(m, a);
    case BB_A_USE_SKILL:
    case BB_A_DECLINE_SKILL:
        return bbe_cb_skill_score(m, a);
    case BB_A_APOTHECARY:
        return a.arg ? 300.0f : 0.0f;
    case BB_A_CHOOSE_OPTION:
        return a.arg == 0xFE ? -20.0f : 50.0f - (float)i * 0.001f;
    case BB_A_SECURE_BALL:
        return 1200.0f;
    default:
        return 0.0f;
    }
}

static bb_action bbe_contact_bot_pick(const bb_match* m, const bb_action* legal, int n) {
    if (n <= 0) return (bb_action){BB_A_NONE, 0, 0, 0};
    if (n == 1) return legal[0];
    int best_i = 0;
    float best = bbe_cb_score_action(m, legal, n, 0);
    for (int i = 1; i < n; i++) {
        float s = bbe_cb_score_action(m, legal, n, i);
        if (s > best) {
            best = s;
            best_i = i;
        }
    }
    return legal[best_i];
}
