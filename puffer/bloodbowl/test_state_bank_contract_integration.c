#include "bloodbowl.h"
#include "state_bank_fixture.expected.h"

#include <pthread.h>
#include <signal.h>
#include <sys/wait.h>
#include <unistd.h>

#define ICHECK(condition)                                                      \
    do {                                                                       \
        if (!(condition)) {                                                    \
            fprintf(stderr, "integration check failed at %s:%d: %s\n",       \
                    __FILE__, __LINE__, #condition);                           \
            _exit(100);                                                        \
        }                                                                      \
    } while (0)

typedef struct {
    Bloodbowl env;
    uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    float actions[BBE_AGENTS * 3];
    unsigned char mask[BBE_AGENTS * BBE_MASK_SIZE];
    float rewards[BBE_AGENTS];
    float terminals[BBE_AGENTS];
} IntegrationEnv;

static void setup_integration_env(IntegrationEnv* fixture, float reset_pct) {
    memset(fixture, 0, sizeof *fixture);
    Bloodbowl* env = &fixture->env;
    env->num_agents = BBE_AGENTS;
    env->seed = 0x5a17u;
    env->demo_reset_pct = reset_pct;
    env->state_bank_kind =
        reset_pct > 0.0f ? BBE_STATE_BANK_STRICT_REPLAY
                         : BBE_STATE_BANK_NONE;
    env->exclude_team = -1;
    env->force_home_team = -1;
    env->force_away_team = -1;
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        env->obs_ptr[agent] = fixture->obs + agent * BBE_OBS_SIZE;
        env->action_ptr[agent] = fixture->actions + agent * 3;
        env->action_mask_ptr[agent] =
            fixture->mask + agent * BBE_MASK_SIZE;
        env->reward_ptr[agent] = fixture->rewards + agent;
        env->terminal_ptr[agent] = fixture->terminals + agent;
    }
}

static void require_and_verify_fixture(void) {
    bbe_state_bank_request request =
        bbe_state_bank_compiled_request(NULL, NULL, NULL);
    ICHECK(bbe_state_bank_require_core(&request) == BBE_SB_OK);
    ICHECK(bbe_state_bank_status == BBE_SB_READY);
    ICHECK(strcmp(PUFFER_STATE_BANK_STRATA_SCHEMA,
                  "bloodbowl-legacy-state-bank-strata-v1") == 0);
    ICHECK(bbe_state_bank_n ==
           (int)BBE_TEST_STATE_BANK_FIXTURE_RECORDS);
    ICHECK(bbe_state_bank_metadata != NULL);
    for (uint32_t ordinal = 0;
         ordinal < BBE_TEST_STATE_BANK_FIXTURE_RECORDS; ordinal++) {
        const bbe_state_bank_meta* metadata =
            &bbe_state_bank_metadata[ordinal];
        ICHECK(metadata->source_id ==
               bbe_test_fixture_source_ids[ordinal]);
        ICHECK(metadata->command ==
               bbe_test_fixture_commands[ordinal]);
        ICHECK(metadata->half == bbe_test_fixture_halves[ordinal]);
        ICHECK(metadata->turn == bbe_test_fixture_turns[ordinal]);

        for (unsigned family = BBE_STATE_BANK_SELECTOR_ENDZONE;
             family < BBE_STATE_BANK_SELECTOR_FAMILY_COUNT; family++) {
            int expected =
                bbe_test_fixture_metrics[ordinal][family - 1u];
            uint32_t metric = UINT32_MAX;
            int eligible = bbe_state_bank_metric(
                &bbe_state_bank[ordinal],
                (bbe_state_bank_selector_family)family, &metric);
            if (expected == BBE_TEST_STATE_BANK_FIXTURE_INELIGIBLE) {
                ICHECK(!eligible);
            } else {
                ICHECK(eligible);
                ICHECK(metric == (uint32_t)expected);
            }
        }
    }
    ICHECK(bbe_state_bank_publications == 1);
    ICHECK(bbe_state_bank_load_attempts == 1);
}

static int fixture_record_eligible(
        uint32_t ordinal, bbe_state_bank_selector_family family,
        uint32_t threshold) {
    if (family == BBE_STATE_BANK_SELECTOR_UNIFORM) return threshold == 0;
    int metric = bbe_test_fixture_metrics[ordinal][family - 1u];
    return metric != BBE_TEST_STATE_BANK_FIXTURE_INELIGIBLE &&
           (uint32_t)metric <= threshold;
}

