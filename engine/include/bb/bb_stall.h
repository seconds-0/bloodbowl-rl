// bb_stall.h — BB2025 Stalling telemetry: a caller-owned side tally.
//
// The Stalling rule itself lives in proc_turn.c (D193). It is invisible from
// outside the engine: the crowd D6 is consumed inside one bb_apply and the
// per-activation candidate bit is cleared as it is consumed, so nothing
// persists that a consumer could count. This header adds the counter.
//
// WHY A SIDE STRUCT AND NOT A bb_match FIELD. bb_match is serialized WHOLESALE
// into the BBS demo-state bank: the loader reads `sizeof(bb_match)` per record
// and the BBS1 header stores `sizeof(bb_match)` as its compat guard
// (puffer/bloodbowl/bloodbowl.h:1655-1671), and the same size feeds
// bbe_state_fingerprint() (bloodbowl.h:185-190). A new field would invalidate
// every record of the hash-pinned filtered bank (D191: 15,348 records / 5,328
// replay IDs). The codebase states the rule at bloodbowl.h:701 — counters
// "Live in the env (never bb_match -- bank fingerprint safe)". There is no
// spare-byte trick either: the previous boundary counters already consumed the
// struct's tail padding exactly (offsetof(turnovers_completed) + 2 ==
// sizeof(bb_match)).
//
// MECHANISM. The engine records through a THREAD-LOCAL pointer to a struct the
// CALLER owns: the RL env keeps one per Bloodbowl, engine tests keep one on the
// stack. Thread-local rather than a plain process-global (the bb_casualty_hook
// pattern, bb_proc.h:118) because the training binding steps environments from
// several OpenMP worker threads — one shared sink would cross-attribute counts
// between environments and race on the counters (the same C11 data race that
// gated the -DBB_COVERAGE skill counters, bb_hooks.h:157-170). NULL is the
// default, so every existing driver, tool, fuzzer and replay harness keeps its
// exact behavior and pays nothing but a NULL test.
//
// No rule ever READS this tally, so it cannot affect determinism, dice
// consumption, or a golden trace.
#ifndef BB_STALL_H
#define BB_STALL_H

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

// Team turns per half. Overtime halves reuse turn numbers 1..8, so a turn
// number is always a valid index after bb_stall_index() clamping.
#define BB_STALL_TURNS 8

// Indexed [team][turn - 1]. Counts are per match/episode; the owner zeroes it.
typedef struct {
    // The crowd D6 was CONSUMED for this team on this turn — i.e. the team
    // was Stalling by the rulebook's definition (eligible carrier held the
    // ball and either finished the activation still carrying, or the coach
    // ended the team turn without activating them). This is the behavioral
    // count the T1-T6 promotion gate needs; it is dice-independent.
    uint32_t rolls[2][BB_STALL_TURNS];
    // ...and the roll came up >= the current team turn, so the crowd acts and
    // a knockdown was pushed. rolls - acted = stalls the dice forgave.
    uint32_t acted[2][BB_STALL_TURNS];
    // ...and that knockdown actually latched a Turnover. acted - turnovers =
    // knockdowns prevented after the fact (Steady Footing's 6).
    uint32_t turnovers[2][BB_STALL_TURNS];
    // Genuine team-turn completions by turn number, bumped at exactly the two
    // sites that bump m->turns_completed (proc_turn.c turn_end and
    // proc_match.c touchdown_advance) so it can never disagree with them.
    // This is the denominator that turns a stall count into a stall RATE.
    uint32_t turn_ends[2][BB_STALL_TURNS];
} bb_stall_tally;

#if defined(__cplusplus)
#define BB_STALL_THREAD_LOCAL thread_local
#else
#define BB_STALL_THREAD_LOCAL _Thread_local
#endif

// Where the engine records. NULL (default) = telemetry off. Defined in
// engine/src/proc_turn.c, next to the rule that writes it.
extern BB_STALL_THREAD_LOCAL bb_stall_tally* bb_stall_sink;

// Attach/detach for the CALLING THREAD only. Callers that drive the engine
// from a worker pool must attach on the thread that will run bb_apply /
// bb_advance, i.e. inside their step function, not once at construction.
static inline void bb_stall_attach(bb_stall_tally* t) { bb_stall_sink = t; }
static inline bb_stall_tally* bb_stall_attached(void) { return bb_stall_sink; }
static inline void bb_stall_reset(bb_stall_tally* t) { memset(t, 0, sizeof *t); }

static inline int bb_stall_index(int turn) {
    if (turn < 1) return 0;
    if (turn > BB_STALL_TURNS) return BB_STALL_TURNS - 1;
    return turn - 1;
}

// --- Engine-side recorders (no-ops when nothing is attached) -----------------
static inline void bb_stall_note_roll(int team, int turn, bool crowd_acts) {
    bb_stall_tally* t = bb_stall_sink;
    if (t == 0 || team < 0 || team > 1) return;
    int i = bb_stall_index(turn);
    t->rolls[team][i]++;
    if (crowd_acts) t->acted[team][i]++;
}

static inline void bb_stall_note_turnover(int team, int turn) {
    bb_stall_tally* t = bb_stall_sink;
    if (t == 0 || team < 0 || team > 1) return;
    t->turnovers[team][bb_stall_index(turn)]++;
}

static inline void bb_stall_note_turn_end(int team, int turn) {
    bb_stall_tally* t = bb_stall_sink;
    if (t == 0 || team < 0 || team > 1) return;
    t->turn_ends[team][bb_stall_index(turn)]++;
}

// --- Consumer-side sums -----------------------------------------------------
typedef enum {
    BB_STALL_ROLLS = 0,
    BB_STALL_ACTED,
    BB_STALL_TURNOVERS,
    BB_STALL_TURN_ENDS,
} bb_stall_series;

// Sum of one series over a 1-based INCLUSIVE turn window; team < 0 = both.
static inline uint32_t bb_stall_sum(const bb_stall_tally* t, bb_stall_series s,
                                    int team, int turn_lo, int turn_hi) {
    if (t == 0) return 0;
    const uint32_t(*c)[BB_STALL_TURNS] = t->rolls;
    if (s == BB_STALL_ACTED) c = t->acted;
    else if (s == BB_STALL_TURNOVERS) c = t->turnovers;
    else if (s == BB_STALL_TURN_ENDS) c = t->turn_ends;
    if (turn_lo < 1) turn_lo = 1;
    if (turn_hi > BB_STALL_TURNS) turn_hi = BB_STALL_TURNS;
    uint32_t sum = 0;
    for (int tm = 0; tm < 2; tm++) {
        if (team >= 0 && tm != team) continue;
        for (int turn = turn_lo; turn <= turn_hi; turn++) {
            sum += c[tm][turn - 1];
        }
    }
    return sum;
}

#endif // BB_STALL_H
