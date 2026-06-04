// proc_match.c — MATCH driver, PREGAME, SETUP, KICKOFF, END_DRIVE, KO_RECOVERY,
// TOUCHDOWN.
#include "bb/bb_proc.h"
#include "bb/bb_hooks.h"
#include "bb/gen_tables.h"
#include <string.h>

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
                // Second half: counters reset; re-rolls replenish; H1
                // receiver kicks.
                m->half = 2;
                m->turn[0] = m->turn[1] = 0;
                m->rerolls[0] = m->rerolls_start[0];
                m->rerolls[1] = m->rerolls_start[1];
                // LEADER: the per-half bonus re-roll (if a Leader survives).
                for (int t = 0; t < 2; t++) {
                    for (int s2 = t * BB_TEAM_SLOTS; s2 < (t + 1) * BB_TEAM_SLOTS; s2++) {
                        const bb_player* lp = &m->players[s2];
                        if ((lp->location == BB_LOC_RESERVES || lp->location == BB_LOC_ON_PITCH ||
                             lp->location == BB_LOC_KO) &&
                            bb_has_skill(&lp->skills, BB_SK_LEADER)) {
                            m->rerolls[t]++;
                            break;
                        }
                    }
                }
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
        // LEADER: a team with a Leader gains one extra team re-roll per half.
        for (int t = 0; t < 2; t++) {
            for (int s2 = t * BB_TEAM_SLOTS; s2 < (t + 1) * BB_TEAM_SLOTS; s2++) {
                if (m->players[s2].location != BB_LOC_ABSENT &&
                    bb_has_skill(&m->players[s2].skills, BB_SK_LEADER)) {
                    m->rerolls[t]++;
                    break;
                }
            }
        }
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

#define SETUP_ACTION_BUDGET 24

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
    // Placement discipline: until the line is filled (11 placed, or reserves
    // exhausted for short-handed squads), ONLY fresh placements from the
    // Reserves box are legal. Re-placing/removing an already-placed player
    // before that point let undertrained policies shuffle one player back
    // and forth for the whole budget (spectator finding). Rules-equivalent:
    // every final formation is still reachable — place 11, then rearrange.
    bool reserves_left = false;
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        if (m->players[s].location == BB_LOC_RESERVES) {
            reserves_left = true;
            break;
        }
    }
    bool placing_phase = on_pitch < 11 && reserves_left;
    // Every candidate has the SAME legal square set: exactly the free squares
    // of the team's half. (A placed player's own square is occupied by
    // himself, so it is excluded either way — the old per-player grid walk
    // allowed the self-occupied square at the grid check only to skip it at
    // the own-square check.) Enumerate the half ONCE into a template, then
    // stamp it per candidate — the 16x195 per-player grid rescan was the
    // hottest single loop in the env profile (~39% of random-play decisions
    // are setup, ~1354 actions per enumeration).
    bb_action tmpl[13 * BB_PITCH_WID];
    int nf = 0;
    for (int x = xmin; x <= xmax; x++) {
        for (int y = 0; y < BB_PITCH_WID; y++) {
            if (!m->grid[x][y]) {
                tmpl[nf++] = (bb_action){BB_A_SETUP_PLACE, 0, (uint8_t)x, (uint8_t)y};
            }
        }
    }
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        const bb_player* p = &m->players[s];
        bool placed = p->location == BB_LOC_ON_PITCH;
        if (p->location != BB_LOC_RESERVES && !placed) continue;
        if (!placed && on_pitch >= 11) continue; // pitch full: may only move placed ones
        if (placed && placing_phase) continue;   // fill the line first
        int take = nf;
        if (take > BB_LEGAL_MAX - n) take = BB_LEGAL_MAX - n;
        if (take > 0) {
            memcpy(out + n, tmpl, (size_t)take * sizeof(bb_action));
            for (int i = 0; i < take; i++) out[n + i].arg = (uint8_t)s;
            n += take;
        }
        if (placed && !placing_phase && n < BB_LEGAL_MAX) {
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
// phase 0: decision — nominate the kick target square (receiving half)
// phase 1: deviate the ball (D8 dir, D6 distance) + kickoff event
// phase 4: High Kick decision (receiving coach) before the ball lands
// phase 3: settling — a landing catch/bounce chain is resolving below; when
//          it finishes, check the touchback condition (ball out of play or in
//          the kicking half, by ANY means, is a touchback)
// phase 2: touchback decision (give to a standing player; if none, place the
//          ball on any unoccupied square of the receiving half)
// Events GET_THE_REF / CHEERING_FANS / SOLID_DEFENCE / QUICK_SNAP / CHARGE /
// DODGY_SNACK remain TODO(phase3) no-ops.

static const int8_t DIR8[8][2] = {
    {-1, -1}, {0, -1}, {1, -1}, {-1, 0}, {1, 0}, {-1, 1}, {0, 1}, {1, 1},
};

// Is a KICKOFF frame somewhere on the stack (ball still in kickoff
// resolution)? Used by SCATTER to suppress throw-ins (kickoff balls that
// leave the pitch are touchbacks, not throw-ins).
bool bb_in_kickoff(const bb_match* m) {
    for (int i = 0; i < m->stack_top; i++) {
        if (m->stack[i].proc == BB_PROC_KICKOFF) return true;
    }
    return false;
}

static void stun_random_players(bb_match* m, bb_rng* rng, int team, int count) {
    for (int i = 0; i < count; i++) {
        int candidates[BB_TEAM_SLOTS];
        int nc = 0;
        for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
            if (m->players[s].location == BB_LOC_ON_PITCH &&
                m->players[s].stance == BB_STANCE_STANDING) {
                candidates[nc++] = s;
            }
        }
        if (!nc) return;
        // Selection consumes the scripted dice stream (replay-faithful): an
        // N-sided roll over the candidate list, sorted by slot.
        int pick = bb_roll(rng, nc) - 1;
        m->players[candidates[pick]].stance = BB_STANCE_STUNNED;
    }
}

