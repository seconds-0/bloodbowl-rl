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

    ad_recipe rediscovered = ad_test_recipe();
    BB_CHECK_EQ(ad_discover_first_team_turn(&rediscovered, error), 0);
    BB_CHECK_EQ(memcmp(&recipe, &rediscovered, sizeof recipe), 0);
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
    changed.initialized.score[0]++;
    BB_CHECK(ad_replay_exact(&changed, &out, error) != 0);
    BB_CHECK(strstr(error, "initialized match") != NULL);

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
    changed.dice_sides[0] = (uint8_t)(changed.dice_sides[0] == 6 ? 8 : 6);
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
    ad_bbs_record record = {0xA0000001u, (uint32_t)recipe.action_count, &recipe};
    BB_CHECK_EQ(ad_bbs_write(file, &record, 1, error), 0);
    BB_CHECK_EQ(fseek(file, 0, SEEK_END), 0);
    BB_CHECK_EQ(ftell(file), 16 + 12 + (long)sizeof(bb_match));
    rewind(file);
    uint8_t bytes[28];
    BB_CHECK_EQ(fread(bytes, 1, sizeof bytes, file), sizeof bytes);
    const uint8_t* header = bytes;
    BB_CHECK_EQ(memcmp(header, "BBS1", 4), 0);
    uint32_t version = (uint32_t)header[4] |
                       ((uint32_t)header[5] << 8) |
                       ((uint32_t)header[6] << 16) |
                       ((uint32_t)header[7] << 24);
    uint32_t match_size = (uint32_t)header[8] |
                          ((uint32_t)header[9] << 8) |
                          ((uint32_t)header[10] << 16) |
                          ((uint32_t)header[11] << 24);
    uint32_t fingerprint = (uint32_t)header[12] |
                           ((uint32_t)header[13] << 8) |
                           ((uint32_t)header[14] << 16) |
                           ((uint32_t)header[15] << 24);
    BB_CHECK_EQ(fingerprint, ad_bbs_fingerprint());
    BB_CHECK_EQ(version, 1);
    BB_CHECK_EQ(match_size, sizeof(bb_match));
    const uint8_t* metadata = bytes + 16;
    uint32_t source_id = (uint32_t)metadata[0] |
                         ((uint32_t)metadata[1] << 8) |
                         ((uint32_t)metadata[2] << 16) |
                         ((uint32_t)metadata[3] << 24);
    uint32_t decision_index = (uint32_t)metadata[4] |
                              ((uint32_t)metadata[5] << 8) |
                              ((uint32_t)metadata[6] << 16) |
                              ((uint32_t)metadata[7] << 24);
    BB_CHECK_EQ(source_id, 0xA0000001u);
    BB_CHECK_EQ(decision_index, recipe.action_count);
    BB_CHECK_EQ(metadata[8], replayed.half);
    BB_CHECK_EQ(metadata[9], replayed.turn[replayed.active_team]);
    BB_CHECK_EQ(metadata[10], 0);
    BB_CHECK_EQ(metadata[11], 0);
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
    record.decision_index++;
    BB_CHECK(ad_bbs_write(file, &record, 1, error) != 0);
    BB_CHECK(strstr(error, "decision index") != NULL);
    BB_CHECK_EQ(ftell(file), 0);
    BB_CHECK_EQ(fclose(file), 0);

    file = tmpfile();
    BB_CHECK(file != NULL);
    if (file == NULL) return;
    record.decision_index = (uint32_t)recipe.action_count;
    recipe.captured.score[0]++;
    BB_CHECK(ad_bbs_write(file, &record, 1, error) != 0);
    BB_CHECK(strstr(error, "replay failed") != NULL);
    BB_CHECK_EQ(ftell(file), 0);
    BB_CHECK_EQ(fclose(file), 0);
}

BB_TEST(authored_drill_one_action_continuation_is_canonical_and_safe) {
    ad_recipe recipe = ad_test_recipe();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_first_team_turn(&recipe, error), 0);

    bb_match loaded;
    BB_CHECK_EQ(ad_replay_exact(&recipe, &loaded, error), 0);
    bb_match original = loaded;
    bb_action legal[BB_LEGAL_MAX];
    int legal_count = bb_legal_actions(&loaded, legal);
    BB_CHECK(legal_count > 0);
    if (legal_count <= 0) return;
    uint32_t expected = bb_action_pack(legal[0]);
    for (int i = 1; i < legal_count; i++) {
        uint32_t packed = bb_action_pack(legal[i]);
        if (packed < expected) expected = packed;
    }

    uint32_t applied = 0;
    bb_status status = BB_STATUS_ERROR;
    int dice_used = -1;
    BB_CHECK_EQ(ad_verify_one_action_continuation(
                    &loaded, &applied, &status, &dice_used, error),
                0);
    BB_CHECK_EQ(applied, expected);
    BB_CHECK(status == BB_STATUS_DECISION || status == BB_STATUS_RUNNING ||
             status == BB_STATUS_MATCH_OVER);
    BB_CHECK(dice_used >= 0 && dice_used <= AD_CONTINUATION_DICE);
    BB_CHECK_EQ(memcmp(&loaded, &original, sizeof loaded), 0);

    loaded.stack[1].a = 255;
    BB_CHECK(ad_verify_one_action_continuation(
                 &loaded, &applied, &status, &dice_used, error) != 0);
    BB_CHECK(strstr(error, "boundary") != NULL);
}
