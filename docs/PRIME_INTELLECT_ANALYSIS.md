# Prime Intellect RL Techniques: Applicability to Blood Bowl

## Executive Summary

Prime Intellect's RL stack (prime-rl, verifiers, GRPO) is primarily designed for LLM reasoning tasks, but several architectural patterns and techniques are highly applicable to our Blood Bowl environment. This document analyzes what to adopt, adapt, and avoid.

**Key Takeaways:**
1. **Async training architecture** - Highly applicable, adopt for distributed self-play
2. **GRPO algorithm** - NOT recommended for Blood Bowl (underperforms PPO in game RL)
3. **Two-sided clipping** - Adopt for training stability
4. **Critic-free training** - Avoid for long-horizon games (Blood Bowl needs value function)
5. **Environment interface patterns** - Adapt the modular rubric/verifier design

---

## Part 1: Prime Intellect Architecture Overview

### 1.1 Core Components

```
┌─────────────────────────────────────────────────────────────────┐
│                    PRIME-RL ARCHITECTURE                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │  Inference   │    │   Trainer    │    │  Validator   │      │
│  │   Workers    │───▶│    (GRPO)    │◀───│  (TOPLOC)    │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│         │                   │                                    │
│         │            ┌──────▼──────┐                            │
│         └───────────▶│  Shardcast  │ (Weight broadcast)         │
│                      └─────────────┘                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Key Innovations

| Innovation | Description | For LLM RL | For Game RL |
|------------|-------------|------------|-------------|
| **Async 4-step** | Training proceeds with 4-step policy lag | Essential | Useful |
| **GRPO** | Critic-free group advantage | Huge memory savings | Problematic |
| **Two-sided clipping** | Clip ratios for both positive/negative advantages | Stabilizes training | Adopt |
| **Shardcast** | Efficient distributed weight broadcast | Enables scale | Adopt |
| **Verifiers** | Modular reward/verification components | Clean abstraction | Adapt |

---

## Part 2: GRPO vs PPO for Blood Bowl

### 2.1 Why GRPO Struggles in Game RL

Recent research ([Learning Without Critics?](https://arxiv.org/html/2511.03527v1)) tested GRPO on classical RL environments and found **significant underperformance** compared to PPO:

| Environment | PPO Score | GRPO Score | Issue |
|-------------|-----------|------------|-------|
| CartPole-v1 | ~500 | ~500 | Works (short horizon) |
| Acrobot-v1 | ~-80 | ~-150 | PPO much better |
| HalfCheetah | ~5000 | ~1500 | PPO dominates |
| Humanoid | ~6000 | ~1200 | PPO dominates |

**Root Causes:**

1. **Credit Assignment**: GRPO uses episodic scalar advantage - it can't distinguish which actions within a trajectory were good vs bad
   ```
   GRPO:     A(τ) = (R(τ) - mean(R)) / std(R)  # Same for all steps!
   PPO/GAE:  A(t) = Σ (γλ)^k δ_{t+k}           # Per-step advantage
   ```

2. **Long Horizons**: Blood Bowl has 16+ turns with ~50-100 actions per game. GRPO's episodic advantage provides no signal for individual action quality.

3. **Sparse Rewards**: With only win/loss/TD outcomes, GRPO can't learn which blocks, moves, or passes were good.

### 2.2 Blood Bowl Characteristics

| Characteristic | Impact on Algorithm Choice |
|----------------|----------------------------|
| ~100 actions per game | Need per-step credit assignment (PPO) |
| Stochastic outcomes | Need value function to reduce variance |
| Sparse terminal reward | Need dense shaping rewards |
| Complex state space | Need learned value function |
| Self-play training | Async architecture beneficial |

### 2.3 Recommendation: PPO with Prime Intellect Enhancements

```python
# Our approach: PPO + Prime Intellect innovations
class BloodBowlPPO:
    """PPO with Prime Intellect-inspired enhancements."""

    def __init__(self):
        # Standard PPO with value function (NOT GRPO)
        self.policy = PolicyNetwork()
        self.value = ValueNetwork()  # Keep the critic!

        # Prime Intellect innovations
        self.use_two_sided_clipping = True
        self.async_training = True
        self.clip_eps = 0.2
        self.clip_delta = 0.5  # Two-sided clipping param

    def compute_loss(self, ratio, advantage):
        # Standard PPO clipping
        clipped_ratio = torch.clamp(ratio, 1 - self.clip_eps, 1 + self.clip_eps)

        # Two-sided clipping (Prime Intellect innovation)
        if self.use_two_sided_clipping:
            # Also clip for negative advantages
            negative_mask = advantage < 0
            clipped_ratio[negative_mask] = torch.clamp(
                ratio[negative_mask],
                1 / self.clip_delta,  # Prevent ratio from going too high
                self.clip_delta        # Or too low
            )

        policy_loss = -torch.min(
            ratio * advantage,
            clipped_ratio * advantage
        ).mean()

        return policy_loss
