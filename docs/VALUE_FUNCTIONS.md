# Blood Bowl Value Functions & Expected Value Calculations

## Philosophy: Reward Decision Quality, Not Dice Outcomes

The fundamental insight for Blood Bowl RL is that we must **reward the Expected Value (EV) of decisions**, not the stochastic outcomes. A 1-die block that rolls Attacker Down was still a bad decision to make; a 3-die block that rolls a Push was still a good decision.

This document provides comprehensive EV calculations for all major decision points.

---

## Part 1: The Central Value Function

### 1.1 Win Probability as Ultimate Value

Everything in Blood Bowl should ultimately tie back to **Win Probability (WP)**. The agent's objective is to maximize WP.

```c
// Primary value function: P(Win | State)
float win_probability(GameState *state, int team) {
    // Start at 50%
    float wp = 0.5f;

    // === SCORE DIFFERENTIAL (Biggest factor) ===
    int score_diff = state->score[team] - state->score[1-team];
    int turns_remaining = 16 - state->turn_number;
    int half = state->half;  // 1 or 2

    // Each TD is worth different amounts based on time remaining
    // Early game: TD worth ~10-15% WP
    // Late game: TD worth ~20-30% WP (harder to catch up)
    float td_value = 0.15f + 0.15f * (1.0f - turns_remaining / 16.0f);

    // Being ahead is better than you might think (cascade effects)
    if (score_diff > 0) {
        wp += td_value * score_diff * 1.1f;  // Slight bonus for being ahead
    } else if (score_diff < 0) {
        wp += td_value * score_diff * 0.9f;  // Slightly easier to catch up
    }

    // === BALL CONTROL ===
    int ball_carrier = state->ball_carrier;
    if (ball_carrier >= 0) {
        if (state->player_team[ball_carrier] == team) {
            wp += 0.08f;  // Having ball is worth ~8% WP
        } else {
            wp -= 0.08f;
        }
    } else {
        // Loose ball - slight advantage to team that can grab it
        // (depends on board position, simplify here)
        wp += 0.01f * (count_players_near_ball(state, team) -
                        count_players_near_ball(state, 1-team));
    }

    // === PLAYER COUNT ADVANTAGE ===
    int our_players = count_standing_players(state, team);
    int their_players = count_standing_players(state, 1-team);
    int player_diff = our_players - their_players;

    // Each player is worth ~2-3% WP
    wp += player_diff * 0.025f;

    // === POSITIONAL ADVANTAGE ===
    float our_position = compute_positional_value(state, team);
    float their_position = compute_positional_value(state, 1-team);
    wp += (our_position - their_position) * 0.05f;

    // === RESOURCE ADVANTAGE ===
    float our_resources = state->rerolls[team] * 0.02f +
                          state->apothecary[team] * 0.03f;
    float their_resources = state->rerolls[1-team] * 0.02f +
                            state->apothecary[1-team] * 0.03f;
    wp += our_resources - their_resources;

    // === RECEIVING IN SECOND HALF ===
    if (half == 1 && state->receiving_team[1] == team) {
        wp += 0.03f;  // Slight advantage if we receive in 2nd half
    }

    return clamp(wp, 0.01f, 0.99f);
}
```

### 1.2 Conversion to Game-Theoretic Value

For self-play, we use a zero-sum formulation:

```c
// Value from team 0's perspective (team 1 is negative)
float game_value(GameState *state) {
    float wp = win_probability(state, 0);
    // Convert to [-1, 1] range
    return 2.0f * wp - 1.0f;
}

// Action value = immediate reward + gamma * future value
float action_value(GameState *state, Action action, Policy *policy) {
    // Simulate action (stochastically)
    GameState next_state;
    float immediate_reward;

    // Take expectation over stochastic outcomes
    float expected_value = 0.0f;
    OutcomeDistribution outcomes = get_action_outcomes(state, action);

    for (int i = 0; i < outcomes.count; i++) {
        simulate_outcome(state, action, outcomes.outcome[i], &next_state, &immediate_reward);

        float future_value = 0.0f;
        if (!next_state.is_terminal) {
            // Recursive evaluation (or use learned value function)
            future_value = evaluate_state(policy, &next_state);
        }

        expected_value += outcomes.probability[i] *
                          (immediate_reward + GAMMA * future_value);
    }

    return expected_value;
}
```

---

## Part 2: Block Expected Value (The Core Calculation)

Blocking is the most important and complex calculation in Blood Bowl.

### 2.1 Complete Block EV Model

