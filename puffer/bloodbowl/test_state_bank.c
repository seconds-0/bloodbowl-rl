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

static void write_state_bank_meta(const char* path, const bb_match* match,
                                  uint32_t source_id, uint8_t half,
                                  uint8_t turn, uint8_t pad0) {
    FILE* file = fopen(path, "wb");
    BB_CHECK(file != NULL);
    if (file == NULL) return;

    BB_CHECK_EQ(fwrite("BBS1", 1, 4, file), 4);
    write_le32(file, 1u);
    write_le32(file, (uint32_t)sizeof(bb_match));
    write_le32(file, bbe_state_fingerprint());
    uint8_t metadata[BBE_STATE_BANK_REC_META] = {0};
    metadata[0] = (uint8_t)source_id;
    metadata[1] = (uint8_t)(source_id >> 8);
    metadata[2] = (uint8_t)(source_id >> 16);
    metadata[3] = (uint8_t)(source_id >> 24);
    metadata[8] = half;
    metadata[9] = turn;
    metadata[10] = pad0;
    BB_CHECK_EQ(fwrite(metadata, 1, sizeof metadata, file), sizeof metadata);
    BB_CHECK_EQ(fwrite(match, sizeof *match, 1, file), 1);
    BB_CHECK_EQ(fclose(file), 0);
}

