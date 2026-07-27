#define BB_TEST_MAIN
#include "bb_test.h"
#include "bloodbowl.h"
#include "bb_fixtures.h"
#include "authored_drill.h"

#include <signal.h>
#include <sys/wait.h>
#include <unistd.h>

#define BBE_STATE_BANK_PATH PUFFER_STATE_BANK_BBS_PATH

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
    uint32_t source_id = bb_state_bank_boundary_valid(match)
                             ? 1u : UINT32_C(0xa9000001);
    write_state_bank_meta(path, match, source_id, match->half,
                          turn, 0);
}

static void write_state_bank_valid_invalid_pair(
        const char* path, const bb_match* valid) {
    FILE* file = fopen(path, "wb");
    BB_CHECK(file != NULL);
    if (file == NULL) return;

    BB_CHECK_EQ(fwrite("BBS1", 1, 4, file), 4);
    write_le32(file, 1u);
    write_le32(file, (uint32_t)sizeof(bb_match));
    write_le32(file, bbe_state_fingerprint());
    for (int record = 0; record < 2; record++) {
        uint8_t metadata[BBE_STATE_BANK_REC_META] = {0};
        uint32_t source_id = record == 0 ? 1u : 0u;
        metadata[0] = (uint8_t)source_id;
        metadata[1] = (uint8_t)(source_id >> 8);
        metadata[2] = (uint8_t)(source_id >> 16);
        metadata[3] = (uint8_t)(source_id >> 24);
        metadata[8] = valid->half;
        metadata[9] = valid->turn[valid->active_team];
        BB_CHECK_EQ(fwrite(metadata, 1, sizeof metadata, file),
                    sizeof metadata);
        BB_CHECK_EQ(fwrite(valid, sizeof *valid, 1, file), 1);
    }
    BB_CHECK_EQ(fclose(file), 0);
}

static void write_state_bank_pair(const char* path,
                                  const bb_match* first,
                                  const bb_match* second) {
    FILE* file = fopen(path, "wb");
    BB_CHECK(file != NULL);
    if (file == NULL) return;

    BB_CHECK_EQ(fwrite("BBS1", 1, 4, file), 4);
    write_le32(file, 1u);
    write_le32(file, (uint32_t)sizeof(bb_match));
    write_le32(file, bbe_state_fingerprint());
    const bb_match* matches[] = {first, second};
    for (uint32_t record = 0; record < 2; record++) {
        uint8_t metadata[BBE_STATE_BANK_REC_META] = {0};
        uint32_t source_id = record + 1u;
        metadata[0] = (uint8_t)source_id;
        metadata[1] = (uint8_t)(source_id >> 8);
        metadata[2] = (uint8_t)(source_id >> 16);
        metadata[3] = (uint8_t)(source_id >> 24);
        metadata[4] = (uint8_t)(0x40u + record);
        metadata[8] = matches[record]->half;
        metadata[9] =
            matches[record]->turn[matches[record]->active_team];
        BB_CHECK_EQ(fwrite(metadata, 1, sizeof metadata, file),
                    sizeof metadata);
        BB_CHECK_EQ(fwrite(matches[record], sizeof *matches[record], 1, file),
                    1);
    }
    BB_CHECK_EQ(fclose(file), 0);
}

static const char* test_state_bank_path;
static char test_producer_path[512];
static char test_contract_path[512];

static void remove_test_sidecars(void) {
    if (test_producer_path[0] != '\0') (void)remove(test_producer_path);
    if (test_contract_path[0] != '\0') (void)remove(test_contract_path);
    test_producer_path[0] = '\0';
    test_contract_path[0] = '\0';
}

static void reset_state_bank_loader(const char* path) {
    remove_test_sidecars();
    bbe_state_bank_test_reset_process();
    test_state_bank_path = path;
}

static int test_file_sha256(const char* path, char hex[65], size_t* size_out) {
    FILE* file = fopen(path, "rb");
    if (file == NULL) return -1;
    bbe_sha256 sha;
    bbe_sha256_init(&sha);
    size_t size = 0;
    uint8_t buffer[4096];
    for (;;) {
        size_t n = fread(buffer, 1, sizeof buffer, file);
        if (n != 0) {
            bbe_sha256_update(&sha, buffer, n);
            size += n;
        }
        if (n < sizeof buffer) {
            if (ferror(file)) {
                fclose(file);
                return -1;
            }
            break;
        }
    }
    if (fclose(file) != 0) return -1;
    uint8_t digest[32];
    bbe_sha256_final(&sha, digest);
    bbe_sha256_hex(digest, hex);
    if (size_out != NULL) *size_out = size;
    return 0;
}

static int write_test_sidecar(const char* path, const char* bytes,
                              char sha[65]) {
    FILE* file = fopen(path, "wb");
    if (file == NULL) return -1;
    size_t size = strlen(bytes);
    int ok = fwrite(bytes, 1, size, file) == size;
    if (fclose(file) != 0) ok = 0;
    return ok && test_file_sha256(path, sha, NULL) == 0 ? 0 : -1;
}

typedef struct {
    bbe_state_bank_request request;
    char bbs_sha[65];
    char producer_sha[65];
    char contract_sha[65];
    char producer_path[512];
    char contract_path[512];
} TestCandidateRequest;