```c
typedef struct {
    float p_defender_down;      // Probability defender ends up down
    float p_defender_removal;   // Probability defender is removed from game
    float p_push;               // Probability of push (no knockdown)
    float p_attacker_down;      // Probability attacker ends up down
    float p_turnover;           // Probability this causes turnover
    float p_both_down;          // Probability both are down
    float expected_surf;        // Probability of pushing into crowd
} BlockOutcome;

// Pre-computed block die face distribution
// Die faces: Attacker Down (1), Both Down (1), Push (1), Stumble (1), POW (2)
typedef struct {
    int attacker_down;  // Count of AD faces shown
    int both_down;      // Count of BD faces shown
    int push;           // Count of Push faces shown
    int stumble;        // Count of Stumble faces shown
    int pow;            // Count of POW faces shown
} DieRoll;

// All possible outcomes for N dice
void compute_block_ev(
    GameState *state,
    int attacker_id,
    int defender_id,
    int num_dice,              // +N = attacker chooses, -N = defender chooses
    bool attacker_has_block,
    bool attacker_has_wrestle,
    bool defender_has_block,
    bool defender_has_dodge,
    bool defender_has_wrestle,
    bool defender_has_stand_firm,
    bool defender_has_fend,
    bool attacker_has_frenzy,
    bool defender_has_sidestep,
    int defender_av,
    bool attacker_has_mighty_blow,
    bool attacker_has_claw,
    BlockOutcome *result
) {
    memset(result, 0, sizeof(BlockOutcome));

    int abs_dice = abs(num_dice);
    bool we_choose = (num_dice > 0);

    // Enumerate all die combinations
    int total_outcomes = pow(6, abs_dice);

    for (int outcome_idx = 0; outcome_idx < total_outcomes; outcome_idx++) {
        // Decode die faces
        int faces[3] = {0};
        int temp = outcome_idx;
        for (int d = 0; d < abs_dice; d++) {
            faces[d] = temp % 6;
            temp /= 6;
        }

        // If we choose, pick best die. If they choose, they pick worst for us.
        int best_face = faces[0];
        for (int d = 1; d < abs_dice; d++) {
            if (we_choose) {
                // We want: POW > Stumble > Push > Both Down > Attacker Down
                if (die_value_for_attacker(faces[d]) >
                    die_value_for_attacker(best_face)) {
                    best_face = faces[d];
                }
            } else {
                // They pick worst for us
                if (die_value_for_attacker(faces[d]) <
                    die_value_for_attacker(best_face)) {
                    best_face = faces[d];
                }
            }
        }

        float outcome_prob = 1.0f / total_outcomes;

        // Process the selected die face
        switch (best_face) {
            case DIE_POW_1:
            case DIE_POW_2:
                // Defender knocked down
                result->p_defender_down += outcome_prob;
                break;

            case DIE_STUMBLE:
                if (defender_has_dodge && !attacker_has_tackle(state, attacker_id)) {
                    // Dodge converts stumble to push
                    result->p_push += outcome_prob;
                } else {
                    result->p_defender_down += outcome_prob;
                }
                break;

            case DIE_PUSH:
                result->p_push += outcome_prob;
                break;

            case DIE_BOTH_DOWN:
                // Complex interaction of skills
                bool attacker_falls = !attacker_has_block && !attacker_has_wrestle;
                bool defender_falls = !defender_has_block && !defender_has_wrestle;

                if (attacker_has_wrestle || defender_has_wrestle) {
                    // Wrestle: both go down, but NOT a turnover
                    if (attacker_has_wrestle && !defender_has_block) {
                        result->p_defender_down += outcome_prob;
                        result->p_attacker_down += outcome_prob;
                        // NOT a turnover if attacker chose to wrestle
                    } else if (defender_has_wrestle && !attacker_has_block) {
                        result->p_defender_down += outcome_prob;
                        result->p_attacker_down += outcome_prob;
                        // IS a turnover
                        result->p_turnover += outcome_prob;
                    }
                    // Both have Block: push result
                    else if (attacker_has_block && defender_has_block) {
                        result->p_push += outcome_prob;
                    }
                } else {
                    // Standard both down
                    if (attacker_has_block && !defender_has_block) {
                        result->p_defender_down += outcome_prob;
                    } else if (!attacker_has_block && defender_has_block) {
                        result->p_attacker_down += outcome_prob;
                        result->p_turnover += outcome_prob;
                    } else if (attacker_has_block && defender_has_block) {
                        result->p_push += outcome_prob;
                    } else {
                        result->p_both_down += outcome_prob;
                        result->p_turnover += outcome_prob;
                    }
                }
                break;

            case DIE_ATTACKER_DOWN:
                result->p_attacker_down += outcome_prob;
                result->p_turnover += outcome_prob;
                break;
        }
    }

    // Compute removal probability from knockdowns
    if (result->p_defender_down > 0) {
        float armor_break_prob = compute_armor_break_prob(
            defender_av, attacker_has_mighty_blow, attacker_has_claw
        );
        float removal_prob = armor_break_prob * 0.417f;  // P(KO or Casualty)
        result->p_defender_removal = result->p_defender_down * removal_prob;
    }
}

// Helper: rank die faces for attacker preference
int die_value_for_attacker(int face) {
    switch (face) {
        case DIE_POW_1:
        case DIE_POW_2:     return 5;  // Best
        case DIE_STUMBLE:   return 4;
        case DIE_PUSH:      return 3;
        case DIE_BOTH_DOWN: return 2;
        case DIE_ATTACKER_DOWN: return 1;  // Worst
    }
    return 0;
}
```

### 2.2 Block EV in Value Units

Convert block probabilities to a scalar value:

```c
// Value coefficients (tunable hyperparameters)
#define V_KNOCKDOWN       0.15f   // Value of knocking down opponent
#define V_REMOVAL         0.40f   // Value of removing opponent from game
#define V_TURNOVER       -0.30f   // Cost of turnover
#define V_OUR_KNOCKDOWN  -0.10f   // Cost of our player being knocked down
#define V_OUR_REMOVAL    -0.50f   // Cost of our player being removed
#define V_SURF            0.35f   // Value of pushing into crowd (auto-injury)

float block_ev_to_value(
    BlockOutcome *outcome,
    float attacker_value,    // Gold value normalized
    float defender_value,    // Gold value normalized
    bool defender_has_ball,
    float field_position     // How close to our end zone (for surf value)
) {
    float ev = 0.0f;

    // Knockdown value (scales with defender value)
    ev += outcome->p_defender_down * V_KNOCKDOWN * defender_value;

    // Removal value (scales with defender value, huge)
    ev += outcome->p_defender_removal * V_REMOVAL * defender_value;

    // Turnover cost (scales with attacker value somewhat)
    ev += outcome->p_turnover * V_TURNOVER * (0.5f + 0.5f * attacker_value);

    // Our knockdown cost
    float our_armor_break = compute_armor_break_prob(
        /* our AV */ 9, false, false
    );
    float our_removal_risk = outcome->p_attacker_down * our_armor_break * 0.417f;
    ev += outcome->p_attacker_down * V_OUR_KNOCKDOWN * attacker_value;
    ev += our_removal_risk * V_OUR_REMOVAL * attacker_value;

    // Ball carrier bonus (forcing turnover is huge)
    if (defender_has_ball) {
        // If defender goes down, ball scatters
        ev += outcome->p_defender_down * 0.25f;
    }

    // Surf potential (edge of board)
    ev += outcome->expected_surf * V_SURF * defender_value;

    return ev;
}
```

