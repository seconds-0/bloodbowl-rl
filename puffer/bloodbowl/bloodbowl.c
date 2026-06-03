// bloodbowl.c — standalone driver for the PufferLib env (build.sh --local /
// --fast, or direct clang on Mac). Plays random-policy matches end-to-end
// through the exact c_reset/c_step path training uses, then reports
// aggregate stats + steps/sec. Heads are sampled from the legality mask
// (like the CUDA masked sampler); pass --unmasked to sample uniformly over
// each head instead, stress-testing the decode snap-to-legal path the
// maskless torch backend relies on.
#include "bloodbowl.h"
#include <stdio.h>
#include <time.h>

// Sample a uniformly random set bit in mask[0..len); -1 if none.
static int sample_masked(const unsigned char* mask, int len, bb_rng* rng) {
    int n = 0;
    for (int i = 0; i < len; i++) n += mask[i];
    if (n == 0) return -1;
    int k = (int)(bb_rng_next(rng) % (uint32_t)n);
    for (int i = 0; i < len; i++) {
        if (mask[i] && k-- == 0) return i;
    }
    return -1;
}

// --- Self-test (--selftest) --------------------------------------------------
// Binding-level regression checks, run over seeded random-policy episodes.
// Expectations are re-derived here straight from engine state (the bb_frame
// semantics documented in each proc_*.c header comment), independent of the
// encoder's own helper tables, so encoder regressions fail loudly.

static int st_failures;
#define ST_CHECK(cond, ...)                                                    \
    do {                                                                       \
        if (!(cond)) {                                                         \
            st_failures++;                                                     \
            printf("SELFTEST FAIL (bloodbowl.c:%d): ", __LINE__);              \
            printf(__VA_ARGS__);                                               \
            printf("\n");                                                      \
        }                                                                      \
    } while (0)

// Independent restatement of the per-proc frame-param semantics (review M14:
// PREGAME stores the toss winner, SETUP/KICKOFF the kicking team and
// TEAM_TURN the acting team — TEAM IDS, not slots — in a; MOVE/TEST store
// kinds and CASUALTY/KO_RECOVERY flags in b). 1 = player slot.
static void st_frame_param_kinds(int proc, int* a_is_slot, int* b_is_slot) {
    *a_is_slot = 0;
    *b_is_slot = 0;
    switch (proc) {
    case BB_PROC_BLOCK: // a = attacker, b = defender
    case BB_PROC_PUSH:  // a = pusher, b = pushee
    case BB_PROC_FOUL:  // a = fouler, b = victim
        *a_is_slot = 1;
        *b_is_slot = 1;
        return;
    case BB_PROC_ACTIVATION:  // a = activating player
    case BB_PROC_MOVE:        // a = mover, b = bb_act_kind
    case BB_PROC_TEST:        // a = tested player, b = bb_test_kind
    case BB_PROC_CASUALTY:    // a = victim, b = apothecary-window flag
    case BB_PROC_KO_RECOVERY: // a = patched player, b = crowd flag
    case BB_PROC_PASS:        // a = thrower, b = interceptor (post-window)
        *a_is_slot = 1;
        return;
    default: // PREGAME / SETUP / KICKOFF / TEAM_TURN: a = team id
        return;
    }
}

// Validate both agents' encoded observations against the current decision
// state. Called when env obs/masks correspond to env->match (loop top).
static void st_check_obs(const Bloodbowl* env) {
    const bb_match* m = &env->match;
    if (m->status != BB_STATUS_DECISION || m->stack_top == 0) return;
    const bb_frame* top = &m->stack[m->stack_top - 1];
    int a_is_slot, b_is_slot;
    st_frame_param_kinds(top->proc, &a_is_slot, &b_is_slot);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        const unsigned char* b = env->obs_ptr[agent] + BBE_CTX_OFF;
        int exp_a = (a_is_slot && top->a < BB_NUM_PLAYERS)
                        ? 1 + (agent == BB_AWAY ? (top->a ^ BB_TEAM_SLOTS) : top->a)
                        : 0;
        int exp_b = (b_is_slot && top->b < BB_NUM_PLAYERS)
                        ? 1 + (agent == BB_AWAY ? (top->b ^ BB_TEAM_SLOTS) : top->b)
                        : 0;
        ST_CHECK(b[6] == exp_a, "proc %d agent %d: ctx frame-a byte %d != %d",
                 top->proc, agent, b[6], exp_a);
        ST_CHECK(b[7] == exp_b, "proc %d agent %d: ctx frame-b byte %d != %d",
                 top->proc, agent, b[7], exp_b);
        // Review M14's exact repro: at every ACTIVATE decision (TEAM_TURN on
        // top, a = team id 0/1) BOTH agents must see "no slot" — the away
        // agent used to see "opponent row 17" for the home team's turn.
        if (top->proc == BB_PROC_TEAM_TURN) {
            ST_CHECK(b[6] == 0, "TEAM_TURN leaked team id as slot %d to agent %d",
                     b[6], agent);
        }
    }
}