```

---

## Part 3: Async Training Architecture (ADOPT)

Prime Intellect's async architecture is directly applicable to Blood Bowl self-play.

### 3.1 Architecture for Blood Bowl

```
┌─────────────────────────────────────────────────────────────────┐
│                BLOOD BOWL ASYNC TRAINING                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                 GAME SERVERS (CPU)                       │    │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐          │    │
│  │  │Game 1│ │Game 2│ │Game 3│ │ ...  │ │Game N│          │    │
│  │  │ BB   │ │ BB   │ │ BB   │ │      │ │ BB   │          │    │
│  │  └──┬───┘ └──┬───┘ └──┬───┘ └──────┘ └──┬───┘          │    │
│  │     │        │        │                  │              │    │
│  └─────┼────────┼────────┼──────────────────┼──────────────┘    │
│        │        │        │                  │                    │
│        ▼        ▼        ▼                  ▼                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              EXPERIENCE BUFFER                           │    │
│  │  (obs, action, reward, next_obs, done, action_mask)     │    │
│  └─────────────────────────────────────────────────────────┘    │
│        │                                                         │
│        ▼                                                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                  TRAINER (GPU)                           │    │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐           │    │
│  │  │   Policy   │ │   Value    │ │    PPO     │           │    │
│  │  │  Network   │ │   Network  │ │  Optimizer │           │    │
│  │  └────────────┘ └────────────┘ └────────────┘           │    │
│  └─────────────────────────────────────────────────────────┘    │
│        │                                                         │
│        ▼                                                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              WEIGHT BROADCAST                            │    │
│  │  (Shardcast-style async distribution)                   │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Off-Policy Tolerance

Prime Intellect showed that **4-step policy lag** is acceptable without performance degradation. For Blood Bowl:

```python
class AsyncBloodBowlTrainer:
    """Async training with off-policy tolerance."""

    def __init__(self):
        self.max_policy_lag = 4  # Steps behind is OK
        self.experience_buffer = ExperienceBuffer(max_size=100000)
        self.current_policy_version = 0

    def is_experience_valid(self, experience):
        """Check if experience is too stale."""
        policy_lag = self.current_policy_version - experience.policy_version
        return policy_lag <= self.max_policy_lag

    def train_step(self):
        # Sample recent-enough experiences
        batch = self.experience_buffer.sample(
            batch_size=2048,
            filter_fn=self.is_experience_valid
        )

        # Standard PPO update
        loss = self.compute_ppo_loss(batch)
        self.optimizer.step()

        self.current_policy_version += 1

        # Async weight broadcast (don't wait)
        self.broadcast_weights_async()
```

### 3.3 Benefits for Blood Bowl

| Benefit | Description |
|---------|-------------|
| **Decoupled compute** | C game engine on CPU, training on GPU |
| **Higher throughput** | Games continue while training |
| **Elastic scaling** | Add/remove game servers dynamically |
| **Fault tolerance** | Game crashes don't stop training |

---

## Part 4: Two-Sided Clipping (ADOPT)

### 4.1 The Problem with Standard PPO Clipping

Standard PPO only clips the ratio for positive advantages:

```python
# Standard PPO
ratio = new_prob / old_prob
clipped = clip(ratio, 1-eps, 1+eps)
loss = -min(ratio * A, clipped * A)  # Only clips when A > 0
```