### 2.3 Complete Block Decision Function

```c
typedef struct {
    int target_id;
    float ev;
    float risk;              // P(bad outcome for us)
    float upside;            // P(great outcome for us)
    BlockOutcome outcome;
} BlockCandidate;

void evaluate_all_blocks(
    GameState *state,
    int attacker_id,
    BlockCandidate *candidates,
    int *num_candidates
) {
    *num_candidates = 0;
    Player *attacker = &state->players[attacker_id];
    float attacker_value = attacker->gold_value / 100000.0f;

    // Find all adjacent enemies
    int adj_enemies[8];
    int num_adj = get_adjacent_enemies(state, attacker_id, adj_enemies);

    for (int i = 0; i < num_adj; i++) {
        int defender_id = adj_enemies[i];
        Player *defender = &state->players[defender_id];
        float defender_value = defender->gold_value / 100000.0f;

        // Compute dice count
        int num_dice = compute_block_dice(state, attacker_id, defender_id);

        // Get all relevant skills
        BlockOutcome outcome;
        compute_block_ev(
            state, attacker_id, defender_id, num_dice,
            has_skill(attacker, SKILL_BLOCK),
            has_skill(attacker, SKILL_WRESTLE),
            has_skill(defender, SKILL_BLOCK),
            has_skill(defender, SKILL_DODGE),
            has_skill(defender, SKILL_WRESTLE),
            has_skill(defender, SKILL_STAND_FIRM),
            has_skill(defender, SKILL_FEND),
            has_skill(attacker, SKILL_FRENZY),
            has_skill(defender, SKILL_SIDESTEP),
            defender->av,
            has_skill(attacker, SKILL_MIGHTY_BLOW),
            has_skill(attacker, SKILL_CLAW),
            &outcome
        );

        // Convert to value
        float ev = block_ev_to_value(
            &outcome,
            attacker_value,
            defender_value,
            state->ball_carrier == defender_id,
            0.5f  // Placeholder field position
        );

        candidates[*num_candidates] = (BlockCandidate){
            .target_id = defender_id,
            .ev = ev,
            .risk = outcome.p_turnover,
            .upside = outcome.p_defender_removal,
            .outcome = outcome,
        };
        (*num_candidates)++;
    }
}
```

---

## Part 3: Contextual Skill Valuation

### 3.1 Skill Value as Function of Matchup

```c
typedef struct {
    // Counts of key skills on each team
    int our_block, their_block;
    int our_dodge, their_dodge;
    int our_tackle, their_tackle;
    int our_guard, their_guard;
    int our_mighty_blow, their_mighty_blow;
    int our_claw, their_claw;
    int our_sure_hands, their_sure_hands;
    int our_strip_ball, their_strip_ball;

    // Aggregate stats
    float our_avg_st, their_avg_st;
    float our_avg_ma, their_avg_ma;
    float our_avg_av, their_avg_av;
    float our_avg_ag, their_avg_ag;

    // Derived metrics
    float bash_matchup;         // >0 if we're more bashy
    float agility_matchup;      // >0 if we're more agile
    float cage_preference;      // How much should we cage?
} MatchupContext;

void compute_matchup_context(GameState *state, int our_team, MatchupContext *ctx) {
    memset(ctx, 0, sizeof(MatchupContext));

    for (int i = 0; i < MAX_PLAYERS; i++) {
        if (state->player_team[i] == our_team) {
            ctx->our_block += has_skill(state, i, SKILL_BLOCK);
            ctx->our_dodge += has_skill(state, i, SKILL_DODGE);
            ctx->our_tackle += has_skill(state, i, SKILL_TACKLE);
            ctx->our_guard += has_skill(state, i, SKILL_GUARD);
            ctx->our_mighty_blow += has_skill(state, i, SKILL_MIGHTY_BLOW);
            ctx->our_claw += has_skill(state, i, SKILL_CLAW);
            // ... more skills
            ctx->our_avg_st += state->players[i].st;
            ctx->our_avg_ma += state->players[i].ma;
            ctx->our_avg_av += state->players[i].av;
            ctx->our_avg_ag += state->players[i].ag;
        } else {
            ctx->their_block += has_skill(state, i, SKILL_BLOCK);
            ctx->their_dodge += has_skill(state, i, SKILL_DODGE);
            ctx->their_tackle += has_skill(state, i, SKILL_TACKLE);
            // ... etc
        }
    }

    // Normalize averages
    int our_count = count_players(state, our_team);
    int their_count = count_players(state, 1 - our_team);
    ctx->our_avg_st /= our_count;
    ctx->our_avg_ma /= our_count;
    ctx->our_avg_av /= our_count;
    ctx->their_avg_st /= their_count;
    ctx->their_avg_ma /= their_count;
    ctx->their_avg_av /= their_count;

    // Derived metrics
    ctx->bash_matchup = (ctx->our_avg_st - ctx->their_avg_st) +
                        (ctx->our_block - ctx->their_block) * 0.1f +
                        (ctx->our_mighty_blow - ctx->their_mighty_blow) * 0.15f;

    ctx->agility_matchup = (ctx->their_avg_ag - ctx->our_avg_ag) +  // Lower is better
                           (ctx->our_dodge - ctx->their_dodge) * 0.1f +
                           (ctx->our_avg_ma - ctx->their_avg_ma) * 0.1f;

    ctx->cage_preference = ctx->bash_matchup * 0.5f +
                           (ctx->our_guard / (float)our_count) * 0.3f;
}

// Get the VALUE of a skill in THIS matchup
float get_skill_value_in_matchup(Skill skill, MatchupContext *ctx) {
    switch (skill) {
        case SKILL_TACKLE:
            // Tackle value = base + scaling with their dodge count
            // If opponent has NO dodge, tackle is nearly useless
            return 0.05f + 0.25f * (ctx->their_dodge / 11.0f);

        case SKILL_DODGE:
            // Dodge value = base - penalty for their tackle count
            // Against full tackle team, dodge is just +1 AG on first dodge
            return 0.35f * (1.0f - ctx->their_tackle / 11.0f) + 0.05f;

        case SKILL_GUARD:
            // Guard value = base + scaling with bash nature of matchup
            // In a cage-heavy bash mirror, guard is amazing
            return 0.20f + 0.30f * fmax(0, ctx->bash_matchup + 1.0f) / 2.0f;

        case SKILL_MIGHTY_BLOW:
            // MB value = base + inverse of their average AV
            // Against AV7 team: amazing. Against AV10: meh.
            return 0.15f + 0.25f * (9.0f - ctx->their_avg_av) / 3.0f;

        case SKILL_CLAW:
            // Claw value = HIGH against high AV (breaks 8+ regardless)
            // Against low AV team: worse than MB actually
            if (ctx->their_avg_av >= 9.0f) {
                return 0.40f + 0.1f * (ctx->their_avg_av - 9.0f);
            } else {
                return 0.20f;  // Still useful for the guarantee
            }

        case SKILL_STRIP_BALL:
            // Strip Ball value depends on their ball security
            if (ctx->their_sure_hands > 0) {
                return 0.05f;  // Blocked by Sure Hands
            }
            return 0.25f;  // Very useful otherwise

        case SKILL_BLOCK:
            // Block is universally good, slightly more in bash
            return 0.40f + 0.10f * fmax(0, ctx->bash_matchup);

        case SKILL_SURE_HANDS:
            // Sure Hands value depends on their strip ball
            return 0.20f + 0.15f * (ctx->their_strip_ball / 11.0f);

        case SKILL_SIDESTEP:
            // Sidestep better against teams that want to push you
            return 0.15f + 0.15f * fmax(0, -ctx->agility_matchup);

        case SKILL_STAND_FIRM:
            // Stand Firm is anti-positioning, good against surfing teams
            return 0.15f + 0.10f * fmax(0, ctx->bash_matchup);

        case SKILL_FRENZY:
            // Frenzy: high risk/reward, worse if they have Stand Firm
            float base = 0.20f;
            float sf_penalty = 0.15f * (ctx->their_sf / 11.0f);
            return base - sf_penalty;

        default:
            return 0.20f;  // Default skill value
    }
}
```

