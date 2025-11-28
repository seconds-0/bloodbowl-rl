# Blood Bowl RL Environment Architecture

## Executive Summary

This document defines the complete architecture for a Blood Bowl reinforcement learning environment that handles:
- **Match play**: Tactical decisions during games
- **Meta-game**: Inducements, apothecary usage, wizard timing
- **League play**: Team development, skill selection, roster management
- **Team building**: Initial roster construction and long-term strategy

The core insight is that Blood Bowl is actually **multiple nested decision problems**, each requiring different value functions and observation spaces.

---

## Part 1: The Decision Hierarchy

Blood Bowl contains five distinct decision layers:

```
┌─────────────────────────────────────────────────────────────────┐
│                    LEAGUE MANAGEMENT                             │
│  • Season-level decisions                                        │
│  • Multi-match optimization                                      │
│  • Team value trajectory                                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    TEAM DEVELOPMENT                              │
│  • Post-match skill selection                                    │
│  • Player hiring/firing                                          │
│  • Treasury management                                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PRE-MATCH SETUP                               │
│  • Inducement purchasing                                         │
│  • Roster selection (which 11 to field)                          │
│  • Initial formation                                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MATCH TACTICS                                 │
│  • Move/block/pass decisions                                     │
│  • Action sequencing                                             │
│  • Risk management                                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RESOURCE TIMING                               │
│  • Re-roll usage                                                 │
│  • Apothecary timing                                             │
│  • Wizard/bribe usage                                            │
└─────────────────────────────────────────────────────────────────┘
```

### 1.1 Training Approach Options

**Option A: Single Unified Agent**
- One policy handles all decisions
- Massive action space but shared learning
- Simpler architecture, harder optimization

**Option B: Hierarchical Multi-Agent**
- Separate policies for each layer
- Each specialized for its decision type
- Communication through value estimates

**Recommendation: Hybrid Approach**
- Single agent for match tactics + resource timing (tightly coupled)
- Separate agent for pre-match/inducements
- Separate agent for team development
- League management as outer optimization loop

---

## Part 2: Match-Level Architecture

### 2.1 State Representation

The match observation must capture both **board state** and **matchup context**.

```c
// =============================================================================
// OBSERVATION STRUCTURE
// =============================================================================

#define OBS_BOARD_LAYERS 16
#define OBS_PLAYER_FEATURES 32
#define OBS_GLOBAL_FEATURES 64
#define OBS_MATCHUP_FEATURES 128

typedef struct {
    // SPATIAL LAYERS (26 x 15 x 16 = 6,240 floats)
    // Each layer is a 26x15 grid
    float board[OBS_BOARD_LAYERS][BOARD_HEIGHT][BOARD_WIDTH];
    // Layer 0:  Friendly standing players
    // Layer 1:  Friendly prone players
    // Layer 2:  Friendly stunned players
    // Layer 3:  Enemy standing players
    // Layer 4:  Enemy prone players
    // Layer 5:  Enemy stunned players
    // Layer 6:  Ball position
    // Layer 7:  Ball carrier (if any)
    // Layer 8:  Friendly tackle zones (count/8)
    // Layer 9:  Enemy tackle zones (count/8)
    // Layer 10: Valid move destinations
    // Layer 11: Valid block targets
    // Layer 12: Scoring threat zones
    // Layer 13: Blitz path options
    // Layer 14: Pass target zones
    // Layer 15: Danger zones (high turnover risk)

    // PLAYER FEATURES (22 players x 32 features = 704 floats)
    float players[MAX_PLAYERS][OBS_PLAYER_FEATURES];
    // Per-player:
    //   0-4:   MA, ST, AG, PA, AV (normalized)
    //   5:     Team (0=ours, 1=enemy)
    //   6:     State (standing/prone/stunned/off-pitch)
    //   7:     Has ball
    //   8:     Activated this turn
    //   9:     Movement remaining (normalized)
    //   10-31: Skill flags (one-hot for relevant skills)

    // GLOBAL STATE (64 floats)
    float global[OBS_GLOBAL_FEATURES];
    //   0:     Turn number / 16
    //   1:     Half (0 or 0.5)
    //   2:     Score differential / 4 (clamped)
    //   3:     Our re-rolls remaining / 4
    //   4:     Their re-rolls remaining / 4
    //   5:     Apothecary available
    //   6:     Blitz used this turn
    //   7:     Pass used this turn
    //   8:     Foul used this turn
    //   9:     Hand-off used this turn
    //   10:    We are receiving
    //   11:    Weather effects (one-hot: nice/rain/blizzard/sun/heat)
    //   15-31: Reserved
    //   32-47: Our team composition summary
    //   48-63: Their team composition summary

    // MATCHUP CONTEXT (128 floats) - CRITICAL FOR CONTEXTUAL DECISIONS
    float matchup[OBS_MATCHUP_FEATURES];
    //   0-15:  Our skill counts (Block, Dodge, Guard, MB, Tackle, etc.)
    //   16-31: Their skill counts
    //   32-47: Skill interaction matrix (our_tackle vs their_dodge, etc.)
    //   48-63: Positional advantages
    //   64-79: Expected block outcomes (precomputed EV matrix)
    //   80-95: Team archetype features (bash/agility/hybrid)
    //   96-127: Reserved for learned embeddings
} MatchObservation;
```

### 2.2 Matchup Context Features

This is where we encode **contextual skill relevance**:

```c
typedef struct {
    // Skill counts per team
    int our_block_count;
    int our_dodge_count;
    int our_tackle_count;
    int our_guard_count;
    int our_mighty_blow_count;
    int our_claw_count;
    int our_sure_hands_count;
    // ... same for opponent

    // Derived interaction features
    float tackle_vs_dodge_ratio;      // our_tackle / max(1, their_dodge)
    float guard_density_ratio;        // our_guard / their_guard
    float bash_advantage;             // our_ST_sum / their_ST_sum
    float mobility_advantage;         // our_MA_sum / their_MA_sum
    float armor_differential;         // their_AV_avg - our_MB_effectiveness

    // Precomputed matchup EVs
    float avg_block_ev_for_us;        // Average EV when we block them
    float avg_block_ev_against_us;    // Average EV when they block us
    float our_removal_threat;         // How likely we remove their players
    float their_removal_threat;       // How likely they remove ours
} MatchupContext;

// Compute contextual skill value
float contextual_skill_value(Skill skill, MatchupContext *ctx) {
    switch (skill) {
        case SKILL_TACKLE:
            // Tackle is valuable proportional to opponent's dodge count
            return 0.2f + 0.3f * (ctx->their_dodge_count / 11.0f);

        case SKILL_GUARD:
            // Guard is valuable in bash matchups with lots of blocking
            return 0.3f + 0.2f * (1.0f - ctx->mobility_advantage);

        case SKILL_DODGE:
            // Dodge is devalued when opponent has tackle
            return 0.4f * (1.0f - ctx->their_tackle_count / 11.0f);

        case SKILL_MIGHTY_BLOW:
            // MB is valuable against low-AV teams
            return 0.3f + 0.2f * (9.0f - ctx->their_avg_av) / 3.0f;

        case SKILL_CLAW:
            // Claw is valuable against HIGH-AV teams (breaks 8+ regardless)
            return 0.2f + 0.4f * (ctx->their_avg_av - 8.0f) / 2.0f;

        case SKILL_BLOCK:
            // Block is always valuable, slightly more in bash matchups
            return 0.5f + 0.1f * ctx->bash_advantage;

        default:
            return 0.3f;
    }
}
```

### 2.3 Action Space Design

```c
// Hierarchical action encoding
typedef enum {
    // Meta-actions
    ACTION_END_TURN = 0,
    ACTION_USE_REROLL,
    ACTION_USE_APOTHECARY,
    ACTION_USE_WIZARD,
    ACTION_USE_BRIBE,

    // Player selection (when needed)
    ACTION_SELECT_PLAYER_BASE = 100,  // + player_id (0-21)

    // Movement actions
    ACTION_MOVE_BASE = 200,           // + square_id (0-389)

    // Block actions
    ACTION_BLOCK_BASE = 600,          // + target_player_id

    // Block die selection
    ACTION_CHOOSE_BLOCK_DIE_BASE = 700, // + die_index

    // Push direction
    ACTION_PUSH_BASE = 800,           // + direction (0-7)

    // Follow up
    ACTION_FOLLOWUP_YES = 900,
    ACTION_FOLLOWUP_NO = 901,

    // Pass/handoff targets
    ACTION_PASS_BASE = 1000,          // + square_id
    ACTION_HANDOFF_BASE = 1500,       // + player_id

    // Foul
    ACTION_FOUL_BASE = 1600,          // + target_player_id

    MAX_ACTIONS = 2000
} ActionType;

// Action masking is CRITICAL for valid action enforcement
void compute_action_mask(MatchState *state, uint8_t *mask) {
    memset(mask, 0, MAX_ACTIONS);

    // Always can end turn (unless in middle of action)
    if (!state->awaiting_choice) {
        mask[ACTION_END_TURN] = 1;
    }

    // Re-roll available?
    if (state->can_reroll && state->rerolls[state->active_team] > 0) {
        mask[ACTION_USE_REROLL] = 1;
    }

    // Apothecary?
    if (state->awaiting_apothecary_choice) {
        mask[ACTION_USE_APOTHECARY] = 1;
        // Also allow declining
    }

    // ... compute all valid actions based on game state
}
```

---

## Part 3: Value Functions

### 3.1 Multi-Objective Value Decomposition

Blood Bowl has multiple value dimensions that should be tracked separately:

```c
typedef struct {
    float win_probability;        // P(win) - ultimate goal
    float expected_td_diff;       // E[our_score - their_score]
    float team_value_preserved;   // Player injury/death avoidance
    float resource_value;         // Re-rolls, apothecary remaining
    float positional_value;       // Field control, scoring threats
    float tempo_value;            // Turn economy, clock management
} ValueDecomposition;

// Combine into single value for training
float compute_value(ValueDecomposition *v, MatchContext *ctx) {
    // Weights depend on game state
    float w_win = 1.0f;
    float w_td = 0.3f;
    float w_team = 0.1f;  // More important in league play
    float w_resource = 0.1f;
    float w_position = 0.2f;
    float w_tempo = 0.1f;

    // Adjust weights based on context
    if (ctx->is_league_play) {
        w_team = 0.3f;  // Preserving players matters more
    }
    if (ctx->turn_number >= 14) {
        w_tempo = 0.3f;  // Clock management critical late game
    }
    if (abs(ctx->score_diff) >= 2) {
        w_td = 0.1f;    // TD diff less important when ahead/behind by 2+
    }

    return w_win * v->win_probability +
           w_td * v->expected_td_diff +
           w_team * v->team_value_preserved +
           w_resource * v->resource_value +
           w_position * v->positional_value +
           w_tempo * v->tempo_value;
}
```

### 3.2 Win Probability Model

```c
// Factors affecting win probability
float estimate_win_probability(MatchState *state) {
    float p = 0.5f;  // Base 50%

    // Score differential (huge factor)
    int score_diff = state->score[0] - state->score[1];
    p += score_diff * 0.15f;  // Each TD worth ~15% win prob

    // Turns remaining affects TD value
    int turns_left = 16 - state->turn_number;
    float td_weight = turns_left / 16.0f;

    // Team strength differential
    float strength_diff = compute_team_strength(state, 0) -
                          compute_team_strength(state, 1);
    p += strength_diff * 0.05f * td_weight;

    // Player count advantage
    int player_diff = count_available_players(state, 0) -
                      count_available_players(state, 1);
    p += player_diff * 0.02f;

    // Ball control
    if (state->ball_carrier >= 0) {
        if (state->player_team[state->ball_carrier] == 0) {
            p += 0.05f;
        } else {
            p -= 0.05f;
        }
    }

    return clamp(p, 0.01f, 0.99f);
}
```

