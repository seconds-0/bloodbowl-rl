#define BB_TEST_MAIN
#include "bb_test.h"

#include <fcntl.h>
#include <signal.h>
#include <sys/wait.h>
#include <unistd.h>

/*
 * Compile the real binding callback against the minimal test-only vecenv ABI.
 * PUFFER_STRICT_ENV_CONFIG_TESTING is supplied by the Makefile target.
 */
#include "binding.c"

static int bbe_stage_pipe_fd = -1;

static void record_stage_to_pipe(int stage) {
    unsigned char byte = (unsigned char)stage;
    if (bbe_stage_pipe_fd >= 0) {
        ssize_t written = write(bbe_stage_pipe_fd, &byte, sizeof byte);
        if (written != (ssize_t)sizeof byte) _exit(120);
    }
}

static Dict one_item_dict(DictItem* item, const char* key, double value) {
    *item = (DictItem){.key = key, .value = value, .ptr = NULL};
    return (Dict){.items = item, .size = 1, .capacity = 1};
}

typedef enum {
    BBE_INVALID_HAZARD_ENGINE = 0,
    BBE_INVALID_HAZARD_MISSING_BANK,
    BBE_INVALID_HAZARD_EMPTY_STRATUM,
    BBE_INVALID_HAZARD_ENV_ALLOCATION,
} bbe_invalid_callback_hazard;

typedef struct {
    unsigned char stages[8];
    ssize_t stage_count;
    char diagnostic[512];
    ssize_t diagnostic_count;
    int wait_status;
} bbe_invalid_callback_outcome;

static void publish_empty_endzone_bank_or_exit(void) {
    static const char bbs_sha256[] =
        "1111111111111111111111111111111111111111111111111111111111111111";
    bbe_state_bank_candidate candidate = {0};
    candidate.matches = calloc(1, sizeof *candidate.matches);
    candidate.metadata = calloc(1, sizeof *candidate.metadata);
    if (candidate.matches == NULL || candidate.metadata == NULL) _exit(122);
    candidate.count = 1;
    candidate.kind = BBE_STATE_BANK_STRICT_REPLAY;
    candidate.matches[0].ball.state = BB_BALL_OFF_PITCH;
    candidate.matches[0].ball.carrier = BB_NO_PLAYER;
    candidate.matches[0].active_team = BB_HOME;
    bbe_state_bank_request request = {0};
    request.bbs_sha256 = bbs_sha256;
    if (bbe_state_bank_build_strata(
            &request, candidate.matches, candidate.count,
            &candidate.strata) != BBE_SB_OK) {
        _exit(123);
    }
    bbe_state_bank_test_publish_candidate(&candidate);
    bbe_state_bank_stratum_descriptor descriptor = {0};
    if (bbe_state_bank_copy_stratum_descriptor(
            BBE_STATE_BANK_SELECTOR_ENDZONE, 1, &descriptor) != BBE_SB_OK ||
        descriptor.eligible_records != 0) {
        _exit(124);
    }
}

static void wire_single_environment(Bloodbowl* env) {
    static uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    static float actions[BBE_AGENTS * 3];
    static unsigned char masks[BBE_AGENTS * BBE_MASK_SIZE];
    static float rewards[BBE_AGENTS];
    static float terminals[BBE_AGENTS];
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        env->obs_ptr[agent] = obs + agent * BBE_OBS_SIZE;
        env->action_ptr[agent] = actions + agent * 3;
        env->action_mask_ptr[agent] =
            masks + agent * BBE_MASK_SIZE;
        env->reward_ptr[agent] = rewards + agent;
        env->terminal_ptr[agent] = terminals + agent;
    }
}

