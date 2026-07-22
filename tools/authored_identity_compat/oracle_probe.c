#include "authored_drill.h"
#include "bb/gen_skills.h"
#include "bb/gen_teams.h"
#include "bb/bb_skills.h"

#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    FILE* fresh;
    FILE* resumable;
    FILE* continuation;
} gate_outputs;

static void die(const char* message) {
    perror(message);
    exit(1);
}

static void put_bytes(FILE* out, const void* data, size_t size) {
    if (fwrite(data, 1, size, out) != size) die("fwrite");
}

static void put_u8(FILE* out, uint8_t value) {
    put_bytes(out, &value, sizeof value);
}

static void put_u32(FILE* out, uint32_t value) {
    uint8_t data[4] = {
        (uint8_t)value,
        (uint8_t)(value >> 8),
        (uint8_t)(value >> 16),
        (uint8_t)(value >> 24),
    };
    put_bytes(out, data, sizeof data);
}

static void put_case(FILE* out, uint32_t recipe_index,
                     uint32_t byte_index, uint8_t bit_index) {
    put_u32(out, recipe_index);
    put_u32(out, byte_index);
    put_u8(out, bit_index);
}

static size_t error_length(const char error[AD_ERROR_CAP]) {
    size_t length = 0;
    while (length < AD_ERROR_CAP && error[length] != '\0') length++;
    return length;
}

static void record_case(gate_outputs* outputs, const bb_match* match,
                        uint32_t recipe_index, uint32_t byte_index,
                        uint8_t bit_index) {
    bb_match before = *match;
    int fresh = bb_state_bank_boundary_valid(match);
    int fresh_unchanged = memcmp(match, &before, sizeof before) == 0;
    put_case(outputs->fresh, recipe_index, byte_index, bit_index);
    put_u8(outputs->fresh, (uint8_t)(fresh != 0));
    put_u8(outputs->fresh, (uint8_t)fresh_unchanged);

    before = *match;
    int resumable = bb_state_bank_resumable_valid(match);
    int resumable_unchanged = memcmp(match, &before, sizeof before) == 0;
    put_case(outputs->resumable, recipe_index, byte_index, bit_index);
    put_u8(outputs->resumable, (uint8_t)(resumable != 0));
    put_u8(outputs->resumable, (uint8_t)resumable_unchanged);

    before = *match;
    uint32_t packed_action = UINT32_C(0xA5A5A5A5);
    bb_status result_status = (bb_status)INT_MIN;
    int dice_used = INT_MIN;
    char error[AD_ERROR_CAP];
    memset(error, 0xA5, sizeof error);
    int rc = ad_verify_one_action_continuation(
        match, &packed_action, &result_status, &dice_used, error);
    int continuation_unchanged = memcmp(match, &before, sizeof before) == 0;
    size_t length = error_length(error);
    put_case(outputs->continuation, recipe_index, byte_index, bit_index);
    put_u32(outputs->continuation, (uint32_t)rc);
    put_u32(outputs->continuation, packed_action);
    put_u32(outputs->continuation, (uint32_t)result_status);
    put_u32(outputs->continuation, (uint32_t)dice_used);
    put_u8(outputs->continuation, (uint8_t)continuation_unchanged);
    put_u32(outputs->continuation, (uint32_t)length);
    put_bytes(outputs->continuation, error, length);
}

static FILE* open_stream(const char* directory, const char* filename,
                         const char magic[8], uint32_t case_count) {
    char path[4096];
    int length = snprintf(path, sizeof path, "%s/%s", directory, filename);
    if (length < 0 || (size_t)length >= sizeof path) {
        fputs("oracle output path is too long\n", stderr);
        exit(1);
    }
    FILE* out = fopen(path, "wb");
    if (out == NULL) die(path);
    put_bytes(out, magic, 8);
    put_u32(out, 1);
    put_u32(out, AD_AUTHORED_PROOF_BUNDLE_COUNT);
    put_u32(out, (uint32_t)sizeof(bb_match));
    put_u32(out, case_count);
    return out;
}

static void close_stream(FILE* out) {
    if (fclose(out) != 0) die("fclose");
}

static void close_stream_with_count(FILE* out, uint32_t case_count) {
    if (fseek(out, 20, SEEK_SET) != 0) die("fseek");
    put_u32(out, case_count);
    close_stream(out);
}

static void record_curated(gate_outputs* outputs, const bb_match* match,
                           uint32_t recipe_index, uint32_t case_index) {
    record_case(outputs, match, recipe_index, case_index, 0);
}