### 3.3 Positional Value (Field Control)

```c
// Value of each square for ball carrier positioning
float FIELD_VALUE[BOARD_HEIGHT][BOARD_WIDTH];

void init_field_value() {
    for (int y = 0; y < BOARD_HEIGHT; y++) {
        for (int x = 0; x < BOARD_WIDTH; x++) {
            float value = 0.0f;

            // Distance to opponent end zone
            float dist_to_goal = (float)y / BOARD_HEIGHT;
            value += (1.0f - dist_to_goal) * 0.3f;

            // Center vs sideline (center is safer for ball)
            float center_dist = abs(x - BOARD_WIDTH/2) / (float)(BOARD_WIDTH/2);
            value += (1.0f - center_dist) * 0.1f;

            // Wide zones slightly devalued
            if (x < 4 || x >= BOARD_WIDTH - 4) {
                value -= 0.05f;
            }

            FIELD_VALUE[y][x] = value;
        }
    }
}

// Cage formation value
float compute_cage_value(MatchState *state, int ball_carrier) {
    if (ball_carrier < 0) return 0.0f;

    int bx = state->player_x[ball_carrier];
    int by = state->player_y[ball_carrier];

    float cage_strength = 0.0f;
    int cage_count = 0;

    // Check 8 surrounding squares
    for (int dy = -1; dy <= 1; dy++) {
        for (int dx = -1; dx <= 1; dx++) {
            if (dx == 0 && dy == 0) continue;

            int px = bx + dx;
            int py = by + dy;

            int player = get_player_at(state, px, py);
            if (player >= 0 && state->player_team[player] == state->player_team[ball_carrier]) {
                cage_count++;
                // Value based on player's blocking ability
                if (has_skill(state, player, SKILL_BLOCK)) {
                    cage_strength += 1.0f;
                } else {
                    cage_strength += 0.7f;
                }
                if (has_skill(state, player, SKILL_GUARD)) {
                    cage_strength += 0.3f;
                }
                if (has_skill(state, player, SKILL_STAND_FIRM)) {
                    cage_strength += 0.2f;
                }
            }
        }
    }

    // Corner cage (4 players) is ideal
    return cage_strength / 4.0f;
}
```

---

## Part 4: Resource Timing Decisions

### 4.1 Re-roll Decision Framework

Re-rolls are precious. The decision to use one depends on:
1. **Action importance**: How critical is this action?
2. **Success probability**: What's the expected value of re-rolling?
3. **Remaining re-rolls**: Scarcity increases value
4. **Turns remaining**: More turns = more chances to need re-rolls

```c
typedef struct {
    float action_importance;      // 0-1, how game-changing
    float current_success_prob;   // P(success) without re-roll
    float reroll_success_prob;    // P(success) with re-roll
    int rerolls_remaining;
    int turns_remaining;
    bool is_turnover_risk;        // Does failure cause turnover?
} RerollContext;

float compute_reroll_ev(RerollContext *ctx) {
    // Expected value gain from re-rolling
    float ev_gain = ctx->action_importance *
                    (ctx->reroll_success_prob - ctx->current_success_prob);

    // Opportunity cost: expected value of having re-roll later
    // Rough model: each remaining turn has ~20% chance of needing re-roll
    float future_reroll_value = 0.0f;
    for (int t = 0; t < ctx->turns_remaining; t++) {
        float p_need = 0.2f * pow(0.8f, t);  // Diminishing
        float avg_importance = 0.4f;  // Average action importance
        float avg_gain = 0.3f;        // Average success improvement
        future_reroll_value += p_need * avg_importance * avg_gain;
    }

    // Scarcity multiplier
    float scarcity = 1.0f + (3 - ctx->rerolls_remaining) * 0.2f;
    future_reroll_value *= scarcity;

    // Net EV of using re-roll now
    return ev_gain - future_reroll_value;
}

bool should_use_reroll(RerollContext *ctx) {
    // Special cases: always re-roll
    if (ctx->is_turnover_risk && ctx->action_importance > 0.8f) {
        if (ctx->reroll_success_prob > 0.6f) {
            return true;  // Critical action, decent odds
        }
    }

    // Special cases: never re-roll
    if (ctx->reroll_success_prob < 0.3f) {
        return false;  // Don't waste re-roll on low odds
    }

    return compute_reroll_ev(ctx) > 0.0f;
}
```

### 4.2 Apothecary Decision Framework

Apothecary usage is even more strategic. Consider:
1. **Player value**: Gold cost + skills + irreplaceability
2. **Injury severity**: KO vs Badly Hurt vs potential death
3. **Game state**: Winning vs losing, turns remaining
4. **League context**: This game vs future games

