#define _POSIX_C_SOURCE 200809L

#include "authored_drill.h"
#include "bb/bb_reachability.h"
#include "bb/gen_skills.h"
#include "bb/gen_teams.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

_Static_assert(BB_HOME == 0 && BB_AWAY == 1,
               "team-side mapping differs");
_Static_assert(BB_WEATHER_SWELTERING == 0 && BB_WEATHER_SUNNY == 1 &&
                   BB_WEATHER_PERFECT == 2 && BB_WEATHER_RAIN == 3 &&
                   BB_WEATHER_BLIZZARD == 4,
               "weather mapping differs");
_Static_assert(BB_BALL_OFF_PITCH == 0 && BB_BALL_ON_GROUND == 1 &&
                   BB_BALL_HELD == 2 && BB_BALL_IN_AIR == 3,
               "ball-state mapping differs");
_Static_assert(BB_PROC_NONE == 0 && BB_PROC_MATCH == 1 &&
                   BB_PROC_PREGAME == 2 && BB_PROC_SETUP == 3 &&
                   BB_PROC_KICKOFF == 4 && BB_PROC_TEAM_TURN == 5 &&
                   BB_PROC_ACTIVATION == 6 && BB_PROC_MOVE == 7 &&
                   BB_PROC_DODGE == 8 && BB_PROC_RUSH == 9 &&
                   BB_PROC_PICKUP == 10 && BB_PROC_BLOCK == 11 &&
                   BB_PROC_PUSH == 12 && BB_PROC_KNOCKDOWN == 13 &&
                   BB_PROC_ARMOUR == 14 && BB_PROC_INJURY == 15 &&
                   BB_PROC_CASUALTY == 16 && BB_PROC_PASS == 17 &&
                   BB_PROC_CATCH == 18 && BB_PROC_SCATTER == 19 &&
                   BB_PROC_THROW_IN == 20 && BB_PROC_HANDOFF == 21 &&
                   BB_PROC_FOUL == 22 && BB_PROC_TTM == 23 &&
                   BB_PROC_TEST == 24 && BB_PROC_TOUCHDOWN == 25 &&
                   BB_PROC_TURNOVER == 26 && BB_PROC_END_DRIVE == 27 &&
                   BB_PROC_KO_RECOVERY == 28 && BB_PROC_COUNT == 29,
               "procedure mapping differs");
_Static_assert(AD_RECIPE_FIRST_TEAM_TURN == 0 &&
                   AD_RECIPE_F3_LATE_SECOND_HALF == 1 &&
                   AD_RECIPE_F1_PASS_OPPORTUNITY == 2 &&
                   AD_RECIPE_F2_HANDOFF_OPPORTUNITY == 3 &&
                   AD_RECIPE_F5_SCORE_OR_WAIT == 4 &&
                   AD_RECIPE_F4_PENDING_DODGE_REROLL == 5 &&
                   AD_RECIPE_F3_EXACT_SECOND_HALF_TURN == 6 &&
                   AD_RECIPE_F2_EXACT_HANDOFF_TARGET_COUNT == 7 &&
                   AD_RECIPE_F1_EXACT_PASS_CARRIER_PRESSURE == 8 &&
                   AD_RECIPE_KIND_COUNT == 9,
               "recipe-kind mapping differs");
_Static_assert(AD_F2_TARGET_COUNT_NONE == 0 &&
                   AD_F2_TARGET_COUNT_EXACTLY_ONE == 1 &&
                   AD_F2_TARGET_COUNT_TWO_OR_MORE == 2,
               "F2 bucket mapping differs");
_Static_assert(AD_F1_CARRIER_PRESSURE_NONE == 0 &&
                   AD_F1_CARRIER_PRESSURE_OPEN == 1 &&
                   AD_F1_CARRIER_PRESSURE_MARKED == 2,
               "F1 pressure mapping differs");
_Static_assert(BB_RR_TEAM == 0 && BB_RR_SKILL == 1 && BB_RR_PRO == 2 &&
                   BB_RR_LEADER == 3 && BB_RR_SOURCE_COUNT == 4,
               "F4 reroll-source mapping differs");