static int prepare_test_candidate_request(
        TestCandidateRequest* fixture, const char* bbs_path, int kind,
        int test_only_allow_authored) {
    memset(fixture, 0, sizeof *fixture);
    size_t bbs_size = 0;
    if (test_file_sha256(bbs_path, fixture->bbs_sha, &bbs_size) != 0) return -1;
    int n = snprintf(fixture->producer_path, sizeof fixture->producer_path,
                     "%s.candidate.producer.json", bbs_path);
    if (n <= 0 || (size_t)n >= sizeof fixture->producer_path) return -1;
    n = snprintf(fixture->contract_path, sizeof fixture->contract_path,
                 "%s.candidate.contract.json", bbs_path);
    if (n <= 0 || (size_t)n >= sizeof fixture->contract_path) return -1;
    if (write_test_sidecar(
            fixture->producer_path, "{\"test\":\"producer\"}\n",
            fixture->producer_sha) != 0 ||
        write_test_sidecar(
            fixture->contract_path, "{\"test\":\"contract\"}\n",
            fixture->contract_sha) != 0) {
        return -1;
    }
    size_t record_size = BBE_STATE_BANK_REC_META + sizeof(bb_match);
    size_t records = bbs_size >= 16u ? (bbs_size - 16u) / record_size : 0;
    fixture->request = (bbe_state_bank_request){
        "bloodbowl-state-bank-training-contract-v1",
        "bloodbowl-state-bank-producer-v1",
        "bloodbowl-state-bank-authorization-v1",
        kind,
        kind == BBE_STATE_BANK_AUTHORED_SCENARIO
            ? "authored-scenario" : "strict-replay",
        "BB2025",
        fixture->bbs_sha,
        fixture->producer_sha,
        fixture->contract_sha,
        "0000000000000000000000000000000000000000000000000000000000000000",
        "1111111111111111111111111111111111111111111111111111111111111111",
        bbs_size,
        records,
        1,
        sizeof(bb_match),
        bbe_state_fingerprint(),
        "candidate-test-only",
        bbs_path,
        fixture->producer_path,
        fixture->contract_path,
        test_only_allow_authored,
    };
    return 0;
}

static void cleanup_test_candidate_request(TestCandidateRequest* fixture) {
    (void)remove(fixture->producer_path);
    (void)remove(fixture->contract_path);
}

/*
 * Legacy behavior tests load through the pure candidate seam and publish via
 * a test-build-only helper. Production never gains a mutable path/hash API.
 */
static void bbe_state_bank_load(void) {
    if (test_state_bank_path == NULL) return;
    char bbs_sha[65], producer_sha[65], contract_sha[65];
    size_t bbs_size = 0;
    if (test_file_sha256(test_state_bank_path, bbs_sha, &bbs_size) != 0) return;
    int n = snprintf(test_producer_path, sizeof test_producer_path,
                     "%s.producer.json", test_state_bank_path);
    if (n <= 0 || (size_t)n >= sizeof test_producer_path) return;
    n = snprintf(test_contract_path, sizeof test_contract_path,
                 "%s.contract.json", test_state_bank_path);
    if (n <= 0 || (size_t)n >= sizeof test_contract_path) return;
    if (write_test_sidecar(test_producer_path, "{\"test\":\"producer\"}\n",
                           producer_sha) != 0 ||
        write_test_sidecar(test_contract_path, "{\"test\":\"contract\"}\n",
                           contract_sha) != 0) {
        return;
    }

    FILE* file = fopen(test_state_bank_path, "rb");
    if (file == NULL) return;
    uint8_t prefix[28];
    size_t prefix_n = fread(prefix, 1, sizeof prefix, file);
    fclose(file);
    if (prefix_n != sizeof prefix || bbs_size < 16u) return;
    uint32_t source_id = bbe_state_bank_le32(prefix + 16);
    int authored =
        (source_id & UINT32_C(0xf0000000)) == UINT32_C(0xa0000000);
    size_t record_size = BBE_STATE_BANK_REC_META + sizeof(bb_match);
    size_t records = (bbs_size - 16u) / record_size;
    bbe_state_bank_request request = {
        "bloodbowl-state-bank-training-contract-v1",
        "bloodbowl-state-bank-producer-v1",
        "bloodbowl-state-bank-authorization-v1",
        authored ? BBE_STATE_BANK_AUTHORED_SCENARIO
                 : BBE_STATE_BANK_STRICT_REPLAY,
        authored ? "authored-scenario" : "strict-replay",
        "BB2025",
        bbs_sha,
        producer_sha,
        contract_sha,
        "0000000000000000000000000000000000000000000000000000000000000000",
        "1111111111111111111111111111111111111111111111111111111111111111",
        bbs_size,
        records,
        1,
        sizeof(bb_match),
        bbe_state_fingerprint(),
        "candidate-test-only",
        test_state_bank_path,
        test_producer_path,
        test_contract_path,
        authored,
    };
    bbe_state_bank_candidate candidate;
    bbe_state_bank_error error =
        bbe_state_bank_load_candidate(&request, &candidate);
    if (error == BBE_SB_OK) {
        // Historical resume/PBRS behavior tests exercise nested authored
        // proof states through this test-only publication route. Production
        // publication rejects authored kind before loading.
        candidate.kind = BBE_STATE_BANK_STRICT_REPLAY;
        bbe_state_bank_test_publish_candidate(&candidate);
    }
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
    env->state_bank_kind = bbe_state_bank_test_publication
                               ? bbe_state_bank_loaded_kind
                               : BBE_STATE_BANK_STRICT_REPLAY;
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

static void check_state_bank_child_aborted(
        pid_t child, const char* normal_exit_meaning) {
    int status = 0;
    BB_CHECK_EQ(waitpid(child, &status, 0), child);
    if (WIFEXITED(status)) {
        printf("OBSERVED %s: child exited %d instead of aborting\n",
               normal_exit_meaning, WEXITSTATUS(status));
    } else if (WIFSIGNALED(status) && WTERMSIG(status) != SIGABRT) {
        printf("OBSERVED unexpected signal %d instead of SIGABRT\n",
               WTERMSIG(status));
    }
    BB_CHECK(WIFSIGNALED(status));
    if (WIFSIGNALED(status)) {
        BB_CHECK_EQ(WTERMSIG(status), SIGABRT);
    }
}

static void check_state_bank_child_succeeded(
        pid_t child, const char* expected_success) {
    int status = 0;
    BB_CHECK_EQ(waitpid(child, &status, 0), child);
    int succeeded = WIFEXITED(status) && WEXITSTATUS(status) == 0;
    if (!succeeded) {
        if (WIFSIGNALED(status)) {
            printf("OBSERVED %s: child received signal %d\n",
                   expected_success, WTERMSIG(status));
        } else if (WIFEXITED(status)) {
            printf("OBSERVED %s: child exited %d\n",
                   expected_success, WEXITSTATUS(status));
        }
    }
    BB_CHECK(succeeded);
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
    fixture.env.state_bank_kind = BBE_STATE_BANK_NONE;
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

BB_TEST(state_bank_required_missing_aborts_instead_of_procgen) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-missing-required-%ld.bbs",
             (long)getpid());
    (void)remove(path);
    reset_state_bank_loader(path);

    fflush(NULL);
    pid_t child = fork();
    BB_CHECK(child >= 0);
    if (child == 0) {
        FILE* sink = freopen("/dev/null", "w", stderr);
        (void)sink;
        StateBankEnvFixture fixture;
        configure_restored_pbrs_env(&fixture, 0.0f, 0.0f, 0.995f);
        c_reset(&fixture.env);
        int silently_used_procgen =
            fixture.env.demo_started == 0 &&
            fixture.env.match.status == BB_STATUS_DECISION;
        _exit(silently_used_procgen ? 41 : 42);
    }
    if (child > 0) {
        check_state_bank_child_aborted(
            child, "missing required bank reached a procedural decision");
    }

    bb_stall_attach(0);
    reset_state_bank_loader(BBE_STATE_BANK_PATH);
}

