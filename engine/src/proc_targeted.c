// proc_targeted.c — common interruption point for opposition Block Actions
// and directly-targeted Special Actions.
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb/bb_hooks.h"

enum {
    TA_DUMP_DECLINED = 1 << 0,
    TA_DUMP_USED = 1 << 1,
    TA_DUMP_PASS = 1 << 2,
    TA_TRICK_DECLINED = 1 << 3,
    TA_TRICK_USED = 1 << 4,
    TA_PICKUP_DECLINED = 1 << 5,
    TA_PICKUP_TEST = 1 << 6,
    TA_ACTION_PENDING = 1 << 7,
};

uint8_t bb_targeted_action_public_state(const bb_frame* f) {
    if (!f || f->proc != BB_PROC_TARGETED_ACTION) return 0;
    uint8_t out = 0;
    if (f->data & TA_DUMP_DECLINED) out |= BB_TA_STATE_DUMP_DECLINED;
    if (f->data & TA_DUMP_USED) out |= BB_TA_STATE_DUMP_USED;
    if (f->data & TA_DUMP_PASS) out |= BB_TA_STATE_DUMP_PASS_IN_FLIGHT;
    if (f->data & TA_TRICK_DECLINED) out |= BB_TA_STATE_TRICKSTER_DECLINED;
    if (f->data & TA_TRICK_USED) out |= BB_TA_STATE_TRICKSTER_USED;
    if (f->data & TA_PICKUP_DECLINED) out |= BB_TA_STATE_PICKUP_DECLINED;
    if (f->data & TA_PICKUP_TEST) out |= BB_TA_STATE_PICKUP_TEST_IN_FLIGHT;
    if (f->data & TA_ACTION_PENDING) out |= BB_TA_STATE_ACTION_PENDING;
    return out;
}

void bb_push_targeted_action(bb_match* m, int actor, int target, int kind,
                             int context) {
    bb_push(m, BB_PROC_TARGETED_ACTION, actor, target, kind, context);
}

static bool dump_eligible(const bb_match* m, const bb_frame* f) {
    const bb_player* p = &m->players[f->b];
    return !(f->data & (TA_DUMP_DECLINED | TA_DUMP_USED)) &&
           BB_TEAM_OF(f->a) != BB_TEAM_OF(f->b) &&
           p->location == BB_LOC_ON_PITCH &&
           p->stance == BB_STANCE_STANDING &&
           !(p->flags & BB_PF_DISTRACTED) &&
           (p->flags & BB_PF_HAS_BALL) && p->pa > 0 &&
           !bb_has_skill(&p->skills, BB_SK_MY_BALL) &&
           bb_has_skill(&p->skills, BB_SK_DUMP_OFF);
}

static bool trick_eligible(const bb_match* m, const bb_frame* f) {
    const bb_player* p = &m->players[f->b];
    if ((f->data & (TA_TRICK_DECLINED | TA_TRICK_USED)) ||
        (f->y & BB_TA_FROM_BALL_CHAIN) || BB_TEAM_OF(f->a) == BB_TEAM_OF(f->b) ||
        p->location != BB_LOC_ON_PITCH || p->stance != BB_STANCE_STANDING ||
        (p->flags & BB_PF_ROOTED) ||
        (p->flags & BB_PF_DISTRACTED) || !bb_has_skill(&p->skills, BB_SK_TRICKSTER))
        return false;
    const bb_player* actor = &m->players[f->a];
    for (int dx = -1; dx <= 1; dx++) for (int dy = -1; dy <= 1; dy++) {
        int x = actor->x + dx, y = actor->y + dy;
        if ((dx || dy) && x >= 0 && x < BB_PITCH_LEN && y >= 0 && y < BB_PITCH_WID &&
            !m->grid[x][y]) return true;
    }
    return false;
}

