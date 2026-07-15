#include "authored_drill.h"
#include "authored_identity_internal.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

_Static_assert(AD_AUTHORED_IDENTITY_SCHEMA_VERSION == 1u,
               "identity schema constant differs");
_Static_assert(AD_AUTHORED_TEMPLATE_KEY_CAP == 64u,
               "template key capacity differs");
_Static_assert(AD_AUTHORED_PROOF_BUNDLE_COUNT == 26,
               "authored proof count differs");

static void require(int condition, const char* message) {
    if (!condition) {
        fprintf(stderr, "%s\n", message);
        exit(1);
    }
}

static void put_bytes(FILE* out, const void* data, size_t size) {
    require(fwrite(data, 1, size, out) == size, "fwrite failed");
}

static void put_u32(FILE* out, uint32_t value) {
    uint8_t data[4] = {
        (uint8_t)value,
        (uint8_t)(value >> 8),
        (uint8_t)(value >> 16),
        (uint8_t)(value >> 24),
    };
    put_bytes(out, data, sizeof data);
}

static void put_u64(FILE* out, uint64_t value) {
    uint8_t data[8];
    for (int i = 0; i < 8; i++) data[i] = (uint8_t)(value >> (8 * i));
    put_bytes(out, data, sizeof data);
}

static FILE* open_output(const char* directory) {
    char path[4096];
    int length = snprintf(path, sizeof path, "%s/identity.bin", directory);
    require(length >= 0 && (size_t)length < sizeof path,
            "identity output path is too long");
    FILE* out = fopen(path, "wb");
    require(out != NULL, "identity output open failed");
    return out;
}

static void require_projection_difference(const ad_recipe_projection* base,
                                          ad_recipe_projection changed) {
    require(!ad_recipe_projection_equal(base, &changed),
            "projection mutation compared equal");
}

static void require_public_mapping_rejection(
    ad_recipe* recipes, const ad_recipe* canonical,
    ad_authored_identity identities[AD_AUTHORED_PROOF_BUNDLE_COUNT],
    char error[AD_ERROR_CAP]) {
    size_t recipe_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes;
    ad_recipe* before = malloc(recipe_bytes);
    require(before != NULL, "public mapper snapshot allocation failed");
    memcpy(before, recipes, recipe_bytes);
    memset(identities, 0xA5,
           AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *identities);
    ad_authored_identity output_before[AD_AUTHORED_PROOF_BUNDLE_COUNT];
    memcpy(output_before, identities, sizeof output_before);
    require(ad_identify_authored_proof_bundle(
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                identities, AD_AUTHORED_PROOF_BUNDLE_COUNT, error) != 0,
            "mutated recipe identified through the public mapper");
    require(memcmp(before, recipes, recipe_bytes) == 0,
            "failed public mapping changed recipe input");
    require(memcmp(output_before, identities, sizeof output_before) == 0,
            "failed public mapping changed identity output");
    memcpy(recipes, canonical, recipe_bytes);
    free(before);
}

