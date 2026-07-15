// Deterministic authored-state discovery/replay primitives. This module owns
// transcripts and serialization; only the engine owns mutable bb_match state.
#include "authored_drill.h"

#include "bb/gen_teams.h"
#include "bb/gen_skills.h"

#include <stdarg.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    ad_recipe* recipe;
    int overflow;
} ad_record_sink;

typedef struct {
    const ad_recipe* recipe;
    int seen;
    int mismatch;
} ad_check_sink;

typedef struct {
    int seen;
} ad_count_sink;

static int ad_fail(char error[AD_ERROR_CAP], const char* fmt, ...) {
    if (error != NULL) {
        va_list args;
        va_start(args, fmt);
        vsnprintf(error, AD_ERROR_CAP, fmt, args);
        va_end(args);
    }
    return -1;
}

static void ad_record_die(void* user, int sides, int value) {
    ad_record_sink* sink = user;
    if (sink->recipe->dice_count >= AD_MAX_DICE || sides < 1 || sides > 255 ||
        value < 1 || value > 255) {
        sink->overflow = 1;
        return;
    }
    int i = sink->recipe->dice_count++;
    sink->recipe->dice_sides[i] = (uint8_t)sides;
    sink->recipe->dice_values[i] = (uint8_t)value;
}

static void ad_check_die(void* user, int sides, int value) {
    ad_check_sink* sink = user;
    int i = sink->seen++;
    if (i >= sink->recipe->dice_count ||
        sink->recipe->dice_sides[i] != sides ||
        sink->recipe->dice_values[i] != value) {
        sink->mismatch = 1;
    }
}

static void ad_count_die(void* user, int sides, int value) {
    (void)sides;
    (void)value;
    ad_count_sink* sink = user;
    sink->seen++;
}

static int ad_has_team_turn(const bb_match* match) {
    return match->stack_top > 0 &&
           match->stack[match->stack_top - 1].proc == BB_PROC_TEAM_TURN;
}

static int ad_packed_less(bb_action left, bb_action right) {
    return bb_action_pack(left) < bb_action_pack(right);
}

// Canonical pre-turn controller. Formation choices mirror the engine smoke
// controller, but all tie-breaking is stable packed-action order.
static int ad_pick_pre_turn(const bb_match* match, const bb_action* legal, int n) {
    int best = -1;
    for (int i = 0; i < n; i++) {
        if (legal[i].type == BB_A_SETUP_DONE) return i;
    }
    for (int pass = 0; pass < 3; pass++) {
        best = -1;
        for (int i = 0; i < n; i++) {
            if (legal[i].type != BB_A_SETUP_PLACE ||
                match->players[legal[i].arg].location != BB_LOC_RESERVES) {
                continue;
            }
            int is_los = (legal[i].x == 12 || legal[i].x == 13) &&
                         legal[i].y >= 4 && legal[i].y <= 10;
            int is_centre = legal[i].y >= 4 && legal[i].y <= 10;
            if ((pass == 0 && !is_los) || (pass == 1 && (is_los || !is_centre)) ||
                (pass == 2 && (is_los || is_centre))) {
                continue;
            }
            if (best < 0 || ad_packed_less(legal[i], legal[best])) best = i;
        }
        if (best >= 0) return best;
    }
    for (int i = 0; i < n; i++) {
        if (best < 0 || ad_packed_less(legal[i], legal[best])) best = i;
    }
    return best;
}

static int ad_pick_long_horizon(const bb_match* match,
                                const bb_action* legal, int n,
                                bb_rng* controller_rng) {
    int in_setup = n > 0 &&
        (legal[0].type == BB_A_SETUP_PLACE ||
         legal[0].type == BB_A_SETUP_REMOVE);
    if (in_setup) return ad_pick_pre_turn(match, legal, n);
    for (int i = 0; i < n; i++) {
        if (legal[i].type == BB_A_SETUP_DONE) return i;
    }
    return (int)(bb_rng_next(controller_rng) % (uint32_t)n);
}

