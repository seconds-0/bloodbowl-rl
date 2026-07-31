#ifndef BBE_ENVIRONMENT_CONFIG_H
#define BBE_ENVIRONMENT_CONFIG_H

/*
 * Strict Blood Bowl environment configuration.
 *
 * Include this header only after bloodbowl.h and vecenv.h: Bloodbowl,
 * bbe_state_bank_config_values, and Dict are part of this private native
 * implementation.  The ledger below is the sole key/default/domain/
 * destination inventory for the public [env] dictionary.
 */

#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define BBE_ENVIRONMENT_CONFIG_SCHEMA "bloodbowl-environment-config-v1"
#define BBE_ENVIRONMENT_CONFIG_KEY_MAX 63
#define BBE_ENVIRONMENT_CONFIG_EXACT_DOUBLE_INTEGER_MAX 9007199254740991.0

typedef enum {
    BBE_ENV_DOMAIN_SEED = 0,
    BBE_ENV_DOMAIN_REWARD,
    BBE_ENV_DOMAIN_GAMMA,
    BBE_ENV_DOMAIN_STATMATCH,
    BBE_ENV_DOMAIN_BOOL,
    BBE_ENV_DOMAIN_BANK_RESET,
    BBE_ENV_DOMAIN_BANK_KIND,
    BBE_ENV_DOMAIN_BANK_ENDZONE_SELECTOR,
    BBE_ENV_DOMAIN_BANK_PICKUP_SELECTOR,
    BBE_ENV_DOMAIN_BANK_POSTKICK_SELECTOR,
    BBE_ENV_DOMAIN_BANK_PASS_SELECTOR,
    BBE_ENV_DOMAIN_BANK_TEAM,
    BBE_ENV_DOMAIN_SKILL_PLAYERS,
    BBE_ENV_DOMAIN_SKILL_EACH,
    BBE_ENV_DOMAIN_UNIT_INTERVAL,
    BBE_ENV_DOMAIN_SCRIPT_TEAM,
    BBE_ENV_DOMAIN_SCRIPT_TYPE,
    BBE_ENV_DOMAIN_MAX_DECISIONS,
    BBE_ENV_DOMAIN_RENDER_FPS,
} bbe_environment_config_domain;

/*
 * key, raw field, canonical decimal default, raw domain, applied destination
 *
 * The state-bank fields are embedded in the canonical raw value.  Domain-
 * selected declaration macros below suppress duplicate top-level fields for
 * those nine rows while every other use (defaults, parsing, validation, and
 * application) expands directly from this same ledger.
 */