static uint32_t fixture_expected_ordinal(
        bbe_state_bank_selector_family family, uint32_t threshold,
        uint32_t position) {
    if (family == BBE_STATE_BANK_SELECTOR_UNIFORM) {
        return position < BBE_TEST_STATE_BANK_FIXTURE_RECORDS
                   ? position : UINT32_MAX;
    }
    /*
     * The immutable index order is metric bucket first, then original BBS
     * ordinal within a bucket.  Derive that order from the authored metric
     * table rather than consulting the implementation's index.
     */
    for (uint32_t metric = 0; metric <= threshold; metric++) {
        for (uint32_t ordinal = 0;
             ordinal < BBE_TEST_STATE_BANK_FIXTURE_RECORDS; ordinal++) {
            if (bbe_test_fixture_metrics[ordinal][family - 1u] !=
                (int)metric) {
                continue;
            }
            if (position == 0) return ordinal;
            position--;
        }
    }
    return UINT32_MAX;
}

static void verify_latched_selection(
        const IntegrationEnv* fixture,
        bbe_state_bank_selector_family family, uint32_t threshold) {
    const Bloodbowl* env = &fixture->env;
    ICHECK(env->demo_started == 1);
    ICHECK(env->state_bank_config_latched == 1);
    ICHECK(env->state_bank_selector_family_latched == (int)family);
    ICHECK(env->state_bank_selector_threshold_latched == threshold);
    ICHECK(env->state_bank_selector_eligible_latched ==
           bbe_test_fixture_prefix_counts[family][threshold]);
    ICHECK(strcmp(env->state_bank_stratum_sha256_latched,
                  bbe_test_fixture_prefix_sha256[family][threshold]) == 0);
    uint32_t ordinal = env->state_bank_record_index_latched;
    ICHECK(ordinal < BBE_TEST_STATE_BANK_FIXTURE_RECORDS);
    ICHECK(fixture_record_eligible(ordinal, family, threshold));
    ICHECK(env->state_bank_source_id_latched ==
           bbe_test_fixture_source_ids[ordinal]);
    ICHECK(env->state_bank_source_command_latched ==
           bbe_test_fixture_commands[ordinal]);
    ICHECK(env->state_bank_source_half_latched ==
           bbe_test_fixture_halves[ordinal]);
    ICHECK(env->state_bank_source_turn_latched ==
           bbe_test_fixture_turns[ordinal]);
    ICHECK(memcmp(&env->match, &bbe_state_bank[ordinal],
                  sizeof env->match) == 0);
    ICHECK(env->match.status == BB_STATUS_DECISION);
    ICHECK(env->match.stack_top > 0);
    ICHECK(env->n_legal > 0 && env->n_legal <= BB_LEGAL_MAX);
}

static void set_integration_selector(
        Bloodbowl* env, bbe_state_bank_selector_family family,
        uint32_t threshold) {
    env->demo_endzone_maxdist = 0;
    env->demo_pickup_maxdist = 0;
    env->demo_postkick_maxturn = 0;
    env->demo_pass_maxrange = 0;
    switch (family) {
        case BBE_STATE_BANK_SELECTOR_UNIFORM:
            ICHECK(threshold == 0);
            break;
        case BBE_STATE_BANK_SELECTOR_ENDZONE:
            env->demo_endzone_maxdist = (int)threshold;
            break;
        case BBE_STATE_BANK_SELECTOR_PICKUP:
            env->demo_pickup_maxdist = (int)threshold;
            break;
        case BBE_STATE_BANK_SELECTOR_POSTKICK:
            env->demo_postkick_maxturn = (int)threshold;
            break;
        case BBE_STATE_BANK_SELECTOR_PASS:
            env->demo_pass_maxrange = (int)threshold;
            break;
        default:
            ICHECK(0);
    }
}

static void valid_uniform_reset(void) {
    require_and_verify_fixture();
    IntegrationEnv fixture;
    setup_integration_env(&fixture, 1.0f);
    c_reset(&fixture.env);
    verify_latched_selection(
        &fixture, BBE_STATE_BANK_SELECTOR_UNIFORM, 0);
    c_reset(&fixture.env);
    verify_latched_selection(
        &fixture, BBE_STATE_BANK_SELECTOR_UNIFORM, 0);
    ICHECK(bbe_state_bank_publications == 1);
    ICHECK(bbe_state_bank_load_attempts == 1);
}

