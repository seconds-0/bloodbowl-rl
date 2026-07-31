#include "bloodbowl.h"
#include "state_bank_sha256.h"

#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/*
 * Qualification-only diagnostics for the sealed F5 fixture.  This program
 * deliberately drives the same c_reset/c_step, conditional support, and
 * decoder surfaces as Puffer.  It is not linked into a trainer and exposes no
 * action-label API.
 */

enum {
    F5_DECISIONS = 8,
    F5_MOVE_STEPS = 6,
    F5_RANDOM_EPISODE_LIMIT = 1000000,
};

typedef struct {
    Bloodbowl env;
    uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    float actions[BBE_AGENTS * 3];
    unsigned char mask[BBE_AGENTS * BBE_MASK_SIZE];
    float rewards[BBE_AGENTS];
    float terminals[BBE_AGENTS];
} f5_fixture;

typedef struct {
    uint64_t state;
} f5_sampler;

#if !defined(__SIZEOF_INT128__)
#error "F5 exact probability evidence requires compiler unsigned __int128"
#endif

typedef unsigned __int128 f5_u128;

typedef struct {
    f5_u128 numerator;
    f5_u128 denominator;
} f5_fraction;

typedef struct {
    uint64_t trajectories;
    long double probability;
    f5_fraction exact_probability;
    uint64_t nodes;
    int failed;
} f5_enumeration;

static const int f5_reference_heads[F5_DECISIONS][3] = {
    {6, 6, 390},
    {7, 0, 390},
    {9, 32, 254},
    {9, 32, 229},
    {9, 32, 204},
    {9, 32, 179},
    {9, 32, 154},
    {9, 32, 129},
};

static f5_u128 f5_u128_gcd(f5_u128 left, f5_u128 right) {
    while (right != 0) {
        f5_u128 remainder = left % right;
        left = right;
        right = remainder;
    }
    return left;
}

static int f5_u128_multiply(
        f5_u128 left, f5_u128 right, f5_u128* output) {
    const f5_u128 maximum = (f5_u128)-1;
    if (output == NULL || (right != 0 && left > maximum / right)) return -1;
    *output = left * right;
    return 0;
}

static int f5_fraction_divide(
        f5_fraction input, uint64_t divisor, f5_fraction* output) {
    if (divisor == 0 || output == NULL ||
        input.denominator == 0 ||
        f5_u128_multiply(
            input.denominator, (f5_u128)divisor,
            &output->denominator) != 0) {
        return -1;
    }
    output->numerator = input.numerator;
    f5_u128 common = f5_u128_gcd(
        output->numerator, output->denominator);
    output->numerator /= common;
    output->denominator /= common;
    return 0;
}

static int f5_fraction_add(
        f5_fraction left, f5_fraction right, f5_fraction* output) {
    if (output == NULL || left.denominator == 0 ||
        right.denominator == 0) {
        return -1;
    }
    f5_u128 common =
        f5_u128_gcd(left.denominator, right.denominator);
    f5_u128 left_scale = right.denominator / common;
    f5_u128 right_scale = left.denominator / common;
    f5_u128 left_term;
    f5_u128 right_term;
    f5_u128 denominator;
    const f5_u128 maximum = (f5_u128)-1;
    if (f5_u128_multiply(
            left.numerator, left_scale, &left_term) != 0 ||
        f5_u128_multiply(
            right.numerator, right_scale, &right_term) != 0 ||
        left_term > maximum - right_term ||
        f5_u128_multiply(
            left.denominator, left_scale, &denominator) != 0) {
        return -1;
    }
    output->numerator = left_term + right_term;
    output->denominator = denominator;
    common = f5_u128_gcd(output->numerator, output->denominator);
    output->numerator /= common;
    output->denominator /= common;
    return 0;
}

static void f5_u128_decimal(f5_u128 value, char output[40]) {
    char reverse[40];
    size_t length = 0;
    do {
        reverse[length++] = (char)('0' + value % 10);
        value /= 10;
    } while (value != 0);
    for (size_t index = 0; index < length; index++) {
        output[index] = reverse[length - index - 1];
    }
    output[length] = '\0';
}

static long double f5_fraction_long_double(f5_fraction value) {
    return (long double)value.numerator / (long double)value.denominator;
}

static void f5_die_sink(void* user, int sides, int value) {
    (void)sides;
    (void)value;
    uint64_t* count = (uint64_t*)user;
    (*count)++;
}

