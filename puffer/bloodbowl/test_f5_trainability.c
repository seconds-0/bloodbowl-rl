#define BB_TEST_MAIN
#include "bb_test.h"
#include "bloodbowl.h"
#include "authored_drill.h"
#include "test_support/vecenv.h"
#include "environment_config.h"

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
    env->scripted_opponent_team = BB_AWAY;
    env->skillup_max_players = 4;
    env->skillup_max_each = 2;
    env->render_fps = 60;
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
        const Bloodbowl* env, int agent,
        int head, int type, int arg, int value) {
    unsigned char support[BBE_HEAD_SQ];
    const int sizes[3] = {BBE_HEAD_TYPE, BBE_HEAD_ARG, BBE_HEAD_SQ};
    int count = bbe_fill_joint_head_mask(
        env, agent, head, type, arg, support, sizes[head]);
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

static void f5_set_heads(
        Bloodbowl* env, int agent, const int heads[3]) {
    for (int head = 0; head < 3; head++) {
        env->action_ptr[agent][head] = (float)heads[head];
    }
}

static int f5_select_safe_legal_heads(
        const Bloodbowl* env, int heads[3], bb_action* selected) {
    /*
     * Finish an already-corrupted bounded episode without introducing a
     * second route mutation that can score.  The fixture always offers one of
     * these conservative continuations; the final fallback is retained only
     * to make a changed engine surface fail the explicit no-reward assertions
     * instead of reading past the legal list.  Once play leaves the reference
     * route, ordinary turn advancement is allowed to consume dice.
     */
    static const int priority[] = {
        BB_A_END_ACTIVATION,
        BB_A_END_TURN,
        BB_A_DECLARE,
        BB_A_ACTIVATE,
    };
    for (size_t p = 0; p < sizeof priority / sizeof priority[0]; p++) {
        for (int i = 0; i < env->n_legal; i++) {
            const bb_action action = env->legal[i];
            if (action.type != priority[p]) continue;
            if (action.type == BB_A_DECLARE &&
                action.arg != BB_ACT_MOVE) {
                continue;
            }
            heads[0] = action.type;
            heads[1] = env->legal_arg[i];
            heads[2] = env->legal_sq[i];
            *selected = action;
            return 1;
        }
    }
    if (env->n_legal <= 0) return 0;
    heads[0] = env->legal[0].type;
    heads[1] = env->legal_arg[0];
    heads[2] = env->legal_sq[0];
    *selected = env->legal[0];
    return 1;
}

static void f5_check_zero_nonterminal_emission(
        const F5Fixture* fixture) {
    BB_CHECK(fixture->terminals[BB_HOME] == 0.0f);
    BB_CHECK(fixture->terminals[BB_AWAY] == 0.0f);
    BB_CHECK(fixture->rewards[BB_HOME] == 0.0f);
    BB_CHECK(fixture->rewards[BB_AWAY] == 0.0f);
    BB_CHECK_EQ(fixture->env.ep_tds_team[BB_HOME], 0);
    BB_CHECK_EQ(fixture->env.ep_tds_team[BB_AWAY], 0);
}

BB_TEST(f5_trainability_role_identity_is_exact_and_not_a_bank) {
    BB_CHECK_EQ(PUFFER_QUALIFICATION_FIXTURE_ENABLED, 1);
    BB_CHECK_EQ(PUFFER_QUALIFICATION_FIXTURE_QUALIFICATION_ONLY, 1);
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
    BB_CHECK(strcmp(PUFFER_QUALIFICATION_FIXTURE_REWARD_CONTRACT,
                    "touchdown-zero-sum-only-v1") == 0);
    BB_CHECK(strcmp(PUFFER_QUALIFICATION_FIXTURE_REFERENCE_TRACE_SCHEMA,
                    "bloodbowl-f5-reference-trace-v1") == 0);
    BB_CHECK(strcmp(
        PUFFER_QUALIFICATION_FIXTURE_REFERENCE_TRACE_SHA256,
        "456e336e5eaa92e4e5fdedfb753d237a163e9a8e4e58ff09fa8979d2a91f4300")
        == 0);
    BB_CHECK(bbe_f5_trainability_abi_valid());
    BB_CHECK(bbe_f5_trainability_identity_valid());
    for (int decision = 0; decision < 8; decision++) {
        for (int head = 0; head < 3; head++) {
            BB_CHECK_EQ(
                BBE_F5_TRAINABILITY_REFERENCE_ACTIONS[decision][head],
                F5_REFERENCE_HEADS[decision][head]);
        }
    }
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
    ((unsigned char*)&fixture)[sizeof fixture - 1] ^= 1u;
    BB_CHECK(!bbe_f5_trainability_match_sha256_valid(&fixture));
    BB_CHECK_EQ(bbe_f5_trainability_copy_match(NULL), -1);
}

BB_TEST(f5_trainability_config_rejects_every_semantic_mutation) {
    F5Fixture fixture;
    f5_setup_buffers(&fixture);
    BB_CHECK(bbe_f5_trainability_config_error(&fixture.env) == NULL);

#define F5_CHECK_CONFIG_MUTATION(field, value)                         \
    do {                                                                \
        f5_setup_buffers(&fixture);                                     \
        fixture.env.field = (value);                                    \
        const char* error = bbe_f5_trainability_config_error(           \
            &fixture.env);                                              \
        BB_CHECK(error != NULL);                                        \
        BB_CHECK(strcmp(error, #field) == 0);                           \
    } while (0)

    F5_CHECK_CONFIG_MUTATION(seed, UINT64_C(2));
    F5_CHECK_CONFIG_MUTATION(max_decisions, 7);
    F5_CHECK_CONFIG_MUTATION(max_decisions, 9);
    F5_CHECK_CONFIG_MUTATION(macro_moves, 1);
    F5_CHECK_CONFIG_MUTATION(demo_reset_pct, 1.0f);
    F5_CHECK_CONFIG_MUTATION(state_bank_kind, BBE_STATE_BANK_STRICT_REPLAY);
    F5_CHECK_CONFIG_MUTATION(demo_endzone_maxdist, 1);
    F5_CHECK_CONFIG_MUTATION(demo_pickup_maxdist, 1);
    F5_CHECK_CONFIG_MUTATION(demo_postkick_maxturn, 1);
    F5_CHECK_CONFIG_MUTATION(demo_pass_maxrange, 1);
    F5_CHECK_CONFIG_MUTATION(exclude_team, 0);
    F5_CHECK_CONFIG_MUTATION(force_home_team, 0);
    F5_CHECK_CONFIG_MUTATION(force_away_team, 0);
    F5_CHECK_CONFIG_MUTATION(scripted_opponent, 1);
    F5_CHECK_CONFIG_MUTATION(scripted_opponent_type, 1);
    F5_CHECK_CONFIG_MUTATION(scripted_opponent_team, BB_HOME);
    F5_CHECK_CONFIG_MUTATION(skillup_max_players, 3);
    F5_CHECK_CONFIG_MUTATION(skillup_max_each, 1);
    F5_CHECK_CONFIG_MUTATION(skillup_secondary_pct, 0.5f);
    F5_CHECK_CONFIG_MUTATION(render_fps, 59);
    F5_CHECK_CONFIG_MUTATION(reward_configured, 0);
    F5_CHECK_CONFIG_MUTATION(reward_td, 0.5f);
    F5_CHECK_CONFIG_MUTATION(reward_win, 0.5f);
    F5_CHECK_CONFIG_MUTATION(reward_draw, 0.5f);
    F5_CHECK_CONFIG_MUTATION(reward_setup_done, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_setup_autofix, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_ball_gain, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_ball_loss, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_dist_ball, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_dist_endzone, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_dist_pbrs_gamma, 0.5f);
    F5_CHECK_CONFIG_MUTATION(reward_injury_inflicted, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_injury_taken, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_injury_value_scaled, 1);
    F5_CHECK_CONFIG_MUTATION(reward_send_off, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_kickoff_touchback, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_surf_taken, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_surf_inflicted, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_k_kd, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_k_value, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_k_self_injury, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_k_ball, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_k_seq, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_k_turnover, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_possession, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_k_assist, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_rush_cost, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_carrier_exposure, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_carrier_exposure_soft, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_carrier_threat, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_defensive_threat, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_defensive_threat_soft, 0.25f);
    F5_CHECK_CONFIG_MUTATION(reward_statmatch_scale, 0.25f);

#undef F5_CHECK_CONFIG_MUTATION
}

BB_TEST(f5_trainability_strict_parser_hook_preflights_before_vector_seeding) {
    bbe_environment_config config;
    bbe_environment_config_defaults(&config);
    config.reward_td = 1.0;
    config.reward_win = 0.0;
    config.max_decisions = 8.0;

    Bloodbowl applied;
    bbe_environment_config_result result;
    BB_CHECK(bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_NONE, &applied, &result));
    BB_CHECK(bbe_f5_trainability_config_error(&applied) == NULL);
    BB_CHECK_EQ(bbe_environment_config_vector_seed(&applied, 0), 1);
    BB_CHECK_EQ(bbe_environment_config_vector_seed(&applied, 4095), 4096);
    applied.seed = bbe_environment_config_vector_seed(&applied, 4095);
    BB_CHECK(strcmp(
        bbe_f5_trainability_config_error(&applied), "seed") == 0);
    BB_CHECK(bbe_f5_trainability_runtime_config_error(&applied) == NULL);

    config.macro_moves = 1.0;
    BB_CHECK(!bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_NONE, NULL, &result));
    BB_CHECK_EQ(result.error, BBE_ENV_CONFIG_CROSS_FIELD);
    BB_CHECK(strcmp(result.field, "macro_moves") == 0);

    config.macro_moves = 0.0;
    config.seed = 2.0;
    BB_CHECK(!bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_NONE, NULL, &result));
    BB_CHECK_EQ(result.error, BBE_ENV_CONFIG_CROSS_FIELD);
    BB_CHECK(strcmp(result.field, "seed") == 0);
}

