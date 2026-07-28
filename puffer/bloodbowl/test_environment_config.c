#define BB_TEST_MAIN
#include "bb_test.h"
#include "bloodbowl.h"

/* environment_config.h consumes the Puffer Dict ABI after bloodbowl.h. */
typedef struct {
    const char* key;
    double value;
    void* ptr;
} DictItem;

typedef struct {
    DictItem* items;
    int size;
    int capacity;
} Dict;

#include "environment_config.h"

typedef struct {
    const char* key;
    bbe_environment_config_domain domain;
} ExpectedEnvironmentDomain;

/*
 * Independent public-contract oracle.  Do not generate this table from
 * BBE_ENVIRONMENT_CONFIG_LEDGER: its purpose is to make a mistaken ledger
 * category fail even when the category's own boundary tests remain green.
 */
static const ExpectedEnvironmentDomain expected_environment_domains[] = {
    {"seed", BBE_ENV_DOMAIN_SEED},
    {"reward_td", BBE_ENV_DOMAIN_REWARD},
    {"reward_win", BBE_ENV_DOMAIN_REWARD},
    {"reward_draw", BBE_ENV_DOMAIN_REWARD},
    {"reward_setup_done", BBE_ENV_DOMAIN_REWARD},
    {"reward_setup_autofix", BBE_ENV_DOMAIN_REWARD},
    {"reward_ball_gain", BBE_ENV_DOMAIN_REWARD},
    {"reward_ball_loss", BBE_ENV_DOMAIN_REWARD},
    {"reward_dist_ball", BBE_ENV_DOMAIN_REWARD},
    {"reward_dist_endzone", BBE_ENV_DOMAIN_REWARD},
    {"reward_dist_pbrs_gamma", BBE_ENV_DOMAIN_GAMMA},
    {"reward_injury_inflicted", BBE_ENV_DOMAIN_REWARD},
    {"reward_injury_taken", BBE_ENV_DOMAIN_REWARD},
    {"reward_injury_value_scaled", BBE_ENV_DOMAIN_BOOL},
    {"reward_send_off", BBE_ENV_DOMAIN_REWARD},
    {"reward_kickoff_touchback", BBE_ENV_DOMAIN_REWARD},
    {"reward_possession", BBE_ENV_DOMAIN_REWARD},
    {"reward_k_assist", BBE_ENV_DOMAIN_REWARD},
    {"reward_rush_cost", BBE_ENV_DOMAIN_REWARD},
    {"reward_carrier_exposure", BBE_ENV_DOMAIN_REWARD},
    {"reward_carrier_exposure_soft", BBE_ENV_DOMAIN_REWARD},
    {"reward_carrier_threat", BBE_ENV_DOMAIN_REWARD},
    {"reward_defensive_threat", BBE_ENV_DOMAIN_REWARD},
    {"reward_defensive_threat_soft", BBE_ENV_DOMAIN_REWARD},
    {"reward_statmatch_scale", BBE_ENV_DOMAIN_STATMATCH},
    {"demo_endzone_maxdist", BBE_ENV_DOMAIN_BANK_ENDZONE_SELECTOR},
    {"demo_pickup_maxdist", BBE_ENV_DOMAIN_BANK_PICKUP_SELECTOR},
    {"demo_postkick_maxturn", BBE_ENV_DOMAIN_BANK_POSTKICK_SELECTOR},
    {"demo_pass_maxrange", BBE_ENV_DOMAIN_BANK_PASS_SELECTOR},
    {"skillup_max_players", BBE_ENV_DOMAIN_SKILL_PLAYERS},
    {"skillup_max_each", BBE_ENV_DOMAIN_SKILL_EACH},
    {"skillup_secondary_pct", BBE_ENV_DOMAIN_UNIT_INTERVAL},
    {"macro_moves", BBE_ENV_DOMAIN_BOOL},
    {"reward_surf_taken", BBE_ENV_DOMAIN_REWARD},
    {"reward_surf_inflicted", BBE_ENV_DOMAIN_REWARD},
    {"reward_k_kd", BBE_ENV_DOMAIN_REWARD},
    {"reward_k_value", BBE_ENV_DOMAIN_REWARD},
    {"reward_k_self_injury", BBE_ENV_DOMAIN_REWARD},
    {"reward_k_ball", BBE_ENV_DOMAIN_REWARD},
    {"reward_k_seq", BBE_ENV_DOMAIN_REWARD},
    {"reward_k_turnover", BBE_ENV_DOMAIN_REWARD},
    {"demo_reset_pct", BBE_ENV_DOMAIN_BANK_RESET},
    {"state_bank_kind", BBE_ENV_DOMAIN_BANK_KIND},
    {"exclude_team", BBE_ENV_DOMAIN_BANK_TEAM},
    {"force_home_team", BBE_ENV_DOMAIN_BANK_TEAM},
    {"force_away_team", BBE_ENV_DOMAIN_BANK_TEAM},
    {"scripted_opponent", BBE_ENV_DOMAIN_BOOL},
    {"scripted_opponent_type", BBE_ENV_DOMAIN_SCRIPT_TYPE},
    {"scripted_opponent_team", BBE_ENV_DOMAIN_SCRIPT_TEAM},
    {"max_decisions", BBE_ENV_DOMAIN_MAX_DECISIONS},
    {"render_fps", BBE_ENV_DOMAIN_RENDER_FPS},
};

_Static_assert(
    sizeof expected_environment_domains /
            sizeof expected_environment_domains[0] ==
        BBE_ENVIRONMENT_CONFIG_KEY_COUNT,
    "independent environment-domain oracle must cover all 51 keys");

