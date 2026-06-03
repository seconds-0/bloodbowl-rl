// bb_fixtures.h — helpers for constructing mid-game positions in rules tests.
//
// Pattern: build a minimal match state directly, push the procedure under
// test, drive it with a scripted dice sequence (bb_rng_script), and assert
// the resulting state. Scripted dice are the core trick: every die face is
// chosen by the test, so each rules branch is reachable deterministically.
#ifndef BB_FIXTURES_H
#define BB_FIXTURES_H

#include "bb/bb_match.h"
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb/gen_teams.h"
#include <string.h>

// A match mid-team-turn with an empty pitch: MATCH(phase 3) + TEAM_TURN
// (phase 0 — turn-start bookkeeping runs on the first advance, marking
// pre-placed stunned players and clearing per-turn flags); both teams have
// `rerolls` team re-rolls; weather perfect; half 1, turn 1 for both after the
// first advance.
static inline void fx_match_midturn(bb_match* m, int active_team, int rerolls) {
    memset(m, 0, sizeof(*m));
    m->team_id[0] = BB_TEAM_HUMAN;
    m->team_id[1] = BB_TEAM_ORC;
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        m->players[s].location = BB_LOC_ABSENT;
    }
    m->half = 1;
    m->turn[0] = m->turn[1] = 1;
    m->turn[active_team] = 0; // turn_start increments it to 1
    m->weather = BB_WEATHER_PERFECT;
    m->rerolls[0] = m->rerolls[1] = (uint8_t)rerolls;
    m->rerolls_start[0] = m->rerolls_start[1] = (uint8_t)rerolls;
    m->active_team = (uint8_t)active_team;
    m->ball.state = BB_BALL_OFF_PITCH;
    m->ball.carrier = BB_NO_PLAYER;
    m->status = BB_STATUS_RUNNING;
    bb_push(m, BB_PROC_MATCH, 0, 0, 0, 0);
    bb_top(m)->phase = 3; // turn-dispatch loop
    bb_push(m, BB_PROC_TEAM_TURN, active_team, 0, 0, 0);
    // phase 0: turn_start runs on the first fx_run/advance
}

// Place a player: slot = team*16+i. Stats given as (ma, st, ag, pa, av) with
// target numbers (ag 3 == 3+). Returns the slot.
static inline int fx_player(bb_match* m, int team, int idx, int x, int y,
                            int ma, int st, int ag, int pa, int av) {
    int slot = team * BB_TEAM_SLOTS + idx;
    bb_player* p = &m->players[slot];
    memset(p, 0, sizeof(*p));
    p->ma = (int8_t)ma;
    p->st = (int8_t)st;
    p->ag = (int8_t)ag;
    p->pa = (int8_t)pa;
    p->av = (int8_t)av;
    p->stance = BB_STANCE_STANDING;
    bb_place(m, slot, x, y);
    return slot;
}

// A standard "lineman" statline (6338+ / 9+ AV).
static inline int fx_lineman(bb_match* m, int team, int idx, int x, int y) {
    return fx_player(m, team, idx, x, y, 6, 3, 3, 4, 9);
}

static inline void fx_give_skill(bb_match* m, int slot, int skill_id) {
    bb_add_skill(&m->players[slot].skills, skill_id);
}

static inline void fx_ball_held(bb_match* m, int slot) {
    bb_give_ball(m, slot);
}

static inline void fx_ball_ground(bb_match* m, int x, int y) {
    bb_ball_to(m, x, y);
}

// Drive the engine until it needs a decision (or ends), with scripted dice.
// Returns the status.
static inline bb_status fx_run(bb_match* m, bb_rng* rng) {
    return bb_advance(m, rng);
}

// Find a specific legal action; returns index or -1.
static inline int fx_find(const bb_match* m, bb_action want) {
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(m, legal);
    for (int i = 0; i < n; i++) {
        if (bb_action_eq(legal[i], want)) return i;
    }
    return -1;
}

// Apply an action (asserting it is legal) with scripted dice; returns status.
static inline bb_status fx_apply(bb_match* m, bb_action a, bb_rng* rng) {
    return bb_apply(m, a, rng);
}

// Is the player in the stunned family (STUNNED, or STUNNED_USED — i.e.
// stunned and already marked to roll over at the end of their team's current
// turn)? Tests asserting "still stunned, not yet prone" should use this.
static inline bool fx_stunned(const bb_match* m, int slot) {
    return m->players[slot].stance == BB_STANCE_STUNNED ||
           m->players[slot].stance == BB_STANCE_STUNNED_USED;
}

// Does the legal set contain an action of this type?
static inline bool fx_has_type(const bb_match* m, int type) {
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(m, legal);
    for (int i = 0; i < n; i++) {
        if (legal[i].type == type) return true;
    }
    return false;
}

// Setup-aware random action picker (random play cannot stumble into a legal
// formation; see test_match.c). Used by smoke tests, golden generation and
// benchmarks.
static inline int fx_pick_smart(const bb_match* m, bb_action* legal, int n, bb_rng* pick) {
    for (int i = 0; i < n; i++) {
        if (legal[i].type == BB_A_SETUP_DONE) return i;
    }
    if (n > 0 && (legal[0].type == BB_A_SETUP_PLACE || legal[0].type == BB_A_SETUP_REMOVE)) {
        int best = -1;
        for (int i = 0; i < n; i++) {
            if (legal[i].type != BB_A_SETUP_PLACE) continue;
            if (m->players[legal[i].arg].location != BB_LOC_RESERVES) continue;
            bool los = (legal[i].x == 12 || legal[i].x == 13) && legal[i].y >= 4 && legal[i].y <= 10;
            bool centre = legal[i].y >= 4 && legal[i].y <= 10;
            if (los) return i;
            if (centre && best < 0) best = i;
        }
        if (best >= 0) return best;
    }
    return (int)(bb_rng_next(pick) % (uint32_t)n);
}

#endif // BB_FIXTURES_H