```c
typedef struct {
    int player_gold_value;
    int player_spp;              // Star player points (experience)
    int player_skills_count;
    bool player_has_key_skill;   // Block, Dodge, etc.
    bool player_is_big_guy;
    int injury_type;             // KO, BH, SI, DEAD
    int score_diff;
    int turns_remaining;
    bool is_league_play;
    int games_remaining_in_season;
} ApothecaryContext;

float compute_player_value(ApothecaryContext *ctx) {
    // Base value is gold cost
    float value = ctx->player_gold_value / 50000.0f;

    // SPP adds value (experience)
    value += ctx->player_spp * 0.02f;

    // Skills add significant value
    value += ctx->player_skills_count * 0.3f;

    // Key skills are extra valuable
    if (ctx->player_has_key_skill) {
        value += 0.5f;
    }

    // Big guys are hard to replace
    if (ctx->player_is_big_guy) {
        value += 0.5f;
    }

    return value;
}

float compute_apothecary_ev(ApothecaryContext *ctx) {
    float player_value = compute_player_value(ctx);

    // What does apothecary save us from?
    float save_value = 0.0f;

    switch (ctx->injury_type) {
        case INJURY_KO:
            // Might come back anyway (50% each half)
            // Apothecary guarantees return
            save_value = player_value * 0.5f * (ctx->turns_remaining / 16.0f);
            break;

        case INJURY_BADLY_HURT:
            // Out for game, but back next game
            save_value = player_value * (ctx->turns_remaining / 16.0f);
            if (!ctx->is_league_play) {
                save_value *= 0.8f;  // Less important in one-off
            }
            break;

        case INJURY_SERIOUS:
            // Miss next game
            if (ctx->is_league_play) {
                save_value = player_value * 1.5f;
            } else {
                save_value = player_value * 0.5f;
            }
            break;

        case INJURY_DEAD:
            // Permanent loss!
            if (ctx->is_league_play) {
                save_value = player_value * 3.0f;  // Huge value
            } else {
                save_value = player_value * 1.0f;
            }
            break;
    }

    // Opportunity cost: might need apo for more valuable player later
    float future_injury_prob = 0.1f * ctx->turns_remaining;
    float avg_player_value = 1.0f;
    float opportunity_cost = future_injury_prob * avg_player_value * 0.5f;

    return save_value - opportunity_cost;
}

bool should_use_apothecary(ApothecaryContext *ctx) {
    // Always save from death in league play
    if (ctx->is_league_play && ctx->injury_type == INJURY_DEAD) {
        return true;
    }

    // Never use on low-value players for KO
    if (ctx->injury_type == INJURY_KO && compute_player_value(ctx) < 1.0f) {
        return false;
    }

    return compute_apothecary_ev(ctx) > 0.0f;
}
```

### 4.3 Wizard Timing

Wizards (Lightning Bolt or Fireball) are one-shot game-changers.

```c
typedef struct {
    int score_diff;              // Positive = winning
    int turns_remaining;
    bool opponent_has_ball;
    int opponent_ball_carrier_value;
    bool can_hit_multiple_players;  // Fireball opportunity
    int players_in_fireball_range;
    float win_probability_current;
} WizardContext;

float compute_wizard_ev(WizardContext *ctx) {
    float ev = 0.0f;

    // Lightning bolt on ball carrier
    if (ctx->opponent_has_ball) {
        // 2+ to hit, causes knockdown and ball scatter
        float hit_prob = 5.0f / 6.0f;
        float turnover_value = 0.3f;  // Forcing turnover is valuable
        ev += hit_prob * turnover_value;

        // Also damages the player
        float removal_prob = 0.4f;  // Rough armor break + injury
        ev += hit_prob * removal_prob * (ctx->opponent_ball_carrier_value / 100000.0f);
    }

    // Fireball on cluster
    if (ctx->can_hit_multiple_players) {
        float players_hit = ctx->players_in_fireball_range;
        float per_player_value = 0.15f;  // Knockdown + possible removal
        ev = fmax(ev, players_hit * per_player_value);
    }

    // Opportunity cost: saving wizard for later
    // Wizard is more valuable when:
    // - Game is close
    // - More turns remaining = more chances for good opportunity
    // - We're behind (need the swing)
    float save_value = 0.0f;
    if (ctx->turns_remaining > 4) {
        save_value = 0.2f;  // Might get better opportunity
    }
    if (ctx->score_diff < 0) {
        save_value *= 0.5f;  // More urgency when behind
    }

    return ev - save_value;
}

bool should_use_wizard(WizardContext *ctx) {
    // Use defensively when opponent is about to score
    if (ctx->opponent_has_ball && ctx->turns_remaining <= 2 &&
        ctx->score_diff >= 0) {
        return true;  // Prevent equalizer/winner
    }

    // Use when we get a great fireball opportunity
    if (ctx->players_in_fireball_range >= 4) {
        return true;
    }

    return compute_wizard_ev(ctx) > 0.3f;  // Higher threshold than re-roll
}
```

### 4.4 Bribe Decision

Bribes let you avoid ejection for fouls or secret weapons.

```c
typedef struct {
    bool is_secret_weapon;       // Deathroller, chainsaw, etc.
    int player_gold_value;
    int fouls_committed;
    bool already_scored;         // SW already contributed
    int turns_remaining;
    bool have_another_sw;        // Redundancy
} BribeContext;

float compute_bribe_ev(BribeContext *ctx) {
    if (ctx->is_secret_weapon) {
        // Secret weapons are ejected at drive end anyway
        // Bribe value = keeping them for more turns THIS drive
        float turns_value = ctx->turns_remaining / 8.0f;
        float sw_impact = ctx->player_gold_value / 150000.0f;

        // If they already scored/had big impact, less value
        if (ctx->already_scored) {
            sw_impact *= 0.3f;
        }

        return turns_value * sw_impact;
    } else {
        // Regular foul ejection
        // Player value for rest of game
        float player_value = ctx->player_gold_value / 50000.0f;
        float game_fraction = ctx->turns_remaining / 16.0f;

        return player_value * game_fraction;
    }
}
```

---

## Part 5: Pre-Match Decisions

### 5.1 Inducement Selection

When teams have a Team Value (TV) difference, the lower TV team gets gold to spend on inducements.

