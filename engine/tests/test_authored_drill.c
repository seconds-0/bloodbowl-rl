#include "authored_drill.h"
#include "bb_test.h"
#include "bb_fixtures.h"
#include "bb/bb_reachability.h"
#include "bb/gen_skills.h"

#include <string.h>

static ad_recipe ad_test_recipe(void) {
    ad_recipe recipe;
    memset(&recipe, 0, sizeof recipe);
    recipe.procgen_seed = 0xA1170EEDu;
    recipe.procgen_stream = 17;
    recipe.game_seed = 0xD11CE5u;
    recipe.game_stream = 23;
    recipe.controller_seed = 0xF300F3u;
    recipe.controller_stream = 31;
    recipe.home_team = 0;
    recipe.away_team = 1;
    recipe.exclude_team = -1;
    recipe.procgen = bb_procgen_params_default();
    return recipe;
}

static ad_recipe ad_test_f5_recipe(void) {
    ad_recipe recipe = ad_test_recipe();
    recipe.controller_seed = 410;
    return recipe;
}

static ad_recipe ad_test_f4_recipe(void) {
    ad_recipe recipe = ad_test_recipe();
    recipe.controller_seed = 1;
    return recipe;
}

static int ad_test_apply_legal(bb_match* match, bb_action_type type, int arg,
                               bb_rng* rng) {
    bb_action legal[BB_LEGAL_MAX];
    int count = bb_legal_actions(match, legal);
    for (int i = 0; i < count; i++) {
        if (legal[i].type == type && legal[i].arg == arg) {
            return bb_apply(match, legal[i], rng);
        }
    }
    return BB_STATUS_ERROR;
}

