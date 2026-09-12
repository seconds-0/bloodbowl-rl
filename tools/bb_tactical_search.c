// Bounded counterfactual action search over the deterministic Blood Bowl engine.
// This is an offline diagnostic/teacher prototype; it does not inspect or copy a
// live environment RNG. Each branch gets reproducible, action-keyed dice streams.
#include "bloodbowl.h"
#include "bb_fixtures.h"

#include <inttypes.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

enum { TS_HORIZON = 28, TS_SAMPLES = 12 };
enum { FG_HORIZON = 64, FG_SAMPLES = 2, FG_DECISION_CAP = 50000 };
#define FG_GAME_LIMIT_SECONDS 20.0

static uint64_t mix64(uint64_t x) {
    x ^= x >> 30; x *= UINT64_C(0xbf58476d1ce4e5b9);
    x ^= x >> 27; x *= UINT64_C(0x94d049bb133111eb);
    return x ^ (x >> 31);
}

static uint64_t state_key(const bb_match* m) {
    const unsigned char* p = (const unsigned char*)m;
    size_t inactive_stack = offsetof(bb_match, stack) +
                            (size_t)m->stack_top * sizeof m->stack[0];
    size_t stack_end = offsetof(bb_match, stack) + sizeof m->stack;
    uint64_t h = UINT64_C(1469598103934665603);
    for (size_t i = 0; i < sizeof(*m); i++) {
        // Popped frames are engine scratch storage, but bb_pop deliberately
        // leaves their bytes behind. Hash them as zero so planner RNG streams
        // depend on the live stack only. Every byte outside this exact suffix,
        // including active frames and the rest of bb_match, remains hashed.
        unsigned char byte = i >= inactive_stack && i < stack_end ? 0 : p[i];
        h ^= byte;
        h *= UINT64_C(1099511628211);
    }
    return h;
}

static double value(const bb_match* m, int team) {
    int other = 1 - team;
    double v = 10000.0 * ((int)m->score[team] - (int)m->score[other]);
    if (m->ball.state == BB_BALL_HELD && m->ball.carrier < BB_NUM_PLAYERS) {
        int carrier_team = m->ball.carrier / BB_TEAM_SLOTS;
        const bb_player* p = &m->players[m->ball.carrier];
        int remaining = carrier_team == BB_HOME ? bb_endzone_x(BB_HOME) - p->x : p->x;
        double progress = 25.0 - remaining;
        v += carrier_team == team ? 120.0 + 3.0 * progress : -160.0 - 5.0 * progress;
    }
    bb_def_threat t = bb_def_threat_eval(m, team);
    v -= 220.0 * t.n_threats_1turn + 40.0 * t.n_threats_2turn;
    return v;
}

static bb_action rollout_pick(const bb_match* m, const bb_action* legal, int n, int root_team) {
    return m->decision_team == root_team ? bbe_offense_bot_pick(m, legal, n)
                                         : bbe_contact_bot_pick(m, legal, n);
}

static bb_action actual_opponent_pick(const bb_match* m, const bb_action* legal,
                                      int n, int offense_opponent) {
    return offense_opponent ? bbe_offense_bot_pick(m, legal, n)
                            : bbe_contact_bot_pick(m, legal, n);
}

static int counter_apply(bb_match* m, bb_action a, bb_rng* dice, int* failures) {
    bb_status st = bb_apply(m, a, dice);
    if (st == BB_STATUS_ERROR || bb_rng_error(dice)) {
        (*failures)++;
        return 0;
    }
    return 1;
}

static int counter_require_legal(int n, int* failures) {
    if (n > 0) return 1;
    (*failures)++;
    return 0;
}

static double branch(const bb_match* root, bb_action first, int root_team,
                     uint64_t seed, int horizon) {
    bb_match m = *root;
    bb_rng dice;
    bb_rng_seed(&dice, seed, 73);
    if (bb_apply(&m, first, &dice) == BB_STATUS_ERROR || bb_rng_error(&dice)) return -1e30;
    for (int d = 1; d < horizon && m.status == BB_STATUS_DECISION; d++) {
        bb_action legal[BB_LEGAL_MAX];
        int n = bb_legal_actions(&m, legal);
        if (n <= 0) break;
        bb_action a = rollout_pick(&m, legal, n, root_team);
        if (bb_apply(&m, a, &dice) == BB_STATUS_ERROR || bb_rng_error(&dice)) return -1e30;
        if (m.score[root_team] != root->score[root_team] ||
            m.score[1-root_team] != root->score[1-root_team]) break;
    }
    return value(&m, root_team);
}

