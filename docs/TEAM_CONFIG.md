# Blood Bowl Team Configuration & Game Modes

## Part 1: Team Archetypes

Blood Bowl teams fall into distinct strategic archetypes:

### 1.1 Bash Teams
**Philosophy**: Win through attrition. Remove opponent players, then score.

| Team | Strengths | Weaknesses | Key Players |
|------|-----------|------------|-------------|
| Orc | High AV, cheap bash | Slow, low AG | Big Un Blockers |
| Dwarf | Excellent Block/Tackle | Very slow (MA 4-5) | Troll Slayers |
| Chaos | High ST potential | Expensive, slow dev | Chosen Blockers |
| Nurgle | Disturbing Presence | Very slow, fragile AG | Rotters (fodder) |

**Matchup Strategy**:
- Against Agility: Focus on knocking down ball carrier, control the cage
- Against Bash Mirror: Guard advantage wins, first block matters
- Resource Priority: Apothecary, Bribes (for fouling)

### 1.2 Agility Teams
**Philosophy**: Score quickly, avoid contact.

| Team | Strengths | Weaknesses | Key Players |
|------|-----------|------------|-------------|
| Wood Elf | Fastest (MA 7-9), AG 2+ | Fragile (AV 8) | Wardancers |
| Skaven | Very fast, cheap | Low AV, unreliable | Gutter Runners |
| High Elf | Excellent passing | Expensive | Phoenix Warriors |
| Dark Elf | Well-rounded agility | Slightly slower | Witch Elves |

**Matchup Strategy**:
- Against Bash: Stay away, one-turn score threats, don't engage
- Against Agility Mirror: Ball control wins, interception risk
- Resource Priority: Re-rolls (for dodges/passes)

### 1.3 Hybrid Teams
**Philosophy**: Flexible approach based on matchup.

| Team | Strengths | Weaknesses | Key Players |
|------|-----------|------------|-------------|
| Human | Balanced stats | No specialization | Blitzers |
| Undead | Regen, varied players | No passing game | Mummies + Ghouls |
| Lizardmen | Saurus ST + Skink speed | Split team | Kroxigor |
| Amazon | Dodge everywhere | Low ST | Blitzers |

---

## Part 2: Starting Roster Configurations

### 2.1 Optimal Starting Rosters

**Human (1M gold)**
```
4x Blitzer       @ 85k = 340k
2x Catcher       @ 65k = 130k
1x Thrower       @ 80k = 80k
4x Lineman       @ 50k = 200k
3x Re-rolls      @ 50k = 150k
Apothecary       @ 50k = 50k
                 Total: 950k (50k treasury)
```

**Orc (1M gold)**
```
4x Blitzer       @ 80k = 320k
4x Big Un Blocker @ 90k = 360k
1x Thrower       @ 65k = 65k
2x Lineman       @ 50k = 100k
2x Re-rolls      @ 60k = 120k
                 Total: 965k (35k treasury)
```

**Skaven (1M gold)**
```
2x Gutter Runner @ 85k = 170k
2x Blitzer       @ 90k = 180k
1x Thrower       @ 85k = 85k
6x Lineman       @ 50k = 300k
2x Re-rolls      @ 50k = 100k
Apothecary       @ 50k = 50k
                 Total: 885k (115k treasury for Rat Ogre later)
```

**Dwarf (1M gold)**
```
2x Blitzer       @ 80k = 160k
2x Troll Slayer  @ 95k = 190k
2x Runner        @ 85k = 170k
5x Blocker       @ 70k = 350k
2x Re-rolls      @ 50k = 100k
                 Total: 970k (30k treasury)
```

### 2.2 Aggressive/Risky Builds

For teams that want maximum immediate power:

**All-Bash Orc**
```
4x Blitzer       @ 80k = 320k
4x Big Un Blocker @ 90k = 360k
1x Troll         @ 115k = 115k
2x Goblin        @ 40k = 80k
1x Re-roll       @ 60k = 60k
                 Total: 935k
```