### 3.2 Using Matchup Context in Observations

```c
void encode_matchup_features(
    MatchupContext *ctx,
    float *features,      // Output: array of floats
    int *feature_idx      // In/out: current index
) {
    int idx = *feature_idx;

    // Raw skill counts (normalized)
    features[idx++] = ctx->our_block / 11.0f;
    features[idx++] = ctx->their_block / 11.0f;
    features[idx++] = ctx->our_dodge / 11.0f;
    features[idx++] = ctx->their_dodge / 11.0f;
    features[idx++] = ctx->our_tackle / 11.0f;
    features[idx++] = ctx->their_tackle / 11.0f;
    features[idx++] = ctx->our_guard / 11.0f;
    features[idx++] = ctx->their_guard / 11.0f;
    features[idx++] = ctx->our_mighty_blow / 11.0f;
    features[idx++] = ctx->their_mighty_blow / 11.0f;

    // Interaction features (the KEY insight)
    features[idx++] = ctx->our_tackle / fmax(1.0f, ctx->their_dodge);  // Our tackle effectiveness
    features[idx++] = ctx->their_tackle / fmax(1.0f, ctx->our_dodge);  // Their tackle effectiveness
    features[idx++] = ctx->our_mighty_blow * (9.0f - ctx->their_avg_av) / 9.0f;  // Our MB effectiveness
    features[idx++] = ctx->their_mighty_blow * (9.0f - ctx->our_avg_av) / 9.0f;  // Their MB effectiveness

    // Aggregate matchup metrics
    features[idx++] = sigmoid(ctx->bash_matchup);      // 0-1 scale
    features[idx++] = sigmoid(ctx->agility_matchup);   // 0-1 scale
    features[idx++] = sigmoid(ctx->cage_preference);   // 0-1 scale

    // Expected block outcomes (precomputed averages)
    features[idx++] = compute_avg_block_ev_for_us(ctx);
    features[idx++] = compute_avg_block_ev_against_us(ctx);

    *feature_idx = idx;
}
```

---

## Part 4: Action Sequencing Value

### 4.1 The Turnover Problem

Blood Bowl's turnover mechanic makes **action ordering critical**. Do safe actions first.

```c
typedef struct {
    int action_type;
    int player_id;
    int target;             // Square or player
    float ev;               // Expected value
    float turnover_risk;    // P(turnover)
    float importance;       // How much do we need this?
    float seq_priority;     // Combined priority for ordering
} PendingAction;

// Compute optimal action sequence
void compute_action_sequence(
    GameState *state,
    PendingAction *actions,
    int num_actions,
    int *sequence           // Output: indices in optimal order
) {
    // Score = EV * risk_adjusted_factor
    // High importance + low risk = do first
    // High importance + high risk = do last
    // Low importance + high risk = maybe don't do at all

    for (int i = 0; i < num_actions; i++) {
        PendingAction *a = &actions[i];

        // Risk-adjusted priority
        // Safe actions first, risky actions last (but before end turn)
        float risk_factor = 1.0f - a->turnover_risk;
        float importance_factor = a->importance;

        // Special case: must-do actions (like scoring attempt)
        if (a->importance > 0.9f) {
            // Even if risky, we need to do this
            a->seq_priority = 0.5f + 0.5f * risk_factor;
        } else {
            // Standard priority: safe + important = high
            a->seq_priority = risk_factor * 0.7f + importance_factor * 0.3f;
        }
    }

    // Sort by priority (descending)
    qsort_with_context(actions, num_actions, sizeof(PendingAction),
                       compare_by_priority, NULL);

    for (int i = 0; i < num_actions; i++) {
        sequence[i] = i;  // After sorting, indices are already optimal
    }
}

// Reward shaping for action sequence
float sequence_quality_reward(
    GameState *state,
    Action *action_taken,
    PendingAction *remaining_actions,
    int num_remaining
) {
    float reward = 0.0f;

    // Penalize doing risky action when safe options remain
    float our_risk = action_taken->turnover_risk;
    float min_remaining_risk = 1.0f;
    for (int i = 0; i < num_remaining; i++) {
        if (remaining_actions[i].ev > 0) {  // Only positive EV actions
            min_remaining_risk = fmin(min_remaining_risk,
                                       remaining_actions[i].turnover_risk);
        }
    }

    if (our_risk > min_remaining_risk + 0.1f) {
        // We did a risky action when safer options existed
        reward -= 0.02f * (our_risk - min_remaining_risk);
    }

    return reward;
}
```

