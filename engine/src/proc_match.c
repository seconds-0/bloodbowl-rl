// proc_match.c — MATCH driver, PREGAME, SETUP, KICKOFF, END_DRIVE, KO_RECOVERY,
// TOUCHDOWN.
#include "bb/bb_proc.h"
#include "bb/gen_tables.h"

// ===== MATCH =================================================================
// phase 0: push PREGAME
// phase 1: start a drive (SETUP)
// phase 2: after SETUP, push KICKOFF
// phase 3: turn loop — dispatch TEAM_TURNs until TD or half end
// phase 4: half/drive transition
// data bit0: TD-scored latch (set by TOUCHDOWN)  bit1: kicked-first-in-h1 team in bit2

enum { MD_TD = 1 << 0, MD_H1_KICKER_SET = 1 << 1, MD_H1_KICKER = 1 << 2 };

static bool half_over(const bb_match* m) {
    return m->turn[0] >= 8 && m->turn[1] >= 8;
}

static void match_advance(bb_match* m, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    switch (f->phase) {
        case 0:
            f->phase = 1;
            bb_push(m, BB_PROC_PREGAME, 0, 0, 0, 0);
            return;
        case 1:
            if (!(f->data & MD_H1_KICKER_SET)) {
                f->data |= MD_H1_KICKER_SET | (m->kicking_team ? MD_H1_KICKER : 0);
            }
            f->phase = 2;
            bb_push(m, BB_PROC_SETUP, m->kicking_team, 0, 0, 0);
            return;
        case 2:
            f->phase = 3;
            // Receiving team takes the first turn after the kickoff.
            m->active_team = (uint8_t)(1 - m->kicking_team);
            bb_push(m, BB_PROC_KICKOFF, m->kicking_team, 0, 0, 0);
            return;
        case 3: {
            if (f->data & MD_TD) {
                f->data &= (uint16_t)~MD_TD;
                f->phase = 4;
                bb_push(m, BB_PROC_END_DRIVE, 0, 0, 0, 0);
                return;
            }
            if (half_over(m)) {
                f->phase = 4;
                bb_push(m, BB_PROC_END_DRIVE, 0, 0, 0, 0);
                return;
            }
            int next = m->active_team; // set by previous TEAM_TURN/KICKOFF
            if (m->turn[next] >= 8) next = 1 - next;
            if (m->turn[next] >= 8) { // both done
                f->phase = 4;
                bb_push(m, BB_PROC_END_DRIVE, 0, 0, 0, 0);
                return;
            }
            bb_push(m, BB_PROC_TEAM_TURN, next, 0, 0, 0);
            return;
        }
        case 4: {
            if (half_over(m)) {
                if (m->half >= 2) {
                    bb_pop(m); // match over
                    return;
                }
                // Second half: counters reset; H1 receiver kicks.
                m->half = 2;
                m->turn[0] = m->turn[1] = 0;
                int h1_kicker = (f->data & MD_H1_KICKER) ? 1 : 0;
                m->kicking_team = (uint8_t)(1 - h1_kicker);
            } else {
                // Drive ended by TD mid-half: scoring team kicks next drive.
                // kicking_team was set by TOUCHDOWN.
            }
            f->phase = 1;
            return;
        }
    }
    m->status = BB_STATUS_ERROR;
}

// ===== PREGAME ===============================================================
// phase 0: weather roll + coin toss -> decision for the toss winner
// apply: CHOOSE_OPTION 0 = kick, 1 = receive

static void pregame_advance(bb_match* m, bb_rng* rng) {
    bb_frame* f = bb_top(m);
    if (f->phase == 0) {
        int w = bb_2d6(rng);
        m->weather = bb_weather_table[w];
        int toss = bb_roll(rng, 2); // 1 = home wins toss, 2 = away
        f->a = (uint8_t)(toss - 1); // toss winner
        f->phase = 1;
        bb_need_decision(m, f->a);
        return;
    }
    m->status = BB_STATUS_ERROR;
}