```c
typedef struct {
    int petty_cash;              // Gold available
    int our_tv;
    int their_tv;
    bool we_have_apothecary;
    int our_rerolls;
    int their_team_type;         // Bash/agility/hybrid
    bool their_team_has_key_players;  // Targets for assassin
    int our_player_count;
} InducementContext;

typedef enum {
    IND_EXTRA_REROLL = 0,        // 100k
    IND_BRIBE = 1,               // 100k
    IND_WIZARD = 2,              // 150k
    IND_BLOODWEISER_BABES = 3,   // 50k (KO recovery)
    IND_EXTRA_APOTHECARY = 4,    // 100k (if allowed)
    IND_STAR_PLAYER = 5,         // Variable
    IND_MERCENARY = 6,           // 50k + position cost
    IND_HALFLING_MASTER_CHEF = 7,// 100k (steal re-rolls)
} InducementType;

// Priority ordering for inducements
void select_inducements(InducementContext *ctx, InducementList *selected) {
    int remaining = ctx->petty_cash;

    // Priority 1: Wizard if we're outbashed
    if (remaining >= 150000 && is_bash_team(ctx->their_team_type)) {
        // Wizard can swing a bash matchup
        add_inducement(selected, IND_WIZARD);
        remaining -= 150000;
    }

    // Priority 2: Extra re-roll if we're low
    if (remaining >= 100000 && ctx->our_rerolls < 3) {
        add_inducement(selected, IND_EXTRA_REROLL);
        remaining -= 100000;
    }

    // Priority 3: Bribe if we have secret weapons
    if (remaining >= 100000 && has_secret_weapon(ctx)) {
        add_inducement(selected, IND_BRIBE);
        remaining -= 100000;
    }

    // Priority 4: Bloodweiser Babes for KO-heavy matchups
    while (remaining >= 50000 && is_bash_team(ctx->their_team_type)) {
        add_inducement(selected, IND_BLOODWEISER_BABES);
        remaining -= 50000;
        if (count_inducement(selected, IND_BLOODWEISER_BABES) >= 2) break;
    }

    // Priority 5: Star players if significant cash remaining
    if (remaining >= 200000) {
        // Select star player based on matchup
        StarPlayer *star = select_star_for_matchup(ctx, remaining);
        if (star) {
            add_inducement(selected, IND_STAR_PLAYER);
            remaining -= star->cost;
        }
    }

    // Priority 6: Mercenaries if we're short on players
    while (remaining >= 100000 && ctx->our_player_count < 11) {
        add_inducement(selected, IND_MERCENARY);
        remaining -= 100000;  // Approximate
        ctx->our_player_count++;
    }
}
```

### 5.2 Roster Selection (Which 11 to Field)

```c
typedef struct {
    int player_id;
    float matchup_value;         // Value for this specific opponent
    float injury_risk;           // How likely to get hurt
    float irreplaceability;      // How hard to replace
} RosterCandidate;

void select_roster(Team *our_team, Team *their_team, int *selected_11) {
    RosterCandidate candidates[MAX_ROSTER];
    int num_candidates = 0;

    for (int i = 0; i < our_team->roster_size; i++) {
        Player *p = &our_team->players[i];
        if (p->status != PLAYER_AVAILABLE) continue;

        RosterCandidate *c = &candidates[num_candidates++];
        c->player_id = i;

        // Compute matchup-specific value
        c->matchup_value = compute_player_matchup_value(p, their_team);

        // Injury risk (higher against bash teams)
        c->injury_risk = compute_injury_risk(p, their_team);

        // Irreplaceability (for league play)
        c->irreplaceability = compute_irreplaceability(p, our_team);
    }

    // Sort by matchup value (league play might weight irreplaceability)
    sort_candidates(candidates, num_candidates);

    // Select top 11
    for (int i = 0; i < 11 && i < num_candidates; i++) {
        selected_11[i] = candidates[i].player_id;
    }
}

float compute_player_matchup_value(Player *p, Team *opponent) {
    float value = p->gold_value / 50000.0f;

    // Tackle is valuable vs dodge teams
    if (has_skill(p, SKILL_TACKLE)) {
        value += 0.3f * (count_team_skill(opponent, SKILL_DODGE) / 11.0f);
    }

    // Guard is valuable in bash matchups
    if (has_skill(p, SKILL_GUARD)) {
        value += 0.2f * (is_bash_team(opponent) ? 1.0f : 0.5f);
    }

    // Mighty Blow valuable against low AV
    if (has_skill(p, SKILL_MIGHTY_BLOW)) {
        float avg_av = compute_team_avg_av(opponent);
        value += 0.2f * (9.0f - avg_av) / 2.0f;
    }

    // Speed valuable against slow teams
    if (p->ma >= 7) {
        float avg_ma = compute_team_avg_ma(opponent);
        value += 0.1f * (p->ma - avg_ma) / 2.0f;
    }

    return value;
}
```

---

## Part 6: Team Development (Level-Up)

### 6.1 Skill Selection Value

When a player levels up, skill selection is crucial. Value depends on:
1. **Player's role**: What does this position do?
2. **Current skills**: Synergies and gaps
3. **Team needs**: What does the team lack?
4. **Meta/matchup**: What opponents will we face?