static bb_action tactical_pick(const bb_match* m, const bb_action* legal, int n,
                               int samples, int horizon) {
    uint64_t key = state_key(m);
    int team = m->active_team;
    int best = 0;
    double best_v = -1e100;
    for (int i = 0; i < n; i++) {
        double sum = 0.0;
        for (int s = 0; s < samples; s++) {
            // Common random numbers across actions reduce comparison variance.
            // The stream derives only from the public root bytes and sample id.
            uint64_t seed = mix64(key ^ ((uint64_t)(s + 1) << 32));
            sum += branch(m, legal[i], team, seed, horizon);
        }
        if (sum > best_v) { best_v = sum; best = i; }
    }
    return legal[best];
}

// Full-game proposal layer: retain the offense bot on an exact tie and only
// override its root activation when engine rollouts improve actual TD utility.
// No shaping term participates in this comparison.
static bb_action objective_pick(const bb_match* m, const bb_action* legal, int n,
                                int* counter_failures) {
    bb_action baseline = bbe_offense_bot_pick(m, legal, n);
    int baseline_i = 0;
    for (int i = 0; i < n; i++) if (bb_action_eq(legal[i], baseline)) baseline_i = i;
    uint64_t key = state_key(m);
    int team = m->active_team;
    int best = baseline_i;
    double best_v = -1e100;
    for (int i = 0; i < n; i++) {
        double sum = 0.0;
        for (int s = 0; s < FG_SAMPLES; s++) {
            bb_match r = *m;
            bb_rng dice;
            bb_rng_seed(&dice, mix64(key ^ ((uint64_t)(s + 1) << 32)), 73);
            if (!counter_apply(&r, legal[i], &dice, counter_failures)) { sum = -1e30; break; }
            for (int d = 1; d < FG_HORIZON && r.status == BB_STATUS_DECISION; d++) {
                bb_action next[BB_LEGAL_MAX]; int nn = bb_legal_actions(&r, next);
                if (!counter_require_legal(nn, counter_failures)) { sum = -1e30; break; }
                bb_action a = rollout_pick(&r, next, nn, team);
                if (!counter_apply(&r, a, &dice, counter_failures)) { sum = -1e30; break; }
                if (r.score[team] != m->score[team] || r.score[1-team] != m->score[1-team]) break;
            }
            sum += 10000.0 * ((int)r.score[team] - (int)m->score[team]
                            - (int)r.score[1-team] + (int)m->score[1-team]);
        }
        // Strict improvement preserves the scripted baseline on the many
        // short-horizon TD-utility ties.
        if (sum > best_v || (sum == best_v && i == baseline_i)) {
            best_v = sum; best = i;
        }
    }
    return legal[best];
}

static void scoring_fixture(bb_match* m, int y, int decoys) {
    fx_match_midturn(m, BB_HOME, 2);
    int carrier = fx_lineman(m, BB_HOME, 0, 24, y);
    fx_ball_held(m, carrier);
    for (int i = 0; i < decoys; i++) fx_lineman(m, BB_HOME, i + 1, 16 + i, 2 + i);
    for (int i = 0; i < 3; i++) fx_lineman(m, BB_AWAY, i, 12, 4 + 2*i);
    bb_rng dice; bb_rng_seed(&dice, 1000u + (unsigned)y, 1);
    (void)fx_run(m, &dice);
    // Held-out variants keep decoys on pitch as obstacles but make the root
    // choice tactical: activate the scorer now or voluntarily end the turn.
    for (int i = 0; i < decoys; i++) m->players[i + 1].flags |= BB_PF_USED;
}

static int action_scores(const bb_match* start, bb_action first, uint64_t seed) {
    bb_match m = *start;
    bb_rng dice; bb_rng_seed(&dice, seed, 73);
    int initial = m.score[BB_HOME];
    if (bb_apply(&m, first, &dice) == BB_STATUS_ERROR) return 0;
    for (int d = 1; d < TS_HORIZON && m.status == BB_STATUS_DECISION; d++) {
        bb_action legal[BB_LEGAL_MAX]; int n = bb_legal_actions(&m, legal);
        if (n <= 0) break;
        bb_action a = rollout_pick(&m, legal, n, BB_HOME);
        if (bb_apply(&m, a, &dice) == BB_STATUS_ERROR) break;
        if (m.score[BB_HOME] > initial) return 1;
    }
    return m.score[BB_HOME] > initial;
}

