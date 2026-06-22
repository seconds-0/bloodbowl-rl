// offense_bot.h -- deterministic bashy cage-advance scripted offense.
//
// Like contact_bot, this bot never invents actions: it scores the engine's
// current legal bb_action list and returns one exact legal action. The plan is
// intentionally simple and conservative: secure the ball, build the four
// diagonal cage corners, grind toward the scoring endzone, and throw only
// skill-aware low-turnover blocks.
#pragma once

#include "contact_bot.h"
#include "bb/bb_reachability.h"

#define BBE_OB_BLOCK_TURNOVER_MAX 0.17f
#define BBE_OB_PICKUP_P_MIN 0.62f

static int bbe_ob_attack_dir(int team) { return team == BB_HOME ? 1 : -1; }

static int bbe_ob_endzone_dist(int team, int x) {
    return bbe_cb_abs_i(x - bb_endzone_x(team));
}

static int bbe_ob_team_carrier(const bb_match* m, int team) {
    if (m->ball.state != BB_BALL_HELD || m->ball.carrier == BB_NO_PLAYER) {
        return BB_NO_PLAYER;
    }
    return BB_TEAM_OF(m->ball.carrier) == team ? m->ball.carrier : BB_NO_PLAYER;
}

static int bbe_ob_carrier_can_score_now(const bb_match* m, int carrier) {
    if (carrier >= BB_NUM_PLAYERS || !bbe_cb_standing_on_pitch(m, carrier)) return 0;
    const bb_player* p = &m->players[carrier];
    int reach = p->ma - p->moved;
    if (reach < 0) reach = 0;
    reach += bb_max_rushes(m, carrier) - p->rushes;
    return bbe_ob_endzone_dist(BB_TEAM_OF(carrier), p->x) <= reach;
}

static int bbe_ob_cage_corner_xy(const bb_match* m, int carrier,
                                 int idx, int* x, int* y) {
    if (carrier >= BB_NUM_PLAYERS) return 0;
    const bb_player* c = &m->players[carrier];
    if (c->location != BB_LOC_ON_PITCH) return 0;
    static const int dx[4] = {-1, -1, 1, 1};
    static const int dy[4] = {-1, 1, -1, 1};
    *x = (int)c->x + dx[idx & 3];
    *y = (int)c->y + dy[idx & 3];
    return bb_on_pitch_xy(*x, *y);
}

static int bbe_ob_empty_cage_corners(const bb_match* m, int carrier,
                                     int xs[4], int ys[4]) {
    int n = 0;
    int team = BB_TEAM_OF(carrier);
    for (int i = 0; i < 4; i++) {
        int x, y;
        if (!bbe_ob_cage_corner_xy(m, carrier, i, &x, &y)) continue;
        int s = bb_slot_at(m, x, y);
        if (s >= 0 && BB_TEAM_OF(s) == team && bbe_cb_standing_on_pitch(m, s)) {
            continue;
        }
        xs[n] = x;
        ys[n] = y;
        n++;
    }
    return n;
}

static int bbe_ob_square_is_empty_cage_corner(const bb_match* m, int carrier,
                                              int x, int y) {
    int xs[4], ys[4];
    int n = bbe_ob_empty_cage_corners(m, carrier, xs, ys);
    for (int i = 0; i < n; i++) {
        if (xs[i] == x && ys[i] == y) return 1;
    }
    return 0;
}

static int bbe_ob_min_empty_corner_dist(const bb_match* m, int carrier,
                                        int x, int y) {
    int xs[4], ys[4];
    int n = bbe_ob_empty_cage_corners(m, carrier, xs, ys);
    int best = 99;
    for (int i = 0; i < n; i++) {
        int d = bbe_cb_cheb(x, y, xs[i], ys[i]);
        if (d < best) best = d;
    }
    return best == 99 ? 0 : best;
}

static int bbe_ob_adjacent_enemy_count(const bb_match* m, int team, int x, int y) {
    int n = 0;
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            if (!dx && !dy) continue;
            int nx = x + dx, ny = y + dy;
            if (!bb_on_pitch_xy(nx, ny)) continue;
            int s = bb_slot_at(m, nx, ny);
            if (s >= 0 && BB_TEAM_OF(s) != team && bbe_cb_standing_on_pitch(m, s)) {
                n++;
            }
        }
    }
    return n;
}