**Speed Skaven**
```
4x Gutter Runner @ 85k = 340k
2x Blitzer       @ 90k = 180k
5x Lineman       @ 50k = 250k
1x Re-roll       @ 50k = 50k
Apothecary       @ 50k = 50k
                 Total: 870k (extra cash for Rat Ogre)
```

---

## Part 3: Random Team Generation

For diverse training, we need to generate varied but valid rosters.

### 3.1 Team Generation Algorithm

```c
typedef struct {
    int position_type;
    int count;
    int min_count;
    int max_count;
    int cost;
    int st, ma, ag, av;
    uint32_t starting_skills;
} PositionTemplate;

typedef struct {
    char name[32];
    int reroll_cost;
    int num_positions;
    PositionTemplate positions[8];
    bool has_apothecary;
    int tier;  // 1=competitive, 2=balanced, 3=challenging
} TeamTemplate;

// Generate a random valid roster
void generate_random_roster(
    TeamTemplate *template,
    int budget,
    Team *output,
    uint64_t *rng
) {
    output->gold_spent = 0;
    output->roster_size = 0;

    // Step 1: Satisfy minimums
    for (int i = 0; i < template->num_positions; i++) {
        PositionTemplate *pos = &template->positions[i];
        for (int j = 0; j < pos->min_count; j++) {
            add_player(output, pos);
        }
    }

    // Step 2: Fill to 11+ with random picks
    while (output->roster_size < 11 && output->gold_spent < budget - 50000) {
        // Pick random position (weighted by tier/cost)
        int pos_idx = weighted_random_position(template, rng);
        PositionTemplate *pos = &template->positions[pos_idx];

        // Check limits
        int current_count = count_position(output, pos_idx);
        if (current_count >= pos->max_count) continue;
        if (output->gold_spent + pos->cost > budget) continue;

        add_player(output, pos);
    }

    // Step 3: Buy re-rolls (2-4)
    int target_rerolls = 2 + rand_int(rng, 3);  // 2-4
    while (output->rerolls < target_rerolls &&
           output->gold_spent + template->reroll_cost <= budget) {
        output->rerolls++;
        output->gold_spent += template->reroll_cost;
    }

    // Step 4: Buy apothecary if available and affordable
    if (template->has_apothecary &&
        output->gold_spent + 50000 <= budget) {
        output->has_apothecary = true;
        output->gold_spent += 50000;
    }

    // Step 5: Fill remaining roster slots if cash available
    while (output->roster_size < 14 &&
           output->gold_spent + get_cheapest_position_cost(template) <= budget) {
        int pos_idx = get_cheapest_available_position(template, output);
        if (pos_idx < 0) break;
        add_player(output, &template->positions[pos_idx]);
    }
}
```

### 3.2 Random Team for Training

```c
typedef enum {
    RANDOM_ANY,              // Any valid team
    RANDOM_BASH,             // Bash archetype only
    RANDOM_AGILITY,          // Agility archetype only
    RANDOM_HYBRID,           // Hybrid teams only
    RANDOM_MIRROR,           // Same team both sides
    RANDOM_COUNTER,          // Opposite archetype matchup
} RandomTeamMode;

void generate_training_matchup(
    RandomTeamMode mode,
    Team *team_a,
    Team *team_b,
    uint64_t *rng
) {
    TeamTemplate *all_templates[20];
    int num_templates = load_all_templates(all_templates);

    switch (mode) {
        case RANDOM_ANY:
            generate_random_roster(random_template(all_templates, num_templates, rng),
                                   1000000, team_a, rng);
            generate_random_roster(random_template(all_templates, num_templates, rng),
                                   1000000, team_b, rng);
            break;

        case RANDOM_MIRROR:
            TeamTemplate *t = random_template(all_templates, num_templates, rng);
            generate_random_roster(t, 1000000, team_a, rng);
            generate_random_roster(t, 1000000, team_b, rng);
            break;

        case RANDOM_COUNTER:
            // Pick bash team vs agility team
            if (rand_int(rng, 2) == 0) {
                generate_random_roster(random_bash_template(rng), 1000000, team_a, rng);
                generate_random_roster(random_agility_template(rng), 1000000, team_b, rng);
            } else {
                generate_random_roster(random_agility_template(rng), 1000000, team_a, rng);
                generate_random_roster(random_bash_template(rng), 1000000, team_b, rng);
            }
            break;

        // ... other modes
    }
}
```

