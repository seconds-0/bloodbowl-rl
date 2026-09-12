#define BB_TEST_MAIN
#include "bb_test.h"
#include "bloodbowl.h"
#include "bb_fixtures.h"
#include "authored_drill.h"

#include <signal.h>
#include <sys/wait.h>
#include <unistd.h>

static void check_state_bank_float(float got, float want) {
    float delta = got - want;
    if (delta < 0.0f) delta = -delta;
    if (!(delta < 0.00001f)) {
        printf("FLOAT %s: got %.9g, want %.9g\n",
               bb_test_current, (double)got, (double)want);
    }
    BB_CHECK(delta < 0.00001f);
}

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

static void setup_state_bank_buffers(StateBankEnvFixture* fixture) {
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
}

static void setup_state_bank_env(StateBankEnvFixture* fixture,
                                 const bb_match* match) {
    setup_state_bank_buffers(fixture);
    Bloodbowl* env = &fixture->env;
    env->match = *match;
    bbe_refresh_legal(env);
    bbe_emit_all(env);
}

static int load_one(const char* path, const bb_match* match) {
    write_state_bank(path, match);
    reset_state_bank_loader(path);
    bbe_state_bank_load();
    return bbe_state_bank_n;
}

static void configure_restored_pbrs_env(StateBankEnvFixture* fixture,
                                        float fetch_coeff,
                                        float carry_coeff,
                                        float gamma) {
    setup_state_bank_buffers(fixture);
    Bloodbowl* env = &fixture->env;
    env->seed = 0x5A17u;
    env->max_decisions = BBE_MAX_DECISIONS;
    env->force_home_team = -1;
    env->force_away_team = -1;
    env->exclude_team = -1;
    env->demo_reset_pct = 1.0f;
    env->reward_configured = 1;
    env->reward_dist_ball = fetch_coeff;
    env->reward_dist_endzone = carry_coeff;
    env->reward_dist_pbrs_gamma = gamma;
}

static void step_state_bank_action(StateBankEnvFixture* fixture, bb_action act) {
    Bloodbowl* env = &fixture->env;
    int agent = env->match.decision_team;
    BB_CHECK(agent == BB_HOME || agent == BB_AWAY);
    if (agent != BB_HOME && agent != BB_AWAY) return;
    BB_CHECK(fx_find(&env->match, act) >= 0);
    if (fx_find(&env->match, act) < 0) return;
    env->action_ptr[agent][0] = (float)act.type;
    env->action_ptr[agent][1] = (float)bbe_action_arg(agent, act);
    env->action_ptr[agent][2] = (float)bbe_action_sq(agent, act);
    c_step(env);
}

static bb_match restored_pbrs_nested_loose_match(void) {
    bb_match match = pending_dodge_reroll_match();
    match.stack[3].x = 11;
    fx_ball_ground(&match, 13, 7);
    BB_CHECK(bb_state_bank_dodge_reroll_valid(&match));
    BB_CHECK(bb_state_bank_resumable_valid(&match));
    return match;
}

static void check_reset_reward_scratch_zero(
        const StateBankEnvFixture* fixture) {
    const Bloodbowl* env = &fixture->env;
    for (int team = 0; team < BBE_AGENTS; team++) {
        check_state_bank_float(fixture->rewards[team], 0.0f);
        check_state_bank_float(fixture->terminals[team], 0.0f);
        check_state_bank_float(env->ep_return[team], 0.0f);
        check_state_bank_float(env->ep_reward_component_residual[team], 0.0f);
        for (int component = 0;
             component < BBE_REWARD_COMPONENT_COUNT; component++) {
            check_state_bank_float(
                env->step_reward_component[team][component], 0.0f);
            check_state_bank_float(
                env->ep_reward_component[team][component], 0.0f);
        }
    }
}

static void poison_potential_history(Bloodbowl* env) {
    env->pot_fetch_prev[BB_HOME] = NAN;
    env->pot_fetch_prev[BB_AWAY] = 77.0f;
    env->pot_carry_prev[BB_HOME] = 78.0f;
    env->pot_carry_prev[BB_AWAY] = NAN;
}

static void cleanup_state_bank_path(const char* path) {
    bb_stall_attach(0);
    reset_state_bank_loader(BBE_STATE_BANK_PATH);
    BB_CHECK_EQ(remove(path), 0);
}