int main(int argc, char** argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s OUTPUT_DIRECTORY\n", argv[0]);
        return 2;
    }
    const char* (*key_lookup)(uint32_t) = ad_authored_template_key;
    int (*identify_bundle)(const ad_recipe*, size_t, ad_authored_identity*,
                           size_t, char[AD_ERROR_CAP]) =
        ad_identify_authored_proof_bundle;
    require(key_lookup != NULL && identify_bundle != NULL,
            "public identity function signature differs");
    ad_recipe* recipes = calloc(AD_AUTHORED_PROOF_BUNDLE_COUNT,
                                sizeof *recipes);
    ad_bbs_record* records = calloc(AD_AUTHORED_PROOF_BUNDLE_COUNT,
                                    sizeof *records);
    require(recipes != NULL && records != NULL, "allocation failed");
    char error[AD_ERROR_CAP];
    require(ad_build_authored_proof_bundle(
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                records, AD_AUTHORED_PROOF_BUNDLE_COUNT, error) == 0,
            error);
    ad_authored_identity identities[AD_AUTHORED_PROOF_BUNDLE_COUNT];
    require(ad_identify_authored_proof_bundle(
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                identities, AD_AUTHORED_PROOF_BUNDLE_COUNT, error) == 0,
            error);

    FILE* out = open_output(argv[1]);
    put_bytes(out, "ADIDN001", 8);
    put_u32(out, AD_AUTHORED_PROOF_BUNDLE_COUNT);
    for (uint32_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        const ad_authored_identity* identity = &identities[i];
        const char* key = ad_authored_template_key(identity->template_id);
        require(key != NULL, "identity has unknown template key");
        size_t key_length = strlen(key);
        require(key_length > 0 && key_length < AD_AUTHORED_TEMPLATE_KEY_CAP,
                "identity key length differs");
        put_u32(out, i);
        put_u64(out, identity->variant_seed);
        put_u32(out, identity->identity_schema_version);
        put_u32(out, identity->source_id);
        put_u32(out, identity->template_id);
        put_u32(out, identity->recipe_revision);
        put_u32(out, identity->cell_id);
        put_u32(out, identity->variant_id);
        put_u32(out, (uint32_t)key_length);
        put_bytes(out, key, key_length);
    }
    require(fclose(out) == 0, "identity output close failed");

    ad_recipe_projection base;
    ad_recipe_projection changed;
    ad_recipe_projection_from_recipe(&recipes[0], &base);
#define DIFFERENT(field, value) do {                                          \
        changed = base;                                                       \
        changed.field = (value);                                              \
        require_projection_difference(&base, changed);                        \
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

    size_t recipe_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes;
    ad_recipe* canonical = malloc(recipe_bytes);
    require(canonical != NULL, "canonical recipe allocation failed");
    memcpy(canonical, recipes, recipe_bytes);

#define REJECT_PUBLIC(statement) do {                                        \
        memcpy(recipes, canonical, recipe_bytes);                            \
        statement;                                                           \
        require_public_mapping_rejection(recipes, canonical, identities,     \
                                         error);                              \
    } while (0)
    REJECT_PUBLIC(recipes[0].procgen_seed++);
    REJECT_PUBLIC(recipes[0].procgen_stream++);
    REJECT_PUBLIC(recipes[0].game_seed++);
    REJECT_PUBLIC(recipes[0].game_stream++);
    REJECT_PUBLIC(recipes[0].controller_seed++);
    REJECT_PUBLIC(recipes[0].controller_stream++);
    REJECT_PUBLIC(recipes[25].kind = AD_RECIPE_F4_PENDING_DODGE_REROLL);
    REJECT_PUBLIC(recipes[8].capture_turn =
                      recipes[8].capture_turn == 1 ? 2 : 1);
    REJECT_PUBLIC(recipes[0].capture_active_team =
                      recipes[0].capture_active_team == BB_HOME
                          ? BB_AWAY : BB_HOME);
    REJECT_PUBLIC(recipes[4].capture_handoff_target_bucket =
                      recipes[4].capture_handoff_target_bucket ==
                              AD_F2_TARGET_COUNT_EXACTLY_ONE
                          ? AD_F2_TARGET_COUNT_TWO_OR_MORE
                          : AD_F2_TARGET_COUNT_EXACTLY_ONE);
    REJECT_PUBLIC(recipes[0].capture_pass_carrier_pressure =
                      recipes[0].capture_pass_carrier_pressure ==
                              AD_F1_CARRIER_PRESSURE_OPEN
                          ? AD_F1_CARRIER_PRESSURE_MARKED
                          : AD_F1_CARRIER_PRESSURE_OPEN);
    REJECT_PUBLIC(recipes[0].home_team = -1);
    REJECT_PUBLIC(recipes[0].away_team = -1);
    REJECT_PUBLIC(recipes[0].exclude_team =
                      recipes[0].exclude_team == 0 ? 1 : 0);
    REJECT_PUBLIC(recipes[0].procgen.skillup_max_players =
                      recipes[0].procgen.skillup_max_players == 0 ? 1 : 0);
    REJECT_PUBLIC(recipes[0].procgen.skillup_max_each =
                      recipes[0].procgen.skillup_max_each == 0 ? 1 : 0);
    REJECT_PUBLIC(recipes[0].procgen.skillup_secondary_pct =
                      recipes[0].procgen.skillup_secondary_pct == 0.0f
                          ? 0.5f : 0.0f);