static void targeted_dispatch(bb_match* m, bb_rng* rng, bb_frame f) {
    int actor = f.a, target = f.b;
    bb_top(m)->phase = 3; // retain owner until the targeted Action settles
    bb_top(m)->data |= TA_ACTION_PENDING;
    switch (f.x) {
    case BB_TA_BLOCK:
        bb_push(m, BB_PROC_BLOCK, actor, target, 0, 0);
        if (f.y & BB_TA_FROM_BLITZ) bb_top(m)->data |= 1 << 13;
        if (f.y & BB_TA_FRENZY_SECOND) bb_top(m)->data |= 1 << 15;
        return;
    case BB_TA_STAB:
        bb_push(m, BB_PROC_ARMOUR, target, 3, 0, actor + 1);
        return;
    case BB_TA_CHAINSAW:
        bb_cover(BB_SK_CHAINSAW);
        if (bb_d6(rng) == 1) bb_knockdown(m, actor, BB_KD_OTHER, 0);
        else bb_push(m, BB_PROC_ARMOUR, target, 0, 3, actor + 1);
        return;
    case BB_TA_BREATHE_FIRE: {
        bb_cover(BB_SK_BREATHE_FIRE);
        int mod = m->players[target].st >= 5 ? -1 : 0;
        int die = bb_d6(rng);
        if (die == 1) {
            bb_knockdown(m, actor, BB_KD_OTHER, 0);
        } else if (die == 6) {
            bb_knockdown2(m, target, BB_KD_OTHER, 0, actor);
        } else if (die + mod >= 4) {
            bb_player* t = &m->players[target];
            t->stance = BB_STANCE_PRONE;
            if (t->flags & BB_PF_HAS_BALL) {
                int bx = t->x, by = t->y;
                if (BB_TEAM_OF(target) == m->active_team) bb_turnover(m);
                bb_drop_ball(m);
                bb_push(m, BB_PROC_SCATTER, 0, 1, bx, by);
            }
        }
        return;
    }
    case BB_TA_VOMIT: {
        bb_cover(BB_SK_PROJECTILE_VOMIT);
        int victim = bb_d6(rng) >= 2 ? target : actor;
        bb_push(m, BB_PROC_ARMOUR, victim, 3, 0, actor + 1);
        return;
    }
    case BB_TA_GAZE:
        if (bb_d6(rng) >= 3) m->players[target].flags |= BB_PF_DISTRACTED;
        return;
    default:
        m->status = BB_STATUS_ERROR;
        return;
    }
}

static void targeted_advance(bb_match* m, bb_rng* rng) {
    bb_frame* f = bb_top(m);
    if (f->phase == 2) { // ordinary Dump-off PASS chain completed
        f->data &= (uint16_t)~TA_DUMP_PASS;
        f->phase = 0;
    }
    if (f->phase == 0) {
        if (dump_eligible(m, f) || trick_eligible(m, f)) {
            bb_need_decision(m, BB_TEAM_OF(f->b));
            return;
        }
        targeted_dispatch(m, rng, *f);
        return;
    }
    if (f->phase == 1) {
        bb_need_decision(m, BB_TEAM_OF(f->b));
        return;
    }
    if (f->phase == 4 || f->phase == 5) {
        bb_need_decision(m, BB_TEAM_OF(f->b));
        return;
    }
    if (f->phase == 6) {
        f->data &= (uint16_t)~TA_PICKUP_TEST;
        if (m->ret & 1) {
            bb_give_ball(m, f->b);
            f->phase = 0;
        } else {
            f->phase = 7;
            bb_push(m, BB_PROC_SCATTER, 0, 1, m->players[f->b].x, m->players[f->b].y);
        }
        return;
    }
    if (f->phase == 7) { f->phase = 0; return; }
    if (f->phase == 3) {
        int target = f->b;
        // Trickster may have placed a carrier in the opposition End Zone.
        // The rule delays that TD until the targeting Action fully resolves.
        if (target < BB_NUM_PLAYERS &&
            m->players[target].location == BB_LOC_ON_PITCH &&
            m->players[target].stance == BB_STANCE_STANDING &&
            (m->players[target].flags & BB_PF_HAS_BALL) && bb_check_td(m)) {
            return;
        }
        bb_pop(m);
        return;
    }
    m->status = BB_STATUS_ERROR;
}