BB_TEST(restored_pbrs_nested_loose_first_transition_uses_s0) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-pbrs-nested-%ld.bbs",
             (long)getpid());
    bb_match restored = restored_pbrs_nested_loose_match();
    BB_CHECK_EQ(load_one(path, &restored), 1);

    StateBankEnvFixture fixture;
    configure_restored_pbrs_env(&fixture, 0.05f, 0.0f, 0.995f);
    c_reset(&fixture.env);
    Bloodbowl* env = &fixture.env;

    BB_CHECK_EQ(bbe_state_bank_n, 1);
    BB_CHECK_EQ(env->demo_started, 1);
    BB_CHECK_EQ(memcmp(&env->match, &restored, sizeof restored), 0);
    BB_CHECK_EQ(env->match.players[0].x, 10);
    BB_CHECK_EQ(env->match.players[0].y, 7);
    BB_CHECK_EQ(env->match.players[BB_TEAM_SLOTS].x, 10);
    BB_CHECK_EQ(env->match.players[BB_TEAM_SLOTS].y, 8);
    BB_CHECK_EQ(env->match.ball.x, 13);
    BB_CHECK_EQ(env->match.ball.y, 7);
    check_state_bank_float(env->pot_fetch_prev[BB_HOME], 1.10f);
    check_state_bank_float(env->pot_fetch_prev[BB_AWAY], 1.10f);
    check_state_bank_float(env->pot_carry_prev[BB_HOME], 0.0f);
    check_state_bank_float(env->pot_carry_prev[BB_AWAY], 0.0f);
    check_reset_reward_scratch_zero(&fixture);

    uint8_t successful_reroll = 4;
    bb_rng_script(&env->rng, &successful_reroll, 1);
    step_state_bank_action(
        &fixture, (bb_action){BB_A_USE_REROLL, BB_RR_TEAM, 0, 0});

    BB_CHECK_EQ(env->match.players[0].x, 11);
    BB_CHECK_EQ(env->match.players[0].y, 6);
    BB_CHECK_EQ(env->match.ball.x, 13);
    BB_CHECK_EQ(env->match.ball.y, 7);
    BB_CHECK_EQ(env->rng.script_pos, 1);
    BB_CHECK(!bb_rng_error(&env->rng));
    check_state_bank_float(
        env->step_reward_component[BB_HOME][BBE_REWARD_DISTANCE_BALL],
        0.04425f);
    check_state_bank_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_BALL],
        -0.0055f);
    check_state_bank_float(env->pot_fetch_prev[BB_HOME], 1.15f);
    check_state_bank_float(env->pot_fetch_prev[BB_AWAY], 1.10f);
    check_state_bank_float(fixture.rewards[BB_HOME], 0.04425f);
    check_state_bank_float(fixture.rewards[BB_AWAY], -0.0055f);
    check_state_bank_float(env->ep_return[BB_HOME], 0.04425f);
    check_state_bank_float(env->ep_return[BB_AWAY], -0.0055f);
    for (int team = 0; team < BBE_AGENTS; team++) {
        check_state_bank_float(env->ep_reward_component_residual[team], 0.0f);
        for (int component = 0;
             component < BBE_REWARD_COMPONENT_COUNT; component++) {
            if (component == BBE_REWARD_DISTANCE_BALL) continue;
            check_state_bank_float(
                env->step_reward_component[team][component], 0.0f);
        }
    }

    cleanup_state_bank_path(path);
}

BB_TEST(restored_pbrs_held_boundary_initializes_carry_s0) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-pbrs-held-%ld.bbs",
             (long)getpid());
    bb_match restored = valid_bank_match();
    fx_ball_held(&restored, 0);
    BB_CHECK(bb_state_bank_boundary_valid(&restored));
    BB_CHECK_EQ(load_one(path, &restored), 1);

    StateBankEnvFixture fixture;
    configure_restored_pbrs_env(&fixture, 0.0f, 0.04f, 0.995f);
    c_reset(&fixture.env);
    Bloodbowl* env = &fixture.env;

    BB_CHECK_EQ(env->demo_started, 1);
    BB_CHECK_EQ(memcmp(&env->match, &restored, sizeof restored), 0);
    BB_CHECK_EQ(env->match.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(env->match.ball.carrier, 0);
    check_state_bank_float(env->pot_fetch_prev[BB_HOME], 0.0f);
    check_state_bank_float(env->pot_fetch_prev[BB_AWAY], 0.0f);
    check_state_bank_float(env->pot_carry_prev[BB_HOME], 0.32f);
    check_state_bank_float(env->pot_carry_prev[BB_AWAY], 0.0f);
    BB_CHECK_EQ(env->possessor, BB_HOME);
    check_reset_reward_scratch_zero(&fixture);

    step_state_bank_action(
        &fixture, (bb_action){BB_A_ACTIVATE, 0, 0, 0});
    check_state_bank_float(
        env->step_reward_component[BB_HOME][BBE_REWARD_DISTANCE_ENDZONE],
        -0.0016f);
    check_state_bank_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_ENDZONE],
        0.0f);
    check_state_bank_float(fixture.rewards[BB_HOME], -0.0016f);
    check_state_bank_float(fixture.rewards[BB_AWAY], 0.0f);
    check_state_bank_float(env->ep_return[BB_HOME], -0.0016f);
    check_state_bank_float(env->ep_return[BB_AWAY], 0.0f);
    check_state_bank_float(env->ep_reward_component_residual[BB_HOME], 0.0f);
    check_state_bank_float(env->ep_reward_component_residual[BB_AWAY], 0.0f);

    cleanup_state_bank_path(path);
}