static int config_set_raw(
        bbe_environment_config* config, const char* key, double value) {
    int matched = 0;
#define BBE_TEST_SET_ROW(key_token, raw, default_value, domain, destination) \
    if (!matched && strcmp(key, #key_token) == 0) {                         \
        config->raw = value;                                                 \
        matched = 1;                                                         \
    }
    BBE_ENVIRONMENT_CONFIG_LEDGER(BBE_TEST_SET_ROW)
#undef BBE_TEST_SET_ROW
    return matched;
}

static double descriptor_valid_min(bbe_environment_config_domain domain) {
    switch (domain) {
    case BBE_ENV_DOMAIN_SEED:
    case BBE_ENV_DOMAIN_REWARD:
    case BBE_ENV_DOMAIN_GAMMA:
    case BBE_ENV_DOMAIN_STATMATCH:
    case BBE_ENV_DOMAIN_BOOL:
    case BBE_ENV_DOMAIN_BANK_RESET:
    case BBE_ENV_DOMAIN_BANK_KIND:
    case BBE_ENV_DOMAIN_BANK_ENDZONE_SELECTOR:
    case BBE_ENV_DOMAIN_BANK_PICKUP_SELECTOR:
    case BBE_ENV_DOMAIN_BANK_POSTKICK_SELECTOR:
    case BBE_ENV_DOMAIN_BANK_PASS_SELECTOR:
    case BBE_ENV_DOMAIN_SKILL_PLAYERS:
    case BBE_ENV_DOMAIN_SKILL_EACH:
    case BBE_ENV_DOMAIN_UNIT_INTERVAL:
    case BBE_ENV_DOMAIN_SCRIPT_TEAM:
    case BBE_ENV_DOMAIN_SCRIPT_TYPE:
        return domain == BBE_ENV_DOMAIN_REWARD ? -1.0 : 0.0;
    case BBE_ENV_DOMAIN_BANK_TEAM:
        return -1.0;
    case BBE_ENV_DOMAIN_MAX_DECISIONS:
    case BBE_ENV_DOMAIN_RENDER_FPS:
        return 1.0;
    }
    return 0.0;
}

static double descriptor_valid_max(bbe_environment_config_domain domain) {
    switch (domain) {
    case BBE_ENV_DOMAIN_SEED:
        return BBE_ENVIRONMENT_CONFIG_EXACT_DOUBLE_INTEGER_MAX;
    case BBE_ENV_DOMAIN_REWARD:
    case BBE_ENV_DOMAIN_GAMMA:
    case BBE_ENV_DOMAIN_STATMATCH:
    case BBE_ENV_DOMAIN_BOOL:
    case BBE_ENV_DOMAIN_BANK_RESET:
    case BBE_ENV_DOMAIN_UNIT_INTERVAL:
    case BBE_ENV_DOMAIN_SCRIPT_TYPE:
        return 1.0;
    case BBE_ENV_DOMAIN_BANK_KIND:
    case BBE_ENV_DOMAIN_SCRIPT_TEAM:
        return 2.0;
    case BBE_ENV_DOMAIN_BANK_ENDZONE_SELECTOR:
    case BBE_ENV_DOMAIN_BANK_PICKUP_SELECTOR:
    case BBE_ENV_DOMAIN_BANK_PASS_SELECTOR:
        return BBE_STATE_BANK_MAX_DISTANCE;
    case BBE_ENV_DOMAIN_BANK_POSTKICK_SELECTOR:
        return BBE_STATE_BANK_MAX_TURN;
    case BBE_ENV_DOMAIN_BANK_TEAM:
        return BB_TEAM_COUNT - 1;
    case BBE_ENV_DOMAIN_SKILL_PLAYERS:
        return BB_TEAM_SLOTS;
    case BBE_ENV_DOMAIN_SKILL_EACH:
        return 12.0;
    case BBE_ENV_DOMAIN_MAX_DECISIONS:
        return BBE_MAX_DECISIONS;
    case BBE_ENV_DOMAIN_RENDER_FPS:
        return INT_MAX;
    }
    return 0.0;
}

static double descriptor_invalid_low(bbe_environment_config_domain domain) {
    switch (domain) {
    case BBE_ENV_DOMAIN_REWARD:
        return nextafter(-1.0, -INFINITY);
    case BBE_ENV_DOMAIN_BANK_TEAM:
        return -2.0;
    case BBE_ENV_DOMAIN_MAX_DECISIONS:
    case BBE_ENV_DOMAIN_RENDER_FPS:
        return 0.0;
    default:
        return -1.0;
    }
}

static double descriptor_invalid_high(bbe_environment_config_domain domain) {
    return nextafter(descriptor_valid_max(domain), INFINITY);
}

static int descriptor_is_float_backed(
        bbe_environment_config_domain domain) {
    return domain == BBE_ENV_DOMAIN_REWARD ||
           domain == BBE_ENV_DOMAIN_GAMMA ||
           domain == BBE_ENV_DOMAIN_STATMATCH ||
           domain == BBE_ENV_DOMAIN_BANK_RESET ||
           domain == BBE_ENV_DOMAIN_UNIT_INTERVAL;
}

static int descriptor_is_integer_backed(
        bbe_environment_config_domain domain) {
    return !descriptor_is_float_backed(domain);
}

typedef struct {
    Bloodbowl env;
    uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    float actions[BBE_AGENTS * 3];
    unsigned char masks[BBE_AGENTS * BBE_MASK_SIZE];
    float rewards[BBE_AGENTS];
    float terminals[BBE_AGENTS];
} EnvironmentConfigFixture;

static void construct_and_reset(
        const bbe_environment_config* config, uint64_t seed,
        EnvironmentConfigFixture* fixture) {
    memset(fixture, 0, sizeof *fixture);
    bbe_environment_config_result result;
    BB_CHECK(bbe_environment_config_validate_and_apply(
        config, BBE_STATE_BANK_STRICT_REPLAY, &fixture->env, &result));
    fixture->env.seed = seed;
    fixture->env.num_agents = BBE_AGENTS;
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        fixture->env.obs_ptr[agent] =
            fixture->obs + agent * BBE_OBS_SIZE;
        fixture->env.action_ptr[agent] = fixture->actions + agent * 3;
        fixture->env.action_mask_ptr[agent] =
            fixture->masks + agent * BBE_MASK_SIZE;
        fixture->env.reward_ptr[agent] = fixture->rewards + agent;
        fixture->env.terminal_ptr[agent] = fixture->terminals + agent;
    }
    c_reset(&fixture->env);
    BB_CHECK(fixture->env.match.status == BB_STATUS_DECISION);
    BB_CHECK(fixture->env.n_legal > 0);
}