BB_TEST(state_bank_mixed_valid_invalid_rejects_all_records) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-mixed-bank-%ld.bbs",
             (long)getpid());
    bb_match valid = valid_bank_match();
    BB_CHECK(bb_state_bank_resumable_valid(&valid));
    write_state_bank_valid_invalid_pair(path, &valid);

    reset_state_bank_loader(path);
    bbe_state_bank_load();
    if (bbe_state_bank_n != 0) {
        printf("OBSERVED mixed valid/invalid bank published %d-record subset\n",
               bbe_state_bank_n);
    }
    BB_CHECK_EQ(bbe_state_bank_n, 0);

    cleanup_state_bank_path(path);
}

BB_TEST(state_bank_selector_miss_aborts_instead_of_last_random_record) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-selector-miss-%ld.bbs",
             (long)getpid());
    bb_match restored = valid_bank_match();
    BB_CHECK_EQ(restored.ball.state, BB_BALL_OFF_PITCH);
    BB_CHECK(bb_state_bank_boundary_valid(&restored));
    write_state_bank(path, &restored);
    reset_state_bank_loader(path);

    fflush(NULL);
    pid_t child = fork();
    BB_CHECK(child >= 0);
    if (child == 0) {
        FILE* sink = freopen("/dev/null", "w", stderr);
        (void)sink;
        StateBankEnvFixture fixture;
        configure_restored_pbrs_env(&fixture, 0.0f, 0.0f, 0.995f);
        fixture.env.demo_endzone_maxdist = 1;
        c_reset(&fixture.env);
        int silently_used_nonqualifying_record =
            fixture.env.demo_started == 1 &&
            fixture.env.log.demo_fallbacks == 0.0f &&
            memcmp(&fixture.env.match, &restored, sizeof restored) == 0;
        _exit(silently_used_nonqualifying_record ? 51 : 52);
    }
    if (child > 0) {
        check_state_bank_child_aborted(
            child, "selector miss used the last nonqualifying random record");
    }

    cleanup_state_bank_path(path);
}

BB_TEST(state_bank_qualifying_endzone_selector_resets_exact_record) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-endzone-stratum-%ld.bbs",
             (long)getpid());
    bb_match nonqualifying = valid_bank_match();
    fx_ball_held(&nonqualifying, 0);
    bb_match qualifying = nonqualifying;
    bb_place(&qualifying, 0, 20, 7);
    fx_ball_held(&qualifying, 0);
    BB_CHECK(bb_state_bank_boundary_valid(&nonqualifying));
    BB_CHECK(bb_state_bank_boundary_valid(&qualifying));
    write_state_bank_pair(path, &nonqualifying, &qualifying);
    reset_state_bank_loader(path);
    bbe_state_bank_load();
    BB_CHECK_EQ(bbe_state_bank_n, 2);

    fflush(NULL);
    pid_t child = fork();
    BB_CHECK(child >= 0);
    if (child == 0) {
        StateBankEnvFixture fixture;
        configure_restored_pbrs_env(&fixture, 0.0f, 0.0f, 0.995f);
        fixture.env.demo_endzone_maxdist = 6;
        for (int reset = 0; reset < 8; reset++) {
            c_reset(&fixture.env);
            if (fixture.env.demo_started != 1) _exit(61);
            if (memcmp(&fixture.env.match, &qualifying,
                       sizeof qualifying) != 0) {
                _exit(62);
            }
        }
        _exit(0);
    }
    if (child > 0) {
        check_state_bank_child_succeeded(
            child, "qualifying endzone selector should reset successfully");
    }
    cleanup_state_bank_path(path);
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