### 4.2 Go For It Decision

Going For It (GFI) adds 2 extra moves but risks turnover (1/6 each).

```c
typedef struct {
    int squares_moved;       // Without GFI
    int gfi_squares;         // How many GFI squares used
    float destination_value; // Value of reaching destination
    bool touchdown_threat;   // Can score if we make it
    float gfi1_prob;         // P(first GFI succeeds) = 5/6
    float gfi2_prob;         // P(both GFIs succeed) = 25/36
    int rerolls_available;
} GFIContext;

float compute_gfi_ev(GFIContext *ctx) {
    float p_success, p_fail;

    if (ctx->gfi_squares == 0) {
        return ctx->destination_value;  // No GFI needed
    }

    if (ctx->gfi_squares == 1) {
        p_success = 5.0f / 6.0f;
    } else {  // 2 GFIs
        p_success = 25.0f / 36.0f;
    }

    // With re-roll available
    if (ctx->rerolls_available > 0) {
        float p_fail_first = 1.0f - p_success;
        float p_success_reroll = p_success;  // Same odds on re-roll
        float p_success_with_reroll = p_success + p_fail_first * p_success_reroll;

        // But using re-roll has opportunity cost
        float reroll_opportunity_cost = 0.08f;  // Rough value of re-roll
        p_success = p_success_with_reroll;
        // We'll account for re-roll cost if we actually use it
    }

    p_fail = 1.0f - p_success;

    // EV = P(success) * destination_value - P(fail) * turnover_cost
    float turnover_cost = 0.25f;  // Average cost of turnover

    // If touchdown threat, success is HUGE
    if (ctx->touchdown_threat) {
        float td_value = 0.5f;  // Scoring a TD
        return p_success * (ctx->destination_value + td_value) -
               p_fail * turnover_cost;
    }

    return p_success * ctx->destination_value - p_fail * turnover_cost;
}

bool should_gfi(GFIContext *ctx) {
    // Compare EV of GFI vs not GFI
    float ev_with_gfi = compute_gfi_ev(ctx);
    float ev_without_gfi = 0.0f;  // Value of stopping where we are

    // Also consider: is there a safer way to achieve our goal?
    return ev_with_gfi > ev_without_gfi;
}
```

---

## Part 5: Dodge Expected Value

### 5.1 Complete Dodge EV Calculation

```c
typedef struct {
    int num_tackle_zones;    // TZs we're dodging through
    int player_ag;           // Agility (2+ to 6+)
    bool has_dodge_skill;    // Re-roll + stumble immunity
    bool has_sure_feet;      // Re-roll GFI
    bool has_break_tackle;   // Use ST for dodge
    bool enemy_has_tackle;   // In this specific TZ
    bool enemy_has_diving_tackle; // -2 penalty
    bool enemy_has_prehensile_tail; // -1 penalty
    bool has_two_heads;      // +1 to dodge
    int rerolls_available;
    float destination_value; // Why are we dodging?
} DodgeContext;

float compute_dodge_ev(DodgeContext *ctx) {
    // Base target
    int target = ctx->player_ag;

    // Modifiers
    int modifier = 0;
    modifier -= (ctx->num_tackle_zones - 1);  // -1 per TZ after first
    if (ctx->enemy_has_diving_tackle) modifier -= 2;
    if (ctx->enemy_has_prehensile_tail) modifier -= 1;
    if (ctx->has_two_heads) modifier += 1;

    // Break Tackle: use ST instead if better
    // (For ST 4+, this means 4+ roll instead of AG roll)
    // Simplified here

    // Effective target (capped at 2+ and 6+)
    int effective_target = clamp(target - modifier, 2, 6);

    // Base success probability
    float p_base = (7 - effective_target) / 6.0f;

    // Natural 1 always fails
    p_base = fmin(p_base, 5.0f/6.0f);

    // Tackle negates Dodge skill
    bool dodge_skill_active = ctx->has_dodge_skill && !ctx->enemy_has_tackle;

    float p_success;
    if (dodge_skill_active) {
        // Can re-roll failed dodge
        p_success = p_base + (1.0f - p_base) * p_base;
    } else {
        p_success = p_base;
    }

    // With team re-roll
    if (ctx->rerolls_available > 0 && !dodge_skill_active) {
        // Can use team re-roll
        float p_with_reroll = p_base + (1.0f - p_base) * p_base;
        // But re-roll has opportunity cost
        // Agent should learn when to use it
        p_success = fmax(p_success, p_with_reroll * 0.9f);  // Slight discount
    }

    // EV = P(success) * destination_value - P(fail) * turnover_cost
    float turnover_cost = 0.25f;
    return p_success * ctx->destination_value - (1.0f - p_success) * turnover_cost;
}
```

---

## Part 6: Passing Expected Value

### 6.1 Complete Pass EV Calculation

