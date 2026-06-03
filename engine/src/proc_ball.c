// proc_ball.c — SCATTER (bounce/scatter), THROW_IN, CATCH, PASS, HANDOFF.
//
// Catch modifiers (BB2025): bounced ball -1, thrown-in ball -1, scattered
// (inaccurate-pass landing) 0, accurate pass / hand-off 0; always -1 per
// opponent marking the catcher; pouring rain -1. Distracted (or prone/stunned)
// players auto-fail and the ball bounces.
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb/bb_hooks.h"

static const int8_t DIR8[8][2] = {
    {-1, -1}, {0, -1}, {1, -1}, {-1, 0}, {1, 0}, {-1, 1}, {0, 1}, {1, 1},
};

// ===== SCATTER ================================================================
// b = number of single-square hops, x,y = current ball square.
// data bit0 = 1: this is a pass-flight SCATTER (landing catch unmodified, and
// an empty landing square bounces once). Default (0) = a BOUNCE (-1 catch).
// Landing on a standing player -> catch attempt; prone/stunned/distracted
// occupant or empty square after a SCATTER -> one final bounce; off-pitch ->
// throw-in from the last on-pitch square.

static void scatter_advance(bb_match* m, bb_rng* rng) {
    bb_frame f = *bb_top(m);
    bb_pop(m);
    int x = f.x, y = f.y;
    bool is_bounce = (f.data & 1) == 0;
    int hops = f.b ? f.b : 1;
    for (int i = 0; i < hops; i++) {
        int dir = bb_roll(rng, 8) - 1;
        int nx = x + DIR8[dir][0];
        int ny = y + DIR8[dir][1];
        if (!bb_on_pitch_xy(nx, ny)) {
            if (bb_in_kickoff(m)) {
                // A kicked ball leaving the pitch is a touchback, never a
                // throw-in; KICKOFF (below us) resolves it.
                m->ball.state = BB_BALL_OFF_PITCH;
                m->ball.carrier = BB_NO_PLAYER;
                return;
            }
            bb_push(m, BB_PROC_THROW_IN, 0, 0, (uint8_t)x, (uint8_t)y);
            return;
        }
        x = nx;
        y = ny;
    }
    int s = bb_slot_at(m, x, y);
    if (s >= 0 && bb_can_catch(m, s)) {
        bb_ball_to(m, x, y);
        bb_push(m, BB_PROC_CATCH, s, (uint8_t)(int8_t)(is_bounce ? -1 : 0), 0, 0);
        return;
    }
    if (s >= 0) {
        // Prone/stunned/distracted occupant: auto-fail, the ball bounces on.
        bb_ball_to(m, x, y);
        bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)x, (uint8_t)y);
        return;
    }
    bb_ball_to(m, x, y); // comes to rest (scatter and bounce alike)
}

// ===== THROW_IN ===============================================================
// x,y = last on-pitch square before the ball left. The crowd throws it back:
// direction by D6 over the three inward template arrows (1-2/3-4/5-6),
// distance 2D6 counting the boundary square as the FIRST square (so 2D6-1
// steps inward). The ball lands: occupied square -> direct catch at -1;
// empty -> comes to rest (no bounce). Leaving the pitch again -> repeat
// throw-in from the new exit square. Corners use three inward diagonals.

static void throw_in_dirs(int x, int y, int dirs[3][2]) {
    bool left = x <= 0, right = x >= BB_PITCH_LEN - 1;
    bool top = y <= 0, bottom = y >= BB_PITCH_WID - 1;
    int ix = left ? 1 : (right ? -1 : 0);
    int iy = top ? 1 : (bottom ? -1 : 0);
    if (ix && iy) { // corner: three inward directions
        dirs[0][0] = ix; dirs[0][1] = 0;
        dirs[1][0] = ix; dirs[1][1] = iy;
        dirs[2][0] = 0;  dirs[2][1] = iy;
    } else if (ix) { // side edge (left/right)
        dirs[0][0] = ix; dirs[0][1] = -1;
        dirs[1][0] = ix; dirs[1][1] = 0;
        dirs[2][0] = ix; dirs[2][1] = 1;
    } else { // top/bottom edge
        dirs[0][0] = -1; dirs[0][1] = iy;
        dirs[1][0] = 0;  dirs[1][1] = iy;
        dirs[2][0] = 1;  dirs[2][1] = iy;
    }
}

