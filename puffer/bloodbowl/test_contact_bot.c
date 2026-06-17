#define BB_TEST_MAIN
#include "bb_test.h"
#include "bloodbowl.h"

enum {
    CONTACT_GAMES = 200,
    CONTACT_DECISION_CAP = BBE_MAX_DECISIONS,
};

static int action_in_legal(bb_action a, const bb_action* legal, int n) {
    for (int i = 0; i < n; i++) {
        if (bb_action_eq(a, legal[i])) return 1;
    }
    return 0;
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