_Static_assert(BB_A_USE_REROLL == 23 && BB_A_DECLINE_REROLL == 24,
               "F4 action mapping differs");

static void fail(const char* message) {
    fprintf(stderr, "sidecar fact probe: %s\n", message);
    exit(1);
}

static void require(int condition, const char* message) {
    if (!condition) fail(message);
}

static void put_bytes(const void* data, size_t size) {
    if (fwrite(data, 1, size, stdout) != size) fail("stdout write failed");
}

static void put_u8(uint8_t value) {
    put_bytes(&value, sizeof value);
}

static void put_u32(uint32_t value) {
    const uint8_t bytes[4] = {
        (uint8_t)value,
        (uint8_t)(value >> 8),
        (uint8_t)(value >> 16),
        (uint8_t)(value >> 24),
    };
    put_bytes(bytes, sizeof bytes);
}

static void put_i32(int value) {
    require(value >= INT32_MIN && value <= INT32_MAX, "int exceeds int32");
    put_u32((uint32_t)(int32_t)value);
}

static void put_u64(uint64_t value) {
    const uint8_t bytes[8] = {
        (uint8_t)value,
        (uint8_t)(value >> 8),
        (uint8_t)(value >> 16),
        (uint8_t)(value >> 24),
        (uint8_t)(value >> 32),
        (uint8_t)(value >> 40),
        (uint8_t)(value >> 48),
        (uint8_t)(value >> 56),
    };
    put_bytes(bytes, sizeof bytes);
}

static int compare_u32(const void* left, const void* right) {
    uint32_t a = *(const uint32_t*)left;
    uint32_t b = *(const uint32_t*)right;
    return a < b ? -1 : a > b;
}

static int find_legal(const bb_match* match, bb_action wanted) {
    bb_action legal[BB_LEGAL_MAX];
    int count = bb_legal_actions(match, legal);
    require(count > 0 && count <= BB_LEGAL_MAX, "invalid legal action count");
    uint32_t packed = bb_action_pack(wanted);
    for (int i = 0; i < count; i++) {
        if (bb_action_pack(legal[i]) == packed) return 1;
    }
    return 0;
}

static int find_type_arg(const bb_match* match, bb_action_type type, int arg,
                         bb_action* found) {
    bb_action legal[BB_LEGAL_MAX];
    int count = bb_legal_actions(match, legal);
    require(count > 0 && count <= BB_LEGAL_MAX, "invalid private legal count");
    for (int i = 0; i < count; i++) {
        if (legal[i].type == type && (arg < 0 || legal[i].arg == arg)) {
            *found = legal[i];
            return 1;
        }
    }
    return 0;
}

static int f5_end_activation_legal(const bb_match* match) {
    if (match->ball.state != BB_BALL_HELD ||
        match->ball.carrier >= BB_NUM_PLAYERS) {
        return 0;
    }
    int carrier = match->ball.carrier;
    bb_action action;
    if (!find_type_arg(match, BB_A_ACTIVATE, carrier, &action)) return 0;
    bb_match probe = *match;
    uint8_t die = 6;
    bb_rng rng;
    bb_rng_script(&rng, &die, 1);
    if (bb_apply(&probe, action, &rng) != BB_STATUS_DECISION ||
        rng.script_pos != 0 || bb_rng_error(&rng) ||
        !find_type_arg(&probe, BB_A_DECLARE, BB_ACT_MOVE, &action)) {
        return 0;
    }
    if (bb_apply(&probe, action, &rng) != BB_STATUS_DECISION ||
        rng.script_pos != 0 || bb_rng_error(&rng)) {
        return 0;
    }
    return find_type_arg(&probe, BB_A_END_ACTIVATION, -1, &action);
}

static uint32_t f4_option_mask(const bb_match* match) {
    const bb_action options[] = {
        {BB_A_DECLINE_REROLL, 0, 0, 0},
        {BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_DODGE, 0},
        {BB_A_USE_REROLL, BB_RR_PRO, 0, 0},
        {BB_A_USE_REROLL, BB_RR_TEAM, 0, 0},
    };
    uint32_t mask = 0;
    for (size_t i = 0; i < sizeof options / sizeof options[0]; i++) {
        if (find_legal(match, options[i])) mask |= UINT32_C(1) << i;
    }
    return mask;
}

