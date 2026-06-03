// bb_proc.h — internal procedure-machine interface (engine/src only).
//
// Each procedure implements up to three handlers, registered in the dispatch
// table in bb_match.c:
//
//   advance(m, rng) — called while the frame is on top of the stack and the
//       engine is RUNNING. Does dice/state work; may push child frames, pop
//       itself (bb_pop), or request a coach decision (bb_need_decision).
//   legal(m, out)   — enumerate the legal actions for the pending decision.
//   apply(m, a, rng)— consume a (validated) action; typically bumps `phase`.
//
// Frames communicate to their parent through m->ret (last child result).
#ifndef BB_PROC_H
#define BB_PROC_H

#include "bb/bb_match.h"

typedef void (*bb_proc_advance)(bb_match* m, bb_rng* rng);
typedef int (*bb_proc_legal)(const bb_match* m, bb_action* out);
typedef void (*bb_proc_apply)(bb_match* m, bb_action a, bb_rng* rng);

typedef struct {
    bb_proc_advance advance;
    bb_proc_legal legal;
    bb_proc_apply apply;
} bb_proc_vtable;

extern bb_proc_vtable bb_proc_table[BB_PROC_COUNT];

// --- Stack helpers (defined in bb_match.c) ---
bb_frame* bb_top(bb_match* m);
bb_frame* bb_parent(bb_match* m); // frame below top, or NULL
void bb_push(bb_match* m, bb_proc proc, int a, int b, int x, int y);
void bb_pop(bb_match* m);
// Request a coach decision and pause the engine.
void bb_need_decision(bb_match* m, int team);

// --- Shared mechanics helpers ---
// Move a player on the grid (handles grid bookkeeping; not rules).
void bb_place(bb_match* m, int slot, int x, int y);
void bb_remove_from_pitch(bb_match* m, int slot, int new_location);

// Ball helpers.
void bb_ball_to(bb_match* m, int x, int y);     // ground at square (no bounce logic)
void bb_give_ball(bb_match* m, int slot);
void bb_drop_ball(bb_match* m);                 // carrier loses it (pre-bounce)

// Knock a player down (pushes KNOCKDOWN with cause in data).
typedef enum {
    BB_KD_BLOCK = 0,
    BB_KD_FAILED_DODGE,
    BB_KD_FAILED_RUSH,
    BB_KD_FOUL,
    BB_KD_OTHER,
} bb_kd_cause;
void bb_knockdown(bb_match* m, int slot, int cause, int armour_mod);
// Knockdown with a known causer (block/foul) so armour/injury skill mods
// (Mighty Blow, Claws...) apply. causer = -1 for none.
void bb_knockdown2(bb_match* m, int slot, int cause, int armour_mod, int causer);

// Latch a turnover for the active team (takes effect as procs unwind).
void bb_turnover(bb_match* m);

// If the ball carrier is standing in their scoring end zone, push TOUCHDOWN
// and return true.
bool bb_check_td(bb_match* m);

// Is a KICKOFF frame on the stack (kicked ball still resolving)?
bool bb_in_kickoff(const bb_match* m);

// Squares / geometry.
static inline bool bb_on_pitch_xy(int x, int y) {
    return x >= 0 && x < BB_PITCH_LEN && y >= 0 && y < BB_PITCH_WID;
}
bool bb_adjacent(int x1, int y1, int x2, int y2);

// End-zone x for scoring direction of `team` (home scores at x==25).
static inline int bb_endzone_x(int team) { return team == BB_HOME ? BB_PITCH_LEN - 1 : 0; }
static inline bool bb_own_half_x(int team, int x) {
    return team == BB_HOME ? (x <= 12) : (x >= 13);
}

// Stat test target helper: returns needed roll (clamped 2..6) for an AG/PA
// style target-number test with modifiers. Natural 1 always fails, natural 6
// always succeeds — callers compare the raw die separately.
int bb_test_target(int stat_target, int modifiers);

#endif // BB_PROC_H
