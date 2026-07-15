// authored_drill.h — deterministic, no-surgery authored-state replay core.
#ifndef AUTHORED_DRILL_H
#define AUTHORED_DRILL_H

#include "bb/bb_match.h"

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define AD_MAX_ACTIONS 8192
#define AD_MAX_DICE 8192
#define AD_ERROR_CAP 192

typedef struct {
    uint64_t procgen_seed;
    uint64_t procgen_stream;
    uint64_t game_seed;
    uint64_t game_stream;
    int home_team;
    int away_team;
    int exclude_team;
    bb_procgen_params procgen;

    bb_match initialized;
    bb_match captured;
    uint32_t actions[AD_MAX_ACTIONS];
    uint8_t decision_teams[AD_MAX_ACTIONS];
    uint8_t dice_sides[AD_MAX_DICE];
    uint8_t dice_values[AD_MAX_DICE];
    int action_count;
    int dice_count;
} ad_recipe;

typedef struct {
    uint32_t source_id;
    uint32_t decision_index;
    const ad_recipe* recipe;
} ad_bbs_record;

// Discover the first genuine team-turn decision using only engine init,
// advance, and legal apply calls. The built-in controller is deterministic and
// setup-aware; it receives match state as const and cannot mutate it.
int ad_discover_first_team_turn(ad_recipe* recipe, char error[AD_ERROR_CAP]);

// Reinitialize from the procgen seed, inject the exact recorded in-match dice,
// replay every packed legal action, and require raw-state identity.
int ad_replay_exact(const ad_recipe* recipe, bb_match* out,
                    char error[AD_ERROR_CAP]);

// BBS1 compatibility stamp shared with the Puffer loader.
uint32_t ad_bbs_fingerprint(void);

// Write an ordinary BBS1 stream. The writer exact-replays every recipe into
// private storage and serializes only those verified bytes; callers cannot
// supply a separately mutable raw match. It also requires decision_index to
// equal the verified recipe capture point. Authored IDs must use the reserved
// 0xA high nibble. A failed call invalidates the caller-owned stream; atomic
// publication is the responsibility of the later manifest transaction.
int ad_bbs_write(FILE* file, const ad_bbs_record* records, size_t count,
                 char error[AD_ERROR_CAP]);

#endif // AUTHORED_DRILL_H
