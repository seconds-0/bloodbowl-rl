// bb_match.h — the complete in-match state and the engine's step interface.
//
// Design rules:
//   * Fixed size, no pointers, memcpy-able. Copying a bb_match IS a forward
//     model snapshot (search, undo, golden traces).
//   * The engine is a PROCEDURE STACK machine. Blood Bowl resolves as nested
//     procedures with coach decision points (turn -> activation -> move step ->
//     dodge -> reroll offer -> ... ; block -> choose dice -> push chain ->
//     armour -> injury -> casualty -> apothecary ...). bb_advance() runs
//     procedures until a decision is required or the match ends.
//   * Every die roll goes through the bb_rng passed to bb_advance/bb_apply —
//     the state itself holds no RNG, so the same state can be advanced under
//     PRNG or under a replay dice script.
#ifndef BB_MATCH_H
#define BB_MATCH_H

#include "bb/bb_types.h"
#include "bb/bb_actions.h"
#include "bb/bb_rng.h"

// --- Procedure stack ---------------------------------------------------------
// Procedure ids. Each procedure is a small state machine over its `phase`
// byte; params live in a..d / data. Implementations in engine/src/proc_*.c.
typedef enum {
    BB_PROC_NONE = 0,
    BB_PROC_MATCH,        // whole-match driver (halves, drives)
    BB_PROC_PREGAME,      // weather, fans, (inducements/prayers when enabled)
    BB_PROC_SETUP,        // both coaches set up a drive
    BB_PROC_KICKOFF,      // kick + kickoff event + ball landing
    BB_PROC_TEAM_TURN,    // one team turn (activations until done/turnover)
    BB_PROC_ACTIVATION,   // a single player's activation
    BB_PROC_MOVE,         // movement sub-machine (steps, dodges, rushes, pickup)
    BB_PROC_DODGE,        // a dodge test for one step
    BB_PROC_RUSH,         // a rush (GFI) test for one step
    BB_PROC_PICKUP,
    BB_PROC_BLOCK,        // single block incl. dice pool & choice
    BB_PROC_PUSH,         // push (chain) resolution incl. square choice
    BB_PROC_KNOCKDOWN,    // a player is knocked down (ball, armour trigger)
    BB_PROC_ARMOUR,       // armour roll (incl. foul modifiers)
    BB_PROC_INJURY,       // injury roll
    BB_PROC_CASUALTY,     // D16 casualty + apothecary window
    BB_PROC_PASS,         // pass action: range, test, interception, scatter/catch
    BB_PROC_CATCH,
    BB_PROC_SCATTER,      // ball scatter / bounce resolution
    BB_PROC_THROW_IN,
    BB_PROC_HANDOFF,
    BB_PROC_FOUL,
    BB_PROC_TTM,          // throw team-mate
    BB_PROC_TEST,         // generic D6 test w/ reroll window (parameterized)
    BB_PROC_TOUCHDOWN,
    BB_PROC_TURNOVER,
    BB_PROC_END_DRIVE,
    BB_PROC_KO_RECOVERY,
    BB_PROC_COUNT
} bb_proc;

typedef struct {
    uint8_t proc;   // bb_proc
    uint8_t phase;  // step within the procedure's state machine
    uint8_t a, b;   // params: usually player slots
    uint8_t x, y;   // params: usually a square
    uint16_t data;  // procedure-specific extra state
} bb_frame;

#define BB_STACK_MAX 32

// --- Engine status -----------------------------------------------------------
typedef enum {
    BB_STATUS_RUNNING = 0,   // bb_advance may continue
    BB_STATUS_DECISION,      // a coach decision is required (see decision_team)
    BB_STATUS_MATCH_OVER,
    BB_STATUS_ERROR,         // illegal action applied / dice script divergence
} bb_status;