static void write_state_bank(const char* path, const bb_match* match) {
    uint8_t turn = match->active_team <= BB_AWAY
        ? match->turn[match->active_team] : 1;
    write_state_bank_meta(path, match, 1u, match->half,
                          turn, 0);
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

static bb_match pending_dodge_reroll_match(void) {
    bb_match match;
    fx_match_midturn(&match, BB_HOME, 2);
    int mover = fx_lineman(&match, BB_HOME, 0, 10, 7);
    fx_lineman(&match, BB_AWAY, 0, 10, 8);
    uint8_t die = 2;
    bb_rng rng;
    bb_rng_script(&rng, &die, 1);
    BB_CHECK_EQ(fx_run(&match, &rng), BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_apply(&match,
                        (bb_action){BB_A_ACTIVATE, mover, 0, 0}, &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_apply(&match,
                        (bb_action){BB_A_DECLARE, BB_ACT_MOVE, 0, 0}, &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_apply(&match, (bb_action){BB_A_STEP, 0, 10, 6}, &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 1);
    BB_CHECK(!bb_rng_error(&rng));
    return match;
}

typedef struct {
    Bloodbowl env;
    uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    float actions[BBE_AGENTS * 3];
    unsigned char mask[BBE_AGENTS * BBE_MASK_SIZE];
    float rewards[BBE_AGENTS];
    float terminals[BBE_AGENTS];
} StateBankEnvFixture;

static void setup_state_bank_env(StateBankEnvFixture* fixture,
                                 const bb_match* match) {
    memset(fixture, 0, sizeof *fixture);
    Bloodbowl* env = &fixture->env;
    env->match = *match;
    env->num_agents = BBE_AGENTS;
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        env->obs_ptr[agent] = fixture->obs + agent * BBE_OBS_SIZE;
        env->action_ptr[agent] = fixture->actions + agent * 3;
        env->action_mask_ptr[agent] =
            fixture->mask + agent * BBE_MASK_SIZE;
        env->reward_ptr[agent] = fixture->rewards + agent;
        env->terminal_ptr[agent] = fixture->terminals + agent;
        env->v4_dirty[agent] = 1;
    }
    bbe_refresh_legal(env);
    bbe_emit_all(env);
}

static int load_one(const char* path, const bb_match* match) {
    write_state_bank(path, match);
    reset_state_bank_loader(path);
    bbe_state_bank_load();
    return bbe_state_bank_n;
}

static ad_recipe authored_test_recipe(void) {
    ad_recipe recipe;
    memset(&recipe, 0, sizeof recipe);
    recipe.procgen_seed = 0xA1170EEDu;
    recipe.procgen_stream = 17;
    recipe.game_seed = 0xD11CE5u;
    recipe.game_stream = 23;
    recipe.controller_seed = 0xF300F3u;
    recipe.controller_stream = 31;
    recipe.home_team = 0;
    recipe.away_team = 1;
    recipe.exclude_team = -1;
    recipe.procgen = bb_procgen_params_default();
    return recipe;
}

static ad_recipe authored_f5_test_recipe(void) {
    ad_recipe recipe = authored_test_recipe();
    recipe.controller_seed = 410;
    return recipe;
}

static ad_recipe authored_f4_test_recipe(void) {
    ad_recipe recipe = authored_test_recipe();
    recipe.controller_seed = 1;
    return recipe;
}

BB_TEST(state_bank_accepts_exact_replayed_authored_record) {
    ad_recipe recipe = authored_test_recipe();
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
    ad_bbs_record record = {0xA0000001u, (uint32_t)recipe.action_count, &recipe};
    BB_CHECK_EQ(ad_bbs_write(file, &record, 1, error), 0);
    BB_CHECK_EQ(fclose(file), 0);

    reset_state_bank_loader(path);
    bbe_state_bank_load();
    BB_CHECK_EQ(bbe_state_bank_n, 1);
    if (bbe_state_bank_n == 1) {
        BB_CHECK_EQ(memcmp(&bbe_state_bank[0], &replayed, sizeof replayed), 0);
        uint32_t packed_action = 0;
        bb_status status = BB_STATUS_ERROR;
        int dice_used = -1;
        BB_CHECK_EQ(ad_verify_one_action_continuation(
                        &bbe_state_bank[0], &packed_action, &status,
                        &dice_used, error),
                    0);
        BB_CHECK(packed_action != 0);
        BB_CHECK(status != BB_STATUS_ERROR);
        BB_CHECK(dice_used >= 0 && dice_used <= AD_CONTINUATION_DICE);
    }
    reset_state_bank_loader(BBE_STATE_BANK_PATH);
    BB_CHECK_EQ(remove(path), 0);
}

BB_TEST(state_bank_accepts_exact_replayed_late_second_half_record) {
    ad_recipe recipe = authored_test_recipe();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_f3_late_second_half(&recipe, error), 0);

    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-authored-f3-%ld.bbs",
             (long)getpid());
    FILE* file = fopen(path, "wb");
    BB_CHECK(file != NULL);
    if (file == NULL) return;
    ad_bbs_record record = {
        0xA3000001u, (uint32_t)recipe.action_count, &recipe,
    };
    BB_CHECK_EQ(ad_bbs_write(file, &record, 1, error), 0);
    BB_CHECK_EQ(fclose(file), 0);

    reset_state_bank_loader(path);
    bbe_state_bank_load();
    BB_CHECK_EQ(bbe_state_bank_n, 1);
    if (bbe_state_bank_n == 1) {
        const bb_match* loaded = &bbe_state_bank[0];
        BB_CHECK_EQ(memcmp(loaded, &recipe.captured, sizeof *loaded), 0);
        BB_CHECK_EQ(loaded->half, 2);
        BB_CHECK(loaded->turn[loaded->active_team] >= 5);
        BB_CHECK_EQ(ad_verify_one_action_continuation(
                        loaded, NULL, NULL, NULL, error),
                    0);
    }
    reset_state_bank_loader(BBE_STATE_BANK_PATH);
    BB_CHECK_EQ(remove(path), 0);
}

BB_TEST(state_bank_accepts_exact_replayed_pass_opportunity_record) {
    ad_recipe recipe = authored_test_recipe();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_f1_pass_opportunity(&recipe, error), 0);

    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-authored-f1-%ld.bbs",
             (long)getpid());
    FILE* file = fopen(path, "wb");
    BB_CHECK(file != NULL);
    if (file == NULL) return;
    ad_bbs_record record = {
        0xA1000001u, (uint32_t)recipe.action_count, &recipe,
    };
    BB_CHECK_EQ(ad_bbs_write(file, &record, 1, error), 0);
    BB_CHECK_EQ(fclose(file), 0);

    reset_state_bank_loader(path);
    bbe_state_bank_load();
    BB_CHECK_EQ(bbe_state_bank_n, 1);
    if (bbe_state_bank_n == 1) {
        const bb_match* loaded = &bbe_state_bank[0];
        BB_CHECK_EQ(memcmp(loaded, &recipe.captured, sizeof *loaded), 0);
        BB_CHECK(ad_f1_pass_opportunity_valid(loaded));
        BB_CHECK_EQ(ad_verify_one_action_continuation(
                        loaded, NULL, NULL, NULL, error),
                    0);
    }
    reset_state_bank_loader(BBE_STATE_BANK_PATH);
    BB_CHECK_EQ(remove(path), 0);
}