```c
typedef struct {
    int thrower_pa;          // Passing stat (2+ to 6+)
    int distance;            // Squares to target
    int thrower_tz;          // Tackle zones on thrower
    bool thrower_has_pass;   // Re-roll pass
    bool thrower_has_accurate; // +1 to roll
    bool thrower_has_strong_arm; // +1 range band
    bool thrower_has_nerves; // Ignore TZ
    bool catcher_has_catch;  // Re-roll catch
    bool catcher_has_nerves; // Ignore TZ
    int catcher_ag;
    int catcher_tz;          // Tackle zones on catcher
    int interceptors;        // Enemies in path
    bool opponent_has_disturbing_presence; // -1 to pass/catch
    int weather;             // Rain = -1
} PassContext;

float compute_pass_ev(PassContext *ctx) {
    // Step 1: Determine range and modifier
    int range_mod = 0;
    if (ctx->distance <= 3) {
        range_mod = 1;   // Quick pass: +1
    } else if (ctx->distance <= 6) {
        range_mod = 0;   // Short pass
    } else if (ctx->distance <= 10) {
        range_mod = -1;  // Long pass
    } else if (ctx->distance <= 13) {
        range_mod = -2;  // Long bomb
    } else {
        return -0.5f;    // Too far (need Hail Mary)
    }

    // Strong arm improves range
    if (ctx->thrower_has_strong_arm) {
        range_mod += 1;
    }

    // Step 2: Pass roll
    int tz_mod = ctx->thrower_has_nerves ? 0 : -ctx->thrower_tz;
    int pass_target = ctx->thrower_pa - range_mod - tz_mod;
    if (ctx->thrower_has_accurate) pass_target -= 1;
    if (ctx->weather == WEATHER_RAIN) pass_target += 1;
    if (ctx->opponent_has_disturbing_presence) pass_target += 1;

    pass_target = clamp(pass_target, 2, 6);
    float p_accurate = (7 - pass_target) / 6.0f;
    float p_fumble = 1.0f / 6.0f;  // Natural 1 always fumbles
    p_accurate = fmin(p_accurate, 5.0f/6.0f);

    // With Pass skill re-roll
    if (ctx->thrower_has_pass) {
        float p_inaccurate = 1.0f - p_accurate - p_fumble;
        float p_pass_reroll_accurate = p_accurate;
        float p_new_accurate = p_accurate + p_inaccurate * p_pass_reroll_accurate;
        float p_new_fumble = p_fumble * p_fumble;  // Fumble then fumble again
        p_accurate = p_new_accurate;
        p_fumble = p_new_fumble;
    }

    float p_inaccurate = 1.0f - p_accurate - p_fumble;

    // Step 3: Interception (simplified)
    float p_intercept = 0.0f;
    if (ctx->interceptors > 0) {
        // Each interceptor gets AG-2 roll
        float p_single_intercept = 0.1f;  // Rough average
        p_intercept = 1.0f - pow(1.0f - p_single_intercept, ctx->interceptors);
    }

    // Step 4: Catch roll (if not intercepted)
    int catch_tz_mod = ctx->catcher_has_nerves ? 0 : -ctx->catcher_tz;
    int catch_target = ctx->catcher_ag + catch_tz_mod;
    if (ctx->weather == WEATHER_RAIN) catch_target += 1;
    if (ctx->opponent_has_disturbing_presence) catch_target += 1;

    catch_target = clamp(catch_target, 2, 6);
    float p_catch = (7 - catch_target) / 6.0f;
    p_catch = fmin(p_catch, 5.0f/6.0f);

    if (ctx->catcher_has_catch) {
        p_catch = p_catch + (1.0f - p_catch) * p_catch;
    }

    // Inaccurate pass scatters - chance catcher still gets it
    float p_inaccurate_catch = p_catch * 0.3f;  // Rough: sometimes scatters to them

    // Step 5: Combine probabilities
    float p_complete = (1.0f - p_intercept) *
                       (p_accurate * p_catch + p_inaccurate * p_inaccurate_catch);
    float p_turnover = p_fumble + (1.0f - p_fumble) *
                       (p_intercept + (1.0f - p_intercept) *
                        (p_accurate * (1.0f - p_catch) +
                         p_inaccurate * (1.0f - p_inaccurate_catch)));

    // Step 6: Compute EV
    float pass_value = 0.15f;  // Value of completing a pass
    float turnover_cost = 0.25f;

    return p_complete * pass_value - p_turnover * turnover_cost;
}
```

---

## Part 7: Positional Value Functions

### 7.1 Field Position Value

```c
// Precomputed field value heatmap
float FIELD_VALUE[BOARD_HEIGHT][BOARD_WIDTH];
float SCORING_THREAT[BOARD_HEIGHT][BOARD_WIDTH];
float CAGE_VALUE[BOARD_HEIGHT][BOARD_WIDTH];

void init_positional_values() {
    for (int y = 0; y < BOARD_HEIGHT; y++) {
        for (int x = 0; x < BOARD_WIDTH; x++) {
            // Field value: closer to opponent end zone is better
            float y_value = (float)(BOARD_HEIGHT - 1 - y) / (BOARD_HEIGHT - 1);
            FIELD_VALUE[y][x] = y_value;

            // Scoring threat: can we score from here?
            int dist_to_endzone = y;  // For team 0 scoring at y=0
            // With MA 6-8 typical, and 2 GFI possible
            int typical_range = 8;
            SCORING_THREAT[y][x] = fmax(0, 1.0f - dist_to_endzone / (float)typical_range);

            // Cage value: center is better for cages, avoid edges
            float x_center = abs(x - BOARD_WIDTH/2) / (float)(BOARD_WIDTH/2);
            float y_center = abs(y - BOARD_HEIGHT/2) / (float)(BOARD_HEIGHT/2);
            CAGE_VALUE[y][x] = (1.0f - x_center) * (1.0f - y_center);
        }
    }
}

// Dynamic positional value based on game state
float compute_square_value(GameState *state, int x, int y, int team) {
    float value = 0.0f;

    // Base field position
    if (team == 0) {
        value += FIELD_VALUE[y][x] * 0.3f;
    } else {
        value += FIELD_VALUE[BOARD_HEIGHT - 1 - y][x] * 0.3f;
    }

    // Scoring threat
    value += SCORING_THREAT[y][x] * 0.2f;

    // Control of center
    if (abs(x - BOARD_WIDTH/2) <= 4 && abs(y - BOARD_HEIGHT/2) <= 3) {
        value += 0.1f;
    }

    // Avoid edges (surf risk)
    if (x == 0 || x == BOARD_WIDTH - 1 || y == 0 || y == BOARD_HEIGHT - 1) {
        value -= 0.15f;
    }

    // Enemy tackle zone density (dangerous)
    int enemy_tz = count_enemy_tz_at(state, x, y, team);
    value -= enemy_tz * 0.05f;

    // Friendly support (good)
    int friendly_adj = count_friendly_adjacent(state, x, y, team);
    value += friendly_adj * 0.03f;

    return value;
}
```

