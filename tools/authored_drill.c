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

static int ad_action_is_legal(const bb_match* match, uint32_t packed) {
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(match, legal);
    for (int i = 0; i < n; i++) {
        if (bb_action_pack(legal[i]) == packed) return 1;
    }
    return 0;
}

static int ad_recipe_config_valid(const ad_recipe* recipe) {
    return recipe->home_team >= -1 && recipe->home_team < BB_TEAM_COUNT &&
           recipe->away_team >= -1 && recipe->away_team < BB_TEAM_COUNT &&
           recipe->exclude_team >= -1 && recipe->exclude_team < BB_TEAM_COUNT &&
           recipe->procgen.skillup_max_players >= 0 &&
           recipe->procgen.skillup_max_players <= BB_TEAM_SLOTS &&
           recipe->procgen.skillup_max_each >= 0 &&
           recipe->procgen.skillup_max_each <= 12 &&
           recipe->procgen.skillup_secondary_pct >= 0.0f &&
           recipe->procgen.skillup_secondary_pct <= 1.0f;
}

int ad_discover_first_team_turn(ad_recipe* recipe, char error[AD_ERROR_CAP]) {
    if (recipe == NULL) return ad_fail(error, "null recipe");
    if (!ad_recipe_config_valid(recipe)) return ad_fail(error, "invalid recipe configuration");
    recipe->action_count = 0;
    recipe->dice_count = 0;

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
    bb_status status = bb_advance(&match, &game_rng);

    while (status == BB_STATUS_DECISION && recipe->action_count < AD_MAX_ACTIONS) {
        if (sink.overflow) return ad_fail(error, "dice transcript exceeds %d", AD_MAX_DICE);
        if (ad_has_team_turn(&match)) {
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
        int picked = ad_pick_pre_turn(&match, legal, n);
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
    return ad_fail(error, "match ended with status %d before a team turn", status);
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

    // Exact-replay and validate the complete batch before emitting even the
    // header. This binds serialized bytes to transcripts and keeps malformed
    // later records from leaving a plausible prefix.
    for (size_t i = 0; i < count; i++) {
        const ad_bbs_record* record = &records[i];
        if ((record->source_id & 0xF0000000u) != 0xA0000000u ||
            record->recipe == NULL) {
            free(verified);
            return ad_fail(error, "invalid authored BBS record %zu", i);
        }
        char replay_error[AD_ERROR_CAP];
        if (ad_replay_exact(record->recipe, &verified[i], replay_error) != 0) {
            free(verified);
            return ad_fail(error, "authored BBS record %zu replay failed: %s",
                           i, replay_error);
        }
        if (!bb_state_bank_boundary_valid(&verified[i])) {
            free(verified);
            return ad_fail(error, "authored BBS record %zu is not a safe BBS1 boundary", i);
        }
    }
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