static void emit_record(uint32_t index, const ad_recipe* recipe,
                        const ad_bbs_record* record,
                        const ad_authored_identity* identity) {
    const bb_match* match = &recipe->captured;
    const char* template_key = ad_authored_template_key(identity->template_id);
    require(template_key != NULL, "unknown template key");
    size_t key_length = strlen(template_key);
    require(key_length > 0 && key_length < AD_AUTHORED_TEMPLATE_KEY_CAP,
            "template key length invalid");

    require(record->source_id == UINT32_C(0xA9000000) + index,
            "legacy source schedule differs");
    require(record->decision_index == (uint32_t)recipe->action_count,
            "capture decision index differs");
    require(record->recipe == recipe, "record pointer differs");

    bb_action legal[BB_LEGAL_MAX];
    int legal_count = bb_legal_actions(match, legal);
    require(legal_count > 0 && legal_count <= BB_LEGAL_MAX,
            "capture legal count invalid");
    uint32_t packed[BB_LEGAL_MAX];
    for (int i = 0; i < legal_count; i++) packed[i] = bb_action_pack(legal[i]);
    qsort(packed, (size_t)legal_count, sizeof packed[0], compare_u32);
    for (int i = 1; i < legal_count; i++) {
        require(packed[i - 1] != packed[i], "duplicate packed legal action");
    }

    uint32_t locations[2][6] = {{0}};
    for (int slot = 0; slot < BB_NUM_PLAYERS; slot++) {
        uint8_t location = match->players[slot].location;
        require(location <= BB_LOC_ABSENT, "invalid player location");
        locations[BB_TEAM_OF(slot)][location]++;
    }
    for (int team = BB_HOME; team <= BB_AWAY; team++) {
        uint32_t total = 0;
        for (size_t location = 0; location < 6; location++) {
            total += locations[team][location];
        }
        require(total == BB_TEAM_SLOTS, "player location reconciliation failed");
    }

    uint32_t family = 0;
    uint32_t f1_pressure = 0;
    uint32_t f2_targets = 0;
    uint32_t f3_turn = 0;
    uint32_t f3_orientation = 0;
    uint32_t f4_options = 0;
    uint32_t f5_score = 0;
    uint32_t f5_end = 0;
    switch (recipe->kind) {
        case AD_RECIPE_F1_EXACT_PASS_CARRIER_PRESSURE: {
            family = 1;
            require(ad_f1_pass_opportunity_valid(match), "F1 predicate failed");
            require(match->ball.state == BB_BALL_HELD &&
                        match->ball.carrier < BB_NUM_PLAYERS,
                    "F1 carrier invalid");
            f1_pressure = bb_is_marked(match, match->ball.carrier) ? 2u : 1u;
            require(f1_pressure == (uint32_t)recipe->capture_pass_carrier_pressure,
                    "F1 pressure differs");
            break;
        }
        case AD_RECIPE_F2_EXACT_HANDOFF_TARGET_COUNT:
            family = 2;
            f2_targets = (uint32_t)ad_f2_handoff_target_count(match);
            require(f2_targets > 0, "F2 predicate failed");
            require((f2_targets == 1 ? 1u : 2u) ==
                        (uint32_t)recipe->capture_handoff_target_bucket,
                    "F2 target bucket differs");
            break;
        case AD_RECIPE_F3_EXACT_SECOND_HALF_TURN:
            family = 3;
            f3_turn = (uint32_t)recipe->capture_turn;
            f3_orientation = (uint32_t)recipe->capture_active_team + 1u;
            require(match->half == 2 && match->active_team ==
                        (uint8_t)recipe->capture_active_team &&
                        match->turn[match->active_team] == recipe->capture_turn,
                    "F3 capture differs");
            break;
        case AD_RECIPE_F4_PENDING_DODGE_REROLL:
            family = 4;
            require(ad_f4_pending_dodge_reroll_valid(match),
                    "F4 predicate failed");
            f4_options = f4_option_mask(match);
            require(f4_options == (1u | 2u | 8u), "F4 options differ");
            break;
        case AD_RECIPE_F5_SCORE_OR_WAIT:
            family = 5;
            require(match->ball.state == BB_BALL_HELD &&
                        match->ball.carrier < BB_NUM_PLAYERS,
                    "F5 carrier invalid");
            f5_score = bb_can_score_without_dice(match, match->ball.carrier);
            f5_end = (uint32_t)f5_end_activation_legal(match);
            require(f5_score == 1 && f5_end == 1 &&
                        ad_f5_score_or_wait_valid(match),
                    "F5 facts differ");
            break;
        default:
            fail("unsupported proof recipe family");
    }

    put_u32(index);
    put_u32(record->source_id);
    put_u32(record->decision_index);
    put_u64(identity->variant_seed);
    put_u32(identity->identity_schema_version);
    put_u32(identity->source_id);
    put_u32(identity->template_id);
    put_u32(identity->recipe_revision);
    put_u32(identity->cell_id);
    put_u32(identity->variant_id);
    put_u32((uint32_t)key_length);
    put_bytes(template_key, key_length);

    put_u64(recipe->procgen_seed);
    put_u64(recipe->procgen_stream);
    put_u64(recipe->game_seed);
    put_u64(recipe->game_stream);
    put_u64(recipe->controller_seed);
    put_u64(recipe->controller_stream);
    put_i32(recipe->kind);
    put_i32(recipe->capture_turn);
    put_i32(recipe->capture_active_team);
    put_i32(recipe->capture_handoff_target_bucket);
    put_i32(recipe->capture_pass_carrier_pressure);
    put_i32(recipe->home_team);
    put_i32(recipe->away_team);
    put_i32(recipe->exclude_team);
    put_i32(recipe->procgen.skillup_max_players);
    put_i32(recipe->procgen.skillup_max_each);
    uint32_t percentage_bits = 0;
    memcpy(&percentage_bits, &recipe->procgen.skillup_secondary_pct,
           sizeof percentage_bits);
    put_u32(percentage_bits);

    put_bytes(&recipe->initialized, sizeof recipe->initialized);
    put_bytes(&recipe->captured, sizeof recipe->captured);
    require(recipe->action_count >= 0 && recipe->action_count < AD_MAX_ACTIONS,
            "action count invalid");
    put_u32((uint32_t)recipe->action_count);
    for (int i = 0; i < recipe->action_count; i++) {
        put_u32(recipe->actions[i]);
        put_u8(recipe->decision_teams[i]);
    }
    require(recipe->dice_count >= 0 && recipe->dice_count <= AD_MAX_DICE,
            "dice count invalid");
    put_u32((uint32_t)recipe->dice_count);
    for (int i = 0; i < recipe->dice_count; i++) {
        put_u8(recipe->dice_sides[i]);
        put_u8(recipe->dice_values[i]);
    }
    put_u32((uint32_t)legal_count);
    for (int i = 0; i < legal_count; i++) put_u32(packed[i]);

    for (int team = BB_HOME; team <= BB_AWAY; team++) {
        for (size_t location = 0; location < 6; location++) {
            put_u32(locations[team][location]);
        }
    }
    require(match->half == 1 || match->half == 2, "invalid half");
    require(match->active_team <= BB_AWAY && match->decision_team <= BB_AWAY &&
                match->kicking_team <= BB_AWAY,
            "invalid team scalar");
    require(match->weather <= BB_WEATHER_BLIZZARD, "invalid weather");
    require(match->ball.state <= BB_BALL_IN_AIR, "invalid ball state");
    put_u32(match->half);
    put_u32(match->turn[BB_HOME]);
    put_u32(match->turn[BB_AWAY]);
    put_u32(match->active_team);
    put_u32(match->decision_team);
    put_u32(match->score[BB_HOME]);
    put_u32(match->score[BB_AWAY]);
    put_u32(match->kicking_team);
    put_u32(match->weather);
    put_u32(match->rerolls[BB_HOME]);
    put_u32(match->rerolls[BB_AWAY]);
    put_u32(match->ball.state);
    put_i32(match->ball.state == BB_BALL_HELD ? match->ball.carrier : -1);
    put_u32(match->stack_top);
    for (uint32_t i = 0; i < match->stack_top; i++) {
        require(match->stack[i].proc < BB_PROC_COUNT,
                "invalid procedure id");
        put_u32(match->stack[i].proc);
    }
    put_u32(family);
    put_u32(f1_pressure);
    put_u32(f2_targets);
    put_u32(f3_turn);
    put_u32(f3_orientation);
    put_u32(f4_options);
    put_u32(f5_score);
    put_u32(f5_end);
}