static int targeted_legal(const bb_match* m, bb_action* out) {
    const bb_frame* f = &m->stack[m->stack_top - 1];
    int n = 0;
    if (f->phase == 0) {
        if (dump_eligible(m, f)) {
            out[n++] = (bb_action){BB_A_CHOOSE_OPTION, 0, 0, 0}; /* use Dump-off */
            out[n++] = (bb_action){BB_A_CHOOSE_OPTION, 1, 0, 0}; /* decline Dump-off */
        }
        if (trick_eligible(m, f)) {
            out[n++] = (bb_action){BB_A_CHOOSE_OPTION, 2, 0, 0}; /* use Trickster */
            out[n++] = (bb_action){BB_A_CHOOSE_OPTION, 3, 0, 0}; /* decline Trickster */
        }
        return n;
    }
    if (f->phase == 4) {
        const bb_player* actor = &m->players[f->a];
        for (int dx = -1; dx <= 1; dx++) for (int dy = -1; dy <= 1; dy++) {
            int x = actor->x + dx, y = actor->y + dy;
            if ((dx || dy) && x >= 0 && x < BB_PITCH_LEN && y >= 0 && y < BB_PITCH_WID &&
                !m->grid[x][y]) out[n++] = (bb_action){BB_A_SPECIAL_TARGET, BB_SK_TRICKSTER, x, y};
        }
        return n;
    }
    if (f->phase == 5) {
        out[n++] = (bb_action){BB_A_CHOOSE_OPTION, 4, 0, 0}; /* attempt pickup */
        out[n++] = (bb_action){BB_A_CHOOSE_OPTION, 5, 0, 0}; /* decline pickup */
        return n;
    }
    const bb_player* p = &m->players[f->b];
    for (int x = 0; x < BB_PITCH_LEN; x++) {
        for (int y = 0; y < BB_PITCH_WID; y++) {
            int dx = x - p->x, dy = y - p->y;
            if ((dx || dy) && dx * dx + dy * dy <= 12) {
                out[n++] = (bb_action){BB_A_PASS_TARGET, 0, x, y};
            }
        }
    }
    return n;
}

static void targeted_apply(bb_match* m, bb_action a, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    if (f->phase == 0) {
        if (a.arg == 0) {
            f->data |= TA_DUMP_USED;
            bb_cover(BB_SK_DUMP_OFF);
            f->phase = 1;
            bb_need_decision(m, BB_TEAM_OF(f->b));
        } else if (a.arg == 1) f->data |= TA_DUMP_DECLINED;
        else if (a.arg == 2) { f->data |= TA_TRICK_USED; bb_cover(BB_SK_TRICKSTER); f->phase = 4; }
        else if (a.arg == 3) f->data |= TA_TRICK_DECLINED;
        else m->status = BB_STATUS_ERROR;
        return;
    }
    if (f->phase == 4) {
        int target = f->b;
        bb_place(m, target, a.x, a.y);
        if (m->players[target].flags & BB_PF_HAS_BALL) { m->ball.x = a.x; m->ball.y = a.y; }
        if (m->ball.state == BB_BALL_ON_GROUND && m->ball.x == a.x && m->ball.y == a.y) f->phase = 5;
        else f->phase = 0;
        return;
    }
    if (f->phase == 5) {
        if (a.arg == 5) { f->data |= TA_PICKUP_DECLINED; f->phase = 0; return; }
        int target = f->b, x = m->players[target].x, y = m->players[target].y;
        if (bb_has_skill(&m->players[target].skills, BB_SK_NO_BALL)) {
            f->phase = 7;
            bb_push(m, BB_PROC_SCATTER, 0, 1, x, y);
            return;
        }
        bb_ctx c = {BB_TEST_PICKUP, target, BB_NO_PLAYER, target, x, y, x, y, -1, 0};
        int mod = -bb_tackle_zones(m, BB_TEAM_OF(target), x, y);
        if (m->weather == BB_WEATHER_RAIN) mod--;
        mod += bb_hook_mods(m, &c);
        f->data |= TA_PICKUP_TEST;
        f->phase = 6;
        bb_push(m, BB_PROC_TEST, target, BB_TEST_PICKUP,
                bb_test_target(m->players[target].ag, mod), 0);
        return;
    }
    int thrower = f->b;
    f->phase = 2;
    f->data |= TA_DUMP_PASS;
    bb_push(m, BB_PROC_PASS, thrower, 0, a.x, a.y);
    bb_top(m)->data |= BB_PASS_NO_TURNOVER;
}

const bb_proc_vtable bb_proc_targeted_action_vtable = {
    targeted_advance, targeted_legal, targeted_apply,
};