static int bbe_ob_threatens_cage_or_lane(const bb_match* m, int team, int def) {
    if (!bbe_cb_standing_on_pitch(m, def)) return 0;
    int carrier = bbe_ob_team_carrier(m, team);
    if (carrier == BB_NO_PLAYER) return 0;
    const bb_player* c = &m->players[carrier];
    const bb_player* d = &m->players[def];
    if (bb_adjacent(c->x, c->y, d->x, d->y)) return 1;

    int dir = bbe_ob_attack_dir(team);
    int ahead = dir * ((int)d->x - (int)c->x);
    int lateral = bbe_cb_abs_i((int)d->y - (int)c->y);
    if (ahead >= 1 && ahead <= 4 && lateral <= 2) return 1;

    for (int i = 0; i < 4; i++) {
        int x, y;
        if (bbe_ob_cage_corner_xy(m, carrier, i, &x, &y) &&
            bb_adjacent(x, y, d->x, d->y)) {
            return 1;
        }
    }
    return 0;
}

static float bbe_ob_allowed_block_score(const bb_match* m, int att, int def,
                                        int is_blitz) {
    if (att < 0 || att >= BB_NUM_PLAYERS || def < 0 || def >= BB_NUM_PLAYERS) {
        return -100000.0f;
    }
    if (!bbe_cb_standing_on_pitch(m, att) || !bbe_cb_standing_on_pitch(m, def)) {
        return -100000.0f;
    }

    bb_blockev ev;
    bb_block_ev(m, att, def, is_blitz, NULL, &ev);
    if (ev.p_turnover > BBE_OB_BLOCK_TURNOVER_MAX) return -100000.0f;

    int team = BB_TEAM_OF(att);
    float context = 0.0f;
    if (bbe_ob_threatens_cage_or_lane(m, team, def)) context += 240.0f;
    if (bbe_cb_enemy_carrier(m, team, def)) context += 360.0f;
    context += 60.0f * ev.p_def_removed + 120.0f * ev.p_ball_out;

    return 1000000.0f * ev.p_def_down + context;
}

static float bbe_ob_best_adjacent_allowed_block(const bb_match* m, int slot,
                                                int is_blitz) {
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
            float s = bbe_ob_allowed_block_score(m, slot, def, is_blitz);
            if (s > best) best = s;
        }
    }
    return best;
}

static float bbe_ob_setup_score(const bb_match* m, bb_action a, int index) {
    return bbe_cb_setup_score(m, a, index);
}

static float bbe_ob_activate_score(const bb_match* m, bb_action a) {
    if (a.type == BB_A_END_TURN) return -1200.0f;
    if (a.type != BB_A_ACTIVATE || a.arg >= BB_NUM_PLAYERS) return 0.0f;

    int slot = a.arg;
    int team = BB_TEAM_OF(slot);
    const bb_player* p = &m->players[slot];
    float score = 80.0f - (float)BB_SLOT_OF(slot) * 0.01f;

    if (m->ball.state == BB_BALL_ON_GROUND && p->location == BB_LOC_ON_PITCH) {
        int d = bbe_cb_cheb(p->x, p->y, m->ball.x, m->ball.y);
        int tz = bb_tackle_zones(m, team, m->ball.x, m->ball.y);
        int reach = p->ma + bb_max_rushes(m, slot);
        if (d <= reach && tz <= 1 && p->ag <= 3) {
            score += 5200.0f - 170.0f * (float)d - 260.0f * (float)tz;
        } else {
            score += 1600.0f - 70.0f * (float)d - 180.0f * (float)tz;
        }
    }

    int carrier = bbe_ob_team_carrier(m, team);
    if (carrier == slot) {
        if (bbe_ob_carrier_can_score_now(m, slot)) return 9000.0f;
        int xs[4], ys[4];
        int holes = bbe_ob_empty_cage_corners(m, slot, xs, ys);
        score += holes == 0 ? 6200.0f : 3600.0f - 350.0f * (float)holes;
        score -= 22.0f * (float)bbe_ob_endzone_dist(team, p->x);
        return score;
    }

    if (carrier != BB_NO_PLAYER && p->location == BB_LOC_ON_PITCH) {
        int d = bbe_ob_min_empty_corner_dist(m, carrier, p->x, p->y);
        if (d > 0) score += 4300.0f - 260.0f * (float)d;
        const bb_player* c = &m->players[carrier];
        if (bb_adjacent(p->x, p->y, c->x, c->y)) score += 500.0f;
    }

    float block = bbe_ob_best_adjacent_allowed_block(m, slot, 0);
    if (block > -99999.0f) score += 1400.0f + block * 0.001f;
    return score;
}