static bool kickoff_ball_misplaced(const bb_match* m, int kicking);

// Returns true if the event paused the kickoff with a decision (High Kick).
static bool kickoff_event(bb_match* m, bb_rng* rng) {
    bb_frame* f = bb_top(m);
    int roll = bb_2d6(rng);
    int ev = bb_kickoff_table[roll];
    switch (ev) {
        case BB_KO_TIME_OUT: {
            int kt = f->a;
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
            // D6 per side (+assistant coaches TODO(phase3)); winner +1 reroll
            // for this drive (tracked in bonus_rerolls; expires at END_DRIVE).
            int h = bb_d6(rng), a = bb_d6(rng);
            if (h > a) {
                m->rerolls[BB_HOME]++;
                m->bonus_rerolls[BB_HOME]++;
            } else if (a > h) {
                m->rerolls[BB_AWAY]++;
                m->bonus_rerolls[BB_AWAY]++;
            }
            break;
        }
        case BB_KO_PITCH_INVASION: {
            // "Both Coaches roll a D6 and add their Fan Factor. The Coach
            // that rolled lowest, or both Coaches in the result of a tie,
            // randomly selects D3 of their players" -> Stunned.
            int h = bb_d6(rng) + m->fan_factor[BB_HOME];
            int a = bb_d6(rng) + m->fan_factor[BB_AWAY];
            if (h <= a) stun_random_players(m, rng, BB_HOME, bb_d3(rng));
            if (a <= h && a != h) stun_random_players(m, rng, BB_AWAY, bb_d3(rng));
            else if (a == h) stun_random_players(m, rng, BB_AWAY, bb_d3(rng));
            break;
        }
        case BB_KO_CHANGING_WEATHER: {
            int w = bb_2d6(rng);
            m->weather = bb_weather_table[w];
            if (m->weather == BB_WEATHER_PERFECT &&
                !kickoff_ball_misplaced(m, f->a)) {
                // Perfect Conditions: the ball Scatters (3) in the air —
                // one D8 at a time, STOPPING the moment it leaves the
                // receiving half / pitch (the touchback is then certain and
                // FFB rolls no further dice; a kick already misplaced gusts
                // not at all). The ball stays on the out square so the
                // landing check routes to the touchback decision.
                for (int i = 0; i < 3; i++) {
                    int dir = bb_roll(rng, 8) - 1;
                    m->ball.x = (uint8_t)(m->ball.x + DIR8[dir][0]);
                    m->ball.y = (uint8_t)(m->ball.y + DIR8[dir][1]);
                    if (kickoff_ball_misplaced(m, f->a)) break;
                }
            }
            break;
        }
        case BB_KO_HIGH_KICK: {
            // One Open receiving player may be placed under the ball.
            f->phase = 4;
            bb_need_decision(m, 1 - f->a);
            return true;
        }
        case BB_KO_GET_THE_REF:
            // "Each team immediately receives one free Bribe Inducement."
            m->bribes[0]++;
            m->bribes[1]++;
            break;
        case BB_KO_CHEERING_FANS: {
            // BB2025: D6 + cheerleaders each; the winner's FIRST Block next
            // turn gets an extra offensive assist (both on a tie). Cheerleader
            // counts are 0 until inducements exist; flag the buff per team.
            int h = bb_d6(rng), a = bb_d6(rng);
            if (h >= a) m->cheer_assist[BB_HOME] = 1;
            if (a >= h) m->cheer_assist[BB_AWAY] = 1;
            break;
        }
        case BB_KO_DODGY_SNACK: {
            // Lowest D6 (both on tie): a random on-pitch player rolls D6:
            // 2+ -> -1 MA and -1 AV for the drive; 1 -> Reserves.
            int h = bb_d6(rng), a = bb_d6(rng);
            for (int team = 0; team < 2; team++) {
                if ((team == 0 && h > a) || (team == 1 && a > h)) continue;
                int candidates[BB_TEAM_SLOTS];
                int nc = 0;
                for (int s2 = team * BB_TEAM_SLOTS; s2 < (team + 1) * BB_TEAM_SLOTS; s2++) {
                    if (m->players[s2].location == BB_LOC_ON_PITCH) candidates[nc++] = s2;
                }
                if (!nc) continue;
                int victim = candidates[bb_roll(rng, nc) - 1];
                if (bb_d6(rng) >= 2) {
                    bb_player* v = &m->players[victim];
                    if (v->ma > 1) v->ma--;
                    if (v->av > 3) v->av--; // restored at END_DRIVE via squad reset?
                    // NOTE: stat restoration at drive end is handled by the
                    // procedural-squad reinit in Phase 5; for now the debuff
                    // persists for the match (flagged in DECISIONS.md).
                } else {
                    bb_remove_from_pitch(m, victim, BB_LOC_RESERVES);
                }
            }
            break;
        }
        case BB_KO_SOLID_DEFENCE: {
            // Kicking coach repositions up to D3+3 Open players. Auto-policy:
            // no repositioning (formation kept). The D3 is still rolled for
            // replay-stream fidelity. TODO: decision window.
            (void)bb_d3(rng);
            break;
        }
        case BB_KO_QUICK_SNAP: {
            // Receiving coach: up to D3+3 Open players move one square.
            // Auto-policy: no moves; D3 rolled for stream fidelity.
            (void)bb_d3(rng);
            break;
        }
        case BB_KO_CHARGE: {
            // Kicking coach: D3+3 Open players take free Move actions (one
            // may Blitz/TTM/KTM). Auto-policy: no moves; D3 rolled.
            (void)bb_d3(rng);
            break;
        }
        default:
            break;
    }
    return false;
}