static bb_match ad_test_pending_dodge_reroll(void) {
    bb_match match;
    fx_match_midturn(&match, BB_HOME, 2);
    int mover = fx_lineman(&match, BB_HOME, 0, 10, 7);
    fx_lineman(&match, BB_AWAY, 0, 10, 8);

    uint8_t die = 2;
    bb_rng rng;
    bb_rng_script(&rng, &die, 1);
    BB_CHECK_EQ(fx_run(&match, &rng), BB_STATUS_DECISION);
    BB_CHECK(fx_find(&match, (bb_action){BB_A_ACTIVATE, mover, 0, 0}) >= 0);
    BB_CHECK_EQ(fx_apply(&match,
                        (bb_action){BB_A_ACTIVATE, mover, 0, 0}, &rng),
                BB_STATUS_DECISION);
    BB_CHECK(fx_find(&match,
                     (bb_action){BB_A_DECLARE, BB_ACT_MOVE, 0, 0}) >= 0);
    BB_CHECK_EQ(fx_apply(&match,
                        (bb_action){BB_A_DECLARE, BB_ACT_MOVE, 0, 0}, &rng),
                BB_STATUS_DECISION);
    BB_CHECK(fx_find(&match, (bb_action){BB_A_STEP, 0, 10, 6}) >= 0);
    BB_CHECK_EQ(fx_apply(&match, (bb_action){BB_A_STEP, 0, 10, 6}, &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 1);
    BB_CHECK(!bb_rng_error(&rng));
    return match;
}

static bb_match ad_test_pending_rush_then_dodge_reroll(void) {
    bb_match match;
    fx_match_midturn(&match, BB_HOME, 2);
    int mover = fx_player(&match, BB_HOME, 0, 10, 7, 0, 3, 3, 4, 9);
    fx_lineman(&match, BB_AWAY, 0, 10, 8);

    // MA 0 makes the first step a Rush. The Rush succeeds, then the Dodge
    // fails. MOVE has not committed moved/rushes yet, but match.ret retains
    // the successful Rush result. This legally reached state proves why the
    // first strict nested admission remains explicitly non-Rush.
    uint8_t dice[] = {2, 2};
    bb_rng rng;
    bb_rng_script(&rng, dice, 2);
    BB_CHECK_EQ(fx_run(&match, &rng), BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_apply(&match,
                        (bb_action){BB_A_ACTIVATE, mover, 0, 0}, &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_apply(&match,
                        (bb_action){BB_A_DECLARE, BB_ACT_MOVE, 0, 0}, &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_apply(&match,
                        (bb_action){BB_A_STEP, 0, 10, 6}, &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 2);
    BB_CHECK(!bb_rng_error(&rng));
    return match;
}

static int ad_test_handoff_target_count(const bb_match* source,
                                        int* catch_capable) {
    bb_match match = *source;
    uint8_t die = 6;
    bb_rng rng;
    bb_rng_script(&rng, &die, 1);
    int carrier = match.ball.carrier;
    if (ad_test_apply_legal(&match, BB_A_ACTIVATE, carrier, &rng) !=
            BB_STATUS_DECISION ||
        ad_test_apply_legal(&match, BB_A_DECLARE, BB_ACT_HANDOFF, &rng) !=
            BB_STATUS_DECISION ||
        rng.script_pos != 0 || bb_rng_error(&rng)) {
        return -1;
    }

    int targets = 0;
    int can_catch = 0;
    bb_action legal[BB_LEGAL_MAX];
    int count = bb_legal_actions(&match, legal);
    for (int i = 0; i < count; i++) {
        if (legal[i].type != BB_A_HANDOFF_TARGET) continue;
        targets++;
        int slot = bb_slot_at(&match, legal[i].x, legal[i].y);
        if (slot >= 0 && bb_can_catch(&match, slot)) can_catch++;
    }
    if (catch_capable != NULL) *catch_capable = can_catch;
    return targets;
}

BB_TEST(authored_drill_exact_replay_reproduces_raw_state) {
    ad_recipe recipe = ad_test_recipe();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_first_team_turn(&recipe, error), 0);
    BB_CHECK_EQ(recipe.controller_seed, 0);
    BB_CHECK_EQ(recipe.controller_stream, 0);
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
    BB_CHECK(strstr(error, "provenance") != NULL ||
             strstr(error, "replay failed") != NULL);
    BB_CHECK_EQ(ftell(file), 0);
    BB_CHECK_EQ(fclose(file), 0);

    recipe = ad_test_recipe();
    BB_CHECK_EQ(ad_discover_first_team_turn(&recipe, error), 0);
    record.recipe = &recipe;
    file = tmpfile();
    BB_CHECK(file != NULL);
    if (file == NULL) return;
    recipe.game_seed++;
    BB_CHECK(ad_bbs_write(file, &record, 1, error) != 0);
    BB_CHECK(strstr(error, "provenance") != NULL);
    BB_CHECK_EQ(ftell(file), 0);
    BB_CHECK_EQ(fclose(file), 0);

    recipe = ad_test_recipe();
    BB_CHECK_EQ(ad_discover_first_team_turn(&recipe, error), 0);
    record.recipe = &recipe;
    file = tmpfile();
    BB_CHECK(file != NULL);
    if (file == NULL) return;
    recipe.controller_seed++;
    BB_CHECK(ad_bbs_write(file, &record, 1, error) != 0);
    BB_CHECK(strstr(error, "provenance") != NULL);
    BB_CHECK_EQ(ftell(file), 0);
    BB_CHECK_EQ(fclose(file), 0);

    recipe.controller_seed--;
    file = tmpfile();
    BB_CHECK(file != NULL);
    if (file == NULL) return;
    recipe.controller_stream++;
    BB_CHECK(ad_bbs_write(file, &record, 1, error) != 0);
    BB_CHECK(strstr(error, "provenance") != NULL);
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
    BB_CHECK(strstr(error, "decision") != NULL);
}

BB_TEST(state_bank_dodge_reroll_boundary_is_exact_and_continuable) {
    bb_match pending = ad_test_pending_dodge_reroll();
    bb_match original = pending;
    BB_CHECK(!bb_state_bank_boundary_valid(&pending));
    BB_CHECK(bb_state_bank_dodge_reroll_valid(&pending));
    BB_CHECK(bb_state_bank_resumable_valid(&pending));
    BB_CHECK_EQ(memcmp(&pending, &original, sizeof pending), 0);
    BB_CHECK_EQ(pending.stack_top, 5);

    bb_action legal[BB_LEGAL_MAX];
    int count = bb_legal_actions(&pending, legal);
    BB_CHECK_EQ(count, 2);
    BB_CHECK(fx_find(&pending,
                     (bb_action){BB_A_USE_REROLL, BB_RR_TEAM, 0, 0}) >= 0);
    BB_CHECK(fx_find(&pending,
                     (bb_action){BB_A_DECLINE_REROLL, 0, 0, 0}) >= 0);

    bb_match used = pending;
    uint8_t success_die = 4;
    bb_rng use_rng;
    bb_rng_script(&use_rng, &success_die, 1);
    BB_CHECK_EQ(fx_apply(&used,
                        (bb_action){BB_A_USE_REROLL, BB_RR_TEAM, 0, 0},
                        &use_rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(use_rng.script_pos, 1);
    BB_CHECK(!bb_rng_error(&use_rng));
    BB_CHECK_EQ(used.rerolls[BB_HOME], 1);
    BB_CHECK_EQ(used.players[0].x, 10);
    BB_CHECK_EQ(used.players[0].y, 6);
    BB_CHECK_EQ(used.players[0].stance, BB_STANCE_STANDING);

    bb_match declined = pending;
    uint8_t armour_dice[] = {3, 3};
    bb_rng decline_rng;
    bb_rng_script(&decline_rng, armour_dice, 2);
    BB_CHECK_EQ(fx_apply(&declined,
                        (bb_action){BB_A_DECLINE_REROLL, 0, 0, 0},
                        &decline_rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(decline_rng.script_pos, 2);
    BB_CHECK(!bb_rng_error(&decline_rng));
    BB_CHECK_EQ(declined.rerolls[BB_HOME], 2);
    BB_CHECK_EQ(declined.players[0].x, 10);
    BB_CHECK_EQ(declined.players[0].y, 6);
    BB_CHECK_EQ(declined.players[0].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(declined.decision_team, BB_AWAY);

    char error[AD_ERROR_CAP];
    uint32_t applied = 0;
    bb_status status = BB_STATUS_ERROR;
    int dice_used = -1;
    BB_CHECK_EQ(ad_verify_one_action_continuation(
                    &pending, &applied, &status, &dice_used, error),
                0);
    BB_CHECK_EQ(applied, bb_action_pack(
                             (bb_action){BB_A_USE_REROLL, BB_RR_TEAM, 0, 0}));
    BB_CHECK(status == BB_STATUS_DECISION || status == BB_STATUS_RUNNING ||
             status == BB_STATUS_MATCH_OVER);
    BB_CHECK(dice_used > 0 && dice_used <= AD_CONTINUATION_DICE);
    BB_CHECK_EQ(memcmp(&pending, &original, sizeof pending), 0);

#define REJECT_MUTATION(statement) do {                                      \
        bb_match changed = pending;                                          \
        statement;                                                           \
        BB_CHECK(!bb_state_bank_dodge_reroll_valid(&changed));               \
        BB_CHECK(!bb_state_bank_resumable_valid(&changed));                  \
    } while (0)
    REJECT_MUTATION(changed.stack_top = 4);
    REJECT_MUTATION(changed.ret = 1);
    REJECT_MUTATION(changed.stack[2].proc = BB_PROC_MOVE);
    REJECT_MUTATION(changed.stack[2].phase = 0);
    REJECT_MUTATION(changed.stack[2].a = 1);
    REJECT_MUTATION(changed.stack[2].b = BB_ACT_BLITZ);
    REJECT_MUTATION(changed.stack[2].x = 1);
    REJECT_MUTATION(changed.stack[2].data = 1);
    REJECT_MUTATION(changed.stack[3].proc = BB_PROC_TEST);
    REJECT_MUTATION(changed.stack[3].phase = 1);
    REJECT_MUTATION(changed.stack[3].a = 1);
    REJECT_MUTATION(changed.stack[3].data = 0);
    REJECT_MUTATION(changed.stack[3].x = 12);
    REJECT_MUTATION(changed.stack[4].proc = BB_PROC_MOVE);
    REJECT_MUTATION(changed.stack[4].phase = 0);
    REJECT_MUTATION(changed.stack[4].a = 1);
    REJECT_MUTATION(changed.stack[4].b = BB_TEST_RUSH);
    REJECT_MUTATION(changed.stack[4].x = 2);
    REJECT_MUTATION(changed.stack[4].y = 1);
    REJECT_MUTATION(changed.stack[4].data &= (uint16_t)~(1u << 2));
    REJECT_MUTATION(changed.stack[4].data |= (uint16_t)(1u << 1));
    REJECT_MUTATION(changed.stack[4].data =
                        (uint16_t)((changed.stack[4].data & 0x0FFFu) |
                                   (3u << 12)));
    REJECT_MUTATION(changed.players[0].flags &=
                        (uint16_t)~BB_PF_ACTIVATING);
    REJECT_MUTATION(changed.players[0].flags |= BB_PF_USED);
    REJECT_MUTATION(changed.players[0].flags |= BB_PF_ROOTED);
    REJECT_MUTATION(changed.players[0].flags |= BB_PF_DISTRACTED);
    REJECT_MUTATION(changed.players[0].flags |= BB_PF_EYE_GOUGED);
    REJECT_MUTATION(changed.players[0].moved = 1);
    REJECT_MUTATION(changed.players[0].rushes = 1);
    REJECT_MUTATION(changed.players[0].ma = 0);
    REJECT_MUTATION(changed.players[0].ma = -1);
    REJECT_MUTATION(changed.rerolls[BB_HOME] = 0);
    REJECT_MUTATION(bb_give_ball(&changed, 0));
    REJECT_MUTATION(changed.ball.state = BB_BALL_ON_GROUND;
                    changed.ball.x = 10;
                    changed.ball.y = 6);
#undef REJECT_MUTATION

    bb_match unknown_skill = pending;
    unknown_skill.players[0].skills.w[BB_SKILL_COUNT >> 6] |=
        (uint64_t)1 << (BB_SKILL_COUNT & 63);
    BB_CHECK(!bb_state_bank_dodge_reroll_valid(&unknown_skill));
    BB_CHECK(!bb_state_bank_resumable_valid(&unknown_skill));
}

BB_TEST(state_bank_dodge_reroll_after_resolved_rush_is_out_of_scope) {
    bb_match pending = ad_test_pending_rush_then_dodge_reroll();
    BB_CHECK_EQ(pending.players[0].ma, 0);
    BB_CHECK_EQ(pending.players[0].moved, 0);
    BB_CHECK_EQ(pending.players[0].rushes, 0);
    BB_CHECK(pending.ret != 0); // retained successful Rush result
    BB_CHECK(!bb_state_bank_dodge_reroll_valid(&pending));
    BB_CHECK(!bb_state_bank_resumable_valid(&pending));
}

BB_TEST(authored_drill_f3_reaches_late_second_half_by_legal_play) {
    ad_recipe recipe = ad_test_recipe();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_f3_late_second_half(&recipe, error), 0);
    BB_CHECK(recipe.action_count > 0);
    BB_CHECK(recipe.action_count < AD_MAX_ACTIONS / 4);
    BB_CHECK(recipe.dice_count > 0);
    BB_CHECK(recipe.dice_count < AD_MAX_DICE / 4);
    BB_CHECK_EQ(recipe.captured.half, 2);
    BB_CHECK_EQ(recipe.captured.score[BB_HOME], 0);
    BB_CHECK_EQ(recipe.captured.score[BB_AWAY], 0);
    BB_CHECK(recipe.captured.active_team <= BB_AWAY);
    if (recipe.captured.active_team > BB_AWAY) return;
    BB_CHECK(recipe.captured.turn[recipe.captured.active_team] >= 5);
    BB_CHECK(bb_state_bank_boundary_valid(&recipe.captured));

    bb_match replayed;
    BB_CHECK_EQ(ad_replay_exact(&recipe, &replayed, error), 0);
    BB_CHECK_EQ(memcmp(&replayed, &recipe.captured, sizeof replayed), 0);
    BB_CHECK_EQ(ad_verify_one_action_continuation(
                    &replayed, NULL, NULL, NULL, error),
                0);

    FILE* file = tmpfile();
    BB_CHECK(file != NULL);
    if (file != NULL) {
        ad_bbs_record record = {
            0xA3000001u, (uint32_t)recipe.action_count, &recipe,
        };
        recipe.controller_seed++;
        BB_CHECK(ad_bbs_write(file, &record, 1, error) != 0);
        BB_CHECK(strstr(error, "provenance") != NULL);
        BB_CHECK_EQ(ftell(file), 0);
        BB_CHECK_EQ(fclose(file), 0);
        recipe.controller_seed--;
    }

    ad_recipe rediscovered = ad_test_recipe();
    BB_CHECK_EQ(ad_discover_f3_late_second_half(&rediscovered, error), 0);
    BB_CHECK_EQ(memcmp(&recipe, &rediscovered, sizeof recipe), 0);
}

BB_TEST(authored_drill_writer_preflights_mixed_batch_before_header) {
    ad_recipe first = ad_test_recipe();
    ad_recipe late = ad_test_recipe();
    ad_recipe nested = ad_test_f4_recipe();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_first_team_turn(&first, error), 0);
    BB_CHECK_EQ(ad_discover_f3_late_second_half(&late, error), 0);
    BB_CHECK_EQ(ad_discover_f4_pending_dodge_reroll(&nested, error), 0);
    ad_bbs_record records[3] = {
        {0xA0000002u, (uint32_t)first.action_count, &first},
        {0xA3000002u, (uint32_t)late.action_count, &late},
        {0xA4000002u, (uint32_t)nested.action_count, &nested},
    };

    FILE* file = tmpfile();
    BB_CHECK(file != NULL);
    if (file == NULL) return;
    BB_CHECK_EQ(ad_bbs_write(file, records, 3, error), 0);
    BB_CHECK_EQ(fseek(file, 0, SEEK_END), 0);
    BB_CHECK_EQ(ftell(file), 16 + 3 * (12 + (long)sizeof(bb_match)));
    BB_CHECK_EQ(fclose(file), 0);

    file = tmpfile();
    BB_CHECK(file != NULL);
    if (file == NULL) return;
    nested.controller_stream++;
    BB_CHECK(ad_bbs_write(file, records, 3, error) != 0);
    BB_CHECK(strstr(error, "record 2 provenance failed") != NULL);
    BB_CHECK_EQ(ftell(file), 0);
    BB_CHECK_EQ(fclose(file), 0);
}

BB_TEST(authored_drill_f1_reaches_real_pass_opportunity) {
    ad_recipe recipe = ad_test_recipe();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_f1_pass_opportunity(&recipe, error), 0);
    BB_CHECK(recipe.action_count > 0);
    BB_CHECK(recipe.action_count < AD_MAX_ACTIONS / 4);
    BB_CHECK(recipe.dice_count > 0);
    BB_CHECK(recipe.dice_count < AD_MAX_DICE / 4);
    BB_CHECK(bb_state_bank_boundary_valid(&recipe.captured));
    BB_CHECK_EQ(recipe.captured.half, 2);
    BB_CHECK_EQ(recipe.captured.active_team, BB_AWAY);
    BB_CHECK_EQ(recipe.captured.turn[BB_AWAY], 1);
    BB_CHECK_EQ(recipe.captured.score[BB_HOME], 0);
    BB_CHECK_EQ(recipe.captured.score[BB_AWAY], 0);
    BB_CHECK_EQ(recipe.captured.ball.state, BB_BALL_HELD);
    BB_CHECK(recipe.captured.ball.carrier < BB_NUM_PLAYERS);
    if (recipe.captured.ball.carrier >= BB_NUM_PLAYERS) return;
    BB_CHECK_EQ(BB_TEAM_OF(recipe.captured.ball.carrier), BB_AWAY);
    BB_CHECK_EQ(recipe.captured.players[recipe.captured.ball.carrier].stance,
                BB_STANCE_STANDING);
    BB_CHECK(recipe.captured.players[recipe.captured.ball.carrier].pa > 0);
    bb_match original = recipe.captured;
    BB_CHECK(ad_f1_pass_opportunity_valid(&recipe.captured));
    BB_CHECK_EQ(memcmp(&recipe.captured, &original, sizeof original), 0);
    bb_match no_pa = recipe.captured;
    no_pa.players[no_pa.ball.carrier].pa = 0;
    BB_CHECK(!ad_f1_pass_opportunity_valid(&no_pa));
    bb_match no_ball_carrier = recipe.captured;
    bb_add_skill(&no_ball_carrier.players[no_ball_carrier.ball.carrier].skills,
                 BB_SK_NO_BALL);
    BB_CHECK(bb_state_bank_boundary_valid(&no_ball_carrier));
    BB_CHECK(!ad_f1_pass_opportunity_valid(&no_ball_carrier));
    bb_match no_receivers = recipe.captured;
    for (int slot = BB_AWAY * BB_TEAM_SLOTS;
         slot < (BB_AWAY + 1) * BB_TEAM_SLOTS; slot++) {
        if (slot != no_receivers.ball.carrier) {
            bb_add_skill(&no_receivers.players[slot].skills, BB_SK_NO_BALL);
        }
    }
    BB_CHECK(bb_state_bank_boundary_valid(&no_receivers));
    BB_CHECK(!ad_f1_pass_opportunity_valid(&no_receivers));

    bb_match replayed;
    BB_CHECK_EQ(ad_replay_exact(&recipe, &replayed, error), 0);
    BB_CHECK_EQ(memcmp(&replayed, &recipe.captured, sizeof replayed), 0);
    BB_CHECK_EQ(ad_verify_one_action_continuation(
                    &replayed, NULL, NULL, NULL, error),
                0);

    FILE* file = tmpfile();
    BB_CHECK(file != NULL);
    if (file != NULL) {
        ad_bbs_record record = {
            0xA1000001u, (uint32_t)recipe.action_count, &recipe,
        };
        recipe.controller_stream++;
        BB_CHECK(ad_bbs_write(file, &record, 1, error) != 0);
        BB_CHECK(strstr(error, "provenance") != NULL);
        BB_CHECK_EQ(ftell(file), 0);
        BB_CHECK_EQ(fclose(file), 0);
        recipe.controller_stream--;
    }

    ad_recipe rediscovered = ad_test_recipe();
    BB_CHECK_EQ(ad_discover_f1_pass_opportunity(&rediscovered, error), 0);
    BB_CHECK_EQ(memcmp(&recipe, &rediscovered, sizeof recipe), 0);

    ad_recipe no_pass = ad_test_recipe();
    BB_CHECK_EQ(ad_discover_first_team_turn(&no_pass, error), 0);
    original = no_pass.captured;
    BB_CHECK(!ad_f1_pass_opportunity_valid(&no_pass.captured));
    BB_CHECK_EQ(memcmp(&no_pass.captured, &original, sizeof original), 0);
    no_pass.captured.stack[1].a = 255;
    BB_CHECK(!ad_f1_pass_opportunity_valid(&no_pass.captured));
}

BB_TEST(authored_drill_f2_reaches_real_handoff_opportunity) {
    ad_recipe recipe = ad_test_recipe();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_f2_handoff_opportunity(&recipe, error), 0);
    BB_CHECK_EQ(recipe.action_count, 414);
    BB_CHECK_EQ(recipe.dice_count, 108);
    BB_CHECK(bb_state_bank_boundary_valid(&recipe.captured));
    BB_CHECK_EQ(recipe.captured.half, 2);
    BB_CHECK_EQ(recipe.captured.active_team, BB_AWAY);
    BB_CHECK_EQ(recipe.captured.turn[BB_AWAY], 1);
    BB_CHECK_EQ(recipe.captured.score[BB_HOME], 0);
    BB_CHECK_EQ(recipe.captured.score[BB_AWAY], 0);
    BB_CHECK_EQ(recipe.captured.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(recipe.captured.ball.carrier, 23);
    BB_CHECK_EQ(BB_TEAM_OF(recipe.captured.ball.carrier), BB_AWAY);
    BB_CHECK_EQ(recipe.captured.players[recipe.captured.ball.carrier].stance,
                BB_STANCE_STANDING);
    BB_CHECK_EQ(recipe.captured.handoff_used, 0);

    bb_match original = recipe.captured;
    BB_CHECK(ad_f2_handoff_opportunity_valid(&recipe.captured));
    BB_CHECK_EQ(memcmp(&recipe.captured, &original, sizeof original), 0);
    int catch_capable = 0;
    BB_CHECK(ad_test_handoff_target_count(&recipe.captured, &catch_capable) > 0);
    BB_CHECK(catch_capable > 0);

    bb_match no_ball_carrier = recipe.captured;
    bb_add_skill(&no_ball_carrier.players[no_ball_carrier.ball.carrier].skills,
                 BB_SK_NO_BALL);
    BB_CHECK(bb_state_bank_boundary_valid(&no_ball_carrier));
    BB_CHECK(!ad_f2_handoff_opportunity_valid(&no_ball_carrier));

    bb_match no_receivers = recipe.captured;
    for (int slot = BB_AWAY * BB_TEAM_SLOTS;
         slot < (BB_AWAY + 1) * BB_TEAM_SLOTS; slot++) {
        if (slot != no_receivers.ball.carrier) {
            bb_add_skill(&no_receivers.players[slot].skills, BB_SK_NO_BALL);
        }
    }
    BB_CHECK(bb_state_bank_boundary_valid(&no_receivers));
    BB_CHECK(ad_test_handoff_target_count(&no_receivers, &catch_capable) > 0);
    BB_CHECK_EQ(catch_capable, 0);
    BB_CHECK(!ad_f2_handoff_opportunity_valid(&no_receivers));

    bb_match spent = recipe.captured;
    spent.handoff_used = 1;
    BB_CHECK(bb_state_bank_boundary_valid(&spent));
    BB_CHECK(!ad_f2_handoff_opportunity_valid(&spent));

    bb_match replayed;
    BB_CHECK_EQ(ad_replay_exact(&recipe, &replayed, error), 0);
    BB_CHECK_EQ(memcmp(&replayed, &recipe.captured, sizeof replayed), 0);
    BB_CHECK_EQ(ad_verify_one_action_continuation(
                    &replayed, NULL, NULL, NULL, error),
                0);

    FILE* file = tmpfile();
    BB_CHECK(file != NULL);
    if (file != NULL) {
        ad_bbs_record record = {
            0xA2000001u, (uint32_t)recipe.action_count, &recipe,
        };
        recipe.game_stream++;
        BB_CHECK(ad_bbs_write(file, &record, 1, error) != 0);
        BB_CHECK(strstr(error, "provenance") != NULL);
        BB_CHECK_EQ(ftell(file), 0);
        BB_CHECK_EQ(fclose(file), 0);
        recipe.game_stream--;
    }

    ad_recipe rediscovered = ad_test_recipe();
    BB_CHECK_EQ(ad_discover_f2_handoff_opportunity(&rediscovered, error), 0);
    BB_CHECK_EQ(memcmp(&recipe, &rediscovered, sizeof recipe), 0);

    ad_recipe no_handoff = ad_test_recipe();
    BB_CHECK_EQ(ad_discover_first_team_turn(&no_handoff, error), 0);
    original = no_handoff.captured;
    BB_CHECK(!ad_f2_handoff_opportunity_valid(&no_handoff.captured));
    BB_CHECK_EQ(memcmp(&no_handoff.captured, &original, sizeof original), 0);
    no_handoff.captured.stack[1].a = 255;
    BB_CHECK(!ad_f2_handoff_opportunity_valid(&no_handoff.captured));
}

BB_TEST(authored_drill_f5_reaches_real_score_or_stall_opportunity) {
    ad_recipe recipe = ad_test_f5_recipe();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_f5_score_or_wait(&recipe, error), 0);
    BB_CHECK_EQ(recipe.action_count, 51);
    BB_CHECK_EQ(recipe.dice_count, 19);
    BB_CHECK(bb_state_bank_boundary_valid(&recipe.captured));
    BB_CHECK_EQ(recipe.captured.half, 1);
    BB_CHECK_EQ(recipe.captured.active_team, BB_HOME);
    BB_CHECK_EQ(recipe.captured.turn[BB_HOME], 2);
    BB_CHECK_EQ(recipe.captured.turn[BB_AWAY], 2);
    BB_CHECK_EQ(recipe.captured.score[BB_HOME], 0);
    BB_CHECK_EQ(recipe.captured.score[BB_AWAY], 0);
    BB_CHECK_EQ(recipe.captured.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(recipe.captured.ball.carrier, 6);
    int carrier = recipe.captured.ball.carrier;
    BB_CHECK_EQ(recipe.captured.players[carrier].x, 19);
    BB_CHECK_EQ(recipe.captured.players[carrier].y, 10);
    BB_CHECK_EQ(recipe.captured.players[carrier].ma, 6);
    BB_CHECK_EQ(recipe.captured.players[carrier].flags & BB_PF_USED, 0);
    BB_CHECK(bb_can_score_without_dice(&recipe.captured, carrier));

    bb_match original = recipe.captured;
    BB_CHECK(ad_f5_score_or_wait_valid(&recipe.captured));
    BB_CHECK_EQ(memcmp(&recipe.captured, &original, sizeof original), 0);

    bb_match probe = recipe.captured;
    uint8_t die = 6;
    bb_rng rng;
    bb_rng_script(&rng, &die, 1);
    BB_CHECK_EQ(ad_test_apply_legal(&probe, BB_A_ACTIVATE, carrier, &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(ad_test_apply_legal(&probe, BB_A_DECLARE, BB_ACT_MOVE, &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(rng.script_pos, 0);
    BB_CHECK(!bb_rng_error(&rng));
    bb_action legal[BB_LEGAL_MAX];
    int legal_count = bb_legal_actions(&probe, legal);
    int can_stall = 0;
    for (int i = 0; i < legal_count; i++) {
        if (legal[i].type == BB_A_END_ACTIVATION) can_stall = 1;
    }
    BB_CHECK(can_stall);

    bb_match needs_rush = recipe.captured;
    needs_rush.players[carrier].ma--;
    BB_CHECK(bb_state_bank_boundary_valid(&needs_rush));
    BB_CHECK(!bb_can_score_without_dice(&needs_rush, carrier));
    BB_CHECK(!ad_f5_score_or_wait_valid(&needs_rush));

    bb_match used = recipe.captured;
    used.players[carrier].flags |= BB_PF_USED;
    BB_CHECK(bb_state_bank_boundary_valid(&used));
    BB_CHECK(bb_can_score_without_dice(&used, carrier));
    BB_CHECK(!ad_f5_score_or_wait_valid(&used));

    bb_match no_ball_carrier = recipe.captured;
    bb_add_skill(&no_ball_carrier.players[carrier].skills, BB_SK_NO_BALL);
    BB_CHECK(bb_state_bank_boundary_valid(&no_ball_carrier));
    BB_CHECK(!ad_f5_score_or_wait_valid(&no_ball_carrier));

    bb_match replayed;
    BB_CHECK_EQ(ad_replay_exact(&recipe, &replayed, error), 0);
    BB_CHECK_EQ(memcmp(&replayed, &recipe.captured, sizeof replayed), 0);
    BB_CHECK_EQ(ad_verify_one_action_continuation(
                    &replayed, NULL, NULL, NULL, error),
                0);

    FILE* file = tmpfile();
    BB_CHECK(file != NULL);
    if (file != NULL) {
        ad_bbs_record record = {
            0xA5000001u, (uint32_t)recipe.action_count, &recipe,
        };
        recipe.controller_stream++;
        BB_CHECK(ad_bbs_write(file, &record, 1, error) != 0);
        BB_CHECK(strstr(error, "provenance") != NULL);
        BB_CHECK_EQ(ftell(file), 0);
        BB_CHECK_EQ(fclose(file), 0);
        recipe.controller_stream--;
    }

    ad_recipe rediscovered = ad_test_f5_recipe();
    BB_CHECK_EQ(ad_discover_f5_score_or_wait(&rediscovered, error), 0);
    BB_CHECK_EQ(memcmp(&recipe, &rediscovered, sizeof recipe), 0);

    ad_recipe no_score = ad_test_recipe();
    BB_CHECK_EQ(ad_discover_first_team_turn(&no_score, error), 0);
    original = no_score.captured;
    BB_CHECK(!ad_f5_score_or_wait_valid(&no_score.captured));
    BB_CHECK_EQ(memcmp(&no_score.captured, &original, sizeof original), 0);
    no_score.captured.stack[1].a = 255;
    BB_CHECK(!ad_f5_score_or_wait_valid(&no_score.captured));
}

BB_TEST(authored_drill_f4_reaches_pending_dodge_reroll_before_choice) {
    ad_recipe recipe = ad_test_f4_recipe();
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_discover_f4_pending_dodge_reroll(&recipe, error), 0);
    BB_CHECK_EQ(recipe.kind, AD_RECIPE_F4_PENDING_DODGE_REROLL);
    BB_CHECK_EQ(recipe.action_count, 384);
    BB_CHECK_EQ(recipe.dice_count, 110);
    BB_CHECK_EQ(recipe.controller_seed, 1);
    BB_CHECK(!bb_state_bank_boundary_valid(&recipe.captured));
    BB_CHECK(bb_state_bank_dodge_reroll_valid(&recipe.captured));
    BB_CHECK(bb_state_bank_resumable_valid(&recipe.captured));
    BB_CHECK_EQ(recipe.captured.decision_team, BB_AWAY);
    BB_CHECK_EQ(recipe.captured.stack_top, 5);

    const bb_frame* test =
        &recipe.captured.stack[recipe.captured.stack_top - 1];
    BB_CHECK_EQ(test->proc, BB_PROC_TEST);
    BB_CHECK_EQ(test->phase, 1);
    BB_CHECK_EQ(test->a, 17);
    BB_CHECK_EQ(test->b, BB_TEST_DODGE);
    BB_CHECK_EQ(test->x, 3);
    BB_CHECK_EQ(test->y, 0);
    BB_CHECK_EQ(recipe.captured.players[test->a].moved, 0);
    BB_CHECK_EQ(recipe.captured.players[test->a].rushes, 0);
    BB_CHECK_EQ(recipe.captured.ret, 0);

    // The transcript ends with the Step that produced the failed Dodge. The
    // pending reroll action, its policy choice, and its outcome are absent.
    bb_action last = bb_action_unpack(recipe.actions[recipe.action_count - 1]);
    BB_CHECK_EQ(last.type, BB_A_STEP);
    BB_CHECK_EQ(last.x, 14);
    BB_CHECK_EQ(last.y, 6);
    BB_CHECK_EQ(recipe.dice_sides[recipe.dice_count - 1], 6);
    BB_CHECK(recipe.dice_values[recipe.dice_count - 1] < test->x);

    bb_action legal[BB_LEGAL_MAX];
    int legal_count = bb_legal_actions(&recipe.captured, legal);
    BB_CHECK_EQ(legal_count, 3);
    BB_CHECK(fx_find(&recipe.captured,
                     (bb_action){BB_A_USE_REROLL, BB_RR_TEAM, 0, 0}) >= 0);
    BB_CHECK(fx_find(&recipe.captured,
                     (bb_action){BB_A_USE_REROLL, BB_RR_SKILL,
                                 BB_SK_DODGE, 0}) >= 0);
    BB_CHECK(fx_find(&recipe.captured,
                     (bb_action){BB_A_DECLINE_REROLL, 0, 0, 0}) >= 0);

    bb_match replayed;
    BB_CHECK_EQ(ad_replay_exact(&recipe, &replayed, error), 0);
    BB_CHECK_EQ(memcmp(&replayed, &recipe.captured, sizeof replayed), 0);
    uint32_t continuation_action = 0;
    BB_CHECK_EQ(ad_verify_one_action_continuation(
                    &replayed, &continuation_action, NULL, NULL, error),
                0);
    BB_CHECK_EQ(continuation_action,
                bb_action_pack((bb_action){BB_A_USE_REROLL, BB_RR_TEAM,
                                           0, 0}));

    FILE* file = tmpfile();
    BB_CHECK(file != NULL);
    uint8_t first_bytes[16 + 12 + sizeof(bb_match)];
    if (file != NULL) {
        ad_bbs_record record = {
            0xA4000001u, (uint32_t)recipe.action_count, &recipe,
        };
        BB_CHECK_EQ(ad_bbs_write(file, &record, 1, error), 0);
        BB_CHECK_EQ(fseek(file, 0, SEEK_END), 0);
        BB_CHECK_EQ(ftell(file), (long)sizeof first_bytes);
        rewind(file);
        size_t first_read = fread(first_bytes, 1, sizeof first_bytes, file);
        BB_CHECK_EQ(first_read, sizeof first_bytes);
        if (first_read != sizeof first_bytes) {
            BB_CHECK(!ferror(file));
            BB_CHECK_EQ(fclose(file), 0);
            return;
        }
        BB_CHECK_EQ(fclose(file), 0);

        file = tmpfile();
        BB_CHECK(file != NULL);
        if (file != NULL) {
            uint8_t second_bytes[sizeof first_bytes];
            BB_CHECK_EQ(ad_bbs_write(file, &record, 1, error), 0);
            rewind(file);
            size_t second_read =
                fread(second_bytes, 1, sizeof second_bytes, file);
            BB_CHECK_EQ(second_read, sizeof second_bytes);
            if (second_read == sizeof second_bytes) {
                BB_CHECK_EQ(memcmp(first_bytes, second_bytes,
                                   sizeof first_bytes),
                            0);
            } else {
                BB_CHECK(!ferror(file));
            }
            BB_CHECK_EQ(fclose(file), 0);
        }
    }

    ad_recipe rediscovered = ad_test_f4_recipe();
    BB_CHECK_EQ(ad_discover_f4_pending_dodge_reroll(&rediscovered, error), 0);
    BB_CHECK_EQ(memcmp(&recipe, &rediscovered, sizeof recipe), 0);

    ad_recipe changed = recipe;
    changed.captured.stack[changed.captured.stack_top - 1].x++;
    BB_CHECK(ad_replay_exact(&changed, &replayed, error) != 0);
    BB_CHECK(strstr(error, "captured match") != NULL);

    file = tmpfile();
    BB_CHECK(file != NULL);
    if (file != NULL) {
        ad_bbs_record record = {
            0xA4000001u, (uint32_t)recipe.action_count, &recipe,
        };
        recipe.controller_stream++;
        BB_CHECK(ad_bbs_write(file, &record, 1, error) != 0);
        BB_CHECK(strstr(error, "provenance") != NULL);
        BB_CHECK_EQ(ftell(file), 0);
        BB_CHECK_EQ(fclose(file), 0);
    }

    ad_recipe old_family = ad_test_recipe();
    BB_CHECK_EQ(ad_discover_first_team_turn(&old_family, error), 0);
    BB_CHECK(bb_state_bank_boundary_valid(&old_family.captured));
    BB_CHECK(!ad_f4_pending_dodge_reroll_valid(&old_family.captured));
}

BB_TEST(authored_drill_f3_exact_second_half_turn_axis_is_complete) {
    const size_t expected_count = AD_F3_SECOND_HALF_AXIS_COUNT;
    static const int
        expected_actions[BB_AWAY + 1][AD_F3_SECOND_HALF_TURN_COUNT] = {
        {505, 329, 385, 408, 502, 607, 491, 571},
        {373, 439, 352, 495, 459, 562, 597, 598},
    };
    static const int
        expected_dice[BB_AWAY + 1][AD_F3_SECOND_HALF_TURN_COUNT] = {
        {111, 95, 141, 123, 164, 168, 185, 180},
        {118, 101, 128, 149, 158, 147, 198, 204},
    };
    ad_recipe* recipes = calloc(expected_count, sizeof(*recipes));
    BB_CHECK(recipes != NULL);
    if (recipes == NULL) return;
    char error[AD_ERROR_CAP];

    size_t index = 0;
    for (int team = BB_HOME; team <= BB_AWAY; team++) {
        for (int turn = 1; turn <= AD_F3_SECOND_HALF_TURN_COUNT; turn++) {
            ad_recipe* recipe = &recipes[index++];
            *recipe = ad_test_recipe();
            recipe->controller_seed = 1000u +
                (uint64_t)(team * AD_F3_SECOND_HALF_TURN_COUNT + turn - 1);
            BB_CHECK_EQ(ad_discover_f3_second_half_turn(
                            recipe, turn, team, error),
                        0);
            BB_CHECK_EQ(recipe->kind,
                        AD_RECIPE_F3_EXACT_SECOND_HALF_TURN);
            BB_CHECK_EQ(recipe->capture_turn, turn);
            BB_CHECK_EQ(recipe->capture_active_team, team);
            BB_CHECK_EQ(recipe->captured.half, 2);
            BB_CHECK_EQ(recipe->captured.active_team, team);
            BB_CHECK_EQ(recipe->captured.turn[team], turn);
            BB_CHECK(bb_state_bank_boundary_valid(&recipe->captured));
            BB_CHECK_EQ(recipe->action_count,
                        expected_actions[team][turn - 1]);
            BB_CHECK_EQ(recipe->dice_count, expected_dice[team][turn - 1]);

            bb_match replayed;
            BB_CHECK_EQ(ad_replay_exact(recipe, &replayed, error), 0);
            BB_CHECK_EQ(memcmp(&replayed, &recipe->captured,
                               sizeof replayed),
                        0);
            BB_CHECK_EQ(ad_verify_one_action_continuation(
                            &replayed, NULL, NULL, NULL, error),
                        0);

            ad_recipe rediscovered = ad_test_recipe();
            rediscovered.controller_seed = recipe->controller_seed;
            BB_CHECK_EQ(ad_discover_f3_second_half_turn(
                            &rediscovered, turn, team, error),
                        0);
            BB_CHECK_EQ(memcmp(recipe, &rediscovered, sizeof *recipe), 0);
        }
    }
    BB_CHECK_EQ(index, expected_count);
    BB_CHECK_EQ(ad_validate_f3_second_half_turn_axis(
                    recipes, expected_count, error),
                0);

    BB_CHECK(ad_validate_f3_second_half_turn_axis(
                 recipes, expected_count - 1, error) != 0);
    BB_CHECK(strstr(error, "count") != NULL ||
             strstr(error, "missing") != NULL);

    ad_recipe saved = recipes[expected_count - 1];
    recipes[expected_count - 1] = recipes[0];
    BB_CHECK(ad_validate_f3_second_half_turn_axis(
                 recipes, expected_count, error) != 0);
    BB_CHECK(strstr(error, "duplicate") != NULL ||
             strstr(error, "missing") != NULL);
    recipes[expected_count - 1] = saved;

    recipes[0].captured.turn[BB_HOME]++;
    BB_CHECK(ad_validate_f3_second_half_turn_axis(
                 recipes, expected_count, error) != 0);
    BB_CHECK(strstr(error, "capture") != NULL);
    recipes[0].captured.turn[BB_HOME]--;

    bb_match captured_saved = recipes[0].captured;
    recipes[0].captured.stack_top = 0;
    BB_CHECK(ad_validate_f3_second_half_turn_axis(
                 recipes, expected_count, error) != 0);
    recipes[0].captured = captured_saved;
    recipes[0].captured.stack_top = BB_STACK_MAX + 1;
    BB_CHECK(ad_validate_f3_second_half_turn_axis(
                 recipes, expected_count, error) != 0);
    recipes[0].captured = captured_saved;
    recipes[0].captured.stack_top = UINT8_MAX;
    BB_CHECK(ad_validate_f3_second_half_turn_axis(
                 recipes, expected_count, error) != 0);
    recipes[0].captured = captured_saved;
    recipes[0].captured.stack_top = 1;
    BB_CHECK(ad_validate_f3_second_half_turn_axis(
                 recipes, expected_count, error) != 0);
    recipes[0].captured = captured_saved;
    recipes[0].captured.stack[0].proc = BB_PROC_MOVE;
    BB_CHECK(ad_validate_f3_second_half_turn_axis(
                 recipes, expected_count, error) != 0);
    recipes[0].captured = captured_saved;

    int occupied = -1;
    for (int slot = 0; slot < BB_NUM_PLAYERS; slot++) {
        if (recipes[0].captured.players[slot].location == BB_LOC_ON_PITCH) {
            occupied = slot;
            break;
        }
    }
    BB_CHECK(occupied >= 0);
    if (occupied >= 0) {
        const bb_player* player = &recipes[0].captured.players[occupied];
        recipes[0].captured.grid[player->x][player->y] = 0;
        BB_CHECK(ad_validate_f3_second_half_turn_axis(
                     recipes, expected_count, error) != 0);
        recipes[0].captured = captured_saved;
    }

    ad_recipe invalid = ad_test_recipe();
    BB_CHECK(ad_discover_f3_second_half_turn(
                 &invalid, 0, BB_HOME, error) != 0);
    BB_CHECK(strstr(error, "invalid recipe configuration") != NULL);
    invalid = ad_test_recipe();
    BB_CHECK(ad_discover_f3_second_half_turn(
                 &invalid, 9, BB_HOME, error) != 0);
    BB_CHECK(strstr(error, "invalid recipe configuration") != NULL);
    invalid = ad_test_recipe();
    BB_CHECK(ad_discover_f3_second_half_turn(
                 &invalid, 1, -1, error) != 0);
    BB_CHECK(strstr(error, "invalid recipe configuration") != NULL);
    invalid = ad_test_recipe();
    BB_CHECK(ad_discover_f3_second_half_turn(
                 &invalid, 1, BB_AWAY + 1, error) != 0);
    BB_CHECK(strstr(error, "invalid recipe configuration") != NULL);
    invalid = ad_test_recipe();
    invalid.capture_turn = 1;
    BB_CHECK(ad_discover_f3_late_second_half(&invalid, error) != 0);
    BB_CHECK(strstr(error, "invalid recipe configuration") != NULL);

    FILE* file = tmpfile();
    BB_CHECK(file != NULL);
    if (file != NULL) {
        ad_bbs_record records[AD_F3_SECOND_HALF_AXIS_COUNT];
        size_t expected_bytes = 16 + expected_count *
                                       (12 + sizeof(bb_match));
        uint8_t* first_bytes = malloc(expected_bytes);
        uint8_t* second_bytes = malloc(expected_bytes);
        BB_CHECK(first_bytes != NULL);
        BB_CHECK(second_bytes != NULL);
        if (first_bytes == NULL || second_bytes == NULL) {
            free(first_bytes);
            free(second_bytes);
            BB_CHECK_EQ(fclose(file), 0);
            free(recipes);
            return;
        }
        for (size_t i = 0; i < expected_count; i++) {
            records[i] = (ad_bbs_record){
                0xA3000100u + (uint32_t)i,
                (uint32_t)recipes[i].action_count,
                &recipes[i],
            };
        }
        BB_CHECK_EQ(ad_bbs_write(file, records, expected_count, error), 0);
        BB_CHECK_EQ(fseek(file, 0, SEEK_END), 0);
        BB_CHECK_EQ(ftell(file), expected_bytes);
        rewind(file);
        size_t first_read = fread(first_bytes, 1, expected_bytes, file);
        BB_CHECK_EQ(first_read, expected_bytes);
        BB_CHECK_EQ(fclose(file), 0);

        file = tmpfile();
        BB_CHECK(file != NULL);
        if (file != NULL) {
            BB_CHECK_EQ(ad_bbs_write(file, records, expected_count, error), 0);
            rewind(file);
            size_t second_read = fread(second_bytes, 1, expected_bytes, file);
            BB_CHECK_EQ(second_read, expected_bytes);
            if (first_read == expected_bytes && second_read == expected_bytes) {
                BB_CHECK_EQ(memcmp(first_bytes, second_bytes, expected_bytes),
                            0);
            }
            BB_CHECK_EQ(fclose(file), 0);
        }

        file = tmpfile();
        BB_CHECK(file != NULL);
        if (file != NULL) {
            recipes[expected_count - 1].capture_turn = 7;
            BB_CHECK(ad_bbs_write(file, records, expected_count, error) != 0);
            BB_CHECK(strstr(error, "provenance") != NULL);
            BB_CHECK_EQ(ftell(file), 0);
            recipes[expected_count - 1].capture_turn = 8;
            BB_CHECK_EQ(fclose(file), 0);
        }
        free(first_bytes);
        free(second_bytes);
    }

    free(recipes);
}