static bbe_invalid_callback_outcome run_invalid_callback(
        int single_environment, bbe_invalid_callback_hazard hazard) {
    bbe_invalid_callback_outcome outcome = {
        .stage_count = -1,
        .diagnostic_count = -1,
        .wait_status = -1,
    };
    int stage_pipe[2];
    int diagnostic_pipe[2];
    if (pipe(stage_pipe) != 0 || pipe(diagnostic_pipe) != 0) return outcome;
    fflush(NULL);
    pid_t pid = fork();
    if (pid < 0) return outcome;
    if (pid == 0) {
        close(stage_pipe[0]);
        close(diagnostic_pipe[0]);
        if (dup2(diagnostic_pipe[1], STDERR_FILENO) < 0) _exit(125);
        close(diagnostic_pipe[1]);

        if (hazard == BBE_INVALID_HAZARD_EMPTY_STRATUM) {
            publish_empty_endzone_bank_or_exit();
        }
        bbe_stage_pipe_fd = stage_pipe[1];
        my_environment_config_native_test_reset();
        my_environment_config_native_test_set_stage_hook(
            record_stage_to_pipe);
        if (hazard == BBE_INVALID_HAZARD_ENV_ALLOCATION) {
            my_environment_config_native_test_fail_environment_allocation(1);
        }

        DictItem env_items[] = {
            {.key = "reward_dist_pbrs_gamma", .value = NAN},
            {.key = "demo_reset_pct", .value = 1.0},
            {.key = "state_bank_kind",
             .value = BBE_STATE_BANK_STRICT_REPLAY},
            {.key = "demo_endzone_maxdist", .value = 1.0},
        };
        int env_size =
            hazard == BBE_INVALID_HAZARD_EMPTY_STRATUM ? 4 :
            hazard == BBE_INVALID_HAZARD_MISSING_BANK ? 3 : 1;
        Dict env_kwargs = {
            .items = env_items,
            .size = env_size,
            .capacity = 4,
        };

        Bloodbowl* initialized = NULL;
        Bloodbowl direct = {0};
        if (single_environment) {
            wire_single_environment(&direct);
            my_init(&direct, &env_kwargs);
            initialized = &direct;
        } else {
            DictItem vec_items[] = {
                {.key = "total_agents", .value = 2.0},
                {.key = "num_buffers", .value = 1.0},
            };
            Dict vec_kwargs = {
                .items = vec_items, .size = 2, .capacity = 2};
            int starts[1] = {0};
            int counts[1] = {0};
            int num_envs = 0;
            initialized = my_vec_init(
                &num_envs, starts, counts, &vec_kwargs, &env_kwargs);
            if (initialized != NULL && num_envs > 0) {
                wire_single_environment(&initialized[0]);
            }
        }

        /*
         * If the invalid gamma were accepted, missing/empty-bank hazards fail
         * inside my_init/my_vec_init, allocation failure catches my_vec_init,
         * and the remaining controls reach the real engine-init seam here.
         */
        if (initialized != NULL &&
            hazard != BBE_INVALID_HAZARD_ENV_ALLOCATION) {
            c_reset(initialized);
        }
        _exit(121);
    }

    close(stage_pipe[1]);
    close(diagnostic_pipe[1]);
    outcome.stage_count =
        read(stage_pipe[0], outcome.stages, sizeof outcome.stages);
    close(stage_pipe[0]);
    outcome.diagnostic_count = read(
        diagnostic_pipe[0], outcome.diagnostic,
        sizeof outcome.diagnostic - 1);
    close(diagnostic_pipe[0]);
    if (outcome.diagnostic_count >= 0) {
        outcome.diagnostic[outcome.diagnostic_count] = '\0';
    }
    if (waitpid(pid, &outcome.wait_status, 0) != pid) {
        outcome.wait_status = -1;
    }
    return outcome;
}

BB_TEST(environment_config_public_schema_and_key_count_are_exact) {
    BB_CHECK(strcmp(
        my_environment_config_schema(),
        "bloodbowl-environment-config-v1") == 0);
    BB_CHECK_EQ(my_environment_config_key_count(), 51);
}

BB_TEST(environment_config_public_preflight_is_bounded_and_field_specific) {
    DictItem item;
    Dict env = one_item_dict(
        &item, "force_home_team", (double)BB_TEAM_COUNT);
    char diagnostic[256];
    BB_CHECK(my_environment_config_preflight(
                 &env, diagnostic, sizeof diagnostic) != 0);
    BB_CHECK(strstr(
        diagnostic,
        "force_home_team must be integer -1 or 0..BB_TEAM_COUNT-1") != NULL);

    Dict empty = {0};
    BB_CHECK_EQ(my_environment_config_preflight(
                    &empty, diagnostic, sizeof diagnostic),
                0);
    BB_CHECK_EQ(diagnostic[0], '\0');
}

