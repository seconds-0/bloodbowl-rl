#include "authored_drill.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    FILE* config;
    FILE* actions;
    FILE* dice;
    FILE* unused;
    FILE* initialized;
    FILE* captured;
} recipe_outputs;

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

static void put_u16(FILE* out, uint16_t value) {
    uint8_t data[2] = {(uint8_t)value, (uint8_t)(value >> 8)};
    put_bytes(out, data, sizeof data);
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

static void put_u64(FILE* out, uint64_t value) {
    uint8_t data[8];
    for (int i = 0; i < 8; i++) data[i] = (uint8_t)(value >> (i * 8));
    put_bytes(out, data, sizeof data);
}

static FILE* open_stream(const char* directory, const char* filename,
                         const char magic[8]) {
    char path[4096];
    int length = snprintf(path, sizeof path, "%s/%s", directory, filename);
    if (length < 0 || (size_t)length >= sizeof path) {
        fputs("oracle output path is too long\n", stderr);
        exit(1);
    }
    FILE* out = fopen(path, "wb");
    if (out == NULL) die(path);
    put_bytes(out, magic, 8);
    put_u32(out, AD_AUTHORED_PROOF_BUNDLE_COUNT);
    return out;
}

static void close_stream(FILE* out) {
    if (fclose(out) != 0) die("fclose");
}

static uint32_t float_bits(float value) {
    uint32_t bits;
    _Static_assert(sizeof bits == sizeof value, "float width changed");
    memcpy(&bits, &value, sizeof bits);
    return bits;
}

static size_t put_match(FILE* out, const bb_match* match) {
    size_t bytes = 0;
#define U8(value) do { put_u8(out, (uint8_t)(value)); bytes += 1; } while (0)
#define U16(value) do { put_u16(out, (uint16_t)(value)); bytes += 2; } while (0)
#define U32(value) do { put_u32(out, (uint32_t)(value)); bytes += 4; } while (0)
#define U64(value) do { put_u64(out, (uint64_t)(value)); bytes += 8; } while (0)
    for (int slot = 0; slot < BB_NUM_PLAYERS; slot++) {
        const bb_player* player = &match->players[slot];
        for (int word = 0; word < BB_SKILL_WORDS; word++) {
            U64(player->skills.w[word]);
        }
        U8(player->ma);
        U8(player->st);
        U8(player->ag);
        U8(player->pa);
        U8(player->av);
        U8(player->x);
        U8(player->y);
        U8(player->location);
        U8(player->stance);
        U16(player->flags);
        U8(player->moved);
        U8(player->rushes);
        U8(player->position_id);
        U8(player->star_id);
        U8(player->niggling);
        U8(player->spp_game);
        U16(player->skill_rr_used);
        U8(player->p_loner);
        U8(player->p_bloodlust);
    }
    for (int x = 0; x < BB_PITCH_LEN; x++) {
        for (int y = 0; y < BB_PITCH_WID; y++) U8(match->grid[x][y]);
    }
    U8(match->ball.state);
    U8(match->ball.x);
    U8(match->ball.y);
    U8(match->ball.carrier);
    U8(match->half);
    for (int team = 0; team < 2; team++) U8(match->turn[team]);
    for (int team = 0; team < 2; team++) U8(match->score[team]);
    U8(match->active_team);
    U8(match->kicking_team);
    U8(match->weather);
    for (int team = 0; team < 2; team++) U8(match->rerolls[team]);
    for (int team = 0; team < 2; team++) U8(match->rerolls_start[team]);
    for (int team = 0; team < 2; team++) U8(match->bonus_rerolls[team]);
    U8(match->blitz_used);
    U8(match->pass_used);
    U8(match->handoff_used);
    U8(match->foul_used);
    U8(match->ttm_used);
    U8(match->ktm_used);
    U8(match->secure_used);
    for (int team = 0; team < 2; team++) U8(match->bribes[team]);
    for (int team = 0; team < 2; team++) U8(match->fan_factor[team]);
    for (int team = 0; team < 2; team++) U8(match->cheer_assist[team]);
    for (int team = 0; team < 2; team++) U8(match->surfs[team]);
    for (int team = 0; team < 2; team++) U8(match->apothecary[team]);
    for (int team = 0; team < 2; team++) U8(match->coach_ejected[team]);
    for (int frame_index = 0; frame_index < BB_STACK_MAX; frame_index++) {
        const bb_frame* frame = &match->stack[frame_index];
        U8(frame->proc);
        U8(frame->phase);
        U8(frame->a);
        U8(frame->b);
        U8(frame->x);
        U8(frame->y);
        U16(frame->data);
    }
    U8(match->stack_top);
    U8(match->status);
    U8(match->decision_team);
    U8(match->turnover);
    U16(match->ret);
    U32(match->step_count);
    for (int team = 0; team < 2; team++) U8(match->team_id[team]);
    for (int team = 0; team < 2; team++) U8(match->turns_completed[team]);
    for (int team = 0; team < 2; team++) {
        U8(match->turns_completed_held[team]);
    }
    for (int team = 0; team < 2; team++) U8(match->turnovers_completed[team]);
#undef U64
#undef U32
#undef U16
#undef U8
    return bytes;
}

static void put_config(FILE* out, uint32_t index, const ad_recipe* recipe) {
    put_u32(out, index);
    put_u64(out, recipe->procgen_seed);
    put_u64(out, recipe->procgen_stream);
    put_u64(out, recipe->game_seed);
    put_u64(out, recipe->game_stream);
    put_u64(out, recipe->controller_seed);
    put_u64(out, recipe->controller_stream);
    put_u32(out, (uint32_t)recipe->kind);
    put_u32(out, (uint32_t)recipe->capture_turn);
    put_u32(out, (uint32_t)recipe->capture_active_team);
    put_u32(out, (uint32_t)recipe->capture_handoff_target_bucket);
    put_u32(out, (uint32_t)recipe->capture_pass_carrier_pressure);
    put_u32(out, (uint32_t)recipe->home_team);
    put_u32(out, (uint32_t)recipe->away_team);
    put_u32(out, (uint32_t)recipe->exclude_team);
    put_u32(out, (uint32_t)recipe->procgen.skillup_max_players);
    put_u32(out, (uint32_t)recipe->procgen.skillup_max_each);
    put_u32(out, float_bits(recipe->procgen.skillup_secondary_pct));
}

static void put_recipe(recipe_outputs* outputs, uint32_t index,
                       const ad_recipe* recipe) {
    put_config(outputs->config, index, recipe);

    put_u32(outputs->actions, index);
    put_u32(outputs->actions, (uint32_t)recipe->action_count);
    for (int i = 0; i < recipe->action_count; i++) {
        put_u32(outputs->actions, recipe->actions[i]);
        put_u8(outputs->actions, recipe->decision_teams[i]);
    }

    put_u32(outputs->dice, index);
    put_u32(outputs->dice, (uint32_t)recipe->dice_count);
    for (int i = 0; i < recipe->dice_count; i++) {
        put_u8(outputs->dice, recipe->dice_sides[i]);
        put_u8(outputs->dice, recipe->dice_values[i]);
    }

    put_u32(outputs->unused, index);
    put_u32(outputs->unused, (uint32_t)(AD_MAX_ACTIONS - recipe->action_count));
    for (int i = recipe->action_count; i < AD_MAX_ACTIONS; i++) {
        put_u32(outputs->unused, recipe->actions[i]);
        put_u8(outputs->unused, recipe->decision_teams[i]);
    }
    put_u32(outputs->unused, (uint32_t)(AD_MAX_DICE - recipe->dice_count));
    for (int i = recipe->dice_count; i < AD_MAX_DICE; i++) {
        put_u8(outputs->unused, recipe->dice_sides[i]);
        put_u8(outputs->unused, recipe->dice_values[i]);
    }

    put_u32(outputs->initialized, index);
    if (put_match(outputs->initialized, &recipe->initialized) != 2141) {
        fputs("initialized semantic match width changed\n", stderr);
        exit(1);
    }
    put_u32(outputs->captured, index);
    if (put_match(outputs->captured, &recipe->captured) != 2141) {
        fputs("captured semantic match width changed\n", stderr);
        exit(1);
    }
}

int main(int argc, char** argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s OUTPUT_DIRECTORY\n", argv[0]);
        return 2;
    }
    recipe_outputs outputs = {
        open_stream(argv[1], "config.bin", "ADCFG001"),
        open_stream(argv[1], "actions.bin", "ADACT001"),
        open_stream(argv[1], "dice.bin", "ADDIE001"),
        open_stream(argv[1], "unused.bin", "ADUNU001"),
        open_stream(argv[1], "initialized.bin", "ADINI001"),
        open_stream(argv[1], "captured.bin", "ADCAP001"),
    };
    ad_recipe* recipes = calloc(AD_AUTHORED_PROOF_BUNDLE_COUNT,
                                sizeof *recipes);
    ad_bbs_record* records = calloc(AD_AUTHORED_PROOF_BUNDLE_COUNT,
                                    sizeof *records);
    if (recipes == NULL || records == NULL) die("calloc");
    char error[AD_ERROR_CAP];
    if (ad_build_authored_proof_bundle(
            recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
            records, AD_AUTHORED_PROOF_BUNDLE_COUNT, error) != 0) {
        fprintf(stderr, "builder failed: %s\n", error);
        return 1;
    }
    for (uint32_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        put_recipe(&outputs, i, &recipes[i]);
    }
    free(records);
    free(recipes);
    close_stream(outputs.config);
    close_stream(outputs.actions);
    close_stream(outputs.dice);
    close_stream(outputs.unused);
    close_stream(outputs.initialized);
    close_stream(outputs.captured);
    return 0;
}
