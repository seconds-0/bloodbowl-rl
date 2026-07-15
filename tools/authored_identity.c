#include "authored_identity_internal.h"
#include "bb/gen_teams.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

enum {
    AD_AUTHORED_NAMESPACE = 0xAE000000u,
    AD_AUTHORED_ORDINAL_MASK = 0x00FFFFFFu,
};

static const ad_authored_template_descriptor ad_templates[] = {
#define AD_TEMPLATE(id, key_value, kind_value) \
    {(id), (key_value), (kind_value)},
#define AD_ALLOCATION(...)
#include "authored_identity_ledger.def"
#undef AD_ALLOCATION
#undef AD_TEMPLATE
};

static const ad_authored_allocation ad_allocations[] = {
#define AD_TEMPLATE(...)
#define AD_ALLOCATION(source, template, revision, cell, variant, variant_seed_value, \
                      procgen_seed_value, procgen_stream_value, game_seed_value, \
                      game_stream_value, controller_seed_value,                 \
                      controller_stream_value, kind_value, capture_turn_value,  \
                      active_team_value, handoff_value, pressure_value,          \
                      home_value, away_value, exclude_value, max_players_value,  \
                      max_each_value, secondary_bits_value)                     \
    {                                                                            \
        (source), (template), (revision), (cell), (variant),                     \
        (variant_seed_value),                                                     \
        {                                                                         \
            (procgen_seed_value), (procgen_stream_value), (game_seed_value),     \
            (game_stream_value), (controller_seed_value),                        \
            (controller_stream_value), (kind_value), (capture_turn_value),       \
            (active_team_value), (handoff_value), (pressure_value),              \
            (home_value), (away_value), (exclude_value), (max_players_value),    \
            (max_each_value), (secondary_bits_value),                            \
        },                                                                        \
    },
#include "authored_identity_ledger.def"
#undef AD_ALLOCATION
#undef AD_TEMPLATE
};

static const uint32_t ad_legacy_schedule[] = {
#define AD_LEGACY_PROOF(source) (source),
#include "authored_identity_legacy_proof.def"
#undef AD_LEGACY_PROOF
};

_Static_assert(sizeof ad_allocations / sizeof ad_allocations[0] ==
                   AD_AUTHORED_PROOF_BUNDLE_COUNT,
               "schema-1 allocation count changed");
_Static_assert(sizeof ad_legacy_schedule / sizeof ad_legacy_schedule[0] ==
                   AD_AUTHORED_PROOF_BUNDLE_COUNT,
               "legacy proof schedule count changed");

static int identity_fail(char error[AD_ERROR_CAP], const char* format, ...) {
    if (error != NULL) {
        va_list args;
        va_start(args, format);
        vsnprintf(error, AD_ERROR_CAP, format, args);
        va_end(args);
    }
    return -1;
}

static uint32_t float_bits(float value) {
    uint32_t bits;
    _Static_assert(sizeof bits == sizeof value, "float width changed");
    memcpy(&bits, &value, sizeof bits);
    return bits;
}

static float bits_float(uint32_t bits) {
    float value;
    memcpy(&value, &bits, sizeof value);
    return value;
}

void ad_recipe_projection_from_recipe(const ad_recipe* recipe,
                                      ad_recipe_projection* projection) {
    *projection = (ad_recipe_projection){
        recipe->procgen_seed,
        recipe->procgen_stream,
        recipe->game_seed,
        recipe->game_stream,
        recipe->controller_seed,
        recipe->controller_stream,
        recipe->kind,
        recipe->capture_turn,
        recipe->capture_active_team,
        recipe->capture_handoff_target_bucket,
        recipe->capture_pass_carrier_pressure,
        recipe->home_team,
        recipe->away_team,
        recipe->exclude_team,
        recipe->procgen.skillup_max_players,
        recipe->procgen.skillup_max_each,
        float_bits(recipe->procgen.skillup_secondary_pct),
    };
}