#define BBE_ENVIRONMENT_CONFIG_LEDGER(X)                                      \
    X(seed, seed, 1.0, SEED, seed)                                            \
    X(reward_td, reward_td, 0.4, REWARD, reward_td)                           \
    X(reward_win, reward_win, 0.6, REWARD, reward_win)                        \
    X(reward_draw, reward_draw, 0.0, REWARD, reward_draw)                     \
    X(reward_setup_done, reward_setup_done, 0.0, REWARD, reward_setup_done)   \
    X(reward_setup_autofix, reward_setup_autofix, 0.0, REWARD,                \
      reward_setup_autofix)                                                   \
    X(reward_ball_gain, reward_ball_gain, 0.0, REWARD, reward_ball_gain)      \
    X(reward_ball_loss, reward_ball_loss, 0.0, REWARD, reward_ball_loss)      \
    X(reward_dist_ball, reward_dist_ball, 0.0, REWARD, reward_dist_ball)      \
    X(reward_dist_endzone, reward_dist_endzone, 0.0, REWARD,                  \
      reward_dist_endzone)                                                    \
    X(reward_dist_pbrs_gamma, reward_dist_pbrs_gamma, 0.0, GAMMA,             \
      reward_dist_pbrs_gamma)                                                 \
    X(reward_injury_inflicted, reward_injury_inflicted, 0.0, REWARD,          \
      reward_injury_inflicted)                                                \
    X(reward_injury_taken, reward_injury_taken, 0.0, REWARD,                  \
      reward_injury_taken)                                                    \
    X(reward_injury_value_scaled, reward_injury_value_scaled, 0.0, BOOL,      \
      reward_injury_value_scaled)                                             \
    X(reward_send_off, reward_send_off, 0.0, REWARD, reward_send_off)         \
    X(reward_kickoff_touchback, reward_kickoff_touchback, 0.0, REWARD,        \
      reward_kickoff_touchback)                                               \
    X(reward_possession, reward_possession, 0.0, REWARD, reward_possession)   \
    X(reward_k_assist, reward_k_assist, 0.0, REWARD, reward_k_assist)         \
    X(reward_rush_cost, reward_rush_cost, 0.0, REWARD, reward_rush_cost)      \
    X(reward_carrier_exposure, reward_carrier_exposure, 0.0, REWARD,          \
      reward_carrier_exposure)                                                \
    X(reward_carrier_exposure_soft, reward_carrier_exposure_soft, 0.0,        \
      REWARD, reward_carrier_exposure_soft)                                   \
    X(reward_carrier_threat, reward_carrier_threat, 0.0, REWARD,              \
      reward_carrier_threat)                                                  \
    X(reward_defensive_threat, reward_defensive_threat, 0.0, REWARD,          \
      reward_defensive_threat)                                                \
    X(reward_defensive_threat_soft, reward_defensive_threat_soft, 0.0,        \
      REWARD, reward_defensive_threat_soft)                                   \
    X(reward_statmatch_scale, reward_statmatch_scale, 0.0, STATMATCH,         \
      reward_statmatch_scale)                                                 \
    X(demo_endzone_maxdist, state_bank.endzone_selector, 0.0,                 \
      BANK_ENDZONE_SELECTOR, demo_endzone_maxdist)                            \
    X(demo_pickup_maxdist, state_bank.pickup_selector, 0.0,                   \
      BANK_PICKUP_SELECTOR, demo_pickup_maxdist)                              \
    X(demo_postkick_maxturn, state_bank.postkick_selector, 0.0,               \
      BANK_POSTKICK_SELECTOR, demo_postkick_maxturn)                           \
    X(demo_pass_maxrange, state_bank.pass_selector, 0.0, BANK_PASS_SELECTOR,  \
      demo_pass_maxrange)                                                     \
    X(skillup_max_players, skillup_max_players, 4.0, SKILL_PLAYERS,           \
      skillup_max_players)                                                    \
    X(skillup_max_each, skillup_max_each, 2.0, SKILL_EACH,                    \
      skillup_max_each)                                                       \
    X(skillup_secondary_pct, skillup_secondary_pct, 0.0, UNIT_INTERVAL,       \
      skillup_secondary_pct)                                                  \
    X(macro_moves, macro_moves, 0.0, BOOL, macro_moves)                       \
    X(reward_surf_taken, reward_surf_taken, 0.0, REWARD, reward_surf_taken)  \
    X(reward_surf_inflicted, reward_surf_inflicted, 0.0, REWARD,              \
      reward_surf_inflicted)                                                  \
    X(reward_k_kd, reward_k_kd, 0.0, REWARD, reward_k_kd)                    \
    X(reward_k_value, reward_k_value, 0.0, REWARD, reward_k_value)            \
    X(reward_k_self_injury, reward_k_self_injury, 0.0, REWARD,                \
      reward_k_self_injury)                                                   \
    X(reward_k_ball, reward_k_ball, 0.0, REWARD, reward_k_ball)               \
    X(reward_k_seq, reward_k_seq, 0.0, REWARD, reward_k_seq)                  \
    X(reward_k_turnover, reward_k_turnover, 0.0, REWARD, reward_k_turnover)   \
    X(demo_reset_pct, state_bank.reset_pct, 0.0, BANK_RESET, demo_reset_pct)  \
    X(state_bank_kind, state_bank.kind, 0.0, BANK_KIND, state_bank_kind)      \
    X(exclude_team, state_bank.exclude_team, -1.0, BANK_TEAM, exclude_team)   \
    X(force_home_team, state_bank.force_home_team, -1.0, BANK_TEAM,           \
      force_home_team)                                                        \
    X(force_away_team, state_bank.force_away_team, -1.0, BANK_TEAM,           \
      force_away_team)                                                        \
    X(scripted_opponent, scripted_opponent, 0.0, BOOL, scripted_opponent)     \
    X(scripted_opponent_type, scripted_opponent_type, 0.0, SCRIPT_TYPE,       \
      scripted_opponent_type)                                                 \
    X(scripted_opponent_team, scripted_opponent_team, 1.0, SCRIPT_TEAM,       \
      scripted_opponent_team)                                                 \
    X(max_decisions, max_decisions, 4096.0, MAX_DECISIONS, max_decisions)     \
    X(render_fps, render_fps, 60.0, RENDER_FPS, render_fps)

enum {
    BBE_ENVIRONMENT_CONFIG_KEY_COUNT =
#define BBE_ENV_COUNT_KEY(key, raw, default_value, domain, destination) +1
        0 BBE_ENVIRONMENT_CONFIG_LEDGER(BBE_ENV_COUNT_KEY)
#undef BBE_ENV_COUNT_KEY
};

_Static_assert(BBE_ENVIRONMENT_CONFIG_KEY_COUNT == 51,
               "Blood Bowl environment schema must contain exactly 51 keys");
_Static_assert(BBE_MAX_DECISIONS == 4096,
               "ledger max_decisions default must track BBE_MAX_DECISIONS");

