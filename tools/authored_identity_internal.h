#ifndef AUTHORED_IDENTITY_INTERNAL_H
#define AUTHORED_IDENTITY_INTERNAL_H

#include "authored_drill.h"

#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint64_t procgen_seed;
    uint64_t procgen_stream;
    uint64_t game_seed;
    uint64_t game_stream;
    uint64_t controller_seed;
    uint64_t controller_stream;
    ad_recipe_kind kind;
    int capture_turn;
    int capture_active_team;
    ad_f2_target_count_bucket capture_handoff_target_bucket;
    ad_f1_carrier_pressure_bucket capture_pass_carrier_pressure;
    int home_team;
    int away_team;
    int exclude_team;
    int skillup_max_players;
    int skillup_max_each;
    uint32_t skillup_secondary_pct_bits;
} ad_recipe_projection;

typedef struct {
    uint32_t template_id;
    char key[AD_AUTHORED_TEMPLATE_KEY_CAP];
    ad_recipe_kind revision_1_kind;
} ad_authored_template_descriptor;

typedef struct {
    uint32_t source_id;
    uint32_t template_id;
    uint32_t recipe_revision;
    uint32_t cell_id;
    uint32_t variant_id;
    uint64_t variant_seed;
    ad_recipe_projection projection;
} ad_authored_allocation;

void ad_recipe_projection_from_recipe(const ad_recipe* recipe,
                                      ad_recipe_projection* projection);
int ad_recipe_projection_equal(const ad_recipe_projection* left,
                               const ad_recipe_projection* right);

int ad_validate_authored_registry(
    const ad_authored_template_descriptor* templates, size_t template_count,
    const ad_authored_allocation* allocations, size_t allocation_count,
    const uint32_t* legacy_schedule, size_t schedule_count,
    char error[AD_ERROR_CAP]);

void ad_authored_registry_view(
    const ad_authored_template_descriptor** templates, size_t* template_count,
    const ad_authored_allocation** allocations, size_t* allocation_count,
    const uint32_t** legacy_schedule, size_t* schedule_count);

const ad_authored_allocation* ad_authored_allocation_by_source(
    uint32_t source_id);
const ad_authored_allocation* ad_authored_legacy_allocation(size_t index);
void ad_recipe_apply_projection(ad_recipe* recipe,
                                const ad_recipe_projection* projection);

// Writer gateways intentionally have external linkage and live in their own
// translation unit so the trusted compatibility harness can interpose on the
// real public writer path.
int ad_authored_fresh_admission_gate(const bb_match* match);
int ad_authored_resumable_admission_gate(const bb_match* match);
int ad_authored_continuation_gate(const bb_match* match,
                                  char error[AD_ERROR_CAP]);

#endif
