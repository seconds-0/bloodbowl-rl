#include "authored_drill.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void require(int condition, const char* message) {
    if (!condition) {
        fprintf(stderr, "%s\n", message);
        exit(1);
    }
}

static void require_rejected_unchanged(ad_recipe* recipes,
                                       ad_bbs_record* records) {
    size_t recipe_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes;
    ad_recipe* before_recipes = malloc(recipe_bytes);
    ad_bbs_record before_records[AD_AUTHORED_PROOF_BUNDLE_COUNT];
    require(before_recipes != NULL, "snapshot allocation failed");
    memcpy(before_recipes, recipes, recipe_bytes);
    memcpy(before_records, records, sizeof before_records);
    FILE* file = tmpfile();
    require(file != NULL, "tmpfile failed");
    char error[AD_ERROR_CAP];
    require(ad_bbs_write(file, records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                         error) != 0,
            "provenance mutation unexpectedly succeeded");
    require(fseek(file, 0, SEEK_END) == 0, "failed to seek writer output");
    require(ftell(file) == 0, "failed writer emitted a byte");
    require(memcmp(before_recipes, recipes, recipe_bytes) == 0,
            "writer mutated recipe input");
    require(memcmp(before_records, records, sizeof before_records) == 0,
            "writer mutated record input");
    require(fclose(file) == 0, "fclose failed");
    free(before_recipes);
}

int main(void) {
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
    size_t recipe_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes;
    ad_recipe* canonical = malloc(recipe_bytes);
    require(canonical != NULL, "canonical allocation failed");
    memcpy(canonical, recipes, recipe_bytes);
    ad_bbs_record canonical_records[AD_AUTHORED_PROOF_BUNDLE_COUNT];
    memcpy(canonical_records, records, sizeof canonical_records);

#define REJECT_MUTATION(statement) do {                                      \
        memcpy(recipes, canonical, recipe_bytes);                             \
        memcpy(records, canonical_records, sizeof canonical_records);         \
        statement;                                                            \
        require_rejected_unchanged(recipes, records);                         \
    } while (0)
    REJECT_MUTATION(recipes[0].initialized.score[0]++);
    REJECT_MUTATION(recipes[0].actions[0] ^= UINT32_C(1));
    REJECT_MUTATION(recipes[0].actions[recipes[0].action_count] ^=
                        UINT32_C(1));
    REJECT_MUTATION(recipes[0].decision_teams[0] ^= UINT8_C(1));
    REJECT_MUTATION(recipes[0].decision_teams[recipes[0].action_count] ^=
                        UINT8_C(1));
    REJECT_MUTATION(recipes[0].dice_sides[0] ^= UINT8_C(1));
    REJECT_MUTATION(recipes[0].dice_values[0] ^= UINT8_C(1));
    REJECT_MUTATION(recipes[0].dice_sides[recipes[0].dice_count] = 6);
    REJECT_MUTATION(recipes[0].dice_values[recipes[0].dice_count] = 1);
    REJECT_MUTATION(recipes[0].action_count--);
    REJECT_MUTATION(recipes[0].dice_count--);
    REJECT_MUTATION(recipes[0].captured.step_count++);
    REJECT_MUTATION(recipes[0].controller_seed++);
    REJECT_MUTATION(recipes[0].game_seed++);
    REJECT_MUTATION(records[0].decision_index++);

    // Repeat representative provenance failures for every authored family,
    // including F2 and the distinct nested F4 shape.
    static const size_t family_indices[] = {0, 4, 8, 24, 25};
    for (size_t family = 0;
         family < sizeof family_indices / sizeof family_indices[0]; family++) {
        size_t i = family_indices[family];
        REJECT_MUTATION(recipes[i].initialized.score[0]++);
        REJECT_MUTATION(recipes[i].actions[0] ^= UINT32_C(1));
        REJECT_MUTATION(recipes[i].decision_teams[0] ^= UINT8_C(1));
        REJECT_MUTATION(recipes[i].dice_sides[0] ^= UINT8_C(1));
        REJECT_MUTATION(recipes[i].dice_values[0] ^= UINT8_C(1));
        REJECT_MUTATION(recipes[i].action_count--);
        REJECT_MUTATION(recipes[i].dice_count--);
        REJECT_MUTATION(recipes[i].captured.step_count++);
        REJECT_MUTATION(recipes[i].game_seed++);
    }

    // Seeds and record indices are the obvious index-selective branch keys, so
    // bind both at every one of the 26 positions.
    for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        REJECT_MUTATION(recipes[i].controller_seed++);
        REJECT_MUTATION(records[i].decision_index++);
    }
#undef REJECT_MUTATION

    free(canonical);
    free(records);
    free(recipes);
    puts("writer negative provenance verified");
    return 0;
}