BB_TEST(restored_pbrs_away_held_boundary_initializes_carry_s0) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-pbrs-away-held-%ld.bbs",
             (long)getpid());
    bb_match restored;
    fx_match_midturn(&restored, BB_AWAY, 2);
    fx_lineman(&restored, BB_HOME, 0, 8, 7);
    int carrier = fx_lineman(&restored, BB_AWAY, 0, 17, 7);
    bb_rng rng;
    bb_rng_seed(&rng, 0xB4A6u, 3);
    BB_CHECK_EQ(fx_run(&restored, &rng), BB_STATUS_DECISION);
    fx_ball_held(&restored, carrier);
    BB_CHECK(bb_state_bank_boundary_valid(&restored));
    BB_CHECK_EQ(load_one(path, &restored), 1);

    StateBankEnvFixture fixture;
    configure_restored_pbrs_env(&fixture, 0.0f, 0.04f, 0.995f);
    c_reset(&fixture.env);
    Bloodbowl* env = &fixture.env;

    BB_CHECK_EQ(env->demo_started, 1);
    BB_CHECK_EQ(memcmp(&env->match, &restored, sizeof restored), 0);
    BB_CHECK_EQ(env->match.decision_team, BB_AWAY);
    BB_CHECK_EQ(env->match.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(env->match.ball.carrier, BB_TEAM_SLOTS);
    check_state_bank_float(env->pot_fetch_prev[BB_HOME], 0.0f);
    check_state_bank_float(env->pot_fetch_prev[BB_AWAY], 0.0f);
    check_state_bank_float(env->pot_carry_prev[BB_HOME], 0.0f);
    check_state_bank_float(env->pot_carry_prev[BB_AWAY], 0.32f);
    BB_CHECK_EQ(env->possessor, BB_AWAY);
    check_reset_reward_scratch_zero(&fixture);

    step_state_bank_action(
        &fixture, (bb_action){BB_A_ACTIVATE, BB_TEAM_SLOTS, 0, 0});
    check_state_bank_float(
        env->step_reward_component[BB_HOME][BBE_REWARD_DISTANCE_ENDZONE],
        0.0f);
    check_state_bank_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_ENDZONE],
        -0.0016f);
    check_state_bank_float(fixture.rewards[BB_HOME], 0.0f);
    check_state_bank_float(fixture.rewards[BB_AWAY], -0.0016f);
    check_state_bank_float(env->ep_return[BB_HOME], 0.0f);
    check_state_bank_float(env->ep_return[BB_AWAY], -0.0016f);
    check_state_bank_float(env->ep_reward_component_residual[BB_HOME], 0.0f);
    check_state_bank_float(env->ep_reward_component_residual[BB_AWAY], 0.0f);

    cleanup_state_bank_path(path);
}

BB_TEST(restored_pbrs_loose_boundary_initializes_both_teams) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-pbrs-loose-%ld.bbs",
             (long)getpid());
    bb_match restored = valid_bank_match();
    fx_ball_ground(&restored, 11, 7);
    BB_CHECK(bb_state_bank_boundary_valid(&restored));
    BB_CHECK_EQ(load_one(path, &restored), 1);

    StateBankEnvFixture fixture;
    configure_restored_pbrs_env(&fixture, 0.05f, 0.0f, 0.995f);
    c_reset(&fixture.env);
    Bloodbowl* env = &fixture.env;

    BB_CHECK_EQ(env->demo_started, 1);
    BB_CHECK_EQ(memcmp(&env->match, &restored, sizeof restored), 0);
    check_state_bank_float(env->pot_fetch_prev[BB_HOME], 1.10f);
    check_state_bank_float(env->pot_fetch_prev[BB_AWAY], 0.95f);
    check_state_bank_float(env->pot_carry_prev[BB_HOME], 0.0f);
    check_state_bank_float(env->pot_carry_prev[BB_AWAY], 0.0f);
    check_reset_reward_scratch_zero(&fixture);

    step_state_bank_action(
        &fixture, (bb_action){BB_A_ACTIVATE, 0, 0, 0});
    check_state_bank_float(
        env->step_reward_component[BB_HOME][BBE_REWARD_DISTANCE_BALL],
        -0.0055f);
    check_state_bank_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_BALL],
        -0.00475f);
    check_state_bank_float(fixture.rewards[BB_HOME], -0.0055f);
    check_state_bank_float(fixture.rewards[BB_AWAY], -0.00475f);
    check_state_bank_float(env->ep_return[BB_HOME], -0.0055f);
    check_state_bank_float(env->ep_return[BB_AWAY], -0.00475f);
    check_state_bank_float(env->ep_reward_component_residual[BB_HOME], 0.0f);
    check_state_bank_float(env->ep_reward_component_residual[BB_AWAY], 0.0f);

    cleanup_state_bank_path(path);
}

BB_TEST(restored_pbrs_exact_inactive_and_zero_channels_are_finite) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-pbrs-inactive-%ld.bbs",
             (long)getpid());
    bb_match restored = valid_bank_match();
    BB_CHECK_EQ(restored.ball.state, BB_BALL_OFF_PITCH);
    BB_CHECK(bb_state_bank_boundary_valid(&restored));
    BB_CHECK_EQ(load_one(path, &restored), 1);

    StateBankEnvFixture fixture;
    configure_restored_pbrs_env(&fixture, 0.05f, 0.04f, 0.995f);
    poison_potential_history(&fixture.env);
    c_reset(&fixture.env);
    BB_CHECK_EQ(fixture.env.demo_started, 1);
    BB_CHECK_EQ(memcmp(&fixture.env.match, &restored, sizeof restored), 0);
    for (int team = 0; team < BBE_AGENTS; team++) {
        BB_CHECK(isfinite(fixture.env.pot_fetch_prev[team]));
        BB_CHECK(isfinite(fixture.env.pot_carry_prev[team]));
        check_state_bank_float(fixture.env.pot_fetch_prev[team], 0.0f);
        check_state_bank_float(fixture.env.pot_carry_prev[team], 0.0f);
    }
    check_reset_reward_scratch_zero(&fixture);

    fixture.env.reward_dist_ball = 0.0f;
    fixture.env.reward_dist_endzone = 0.0f;
    poison_potential_history(&fixture.env);
    c_reset(&fixture.env);
    BB_CHECK_EQ(fixture.env.demo_started, 1);
    BB_CHECK_EQ(memcmp(&fixture.env.match, &restored, sizeof restored), 0);
    for (int team = 0; team < BBE_AGENTS; team++) {
        BB_CHECK(isfinite(fixture.env.pot_fetch_prev[team]));
        BB_CHECK(isfinite(fixture.env.pot_carry_prev[team]));
        check_state_bank_float(fixture.env.pot_fetch_prev[team], 0.0f);
        check_state_bank_float(fixture.env.pot_carry_prev[team], 0.0f);
    }
    check_reset_reward_scratch_zero(&fixture);

    cleanup_state_bank_path(path);
}

