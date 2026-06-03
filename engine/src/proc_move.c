// proc_move.c — the MOVE machine driving every activation kind.
//
// Frame: a = slot, b = bb_act_kind. x,y = pending step destination.
// data bits:
//   bit0 block_done    (blitz block performed)
//   bit1 action_done   (pass/handoff/foul performed)
//   bit2 rush_pending  (rush test queued for the pending step)
//   bit3 dodge_pending (dodge test queued for the pending step)
//   bit4 await_test    (a step test result is on m->ret)
//   bit5 await_pickup  (a pickup test result is on m->ret)
//   bit6 await_block   (a blitz block child just ran)
//   bit7 await_action  (pass/handoff/foul child just ran)
//   bit8 stand_pending (stand-up roll for MA<3 queued)
//
// Step sequence per BB2025: declare step -> rush test (if beyond MA) -> dodge
// test (if leaving a marked square) -> move -> pickup (if ball on square) ->
// touchdown check. Failed rush/dodge: the player is moved to the destination
// square and is Knocked Down there; failed pickup: ball bounces; both are
// turnovers (knockdown of active player / failed pickup).
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb/bb_hooks.h"

enum {
    MV_BLOCK_DONE = 1 << 0,
    MV_ACTION_DONE = 1 << 1,
    MV_RUSH_PEND = 1 << 2,
    MV_DODGE_PEND = 1 << 3,
    MV_AWAIT_TEST = 1 << 4,
    MV_AWAIT_PICKUP = 1 << 5,
    MV_AWAIT_BLOCK = 1 << 6,
    MV_AWAIT_ACTION = 1 << 7,
    MV_STAND_PEND = 1 << 8,
    // bit 9..13: target slot for a rush-for-block (5 bits, 0..31)
    MV_BLOCK_RUSH = 1 << 14,
};

static int movement_left(const bb_match* m, int slot) {
    const bb_player* p = &m->players[slot];
    int left = p->ma - p->moved;
    return left > 0 ? left : 0;
}

static bool can_step(const bb_match* m, int slot) {
    const bb_player* p = &m->players[slot];
    if (p->stance != BB_STANCE_STANDING) return false;
    if (p->flags & BB_PF_ROOTED) return false;
    return movement_left(m, slot) > 0 || p->rushes < bb_max_rushes(m, slot);
}

static void finish_move(bb_match* m) {
    bb_pop(m);
}

static void execute_step(bb_match* m, bb_rng* rng, bb_frame* f) {
    (void)rng;
    int slot = f->a;
    bb_player* p = &m->players[slot];
    int x = f->x, y = f->y;
    if (p->moved >= p->ma) p->rushes++;
    p->moved++;
    bb_place(m, slot, x, y);
    if (p->flags & BB_PF_HAS_BALL) {
        m->ball.x = (uint8_t)x;
        m->ball.y = (uint8_t)y;
        if (bb_check_td(m)) return;
    }
    // Pick up the ball if it is on the destination square.
    if (m->ball.state == BB_BALL_ON_GROUND && m->ball.x == x && m->ball.y == y) {
        f->data |= MV_AWAIT_PICKUP;
        if (f->b == BB_ACT_SECURE_BALL) {
            // Secure the Ball: a flat 2+ regardless of AG; weather still
            // applies (May 2026 FAQ: pick-up modifiers like rain apply).
            int target = m->weather == BB_WEATHER_RAIN ? 3 : 2;
            bb_push(m, BB_PROC_TEST, slot, BB_TEST_GENERIC, target, 0);
        } else {
            bb_ctx c = {BB_TEST_PICKUP, (uint8_t)slot, BB_NO_PLAYER,
                        (int8_t)x, (int8_t)y, (int8_t)x, (int8_t)y, -1, 0};
            int mod = -bb_tackle_zones(m, BB_TEAM_OF(slot), x, y) +
                      bb_hook_mods(m, &c);
            if (m->weather == BB_WEATHER_RAIN) mod -= 1;
            bb_push(m, BB_PROC_TEST, slot, BB_TEST_PICKUP,
                    bb_test_target(p->ag, mod), 0);
        }
    }
}