static double elapsed_us(struct timespec a, struct timespec b) {
    return (b.tv_sec-a.tv_sec)*1e6 + (b.tv_nsec-a.tv_nsec)/1e3;
}

typedef struct {
    int completed, errors, counter_errors, decisions, search_roots, overrides;
    int score_for, score_against;
    double search_us;
    double runtime_us;
} GameResult;

static GameResult full_game(uint64_t seed, int tested_team, int use_search,
                            int offense_opponent) {
    GameResult out = {0};
    struct timespec game_start, game_now;
    clock_gettime(CLOCK_MONOTONIC, &game_start);
    bb_rng procgen, dice;
    bb_rng_seed(&procgen, seed * 9973u + 0xC0A7AC7u, 11);
    bb_rng_seed(&dice, seed * 7919u + 0xB10CBB01u, 1);
    bb_match m;
    bb_procgen_params pp = bb_procgen_params_default();
    bb_match_init_random_p(&m, &procgen, &pp);
    bb_advance(&m, &dice);
    while (m.status == BB_STATUS_DECISION && out.decisions < FG_DECISION_CAP) {
        clock_gettime(CLOCK_MONOTONIC, &game_now);
        if (elapsed_us(game_start, game_now) > FG_GAME_LIMIT_SECONDS * 1e6) {
            out.errors++; break;
        }
        bb_action legal[BB_LEGAL_MAX]; int n = bb_legal_actions(&m, legal);
        if (n <= 0) { out.errors++; break; }
        bb_action pick;
        if (m.decision_team == tested_team) {
            bb_action baseline = bbe_offense_bot_pick(&m, legal, n);
            const bb_frame* top = m.stack_top ? &m.stack[m.stack_top - 1] : NULL;
            if (use_search && top && top->proc == BB_PROC_TEAM_TURN && n > 1) {
                struct timespec a, b; clock_gettime(CLOCK_MONOTONIC, &a);
                pick = objective_pick(&m, legal, n, &out.counter_errors);
                clock_gettime(CLOCK_MONOTONIC, &b);
                out.search_us += elapsed_us(a, b);
                out.search_roots++;
                out.overrides += !bb_action_eq(pick, baseline);
            } else {
                pick = baseline;
            }
        } else {
            pick = actual_opponent_pick(&m, legal, n, offense_opponent);
        }
        if (bb_apply(&m, pick, &dice) == BB_STATUS_ERROR || bb_rng_error(&dice)) {
            out.errors++; break;
        }
        out.decisions++;
    }
    out.completed = m.status == BB_STATUS_MATCH_OVER;
    if (!out.completed && !out.errors) out.errors++;
    out.score_for = m.score[tested_team];
    out.score_against = m.score[1-tested_team];
    clock_gettime(CLOCK_MONOTONIC, &game_now);
    out.runtime_us = elapsed_us(game_start, game_now);
    return out;
}

static void add_result(GameResult* dst, GameResult x) {
    dst->completed += x.completed; dst->errors += x.errors;
    dst->counter_errors += x.counter_errors;
    dst->decisions += x.decisions; dst->search_roots += x.search_roots;
    dst->overrides += x.overrides; dst->score_for += x.score_for;
    dst->score_against += x.score_against; dst->search_us += x.search_us;
}

static int points(GameResult x) {
    return x.score_for > x.score_against ? 3 : x.score_for == x.score_against ? 1 : 0;
}

