#include "authored_drill.h"
#include "bb_test.h"

#include <string.h>

static ad_recipe ad_test_recipe(void) {
    ad_recipe recipe;
    memset(&recipe, 0, sizeof recipe);
    recipe.procgen_seed = 0xA1170EEDu;
    recipe.procgen_stream = 17;
    recipe.game_seed = 0xD11CE5u;
    recipe.game_stream = 23;
    recipe.home_team = 0;
    recipe.away_team = 1;
    recipe.exclude_team = -1;
    recipe.procgen = bb_procgen_params_default();
    return recipe;
}

BB_TEST(authored_drill_exact_replay_reproduces_raw_state) {
    ad_recipe recipe = ad_test_recipe();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_first_team_turn(&recipe, error), 0);
    BB_CHECK(recipe.action_count > 0);
    BB_CHECK(recipe.dice_count > 0);

    bb_match replayed;
    BB_CHECK_EQ(ad_replay_exact(&recipe, &replayed, error), 0);
    BB_CHECK_EQ(memcmp(&replayed, &recipe.captured, sizeof replayed), 0);
}

BB_TEST(authored_drill_replay_fails_closed_on_transcript_drift) {
    ad_recipe base = ad_test_recipe();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_first_team_turn(&base, error), 0);

    bb_match out;
    ad_recipe changed = base;
    changed.actions[0] = bb_action_pack((bb_action){BB_A_NONE, 0, 0, 0});
    BB_CHECK(ad_replay_exact(&changed, &out, error) != 0);
    BB_CHECK(strstr(error, "not legal") != NULL);

    changed = base;
    changed.decision_teams[0] ^= 1;
    BB_CHECK(ad_replay_exact(&changed, &out, error) != 0);
    BB_CHECK(strstr(error, "decision team") != NULL);

    changed = base;
    BB_CHECK(changed.dice_count > 0);
    if (changed.dice_count <= 0) return;
    changed.dice_count--;
    BB_CHECK(ad_replay_exact(&changed, &out, error) != 0);
    BB_CHECK(strstr(error, "dice") != NULL || strstr(error, "status") != NULL);

    changed = base;
    changed.dice_values[changed.dice_count] = 1;
    changed.dice_sides[changed.dice_count] = 6;
    changed.dice_count++;
    BB_CHECK(ad_replay_exact(&changed, &out, error) != 0);
    BB_CHECK(strstr(error, "dice transcript") != NULL);

    changed = base;
    changed.captured.score[0]++;
    BB_CHECK(ad_replay_exact(&changed, &out, error) != 0);
    BB_CHECK(strstr(error, "captured match") != NULL);
}

BB_TEST(authored_drill_bbs_writer_emits_canonical_header_and_record) {
    ad_recipe recipe = ad_test_recipe();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_first_team_turn(&recipe, error), 0);
    bb_match replayed;
    BB_CHECK_EQ(ad_replay_exact(&recipe, &replayed, error), 0);

    FILE* file = tmpfile();
    BB_CHECK(file != NULL);
    if (file == NULL) return;
    ad_bbs_record record = {0xA0000001u, (uint32_t)recipe.action_count, replayed};
    BB_CHECK_EQ(ad_bbs_write(file, &record, 1, error), 0);
    BB_CHECK_EQ(fseek(file, 0, SEEK_END), 0);
    BB_CHECK_EQ(ftell(file), 16 + 12 + (long)sizeof(bb_match));
    rewind(file);
    uint8_t header[16];
    BB_CHECK_EQ(fread(header, 1, sizeof header, file), sizeof header);
    BB_CHECK_EQ(memcmp(header, "BBS1", 4), 0);
    uint32_t fingerprint = (uint32_t)header[12] |
                           ((uint32_t)header[13] << 8) |
                           ((uint32_t)header[14] << 16) |
                           ((uint32_t)header[15] << 24);
    BB_CHECK_EQ(fingerprint, ad_bbs_fingerprint());
    BB_CHECK_EQ(fclose(file), 0);

    file = tmpfile();
    BB_CHECK(file != NULL);
    if (file == NULL) return;
    record.source_id = 1;
    BB_CHECK(ad_bbs_write(file, &record, 1, error) != 0);
    BB_CHECK(strstr(error, "invalid authored") != NULL);
    BB_CHECK_EQ(ftell(file), 0);
    BB_CHECK_EQ(fclose(file), 0);

    file = tmpfile();
    BB_CHECK(file != NULL);
    if (file == NULL) return;
    record.source_id = 0xA0000001u;
    record.match.grid[0][0] = BB_NUM_PLAYERS + 1;
    BB_CHECK(ad_bbs_write(file, &record, 1, error) != 0);
    BB_CHECK_EQ(ftell(file), 0);
    BB_CHECK_EQ(fclose(file), 0);
}