static void select_first_legal_action(EnvironmentConfigFixture* fixture) {
    BB_CHECK(fixture->env.match.status == BB_STATUS_DECISION);
    BB_CHECK(fixture->env.n_legal > 0);
    int team = fixture->env.match.decision_team;
    BB_CHECK(team == BB_HOME || team == BB_AWAY);
    fixture->actions[team * 3] =
        (float)fixture->env.legal[0].type;
    fixture->actions[team * 3 + 1] =
        (float)fixture->env.legal_arg[0];
    fixture->actions[team * 3 + 2] =
        (float)fixture->env.legal_sq[0];
}

typedef struct {
    int c_steps;
    int engine_decisions;
    float score_diff;
    float touchdowns;
} EnvironmentConfigEpisodeResult;

static EnvironmentConfigEpisodeResult complete_scripted_episode(
        EnvironmentConfigFixture* fixture) {
    enum { NATURAL_COMPLETION_DECISION_CAP = 200000 };
    EnvironmentConfigEpisodeResult result = {0};
    /*
     * The production contract deliberately caps an episode at 4096 engine
     * decisions. Raise only this test fixture's post-validation safety budget
     * so a terminal proves natural match completion rather than truncation.
     */
    fixture->env.max_decisions = NATURAL_COMPLETION_DECISION_CAP;
    while (fixture->terminals[0] == 0.0f &&
           result.c_steps < NATURAL_COMPLETION_DECISION_CAP) {
        c_step(&fixture->env);
        result.c_steps++;
    }
    result.engine_decisions = (int)fixture->env.log.episode_length;
    result.score_diff = fixture->env.log.score_diff;
    result.touchdowns = fixture->env.log.tds;
    BB_CHECK(fixture->terminals[0] != 0.0f);
    BB_CHECK_EQ((int)fixture->env.log.n, 1);
    BB_CHECK_EQ((int)fixture->env.log.error_episodes, 0);
    BB_CHECK(result.engine_decisions < NATURAL_COMPLETION_DECISION_CAP);
    BB_CHECK(result.c_steps < NATURAL_COMPLETION_DECISION_CAP);
    return result;
}

BB_TEST(environment_config_schema_has_51_unique_complete_rows) {
    BB_CHECK_EQ(BBE_ENVIRONMENT_CONFIG_KEY_COUNT, 51);
    BB_CHECK_EQ(sizeof bbe_environment_config_descriptors /
                    sizeof bbe_environment_config_descriptors[0],
                51);
    for (int i = 0; i < BBE_ENVIRONMENT_CONFIG_KEY_COUNT; i++) {
        const bbe_environment_config_descriptor* descriptor =
            &bbe_environment_config_descriptors[i];
        int expected_domain_matches = 0;
        BB_CHECK(descriptor->key != NULL && descriptor->key[0] != '\0');
        BB_CHECK(descriptor->raw_field != NULL &&
                 descriptor->raw_field[0] != '\0');
        BB_CHECK(descriptor->destination != NULL &&
                 descriptor->destination[0] != '\0');
        BB_CHECK(strcmp(descriptor->destination, descriptor->key) == 0);
        BB_CHECK(bbe_environment_config_domain_name(descriptor->domain) != NULL);
        for (int prior = 0; prior < i; prior++) {
            BB_CHECK(strcmp(
                         descriptor->key,
                         bbe_environment_config_descriptors[prior].key) != 0);
            BB_CHECK(strcmp(
                         descriptor->raw_field,
                         bbe_environment_config_descriptors[prior].raw_field) !=
                     0);
        }
        for (int expected = 0;
             expected < BBE_ENVIRONMENT_CONFIG_KEY_COUNT; expected++) {
            if (strcmp(
                    descriptor->key,
                    expected_environment_domains[expected].key) != 0) {
                continue;
            }
            BB_CHECK(
                descriptor->domain ==
                expected_environment_domains[expected].domain);
            expected_domain_matches++;
        }
        BB_CHECK_EQ(expected_domain_matches, 1);
    }
    for (int expected = 0;
         expected < BBE_ENVIRONMENT_CONFIG_KEY_COUNT; expected++) {
        for (int prior = 0; prior < expected; prior++) {
            BB_CHECK(strcmp(
                         expected_environment_domains[expected].key,
                         expected_environment_domains[prior].key) != 0);
        }
    }

    const char* const bank_keys[] = {
        "demo_reset_pct",
        "state_bank_kind",
        "demo_endzone_maxdist",
        "demo_pickup_maxdist",
        "demo_postkick_maxturn",
        "demo_pass_maxrange",
        "exclude_team",
        "force_home_team",
        "force_away_team",
    };
    const char* const bank_raw_fields[] = {
        "state_bank.reset_pct",
        "state_bank.kind",
        "state_bank.endzone_selector",
        "state_bank.pickup_selector",
        "state_bank.postkick_selector",
        "state_bank.pass_selector",
        "state_bank.exclude_team",
        "state_bank.force_home_team",
        "state_bank.force_away_team",
    };
    for (size_t expected = 0;
         expected < sizeof bank_keys / sizeof bank_keys[0]; expected++) {
        int matches = 0;
        for (int i = 0; i < BBE_ENVIRONMENT_CONFIG_KEY_COUNT; i++) {
            const bbe_environment_config_descriptor* descriptor =
                &bbe_environment_config_descriptors[i];
            if (strcmp(descriptor->key, bank_keys[expected]) != 0) continue;
            BB_CHECK(strcmp(
                         descriptor->raw_field,
                         bank_raw_fields[expected]) == 0);
            matches++;
        }
        BB_CHECK_EQ(matches, 1);
    }
}