static void all_descriptors_match_independent_fixture_oracle(void) {
    require_and_verify_fixture();
    for (unsigned family_value = BBE_STATE_BANK_SELECTOR_UNIFORM;
         family_value < BBE_STATE_BANK_SELECTOR_FAMILY_COUNT;
         family_value++) {
        bbe_state_bank_selector_family family =
            (bbe_state_bank_selector_family)family_value;
        uint32_t maximum =
            bbe_state_bank_selector_max_threshold(family);
        for (uint32_t threshold = 0; threshold <= maximum; threshold++) {
            bbe_state_bank_stratum_descriptor descriptor;
            ICHECK(bbe_state_bank_copy_stratum_descriptor(
                        family, threshold, &descriptor) == BBE_SB_OK);
            ICHECK(descriptor.family == family);
            ICHECK(descriptor.threshold == threshold);
            ICHECK(descriptor.eligible_records ==
                   bbe_test_fixture_prefix_counts[family][threshold]);
            ICHECK(strcmp(
                       descriptor.sha256,
                       bbe_test_fixture_prefix_sha256[family][threshold]) ==
                   0);
            for (uint32_t position = 0;
                 position < descriptor.eligible_records; position++) {
                uint32_t ordinal = UINT32_MAX;
                ICHECK(bbe_state_bank_copy_stratum_ordinal(
                            family, threshold, position, &ordinal) ==
                       BBE_SB_OK);
                ICHECK(ordinal == fixture_expected_ordinal(
                                       family, threshold, position));
            }
        }
    }
}

static void every_qualifying_selector_resets_from_exact_prefix(void) {
    require_and_verify_fixture();
    static const struct {
        bbe_state_bank_selector_family family;
        uint32_t threshold;
    } cases[] = {
        {BBE_STATE_BANK_SELECTOR_ENDZONE, 2},
        {BBE_STATE_BANK_SELECTOR_PICKUP, 2},
        {BBE_STATE_BANK_SELECTOR_POSTKICK, 1},
        {BBE_STATE_BANK_SELECTOR_PASS, 3},
    };
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        IntegrationEnv fixture;
        setup_integration_env(&fixture, 1.0f);
        fixture.env.seed += (uint64_t)i * UINT64_C(0x10001);
        set_integration_selector(
            &fixture.env, cases[i].family, cases[i].threshold);
        for (int episode = 0; episode < 16; episode++) {
            c_reset(&fixture.env);
            verify_latched_selection(
                &fixture, cases[i].family, cases[i].threshold);
        }
    }
}

static void zero_reset_never_opens_bank(void) {
    IntegrationEnv fixture;
    setup_integration_env(&fixture, 0.0f);
    c_reset(&fixture.env);
    ICHECK(fixture.env.demo_started == 0);
    ICHECK(bbe_state_bank_status == BBE_SB_UNTRIED);
    ICHECK(bbe_state_bank_load_attempts == 0);
    ICHECK(fixture.env.match.status == BB_STATUS_DECISION);
}

static void owned_paths_survive_caller_mutation(void) {
    char bbs[BBE_STATE_BANK_MAX_PATH];
    char producer[BBE_STATE_BANK_MAX_PATH];
    char contract[BBE_STATE_BANK_MAX_PATH];
    ICHECK(strlen(PUFFER_STATE_BANK_BBS_PATH) + 1 < sizeof bbs);
    ICHECK(strlen(PUFFER_STATE_BANK_PRODUCER_MANIFEST_PATH) + 1 <
           sizeof producer);
    ICHECK(strlen(PUFFER_STATE_BANK_TRAINING_CONTRACT_PATH) + 1 <
           sizeof contract);
    strcpy(bbs, PUFFER_STATE_BANK_BBS_PATH);
    strcpy(producer, PUFFER_STATE_BANK_PRODUCER_MANIFEST_PATH);
    strcpy(contract, PUFFER_STATE_BANK_TRAINING_CONTRACT_PATH);
    bbe_state_bank_request local =
        bbe_state_bank_compiled_request(bbs, producer, contract);
    ICHECK(bbe_state_bank_require_core(&local) == BBE_SB_OK);
    bbs[0] = 'X';
    producer[0] = 'X';
    contract[0] = 'X';
    bbe_state_bank_request immutable =
        bbe_state_bank_compiled_request(NULL, NULL, NULL);
    ICHECK(bbe_state_bank_require_core(&immutable) == BBE_SB_OK);
}