BB_TEST(restored_pbrs_fresh_procgen_initializes_finite_zero) {
    reset_state_bank_loader(BBE_STATE_BANK_PATH);
    StateBankEnvFixture fixture;
    configure_restored_pbrs_env(&fixture, 0.05f, 0.04f, 0.995f);
    fixture.env.demo_reset_pct = 0.0f;
    poison_potential_history(&fixture.env);
    c_reset(&fixture.env);

    BB_CHECK_EQ(fixture.env.demo_started, 0);
    BB_CHECK_EQ(fixture.env.match.ball.state, BB_BALL_OFF_PITCH);
    for (int team = 0; team < BBE_AGENTS; team++) {
        BB_CHECK(isfinite(fixture.env.pot_fetch_prev[team]));
        BB_CHECK(isfinite(fixture.env.pot_carry_prev[team]));
        check_state_bank_float(fixture.env.pot_fetch_prev[team], 0.0f);
        check_state_bank_float(fixture.env.pot_carry_prev[team], 0.0f);
    }
    check_reset_reward_scratch_zero(&fixture);
    bb_stall_attach(0);
    reset_state_bank_loader(BBE_STATE_BANK_PATH);
}

BB_TEST(restored_pbrs_legacy_reset_preserves_nan_priming) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-pbrs-legacy-%ld.bbs",
             (long)getpid());
    bb_match restored = valid_bank_match();
    fx_ball_ground(&restored, 11, 7);
    BB_CHECK(bb_state_bank_boundary_valid(&restored));
    BB_CHECK_EQ(load_one(path, &restored), 1);

    StateBankEnvFixture fixture;
    configure_restored_pbrs_env(&fixture, 0.05f, 0.04f, 0.0f);
    c_reset(&fixture.env);
    Bloodbowl* env = &fixture.env;
    for (int team = 0; team < BBE_AGENTS; team++) {
        BB_CHECK(isnan(env->pot_fetch_prev[team]));
        BB_CHECK(isnan(env->pot_carry_prev[team]));
    }
    check_reset_reward_scratch_zero(&fixture);

    step_state_bank_action(
        &fixture, (bb_action){BB_A_ACTIVATE, 0, 0, 0});
    check_state_bank_float(
        env->step_reward_component[BB_HOME][BBE_REWARD_DISTANCE_BALL], 0.0f);
    check_state_bank_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_BALL], 0.0f);
    check_state_bank_float(env->pot_fetch_prev[BB_HOME], -0.15f);
    check_state_bank_float(env->pot_fetch_prev[BB_AWAY], -0.30f);
    BB_CHECK(isnan(env->pot_carry_prev[BB_HOME]));
    BB_CHECK(isnan(env->pot_carry_prev[BB_AWAY]));
    check_state_bank_float(fixture.rewards[BB_HOME], 0.0f);
    check_state_bank_float(fixture.rewards[BB_AWAY], 0.0f);
    check_state_bank_float(env->ep_return[BB_HOME], 0.0f);
    check_state_bank_float(env->ep_return[BB_AWAY], 0.0f);
    check_state_bank_float(env->ep_reward_component_residual[BB_HOME], 0.0f);
    check_state_bank_float(env->ep_reward_component_residual[BB_AWAY], 0.0f);

    env->reward_dist_pbrs_gamma = -0.5f;
    poison_potential_history(env);
    c_reset(env);
    BB_CHECK_EQ(env->demo_started, 1);
    BB_CHECK_EQ(memcmp(&env->match, &restored, sizeof restored), 0);
    for (int team = 0; team < BBE_AGENTS; team++) {
        BB_CHECK(isnan(env->pot_fetch_prev[team]));
        BB_CHECK(isnan(env->pot_carry_prev[team]));
    }
    check_reset_reward_scratch_zero(&fixture);
    step_state_bank_action(
        &fixture, (bb_action){BB_A_ACTIVATE, 0, 0, 0});
    check_state_bank_float(
        env->step_reward_component[BB_HOME][BBE_REWARD_DISTANCE_BALL], 0.0f);
    check_state_bank_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_BALL], 0.0f);
    check_state_bank_float(env->pot_fetch_prev[BB_HOME], -0.15f);
    check_state_bank_float(env->pot_fetch_prev[BB_AWAY], -0.30f);
    BB_CHECK(isnan(env->pot_carry_prev[BB_HOME]));
    BB_CHECK(isnan(env->pot_carry_prev[BB_AWAY]));
    check_state_bank_float(fixture.rewards[BB_HOME], 0.0f);
    check_state_bank_float(fixture.rewards[BB_AWAY], 0.0f);
    check_state_bank_float(env->ep_return[BB_HOME], 0.0f);
    check_state_bank_float(env->ep_return[BB_AWAY], 0.0f);
    check_state_bank_float(env->ep_reward_component_residual[BB_HOME], 0.0f);
    check_state_bank_float(env->ep_reward_component_residual[BB_AWAY], 0.0f);

    cleanup_state_bank_path(path);
}

