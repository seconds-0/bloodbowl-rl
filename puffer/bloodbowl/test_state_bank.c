#define BB_TEST_MAIN
#include "bb_test.h"
#include "bloodbowl.h"
#include "bb_fixtures.h"
#include "authored_drill.h"

#include <unistd.h>

static void write_le32(FILE* file, uint32_t value) {
    uint8_t bytes[4] = {
        (uint8_t)value,
        (uint8_t)(value >> 8),
        (uint8_t)(value >> 16),
        (uint8_t)(value >> 24),
    };
    BB_CHECK_EQ(fwrite(bytes, 1, sizeof bytes, file), sizeof bytes);
}

static void write_state_bank(const char* path, const bb_match* match) {
    FILE* file = fopen(path, "wb");
    BB_CHECK(file != NULL);
    if (file == NULL) return;

    BB_CHECK_EQ(fwrite("BBS1", 1, 4, file), 4);
    write_le32(file, 1u);
    write_le32(file, (uint32_t)sizeof(bb_match));
    write_le32(file, bbe_state_fingerprint());
    uint8_t metadata[BBE_STATE_BANK_REC_META] = {0};
    BB_CHECK_EQ(fwrite(metadata, 1, sizeof metadata, file), sizeof metadata);
    BB_CHECK_EQ(fwrite(match, sizeof *match, 1, file), 1);
    BB_CHECK_EQ(fclose(file), 0);
}

static void reset_state_bank_loader(const char* path) {
    free(bbe_state_bank);
    bbe_state_bank = NULL;
    bbe_state_bank_n = 0;
    bbe_state_bank_tried = 0;
    bbe_state_bank_path = path;
}

static bb_match valid_bank_match(void) {
    bb_match match;
    fx_match_midturn(&match, BB_HOME, 2);
    fx_lineman(&match, BB_HOME, 0, 8, 7);
    fx_lineman(&match, BB_AWAY, 0, 17, 7);
    bb_rng rng;
    bb_rng_seed(&rng, 0xB4A6u, 3);
    BB_CHECK_EQ(fx_run(&match, &rng), BB_STATUS_DECISION);
    return match;
}

static int load_one(const char* path, const bb_match* match) {
    write_state_bank(path, match);
    reset_state_bank_loader(path);
    bbe_state_bank_load();
    return bbe_state_bank_n;
}

BB_TEST(state_bank_accepts_exact_replayed_authored_record) {
    ad_recipe recipe;
    memset(&recipe, 0, sizeof recipe);
    recipe.procgen_seed = 0xA1170EEDu;
    recipe.procgen_stream = 17;
    recipe.game_seed = 0xD11CE5u;
    recipe.game_stream = 23;
    recipe.home_team = 0;
    recipe.away_team = 1;
    recipe.exclude_team = -1;
    recipe.procgen = bb_procgen_params_default();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_first_team_turn(&recipe, error), 0);
    bb_match replayed;
    BB_CHECK_EQ(ad_replay_exact(&recipe, &replayed, error), 0);

    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-authored-bank-%ld.bbs",
             (long)getpid());
    FILE* file = fopen(path, "wb");
    BB_CHECK(file != NULL);
    if (file == NULL) return;
    ad_bbs_record record = {0xA0000001u, (uint32_t)recipe.action_count, replayed};
    BB_CHECK_EQ(ad_bbs_write(file, &record, 1, error), 0);
    BB_CHECK_EQ(fclose(file), 0);

    reset_state_bank_loader(path);
    bbe_state_bank_load();
    BB_CHECK_EQ(bbe_state_bank_n, 1);
    if (bbe_state_bank_n == 1) {
        BB_CHECK_EQ(memcmp(&bbe_state_bank[0], &replayed, sizeof replayed), 0);
    }
    reset_state_bank_loader(BBE_STATE_BANK_PATH);
    BB_CHECK_EQ(remove(path), 0);
}

BB_TEST(state_bank_rejects_unsafe_record_content) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-state-bank-%ld.bbs",
             (long)getpid());

    bb_match valid = valid_bank_match();
    BB_CHECK_EQ(load_one(path, &valid), 1);

    bb_match bad_stack = valid;
    bad_stack.stack_top = BB_STACK_MAX + 1;
    BB_CHECK_EQ(load_one(path, &bad_stack), 0);

    bb_match bad_player_coord = valid;
    bad_player_coord.players[0].x = BB_PITCH_LEN;
    BB_CHECK_EQ(load_one(path, &bad_player_coord), 0);

    bb_match bad_player_enum = valid;
    bad_player_enum.players[0].location = BB_LOC_ABSENT + 1;
    BB_CHECK_EQ(load_one(path, &bad_player_enum), 0);

    bb_match bad_grid = valid;
    bad_grid.grid[8][7] = BB_NUM_PLAYERS + 1;
    BB_CHECK_EQ(load_one(path, &bad_grid), 0);

    bb_match bad_ball = valid;
    bad_ball.ball.state = BB_BALL_HELD;
    bad_ball.ball.carrier = BB_NUM_PLAYERS;
    BB_CHECK_EQ(load_one(path, &bad_ball), 0);

    bb_match bad_ground_ball = valid;
    bad_ground_ball.ball.state = BB_BALL_ON_GROUND;
    bad_ground_ball.ball.x = BB_PITCH_LEN;
    BB_CHECK_EQ(load_one(path, &bad_ground_ball), 0);

    bb_match bad_proc = valid;
    bad_proc.stack[0].proc = BB_PROC_COUNT;
    BB_CHECK_EQ(load_one(path, &bad_proc), 0);

    bb_match bad_team_selector = valid;
    bad_team_selector.active_team = BB_AWAY + 1;
    BB_CHECK_EQ(load_one(path, &bad_team_selector), 0);

    bad_team_selector = valid;
    bad_team_selector.kicking_team = BB_AWAY + 1;
    BB_CHECK_EQ(load_one(path, &bad_team_selector), 0);

    bad_team_selector = valid;
    bad_team_selector.decision_team = BB_AWAY + 1;
    BB_CHECK_EQ(load_one(path, &bad_team_selector), 0);

    bb_match bad_weather = valid;
    bad_weather.weather = BB_WEATHER_BLIZZARD + 1;
    BB_CHECK_EQ(load_one(path, &bad_weather), 0);

    reset_state_bank_loader(BBE_STATE_BANK_PATH);
    BB_CHECK_EQ(remove(path), 0);
}