int ad_recipe_projection_equal(const ad_recipe_projection* left,
                               const ad_recipe_projection* right) {
    return left->procgen_seed == right->procgen_seed &&
           left->procgen_stream == right->procgen_stream &&
           left->game_seed == right->game_seed &&
           left->game_stream == right->game_stream &&
           left->controller_seed == right->controller_seed &&
           left->controller_stream == right->controller_stream &&
           left->kind == right->kind &&
           left->capture_turn == right->capture_turn &&
           left->capture_active_team == right->capture_active_team &&
           left->capture_handoff_target_bucket ==
               right->capture_handoff_target_bucket &&
           left->capture_pass_carrier_pressure ==
               right->capture_pass_carrier_pressure &&
           left->home_team == right->home_team &&
           left->away_team == right->away_team &&
           left->exclude_team == right->exclude_team &&
           left->skillup_max_players == right->skillup_max_players &&
           left->skillup_max_each == right->skillup_max_each &&
           left->skillup_secondary_pct_bits ==
               right->skillup_secondary_pct_bits;
}

static int cell_projection_equal(const ad_recipe_projection* left,
                                 const ad_recipe_projection* right) {
    return left->kind == right->kind &&
           left->capture_turn == right->capture_turn &&
           left->capture_active_team == right->capture_active_team &&
           left->capture_handoff_target_bucket ==
               right->capture_handoff_target_bucket &&
           left->capture_pass_carrier_pressure ==
               right->capture_pass_carrier_pressure;
}

static int equal_except_controller_seed(const ad_recipe_projection* left,
                                        const ad_recipe_projection* right) {
    ad_recipe_projection left_copy = *left;
    ad_recipe_projection right_copy = *right;
    left_copy.controller_seed = 0;
    right_copy.controller_seed = 0;
    return ad_recipe_projection_equal(&left_copy, &right_copy);
}

static int projection_valid(const ad_recipe_projection* projection) {
    int f3 = projection->kind == AD_RECIPE_F3_EXACT_SECOND_HALF_TURN;
    int f2 = projection->kind == AD_RECIPE_F2_EXACT_HANDOFF_TARGET_COUNT;
    int f1 = projection->kind == AD_RECIPE_F1_EXACT_PASS_CARRIER_PRESSURE;
    float secondary = bits_float(projection->skillup_secondary_pct_bits);
    return projection->kind >= AD_RECIPE_FIRST_TEAM_TURN &&
           projection->kind < AD_RECIPE_KIND_COUNT &&
           (f3 ? projection->capture_turn >= 1 &&
                     projection->capture_turn <= AD_F3_SECOND_HALF_TURN_COUNT
               : projection->capture_turn == 0) &&
           (f1 || f2 || f3
                ? projection->capture_active_team >= BB_HOME &&
                      projection->capture_active_team <= BB_AWAY
                : projection->capture_active_team == 0) &&
           (f2 ? projection->capture_handoff_target_bucket >=
                         AD_F2_TARGET_COUNT_EXACTLY_ONE &&
                     projection->capture_handoff_target_bucket <=
                         AD_F2_TARGET_COUNT_TWO_OR_MORE
               : projection->capture_handoff_target_bucket ==
                     AD_F2_TARGET_COUNT_NONE) &&
           (f1 ? projection->capture_pass_carrier_pressure >=
                         AD_F1_CARRIER_PRESSURE_OPEN &&
                     projection->capture_pass_carrier_pressure <=
                         AD_F1_CARRIER_PRESSURE_MARKED
               : projection->capture_pass_carrier_pressure ==
                     AD_F1_CARRIER_PRESSURE_NONE) &&
           projection->home_team >= -1 &&
           projection->home_team < BB_TEAM_COUNT &&
           projection->away_team >= -1 &&
           projection->away_team < BB_TEAM_COUNT &&
           projection->exclude_team >= -1 &&
           projection->exclude_team < BB_TEAM_COUNT &&
           projection->skillup_max_players >= 0 &&
           projection->skillup_max_players <= BB_TEAM_SLOTS &&
           projection->skillup_max_each >= 0 &&
           projection->skillup_max_each <= 12 && secondary >= 0.0f &&
           secondary <= 1.0f;
}

static int key_valid(const char key[AD_AUTHORED_TEMPLATE_KEY_CAP]) {
    size_t length = 0;
    while (length < AD_AUTHORED_TEMPLATE_KEY_CAP && key[length] != '\0') {
        unsigned char c = (unsigned char)key[length];
        if ((length == 0 && (c < 'a' || c > 'z')) ||
            (length > 0 && !((c >= 'a' && c <= 'z') ||
                             (c >= '0' && c <= '9') || c == '-'))) {
            return 0;
        }
        length++;
    }
    return length > 0 && length < AD_AUTHORED_TEMPLATE_KEY_CAP;
}