BB_TEST(environment_config_empty_dict_applies_historical_defaults) {
    Dict dict = {0};
    bbe_environment_config raw;
    Bloodbowl applied;
    bbe_environment_config_result result;
    BB_CHECK(bbe_environment_config_parse_dict(
        &dict, BBE_STATE_BANK_STRICT_REPLAY, &raw, &applied, &result));
    BB_CHECK(applied.seed == UINT64_C(1));
    BB_CHECK(applied.reward_td == BBE_DEFAULT_REWARD_TD);
    BB_CHECK(applied.reward_win == BBE_DEFAULT_REWARD_WIN);
    BB_CHECK(applied.reward_draw == BBE_DEFAULT_REWARD_DRAW);
    BB_CHECK_EQ(applied.skillup_max_players, 4);
    BB_CHECK_EQ(applied.skillup_max_each, 2);
    BB_CHECK_EQ(applied.scripted_opponent_team, 1);
    BB_CHECK_EQ(applied.max_decisions, BBE_MAX_DECISIONS);
    BB_CHECK_EQ(applied.render_fps, 60);
    BB_CHECK_EQ(applied.exclude_team, -1);
    BB_CHECK_EQ(applied.force_home_team, -1);
    BB_CHECK_EQ(applied.force_away_team, -1);
    BB_CHECK_EQ(applied.reach_mover, -1);
    BB_CHECK_EQ(applied.macro_mover, -1);
}

BB_TEST(environment_config_exact_sparse_qualification_dict_is_valid) {
    DictItem items[] = {
        {.key = "seed", .value = 42.0},
        {.key = "max_decisions", .value = 1.0},
    };
    Dict dict = {.items = items, .size = 2, .capacity = 2};
    Bloodbowl applied;
    bbe_environment_config_result result;
    BB_CHECK(bbe_environment_config_parse_dict(
        &dict, BBE_STATE_BANK_STRICT_REPLAY, NULL, &applied, &result));
    BB_CHECK(applied.seed == UINT64_C(42));
    BB_CHECK_EQ(applied.max_decisions, 1);
    BB_CHECK(applied.reward_td == BBE_DEFAULT_REWARD_TD);
    BB_CHECK_EQ(applied.scripted_opponent_team, 1);
}

BB_TEST(environment_config_exact_full_default_dictionary_is_valid) {
    DictItem items[BBE_ENVIRONMENT_CONFIG_KEY_COUNT] = {{0}};
    for (int i = 0; i < BBE_ENVIRONMENT_CONFIG_KEY_COUNT; i++) {
        items[i].key = bbe_environment_config_descriptors[i].key;
        items[i].value = bbe_environment_config_descriptors[i].default_value;
    }
    Dict dict = {
        .items = items,
        .size = BBE_ENVIRONMENT_CONFIG_KEY_COUNT,
        .capacity = BBE_ENVIRONMENT_CONFIG_KEY_COUNT,
    };
    bbe_environment_config_result result;
    BB_CHECK(bbe_environment_config_parse_dict(
        &dict, BBE_STATE_BANK_STRICT_REPLAY, NULL, NULL, &result));
}

BB_TEST(environment_config_rejects_cardinality_before_item_access) {
    Dict dict = {.items = NULL, .size = 52, .capacity = 52};
    bbe_environment_config_result result;
    BB_CHECK(!bbe_environment_config_parse_dict(
        &dict, BBE_STATE_BANK_STRICT_REPLAY, NULL, NULL, &result));
    BB_CHECK_EQ(result.error, BBE_ENV_CONFIG_CARDINALITY);
    BB_CHECK(strcmp(result.field, "environment dictionary") == 0);
}

BB_TEST(environment_config_structural_null_key_precedes_all_key_access) {
    DictItem items[] = {
        {.key = "seed", .value = 1.0},
        {.key = NULL, .value = 2.0},
    };
    Dict dict = {.items = items, .size = 2, .capacity = 2};
    bbe_environment_config_result result;
    BB_CHECK(!bbe_environment_config_parse_dict(
        &dict, BBE_STATE_BANK_STRICT_REPLAY, NULL, NULL, &result));
    BB_CHECK_EQ(result.error, BBE_ENV_CONFIG_NULL_KEY);
}

