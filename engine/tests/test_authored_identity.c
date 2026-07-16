#include "bb_test.h"
#include "authored_drill.h"
#include "authored_identity_internal.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

static int build_bundle(ad_recipe** recipes_out, ad_bbs_record** records_out) {
    ad_recipe* recipes = calloc(AD_AUTHORED_PROOF_BUNDLE_COUNT,
                                sizeof *recipes);
    ad_bbs_record* records = calloc(AD_AUTHORED_PROOF_BUNDLE_COUNT,
                                    sizeof *records);
    if (recipes == NULL || records == NULL) {
        free(recipes);
        free(records);
        return -1;
    }
    char error[AD_ERROR_CAP];
    if (ad_build_authored_proof_bundle(
            recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
            records, AD_AUTHORED_PROOF_BUNDLE_COUNT, error) != 0) {
        free(recipes);
        free(records);
        return -1;
    }
    *recipes_out = recipes;
    *records_out = records;
    return 0;
}

BB_TEST(authored_identity_public_contract_exists) {
    ad_authored_identity identity = {0};
    int (*identify)(const ad_recipe*, size_t, ad_authored_identity*, size_t,
                    char[AD_ERROR_CAP]) =
        ad_identify_authored_proof_bundle;

    BB_CHECK_EQ(AD_AUTHORED_IDENTITY_SCHEMA_VERSION, 1u);
    BB_CHECK_EQ(AD_AUTHORED_TEMPLATE_KEY_CAP, 64u);
    BB_CHECK_EQ(identity.identity_schema_version, 0u);
    BB_CHECK(identify != NULL);
    BB_CHECK(ad_authored_template_key(0) == NULL);
}

BB_TEST(authored_identity_maps_all_fixed_allocations_exactly) {
    static const uint32_t expected_templates[26] = {
        1, 1, 1, 1, 2, 2, 2, 2,
        3, 3, 3, 3, 3, 3, 3, 3,
        3, 3, 3, 3, 3, 3, 3, 3, 4, 5,
    };
    static const uint64_t expected_seeds[26] = {
        4, 2, 10, 8, 4, 2, 8, 13,
        1000, 1001, 1002, 1003, 1004, 1005, 1006, 1007,
        1008, 1009, 1010, 1011, 1012, 1013, 1014, 1015, 1, 410,
    };
    ad_recipe* recipes = NULL;
    ad_bbs_record* records = NULL;
    BB_CHECK_EQ(build_bundle(&recipes, &records), 0);
    if (recipes == NULL) return;
    ad_authored_identity identities[AD_AUTHORED_PROOF_BUNDLE_COUNT];
    memset(identities, 0xA5, sizeof identities);
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_identify_authored_proof_bundle(
                    recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                    identities, AD_AUTHORED_PROOF_BUNDLE_COUNT, error),
                0);
    BB_CHECK_EQ(error[0], '\0');
    for (uint32_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        BB_CHECK_EQ(identities[i].identity_schema_version, 1u);
        BB_CHECK_EQ(identities[i].source_id, 0xAE000001u + i);
        BB_CHECK_EQ(identities[i].template_id, expected_templates[i]);
        BB_CHECK_EQ(identities[i].recipe_revision, 1u);
        BB_CHECK_EQ(identities[i].variant_seed, expected_seeds[i]);
        BB_CHECK_EQ(identities[i].cell_id,
                    i < 4 ? i + 1 : i < 8 ? i - 3 :
                    i < 24 ? i - 7 : 1);
        BB_CHECK_EQ(identities[i].variant_id, identities[i].cell_id);
        BB_CHECK(ad_authored_template_key(identities[i].template_id) != NULL);
    }
    BB_CHECK_EQ(strcmp(ad_authored_template_key(1),
                       "f1-pass-carrier-pressure"), 0);
    BB_CHECK_EQ(strcmp(ad_authored_template_key(2),
                       "f2-handoff-target-count"), 0);
    BB_CHECK_EQ(strcmp(ad_authored_template_key(3),
                       "f3-second-half-turn"), 0);
    BB_CHECK_EQ(strcmp(ad_authored_template_key(4),
                       "f4-pending-dodge-reroll"), 0);
    BB_CHECK_EQ(strcmp(ad_authored_template_key(5),
                       "f5-score-or-wait"), 0);
    BB_CHECK(ad_authored_template_key(6) == NULL);
    BB_CHECK(ad_authored_template_key(UINT32_MAX) == NULL);
    free(records);
    free(recipes);
}