static int pregame_legal(const bb_match* m, bb_action* out) {
    (void)m;
    out[0] = (bb_action){BB_A_CHOOSE_OPTION, 0, 0, 0}; // kick
    out[1] = (bb_action){BB_A_CHOOSE_OPTION, 1, 0, 0}; // receive
    return 2;
}

static void pregame_apply(bb_match* m, bb_action a, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    int winner = f->a;
    m->kicking_team = (uint8_t)(a.arg == 0 ? winner : 1 - winner);
    bb_pop(m);
}

// ===== SETUP =================================================================
// a = kicking team. phase 0 = kicking team sets up, 1 = receiving team.
// Constraints (checked for SETUP_DONE): exactly min(11, available) on pitch,
// >= min(3, available) on own line-of-scrimmage column within the centre
// field, <= 2 players per wide zone.

static int setup_team(const bb_match* m) {
    const bb_frame* f = &m->stack[m->stack_top - 1];
    return f->phase == 0 ? f->a : 1 - f->a;
}

static int count_available(const bb_match* m, int team) {
    int n = 0;
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        int loc = m->players[s].location;
        if (loc == BB_LOC_RESERVES || loc == BB_LOC_ON_PITCH) n++;
    }
    return n;
}

static int count_on_pitch(const bb_match* m, int team) {
    int n = 0;
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        if (m->players[s].location == BB_LOC_ON_PITCH) n++;
    }
    return n;
}

static bool setup_constraints_ok(const bb_match* m, int team) {
    int avail = count_available(m, team);
    int on_pitch = count_on_pitch(m, team);
    int want = avail < 11 ? avail : 11;
    if (on_pitch != want) return false;
    int los_x = team == BB_HOME ? 12 : 13;
    int los = 0, wz_top = 0, wz_bot = 0;
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        const bb_player* p = &m->players[s];
        if (p->location != BB_LOC_ON_PITCH) continue;
        if (p->x == los_x && p->y >= 4 && p->y <= 10) los++;
        if (p->y <= 3) wz_top++;
        if (p->y >= 11) wz_bot++;
    }
    int need_los = on_pitch < 3 ? on_pitch : 3;
    if (los < need_los) return false;
    if (wz_top > 2 || wz_bot > 2) return false;
    return true;
}

// Deterministic formation fix-up (no dice; replay-safe). Used when a coach
// confirms setup past the action budget without a legal formation — the
// engine equivalent of FUMBBL's setup clock running out.
static void setup_autofix(bb_match* m, int team) {
    int base = team * BB_TEAM_SLOTS;
    int los_x = team == BB_HOME ? 12 : 13;
    int xmin = team == BB_HOME ? 0 : 13;
    int xmax = team == BB_HOME ? 12 : BB_PITCH_LEN - 1;
    int avail = count_available(m, team);
    int want = avail < 11 ? avail : 11;

    // 1. Remove surplus (highest slots first).
    for (int s = base + BB_TEAM_SLOTS - 1; s >= base && count_on_pitch(m, team) > want; s--) {
        if (m->players[s].location == BB_LOC_ON_PITCH) {
            bb_remove_from_pitch(m, s, BB_LOC_RESERVES);
        }
    }
    // 2. Clear wide-zone surplus into free centre squares.
    for (int wz = 0; wz < 2; wz++) {
        int ylo = wz == 0 ? 0 : 11, yhi = wz == 0 ? 3 : 14;
        int count = 0;
        for (int s = base; s < base + BB_TEAM_SLOTS; s++) {
            bb_player* p = &m->players[s];
            if (p->location != BB_LOC_ON_PITCH || p->y < ylo || p->y > yhi) continue;
            count++;
            if (count <= 2) continue;
            for (int x = xmin; x <= xmax; x++) {
                bool moved = false;
                for (int y = 4; y <= 10; y++) {
                    if (!m->grid[x][y]) {
                        bb_place(m, s, x, y);
                        moved = true;
                        break;
                    }
                }
                if (moved) break;
            }
        }
    }
    // 3. Ensure the line of scrimmage minimum.
    int need = count_on_pitch(m, team) < 3 ? count_on_pitch(m, team) : 3;
    int los = 0;
    for (int s = base; s < base + BB_TEAM_SLOTS; s++) {
        const bb_player* p = &m->players[s];
        if (p->location == BB_LOC_ON_PITCH && p->x == los_x && p->y >= 4 && p->y <= 10) los++;
    }
    for (int s = base; s < base + BB_TEAM_SLOTS && los < need; s++) {
        bb_player* p = &m->players[s];
        if (p->location != BB_LOC_ON_PITCH) continue;
        if (p->x == los_x && p->y >= 4 && p->y <= 10) continue;
        for (int y = 4; y <= 10; y++) {
            if (!m->grid[los_x][y]) {
                bb_place(m, s, los_x, y);
                los++;
                break;
            }
        }
    }
    // 4. Fill up to `want` from reserves (centre squares first).
    for (int s = base; s < base + BB_TEAM_SLOTS && count_on_pitch(m, team) < want; s++) {
        if (m->players[s].location != BB_LOC_RESERVES) continue;
        bool placed = false;
        for (int x = los_x; x >= xmin && x <= xmax && !placed; x += (team == BB_HOME ? -1 : 1)) {
            for (int y = 4; y <= 10; y++) {
                if (!m->grid[x][y]) {
                    bb_place(m, s, x, y);
                    placed = true;
                    break;
                }
            }
        }
    }
}