static void check_sha256_literal(const uint8_t* bytes, size_t size,
                                 const char* expected) {
    uint8_t digest[32];
    char actual[65];
    bbe_sha256_bytes(bytes, size, digest);
    bbe_sha256_hex(digest, actual);
    BB_CHECK_EQ(strcmp(actual, expected), 0);

    bbe_sha256 incremental;
    bbe_sha256_init(&incremental);
    for (size_t i = 0; i < size; i++) {
        bbe_sha256_update(&incremental, bytes + i, 1);
    }
    bbe_sha256_final(&incremental, digest);
    bbe_sha256_hex(digest, actual);
    BB_CHECK_EQ(strcmp(actual, expected), 0);
}

BB_TEST(state_bank_sha256_independent_standard_vectors) {
    static const uint8_t empty[] = "";
    static const uint8_t abc[] = "abc";
    static const uint8_t multiblock[] =
        "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq";
    check_sha256_literal(
        empty, 0,
        "e3b0c44298fc1c149afbf4c8996fb924"
        "27ae41e4649b934ca495991b7852b855");
    check_sha256_literal(
        abc, 3,
        "ba7816bf8f01cfea414140de5dae2223"
        "b00361a396177a9cb410ff61f20015ad");
    check_sha256_literal(
        multiblock, sizeof multiblock - 1,
        "248d6a61d20638b8e5c026930c3e6039"
        "a33ce45964ff2167f6ecedd419db06c1");
}

BB_TEST(state_bank_sha256_padding_boundaries) {
    static const char* const expected[] = {
        "463eb28e72f82e0a96c0a4cc53690c57"
        "1281131f672aa229e0d45ae59b598b59",
        "da2ae4d6b36748f2a318f23e7ab1dfd"
        "f45acdc9d049bd80e59de82a60895f562",
        "29af2686fd53374a36b0846694cc34217"
        "7e428d1647515f078784d69cdb9e488",
        "fdeab9acf3710362bd2658cdc9a29e8f9"
        "c757fcf9811603a8c447cd1d9151108",
        "4bfd2c8b6f1eec7a2afeb48b934ee4b2"
        "694182027e6d0fc075074f2fabb31781",
    };
    static const size_t lengths[] = {55, 56, 63, 64, 65};
    uint8_t bytes[65];
    for (size_t i = 0; i < sizeof bytes; i++) bytes[i] = (uint8_t)i;
    for (size_t i = 0; i < sizeof lengths / sizeof lengths[0]; i++) {
        check_sha256_literal(bytes, lengths[i], expected[i]);
    }
}

BB_TEST(state_bank_config_rejects_raw_conversion_traps) {
    bbe_state_bank_config_values values = {
        0.0, BBE_STATE_BANK_NONE, 0.0, 0.0, 0.0, 0.0,
        -1.0, -1.0, -1.0,
    };
    BB_CHECK_EQ(bbe_state_bank_validate_config_values(
                    &values, BBE_STATE_BANK_STRICT_REPLAY),
                BBE_SB_OK);

    values.reset_pct = NAN;
    BB_CHECK_EQ(bbe_state_bank_validate_config_values(
                    &values, BBE_STATE_BANK_STRICT_REPLAY),
                BBE_SB_CONFIG_RESET_PCT);
    values.reset_pct = 2.0;
    BB_CHECK_EQ(bbe_state_bank_validate_config_values(
                    &values, BBE_STATE_BANK_STRICT_REPLAY),
                BBE_SB_CONFIG_RESET_PCT);
    values.reset_pct = 0x1p-1074;
    BB_CHECK_EQ(bbe_state_bank_validate_config_values(
                    &values, BBE_STATE_BANK_STRICT_REPLAY),
                BBE_SB_CONFIG_RESET_PCT_UNDERFLOW);

    values.reset_pct = 1.0;
    values.kind = 1.5;
    BB_CHECK_EQ(bbe_state_bank_validate_config_values(
                    &values, BBE_STATE_BANK_STRICT_REPLAY),
                BBE_SB_CONFIG_KIND);
    values.kind = BBE_STATE_BANK_AUTHORED_SCENARIO;
    BB_CHECK_EQ(bbe_state_bank_validate_config_values(
                    &values, BBE_STATE_BANK_STRICT_REPLAY),
                BBE_SB_REQUEST_AUTHORED_DISABLED);
    values.kind = BBE_STATE_BANK_NONE;
    BB_CHECK_EQ(bbe_state_bank_validate_config_values(
                    &values, BBE_STATE_BANK_STRICT_REPLAY),
                BBE_SB_CONFIG_MISSING_KIND);
    values.kind = BBE_STATE_BANK_STRICT_REPLAY;
    BB_CHECK_EQ(bbe_state_bank_validate_config_values(
                    &values, BBE_STATE_BANK_NONE),
                BBE_SB_CONFIG_KIND_MISMATCH);
    values.exclude_team = NAN;
    BB_CHECK_EQ(bbe_state_bank_validate_config_values(
                    &values, BBE_STATE_BANK_STRICT_REPLAY),
                BBE_SB_CONFIG_TEAM_SENTINEL);
    values.exclude_team = -1.0;
    values.endzone_selector = 1.5;
    BB_CHECK_EQ(bbe_state_bank_validate_config_values(
                    &values, BBE_STATE_BANK_STRICT_REPLAY),
                BBE_SB_CONFIG_SELECTOR);
    values.endzone_selector = 1.0;
    values.pickup_selector = 1.0;
    BB_CHECK_EQ(bbe_state_bank_validate_config_values(
                    &values, BBE_STATE_BANK_STRICT_REPLAY),
                BBE_SB_CONFIG_MULTIPLE_SELECTORS);
    values.pickup_selector = 0.0;
    BB_CHECK_EQ(bbe_state_bank_validate_config_values(
                    &values, BBE_STATE_BANK_STRICT_REPLAY),
                BBE_SB_CONFIG_SELECTOR_BRIDGE);
    values.reset_pct = 0.0;
    BB_CHECK_EQ(bbe_state_bank_validate_config_values(
                    &values, BBE_STATE_BANK_STRICT_REPLAY),
                BBE_SB_CONFIG_INERT_SELECTOR);
    values.endzone_selector = 0.0;
    BB_CHECK_EQ(bbe_state_bank_validate_config_values(
                    &values, BBE_STATE_BANK_STRICT_REPLAY),
                BBE_SB_CONFIG_INERT_KIND);
}