### 3.3 Developed Team Generation (League Simulation)

For training on developed teams with skills:

```c
typedef struct {
    int team_value_target;   // e.g., 1200k
    int avg_spp_per_player;  // SPP distribution
    float skill_randomness;  // How random vs optimal
} DevelopedTeamConfig;

void generate_developed_team(
    TeamTemplate *template,
    DevelopedTeamConfig *config,
    Team *output,
    uint64_t *rng
) {
    // Generate base roster
    generate_random_roster(template, 1000000, output, rng);

    // Add skills to reach target TV
    int current_tv = compute_team_value(output);
    int skill_budget = config->team_value_target - current_tv;

    while (skill_budget > 20000 && output->total_skills < 20) {
        // Pick random player
        int player_idx = rand_int(rng, output->roster_size);
        Player *p = &output->players[player_idx];

        // Pick skill (sometimes optimal, sometimes random)
        Skill skill;
        if (randf(rng) < config->skill_randomness) {
            skill = random_valid_skill(p, rng);
        } else {
            skill = optimal_skill_for_position(p, output);
        }

        if (skill != SKILL_NONE && !has_skill(p, skill)) {
            add_skill(p, skill);
            skill_budget -= 20000;  // Rough cost per skill
        }
    }
}
```

---

## Part 4: Matchup-Specific Configurations

### 4.1 Pre-Game Analysis