static float bbe_ob_declare_score(const bb_match* m, bb_action a) {
    const bb_frame* f = m->stack_top ? &m->stack[m->stack_top - 1] : NULL;
    int slot = f && f->proc == BB_PROC_ACTIVATION ? f->a : BB_NO_PLAYER;
    if (a.type != BB_A_DECLARE || slot >= BB_NUM_PLAYERS) return 0.0f;

    if (a.arg == BB_ACT_BLOCK) {
        float b = bbe_ob_best_adjacent_allowed_block(m, slot, 0);
        return b > -99999.0f ? 5200.0f + b * 0.001f : -1200.0f;
    }
    if (a.arg == BB_ACT_BLITZ) {
        float b = bbe_ob_best_adjacent_allowed_block(m, slot, 1);
        if (b > -99999.0f) return 4700.0f + b * 0.001f;
        return -900.0f;
    }
    if (a.arg == BB_ACT_SECURE_BALL && m->ball.state == BB_BALL_ON_GROUND) {
        return 2500.0f;
    }
    if (a.arg == BB_ACT_MOVE) return 3600.0f;
    if (a.arg == BB_ACT_PASS || a.arg == BB_ACT_HANDOFF) return -900.0f;
    if (a.arg == BB_ACT_FOUL) return -600.0f;
    return -150.0f;
}

static float bbe_ob_step_like_score(const bb_match* m, bb_action a) {
    const bb_frame* f = m->stack_top ? &m->stack[m->stack_top - 1] : NULL;
    if (!f || f->proc != BB_PROC_MOVE || f->a >= BB_NUM_PLAYERS) return 0.0f;
    int slot = f->a;
    int team = BB_TEAM_OF(slot);
    const bb_player* p = &m->players[slot];
    int to_tz = bb_tackle_zones(m, team, a.x, a.y);
    int from_tz = p->location == BB_LOC_ON_PITCH ? bb_tackle_zones(m, team, p->x, p->y) : 0;
    int rush_test = 0, dodge_test = 0, pickup_test = 0;
    float rush_p = 1.0f, dodge_p = 1.0f, pickup_p = 1.0f;
    bb_step_success_components(m, slot, a.x, a.y, f->b == BB_ACT_BLITZ,
                               &rush_test, &rush_p, &dodge_test, &dodge_p,
                               &pickup_test, &pickup_p);
    float ps = (float)bb_step_success_p255(m, slot, a.x, a.y, f->b == BB_ACT_BLITZ) / 255.0f;
    float score = 20.0f + 80.0f * ps - 140.0f * (float)to_tz;

    if (m->ball.state == BB_BALL_ON_GROUND && m->ball.x == a.x && m->ball.y == a.y) {
        if (ps >= BBE_OB_PICKUP_P_MIN && to_tz <= 1) {
            return 9000.0f + 600.0f * ps - 260.0f * (float)to_tz;
        }
        return 450.0f * ps - 900.0f - 350.0f * (float)to_tz;
    }

    if (p->flags & BB_PF_HAS_BALL) {
        int before = bbe_ob_endzone_dist(team, p->x);
        int after = bbe_ob_endzone_dist(team, a.x);
        int progress = before - after;
        int scores = a.x == bb_endzone_x(team);
        if (scores) {
            score += 20000.0f + 500.0f * ps;
        } else {
            if (rush_test) score -= 4500.0f;
            score += 4600.0f + 520.0f * (float)progress - 28.0f * (float)after;
            score += 240.0f * (float)bbe_cb_adjacent_friendlies(m, team, slot, a.x, a.y);
            score -= 300.0f * (float)to_tz;
            if (from_tz) score -= 420.0f;
            if (progress < 0) score -= 700.0f;
        }
        return score;
    }

    int carrier = bbe_ob_team_carrier(m, team);
    if (carrier != BB_NO_PLAYER) {
        int before = bbe_ob_min_empty_corner_dist(m, carrier, p->x, p->y);
        int after = bbe_ob_min_empty_corner_dist(m, carrier, a.x, a.y);
        if (bbe_ob_square_is_empty_cage_corner(m, carrier, a.x, a.y)) {
            score += 7600.0f;
        } else {
            score += 520.0f * (float)(before - after) - 35.0f * (float)after;
        }
        if (rush_test) score -= 1200.0f;
        if (dodge_test) score -= 700.0f;
        return score;
    }

    if (m->ball.state == BB_BALL_ON_GROUND) {
        int before = bbe_cb_cheb(p->x, p->y, m->ball.x, m->ball.y);
        int after = bbe_cb_cheb(a.x, a.y, m->ball.x, m->ball.y);
        score += 380.0f * (float)(before - after) - 22.0f * (float)after;
        score += 140.0f * (float)bbe_ob_adjacent_enemy_count(m, team, a.x, a.y);
    }
    (void)rush_p;
    (void)dodge_p;
    (void)pickup_p;
    (void)pickup_test;
    return score;
}