static uint32_t record_curated_cases(gate_outputs* outputs,
                                     const ad_recipe* recipes) {
    const uint32_t nested_index =
        AD_F1_PASS_CARRIER_PRESSURE_AXIS_COUNT +
        AD_F2_HANDOFF_TARGET_AXIS_COUNT + AD_F3_SECOND_HALF_AXIS_COUNT;
    uint32_t case_index = 0;
    uint32_t curated_recipe_index = 0;

#define CURATED_FROM(base, statement) do {                                   \
        bb_match changed = (base);                                           \
        statement;                                                           \
        record_curated(outputs, &changed, curated_recipe_index, case_index++); \
    } while (0)

    const bb_match* fresh_ptr = &recipes[0].captured;
    const bb_match* nested_ptr = &recipes[nested_index].captured;
    record_curated(outputs, fresh_ptr, 0, case_index++);
    record_curated(outputs, nested_ptr, nested_index, case_index++);

    bb_match fresh = *fresh_ptr;
    CURATED_FROM(fresh, changed.stack_top = 1;
                 changed.stack[1].proc = BB_PROC_NONE);
    CURATED_FROM(fresh, changed.stack_top = 3;
                 changed.stack[2].proc = BB_PROC_ACTIVATION);
    CURATED_FROM(fresh, changed.status = BB_STATUS_RUNNING;
                 changed.decision_team ^= 1u);
    CURATED_FROM(fresh, changed.half = 0;
                 changed.turn[changed.active_team] = 0);
    CURATED_FROM(fresh, changed.half = 4;
                 changed.turn[changed.active_team] = 9);
    CURATED_FROM(fresh, changed.active_team = BB_AWAY + 1;
                 changed.decision_team = BB_AWAY + 1);
    CURATED_FROM(fresh, changed.kicking_team = BB_AWAY + 1;
                 changed.decision_team = BB_AWAY + 1);
    CURATED_FROM(fresh, changed.team_id[0] = BB_TEAM_COUNT;
                 changed.team_id[1] = BB_TEAM_COUNT);
    CURATED_FROM(fresh, changed.weather = BB_WEATHER_BLIZZARD + 1;
                 changed.half = 0);
    CURATED_FROM(fresh, changed.stack[0].proc = BB_PROC_COUNT;
                 changed.stack[0].phase = 0);
    CURATED_FROM(fresh, changed.stack[0].phase = 2;
                 changed.stack[0].a = 1);
    CURATED_FROM(fresh, changed.stack[0].b = 1;
                 changed.stack[0].x = 1;
                 changed.stack[0].y = 1);
    CURATED_FROM(fresh, changed.stack[0].data = UINT16_MAX;
                 changed.turnover = 1);
    CURATED_FROM(fresh, changed.stack[1].proc = BB_PROC_ACTIVATION;
                 changed.stack[1].phase = 0);
    CURATED_FROM(fresh, changed.stack[1].a ^= 1u;
                 changed.decision_team ^= 1u);
    CURATED_FROM(fresh, changed.stack[1].b = 1;
                 changed.stack[1].data = 1);
    CURATED_FROM(fresh, changed.stack[1].x = 1;
                 changed.stack[1].y = 1);
    CURATED_FROM(fresh, changed.players[0].position_id = BB_MAX_POSITIONS;
                 changed.players[0].location = BB_LOC_ABSENT + 1);
    CURATED_FROM(fresh, changed.players[0].stance = BB_STANCE_STUNNED_USED + 1;
                 changed.players[0].flags |= UINT16_C(0x8000));
    CURATED_FROM(fresh, changed.players[0].location = BB_LOC_ON_PITCH;
                 changed.players[0].x = BB_PITCH_LEN;
                 changed.players[0].y = BB_PITCH_WID);
    CURATED_FROM(fresh, changed.players[0].skills.w[BB_SKILL_COUNT >> 6] |=
                    UINT64_C(1) << (BB_SKILL_COUNT & 63);
                 changed.players[0].position_id = BB_MAX_POSITIONS);
    CURATED_FROM(fresh, changed.grid[0][0] = BB_NUM_PLAYERS + 1;
                 changed.grid[1][1] = BB_NUM_PLAYERS + 1);
    CURATED_FROM(fresh, changed.grid[changed.players[0].x]
                                      [changed.players[0].y] = 0;
                 changed.players[0].x ^= 1u);
    CURATED_FROM(fresh, changed.ball.state = BB_BALL_HELD;
                 changed.ball.carrier = BB_NUM_PLAYERS;
                 changed.ball.x = BB_PITCH_LEN);
    CURATED_FROM(fresh, changed.ball.state = BB_BALL_ON_GROUND;
                 changed.ball.carrier = 0;
                 changed.ball.x = BB_PITCH_LEN;
                 changed.ball.y = BB_PITCH_WID);
    CURATED_FROM(fresh, changed.ball.state = BB_BALL_IN_AIR;
                 changed.ball.carrier = BB_NO_PLAYER);
    CURATED_FROM(fresh, changed.players[0].flags |= BB_PF_HAS_BALL;
                 changed.players[1].flags |= BB_PF_HAS_BALL;
                 changed.ball.state = BB_BALL_HELD;
                 changed.ball.carrier = 0);
    CURATED_FROM(fresh, changed.step_count = UINT32_MAX;
                 changed.turnover = 1);

    bb_match nested = *nested_ptr;
    curated_recipe_index = nested_index;
    CURATED_FROM(nested, changed.stack_top = 4; changed.ret = 1);
    CURATED_FROM(nested, changed.stack_top = 6;
                 changed.stack[5].proc = BB_PROC_TEST);
    CURATED_FROM(nested, changed.stack[2].proc = BB_PROC_MOVE;
                 changed.stack[2].phase = 0);
    CURATED_FROM(nested, changed.stack[2].a ^= 1u;
                 changed.stack[2].b = BB_ACT_BLITZ);
    CURATED_FROM(nested, changed.stack[2].x = 1;
                 changed.stack[2].y = 1;
                 changed.stack[2].data = 1);
    CURATED_FROM(nested, changed.stack[3].proc = BB_PROC_TEST;
                 changed.stack[3].phase = 1);
    CURATED_FROM(nested, changed.stack[3].a ^= 1u;
                 changed.stack[3].b = BB_ACT_BLITZ);
    CURATED_FROM(nested, changed.stack[3].x = BB_PITCH_LEN;
                 changed.stack[3].y = BB_PITCH_WID;
                 changed.stack[3].data = 0);
    CURATED_FROM(nested, changed.stack[4].proc = BB_PROC_MOVE;
                 changed.stack[4].phase = 0);
    CURATED_FROM(nested, changed.stack[4].a ^= 1u;
                 changed.stack[4].b = BB_TEST_RUSH);
    CURATED_FROM(nested, changed.stack[4].x = 2;
                 changed.stack[4].y = 1);
    CURATED_FROM(nested, changed.stack[4].data &=
                    (uint16_t)~(UINT16_C(1) << 2);
                 changed.stack[4].data |= UINT16_C(1) << 1);
    CURATED_FROM(nested, changed.stack[4].data =
                    (uint16_t)((changed.stack[4].data & UINT16_C(0x0FFF)) |
                               (UINT16_C(3) << 12));
                 changed.stack[4].x = 3);
    CURATED_FROM(nested, changed.stack[4].data =
                    (uint16_t)((changed.stack[4].data & UINT16_C(0x0FFF)) |
                               (UINT16_C(6) << 12)));

    const uint8_t mover = nested.stack[2].a;
    CURATED_FROM(nested, changed.players[mover].flags &=
                    (uint16_t)~BB_PF_ACTIVATING;
                 changed.players[mover].flags |= BB_PF_USED);
    CURATED_FROM(nested, changed.players[mover].flags |=
                    BB_PF_ROOTED | BB_PF_DISTRACTED | BB_PF_EYE_GOUGED);
    CURATED_FROM(nested, changed.players[mover].moved = 1;
                 changed.players[mover].rushes = 1);
    CURATED_FROM(nested, changed.players[mover].ma = 0;
                 changed.players[mover].moved = 0);
    CURATED_FROM(nested, changed.players[mover].ma = -1;
                 changed.players[mover].rushes = 1);
    CURATED_FROM(nested, changed.rerolls[BB_TEAM_OF(mover)] = 0;
                 bb_clear_skill(&changed.players[mover].skills, BB_SK_DODGE));
    CURATED_FROM(nested, changed.ball.state = BB_BALL_HELD;
                 changed.ball.carrier = mover;
                 changed.ball.x = changed.players[mover].x;
                 changed.ball.y = changed.players[mover].y;
                 changed.players[mover].flags |= BB_PF_HAS_BALL);
    CURATED_FROM(nested, changed.ball.state = BB_BALL_ON_GROUND;
                 changed.ball.carrier = BB_NO_PLAYER;
                 changed.ball.x = changed.stack[3].x;
                 changed.ball.y = changed.stack[3].y);
    CURATED_FROM(nested, changed.grid[changed.stack[3].x]
                                       [changed.stack[3].y] = mover + 1;
                 changed.players[mover].x = changed.stack[3].x;
                 changed.players[mover].y = changed.stack[3].y);
    CURATED_FROM(nested, changed.stack[3].x = changed.players[mover].x;
                 changed.stack[3].y = changed.players[mover].y);
    CURATED_FROM(nested, changed.stack[3].x = BB_PITCH_LEN;
                 changed.stack[4].x = 2);
    CURATED_FROM(nested, changed.stack[4].a = BB_NUM_PLAYERS;
                 changed.stack[2].a = BB_NUM_PLAYERS);
    CURATED_FROM(nested, changed.decision_team ^= 1u;
                 changed.stack[1].a ^= 1u);
    CURATED_FROM(nested, changed.status = BB_STATUS_ERROR;
                 changed.step_count = UINT32_MAX);
    CURATED_FROM(nested, changed.players[mover].skills.w[BB_SKILL_COUNT >> 6] |=
                    UINT64_C(1) << (BB_SKILL_COUNT & 63);
                 changed.players[mover].flags |= UINT16_C(0x8000));

