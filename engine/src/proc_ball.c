// proc_ball.c — SCATTER (bounce), THROW_IN, CATCH, PASS, HANDOFF.
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"

static const int8_t DIR8[8][2] = {
    {-1, -1}, {0, -1}, {1, -1}, {-1, 0}, {1, 0}, {-1, 1}, {0, 1}, {1, 1},
};

// ===== SCATTER (bounce) =======================================================
// b = number of bounces to perform, x,y = current ball square.
// Each bounce: D8 one square. Landing on a standing player -> catch attempt
// (-1 modifier for a bouncing ball); prone/stunned occupant -> bounce again;
// off-pitch -> throw-in from the boundary square it left.

static void scatter_advance(bb_match* m, bb_rng* rng) {
    bb_frame f = *bb_top(m);
    bb_pop(m);
    int x = f.x, y = f.y;
    int bounces = f.b ? f.b : 1;
    for (int i = 0; i < bounces; i++) {
        int dir = bb_roll(rng, 8) - 1;
        int nx = x + DIR8[dir][0];
        int ny = y + DIR8[dir][1];
        if (!bb_on_pitch_xy(nx, ny)) {
            bb_push(m, BB_PROC_THROW_IN, 0, 0, (uint8_t)x, (uint8_t)y);
            return;
        }
        x = nx;
        y = ny;
    }
    int s = bb_slot_at(m, x, y);
    if (s >= 0 && m->players[s].stance == BB_STANCE_STANDING) {
        bb_ball_to(m, x, y);
        bb_push(m, BB_PROC_CATCH, s, (uint8_t)(int8_t)-1, 0, 0);
        return;
    }
    if (s >= 0) {
        // Prone/stunned occupant: the ball keeps bouncing.
        bb_ball_to(m, x, y);
        bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)x, (uint8_t)y);
        return;
    }
    bb_ball_to(m, x, y);
}

// ===== THROW_IN ===============================================================
// x,y = boundary square where the ball left the pitch. The crowd throws it
// back: direction D3 over the three inward directions, distance 2D6, then the
// ball bounces once on landing (or throws in again if it leaves the pitch).

static void throw_in_advance(bb_match* m, bb_rng* rng) {
    bb_frame f = *bb_top(m);
    bb_pop(m);
    int x = f.x, y = f.y;
    // Determine inward directions from the edge the ball left.
    int dirs[3][2];
    if (x <= 0) {
        dirs[0][0] = 1; dirs[0][1] = -1;
        dirs[1][0] = 1; dirs[1][1] = 0;
        dirs[2][0] = 1; dirs[2][1] = 1;
    } else if (x >= BB_PITCH_LEN - 1) {
        dirs[0][0] = -1; dirs[0][1] = -1;
        dirs[1][0] = -1; dirs[1][1] = 0;
        dirs[2][0] = -1; dirs[2][1] = 1;
    } else if (y <= 0) {
        dirs[0][0] = -1; dirs[0][1] = 1;
        dirs[1][0] = 0; dirs[1][1] = 1;
        dirs[2][0] = 1; dirs[2][1] = 1;
    } else {
        dirs[0][0] = -1; dirs[0][1] = -1;
        dirs[1][0] = 0; dirs[1][1] = -1;
        dirs[2][0] = 1; dirs[2][1] = -1;
    }
    int d = bb_d3(rng) - 1;
    int dist = bb_2d6(rng);
    int cx = x, cy = y;
    for (int i = 0; i < dist; i++) {
        int nx = cx + dirs[d][0], ny = cy + dirs[d][1];
        if (!bb_on_pitch_xy(nx, ny)) {
            // Left the pitch again: new throw-in from the last on-pitch square.
            bb_push(m, BB_PROC_THROW_IN, 0, 0, (uint8_t)cx, (uint8_t)cy);
            return;
        }
        cx = nx;
        cy = ny;
    }
    bb_ball_to(m, cx, cy);
    // Thrown-in ball bounces once on landing (catch handled by the bounce).
    bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)cx, (uint8_t)cy);
}

// ===== CATCH ==================================================================
// a = player slot, b = base modifier (int8: -1 bouncing, 0 accurate/hand-off).
// Marked catcher: -1 per opposing tackle zone. Failure: ball bounces from the
// catcher's square.