```c
typedef struct {
    Player *player;
    Team *our_team;
    SkillCategory available_categories;  // Normal/doubles based on roll
    LeagueMeta *meta;                     // Common opponents
} LevelUpContext;

float evaluate_skill_choice(LevelUpContext *ctx, Skill skill) {
    float value = 0.0f;
    Player *p = ctx->player;

    // Base skill value
    value = get_base_skill_value(skill);

    // Role-specific value
    switch (p->position_type) {
        case POS_BLITZER:
            if (skill == SKILL_MIGHTY_BLOW) value += 0.3f;
            if (skill == SKILL_TACKLE) value += 0.2f;
            if (skill == SKILL_PILING_ON) value += 0.2f;
            break;

        case POS_LINEMAN:
            if (skill == SKILL_BLOCK) value += 0.5f;  // First skill should be Block
            if (skill == SKILL_GUARD) value += 0.3f;
            if (skill == SKILL_DIRTY_PLAYER) value += 0.2f;
            break;

        case POS_CATCHER:
            if (skill == SKILL_BLOCK) value += 0.3f;
            if (skill == SKILL_SIDESTEP) value += 0.2f;
            if (skill == SKILL_SPRINT) value += 0.1f;
            break;

        case POS_BIG_GUY:
            if (skill == SKILL_BLOCK) value += 0.5f;  // Usually doubles
            if (skill == SKILL_GUARD) value += 0.3f;
            if (skill == SKILL_BREAK_TACKLE) value += 0.2f;
            break;
    }

    // Synergy with existing skills
    if (has_skill(p, SKILL_MIGHTY_BLOW) && skill == SKILL_PILING_ON) {
        value += 0.2f;  // Combo
    }
    if (has_skill(p, SKILL_BLOCK) && skill == SKILL_DODGE) {
        value += 0.2f;  // Blodge combo
    }
    if (has_skill(p, SKILL_DODGE) && skill == SKILL_SIDESTEP) {
        value += 0.1f;  // Dodge-step combo
    }

    // Team needs
    int team_guard_count = count_team_skill(ctx->our_team, SKILL_GUARD);
    if (skill == SKILL_GUARD && team_guard_count < 2) {
        value += 0.3f;  // Team needs guard
    }

    int team_tackle_count = count_team_skill(ctx->our_team, SKILL_TACKLE);
    if (skill == SKILL_TACKLE && team_tackle_count < 2) {
        value += 0.2f;  // Team needs tackle
    }

    // Meta considerations
    if (ctx->meta != NULL) {
        float meta_dodge_density = ctx->meta->avg_dodge_per_team / 11.0f;
        if (skill == SKILL_TACKLE) {
            value += 0.3f * meta_dodge_density;
        }

        float meta_bash_frequency = ctx->meta->bash_team_frequency;
        if (skill == SKILL_GUARD) {
            value += 0.2f * meta_bash_frequency;
        }
    }

    // Doubles premium (getting a skill from another category is rare)
    if (is_doubles_skill(skill, p)) {
        value += 0.2f;  // Extra value for rarity
    }

    // Stat increases vs skills
    if (skill == SKILL_PLUS_MA && p->ma <= 6) {
        value = 0.5f;  // +MA on slow player is great
    }
    if (skill == SKILL_PLUS_ST) {
        value = 0.8f;  // +ST is almost always best on doubles
    }
    if (skill == SKILL_PLUS_AG && p->ag >= 3) {
        value = 0.4f;  // +AG on already agile player
    }

    return value;
}

Skill select_best_skill(LevelUpContext *ctx) {
    Skill best = SKILL_NONE;
    float best_value = -1.0f;

    for (int s = 0; s < NUM_SKILLS; s++) {
        if (!can_take_skill(ctx->player, s, ctx->available_categories)) {
            continue;
        }

        float v = evaluate_skill_choice(ctx, s);
        if (v > best_value) {
            best_value = v;
            best = s;
        }
    }

    return best;
}
```

### 6.2 Skill Value Table

```c
// Base value of skills (before context)
float BASE_SKILL_VALUE[] = {
    [SKILL_BLOCK] = 0.5f,        // Universally good
    [SKILL_DODGE] = 0.4f,        // Great, but countered by tackle
    [SKILL_GUARD] = 0.4f,        // Essential for bash
    [SKILL_MIGHTY_BLOW] = 0.4f,  // Great damage
    [SKILL_TACKLE] = 0.3f,       // Matchup dependent
    [SKILL_SURE_HANDS] = 0.3f,   // Essential for ball carriers
    [SKILL_CLAW] = 0.4f,         // Elite damage
    [SKILL_FRENZY] = 0.3f,       // High risk/reward
    [SKILL_STAND_FIRM] = 0.3f,   // Positioning
    [SKILL_SIDESTEP] = 0.3f,     // Positioning
    [SKILL_WRESTLE] = 0.3f,      // Alternative to Block
    [SKILL_STRIP_BALL] = 0.2f,   // Situational
    [SKILL_SURE_FEET] = 0.2f,    // Nice to have
    [SKILL_CATCH] = 0.2f,        // For receivers
    [SKILL_PASS] = 0.2f,         // For throwers
    [SKILL_ACCURATE] = 0.2f,     // For throwers
    [SKILL_NERVES_OF_STEEL] = 0.3f, // Elite passing
    [SKILL_LEADER] = 0.2f,       // One per team
    [SKILL_DIRTY_PLAYER] = 0.2f, // For foulers
    // ... etc
};
```

---

## Part 7: League Management

### 7.1 Long-Term Team Value Optimization

In league play, decisions must consider multiple games.

```c
typedef struct {
    int treasury;
    int games_remaining;
    float current_playoff_odds;
    Team team;
    LeagueStandings standings;
} LeagueContext;

// Decision: Fire an injured player or keep?
bool should_fire_player(LeagueContext *ctx, Player *p, Injury injury) {
    // Cost to replace
    int replacement_cost = get_position_cost(p->position);
    int development_loss = p->spp * 5000;  // Rough value of SPP

    // Miss games
    int games_missed = get_injury_duration(injury);

    // Can we afford to keep them?
    bool can_afford_replacement = ctx->treasury >= replacement_cost;

    // Are playoffs locked in?
    bool playoffs_secure = ctx->current_playoff_odds > 0.9f;

    // Decision logic
    if (injury == INJURY_DEAD) {
        return true;  // Must remove
    }

    if (injury == INJURY_NIGGLING) {
        // Niggling injuries stack and get worse
        if (count_niggling(p) >= 2) {
            return true;  // Too risky
        }
        if (p->gold_value < 100000 && can_afford_replacement) {
            return true;  // Not worth keeping
        }
    }

    if (games_missed >= ctx->games_remaining) {
        // Won't play again this season
        if (!playoffs_secure && can_afford_replacement) {
            return true;  // Get fresh player for remaining games
        }
    }

    return false;  // Keep them
}

// Treasury management
typedef enum {
    SPEND_REROLL,
    SPEND_APOTHECARY,
    SPEND_CHEERLEADERS,
    SPEND_ASSISTANT_COACHES,
    SPEND_PLAYER,
    SAVE_TREASURY,
} TreasuryAction;

TreasuryAction decide_treasury_spending(LeagueContext *ctx) {
    // Priority: Re-rolls up to 4
    if (ctx->team.rerolls < 4 && ctx->treasury >= ctx->team.reroll_cost) {
        return SPEND_REROLL;
    }

    // Priority: Apothecary
    if (!ctx->team.has_apothecary && ctx->treasury >= 50000) {
        return SPEND_APOTHECARY;
    }

    // Priority: Fill roster to 13
    if (ctx->team.roster_size < 13 && ctx->treasury >= 50000) {
        return SPEND_PLAYER;
    }

    // Priority: Replace dead/fired players
    if (has_position_gap(&ctx->team) && ctx->treasury >= 80000) {
        return SPEND_PLAYER;
    }

    // Save for emergencies
    if (ctx->treasury < 100000) {
        return SAVE_TREASURY;
    }

    // Low priority: Fan Factor improvements
    if (ctx->team.cheerleaders < 2 && ctx->treasury >= 10000) {
        return SPEND_CHEERLEADERS;
    }

    return SAVE_TREASURY;
}
```

