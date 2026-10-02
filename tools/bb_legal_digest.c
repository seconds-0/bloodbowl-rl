// bb_legal_digest.c - per-game digests of every legal-action set and action
// mask, for bit-identity checks between two engine builds (build this file
// against each tree and diff the outputs).
//
//   engine games: seeded fx_pick_smart play through bb_legal_actions/bb_apply;
//                 hashes n_legal and every packed legal action per decision.
//   env episodes: the training c_reset/c_step path with exact-joint uniform
//                 sampling; hashes both agents' obs and masks, n_legal, the
//                 legal list and its projections, actions, rewards, terminals.
//
// Usage: bb_legal_digest [--games N] [--episodes N] [--seed S]
#include "bloodbowl.h"
#include "bb_fixtures.h"
#include <stdio.h>

#define FNV_INIT 1469598103934665603ULL

static uint64_t fnv_bytes(uint64_t h, const void* ptr, size_t len) {
    const unsigned char* b = (const unsigned char*)ptr;
    for (size_t i = 0; i < len; i++) {
        h ^= b[i];
        h *= 1099511628211ULL;
    }
    return h;
}

static uint64_t engine_games(int games, uint64_t seed) {
    uint64_t total = FNV_INIT;
    for (int g = 0; g < games; g++) {
        int home = g % BB_TEAM_COUNT;
        int away = (g / BB_TEAM_COUNT + g * 7 + 3) % BB_TEAM_COUNT;
        bb_match m;
        bb_match_init(&m, home, away);
        bb_rng rng, pick;
        bb_rng_seed(&rng, seed + (uint64_t)g * 7919, 1);
        bb_rng_seed(&pick, (seed + (uint64_t)g * 7919) ^ 0x5EED, 2);
        uint64_t h = FNV_INIT;
        long decisions = 0, legal_total = 0;
        bb_status st = bb_advance(&m, &rng);
        while (st == BB_STATUS_DECISION && decisions < 200000) {
            bb_action legal[BB_LEGAL_MAX];
            int n = bb_legal_actions(&m, legal);
            h = fnv_bytes(h, &n, sizeof n);
            for (int i = 0; i < n; i++) {
                uint32_t packed = bb_action_pack(legal[i]);
                h = fnv_bytes(h, &packed, sizeof packed);
            }
            if (n <= 0) break;
            legal_total += n;
            st = bb_apply(&m, legal[fx_pick_smart(&m, legal, n, &pick)], &rng);
            decisions++;
        }
        h = fnv_bytes(h, &st, sizeof st);
        h = fnv_bytes(h, m.score, sizeof m.score);
        printf("engine game %d teams %d-%d status %d decisions %ld legal %ld "
               "score %d-%d fnv %016llx\n",
               g, home, away, (int)st, decisions, legal_total, m.score[0],
               m.score[1], (unsigned long long)h);
        total = fnv_bytes(total, &h, sizeof h);
    }
    return total;
}

static uint64_t env_episodes(int episodes, uint64_t seed) {
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

    uint64_t total = FNV_INIT;
    uint64_t h = FNV_INIT;
    long steps = 0;
    int done = 0;
    while (done < episodes) {
        h = fnv_bytes(h, obs, sizeof obs);
        h = fnv_bytes(h, mask, sizeof mask);
        h = fnv_bytes(h, &env.n_legal, sizeof env.n_legal);
        for (int i = 0; i < env.n_legal; i++) {
            uint32_t packed = bb_action_pack(env.legal[i]);
            h = fnv_bytes(h, &packed, sizeof packed);
        }
        if (env.n_legal > 0) {
            h = fnv_bytes(h, env.legal_arg, (size_t)env.n_legal);
            h = fnv_bytes(h, env.legal_sq, (size_t)env.n_legal * sizeof(uint16_t));
        }
        for (int a = 0; a < BBE_AGENTS; a++) {
            bbe_sample_joint_uniform(&env, a, env.action_ptr[a], &pol);
        }
        c_step(&env);
        steps++;
        h = fnv_bytes(h, actions, sizeof actions);
        h = fnv_bytes(h, rewards, sizeof rewards);
        h = fnv_bytes(h, terminals, sizeof terminals);
        if (terminals[0] != 0.0f) {
            printf("env episode %d steps %ld fnv %016llx\n", done, steps,
                   (unsigned long long)h);
            total = fnv_bytes(total, &h, sizeof h);
            h = FNV_INIT;
            steps = 0;
            done++;
        }
    }
    return total;
}

int main(int argc, char** argv) {
    int games = 200, episodes = 200;
    uint64_t seed = 42;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--games") == 0 && i + 1 < argc) games = atoi(argv[++i]);
        else if (strcmp(argv[i], "--episodes") == 0 && i + 1 < argc) episodes = atoi(argv[++i]);
        else if (strcmp(argv[i], "--seed") == 0 && i + 1 < argc) seed = strtoull(argv[++i], 0, 10);
        else {
            fprintf(stderr, "usage: %s [--games N] [--episodes N] [--seed S]\n", argv[0]);
            return 2;
        }
    }
    uint64_t eg = engine_games(games, seed);
    uint64_t ee = env_episodes(episodes, seed);
    printf("engine total fnv %016llx\n", (unsigned long long)eg);
    printf("env total fnv %016llx\n", (unsigned long long)ee);
    return 0;
}