#undef REJECT_PUBLIC

#define SWAP_FIELD(type, left, right, field) do {                            \
        type temporary = recipes[(left)].field;                              \
        recipes[(left)].field = recipes[(right)].field;                      \
        recipes[(right)].field = temporary;                                  \
    } while (0)
#define REJECT_COMPOSITION_VALID(statement) do {                             \
        memcpy(recipes, canonical, recipe_bytes);                            \
        statement;                                                           \
        require(ad_validate_authored_proof_bundle(                           \
                    recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT, error) == 0,    \
                "paired semantic mutation failed composition first");       \
        require_public_mapping_rejection(recipes, canonical, identities,     \
                                         error);                              \
    } while (0)
    REJECT_COMPOSITION_VALID(
        SWAP_FIELD(ad_recipe_kind, 24, 25, kind);
        SWAP_FIELD(bb_match, 24, 25, captured));
    REJECT_COMPOSITION_VALID(
        SWAP_FIELD(int, 8, 9, capture_turn);
        SWAP_FIELD(bb_match, 8, 9, captured));
    REJECT_COMPOSITION_VALID(
        SWAP_FIELD(int, 0, 2, capture_active_team);
        SWAP_FIELD(bb_match, 0, 2, captured));
    REJECT_COMPOSITION_VALID(
        SWAP_FIELD(ad_f2_target_count_bucket, 4, 5,
                   capture_handoff_target_bucket);
        SWAP_FIELD(bb_match, 4, 5, captured));
    REJECT_COMPOSITION_VALID(
        SWAP_FIELD(ad_f1_carrier_pressure_bucket, 0, 1,
                   capture_pass_carrier_pressure);
        SWAP_FIELD(bb_match, 0, 1, captured));