static void throw_in_advance(bb_match* m, bb_rng* rng) {
    bb_frame f = *bb_top(m);
    bb_pop(m);
    int dirs[3][2];
    throw_in_dirs(f.x, f.y, dirs);
    bool corner = (f.x <= 0 || f.x >= BB_PITCH_LEN - 1) &&
                  (f.y <= 0 || f.y >= BB_PITCH_WID - 1);
    // Edge: D6 over the template arrows (1-2/3-4/5-6); corner: D3.
    int d = corner ? bb_d3(rng) - 1 : (bb_d6(rng) - 1) / 2;
    int steps = bb_2d6(rng) - 1;          // boundary square counts as first
    int cx = f.x, cy = f.y;
    for (int i = 0; i < steps; i++) {
        int nx = cx + dirs[d][0], ny = cy + dirs[d][1];
        if (!bb_on_pitch_xy(nx, ny)) {
            bb_push(m, BB_PROC_THROW_IN, 0, 0, (uint8_t)cx, (uint8_t)cy);
            return;
        }
        cx = nx;
        cy = ny;
    }
    int s = bb_slot_at(m, cx, cy);
    if (s >= 0 && bb_can_catch(m, s)) {
        bb_ball_to(m, cx, cy);
        bb_push(m, BB_PROC_CATCH, s, (uint8_t)(int8_t)-1, 0, 0); // thrown-in -1
        return;
    }
    if (s >= 0) {
        // Occupied by a player who cannot catch: the ball bounces.
        bb_ball_to(m, cx, cy);
        bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)cx, (uint8_t)cy);
        return;
    }
    bb_ball_to(m, cx, cy); // comes to rest
}

// ===== CATCH ==================================================================
// a = player slot, b = base modifier (int8: -1 bounce/throw-in, 0 otherwise).

static void catch_advance(bb_match* m, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    int slot = f->a;
    bb_player* p = &m->players[slot];
    if (f->phase == 0) {
        if (!bb_can_catch(m, slot) ||
            bb_has_skill(&p->skills, BB_SK_NO_BALL)) { // distracted/prone/No Ball: auto-fail
            int x = p->x, y = p->y;
            bb_pop(m);
            bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)x, (uint8_t)y);
            return;
        }
        bb_ctx c = {BB_TEST_CATCH, (uint8_t)slot, BB_NO_PLAYER,
                    (int8_t)p->x, (int8_t)p->y, (int8_t)p->x, (int8_t)p->y, -1, 0};
        int mod = (int8_t)f->b;
        mod -= bb_tackle_zones(m, BB_TEAM_OF(slot), p->x, p->y);
        mod += bb_hook_mods(m, &c);
        if (m->weather == BB_WEATHER_RAIN) mod -= 1;
        f->phase = 1;
        bb_push(m, BB_PROC_TEST, slot, BB_TEST_CATCH, bb_test_target(p->ag, mod), 0);
        return;
    }
    // Test result on m->ret.
    int x = p->x, y = p->y;
    bb_pop(m);
    if (m->ret & 1) {
        bb_give_ball(m, slot);
        bb_check_td(m);
    } else {
        bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)x, (uint8_t)y);
    }
}