### 7.2 Formation Value

```c
typedef struct {
    float cage_strength;     // Ball carrier protection
    float line_coverage;     // Scrimmage presence
    float deep_threat;       // Players in scoring position
    float ball_security;     // Risk of losing ball
    float defensive_coverage;// Coverage against opponent score
} FormationMetrics;

void evaluate_formation(GameState *state, int team, FormationMetrics *metrics) {
    memset(metrics, 0, sizeof(FormationMetrics));

    int ball_carrier = get_ball_carrier(state);
    bool we_have_ball = (ball_carrier >= 0 && state->player_team[ball_carrier] == team);

    // Cage strength
    if (we_have_ball) {
        metrics->cage_strength = compute_cage_value(state, ball_carrier);
    }

    // Count players in different zones
    int in_our_half = 0, in_their_half = 0;
    int on_line = 0;
    int deep_threats = 0;

    for (int i = 0; i < MAX_PLAYERS; i++) {
        if (state->player_team[i] != team) continue;
        if (!is_standing(state, i)) continue;

        int y = state->player_y[i];

        // Normalize y so that lower is closer to opponent endzone
        int norm_y = (team == 0) ? y : (BOARD_HEIGHT - 1 - y);

        if (norm_y < BOARD_HEIGHT / 2) {
            in_their_half++;
        } else {
            in_our_half++;
        }

        if (abs(y - BOARD_HEIGHT/2) <= 1) {
            on_line++;
        }

        if (norm_y <= 2) {
            deep_threats++;
        }
    }

    metrics->line_coverage = fmin(1.0f, on_line / 3.0f);
    metrics->deep_threat = fmin(1.0f, deep_threats / 2.0f);

    // Ball security
    if (we_have_ball) {
        int bc_x = state->player_x[ball_carrier];
        int bc_y = state->player_y[ball_carrier];
        int enemy_tz = count_enemy_tz_at(state, bc_x, bc_y, team);
        metrics->ball_security = 1.0f - enemy_tz * 0.2f;
    }

    // Defensive coverage (prevent opponent scoring)
    if (!we_have_ball && state->ball_carrier >= 0) {
        int opp_bc = state->ball_carrier;
        int opp_bc_y = state->player_y[opp_bc];
        int norm_opp_y = (team == 0) ? (BOARD_HEIGHT - 1 - opp_bc_y) : opp_bc_y;

        // How many defenders between ball and our endzone?
        int defenders = count_players_between(state, team, opp_bc_y,
                                               team == 0 ? BOARD_HEIGHT - 1 : 0);
        metrics->defensive_coverage = fmin(1.0f, defenders / 3.0f);
    }
}

float formation_value(FormationMetrics *m, bool we_have_ball, int turns_left) {
    if (we_have_ball) {
        // Offensive formation value
        return m->cage_strength * 0.3f +
               m->ball_security * 0.3f +
               m->deep_threat * 0.2f * (turns_left / 8.0f) +  // Less important late
               m->line_coverage * 0.1f;
    } else {
        // Defensive formation value
        return m->defensive_coverage * 0.4f +
               m->line_coverage * 0.3f +
               m->deep_threat * 0.1f +  // Counter-attack potential
               (1.0f - m->ball_security) * 0.2f;  // Inverse: their ball security is bad for us
    }
}
```

---

## Part 8: Resource Valuation

### 8.1 Re-roll Value Model

```c
// Expected value of having a re-roll available
float reroll_value(GameState *state, int team) {
    int turns_left = 16 - state->turn_number;
    int rerolls = state->rerolls[team];

    // Base value: each re-roll is worth ~8% of a TD
    float base_value = 0.08f;

    // Scarcity increases value
    float scarcity_mult = 1.0f + (4 - rerolls) * 0.15f;

    // Time value: more turns = more chances to use
    float time_mult = 0.5f + 0.5f * (turns_left / 16.0f);

    // Team-specific: low-AG teams need more re-rolls
    float avg_ag = compute_team_avg_ag(state, team);
    float ag_mult = 1.0f + (4.0f - avg_ag) * 0.1f;

    return base_value * scarcity_mult * time_mult * ag_mult;
}

// Should we use a re-roll now?
float compute_reroll_decision_value(
    float action_ev_without_reroll,
    float action_ev_with_reroll,
    float reroll_remaining_value
) {
    float ev_gain = action_ev_with_reroll - action_ev_without_reroll;
    float opportunity_cost = reroll_remaining_value;

    return ev_gain - opportunity_cost;
}
```

### 8.2 Apothecary Value Model

```c
// Expected value of having apothecary available
float apothecary_value(GameState *state, int team, bool is_league) {
    int turns_left = 16 - state->turn_number;
    float avg_player_value = compute_team_avg_player_value(state, team);

    // P(injury happens) * P(it's bad enough to use apo) * player_value
    float p_injury_per_turn = 0.15f;  // Rough estimate
    float p_severe = 0.4f;            // P(KO or worse)
    float turns_factor = turns_left / 16.0f;

    float base_value = p_injury_per_turn * p_severe * avg_player_value * turns_factor;

    if (is_league) {
        // Long-term value of saving player
        base_value *= 2.0f;
    }

    return base_value;
}
```

---

## Part 9: Composite Reward Function

### 9.1 Final Reward Shaping