```c
typedef struct {
    float expected_win_rate;
    TeamArchetype our_archetype;
    TeamArchetype their_archetype;
    MatchupType matchup_type;
    StrategyRecommendation strategy;
    float key_skill_importance[NUM_SKILLS];
} MatchupAnalysis;

typedef enum {
    MATCHUP_BASH_MIRROR,
    MATCHUP_AGILITY_MIRROR,
    MATCHUP_BASH_VS_AGILITY,
    MATCHUP_HYBRID,
} MatchupType;

typedef struct {
    bool prefer_receiving;
    bool should_cage;
    bool should_spread;
    float aggression_level;      // 0-1: how much to block
    float risk_tolerance;        // 0-1: how much to GFI/dodge
    int priority_targets[3];     // Which players to hit first
} StrategyRecommendation;

void analyze_matchup(Team *our_team, Team *their_team, MatchupAnalysis *analysis) {
    // Classify teams
    analysis->our_archetype = classify_team_archetype(our_team);
    analysis->their_archetype = classify_team_archetype(their_team);

    // Determine matchup type
    if (is_bash(analysis->our_archetype) && is_bash(analysis->their_archetype)) {
        analysis->matchup_type = MATCHUP_BASH_MIRROR;
    } else if (is_agility(analysis->our_archetype) && is_agility(analysis->their_archetype)) {
        analysis->matchup_type = MATCHUP_AGILITY_MIRROR;
    } else if (is_bash(analysis->our_archetype) != is_bash(analysis->their_archetype)) {
        analysis->matchup_type = MATCHUP_BASH_VS_AGILITY;
    } else {
        analysis->matchup_type = MATCHUP_HYBRID;
    }

    // Compute skill importance for this matchup
    MatchupContext ctx;
    compute_matchup_context_from_teams(our_team, their_team, &ctx);

    for (int s = 0; s < NUM_SKILLS; s++) {
        analysis->key_skill_importance[s] = get_skill_value_in_matchup(s, &ctx);
    }

    // Strategy recommendation
    switch (analysis->matchup_type) {
        case MATCHUP_BASH_MIRROR:
            analysis->strategy.prefer_receiving = false;  // Kick, grind them down
            analysis->strategy.should_cage = true;
            analysis->strategy.should_spread = false;
            analysis->strategy.aggression_level = 0.8f;
            analysis->strategy.risk_tolerance = 0.3f;
            // Priority: Their Guard players, then Mighty Blow
            find_priority_targets(their_team, analysis->strategy.priority_targets,
                                  (Skill[]){SKILL_GUARD, SKILL_MIGHTY_BLOW, SKILL_BLOCK}, 3);
            break;

        case MATCHUP_BASH_VS_AGILITY:
            if (is_bash(analysis->our_archetype)) {
                // We're bash, they're agility
                analysis->strategy.prefer_receiving = false;  // Grind
                analysis->strategy.should_cage = true;
                analysis->strategy.should_spread = false;
                analysis->strategy.aggression_level = 0.7f;
                analysis->strategy.risk_tolerance = 0.2f;
                // Priority: Ball carrier, then fast players
                find_priority_targets_by_role(their_team, analysis->strategy.priority_targets,
                                              (Role[]){ROLE_BALL_CARRIER, ROLE_SCORER}, 2);
            } else {
                // We're agility, they're bash
                analysis->strategy.prefer_receiving = true;   // Score fast
                analysis->strategy.should_cage = false;
                analysis->strategy.should_spread = true;
                analysis->strategy.aggression_level = 0.3f;  // Avoid blocks
                analysis->strategy.risk_tolerance = 0.6f;    // Worth dodging
                // Priority: Avoid their blitzers
            }
            break;

        case MATCHUP_AGILITY_MIRROR:
            analysis->strategy.prefer_receiving = true;   // First score matters
            analysis->strategy.should_cage = false;
            analysis->strategy.should_spread = true;
            analysis->strategy.aggression_level = 0.4f;
            analysis->strategy.risk_tolerance = 0.5f;
            // Priority: Their ball carrier
            break;

        default:
            // Balanced/hybrid strategy
            analysis->strategy.prefer_receiving = true;
            analysis->strategy.should_cage = true;
            analysis->strategy.should_spread = false;
            analysis->strategy.aggression_level = 0.5f;
            analysis->strategy.risk_tolerance = 0.4f;
            break;
    }

    // Compute expected win rate
    analysis->expected_win_rate = compute_expected_win_rate(our_team, their_team);
}
```

### 4.2 Encoding Strategy as Observation

```c
// Add strategy features to observation
void encode_strategy_features(
    MatchupAnalysis *analysis,
    float *features,
    int *idx
) {
    // Matchup type one-hot
    for (int i = 0; i < NUM_MATCHUP_TYPES; i++) {
        features[(*idx)++] = (analysis->matchup_type == i) ? 1.0f : 0.0f;
    }

    // Strategy recommendation
    features[(*idx)++] = analysis->strategy.prefer_receiving ? 1.0f : 0.0f;
    features[(*idx)++] = analysis->strategy.should_cage ? 1.0f : 0.0f;
    features[(*idx)++] = analysis->strategy.should_spread ? 1.0f : 0.0f;
    features[(*idx)++] = analysis->strategy.aggression_level;
    features[(*idx)++] = analysis->strategy.risk_tolerance;

    // Key skill importance (top 10 skills)
    Skill important_skills[] = {
        SKILL_BLOCK, SKILL_DODGE, SKILL_TACKLE, SKILL_GUARD,
        SKILL_MIGHTY_BLOW, SKILL_CLAW, SKILL_SURE_HANDS,
        SKILL_STRIP_BALL, SKILL_FRENZY, SKILL_STAND_FIRM
    };
    for (int i = 0; i < 10; i++) {
        features[(*idx)++] = analysis->key_skill_importance[important_skills[i]];
    }

    // Expected win rate
    features[(*idx)++] = analysis->expected_win_rate;
}
```