BB_TEST(restored_pbrs_second_reset_recomputes_new_s0) {
    char loose_path[256];
    char held_path[256];
    snprintf(loose_path, sizeof loose_path,
             "/tmp/bloodbowl-pbrs-reset-loose-%ld.bbs", (long)getpid());
    snprintf(held_path, sizeof held_path,
             "/tmp/bloodbowl-pbrs-reset-held-%ld.bbs", (long)getpid());
    bb_match loose = valid_bank_match();
    fx_ball_ground(&loose, 11, 7);
    bb_match held = valid_bank_match();
    fx_ball_held(&held, 0);
    BB_CHECK_EQ(load_one(loose_path, &loose), 1);

    StateBankEnvFixture fixture;
    configure_restored_pbrs_env(&fixture, 0.05f, 0.04f, 0.995f);
    c_reset(&fixture.env);
    check_state_bank_float(fixture.env.pot_fetch_prev[BB_HOME], 1.10f);
    check_state_bank_float(fixture.env.pot_fetch_prev[BB_AWAY], 0.95f);

    fixture.env.pot_fetch_prev[BB_HOME] = 77.0f;
    fixture.env.pot_fetch_prev[BB_AWAY] = 78.0f;
    fixture.env.pot_carry_prev[BB_HOME] = 79.0f;
    fixture.env.pot_carry_prev[BB_AWAY] = 80.0f;
    BB_CHECK_EQ(load_one(held_path, &held), 1);
    c_reset(&fixture.env);

    BB_CHECK_EQ(fixture.env.demo_started, 1);
    BB_CHECK_EQ(memcmp(&fixture.env.match, &held, sizeof held), 0);
    check_state_bank_float(fixture.env.pot_fetch_prev[BB_HOME], 0.0f);
    check_state_bank_float(fixture.env.pot_fetch_prev[BB_AWAY], 0.0f);
    check_state_bank_float(fixture.env.pot_carry_prev[BB_HOME], 0.32f);
    check_state_bank_float(fixture.env.pot_carry_prev[BB_AWAY], 0.0f);
    check_reset_reward_scratch_zero(&fixture);

    bb_stall_attach(0);
    reset_state_bank_loader(BBE_STATE_BANK_PATH);
    BB_CHECK_EQ(remove(loose_path), 0);
    BB_CHECK_EQ(remove(held_path), 0);
}

BB_TEST(restored_pbrs_terminal_autoreset_consumes_old_history) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-pbrs-autoreset-%ld.bbs",
             (long)getpid());
    bb_match restored = restored_pbrs_nested_loose_match();
    BB_CHECK_EQ(load_one(path, &restored), 1);

    StateBankEnvFixture fixture;
    configure_restored_pbrs_env(&fixture, 0.05f, 0.0f, 0.995f);
    fixture.env.max_decisions = 1;
    c_reset(&fixture.env);
    uint8_t successful_reroll = 4;
    bb_rng_script(&fixture.env.rng, &successful_reroll, 1);
    step_state_bank_action(
        &fixture, (bb_action){BB_A_USE_REROLL, BB_RR_TEAM, 0, 0});

    BB_CHECK_EQ(fixture.terminals[BB_HOME], 1.0f);
    BB_CHECK_EQ(fixture.terminals[BB_AWAY], 1.0f);
    check_state_bank_float(fixture.rewards[BB_HOME], -1.10f);
    check_state_bank_float(fixture.rewards[BB_AWAY], -1.10f);
    check_state_bank_float(
        fixture.env.log.reward_component[BBE_REWARD_DISTANCE_BALL], -1.10f);
    check_state_bank_float(fixture.env.log.episode_return, -1.10f);
    check_state_bank_float(fixture.env.log.reward_component_residual, 0.0f);
    BB_CHECK_EQ(fixture.env.log.n, 1.0f);
    BB_CHECK_EQ(fixture.env.demo_started, 1);
    BB_CHECK_EQ(memcmp(&fixture.env.match, &restored, sizeof restored), 0);
    check_state_bank_float(fixture.env.pot_fetch_prev[BB_HOME], 1.10f);
    check_state_bank_float(fixture.env.pot_fetch_prev[BB_AWAY], 1.10f);
    check_state_bank_float(fixture.env.pot_carry_prev[BB_HOME], 0.0f);
    check_state_bank_float(fixture.env.pot_carry_prev[BB_AWAY], 0.0f);
    check_state_bank_float(fixture.env.ep_return[BB_HOME], 0.0f);
    check_state_bank_float(fixture.env.ep_return[BB_AWAY], 0.0f);
    for (int team = 0; team < BBE_AGENTS; team++) {
        check_state_bank_float(
            fixture.env.ep_reward_component_residual[team], 0.0f);
        for (int component = 0;
             component < BBE_REWARD_COMPONENT_COUNT; component++) {
            check_state_bank_float(
                fixture.env.step_reward_component[team][component], 0.0f);
            check_state_bank_float(
                fixture.env.ep_reward_component[team][component], 0.0f);
        }
    }

    cleanup_state_bank_path(path);
}

