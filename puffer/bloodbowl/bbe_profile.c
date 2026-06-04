// bbe_profile.c — instrumented mirror of the standalone driver's step loop.
// Replicates c_step's state trajectory (decode -> bb_apply -> refresh ->
// emit) with nanosecond timers around each phase plus per-proc attribution
// of legal-action enumeration. Measurement-only tool: the production
// c_step/bb_apply paths are untouched; throughput claims come from the
// untimed driver (bloodbowl.c), this file explains WHERE the time goes.
//
// Build: clang -O2 -Ipuffer/bloodbowl puffer/bloodbowl/bbe_profile.c -o bbe_profile
#include "bloodbowl.h"
#include <stdio.h>
#include <time.h>

static inline uint64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

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

// Per-phase accumulators (ns).
static uint64_t t_sample, t_decode, t_enum_pre, t_eqscan, t_apply_inner,
    t_refresh, t_tz, t_encode, t_mask;
// Per-proc enumeration attribution: time + calls + action counts, summed over
// BOTH enumerations a step pays for (bb_apply re-validation ~= pre-proxy,
// bbe_refresh_legal measured directly).
static uint64_t enum_ns[BB_PROC_COUNT];
static uint64_t enum_calls[BB_PROC_COUNT];
static uint64_t enum_actions[BB_PROC_COUNT];
static uint64_t dec_by_proc[BB_PROC_COUNT];
static uint64_t mask_ns_by_proc[BB_PROC_COUNT]; // deciding-agent fill keyed on proc
static uint64_t decode_ns_by_proc[BB_PROC_COUNT];

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