static int planner_regressions(void) {
    bb_match m;
    scoring_fixture(&m, 7, 2);
    if (m.stack_top == 0 || m.stack_top >= BB_STACK_MAX) return 0;
    bb_match inactive = m;
    inactive.stack[m.stack_top].y ^= BB_TA_FROM_BLITZ;
    if (state_key(&inactive) != state_key(&m)) return 0;
    bb_match active = m;
    active.stack[0].y ^= BB_TA_FROM_BLITZ;
    if (state_key(&active) == state_key(&m)) return 0;
    bb_action legal[BB_LEGAL_MAX]; int n = bb_legal_actions(&m, legal);
    if (n <= 0) return 0;
    m.active_team = BB_HOME;
    m.decision_team = BB_AWAY;
    bb_action got_contact = rollout_pick(&m, legal, n, BB_HOME);
    bb_action want_contact = bbe_contact_bot_pick(&m, legal, n);
    if (!bb_action_eq(got_contact, want_contact)) return 0;
    m.active_team = BB_AWAY;
    m.decision_team = BB_HOME;
    bb_action got_offense = rollout_pick(&m, legal, n, BB_HOME);
    bb_action want_offense = bbe_offense_bot_pick(&m, legal, n);
    if (!bb_action_eq(got_offense, want_offense)) return 0;
    if (!bb_action_eq(actual_opponent_pick(&m, legal, n, 0),
                      bbe_contact_bot_pick(&m, legal, n))) return 0;
    if (!bb_action_eq(actual_opponent_pick(&m, legal, n, 1),
                      bbe_offense_bot_pick(&m, legal, n))) return 0;

    int failures = 0;
    bb_rng dice; bb_rng_seed(&dice, 991, 73);
    bb_match bad = m;
    if (counter_apply(&bad, (bb_action){BB_A_NONE, 0, 0, 0}, &dice, &failures)) return 0;
    if (failures != 1 || bad.status != BB_STATUS_ERROR) return 0;
    if (counter_require_legal(0, &failures) || failures != 2) return 0;
    bb_match rng_bad = m;
    bb_rng_seed(&dice, 992, 73); dice.error = 1;
    if (counter_apply(&rng_bad, legal[0], &dice, &failures) || failures != 3) return 0;
    printf("planner_regressions ownership=pass actual_opponent=pass engine_failure=pass rng_failure=pass no_legal=pass\n");
    return 1;
}