BB_TEST(f5_trainability_reference_scores_on_exact_eighth_c_step) {
    F5Fixture fixture;
    f5_setup_buffers(&fixture);
    c_reset(&fixture.env);

    bb_match expected;
    BB_CHECK_EQ(bbe_f5_trainability_copy_match(&expected), 0);
    BB_CHECK_EQ(memcmp(&fixture.env.match, &expected, sizeof expected), 0);
    uint8_t first_obs[sizeof fixture.obs];
    unsigned char first_mask[sizeof fixture.mask];
    memcpy(first_obs, fixture.obs, sizeof first_obs);
    memcpy(first_mask, fixture.mask, sizeof first_mask);
    int first_n_legal = fixture.env.n_legal;
    bb_action first_legal[BB_LEGAL_MAX];
    uint8_t first_legal_arg[BB_LEGAL_MAX];
    uint16_t first_legal_sq[BB_LEGAL_MAX];
    memcpy(first_legal, fixture.env.legal,
           (size_t)first_n_legal * sizeof first_legal[0]);
    memcpy(first_legal_arg, fixture.env.legal_arg,
           (size_t)first_n_legal * sizeof first_legal_arg[0]);
    memcpy(first_legal_sq, fixture.env.legal_sq,
           (size_t)first_n_legal * sizeof first_legal_sq[0]);

    int dice = 0;
    bb_rng_set_sink(&fixture.env.rng, f5_count_die, &dice);
    for (int step = 0; step < 8; step++) {
        Bloodbowl* env = &fixture.env;
        const bb_action expected_action = F5_REFERENCE_ACTIONS[step];
        const int* heads = F5_REFERENCE_HEADS[step];
        BB_CHECK_EQ(env->match.decision_team, BB_HOME);
        BB_CHECK(env->match.stack_top > 0);
        BB_CHECK(env->match.stack[env->match.stack_top - 1].proc !=
                 BB_PROC_TEST);
        f5_check_waiting_mask(&fixture);
        BB_CHECK(f5_support_contains(
            env, BB_HOME, 0, 0, 32, heads[0]));
        BB_CHECK(f5_support_contains(
            env, BB_HOME, 1, heads[0], 32, heads[1]));
        BB_CHECK(f5_support_contains(
            env, BB_HOME, 2, heads[0], heads[1], heads[2]));

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
    BB_CHECK_EQ(fixture.env.log.demo_episodes, 0.0f);
    BB_CHECK_EQ(fixture.env.log.state_bank_config_episodes, 0.0f);
    BB_CHECK_EQ(memcmp(&fixture.env.match, &expected, sizeof expected), 0);
    BB_CHECK_EQ(memcmp(fixture.obs, first_obs, sizeof first_obs), 0);
    BB_CHECK_EQ(memcmp(fixture.mask, first_mask, sizeof first_mask), 0);
    BB_CHECK_EQ(fixture.env.n_legal, first_n_legal);
    BB_CHECK_EQ(memcmp(fixture.env.legal, first_legal,
                       (size_t)first_n_legal * sizeof first_legal[0]), 0);
    BB_CHECK_EQ(memcmp(fixture.env.legal_arg, first_legal_arg,
                       (size_t)first_n_legal * sizeof first_legal_arg[0]), 0);
    BB_CHECK_EQ(memcmp(fixture.env.legal_sq, first_legal_sq,
                       (size_t)first_n_legal * sizeof first_legal_sq[0]), 0);
    /*
     * bb_rng_seed clears the die sink during autoreset, so reconcile the
     * post-reset PRNG state against a freshly seeded, unconsumed stream too.
     * This catches hidden dice in bb_advance after the eighth action.
     */
    bb_rng expected_reset_rng;
    bb_rng_seed(
        &expected_reset_rng,
        fixture.env.seed + fixture.env.episode * UINT64_C(7919), 1);
    BB_CHECK_EQ(fixture.env.rng.mode, expected_reset_rng.mode);
    BB_CHECK_EQ(fixture.env.rng.error, expected_reset_rng.error);
    BB_CHECK_EQ(fixture.env.rng.state, expected_reset_rng.state);
    BB_CHECK_EQ(fixture.env.rng.inc, expected_reset_rng.inc);
}

BB_TEST(f5_trainability_legal_route_corruptions_never_score) {
    typedef struct {
        const char* name;
        int decision;
        int heads[3];
        bb_action decoded;
    } route_corruption;
    static const route_corruption cases[] = {
        {
            "wrong player",
            0,
            {BB_A_ACTIVATE, 5, 390},
            {BB_A_ACTIVATE, 5, 0, 0},
        },
        {
            "wrong declaration",
            1,
            {BB_A_DECLARE, BB_ACT_BLITZ, 390},
            {BB_A_DECLARE, BB_ACT_BLITZ, 0, 0},
        },
        {
            "altered square",
            2,
            {BB_A_STEP, 32, 280},
            {BB_A_STEP, 0, 20, 10},
        },
    };

    for (size_t case_index = 0;
         case_index < sizeof cases / sizeof cases[0]; case_index++) {
        const route_corruption* test_case = &cases[case_index];
        (void)test_case->name;
        F5Fixture fixture;
        f5_setup_buffers(&fixture);
        c_reset(&fixture.env);

        int dice = 0;
        bb_rng_set_sink(&fixture.env.rng, f5_count_die, &dice);
        for (int decision = 0; decision < 8; decision++) {
            Bloodbowl* env = &fixture.env;
            int heads[3];
            bb_action expected;
            if (decision < test_case->decision) {
                memcpy(heads, F5_REFERENCE_HEADS[decision], sizeof heads);
                expected = F5_REFERENCE_ACTIONS[decision];
            } else if (decision == test_case->decision) {
                memcpy(heads, test_case->heads, sizeof heads);
                expected = test_case->decoded;
            } else {
                int selected =
                    f5_select_safe_legal_heads(env, heads, &expected);
                BB_CHECK(selected);
                if (!selected) return;
            }

            const int agent = env->match.decision_team;
            BB_CHECK(agent == BB_HOME || agent == BB_AWAY);
            if (agent != BB_HOME && agent != BB_AWAY) return;
            BB_CHECK(f5_support_contains(
                env, agent, 0, 0, 32, heads[0]));
            BB_CHECK(f5_support_contains(
                env, agent, 1, heads[0], 32, heads[1]));
            BB_CHECK(f5_support_contains(
                env, agent, 2, heads[0], heads[1], heads[2]));
            f5_set_heads(env, agent, heads);
            BB_CHECK(bb_action_eq(
                bbe_decode(env, agent, env->action_ptr[agent]), expected));
            c_step(env);

            if (decision <= test_case->decision) {
                /*
                 * The exact prefix and the legal corrupting action themselves
                 * are deterministic.  Dice after the divergence belong to
                 * ordinary alternate play and are not evidence about the
                 * reference route's no-dice contract.
                 */
                BB_CHECK_EQ(dice, 0);
            }
            BB_CHECK_EQ(env->illegal, 0);
            BB_CHECK_EQ(env->illegal_projection_collision, 0);
            if (decision < 7) {
                f5_check_zero_nonterminal_emission(&fixture);
            }
        }

        /*
         * A corrupt but legal eight-decision episode terminates only at the
         * frozen decision cap.  It is a zero-reward draw, never a false F5
         * success, and autoresets to the sealed fixture.
         */
        BB_CHECK(fixture.terminals[BB_HOME] == 1.0f);
        BB_CHECK(fixture.terminals[BB_AWAY] == 1.0f);
        BB_CHECK(fixture.rewards[BB_HOME] == 0.0f);
        BB_CHECK(fixture.rewards[BB_AWAY] == 0.0f);
        BB_CHECK(fixture.env.log.n == 1.0f);
        BB_CHECK(fixture.env.log.tds_t0 == 0.0f);
        BB_CHECK(fixture.env.log.tds_t1 == 0.0f);
        BB_CHECK(fixture.env.log.episode_return == 0.0f);
        BB_CHECK(fixture.env.log.episode_length == 8.0f);
        BB_CHECK_EQ(fixture.env.episode, 2);
        BB_CHECK_EQ(fixture.env.decisions, 0);
        BB_CHECK_EQ(fixture.env.match.score[BB_HOME], 0);
        BB_CHECK_EQ(fixture.env.match.score[BB_AWAY], 0);
        BB_CHECK(bbe_f5_trainability_match_sha256_valid(
            &fixture.env.match));
    }
}

BB_TEST(f5_trainability_seven_action_prefix_is_incomplete) {
    F5Fixture fixture;
    f5_setup_buffers(&fixture);
    c_reset(&fixture.env);

    int dice = 0;
    bb_rng_set_sink(&fixture.env.rng, f5_count_die, &dice);
    for (int decision = 0; decision < 7; decision++) {
        Bloodbowl* env = &fixture.env;
        f5_set_heads(env, BB_HOME, F5_REFERENCE_HEADS[decision]);
        BB_CHECK(bb_action_eq(
            bbe_decode(env, BB_HOME, env->action_ptr[BB_HOME]),
            F5_REFERENCE_ACTIONS[decision]));
        c_step(env);
        BB_CHECK_EQ(dice, 0);
        f5_check_zero_nonterminal_emission(&fixture);
    }

    BB_CHECK_EQ(fixture.env.decisions, 7);
    BB_CHECK_EQ(fixture.env.episode, 1);
    BB_CHECK(fixture.env.log.n == 0.0f);
    BB_CHECK_EQ(fixture.env.match.score[BB_HOME], 0);
    BB_CHECK_EQ(fixture.env.match.score[BB_AWAY], 0);
    BB_CHECK_EQ(fixture.env.match.ball.carrier, 6);
    BB_CHECK_EQ(fixture.env.match.players[6].x, 24);
    BB_CHECK_EQ(fixture.env.match.players[6].y, 5);
}

BB_TEST(f5_trainability_ninth_action_belongs_to_autoreset_episode) {
    F5Fixture fixture;
    f5_setup_buffers(&fixture);
    c_reset(&fixture.env);

    int dice = 0;
    bb_rng_set_sink(&fixture.env.rng, f5_count_die, &dice);
    for (int decision = 0; decision < 8; decision++) {
        f5_set_heads(
            &fixture.env, BB_HOME, F5_REFERENCE_HEADS[decision]);
        c_step(&fixture.env);
        BB_CHECK_EQ(dice, 0);
    }
    BB_CHECK(fixture.terminals[BB_HOME] == 1.0f);
    BB_CHECK(fixture.rewards[BB_HOME] == 1.0f);
    BB_CHECK_EQ(fixture.env.episode, 2);
    BB_CHECK_EQ(fixture.env.decisions, 0);
    BB_CHECK(fixture.env.log.n == 1.0f);

    /*
     * Autoreset reseeds the in-match RNG and clears its sink.  Reattach the
     * observer before the putative ninth action so this transition is covered
     * by the same no-hidden-dice invariant as the reference trace.
     */
    dice = 0;
    bb_rng_set_sink(&fixture.env.rng, f5_count_die, &dice);
    f5_set_heads(&fixture.env, BB_HOME, F5_REFERENCE_HEADS[0]);
    BB_CHECK(bb_action_eq(
        bbe_decode(
            &fixture.env, BB_HOME, fixture.env.action_ptr[BB_HOME]),
        F5_REFERENCE_ACTIONS[0]));
    c_step(&fixture.env);

    BB_CHECK_EQ(dice, 0);
    f5_check_zero_nonterminal_emission(&fixture);
    BB_CHECK_EQ(fixture.env.episode, 2);
    BB_CHECK_EQ(fixture.env.decisions, 1);
    BB_CHECK(fixture.env.log.n == 1.0f);
    BB_CHECK(fixture.env.log.tds_t0 == 1.0f);
    BB_CHECK(fixture.env.log.episode_length == 8.0f);
}