static void check_state_bank_selector_range_error(
        const bbe_state_bank_config_values* values,
        const char* expected_error) {
    bbe_state_bank_error actual = bbe_state_bank_validate_config_values(
        values, BBE_STATE_BANK_STRICT_REPLAY);
    const char* actual_error = bbe_state_bank_error_name(actual);
    if (strcmp(actual_error, expected_error) != 0) {
        printf("OBSERVED selector range error: got \"%s\", expected \"%s\"\n",
               actual_error, expected_error);
    }
    BB_CHECK_EQ(strcmp(actual_error, expected_error), 0);
}

BB_TEST(state_bank_endzone_selector_rejects_upper_bound_26) {
    const bbe_state_bank_config_values values = {
        1.0, BBE_STATE_BANK_STRICT_REPLAY, 26.0, 0.0, 0.0, 0.0,
        -1.0, -1.0, -1.0,
    };
    check_state_bank_selector_range_error(
        &values,
        "demo_endzone_maxdist must be an exact integer in [0,25]");
}

BB_TEST(state_bank_pickup_selector_rejects_upper_bound_26) {
    const bbe_state_bank_config_values values = {
        1.0, BBE_STATE_BANK_STRICT_REPLAY, 0.0, 26.0, 0.0, 0.0,
        -1.0, -1.0, -1.0,
    };
    check_state_bank_selector_range_error(
        &values,
        "demo_pickup_maxdist must be an exact integer in [0,25]");
}

BB_TEST(state_bank_postkick_selector_rejects_upper_bound_9) {
    const bbe_state_bank_config_values values = {
        1.0, BBE_STATE_BANK_STRICT_REPLAY, 0.0, 0.0, 9.0, 0.0,
        -1.0, -1.0, -1.0,
    };
    check_state_bank_selector_range_error(
        &values,
        "demo_postkick_maxturn must be an exact integer in [0,8]");
}

BB_TEST(state_bank_pass_selector_rejects_upper_bound_26) {
    const bbe_state_bank_config_values values = {
        1.0, BBE_STATE_BANK_STRICT_REPLAY, 0.0, 0.0, 0.0, 26.0,
        -1.0, -1.0, -1.0,
    };
    check_state_bank_selector_range_error(
        &values,
        "demo_pass_maxrange must be an exact integer in [0,25]");
}

BB_TEST(state_bank_request_paths_are_nonempty_and_bounded) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-request-path-%ld.bbs",
             (long)getpid());
    bb_match match = valid_bank_match();
    write_state_bank(path, &match);
    TestCandidateRequest fixture;
    BB_CHECK_EQ(prepare_test_candidate_request(
                    &fixture, path, BBE_STATE_BANK_STRICT_REPLAY, 0),
                0);
    BB_CHECK_EQ(bbe_state_bank_validate_request(&fixture.request, 0),
                BBE_SB_OK);
    fixture.request.bbs_path = "";
    BB_CHECK_EQ(bbe_state_bank_validate_request(&fixture.request, 0),
                BBE_SB_REQUEST_PATH_TOO_LONG);

    char maximum[BBE_STATE_BANK_MAX_PATH];
    memset(maximum, 'x', sizeof maximum);
    maximum[sizeof maximum - 1] = '\0';
    fixture.request.bbs_path = maximum;
    BB_CHECK_EQ(bbe_state_bank_validate_request(&fixture.request, 0),
                BBE_SB_OK);

    char too_long[BBE_STATE_BANK_MAX_PATH + 1];
    memset(too_long, 'x', sizeof too_long);
    too_long[sizeof too_long - 1] = '\0';
    fixture.request.bbs_path = too_long;
    BB_CHECK_EQ(bbe_state_bank_validate_request(&fixture.request, 0),
                BBE_SB_REQUEST_PATH_TOO_LONG);

    cleanup_test_candidate_request(&fixture);
    BB_CHECK_EQ(remove(path), 0);
}

