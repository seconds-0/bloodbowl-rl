// bbe_profile.c — per-phase profiler for the production env step.
// Drives the real c_step (exact decode, bb_apply_trusted, reward shaping,
// terminal bookkeeping, legal refresh, obs/mask emission) under the uniform
// exact-joint sampler, with the BBE_PROF_* hooks in bloodbowl.h compiled in
// for this translation unit only. Every nanosecond between two hook
// boundaries is charged to exactly one phase, so the phases sum to c_step's
// wall time (timer cost included; it is calibrated and reported).
//
// Build: make build/bbe_profile                      (timed phases)
//        add -DBBE_PROFILE_UNTIMED to the same command (no clock calls; use
//        its steps/sec as the per-core throughput figure)
// Usage: bbe_profile [episodes] [--seed N] [--smoke] [field=value ...]
//        field = any reward_* knob from binding.c apply_kwargs, macro_moves,
//        or max_decisions. Fields not given keep the standalone defaults
//        (TD/win/draw only), so pass a reward manifest to profile its shaping.
#include <stdint.h>
#include <stdio.h>
#include <time.h>

enum {
    BBE_PROF_DRIVER,  // outside c_step: policy sampling
    BBE_PROF_REWARD,  // c_step bookkeeping + reward shaping + telemetry
    BBE_PROF_DECODE,
    BBE_PROF_APPLY,   // bb_apply_trusted (engine rules + advance)
    BBE_PROF_EPISODE, // terminal check, finish + reset on episode end
    BBE_PROF_LEGAL,   // bbe_refresh_legal (legal-action enumeration)
    BBE_PROF_TZ,
    BBE_PROF_OBS,
    BBE_PROF_MASK,
    BBE_PROF_COUNT
};