BB_TEST(environment_config_invalid_callback_precedes_all_native_stages) {
    static const char expected_diagnostic[] =
        "bloodbowl: invalid environment configuration: "
        "reward_dist_pbrs_gamma must be finite in [0,1] and remain "
        "nonzero as float; got";
    for (int single_environment = 0; single_environment <= 1;
         single_environment++) {
        for (int hazard = BBE_INVALID_HAZARD_ENGINE;
             hazard <= BBE_INVALID_HAZARD_ENV_ALLOCATION; hazard++) {
            if (single_environment &&
                hazard == BBE_INVALID_HAZARD_ENV_ALLOCATION) {
                continue;
            }
            bbe_invalid_callback_outcome outcome = run_invalid_callback(
                single_environment,
                (bbe_invalid_callback_hazard)hazard);
            BB_CHECK_EQ(outcome.stage_count, 0);
            BB_CHECK(outcome.diagnostic_count > 0);
            BB_CHECK(strstr(
                         outcome.diagnostic,
                         expected_diagnostic) == outcome.diagnostic);
            BB_CHECK(WIFEXITED(outcome.wait_status));
            BB_CHECK_EQ(WEXITSTATUS(outcome.wait_status), 1);
        }
    }
}

BB_TEST(environment_config_my_init_preserves_or_applies_seed_exactly) {
    DictItem item;
    Dict env_kwargs = one_item_dict(&item, "seed", 123.0);

    Bloodbowl zero_seed = {0};
    my_init(&zero_seed, &env_kwargs);
    BB_CHECK(zero_seed.seed == UINT64_C(123));
    BB_CHECK_EQ(zero_seed.num_agents, BBE_AGENTS);

    Bloodbowl caller_seed = {.seed = UINT64_C(987654321)};
    my_init(&caller_seed, &env_kwargs);
    BB_CHECK(caller_seed.seed == UINT64_C(987654321));
    BB_CHECK_EQ(caller_seed.num_agents, BBE_AGENTS);
}

BB_TEST(environment_config_valid_callback_reaches_all_expected_stages) {
    my_environment_config_native_test_reset();
    DictItem vec_items[] = {
        {.key = "total_agents", .value = 4.0},
        {.key = "num_buffers", .value = 1.0},
    };
    Dict vec = {.items = vec_items, .size = 2, .capacity = 2};
    Dict env = {0};
    int starts[1] = {0};
    int counts[1] = {0};
    int num_envs = 0;
    Bloodbowl* envs = my_vec_init(
        &num_envs, starts, counts, &vec, &env);
    BB_CHECK(envs != NULL);
    BB_CHECK_EQ(num_envs, 2);
    BB_CHECK_EQ(
        my_environment_config_native_test_stage_count(
            BBE_STRICT_NATIVE_STAGE_ENV_ARRAY_ALLOC),
        1);
    BB_CHECK_EQ(
        my_environment_config_native_test_stage_count(
            BBE_STRICT_NATIVE_STAGE_STATE_BANK_REQUIRE),
        0);
    BB_CHECK_EQ(
        my_environment_config_native_test_stage_count(
            BBE_STRICT_NATIVE_STAGE_ENGINE_INIT),
        0);
    BB_CHECK(envs[0].seed == UINT64_C(1));
    BB_CHECK(envs[1].seed == UINT64_C(2));

    uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE] = {0};
    float actions[BBE_AGENTS * 3] = {0};
    unsigned char masks[BBE_AGENTS * BBE_MASK_SIZE] = {0};
    float rewards[BBE_AGENTS] = {0};
    float terminals[BBE_AGENTS] = {0};
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        envs[0].obs_ptr[agent] = obs + agent * BBE_OBS_SIZE;
        envs[0].action_ptr[agent] = actions + agent * 3;
        envs[0].action_mask_ptr[agent] =
            masks + agent * BBE_MASK_SIZE;
        envs[0].reward_ptr[agent] = rewards + agent;
        envs[0].terminal_ptr[agent] = terminals + agent;
    }
    c_reset(&envs[0]);
    BB_CHECK_EQ(
        my_environment_config_native_test_stage_count(
            BBE_STRICT_NATIVE_STAGE_ENGINE_INIT),
        1);
    free(envs);
}