static const ad_authored_template_descriptor* find_template(
    const ad_authored_template_descriptor* templates, size_t count,
    uint32_t template_id) {
    const ad_authored_template_descriptor* found = NULL;
    for (size_t i = 0; i < count; i++) {
        if (templates[i].template_id == template_id) {
            if (found != NULL) return NULL;
            found = &templates[i];
        }
    }
    return found;
}

static const ad_authored_allocation* find_allocation(
    const ad_authored_allocation* allocations, size_t count,
    uint32_t source_id) {
    const ad_authored_allocation* found = NULL;
    for (size_t i = 0; i < count; i++) {
        if (allocations[i].source_id == source_id) {
            if (found != NULL) return NULL;
            found = &allocations[i];
        }
    }
    return found;
}

int ad_validate_authored_registry(
    const ad_authored_template_descriptor* templates, size_t template_count,
    const ad_authored_allocation* allocations, size_t allocation_count,
    const uint32_t* legacy_schedule, size_t schedule_count,
    char error[AD_ERROR_CAP]) {
    if (error == NULL) return -1;
    if (templates == NULL || allocations == NULL || legacy_schedule == NULL) {
        return identity_fail(error, "null authored registry table");
    }
    if (template_count != sizeof ad_templates / sizeof ad_templates[0] ||
        allocation_count != AD_AUTHORED_PROOF_BUNDLE_COUNT ||
        allocation_count > AD_AUTHORED_ORDINAL_MASK) {
        return identity_fail(error, "invalid authored registry table count");
    }
    for (size_t i = 0; i < template_count; i++) {
        const ad_authored_template_descriptor* item = &templates[i];
        if (item->template_id == 0 || !key_valid(item->key) ||
            item->revision_1_kind < AD_RECIPE_FIRST_TEAM_TURN ||
            item->revision_1_kind >= AD_RECIPE_KIND_COUNT) {
            return identity_fail(error, "invalid authored template %zu", i);
        }
        for (size_t j = 0; j < i; j++) {
            if (templates[j].template_id == item->template_id ||
                strcmp(templates[j].key, item->key) == 0) {
                return identity_fail(error,
                                     "duplicate authored template %zu", i);
            }
        }
    }

    for (size_t i = 0; i < allocation_count; i++) {
        const ad_authored_allocation* item = &allocations[i];
        uint32_t expected = AD_AUTHORED_NAMESPACE | (uint32_t)(i + 1);
        const ad_authored_template_descriptor* descriptor =
            find_template(templates, template_count, item->template_id);
        if (item->source_id != expected || descriptor == NULL ||
            item->recipe_revision != 1 || item->cell_id == 0 ||
            item->variant_id == 0 ||
            item->variant_seed != item->projection.controller_seed ||
            descriptor->revision_1_kind != item->projection.kind ||
            !projection_valid(&item->projection)) {
            return identity_fail(error,
                                 "invalid authored allocation %zu", i);
        }
        for (size_t j = 0; j < i; j++) {
            const ad_authored_allocation* prior = &allocations[j];
            if (prior->source_id == item->source_id ||
                (prior->template_id == item->template_id &&
                 prior->recipe_revision == item->recipe_revision &&
                 prior->variant_id == item->variant_id) ||
                ad_recipe_projection_equal(&prior->projection,
                                           &item->projection)) {
                return identity_fail(error,
                                     "duplicate authored allocation %zu", i);
            }
            if (prior->template_id == item->template_id &&
                prior->recipe_revision == item->recipe_revision) {
                int same_cell = prior->cell_id == item->cell_id;
                int same_projection = cell_projection_equal(
                    &prior->projection, &item->projection);
                if (same_cell != same_projection ||
                    (same_cell &&
                     (!equal_except_controller_seed(&prior->projection,
                                                    &item->projection) ||
                      prior->projection.controller_seed ==
                          item->projection.controller_seed))) {
                    return identity_fail(error,
                                         "inconsistent authored cell %zu", i);
                }
            }
        }
    }

    if (schedule_count != AD_AUTHORED_PROOF_BUNDLE_COUNT) {
        return identity_fail(error, "legacy authored schedule count differs");
    }
    size_t families[AD_RECIPE_KIND_COUNT] = {0};
    for (size_t i = 0; i < schedule_count; i++) {
        const ad_authored_allocation* item = find_allocation(
            allocations, allocation_count, legacy_schedule[i]);
        if (item == NULL) {
            return identity_fail(error,
                                 "unknown legacy authored schedule row %zu", i);
        }
        for (size_t j = 0; j < i; j++) {
            if (legacy_schedule[j] == legacy_schedule[i]) {
                return identity_fail(error,
                                     "duplicate legacy authored row %zu", i);
            }
        }
        families[item->projection.kind]++;
    }
    if (families[AD_RECIPE_F1_EXACT_PASS_CARRIER_PRESSURE] != 4 ||
        families[AD_RECIPE_F2_EXACT_HANDOFF_TARGET_COUNT] != 4 ||
        families[AD_RECIPE_F3_EXACT_SECOND_HALF_TURN] != 16 ||
        families[AD_RECIPE_F4_PENDING_DODGE_REROLL] != 1 ||
        families[AD_RECIPE_F5_SCORE_OR_WAIT] != 1) {
        return identity_fail(error, "legacy authored family composition differs");
    }
    error[0] = '\0';
    return 0;
}