#define BBE_ENV_RAW_DECL_SEED(field) double field;
#define BBE_ENV_RAW_DECL_REWARD(field) double field;
#define BBE_ENV_RAW_DECL_GAMMA(field) double field;
#define BBE_ENV_RAW_DECL_STATMATCH(field) double field;
#define BBE_ENV_RAW_DECL_BOOL(field) double field;
#define BBE_ENV_RAW_DECL_BANK_RESET(field)
#define BBE_ENV_RAW_DECL_BANK_KIND(field)
#define BBE_ENV_RAW_DECL_BANK_ENDZONE_SELECTOR(field)
#define BBE_ENV_RAW_DECL_BANK_PICKUP_SELECTOR(field)
#define BBE_ENV_RAW_DECL_BANK_POSTKICK_SELECTOR(field)
#define BBE_ENV_RAW_DECL_BANK_PASS_SELECTOR(field)
#define BBE_ENV_RAW_DECL_BANK_TEAM(field)
#define BBE_ENV_RAW_DECL_SKILL_PLAYERS(field) double field;
#define BBE_ENV_RAW_DECL_SKILL_EACH(field) double field;
#define BBE_ENV_RAW_DECL_UNIT_INTERVAL(field) double field;
#define BBE_ENV_RAW_DECL_SCRIPT_TEAM(field) double field;
#define BBE_ENV_RAW_DECL_SCRIPT_TYPE(field) double field;
#define BBE_ENV_RAW_DECL_MAX_DECISIONS(field) double field;
#define BBE_ENV_RAW_DECL_RENDER_FPS(field) double field;

typedef struct {
    bbe_state_bank_config_values state_bank;
#define BBE_ENV_RAW_DECL(key, raw, default_value, domain, destination) \
    BBE_ENV_RAW_DECL_##domain(raw)
    BBE_ENVIRONMENT_CONFIG_LEDGER(BBE_ENV_RAW_DECL)
#undef BBE_ENV_RAW_DECL
} bbe_environment_config;

#undef BBE_ENV_RAW_DECL_SEED
#undef BBE_ENV_RAW_DECL_REWARD
#undef BBE_ENV_RAW_DECL_GAMMA
#undef BBE_ENV_RAW_DECL_STATMATCH
#undef BBE_ENV_RAW_DECL_BOOL
#undef BBE_ENV_RAW_DECL_BANK_RESET
#undef BBE_ENV_RAW_DECL_BANK_KIND
#undef BBE_ENV_RAW_DECL_BANK_ENDZONE_SELECTOR
#undef BBE_ENV_RAW_DECL_BANK_PICKUP_SELECTOR
#undef BBE_ENV_RAW_DECL_BANK_POSTKICK_SELECTOR
#undef BBE_ENV_RAW_DECL_BANK_PASS_SELECTOR
#undef BBE_ENV_RAW_DECL_BANK_TEAM
#undef BBE_ENV_RAW_DECL_SKILL_PLAYERS
#undef BBE_ENV_RAW_DECL_SKILL_EACH
#undef BBE_ENV_RAW_DECL_UNIT_INTERVAL
#undef BBE_ENV_RAW_DECL_SCRIPT_TEAM
#undef BBE_ENV_RAW_DECL_SCRIPT_TYPE
#undef BBE_ENV_RAW_DECL_MAX_DECISIONS
#undef BBE_ENV_RAW_DECL_RENDER_FPS

typedef struct {
    const char* key;
    const char* raw_field;
    double default_value;
    bbe_environment_config_domain domain;
    const char* destination;
} bbe_environment_config_descriptor;