static void f5_setup(f5_fixture* fixture) {
    memset(fixture, 0, sizeof *fixture);
    Bloodbowl* env = &fixture->env;
    env->num_agents = BBE_AGENTS;
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        env->obs_ptr[agent] = fixture->obs + agent * BBE_OBS_SIZE;
        env->action_ptr[agent] = fixture->actions + agent * 3;
        env->action_mask_ptr[agent] =
            fixture->mask + agent * BBE_MASK_SIZE;
        env->reward_ptr[agent] = fixture->rewards + agent;
        env->terminal_ptr[agent] = fixture->terminals + agent;
        env->v4_dirty[agent] = 1;
    }
    env->seed = 1;
    env->max_decisions = F5_DECISIONS;
    env->macro_moves = 0;
    env->demo_reset_pct = 0.0f;
    env->state_bank_kind = BBE_STATE_BANK_NONE;
    env->exclude_team = -1;
    env->force_home_team = -1;
    env->force_away_team = -1;
    env->scripted_opponent_team = BB_AWAY;
    env->skillup_max_players = 4;
    env->skillup_max_each = 2;
    env->render_fps = 60;
    env->reward_configured = 1;
    env->reward_td = 1.0f;
}

static void f5_hash(const void* bytes, size_t size, char out[65]) {
    uint8_t digest[32];
    bbe_sha256_bytes(bytes, size, digest);
    bbe_sha256_hex(digest, out);
}

static int f5_waiting_mask_is_singleton(const f5_fixture* fixture, int team) {
    const unsigned char* mask =
        fixture->mask + team * BBE_MASK_SIZE;
    int type_count = 0;
    int arg_count = 0;
    int square_count = 0;
    for (int i = 0; i < BBE_HEAD_TYPE; i++) type_count += mask[i] != 0;
    for (int i = 0; i < BBE_HEAD_ARG; i++) {
        arg_count += mask[BBE_HEAD_TYPE + i] != 0;
    }
    for (int i = 0; i < BBE_HEAD_SQ; i++) {
        square_count +=
            mask[BBE_HEAD_TYPE + BBE_HEAD_ARG + i] != 0;
    }
    return type_count == 1 && arg_count == 1 && square_count == 1 &&
        mask[BB_A_NONE] != 0 &&
        mask[BBE_HEAD_TYPE + 32] != 0 &&
        mask[BBE_HEAD_TYPE + BBE_HEAD_ARG + 390] != 0;
}

static int f5_support(
        const Bloodbowl* env,
        int head,
        int type,
        int arg,
        unsigned char* support,
        int size) {
    memset(support, 0, (size_t)size);
    return bbe_fill_joint_head_mask(
        env, BB_HOME, head, type, arg, support, size);
}

static int f5_apply_heads(f5_fixture* fixture, const int heads[3]) {
    Bloodbowl* env = &fixture->env;
    if (env->match.decision_team != BB_HOME) return -1;
    unsigned char type_support[BBE_HEAD_TYPE];
    unsigned char arg_support[BBE_HEAD_ARG];
    unsigned char square_support[BBE_HEAD_SQ];
    if (f5_support(env, 0, 0, 32, type_support, BBE_HEAD_TYPE) <= 0 ||
        heads[0] < 0 || heads[0] >= BBE_HEAD_TYPE ||
        !type_support[heads[0]]) {
        return -1;
    }
    if (f5_support(
            env, 1, heads[0], 32, arg_support, BBE_HEAD_ARG) <= 0 ||
        heads[1] < 0 || heads[1] >= BBE_HEAD_ARG ||
        !arg_support[heads[1]]) {
        return -1;
    }
    if (f5_support(
            env, 2, heads[0], heads[1],
            square_support, BBE_HEAD_SQ) <= 0 ||
        heads[2] < 0 || heads[2] >= BBE_HEAD_SQ ||
        !square_support[heads[2]]) {
        return -1;
    }
    for (int head = 0; head < 3; head++) {
        env->action_ptr[BB_HOME][head] = (float)heads[head];
        env->action_ptr[BB_AWAY][head] =
            (float)(head == 0 ? BB_A_NONE : head == 1 ? 32 : 390);
    }
    c_step(env);
    return 0;
}