#define SETUP_ACTION_BUDGET 64

static void setup_advance(bb_match* m, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    if (f->phase <= 1) {
        bb_need_decision(m, setup_team(m));
        return;
    }
    bb_pop(m);
}

static int setup_legal(const bb_match* m, bb_action* out) {
    const bb_frame* f = &m->stack[m->stack_top - 1];
    int team = setup_team(m);
    int n = 0;
    // Setup action budget exhausted: only DONE remains (the engine fixes the
    // formation deterministically if needed) — guarantees termination.
    if (f->data >= SETUP_ACTION_BUDGET) {
        out[n++] = (bb_action){BB_A_SETUP_DONE, 0, 0, 0};
        return n;
    }
    // DONE is emitted first so it can never be truncated by the action cap.
    if (setup_constraints_ok(m, team)) {
        out[n++] = (bb_action){BB_A_SETUP_DONE, 0, 0, 0};
    }
    int xmin = team == BB_HOME ? 0 : 13;
    int xmax = team == BB_HOME ? 12 : BB_PITCH_LEN - 1;
    int on_pitch = count_on_pitch(m, team);
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        const bb_player* p = &m->players[s];
        bool placed = p->location == BB_LOC_ON_PITCH;
        if (p->location != BB_LOC_RESERVES && !placed) continue;
        if (!placed && on_pitch >= 11) continue; // pitch full: may only move placed ones
        for (int x = xmin; x <= xmax; x++) {
            for (int y = 0; y < BB_PITCH_WID; y++) {
                if (m->grid[x][y] && bb_slot_at(m, x, y) != s) continue;
                if (placed && p->x == x && p->y == y) continue;
                if (n < BB_LEGAL_MAX) out[n++] = (bb_action){BB_A_SETUP_PLACE, (uint8_t)s, (uint8_t)x, (uint8_t)y};
            }
        }
        if (placed && n < BB_LEGAL_MAX) {
            out[n++] = (bb_action){BB_A_SETUP_REMOVE, (uint8_t)s, 0, 0};
        }
    }
    return n;
}

static void setup_apply(bb_match* m, bb_action a, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    if (a.type == BB_A_SETUP_PLACE) {
        f->data++;
        bb_place(m, a.arg, a.x, a.y);
        return; // stay in this phase; advance() re-issues the decision
    }
    if (a.type == BB_A_SETUP_REMOVE) {
        f->data++;
        bb_remove_from_pitch(m, a.arg, BB_LOC_RESERVES);
        return;
    }
    // SETUP_DONE
    int team = setup_team(m);
    if (!setup_constraints_ok(m, team)) {
        setup_autofix(m, team);
    }
    f->data = 0; // reset the budget for the second team's setup
    f->phase++;
}