static int ad_action_is_legal(const bb_match* match, uint32_t packed) {
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(match, legal);
    for (int i = 0; i < n; i++) {
        if (bb_action_pack(legal[i]) == packed) return 1;
    }
    return 0;
}

static int ad_recipe_config_valid(const ad_recipe* recipe) {
    return recipe->kind >= AD_RECIPE_FIRST_TEAM_TURN &&
           recipe->kind < AD_RECIPE_KIND_COUNT &&
           recipe->home_team >= -1 && recipe->home_team < BB_TEAM_COUNT &&
           recipe->away_team >= -1 && recipe->away_team < BB_TEAM_COUNT &&
           recipe->exclude_team >= -1 && recipe->exclude_team < BB_TEAM_COUNT &&
           recipe->procgen.skillup_max_players >= 0 &&
           recipe->procgen.skillup_max_players <= BB_TEAM_SLOTS &&
           recipe->procgen.skillup_max_each >= 0 &&
           recipe->procgen.skillup_max_each <= 12 &&
           recipe->procgen.skillup_secondary_pct >= 0.0f &&
           recipe->procgen.skillup_secondary_pct <= 1.0f;
}

static int ad_capture_ready(const bb_match* match, ad_recipe_kind kind) {
    if (!ad_has_team_turn(match)) return 0;
    if (kind == AD_RECIPE_FIRST_TEAM_TURN) return 1;
    return match->half == 2 && match->active_team <= BB_AWAY &&
           match->turn[match->active_team] >= 5;
}

static void ad_clear_discovery(ad_recipe* recipe) {
    memset(&recipe->initialized, 0, sizeof recipe->initialized);
    memset(&recipe->captured, 0, sizeof recipe->captured);
    memset(recipe->actions, 0, sizeof recipe->actions);
    memset(recipe->decision_teams, 0, sizeof recipe->decision_teams);
    memset(recipe->dice_sides, 0, sizeof recipe->dice_sides);
    memset(recipe->dice_values, 0, sizeof recipe->dice_values);
    recipe->action_count = 0;
    recipe->dice_count = 0;
}

static int ad_discover(ad_recipe* recipe, ad_recipe_kind kind,
                       char error[AD_ERROR_CAP]) {
    if (recipe == NULL) return ad_fail(error, "null recipe");
    recipe->kind = kind;
    if (!ad_recipe_config_valid(recipe)) return ad_fail(error, "invalid recipe configuration");
    ad_clear_discovery(recipe);

    bb_rng procgen_rng;
    bb_rng_seed(&procgen_rng, recipe->procgen_seed, recipe->procgen_stream);
    bb_match match;
    bb_match_init_forced_p(&match, &procgen_rng, recipe->home_team,
                           recipe->away_team, recipe->exclude_team,
                           &recipe->procgen);
    recipe->initialized = match;

    bb_rng game_rng;
    bb_rng_seed(&game_rng, recipe->game_seed, recipe->game_stream);
    ad_record_sink sink = {recipe, 0};
    bb_rng_set_sink(&game_rng, ad_record_die, &sink);
    bb_rng controller_rng;
    bb_rng_seed(&controller_rng, recipe->controller_seed,
                recipe->controller_stream);
    bb_status status = bb_advance(&match, &game_rng);

    while (status == BB_STATUS_DECISION && recipe->action_count < AD_MAX_ACTIONS) {
        if (sink.overflow) return ad_fail(error, "dice transcript exceeds %d", AD_MAX_DICE);
        if (ad_capture_ready(&match, kind)) {
            bb_action legal[BB_LEGAL_MAX];
            if (bb_legal_actions(&match, legal) <= 0) {
                return ad_fail(error, "captured decision has no legal actions");
            }
            recipe->captured = match;
            if (error != NULL) error[0] = '\0';
            return 0;
        }

        bb_action legal[BB_LEGAL_MAX];
        int n = bb_legal_actions(&match, legal);
        if (n <= 0) return ad_fail(error, "decision %d has no legal action", recipe->action_count);
        int picked = kind == AD_RECIPE_FIRST_TEAM_TURN
            ? ad_pick_pre_turn(&match, legal, n)
            : ad_pick_long_horizon(&match, legal, n, &controller_rng);
        if (picked < 0 || picked >= n) return ad_fail(error, "controller failed at decision %d", recipe->action_count);
        int i = recipe->action_count++;
        recipe->actions[i] = bb_action_pack(legal[picked]);
        recipe->decision_teams[i] = match.decision_team;
        status = bb_apply(&match, legal[picked], &game_rng);
    }

    if (sink.overflow) return ad_fail(error, "dice transcript exceeds %d", AD_MAX_DICE);
    if (recipe->action_count >= AD_MAX_ACTIONS) {
        return ad_fail(error, "action transcript exceeds %d", AD_MAX_ACTIONS);
    }
    return ad_fail(error, "match ended with status %d before capture %d",
                   status, kind);
}