static int f5_reference(void) {
    f5_fixture fixture;
    f5_setup(&fixture);
    if (bbe_f5_trainability_config_error(&fixture.env) != NULL) return 2;
    c_reset(&fixture.env);
    uint64_t dice = 0;
    bb_rng_set_sink(&fixture.env.rng, f5_die_sink, &dice);

    printf("{\"schema\":\"bloodbowl-f5-reference-diagnostic-v1\",");
    printf("\"fixture_role\":\"%s\",", PUFFER_QUALIFICATION_FIXTURE_ROLE);
    printf("\"transitions\":[");
    for (int step = 0; step < F5_DECISIONS; step++) {
        Bloodbowl* env = &fixture.env;
        char match_before[65];
        char obs_home[65];
        char obs_away[65];
        char mask_home[65];
        char mask_away[65];
        f5_hash(&env->match, sizeof env->match, match_before);
        f5_hash(fixture.obs, BBE_OBS_SIZE, obs_home);
        f5_hash(fixture.obs + BBE_OBS_SIZE, BBE_OBS_SIZE, obs_away);
        f5_hash(fixture.mask, BBE_MASK_SIZE, mask_home);
        f5_hash(
            fixture.mask + BBE_MASK_SIZE, BBE_MASK_SIZE, mask_away);

        const int* heads = f5_reference_heads[step];
        unsigned char type_support[BBE_HEAD_TYPE];
        unsigned char arg_support[BBE_HEAD_ARG];
        unsigned char square_support[BBE_HEAD_SQ];
        int type_count =
            f5_support(env, 0, 0, 32, type_support, BBE_HEAD_TYPE);
        int arg_count = f5_support(
            env, 1, heads[0], 32, arg_support, BBE_HEAD_ARG);
        int square_count = f5_support(
            env, 2, heads[0], heads[1],
            square_support, BBE_HEAD_SQ);
        int support_valid =
            type_count > 0 && arg_count > 0 && square_count > 0 &&
            type_support[heads[0]] && arg_support[heads[1]] &&
            square_support[heads[2]];
        int waiting_singleton =
            f5_waiting_mask_is_singleton(&fixture, BB_AWAY);
        uint64_t dice_before = dice;
        int illegal_before = env->illegal;
        int collision_before = env->illegal_projection_collision;
        if (!support_valid ||
            f5_apply_heads(&fixture, heads) != 0) {
            return 2;
        }
        if (step != 0) printf(",");
        printf(
            "{\"decision\":%d,\"heads\":[%d,%d,%d],"
            "\"decision_team\":%d,\"support_counts\":[%d,%d,%d],"
            "\"waiting_singleton\":%s,"
            "\"match_before_sha256\":\"%s\","
            "\"obs_sha256\":[\"%s\",\"%s\"],"
            "\"mask_sha256\":[\"%s\",\"%s\"],"
            "\"rewards\":[%.9g,%.9g],\"terminals\":[%.9g,%.9g],"
            "\"dice\":%" PRIu64 ",\"illegal\":%d,\"collisions\":%d}",
            step + 1,
            heads[0], heads[1], heads[2],
            BB_HOME,
            type_count, arg_count, square_count,
            waiting_singleton ? "true" : "false",
            match_before,
            obs_home, obs_away,
            mask_home, mask_away,
            fixture.rewards[BB_HOME], fixture.rewards[BB_AWAY],
            fixture.terminals[BB_HOME], fixture.terminals[BB_AWAY],
            dice - dice_before,
            env->illegal - illegal_before,
            env->illegal_projection_collision - collision_before);
    }
    char autoreset_match[65];
    f5_hash(&fixture.env.match, sizeof fixture.env.match, autoreset_match);
    printf(
        "],\"summary\":{\"completed_episodes\":%.0f,"
        "\"tds_t0\":%.0f,\"tds_t1\":%.0f,\"episode_length\":%.0f,"
        "\"dice\":%" PRIu64 ",\"illegal\":%d,\"collisions\":%d,"
        "\"illegal_fraction\":%.9g,\"error_episodes\":%.0f,"
        "\"demo_episodes\":%.0f,\"state_bank_config_episodes\":%.0f,"
        "\"reward_samples\":%.0f,\"reward_nonzero_samples\":%.0f,"
        "\"reward_clipped_samples\":%.0f,"
        "\"reward_nonfinite_samples\":%.0f,"
        "\"reward_clip_episodes\":%.0f,"
        "\"reward_nonfinite_episodes\":%.0f,"
        "\"reward_component_touchdown\":%.9g,"
        "\"reward_component_residual\":%.9g,"
        "\"reward_component_mismatch_samples\":%.0f,"
        "\"reward_component_nonfinite_samples\":%.0f,"
        "\"reward_terminal_suppressed_signed\":%.9g,"
        "\"reward_terminal_suppressed_abs\":%.9g,"
        "\"reward_postclip_return\":%.9g,"
        "\"autoreset_match_sha256\":\"%s\"}}\n",
        fixture.env.log.n,
        fixture.env.log.tds_t0,
        fixture.env.log.tds_t1,
        fixture.env.log.episode_length,
        dice,
        fixture.env.illegal,
        fixture.env.illegal_projection_collision,
        fixture.env.log.illegal_frac,
        fixture.env.log.error_episodes,
        fixture.env.log.demo_episodes,
        fixture.env.log.state_bank_config_episodes,
        fixture.env.log.reward_samples,
        fixture.env.log.reward_nonzero_samples,
        fixture.env.log.reward_clipped_samples,
        fixture.env.log.reward_nonfinite_samples,
        fixture.env.log.reward_clip_episodes,
        fixture.env.log.reward_nonfinite_episodes,
        fixture.env.log.reward_component[BBE_REWARD_TOUCHDOWN],
        fixture.env.log.reward_component_residual,
        fixture.env.log.reward_component_mismatch_samples,
        fixture.env.log.reward_component_nonfinite_samples,
        fixture.env.log.reward_terminal_suppressed_signed,
        fixture.env.log.reward_terminal_suppressed_abs,
        fixture.env.log.reward_postclip_return,
        autoreset_match);
    return 0;
}