static void move_advance(bb_match* m, bb_rng* rng) {
    bb_frame* f = bb_top(m);
    int slot = f->a;
    bb_player* p = &m->players[slot];

    if (f->data & MV_AWAIT_TEST) {
        f->data &= (uint16_t)~MV_AWAIT_TEST;
        bool was_rush = (f->data & MV_RUSH_PEND) != 0;
        f->data &= (uint16_t)~MV_RUSH_PEND;
        if (f->data & MV_BLOCK_RUSH) {
            // Rush-for-block resolved.
            int target = (f->data >> 9) & 31;
            f->data &= (uint16_t)~(MV_BLOCK_RUSH | (31u << 9));
            if (m->ret & 1) {
                f->data |= MV_AWAIT_BLOCK;
                bb_push(m, BB_PROC_BLOCK, slot, target, 0, 0);
            } else {
                // Failed rush: knocked down in their own square, no block.
                bb_pop(m); // MOVE
                bb_knockdown(m, slot, BB_KD_FAILED_RUSH, 0);
            }
            return;
        }
        if (!(m->ret & 1)) {
            // Failed rush or dodge: player moves to the destination and is
            // knocked down there. Pop MOVE FIRST so the knockdown resolves on
            // top of the parent activation.
            int dx = f->x, dy = f->y;
            f->data &= (uint16_t)~MV_DODGE_PEND;
            if (p->moved >= p->ma) p->rushes++;
            p->moved++;
            bb_place(m, slot, dx, dy);
            if (p->flags & BB_PF_HAS_BALL) {
                m->ball.x = (uint8_t)dx;
                m->ball.y = (uint8_t)dy;
            }
            bb_pop(m); // MOVE
            bb_knockdown(m, slot, was_rush ? BB_KD_FAILED_RUSH : BB_KD_FAILED_DODGE, 0);
            return;
        }
        // Passed; run the next queued test or execute the step.
        if (f->data & MV_DODGE_PEND) {
            f->data &= (uint16_t)~MV_DODGE_PEND;
            bb_ctx c = {BB_TEST_DODGE, (uint8_t)slot, BB_NO_PLAYER,
                        (int8_t)p->x, (int8_t)p->y, (int8_t)f->x, (int8_t)f->y, -1,
                        f->b == BB_ACT_BLITZ};
            int mod = -bb_tackle_zones(m, BB_TEAM_OF(slot), f->x, f->y) +
                      bb_hook_mods(m, &c);
            f->data |= MV_AWAIT_TEST;
            bb_push(m, BB_PROC_TEST, slot, BB_TEST_DODGE,
                    bb_test_target(p->ag, mod), 0);
            return;
        }
        execute_step(m, rng, f);
        return;
    }

    if (f->data & MV_AWAIT_PICKUP) {
        f->data &= (uint16_t)~MV_AWAIT_PICKUP;
        if (m->ret & 1) {
            bb_give_ball(m, slot);
            if (bb_check_td(m)) return;
            if (f->b == BB_ACT_SECURE_BALL) {
                finish_move(m); // securing the ball ends the activation
                return;
            }
        } else {
            // Failed pickup: ball bounces, turnover. Pop MOVE first so the
            // bounce resolves cleanly above the activation.
            int bx = m->ball.x, by = m->ball.y;
            bb_turnover(m);
            bb_pop(m); // MOVE
            bb_push(m, BB_PROC_SCATTER, 0, 1, bx, by);
            return;
        }
        // fall through to decision loop
    }

    if (f->data & MV_AWAIT_BLOCK) {
        f->data &= (uint16_t)~MV_AWAIT_BLOCK;
        // Attacker may have gone down or the turn turned over.
    }
    if (f->data & MV_AWAIT_ACTION) {
        // Pass/hand-off/foul ends the activation. For ball actions, this code
        // runs only after the full catch/bounce chain has settled, so it is
        // the correct place for the possession turnover check: a pass or
        // hand-off that the acting team does not end up holding is a turnover.
        if (f->b == BB_ACT_PASS || f->b == BB_ACT_HANDOFF) {
            int c = m->ball.carrier;
            if (c == BB_NO_PLAYER || BB_TEAM_OF(c) != m->active_team) {
                bb_turnover(m);
            }
        }
        finish_move(m);
        return;
    }

    if (f->data & MV_STAND_PEND) {
        f->data &= (uint16_t)~MV_STAND_PEND;
        if (m->ret & 1) {
            // MA<3 stand-up: stands but may not move further this activation.
            p->stance = BB_STANCE_STANDING;
            p->moved = (uint8_t)p->ma;
            p->rushes = (uint8_t)bb_max_rushes(m, slot);
        } else {
            finish_move(m); // failed 4+ stand for MA<3: activation ends
            return;
        }
    }

    if (m->turnover) {
        finish_move(m);
        return;
    }
    if (p->location != BB_LOC_ON_PITCH || p->stance == BB_STANCE_STUNNED ||
        p->stance == BB_STANCE_STUNNED_USED) {
        finish_move(m);
        return;
    }
    if (p->stance == BB_STANCE_PRONE && p->moved > 0) {
        finish_move(m); // can't stand after moving
        return;
    }
    bb_need_decision(m, BB_TEAM_OF(slot));
}