BB_TEST(restored_pbrs_exact_nonfinite_history_aborts) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-pbrs-abort-%ld.bbs",
             (long)getpid());
    bb_match restored = valid_bank_match();
    fx_ball_held(&restored, 0);
    BB_CHECK_EQ(load_one(path, &restored), 1);

    StateBankEnvFixture fixture;
    configure_restored_pbrs_env(&fixture, 0.0f, 0.04f, 0.995f);
    c_reset(&fixture.env);
    fixture.env.pot_carry_prev[BB_HOME] = NAN;

    fflush(NULL);
    pid_t child = fork();
    BB_CHECK(child >= 0);
    if (child == 0) {
        FILE* sink = freopen("/dev/null", "w", stderr);
        (void)sink;
        step_state_bank_action(
            &fixture, (bb_action){BB_A_ACTIVATE, 0, 0, 0});
        _exit(0);
    }
    if (child > 0) {
        int status = 0;
        BB_CHECK_EQ(waitpid(child, &status, 0), child);
        BB_CHECK(WIFSIGNALED(status));
        if (WIFSIGNALED(status)) {
            BB_CHECK_EQ(WTERMSIG(status), SIGABRT);
        }
    }

    cleanup_state_bank_path(path);
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

BB_TEST(state_bank_accepts_complete_f3_second_half_turn_axis) {
    const size_t count = AD_F3_SECOND_HALF_AXIS_COUNT;
    ad_recipe* recipes = calloc(count, sizeof(*recipes));
    BB_CHECK(recipes != NULL);
    if (recipes == NULL) return;
    ad_bbs_record records[AD_F3_SECOND_HALF_AXIS_COUNT];
    char error[AD_ERROR_CAP];

    size_t index = 0;
    for (int team = BB_HOME; team <= BB_AWAY; team++) {
        for (int turn = 1; turn <= AD_F3_SECOND_HALF_TURN_COUNT; turn++) {
            ad_recipe* recipe = &recipes[index];
            *recipe = authored_test_recipe();
            recipe->controller_seed = 1000u +
                (uint64_t)(team * AD_F3_SECOND_HALF_TURN_COUNT + turn - 1);
            BB_CHECK_EQ(ad_discover_f3_second_half_turn(
                            recipe, turn, team, error),
                        0);
            records[index] = (ad_bbs_record){
                0xA3000100u + (uint32_t)index,
                (uint32_t)recipe->action_count,
                recipe,
            };
            index++;
        }
    }
    BB_CHECK_EQ(index, count);
    BB_CHECK_EQ(ad_validate_f3_second_half_turn_axis(
                    recipes, count, error),
                0);

    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-authored-f3-axis-%ld.bbs",
             (long)getpid());
    FILE* file = fopen(path, "wb");
    BB_CHECK(file != NULL);
    if (file == NULL) {
        free(recipes);
        return;
    }
    BB_CHECK_EQ(ad_bbs_write(file, records, count, error), 0);
    BB_CHECK_EQ(fclose(file), 0);

    reset_state_bank_loader(path);
    bbe_state_bank_load();
    BB_CHECK_EQ(bbe_state_bank_n, count);
    if (bbe_state_bank_n == (int)count) {
        unsigned char
            seen[BB_AWAY + 1][AD_F3_SECOND_HALF_TURN_COUNT] = {{0}};
        for (size_t i = 0; i < count; i++) {
            const bb_match* loaded = &bbe_state_bank[i];
            const ad_recipe* recipe = &recipes[i];
            BB_CHECK_EQ(memcmp(loaded, &recipe->captured, sizeof *loaded), 0);
            BB_CHECK(bb_state_bank_boundary_valid(loaded));
            BB_CHECK_EQ(loaded->half, 2);
            BB_CHECK_EQ(loaded->active_team,
                        recipe->capture_active_team);
            int loaded_team = loaded->active_team;
            if (loaded_team >= BB_HOME && loaded_team <= BB_AWAY) {
                int loaded_turn = loaded->turn[loaded_team];
                BB_CHECK_EQ(loaded_turn, recipe->capture_turn);
                if (loaded_turn >= 1 &&
                    loaded_turn <= AD_F3_SECOND_HALF_TURN_COUNT) {
                    seen[loaded_team][loaded_turn - 1]++;
                }
            }
            BB_CHECK_EQ(ad_verify_one_action_continuation(
                            loaded, NULL, NULL, NULL, error),
                        0);
        }
        for (int team = BB_HOME; team <= BB_AWAY; team++) {
            for (int turn_index = 0;
                 turn_index < AD_F3_SECOND_HALF_TURN_COUNT; turn_index++) {
                BB_CHECK_EQ(seen[team][turn_index], 1);
            }
        }
    }
    reset_state_bank_loader(BBE_STATE_BANK_PATH);
    BB_CHECK_EQ(remove(path), 0);
    free(recipes);
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

