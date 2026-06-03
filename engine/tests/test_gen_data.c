// Sanity tests over the codegen'd rules tables (spot values verified by hand
// against the BB2025 reference mirror).
#include "bb/gen_skills.h"
#include "bb/gen_teams.h"
#include "bb/gen_tables.h"
#include "bb_test.h"
#include <string.h>

BB_TEST(gen_skill_counts) {
    BB_CHECK_EQ(BB_NUM_SKILLS, 72);            // 6 categories x 12
    BB_CHECK_EQ(BB_SKILL_COUNT - BB_NUM_SKILLS, 36); // traits
    int per_cat[BB_CAT_COUNT] = {0};
    for (int i = 0; i < BB_NUM_SKILLS; i++) {
        BB_CHECK(bb_skill_defs[i].category < BB_CAT_COUNT);
        BB_CHECK(!bb_skill_defs[i].is_trait);
        per_cat[bb_skill_defs[i].category]++;
    }
    for (int c = 0; c < BB_CAT_COUNT; c++) BB_CHECK_EQ(per_cat[c], 12);
    for (int i = BB_NUM_SKILLS; i < BB_SKILL_COUNT; i++) BB_CHECK(bb_skill_defs[i].is_trait);
}

BB_TEST(gen_elite_skills_are_exactly_four) {
    int elite = 0;
    int block_elite = 0;
    for (int i = 0; i < BB_SKILL_COUNT; i++) {
        if (bb_skill_defs[i].elite) elite++;
        if (!strcmp(bb_skill_defs[i].id, "block")) block_elite = bb_skill_defs[i].elite;
    }
    BB_CHECK_EQ(elite, 4); // Block, Dodge, Guard, Mighty Blow
    BB_CHECK_EQ(block_elite, 1);
}

BB_TEST(gen_team_count_and_human_roster) {
    BB_CHECK_EQ(BB_TEAM_COUNT, 30);
    const bb_team_def* hum = &bb_team_defs[BB_TEAM_HUMAN];
    BB_CHECK(!strcmp(hum->id, "human"));
    BB_CHECK_EQ(hum->reroll_cost_k, 50);
    BB_CHECK_EQ(hum->tier, 2);
    // Human Lineman: 0-16, 50k, MA6 ST3 AG3+ PA4+ AV9+
    const bb_position_def* lin = &hum->positions[0];
    BB_CHECK_EQ(lin->cost_k, 50);
    BB_CHECK_EQ(lin->ma, 6);
    BB_CHECK_EQ(lin->st, 3);
    BB_CHECK_EQ(lin->ag, 3);
    BB_CHECK_EQ(lin->pa, 4);
    BB_CHECK_EQ(lin->av, 9);
    BB_CHECK_EQ(lin->qty_max, 16);
}

BB_TEST(gen_all_teams_well_formed) {
    for (int t = 0; t < BB_TEAM_COUNT; t++) {
        const bb_team_def* td = &bb_team_defs[t];
        BB_CHECK(td->num_positions >= 2 && td->num_positions <= BB_MAX_POSITIONS);
        BB_CHECK(td->reroll_cost_k == 50 || td->reroll_cost_k == 60 || td->reroll_cost_k == 70);
        BB_CHECK(td->tier >= 1 && td->tier <= 4);
        int roster_max = 0;
        for (int p = 0; p < td->num_positions; p++) {
            const bb_position_def* pd = &td->positions[p];
            BB_CHECK(pd->ma >= 1 && pd->ma <= 9);
            BB_CHECK(pd->st >= 1 && pd->st <= 8);
            BB_CHECK(pd->ag >= 1 && pd->ag <= 6);
            BB_CHECK(pd->pa >= 0 && pd->pa <= 6); // 0 = '-'
            BB_CHECK(pd->av >= 3 && pd->av <= 11);
            BB_CHECK(pd->num_skills <= BB_POS_MAX_SKILLS);
            for (int s = 0; s < pd->num_skills; s++) BB_CHECK(pd->skills[s] < BB_SKILL_COUNT);
            roster_max += pd->qty_max;
        }
        BB_CHECK(roster_max >= 11); // every team can field a full squad
    }
}

BB_TEST(gen_casualty_table_bb2025) {
    // BB2025 D16: 1-8 BH, 9-10 SH, 11-12 SI, 13-14 LI, 15-16 DEAD
    BB_CHECK_EQ(bb_casualty_table[1], BB_CAS_BADLY_HURT);
    BB_CHECK_EQ(bb_casualty_table[8], BB_CAS_BADLY_HURT);
    BB_CHECK_EQ(bb_casualty_table[9], BB_CAS_SERIOUSLY_HURT);
    BB_CHECK_EQ(bb_casualty_table[10], BB_CAS_SERIOUSLY_HURT);
    BB_CHECK_EQ(bb_casualty_table[11], BB_CAS_SERIOUS_INJURY);
    BB_CHECK_EQ(bb_casualty_table[12], BB_CAS_SERIOUS_INJURY);
    BB_CHECK_EQ(bb_casualty_table[13], BB_CAS_LASTING_INJURY);
    BB_CHECK_EQ(bb_casualty_table[14], BB_CAS_LASTING_INJURY);
    BB_CHECK_EQ(bb_casualty_table[15], BB_CAS_DEAD);
    BB_CHECK_EQ(bb_casualty_table[16], BB_CAS_DEAD);
}

BB_TEST(gen_injury_bands) {
    BB_CHECK_EQ(BB_INJ_STUN_MAX, 7);
    BB_CHECK_EQ(BB_INJ_KO_MAX, 9);
    BB_CHECK_EQ(BB_INJ_STUNTY_STUN_MAX, 6);
    BB_CHECK_EQ(BB_INJ_STUNTY_KO_MAX, 8);
}

BB_TEST(gen_weather_table) {
    // 2 = sweltering heat, 3 = very sunny, 4-10 perfect, 11 rain, 12 blizzard
    BB_CHECK_EQ(bb_weather_table[2], 0);
    BB_CHECK_EQ(bb_weather_table[3], 1);
    for (int r = 4; r <= 10; r++) BB_CHECK_EQ(bb_weather_table[r], 2);
    BB_CHECK_EQ(bb_weather_table[11], 3);
    BB_CHECK_EQ(bb_weather_table[12], 4);
}

BB_TEST(gen_random_skill_table_resolves) {
    for (int c = 0; c < BB_CAT_COUNT; c++) {
        for (int k = 0; k < 12; k++) {
            int sk = bb_random_skill_table[c][k];
            BB_CHECK(sk < BB_NUM_SKILLS);          // only learnable skills
            BB_CHECK_EQ(bb_skill_defs[sk].category, c); // table stays in-category
        }
    }
}