// --- Match state ---------------------------------------------------------------
typedef struct {
    // Players & pitch
    bb_player players[BB_NUM_PLAYERS];
    uint8_t grid[BB_PITCH_LEN][BB_PITCH_WID]; // player slot + 1; 0 = empty
    bb_ball ball;

    // Clock & score
    uint8_t half;           // 1..2 (3+ = overtime when enabled)
    uint8_t turn[2];        // team turn counters 1..8 per half
    uint8_t score[2];
    uint8_t active_team;    // team whose team turn it is
    uint8_t kicking_team;   // this drive
    uint8_t weather;        // bb_weather

    // Team-turn resources. BB2025: any number of team re-rolls per turn (the
    // only limit is that no single die/pool is ever re-rolled twice).
    uint8_t rerolls[2];
    uint8_t rerolls_start[2]; // purchased complement; replenished at half-time,
                              // and bonus re-rolls (Brilliant Coaching) expire
                              // back to this at the end of each drive
    uint8_t blitz_used;               // team blitz action used this turn
    uint8_t pass_used;                // pass action used this turn
    uint8_t handoff_used;
    uint8_t foul_used;
    uint8_t ttm_used;
    uint8_t ktm_used;                 // Kick Team-mate: its own per-turn budget
    uint8_t secure_used;              // BB2025 Secure the Ball: once per turn
    uint8_t bribes[2];                // bribe tokens (Get the Ref / inducements)
    uint8_t apothecary[2];            // remaining uses
    uint8_t coach_ejected[2];         // "You're Outta Here": no more arguing

    // Procedure stack
    bb_frame stack[BB_STACK_MAX];
    uint8_t stack_top;      // number of frames

    // Decision surface (valid when status == BB_STATUS_DECISION)
    uint8_t status;         // bb_status
    uint8_t decision_team;  // which coach must act
    uint8_t turnover;       // pending turnover latch for the active team
    uint16_t ret;           // last popped child's result (child -> parent)

    // Bookkeeping
    uint32_t step_count;    // decisions resolved (sanity/timeout)
    uint8_t team_id[2];     // roster ids (codegen index) for obs/embeddings
} bb_match;

// --- Lifecycle -----------------------------------------------------------------
// Initialize a match between two rosters (codegen team ids) with default
// matchday squads (first 11+ players per roster definition). Procedural/custom
// squads come via bb_match_init_custom (Phase 5).
void bb_match_init(bb_match* m, int home_team_id, int away_team_id);

// Advance the engine until a coach decision is required or the match ends.
// All dice are drawn from `rng`. Returns the resulting status.
bb_status bb_advance(bb_match* m, bb_rng* rng);

// Enumerate legal actions for the current decision point into `out`
// (capacity BB_LEGAL_MAX). Returns the count. Only valid in BB_STATUS_DECISION.
int bb_legal_actions(const bb_match* m, bb_action* out);

// Apply one action for the current decision point, then advance.
// Applying an action not in bb_legal_actions sets BB_STATUS_ERROR.
bb_status bb_apply(bb_match* m, bb_action a, bb_rng* rng);

// --- Queries (pure) --------------------------------------------------------------
static inline const bb_player* bb_at(const bb_match* m, int x, int y) {
    uint8_t v = m->grid[x][y];
    return v ? &m->players[v - 1] : 0;
}
static inline int bb_slot_at(const bb_match* m, int x, int y) {
    return m->grid[x][y] ? m->grid[x][y] - 1 : -1;
}

// Number of opposing tackle zones on square (x,y) for a player of `team`.
int bb_tackle_zones(const bb_match* m, int team, int x, int y);

// Does this player currently exert a tackle zone?
bool bb_exerts_tz(const bb_match* m, int slot);

// May this player attempt catches / receive hand-offs (standing, has TZ,
// not Distracted)?
bool bb_can_catch(const bb_match* m, int slot);

// Marked/Open (BB2025): a standing player is Marked while in an opposing TZ.
bool bb_is_marked(const bb_match* m, int slot);

#endif // BB_MATCH_H