static int move_legal(const bb_match* m, bb_action* out) {
    const bb_frame* f = &m->stack[m->stack_top - 1];
    int slot = f->a;
    int kind = f->b;
    const bb_player* p = &m->players[slot];
    int n = 0;

    if (p->stance == BB_STANCE_PRONE) {
        // Standing up costs 3 movement (MA<3: 4+ roll, no further movement).
        out[n++] = (bb_action){BB_A_STAND_UP, 0, 0, 0};
        out[n++] = (bb_action){BB_A_END_ACTIVATION, 0, 0, 0};
        return n;
    }

    bool may_move = kind != BB_ACT_BLOCK; // a plain Block action has no movement
    if (may_move && can_step(m, slot)) {
        for (int dx = -1; dx <= 1; dx++) {
            for (int dy = -1; dy <= 1; dy++) {
                if (!dx && !dy) continue;
                int nx = p->x + dx, ny = p->y + dy;
                if (!bb_on_pitch_xy(nx, ny)) continue;
                if (m->grid[nx][ny]) continue; // occupied (jump: phase 3)
                out[n++] = (bb_action){BB_A_STEP, 0, (uint8_t)nx, (uint8_t)ny};
            }
        }
    }

    bool block_ok = false;
    if (kind == BB_ACT_BLOCK && !(f->data & MV_BLOCK_DONE)) block_ok = true;
    if (kind == BB_ACT_BLITZ && !(f->data & MV_BLOCK_DONE) &&
        (movement_left(m, slot) > 0 || p->rushes < bb_max_rushes(m, slot))) {
        block_ok = true; // may Rush to gain the movement for the block
    }
    if (block_ok && p->stance == BB_STANCE_STANDING) {
        for (int dx = -1; dx <= 1; dx++) {
            for (int dy = -1; dy <= 1; dy++) {
                if (!dx && !dy) continue;
                int nx = p->x + dx, ny = p->y + dy;
                if (!bb_on_pitch_xy(nx, ny)) continue;
                int s = bb_slot_at(m, nx, ny);
                if (s >= 0 && BB_TEAM_OF(s) != BB_TEAM_OF(slot) &&
                    m->players[s].stance == BB_STANCE_STANDING) {
                    out[n++] = (bb_action){BB_A_BLOCK_TARGET, 0, (uint8_t)nx, (uint8_t)ny};
                }
            }
        }
    }

    if (kind == BB_ACT_PASS && !(f->data & MV_ACTION_DONE) && (p->flags & BB_PF_HAS_BALL)) {
        // Ruler reach: 13.5 squares (d^2 <= 182.25). Blizzard: only Quick and
        // Short passes may be attempted (d^2 <= 42.25).
        int max_d2 = m->weather == BB_WEATHER_BLIZZARD ? 42 : 182;
        for (int x = 0; x < BB_PITCH_LEN; x++) {
            for (int y = 0; y < BB_PITCH_WID; y++) {
                int dx = x - p->x, dy = y - p->y;
                if (!dx && !dy) continue;
                if (dx * dx + dy * dy <= max_d2 && n < BB_LEGAL_MAX - 2) {
                    out[n++] = (bb_action){BB_A_PASS_TARGET, 0, (uint8_t)x, (uint8_t)y};
                }
            }
        }
    }

    if (kind == BB_ACT_HANDOFF && !(f->data & MV_ACTION_DONE) && (p->flags & BB_PF_HAS_BALL)) {
        for (int dx = -1; dx <= 1; dx++) {
            for (int dy = -1; dy <= 1; dy++) {
                if (!dx && !dy) continue;
                int nx = p->x + dx, ny = p->y + dy;
                if (!bb_on_pitch_xy(nx, ny)) continue;
                int s = bb_slot_at(m, nx, ny);
                if (s >= 0 && BB_TEAM_OF(s) == BB_TEAM_OF(slot) && bb_can_catch(m, s)) {
                    out[n++] = (bb_action){BB_A_HANDOFF_TARGET, 0, (uint8_t)nx, (uint8_t)ny};
                }
            }
        }
    }

    if (kind == BB_ACT_FOUL && !(f->data & MV_ACTION_DONE)) {
        for (int dx = -1; dx <= 1; dx++) {
            for (int dy = -1; dy <= 1; dy++) {
                if (!dx && !dy) continue;
                int nx = p->x + dx, ny = p->y + dy;
                if (!bb_on_pitch_xy(nx, ny)) continue;
                int s = bb_slot_at(m, nx, ny);
                if (s >= 0 && BB_TEAM_OF(s) != BB_TEAM_OF(slot) &&
                    m->players[s].stance != BB_STANCE_STANDING) {
                    out[n++] = (bb_action){BB_A_FOUL_TARGET, 0, (uint8_t)nx, (uint8_t)ny};
                }
            }
        }
    }

    out[n++] = (bb_action){BB_A_END_ACTIVATION, 0, 0, 0};
    return n;
}