BB_TEST(state_bank_accepts_complete_f1_pass_carrier_pressure_axis) {
    static const uint64_t
        controller_seed[BB_AWAY + 1][AD_F1_PASS_CARRIER_PRESSURE_BUCKET_COUNT] = {
        {4, 2},
        {10, 8},
    };
    const size_t count = AD_F1_PASS_CARRIER_PRESSURE_AXIS_COUNT;
    ad_recipe* recipes = calloc(count, sizeof(*recipes));
    BB_CHECK(recipes != NULL);
    if (recipes == NULL) return;
    ad_bbs_record records[AD_F1_PASS_CARRIER_PRESSURE_AXIS_COUNT];
    char error[AD_ERROR_CAP];

    size_t index = 0;
    for (int team = BB_HOME; team <= BB_AWAY; team++) {
        for (int pressure = AD_F1_CARRIER_PRESSURE_OPEN;
             pressure <= AD_F1_CARRIER_PRESSURE_MARKED; pressure++) {
            ad_recipe* recipe = &recipes[index];
            *recipe = authored_test_recipe();
            recipe->controller_seed = controller_seed[team][pressure - 1];
            BB_CHECK_EQ(ad_discover_f1_pass_carrier_pressure(
                            recipe, team, pressure, error),
                        0);
            records[index] = (ad_bbs_record){
                0xA1000100u + (uint32_t)index,
                (uint32_t)recipe->action_count,
                recipe,
            };
            index++;
        }
    }
    BB_CHECK_EQ(index, count);
    BB_CHECK_EQ(ad_validate_f1_pass_carrier_pressure_axis(
                    recipes, count, error),
                0);

    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-authored-f1-axis-%ld.bbs",
             (long)getpid());
    FILE* file = fopen(path, "wb");
    BB_CHECK(file != NULL);
    if (file == NULL) {
        free(recipes);
        return;
    }
    BB_CHECK_EQ(ad_bbs_write(file, records, count, error), 0);
    BB_CHECK_EQ(fclose(file), 0);

    reset_state_bank_loader(path);
    bbe_state_bank_load();
    BB_CHECK_EQ(bbe_state_bank_n, count);
    if (bbe_state_bank_n == (int)count) {
        unsigned char
            seen[BB_AWAY + 1][AD_F1_PASS_CARRIER_PRESSURE_BUCKET_COUNT] = {{0}};
        for (size_t i = 0; i < count; i++) {
            const bb_match* loaded = &bbe_state_bank[i];
            const ad_recipe* recipe = &recipes[i];
            BB_CHECK_EQ(memcmp(loaded, &recipe->captured, sizeof *loaded), 0);
            BB_CHECK(bb_state_bank_boundary_valid(loaded));
            BB_CHECK(ad_f1_pass_opportunity_valid(loaded));
            BB_CHECK_EQ(loaded->active_team, recipe->capture_active_team);
            int carrier = loaded->ball.carrier;
            int pressure = bb_is_marked(loaded, carrier)
                ? AD_F1_CARRIER_PRESSURE_MARKED
                : AD_F1_CARRIER_PRESSURE_OPEN;
            BB_CHECK_EQ(pressure, recipe->capture_pass_carrier_pressure);
            int team = loaded->active_team;
            if (team >= BB_HOME && team <= BB_AWAY &&
                pressure >= AD_F1_CARRIER_PRESSURE_OPEN &&
                pressure <= AD_F1_CARRIER_PRESSURE_MARKED) {
                seen[team][pressure - 1]++;
            }
            BB_CHECK_EQ(ad_verify_one_action_continuation(
                            loaded, NULL, NULL, NULL, error),
                        0);
        }
        for (int team = BB_HOME; team <= BB_AWAY; team++) {
            for (int pressure_index = 0;
                 pressure_index < AD_F1_PASS_CARRIER_PRESSURE_BUCKET_COUNT;
                 pressure_index++) {
                BB_CHECK_EQ(seen[team][pressure_index], 1);
            }
        }
    }
    reset_state_bank_loader(BBE_STATE_BANK_PATH);
    BB_CHECK_EQ(remove(path), 0);
    free(recipes);
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

