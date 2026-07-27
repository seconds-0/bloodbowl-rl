#include "bloodbowl.h"

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

static void valid_uniform_reset(void) {
    static const char expected_fixture_sha[] =
        "0f47d8ba9754555bd5eac5bc954c1c52"
        "5ff97295d5e0bcfadebbb823a4457a93";
    ICHECK(strcmp(PUFFER_STATE_BANK_BBS_SHA256,
                  expected_fixture_sha) == 0);
    bbe_state_bank_request request =
        bbe_state_bank_compiled_request(NULL, NULL, NULL);
    ICHECK(bbe_state_bank_require_core(&request) == BBE_SB_OK);
    ICHECK(bbe_state_bank_status == BBE_SB_READY);
    ICHECK(bbe_state_bank_n == 1);
    ICHECK(bbe_state_bank_metadata != NULL);
    ICHECK(bbe_state_bank_metadata[0].source_id == UINT32_C(0x01020304));
    ICHECK(bbe_state_bank_metadata[0].command == UINT32_C(0x0a0b0c0d));
    ICHECK(bbe_state_bank_publications == 1);
    ICHECK(bbe_state_bank_load_attempts == 1);

    IntegrationEnv fixture;
    setup_integration_env(&fixture, 1.0f);
    c_reset(&fixture.env);
    ICHECK(fixture.env.demo_started == 1);
    ICHECK(fixture.env.match.status == BB_STATUS_DECISION);
    ICHECK(fixture.env.match.stack_top > 0);
    ICHECK(fixture.env.n_legal > 0 &&
           fixture.env.n_legal <= BB_LEGAL_MAX);
    ICHECK(memcmp(&fixture.env.match, &bbe_state_bank[0],
                  sizeof fixture.env.match) == 0);
    c_reset(&fixture.env);
    ICHECK(fixture.env.demo_started == 1);
    ICHECK(bbe_state_bank_publications == 1);
    ICHECK(bbe_state_bank_load_attempts == 1);
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

static void selector_bridge_aborts(void) {
    bbe_state_bank_request request =
        bbe_state_bank_compiled_request(NULL, NULL, NULL);
    ICHECK(bbe_state_bank_require_core(&request) == BBE_SB_OK);
    ICHECK(bbe_state_bank_status == BBE_SB_READY);
    ICHECK(bbe_state_bank_n == 1);
    IntegrationEnv fixture;
    setup_integration_env(&fixture, 1.0f);
    fixture.env.demo_endzone_maxdist = 1;
    c_reset(&fixture.env);
    _exit(101);
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
    int failed = total == 0 || fclose(in) != 0 || fclose(out) != 0;
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
    failures += run_case("zero reset leaves bank unopened",
                         zero_reset_never_opens_bank, 0);
    failures += run_case("owned path copies", owned_paths_survive_caller_mutation, 0);
    failures += run_case("location overrides own caller paths",
                         location_overrides_survive_caller_mutation, 0);
    failures += run_case("changed location override conflicts",
                         changed_location_override_after_require_aborts, 1);
    failures += run_case("failed request is stable", failed_missing_is_stable, 0);
    failures += run_case("missing wrapper aborts", missing_wrapper_aborts, 1);
    failures += run_case("selector bridge aborts", selector_bridge_aborts, 1);
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
