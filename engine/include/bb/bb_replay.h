// bb_replay.h — the engine's replay format.
//
// A replay is: an init record (how to construct the initial match) followed by
// the interleaved sequence of coach actions and dice values, exactly as
// consumed. Because the engine is deterministic, (init, actions, dice) fully
// reproduces the match. One format serves golden-trace tests, the raylib
// viewer, FUMBBL-replay normalization output, and BC training data.
//
// On-disk encoding: JSON Lines (one JSON object per line) — easy to read from
// Python and to diff. The C reader parses only this fixed schema.
//
//   {"t":"init","v":1,"home":3,"away":7,"seed":12345}
//   {"t":"a","u":328706}            // packed bb_action (bb_action_pack)
//   {"t":"d","s":6,"v":4}           // die with s sides rolled v
//   {"t":"end","home_score":2,"away_score":1}
//
// Memory model: the writer appends to a growable buffer owned by the caller;
// the reader walks a loaded buffer without allocating.
#ifndef BB_REPLAY_H
#define BB_REPLAY_H

#include <stdint.h>
#include <stdio.h>
#include "bb/bb_actions.h"

#define BB_REPLAY_VERSION 1

typedef struct {
    FILE* f;
} bb_replay_writer;

int  bb_replay_open(bb_replay_writer* w, const char* path);
void bb_replay_init_record(bb_replay_writer* w, int home_team_id, int away_team_id, uint64_t seed);
void bb_replay_action(bb_replay_writer* w, bb_action a);
void bb_replay_dice(bb_replay_writer* w, int sides, int value);
void bb_replay_end_record(bb_replay_writer* w, int home_score, int away_score);
void bb_replay_close(bb_replay_writer* w);

// bb_rng dice sink that records into a writer:
//   bb_rng_set_sink(&rng, bb_replay_dice_sink, &writer);
void bb_replay_dice_sink(void* user, int sides, int value);

// --- Reader ------------------------------------------------------------------
typedef enum {
    BB_REC_INIT,
    BB_REC_ACTION,
    BB_REC_DICE,
    BB_REC_END,
    BB_REC_EOF,
    BB_REC_PARSE_ERROR,
} bb_rec_type;

typedef struct {
    bb_rec_type type;
    // init
    int home_team_id, away_team_id;
    uint64_t seed;
    int version;
    // action
    bb_action action;
    // dice
    int sides, value;
    // end
    int home_score, away_score;
} bb_record;

typedef struct {
    const char* buf; // caller-owned replay file contents
    size_t len;
    size_t pos;
    int line;
} bb_replay_reader;

void bb_replay_reader_init(bb_replay_reader* r, const char* buf, size_t len);
// Parse the next record. Returns false at EOF (record.type == BB_REC_EOF) or
// parse error (BB_REC_PARSE_ERROR with r->line set).
bool bb_replay_next(bb_replay_reader* r, bb_record* out);

#endif // BB_REPLAY_H