int ad_discover_first_team_turn(ad_recipe* recipe, char error[AD_ERROR_CAP]) {
    return ad_discover(recipe, AD_RECIPE_FIRST_TEAM_TURN, error);
}

int ad_discover_f3_late_second_half(ad_recipe* recipe,
                                    char error[AD_ERROR_CAP]) {
    return ad_discover(recipe, AD_RECIPE_F3_LATE_SECOND_HALF, error);
}

int ad_replay_exact(const ad_recipe* recipe, bb_match* out,
                    char error[AD_ERROR_CAP]) {
    if (recipe == NULL || out == NULL) return ad_fail(error, "null replay input");
    if (!ad_recipe_config_valid(recipe)) return ad_fail(error, "invalid recipe configuration");
    if (recipe->action_count < 0 || recipe->action_count > AD_MAX_ACTIONS ||
        recipe->dice_count < 0 || recipe->dice_count > AD_MAX_DICE) {
        return ad_fail(error, "invalid transcript length");
    }

    bb_rng procgen_rng;
    bb_rng_seed(&procgen_rng, recipe->procgen_seed, recipe->procgen_stream);
    bb_match match;
    bb_match_init_forced_p(&match, &procgen_rng, recipe->home_team,
                           recipe->away_team, recipe->exclude_team,
                           &recipe->procgen);
    if (memcmp(&match, &recipe->initialized, sizeof match) != 0) {
        return ad_fail(error, "initialized match bytes differ");
    }

    bb_rng game_rng;
    bb_rng_script(&game_rng, recipe->dice_values, recipe->dice_count);
    ad_check_sink sink = {recipe, 0, 0};
    bb_rng_set_sink(&game_rng, ad_check_die, &sink);
    bb_status status = bb_advance(&match, &game_rng);

    for (int i = 0; i < recipe->action_count; i++) {
        if (status != BB_STATUS_DECISION) {
            return ad_fail(error, "action %d reached status %d", i, status);
        }
        if (match.decision_team != recipe->decision_teams[i]) {
            return ad_fail(error, "decision team differs at action %d", i);
        }
        if (!ad_action_is_legal(&match, recipe->actions[i])) {
            return ad_fail(error, "recorded action %d is not legal", i);
        }
        status = bb_apply(&match, bb_action_unpack(recipe->actions[i]), &game_rng);
    }

    if (bb_rng_error(&game_rng)) return ad_fail(error, "dice script exhausted or invalid");
    if (sink.mismatch || sink.seen != recipe->dice_count ||
        game_rng.script_pos != recipe->dice_count) {
        return ad_fail(error, "dice transcript was not consumed exactly");
    }
    if (status != BB_STATUS_DECISION || !ad_has_team_turn(&match)) {
        return ad_fail(error, "capture status/procedure differs");
    }
    if (memcmp(&match, &recipe->captured, sizeof match) != 0) {
        return ad_fail(error, "captured match bytes differ");
    }
    *out = match;
    if (error != NULL) error[0] = '\0';
    return 0;
}