BB_TEST(authored_identity_follows_recipe_permutations) {
    ad_recipe* recipes = NULL;
    ad_bbs_record* records = NULL;
    BB_CHECK_EQ(build_bundle(&recipes, &records), 0);
    if (recipes == NULL) return;
    ad_recipe temporary = recipes[0];
    recipes[0] = recipes[25];
    recipes[25] = recipes[7];
    recipes[7] = recipes[13];
    recipes[13] = temporary;

    ad_authored_identity identities[AD_AUTHORED_PROOF_BUNDLE_COUNT];
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_identify_authored_proof_bundle(
                    recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                    identities, AD_AUTHORED_PROOF_BUNDLE_COUNT, error),
                0);
    BB_CHECK_EQ(identities[0].source_id, 0xAE00001Au);
    BB_CHECK_EQ(identities[25].source_id, 0xAE000008u);
    BB_CHECK_EQ(identities[7].source_id, 0xAE00000Eu);
    BB_CHECK_EQ(identities[13].source_id, 0xAE000001u);
    free(records);
    free(recipes);
}

BB_TEST(authored_identity_count_and_unknown_failures_are_atomic) {
    ad_recipe* recipes = NULL;
    ad_bbs_record* records = NULL;
    BB_CHECK_EQ(build_bundle(&recipes, &records), 0);
    if (recipes == NULL) return;
    ad_authored_identity identities[AD_AUTHORED_PROOF_BUNDLE_COUNT];
    ad_authored_identity sentinel[AD_AUTHORED_PROOF_BUNDLE_COUNT];
    memset(sentinel, 0xA5, sizeof sentinel);
    char error[AD_ERROR_CAP];
    const size_t counts[] = {0, 25, 26, 27};
    for (size_t i = 0; i < sizeof counts / sizeof counts[0]; i++) {
        for (size_t j = 0; j < sizeof counts / sizeof counts[0]; j++) {
            if (counts[i] == 26 && counts[j] == 26) continue;
            memcpy(identities, sentinel, sizeof identities);
            BB_CHECK(ad_identify_authored_proof_bundle(
                         recipes, counts[i], identities, counts[j], error) != 0);
            BB_CHECK_EQ(memcmp(identities, sentinel, sizeof identities), 0);
        }
    }

    ad_recipe original = recipes[0];
    recipes[0].controller_seed = UINT64_C(0xDEADBEEF);
    memcpy(identities, sentinel, sizeof identities);
    BB_CHECK(ad_identify_authored_proof_bundle(
                 recipes, 26, identities, 26, error) != 0);
    BB_CHECK_EQ(memcmp(identities, sentinel, sizeof identities), 0);
    recipes[0] = original;

    recipes[1] = recipes[0];
    memcpy(identities, sentinel, sizeof identities);
    BB_CHECK(ad_identify_authored_proof_bundle(
                 recipes, 26, identities, 26, error) != 0);
    BB_CHECK_EQ(memcmp(identities, sentinel, sizeof identities), 0);
    free(records);
    free(recipes);
}

BB_TEST(authored_identity_projection_is_fieldwise_and_float_bit_exact) {
    ad_recipe* recipes = NULL;
    ad_bbs_record* records = NULL;
    BB_CHECK_EQ(build_bundle(&recipes, &records), 0);
    if (recipes == NULL) return;
    ad_recipe_projection base;
    ad_recipe_projection changed;
    ad_recipe_projection_from_recipe(&recipes[0], &base);

#define DIFFERENT(field, expression) do {                                    \
        changed = base;                                                       \
        changed.field = (expression);                                         \
        BB_CHECK(!ad_recipe_projection_equal(&base, &changed));               \
    } while (0)
    DIFFERENT(procgen_seed, base.procgen_seed + 1);
    DIFFERENT(procgen_stream, base.procgen_stream + 1);
    DIFFERENT(game_seed, base.game_seed + 1);
    DIFFERENT(game_stream, base.game_stream + 1);
    DIFFERENT(controller_seed, base.controller_seed + 1);
    DIFFERENT(controller_stream, base.controller_stream + 1);
    DIFFERENT(kind, AD_RECIPE_F2_EXACT_HANDOFF_TARGET_COUNT);
    DIFFERENT(capture_turn, 1);
    DIFFERENT(capture_active_team, BB_AWAY);
    DIFFERENT(capture_handoff_target_bucket,
              AD_F2_TARGET_COUNT_EXACTLY_ONE);
    DIFFERENT(capture_pass_carrier_pressure,
              AD_F1_CARRIER_PRESSURE_MARKED);
    DIFFERENT(home_team, -1);
    DIFFERENT(away_team, -1);
    DIFFERENT(exclude_team, 0);
    DIFFERENT(skillup_max_players, base.skillup_max_players + 1);
    DIFFERENT(skillup_max_each, base.skillup_max_each + 1);
    DIFFERENT(skillup_secondary_pct_bits, UINT32_C(0x80000000));