BB_TEST(environment_config_rejects_duplicate_unknown_and_malformed_keys) {
    bbe_environment_config_result result;
    DictItem duplicate_items[] = {
        {.key = "seed", .value = 1.0},
        {.key = "seed", .value = 2.0},
    };
    Dict duplicate = {
        .items = duplicate_items, .size = 2, .capacity = 2};
    BB_CHECK(!bbe_environment_config_parse_dict(
        &duplicate, BBE_STATE_BANK_STRICT_REPLAY, NULL, NULL, &result));
    BB_CHECK_EQ(result.error, BBE_ENV_CONFIG_DUPLICATE_KEY);
    BB_CHECK(strcmp(result.field, "seed") == 0);

    DictItem unknown_item = {.key = "reward_touchdwon", .value = 0.4};
    Dict unknown = {.items = &unknown_item, .size = 1, .capacity = 1};
    BB_CHECK(!bbe_environment_config_parse_dict(
        &unknown, BBE_STATE_BANK_STRICT_REPLAY, NULL, NULL, &result));
    BB_CHECK_EQ(result.error, BBE_ENV_CONFIG_UNKNOWN_KEY);
    BB_CHECK(strcmp(result.field, "reward_touchdwon") == 0);

    DictItem malformed_item = {.key = "reward-TD", .value = 0.4};
    Dict malformed = {.items = &malformed_item, .size = 1, .capacity = 1};
    BB_CHECK(!bbe_environment_config_parse_dict(
        &malformed, BBE_STATE_BANK_STRICT_REPLAY, NULL, NULL, &result));
    BB_CHECK_EQ(result.error, BBE_ENV_CONFIG_MALFORMED_KEY);
}

BB_TEST(environment_config_each_field_uses_its_declared_closed_domain) {
    for (int i = 0; i < BBE_ENVIRONMENT_CONFIG_KEY_COUNT; i++) {
        const bbe_environment_config_descriptor* descriptor =
            &bbe_environment_config_descriptors[i];
        bbe_environment_config config;
        bbe_environment_config_result result;

        bbe_environment_config_defaults(&config);
        BB_CHECK(config_set_raw(
            &config, descriptor->key,
            descriptor_valid_min(descriptor->domain)));
        BB_CHECK(bbe_environment_config_validate_raw(&config, &result));

        bbe_environment_config_defaults(&config);
        BB_CHECK(config_set_raw(
            &config, descriptor->key,
            descriptor_valid_max(descriptor->domain)));
        BB_CHECK(bbe_environment_config_validate_raw(&config, &result));

        bbe_environment_config_defaults(&config);
        BB_CHECK(config_set_raw(
            &config, descriptor->key,
            descriptor_invalid_low(descriptor->domain)));
        BB_CHECK(!bbe_environment_config_validate_raw(&config, &result));
        BB_CHECK(strcmp(result.field, descriptor->key) == 0);

        bbe_environment_config_defaults(&config);
        BB_CHECK(config_set_raw(
            &config, descriptor->key,
            descriptor_invalid_high(descriptor->domain)));
        BB_CHECK(!bbe_environment_config_validate_raw(&config, &result));
        BB_CHECK(strcmp(result.field, descriptor->key) == 0);

        const double nonfinite[] = {NAN, INFINITY, -INFINITY};
        for (size_t n = 0; n < sizeof nonfinite / sizeof nonfinite[0]; n++) {
            bbe_environment_config_defaults(&config);
            BB_CHECK(config_set_raw(
                &config, descriptor->key, nonfinite[n]));
            BB_CHECK(!bbe_environment_config_validate_raw(&config, &result));
            BB_CHECK(strcmp(result.field, descriptor->key) == 0);
        }
    }
}

BB_TEST(environment_config_integer_fields_reject_fractions) {
    const char* fields[] = {
        "seed",
        "reward_injury_value_scaled",
        "demo_endzone_maxdist",
        "demo_pickup_maxdist",
        "demo_postkick_maxturn",
        "demo_pass_maxrange",
        "skillup_max_players",
        "skillup_max_each",
        "macro_moves",
        "state_bank_kind",
        "exclude_team",
        "force_home_team",
        "force_away_team",
        "scripted_opponent",
        "scripted_opponent_type",
        "scripted_opponent_team",
        "max_decisions",
        "render_fps",
    };
    for (size_t i = 0; i < sizeof fields / sizeof fields[0]; i++) {
        bbe_environment_config config;
        bbe_environment_config_result result;
        bbe_environment_config_defaults(&config);
        BB_CHECK(config_set_raw(&config, fields[i], 0.5));
        BB_CHECK(!bbe_environment_config_validate_raw(&config, &result));
        BB_CHECK(strcmp(result.field, fields[i]) == 0);
    }
}

BB_TEST(environment_config_float_enablement_rejects_underflow_to_zero) {
    int checked = 0;
    for (int i = 0; i < BBE_ENVIRONMENT_CONFIG_KEY_COUNT; i++) {
        const bbe_environment_config_descriptor* descriptor =
            &bbe_environment_config_descriptors[i];
        if (!descriptor_is_float_backed(descriptor->domain)) continue;
        bbe_environment_config config;
        bbe_environment_config_result result;
        bbe_environment_config_defaults(&config);
        BB_CHECK(config_set_raw(&config, descriptor->key, 0x1p-1074));
        BB_CHECK(!bbe_environment_config_validate_raw(&config, &result));
        BB_CHECK(strcmp(result.field, descriptor->key) == 0);
        checked++;
    }
    /* 29 ordinary rewards + gamma + statmatch + reset + skill probability. */
    BB_CHECK_EQ(checked, 33);
}

BB_TEST(environment_config_integer_domains_reject_fraction_and_double_extremes) {
    const double invalid[] = {-0.5, 0.5, -DBL_MAX, DBL_MAX};
    int checked = 0;
    for (int i = 0; i < BBE_ENVIRONMENT_CONFIG_KEY_COUNT; i++) {
        const bbe_environment_config_descriptor* descriptor =
            &bbe_environment_config_descriptors[i];
        if (!descriptor_is_integer_backed(descriptor->domain)) continue;
        for (size_t j = 0; j < sizeof invalid / sizeof invalid[0]; j++) {
            bbe_environment_config config;
            bbe_environment_config_result result;
            bbe_environment_config_defaults(&config);
            BB_CHECK(config_set_raw(
                &config, descriptor->key, invalid[j]));
            BB_CHECK(!bbe_environment_config_validate_raw(&config, &result));
            BB_CHECK(strcmp(result.field, descriptor->key) == 0);
        }
        checked++;
    }
    BB_CHECK_EQ(checked, 18);
}