#undef REJECT_COMPOSITION_VALID
#undef SWAP_FIELD

    ad_recipe original = recipes[0];
    for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        recipes[0] = original;
        recipes[0].controller_seed = UINT64_C(0xF0000000) + i;
        memset(identities, 0xA5, sizeof identities);
        ad_authored_identity before[AD_AUTHORED_PROOF_BUNDLE_COUNT];
        memcpy(before, identities, sizeof before);
        require(ad_identify_authored_proof_bundle(
                    recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                    identities, AD_AUTHORED_PROOF_BUNDLE_COUNT, error) != 0,
                "unknown controller seed identified");
        require(memcmp(before, identities, sizeof before) == 0,
                "failed identity mapping changed output");
    }
    recipes[0] = original;
    memset(identities, 0xA5, sizeof identities);
    ad_authored_identity alias_before[AD_AUTHORED_PROOF_BUNDLE_COUNT];
    memcpy(alias_before, identities, sizeof alias_before);
    require(ad_identify_authored_proof_bundle(
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT - 1,
                identities, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (char*)identities) != 0,
            "identity/error alias unexpectedly succeeded");
    require(memcmp(alias_before, identities, sizeof alias_before) == 0,
            "early identity/error alias changed output");
    ad_recipe recipe_alias_before = recipes[0];
    require(ad_identify_authored_proof_bundle(
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                NULL, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (char*)recipes) != 0,
            "recipe/error alias unexpectedly succeeded");
    require(memcmp(&recipe_alias_before, &recipes[0], sizeof recipe_alias_before)
                == 0,
            "early recipe/error alias changed input");

    ad_recipe* over_recipes = malloc(
        (AD_AUTHORED_PROOF_BUNDLE_COUNT + 1) * sizeof *over_recipes);
    ad_recipe* over_recipes_before = malloc(
        (AD_AUTHORED_PROOF_BUNDLE_COUNT + 1) * sizeof *over_recipes_before);
    require(over_recipes != NULL && over_recipes_before != NULL,
            "over-count recipe allocation failed");
    memcpy(over_recipes, recipes, recipe_bytes);
    memset(&over_recipes[AD_AUTHORED_PROOF_BUNDLE_COUNT], 0x5A,
           sizeof over_recipes[AD_AUTHORED_PROOF_BUNDLE_COUNT]);
    memcpy(over_recipes_before, over_recipes,
           (AD_AUTHORED_PROOF_BUNDLE_COUNT + 1) * sizeof *over_recipes_before);
    require(ad_identify_authored_proof_bundle(
                over_recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT + 1,
                identities, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (char*)&over_recipes[AD_AUTHORED_PROOF_BUNDLE_COUNT]) != 0,
            "over-count recipe/error alias unexpectedly succeeded");
    require(memcmp(over_recipes, over_recipes_before,
                   (AD_AUTHORED_PROOF_BUNDLE_COUNT + 1) *
                       sizeof *over_recipes) == 0,
            "over-count recipe/error alias changed input");
    free(over_recipes_before);
    free(over_recipes);

    size_t over_identity_bytes =
        (AD_AUTHORED_PROOF_BUNDLE_COUNT + 1) *
            sizeof(ad_authored_identity) + AD_ERROR_CAP;
    ad_authored_identity* over_identities = malloc(over_identity_bytes);
    ad_authored_identity* over_identities_before = malloc(over_identity_bytes);
    require(over_identities != NULL && over_identities_before != NULL,
            "over-count identity allocation failed");
    memset(over_identities, 0xA5, over_identity_bytes);
    memcpy(over_identities_before, over_identities, over_identity_bytes);
    require(ad_identify_authored_proof_bundle(
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                over_identities, AD_AUTHORED_PROOF_BUNDLE_COUNT + 1,
                (char*)&over_identities[AD_AUTHORED_PROOF_BUNDLE_COUNT]) != 0,
            "over-count identity/error alias unexpectedly succeeded");
    require(memcmp(over_identities, over_identities_before,
                   over_identity_bytes) == 0,
            "over-count identity/error alias changed output");
    free(over_identities_before);
    free(over_identities);

    char overflow_error[AD_ERROR_CAP];
    char overflow_error_before[AD_ERROR_CAP];
    memset(overflow_error, 0x3C, sizeof overflow_error);
    memcpy(overflow_error_before, overflow_error, sizeof overflow_error);
    memcpy(alias_before, identities, sizeof alias_before);
    require(ad_identify_authored_proof_bundle(
                recipes, SIZE_MAX, identities,
                AD_AUTHORED_PROOF_BUNDLE_COUNT, overflow_error) != 0,
            "overflowing recipe extent unexpectedly succeeded");
    require(memcmp(overflow_error, overflow_error_before,
                   sizeof overflow_error) == 0,
            "overflowing extent wrote an error diagnostic");
    require(memcmp(alias_before, identities, sizeof alias_before) == 0,
            "overflowing extent changed identity output");
    require(ad_identify_authored_proof_bundle(
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                identities, SIZE_MAX, overflow_error) != 0,
            "overflowing identity extent unexpectedly succeeded");
    require(memcmp(overflow_error, overflow_error_before,
                   sizeof overflow_error) == 0,
            "overflowing identity extent wrote an error diagnostic");
    require(memcmp(alias_before, identities, sizeof alias_before) == 0,
            "overflowing identity extent changed output");

    free(canonical);
    free(records);
    free(recipes);
    return 0;
}
