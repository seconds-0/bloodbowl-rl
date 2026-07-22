#define BB_TEST_MAIN
#include "bb_test.h"
#include "bloodbowl.h"

enum {
    CONTACT_GAMES = 200,
    CONTACT_HOOK_GAMES = 24,
    CONTACT_DECISION_CAP = BBE_MAX_DECISIONS,
};

static int action_in_legal(bb_action a, const bb_action* legal, int n) {
    for (int i = 0; i < n; i++) {
        if (bb_action_eq(a, legal[i])) return 1;
    }
    return 0;
}

static void hash_bytes(uint64_t* h, const void* ptr, size_t len) {
    const unsigned char* p = (const unsigned char*)ptr;
    for (size_t i = 0; i < len; i++) {
        *h ^= (uint64_t)p[i];
        *h *= 1099511628211ull;
    }
}

typedef struct {
    int completed;
    long decisions;
    uint64_t digest;
    float n;
    float blocks_thrown;
    float blocks_thrown_t0;
    float blocks_thrown_t1;
    float tds;
    float tds_t0;
    float tds_t1;
} ContactHookStats;

static ContactHookStats run_contact_hook(int scripted, int scripted_team,
                                         uint64_t seed, int games) {
    Bloodbowl env;
    memset(&env, 0, sizeof env);
    static uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    static float actions[BBE_AGENTS * 3];
    static unsigned char masks[BBE_AGENTS * BBE_MASK_SIZE];
    static float rewards[BBE_AGENTS];
    static float terminals[BBE_AGENTS];
    env.num_agents = BBE_AGENTS;
    env.seed = seed;
    env.scripted_opponent = scripted;
    env.scripted_opponent_team = scripted_team;
    env.max_decisions = CONTACT_DECISION_CAP;
    for (int a = 0; a < BBE_AGENTS; a++) {
        env.obs_ptr[a] = obs + a * BBE_OBS_SIZE;
        env.action_ptr[a] = actions + a * 3;
        env.action_mask_ptr[a] = masks + a * BBE_MASK_SIZE;
        env.reward_ptr[a] = rewards + a;
        env.terminal_ptr[a] = terminals + a;
    }
    c_reset(&env);

    bb_rng pol;
    bb_rng_seed(&pol, seed ^ 0x51C1A7EDu, 5);
    ContactHookStats out = {.digest = 1469598103934665603ull};
    int episode_decisions = 0;
    while (out.completed < games &&
           out.decisions < (long)games * CONTACT_DECISION_CAP) {
        for (int a = 0; a < BBE_AGENTS; a++) {
            bbe_sample_joint_uniform(&env, a, env.action_ptr[a], &pol);
        }
        hash_bytes(&out.digest, actions, sizeof actions);
        c_step(&env);
        hash_bytes(&out.digest, rewards, sizeof rewards);
        hash_bytes(&out.digest, terminals, sizeof terminals);
        out.decisions++;
        episode_decisions++;
        if (terminals[0] != 0.0f) {
            BB_CHECK(episode_decisions < CONTACT_DECISION_CAP);
            out.completed++;
            episode_decisions = 0;
        }
    }

    out.n = env.log.n;
    out.blocks_thrown = env.log.blocks_thrown;
    out.blocks_thrown_t0 = env.log.blocks_thrown_t0;
    out.blocks_thrown_t1 = env.log.blocks_thrown_t1;
    out.tds = env.log.tds;
    out.tds_t0 = env.log.tds_t0;
    out.tds_t1 = env.log.tds_t1;
    return out;
}

BB_TEST(contact_bot_full_games_terminate_and_make_contact) {
    long total_blocks = 0;
    long total_tds = 0;
    long total_decisions = 0;
    int completed = 0;

    for (int g = 0; g < CONTACT_GAMES; g++) {
        bb_rng procgen;
        bb_rng dice;
        bb_rng_seed(&procgen, 0xC0A7AC7u + (uint64_t)g * 9973u, 11);
        bb_rng_seed(&dice, 0xB10CBB01u + (uint64_t)g * 7919u, 1);

        bb_match m;
        bb_procgen_params pp = bb_procgen_params_default();
        bb_match_init_random_p(&m, &procgen, &pp);
        bb_advance(&m, &dice);

        int decisions = 0;
        int blocks = 0;
        while (m.status == BB_STATUS_DECISION && decisions < CONTACT_DECISION_CAP) {
            bb_action legal[BB_LEGAL_MAX];
            int n = bb_legal_actions(&m, legal);
            BB_CHECK(n > 0);
            if (n <= 0) break;

            bb_action pick = bbe_contact_bot_pick(&m, legal, n);
            BB_CHECK(action_in_legal(pick, legal, n));
            if (!action_in_legal(pick, legal, n)) break;

            if (pick.type == BB_A_CHOOSE_DIE) blocks++;
            bb_apply(&m, pick, &dice);
            decisions++;
            BB_CHECK(m.status != BB_STATUS_ERROR);
            if (m.status == BB_STATUS_ERROR) break;
        }

        BB_CHECK_EQ(m.status, BB_STATUS_MATCH_OVER);
        BB_CHECK(decisions < CONTACT_DECISION_CAP);
        total_blocks += blocks;
        total_tds += (long)m.score[0] + (long)m.score[1];
        total_decisions += decisions;
        completed += m.status == BB_STATUS_MATCH_OVER;
    }

    BB_CHECK_EQ(completed, CONTACT_GAMES);
    BB_CHECK(total_blocks > CONTACT_GAMES * 4);
    BB_CHECK(total_blocks < CONTACT_GAMES * 300);
    BB_CHECK(total_tds > 0);
    printf("contact_bot: games=%d decisions=%ld blocks_thrown=%ld tds=%ld\n",
           CONTACT_GAMES, total_decisions, total_blocks, total_tds);
}

BB_TEST(contact_bot_c_step_hook_logs_per_team_and_off_is_inert) {
    ContactHookStats bot = run_contact_hook(
        1, BB_AWAY, 0xB07C057u, CONTACT_HOOK_GAMES);
    BB_CHECK_EQ(bot.completed, CONTACT_HOOK_GAMES);
    BB_CHECK_EQ((int)bot.n, CONTACT_HOOK_GAMES);
    BB_CHECK(bot.blocks_thrown_t1 > (float)CONTACT_HOOK_GAMES * 2.0f);
    BB_CHECK(bot.blocks_thrown_t0 + bot.blocks_thrown_t1 == bot.blocks_thrown);
    BB_CHECK(bot.tds_t0 + bot.tds_t1 == bot.tds);

    ContactHookStats off_away_side = run_contact_hook(
        0, BB_AWAY, 0x0FF51DEu, 6);
    ContactHookStats off_home_side = run_contact_hook(
        0, BB_HOME, 0x0FF51DEu, 6);
    BB_CHECK_EQ(off_away_side.completed, off_home_side.completed);
    BB_CHECK(off_away_side.digest == off_home_side.digest);
    BB_CHECK_EQ((int)off_away_side.n, (int)off_home_side.n);
}