#undef CURATED_FROM
    return case_index;
}

int main(int argc, char** argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s OUTPUT_DIRECTORY\n", argv[0]);
        return 2;
    }
    const size_t recipe_count = AD_AUTHORED_PROOF_BUNDLE_COUNT;
    if (sizeof(bb_match) > UINT32_MAX ||
        recipe_count > UINT32_MAX ||
        sizeof(bb_match) >
            (UINT32_MAX / 8u - 1u) / AD_AUTHORED_PROOF_BUNDLE_COUNT) {
        fputs("gate corpus size exceeds canonical encoding\n", stderr);
        return 1;
    }
    uint32_t case_count = (uint32_t)recipe_count *
        (1u + (uint32_t)sizeof(bb_match) * 8u);
    gate_outputs outputs = {
        open_stream(argv[1], "fresh.bin", "ADGFR001", case_count),
        open_stream(argv[1], "resumable.bin", "ADGRS001", case_count),
        open_stream(argv[1], "continuation.bin", "ADGCO001", case_count),
    };
    gate_outputs curated_outputs = {
        open_stream(argv[1], "curated_fresh.bin", "ADCFR001", 0),
        open_stream(argv[1], "curated_resumable.bin", "ADCRS001", 0),
        open_stream(argv[1], "curated_continuation.bin", "ADCCO001", 0),
    };

    ad_recipe* recipes = calloc(recipe_count, sizeof(*recipes));
    ad_bbs_record* records = calloc(recipe_count, sizeof(*records));
    if (recipes == NULL || records == NULL) die("calloc");
    char error[AD_ERROR_CAP];
    if (ad_build_authored_proof_bundle(
            recipes, recipe_count, records, recipe_count, error) != 0) {
        fprintf(stderr, "builder failed: %s\n", error);
        return 1;
    }

    for (uint32_t recipe_index = 0;
         recipe_index < (uint32_t)recipe_count; recipe_index++) {
        const bb_match* canonical = &recipes[recipe_index].captured;
        record_case(&outputs, canonical, recipe_index, UINT32_MAX, UINT8_MAX);
        for (uint32_t byte_index = 0;
             byte_index < (uint32_t)sizeof(*canonical); byte_index++) {
            for (uint8_t bit_index = 0; bit_index < 8; bit_index++) {
                bb_match mutated = *canonical;
                ((uint8_t*)&mutated)[byte_index] ^=
                    (uint8_t)(UINT8_C(1) << bit_index);
                record_case(&outputs, &mutated, recipe_index,
                            byte_index, bit_index);
            }
        }
    }
    uint32_t curated_count = record_curated_cases(&curated_outputs, recipes);

    free(records);
    free(recipes);
    close_stream(outputs.fresh);
    close_stream(outputs.resumable);
    close_stream(outputs.continuation);
    close_stream_with_count(curated_outputs.fresh, curated_count);
    close_stream_with_count(curated_outputs.resumable, curated_count);
    close_stream_with_count(curated_outputs.continuation, curated_count);
    return 0;
}