---

## Part 5: Special Game Situations

### 5.1 Receiving vs Kicking Strategy

```c
typedef struct {
    int score_diff;
    int turn;
    int half;
    bool we_have_ball;
    int our_players;
    int their_players;
    TeamArchetype our_archetype;
    float time_pressure;         // How urgent to score
} GameSituation;

typedef enum {
    STRAT_GRIND,                 // Slow cage, burn clock
    STRAT_SCORE_FAST,            // Quick score
    STRAT_STALL,                 // Hold ball, don't score
    STRAT_TWO_FOR_ONE,           // Quick score to get ball back
    STRAT_PREVENT_SCORE,         // Defensive focus
    STRAT_ALL_OUT_ATTACK,        // Must score now
} SituationalStrategy;

SituationalStrategy determine_strategy(GameSituation *sit) {
    // === RECEIVING FIRST HALF ===
    if (sit->half == 1 && sit->we_have_ball) {
        if (is_bash(sit->our_archetype)) {
            // Bash teams grind for 8 turns, score on turn 8
            return STRAT_GRIND;
        } else {
            // Agility teams might want two-for-one
            // Score turn 6-7, get ball back turn 8
            if (sit->turn <= 5) {
                return STRAT_SCORE_FAST;
            } else if (sit->turn == 8) {
                return STRAT_STALL;  // Don't score, force overtime
            }
        }
    }

    // === RECEIVING SECOND HALF ===
    if (sit->half == 2 && sit->we_have_ball) {
        if (sit->score_diff < 0) {
            // Behind: must score
            return STRAT_SCORE_FAST;
        } else if (sit->score_diff > 0) {
            // Ahead: stall to burn clock
            return STRAT_STALL;
        } else {
            // Tied: grind for winning score
            return STRAT_GRIND;
        }
    }

    // === KICKING ===
    if (!sit->we_have_ball) {
        if (sit->score_diff > 0 && sit->turn >= 12) {
            // Ahead late: just prevent score
            return STRAT_PREVENT_SCORE;
        } else {
            // Try to cause turnover, get ball
            return STRAT_PREVENT_SCORE;
        }
    }

    // === CRITICAL MOMENTS ===
    // Down by 2+ with few turns left
    if (sit->score_diff <= -2 && (16 - sit->turn) <= 4) {
        return STRAT_ALL_OUT_ATTACK;
    }

    // Up by 2+ late game
    if (sit->score_diff >= 2 && sit->turn >= 12) {
        return STRAT_STALL;
    }

    return STRAT_GRIND;  // Default
}

// Adjust risk tolerance based on strategy
float strategy_risk_modifier(SituationalStrategy strat) {
    switch (strat) {
        case STRAT_GRIND:           return 0.0f;   // Base risk
        case STRAT_SCORE_FAST:      return 0.2f;   // More aggressive
        case STRAT_STALL:           return -0.3f;  // Very conservative
        case STRAT_TWO_FOR_ONE:     return 0.3f;   // Aggressive
        case STRAT_PREVENT_SCORE:   return 0.1f;   // Slightly aggressive
        case STRAT_ALL_OUT_ATTACK:  return 0.5f;   // Maximum aggression
    }
    return 0.0f;
}
```

### 5.2 Inducement Timing (Wizard Example)