static void set_location_overrides_from_ephemeral_storage(void) {
    char bbs[BBE_STATE_BANK_MAX_PATH];
    char producer[BBE_STATE_BANK_MAX_PATH];
    char contract[BBE_STATE_BANK_MAX_PATH];
    ICHECK(strlen(PUFFER_STATE_BANK_BBS_PATH) + 1 < sizeof bbs);
    ICHECK(strlen(PUFFER_STATE_BANK_PRODUCER_MANIFEST_PATH) + 1 <
           sizeof producer);
    ICHECK(strlen(PUFFER_STATE_BANK_TRAINING_CONTRACT_PATH) + 1 <
           sizeof contract);
    strcpy(bbs, PUFFER_STATE_BANK_BBS_PATH);
    strcpy(producer, PUFFER_STATE_BANK_PRODUCER_MANIFEST_PATH);
    strcpy(contract, PUFFER_STATE_BANK_TRAINING_CONTRACT_PATH);
    bbe_state_bank_set_location_overrides(bbs, producer, contract);

    /*
     * The setter must have completed bounded owned copies.  Destroy the
     * caller's buffers and end their lifetime before the lazy reset requires
     * the compiled contract.
     */
    bbs[0] = 'X';
    producer[0] = 'X';
    contract[0] = 'X';
}

static void location_overrides_survive_caller_mutation(void) {
    set_location_overrides_from_ephemeral_storage();
    IntegrationEnv fixture;
    setup_integration_env(&fixture, 1.0f);
    c_reset(&fixture.env);
    ICHECK(fixture.env.demo_started == 1);
    ICHECK(bbe_state_bank_status == BBE_SB_READY);
    ICHECK(bbe_state_bank_load_attempts == 1);
    ICHECK(bbe_state_bank_publications == 1);
}

static void changed_location_override_after_require_aborts(void) {
    bbe_state_bank_request request =
        bbe_state_bank_compiled_request(NULL, NULL, NULL);
    ICHECK(bbe_state_bank_require_core(&request) == BBE_SB_OK);
    bbe_state_bank_set_location_overrides(
        "/tmp/different-but-equally-pinned-bank.bbs",
        PUFFER_STATE_BANK_PRODUCER_MANIFEST_PATH,
        PUFFER_STATE_BANK_TRAINING_CONTRACT_PATH);
    _exit(101);
}

static void failed_missing_is_stable(void) {
    bbe_state_bank_request request = bbe_state_bank_compiled_request(
        "/tmp/bloodbowl-integration-definitely-missing.bbs", NULL, NULL);
    ICHECK(bbe_state_bank_require_core(&request) == BBE_SB_BBS_OPEN);
    ICHECK(bbe_state_bank_status == BBE_SB_FAILED);
    ICHECK(bbe_state_bank_load_attempts == 1);
    ICHECK(bbe_state_bank_require_core(&request) == BBE_SB_BBS_OPEN);
    ICHECK(bbe_state_bank_load_attempts == 1);
    ICHECK(bbe_state_bank == NULL);
    ICHECK(bbe_state_bank_metadata == NULL);
}

static void missing_wrapper_aborts(void) {
    bbe_state_bank_require_paths_or_abort(
        BBE_STATE_BANK_STRICT_REPLAY,
        "/tmp/bloodbowl-integration-definitely-missing.bbs",
        NULL, NULL);
    _exit(101);
}

static void empty_endzone_stratum_aborts_distinctly(void) {
    bbe_state_bank_request request =
        bbe_state_bank_compiled_request(NULL, NULL, NULL);
    ICHECK(bbe_state_bank_require_core(&request) == BBE_SB_OK);
    ICHECK(bbe_state_bank_status == BBE_SB_READY);
    ICHECK(bbe_state_bank_n ==
           (int)BBE_TEST_STATE_BANK_FIXTURE_RECORDS);
    int diagnostic[2];
    ICHECK(pipe(diagnostic) == 0);
    pid_t child = fork();
    ICHECK(child >= 0);
    if (child == 0) {
        close(diagnostic[0]);
        ICHECK(dup2(diagnostic[1], STDERR_FILENO) == STDERR_FILENO);
        close(diagnostic[1]);
        IntegrationEnv fixture;
        setup_integration_env(&fixture, 0.01f);
        fixture.env.demo_endzone_maxdist = 1;
        c_reset(&fixture.env);
        _exit(101);
    }
    close(diagnostic[1]);
    char observed[512];
    size_t used = 0;
    while (used + 1 < sizeof observed) {
        ssize_t count =
            read(diagnostic[0], observed + used, sizeof observed - used - 1);
        if (count <= 0) break;
        used += (size_t)count;
    }
    observed[used] = '\0';
    close(diagnostic[0]);
    int status = 0;
    ICHECK(waitpid(child, &status, 0) == child);
    ICHECK(WIFSIGNALED(status) && WTERMSIG(status) == SIGABRT);
    static const char expected[] =
        "bloodbowl: requested state-bank stratum is empty: "
        "endzone-maxdist=1\n";
    if (strcmp(observed, expected) != 0) {
        fprintf(stderr,
                "observed empty-stratum diagnostic \"%s\", expected \"%s\"\n",
                observed, expected);
    }
    ICHECK(strcmp(observed, expected) == 0);
}