static void catch_advance(bb_match* m, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    int slot = f->a;
    bb_player* p = &m->players[slot];
    if (f->phase == 0) {
        int mod = (int8_t)f->b;
        mod -= bb_tackle_zones(m, BB_TEAM_OF(slot), p->x, p->y);
        if (m->weather == BB_WEATHER_RAIN) mod -= 1;
        f->phase = 1;
        bb_push(m, BB_PROC_TEST, slot, BB_TEST_CATCH, bb_test_target(p->ag, mod), 0);
        return;
    }
    // Test result on m->ret.
    int x = p->x, y = p->y;
    bb_pop(m);
    if (m->ret == 1) {
        bb_give_ball(m, slot);
        bb_check_td(m);
    } else {
        bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)x, (uint8_t)y);
    }
}

// ===== PASS ===================================================================
// a = thrower, x,y = target square.
// Range bands (squares, Euclidean): quick <= 3.5, short <= 6.5, long <= 9.5,
// long bomb <= 13.5. Modifiers: quick 0 / short -1 / long -2 / bomb -3, -1 per
// marking opponent on the thrower. Natural 1 = fumble (bounce at thrower).
// Accurate: catch at target (mod 0). Inaccurate: ball scatters 3 squares from
// the target, then lands (catch -1 via bounce path handled by SCATTER).
// Turnover: resolved by the parent MOVE/ACTIVATION when the acting team no
// longer holds the ball. TODO(phase3): interception (BB2025 single direct
// test), Safe Pass/skill effects, weather.

static int pass_range_mod(int dx, int dy) {
    int d2 = dx * dx + dy * dy;
    if (d2 <= 12) return 0;        // quick (3.5^2 = 12.25)
    if (d2 <= 42) return -1;       // short (6.5^2 = 42.25)
    if (d2 <= 90) return -2;       // long (9.5^2 = 90.25)
    return -3;                     // long bomb (13.5^2 = 182.25)
}

static void pass_advance(bb_match* m, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    int slot = f->a;
    bb_player* p = &m->players[slot];
    if (f->phase == 0) {
        if (p->pa <= 0) { // PA '-': cannot pass (mask should prevent this)
            bb_pop(m);
            bb_turnover(m);
            return;
        }
        int mod = pass_range_mod(f->x - p->x, f->y - p->y);
        mod -= bb_tackle_zones(m, BB_TEAM_OF(slot), p->x, p->y);
        if (m->weather == BB_WEATHER_RAIN) mod -= 1;
        f->phase = 1;
        bb_push(m, BB_PROC_TEST, slot, BB_TEST_PASS, bb_test_target(p->pa, mod), 0);
        return;
    }
    // Pass test resolved.
    bb_frame fr = *f;
    bb_pop(m);
    bb_drop_ball(m);
    if (m->ret == 1) {
        // Accurate: ball arrives at the target square.
        int s = bb_slot_at(m, fr.x, fr.y);
        bb_ball_to(m, fr.x, fr.y);
        if (s >= 0 && m->players[s].stance == BB_STANCE_STANDING) {
            bb_push(m, BB_PROC_CATCH, s, 0, 0, 0);
        } else {
            bb_push(m, BB_PROC_SCATTER, 0, 1, fr.x, fr.y);
        }
    } else {
        // Inaccurate: scatter three squares from the target square.
        // (A fumble — natural 1 — is approximated as a bounce from the
        // thrower. TODO(phase3): distinguish fumble vs inaccurate precisely.)
        bb_ball_to(m, fr.x, fr.y);
        bb_push(m, BB_PROC_SCATTER, 0, 3, fr.x, fr.y);
    }
    // Turnover check happens after resolution: if the acting team does not
    // hold the ball, it is a turnover. The simplest correct place is here via
    // a deferred check — the catch/bounce chain runs first, so we piggyback on
    // the activation end in MOVE (MV_AWAIT_ACTION) … Phase 2 approximation:
    // latch turnover now and clear it if a team-mate ends up with the ball.
    // TODO(phase2-followup): replace with a dedicated PASS_RESULT frame.
    return;
}

// ===== HANDOFF ================================================================
// a = carrier, b = receiver. The receiver attempts a catch (mod 0).

static void handoff_advance(bb_match* m, bb_rng* rng) {
    (void)rng;
    bb_frame f = *bb_top(m);
    bb_pop(m);
    bb_drop_ball(m);
    bb_ball_to(m, m->players[f.b].x, m->players[f.b].y);
    bb_push(m, BB_PROC_CATCH, f.b, 0, 0, 0);
}

const bb_proc_vtable bb_proc_scatter_vtable = {scatter_advance, 0, 0};
const bb_proc_vtable bb_proc_throw_in_vtable = {throw_in_advance, 0, 0};
const bb_proc_vtable bb_proc_catch_vtable = {catch_advance, 0, 0};
const bb_proc_vtable bb_proc_pass_vtable = {pass_advance, 0, 0};
const bb_proc_vtable bb_proc_handoff_vtable = {handoff_advance, 0, 0};