int ad_verify_one_action_continuation(const bb_match* loaded,
                                      uint32_t* packed_action,
                                      bb_status* result_status,
                                      int* dice_used,
                                      char error[AD_ERROR_CAP]) {
    if (loaded == NULL) return ad_fail(error, "null continuation state");
    if (!bb_state_bank_boundary_valid(loaded)) {
        return ad_fail(error, "continuation state is not a safe BBS1 boundary");
    }

    bb_action legal[BB_LEGAL_MAX];
    int count = bb_legal_actions(loaded, legal);
    if (count <= 0) return ad_fail(error, "continuation has no legal action");
    int selected = 0;
    for (int i = 1; i < count; i++) {
        if (bb_action_pack(legal[i]) < bb_action_pack(legal[selected])) {
            selected = i;
        }
    }

    uint8_t dice[AD_CONTINUATION_DICE];
    memset(dice, 1, sizeof dice);
    bb_rng rng;
    bb_rng_script(&rng, dice, AD_CONTINUATION_DICE);
    ad_count_sink sink = {0};
    bb_rng_set_sink(&rng, ad_count_die, &sink);

    bb_match resumed = *loaded;
    bb_status status = bb_apply(&resumed, legal[selected], &rng);
    if (bb_rng_error(&rng)) {
        return ad_fail(error, "continuation dice suffix exhausted or invalid");
    }
    if (status != BB_STATUS_DECISION && status != BB_STATUS_RUNNING &&
        status != BB_STATUS_MATCH_OVER) {
        return ad_fail(error, "continuation reached engine status %d", status);
    }
    if (sink.seen < 0 || sink.seen > AD_CONTINUATION_DICE) {
        return ad_fail(error, "continuation dice count is out of bounds");
    }

    if (packed_action != NULL) {
        *packed_action = bb_action_pack(legal[selected]);
    }
    if (result_status != NULL) *result_status = status;
    if (dice_used != NULL) *dice_used = sink.seen;
    if (error != NULL) error[0] = '\0';
    return 0;
}

uint32_t ad_bbs_fingerprint(void) {
    return (uint32_t)sizeof(bb_match) * 2654435761u
         ^ ((uint32_t)BB_TEAM_COUNT << 20)
         ^ ((uint32_t)BB_SKILL_COUNT << 10)
         ^ (uint32_t)BB_A_TYPE_COUNT;
}

static int ad_write_bytes(FILE* file, const void* bytes, size_t size) {
    return fwrite(bytes, 1, size, file) == size ? 0 : -1;
}

static int ad_write_u32(FILE* file, uint32_t value) {
    uint8_t bytes[4] = {(uint8_t)value, (uint8_t)(value >> 8),
                        (uint8_t)(value >> 16), (uint8_t)(value >> 24)};
    return ad_write_bytes(file, bytes, sizeof bytes);
}

static int ad_rediscover_recipe(const ad_recipe* source, ad_recipe* out,
                                char error[AD_ERROR_CAP]) {
    *out = *source;
    int rc;
    switch (source->kind) {
        case AD_RECIPE_FIRST_TEAM_TURN:
            rc = ad_discover_first_team_turn(out, error);
            break;
        case AD_RECIPE_F3_LATE_SECOND_HALF:
            rc = ad_discover_f3_late_second_half(out, error);
            break;
        default:
            return ad_fail(error, "unknown authored recipe kind %d",
                           source->kind);
    }
    if (rc != 0) return rc;
    if (memcmp(source, out, sizeof *out) != 0) {
        return ad_fail(error, "rediscovered recipe provenance differs");
    }
    if (error != NULL) error[0] = '\0';
    return 0;
}