```c
typedef struct {
    float win_bonus;           // +1 for win, -1 for loss
    float td_value;            // Scored/conceded TD
    float block_ev;            // EV of blocks made
    float opp_block_ev;        // EV of blocks taken (negative)
    float positional_delta;    // Change in positional value
    float resource_efficiency; // Good use of re-rolls/apo
    float turnover_penalty;    // Cost of turnovers
    float action_sequence;     // Did safe actions first?
    float formation_value;     // Quality of formation
} RewardComponents;

float compute_step_reward(
    GameState *prev_state,
    GameState *next_state,
    Action action,
    int our_team,
    bool is_league,
    RewardComponents *components  // For logging/debugging
) {
    memset(components, 0, sizeof(RewardComponents));

    // === TERMINAL REWARDS ===
    if (next_state->is_game_over) {
        if (next_state->winner == our_team) {
            components->win_bonus = 1.0f;
        } else if (next_state->winner == 1 - our_team) {
            components->win_bonus = -1.0f;
        }
        // Draw = 0
    }

    // === TD REWARDS ===
    if (next_state->just_scored) {
        if (next_state->scoring_team == our_team) {
            components->td_value = 0.4f;
        } else {
            components->td_value = -0.4f;
        }
    }

    // === BLOCK EV ===
    if (action.type == ACTION_BLOCK) {
        MatchupContext ctx;
        compute_matchup_context(prev_state, our_team, &ctx);

        BlockOutcome outcome;
        compute_block_ev(/* ... */);

        float defender_value = prev_state->players[action.target].gold_value / 100000.0f;
        components->block_ev = block_ev_to_value(&outcome, 1.0f, defender_value,
                                                  prev_state->ball_carrier == action.target,
                                                  0.5f) * 0.1f;
    }

    // === OPPONENT BLOCK PENALTY ===
    if (next_state->opponent_blocked_us) {
        float our_player_value = prev_state->players[next_state->block_target].gold_value / 100000.0f;
        // Negative EV for getting blocked
        components->opp_block_ev = -0.05f * our_player_value;
    }

    // === POSITIONAL DELTA ===
    float old_position = compute_formation_value(prev_state, our_team);
    float new_position = compute_formation_value(next_state, our_team);
    components->positional_delta = (new_position - old_position) * 0.05f;

    // === TURNOVER PENALTY ===
    if (next_state->turnover && prev_state->active_team == our_team) {
        float turn_progress = prev_state->turn_number / 16.0f;
        components->turnover_penalty = -0.15f * (1.0f - turn_progress * 0.5f);
    }

    // === RESOURCE EFFICIENCY ===
    if (action.type == ACTION_USE_REROLL) {
        float reroll_ev = compute_reroll_decision_value(/* ... */);
        if (reroll_ev < 0) {
            components->resource_efficiency = -0.02f;  // Bad re-roll usage
        }
    }

    // Sum all components
    float total = 0.0f;
    total += components->win_bonus;
    total += components->td_value;
    total += components->block_ev;
    total += components->opp_block_ev;
    total += components->positional_delta;
    total += components->resource_efficiency;
    total += components->turnover_penalty;
    total += components->formation_value;
    total += components->action_sequence;

    return total;
}
```

---

## Part 10: Training Considerations

### 10.1 Reward Scaling

```python
class RewardNormalizer:
    """Running normalization for stable training."""

    def __init__(self, gamma=0.99):
        self.gamma = gamma
        self.ret_rms = RunningMeanStd()
        self.returns = 0

    def normalize(self, reward, done):
        self.returns = reward + self.gamma * self.returns * (1 - done)
        self.ret_rms.update(self.returns)
        return reward / (self.ret_rms.std + 1e-8)
```

### 10.2 Auxiliary Losses

```python
def compute_auxiliary_losses(model, obs, actions, values):
    """Additional training signals."""
    losses = {}

    # Value function should predict win probability
    predicted_wp = model.predict_win_prob(obs)
    actual_wp = compute_win_probability(obs)
    losses['wp_loss'] = F.mse_loss(predicted_wp, actual_wp)

    # Block EV prediction
    predicted_block_ev = model.predict_block_ev(obs, actions)
    actual_block_ev = compute_block_ev_batch(obs, actions)
    losses['block_ev_loss'] = F.mse_loss(predicted_block_ev, actual_block_ev)

    # Matchup embedding should be consistent
    matchup_embed = model.matchup_encoder(obs)
    matchup_consistency = model.matchup_decoder(matchup_embed)
    losses['matchup_loss'] = F.mse_loss(matchup_consistency, obs.matchup_features)

    return losses
```

### 10.3 Curriculum for Value Learning

```python
CURRICULUM_STAGES = [
    # Stage 1: Learn basic value function
    {
        'reward_components': ['win_bonus', 'td_value'],
        'reward_scale': {'win_bonus': 1.0, 'td_value': 0.5},
    },
    # Stage 2: Add EV-based shaping
    {
        'reward_components': ['win_bonus', 'td_value', 'block_ev'],
        'reward_scale': {'win_bonus': 1.0, 'td_value': 0.4, 'block_ev': 0.1},
    },
    # Stage 3: Add positional value
    {
        'reward_components': ['win_bonus', 'td_value', 'block_ev', 'positional_delta'],
        'reward_scale': {'win_bonus': 1.0, 'td_value': 0.4, 'block_ev': 0.1, 'positional_delta': 0.05},
    },
    # Stage 4: Full reward
    {
        'reward_components': 'all',
        'reward_scale': 'default',
    },
]
```

---

## Summary: Key Insights

1. **EV-Based Rewards**: Always reward the quality of the decision, not the dice outcome. A good block is good even if it rolls Attacker Down.

2. **Contextual Skill Valuation**: Skills have different values depending on the matchup. Tackle is worthless against a team with no Dodge.

3. **Matchup Features in Observation**: The agent needs to SEE the matchup context (their skills vs ours) to make good decisions.

4. **Resource Timing**: Re-rolls, apothecary, wizard all have optimal usage timing. Model the opportunity cost.

5. **Action Sequencing**: Do safe actions first, risky actions last. The turnover mechanic makes ordering critical.

6. **Multi-Scale Value**: Track win probability, TD differential, player value, positional value, and resources separately.

7. **Formation Value**: Cage strength, defensive coverage, and ball security are key tactical concepts.

8. **League vs One-Off**: In league play, player preservation becomes much more important.