```c
typedef struct {
    bool wizard_available;
    bool bribe_available;
    int bribes_remaining;
    bool opponent_has_ball;
    int opponent_ball_carrier_position[2];
    int opponents_in_cluster[8];  // Count for each cluster
    int max_cluster_size;
    int best_cluster_position[2];
    int turn;
    int score_diff;
} InducementState;

typedef enum {
    WIZARD_WAIT,
    WIZARD_LIGHTNING_BALL_CARRIER,
    WIZARD_FIREBALL_CLUSTER,
} WizardAction;

WizardAction decide_wizard_action(InducementState *state) {
    if (!state->wizard_available) {
        return WIZARD_WAIT;
    }

    // === DEFENSIVE USE: Stop them scoring ===
    if (state->opponent_has_ball) {
        int opp_y = state->opponent_ball_carrier_position[1];
        int turns_to_endzone = opp_y;  // Simplified

        // If they're about to score and we're tied/behind
        if (turns_to_endzone <= 2 && state->score_diff >= 0) {
            return WIZARD_LIGHTNING_BALL_CARRIER;
        }

        // If they're deep in our territory
        if (turns_to_endzone <= 4 && state->score_diff > 0) {
            // Only use if we're protecting a lead
            return WIZARD_LIGHTNING_BALL_CARRIER;
        }
    }

    // === OFFENSIVE USE: Fireball cluster ===
    if (state->max_cluster_size >= 4) {
        // Great fireball opportunity
        return WIZARD_FIREBALL_CLUSTER;
    }

    // === LATE GAME: Use it or lose it ===
    if (state->turn >= 14) {
        if (state->opponent_has_ball) {
            return WIZARD_LIGHTNING_BALL_CARRIER;
        }
        if (state->max_cluster_size >= 3) {
            return WIZARD_FIREBALL_CLUSTER;
        }
    }

    return WIZARD_WAIT;
}

// Bribe decision for secret weapons
typedef enum {
    BRIBE_WAIT,
    BRIBE_USE,
    BRIBE_DECLINE,
} BribeAction;

BribeAction decide_bribe_action(
    InducementState *state,
    Player *ejected_player,
    bool is_secret_weapon
) {
    if (state->bribes_remaining == 0) {
        return BRIBE_DECLINE;
    }

    float player_value = ejected_player->gold_value / 100000.0f;
    int turns_remaining = 16 - state->turn;

    if (is_secret_weapon) {
        // Secret weapons: value depends on remaining impact
        // Deathroller on turn 1: huge value
        // Deathroller on turn 15: minimal value
        float turn_value = turns_remaining / 8.0f;  // Per-drive value
        if (turn_value * player_value > 0.5f) {
            return BRIBE_USE;
        }
    } else {
        // Regular player fouled out
        // Value = player_value * game_fraction
        float game_value = player_value * (turns_remaining / 16.0f);
        if (game_value > 0.3f) {
            return BRIBE_USE;
        }
    }

    return BRIBE_DECLINE;
}
```

---

## Part 6: Training Data Generation

### 6.1 Diverse Game Generation