BB_TEST(environment_config_float_domains_cover_underflow_extremes_and_signs) {
    int checked = 0;
    for (int i = 0; i < BBE_ENVIRONMENT_CONFIG_KEY_COUNT; i++) {
        const bbe_environment_config_descriptor* descriptor =
            &bbe_environment_config_descriptors[i];
        if (!descriptor_is_float_backed(descriptor->domain)) continue;

        const double always_invalid[] = {
            0x1p-1074, -0x1p-1074, DBL_MAX, -DBL_MAX, NAN, INFINITY,
            -INFINITY,
        };
        for (size_t j = 0;
             j < sizeof always_invalid / sizeof always_invalid[0]; j++) {
            bbe_environment_config config;
            bbe_environment_config_result result;
            bbe_environment_config_defaults(&config);
            BB_CHECK(config_set_raw(
                &config, descriptor->key, always_invalid[j]));
            BB_CHECK(!bbe_environment_config_validate_raw(&config, &result));
            BB_CHECK(strcmp(result.field, descriptor->key) == 0);
        }

        bbe_environment_config config;
        bbe_environment_config_result result;
        bbe_environment_config_defaults(&config);
        BB_CHECK(config_set_raw(&config, descriptor->key, 0.5));
        BB_CHECK(bbe_environment_config_validate_raw(&config, &result));

        bbe_environment_config_defaults(&config);
        BB_CHECK(config_set_raw(&config, descriptor->key, -0.5));
        if (descriptor->domain == BBE_ENV_DOMAIN_REWARD) {
            BB_CHECK(bbe_environment_config_validate_raw(&config, &result));
        } else {
            BB_CHECK(!bbe_environment_config_validate_raw(&config, &result));
            BB_CHECK(strcmp(result.field, descriptor->key) == 0);
        }
        checked++;
    }
    BB_CHECK_EQ(checked, 33);
}

BB_TEST(environment_config_procgen_teams_validate_when_bank_is_inactive) {
    const char* fields[] = {
        "exclude_team", "force_home_team", "force_away_team"};
    const double invalid[] = {
        -2.0, (double)BB_TEAM_COUNT, 0.5, NAN, INFINITY};
    for (size_t i = 0; i < sizeof fields / sizeof fields[0]; i++) {
        for (size_t j = 0; j < sizeof invalid / sizeof invalid[0]; j++) {
            bbe_environment_config config;
            bbe_environment_config_result result;
            bbe_environment_config_defaults(&config);
            BB_CHECK(config_set_raw(&config, fields[i], invalid[j]));
            BB_CHECK(!bbe_environment_config_validate_and_apply(
                &config, BBE_STATE_BANK_STRICT_REPLAY, NULL, &result));
            BB_CHECK(strcmp(result.field, fields[i]) == 0);
        }
    }
}

BB_TEST(environment_config_scripted_both_is_preserved_without_clamp) {
    bbe_environment_config config;
    Bloodbowl applied;
    bbe_environment_config_result result;
    bbe_environment_config_defaults(&config);
    config.scripted_opponent = 1.0;
    config.scripted_opponent_team = 2.0;
    config.scripted_opponent_type = 1.0;
    BB_CHECK(bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_STRICT_REPLAY, &applied, &result));
    BB_CHECK_EQ(applied.scripted_opponent, 1);
    BB_CHECK_EQ(applied.scripted_opponent_team, 2);
    BB_CHECK_EQ(applied.scripted_opponent_type, 1);
}

BB_TEST(environment_config_team_and_procgen_boundaries_construct) {
    bbe_environment_config config;
    EnvironmentConfigFixture fixture;

    _Static_assert(
        BB_TEAM_COUNT >= 3,
        "team-selection matrix needs two forced IDs and one excluded ID");
    const int forced_team[BBE_AGENTS] = {0, 1};
    const int excluded_team = BB_TEAM_COUNT - 1;
    /*
     * Exercise every sentinel/concrete combination:
     * bit 0 = exclusion active, bit 1 = home forced, bit 2 = away forced.
     * Distinct concrete IDs make the exclusion assertion meaningful even when
     * either or both sides are forced.
     */
    for (int combination = 0; combination < 8; combination++) {
        bbe_environment_config_defaults(&config);
        if (combination & 1) {
            config.state_bank.exclude_team = (double)excluded_team;
        }
        if (combination & 2) {
            config.state_bank.force_home_team =
                (double)forced_team[BB_HOME];
        }
        if (combination & 4) {
            config.state_bank.force_away_team =
                (double)forced_team[BB_AWAY];
        }
        construct_and_reset(
            &config, UINT64_C(1001) + (uint64_t)combination, &fixture);

        for (int side = 0; side < BBE_AGENTS; side++) {
            int actual = fixture.env.match.team_id[side];
            int force_bit = side == BB_HOME ? 2 : 4;
            BB_CHECK(actual >= 0);
            BB_CHECK(actual < BB_TEAM_COUNT);
            if (combination & force_bit) {
                BB_CHECK_EQ(actual, forced_team[side]);
            }
            if (combination & 1) {
                BB_CHECK(actual != excluded_team);
            }
        }
    }

    bbe_environment_config_defaults(&config);
    config.skillup_max_players = 0.0;
    config.skillup_max_each = 0.0;
    config.skillup_secondary_pct = 0.0;
    config.scripted_opponent = 1.0;
    config.scripted_opponent_team = 2.0;
    config.scripted_opponent_type = 1.0;
    construct_and_reset(&config, UINT64_C(2001), &fixture);
    EnvironmentConfigEpisodeResult minimum_first =
        complete_scripted_episode(&fixture);
    construct_and_reset(&config, UINT64_C(2001), &fixture);
    EnvironmentConfigEpisodeResult minimum_second =
        complete_scripted_episode(&fixture);
    BB_CHECK_EQ(minimum_first.c_steps, minimum_second.c_steps);
    BB_CHECK_EQ(
        minimum_first.engine_decisions, minimum_second.engine_decisions);
    BB_CHECK(minimum_first.score_diff == minimum_second.score_diff);
    BB_CHECK(minimum_first.touchdowns == minimum_second.touchdowns);

    bbe_environment_config_defaults(&config);
    config.skillup_max_players = (double)BB_TEAM_SLOTS;
    config.skillup_max_each = 12.0;
    config.skillup_secondary_pct = 1.0;
    config.scripted_opponent = 1.0;
    config.scripted_opponent_team = 2.0;
    config.scripted_opponent_type = 1.0;
    construct_and_reset(&config, UINT64_C(2002), &fixture);
    EnvironmentConfigEpisodeResult maximum_first =
        complete_scripted_episode(&fixture);
    construct_and_reset(&config, UINT64_C(2002), &fixture);
    EnvironmentConfigEpisodeResult maximum_second =
        complete_scripted_episode(&fixture);
    BB_CHECK_EQ(maximum_first.c_steps, maximum_second.c_steps);
    BB_CHECK_EQ(
        maximum_first.engine_decisions, maximum_second.engine_decisions);
    BB_CHECK(maximum_first.score_diff == maximum_second.score_diff);
    BB_CHECK(maximum_first.touchdowns == maximum_second.touchdowns);
}