void ad_authored_registry_view(
    const ad_authored_template_descriptor** templates, size_t* template_count,
    const ad_authored_allocation** allocations, size_t* allocation_count,
    const uint32_t** legacy_schedule, size_t* schedule_count) {
    if (templates != NULL) *templates = ad_templates;
    if (template_count != NULL) {
        *template_count = sizeof ad_templates / sizeof ad_templates[0];
    }
    if (allocations != NULL) *allocations = ad_allocations;
    if (allocation_count != NULL) {
        *allocation_count = sizeof ad_allocations / sizeof ad_allocations[0];
    }
    if (legacy_schedule != NULL) *legacy_schedule = ad_legacy_schedule;
    if (schedule_count != NULL) {
        *schedule_count = sizeof ad_legacy_schedule / sizeof ad_legacy_schedule[0];
    }
}

const ad_authored_allocation* ad_authored_allocation_by_source(
    uint32_t source_id) {
    return find_allocation(ad_allocations,
                           sizeof ad_allocations / sizeof ad_allocations[0],
                           source_id);
}

const ad_authored_allocation* ad_authored_legacy_allocation(size_t index) {
    if (index >= sizeof ad_legacy_schedule / sizeof ad_legacy_schedule[0]) {
        return NULL;
    }
    return ad_authored_allocation_by_source(ad_legacy_schedule[index]);
}

void ad_recipe_apply_projection(ad_recipe* recipe,
                                const ad_recipe_projection* projection) {
    recipe->procgen_seed = projection->procgen_seed;
    recipe->procgen_stream = projection->procgen_stream;
    recipe->game_seed = projection->game_seed;
    recipe->game_stream = projection->game_stream;
    recipe->controller_seed = projection->controller_seed;
    recipe->controller_stream = projection->controller_stream;
    recipe->kind = projection->kind;
    recipe->capture_turn = projection->capture_turn;
    recipe->capture_active_team = projection->capture_active_team;
    recipe->capture_handoff_target_bucket =
        projection->capture_handoff_target_bucket;
    recipe->capture_pass_carrier_pressure =
        projection->capture_pass_carrier_pressure;
    recipe->home_team = projection->home_team;
    recipe->away_team = projection->away_team;
    recipe->exclude_team = projection->exclude_team;
    recipe->procgen.skillup_max_players = projection->skillup_max_players;
    recipe->procgen.skillup_max_each = projection->skillup_max_each;
    recipe->procgen.skillup_secondary_pct =
        bits_float(projection->skillup_secondary_pct_bits);
}

const char* ad_authored_template_key(uint32_t template_id) {
    const ad_authored_template_descriptor* descriptor = find_template(
        ad_templates, sizeof ad_templates / sizeof ad_templates[0], template_id);
    return descriptor == NULL ? NULL : descriptor->key;
}