static int bbe_selftest(uint64_t seed, int episodes) {
    static Bloodbowl env;
    static uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    static float actions[BBE_AGENTS * 3];
    static unsigned char mask[BBE_AGENTS * BBE_MASK_SIZE];
    static float rewards[BBE_AGENTS];
    static float terminals[BBE_AGENTS];
    env.num_agents = BBE_AGENTS;
    env.seed = seed;
    for (int a = 0; a < BBE_AGENTS; a++) {
        env.obs_ptr[a] = obs + a * BBE_OBS_SIZE;
        env.action_ptr[a] = actions + a * 3;
        env.action_mask_ptr[a] = mask + a * BBE_MASK_SIZE;
        env.reward_ptr[a] = rewards + a;
        env.terminal_ptr[a] = terminals + a;
    }
    c_reset(&env);

    bb_rng pol;
    bb_rng_seed(&pol, seed ^ 0x5E1F7E57, 5);
    long proc_seen[BB_PROC_COUNT] = {0};
    int done = 0;
    while (done < episodes) {
        if (env.match.status == BB_STATUS_DECISION && env.match.stack_top > 0) {
            proc_seen[env.match.stack[env.match.stack_top - 1].proc]++;
        }
        st_check_obs(&env);
        for (int a = 0; a < BBE_AGENTS; a++) {
            const unsigned char* mk = env.action_mask_ptr[a];
            env.action_ptr[a][0] = (float)sample_masked(mk, BBE_HEAD_TYPE, &pol);
            env.action_ptr[a][1] =
                (float)sample_masked(mk + BBE_HEAD_TYPE, BBE_HEAD_ARG, &pol);
            env.action_ptr[a][2] = (float)sample_masked(
                mk + BBE_HEAD_TYPE + BBE_HEAD_ARG, BBE_HEAD_SQ, &pol);
        }
        c_step(&env);
        if (terminals[0] != 0.0f) done++;
    }
    // Random play must have exercised the procs whose frame-param semantics
    // the checks above pin down (rarer windows — FOUL argue-the-call, PASS
    // interceptions, apothecary — are checked whenever they occur).
    static const int st_required[] = {
        BB_PROC_PREGAME, BB_PROC_SETUP,      BB_PROC_KICKOFF,
        BB_PROC_TEAM_TURN, BB_PROC_ACTIVATION, BB_PROC_MOVE,
        BB_PROC_TEST,    BB_PROC_BLOCK,      BB_PROC_PUSH,
    };
    for (size_t i = 0; i < sizeof(st_required) / sizeof(st_required[0]); i++) {
        ST_CHECK(proc_seen[st_required[i]] > 0,
                 "decision proc %d never reached in %d episodes",
                 st_required[i], episodes);
    }
    // Defensive termination: a DECISION state whose legal enumeration came
    // back empty must end the episode instead of livelocking the env (the
    // mask path emits a null action, but the step path applies nothing and
    // would otherwise never advance or terminate).
    ST_CHECK(env.match.status == BB_STATUS_DECISION,
             "expected a decision state after the episode loop");
    ST_CHECK(env.log.error_episodes == 0.0f,
             "error episodes during normal play: %g", env.log.error_episodes);
    {
        float n_before = env.log.n;
        env.n_legal = 0; // simulate an enumerator returning no actions
        c_step(&env);
        ST_CHECK(terminals[0] == 1.0f && terminals[1] == 1.0f,
                 "empty-legal decision did not terminate the episode");
        ST_CHECK(env.log.n == n_before + 1,
                 "defensive reset did not log the episode");
        ST_CHECK(env.log.error_episodes == 1.0f,
                 "empty-legal defensive reset not counted: %g",
                 env.log.error_episodes);
        ST_CHECK(env.match.status == BB_STATUS_DECISION && env.n_legal > 0,
                 "env did not reset to a fresh decision after defensive reset");
    }
    // BB_STATUS_ERROR mid-episode (the other defensive-reset trigger).
    {
        env.match.status = BB_STATUS_ERROR;
        c_step(&env);
        ST_CHECK(terminals[0] == 1.0f && terminals[1] == 1.0f,
                 "ERROR status did not terminate the episode");
        ST_CHECK(env.log.error_episodes == 2.0f,
                 "ERROR defensive reset not counted: %g", env.log.error_episodes);
        ST_CHECK(env.match.status == BB_STATUS_DECISION && env.n_legal > 0,
                 "env did not reset to a fresh decision after ERROR reset");
    }
    printf("bloodbowl selftest: %d episodes, %d failure(s)\n", done, st_failures);
    return st_failures ? 1 : 0;
}