BB_TEST(state_bank_resource_limits_are_hard_and_boundary_inclusive) {
    char bbs_path[256];
    snprintf(bbs_path, sizeof bbs_path,
             "/tmp/bloodbowl-request-limits-%ld.bbs", (long)getpid());
    bb_match match = valid_bank_match();
    write_state_bank(bbs_path, &match);
    TestCandidateRequest fixture;
    BB_CHECK_EQ(prepare_test_candidate_request(
                    &fixture, bbs_path, BBE_STATE_BANK_STRICT_REPLAY, 0),
                0);

    bbe_state_bank_request request = fixture.request;
    request.bbs_bytes = BBE_STATE_BANK_MAX_BBS_BYTES + 1u;
    BB_CHECK_EQ(bbe_state_bank_validate_request(&request, 0),
                BBE_SB_REQUEST_LIMIT);

    request = fixture.request;
    request.records = BBE_STATE_BANK_MAX_RECORDS + 1u;
    BB_CHECK_EQ(bbe_state_bank_validate_request(&request, 0),
                BBE_SB_REQUEST_LIMIT);

    const uint64_t record_bytes =
        BBE_STATE_BANK_REC_META + (uint64_t)sizeof(bb_match);
    const uint64_t maximum_fitting_records =
        (BBE_STATE_BANK_MAX_BBS_BYTES - 16u) / record_bytes;
    request = fixture.request;
    request.records = maximum_fitting_records;
    request.bbs_bytes = 16u + maximum_fitting_records * record_bytes;
    BB_CHECK(request.bbs_bytes <= BBE_STATE_BANK_MAX_BBS_BYTES);
    BB_CHECK_EQ(bbe_state_bank_validate_request(&request, 0), BBE_SB_OK);

    char manifest_path[256];
    snprintf(manifest_path, sizeof manifest_path,
             "/tmp/bloodbowl-manifest-limits-%ld.json", (long)getpid());
    int fd = open(manifest_path, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    BB_CHECK(fd >= 0);
    if (fd >= 0) {
        BB_CHECK_EQ(ftruncate(
                        fd, (off_t)BBE_STATE_BANK_MAX_MANIFEST_BYTES),
                    0);
        BB_CHECK_EQ(close(fd), 0);
        BB_CHECK_EQ(bbe_state_bank_check_manifest(
                        manifest_path,
                        "0000000000000000000000000000000000000000000000000000000000000000",
                        BBE_SB_CONTRACT_OPEN, BBE_SB_CONTRACT_NOT_REGULAR,
                        BBE_SB_CONTRACT_SIZE, BBE_SB_CONTRACT_READ,
                        BBE_SB_CONTRACT_HASH),
                    BBE_SB_CONTRACT_HASH);

        fd = open(manifest_path, O_WRONLY);
        BB_CHECK(fd >= 0);
        if (fd >= 0) {
            BB_CHECK_EQ(ftruncate(
                            fd,
                            (off_t)(BBE_STATE_BANK_MAX_MANIFEST_BYTES + 1u)),
                        0);
            BB_CHECK_EQ(close(fd), 0);
            BB_CHECK_EQ(bbe_state_bank_check_manifest(
                            manifest_path,
                            "0000000000000000000000000000000000000000000000000000000000000000",
                            BBE_SB_CONTRACT_OPEN,
                            BBE_SB_CONTRACT_NOT_REGULAR,
                            BBE_SB_CONTRACT_SIZE, BBE_SB_CONTRACT_READ,
                            BBE_SB_CONTRACT_HASH),
                        BBE_SB_CONTRACT_SIZE);
        }
        BB_CHECK_EQ(remove(manifest_path), 0);
    }

    cleanup_test_candidate_request(&fixture);
    BB_CHECK_EQ(remove(bbs_path), 0);
}

BB_TEST(state_bank_candidate_retains_metadata_and_never_publishes) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-candidate-%ld.bbs",
             (long)getpid());
    bb_match match = valid_bank_match();
    write_state_bank_meta(path, &match, 0x1234u, match.half,
                          match.turn[match.active_team], 0);
    TestCandidateRequest fixture;
    BB_CHECK_EQ(prepare_test_candidate_request(
                    &fixture, path, BBE_STATE_BANK_STRICT_REPLAY, 0),
                0);
    bbe_state_bank_test_reset_process();
    bbe_state_bank_candidate candidate;
    BB_CHECK_EQ(bbe_state_bank_load_candidate(
                    &fixture.request, &candidate),
                BBE_SB_OK);
    BB_CHECK_EQ(candidate.count, 1);
    BB_CHECK_EQ(candidate.kind, BBE_STATE_BANK_STRICT_REPLAY);
    BB_CHECK_EQ(candidate.metadata[0].source_id, 0x1234u);
    BB_CHECK_EQ(candidate.metadata[0].command, 0u);
    BB_CHECK_EQ(candidate.metadata[0].half, match.half);
    BB_CHECK_EQ(candidate.metadata[0].turn,
                match.turn[match.active_team]);
    BB_CHECK_EQ(memcmp(&candidate.matches[0], &match, sizeof match), 0);
    BB_CHECK_EQ(bbe_state_bank_status, BBE_SB_UNTRIED);
    BB_CHECK(bbe_state_bank == NULL);
    bbe_state_bank_candidate_close(&candidate);
    cleanup_test_candidate_request(&fixture);
    BB_CHECK_EQ(remove(path), 0);
}