#undef DIFFERENT
    BB_CHECK(ad_recipe_projection_equal(&base, &base));
    free(records);
    free(recipes);
}

BB_TEST(authored_identity_registry_rejects_collisions_and_malformed_rows) {
    const ad_authored_template_descriptor* source_templates;
    const ad_authored_allocation* source_allocations;
    const uint32_t* source_schedule;
    size_t template_count;
    size_t allocation_count;
    size_t schedule_count;
    ad_authored_registry_view(
        &source_templates, &template_count, &source_allocations,
        &allocation_count, &source_schedule, &schedule_count);
    BB_CHECK_EQ(template_count, 5);
    BB_CHECK_EQ(allocation_count, 26);
    BB_CHECK_EQ(schedule_count, 26);

    ad_authored_template_descriptor templates[5];
    ad_authored_allocation allocations[26];
    uint32_t schedule[26];
    char error[AD_ERROR_CAP];

#define RESET() do {                                                          \
        memcpy(templates, source_templates, sizeof templates);                \
        memcpy(allocations, source_allocations, sizeof allocations);          \
        memcpy(schedule, source_schedule, sizeof schedule);                    \
    } while (0)
#define VALIDATE() ad_validate_authored_registry(                              \
        templates, template_count, allocations, allocation_count,             \
        schedule, schedule_count, error)
#define REJECT(statement) do {                                                 \
        RESET();                                                               \
        statement;                                                             \
        BB_CHECK(VALIDATE() != 0);                                             \
    } while (0)

    RESET();
    BB_CHECK_EQ(VALIDATE(), 0);
    BB_CHECK_EQ(error[0], '\0');

    REJECT(templates[0].template_id = 0);
    REJECT(templates[1].template_id = templates[0].template_id);
    REJECT(templates[0].key[0] = '\0');
    REJECT(templates[0].key[0] = 'A');
    REJECT(templates[0].key[0] = '-');
    REJECT(templates[1].revision_1_kind = templates[0].revision_1_kind);
    REJECT(memset(templates[0].key, 'a', sizeof templates[0].key));

    RESET();
    memset(templates[0].key, 'a', sizeof templates[0].key);
    templates[0].key[sizeof templates[0].key - 1] = '\0';
    BB_CHECK_EQ(VALIDATE(), 0);

    REJECT(allocations[0].source_id = 0xAD000001u);
    REJECT(allocations[1].source_id = 0xAE000003u);
    REJECT(allocations[0].recipe_revision = 2);
    REJECT(allocations[0].cell_id = 0);
    REJECT(allocations[0].variant_id = 0);
    REJECT(allocations[0].variant_seed++);
    REJECT(allocations[0].projection.kind =
               AD_RECIPE_F2_EXACT_HANDOFF_TARGET_COUNT);
    REJECT(allocations[1].variant_id = allocations[0].variant_id);
    REJECT(allocations[1].cell_id = allocations[0].cell_id);

    REJECT(allocations[1].projection.capture_pass_carrier_pressure =
               allocations[0].projection.capture_pass_carrier_pressure);
    REJECT(allocations[1].projection = allocations[0].projection;
           allocations[1].variant_seed = allocations[0].variant_seed);

    // A second seed in the same exact cell is valid when every other
    // configuration field remains equal and its variant ID stays unique.
    RESET();
    allocations[1].projection = allocations[0].projection;
    allocations[1].projection.controller_seed = 2;
    allocations[1].variant_seed = 2;
    allocations[1].cell_id = allocations[0].cell_id;
    BB_CHECK_EQ(VALIDATE(), 0);

    REJECT(allocations[1].projection = allocations[0].projection;
           allocations[1].projection.controller_seed = 2;
           allocations[1].projection.game_seed++;
           allocations[1].variant_seed = 2;
           allocations[1].cell_id = allocations[0].cell_id);
    REJECT(schedule[0] = UINT32_C(0xAEFFFFFF));
    REJECT(schedule[0] = schedule[1]);

#undef REJECT
#undef VALIDATE
#undef RESET
}