int main(void) {
    require(sizeof(uint32_t) == 4 && sizeof(uint64_t) == 8 &&
                sizeof(float) == 4,
            "unsupported scalar ABI");
    require(sizeof(bb_action) == 4, "bb_action ABI differs");
    require(sizeof(bb_match) == 2240, "bb_match ABI differs");
    require(AD_AUTHORED_PROOF_BUNDLE_COUNT == 26, "proof count differs");
    require(BB_TEAM_COUNT == 30, "team catalogue differs");
    require(BB_PROC_COUNT == 29, "procedure catalogue differs");

    ad_recipe* recipes = calloc(AD_AUTHORED_PROOF_BUNDLE_COUNT,
                                sizeof *recipes);
    ad_bbs_record* records = calloc(AD_AUTHORED_PROOF_BUNDLE_COUNT,
                                    sizeof *records);
    ad_authored_identity* identities = calloc(
        AD_AUTHORED_PROOF_BUNDLE_COUNT, sizeof *identities);
    require(recipes != NULL && records != NULL && identities != NULL,
            "allocation failed");
    char error[AD_ERROR_CAP];
    require(ad_build_authored_proof_bundle(
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                records, AD_AUTHORED_PROOF_BUNDLE_COUNT, error) == 0,
            "proof builder failed");
    require(ad_identify_authored_proof_bundle(
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                identities, AD_AUTHORED_PROOF_BUNDLE_COUNT, error) == 0,
            "identity mapper failed");

    char* bbs = NULL;
    size_t bbs_length = 0;
    FILE* stream = open_memstream(&bbs, &bbs_length);
    require(stream != NULL, "open_memstream failed");
    require(ad_bbs_write(stream, records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                         error) == 0,
            "public writer failed");
    require(fflush(stream) == 0, "memory stream flush failed");
    require(fclose(stream) == 0, "memory stream close failed");
    require(bbs != NULL && bbs_length == 58568 && bbs[bbs_length] == '\0',
            "memory stream length or trailing NUL differs");

    put_bytes("ADSFACT1", 8);
    put_u32(1);
    put_u32(AD_AUTHORED_PROOF_BUNDLE_COUNT);
    put_u32((uint32_t)sizeof(bb_match));
    put_u32((uint32_t)sizeof(ad_recipe));
    put_u32((uint32_t)sizeof(ad_bbs_record));
    put_u32((uint32_t)sizeof(ad_authored_identity));
    put_u32(BB_TEAM_COUNT);
    put_u32(BB_SKILL_COUNT);
    put_u32(BB_A_TYPE_COUNT);
    put_u32(BB_PROC_COUNT);
    put_u32(BB_LEGAL_MAX);
    put_u32(AD_MAX_ACTIONS);
    put_u32(AD_MAX_DICE);
    put_u32(AD_ERROR_CAP);
    put_u32((uint32_t)bbs_length);
    put_bytes(bbs, bbs_length);
    for (uint32_t i = 0; i < BB_TEAM_COUNT; i++) {
        const char* team_id = bb_team_defs[i].id;
        require(team_id != NULL, "team ID is null");
        size_t team_id_length = strlen(team_id);
        require(team_id_length > 0 && team_id_length < 64,
                "team ID length invalid");
        put_u32((uint32_t)team_id_length);
        put_bytes(team_id, team_id_length);
    }
    for (uint32_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        emit_record(i, &recipes[i], &records[i], &identities[i]);
    }
    require(fflush(stdout) == 0, "stdout flush failed");
    free(bbs);
    free(identities);
    free(records);
    free(recipes);
    return 0;
}