### 7.2 Matchup-Aware Season Strategy

```c
typedef struct {
    int game_number;
    Team *opponent;
    float opponent_strength;
    bool is_must_win;
    bool is_playoff;
} UpcomingGame;

// Adjust player risk tolerance based on upcoming schedule
float compute_risk_tolerance(LeagueContext *ctx, UpcomingGame *upcoming, int num_upcoming) {
    // Base risk tolerance
    float tolerance = 0.5f;

    // Reduce risk before important games
    for (int i = 0; i < min(3, num_upcoming); i++) {
        if (upcoming[i].is_must_win || upcoming[i].is_playoff) {
            tolerance -= 0.1f * (3 - i);  // More reduction for sooner games
        }
    }

    // Increase risk if fighting for playoffs
    if (ctx->current_playoff_odds > 0.3f && ctx->current_playoff_odds < 0.7f) {
        tolerance += 0.1f;  // Every game matters
    }

    // Reduce risk if playoffs secure
    if (ctx->current_playoff_odds > 0.9f) {
        tolerance -= 0.2f;  // Protect players for playoffs
    }

    return clamp(tolerance, 0.2f, 0.8f);
}
```

---

## Part 8: Training Architecture

### 8.1 Curriculum Design

```python
class BloodBowlCurriculum:
    """Progressive training curriculum for Blood Bowl agent."""

    def __init__(self):
        self.stage = 0
        self.stages = [
            # Stage 0: Basic movement and blocking
            {
                "max_turns": 4,
                "opponent": "random",
                "teams": ["human_vs_human"],
                "skills_enabled": ["Block"],
                "inducements": False,
            },
            # Stage 1: Full turns, simple teams
            {
                "max_turns": 16,
                "opponent": "random",
                "teams": ["human_vs_human", "orc_vs_orc"],
                "skills_enabled": ["Block", "Dodge", "SureHands"],
                "inducements": False,
            },
            # Stage 2: Asymmetric matchups
            {
                "max_turns": 16,
                "opponent": "self_play",
                "teams": ["human_vs_orc", "elf_vs_dwarf"],
                "skills_enabled": "all",
                "inducements": False,
            },
            # Stage 3: Full game with inducements
            {
                "max_turns": 16,
                "opponent": "self_play",
                "teams": "all",
                "skills_enabled": "all",
                "inducements": True,
            },
            # Stage 4: League play
            {
                "max_turns": 16,
                "opponent": "self_play",
                "teams": "all",
                "skills_enabled": "all",
                "inducements": True,
                "league_mode": True,
            },
        ]

    def get_env_config(self):
        return self.stages[self.stage]

    def should_advance(self, metrics):
        """Check if ready for next curriculum stage."""
        if self.stage >= len(self.stages) - 1:
            return False

        thresholds = {
            0: {"win_rate": 0.6, "episodes": 10000},
            1: {"win_rate": 0.55, "episodes": 50000},
            2: {"win_rate": 0.52, "episodes": 100000},
            3: {"win_rate": 0.51, "episodes": 200000},
        }

        t = thresholds.get(self.stage, {})
        return (metrics.get("win_rate", 0) >= t.get("win_rate", 1.0) and
                metrics.get("total_episodes", 0) >= t.get("episodes", float("inf")))
```

### 8.2 Reward Shaping Summary

```python
def compute_reward(state, action, next_state, context):
    """Complete reward function for Blood Bowl."""
    reward = 0.0

    # === TERMINAL REWARDS (sparse) ===
    if next_state.is_game_over:
        if next_state.winner == context.our_team:
            reward += 1.0
        elif next_state.winner == context.their_team:
            reward -= 1.0
        # Draw = 0

    # === TOUCHDOWN REWARDS ===
    if next_state.scored_td:
        if next_state.scoring_team == context.our_team:
            reward += 0.5
        else:
            reward -= 0.5

    # === EV-BASED SHAPING (reward good decisions, not luck) ===

    # Block EV
    if action.type == ACTION_BLOCK:
        block_ev = compute_block_ev(
            state, action.attacker, action.target,
            context.matchup
        )
        # Scale by target value
        target_value = state.players[action.target].gold_value / 100000.0
        reward += block_ev * target_value * 0.1

    # Opponent block penalty (symmetric)
    if next_state.opponent_just_blocked:
        opp_block_ev = compute_block_ev(
            state, next_state.opp_attacker, next_state.opp_target,
            context.matchup
        )
        our_player_value = state.players[next_state.opp_target].gold_value / 100000.0
        reward -= opp_block_ev * our_player_value * 0.1

    # === TURNOVER PENALTY ===
    if next_state.turnover and state.active_team == context.our_team:
        # Penalize based on how bad the turnover was
        turn_progress = state.turn_number / 16.0
        reward -= 0.1 * (1.0 - turn_progress)  # Worse early

    # === POSITIONAL VALUE ===
    if state.ball_carrier >= 0 and state.player_team[state.ball_carrier] == context.our_team:
        old_field_value = FIELD_VALUE[state.ball_y][state.ball_x]
        new_field_value = FIELD_VALUE[next_state.ball_y][next_state.ball_x]
        reward += (new_field_value - old_field_value) * 0.05

    # === RESOURCE MANAGEMENT ===
    # Small reward for NOT using re-roll (encourages conservation)
    if action.type == ACTION_USE_REROLL:
        reroll_ev = compute_reroll_ev(context.reroll_context)
        if reroll_ev < 0:
            reward -= 0.02  # Penalize bad re-roll usage

    # === PLAYER PRESERVATION (league mode) ===
    if context.is_league_mode:
        for player in next_state.injured_this_turn:
            if player.team == context.our_team:
                player_value = player.gold_value / 100000.0
                injury_severity = get_injury_severity(player.injury)
                reward -= player_value * injury_severity * 0.1

    return reward
```