int ad_bbs_write(FILE* file, const ad_bbs_record* records, size_t count,
                 char error[AD_ERROR_CAP]) {
    if (file == NULL || records == NULL || count == 0) {
        return ad_fail(error, "BBS writer requires a file and records");
    }
    if (count > SIZE_MAX / sizeof(bb_match)) {
        return ad_fail(error, "BBS record count overflows allocation");
    }
    bb_match* verified = calloc(count, sizeof(*verified));
    if (verified == NULL) return ad_fail(error, "cannot allocate verified BBS records");
    ad_recipe* rediscovered = malloc(sizeof(*rediscovered));
    if (rediscovered == NULL) {
        free(verified);
        return ad_fail(error, "cannot allocate rediscovered BBS recipe");
    }

    // Independently rediscover, exact-replay, and validate the complete batch
    // before emitting even the header. This binds declared seeds and controller
    // provenance to transcripts, binds serialized bytes to exact replay, and
    // keeps malformed later records from leaving a plausible prefix.
    for (size_t i = 0; i < count; i++) {
        const ad_bbs_record* record = &records[i];
        if ((record->source_id & 0xF0000000u) != 0xA0000000u ||
            record->recipe == NULL) {
            free(rediscovered);
            free(verified);
            return ad_fail(error, "invalid authored BBS record %zu", i);
        }
        char provenance_error[AD_ERROR_CAP];
        if (ad_rediscover_recipe(record->recipe, rediscovered,
                                 provenance_error) != 0) {
            free(rediscovered);
            free(verified);
            return ad_fail(error,
                           "authored BBS record %zu provenance failed: %s",
                           i, provenance_error);
        }
        char replay_error[AD_ERROR_CAP];
        if (ad_replay_exact(rediscovered, &verified[i], replay_error) != 0) {
            free(rediscovered);
            free(verified);
            return ad_fail(error, "authored BBS record %zu replay failed: %s",
                           i, replay_error);
        }
        if (record->decision_index !=
            (uint32_t)rediscovered->action_count) {
            free(rediscovered);
            free(verified);
            return ad_fail(error,
                           "authored BBS record %zu decision index differs",
                           i);
        }
        if (!bb_state_bank_boundary_valid(&verified[i])) {
            free(rediscovered);
            free(verified);
            return ad_fail(error,
                           "authored BBS record %zu is not a safe BBS1 boundary",
                           i);
        }
        char continuation_error[AD_ERROR_CAP];
        if (ad_verify_one_action_continuation(
                &verified[i], NULL, NULL, NULL, continuation_error) != 0) {
            free(rediscovered);
            free(verified);
            return ad_fail(error,
                           "authored BBS record %zu cannot continue: %s",
                           i, continuation_error);
        }
    }
    free(rediscovered);
    if (ad_write_bytes(file, "BBS1", 4) != 0 || ad_write_u32(file, 1) != 0 ||
        ad_write_u32(file, (uint32_t)sizeof(bb_match)) != 0 ||
        ad_write_u32(file, ad_bbs_fingerprint()) != 0) {
        free(verified);
        return ad_fail(error, "failed to write BBS header");
    }
    for (size_t i = 0; i < count; i++) {
        const ad_bbs_record* record = &records[i];
        const bb_match* match = &verified[i];
        uint8_t meta[4] = {match->half, match->turn[match->active_team], 0, 0};
        if (ad_write_u32(file, record->source_id) != 0 ||
            ad_write_u32(file, record->decision_index) != 0 ||
            ad_write_bytes(file, meta, sizeof meta) != 0 ||
            ad_write_bytes(file, match, sizeof *match) != 0) {
            free(verified);
            return ad_fail(error, "failed to write BBS record %zu", i);
        }
    }
    free(verified);
    if (fflush(file) != 0 || ferror(file)) return ad_fail(error, "failed to flush BBS stream");
    if (error != NULL) error[0] = '\0';
    return 0;
}