static void move_apply(bb_match* m, bb_action a, bb_rng* rng) {
    bb_frame* f = bb_top(m);
    int slot = f->a;
    bb_player* p = &m->players[slot];

    switch (a.type) {
        case BB_A_END_ACTIVATION:
            finish_move(m);
            return;

        case BB_A_STAND_UP:
            if (p->ma < 3) {
                f->data |= MV_STAND_PEND;
                bb_push(m, BB_PROC_TEST, slot, BB_TEST_GENERIC, 4, 0);
                return;
            }
            p->stance = BB_STANCE_STANDING;
            p->moved = 3;
            return;

        case BB_A_STEP: {
            f->x = a.x;
            f->y = a.y;
            bool rush = p->moved >= p->ma;
            bool dodge = bb_tackle_zones(m, BB_TEAM_OF(slot), p->x, p->y) > 0;
            if (rush) f->data |= MV_RUSH_PEND;
            if (dodge) f->data |= MV_DODGE_PEND;
            if (rush) {
                // Rush first: 2+ (Blizzard: an additional -1, so 3+).
                int rush_target = m->weather == BB_WEATHER_BLIZZARD ? 3 : 2;
                f->data &= (uint16_t)~MV_RUSH_PEND;
                f->data |= MV_AWAIT_TEST | (dodge ? MV_DODGE_PEND : 0) | MV_RUSH_PEND;
                bb_push(m, BB_PROC_TEST, slot, BB_TEST_RUSH, rush_target, 0);
                return;
            }
            if (dodge) {
                f->data &= (uint16_t)~MV_DODGE_PEND;
                bb_ctx c = {BB_TEST_DODGE, (uint8_t)slot, BB_NO_PLAYER,
                            (int8_t)p->x, (int8_t)p->y, (int8_t)a.x, (int8_t)a.y, -1,
                            f->b == BB_ACT_BLITZ};
                int mod = -bb_tackle_zones(m, BB_TEAM_OF(slot), a.x, a.y) +
                          bb_hook_mods(m, &c);
                f->data |= MV_AWAIT_TEST;
                bb_push(m, BB_PROC_TEST, slot, BB_TEST_DODGE,
                        bb_test_target(p->ag, mod), 0);
                return;
            }
            execute_step(m, rng, f);
            return;
        }

        case BB_A_BLOCK_TARGET: {
            int target = bb_slot_at(m, a.x, a.y);
            f->data |= MV_AWAIT_BLOCK | MV_BLOCK_DONE;
            if (f->b == BB_ACT_BLITZ) {
                bool rush_needed = movement_left(m, slot) == 0;
                p->flags |= BB_PF_BLITZED;
                if (rush_needed) {
                    // Rush to gain the point of movement for the block: roll
                    // first; failure = knocked down in place, no block.
                    p->rushes++;
                    f->x = p->x;
                    f->y = p->y;
                    f->data |= MV_AWAIT_TEST | MV_RUSH_PEND | MV_BLOCK_RUSH;
                    int rush_target = m->weather == BB_WEATHER_BLIZZARD ? 3 : 2;
                    bb_push(m, BB_PROC_TEST, slot, BB_TEST_RUSH, rush_target, 0);
                    f->data = (uint16_t)(f->data | ((uint16_t)target << 9));
                    return;
                }
                p->moved++; // the blitz block costs one square of movement
            }
            bb_push(m, BB_PROC_BLOCK, slot, target, 0, 0);
            return;
        }

        case BB_A_PASS_TARGET:
            f->data |= MV_AWAIT_ACTION | MV_ACTION_DONE;
            bb_push(m, BB_PROC_PASS, slot, 0, a.x, a.y);
            return;

        case BB_A_HANDOFF_TARGET: {
            int rec = bb_slot_at(m, a.x, a.y);
            f->data |= MV_AWAIT_ACTION | MV_ACTION_DONE;
            bb_push(m, BB_PROC_HANDOFF, slot, rec, 0, 0);
            return;
        }

        case BB_A_FOUL_TARGET: {
            int target = bb_slot_at(m, a.x, a.y);
            f->data |= MV_AWAIT_ACTION | MV_ACTION_DONE;
            bb_push(m, BB_PROC_FOUL, slot, target, 0, 0);
            return;
        }
    }
    m->status = BB_STATUS_ERROR;
}

const bb_proc_vtable bb_proc_move_vtable = {move_advance, move_legal, move_apply};
