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
static long st_tz_nonzero;    // marking-TZ bytes observed > 0 (coverage)
static long st_plane_nonzero; // obs-v3 TZ-plane bytes observed > 0 (coverage)
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
static long st_v4_b_bytes, st_v4_a_bytes;

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
        // [8] pending-TEST target (2..6 at a TEST reroll window, else 0).
        int exp_target = top->proc == BB_PROC_TEST ? top->x : 0;
        ST_CHECK(b[8] == exp_target, "proc %d agent %d: test-target byte %d != %d",
                 top->proc, agent, b[8], exp_target);
        if (top->proc == BB_PROC_TEST) {
            ST_CHECK(b[8] >= 2 && b[8] <= 6, "TEST target %d outside 2..6", b[8]);
        }
        // Review M14's exact repro: at every ACTIVATE decision (TEAM_TURN on
        // top, a = team id 0/1) BOTH agents must see "no slot" — the away
        // agent used to see "opponent row 17" for the home team's turn.
        // Obs-v4 plane invariants (docs/obs-v4-spec.md): planes belong to
        // the DECIDING agent at MOVE-proc decisions only; fill counts must
        // track the legal list (B bytes <= legal steps; A nonempty iff
        // block targets legal — min realistic P(def down) is ~3%, byte 7).
        {
            const unsigned char* o = env->obs_ptr[agent];
            int bfill = 0, afill = 0;
            for (int k = 0; k < BBE_TZ_PLANE; k++) {
                if (o[BBE_B_OFF + k]) bfill++;
                if (o[BBE_A1_OFF + k] || o[BBE_A2_OFF + k]) afill++;
            }
            int deciding = (m->decision_team & 1) == agent;
            int moveproc = top->proc == BB_PROC_MOVE && top->a < BB_NUM_PLAYERS;
            if (!deciding || !moveproc) {
                ST_CHECK(bfill == 0 && afill == 0,
                         "v4 planes filled out of context (proc %d agent %d "
                         "deciding %d: B=%d A=%d)",
                         top->proc, agent, deciding, bfill, afill);
            } else {
                int steps = 0, tgts = 0;
                for (int i = 0; i < env->n_legal; i++) {
                    if (env->legal[i].type == BB_A_STEP) steps++;
                    if (env->legal[i].type == BB_A_BLOCK_TARGET) tgts++;
                }
                ST_CHECK(bfill <= steps, "plane B overfilled (%d > %d legal)",
                         bfill, steps);
                ST_CHECK(afill <= tgts, "plane A overfilled (%d > %d legal)",
                         afill, tgts);
                ST_CHECK(steps == 0 || bfill > 0,
                         "steps legal but plane B empty (%d steps)", steps);
                ST_CHECK(tgts == 0 || afill > 0,
                         "block targets legal but plane A empty (%d)", tgts);
                st_v4_b_bytes += bfill;
                st_v4_a_bytes += afill;
            }
        }
        if (top->proc == BB_PROC_TEAM_TURN) {
            ST_CHECK(b[6] == 0, "TEAM_TURN leaked team id as slot %d to agent %d",
                     b[6], agent);
        }
        // Player records: [23] = opposing tackle zones marking the player's
        // square (on-pitch only, else 0).
        for (int row = 0; row < BB_NUM_PLAYERS; row++) {
            int team = row < BB_TEAM_SLOTS ? agent : 1 - agent;
            int slot = team * BB_TEAM_SLOTS + (row & 15);
            const bb_player* p = &m->players[slot];
            const unsigned char* t = env->obs_ptr[agent] + row * BBE_PLAYER_BYTES;
            int exp_tz = p->location == BB_LOC_ON_PITCH
                             ? bb_tackle_zones(m, team, p->x, p->y)
                             : 0;
            ST_CHECK(t[23] == exp_tz, "agent %d row %d: marking-TZ byte %d != %d",
                     agent, row, t[23], exp_tz);
            if (t[23] > 0) st_tz_nonzero++;
            // [11..22] skill ids: re-derive straight from the engine
            // skillset. The encoder caches these rows per slot behind a
            // skillset dirty-check; a stale or mis-keyed cache must fail
            // loudly here, not silently feed the policy wrong skills.
            unsigned char want[BBE_SKILL_SLOTS] = {0};
            int k = 0;
            for (int sk = bb_next_skill(&p->skills, 0);
                 sk >= 0 && k < BBE_SKILL_SLOTS;
                 sk = bb_next_skill(&p->skills, sk + 1)) {
                want[k++] = (unsigned char)(sk + 1);
            }
            ST_CHECK(memcmp(t + 11, want, BBE_SKILL_SLOTS) == 0,
                     "agent %d row %d: skill row diverges from skillset",
                     agent, row);
        }
        // [BBE_TZ_OFF..] obs-v3 tackle-zone planes (my coverage, then the
        // opponent's), spot-checked against the engine's bb_tackle_zones —
        // which counts the TZs the OPPOSING team of its `team` argument
        // exerts on a square, so "my plane" must match a query for the
        // opponent team and vice versa. Squares: every on-pitch player's
        // square (where counts cluster) plus a fixed 24-point lattice
        // (gcd(7,26)=1 / gcd(5,15)=5 walks cover empty regions and both
        // mirrored edges). The away agent's check exercises the x-mirror.
        const unsigned char* tz_my = env->obs_ptr[agent] + BBE_TZ_OFF;
        const unsigned char* tz_op = tz_my + BBE_TZ_PLANE;
        for (int i = 0; i < BB_NUM_PLAYERS + 24; i++) {
            int x, y;
            if (i < BB_NUM_PLAYERS) {
                const bb_player* p = &m->players[i];
                if (p->location != BB_LOC_ON_PITCH) continue;
                x = p->x;
                y = p->y;
            } else {
                x = ((i - BB_NUM_PLAYERS) * 7) % BB_PITCH_LEN;
                y = ((i - BB_NUM_PLAYERS) * 5 + i) % BB_PITCH_WID;
            }
            int ex = agent == BB_AWAY ? BB_PITCH_LEN - 1 - x : x;
            int idx = y * BB_PITCH_LEN + ex;
            int mine = bb_tackle_zones(m, 1 - agent, x, y);
            int theirs = bb_tackle_zones(m, agent, x, y);
            ST_CHECK(tz_my[idx] == mine,
                     "agent %d square %d,%d: my-TZ plane %d != %d",
                     agent, x, y, tz_my[idx], mine);
            ST_CHECK(tz_op[idx] == theirs,
                     "agent %d square %d,%d: opp-TZ plane %d != %d",
                     agent, x, y, tz_op[idx], theirs);
            st_plane_nonzero += (mine > 0) + (theirs > 0);
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
        // Behavioral micro-stat counters: monotone within an episode, zeroed
        // by the episode reset (each step applies ONE action, so a counter
        // may grow by at most a bounded amount, but never shrink mid-game).
        int ep_prev[8] = {env.ep_blocks,          env.ep_blitzes,
                          env.ep_dodge_attempts,  env.ep_gfi_attempts,
                          env.ep_pickup_attempts, env.ep_pass_attempts,
                          env.ep_knockdowns_inflicted, env.ep_knockdowns_own};
        c_step(&env);
        int ep_now[8] = {env.ep_blocks,          env.ep_blitzes,
                         env.ep_dodge_attempts,  env.ep_gfi_attempts,
                         env.ep_pickup_attempts, env.ep_pass_attempts,
                         env.ep_knockdowns_inflicted, env.ep_knockdowns_own};
        if (terminals[0] != 0.0f) {
            done++;
            for (int k = 0; k < 8; k++) {
                ST_CHECK(ep_now[k] == 0,
                         "micro-stat %d not reset by the episode reset (%d)",
                         k, ep_now[k]);
            }
        } else {
            for (int k = 0; k < 8; k++) {
                ST_CHECK(ep_now[k] >= ep_prev[k],
                         "micro-stat %d shrank mid-episode (%d -> %d)",
                         k, ep_prev[k], ep_now[k]);
            }
        }
    }
    // Coverage: random masked play must exercise every micro-stat counter
    // (64 episodes ~ 17k decisions; each of these fires hundreds of times).
    ST_CHECK(env.log.blocks > 0, "no block declared in random play");
    ST_CHECK(env.log.blitzes > 0, "no blitz declared in random play");
    ST_CHECK(env.log.dodge_attempts > 0, "no dodge attempted in random play");
    ST_CHECK(env.log.gfi_attempts > 0, "no rush attempted in random play");
    ST_CHECK(env.log.pickup_attempts > 0, "no pickup attempted in random play");
    ST_CHECK(env.log.pass_attempts > 0, "no pass attempted in random play");
    ST_CHECK(env.log.knockdowns_own > 0 && env.log.knockdowns_inflicted > 0,
             "no knockdowns counted in random play (%g own / %g inflicted)",
             env.log.knockdowns_own, env.log.knockdowns_inflicted);
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
    ST_CHECK(st_tz_nonzero > 0,
             "no marked player ever observed — TZ byte coverage is vacuous");
    ST_CHECK(st_plane_nonzero > 0,
             "no nonzero TZ-plane square ever checked — plane coverage vacuous");
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
    ST_CHECK(st_v4_b_bytes > 0 && st_v4_a_bytes > 0,
             "v4 planes never exercised (B=%ld A=%ld)", st_v4_b_bytes,
             st_v4_a_bytes);
    printf("bloodbowl selftest: %d episodes, %d failure(s), v4 planes B=%ld A=%ld\n",
           done, st_failures, st_v4_b_bytes, st_v4_a_bytes);
    return st_failures ? 1 : 0;
}