static void check_projection_only_mutation(
    ad_recipe* recipes, ad_bbs_record* records,
    const ad_authored_identity* expected) {
    ad_authored_identity actual[AD_AUTHORED_PROOF_BUNDLE_COUNT];
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_identify_authored_proof_bundle(
                    recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                    actual, AD_AUTHORED_PROOF_BUNDLE_COUNT, error),
                0);
    BB_CHECK_EQ(memcmp(actual, expected, sizeof actual), 0);

    FILE* file = tmpfile();
    BB_CHECK(file != NULL);
    if (file != NULL) {
        BB_CHECK(ad_bbs_write(file, records,
                              AD_AUTHORED_PROOF_BUNDLE_COUNT, error) != 0);
        BB_CHECK_EQ(ftell(file), 0);
        BB_CHECK_EQ(fclose(file), 0);
    }
}

BB_TEST(authored_identity_excludes_transcripts_but_writer_still_binds_them) {
    ad_recipe* recipes = NULL;
    ad_bbs_record* records = NULL;
    BB_CHECK_EQ(build_bundle(&recipes, &records), 0);
    if (recipes == NULL) return;
    ad_authored_identity expected[AD_AUTHORED_PROOF_BUNDLE_COUNT];
    char error[AD_ERROR_CAP];
    BB_CHECK_EQ(ad_identify_authored_proof_bundle(
                    recipes, 26, expected, 26, error),
                0);
    ad_recipe* original = malloc(sizeof *original);
    BB_CHECK(original != NULL);
    if (original == NULL) {
        free(records);
        free(recipes);
        return;
    }
    *original = recipes[0];

#define MUTATE_AND_CHECK(statement) do {                                      \
        recipes[0] = *original;                                               \
        statement;                                                            \
        ad_recipe before = recipes[0];                                        \
        check_projection_only_mutation(recipes, records, expected);           \
        BB_CHECK_EQ(memcmp(&recipes[0], &before, sizeof before), 0);           \
    } while (0)
    MUTATE_AND_CHECK(recipes[0].initialized.score[0]++);
    MUTATE_AND_CHECK(recipes[0].actions[0] ^= UINT32_C(1));
    MUTATE_AND_CHECK(recipes[0].actions[recipes[0].action_count] ^=
                         UINT32_C(1));
    MUTATE_AND_CHECK(recipes[0].decision_teams[0] ^= UINT8_C(1));
    MUTATE_AND_CHECK(recipes[0].decision_teams[recipes[0].action_count] ^=
                         UINT8_C(1));
    MUTATE_AND_CHECK(recipes[0].dice_sides[0] ^= UINT8_C(1));
    MUTATE_AND_CHECK(recipes[0].dice_values[0] ^= UINT8_C(1));
    MUTATE_AND_CHECK(recipes[0].dice_sides[recipes[0].dice_count] = 6);
    MUTATE_AND_CHECK(recipes[0].dice_values[recipes[0].dice_count] = 1);
    MUTATE_AND_CHECK(recipes[0].action_count--);
    MUTATE_AND_CHECK(recipes[0].dice_count--);
    MUTATE_AND_CHECK(recipes[0].captured.step_count++);
#undef MUTATE_AND_CHECK

    free(original);
    free(records);
    free(recipes);
}