```python
class BloodBowlGameGenerator:
    """Generate diverse games for training."""

    def __init__(self):
        self.team_templates = load_all_team_templates()

    def generate_game(self, mode='random'):
        """Generate a game configuration."""

        if mode == 'random':
            # Completely random valid matchup
            team_a = self.random_roster(random.choice(self.team_templates))
            team_b = self.random_roster(random.choice(self.team_templates))

        elif mode == 'mirror':
            # Same team type, different rosters
            template = random.choice(self.team_templates)
            team_a = self.random_roster(template)
            team_b = self.random_roster(template)

        elif mode == 'counter':
            # Deliberate mismatch (bash vs agility)
            if random.random() < 0.5:
                team_a = self.random_roster(random.choice(self.bash_templates))
                team_b = self.random_roster(random.choice(self.agility_templates))
            else:
                team_a = self.random_roster(random.choice(self.agility_templates))
                team_b = self.random_roster(random.choice(self.bash_templates))

        elif mode == 'developed':
            # Teams with developed skills (league-style)
            template_a = random.choice(self.team_templates)
            template_b = random.choice(self.team_templates)
            team_a = self.developed_roster(template_a, tv_target=1200000)
            team_b = self.developed_roster(template_b, tv_target=1200000)

        elif mode == 'inducement':
            # One team has significant petty cash
            template_a = random.choice(self.team_templates)
            template_b = random.choice(self.team_templates)
            team_a = self.random_roster(template_a)
            team_b = self.developed_roster(template_b, tv_target=1300000)
            # Team A gets inducements due to TV difference

        # Generate starting conditions
        receiving_team = random.randint(0, 1)
        weather = self.random_weather()

        return GameConfig(
            team_a=team_a,
            team_b=team_b,
            receiving_team=receiving_team,
            weather=weather,
        )

    def random_roster(self, template, budget=1000000):
        """Generate random valid roster."""
        roster = Roster(template)

        # Fill minimums
        for pos in template.positions:
            for _ in range(pos.min_count):
                roster.add_player(pos)

        # Fill to 11 with weighted random
        while roster.player_count < 11:
            pos = random.choices(
                template.positions,
                weights=[1.0 / (p.cost + 1) for p in template.positions]
            )[0]
            if roster.can_add(pos) and roster.can_afford(pos, budget):
                roster.add_player(pos)

        # Buy re-rolls (2-4)
        target_rr = random.randint(2, 4)
        while roster.rerolls < target_rr and roster.can_afford_reroll(budget):
            roster.buy_reroll()

        # Maybe apothecary
        if random.random() < 0.8 and roster.can_afford_apothecary(budget):
            roster.buy_apothecary()

        return roster

    def developed_roster(self, template, tv_target):
        """Generate roster with skills."""
        roster = self.random_roster(template)

        while roster.team_value < tv_target:
            # Pick random player
            player = random.choice(roster.players)

            # Pick skill (80% optimal, 20% random)
            if random.random() < 0.8:
                skill = optimal_skill(player)
            else:
                skill = random_valid_skill(player)

            if skill and not player.has_skill(skill):
                player.add_skill(skill)

        return roster
```

### 6.2 Training Distribution

```python
TRAINING_DISTRIBUTION = {
    'random': 0.3,      # Basic diverse training
    'mirror': 0.2,      # Learn team-specific tactics
    'counter': 0.2,     # Learn matchup-specific play
    'developed': 0.2,   # Handle skilled players
    'inducement': 0.1,  # Learn inducement usage
}

class MatchupCurriculum:
    """Curriculum that introduces complexity gradually."""

    def __init__(self):
        self.stage = 0

    def get_distribution(self):
        if self.stage == 0:
            # Stage 0: Simple mirror matches
            return {'mirror': 1.0}
        elif self.stage == 1:
            # Stage 1: Add random
            return {'mirror': 0.5, 'random': 0.5}
        elif self.stage == 2:
            # Stage 2: Add counter matchups
            return {'mirror': 0.3, 'random': 0.4, 'counter': 0.3}
        elif self.stage == 3:
            # Stage 3: Add developed teams
            return {'mirror': 0.2, 'random': 0.3, 'counter': 0.2, 'developed': 0.3}
        else:
            # Stage 4+: Full distribution
            return TRAINING_DISTRIBUTION
```

---

## Part 7: Observation Space for Team Config

### 7.1 Team Encoding