static void different_path_conflicts(void) {
    bbe_state_bank_request request =
        bbe_state_bank_compiled_request(NULL, NULL, NULL);
    ICHECK(bbe_state_bank_require_core(&request) == BBE_SB_OK);
    bbe_state_bank_request changed = bbe_state_bank_compiled_request(
        "/tmp/different-but-equally-pinned-bank.bbs", NULL, NULL);
    ICHECK(bbe_state_bank_require_core(&changed) ==
           BBE_SB_IDENTITY_CONFLICT);
    ICHECK(bbe_state_bank_publications == 1);
}

static int copy_and_flip(const char* source, char* destination,
                         size_t destination_size) {
    int n = snprintf(destination, destination_size,
                     "/tmp/bloodbowl-state-bank-mutation-%ld-%s",
                     (long)getpid(), strrchr(source, '/') != NULL
                                          ? strrchr(source, '/') + 1
                                          : source);
    if (n <= 0 || (size_t)n >= destination_size) return -1;
    FILE* in = fopen(source, "rb");
    FILE* out = fopen(destination, "wb");
    if (in == NULL || out == NULL) {
        if (in != NULL) fclose(in);
        if (out != NULL) fclose(out);
        return -1;
    }
    uint8_t bytes[4096];
    size_t total = 0;
    for (;;) {
        size_t count = fread(bytes, 1, sizeof bytes, in);
        if (count != 0) {
            if (total == 0) bytes[0] ^= 1;
            if (fwrite(bytes, 1, count, out) != count) {
                fclose(in);
                fclose(out);
                return -1;
            }
            total += count;
        }
        if (count < sizeof bytes) {
            if (ferror(in)) {
                fclose(in);
                fclose(out);
                return -1;
            }
            break;
        }
    }
    int close_in_failed = fclose(in) != 0;
    int close_out_failed = fclose(out) != 0;
    int failed = total == 0 || close_in_failed || close_out_failed;
    return failed ? -1 : 0;
}

static void mutated_contract_hash_fails(void) {
    char path[512];
    ICHECK(copy_and_flip(PUFFER_STATE_BANK_TRAINING_CONTRACT_PATH,
                         path, sizeof path) == 0);
    bbe_state_bank_request request =
        bbe_state_bank_compiled_request(NULL, NULL, path);
    ICHECK(bbe_state_bank_require_core(&request) == BBE_SB_CONTRACT_HASH);
    ICHECK(remove(path) == 0);
}

static void mutated_producer_hash_fails(void) {
    char path[512];
    ICHECK(copy_and_flip(PUFFER_STATE_BANK_PRODUCER_MANIFEST_PATH,
                         path, sizeof path) == 0);
    bbe_state_bank_request request =
        bbe_state_bank_compiled_request(NULL, path, NULL);
    ICHECK(bbe_state_bank_require_core(&request) == BBE_SB_PRODUCER_HASH);
    ICHECK(remove(path) == 0);
}

static void mutated_bbs_hash_fails(void) {
    char path[512];
    ICHECK(copy_and_flip(PUFFER_STATE_BANK_BBS_PATH,
                         path, sizeof path) == 0);
    bbe_state_bank_request request =
        bbe_state_bank_compiled_request(path, NULL, NULL);
    ICHECK(bbe_state_bank_require_core(&request) == BBE_SB_BBS_HASH);
    ICHECK(remove(path) == 0);
}

typedef struct {
    const bbe_state_bank_request* request;
    atomic_int* ready;
    atomic_int* go;
    bbe_state_bank_error result;
} ThreadRequest;

