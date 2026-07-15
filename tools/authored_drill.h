// authored_drill.h — deterministic, no-surgery authored-state replay core.
#ifndef AUTHORED_DRILL_H
#define AUTHORED_DRILL_H

#include "bb/bb_match.h"

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define AD_MAX_ACTIONS 8192
#define AD_MAX_DICE 8192
#define AD_CONTINUATION_DICE 256
#define AD_ERROR_CAP 192
#define AD_F3_SECOND_HALF_TURN_COUNT 8
#define AD_F3_SECOND_HALF_AXIS_COUNT \
    ((BB_AWAY + 1) * AD_F3_SECOND_HALF_TURN_COUNT)

typedef enum {
    AD_RECIPE_FIRST_TEAM_TURN = 0,
    AD_RECIPE_F3_LATE_SECOND_HALF,
    AD_RECIPE_F1_PASS_OPPORTUNITY,
    AD_RECIPE_F2_HANDOFF_OPPORTUNITY,
    AD_RECIPE_F5_SCORE_OR_WAIT,
    AD_RECIPE_F4_PENDING_DODGE_REROLL,
    AD_RECIPE_F3_EXACT_SECOND_HALF_TURN,
    AD_RECIPE_KIND_COUNT,
} ad_recipe_kind;

typedef struct {
    uint64_t procgen_seed;
    uint64_t procgen_stream;
    uint64_t game_seed;
    uint64_t game_stream;
    uint64_t controller_seed;
    uint64_t controller_stream;
    ad_recipe_kind kind;
    // Configured only for AD_RECIPE_F3_EXACT_SECOND_HALF_TURN. Keeping these
    // inside the recipe binds the requested axis cell through rediscovery.
    int capture_turn;
    int capture_active_team;
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

// Play through real drives and halftime with an independent deterministic
// controller stream, capturing a fresh team-turn boundary in half two at turn
// five or later. No clock, score, player, ball, or procedure field is written.
int ad_discover_f3_late_second_half(ad_recipe* recipe,
                                    char error[AD_ERROR_CAP]);

// Reach an exact fresh team-turn boundary for one half-two turn/orientation
// cell. The request is stored in the recipe and therefore covered by complete
// provenance rediscovery and byte-exact replay.
int ad_discover_f3_second_half_turn(ad_recipe* recipe, int turn,
                                    int active_team,
                                    char error[AD_ERROR_CAP]);

// Require exactly one structurally valid recipe for each half-two turn 1-8 and
// active-team orientation. The writer remains the provenance/replay gate; this
// is a coverage/quota contract, not a sampler or label.
int ad_validate_f3_second_half_turn_axis(const ad_recipe* recipes, size_t count,
                                         char error[AD_ERROR_CAP]);

// Purely validate that a supported fresh team-turn state has a standing,
// unused active-team carrier whose legal ACTIVATE -> DECLARE PASS path reaches
// at least one legal catch-capable team-mate target without consuming a die.
int ad_f1_pass_opportunity_valid(const bb_match* match);

// Play only legal engine actions until the F1 predicate above is true. The
// nested activation/declaration/target frames are privately probed, not stored;
// the captured BBS state remains the supported fresh team-turn boundary.
int ad_discover_f1_pass_opportunity(ad_recipe* recipe,
                                    char error[AD_ERROR_CAP]);

// Purely validate that a supported fresh team-turn state has a standing,
// unused active-team carrier whose legal ACTIVATE -> DECLARE HAND-OFF path
// reaches at least one adjacent catch-capable team-mate without consuming a
// die. A No Ball target may be rules-legal but does not satisfy this proof.
int ad_f2_handoff_opportunity_valid(const bb_match* match);

// Play only legal engine actions until the F2 predicate above is true. The
// nested activation/declaration/target frames are privately probed, not stored;
// the captured BBS state remains the supported fresh team-turn boundary.
int ad_discover_f2_handoff_opportunity(ad_recipe* recipe,
                                       char error[AD_ERROR_CAP]);

// Purely validate that a supported fresh team-turn state has an unused
// active-team carrier that can score without dice under the engine's BB2025
// Stalling predicate, and whose private zero-die activation -> Move declaration
// retains the legal choice to end the activation without scoring.
int ad_f5_score_or_wait_valid(const bb_match* match);

// Play only legal engine actions until the F5 predicate above is true. The
// activation/Move decision is privately probed and discarded; the captured
// BBS state remains the supported fresh team-turn boundary.
int ad_discover_f5_score_or_wait(ad_recipe* recipe,
                                 char error[AD_ERROR_CAP]);

// Purely validate the exact supported nested F4 decision: a failed first-step,
// non-Rush Dodge awaiting a real reroll Use/Decline choice. The pending choice
// itself is the capture endpoint; no selected action or outcome is a label.
int ad_f4_pending_dodge_reroll_valid(const bb_match* match);

// Play only legal engine actions until the exact nested F4 predicate is true.
// Discovery stops before applying either reroll choice and records every
// preceding legal action and game die for byte-exact replay.
int ad_discover_f4_pending_dodge_reroll(ad_recipe* recipe,
                                        char error[AD_ERROR_CAP]);

// Reinitialize from the procgen seed, inject the exact recorded in-match dice,
// replay every packed legal action, and require recipe-specific endpoint and
// raw-state identity.
int ad_replay_exact(const ad_recipe* recipe, bb_match* out,
                    char error[AD_ERROR_CAP]);

// Validate a loaded BBS1 state, choose the lowest packed legal action, and
// apply it to a private copy with a bounded deterministic dice suffix. This is
// a post-serialization resumability gate, not a policy-quality label.
int ad_verify_one_action_continuation(const bb_match* loaded,
                                      uint32_t* packed_action,
                                      bb_status* result_status,
                                      int* dice_used,
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