static int f5_replay_move_prefix(
        const int squares[F5_MOVE_STEPS],
        int count,
        f5_fixture* fixture,
        uint64_t* dice) {
    f5_setup(fixture);
    c_reset(&fixture->env);
    *dice = 0;
    bb_rng_set_sink(&fixture->env.rng, f5_die_sink, dice);
    if (f5_apply_heads(fixture, f5_reference_heads[0]) != 0 ||
        f5_apply_heads(fixture, f5_reference_heads[1]) != 0) {
        return -1;
    }
    for (int i = 0; i < count; i++) {
        const int heads[3] = {9, 32, squares[i]};
        if (f5_apply_heads(fixture, heads) != 0) return -1;
    }
    return 0;
}

static uint64_t f5_selected_probability_denominator(
        const f5_fixture* fixture,
        const int heads[3]) {
    unsigned char type_support[BBE_HEAD_TYPE];
    unsigned char arg_support[BBE_HEAD_ARG];
    unsigned char square_support[BBE_HEAD_SQ];
    int type_count = f5_support(
        &fixture->env, 0, 0, 32, type_support, BBE_HEAD_TYPE);
    int arg_count = f5_support(
        &fixture->env, 1, heads[0], 32, arg_support, BBE_HEAD_ARG);
    int square_count = f5_support(
        &fixture->env, 2, heads[0], heads[1],
        square_support, BBE_HEAD_SQ);
    if (type_count <= 0 || arg_count <= 0 || square_count <= 0 ||
        !type_support[heads[0]] || !arg_support[heads[1]] ||
        !square_support[heads[2]]) {
        return 0;
    }
    return (uint64_t)type_count * (uint64_t)arg_count *
        (uint64_t)square_count;
}

static long double f5_selected_probability(
        const f5_fixture* fixture,
        const int heads[3]) {
    uint64_t denominator =
        f5_selected_probability_denominator(fixture, heads);
    return denominator == 0
        ? 0.0L : 1.0L / (long double)denominator;
}

static void f5_enumerate_moves(
        int squares[F5_MOVE_STEPS],
        int depth,
        long double probability,
        f5_fraction exact_probability,
        f5_enumeration* result) {
    f5_fixture state;
    uint64_t dice = 0;
    if (f5_replay_move_prefix(squares, depth, &state, &dice) != 0) {
        result->failed = 1;
        return;
    }
    result->nodes++;
    if (dice != 0 || state.terminals[BB_HOME] != 0.0f) return;

    unsigned char type_support[BBE_HEAD_TYPE];
    unsigned char arg_support[BBE_HEAD_ARG];
    unsigned char square_support[BBE_HEAD_SQ];
    int type_count = f5_support(
        &state.env, 0, 0, 32, type_support, BBE_HEAD_TYPE);
    int arg_count = f5_support(
        &state.env, 1, 9, 32, arg_support, BBE_HEAD_ARG);
    int square_count = f5_support(
        &state.env, 2, 9, 32, square_support, BBE_HEAD_SQ);
    if (type_count <= 0 || arg_count <= 0 || square_count <= 0 ||
        !type_support[9] || !arg_support[32]) {
        return;
    }
    long double branch_probability =
        probability / (long double)type_count /
        (long double)arg_count / (long double)square_count;
    f5_fraction exact_branch_probability;
    uint64_t branch_denominator =
        (uint64_t)type_count * (uint64_t)arg_count *
        (uint64_t)square_count;
    if (f5_fraction_divide(
            exact_probability, branch_denominator,
            &exact_branch_probability) != 0) {
        result->failed = 1;
        return;
    }
    for (int square = 0; square < BBE_HEAD_SQ; square++) {
        if (!square_support[square]) continue;
        squares[depth] = square;
        f5_fixture next;
        uint64_t next_dice = 0;
        if (f5_replay_move_prefix(
                squares, depth + 1, &next, &next_dice) != 0) {
            result->failed = 1;
            return;
        }
        if (next_dice != 0) continue;
        if (depth + 1 == F5_MOVE_STEPS) {
            if (next.terminals[BB_HOME] == 1.0f &&
                next.terminals[BB_AWAY] == 1.0f &&
                next.rewards[BB_HOME] == 1.0f &&
                next.rewards[BB_AWAY] == -1.0f &&
                next.env.log.n == 1.0f &&
                next.env.log.tds_t0 == 1.0f &&
                next.env.log.tds_t1 == 0.0f &&
                next.env.log.episode_length == 8.0f &&
                next.env.log.illegal_frac == 0.0f &&
                next.env.log.error_episodes == 0.0f &&
                next.env.log.reward_nonfinite_samples == 0.0f &&
                next.env.log.reward_component_mismatch_samples == 0.0f &&
                next.env.log.reward_component_nonfinite_samples == 0.0f &&
                next.env.log.reward_component_residual == 0.0f &&
                next.env.log.reward_component[BBE_REWARD_TOUCHDOWN] == 1.0f) {
                f5_fraction sum;
                if (f5_fraction_add(
                        result->exact_probability,
                        exact_branch_probability, &sum) != 0) {
                    result->failed = 1;
                    return;
                }
                result->trajectories++;
                result->probability += branch_probability;
                result->exact_probability = sum;
            }
            continue;
        }
        if (next.terminals[BB_HOME] == 0.0f) {
            f5_enumerate_moves(
                squares, depth + 1, branch_probability,
                exact_branch_probability, result);
            if (result->failed) return;
        }
    }
}