BB_TEST(environment_config_seed_budget_and_render_boundaries_retain_exactly) {
    bbe_environment_config config;
    Bloodbowl applied;
    bbe_environment_config_result result;
    bbe_environment_config_defaults(&config);
    config.seed = BBE_ENVIRONMENT_CONFIG_EXACT_DOUBLE_INTEGER_MAX;
    config.max_decisions = (double)BBE_MAX_DECISIONS;
    config.render_fps = (double)INT_MAX;
    BB_CHECK(bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_STRICT_REPLAY, &applied, &result));
    BB_CHECK(applied.seed == UINT64_C(9007199254740991));
    BB_CHECK_EQ(applied.max_decisions, BBE_MAX_DECISIONS);
    BB_CHECK_EQ(applied.render_fps, INT_MAX);

    config.seed = 0.0;
    config.max_decisions = 1.0;
    config.render_fps = 1.0;
    BB_CHECK(bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_STRICT_REPLAY, &applied, &result));
    BB_CHECK(applied.seed == UINT64_C(0));
    BB_CHECK_EQ(applied.max_decisions, 1);
    BB_CHECK_EQ(applied.render_fps, 1);
}

BB_TEST(environment_config_one_decision_budget_terminates_after_one_action) {
    bbe_environment_config config;
    EnvironmentConfigFixture fixture;
    bbe_environment_config_defaults(&config);
    config.max_decisions = 1.0;
    construct_and_reset(&config, UINT64_C(424242), &fixture);
    select_first_legal_action(&fixture);
    c_step(&fixture.env);
    BB_CHECK(fixture.terminals[BB_HOME] == 1.0f);
    BB_CHECK(fixture.terminals[BB_AWAY] == 1.0f);
    BB_CHECK(fixture.env.log.episode_length == 1.0f);
    BB_CHECK(fixture.env.log.n == 1.0f);
}

BB_TEST(environment_config_seed_boundaries_repeat_exact_trajectories) {
    const uint64_t seeds[] = {
        UINT64_C(0),
        UINT64_C(1),
        UINT64_C(9007199254740991),
    };
    for (size_t seed_index = 0;
         seed_index < sizeof seeds / sizeof seeds[0]; seed_index++) {
        bbe_environment_config config;
        EnvironmentConfigFixture first;
        EnvironmentConfigFixture second;
        bbe_environment_config_defaults(&config);
        config.seed = (double)seeds[seed_index];
        construct_and_reset(&config, seeds[seed_index], &first);
        construct_and_reset(&config, seeds[seed_index], &second);
        for (int step = 0; step < 64; step++) {
            BB_CHECK_EQ(first.env.n_legal, second.env.n_legal);
            BB_CHECK_EQ(
                first.env.match.decision_team,
                second.env.match.decision_team);
            BB_CHECK(memcmp(
                         &first.env.match, &second.env.match,
                         sizeof first.env.match) == 0);
            BB_CHECK(memcmp(
                         first.env.legal, second.env.legal,
                         (size_t)first.env.n_legal *
                             sizeof first.env.legal[0]) == 0);
            BB_CHECK(memcmp(
                         first.env.legal_arg, second.env.legal_arg,
                         (size_t)first.env.n_legal) == 0);
            BB_CHECK(memcmp(
                         first.env.legal_sq, second.env.legal_sq,
                         (size_t)first.env.n_legal *
                             sizeof first.env.legal_sq[0]) == 0);
            select_first_legal_action(&first);
            select_first_legal_action(&second);
            c_step(&first.env);
            c_step(&second.env);
            BB_CHECK(memcmp(
                         first.rewards, second.rewards,
                         sizeof first.rewards) == 0);
            BB_CHECK(memcmp(
                         first.terminals, second.terminals,
                         sizeof first.terminals) == 0);
        }
    }
}