// ===== PASS ===================================================================
// a = thrower, x,y = target square. data: low 8 bits = signed PA-test modifier
// total (for the fumble check), bit8 = inaccurate latch.
//
// BB2025 sequence: PA test (range 0/-1/-2/-3, -1 per marking opponent,
// Very Sunny -1; rain does NOT modify the PA test) -> fumble if natural 1 OR
// modified result <= 1 (ball bounces from the THROWER, unconditional
// turnover) -> otherwise interception window: ONE standing opposition player
// with a tackle zone under the thrower->target line may attempt an AG test at
// -3 (accurate) / -2 (inaccurate), -1 per marker; success = possession +
// turnover -> otherwise accurate lands on the target (catch unmodified) or
// inaccurate scatters 3 from the target.

static int pass_range_mod(int dx, int dy) {
    int d2 = dx * dx + dy * dy;
    if (d2 <= 12) return 0;        // quick (3.5^2 = 12.25)
    if (d2 <= 42) return -1;       // short (6.5^2 = 42.25)
    if (d2 <= 90) return -2;       // long (9.5^2 = 90.25)
    return -3;                     // long bomb (13.5^2 = 182.25)
}

// Squares strictly between thrower and target that the passing "ruler"
// passes over (supercover line traversal on square centres).
static int ruler_candidates(const bb_match* m, int thrower, int tx, int ty, uint8_t out[16]) {
    const bb_player* p = &m->players[thrower];
    int x0 = p->x, y0 = p->y;
    int n = 0;
    // March in small steps along the segment, collecting distinct squares.
    int steps = 64;
    int last_x = x0, last_y = y0;
    for (int i = 1; i < steps; i++) {
        double t = (double)i / steps;
        int cx = (int)(x0 + (tx - x0) * t + 0.5);
        int cy = (int)(y0 + (ty - y0) * t + 0.5);
        if ((cx == last_x && cy == last_y) || (cx == tx && cy == ty)) continue;
        if (cx == x0 && cy == y0) continue;
        last_x = cx;
        last_y = cy;
        int s = bb_slot_at(m, cx, cy);
        if (s >= 0 && BB_TEAM_OF(s) != BB_TEAM_OF(thrower) && bb_exerts_tz(m, s)) {
            bool dup = false;
            for (int k = 0; k < n; k++) {
                if (out[k] == (uint8_t)s) dup = true;
            }
            if (!dup && n < 16) out[n++] = (uint8_t)s;
        }
    }
    return n;
}

static void pass_start_interception(bb_match* m, bb_frame* f, int interceptor);