When advantage is negative, the ratio can grow unboundedly, causing gradient spikes.

### 4.2 Two-Sided Clipping Solution

```python
def two_sided_ppo_loss(ratio, advantage, eps=0.2, delta=0.5):
    """
    Prime Intellect's two-sided clipping.

    Args:
        ratio: π(a|s) / π_old(a|s)
        advantage: A(s, a)
        eps: Standard PPO clip parameter
        delta: Two-sided clip parameter (new)
    """
    # Standard clipping
    clipped_ratio = torch.clamp(ratio, 1 - eps, 1 + eps)

    # Two-sided: also clip for negative advantages
    # Prevents ratio from exploding when A < 0
    two_sided_clip = torch.where(
        advantage >= 0,
        clipped_ratio,
        torch.clamp(ratio, 1 / delta, delta)  # Tighter bounds for A < 0
    )

    loss = -torch.min(ratio * advantage, two_sided_clip * advantage)
    return loss.mean()
```

### 4.3 Why This Matters for Blood Bowl

- **High variance rewards**: Block outcomes, turnovers create large advantage swings
- **Action masking**: Invalid actions can cause ratio issues
- **Self-play**: Opponent improvement changes advantage distribution

---

## Part 5: Verifier/Rubric Pattern (ADAPT)

### 5.1 Prime Intellect's Modular Rewards

Prime Intellect's `verifiers` library separates:
- **Environment logic** (state transitions)
- **Reward components** (rubrics)
- **Verification** (is output valid?)

### 5.2 Adaptation for Blood Bowl

```python
class BloodBowlRubric:
    """Modular reward components inspired by Prime Intellect verifiers."""

    def __init__(self):
        self.components = [
            # Primary rewards
            WinReward(weight=1.0),
            TouchdownReward(weight=0.4),

            # EV-based shaping
            BlockEVReward(weight=0.1),
            OpponentBlockPenalty(weight=0.1),
            PositionalReward(weight=0.05),

            # Resource rewards
            TurnoverPenalty(weight=0.15),
            RerollEfficiency(weight=0.02),

            # Format/validity (from verifiers concept)
            ActionValidityBonus(weight=0.01),
        ]

    def compute_reward(self, state, action, next_state, info):
        """Compute composite reward from all components."""
        total = 0.0
        component_values = {}

        for component in self.components:
            value = component.evaluate(state, action, next_state, info)
            weighted_value = value * component.weight
            total += weighted_value
            component_values[component.name] = value

        return total, component_values


class BlockEVReward:
    """EV-based reward for blocks (decision quality, not outcome)."""

    name = "block_ev"
    weight = 0.1

    def evaluate(self, state, action, next_state, info):
        if action.type != ActionType.BLOCK:
            return 0.0

        # Compute EV of the block decision
        block_ev = compute_block_ev(
            state=state,
            attacker=action.player,
            defender=action.target,
            matchup=info.get('matchup_context')
        )

        # Scale by defender value
        defender_value = state.players[action.target].gold_value / 100000.0
        return block_ev * defender_value
```

### 5.3 Benefits

| Pattern | Benefit |
|---------|---------|
| Modular components | Easy to add/remove reward signals |
| Named components | Clear logging and debugging |
| Weighted combination | Easy hyperparameter tuning |
| Separation of concerns | Environment doesn't know about rewards |

---

## Part 6: What NOT to Adopt

### 6.1 GRPO for Game RL

**Don't use GRPO** for Blood Bowl because:

1. **No per-step credit assignment**: Blood Bowl games have ~100 actions. GRPO assigns the same advantage to all actions in an episode.