BB_TEST(authored_identity_rejects_null_and_overlapping_storage) {
    ad_recipe* recipes = NULL;
    ad_bbs_record* records = NULL;
    BB_CHECK_EQ(build_bundle(&recipes, &records), 0);
    if (recipes == NULL) return;
    ad_authored_identity identities[AD_AUTHORED_PROOF_BUNDLE_COUNT];
    ad_authored_identity sentinel[AD_AUTHORED_PROOF_BUNDLE_COUNT];
    memset(sentinel, 0xA5, sizeof sentinel);
    memcpy(identities, sentinel, sizeof identities);
    char error[AD_ERROR_CAP];
    BB_CHECK(ad_identify_authored_proof_bundle(
                 NULL, 26, identities, 26, error) != 0);
    BB_CHECK_EQ(memcmp(identities, sentinel, sizeof identities), 0);
    BB_CHECK(ad_identify_authored_proof_bundle(
                 recipes, 26, NULL, 26, error) != 0);
    BB_CHECK_EQ(memcmp(identities, sentinel, sizeof identities), 0);
    BB_CHECK(ad_identify_authored_proof_bundle(
                 recipes, 26, identities, 26, NULL) != 0);
    BB_CHECK_EQ(memcmp(identities, sentinel, sizeof identities), 0);

    // Error storage is part of the disjointness contract. Aliases must be
    // rejected before null/count diagnostics can write into caller arrays.
    BB_CHECK(ad_identify_authored_proof_bundle(
                 recipes, 25, identities, 26, (char*)identities) != 0);
    BB_CHECK_EQ(memcmp(identities, sentinel, sizeof identities), 0);
    BB_CHECK(ad_identify_authored_proof_bundle(
                 NULL, 26, identities, 26, (char*)identities) != 0);
    BB_CHECK_EQ(memcmp(identities, sentinel, sizeof identities), 0);
    ad_recipe recipe_before = recipes[0];
    BB_CHECK(ad_identify_authored_proof_bundle(
                 recipes, 26, NULL, 26, (char*)recipes) != 0);
    BB_CHECK_EQ(memcmp(&recipes[0], &recipe_before, sizeof recipe_before), 0);
    BB_CHECK(ad_identify_authored_proof_bundle(
                 recipes, 26, identities, 25, (char*)recipes) != 0);
    BB_CHECK_EQ(memcmp(&recipes[0], &recipe_before, sizeof recipe_before), 0);
    BB_CHECK_EQ(memcmp(identities, sentinel, sizeof identities), 0);

    // Over-count diagnostics must protect the caller-declared 27th element,
    // not only the fixed 26-element bundle prefix.
    ad_recipe* over_recipes = malloc(27 * sizeof *over_recipes);
    ad_recipe* over_recipes_before = malloc(27 * sizeof *over_recipes_before);
    BB_CHECK(over_recipes != NULL && over_recipes_before != NULL);
    if (over_recipes != NULL && over_recipes_before != NULL) {
        memcpy(over_recipes, recipes, 26 * sizeof *over_recipes);
        memset(&over_recipes[26], 0x5A, sizeof over_recipes[26]);
        memcpy(over_recipes_before, over_recipes,
               27 * sizeof *over_recipes_before);
        BB_CHECK(ad_identify_authored_proof_bundle(
                     over_recipes, 27, identities, 26,
                     (char*)&over_recipes[26]) != 0);
        BB_CHECK_EQ(memcmp(over_recipes, over_recipes_before,
                           27 * sizeof *over_recipes), 0);
    }
    free(over_recipes_before);
    free(over_recipes);

    size_t over_identity_bytes = 27 * sizeof(ad_authored_identity) +
        AD_ERROR_CAP;
    ad_authored_identity* over_identities = malloc(over_identity_bytes);
    ad_authored_identity* over_identities_before = malloc(over_identity_bytes);
    BB_CHECK(over_identities != NULL && over_identities_before != NULL);
    if (over_identities != NULL && over_identities_before != NULL) {
        memset(over_identities, 0xA5, over_identity_bytes);
        memcpy(over_identities_before, over_identities, over_identity_bytes);
        BB_CHECK(ad_identify_authored_proof_bundle(
                     recipes, 26, over_identities, 27,
                     (char*)&over_identities[26]) != 0);
        BB_CHECK_EQ(memcmp(over_identities, over_identities_before,
                           over_identity_bytes), 0);
    }
    free(over_identities_before);
    free(over_identities);

    char overflow_error[AD_ERROR_CAP];
    char overflow_error_before[AD_ERROR_CAP];
    memset(overflow_error, 0x3C, sizeof overflow_error);
    memcpy(overflow_error_before, overflow_error, sizeof overflow_error);
    BB_CHECK(ad_identify_authored_proof_bundle(
                 recipes, SIZE_MAX, identities, 26, overflow_error) != 0);
    BB_CHECK_EQ(memcmp(overflow_error, overflow_error_before,
                       sizeof overflow_error), 0);
    BB_CHECK_EQ(memcmp(identities, sentinel, sizeof identities), 0);
    BB_CHECK(ad_identify_authored_proof_bundle(
                 recipes, 26, identities, SIZE_MAX, overflow_error) != 0);
    BB_CHECK_EQ(memcmp(overflow_error, overflow_error_before,
                       sizeof overflow_error), 0);
    BB_CHECK_EQ(memcmp(identities, sentinel, sizeof identities), 0);

    // Deliberately overlapping recipe/output storage must fail before either
    // caller-owned object is touched.
    BB_CHECK(ad_identify_authored_proof_bundle(
                 recipes, 26, (ad_authored_identity*)recipes, 26, error) != 0);
    BB_CHECK_EQ(memcmp(&recipes[0], &recipe_before, sizeof recipe_before), 0);
    free(records);
    free(recipes);
}