static void bbe_prof_switch(int phase);
#ifndef BBE_PROFILE_UNTIMED
#define BBE_PROF_SWITCH(phase) bbe_prof_switch(BBE_PROF_##phase)
#define BBE_PROF_ENTER(saved, phase) \
    int saved = bbe_prof_enter(BBE_PROF_##phase)
#define BBE_PROF_LEAVE(saved) prof_charge(saved)
static int bbe_prof_enter(int phase);
static void prof_charge(int phase);
#else
// Untimed: only the episode boundary is observed (no clock call).
#define BBE_PROF_SWITCH(phase)                                   \
    do {                                                         \
        if (BBE_PROF_##phase == BBE_PROF_EPISODE) bbe_prof_switch(BBE_PROF_EPISODE); \
    } while (0)
#define BBE_PROF_ENTER(saved, phase) ((void)0)
#define BBE_PROF_LEAVE(saved) ((void)0)
#endif
#include "bloodbowl.h"

static inline uint64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static const Bloodbowl* prof_env;
static int prof_cur = BBE_PROF_DRIVER;
static uint64_t prof_last;
static uint64_t prof_ns[BBE_PROF_COUNT];
static uint64_t prof_switches;
// Status of the match as c_step reached its terminal
// check: after an episode ends, env->match already holds the next match.
static int prof_end_status;

#ifndef BBE_PROFILE_UNTIMED
static void prof_charge(int phase) {
    uint64_t t = now_ns();
    prof_ns[prof_cur] += t - prof_last;
    prof_last = t;
    prof_cur = phase;
    prof_switches++;
}

// Nested ENTER/LEAVE (a refresh inside the reset) must not re-capture the
// episode status on the way back out: by then it belongs to the next match.
static int bbe_prof_enter(int phase) {
    int saved = prof_cur;
    prof_charge(phase);
    return saved;
}
#endif

static void bbe_prof_switch(int phase) {
    if (phase == BBE_PROF_EPISODE) prof_end_status = prof_env->match.status;
#ifndef BBE_PROFILE_UNTIMED
    prof_charge(phase);
#endif
}

static const char* phase_name(int p) {
    static const char* names[BBE_PROF_COUNT] = {
        "driver joint sampling", "reward+bookkeeping", "decode",
        "engine apply (trusted)", "episode end/reset", "legal enumeration",
        "compute tz scratch", "encode obs x2", "fill mask x2",
    };
    return names[p];
}

static const char* proc_name(int p) {
    static char buf[16];
    switch (p) {
#define N(x) case BB_PROC_##x: return #x
        N(MATCH); N(PREGAME); N(SETUP); N(KICKOFF); N(TEAM_TURN);
        N(ACTIVATION); N(MOVE); N(DODGE); N(RUSH); N(PICKUP); N(BLOCK);
        N(PUSH); N(KNOCKDOWN); N(ARMOUR); N(INJURY); N(CASUALTY); N(PASS);
        N(CATCH); N(SCATTER); N(THROW_IN); N(HANDOFF); N(FOUL); N(TTM);
        N(TEST); N(TOUCHDOWN); N(TURNOVER); N(END_DRIVE); N(KO_RECOVERY);
#undef N
    default: snprintf(buf, sizeof buf, "proc%d", p); return buf;
    }
}

typedef struct {
    const char* name;
    size_t off;
    int is_int;
} env_field;

#define FF(x) {#x, offsetof(Bloodbowl, x), 0}
#define FI(x) {#x, offsetof(Bloodbowl, x), 1}
static const env_field env_fields[] = {
    FF(reward_td), FF(reward_win), FF(reward_draw), FF(reward_setup_done),
    FF(reward_setup_autofix), FF(reward_ball_gain), FF(reward_ball_loss),
    FF(reward_dist_ball), FF(reward_dist_endzone), FF(reward_dist_pbrs_gamma),
    FF(reward_injury_inflicted), FF(reward_injury_taken),
    FI(reward_injury_value_scaled), FF(reward_send_off),
    FF(reward_kickoff_touchback), FF(reward_surf_taken),
    FF(reward_surf_inflicted), FF(reward_k_kd), FF(reward_k_value),
    FF(reward_k_self_injury), FF(reward_k_ball), FF(reward_k_seq),
    FF(reward_k_turnover), FF(reward_possession), FF(reward_k_assist),
    FF(reward_rush_cost), FF(reward_carrier_exposure),
    FF(reward_carrier_exposure_soft), FF(reward_carrier_threat),
    FF(reward_defensive_threat), FF(reward_defensive_threat_soft),
    FF(reward_statmatch_scale), FI(macro_moves), FI(max_decisions),
};
#undef FF
#undef FI

static int set_env_field(Bloodbowl* env, const char* arg) {
    const char* eq = strchr(arg, '=');
    if (!eq) return 0;
    size_t n = (size_t)(eq - arg);
    for (size_t i = 0; i < sizeof env_fields / sizeof env_fields[0]; i++) {
        if (strlen(env_fields[i].name) != n ||
            strncmp(env_fields[i].name, arg, n) != 0) continue;
        char* end;
        double v = strtod(eq + 1, &end);
        if (end == eq + 1 || *end != '\0') return 0;
        if (env_fields[i].is_int) {
            *(int*)((char*)env + env_fields[i].off) = (int)v;
        } else {
            *(float*)((char*)env + env_fields[i].off) = (float)v;
        }
        return 1;
    }
    return 0;
}

int main(int argc, char** argv) {
    static Bloodbowl env;
    int episodes = 200;
    int smoke = 0;
    uint64_t seed = 42;
    env.reward_td = BBE_DEFAULT_REWARD_TD;
    env.reward_win = BBE_DEFAULT_REWARD_WIN;
    env.reward_draw = BBE_DEFAULT_REWARD_DRAW;
    env.reward_configured = 1;
    env.reach_mover = -1;
    env.macro_mover = -1;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--smoke") == 0) {
            smoke = 1;
        } else if (strcmp(argv[i], "--seed") == 0 && i + 1 < argc) {
            seed = strtoull(argv[++i], 0, 10);
        } else if (strchr(argv[i], '=')) {
            if (!set_env_field(&env, argv[i])) {
                fprintf(stderr, "bbe_profile: bad env field '%s'\n", argv[i]);
                return 2;
            }
        } else {
            episodes = atoi(argv[i]);
        }
    }

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
    prof_env = &env;
    c_reset(&env);

#ifndef BBE_PROFILE_UNTIMED
    // Timer calibration: one hook boundary costs one clock read.
    uint64_t cal0 = now_ns();
    volatile uint64_t sink = 0;
    for (int i = 0; i < 1000000; i++) sink += now_ns();
    double ns_per_clock = (double)(now_ns() - cal0) / 1e6;
    (void)sink;
#endif
    memset(prof_ns, 0, sizeof prof_ns);
    prof_switches = 0;

    bb_rng pol;
    bb_rng_seed(&pol, seed ^ 0xBADC0DE, 3);

    static uint64_t dec_by_proc[BB_PROC_COUNT];
    static uint64_t apply_ns_by_proc[BB_PROC_COUNT];
    static uint64_t enum_ns[BB_PROC_COUNT];
    static uint64_t enum_calls[BB_PROC_COUNT];
    static uint64_t enum_actions[BB_PROC_COUNT];
    long steps = 0, decisions = 0, n_legal_sum = 0;
    int done = 0, ep_match_over = 0, ep_truncated = 0, ep_error = 0;
    uint64_t t_total0 = now_ns();
    prof_last = t_total0;
    prof_cur = BBE_PROF_DRIVER;
    while (done < episodes) {
        bb_match* m = &env.match;
        for (int a = 0; a < BBE_AGENTS; a++) {
            bbe_sample_joint_uniform(&env, a, env.action_ptr[a], &pol);
        }
        int dec_proc = -1;
        if (m->status == BB_STATUS_DECISION && env.n_legal > 0 &&
            m->stack_top > 0) {
            dec_proc = m->stack[m->stack_top - 1].proc;
            dec_by_proc[dec_proc]++;
            n_legal_sum += env.n_legal;
            decisions++;
        }
        float errors_before = env.log.error_episodes;
        uint64_t apply_before = prof_ns[BBE_PROF_APPLY];
        uint64_t legal_before = prof_ns[BBE_PROF_LEGAL];

        bbe_prof_switch(BBE_PROF_REWARD);
        c_step(&env);
        bbe_prof_switch(BBE_PROF_DRIVER);
        steps++;

        if (dec_proc >= 0) {
            apply_ns_by_proc[dec_proc] += prof_ns[BBE_PROF_APPLY] - apply_before;
        }
        // The step's final refresh enumerated the state c_step left behind.
        if (m->status == BB_STATUS_DECISION && m->stack_top > 0) {
            int p = m->stack[m->stack_top - 1].proc;
            enum_ns[p] += prof_ns[BBE_PROF_LEGAL] - legal_before;
            enum_calls[p]++;
            enum_actions[p] += (uint64_t)env.n_legal;
        }
        if (terminals[0] != 0.0f) {
            done++;
            if (env.log.error_episodes != errors_before) {
                ep_error++;
            } else if (prof_end_status == BB_STATUS_MATCH_OVER) {
                ep_match_over++;
            } else {
                ep_truncated++;
            }
        }
    }
    uint64_t t_total = now_ns() - t_total0;

    printf("outcomes: match_over=%d truncated=%d error=%d\n", ep_match_over,
           ep_truncated, ep_error);
    if (ep_error > 0) {
        // An error episode is a rejected decode or an empty legal set; its
        // step mix is not a game, so no number below would mean anything.
        fprintf(stderr,
                "bbe_profile: %d of %d episodes ended in ERROR; profile is "
                "invalid\n", ep_error, done);
        return 1;
    }
    double secs = (double)t_total / 1e9;
    printf("steps %ld  decisions %ld  episodes %d  steps/episode %.1f  "
           "wall %.3fs\n", steps, decisions, done, (double)steps / done, secs);
    printf("avg n_legal at decisions: %.1f\n",
           decisions ? (double)n_legal_sum / (double)decisions : 0.0);
    // Confirms field=value reward overrides reached the env.
    printf("mean home episode_return: %+.4f\n",
           env.log.n > 0 ? (double)env.log.episode_return / env.log.n : 0.0);
#ifdef BBE_PROFILE_UNTIMED
    printf("untimed steps/sec (1 core, incl. driver sampling): %.0f\n",
           (double)steps / secs);
#else
    uint64_t t_env = 0;
    for (int p = BBE_PROF_REWARD; p < BBE_PROF_COUNT; p++) t_env += prof_ns[p];
    double clock_per_step = (double)prof_switches / (double)steps;
    printf("\n-- per-step cost (ns; hook timer cost included, "
           "%.1f clock reads/step at %.1f ns = %.0f ns/step) --\n",
           clock_per_step, ns_per_clock, clock_per_step * ns_per_clock);
    for (int p = BBE_PROF_REWARD; p < BBE_PROF_COUNT; p++) {
        printf("  %-26s %8.0f  %5.1f%%\n", phase_name(p),
               (double)prof_ns[p] / (double)steps,
               100.0 * (double)prof_ns[p] / (double)t_env);
    }
    printf("  %-26s %8.0f\n", "TOTAL c_step",
           (double)t_env / (double)steps);
    printf("  %-26s %8.0f\n", phase_name(BBE_PROF_DRIVER),
           (double)prof_ns[BBE_PROF_DRIVER] / (double)steps);
    printf("timed steps/sec (1 core, incl. driver + timers): %.0f\n",
           (double)steps / secs);

    printf("\n-- by decision proc (apply keyed on the decided proc; "
           "enumeration on the proc enumerated) --\n");
    printf("  %-12s %10s %12s %10s %10s %11s %12s\n", "proc", "decisions",
           "apply ns/dec", "enum-calls", "ns/call", "actions/c",
           "enum total%");
    uint64_t enum_total = 0;
    for (int p = 0; p < BB_PROC_COUNT; p++) enum_total += enum_ns[p];
    for (int p = 0; p < BB_PROC_COUNT; p++) {
        if (!enum_calls[p] && !dec_by_proc[p]) continue;
        printf("  %-12s %10llu %12.0f %10llu %10.0f %11.1f %11.1f%%\n",
               proc_name(p), (unsigned long long)dec_by_proc[p],
               dec_by_proc[p] ? (double)apply_ns_by_proc[p] /
                                    (double)dec_by_proc[p] : 0.0,
               (unsigned long long)enum_calls[p],
               enum_calls[p] ? (double)enum_ns[p] / (double)enum_calls[p] : 0.0,
               enum_calls[p] ? (double)enum_actions[p] /
                                   (double)enum_calls[p] : 0.0,
               enum_total ? 100.0 * (double)enum_ns[p] / (double)enum_total
                          : 0.0);
    }
#endif
    if (smoke) {
        int top = -1;
        for (int p = 0; p < BB_PROC_COUNT; p++) {
            if (enum_calls[p] && (top < 0 || enum_ns[p] > enum_ns[top])) top = p;
        }
        int require_top = 1;
#ifdef BBE_PROFILE_UNTIMED
        require_top = 0;
#endif
        if (ep_match_over != done ||
            (require_top && top != BB_PROC_ACTIVATION)) {
            fprintf(stderr,
                    "bbe_profile smoke FAIL: match_over=%d of %d episodes, "
                    "top enumeration proc %s (expected ACTIVATION)\n",
                    ep_match_over, done, top >= 0 ? proc_name(top) : "none");
            return 1;
        }
        printf("bbe_profile smoke OK: %d/%d MATCH_OVER, ACTIVATION dominates "
               "enumeration\n", ep_match_over, done);
    }
    return 0;
}