```c
// Encode team composition as observation features
void encode_team_composition(
    Team *team,
    float *features,
    int *idx
) {
    // Position counts (normalized)
    int pos_counts[8] = {0};
    for (int i = 0; i < team->roster_size; i++) {
        pos_counts[team->players[i].position_type]++;
    }
    for (int i = 0; i < 8; i++) {
        features[(*idx)++] = pos_counts[i] / 11.0f;
    }

    // Aggregate stats
    float total_ma = 0, total_st = 0, total_ag = 0, total_av = 0;
    for (int i = 0; i < team->roster_size; i++) {
        total_ma += team->players[i].ma;
        total_st += team->players[i].st;
        total_ag += 7 - team->players[i].ag;  // Invert AG
        total_av += team->players[i].av;
    }
    int n = team->roster_size;
    features[(*idx)++] = (total_ma / n) / 9.0f;
    features[(*idx)++] = (total_st / n) / 7.0f;
    features[(*idx)++] = (total_ag / n) / 6.0f;
    features[(*idx)++] = (total_av / n - 7) / 5.0f;

    // Key skill counts
    Skill tracked_skills[] = {
        SKILL_BLOCK, SKILL_DODGE, SKILL_TACKLE, SKILL_GUARD,
        SKILL_MIGHTY_BLOW, SKILL_CLAW, SKILL_SURE_HANDS,
        SKILL_FRENZY, SKILL_STAND_FIRM, SKILL_SIDESTEP
    };
    for (int s = 0; s < 10; s++) {
        int count = count_team_skill(team, tracked_skills[s]);
        features[(*idx)++] = count / 11.0f;
    }

    // Resources
    features[(*idx)++] = team->rerolls / 4.0f;
    features[(*idx)++] = team->has_apothecary ? 1.0f : 0.0f;

    // Team value (for inducement calculation)
    features[(*idx)++] = team->team_value / 2000000.0f;

    // Team archetype (one-hot)
    TeamArchetype arch = classify_team_archetype(team);
    for (int i = 0; i < NUM_ARCHETYPES; i++) {
        features[(*idx)++] = (arch == i) ? 1.0f : 0.0f;
    }
}
```

### 7.2 Full Pre-Game Observation

```c
typedef struct {
    // Our team (composition + roster)
    float our_team_features[64];

    // Their team (composition + roster)
    float their_team_features[64];

    // Matchup features
    float matchup_features[32];

    // Available inducements
    float inducement_features[16];

    // Game context
    float weather;
    float we_receive;
    float is_league;
    float games_remaining;
    float playoff_odds;
} PreGameObservation;

void compute_pre_game_observation(
    Team *our_team,
    Team *their_team,
    GameContext *ctx,
    PreGameObservation *obs
) {
    int idx;

    // Encode teams
    idx = 0;
    encode_team_composition(our_team, obs->our_team_features, &idx);

    idx = 0;
    encode_team_composition(their_team, obs->their_team_features, &idx);

    // Compute matchup
    MatchupContext matchup;
    compute_matchup_context_from_teams(our_team, their_team, &matchup);

    idx = 0;
    encode_matchup_features(&matchup, obs->matchup_features, &idx);

    // Inducements
    int petty_cash = their_team->team_value - our_team->team_value;
    if (petty_cash < 0) petty_cash = 0;

    idx = 0;
    obs->inducement_features[idx++] = petty_cash / 500000.0f;
    obs->inducement_features[idx++] = (petty_cash >= 150000) ? 1.0f : 0.0f;  // Can afford wizard
    obs->inducement_features[idx++] = (petty_cash >= 100000) ? 1.0f : 0.0f;  // Can afford bribe
    // ... more inducement options

    // Context
    obs->weather = ctx->weather / 5.0f;
    obs->we_receive = ctx->we_receive ? 1.0f : 0.0f;
    obs->is_league = ctx->is_league ? 1.0f : 0.0f;
    obs->games_remaining = ctx->games_remaining / 20.0f;
    obs->playoff_odds = ctx->playoff_odds;
}
```

---

## Summary

This document covers:

1. **Team Archetypes**: Bash, Agility, Hybrid with strategic implications
2. **Starting Rosters**: Optimal builds for major teams
3. **Random Generation**: Algorithms for diverse training data
4. **Matchup Analysis**: Pre-game strategic recommendations
5. **Situational Strategy**: Receiving/kicking, game state dependent
6. **Inducement Timing**: Wizard, bribe, and other special items
7. **Training Distribution**: Balanced game generation for learning
8. **Observation Encoding**: Team composition as features

The key insight is that **the agent needs to understand team composition** to play well. A policy that works for Dwarves won't work for Skaven. The observation space must include enough information about both teams' composition and the resulting matchup dynamics.