BB_TEST(state_bank_authored_is_candidate_only_and_production_rejected) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-authored-candidate-%ld.bbs",
             (long)getpid());
    bb_match match = pending_dodge_reroll_match();
    write_state_bank(path, &match);
    TestCandidateRequest fixture;
    BB_CHECK_EQ(prepare_test_candidate_request(
                    &fixture, path, BBE_STATE_BANK_AUTHORED_SCENARIO, 1),
                0);
    bbe_state_bank_candidate candidate;
    BB_CHECK_EQ(bbe_state_bank_load_candidate(
                    &fixture.request, &candidate),
                BBE_SB_OK);
    BB_CHECK_EQ(candidate.kind, BBE_STATE_BANK_AUTHORED_SCENARIO);
    bbe_state_bank_candidate_close(&candidate);

    bbe_state_bank_test_reset_process();
    fixture.request.test_only_allow_authored = 0;
    BB_CHECK_EQ(bbe_state_bank_require_core(&fixture.request),
                BBE_SB_REQUEST_AUTHORED_DISABLED);
    BB_CHECK_EQ(bbe_state_bank_status, BBE_SB_FAILED);
    BB_CHECK(bbe_state_bank == NULL);
    bbe_state_bank_test_reset_process();
    cleanup_test_candidate_request(&fixture);
    BB_CHECK_EQ(remove(path), 0);
}

BB_TEST(state_bank_process_identity_covers_every_request_string) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-identity-%ld.bbs",
             (long)getpid());
    bb_match match = valid_bank_match();
    write_state_bank(path, &match);
    TestCandidateRequest fixture;
    BB_CHECK_EQ(prepare_test_candidate_request(
                    &fixture, path, BBE_STATE_BANK_STRICT_REPLAY, 0),
                0);
    bbe_state_bank_test_reset_process();
    BB_CHECK_EQ(bbe_state_bank_require_core(&fixture.request), BBE_SB_OK);
    BB_CHECK_EQ(bbe_state_bank_status, BBE_SB_READY);
    BB_CHECK_EQ(bbe_state_bank_publications, 1u);
    BB_CHECK_EQ(bbe_state_bank_load_attempts, 1u);
    BB_CHECK_EQ(bbe_state_bank_require_core(&fixture.request), BBE_SB_OK);
    BB_CHECK_EQ(bbe_state_bank_publications, 1u);

#define CHECK_IDENTITY_STRING(field, replacement)                              \
    do {                                                                       \
        bbe_state_bank_request changed = fixture.request;                      \
        changed.field = replacement;                                           \
        BB_CHECK_EQ(bbe_state_bank_require_core(&changed),                     \
                    BBE_SB_IDENTITY_CONFLICT);                                 \
    } while (0)
    CHECK_IDENTITY_STRING(contract_schema, "different-contract-schema");
    CHECK_IDENTITY_STRING(producer_schema, "different-producer-schema");
    CHECK_IDENTITY_STRING(authorization_schema, "different-auth-schema");
    CHECK_IDENTITY_STRING(kind_name, "different-kind");
    CHECK_IDENTITY_STRING(ruleset, "different-ruleset");
    CHECK_IDENTITY_STRING(contract_identity, "different-identity");
    CHECK_IDENTITY_STRING(bbs_sha256,
                          "2222222222222222222222222222222222222222222222222222222222222222");
    CHECK_IDENTITY_STRING(
        producer_manifest_sha256,
        "2222222222222222222222222222222222222222222222222222222222222222");
    CHECK_IDENTITY_STRING(
        training_contract_sha256,
        "2222222222222222222222222222222222222222222222222222222222222222");
    CHECK_IDENTITY_STRING(
        producer_engine_source_sha256,
        "2222222222222222222222222222222222222222222222222222222222222222");
    CHECK_IDENTITY_STRING(
        loader_engine_source_sha256,
        "2222222222222222222222222222222222222222222222222222222222222222");
    CHECK_IDENTITY_STRING(bbs_path, "/tmp/different-bank.bbs");
    CHECK_IDENTITY_STRING(producer_manifest_path, "/tmp/different-producer");
    CHECK_IDENTITY_STRING(training_contract_path, "/tmp/different-contract");
#undef CHECK_IDENTITY_STRING
    bbe_state_bank_request numeric = fixture.request;
    numeric.kind = BBE_STATE_BANK_AUTHORED_SCENARIO;
    BB_CHECK_EQ(bbe_state_bank_require_core(&numeric),
                BBE_SB_IDENTITY_CONFLICT);
    numeric = fixture.request;
    numeric.bbs_bytes++;
    BB_CHECK_EQ(bbe_state_bank_require_core(&numeric),
                BBE_SB_IDENTITY_CONFLICT);
    numeric = fixture.request;
    numeric.records++;
    BB_CHECK_EQ(bbe_state_bank_require_core(&numeric),
                BBE_SB_IDENTITY_CONFLICT);
    numeric = fixture.request;
    numeric.bbs_version++;
    BB_CHECK_EQ(bbe_state_bank_require_core(&numeric),
                BBE_SB_IDENTITY_CONFLICT);
    numeric = fixture.request;
    numeric.match_size++;
    BB_CHECK_EQ(bbe_state_bank_require_core(&numeric),
                BBE_SB_IDENTITY_CONFLICT);
    numeric = fixture.request;
    numeric.engine_fingerprint++;
    BB_CHECK_EQ(bbe_state_bank_require_core(&numeric),
                BBE_SB_IDENTITY_CONFLICT);
    bbe_state_bank_request changed = fixture.request;
    changed.test_only_allow_authored = 1;
    BB_CHECK_EQ(bbe_state_bank_require_core(&changed),
                BBE_SB_IDENTITY_CONFLICT);

    bbe_state_bank_test_reset_process();
    cleanup_test_candidate_request(&fixture);
    BB_CHECK_EQ(remove(path), 0);
}