static float bbe_ob_block_target_score(const bb_match* m, bb_action a) {
    const bb_frame* f = m->stack_top ? &m->stack[m->stack_top - 1] : NULL;
    if (!f || f->proc != BB_PROC_MOVE || f->a >= BB_NUM_PLAYERS) return -100000.0f;
    int def = bb_slot_at(m, a.x, a.y);
    return bbe_ob_allowed_block_score(m, f->a, def, f->b == BB_ACT_BLITZ);
}

static float bbe_ob_push_square_score(const bb_match* m, bb_action a) {
    const bb_frame* f = m->stack_top ? &m->stack[m->stack_top - 1] : NULL;
    if (!f || f->proc != BB_PROC_PUSH || f->b >= BB_NUM_PLAYERS) return 0.0f;
    int team = m->decision_team & 1;
    int pushee = f->b;
    int dir = bbe_ob_attack_dir(team);
    float score = 0.0f;
    if (BB_TEAM_OF(pushee) != team) {
        score += 55.0f * (float)(dir * (int)a.x);
        int carrier = bbe_ob_team_carrier(m, team);
        if (carrier != BB_NO_PLAYER) {
            const bb_player* c = &m->players[carrier];
            int before = bbe_cb_cheb(m->players[pushee].x, m->players[pushee].y, c->x, c->y);
            int after = bbe_cb_cheb(a.x, a.y, c->x, c->y);
            score += 180.0f * (float)(after - before);
        }
    } else {
        score -= 120.0f * (float)bb_tackle_zones(m, team, a.x, a.y);
    }
    return score;
}

static float bbe_ob_score_action(const bb_match* m, const bb_action* legal,
                                 int n, int i) {
    (void)legal;
    (void)n;
    bb_action a = legal[i];
    switch (a.type) {
    case BB_A_SETUP_PLACE:
    case BB_A_SETUP_REMOVE:
    case BB_A_SETUP_DONE:
        return bbe_ob_setup_score(m, a, i);
    case BB_A_KICK_TARGET:
    case BB_A_TOUCHBACK:
        return bbe_cb_score_action(m, legal, n, i);
    case BB_A_ACTIVATE:
    case BB_A_END_TURN:
        return bbe_ob_activate_score(m, a);
    case BB_A_DECLARE:
        return bbe_ob_declare_score(m, a);
    case BB_A_STEP:
    case BB_A_JUMP:
        return bbe_ob_step_like_score(m, a) - (a.type == BB_A_JUMP ? 300.0f : 0.0f);
    case BB_A_STAND_UP:
        return 300.0f;
    case BB_A_BLOCK_TARGET:
        return bbe_ob_block_target_score(m, a);
    case BB_A_PASS_TARGET:
    case BB_A_HANDOFF_TARGET:
    case BB_A_FOUL_TARGET:
    case BB_A_TTM_TARGET:
    case BB_A_SPECIAL_TARGET:
        return -800.0f;
    case BB_A_END_ACTIVATION:
        return 70.0f;
    case BB_A_CHOOSE_DIE:
        return bbe_cb_choose_die_score(m, a);
    case BB_A_PUSH_SQUARE:
        return bbe_ob_push_square_score(m, a);
    case BB_A_FOLLOW_UP:
        return a.arg ? 120.0f : 40.0f;
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
        return 1800.0f;
    default:
        return 0.0f;
    }
}

static bb_action bbe_offense_bot_pick(const bb_match* m, const bb_action* legal, int n) {
    if (n <= 0) return (bb_action){BB_A_NONE, 0, 0, 0};
    if (n == 1) return legal[0];
    int best_i = 0;
    float best = bbe_ob_score_action(m, legal, n, 0);
    for (int i = 1; i < n; i++) {
        float s = bbe_ob_score_action(m, legal, n, i);
        if (s > best) {
            best = s;
            best_i = i;
        }
    }
    return legal[best_i];
}