### 8.3 Observation Normalization

```python
def normalize_observation(obs: MatchObservation) -> np.ndarray:
    """Convert structured observation to normalized array."""
    normalized = []

    # Board layers: already 0-1
    normalized.append(obs.board.flatten())

    # Player features: normalize each
    player_features = []
    for p in obs.players:
        player_features.extend([
            p.ma / 9.0,          # MA: 1-9
            p.st / 7.0,          # ST: 1-7
            (7 - p.ag) / 6.0,    # AG: 1+-6+ (inverted)
            (7 - p.pa) / 6.0,    # PA: 1+-6+ (inverted)
            (p.av - 3) / 9.0,    # AV: 3+-12+
            p.team,              # 0 or 1
            p.state / 3.0,       # 0-3
            p.has_ball,          # 0 or 1
            p.activated,         # 0 or 1
            p.movement_left / 9.0,
            *p.skills_one_hot,   # Binary skill flags
        ])
    normalized.append(np.array(player_features))

    # Global: already mostly normalized
    normalized.append(obs.global_features)

    # Matchup: already normalized
    normalized.append(obs.matchup_features)

    return np.concatenate(normalized).astype(np.float32)
```

---

## Part 9: Implementation Roadmap

### Phase 1: Core Match Engine (Weeks 1-4)
- [ ] C game state structure
- [ ] Basic actions (move, block, pass)
- [ ] Turnover system
- [ ] Core skills (Block, Dodge, Tackle, Guard, MB)
- [ ] Cython bindings
- [ ] Basic observation space
- [ ] Random opponent baseline

### Phase 2: Complete Rules (Weeks 5-8)
- [ ] All 50+ skills
- [ ] Kick-off events
- [ ] Weather
- [ ] All team rosters
- [ ] Action masking
- [ ] EV-based reward shaping

### Phase 3: Self-Play Training (Weeks 9-12)
- [ ] PufferLib integration
- [ ] Self-play infrastructure
- [ ] Curriculum learning
- [ ] Win rate tracking
- [ ] Matchup-aware observations

### Phase 4: Meta-Game (Weeks 13-16)
- [ ] Inducement selection
- [ ] Apothecary/wizard/bribe timing
- [ ] Pre-match roster selection
- [ ] Resource timing integration

### Phase 5: League Mode (Weeks 17-20)
- [ ] Multi-game sequences
- [ ] Skill selection agent
- [ ] Treasury management
- [ ] Season simulation
- [ ] Long-term value optimization

### Phase 6: Polish & Evaluation (Weeks 21-24)
- [ ] Performance optimization (>1M sps)
- [ ] Evaluation suite
- [ ] Matchup analysis tools
- [ ] Human-playable interface
- [ ] Documentation

---

## Part 10: Open Questions

1. **Single vs Multi-Agent**: Should we train one policy for all teams or specialize?

2. **Action Space**: Flat vs hierarchical? Affects exploration efficiency.

3. **Observation Size**: Full board state vs attention-based selection?

4. **League Credit Assignment**: How to assign reward for season-long decisions?

5. **Opponent Modeling**: Should we explicitly model opponent tendencies?

6. **Transfer Learning**: Train on simple teams, transfer to complex?

7. **Human Evaluation**: How do we efficiently evaluate against human experts?

---

## Appendix A: Matchup Matrix

```
           │ Human │ Orc  │ Skaven │ Dwarf │ Elf  │ Undead │ Chaos
───────────┼───────┼──────┼────────┼───────┼──────┼────────┼───────
Human      │  50   │  45  │   52   │  48   │  48  │   50   │  47
Orc        │  55   │  50  │   55   │  52   │  58  │   50   │  48
Skaven     │  48   │  45  │   50   │  42   │  50  │   48   │  43
Dwarf      │  52   │  48  │   58   │  50   │  55  │   52   │  50
Elf        │  52   │  42  │   50   │  45   │  50  │   48   │  42
Undead     │  50   │  50  │   52   │  48   │  52  │   50   │  48
Chaos      │  53   │  52  │   57   │  50   │  58  │   52   │  50

(Approximate win % for row team vs column team)
```

## Appendix B: Skill Priority by Position

```
Blitzer:   Block > MB > Tackle > Piling On > Guard
Lineman:   Block > Guard > MB > Tackle > Dirty Player
Catcher:   Block > Sidestep > +AG > Sprint > Sure Feet
Thrower:   Block > Sure Hands > Accurate > +AG > Nerves
Big Guy:   Block* > Guard* > Break Tackle > MB > Stand Firm
           (*usually doubles)
```

## Appendix C: Inducement Priority

```
1. Wizard (150k) - if facing bash team
2. Extra Re-roll (100k) - if <3 re-rolls
3. Bribe (100k) - if have secret weapon
4. Bloodweiser Babes (50k) - if facing bash
5. Star Player (variable) - fill remaining budget
6. Mercenaries (variable) - if <11 players
```