static const bbe_environment_config_descriptor
    bbe_environment_config_descriptors[] = {
#define BBE_ENV_DESCRIPTOR(key, raw, default_value, domain, destination) \
    {#key, #raw, default_value, BBE_ENV_DOMAIN_##domain, #destination},
        BBE_ENVIRONMENT_CONFIG_LEDGER(BBE_ENV_DESCRIPTOR)
#undef BBE_ENV_DESCRIPTOR
};

_Static_assert(
    sizeof bbe_environment_config_descriptors /
            sizeof bbe_environment_config_descriptors[0] ==
        BBE_ENVIRONMENT_CONFIG_KEY_COUNT,
    "environment descriptor table must be generated from the complete ledger");

typedef enum {
    BBE_ENV_CONFIG_OK = 0,
    BBE_ENV_CONFIG_STRUCTURE,
    BBE_ENV_CONFIG_CARDINALITY,
    BBE_ENV_CONFIG_NULL_KEY,
    BBE_ENV_CONFIG_MALFORMED_KEY,
    BBE_ENV_CONFIG_DUPLICATE_KEY,
    BBE_ENV_CONFIG_UNKNOWN_KEY,
    BBE_ENV_CONFIG_DOMAIN,
    BBE_ENV_CONFIG_CROSS_FIELD,
} bbe_environment_config_error;

typedef struct {
    bbe_environment_config_error error;
    const char* field;
    const char* domain;
    double value;
    int has_value;
} bbe_environment_config_result;

static void bbe_environment_config_result_clear(
        bbe_environment_config_result* result) {
    if (result == NULL) return;
    *result = (bbe_environment_config_result){
        .error = BBE_ENV_CONFIG_OK,
        .field = NULL,
        .domain = NULL,
        .value = 0.0,
        .has_value = 0,
    };
}

static int bbe_environment_config_fail(
        bbe_environment_config_result* result,
        bbe_environment_config_error error, const char* field,
        const char* domain, double value, int has_value) {
    if (result != NULL) {
        *result = (bbe_environment_config_result){
            .error = error,
            .field = field,
            .domain = domain,
            .value = value,
            .has_value = has_value,
        };
    }
    return 0;
}

static const char* bbe_environment_config_domain_name(
        bbe_environment_config_domain domain) {
    switch (domain) {
    case BBE_ENV_DOMAIN_SEED:
        return "be an exact integer in [0, 2^53-1]";
    case BBE_ENV_DOMAIN_REWARD:
        return "be finite in [-1,1] and remain nonzero as float";
    case BBE_ENV_DOMAIN_GAMMA:
        return "be finite in [0,1] and remain nonzero as float";
    case BBE_ENV_DOMAIN_STATMATCH:
        return "be finite in [0,1] and remain nonzero as float";
    case BBE_ENV_DOMAIN_BOOL:
        return "be the exact boolean 0 or 1";
    case BBE_ENV_DOMAIN_BANK_RESET:
        return "be finite in [0,1] and remain nonzero as float";
    case BBE_ENV_DOMAIN_BANK_KIND:
        return "be the exact state-bank enum 0, 1, or 2";
    case BBE_ENV_DOMAIN_BANK_ENDZONE_SELECTOR:
        return "be an exact integer in [0, BBE_STATE_BANK_MAX_DISTANCE]";
    case BBE_ENV_DOMAIN_BANK_PICKUP_SELECTOR:
        return "be an exact integer in [0, BBE_STATE_BANK_MAX_DISTANCE]";
    case BBE_ENV_DOMAIN_BANK_POSTKICK_SELECTOR:
        return "be an exact integer in [0, BBE_STATE_BANK_MAX_TURN]";
    case BBE_ENV_DOMAIN_BANK_PASS_SELECTOR:
        return "be an exact integer in [0, BBE_STATE_BANK_MAX_DISTANCE]";
    case BBE_ENV_DOMAIN_BANK_TEAM:
        return "be integer -1 or 0..BB_TEAM_COUNT-1";
    case BBE_ENV_DOMAIN_SKILL_PLAYERS:
        return "be an exact integer in [0, BB_TEAM_SLOTS]";
    case BBE_ENV_DOMAIN_SKILL_EACH:
        return "be an exact integer in [0, 12]";
    case BBE_ENV_DOMAIN_UNIT_INTERVAL:
        return "be finite in [0,1] and remain nonzero as float";
    case BBE_ENV_DOMAIN_SCRIPT_TEAM:
        return "be the exact scripted-team enum 0, 1, or 2";
    case BBE_ENV_DOMAIN_SCRIPT_TYPE:
        return "be the exact scripted-opponent type 0 or 1";
    case BBE_ENV_DOMAIN_MAX_DECISIONS:
        return "be an exact integer in [1, BBE_MAX_DECISIONS]";
    case BBE_ENV_DOMAIN_RENDER_FPS:
        return "be an exact integer in [1, INT_MAX]";
    }
    return "be a valid closed-domain value";
}

static int bbe_environment_config_exact_integer(
        double value, double minimum, double maximum) {
    return isfinite(value) && value >= minimum && value <= maximum &&
           value == floor(value);
}

static int bbe_environment_config_float_preserves_nonzero(double value) {
    return value == 0.0 || (float)value != 0.0f;
}

static int bbe_environment_config_domain_valid(
        bbe_environment_config_domain domain, double value) {
    switch (domain) {
    case BBE_ENV_DOMAIN_SEED:
        return bbe_environment_config_exact_integer(
            value, 0.0, BBE_ENVIRONMENT_CONFIG_EXACT_DOUBLE_INTEGER_MAX);
    case BBE_ENV_DOMAIN_REWARD:
        return isfinite(value) && value >= -1.0 && value <= 1.0 &&
               bbe_environment_config_float_preserves_nonzero(value);
    case BBE_ENV_DOMAIN_GAMMA:
    case BBE_ENV_DOMAIN_STATMATCH:
    case BBE_ENV_DOMAIN_BANK_RESET:
    case BBE_ENV_DOMAIN_UNIT_INTERVAL:
        return isfinite(value) && value >= 0.0 && value <= 1.0 &&
               bbe_environment_config_float_preserves_nonzero(value);
    case BBE_ENV_DOMAIN_BOOL:
    case BBE_ENV_DOMAIN_SCRIPT_TYPE:
        return bbe_environment_config_exact_integer(value, 0.0, 1.0);
    case BBE_ENV_DOMAIN_BANK_KIND:
    case BBE_ENV_DOMAIN_SCRIPT_TEAM:
        return bbe_environment_config_exact_integer(value, 0.0, 2.0);
    case BBE_ENV_DOMAIN_BANK_ENDZONE_SELECTOR:
    case BBE_ENV_DOMAIN_BANK_PICKUP_SELECTOR:
    case BBE_ENV_DOMAIN_BANK_PASS_SELECTOR:
        return bbe_environment_config_exact_integer(
            value, 0.0, (double)BBE_STATE_BANK_MAX_DISTANCE);
    case BBE_ENV_DOMAIN_BANK_POSTKICK_SELECTOR:
        return bbe_environment_config_exact_integer(
            value, 0.0, (double)BBE_STATE_BANK_MAX_TURN);
    case BBE_ENV_DOMAIN_BANK_TEAM:
        return value == -1.0 ||
               bbe_environment_config_exact_integer(
                   value, 0.0, (double)(BB_TEAM_COUNT - 1));
    case BBE_ENV_DOMAIN_SKILL_PLAYERS:
        return bbe_environment_config_exact_integer(
            value, 0.0, (double)BB_TEAM_SLOTS);
    case BBE_ENV_DOMAIN_SKILL_EACH:
        return bbe_environment_config_exact_integer(value, 0.0, 12.0);
    case BBE_ENV_DOMAIN_MAX_DECISIONS:
        return bbe_environment_config_exact_integer(
            value, 1.0, (double)BBE_MAX_DECISIONS);
    case BBE_ENV_DOMAIN_RENDER_FPS:
        return bbe_environment_config_exact_integer(
            value, 1.0, (double)INT_MAX);
    }
    return 0;
}

static void bbe_environment_config_defaults(
        bbe_environment_config* config) {
    if (config == NULL) return;
    memset(config, 0, sizeof *config);
#define BBE_ENV_SET_DEFAULT(key, raw, default_value, domain, destination) \
    config->raw = (default_value);
    BBE_ENVIRONMENT_CONFIG_LEDGER(BBE_ENV_SET_DEFAULT)
#undef BBE_ENV_SET_DEFAULT
}

static int bbe_environment_config_validate_raw(
        const bbe_environment_config* config,
        bbe_environment_config_result* result) {
    bbe_environment_config_result_clear(result);
    if (config == NULL) {
        return bbe_environment_config_fail(
            result, BBE_ENV_CONFIG_STRUCTURE, "environment configuration",
            "be non-NULL", 0.0, 0);
    }
#define BBE_ENV_VALIDATE_RAW(key, raw, default_value, domain, destination)    \
    do {                                                                     \
        double bbe_env_value_ = config->raw;                                 \
        if (!bbe_environment_config_domain_valid(                            \
                BBE_ENV_DOMAIN_##domain, bbe_env_value_)) {                  \
            return bbe_environment_config_fail(                              \
                result, BBE_ENV_CONFIG_DOMAIN, #key,                         \
                bbe_environment_config_domain_name(                          \
                    BBE_ENV_DOMAIN_##domain),                                \
                bbe_env_value_, 1);                                          \
        }                                                                    \
    } while (0);
    BBE_ENVIRONMENT_CONFIG_LEDGER(BBE_ENV_VALIDATE_RAW)
#undef BBE_ENV_VALIDATE_RAW
    return 1;
}

#define BBE_ENV_APPLY_SEED(target, destination, value) \
    (target)->destination = (uint64_t)(value)
#define BBE_ENV_APPLY_REWARD(target, destination, value) \
    (target)->destination = (float)(value)
#define BBE_ENV_APPLY_GAMMA(target, destination, value) \
    (target)->destination = (float)(value)
#define BBE_ENV_APPLY_STATMATCH(target, destination, value) \
    (target)->destination = (float)(value)
#define BBE_ENV_APPLY_BOOL(target, destination, value) \
    (target)->destination = (int)(value)
#define BBE_ENV_APPLY_BANK_RESET(target, destination, value) \
    (target)->destination = (float)(value)
#define BBE_ENV_APPLY_BANK_KIND(target, destination, value) \
    (target)->destination = (int)(value)
#define BBE_ENV_APPLY_BANK_ENDZONE_SELECTOR(target, destination, value) \
    (target)->destination = (int)(value)
#define BBE_ENV_APPLY_BANK_PICKUP_SELECTOR(target, destination, value) \
    (target)->destination = (int)(value)
#define BBE_ENV_APPLY_BANK_POSTKICK_SELECTOR(target, destination, value) \
    (target)->destination = (int)(value)
#define BBE_ENV_APPLY_BANK_PASS_SELECTOR(target, destination, value) \
    (target)->destination = (int)(value)
#define BBE_ENV_APPLY_BANK_TEAM(target, destination, value) \
    (target)->destination = (int)(value)
#define BBE_ENV_APPLY_SKILL_PLAYERS(target, destination, value) \
    (target)->destination = (int)(value)
#define BBE_ENV_APPLY_SKILL_EACH(target, destination, value) \
    (target)->destination = (int)(value)
#define BBE_ENV_APPLY_UNIT_INTERVAL(target, destination, value) \
    (target)->destination = (float)(value)
#define BBE_ENV_APPLY_SCRIPT_TEAM(target, destination, value) \
    (target)->destination = (int)(value)
#define BBE_ENV_APPLY_SCRIPT_TYPE(target, destination, value) \
    (target)->destination = (int)(value)
#define BBE_ENV_APPLY_MAX_DECISIONS(target, destination, value) \
    (target)->destination = (int)(value)
#define BBE_ENV_APPLY_RENDER_FPS(target, destination, value) \
    (target)->destination = (int)(value)

static void bbe_environment_config_apply_validated(
        Bloodbowl* target, const bbe_environment_config* config) {
#define BBE_ENV_APPLY_ROW(key, raw, default_value, domain, destination) \
    BBE_ENV_APPLY_##domain(target, destination, config->raw);
    BBE_ENVIRONMENT_CONFIG_LEDGER(BBE_ENV_APPLY_ROW)
#undef BBE_ENV_APPLY_ROW
    target->reward_configured = 1;
    target->reach_mover = -1;
    target->macro_mover = -1;
}

static void bbe_environment_config_copy_applied(
        Bloodbowl* target, const Bloodbowl* source) {
#define BBE_ENV_COPY_ROW(key, raw, default_value, domain, destination) \
    target->destination = source->destination;
    BBE_ENVIRONMENT_CONFIG_LEDGER(BBE_ENV_COPY_ROW)
#undef BBE_ENV_COPY_ROW
    target->reward_configured = source->reward_configured;
    target->reach_mover = source->reach_mover;
    target->macro_mover = source->macro_mover;
}

static uint64_t bbe_environment_config_vector_seed(
        const Bloodbowl* applied, uint64_t environment_index) {
    return applied->seed + environment_index;
}

#undef BBE_ENV_APPLY_SEED
#undef BBE_ENV_APPLY_REWARD
#undef BBE_ENV_APPLY_GAMMA
#undef BBE_ENV_APPLY_STATMATCH
#undef BBE_ENV_APPLY_BOOL
#undef BBE_ENV_APPLY_BANK_RESET
#undef BBE_ENV_APPLY_BANK_KIND
#undef BBE_ENV_APPLY_BANK_ENDZONE_SELECTOR
#undef BBE_ENV_APPLY_BANK_PICKUP_SELECTOR
#undef BBE_ENV_APPLY_BANK_POSTKICK_SELECTOR
#undef BBE_ENV_APPLY_BANK_PASS_SELECTOR
#undef BBE_ENV_APPLY_BANK_TEAM
#undef BBE_ENV_APPLY_SKILL_PLAYERS
#undef BBE_ENV_APPLY_SKILL_EACH
#undef BBE_ENV_APPLY_UNIT_INTERVAL
#undef BBE_ENV_APPLY_SCRIPT_TEAM
#undef BBE_ENV_APPLY_SCRIPT_TYPE
#undef BBE_ENV_APPLY_MAX_DECISIONS
#undef BBE_ENV_APPLY_RENDER_FPS

static const char* bbe_environment_config_first_nonzero_selector(
        const bbe_environment_config* config, double* value_out) {
    if (config->state_bank.endzone_selector != 0.0) {
        *value_out = config->state_bank.endzone_selector;
        return "demo_endzone_maxdist";
    }
    if (config->state_bank.pickup_selector != 0.0) {
        *value_out = config->state_bank.pickup_selector;
        return "demo_pickup_maxdist";
    }
    if (config->state_bank.postkick_selector != 0.0) {
        *value_out = config->state_bank.postkick_selector;
        return "demo_postkick_maxturn";
    }
    *value_out = config->state_bank.pass_selector;
    return "demo_pass_maxrange";
}

static int bbe_environment_config_validate_cross_fields(
        const bbe_environment_config* config, const Bloodbowl* applied,
        int compiled_kind, bbe_environment_config_result* result) {
    bbe_state_bank_error bank_error = bbe_state_bank_validate_config_values(
        &config->state_bank, compiled_kind);
    if (bank_error != BBE_SB_OK) {
        const char* field = "state_bank_kind";
        const char* domain = "satisfy the state-bank cross-field contract";
        double value = config->state_bank.kind;
        if (bank_error == BBE_SB_CONFIG_MULTIPLE_SELECTORS) {
            field = bbe_environment_config_first_nonzero_selector(
                config, &value);
            domain = "be the only nonzero state-bank selector";
        } else if (bank_error == BBE_SB_CONFIG_INERT_SELECTOR) {
            field = bbe_environment_config_first_nonzero_selector(
                config, &value);
            domain = "be zero when demo_reset_pct is zero";
        } else if (bank_error == BBE_SB_CONFIG_ENDZONE_SELECTOR ||
            bank_error == BBE_SB_CONFIG_PICKUP_SELECTOR ||
            bank_error == BBE_SB_CONFIG_POSTKICK_SELECTOR ||
            bank_error == BBE_SB_CONFIG_PASS_SELECTOR ||
            bank_error == BBE_SB_CONFIG_SELECTOR) {
            field = bbe_environment_config_first_nonzero_selector(
                config, &value);
            domain = "satisfy its exact selector domain";
        } else if (bank_error == BBE_SB_CONFIG_RESET_PCT ||
                   bank_error == BBE_SB_CONFIG_RESET_PCT_UNDERFLOW) {
            field = "demo_reset_pct";
            value = config->state_bank.reset_pct;
            domain = bbe_environment_config_domain_name(
                BBE_ENV_DOMAIN_BANK_RESET);
        } else if (bank_error == BBE_SB_CONFIG_INERT_KIND) {
            domain = "be zero when demo_reset_pct is zero";
        } else if (bank_error == BBE_SB_CONFIG_MISSING_KIND) {
            domain = "be nonzero when demo_reset_pct is positive";
        } else if (bank_error == BBE_SB_CONFIG_KIND_MISMATCH) {
            domain =
                "equal the compiled state-bank kind when demo_reset_pct "
                "is positive";
        } else if (bank_error == BBE_SB_REQUEST_AUTHORED_DISABLED) {
            domain =
                "be 0 or the compiled production state-bank kind; "
                "authored mode is disabled";
        } else if (bank_error == BBE_SB_CONFIG_TEAM_SENTINEL) {
            domain = config->state_bank.reset_pct > 0.0
                         ? "be -1 when demo_reset_pct is positive"
                         : "be integer -1 or 0..BB_TEAM_COUNT-1";
            if (config->state_bank.exclude_team != -1.0) {
                field = "exclude_team";
                value = config->state_bank.exclude_team;
            } else if (config->state_bank.force_home_team != -1.0) {
                field = "force_home_team";
                value = config->state_bank.force_home_team;
            } else {
                field = "force_away_team";
                value = config->state_bank.force_away_team;
            }
        }
        return bbe_environment_config_fail(
            result, BBE_ENV_CONFIG_CROSS_FIELD, field, domain, value, 1);
    }

    if (applied->reward_carrier_threat != 0.0f &&
        (applied->reward_carrier_exposure != 0.0f ||
         applied->reward_carrier_exposure_soft != 0.0f)) {
        return bbe_environment_config_fail(
            result, BBE_ENV_CONFIG_CROSS_FIELD, "reward_carrier_threat",
            "be zero when either reward_carrier_exposure field is nonzero",
            config->reward_carrier_threat, 1);
    }
    if (applied->reward_carrier_threat != 0.0f &&
        applied->reward_k_assist != 0.0f) {
        return bbe_environment_config_fail(
            result, BBE_ENV_CONFIG_CROSS_FIELD, "reward_carrier_threat",
            "be zero when reward_k_assist is nonzero",
            config->reward_carrier_threat, 1);
    }
    if (!bbe_reward_potential_sign_valid(applied)) {
        const char* field = applied->reward_dist_ball < 0.0f
                                ? "reward_dist_ball"
                                : "reward_dist_endzone";
        double value = applied->reward_dist_ball < 0.0f
                           ? config->reward_dist_ball
                           : config->reward_dist_endzone;
        return bbe_environment_config_fail(
            result, BBE_ENV_CONFIG_CROSS_FIELD, field,
            "be nonnegative when reward_dist_pbrs_gamma is positive",
            value, 1);
    }
    if (!bbe_reward_envelope_valid(applied)) {
        return bbe_environment_config_fail(
            result, BBE_ENV_CONFIG_CROSS_FIELD, "reward_td",
            "combine with reward_win, reward_draw, and PBRS distances "
            "within the trainer reward clamp",
            (double)bbe_reward_clip_threshold(applied), 1);
    }
#if PUFFER_QUALIFICATION_FIXTURE_ENABLED
    const char* qualification_error =
        bbe_f5_trainability_config_error(applied);
    if (qualification_error != NULL) {
        return bbe_environment_config_fail(
            result, BBE_ENV_CONFIG_CROSS_FIELD, qualification_error,
            "match the sealed f5-fixed-state-v1 qualification contract",
            0.0, 0);
    }
#endif
    return 1;
}

static int bbe_environment_config_validate_and_apply(
        const bbe_environment_config* config, int compiled_kind,
        Bloodbowl* applied_out, bbe_environment_config_result* result) {
    if (!bbe_environment_config_validate_raw(config, result)) return 0;
    Bloodbowl applied = {0};
    bbe_environment_config_apply_validated(&applied, config);
    if (!bbe_environment_config_validate_cross_fields(
            config, &applied, compiled_kind, result)) {
        return 0;
    }
    if (applied_out != NULL) *applied_out = applied;
    bbe_environment_config_result_clear(result);
    return 1;
}

static int bbe_environment_config_key_valid(const char* key) {
    size_t length = 0;
    while (length <= BBE_ENVIRONMENT_CONFIG_KEY_MAX &&
           key[length] != '\0') {
        unsigned char byte = (unsigned char)key[length];
        if (!((byte >= (unsigned char)'a' && byte <= (unsigned char)'z') ||
              (byte >= (unsigned char)'0' && byte <= (unsigned char)'9') ||
              byte == (unsigned char)'_')) {
            return 0;
        }
        length++;
    }
    return length > 0 && length <= BBE_ENVIRONMENT_CONFIG_KEY_MAX &&
           key[length] == '\0';
}

static int bbe_environment_config_parse_dict(
        Dict* kwargs, int compiled_kind, bbe_environment_config* config_out,
        Bloodbowl* applied_out, bbe_environment_config_result* result) {
    bbe_environment_config_result_clear(result);
    if (kwargs == NULL) {
        return bbe_environment_config_fail(
            result, BBE_ENV_CONFIG_STRUCTURE, "environment dictionary",
            "be non-NULL", 0.0, 0);
    }
    if (kwargs->size < 0 || kwargs->capacity < 0 ||
        kwargs->size > kwargs->capacity) {
        return bbe_environment_config_fail(
            result, BBE_ENV_CONFIG_STRUCTURE, "environment dictionary",
            "have coherent nonnegative size and capacity", 0.0, 0);
    }
    if (kwargs->size > BBE_ENVIRONMENT_CONFIG_KEY_COUNT) {
        return bbe_environment_config_fail(
            result, BBE_ENV_CONFIG_CARDINALITY, "environment dictionary",
            "contain at most 51 keys", (double)kwargs->size, 1);
    }
    if (kwargs->size > 0 && kwargs->items == NULL) {
        return bbe_environment_config_fail(
            result, BBE_ENV_CONFIG_STRUCTURE, "environment dictionary items",
            "be non-NULL when size is positive", 0.0, 0);
    }

    /*
     * Structural first pass: no key reaches strcmp, bounded scanning, or
     * diagnostics until every occupied item is known non-NULL.
     */
    for (int i = 0; i < kwargs->size; i++) {
        if (kwargs->items[i].key == NULL) {
            return bbe_environment_config_fail(
                result, BBE_ENV_CONFIG_NULL_KEY,
                "environment dictionary item key", "be non-NULL", 0.0, 0);
        }
    }

    bbe_environment_config config;
    bbe_environment_config_defaults(&config);
    for (int i = 0; i < kwargs->size; i++) {
        const char* key = kwargs->items[i].key;
        if (!bbe_environment_config_key_valid(key)) {
            return bbe_environment_config_fail(
                result, BBE_ENV_CONFIG_MALFORMED_KEY, "environment key",
                "be nonempty [a-z0-9_]+ with at most 63 bytes", 0.0, 0);
        }
        for (int prior = 0; prior < i; prior++) {
            if (strcmp(kwargs->items[prior].key, key) == 0) {
                return bbe_environment_config_fail(
                    result, BBE_ENV_CONFIG_DUPLICATE_KEY, key,
                    "appear at most once", kwargs->items[i].value, 1);
            }
        }
        int matched = 0;
        double value = kwargs->items[i].value;
#define BBE_ENV_PARSE_ROW(key_token, raw, default_value, domain, destination) \
        if (!matched && strcmp(key, #key_token) == 0) {                       \
            config.raw = value;                                               \
            matched = 1;                                                      \
        }
        BBE_ENVIRONMENT_CONFIG_LEDGER(BBE_ENV_PARSE_ROW)
#undef BBE_ENV_PARSE_ROW
        if (!matched) {
            return bbe_environment_config_fail(
                result, BBE_ENV_CONFIG_UNKNOWN_KEY, key,
                "be a key in bloodbowl-environment-config-v1", value, 1);
        }
    }

    Bloodbowl applied;
    if (!bbe_environment_config_validate_and_apply(
            &config, compiled_kind, &applied, result)) {
        return 0;
    }
    if (config_out != NULL) *config_out = config;
    if (applied_out != NULL) *applied_out = applied;
    return 1;
}

static void bbe_environment_config_format_diagnostic(
        const bbe_environment_config_result* result, char* diagnostic,
        size_t diagnostic_capacity) {
    if (diagnostic == NULL || diagnostic_capacity == 0) return;
    diagnostic[0] = '\0';
    if (result == NULL || result->error == BBE_ENV_CONFIG_OK) return;
    const char* field = result->field != NULL ? result->field : "<unknown>";
    const char* domain = result->domain != NULL ? result->domain : "be valid";
    if (result->has_value) {
        (void)snprintf(diagnostic, diagnostic_capacity,
                       "%s must %s; got %.17g", field, domain, result->value);
    } else {
        (void)snprintf(diagnostic, diagnostic_capacity, "%s must %s",
                       field, domain);
    }
}

#endif
