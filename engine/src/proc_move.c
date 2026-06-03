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
    // bit 9..13: target slot for a rush-for-block / pending jump-rush count
    MV_BLOCK_RUSH = 1 << 14,
    MV_JUMP = 1 << 15,
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
    int slot = f->a;
    bb_player* p = &m->players[slot];
    int x = f->x, y = f->y;
    int vx = p->x, vy = p->y; // vacated square
    if (p->moved >= p->ma) p->rushes++;
    p->moved++;
    bb_place(m, slot, x, y);
    // SHADOWING: a player whose TZ the mover just left may follow: D6 4+
    // places them into the vacated square. (Per-turn use cap = MA is TODO;
    // first eligible shadower follows; never auto-shadow with the carrier's
    // marker... shadower may carry the ball - relocation keeps possession.)
    for (int sdx = -1; sdx <= 1; sdx++) {
        bool followed = false;
        for (int sdy = -1; sdy <= 1; sdy++) {
            if (!sdx && !sdy) continue;
            int nx0 = vx + sdx, ny0 = vy + sdy;
            if (!bb_on_pitch_xy(nx0, ny0)) continue;
            if (nx0 == x && ny0 == y) continue;
            int ss = bb_slot_at(m, nx0, ny0);
            if (ss < 0 || BB_TEAM_OF(ss) == BB_TEAM_OF(slot)) continue;
            if (!bb_exerts_tz(m, ss)) continue;
            if (!bb_has_skill(&m->players[ss].skills, BB_SK_SHADOWING)) continue;
            // Still adjacent to the mover's new square? Then no need.
            if (bb_adjacent(nx0, ny0, x, y)) continue;
            if (bb_d6(rng) >= 4 && !m->grid[vx][vy]) {
                bb_place(m, ss, vx, vy);
                if (m->players[ss].flags & BB_PF_HAS_BALL) {
                    m->ball.x = (uint8_t)vx;
                    m->ball.y = (uint8_t)vy;
                }
            }
            followed = true;
            break;
        }
        if (followed) break;
    }
    if (p->flags & BB_PF_HAS_BALL) {
        m->ball.x = (uint8_t)x;
        m->ball.y = (uint8_t)y;
        if (bb_check_td(m)) return;
    }
    // Pick up the ball if it is on the destination square.
    if (m->ball.state == BB_BALL_ON_GROUND && m->ball.x == x && m->ball.y == y) {
        if (bb_has_skill(&p->skills, BB_SK_NO_BALL)) {
            // NO BALL: "will automatically fail ... as if they had rolled a
            // natural 1" — the ball bounces, turnover.
            int bx = x, by = y;
            bb_turnover(m);
            bb_pop(m); // MOVE
            bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)bx, (uint8_t)by);
            return;
        }
        f->data |= MV_AWAIT_PICKUP;
        if (f->b == BB_ACT_SECURE_BALL) {
            // Secure the Ball: a flat 2+ regardless of AG; weather still
            // applies (May 2026 FAQ: pick-up modifiers like rain apply).
            int target = m->weather == BB_WEATHER_RAIN ? 3 : 2;
            bb_push(m, BB_PROC_TEST, slot, BB_TEST_GENERIC, target, 0);
        } else {
            bb_ctx c = {BB_TEST_PICKUP, (uint8_t)slot, BB_NO_PLAYER, (uint8_t)slot,
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

    if ((f->data & MV_AWAIT_TEST) && (f->data & MV_JUMP)) {
        f->data &= (uint16_t)~MV_AWAIT_TEST;
        bool was_rush = (f->data & MV_RUSH_PEND) != 0;
        f->data &= (uint16_t)~MV_RUSH_PEND;
        if (was_rush) {
            if (!(m->ret & 1)) {
                // Failed rush while jumping: fall in the CURRENT square.
                f->data &= (uint16_t)~MV_JUMP;
                bb_pop(m); // MOVE
                bb_knockdown(m, slot, BB_KD_FAILED_RUSH, 0);
                return;
            }
            int remaining = ((f->data >> 9) & 31) - 1;
            f->data = (uint16_t)((f->data & ~(31u << 9)) | ((uint16_t)remaining << 9));
            if (remaining > 0) {
                p->rushes++;
                bb_ctx rc = {BB_TEST_RUSH, (uint8_t)slot, BB_NO_PLAYER, (uint8_t)slot,
                             (int8_t)p->x, (int8_t)p->y, (int8_t)f->x, (int8_t)f->y, -1,
                             f->b == BB_ACT_BLITZ};
                int rmod = bb_hook_mods(m, &rc);
                if (m->weather == BB_WEATHER_BLIZZARD) rmod -= 1;
                f->data |= MV_AWAIT_TEST | MV_RUSH_PEND;
                bb_push(m, BB_PROC_TEST, slot, BB_TEST_RUSH, bb_test_target(2, rmod), 0);
                return;
            }
            // Rushes done: the jump test itself.
            bb_ctx jc = {BB_TEST_JUMP, (uint8_t)slot, BB_NO_PLAYER, (uint8_t)slot,
                         (int8_t)p->x, (int8_t)p->y, (int8_t)f->x, (int8_t)f->y, -1,
                         f->b == BB_ACT_BLITZ};
            int from_tz = bb_tackle_zones(m, BB_TEAM_OF(slot), p->x, p->y);
            int to_tz = bb_tackle_zones(m, BB_TEAM_OF(slot), f->x, f->y);
            int mod = -(from_tz > to_tz ? from_tz : to_tz) + bb_hook_mods(m, &jc);
            f->data |= MV_AWAIT_TEST;
            bb_push(m, BB_PROC_TEST, slot, BB_TEST_JUMP, bb_test_target(p->ag, mod), 0);
            return;
        }
        // The jump AG test resolved.
        f->data &= (uint16_t)~MV_JUMP;
        int tx = f->x, ty = f->y;
        if (!(m->ret & 1)) {
            bb_place(m, slot, tx, ty);
            if (p->flags & BB_PF_HAS_BALL) {
                m->ball.x = (uint8_t)tx;
                m->ball.y = (uint8_t)ty;
            }
            bb_pop(m); // MOVE
            bb_knockdown(m, slot, BB_KD_FAILED_DODGE, 0);
            return;
        }
        bb_place(m, slot, tx, ty);
        if (p->flags & BB_PF_HAS_BALL) {
            m->ball.x = (uint8_t)tx;
            m->ball.y = (uint8_t)ty;
            if (bb_check_td(m)) return;
        }
        if (m->ball.state == BB_BALL_ON_GROUND && m->ball.x == tx && m->ball.y == ty) {
            if (bb_has_skill(&p->skills, BB_SK_NO_BALL)) {
                bb_turnover(m);
                bb_pop(m);
                bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)tx, (uint8_t)ty);
                return;
            }
            bb_ctx pc = {BB_TEST_PICKUP, (uint8_t)slot, BB_NO_PLAYER, (uint8_t)slot,
                         (int8_t)tx, (int8_t)ty, (int8_t)tx, (int8_t)ty, -1, 0};
            int pmod = -bb_tackle_zones(m, BB_TEAM_OF(slot), tx, ty) + bb_hook_mods(m, &pc);
            if (m->weather == BB_WEATHER_RAIN) pmod -= 1;
            f->data |= MV_AWAIT_PICKUP;
            bb_push(m, BB_PROC_TEST, slot, BB_TEST_PICKUP, bb_test_target(p->ag, pmod), 0);
        }
        return;
    }

    if (f->data & MV_AWAIT_TEST) {
        f->data &= (uint16_t)~MV_AWAIT_TEST;
        bool was_rush = (f->data & MV_RUSH_PEND) != 0;
        f->data &= (uint16_t)~MV_RUSH_PEND;
        // DIVING TACKLE: "after ... re-rolls have been applied" a player
        // marking the vacated square may apply -2 and be Placed Prone there.
        // Auto-applied when it flips a passing dodge into a failure (the only
        // rational use). The diver relocates AFTER the mover vacates.
        int diver = -1;
        if (!was_rush && (m->ret & 1)) {
            int die = (m->ret >> 8) & 0xF;
            int target = (m->ret >> 12) & 7;
            if (die != 6 && die - 2 < target) {
                for (int ddx = -1; ddx <= 1 && diver < 0; ddx++) {
                    for (int ddy = -1; ddy <= 1; ddy++) {
                        if (!ddx && !ddy) continue;
                        int nx0 = p->x + ddx, ny0 = p->y + ddy;
                        if (!bb_on_pitch_xy(nx0, ny0)) continue;
                        int dts = bb_slot_at(m, nx0, ny0);
                        if (dts < 0 || BB_TEAM_OF(dts) == BB_TEAM_OF(slot)) continue;
                        if (!bb_exerts_tz(m, dts)) continue;
                        if (!bb_has_skill(&m->players[dts].skills, BB_SK_DIVING_TACKLE)) continue;
                        // Auto-policy: never dive with the ball carrier (a
                        // carrier Placed Prone would drop the ball).
                        if (m->players[dts].flags & BB_PF_HAS_BALL) continue;
                        diver = dts;
                        m->ret &= (uint16_t)~1u; // the dodge now fails
                        break;
                    }
                }
            }
        }
        if (f->data & MV_BLOCK_RUSH) {
            // Rush-for-block resolved.
            int target = (f->data >> 9) & 31;
            f->data &= (uint16_t)~(MV_BLOCK_RUSH | (31u << 9));
            if (m->ret & 1) {
                f->data |= MV_AWAIT_BLOCK;
                bb_push(m, BB_PROC_BLOCK, slot, target, 0, 0);
                bb_top(m)->data |= 1 << 13; // BLK_IS_BLITZ (rush-for-block)
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
            int vx = p->x, vy = p->y; // vacated square (for Diving Tackle)
            f->data &= (uint16_t)~MV_DODGE_PEND;
            if (p->moved >= p->ma) p->rushes++;
            p->moved++;
            bb_place(m, slot, dx, dy);
            if (p->flags & BB_PF_HAS_BALL) {
                m->ball.x = (uint8_t)dx;
                m->ball.y = (uint8_t)dy;
            }
            if (diver >= 0) {
                bb_place(m, diver, vx, vy);
                m->players[diver].stance = BB_STANCE_PRONE; // Placed Prone: no armour
            }
            bb_pop(m); // MOVE
            bb_knockdown(m, slot, was_rush ? BB_KD_FAILED_RUSH : BB_KD_FAILED_DODGE, 0);
            return;
        }
        // Passed; run the next queued test or execute the step.
        if (f->data & MV_DODGE_PEND) {
            f->data &= (uint16_t)~MV_DODGE_PEND;
            bb_ctx c = {BB_TEST_DODGE, (uint8_t)slot, BB_NO_PLAYER, (uint8_t)slot,
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
        f->data &= (uint16_t)~MV_AWAIT_ACTION;
        // QUICK FOUL: "activation does not end after performing a Foul
        // Action" — continue moving with remaining MA (unless sent off /
        // turnover).
        if (f->b == BB_ACT_FOUL && !m->turnover &&
            p->location == BB_LOC_ON_PITCH &&
            bb_has_skill(&p->skills, BB_SK_QUICK_FOUL)) {
            bb_need_decision(m, BB_TEAM_OF(slot));
            return;
        }
        if (f->b == BB_ACT_PASS || f->b == BB_ACT_HANDOFF) {
            int c = m->ball.carrier;
            if (c == BB_NO_PLAYER || BB_TEAM_OF(c) != m->active_team) {
                bb_turnover(m);
            }
            // GIVE AND GO: after a Quick Pass or a Hand-off without a
            // turnover, the player may continue moving.
            if (!m->turnover && bb_has_skill(&p->skills, BB_SK_GIVE_AND_GO)) {
                bool quick = f->b == BB_ACT_HANDOFF || (f->b == BB_ACT_PASS && f->x == 1);
                if (quick) {
                    bb_need_decision(m, BB_TEAM_OF(slot));
                    return;
                }
            }
        }
        finish_move(m);
        return;
    }

    if (f->data & MV_STAND_PEND) {
        f->data &= (uint16_t)~MV_STAND_PEND;
        if (f->b == BB_ACT_BLOCK) {
            // JUMP UP prone-block test resolved.
            int target = (f->data >> 9) & 31;
            f->data &= (uint16_t)~(31u << 9);
            if (m->ret & 1) {
                p->stance = BB_STANCE_STANDING;
                f->data |= MV_AWAIT_BLOCK | MV_BLOCK_DONE;
                bb_push(m, BB_PROC_BLOCK, slot, target, 0, 0);
            } else {
                finish_move(m); // stays prone; activation ends
            }
            return;
        }
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
        // JUMP UP: stands for free; may also declare a Block whilst Prone
        // (AG test +1: stand and block, or stay down and end).
        out[n++] = (bb_action){BB_A_STAND_UP, 0, 0, 0};
        if (kind == BB_ACT_BLOCK && bb_has_skill(&p->skills, BB_SK_JUMP_UP)) {
            for (int dx = -1; dx <= 1; dx++) {
                for (int dy = -1; dy <= 1; dy++) {
                    if (!dx && !dy) continue;
                    int nx = p->x + dx, ny = p->y + dy;
                    if (!bb_on_pitch_xy(nx, ny)) continue;
                    int s2 = bb_slot_at(m, nx, ny);
                    if (s2 >= 0 && BB_TEAM_OF(s2) != BB_TEAM_OF(slot) &&
                        m->players[s2].stance == BB_STANCE_STANDING) {
                        out[n++] = (bb_action){BB_A_BLOCK_TARGET, 0, (uint8_t)nx, (uint8_t)ny};
                    }
                }
            }
        }
        out[n++] = (bb_action){BB_A_END_ACTIVATION, 0, 0, 0};
        return n;
    }

    bool may_move = kind != BB_ACT_BLOCK; // a plain Block action has no movement
    // TTM/KTM: once the team-mate is picked up, no further movement — the
    // rules sequence is move-then-pick-then-throw, and BB_A_JUMP reuses data
    // bits 9-13 (rush count) which hold the stashed mate slot (review H3).
    if ((kind == BB_ACT_TTM || kind == BB_ACT_KTM) && (f->data & MV_BLOCK_DONE)) {
        may_move = false;
    }
    if (may_move && can_step(m, slot)) {
        for (int dx = -1; dx <= 1; dx++) {
            for (int dy = -1; dy <= 1; dy++) {
                if (!dx && !dy) continue;
                int nx = p->x + dx, ny = p->y + dy;
                if (!bb_on_pitch_xy(nx, ny)) continue;
                if (m->grid[nx][ny]) continue;
                out[n++] = (bb_action){BB_A_STEP, 0, (uint8_t)nx, (uint8_t)ny};
            }
        }
        // JUMPING OVER PLAYERS: over an adjacent Prone/Stunned player (LEAP:
        // over any single adjacent square) into an unoccupied square adjacent
        // to the jumped square but not to the jumper. Costs 2 MA (rushes ok:
        // need movement+rush budget of 2).
        int budget = movement_left(m, slot) + (bb_max_rushes(m, slot) - p->rushes);
        bool leap = bb_has_skill(&p->skills, BB_SK_LEAP) ||
                    bb_has_skill(&p->skills, BB_SK_POGO);
        if (budget >= 2) {
            for (int dx = -1; dx <= 1; dx++) {
                for (int dy = -1; dy <= 1; dy++) {
                    if (!dx && !dy) continue;
                    int jx = p->x + dx, jy = p->y + dy;
                    if (!bb_on_pitch_xy(jx, jy)) continue;
                    int js = bb_slot_at(m, jx, jy);
                    bool jumpable = js >= 0 && m->players[js].stance != BB_STANCE_STANDING;
                    if (!jumpable && !leap) continue;
                    if (leap && js < 0 && false) continue; // leap may cross empty too
                    for (int tx = jx - 1; tx <= jx + 1; tx++) {
                        for (int ty = jy - 1; ty <= jy + 1; ty++) {
                            if (!bb_on_pitch_xy(tx, ty)) continue;
                            if (m->grid[tx][ty]) continue;
                            if (tx == p->x && ty == p->y) continue;
                            if (bb_adjacent(tx, ty, p->x, p->y)) continue; // must be beyond
                            if (n < BB_LEGAL_MAX - 2) {
                                out[n++] = (bb_action){BB_A_JUMP, 0, (uint8_t)tx, (uint8_t)ty};
                            }
                        }
                    }
                }
            }
        }
    }

    // STAB: target an adjacent standing opponent (no movement first — Stab
    // is its own action); also offered during a Blitz as the block
    // replacement (BB_A_SPECIAL_TARGET arg 1).
    if ((kind == BB_ACT_STAB && !(f->data & MV_ACTION_DONE)) ||
        (kind == BB_ACT_BLITZ && !(f->data & MV_BLOCK_DONE) &&
         bb_has_skill(&p->skills, BB_SK_STAB) &&
         (movement_left(m, slot) > 0 || kind == BB_ACT_STAB))) {
        if (p->stance == BB_STANCE_STANDING) {
            for (int dx = -1; dx <= 1; dx++) {
                for (int dy = -1; dy <= 1; dy++) {
                    if (!dx && !dy) continue;
                    int nx = p->x + dx, ny = p->y + dy;
                    if (!bb_on_pitch_xy(nx, ny)) continue;
                    int s2 = bb_slot_at(m, nx, ny);
                    if (s2 >= 0 && BB_TEAM_OF(s2) != BB_TEAM_OF(slot) &&
                        m->players[s2].stance == BB_STANCE_STANDING) {
                        out[n++] = (bb_action){BB_A_SPECIAL_TARGET, 1, (uint8_t)nx, (uint8_t)ny};
                    }
                }
            }
        }
    }
    // CHAINSAW / BREATHE FIRE / PROJECTILE VOMIT: target selection (also as
    // blitz block replacement is TODO for chainsaw; standalone here).
    if ((kind == BB_ACT_CHAINSAW || kind == BB_ACT_BREATHE_FIRE ||
         kind == BB_ACT_VOMIT) && !(f->data & MV_ACTION_DONE) &&
        p->stance == BB_STANCE_STANDING) {
        int variant = kind == BB_ACT_CHAINSAW ? 4 : (kind == BB_ACT_BREATHE_FIRE ? 5 : 6);
        for (int dx = -1; dx <= 1; dx++) {
            for (int dy = -1; dy <= 1; dy++) {
                if (!dx && !dy) continue;
                int nx = p->x + dx, ny = p->y + dy;
                if (!bb_on_pitch_xy(nx, ny)) continue;
                int s2 = bb_slot_at(m, nx, ny);
                if (s2 >= 0 && BB_TEAM_OF(s2) != BB_TEAM_OF(slot) &&
                    m->players[s2].stance == BB_STANCE_STANDING) {
                    out[n++] = (bb_action){BB_A_SPECIAL_TARGET, (uint8_t)variant, (uint8_t)nx, (uint8_t)ny};
                }
            }
        }
    }
    // TTM / KTM: pick the adjacent Right Stuff team-mate (arg 7), then the
    // target square (BB_A_TTM_TARGET, quick/short range only).
    if ((kind == BB_ACT_TTM || kind == BB_ACT_KTM) && !(f->data & MV_ACTION_DONE) &&
        p->stance == BB_STANCE_STANDING) {
        if (!(f->data & MV_BLOCK_DONE)) { // reuse the bit as "mate picked"
            for (int dx = -1; dx <= 1; dx++) {
                for (int dy = -1; dy <= 1; dy++) {
                    if (!dx && !dy) continue;
                    int nx = p->x + dx, ny = p->y + dy;
                    if (!bb_on_pitch_xy(nx, ny)) continue;
                    int s2 = bb_slot_at(m, nx, ny);
                    if (s2 >= 0 && BB_TEAM_OF(s2) == BB_TEAM_OF(slot) &&
                        bb_has_skill(&m->players[s2].skills, BB_SK_RIGHT_STUFF)) {
                        out[n++] = (bb_action){BB_A_SPECIAL_TARGET, 7, (uint8_t)nx, (uint8_t)ny};
                    }
                }
            }
        } else {
            // Quick/Short throw range: d^2 <= 42.25.
            for (int x = 0; x < BB_PITCH_LEN; x++) {
                for (int y = 0; y < BB_PITCH_WID; y++) {
                    int ddx = x - p->x, ddy = y - p->y;
                    if (!ddx && !ddy) continue;
                    if (ddx * ddx + ddy * ddy <= 42 && n < BB_LEGAL_MAX - 2) {
                        out[n++] = (bb_action){BB_A_TTM_TARGET, 0, (uint8_t)x, (uint8_t)y};
                    }
                }
            }
        }
    }
    // HIT AND RUN: after a resolved Block (plain Block action), one free
    // square ignoring TZs that leaves the player unmarked and marking no one.
    if (kind == BB_ACT_BLOCK && (f->data & MV_BLOCK_DONE) &&
        p->stance == BB_STANCE_STANDING &&
        bb_has_skill(&p->skills, BB_SK_HIT_AND_RUN)) {
        for (int dx = -1; dx <= 1; dx++) {
            for (int dy = -1; dy <= 1; dy++) {
                if (!dx && !dy) continue;
                int nx = p->x + dx, ny = p->y + dy;
                if (!bb_on_pitch_xy(nx, ny)) continue;
                if (m->grid[nx][ny]) continue;
                if (bb_tackle_zones(m, BB_TEAM_OF(slot), nx, ny) > 0) continue;
                out[n++] = (bb_action){BB_A_SPECIAL_TARGET, 9, (uint8_t)nx, (uint8_t)ny};
            }
        }
    }

    // HYPNOTIC GAZE: after any movement, gaze an adjacent standing opponent.
    if (kind == BB_ACT_GAZE && !(f->data & MV_ACTION_DONE) &&
        p->stance == BB_STANCE_STANDING) {
        for (int dx = -1; dx <= 1; dx++) {
            for (int dy = -1; dy <= 1; dy++) {
                if (!dx && !dy) continue;
                int nx = p->x + dx, ny = p->y + dy;
                if (!bb_on_pitch_xy(nx, ny)) continue;
                int s2 = bb_slot_at(m, nx, ny);
                if (s2 >= 0 && BB_TEAM_OF(s2) != BB_TEAM_OF(slot) &&
                    m->players[s2].stance == BB_STANCE_STANDING) {
                    out[n++] = (bb_action){BB_A_SPECIAL_TARGET, 2, (uint8_t)nx, (uint8_t)ny};
                }
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
        // Short passes may be attempted (d^2 <= 42.25). HAIL MARY PASS: "may
        // declare any square on the pitch as the target square".
        int max_d2 = m->weather == BB_WEATHER_BLIZZARD ? 42 : 182;
        if (bb_has_skill(&p->skills, BB_SK_HAIL_MARY_PASS) &&
            m->weather != BB_WEATHER_BLIZZARD) {
            max_d2 = 32767;
        }
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
            if (bb_has_skill(&p->skills, BB_SK_JUMP_UP)) {
                p->stance = BB_STANCE_STANDING; // free
                return;
            }
            if (p->ma < 3) {
                bb_ctx sc = {BB_TEST_STANDUP, (uint8_t)slot, BB_NO_PLAYER, (uint8_t)slot,
                             (int8_t)p->x, (int8_t)p->y, (int8_t)p->x, (int8_t)p->y, -1, 0};
                f->data |= MV_STAND_PEND;
                bb_push(m, BB_PROC_TEST, slot, BB_TEST_STANDUP,
                        bb_test_target(4, bb_hook_mods(m, &sc)), 0);
                return;
            }
            p->stance = BB_STANCE_STANDING;
            p->moved = 3;
            return;

        case BB_A_JUMP: {
            f->x = a.x;
            f->y = a.y;
            f->data |= MV_JUMP;
            int rushes_needed = 2 - movement_left(m, slot);
            if (rushes_needed < 0) rushes_needed = 0;
            // Charge the movement now; rushes roll one at a time first.
            p->moved = (uint8_t)(p->moved + (2 - rushes_needed) > p->ma
                                     ? p->ma : p->moved + (2 - rushes_needed));
            f->data = (uint16_t)((f->data & ~(31u << 9)) | ((uint16_t)rushes_needed << 9));
            if (rushes_needed > 0) {
                p->rushes++;
                bb_ctx rc = {BB_TEST_RUSH, (uint8_t)slot, BB_NO_PLAYER, (uint8_t)slot,
                             (int8_t)p->x, (int8_t)p->y, (int8_t)a.x, (int8_t)a.y, -1,
                             f->b == BB_ACT_BLITZ};
                int rmod = bb_hook_mods(m, &rc);
                if (m->weather == BB_WEATHER_BLIZZARD) rmod -= 1;
                f->data |= MV_AWAIT_TEST | MV_RUSH_PEND;
                bb_push(m, BB_PROC_TEST, slot, BB_TEST_RUSH, bb_test_target(2, rmod), 0);
                return;
            }
            // No rushes: straight to the jump test.
            bb_ctx jc = {BB_TEST_JUMP, (uint8_t)slot, BB_NO_PLAYER, (uint8_t)slot,
                         (int8_t)p->x, (int8_t)p->y, (int8_t)a.x, (int8_t)a.y, -1,
                         f->b == BB_ACT_BLITZ};
            int from_tz = bb_tackle_zones(m, BB_TEAM_OF(slot), p->x, p->y);
            int to_tz = bb_tackle_zones(m, BB_TEAM_OF(slot), a.x, a.y);
            int mod = -(from_tz > to_tz ? from_tz : to_tz) + bb_hook_mods(m, &jc);
            f->data |= MV_AWAIT_TEST;
            bb_push(m, BB_PROC_TEST, slot, BB_TEST_JUMP, bb_test_target(p->ag, mod), 0);
            return;
        }

        case BB_A_STEP: {
            // TENTACLES: when leaving a tentacled player's TZ, that player
            // may try to hold the mover: D6 + own ST - mover ST >= 6 (or a
            // natural 6) cancels the move and ends the activation (no fall,
            // no turnover). Resolves BEFORE the move and any dodge (FAQ).
            for (int tdx = -1; tdx <= 1; tdx++) {
                for (int tdy = -1; tdy <= 1; tdy++) {
                    if (!tdx && !tdy) continue;
                    int nx = p->x + tdx, ny = p->y + tdy;
                    if (!bb_on_pitch_xy(nx, ny)) continue;
                    int ts = bb_slot_at(m, nx, ny);
                    if (ts < 0 || BB_TEAM_OF(ts) == BB_TEAM_OF(slot)) continue;
                    if (!bb_exerts_tz(m, ts)) continue;
                    if (!bb_has_skill(&m->players[ts].skills, BB_SK_TENTACLES)) continue;
                    int die = bb_d6(rng);
                    if (die == 6 || die + m->players[ts].st - p->st >= 6) {
                        finish_move(m); // held: activation ends in place
                        return;
                    }
                    tdx = 2; // one attempt per step (strongest-first TODO)
                    break;
                }
            }
            f->x = a.x;
            f->y = a.y;
            bool rush = p->moved >= p->ma;
            bool dodge = bb_tackle_zones(m, BB_TEAM_OF(slot), p->x, p->y) > 0;
            if (rush) f->data |= MV_RUSH_PEND;
            if (dodge) f->data |= MV_DODGE_PEND;
            if (rush) {
                // Rush: 2+, Blizzard -1, plus skill mods (Drunkard...).
                bb_ctx rc = {BB_TEST_RUSH, (uint8_t)slot, BB_NO_PLAYER, (uint8_t)slot,
                             (int8_t)p->x, (int8_t)p->y, (int8_t)a.x, (int8_t)a.y, -1,
                             f->b == BB_ACT_BLITZ};
                int rmod = bb_hook_mods(m, &rc);
                if (m->weather == BB_WEATHER_BLIZZARD) rmod -= 1;
                f->data &= (uint16_t)~MV_RUSH_PEND;
                f->data |= MV_AWAIT_TEST | (dodge ? MV_DODGE_PEND : 0) | MV_RUSH_PEND;
                bb_push(m, BB_PROC_TEST, slot, BB_TEST_RUSH, bb_test_target(2, rmod), 0);
                return;
            }
            if (dodge) {
                f->data &= (uint16_t)~MV_DODGE_PEND;
                bb_ctx c = {BB_TEST_DODGE, (uint8_t)slot, BB_NO_PLAYER, (uint8_t)slot,
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
            if (p->stance == BB_STANCE_PRONE) {
                // JUMP UP prone block: AG test +1; pass = stand and block.
                bb_ctx jc = {BB_TEST_GENERIC, (uint8_t)slot, (uint8_t)target, (uint8_t)slot,
                             (int8_t)p->x, (int8_t)p->y, (int8_t)a.x, (int8_t)a.y, -1, 0};
                f->data |= MV_STAND_PEND;
                f->data = (uint16_t)((f->data & ~(31u << 9)) | ((uint16_t)target << 9));
                bb_push(m, BB_PROC_TEST, slot, BB_TEST_GENERIC,
                        bb_test_target(p->ag, 1 + bb_hook_mods(m, &jc)), 0);
                return;
            }
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
                    bb_ctx rc = {BB_TEST_RUSH, (uint8_t)slot, BB_NO_PLAYER, (uint8_t)slot,
                                 (int8_t)p->x, (int8_t)p->y, (int8_t)p->x, (int8_t)p->y, -1, 1};
                    int rmod = bb_hook_mods(m, &rc);
                    if (m->weather == BB_WEATHER_BLIZZARD) rmod -= 1;
                    bb_push(m, BB_PROC_TEST, slot, BB_TEST_RUSH, bb_test_target(2, rmod), 0);
                    f->data = (uint16_t)(f->data | ((uint16_t)target << 9));
                    return;
                }
                p->moved++; // the blitz block costs one square of movement
            }
            bb_push(m, BB_PROC_BLOCK, slot, target, 0, 0);
            if (f->b == BB_ACT_BLITZ) bb_top(m)->data |= 1 << 13; // BLK_IS_BLITZ
            return;
        }

        case BB_A_PASS_TARGET: {
            f->data |= MV_AWAIT_ACTION | MV_ACTION_DONE;
            // Latch whether this is a Quick Pass (Give and Go continuation).
            int qdx = a.x - p->x, qdy = a.y - p->y;
            f->x = (uint8_t)(qdx * qdx + qdy * qdy <= 12 ? 1 : 0);
            bb_push(m, BB_PROC_PASS, slot, 0, a.x, a.y);
            return;
        }

        case BB_A_HANDOFF_TARGET: {
            int rec = bb_slot_at(m, a.x, a.y);
            f->data |= MV_AWAIT_ACTION | MV_ACTION_DONE;
            bb_push(m, BB_PROC_HANDOFF, slot, rec, 0, 0);
            return;
        }

        case BB_A_TTM_TARGET: {
            int mate = (f->data >> 9) & 31;
            // Defense-in-depth (review H3): the stash shares bits with the
            // rush counter; if anything clobbered it, throwing a bogus slot
            // (off-pitch / wrong team / not adjacent / no Right Stuff) would
            // corrupt the grid invisibly. Engine-bug canary, not a rule.
            const bb_player* mp = &m->players[mate];
            if (mp->location != BB_LOC_ON_PITCH ||
                BB_TEAM_OF(mate) != BB_TEAM_OF(slot) ||
                !bb_adjacent(mp->x, mp->y, p->x, p->y) ||
                !bb_has_skill(&mp->skills, BB_SK_RIGHT_STUFF)) {
                m->status = BB_STATUS_ERROR;
                return;
            }
            f->data |= MV_ACTION_DONE | MV_AWAIT_ACTION;
            bb_push(m, BB_PROC_TTM, mate, slot, a.x, a.y);
            if (f->b == BB_ACT_KTM) bb_top(m)->data |= 1;
            return;
        }

        case BB_A_SPECIAL_TARGET: {
            int target = bb_slot_at(m, a.x, a.y);
            if (a.arg == 7) { // TTM: team-mate picked; stash in bits 9-13
                f->data |= MV_BLOCK_DONE;
                f->data = (uint16_t)((f->data & ~(31u << 9)) | ((uint16_t)target << 9));
                return;
            }
            if (a.arg == 9) { // Hit and Run free square (ignores TZs)
                bb_cover(BB_SK_HIT_AND_RUN);
                bb_place(m, slot, a.x, a.y);
                if (p->flags & BB_PF_HAS_BALL) {
                    m->ball.x = p->x;
                    m->ball.y = p->y;
                    if (bb_check_td(m)) return;
                }
                finish_move(m);
                return;
            }
            if (a.arg == 4) { // CHAINSAW: 2+ attack (+3 armour), 1 kick-back
                f->data |= MV_ACTION_DONE | MV_AWAIT_ACTION;
                bb_cover(BB_SK_CHAINSAW);
                if (bb_d6(rng) == 1) {
                    bb_knockdown(m, slot, BB_KD_OTHER, 0); // kick-back (victim-
                    return;                                 // side +3 in ARMOUR)
                }
                bb_push(m, BB_PROC_ARMOUR, target, 0, 3, slot + 1);
                return;
            }
            if (a.arg == 5) { // BREATHE FIRE
                f->data |= MV_ACTION_DONE | MV_AWAIT_ACTION;
                bb_cover(BB_SK_BREATHE_FIRE);
                int mod = m->players[target].st >= 5 ? -1 : 0;
                int die = bb_d6(rng);
                if (die == 1) {
                    bb_knockdown(m, slot, BB_KD_OTHER, 0);
                    return;
                }
                if (die == 6) {
                    bb_knockdown2(m, target, BB_KD_OTHER, 0, slot);
                    return;
                }
                if (die + mod >= 4) {
                    // Placed Prone: no armour; a carrier drops the ball.
                    bb_player* t = &m->players[target];
                    t->stance = BB_STANCE_PRONE;
                    if (t->flags & BB_PF_HAS_BALL) {
                        int bx = t->x, by = t->y;
                        if (BB_TEAM_OF(target) == m->active_team) bb_turnover(m);
                        bb_drop_ball(m);
                        bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)bx, (uint8_t)by);
                    }
                }
                return;
            }
            if (a.arg == 6) { // PROJECTILE VOMIT: 2+ target, 1 self; unmodifiable
                f->data |= MV_ACTION_DONE | MV_AWAIT_ACTION;
                bb_cover(BB_SK_PROJECTILE_VOMIT);
                int victim = bb_d6(rng) >= 2 ? target : slot;
                bb_push(m, BB_PROC_ARMOUR, victim, 3, 0, slot + 1);
                return;
            }
            if (a.arg == 1) {
                // STAB: unmodifiable Armour Roll; armour broken -> Injury;
                // the activation ends (even as a Blitz block replacement).
                if (f->b == BB_ACT_BLITZ) {
                    p->moved++; // replaces the blitz block: costs the square
                    f->data |= MV_BLOCK_DONE;
                }
                f->data |= MV_ACTION_DONE | MV_AWAIT_ACTION;
                bb_push(m, BB_PROC_ARMOUR, target, 3 /* unmodifiable */, 0,
                        slot + 1);
                return;
            }
            // GAZE (arg 2): D6 3+ -> target Distracted; activation ends.
            f->data |= MV_ACTION_DONE;
            if (bb_d6(rng) >= 3) {
                m->players[target].flags |= BB_PF_DISTRACTED;
            }
            finish_move(m);
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