BB_TEST(state_bank_accepts_exact_replayed_handoff_opportunity_record) {
    ad_recipe recipe = authored_test_recipe();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_f2_handoff_opportunity(&recipe, error), 0);

    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-authored-f2-%ld.bbs",
             (long)getpid());
    FILE* file = fopen(path, "wb");
    BB_CHECK(file != NULL);
    if (file == NULL) return;
    ad_bbs_record record = {
        0xA2000001u, (uint32_t)recipe.action_count, &recipe,
    };
    BB_CHECK_EQ(ad_bbs_write(file, &record, 1, error), 0);
    BB_CHECK_EQ(fclose(file), 0);

    reset_state_bank_loader(path);
    bbe_state_bank_load();
    BB_CHECK_EQ(bbe_state_bank_n, 1);
    if (bbe_state_bank_n == 1) {
        const bb_match* loaded = &bbe_state_bank[0];
        BB_CHECK_EQ(memcmp(loaded, &recipe.captured, sizeof *loaded), 0);
        BB_CHECK(ad_f2_handoff_opportunity_valid(loaded));
        BB_CHECK_EQ(ad_verify_one_action_continuation(
                        loaded, NULL, NULL, NULL, error),
                    0);
    }
    reset_state_bank_loader(BBE_STATE_BANK_PATH);
    BB_CHECK_EQ(remove(path), 0);
}

BB_TEST(state_bank_accepts_exact_replayed_score_or_stall_record) {
    ad_recipe recipe = authored_f5_test_recipe();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_f5_score_or_wait(&recipe, error), 0);

    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-authored-f5-%ld.bbs",
             (long)getpid());
    FILE* file = fopen(path, "wb");
    BB_CHECK(file != NULL);
    if (file == NULL) return;
    ad_bbs_record record = {
        0xA5000001u, (uint32_t)recipe.action_count, &recipe,
    };
    BB_CHECK_EQ(ad_bbs_write(file, &record, 1, error), 0);
    BB_CHECK_EQ(fclose(file), 0);

    reset_state_bank_loader(path);
    bbe_state_bank_load();
    BB_CHECK_EQ(bbe_state_bank_n, 1);
    if (bbe_state_bank_n == 1) {
        const bb_match* loaded = &bbe_state_bank[0];
        BB_CHECK_EQ(memcmp(loaded, &recipe.captured, sizeof *loaded), 0);
        BB_CHECK(ad_f5_score_or_wait_valid(loaded));
        BB_CHECK_EQ(ad_verify_one_action_continuation(
                        loaded, NULL, NULL, NULL, error),
                    0);
    }
    reset_state_bank_loader(BBE_STATE_BANK_PATH);
    BB_CHECK_EQ(remove(path), 0);
}

BB_TEST(state_bank_accepts_exact_replayed_pending_dodge_reroll_record) {
    ad_recipe recipe = authored_f4_test_recipe();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_f4_pending_dodge_reroll(&recipe, error), 0);
    BB_CHECK_EQ(recipe.action_count, 384);
    BB_CHECK_EQ(recipe.dice_count, 110);
    BB_CHECK(!bb_state_bank_boundary_valid(&recipe.captured));
    BB_CHECK(bb_state_bank_dodge_reroll_valid(&recipe.captured));
    BB_CHECK(bb_state_bank_resumable_valid(&recipe.captured));

    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-authored-f4-%ld.bbs",
             (long)getpid());
    FILE* file = fopen(path, "wb");
    BB_CHECK(file != NULL);
    if (file == NULL) return;
    ad_bbs_record record = {
        0xA4000001u, (uint32_t)recipe.action_count, &recipe,
    };
    BB_CHECK_EQ(ad_bbs_write(file, &record, 1, error), 0);
    BB_CHECK_EQ(fclose(file), 0);

    reset_state_bank_loader(path);
    bbe_state_bank_load();
    BB_CHECK_EQ(bbe_state_bank_n, 1);
    if (bbe_state_bank_n == 1) {
        const bb_match* loaded = &bbe_state_bank[0];
        BB_CHECK_EQ(memcmp(loaded, &recipe.captured, sizeof *loaded), 0);
        BB_CHECK(!bb_state_bank_boundary_valid(loaded));
        BB_CHECK(ad_f4_pending_dodge_reroll_valid(loaded));
        BB_CHECK(bb_state_bank_resumable_valid(loaded));

        StateBankEnvFixture fixture;
        setup_state_bank_env(&fixture, loaded);
        Bloodbowl* env = &fixture.env;
        BB_CHECK_EQ(env->n_legal, 3);
        uint8_t* home = env->obs_ptr[BB_HOME] + BBE_CTX_OFF;
        uint8_t* away = env->obs_ptr[BB_AWAY] + BBE_CTX_OFF;
        BB_CHECK_EQ(home[4], BB_PROC_TEST);
        BB_CHECK_EQ(home[5], 1);
        BB_CHECK_EQ(home[8], 3);
        BB_CHECK_EQ(home[10], 0);
        BB_CHECK_EQ(away[4], BB_PROC_TEST);
        BB_CHECK_EQ(away[5], 1);
        BB_CHECK_EQ(away[8], 3);
        BB_CHECK_EQ(away[10], 1);
        unsigned char* home_mask = env->action_mask_ptr[BB_HOME];
        unsigned char* away_mask = env->action_mask_ptr[BB_AWAY];
        BB_CHECK_EQ(home_mask[BB_A_NONE], 1);
        BB_CHECK_EQ(home_mask[BB_A_USE_REROLL], 0);
        BB_CHECK_EQ(home_mask[BB_A_DECLINE_REROLL], 0);
        BB_CHECK_EQ(away_mask[BB_A_USE_REROLL], 1);
        BB_CHECK_EQ(away_mask[BB_A_DECLINE_REROLL], 1);

        BB_CHECK_EQ(ad_verify_one_action_continuation(
                        loaded, NULL, NULL, NULL, error),
                    0);
    }
    reset_state_bank_loader(BBE_STATE_BANK_PATH);
    BB_CHECK_EQ(remove(path), 0);
}