BB_TEST(environment_config_vector_seeds_are_distinct_and_deterministic) {
    Bloodbowl applied = {.seed = UINT64_C(42)};
    BB_CHECK(
        bbe_environment_config_vector_seed(&applied, 0) == UINT64_C(42));
    BB_CHECK(
        bbe_environment_config_vector_seed(&applied, 1) == UINT64_C(43));
    BB_CHECK(
        bbe_environment_config_vector_seed(&applied, 2047) ==
        UINT64_C(2089));
}

BB_TEST(environment_config_invalid_input_does_not_mutate_applied_output) {
    bbe_environment_config config;
    Bloodbowl output = {0};
    bbe_environment_config_result result;
    output.scripted_opponent_team = 77;
    output.max_decisions = 99;
    output.reward_td = 0.125f;
    bbe_environment_config_defaults(&config);
    config.scripted_opponent_team = 3.0;
    BB_CHECK(!bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_STRICT_REPLAY, &output, &result));
    BB_CHECK_EQ(output.scripted_opponent_team, 77);
    BB_CHECK_EQ(output.max_decisions, 99);
    BB_CHECK(output.reward_td == 0.125f);
}

BB_TEST(environment_config_retains_reward_and_bank_cross_field_rules) {
    bbe_environment_config config;
    bbe_environment_config_result result;
    bbe_environment_config_defaults(&config);
    config.reward_carrier_threat = 0.1;
    config.reward_carrier_exposure = 0.1;
    BB_CHECK(!bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_STRICT_REPLAY, NULL, &result));
    BB_CHECK(strcmp(result.field, "reward_carrier_threat") == 0);

    bbe_environment_config_defaults(&config);
    config.reward_carrier_threat = 0.1;
    config.reward_k_assist = 0.1;
    BB_CHECK(!bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_STRICT_REPLAY, NULL, &result));
    BB_CHECK(strcmp(result.field, "reward_carrier_threat") == 0);

    bbe_environment_config_defaults(&config);
    config.reward_dist_pbrs_gamma = 0.99;
    config.reward_dist_ball = -0.1;
    BB_CHECK(!bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_STRICT_REPLAY, NULL, &result));
    BB_CHECK(strcmp(result.field, "reward_dist_ball") == 0);

    bbe_environment_config_defaults(&config);
    config.reward_dist_pbrs_gamma = 1.0;
    config.reward_dist_ball = 1.0;
    config.reward_dist_endzone = 1.0;
    BB_CHECK(!bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_STRICT_REPLAY, NULL, &result));
    BB_CHECK(strcmp(result.field, "reward_td") == 0);

    bbe_environment_config_defaults(&config);
    config.state_bank.endzone_selector = 1.0;
    config.state_bank.pickup_selector = 1.0;
    config.state_bank.reset_pct = 1.0;
    config.state_bank.kind = BBE_STATE_BANK_STRICT_REPLAY;
    BB_CHECK(!bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_STRICT_REPLAY, NULL, &result));
    BB_CHECK_EQ(result.error, BBE_ENV_CONFIG_CROSS_FIELD);

    bbe_environment_config_defaults(&config);
    config.state_bank.kind = BBE_STATE_BANK_STRICT_REPLAY;
    BB_CHECK(!bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_STRICT_REPLAY, NULL, &result));
    BB_CHECK(strcmp(result.field, "state_bank_kind") == 0);

    bbe_environment_config_defaults(&config);
    config.state_bank.reset_pct = 1.0;
    BB_CHECK(!bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_STRICT_REPLAY, NULL, &result));
    BB_CHECK(strcmp(result.field, "state_bank_kind") == 0);

    bbe_environment_config_defaults(&config);
    config.state_bank.reset_pct = 1.0;
    config.state_bank.kind = BBE_STATE_BANK_STRICT_REPLAY;
    BB_CHECK(!bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_NONE, NULL, &result));
    BB_CHECK(strcmp(result.field, "state_bank_kind") == 0);

    bbe_environment_config_defaults(&config);
    config.state_bank.reset_pct = 1.0;
    config.state_bank.kind = BBE_STATE_BANK_AUTHORED_SCENARIO;
    BB_CHECK(!bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_STRICT_REPLAY, NULL, &result));
    BB_CHECK(strcmp(result.field, "state_bank_kind") == 0);

    bbe_environment_config_defaults(&config);
    config.state_bank.endzone_selector = 1.0;
    BB_CHECK(!bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_STRICT_REPLAY, NULL, &result));
    BB_CHECK(strcmp(result.field, "demo_endzone_maxdist") == 0);

    bbe_environment_config_defaults(&config);
    config.state_bank.reset_pct = 1.0;
    config.state_bank.kind = BBE_STATE_BANK_STRICT_REPLAY;
    config.state_bank.force_home_team = 0.0;
    BB_CHECK(!bbe_environment_config_validate_and_apply(
        &config, BBE_STATE_BANK_STRICT_REPLAY, NULL, &result));
    BB_CHECK(strcmp(result.field, "force_home_team") == 0);
}

BB_TEST(environment_config_diagnostic_names_field_and_domain) {
    DictItem item = {
        .key = "force_home_team",
        .value = (double)BB_TEAM_COUNT,
    };
    Dict dict = {.items = &item, .size = 1, .capacity = 1};
    bbe_environment_config_result result;
    char diagnostic[256];
    BB_CHECK(!bbe_environment_config_parse_dict(
        &dict, BBE_STATE_BANK_STRICT_REPLAY, NULL, NULL, &result));
    bbe_environment_config_format_diagnostic(
        &result, diagnostic, sizeof diagnostic);
    BB_CHECK(strstr(
        diagnostic,
        "force_home_team must be integer -1 or 0..BB_TEAM_COUNT-1") != NULL);
}