BB_TEST(state_bank_accepts_complete_f2_handoff_target_count_axis) {
    static const uint64_t
        controller_seed[BB_AWAY + 1][AD_F2_HANDOFF_TARGET_BUCKET_COUNT] = {
        {4, 2},
        {8, 13},
    };
    const size_t count = AD_F2_HANDOFF_TARGET_AXIS_COUNT;
    ad_recipe* recipes = calloc(count, sizeof(*recipes));
    BB_CHECK(recipes != NULL);
    if (recipes == NULL) return;
    ad_bbs_record records[AD_F2_HANDOFF_TARGET_AXIS_COUNT];
    char error[AD_ERROR_CAP];

    size_t index = 0;
    for (int team = BB_HOME; team <= BB_AWAY; team++) {
        for (int bucket = AD_F2_TARGET_COUNT_EXACTLY_ONE;
             bucket <= AD_F2_TARGET_COUNT_TWO_OR_MORE; bucket++) {
            ad_recipe* recipe = &recipes[index];
            *recipe = authored_test_recipe();
            recipe->controller_seed = controller_seed[team][bucket - 1];
            BB_CHECK_EQ(ad_discover_f2_handoff_target_count(
                            recipe, team, bucket, error),
                        0);
            records[index] = (ad_bbs_record){
                0xA2000100u + (uint32_t)index,
                (uint32_t)recipe->action_count,
                recipe,
            };
            index++;
        }
    }
    BB_CHECK_EQ(index, count);
    BB_CHECK_EQ(ad_validate_f2_handoff_target_count_axis(
                    recipes, count, error),
                0);

    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-authored-f2-axis-%ld.bbs",
             (long)getpid());
    FILE* file = fopen(path, "wb");
    BB_CHECK(file != NULL);
    if (file == NULL) {
        free(recipes);
        return;
    }
    BB_CHECK_EQ(ad_bbs_write(file, records, count, error), 0);
    BB_CHECK_EQ(fclose(file), 0);

    reset_state_bank_loader(path);
    bbe_state_bank_load();
    BB_CHECK_EQ(bbe_state_bank_n, count);
    if (bbe_state_bank_n == (int)count) {
        unsigned char
            seen[BB_AWAY + 1][AD_F2_HANDOFF_TARGET_BUCKET_COUNT] = {{0}};
        for (size_t i = 0; i < count; i++) {
            const bb_match* loaded = &bbe_state_bank[i];
            const ad_recipe* recipe = &recipes[i];
            BB_CHECK_EQ(memcmp(loaded, &recipe->captured, sizeof *loaded), 0);
            BB_CHECK(bb_state_bank_boundary_valid(loaded));
            BB_CHECK_EQ(loaded->active_team, recipe->capture_active_team);
            int target_count = ad_f2_handoff_target_count(loaded);
            int bucket = target_count == 1
                ? AD_F2_TARGET_COUNT_EXACTLY_ONE
                : AD_F2_TARGET_COUNT_TWO_OR_MORE;
            BB_CHECK(target_count > 0);
            BB_CHECK_EQ(bucket, recipe->capture_handoff_target_bucket);
            int team = loaded->active_team;
            if (team >= BB_HOME && team <= BB_AWAY &&
                bucket >= AD_F2_TARGET_COUNT_EXACTLY_ONE &&
                bucket <= AD_F2_TARGET_COUNT_TWO_OR_MORE) {
                seen[team][bucket - 1]++;
            }
            BB_CHECK_EQ(ad_verify_one_action_continuation(
                            loaded, NULL, NULL, NULL, error),
                        0);
        }
        for (int team = BB_HOME; team <= BB_AWAY; team++) {
            for (int bucket_index = 0;
                 bucket_index < AD_F2_HANDOFF_TARGET_BUCKET_COUNT;
                 bucket_index++) {
                BB_CHECK_EQ(seen[team][bucket_index], 1);
            }
        }
    }
    reset_state_bank_loader(BBE_STATE_BANK_PATH);
    BB_CHECK_EQ(remove(path), 0);
    free(recipes);
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

BB_TEST(state_bank_accepts_complete_authored_proof_bundle) {
    const size_t count = AD_AUTHORED_PROOF_BUNDLE_COUNT;
    ad_recipe* recipes = calloc(count, sizeof(*recipes));
    BB_CHECK(recipes != NULL);
    if (recipes == NULL) return;
    ad_bbs_record records[AD_AUTHORED_PROOF_BUNDLE_COUNT];
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_build_authored_proof_bundle(
                    recipes, count, records, count, error),
                0);
    BB_CHECK_EQ(ad_validate_authored_proof_bundle(recipes, count, error), 0);

    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-authored-proof-%ld.bbs",
             (long)getpid());
    FILE* file = fopen(path, "wb");
    BB_CHECK(file != NULL);
    if (file == NULL) {
        free(recipes);
        return;
    }
    BB_CHECK_EQ(ad_bbs_write(file, records, count, error), 0);
    BB_CHECK_EQ(fclose(file), 0);

    const size_t expected_bytes = 16 + count * (12 + sizeof(bb_match));
    uint8_t* first_bytes = malloc(expected_bytes);
    uint8_t* second_bytes = malloc(expected_bytes);
    BB_CHECK(first_bytes != NULL);
    BB_CHECK(second_bytes != NULL);
    if (first_bytes != NULL && second_bytes != NULL) {
        size_t first_read = 0;
        file = fopen(path, "rb");
        BB_CHECK(file != NULL);
        if (file != NULL) {
            first_read = fread(first_bytes, 1, expected_bytes, file);
            BB_CHECK_EQ(first_read, expected_bytes);
            if (first_read == expected_bytes) BB_CHECK_EQ(fgetc(file), EOF);
            BB_CHECK_EQ(fclose(file), 0);
        }

        size_t second_read = 0;
        file = tmpfile();
        BB_CHECK(file != NULL);
        if (file != NULL) {
            BB_CHECK_EQ(ad_bbs_write(file, records, count, error), 0);
            int seek_result = fseek(file, 0, SEEK_SET);
            BB_CHECK_EQ(seek_result, 0);
            if (seek_result == 0) {
                second_read = fread(second_bytes, 1, expected_bytes, file);
                BB_CHECK_EQ(second_read, expected_bytes);
                if (second_read == expected_bytes) BB_CHECK_EQ(fgetc(file), EOF);
            }
            if (first_read == expected_bytes &&
                second_read == expected_bytes) {
                BB_CHECK_EQ(memcmp(first_bytes, second_bytes, expected_bytes),
                            0);
            }
            BB_CHECK_EQ(fclose(file), 0);
        }
    }
    free(first_bytes);
    free(second_bytes);

    reset_state_bank_loader(path);
    bbe_state_bank_load();
    BB_CHECK_EQ(bbe_state_bank_n, count);
    if (bbe_state_bank_n == (int)count) {
        for (size_t i = 0; i < count; i++) {
            BB_CHECK_EQ(memcmp(&bbe_state_bank[i], &recipes[i].captured,
                               sizeof(bb_match)),
                        0);
            BB_CHECK_EQ(ad_verify_one_action_continuation(
                            &bbe_state_bank[i], NULL, NULL, NULL, error),
                        0);
        }
    }
    reset_state_bank_loader(BBE_STATE_BANK_PATH);
    BB_CHECK_EQ(remove(path), 0);
    free(recipes);
}
