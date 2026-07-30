#define BB_TEST_MAIN
#include "bb_test.h"
#include "bloodbowl.h"
#include "authored_drill.h"

#include <string.h>

typedef struct {
    Bloodbowl env;
    uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    float actions[BBE_AGENTS * 3];
    unsigned char mask[BBE_AGENTS * BBE_MASK_SIZE];
    float rewards[BBE_AGENTS];
    float terminals[BBE_AGENTS];
} F5Fixture;

static const bb_action F5_REFERENCE_ACTIONS[8] = {
    {BB_A_ACTIVATE, 6, 0, 0},
    {BB_A_DECLARE, BB_ACT_MOVE, 0, 0},
    {BB_A_STEP, 0, 20, 9},
    {BB_A_STEP, 0, 21, 8},
    {BB_A_STEP, 0, 22, 7},
    {BB_A_STEP, 0, 23, 6},
    {BB_A_STEP, 0, 24, 5},
    {BB_A_STEP, 0, 25, 4},
};

static const int F5_REFERENCE_HEADS[8][3] = {
    {6, 6, 390},
    {7, 0, 390},
    {9, 32, 254},
    {9, 32, 229},
    {9, 32, 204},
    {9, 32, 179},
    {9, 32, 154},
    {9, 32, 129},
};

static void f5_setup_buffers(F5Fixture* fixture) {
    memset(fixture, 0, sizeof *fixture);
    Bloodbowl* env = &fixture->env;
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
    env->seed = 1;
    env->max_decisions = 8;
    env->macro_moves = 0;
    env->demo_reset_pct = 0.0f;
    env->state_bank_kind = BBE_STATE_BANK_NONE;
    env->exclude_team = -1;
    env->force_home_team = -1;
    env->force_away_team = -1;
    env->skillup_max_players = 4;
    env->skillup_max_each = 2;
    env->reward_configured = 1;
    env->reward_td = 1.0f;
}

static void f5_count_die(void* user, int sides, int value) {
    (void)sides;
    (void)value;
    int* count = user;
    (*count)++;
}

static int f5_support_contains(
        const Bloodbowl* env, int head, int type, int arg, int value) {
    unsigned char support[BBE_HEAD_SQ];
    const int sizes[3] = {BBE_HEAD_TYPE, BBE_HEAD_ARG, BBE_HEAD_SQ};
    int count = bbe_fill_joint_head_mask(
        env, BB_HOME, head, type, arg, support, sizes[head]);
    return count > 0 && value >= 0 && value < sizes[head] &&
        support[value] != 0;
}

static void f5_check_waiting_mask(const F5Fixture* fixture) {
    const unsigned char* mask =
        fixture->mask + BB_AWAY * BBE_MASK_SIZE;
    int type_count = 0;
    int arg_count = 0;
    int square_count = 0;
    for (int i = 0; i < BBE_HEAD_TYPE; i++) type_count += mask[i] != 0;
    for (int i = 0; i < BBE_HEAD_ARG; i++) {
        arg_count += mask[BBE_HEAD_TYPE + i] != 0;
    }
    for (int i = 0; i < BBE_HEAD_SQ; i++) {
        square_count +=
            mask[BBE_HEAD_TYPE + BBE_HEAD_ARG + i] != 0;
    }
    BB_CHECK_EQ(type_count, 1);
    BB_CHECK_EQ(arg_count, 1);
    BB_CHECK_EQ(square_count, 1);
    BB_CHECK(mask[BB_A_NONE] != 0);
    BB_CHECK(mask[BBE_HEAD_TYPE + 32] != 0);
    BB_CHECK(mask[BBE_HEAD_TYPE + BBE_HEAD_ARG + 390] != 0);
}

BB_TEST(f5_trainability_role_identity_is_exact_and_not_a_bank) {
    BB_CHECK_EQ(PUFFER_QUALIFICATION_FIXTURE_ENABLED, 1);
    BB_CHECK(strcmp(PUFFER_QUALIFICATION_FIXTURE_ROLE,
                    "f5-fixed-state-v1") == 0);
    BB_CHECK(strcmp(PUFFER_QUALIFICATION_FIXTURE_SCHEMA,
                    "bloodbowl-trainability-task-v1") == 0);
    BB_CHECK_EQ(PUFFER_STATE_BANK_COMPILED_KIND, BBE_STATE_BANK_NONE);
    BB_CHECK(strcmp(PUFFER_STATE_BANK_KIND_NAME, "none") == 0);
    BB_CHECK_EQ(PUFFER_QUALIFICATION_FIXTURE_BBS_SOURCE_ID,
                UINT32_C(0xA9000019));
    BB_CHECK_EQ(PUFFER_QUALIFICATION_FIXTURE_AUTHORED_SOURCE_ID,
                UINT32_C(0xAE00001A));
    BB_CHECK_EQ(PUFFER_QUALIFICATION_FIXTURE_MAX_DECISIONS, 8);
}