static void pass_resolve_flight(bb_match* m, bb_frame fr) {
    bool inaccurate = (fr.data & 0x100) != 0;
    if (inaccurate) {
        bb_ball_to(m, fr.x, fr.y);
        bb_push(m, BB_PROC_SCATTER, 0, 3, fr.x, fr.y);
        bb_top(m)->data |= 1; // pass-flight scatter: catch mod 0
        return;
    }
    int s = bb_slot_at(m, fr.x, fr.y);
    bb_ball_to(m, fr.x, fr.y);
    if (s >= 0) {
        bb_push(m, BB_PROC_CATCH, s, 0, 0, 0);
    } else {
        bb_push(m, BB_PROC_SCATTER, 0, 1, fr.x, fr.y); // bounces on landing
    }
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
        int rmod = pass_range_mod(f->x - p->x, f->y - p->y);
        bb_ctx c = {BB_TEST_PASS, (uint8_t)slot, BB_NO_PLAYER,
                    (int8_t)p->x, (int8_t)p->y, (int8_t)f->x, (int8_t)f->y,
                    (int8_t)(-rmod), 0};
        int mod = rmod;
        mod -= bb_tackle_zones(m, BB_TEAM_OF(slot), p->x, p->y);
        mod += bb_hook_mods(m, &c);
        if (m->weather == BB_WEATHER_SUNNY) mod -= 1; // Very Sunny: -1 to PA tests
        f->data = (uint16_t)(mod & 0xFF);
        f->phase = 1;
        bb_push(m, BB_PROC_TEST, slot, BB_TEST_PASS, bb_test_target(p->pa, mod), 0);
        return;
    }

    if (f->phase == 1) {
        int die = (m->ret >> 8) & 0xF;
        int mod = (int8_t)(f->data & 0xFF);
        bool fumble = die == 1 || die + mod <= 1;
        if (fumble) {
            if (bb_has_skill(&p->skills, BB_SK_SAFE_PASS) && die == 1) {
                // SAFE PASS: a natural 1 is not a Fumble — the player keeps
                // the ball, the activation ends, no turnover.
                bb_pop(m);
                return;
            }
            // Fumble: ball bounces from the thrower; unconditional turnover.
            int x = p->x, y = p->y;
            bb_pop(m);
            bb_drop_ball(m);
            bb_turnover(m);
            bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)x, (uint8_t)y);
            return;
        }
        if (!(m->ret & 1)) f->data |= 0x100; // inaccurate latch
        bb_drop_ball(m);
        // Interception window. Attempting is cost-free, so a single candidate
        // attempts automatically; with several the defending coach chooses.
        uint8_t cands[16];
        int nc = ruler_candidates(m, slot, f->x, f->y, cands);
        if (nc > 1) {
            f->phase = 2;
            bb_need_decision(m, 1 - BB_TEAM_OF(slot));
            return;
        }
        if (nc == 1) {
            pass_start_interception(m, f, cands[0]);
            return;
        }
        bb_frame fr = *f;
        bb_pop(m);
        pass_resolve_flight(m, fr);
        return;
    }

    if (f->phase == 3) {
        // Interception attempt resolved (ret from the AG TEST).
        bb_frame fr = *f;
        int interceptor = fr.b;
        bb_pop(m);
        if (m->ret & 1) {
            bb_give_ball(m, interceptor);
            bb_turnover(m); // successful interception is always a turnover
            bb_check_td(m);
            return;
        }
        pass_resolve_flight(m, fr);
        return;
    }
    m->status = BB_STATUS_ERROR;
}

static int pass_legal(const bb_match* m, bb_action* out) {
    const bb_frame* f = &m->stack[m->stack_top - 1];
    // phase 2: interception window — defending coach picks a candidate or declines.
    uint8_t cands[16];
    int nc = ruler_candidates(m, f->a, f->x, f->y, cands);
    int n = 0;
    for (int i = 0; i < nc; i++) {
        out[n++] = (bb_action){BB_A_CHOOSE_OPTION, cands[i], 0, 0};
    }
    out[n++] = (bb_action){BB_A_CHOOSE_OPTION, 0xFE, 0, 0}; // decline
    return n;
}

static void pass_start_interception(bb_match* m, bb_frame* f, int interceptor) {
    const bb_player* ip = &m->players[interceptor];
    bool inaccurate = (f->data & 0x100) != 0;
    bb_ctx c = {BB_TEST_CATCH, (uint8_t)interceptor, f->a,
                (int8_t)ip->x, (int8_t)ip->y, (int8_t)ip->x, (int8_t)ip->y, -1, 0};
    int mod = (inaccurate ? -2 : -3) - bb_tackle_zones(m, BB_TEAM_OF(interceptor), ip->x, ip->y);
    mod += bb_hook_mods(m, &c);
    if (m->weather == BB_WEATHER_RAIN) mod -= 1; // rain affects interceptions
    f->b = (uint8_t)interceptor;
    f->phase = 3;
    bb_push(m, BB_PROC_TEST, interceptor, BB_TEST_CATCH, bb_test_target(ip->ag, mod), 0);
}

static void pass_apply(bb_match* m, bb_action a, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    if (a.arg == 0xFE) { // decline interception
        bb_frame fr = *f;
        bb_pop(m);
        pass_resolve_flight(m, fr);
        return;
    }
    pass_start_interception(m, f, a.arg);
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
const bb_proc_vtable bb_proc_pass_vtable = {pass_advance, pass_legal, pass_apply};
const bb_proc_vtable bb_proc_handoff_vtable = {handoff_advance, 0, 0};