int main(int argc, char** argv) {
    uint64_t seed_first = 101, seed_last = 116;
    const char* jsonl_path = "build/tactical-search.jsonl";
    const char* source_hash = "unrecorded";
    const char* phase = "exploratory";
    int self_test_only = 0;
    int offense_opponent = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--seed-first") && i + 1 < argc) seed_first = strtoull(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--seed-last") && i + 1 < argc) seed_last = strtoull(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--jsonl") && i + 1 < argc) jsonl_path = argv[++i];
        else if (!strcmp(argv[i], "--source-hash") && i + 1 < argc) source_hash = argv[++i];
        else if (!strcmp(argv[i], "--phase") && i + 1 < argc) phase = argv[++i];
        else if (!strcmp(argv[i], "--self-test")) self_test_only = 1;
        else if (!strcmp(argv[i], "--actual-opponent") && i + 1 < argc) {
            const char* style = argv[++i];
            if (!strcmp(style, "contact")) offense_opponent = 0;
            else if (!strcmp(style, "offense")) offense_opponent = 1;
            else { fprintf(stderr, "invalid actual opponent: %s\n", style); return 2; }
        }
        else { fprintf(stderr, "invalid argument: %s\n", argv[i]); return 2; }
    }
    if (seed_first > seed_last) {
        fprintf(stderr, "require an ordered seed range\n"); return 2;
    }
    if (!planner_regressions()) { fprintf(stderr, "planner regressions failed\n"); return 2; }
    if (self_test_only) return 0;
    FILE* jsonl = fopen(jsonl_path, "w");
    if (!jsonl) { perror(jsonl_path); return 2; }
    int cases = 0, random_wins = 0, offense_wins = 0, search_wins = 0;
    double total_us = 0.0, max_us = 0.0;
    uint64_t digest = 0;
    for (int heldout = 0; heldout < 24; heldout++) {
        bb_match m; scoring_fixture(&m, 1 + heldout % 13, 2 + heldout % 7);
        bb_action legal[BB_LEGAL_MAX]; int n = bb_legal_actions(&m, legal);
        if (n <= 1) { fprintf(stderr, "bad fixture %d\n", heldout); return 2; }
        bb_rng pick; bb_rng_seed(&pick, 0xC001u + (unsigned)heldout, 9);
        bb_action random = legal[bb_rng_next(&pick) % (uint32_t)n];
        bb_action offense = bbe_offense_bot_pick(&m, legal, n);
        struct timespec a, b; clock_gettime(CLOCK_MONOTONIC, &a);
        bb_action search = tactical_pick(&m, legal, n, TS_SAMPLES, TS_HORIZON);
        clock_gettime(CLOCK_MONOTONIC, &b);
        double us = elapsed_us(a, b); total_us += us; if (us > max_us) max_us = us;
        uint64_t outcome_seed = mix64(UINT64_C(0x5eed0000) + (uint64_t)heldout);
        random_wins += action_scores(&m, random, outcome_seed);
        offense_wins += action_scores(&m, offense, outcome_seed);
        search_wins += action_scores(&m, search, outcome_seed);
        digest = mix64(digest ^ (uint64_t)heldout ^ (uint64_t)search.type << 48 ^
                       (uint64_t)(search.arg + 1) << 24 ^
                       (uint64_t)(search.x + 1) << 12 ^ (uint64_t)(search.y + 1));
        cases++;
    }
    printf("tactical_search cases=%d samples=%d horizon=%d\n", cases, TS_SAMPLES, TS_HORIZON);
    printf("score_within_horizon random=%d/%d offense=%d/%d search=%d/%d\n",
           random_wins, cases, offense_wins, cases, search_wins, cases);
    printf("latency_us mean=%.1f max=%.1f digest=%016" PRIx64 "\n",
           total_us/cases, max_us, digest);

    GameResult base = {0}, searched = {0};
    int base_points = 0, search_points = 0, paired_games = 0;
    struct timespec fg_a, fg_b; clock_gettime(CLOCK_MONOTONIC, &fg_a);
    for (uint64_t seed = seed_first; seed <= seed_last; seed++) {
        for (int side = BB_HOME; side <= BB_AWAY; side++) {
            GameResult b = full_game(seed, side, 0, offense_opponent);
            GameResult s = full_game(seed, side, 1, offense_opponent);
            add_result(&base, b); add_result(&searched, s);
            base_points += points(b); search_points += points(s); paired_games++;
            fprintf(jsonl,
                    "{\"phase\":\"%s\",\"actual_opponent\":\"%s\",\"seed\":%" PRIu64 ",\"side\":\"%s\","
                    "\"base_for\":%d,\"base_against\":%d,\"search_for\":%d,"
                    "\"search_against\":%d,\"base_points\":%d,\"search_points\":%d,"
                    "\"base_decisions\":%d,\"search_decisions\":%d,\"root_calls\":%d,"
                    "\"overrides\":%d,\"base_runtime_us\":%.1f,\"search_runtime_us\":%.1f,"
                    "\"search_compute_us\":%.1f,\"base_errors\":%d,\"search_errors\":%d,"
                    "\"base_counter_errors\":%d,\"search_counter_errors\":%d,"
                    "\"base_complete\":%d,\"search_complete\":%d,\"source_sha256\":\"%s\"}\n",
                    phase, offense_opponent ? "offense" : "contact", seed,
                    side == BB_HOME ? "home" : "away", b.score_for,
                    b.score_against, s.score_for, s.score_against, points(b), points(s),
                    b.decisions, s.decisions, s.search_roots, s.overrides, b.runtime_us,
                    s.runtime_us, s.search_us, b.errors, s.errors, b.counter_errors,
                    s.counter_errors, b.completed, s.completed,
                    source_hash);
            printf("pair seed=%" PRIu64 " side=%s base=%d-%d search=%d-%d "
                   "overrides=%d roots=%d errors=%d/%d\n", seed,
                   side == BB_HOME ? "home" : "away",
                   b.score_for, b.score_against, s.score_for, s.score_against,
                   s.overrides, s.search_roots, b.errors, s.errors);
        }
    }
    fclose(jsonl);
    clock_gettime(CLOCK_MONOTONIC, &fg_b);
    printf("full_games phase=%s paired=%d complete=%d/%d errors=%d/%d counter_errors=%d/%d "
           "points=%d/%d td=%d-%d/%d-%d decisions=%d/%d\n", phase, paired_games,
           base.completed, searched.completed, base.errors, searched.errors,
           base.counter_errors, searched.counter_errors,
           base_points, search_points, base.score_for, base.score_against,
           searched.score_for, searched.score_against, base.decisions, searched.decisions);
    int total_roots = searched.search_roots;
    double total_search_us = searched.search_us;
    printf("full_search roots=%d overrides=%d mean_root_us=%.1f wall_s=%.3f\n",
           total_roots, searched.overrides,
           total_roots ? total_search_us/total_roots : 0.0,
           elapsed_us(fg_a, fg_b)/1e6);
    return search_wins == cases && search_wins > random_wins &&
           base.completed == paired_games && searched.completed == paired_games &&
           base.errors == 0 && searched.errors == 0 &&
           base.counter_errors == 0 && searched.counter_errors == 0 ? 0 : 1;
}