int main(int argc, char** argv) {
    int episodes = 64;
    int unmasked = 0;
    int selftest = 0;
    uint64_t seed = 42;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--unmasked") == 0) unmasked = 1;
        else if (strcmp(argv[i], "--selftest") == 0) selftest = 1;
        else if (strcmp(argv[i], "--seed") == 0 && i + 1 < argc) seed = strtoull(argv[++i], 0, 10);
        else episodes = atoi(argv[i]);
    }
    if (selftest) return bbe_selftest(seed, episodes);

    static Bloodbowl env; // ~20KB of legal-action buffer; keep off the stack
    static uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    static float actions[BBE_AGENTS * 3];
    static unsigned char mask[BBE_AGENTS * BBE_MASK_SIZE];
    static float rewards[BBE_AGENTS];
    static float terminals[BBE_AGENTS];
    env.num_agents = BBE_AGENTS;
    env.seed = seed;
    for (int a = 0; a < BBE_AGENTS; a++) {
        env.obs_ptr[a] = obs + a * BBE_OBS_SIZE;
        env.action_ptr[a] = actions + a * 3;
        env.action_mask_ptr[a] = mask + a * BBE_MASK_SIZE;
        env.reward_ptr[a] = rewards + a;
        env.terminal_ptr[a] = terminals + a;
    }
    c_reset(&env);

    bb_rng pol;
    bb_rng_seed(&pol, seed ^ 0xBADC0DE, 3);

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    long steps = 0;
    int done = 0;
    while (done < episodes) {
        for (int a = 0; a < BBE_AGENTS; a++) {
            const unsigned char* m = env.action_mask_ptr[a];
            if (unmasked) {
                env.action_ptr[a][0] = (float)(bb_rng_next(&pol) % BBE_HEAD_TYPE);
                env.action_ptr[a][1] = (float)(bb_rng_next(&pol) % BBE_HEAD_ARG);
                env.action_ptr[a][2] = (float)(bb_rng_next(&pol) % BBE_HEAD_SQ);
            } else {
                env.action_ptr[a][0] = (float)sample_masked(m, BBE_HEAD_TYPE, &pol);
                env.action_ptr[a][1] = (float)sample_masked(m + BBE_HEAD_TYPE, BBE_HEAD_ARG, &pol);
                env.action_ptr[a][2] = (float)sample_masked(
                    m + BBE_HEAD_TYPE + BBE_HEAD_ARG, BBE_HEAD_SQ, &pol);
            }
        }
        c_step(&env);
        steps++;
        if (terminals[0] != 0.0f) done++;
    }
    clock_gettime(CLOCK_MONOTONIC, &t1);
    double secs = (double)(t1.tv_sec - t0.tv_sec) + (double)(t1.tv_nsec - t0.tv_nsec) / 1e9;

    Log* lg = &env.log;
    float n = lg->n > 0 ? lg->n : 1;
    printf("bloodbowl standalone: %d episodes, %ld steps in %.2fs (%s)\n",
           done, steps, secs, unmasked ? "unmasked" : "masked");
    printf("  steps/sec        %.0f (x2 agent-obs per step)\n", (double)steps / secs);
    printf("  perf             %.3f\n", lg->perf / n);
    printf("  score_diff       %+.2f\n", lg->score_diff / n);
    printf("  tds/match        %.2f\n", lg->tds / n);
    printf("  episode_length   %.0f\n", lg->episode_length / n);
    printf("  episode_return   %+.2f\n", lg->episode_return / n);
    printf("  illegal_frac     %.4f\n", lg->illegal_frac / n);
    c_close(&env);
    return 0;
}