static int f5_enumerate(void) {
    f5_fixture fixture;
    f5_setup(&fixture);
    c_reset(&fixture.env);
    uint64_t first_denominator =
        f5_selected_probability_denominator(
            &fixture, f5_reference_heads[0]);
    long double first =
        f5_selected_probability(&fixture, f5_reference_heads[0]);
    if (first_denominator == 0 || first == 0.0L ||
        f5_apply_heads(&fixture, f5_reference_heads[0]) != 0) {
        return 2;
    }
    uint64_t second_denominator =
        f5_selected_probability_denominator(
            &fixture, f5_reference_heads[1]);
    long double second =
        f5_selected_probability(&fixture, f5_reference_heads[1]);
    if (second_denominator == 0 || second == 0.0L) return 2;

    int squares[F5_MOVE_STEPS] = {0};
    f5_enumeration result = {
        .exact_probability = {0, 1},
    };
    f5_fraction exact_prefix = {1, 1};
    if (f5_fraction_divide(
            exact_prefix, first_denominator, &exact_prefix) != 0 ||
        f5_fraction_divide(
            exact_prefix, second_denominator, &exact_prefix) != 0) {
        return 2;
    }
    f5_enumerate_moves(
        squares, 0, first * second, exact_prefix, &result);
    if (result.failed) return 2;

    long double selected = first * second;
    f5_fraction exact_selected = exact_prefix;
    f5_fixture selected_state;
    f5_setup(&selected_state);
    c_reset(&selected_state.env);
    uint64_t selected_dice = 0;
    bb_rng_set_sink(
        &selected_state.env.rng, f5_die_sink, &selected_dice);
    for (int i = 0; i < F5_DECISIONS; i++) {
        uint64_t denominator =
            f5_selected_probability_denominator(
                &selected_state, f5_reference_heads[i]);
        long double p = f5_selected_probability(
            &selected_state, f5_reference_heads[i]);
        if (denominator == 0 || p == 0.0L) return 2;
        if (i >= 2) {
            selected *= p;
            if (f5_fraction_divide(
                    exact_selected, denominator,
                    &exact_selected) != 0) {
                return 2;
            }
        }
        if (f5_apply_heads(
                &selected_state, f5_reference_heads[i]) != 0) {
            return 2;
        }
    }
    if (selected_dice != 0 ||
        selected_state.rewards[BB_HOME] != 1.0f ||
        selected_state.rewards[BB_AWAY] != -1.0f ||
        selected_state.terminals[BB_HOME] != 1.0f ||
        selected_state.terminals[BB_AWAY] != 1.0f ||
        selected_state.env.log.n != 1.0f ||
        selected_state.env.log.tds_t0 != 1.0f ||
        selected_state.env.log.tds_t1 != 0.0f ||
        selected_state.env.log.episode_length != 8.0f ||
        selected_state.env.log.illegal_frac != 0.0f ||
        selected_state.env.log.error_episodes != 0.0f ||
        selected_state.env.log.reward_nonfinite_samples != 0.0f ||
        selected_state.env.log.reward_component_mismatch_samples != 0.0f ||
        selected_state.env.log.reward_component_nonfinite_samples != 0.0f ||
        selected_state.env.log.reward_component_residual != 0.0f ||
        selected_state.env.log.reward_component[BBE_REWARD_TOUCHDOWN] !=
            1.0f) {
        return 2;
    }
    if (result.exact_probability.denominator == 0 ||
        !isfinite((double)f5_fraction_long_double(
            result.exact_probability)) ||
        fabsl(
            result.probability -
            f5_fraction_long_double(result.exact_probability)) > 1e-20L ||
        fabsl(
            selected -
            f5_fraction_long_double(exact_selected)) > 1e-20L) {
        return 2;
    }
    char safe_numerator[40];
    char safe_denominator[40];
    char selected_numerator[40];
    char selected_denominator_text[40];
    f5_u128_decimal(
        result.exact_probability.numerator, safe_numerator);
    f5_u128_decimal(
        result.exact_probability.denominator, safe_denominator);
    f5_u128_decimal(exact_selected.numerator, selected_numerator);
    f5_u128_decimal(
        exact_selected.denominator, selected_denominator_text);
    printf(
        "{\"schema\":\"bloodbowl-f5-safe-enumeration-v1\","
        "\"safe_zero_dice_trajectories\":%" PRIu64 ","
        "\"safe_probability\":%.21Lg,"
        "\"safe_probability_numerator\":%s,"
        "\"safe_probability_denominator\":%s,"
        "\"selected_probability\":%.21Lg,"
        "\"selected_probability_numerator\":%s,"
        "\"selected_probability_denominator\":%s,"
        "\"nodes\":%" PRIu64 "}\n",
        result.trajectories,
        result.probability,
        safe_numerator,
        safe_denominator,
        selected,
        selected_numerator,
        selected_denominator_text,
        result.nodes);
    return 0;
}