BB_TEST(state_bank_failed_request_is_stable_and_not_retried) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-failed-identity-%ld.bbs",
             (long)getpid());
    bb_match match = valid_bank_match();
    write_state_bank(path, &match);
    TestCandidateRequest fixture;
    BB_CHECK_EQ(prepare_test_candidate_request(
                    &fixture, path, BBE_STATE_BANK_STRICT_REPLAY, 0),
                0);
    BB_CHECK_EQ(remove(path), 0);
    bbe_state_bank_test_reset_process();
    BB_CHECK_EQ(bbe_state_bank_require_core(&fixture.request),
                BBE_SB_BBS_OPEN);
    BB_CHECK_EQ(bbe_state_bank_status, BBE_SB_FAILED);
    BB_CHECK_EQ(bbe_state_bank_load_attempts, 1u);
    BB_CHECK_EQ(bbe_state_bank_require_core(&fixture.request),
                BBE_SB_BBS_OPEN);
    BB_CHECK_EQ(bbe_state_bank_load_attempts, 1u);
    bbe_state_bank_request changed = fixture.request;
    changed.bbs_path = "/tmp/a-different-missing-bank.bbs";
    BB_CHECK_EQ(bbe_state_bank_require_core(&changed),
                BBE_SB_IDENTITY_CONFLICT);
    BB_CHECK_EQ(bbe_state_bank_load_attempts, 1u);
    bbe_state_bank_test_reset_process();
    cleanup_test_candidate_request(&fixture);
}

BB_TEST(state_bank_unstorable_path_failure_reserves_bounded_identity) {
    char path[256];
    snprintf(path, sizeof path, "/tmp/bloodbowl-unstorable-identity-%ld.bbs",
             (long)getpid());
    bb_match match = valid_bank_match();
    write_state_bank(path, &match);
    TestCandidateRequest fixture;
    BB_CHECK_EQ(prepare_test_candidate_request(
                    &fixture, path, BBE_STATE_BANK_STRICT_REPLAY, 0),
                0);

    bbe_state_bank_request malformed = fixture.request;
    malformed.bbs_path = "";
    bbe_state_bank_test_reset_process();
    BB_CHECK_EQ(bbe_state_bank_require_core(&malformed),
                BBE_SB_REQUEST_PATH_TOO_LONG);
    BB_CHECK_EQ(bbe_state_bank_require_core(&malformed),
                BBE_SB_REQUEST_PATH_TOO_LONG);
    BB_CHECK_EQ(bbe_state_bank_status, BBE_SB_FAILED);
    BB_CHECK_EQ(bbe_state_bank_load_attempts, 0u);
    BB_CHECK_EQ(bbe_state_bank_require_core(&fixture.request),
                BBE_SB_IDENTITY_CONFLICT);
    BB_CHECK_EQ(bbe_state_bank_load_attempts, 0u);

    char overlong[BBE_STATE_BANK_MAX_PATH + 1u];
    memset(overlong, 'x', BBE_STATE_BANK_MAX_PATH);
    overlong[BBE_STATE_BANK_MAX_PATH] = '\0';
    malformed = fixture.request;
    malformed.bbs_path = overlong;
    bbe_state_bank_test_reset_process();
    BB_CHECK_EQ(bbe_state_bank_require_core(&malformed),
                BBE_SB_REQUEST_PATH_TOO_LONG);
    BB_CHECK_EQ(bbe_state_bank_require_core(&malformed),
                BBE_SB_REQUEST_PATH_TOO_LONG);
    BB_CHECK_EQ(bbe_state_bank_status, BBE_SB_FAILED);
    BB_CHECK_EQ(bbe_state_bank_load_attempts, 0u);
    overlong[BBE_STATE_BANK_MAX_PATH - 1u] = 'y';
    BB_CHECK_EQ(bbe_state_bank_require_core(&malformed),
                BBE_SB_IDENTITY_CONFLICT);
    BB_CHECK_EQ(bbe_state_bank_load_attempts, 0u);

    bbe_state_bank_test_reset_process();
    cleanup_test_candidate_request(&fixture);
    BB_CHECK_EQ(remove(path), 0);
}

BB_TEST(state_bank_uniform_index_rejects_low_biased_range) {
    const uint32_t bound = UINT32_C(0x80000001);
    const uint32_t threshold = -bound % bound;
    bb_rng actual;
    bb_rng expected;
    bb_rng_seed(&actual, 4u, 3u);
    bb_rng_seed(&expected, 4u, 3u);

    uint32_t rejected = bb_rng_next(&expected);
    uint32_t accepted = bb_rng_next(&expected);
    BB_CHECK_EQ(threshold, UINT32_C(0x7fffffff));
    BB_CHECK_EQ(rejected, UINT32_C(0x54f13138));
    BB_CHECK_EQ(accepted, UINT32_C(0xb20b4acc));
    BB_CHECK(rejected < threshold);
    BB_CHECK(accepted >= threshold);

    BB_CHECK_EQ(bbe_rng_uniform_below(&actual, bound),
                UINT32_C(0x320b4acb));
    BB_CHECK_EQ(actual.state, expected.state);
}