BB_TEST(f5_trainability_fixture_matches_complete_bundle_identity) {
    bb_match fixture;
    BB_CHECK_EQ(bbe_f5_trainability_copy_match(&fixture), 0);
    BB_CHECK(ad_f5_score_or_wait_valid(&fixture));
    BB_CHECK_EQ(fixture.half, 1);
    BB_CHECK_EQ(fixture.turn[BB_HOME], 2);
    BB_CHECK_EQ(fixture.turn[BB_AWAY], 2);
    BB_CHECK_EQ(fixture.score[BB_HOME], 0);
    BB_CHECK_EQ(fixture.score[BB_AWAY], 0);
    BB_CHECK_EQ(fixture.ball.carrier, 6);
    BB_CHECK_EQ(fixture.players[6].x, 19);
    BB_CHECK_EQ(fixture.players[6].y, 10);
    BB_CHECK_EQ(fixture.players[6].ma, 6);
    BB_CHECK(bbe_f5_trainability_match_sha256_valid(&fixture));
}

BB_TEST(f5_trainability_config_rejects_horizon_breakers_and_shaping) {
    F5Fixture fixture;
    f5_setup_buffers(&fixture);
    BB_CHECK(bbe_f5_trainability_config_error(&fixture.env) == NULL);

    fixture.env.macro_moves = 1;
    BB_CHECK(strcmp(bbe_f5_trainability_config_error(&fixture.env),
                    "macro_moves") == 0);
    fixture.env.macro_moves = 0;
    fixture.env.max_decisions = 9;
    BB_CHECK(strcmp(bbe_f5_trainability_config_error(&fixture.env),
                    "max_decisions") == 0);
    fixture.env.max_decisions = 8;
    fixture.env.demo_reset_pct = 1.0f;
    BB_CHECK(strcmp(bbe_f5_trainability_config_error(&fixture.env),
                    "demo_reset_pct") == 0);
    fixture.env.demo_reset_pct = 0.0f;
    fixture.env.reward_win = 0.6f;
    BB_CHECK(strcmp(bbe_f5_trainability_config_error(&fixture.env),
                    "reward_win") == 0);
    fixture.env.reward_win = 0.0f;
    fixture.env.reward_dist_endzone = 0.01f;
    BB_CHECK(strcmp(bbe_f5_trainability_config_error(&fixture.env),
                    "reward_dist_endzone") == 0);
}

BB_TEST(f5_trainability_reference_scores_on_exact_eighth_c_step) {
    F5Fixture fixture;
    f5_setup_buffers(&fixture);
    c_reset(&fixture.env);

    bb_match expected;
    BB_CHECK_EQ(bbe_f5_trainability_copy_match(&expected), 0);
    BB_CHECK_EQ(memcmp(&fixture.env.match, &expected, sizeof expected), 0);

    int dice = 0;
    bb_rng_set_sink(&fixture.env.rng, f5_count_die, &dice);
    for (int step = 0; step < 8; step++) {
        Bloodbowl* env = &fixture.env;
        const bb_action expected_action = F5_REFERENCE_ACTIONS[step];
        const int* heads = F5_REFERENCE_HEADS[step];
        BB_CHECK_EQ(env->match.decision_team, BB_HOME);
        f5_check_waiting_mask(&fixture);
        BB_CHECK(f5_support_contains(env, 0, 0, 32, heads[0]));
        BB_CHECK(f5_support_contains(env, 1, heads[0], 32, heads[1]));
        BB_CHECK(f5_support_contains(
            env, 2, heads[0], heads[1], heads[2]));

        env->action_ptr[BB_HOME][0] = (float)heads[0];
        env->action_ptr[BB_HOME][1] = (float)heads[1];
        env->action_ptr[BB_HOME][2] = (float)heads[2];
        bb_action decoded =
            bbe_decode(env, BB_HOME, env->action_ptr[BB_HOME]);
        BB_CHECK(bb_action_eq(decoded, expected_action));
        c_step(env);

        BB_CHECK_EQ(dice, 0);
        BB_CHECK_EQ(env->illegal, 0);
        BB_CHECK_EQ(env->illegal_projection_collision, 0);
        if (step < 7) {
            BB_CHECK_EQ(fixture.terminals[BB_HOME], 0.0f);
            BB_CHECK_EQ(fixture.terminals[BB_AWAY], 0.0f);
            BB_CHECK_EQ(fixture.rewards[BB_HOME], 0.0f);
            BB_CHECK_EQ(fixture.rewards[BB_AWAY], 0.0f);
            BB_CHECK_EQ(env->ep_tds_team[BB_HOME], 0);
            BB_CHECK_EQ(env->ep_tds_team[BB_AWAY], 0);
        }
    }

    BB_CHECK_EQ(fixture.terminals[BB_HOME], 1.0f);
    BB_CHECK_EQ(fixture.terminals[BB_AWAY], 1.0f);
    BB_CHECK_EQ(fixture.rewards[BB_HOME], 1.0f);
    BB_CHECK_EQ(fixture.rewards[BB_AWAY], -1.0f);
    BB_CHECK_EQ(fixture.env.log.n, 1.0f);
    BB_CHECK_EQ(fixture.env.log.tds_t0, 1.0f);
    BB_CHECK_EQ(fixture.env.log.tds_t1, 0.0f);
    BB_CHECK_EQ(fixture.env.log.episode_length, 8.0f);
    BB_CHECK_EQ(memcmp(&fixture.env.match, &expected, sizeof expected), 0);
}