static uint64_t f5_sampler_next(f5_sampler* sampler) {
    uint64_t value = sampler->state;
    value ^= value >> 12;
    value ^= value << 25;
    value ^= value >> 27;
    sampler->state = value;
    return value * UINT64_C(2685821657736338717);
}

static uint32_t f5_sampler_below(f5_sampler* sampler, uint32_t bound) {
    if (bound == 0) abort();
    uint64_t threshold = (UINT64_MAX - (uint64_t)bound + 1u) %
        (uint64_t)bound;
    uint64_t value;
    do {
        value = f5_sampler_next(sampler);
    } while (value < threshold);
    return (uint32_t)(value % bound);
}

static int f5_sample_support(
        f5_sampler* sampler,
        const unsigned char* support,
        int size,
        int count) {
    if (count <= 0) return -1;
    uint32_t selected = f5_sampler_below(sampler, (uint32_t)count);
    for (int i = 0; i < size; i++) {
        if (support[i] && selected-- == 0) return i;
    }
    return -1;
}

static int f5_sample_action(
        f5_fixture* fixture, f5_sampler* sampler, int team) {
    unsigned char type_support[BBE_HEAD_TYPE];
    unsigned char arg_support[BBE_HEAD_ARG];
    unsigned char square_support[BBE_HEAD_SQ];
    int type_count = bbe_fill_joint_head_mask(
        &fixture->env, team, 0, 0, 32,
        type_support, BBE_HEAD_TYPE);
    int type = f5_sample_support(
        sampler, type_support, BBE_HEAD_TYPE, type_count);
    if (type < 0) return -1;
    int arg_count = bbe_fill_joint_head_mask(
        &fixture->env, team, 1, type, 32,
        arg_support, BBE_HEAD_ARG);
    int arg = f5_sample_support(
        sampler, arg_support, BBE_HEAD_ARG, arg_count);
    if (arg < 0) return -1;
    int square_count = bbe_fill_joint_head_mask(
        &fixture->env, team, 2, type, arg,
        square_support, BBE_HEAD_SQ);
    int square = f5_sample_support(
        sampler, square_support, BBE_HEAD_SQ, square_count);
    if (square < 0) return -1;
    fixture->env.action_ptr[team][0] = (float)type;
    fixture->env.action_ptr[team][1] = (float)arg;
    fixture->env.action_ptr[team][2] = (float)square;
    return 0;
}

static int f5_parse_u64(const char* raw, uint64_t* value) {
    if (raw == NULL || raw[0] == '\0' || raw[0] == '-' ||
        (raw[0] == '0' && raw[1] != '\0')) {
        return -1;
    }
    errno = 0;
    char* end = NULL;
    unsigned long long parsed = strtoull(raw, &end, 10);
    if (errno != 0 || end == raw || *end != '\0') return -1;
    *value = (uint64_t)parsed;
    return 0;
}