static bool kickoff_ball_misplaced(const bb_match* m, int kicking) {
    if (m->ball.state == BB_BALL_OFF_PITCH) return true;
    if (!bb_on_pitch_xy(m->ball.x, m->ball.y)) return true;
    return bb_own_half_x(kicking, m->ball.x);
}

static void kickoff_land(bb_match* m) {
    bb_frame* f = bb_top(m);
    int kicking = f->a;
    f->phase = 3; // settling: re-checked when the children finish
    if (kickoff_ball_misplaced(m, kicking)) {
        return; // phase 3 will route to the touchback decision
    }
    int x = m->ball.x, y = m->ball.y;
    int s = bb_slot_at(m, x, y);
    if (s >= 0 && BB_TEAM_OF(s) == 1 - kicking && bb_can_catch(m, s)) {
        bb_push(m, BB_PROC_CATCH, s, 0, 0, 0);
        return;
    }
    // The kicked ball bounces on landing.
    bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)x, (uint8_t)y);
}

static void kickoff_advance(bb_match* m, bb_rng* rng) {
    bb_frame* f = bb_top(m);
    if (f->phase == 0) {
        bb_need_decision(m, f->a);
        return;
    }
    if (f->phase == 1) {
        // Deviate: D8 direction, D6 squares. KICK: "you may choose to halve
        // the result of the D6 to determine the number of squares that the
        // ball Deviates, rounding any fractions down" (auto-applied when a
        // kicking-team player with Kick is on the pitch; kicker nomination is
        // TODO with the fans/nomination work).
        int dir = bb_roll(rng, 8) - 1;
        int dist = bb_d6(rng);
        for (int s2 = f->a * BB_TEAM_SLOTS; s2 < (f->a + 1) * BB_TEAM_SLOTS; s2++) {
            if (m->players[s2].location == BB_LOC_ON_PITCH &&
                bb_has_skill(&m->players[s2].skills, BB_SK_KICK)) {
                dist /= 2;
                break;
            }
        }
        m->ball.state = BB_BALL_IN_AIR;
        m->ball.x = (uint8_t)(f->x + DIR8[dir][0] * dist);
        m->ball.y = (uint8_t)(f->y + DIR8[dir][1] * dist);
        if (kickoff_event(m, rng)) return; // paused for a High Kick decision
        kickoff_land(m);
        return;
    }
    if (f->phase == 3) {
        // Landing chain settled.
        int kicking = f->a;
        bool held_ok = m->ball.state == BB_BALL_HELD &&
                       !bb_own_half_x(kicking, m->players[m->ball.carrier].x);
        if (!held_ok && kickoff_ball_misplaced(m, kicking)) {
            bb_drop_ball(m);
            m->ball.state = BB_BALL_OFF_PITCH;
            f->phase = 2;
            bb_need_decision(m, 1 - kicking);
            return;
        }
        bb_pop(m);
        return;
    }
    m->status = BB_STATUS_ERROR;
}