int main(int argc, char** argv) {
    int episodes = argc > 1 ? atoi(argv[1]) : 200;
    uint64_t seed = 42;

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
    bb_rng_seed(&pol, seed ^ 0xBADC0DE, 3);

    static bb_action scratch[BB_LEGAL_MAX];
    long steps = 0, n_legal_sum = 0;
    int done = 0;
    uint64_t t_total0 = now_ns();
    while (done < episodes) {
        bb_match* m = &env.match;
        uint64_t t0, t1;

        // --- driver-side mask sampling (not env cost; tracked separately)
        t0 = now_ns();
        for (int a = 0; a < BBE_AGENTS; a++) {
            const unsigned char* mk = env.action_mask_ptr[a];
            env.action_ptr[a][0] = (float)sample_masked(mk, BBE_HEAD_TYPE, &pol);
            env.action_ptr[a][1] = (float)sample_masked(mk + BBE_HEAD_TYPE, BBE_HEAD_ARG, &pol);
            env.action_ptr[a][2] = (float)sample_masked(
                mk + BBE_HEAD_TYPE + BBE_HEAD_ARG, BBE_HEAD_SQ, &pol);
        }
        t_sample += now_ns() - t0;

        // --- c_step mirror -------------------------------------------------
        int top_proc = -1;
        if (m->status == BB_STATUS_DECISION && env.n_legal > 0) {
            int agent = m->decision_team;
            top_proc = m->stack[m->stack_top - 1].proc;
            dec_by_proc[top_proc]++;
            n_legal_sum += env.n_legal;

            t0 = now_ns();
            bb_action act = bbe_decode(&env, agent, env.action_ptr[agent]);
            t1 = now_ns();
            t_decode += t1 - t0;
            decode_ns_by_proc[top_proc] += t1 - t0;

            // Proxy for bb_apply's INTERNAL re-enumeration: same state, same
            // proc->legal call. Measured separately so the re-validation tax
            // can be split out of bb_apply's total.
            t0 = now_ns();
            int n_pre = bb_legal_actions(m, scratch);
            t1 = now_ns();
            t_enum_pre += t1 - t0;
            enum_ns[top_proc] += t1 - t0;
            enum_calls[top_proc]++;
            enum_actions[top_proc] += (uint64_t)n_pre;

            // Proxy for bb_apply's membership eq-scan (average position =
            // half the list for uniform-random picks).
            t0 = now_ns();
            volatile bool ok = false;
            for (int i = 0; i < n_pre; i++) {
                if (bb_action_eq(scratch[i], act)) { ok = true; break; }
            }
            (void)ok;
            t1 = now_ns();
            t_eqscan += t1 - t0;

            // The real thing (validation + apply + advance), as production runs it.
            t0 = now_ns();
            bb_apply(m, act, &env.rng);
            t1 = now_ns();
            t_apply_inner += t1 - t0;
            env.decisions++;
        }
        if (m->status == BB_STATUS_ERROR ||
            (m->status == BB_STATUS_DECISION && env.n_legal <= 0)) {
            bbe_finish_episode(&env);
            done++; // mirror terminal bookkeeping
        } else if (m->status == BB_STATUS_MATCH_OVER ||
                   env.decisions >= env.max_decisions) {
            bbe_finish_episode(&env);
            done++;
        }

        t0 = now_ns();
        bbe_refresh_legal(&env);
        t1 = now_ns();
        t_refresh += t1 - t0;
        if (m->status == BB_STATUS_DECISION && m->stack_top > 0) {
            int p = m->stack[m->stack_top - 1].proc;
            enum_ns[p] += t1 - t0;
            enum_calls[p]++;
            enum_actions[p] += (uint64_t)env.n_legal;
        }

        // Shared TZ scratch (bbe_emit_all does this once before the encodes).
        t0 = now_ns();
        bbe_compute_tz(&env);
        t1 = now_ns();
        t_tz += t1 - t0;

        for (int a = 0; a < BBE_AGENTS; a++) {
            t0 = now_ns();
            bbe_encode_obs(&env, a);
            t1 = now_ns();
            t_encode += t1 - t0;
            t0 = t1;
            bbe_fill_mask(&env, a);
            t1 = now_ns();
            t_mask += t1 - t0;
            if (m->status == BB_STATUS_DECISION && m->decision_team == a &&
                m->stack_top > 0) {
                mask_ns_by_proc[m->stack[m->stack_top - 1].proc] += t1 - t0;
            }
        }
        steps++;
    }
    uint64_t t_total = now_ns() - t_total0;

    uint64_t t_env = t_decode + t_apply_inner + t_refresh + t_tz + t_encode + t_mask;
    double per_step = (double)t_env / (double)steps;
    printf("steps %ld  episodes %d  wall %.2fs  (timer overhead included)\n",
           steps, done, (double)t_total / 1e9);
    printf("avg n_legal at decisions: %.1f\n",
           (double)n_legal_sum / (double)steps);
    printf("\n-- per-step env cost (ns, driver sampling excluded) --\n");
#define ROW(name, v) printf("  %-26s %8.0f  %5.1f%%\n", name, \
    (double)(v) / (double)steps, 100.0 * (double)(v) / (double)t_env)
    ROW("decode (3-pass snap)", t_decode);
    ROW("bb_apply total", t_apply_inner);
    printf("    of which (proxied on identical state):\n");
    ROW("  ~re-enumeration", t_enum_pre);
    ROW("  ~membership eq-scan", t_eqscan);
    ROW("bbe_refresh_legal", t_refresh);
    ROW("compute tz scratch", t_tz);
    ROW("encode obs x2", t_encode);
    ROW("fill mask x2", t_mask);
    printf("  %-26s %8.0f\n", "TOTAL env", per_step);
    printf("  %-26s %8.0f\n", "driver mask sampling", (double)t_sample / (double)steps);
#undef ROW

    printf("\n-- enumeration by proc (both calls per step) --\n");
    printf("  %-12s %10s %12s %9s %11s %12s %12s\n", "proc", "decisions",
           "enum-calls", "ns/call", "actions/c", "enum total%", "mask+dec ns");
    uint64_t enum_total = 0;
    for (int p = 0; p < BB_PROC_COUNT; p++) enum_total += enum_ns[p];
    for (int p = 0; p < BB_PROC_COUNT; p++) {
        if (!enum_calls[p]) continue;
        printf("  %-12s %10llu %12llu %9.0f %11.1f %11.1f%% %12.0f\n",
               proc_name(p), (unsigned long long)dec_by_proc[p],
               (unsigned long long)enum_calls[p],
               (double)enum_ns[p] / (double)enum_calls[p],
               (double)enum_actions[p] / (double)enum_calls[p],
               100.0 * (double)enum_ns[p] / (double)enum_total,
               (double)(mask_ns_by_proc[p] + decode_ns_by_proc[p]));
    }
    return 0;
}