// --- Demo-reset start telemetry (--demo) ---------------------------------------
// Record the start state of each episode (the env resets itself inside
// bbe_finish_episode, so right after c_reset / a terminal step env.match IS
// the next episode's start). Prints a few sanity lines plus the half/turn
// histogram of episode starts — should mirror the staged bank's histogram
// when --demo forces demo_reset_pct = 1.
#define DEMO_PRINT_STARTS 8
static long demo_start_hist[3][9]; // [half-1][turn], halves 1..2 (+overtime)
static long demo_starts;

static void demo_note_start(const Bloodbowl* env) {
    const bb_match* m = &env->match;
    int half = m->half >= 1 && m->half <= 3 ? m->half : 3;
    int turn = m->turn[m->active_team & 1];
    if (turn > 8) turn = 8;
    demo_start_hist[half - 1][turn]++;
    if (demo_starts < DEMO_PRINT_STARTS) {
        printf("  episode start: half=%d turn=%d score=%d-%d %s\n", m->half,
               m->turn[m->active_team & 1], m->score[0], m->score[1],
               env->demo_started ? "(banked state)" : "(procgen kickoff)");
    }
    demo_starts++;
}

static void demo_print_hist(void) {
    printf("  -- episode-start half/turn histogram (%ld starts) --\n",
           demo_starts);
    printf("  turn    ");
    for (int t = 1; t <= 8; t++) printf("%6d", t);
    printf("\n");
    for (int h = 0; h < 3; h++) {
        long row = 0;
        for (int t = 1; t <= 8; t++) row += demo_start_hist[h][t];
        if (row == 0 && h >= 2) continue;
        printf("  half %d  ", h + 1);
        for (int t = 1; t <= 8; t++) printf("%6ld", demo_start_hist[h][t]);
        printf("\n");
    }
}

