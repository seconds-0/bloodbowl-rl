// bb_rng.h — deterministic dice. Every die in the engine rolls through here.
//
// Two modes:
//   PRNG   — PCG32 seeded stream (seed, stream-id) for training & simulation.
//   SCRIPT — consumes an injected sequence of pre-recorded values; used by the
//            replay harness (FUMBBL differential, golden traces) and tests.
//
// An optional `sink` callback observes every roll in either mode — the replay
// writer uses it to record the dice log.
//
// In SCRIPT mode, exhausting the script or reading a value outside [1, sides]
// is a hard error reported via bb_rng_error(); callers treat it as a
// divergence (test failure), never as a crash.
#ifndef BB_RNG_H
#define BB_RNG_H

#include <stdint.h>
#include <stdbool.h>

typedef enum {
    BB_RNG_PRNG = 0,
    BB_RNG_SCRIPT,
} bb_rng_mode;

typedef void (*bb_dice_sink)(void* user, int sides, int value);

typedef struct {
    // PCG32
    uint64_t state;
    uint64_t inc;
    // Script
    const uint8_t* script;
    int script_len;
    int script_pos;
    // Common
    uint8_t mode;     // bb_rng_mode
    uint8_t error;    // sticky: script exhausted / out-of-range value
    bb_dice_sink sink;
    void* sink_user;
} bb_rng;

// Seed a PRNG-mode generator. `stream` selects an independent sequence
// (use the env index for vectorized training).
void bb_rng_seed(bb_rng* rng, uint64_t seed, uint64_t stream);

// Configure SCRIPT mode over `values` (each entry is the face value rolled).
void bb_rng_script(bb_rng* rng, const uint8_t* values, int len);

// Attach/detach a dice observer (replay recording).
void bb_rng_set_sink(bb_rng* rng, bb_dice_sink sink, void* user);

// Roll a fair die with `sides` faces; returns 1..sides. Unbiased (rejection
// sampling) in PRNG mode.
int bb_roll(bb_rng* rng, int sides);

static inline int bb_d3(bb_rng* r)  { return bb_roll(r, 3); }
static inline int bb_d6(bb_rng* r)  { return bb_roll(r, 6); }
static inline int bb_d8(bb_rng* r)  { return bb_roll(r, 8); }
static inline int bb_d16(bb_rng* r) { return bb_roll(r, 16); }
static inline int bb_2d6(bb_rng* r) { return bb_d6(r) + bb_d6(r); }

// Block dice are d6 mapped onto faces (1=skull .. 6=pow); rolled as d6 so
// scripts/replays record the raw face index.
static inline int bb_roll_block_die(bb_rng* r) { return bb_d6(r); }

// True if a SCRIPT-mode generator hit an error (exhausted / bad value).
static inline bool bb_rng_error(const bb_rng* rng) { return rng->error != 0; }

// Raw 32-bit output (used by procedural generation, not by game rules).
uint32_t bb_rng_next(bb_rng* rng);

#endif // BB_RNG_H