BB_TEST(state_bank_accepts_pending_dodge_reroll_and_emits_decision) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-dodge-bank-%ld.bbs",
             (long)getpid());
    bb_match pending = pending_dodge_reroll_match();
    BB_CHECK(!bb_state_bank_boundary_valid(&pending));
    BB_CHECK(bb_state_bank_dodge_reroll_valid(&pending));
    BB_CHECK_EQ(load_one(path, &pending), 1);

    if (bbe_state_bank_n == 1) {
        const bb_match* loaded = &bbe_state_bank[0];
        BB_CHECK_EQ(memcmp(loaded, &pending, sizeof pending), 0);

        StateBankEnvFixture fixture;
        setup_state_bank_env(&fixture, loaded);
        Bloodbowl* env = &fixture.env;
        BB_CHECK_EQ(env->n_legal, 2);
        uint8_t* home = env->obs_ptr[BB_HOME] + BBE_CTX_OFF;
        uint8_t* away = env->obs_ptr[BB_AWAY] + BBE_CTX_OFF;
        BB_CHECK_EQ(home[4], BB_PROC_TEST);
        BB_CHECK_EQ(home[5], 1);
        BB_CHECK_EQ(home[8], 3);
        BB_CHECK_EQ(home[9], 11);
        BB_CHECK_EQ(home[12], 7);
        BB_CHECK_EQ(home[10], 1);
        BB_CHECK_EQ(away[4], BB_PROC_TEST);
        BB_CHECK_EQ(away[5], 1);
        BB_CHECK_EQ(away[8], 3);
        BB_CHECK_EQ(away[9], 16);
        BB_CHECK_EQ(away[12], 7);
        BB_CHECK_EQ(away[10], 0);

        unsigned char* home_mask = env->action_mask_ptr[BB_HOME];
        unsigned char* away_mask = env->action_mask_ptr[BB_AWAY];
        BB_CHECK_EQ(home_mask[BB_A_USE_REROLL], 1);
        BB_CHECK_EQ(home_mask[BB_A_DECLINE_REROLL], 1);
        BB_CHECK_EQ(away_mask[BB_A_NONE], 1);
        BB_CHECK_EQ(away_mask[BB_A_USE_REROLL], 0);
        BB_CHECK_EQ(away_mask[BB_A_DECLINE_REROLL], 0);

        bb_match used = *loaded;
        uint8_t success_die = 4;
        bb_rng use_rng;
        bb_rng_script(&use_rng, &success_die, 1);
        BB_CHECK_EQ(fx_apply(
                        &used,
                        (bb_action){BB_A_USE_REROLL, BB_RR_TEAM, 0, 0},
                        &use_rng),
                    BB_STATUS_DECISION);
        BB_CHECK_EQ(used.rerolls[BB_HOME], 1);
        BB_CHECK_EQ(used.players[0].stance, BB_STANCE_STANDING);

        bb_match declined = *loaded;
        uint8_t armour_dice[] = {3, 3};
        bb_rng decline_rng;
        bb_rng_script(&decline_rng, armour_dice, 2);
        BB_CHECK_EQ(fx_apply(
                        &declined,
                        (bb_action){BB_A_DECLINE_REROLL, 0, 0, 0},
                        &decline_rng),
                    BB_STATUS_DECISION);
        BB_CHECK_EQ(declined.rerolls[BB_HOME], 2);
        BB_CHECK_EQ(declined.players[0].stance, BB_STANCE_PRONE);
        BB_CHECK_EQ(declined.decision_team, BB_AWAY);

        char error[AD_ERROR_CAP];
        BB_CHECK_EQ(ad_verify_one_action_continuation(
                        loaded, NULL, NULL, NULL, error),
                    0);

        // A second accepted state with the same mover, target number, legal
        // rerolls, and masks but a different pending destination must not
        // alias after a reset. The same successful action has a different
        // transition consequence, so the destination is observation context.
        bb_match alternate = *loaded;
        alternate.stack[3].x = 9;
        BB_CHECK(bb_state_bank_dodge_reroll_valid(&alternate));
        StateBankEnvFixture alternate_fixture;
        setup_state_bank_env(&alternate_fixture, &alternate);
        BB_CHECK_EQ(memcmp(fixture.mask, alternate_fixture.mask,
                           sizeof fixture.mask),
                    0);
        BB_CHECK(memcmp(fixture.obs, alternate_fixture.obs,
                        sizeof fixture.obs) != 0);
        uint8_t* alternate_home =
            alternate_fixture.env.obs_ptr[BB_HOME] + BBE_CTX_OFF;
        uint8_t* alternate_away =
            alternate_fixture.env.obs_ptr[BB_AWAY] + BBE_CTX_OFF;
        BB_CHECK_EQ(alternate_home[9], 10);
        BB_CHECK_EQ(alternate_home[12], 7);
        BB_CHECK_EQ(alternate_away[9], 17);
        BB_CHECK_EQ(alternate_away[12], 7);

        bb_match alternate_used = alternate;
        bb_rng alternate_rng;
        bb_rng_script(&alternate_rng, &success_die, 1);
        BB_CHECK_EQ(fx_apply(
                        &alternate_used,
                        (bb_action){BB_A_USE_REROLL, BB_RR_TEAM, 0, 0},
                        &alternate_rng),
                    BB_STATUS_DECISION);
        BB_CHECK_EQ(alternate_used.players[0].x, 9);
        BB_CHECK_EQ(alternate_used.players[0].y, 6);
        BB_CHECK_EQ(alternate_rng.script_pos, 1);
        BB_CHECK(!bb_rng_error(&alternate_rng));
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
    bb_action legal[BB_LEGAL_MAX];
    BB_CHECK(bb_legal_actions(&valid, legal) > 0);

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

    bb_match bad_turn_team = valid;
    bad_turn_team.stack[1].a = 255;
    BB_CHECK_EQ(load_one(path, &bad_turn_team), 0);

    bb_match bad_half = valid;
    bad_half.half = 0;
    BB_CHECK_EQ(load_one(path, &bad_half), 0);

    bb_match bad_turn = valid;
    bad_turn.turn[bad_turn.active_team] = 0;
    BB_CHECK_EQ(load_one(path, &bad_turn), 0);

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

    bb_match bad_skill = valid;
    bad_skill.players[0].skills.w[BB_SKILL_COUNT >> 6] |=
        (uint64_t)1 << (BB_SKILL_COUNT & 63);
    BB_CHECK_EQ(load_one(path, &bad_skill), 0);

    write_state_bank_meta(path, &valid, 0, valid.half,
                          valid.turn[valid.active_team], 0);
    reset_state_bank_loader(path);
    bbe_state_bank_load();
    BB_CHECK_EQ(bbe_state_bank_n, 0);

    write_state_bank_meta(path, &valid, 1, valid.half,
                          (uint8_t)(valid.turn[valid.active_team] + 1), 0);
    reset_state_bank_loader(path);
    bbe_state_bank_load();
    BB_CHECK_EQ(bbe_state_bank_n, 0);

    write_state_bank_meta(path, &valid, 1, valid.half,
                          valid.turn[valid.active_team], 1);
    reset_state_bank_loader(path);
    bbe_state_bank_load();
    BB_CHECK_EQ(bbe_state_bank_n, 0);

    reset_state_bank_loader(BBE_STATE_BANK_PATH);
    BB_CHECK_EQ(remove(path), 0);
}