// ===== KICKOFF ===============================================================
// a = kicking team.
// phase 0: decision — nominate kick target square (receiving half)
// phase 1: deviate ball (D8 dir, D6 distance), kickoff event (2D6), land ball
// phase 2: waiting for touchback decision (if any)
// Kickoff events: simple ones are applied inline; the involved ones are
// TODO(phase3) and currently no-ops — each is marked.

static const int8_t DIR8[8][2] = {
    {-1, -1}, {0, -1}, {1, -1}, {-1, 0}, {1, 0}, {-1, 1}, {0, 1}, {1, 1},
};

static void kickoff_land_ball(bb_match* m, int kicking) {
    int x = m->ball.x, y = m->ball.y;
    bool out_of_bounds = !bb_on_pitch_xy(x, y);
    bool wrong_half = !out_of_bounds && bb_own_half_x(kicking, x);
    if (out_of_bounds || wrong_half) {
        // Touchback: receiving coach gives the ball to any player.
        bb_top(m)->phase = 2;
        bb_need_decision(m, 1 - kicking);
        return;
    }
    int s = bb_slot_at(m, x, y);
    if (s >= 0 && BB_TEAM_OF(s) == 1 - kicking && m->players[s].stance == BB_STANCE_STANDING) {
        // Catch attempt: kick landing on a standing receiver.
        bb_pop(m);
        bb_push(m, BB_PROC_CATCH, s, 0, 0, 0);
        return;
    }
    // Bounce once.
    bb_pop(m);
    bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)x, (uint8_t)y);
}

static void kickoff_event(bb_match* m, bb_rng* rng) {
    int roll = bb_2d6(rng);
    int ev = bb_kickoff_table[roll];
    switch (ev) {
        case BB_KO_TIME_OUT: {
            // Kicking team's turn marker on 6-8: both move back one; else forward.
            int kt = bb_top(m)->a;
            if (m->turn[kt] >= 6) {
                if (m->turn[0]) m->turn[0]--;
                if (m->turn[1]) m->turn[1]--;
            } else {
                m->turn[0]++;
                m->turn[1]++;
            }
            break;
        }
        case BB_KO_BRILLIANT_COACHING: {
            // D6 per side (+assistant coaches TODO(phase3)); winner +1 reroll.
            int h = bb_d6(rng), a = bb_d6(rng);
            if (h > a) m->rerolls[BB_HOME]++;
            else if (a > h) m->rerolls[BB_AWAY]++;
            break;
        }
        case BB_KO_PITCH_INVASION: {
            // D3 random players from each team are stunned.
            for (int team = 0; team < 2; team++) {
                int hits = bb_d3(rng);
                for (int i = 0; i < hits; i++) {
                    // Pick a random on-pitch player (by rolling a slot).
                    int tries = 16;
                    while (tries--) {
                        int s = team * BB_TEAM_SLOTS + (int)(bb_rng_next(rng) % BB_TEAM_SLOTS);
                        bb_player* p = &m->players[s];
                        if (p->location == BB_LOC_ON_PITCH && p->stance == BB_STANCE_STANDING) {
                            p->stance = BB_STANCE_STUNNED;
                            break;
                        }
                    }
                }
            }
            break;
        }
        case BB_KO_CHANGING_WEATHER: {
            int w = bb_2d6(rng);
            m->weather = bb_weather_table[w];
            break;
        }
        // TODO(phase3): GET_THE_REF (bribes), CHEERING_FANS (prayers),
        // SOLID_DEFENCE / QUICK_SNAP / CHARGE / HIGH_KICK (re-setup decisions),
        // DODGY_SNACK. Rule-shaped no-ops for now; differential validation
        // will flag them.
        default:
            break;
    }
}

static void kickoff_advance(bb_match* m, bb_rng* rng) {
    bb_frame* f = bb_top(m);
    if (f->phase == 0) {
        bb_need_decision(m, f->a);
        return;
    }
    if (f->phase == 1) {
        // Deviate: D8 direction, D6 squares.
        int dir = bb_roll(rng, 8) - 1;
        int dist = bb_d6(rng);
        int x = f->x + DIR8[dir][0] * dist;
        int y = f->y + DIR8[dir][1] * dist;
        m->ball.state = BB_BALL_IN_AIR;
        m->ball.x = (uint8_t)x; // may be off pitch; land logic handles it
        m->ball.y = (uint8_t)y;
        kickoff_event(m, rng);
        kickoff_land_ball(m, f->a);
        return;
    }
    m->status = BB_STATUS_ERROR;
}