BB_TEST(environment_config_bank_require_precedes_environment_allocation) {
    int stage_pipe[2];
    BB_CHECK_EQ(pipe(stage_pipe), 0);
    fflush(NULL);
    pid_t pid = fork();
    BB_CHECK(pid >= 0);
    if (pid == 0) {
        close(stage_pipe[0]);
        bbe_stage_pipe_fd = stage_pipe[1];
        my_environment_config_native_test_reset();
        my_environment_config_native_test_set_stage_hook(
            record_stage_to_pipe);
        int devnull = open("/dev/null", O_WRONLY);
        if (devnull >= 0) {
            (void)dup2(devnull, STDERR_FILENO);
            close(devnull);
        }

        DictItem vec_items[] = {
            {.key = "total_agents", .value = 4.0},
            {.key = "num_buffers", .value = 1.0},
        };
        Dict vec = {.items = vec_items, .size = 2, .capacity = 2};
        DictItem env_items[] = {
            {.key = "demo_reset_pct", .value = 1.0},
            {.key = "state_bank_kind",
             .value = BBE_STATE_BANK_STRICT_REPLAY},
        };
        Dict env = {.items = env_items, .size = 2, .capacity = 2};
        int starts[1] = {0};
        int counts[1] = {0};
        int num_envs = 0;
        (void)my_vec_init(
            &num_envs, starts, counts, &vec, &env);
        _exit(121);
    }

    close(stage_pipe[1]);
    unsigned char stages[8] = {0};
    ssize_t observed = read(stage_pipe[0], stages, sizeof stages);
    close(stage_pipe[0]);
    int status = 0;
    BB_CHECK_EQ(waitpid(pid, &status, 0), pid);
    BB_CHECK_EQ(observed, 1);
    if (observed == 1) {
        BB_CHECK_EQ(
            stages[0], BBE_STRICT_NATIVE_STAGE_STATE_BANK_REQUIRE);
    }
    BB_CHECK(WIFSIGNALED(status) || WIFEXITED(status));
    if (WIFEXITED(status)) {
        BB_CHECK(WEXITSTATUS(status) != 0);
    }
}

BB_TEST(environment_config_environment_allocation_failure_is_fail_closed) {
    int stage_pipe[2];
    BB_CHECK_EQ(pipe(stage_pipe), 0);
    fflush(NULL);
    pid_t pid = fork();
    BB_CHECK(pid >= 0);
    if (pid == 0) {
        close(stage_pipe[0]);
        bbe_stage_pipe_fd = stage_pipe[1];
        my_environment_config_native_test_reset();
        my_environment_config_native_test_set_stage_hook(
            record_stage_to_pipe);
        my_environment_config_native_test_fail_environment_allocation(1);
        int devnull = open("/dev/null", O_WRONLY);
        if (devnull >= 0) {
            (void)dup2(devnull, STDERR_FILENO);
            close(devnull);
        }
        DictItem vec_items[] = {
            {.key = "total_agents", .value = 4.0},
            {.key = "num_buffers", .value = 1.0},
        };
        Dict vec = {.items = vec_items, .size = 2, .capacity = 2};
        Dict env = {0};
        int starts[1] = {0};
        int counts[1] = {0};
        int num_envs = 0;
        (void)my_vec_init(
            &num_envs, starts, counts, &vec, &env);
        _exit(121);
    }

    close(stage_pipe[1]);
    unsigned char stages[8] = {0};
    ssize_t observed = read(stage_pipe[0], stages, sizeof stages);
    close(stage_pipe[0]);
    int status = 0;
    BB_CHECK_EQ(waitpid(pid, &status, 0), pid);
    BB_CHECK_EQ(observed, 1);
    if (observed == 1) {
        BB_CHECK_EQ(
            stages[0], BBE_STRICT_NATIVE_STAGE_ENV_ARRAY_ALLOC);
    }
    BB_CHECK(WIFEXITED(status));
    BB_CHECK_EQ(WEXITSTATUS(status), 1);
}