static void* concurrent_require_thread(void* opaque) {
    ThreadRequest* thread = (ThreadRequest*)opaque;
    atomic_fetch_add_explicit(thread->ready, 1, memory_order_release);
    while (atomic_load_explicit(thread->go, memory_order_acquire) == 0) {
    }
    thread->result = bbe_state_bank_require_core(thread->request);
    return NULL;
}

static void concurrent_first_require_publishes_once(void) {
    bbe_state_bank_request request =
        bbe_state_bank_compiled_request(NULL, NULL, NULL);
    atomic_int ready = 0;
    atomic_int go = 0;
    ThreadRequest requests[2] = {
        {&request, &ready, &go, BBE_SB_REQUEST_INCOMPLETE},
        {&request, &ready, &go, BBE_SB_REQUEST_INCOMPLETE},
    };
    pthread_t threads[2];
    ICHECK(pthread_create(&threads[0], NULL, concurrent_require_thread,
                          &requests[0]) == 0);
    ICHECK(pthread_create(&threads[1], NULL, concurrent_require_thread,
                          &requests[1]) == 0);
    while (atomic_load_explicit(&ready, memory_order_acquire) != 2) {
    }
    atomic_store_explicit(&go, 1, memory_order_release);
    ICHECK(pthread_join(threads[0], NULL) == 0);
    ICHECK(pthread_join(threads[1], NULL) == 0);
    ICHECK(requests[0].result == BBE_SB_OK);
    ICHECK(requests[1].result == BBE_SB_OK);
    ICHECK(bbe_state_bank_load_attempts == 1);
    ICHECK(bbe_state_bank_publications == 1);
    ICHECK(bbe_state_bank_status == BBE_SB_READY);
}

static void authored_production_request_rejected(void) {
    bbe_state_bank_request request =
        bbe_state_bank_compiled_request(NULL, NULL, NULL);
    request.kind = BBE_STATE_BANK_AUTHORED_SCENARIO;
    request.kind_name = "authored-scenario";
    ICHECK(bbe_state_bank_require_core(&request) ==
           BBE_SB_REQUEST_AUTHORED_DISABLED);
    ICHECK(bbe_state_bank_status == BBE_SB_FAILED);
    ICHECK(bbe_state_bank == NULL);
}

typedef void (*integration_case)(void);

static int run_case(const char* name, integration_case function,
                    int expect_abort) {
    fflush(NULL);
    pid_t child = fork();
    if (child < 0) {
        perror("fork");
        return 1;
    }
    if (child == 0) {
        function();
        _exit(0);
    }
    int status = 0;
    if (waitpid(child, &status, 0) != child) {
        perror("waitpid");
        return 1;
    }
    int ok = expect_abort
                 ? WIFSIGNALED(status) && WTERMSIG(status) == SIGABRT
                 : WIFEXITED(status) && WEXITSTATUS(status) == 0;
    printf("%s  %s\n", ok ? "ok  " : "FAIL", name);
    return ok ? 0 : 1;
}

int main(void) {
    int failures = 0;
    failures += run_case("valid uniform reset", valid_uniform_reset, 0);
    failures += run_case("all descriptors match independent fixture oracle",
                         all_descriptors_match_independent_fixture_oracle, 0);
    failures += run_case("qualifying selectors reset from exact prefixes",
                         every_qualifying_selector_resets_from_exact_prefix,
                         0);
    failures += run_case("zero reset leaves bank unopened",
                         zero_reset_never_opens_bank, 0);
    failures += run_case("owned path copies", owned_paths_survive_caller_mutation, 0);
    failures += run_case("location overrides own caller paths",
                         location_overrides_survive_caller_mutation, 0);
    failures += run_case("changed location override conflicts",
                         changed_location_override_after_require_aborts, 1);
    failures += run_case("failed request is stable", failed_missing_is_stable, 0);
    failures += run_case("missing wrapper aborts", missing_wrapper_aborts, 1);
    failures += run_case("empty endzone stratum aborts distinctly",
                         empty_endzone_stratum_aborts_distinctly, 0);
    failures += run_case("different path conflicts", different_path_conflicts, 0);
    failures += run_case("mutated contract fails", mutated_contract_hash_fails, 0);
    failures += run_case("mutated producer fails", mutated_producer_hash_fails, 0);
    failures += run_case("mutated BBS fails", mutated_bbs_hash_fails, 0);
    failures += run_case("concurrent publication is singular",
                         concurrent_first_require_publishes_once, 0);
    failures += run_case("authored production request rejected",
                         authored_production_request_rejected, 0);
    printf("%d integration failure(s)\n", failures);
    return failures != 0;
}