// High Kick: enumerate Open (standing, unmarked) receiving players eligible
// to be placed under the ball. Pure; shared by kickoff legal/apply (M15).
static int high_kick_candidates(const bb_match* m, int kicking, uint8_t* out) {
    int receiving = 1 - kicking;
    if (!bb_on_pitch_xy(m->ball.x, m->ball.y) || m->grid[m->ball.x][m->ball.y] ||
        bb_own_half_x(kicking, m->ball.x)) {
        return 0;
    }
    int nc = 0;
    for (int s = receiving * BB_TEAM_SLOTS; s < (receiving + 1) * BB_TEAM_SLOTS; s++) {
        const bb_player* p = &m->players[s];
        if (p->location != BB_LOC_ON_PITCH) continue;
        if (p->stance != BB_STANCE_STANDING) continue;
        if (bb_is_marked(m, s)) continue;
        out[nc++] = (uint8_t)s;
    }
    return nc;
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
    if (f->phase == 4) {
        // High Kick: any Open (standing, unmarked) receiving player may be
        // placed in the (on-pitch, unoccupied, receiving-half) landing square.
        // CHOOSE_OPTION carries the candidate INDEX (review M15); resolved in
        // kickoff_apply via the same (pure) enumeration.
        uint8_t cands[BB_TEAM_SLOTS];
        int nc = high_kick_candidates(m, f->a, cands);
        for (int i = 0; i < nc; i++) {
            out[n++] = (bb_action){BB_A_CHOOSE_OPTION, (uint8_t)i, 0, 0};
        }
        out[n++] = (bb_action){BB_A_CHOOSE_OPTION, 0xFE, 0, 0}; // decline
        return n;
    }
    // phase 2: touchback.
    int receiving = 1 - f->a;
    for (int s = receiving * BB_TEAM_SLOTS; s < (receiving + 1) * BB_TEAM_SLOTS; s++) {
        const bb_player* p = &m->players[s];
        if (p->location == BB_LOC_ON_PITCH && p->stance == BB_STANCE_STANDING) {
            out[n++] = (bb_action){BB_A_TOUCHBACK, (uint8_t)s, 0, 0};
        }
    }
    if (n == 0) {
        // No standing players: place the ball on any unoccupied square of the
        // receiving half instead.
        int xmin = receiving == BB_HOME ? 0 : 13;
        int xmax = receiving == BB_HOME ? 12 : BB_PITCH_LEN - 1;
        for (int x = xmin; x <= xmax; x++) {
            for (int y = 0; y < BB_PITCH_WID; y++) {
                if (!m->grid[x][y] && n < BB_LEGAL_MAX) {
                    out[n++] = (bb_action){BB_A_TOUCHBACK, 0xFF, (uint8_t)x, (uint8_t)y};
                }
            }
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
    if (f->phase == 4) { // High Kick placement (a.arg = candidate index)
        if (a.arg != 0xFE) {
            uint8_t cands[BB_TEAM_SLOTS];
            int nc = high_kick_candidates(m, f->a, cands);
            if (a.arg >= nc) { // engine-bug canary
                m->status = BB_STATUS_ERROR;
                return;
            }
            bb_place(m, cands[a.arg], m->ball.x, m->ball.y);
        }
        kickoff_land(m);
        return;
    }
    // Touchback.
    if (a.arg == 0xFF) {
        bb_ball_to(m, a.x, a.y);
    } else {
        bb_give_ball(m, a.arg);
    }
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
    // Scoring during the OPPONENT's turn: the scorer skips their next turn
    // entirely (advance their marker for the skipped turn).
    if (team != m->active_team && m->turn[team] < 8) m->turn[team]++;
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
            // SECRET WEAPON: "At the end of a Drive in which this player took
            // part ... they are Sent-off." (On-pitch at drive end = took part;
            // earlier-removed participants are handled when removed.)
            if (bb_has_skill(&p->skills, BB_SK_SECRET_WEAPON)) {
                bb_remove_from_pitch(m, s, BB_LOC_SENT_OFF);
                continue;
            }
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
    m->cheer_assist[0] = m->cheer_assist[1] = 0; // unspent Cheering Fans buff dies with the drive (review LOW)
    // Drive-scoped bonus re-rolls (Brilliant Coaching) expire with the drive.
    // Only the unspent bonuses are removed — the old clamp to rerolls_start
    // also deleted the Leader re-roll (HALF scope, granted by PREGAME without
    // touching rerolls_start) on any mid-half TD (review M2).
    for (int t = 0; t < 2; t++) {
        uint8_t expire = m->bonus_rerolls[t] < m->rerolls[t] ? m->bonus_rerolls[t]
                                                             : m->rerolls[t];
        m->rerolls[t] = (uint8_t)(m->rerolls[t] - expire);
        m->bonus_rerolls[t] = 0;
    }
    bb_pop(m);
}

// ===== vtable exports ========================================================
const bb_proc_vtable bb_proc_match_vtable = {match_advance, 0, 0};
const bb_proc_vtable bb_proc_pregame_vtable = {pregame_advance, pregame_legal, pregame_apply};
const bb_proc_vtable bb_proc_setup_vtable = {setup_advance, setup_legal, setup_apply};
const bb_proc_vtable bb_proc_kickoff_vtable = {kickoff_advance, kickoff_legal, kickoff_apply};
const bb_proc_vtable bb_proc_touchdown_vtable = {touchdown_advance, 0, 0};
const bb_proc_vtable bb_proc_end_drive_vtable = {end_drive_advance, 0, 0};

// ===== KO-PATCH window (BB_PROC_KO_RECOVERY) =================================
// a = player, b = injury context (1 = crowd). Apothecary decision: patch the
// KO (player stays Stunned in square / Reserves if crowd) or send to KO box.

static void ko_patch_advance(bb_match* m, bb_rng* rng) {
    (void)rng;
    bb_need_decision(m, BB_TEAM_OF(bb_top(m)->a));
}

static int ko_patch_legal(const bb_match* m, bb_action* out) {
    (void)m;
    out[0] = (bb_action){BB_A_APOTHECARY, 1, 0, 0};
    out[1] = (bb_action){BB_A_APOTHECARY, 0, 0, 0};
    return 2;
}

static void ko_patch_apply(bb_match* m, bb_action a, bb_rng* rng) {
    (void)rng;
    bb_frame f = *bb_top(m);
    bb_pop(m);
    int slot = f.a;
    bb_player* p = &m->players[slot];
    int team = BB_TEAM_OF(slot);
    if (a.arg == 1) {
        m->apothecary[team]--;
        if (f.b == 1) { // crowd KO patched: Reserves
            p->location = BB_LOC_RESERVES;
        } else {
            p->stance = BB_STANCE_STUNNED; // stays on the pitch, Stunned
        }
        return;
    }
    if (p->location == BB_LOC_ON_PITCH) bb_remove_from_pitch(m, slot, BB_LOC_KO);
    else p->location = BB_LOC_KO;
}

const bb_proc_vtable bb_proc_ko_recovery_vtable = {ko_patch_advance, ko_patch_legal, ko_patch_apply};