static int byte_ranges_overlap(const void* left, size_t left_size,
                               const void* right, size_t right_size) {
    uintptr_t left_start = (uintptr_t)left;
    uintptr_t right_start = (uintptr_t)right;
    if (left_start > UINTPTR_MAX - left_size ||
        right_start > UINTPTR_MAX - right_size) {
        return 1;
    }
    uintptr_t left_end = left_start + left_size;
    uintptr_t right_end = right_start + right_size;
    return left_start < right_end && right_start < left_end;
}

static int checked_bundle_extent(size_t supplied_count, size_t element_size,
                                 size_t* bytes) {
    size_t count = supplied_count > AD_AUTHORED_PROOF_BUNDLE_COUNT
        ? supplied_count : AD_AUTHORED_PROOF_BUNDLE_COUNT;
    if (count > SIZE_MAX / element_size) return -1;
    *bytes = count * element_size;
    return 0;
}

int ad_identify_authored_proof_bundle(
    const ad_recipe* recipes, size_t recipe_count,
    ad_authored_identity* identities, size_t identity_capacity,
    char error[AD_ERROR_CAP]) {
    if (error == NULL) return -1;
    size_t recipe_bytes = 0;
    size_t identity_bytes = 0;
    if (checked_bundle_extent(recipe_count, sizeof *recipes, &recipe_bytes) != 0 ||
        checked_bundle_extent(identity_capacity, sizeof *identities,
                              &identity_bytes) != 0) {
        return -1;
    }
    if ((recipes != NULL &&
         byte_ranges_overlap(recipes, recipe_bytes, error, AD_ERROR_CAP)) ||
        (identities != NULL &&
         byte_ranges_overlap(identities, identity_bytes,
                             error, AD_ERROR_CAP)) ||
        (recipes != NULL && identities != NULL &&
         byte_ranges_overlap(recipes, recipe_bytes,
                             identities, identity_bytes))) {
        return -1;
    }
    if (recipes == NULL || identities == NULL) {
        return identity_fail(error, "null authored identity input");
    }
    if (recipe_count != AD_AUTHORED_PROOF_BUNDLE_COUNT ||
        identity_capacity != AD_AUTHORED_PROOF_BUNDLE_COUNT) {
        return identity_fail(error,
                             "authored identity counts %zu/%zu differ from %d",
                             recipe_count, identity_capacity,
                             AD_AUTHORED_PROOF_BUNDLE_COUNT);
    }
    if (ad_validate_authored_registry(
            ad_templates, sizeof ad_templates / sizeof ad_templates[0],
            ad_allocations, sizeof ad_allocations / sizeof ad_allocations[0],
            ad_legacy_schedule,
            sizeof ad_legacy_schedule / sizeof ad_legacy_schedule[0],
            error) != 0 ||
        ad_validate_authored_proof_bundle(recipes, recipe_count, error) != 0) {
        return -1;
    }

    ad_authored_identity staged[AD_AUTHORED_PROOF_BUNDLE_COUNT];
    unsigned char seen[AD_AUTHORED_PROOF_BUNDLE_COUNT] = {0};
    for (size_t i = 0; i < recipe_count; i++) {
        ad_recipe_projection projection;
        ad_recipe_projection_from_recipe(&recipes[i], &projection);
        const ad_authored_allocation* found = NULL;
        size_t found_index = 0;
        for (size_t j = 0;
             j < sizeof ad_allocations / sizeof ad_allocations[0]; j++) {
            if (ad_recipe_projection_equal(
                    &projection, &ad_allocations[j].projection)) {
                if (found != NULL) {
                    return identity_fail(error,
                                         "ambiguous authored recipe %zu", i);
                }
                found = &ad_allocations[j];
                found_index = j;
            }
        }
        if (found == NULL || seen[found_index]) {
            return identity_fail(error,
                                 "unknown or duplicate authored recipe %zu", i);
        }
        seen[found_index] = 1;
        staged[i] = (ad_authored_identity){
            found->variant_seed,
            AD_AUTHORED_IDENTITY_SCHEMA_VERSION,
            found->source_id,
            found->template_id,
            found->recipe_revision,
            found->cell_id,
            found->variant_id,
        };
    }
    for (size_t i = 0; i < sizeof seen; i++) {
        if (!seen[i]) {
            return identity_fail(error,
                                 "missing authored allocation %zu", i);
        }
    }
    memcpy(identities, staged, sizeof staged);
    error[0] = '\0';
    return 0;
}