int main(int argc, char** argv) {
    int episodes = 64;
    int unmasked = 0;
    int selftest = 0;
    int demo = 0;
    int fnv_mode = 0;
    uint64_t seed = 42;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--unmasked") == 0) unmasked = 1;
        else if (strcmp(argv[i], "--fnv") == 0) fnv_mode = 1;
        else if (strcmp(argv[i], "--selftest") == 0) selftest = 1;
        else if (strcmp(argv[i], "--demo") == 0) demo = 1;
        else if (strcmp(argv[i], "--bank") == 0 && i + 1 < argc) {
            // Override the staged-bank path (default BBE_STATE_BANK_PATH);
            // lets repo-root runs point straight at validation/states/bank.bbs.
            bbe_state_bank_path = argv[++i];
        }
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
    // --demo: every episode starts from a banked state (demo_reset_pct
    // forced to 1.0); episodes must still complete and the Log stay sane.
    if (demo) env.demo_reset_pct = 1.0f;
    c_reset(&env);
    if (demo) demo_note_start(&env);

    bb_rng pol;
    bb_rng_seed(&pol, seed ^ 0xBADC0DE, 3);

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    long steps = 0;
    int done = 0;
    uint64_t fnv = 1469598103934665603ULL;
#define FNV_BYTES(ptr, len)                                                    \
    do {                                                                       \
        const unsigned char* fb_ = (const unsigned char*)(ptr);               \
        for (size_t fi_ = 0; fi_ < (size_t)(len); fi_++) {                    \
            fnv ^= fb_[fi_];                                                  \
            fnv *= 1099511628211ULL;                                          \
        }                                                                      \
    } while (0)
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
        if (fnv_mode) {
            FNV_BYTES(obs, sizeof obs);
            FNV_BYTES(mask, sizeof mask);
            FNV_BYTES(env.legal_arg, (size_t)env.n_legal);
            FNV_BYTES(env.legal_sq, (size_t)env.n_legal * sizeof(uint16_t));
            FNV_BYTES(&env.n_legal, sizeof env.n_legal);
            FNV_BYTES(&env.illegal, sizeof env.illegal);
        }
        c_step(&env);
        steps++;
        if (fnv_mode) {
            FNV_BYTES(actions, sizeof actions);
            FNV_BYTES(rewards, sizeof rewards);     // Codex: prove reward equiv
            FNV_BYTES(terminals, sizeof terminals);
        }
        if (terminals[0] != 0.0f) {
            done++;
            if (demo && done < episodes) demo_note_start(&env);
        }
    }
    clock_gettime(CLOCK_MONOTONIC, &t1);
    if (fnv_mode) printf("  fnv              %016llx\n", (unsigned long long)fnv);
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
    printf("  -- behavioral micro-stats (per match) --\n");
    printf("  blocks           %.2f\n", lg->blocks / n);
    printf("  blitzes          %.2f\n", lg->blitzes / n);
    printf("  dodge_attempts   %.2f\n", lg->dodge_attempts / n);
    printf("  gfi_attempts     %.2f\n", lg->gfi_attempts / n);
    printf("  pickup_attempts  %.2f\n", lg->pickup_attempts / n);
    printf("  pass_attempts    %.2f\n", lg->pass_attempts / n);
    printf("  knockdowns       %.2f inflicted / %.2f own\n",
           lg->knockdowns_inflicted / n, lg->knockdowns_own / n);
    if (demo) {
        printf("  -- demo-state resets --\n");
        printf("  demo_episodes    %.2f (of %g episodes)\n",
               lg->demo_episodes / n, n);
        printf("  demo_fallbacks   %.2f (must be 0)\n", lg->demo_fallbacks / n);
        demo_print_hist();
    }
    c_close(&env);
    return 0;
}