2. **Research shows underperformance**: [Learning Without Critics?](https://arxiv.org/html/2511.03527v1) shows GRPO "substantially underperforms PPO" except on short-horizon tasks.

3. **Memory savings not critical**: For our C-based environment, the bottleneck is not GPU memory but CPU simulation speed.

### 6.2 LLM-Specific Patterns

Don't adopt:
- **Token-level rewards**: Blood Bowl has discrete actions, not token sequences
- **Language parsing**: We have structured observations, not text
- **Chat templates**: Our interface is arrays, not conversations

### 6.3 Decentralized Untrusted Compute

Prime Intellect's TOPLOC verification is for untrusted contributors. For self-play training on trusted hardware, this adds unnecessary complexity.

---

## Part 7: Implementation Recommendations

### 7.1 Training Stack

```python
# Recommended Blood Bowl Training Stack
class BloodBowlTrainingConfig:
    # Algorithm: PPO (not GRPO)
    algorithm = "PPO"
    use_critic = True  # Keep the value function!

    # Prime Intellect innovations
    two_sided_clipping = True
    async_training = True
    max_policy_lag = 4

    # PPO hyperparameters
    clip_eps = 0.2
    clip_delta = 0.5  # For two-sided clipping
    gamma = 0.99
    gae_lambda = 0.95
    entropy_coef = 0.01
    value_coef = 0.5

    # Async architecture
    num_game_workers = 64
    experience_buffer_size = 100000
    batch_size = 2048
    update_epochs = 4

    # Reward shaping (modular rubric)
    reward_components = [
        ("win", 1.0),
        ("touchdown", 0.4),
        ("block_ev", 0.1),
        ("turnover", -0.15),
        ("positional", 0.05),
    ]
```

### 7.2 Architecture Diagram

```
┌────────────────────────────────────────────────────────────────┐
│                    BLOOD BOWL RL SYSTEM                         │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │          GAME LAYER (C + Cython, CPU)                   │   │
│  │  ┌─────────────────────────────────────────────────┐    │   │
│  │  │  BloodBowlEnv (PufferLib Ocean pattern)         │    │   │
│  │  │  - Zero-copy observations                       │    │   │
│  │  │  - Action masking                               │    │   │
│  │  │  - EV computation in C                          │    │   │
│  │  └─────────────────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          │                                      │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │          REWARD LAYER (Modular Rubric)                  │   │
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐             │   │
│  │  │ WinReward │ │ BlockEV   │ │ Positional│  ...        │   │
│  │  └───────────┘ └───────────┘ └───────────┘             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          │                                      │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │          TRAINING LAYER (PPO, GPU)                      │   │
│  │  ┌───────────────────────────────────────────────┐      │   │
│  │  │  Async PPO with:                              │      │   │
│  │  │  - Value function (GAE)                       │      │   │
│  │  │  - Two-sided clipping                         │      │   │
│  │  │  - 4-step off-policy tolerance                │      │   │
│  │  │  - Action masking in policy                   │      │   │
│  │  └───────────────────────────────────────────────┘      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          │                                      │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │          SELF-PLAY LAYER                                │   │
│  │  ┌───────────────────────────────────────────────┐      │   │
│  │  │  - Historical policy sampling                 │      │   │
│  │  │  - Symmetric observations                     │      │   │
│  │  │  - League/ELO tracking                        │      │   │
│  │  └───────────────────────────────────────────────┘      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

---

## Part 8: Summary Table

| Prime Intellect Technique | Blood Bowl Applicability | Action |
|---------------------------|--------------------------|--------|
| Async training architecture | High | **ADOPT** |
| Two-sided clipping | High | **ADOPT** |
| Shardcast weight distribution | Medium (for multi-node) | **ADOPT** if scaling |
| Modular verifier/rubric design | High | **ADAPT** |
| GRPO algorithm | Low (underperforms for games) | **AVOID** |
| Critic-free training | Low (need value function) | **AVOID** |
| Length-controlled rewards | Low (not applicable) | **AVOID** |
| TOPLOC verification | Low (trusted compute) | **AVOID** |

---

## Sources

- [Prime Intellect GitHub: prime-rl](https://github.com/PrimeIntellect-ai/prime-rl)
- [Prime Intellect GitHub: verifiers](https://github.com/PrimeIntellect-ai/verifiers)
- [INTELLECT-2 Technical Report](https://arxiv.org/html/2505.07291v1)
- [Environments Hub Blog Post](https://www.primeintellect.ai/blog/environments)
- [Learning Without Critics? GRPO in Classical RL](https://arxiv.org/html/2511.03527v1)
- [GRPO Algorithm Explanation](https://yugeten.github.io/posts/2025/01/ppogrpo/)