static int f5_random(uint64_t episode_target, uint64_t seed) {
    if (episode_target == 0 ||
        episode_target > F5_RANDOM_EPISODE_LIMIT ||
        seed == 0) {
        return 2;
    }
    f5_fixture fixture;
    f5_setup(&fixture);
    c_reset(&fixture.env);
    bb_match reset_match = fixture.env.match;
    uint8_t reset_obs[sizeof fixture.obs];
    unsigned char reset_mask[sizeof fixture.mask];
    memcpy(reset_obs, fixture.obs, sizeof reset_obs);
    memcpy(reset_mask, fixture.mask, sizeof reset_mask);
    int reset_n_legal = fixture.env.n_legal;
    bb_action reset_legal[BB_LEGAL_MAX];
    uint8_t reset_legal_arg[BB_LEGAL_MAX];
    uint16_t reset_legal_sq[BB_LEGAL_MAX];
    if (reset_n_legal <= 0 || reset_n_legal > BB_LEGAL_MAX) return 2;
    memcpy(reset_legal, fixture.env.legal,
           (size_t)reset_n_legal * sizeof reset_legal[0]);
    memcpy(reset_legal_arg, fixture.env.legal_arg,
           (size_t)reset_n_legal * sizeof reset_legal_arg[0]);
    memcpy(reset_legal_sq, fixture.env.legal_sq,
           (size_t)reset_n_legal * sizeof reset_legal_sq[0]);
    uint64_t dice = 0;
    bb_rng_set_sink(&fixture.env.rng, f5_die_sink, &dice);
    f5_sampler sampler = {seed};
    uint64_t episodes = 0;
    uint64_t decisions = 0;
    uint64_t agent_steps = 0;
    uint64_t successes = 0;
    uint64_t away_tds = 0;
    uint64_t early_terminals = 0;
    uint64_t illegal = 0;
    uint64_t collisions = 0;
    uint64_t test_windows = 0;
    uint64_t fixture_resets = 1;
    uint64_t length_histogram[F5_DECISIONS + 1] = {0};
    int current_length = 0;
    long double reward_home = 0.0L;
    long double reward_away = 0.0L;
    double previous_home_tds = fixture.env.log.tds_t0;
    double previous_away_tds = fixture.env.log.tds_t1;

    while (episodes < episode_target) {
        int team = fixture.env.match.decision_team;
        if (team != BB_HOME && team != BB_AWAY) return 2;
        if (fixture.env.match.stack_top > 0 &&
            fixture.env.match.stack[
                fixture.env.match.stack_top - 1].proc == BB_PROC_TEST) {
            test_windows++;
        }
        if (f5_sample_action(&fixture, &sampler, team) != 0) return 2;
        int waiting = 1 - team;
        fixture.env.action_ptr[waiting][0] = (float)BB_A_NONE;
        fixture.env.action_ptr[waiting][1] = 32.0f;
        fixture.env.action_ptr[waiting][2] = 390.0f;
        c_step(&fixture.env);
        decisions++;
        agent_steps += BBE_AGENTS;
        current_length++;
        const float home_reward = fixture.rewards[BB_HOME];
        const float away_reward = fixture.rewards[BB_AWAY];
        const float home_terminal = fixture.terminals[BB_HOME];
        const float away_terminal = fixture.terminals[BB_AWAY];
        if (!isfinite(home_reward) || !isfinite(away_reward) ||
            (home_terminal != 0.0f && home_terminal != 1.0f) ||
            away_terminal != home_terminal ||
            home_reward + away_reward != 0.0f ||
            !((home_reward == 0.0f && away_reward == 0.0f) ||
              (home_reward == 1.0f && away_reward == -1.0f) ||
              (home_reward == -1.0f && away_reward == 1.0f)) ||
            (home_reward != 0.0f && home_terminal != 1.0f)) {
            return 2;
        }
        reward_home += home_reward;
        reward_away += away_reward;
        illegal += (uint64_t)(fixture.env.illegal != 0);
        collisions +=
            (uint64_t)(fixture.env.illegal_projection_collision != 0);
        if (home_terminal != 0.0f) {
            if (current_length < 1 || current_length > F5_DECISIONS) {
                return 2;
            }
            episodes++;
            fixture_resets++;
            length_histogram[current_length]++;
            if (current_length < F5_DECISIONS) early_terminals++;
            double home_tds = fixture.env.log.tds_t0;
            double away_total = fixture.env.log.tds_t1;
            if (home_tds < previous_home_tds ||
                away_total < previous_away_tds) {
                return 2;
            }
            successes +=
                (uint64_t)llround(home_tds - previous_home_tds);
            away_tds +=
                (uint64_t)llround(away_total - previous_away_tds);
            previous_home_tds = home_tds;
            previous_away_tds = away_total;
            current_length = 0;
            if (memcmp(
                    &fixture.env.match, &reset_match,
                    sizeof reset_match) != 0 ||
                memcmp(fixture.obs, reset_obs, sizeof reset_obs) != 0 ||
                memcmp(fixture.mask, reset_mask, sizeof reset_mask) != 0 ||
                fixture.env.n_legal != reset_n_legal ||
                memcmp(
                    fixture.env.legal, reset_legal,
                    (size_t)reset_n_legal * sizeof reset_legal[0]) != 0 ||
                memcmp(
                    fixture.env.legal_arg, reset_legal_arg,
                    (size_t)reset_n_legal * sizeof reset_legal_arg[0]) != 0 ||
                memcmp(
                    fixture.env.legal_sq, reset_legal_sq,
                    (size_t)reset_n_legal * sizeof reset_legal_sq[0]) != 0) {
                return 2;
            }
            bb_rng_set_sink(&fixture.env.rng, f5_die_sink, &dice);
        }
    }
    /* The final automatic reset is observable but is not a started sample. */
    if (fixture_resets > 0) fixture_resets--;
    if (fixture.env.log.n != (float)episode_target ||
        fixture.env.log.tds_t0 != (float)successes ||
        fixture.env.log.tds_t1 != (float)away_tds ||
        fixture.env.log.illegal_frac != 0.0f ||
        fixture.env.log.error_episodes != 0.0f ||
        fixture.env.log.demo_episodes != 0.0f ||
        fixture.env.log.state_bank_config_episodes != 0.0f ||
        fixture.env.log.reward_clipped_samples != 0.0f ||
        fixture.env.log.reward_nonfinite_samples != 0.0f ||
        fixture.env.log.reward_clip_episodes != 0.0f ||
        fixture.env.log.reward_nonfinite_episodes != 0.0f ||
        fixture.env.log.reward_clip_excess != 0.0f ||
        fixture.env.log.reward_clip_terminal_samples != 0.0f ||
        fixture.env.log.reward_clip_nonterminal_samples != 0.0f ||
        fixture.env.log.reward_clip_signed_delta != 0.0f ||
        fixture.env.log.reward_component_mismatch_samples != 0.0f ||
        fixture.env.log.reward_component_nonfinite_samples != 0.0f ||
        fixture.env.log.reward_component_residual != 0.0f ||
        fixture.env.log.reward_terminal_suppressed_signed != 0.0f ||
        fixture.env.log.reward_terminal_suppressed_abs != 0.0f ||
        fixture.env.log.reward_samples != (float)(BBE_AGENTS * decisions) ||
        fixture.env.log.reward_nonzero_samples !=
            (float)(BBE_AGENTS * (successes + away_tds)) ||
        fixture.env.log.demo_fallbacks != 0.0f ||
        fixture.env.log.demo_uniform_episodes != 0.0f ||
        fixture.env.log.demo_endzone_episodes != 0.0f ||
        fixture.env.log.demo_pickup_episodes != 0.0f ||
        fixture.env.log.demo_postkick_episodes != 0.0f ||
        fixture.env.log.demo_pass_episodes != 0.0f ||
        fixture.env.log.demo_selector_threshold_configured != 0.0f ||
        fixture.env.log.demo_selector_eligible_configured != 0.0f ||
        fixture.env.log.statmatch_term != 0.0f ||
        fixture.env.log.reward_postclip_return !=
            (float)((long double)successes - (long double)away_tds) ||
        fixture.env.log.reward_component[BBE_REWARD_TOUCHDOWN] !=
            (float)((long double)successes - (long double)away_tds)) {
        return 2;
    }
    for (int component = 0;
         component < BBE_REWARD_COMPONENT_COUNT;
         component++) {
        if (component != BBE_REWARD_TOUCHDOWN &&
            fixture.env.log.reward_component[component] != 0.0f) {
            return 2;
        }
    }
    for (int bank = 0; bank < BBE_MAX_BANKS; bank++) {
        if (fixture.env.log.hist_n_bank[bank] != 0.0f ||
            fixture.env.log.hist_score_bank[bank] != 0.0f) {
            return 2;
        }
    }
    printf(
        "{\"schema\":\"bloodbowl-f5-random-baseline-v1\","
        "\"seed\":%" PRIu64 ",\"episodes\":%" PRIu64 ","
        "\"decisions\":%" PRIu64 ",\"agent_steps\":%" PRIu64 ","
        "\"successes\":%" PRIu64 ",\"tds_t1\":%" PRIu64 ","
        "\"early_terminals\":%" PRIu64 ","
        "\"illegal\":%" PRIu64 ",\"collisions\":%" PRIu64 ","
        "\"dice\":%" PRIu64 ",\"test_windows\":%" PRIu64 ","
        "\"fixture_resets\":%" PRIu64 ","
        "\"reward_totals\":[%.21Lg,%.21Lg],\"episode_lengths\":[",
        seed,
        episodes,
        decisions,
        agent_steps,
        successes,
        away_tds,
        early_terminals,
        illegal,
        collisions,
        dice,
        test_windows,
        fixture_resets,
        reward_home,
        reward_away);
    for (int length = 1; length <= F5_DECISIONS; length++) {
        if (length != 1) printf(",");
        printf("%" PRIu64, length_histogram[length]);
    }
    printf("]}\n");
    return 0;
}

static void f5_usage(const char* program) {
    fprintf(
        stderr,
        "usage: %s reference | enumerate | "
        "random --episodes N --seed N\n",
        program);
}

int main(int argc, char** argv) {
    if (argc == 2 && strcmp(argv[1], "reference") == 0) {
        return f5_reference();
    }
    if (argc == 2 && strcmp(argv[1], "enumerate") == 0) {
        return f5_enumerate();
    }
    if (argc == 6 && strcmp(argv[1], "random") == 0 &&
        strcmp(argv[2], "--episodes") == 0 &&
        strcmp(argv[4], "--seed") == 0) {
        uint64_t episodes = 0;
        uint64_t seed = 0;
        if (f5_parse_u64(argv[3], &episodes) != 0 ||
            f5_parse_u64(argv[5], &seed) != 0) {
            f5_usage(argv[0]);
            return 2;
        }
        return f5_random(episodes, seed);
    }
    f5_usage(argv[0]);
    return 2;
}