static int kickoff_legal(const bb_match* m, bb_action* out) {
    const bb_frame* f = &m->stack[m->stack_top - 1];
    int n = 0;
    if (f->phase == 0) {
        int kicking = f->a;
        int xmin = kicking == BB_HOME ? 13 : 0;
        int xmax = kicking == BB_HOME ? BB_PITCH_LEN - 1 : 12;
        for (int x = xmin; x <= xmax; x++) {
            for (int y = 0; y < BB_PITCH_WID; y++) {
                if (n < BB_LEGAL_MAX) out[n++] = (bb_action){BB_A_KICK_TARGET, 0, (uint8_t)x, (uint8_t)y};
            }
        }
        return n;
    }
    // phase 2: touchback — any standing player of the receiving team.
    int receiving = 1 - f->a;
    for (int s = receiving * BB_TEAM_SLOTS; s < (receiving + 1) * BB_TEAM_SLOTS; s++) {
        const bb_player* p = &m->players[s];
        if (p->location == BB_LOC_ON_PITCH && p->stance == BB_STANCE_STANDING) {
            out[n++] = (bb_action){BB_A_TOUCHBACK, (uint8_t)s, 0, 0};
        }
    }
    return n;
}

static void kickoff_apply(bb_match* m, bb_action a, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    if (a.type == BB_A_KICK_TARGET) {
        f->x = a.x;
        f->y = a.y;
        f->phase = 1;
        return;
    }
    // Touchback
    bb_give_ball(m, a.arg);
    bb_pop(m);
}

// ===== TOUCHDOWN =============================================================
// a = scoring player. Records the score, sets the MATCH TD latch, ends the
// active team turn.

static void touchdown_advance(bb_match* m, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    int slot = f->a;
    int team = BB_TEAM_OF(slot);
    m->score[team]++;
    m->kicking_team = (uint8_t)team; // scorer kicks the next drive
    bb_drop_ball(m);
    m->ball.state = BB_BALL_OFF_PITCH;
    // Find the MATCH frame and set its TD latch; unwind everything above it.
    for (int i = 0; i < m->stack_top; i++) {
        if (m->stack[i].proc == BB_PROC_MATCH) {
            m->stack[i].data |= MD_TD;
            m->stack_top = (uint8_t)(i + 1);
            m->turnover = 0;
            return;
        }
    }
    m->status = BB_STATUS_ERROR;
}

// ===== END_DRIVE / KO_RECOVERY ==============================================
// Clear the pitch, recover KO'd players (D6 4+), reset ball.

static void end_drive_advance(bb_match* m, bb_rng* rng) {
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        bb_player* p = &m->players[s];
        if (p->location == BB_LOC_ON_PITCH) {
            bb_remove_from_pitch(m, s, BB_LOC_RESERVES);
        }
        if (p->location == BB_LOC_KO) {
            if (bb_d6(rng) >= 4) p->location = BB_LOC_RESERVES;
        }
        p->flags = 0;
        p->stance = BB_STANCE_STANDING;
    }
    m->ball.state = BB_BALL_OFF_PITCH;
    m->ball.carrier = BB_NO_PLAYER;
    m->turnover = 0;
    bb_pop(m);
}

// ===== vtable exports ========================================================
const bb_proc_vtable bb_proc_match_vtable = {match_advance, 0, 0};
const bb_proc_vtable bb_proc_pregame_vtable = {pregame_advance, pregame_legal, pregame_apply};
const bb_proc_vtable bb_proc_setup_vtable = {setup_advance, setup_legal, setup_apply};
const bb_proc_vtable bb_proc_kickoff_vtable = {kickoff_advance, kickoff_legal, kickoff_apply};
const bb_proc_vtable bb_proc_touchdown_vtable = {touchdown_advance, 0, 0};
const bb_proc_vtable bb_proc_end_drive_vtable = {end_drive_advance, 0, 0};
