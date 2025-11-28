# PufferLib Best Practices Audit & Alignment

## Executive Summary

This document audits our Blood Bowl RL design against PufferLib's official best practices and identifies gaps. PufferLib has specific patterns that we MUST follow for optimal performance.

**Overall Assessment**: Our current design is ~70% aligned. Key gaps exist in:
1. Multi-agent API (we designed single-agent with perspective flipping)
2. Buffer management (need external buffer writes, not internal)
3. Training integration (need proper PuffeRL integration)
4. Self-play mechanism (PufferLib has built-in support we're not using)

---

## Part 1: What PufferLib Actually Does

### 1.1 Core Architecture

From [PufferLib documentation](https://puffer.ai/docs.html) and [arXiv paper](https://arxiv.org/html/2406.12905v1):

```
┌─────────────────────────────────────────────────────────────────┐
│                    PUFFERLIB STACK                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  ENVIRONMENT LAYER (Ocean C Environments)                 │  │
│  │  - Header-only C (.h)                                     │  │
│  │  - Cython binding (.pyx)                                  │  │
│  │  - Python wrapper (.py) with spaces                       │  │
│  └───────────────────────────────────────────────────────────┘  │
│                          │                                       │
│                          ▼                                       │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  EMULATION LAYER                                          │  │
│  │  - Flattens complex obs/action spaces                     │  │
│  │  - Handles multi-agent canonicalization                   │  │
│  │  - Variable agent padding                                 │  │
│  └───────────────────────────────────────────────────────────┘  │
│                          │                                       │
│                          ▼                                       │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  VECTORIZATION LAYER                                      │  │
│  │  - Serial / Multiprocessing / Ray backends                │  │
│  │  - Shared memory buffers                                  │  │
│  │  - Zero-copy batching                                     │  │
│  │  - Async environment execution                            │  │
│  └───────────────────────────────────────────────────────────┘  │
│                          │                                       │
│                          ▼                                       │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  PUFFERL TRAINING                                         │  │
│  │  - CleanRL PPO + LSTM (customized)                        │  │
│  │  - Self-play support                                      │  │
│  │  - Variable agent populations                             │  │
│  │  - Experiment management                                  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Key PufferLib Principles

| Principle | Description | Our Status |
|-----------|-------------|------------|
| **Zero-copy buffers** | Envs write directly to shared training buffers | ⚠️ Partial |
| **No dynamic allocation** | Everything allocated at init | ✅ Good |
| **Native multi-agent** | Not a wrapper, core feature | ❌ Missing |
| **Canonical agent ordering** | Consistent observation ordering | ❌ Missing |
| **Variable agent padding** | Fixed buffer sizes | ❌ Missing |
| **PufferEnv API** | Specific vector environment interface | ⚠️ Partial |

---

## Part 2: Critical Gaps in Our Design

### 2.1 GAP: Single-Agent vs Multi-Agent Design

**Our Current Approach** (from `ARCHITECTURE.md`):
```python
# We designed for single-agent with perspective flipping
class SelfPlayBloodBowl(gym.Env):
    def step(self, action):
        self._env.step(action)
        if self._env.get_active_team() != self._current_policy:
            self._current_policy = 1 - self._current_policy
            self._env.flip_perspective()  # WRONG APPROACH
```

**PufferLib's Approach**:
```python
# PufferLib uses native multi-agent with both players as separate agents
# Both get observations simultaneously, canonical ordering ensures consistency
class BloodBowlEnv(pufferlib.PufferEnv):
    def __init__(self):
        self.num_agents = 2  # Always 2 agents

    def step(self, actions):
        # actions is a dict or array with actions for BOTH players
        # Even the inactive player gets an observation (can be masked)
        pass
```

**Fix Required**: Redesign as true multi-agent environment where both teams are always present.

### 2.2 GAP: External Buffer Writes

**Our Current Approach**:
```c
typedef struct {
    // Internal buffers - WRONG!
    float observations[BB_OBSERVATION_SIZE];
    float rewards[2];
} BloodBowlEnv;
```

**PufferLib's Approach**:
```c
// Environment receives EXTERNAL buffer pointers
void bb_step(
    BloodBowlEnv *env,
    int action,
    float *obs_buffer,      // External - from PufferLib
    float *reward_buffer,   // External - from PufferLib
    uint8_t *done_buffer    // External - from PufferLib
) {
    // Write directly to training buffers
    compute_observations(env, obs_buffer);
    *reward_buffer = compute_reward(env);
    *done_buffer = is_terminal(env);
}
```

**Fix Required**: Environment must accept external buffer pointers, not own its buffers.

### 2.3 GAP: PufferEnv API Compliance

**Required PufferEnv API**:
```python
class BloodBowlEnv(pufferlib.PufferEnv):
    """Must inherit from PufferEnv, not gym.Env."""

    def __init__(self, buf):
        # buf is the shared buffer object from PufferLib
        self.buf = buf

        # Initialize observation/action views from buf
        self.observations = buf.observations  # Shared memory!
        self.actions = buf.actions
        self.rewards = buf.rewards
        self.terminals = buf.terminals

    def reset(self):
        # Write observations IN PLACE
        self._compute_observations()  # Writes to self.observations
        return None  # Don't return anything - data is in shared buffer

    def step(self):
        # Read action from self.actions (set by learner)
        action = self.actions[self.agent_id]

        # Execute game logic
        self._execute_action(action)

        # Write results IN PLACE
        self._compute_observations()
        self._compute_rewards()

        return None  # Data is in shared buffers
```

### 2.4 GAP: Self-Play Integration

**PufferLib has built-in self-play**:
```python
# From PufferLib docs: "support for self-play"
# We should use their mechanism, not roll our own

puffer train bloodbowl --self-play --self-play-window 10
```

**We need to investigate**: How PufferLib's self-play works with multi-agent environments.

---

## Part 3: Corrected Blood Bowl Design

### 3.1 Corrected C Header

```c
#ifndef BLOODBOWL_H
#define BLOODBOWL_H

#include <stdint.h>
#include <stdbool.h>
#include <string.h>

// =============================================================================
// CONFIGURATION
// =============================================================================

#define BB_BOARD_WIDTH 26
#define BB_BOARD_HEIGHT 15
#define BB_MAX_PLAYERS_PER_TEAM 11
#define BB_MAX_PLAYERS 22
#define BB_NUM_AGENTS 2  // Always 2 agents (Team 0 and Team 1)

// Observation per agent (each team sees from their perspective)
#define BB_OBS_SIZE_PER_AGENT 2048
#define BB_ACTION_SIZE 256

// =============================================================================
// GAME STATE (no buffers - those come from PufferLib)
// =============================================================================

typedef struct {
    // Player positions (SoA layout)
    int8_t player_x[BB_MAX_PLAYERS];
    int8_t player_y[BB_MAX_PLAYERS];
    int8_t player_state[BB_MAX_PLAYERS];
    int8_t player_team[BB_MAX_PLAYERS];

    // Player stats
    int8_t player_ma[BB_MAX_PLAYERS];
    int8_t player_st[BB_MAX_PLAYERS];
    int8_t player_ag[BB_MAX_PLAYERS];
    int8_t player_av[BB_MAX_PLAYERS];
    uint64_t player_skills[BB_MAX_PLAYERS];
    int32_t player_gold_value[BB_MAX_PLAYERS];

    // Ball state
    int8_t ball_x;
    int8_t ball_y;
    int8_t ball_carrier;  // -1 if loose

    // Game state
    int8_t active_team;   // 0 or 1 - whose turn
    int8_t turn_number;
    int8_t half;
    int8_t score[2];
    int8_t rerolls[2];

    // Turn state
    bool blitz_used;
    bool pass_used;
    bool handoff_used;
    bool foul_used;
    uint32_t activated_players;

    // RNG
    uint64_t rng_state;
} BloodBowlGame;

// =============================================================================
// CORE FUNCTIONS (write to EXTERNAL buffers)
// =============================================================================

// Allocate game state only (not buffers)
static inline BloodBowlGame* bb_allocate(void) {
    BloodBowlGame* game = (BloodBowlGame*)calloc(1, sizeof(BloodBowlGame));
    return game;
}

// Initialize game
static inline void bb_init(BloodBowlGame* game, uint64_t seed) {
    memset(game, 0, sizeof(BloodBowlGame));
    game->rng_state = seed ? seed : 12345;
    game->ball_carrier = -1;
}

// Reset game, write to external observation buffers
static inline void bb_reset(
    BloodBowlGame* game,
    float* obs_team0,      // External buffer for team 0's observation
    float* obs_team1       // External buffer for team 1's observation
) {
    game->turn_number = 1;
    game->half = 1;
    game->score[0] = 0;
    game->score[1] = 0;
    game->active_team = rand_int(&game->rng_state, 2);
    game->blitz_used = false;
    game->pass_used = false;
    game->handoff_used = false;
    game->foul_used = false;
    game->activated_players = 0;

    // Setup initial positions...
    bb_setup_kickoff(game);

    // Write observations for BOTH teams to external buffers
    bb_compute_observation(game, 0, obs_team0);
    bb_compute_observation(game, 1, obs_team1);
}

// Step: active team takes action, write results to external buffers
static inline void bb_step(
    BloodBowlGame* game,
    int action,             // Action from active team
    float* obs_team0,       // External buffer
    float* obs_team1,       // External buffer
    float* reward_team0,    // External buffer
    float* reward_team1,    // External buffer
    uint8_t* done,          // External buffer
    uint8_t* action_mask    // External buffer for next valid actions
) {
    int acting_team = game->active_team;

    // Execute action
    bb_execute_action(game, action);

    // Compute rewards for BOTH teams (zero-sum perspective)
    float reward = bb_compute_reward(game, acting_team);
    *reward_team0 = (acting_team == 0) ? reward : -reward;
    *reward_team1 = (acting_team == 1) ? reward : -reward;

    // Check terminal
    *done = bb_is_terminal(game);

    // Compute observations for BOTH teams
    bb_compute_observation(game, 0, obs_team0);
    bb_compute_observation(game, 1, obs_team1);

    // Compute valid actions for next active team
    bb_compute_action_mask(game, action_mask);
}

// Compute observation from team's perspective (symmetric)
static inline void bb_compute_observation(
    BloodBowlGame* game,
    int team,
    float* obs  // External buffer
) {
    memset(obs, 0, BB_OBS_SIZE_PER_AGENT * sizeof(float));

    int idx = 0;

    // Board is flipped for team 1 so both see "their" endzone at bottom
    bool flip = (team == 1);

    // Encode players relative to this team's perspective
    for (int i = 0; i < BB_MAX_PLAYERS; i++) {
        int x = game->player_x[i];
        int y = game->player_y[i];

        if (flip) {
            x = BB_BOARD_WIDTH - 1 - x;
            y = BB_BOARD_HEIGHT - 1 - y;
        }

        // Friendly vs enemy encoding
        bool is_friendly = (game->player_team[i] == team);

        obs[idx++] = x / (float)BB_BOARD_WIDTH;
        obs[idx++] = y / (float)BB_BOARD_HEIGHT;
        obs[idx++] = is_friendly ? 1.0f : 0.0f;
        obs[idx++] = game->player_state[i] / 2.0f;
        // ... more features
    }

    // Global state
    obs[idx++] = game->turn_number / 16.0f;
    obs[idx++] = (game->active_team == team) ? 1.0f : 0.0f;  // Is it my turn?
    obs[idx++] = (game->score[team] - game->score[1-team]) / 4.0f;  // Score diff from my perspective
    // ... more features
}

// Free game state
static inline void bb_free(BloodBowlGame* game) {
    free(game);
}

#endif // BLOODBOWL_H
```

### 3.2 Corrected Cython Binding

```cython
# bloodbowl.pyx
# distutils: language=c
# cython: boundscheck=False, wraparound=False, nonecheck=False, cdivision=True

cimport numpy as cnp
import numpy as np

cdef extern from "bloodbowl.h":
    cdef int BB_OBS_SIZE_PER_AGENT
    cdef int BB_ACTION_SIZE
    cdef int BB_NUM_AGENTS

    ctypedef struct BloodBowlGame:
        int active_team
        int turn_number
        int score[2]

    BloodBowlGame* bb_allocate()
    void bb_init(BloodBowlGame* game, unsigned long seed)
    void bb_reset(BloodBowlGame* game, float* obs0, float* obs1)
    void bb_step(BloodBowlGame* game, int action,
                 float* obs0, float* obs1,
                 float* rew0, float* rew1,
                 unsigned char* done,
                 unsigned char* action_mask)
    void bb_free(BloodBowlGame* game)


cdef class CBloodBowl:
    """Cython wrapper that writes to EXTERNAL buffers."""

    cdef BloodBowlGame* game

    def __init__(self, seed=0):
        self.game = bb_allocate()
        bb_init(self.game, seed)

    def __dealloc__(self):
        if self.game != NULL:
            bb_free(self.game)

    cpdef void reset(self,
                     float[:] obs_team0,
                     float[:] obs_team1):
        """Reset game, write observations to provided buffers."""
        bb_reset(self.game, &obs_team0[0], &obs_team1[0])

    cpdef void step(self,
                    int action,
                    float[:] obs_team0,
                    float[:] obs_team1,
                    float[:] reward_team0,
                    float[:] reward_team1,
                    unsigned char[:] done,
                    unsigned char[:] action_mask):
        """Step game, write results to provided buffers."""
        bb_step(self.game, action,
                &obs_team0[0], &obs_team1[0],
                &reward_team0[0], &reward_team1[0],
                &done[0], &action_mask[0])

    @property
    def active_team(self):
        return self.game.active_team

    @property
    def turn(self):
        return self.game.turn_number
```

### 3.3 Corrected PufferEnv Wrapper

```python
# bloodbowl.py
import numpy as np
import pufferlib

from .cy_bloodbowl import CBloodBowl

OBS_SIZE = 2048
ACTION_SIZE = 256


class BloodBowl(pufferlib.PufferEnv):
    """Blood Bowl environment following PufferLib conventions.

    This is a 2-agent environment where both teams are always present.
    The active team takes actions, but both teams receive observations.
    """

    def __init__(self, buf=None, seed=None):
        # Number of agents is FIXED at 2 (two teams)
        self.num_agents = 2

        # Create C environment
        self._env = CBloodBowl(seed or 0)

        # If buf provided, use shared buffers (PufferLib mode)
        # If not, create local buffers (standalone mode)
        if buf is not None:
            self.observations = buf.observations
            self.actions = buf.actions
            self.rewards = buf.rewards
            self.terminals = buf.terminals
        else:
            # Standalone mode for testing
            self.observations = np.zeros((2, OBS_SIZE), dtype=np.float32)
            self.actions = np.zeros(2, dtype=np.int32)
            self.rewards = np.zeros(2, dtype=np.float32)
            self.terminals = np.zeros(2, dtype=np.uint8)

        # Action mask (for current active team)
        self.action_mask = np.zeros(ACTION_SIZE, dtype=np.uint8)

        # Track which agent is active
        self._active_agent = 0

    @property
    def observation_space(self):
        return pufferlib.spaces.Box(
            low=-1.0, high=1.0,
            shape=(OBS_SIZE,),
            dtype=np.float32
        )

    @property
    def action_space(self):
        return pufferlib.spaces.Discrete(ACTION_SIZE)

    def reset(self):
        """Reset game, write observations to shared buffers."""
        self._env.reset(
            self.observations[0],  # Team 0's observation buffer
            self.observations[1]   # Team 1's observation buffer
        )
        self._active_agent = self._env.active_team
        self.terminals[:] = 0
        self.rewards[:] = 0

    def step(self):
        """Execute action from active agent, update all buffers."""
        # Get action from active team's buffer
        action = self.actions[self._active_agent]

        # Single-element buffers for step outputs
        done = np.zeros(1, dtype=np.uint8)

        # Step the game
        self._env.step(
            action,
            self.observations[0],
            self.observations[1],
            self.rewards[0:1],  # Slice to get view
            self.rewards[1:2],
            done,
            self.action_mask
        )

        # Update terminals
        self.terminals[:] = done[0]

        # Update active agent for next step
        self._active_agent = self._env.active_team

    def close(self):
        pass


def make_bloodbowl(buf=None, seed=None):
    """Factory function for PufferLib."""
    return BloodBowl(buf=buf, seed=seed)
```

---

## Part 4: Training Integration

### 4.1 Config File (bloodbowl.ini)

```ini
[env]
name = bloodbowl
# Multi-agent settings
num_agents = 2
# Environment-specific
board_width = 26
board_height = 15

[train]
# PuffeRL PPO settings
total_timesteps = 100_000_000
learning_rate = 2.5e-4
batch_size = 2048
minibatch_size = 512
update_epochs = 4
gamma = 0.99
gae_lambda = 0.95
clip_coef = 0.2
ent_coef = 0.01
vf_coef = 0.5
max_grad_norm = 0.5

# Self-play
self_play = true
self_play_window = 10

# Async settings
num_envs = 128
num_workers = 16
envs_per_worker = 8

[policy]
# Network architecture
hidden_size = 256
num_layers = 2
use_lstm = false  # Start without LSTM
```

### 4.2 Training Command

```bash
# Using PufferLib's CLI
puffer train bloodbowl

# Or with custom settings
puffer train bloodbowl \
    --train.learning_rate 0.0003 \
    --train.total_timesteps 50000000 \
    --train.self_play true
```

### 4.3 Custom Training Script (if needed)

```python
import pufferlib
import pufferlib.vector
import pufferlib.frameworks.cleanrl as cleanrl

from bloodbowl import make_bloodbowl


def train():
    # Create vectorized environments
    envs = pufferlib.vector.make(
        make_bloodbowl,
        backend='Multiprocessing',
        num_envs=128,
        num_workers=16,
    )

    # Get a sample env for spaces
    sample_env = make_bloodbowl()

    # Create policy
    policy = cleanrl.Policy(
        envs.driver_env,
        hidden_size=256,
    )

    # Train with PuffeRL
    cleanrl.train(
        envs=envs,
        policy=policy,
        total_timesteps=100_000_000,

        # PPO hyperparameters
        learning_rate=2.5e-4,
        batch_size=2048,
        minibatch_size=512,
        gamma=0.99,
        gae_lambda=0.95,
        clip_coef=0.2,
        ent_coef=0.01,
        vf_coef=0.5,

        # Self-play
        self_play=True,
        self_play_window=10,

        # Logging
        track=True,
        wandb_project='bloodbowl-rl',
    )


if __name__ == '__main__':
    train()
```

---

## Part 5: Checklist for PufferLib Compliance

### Environment Implementation
- [ ] Inherit from `pufferlib.PufferEnv` (not `gym.Env`)
- [ ] Accept `buf` parameter for shared buffers
- [ ] Write observations/rewards in-place (no return values)
- [ ] Fixed number of agents (2 for Blood Bowl)
- [ ] Symmetric observations (both teams see from their perspective)
- [ ] No dynamic memory allocation in step/reset

### C Implementation
- [ ] Header-only design (.h file)
- [ ] Accept external buffer pointers
- [ ] No internal observation/reward buffers
- [ ] Structure of Arrays layout
- [ ] Fast RNG (xorshift64)

### Cython Binding
- [ ] Memory views for zero-copy
- [ ] cpdef for Python-callable functions
- [ ] All buffer arguments are views, not copies

### Training
- [ ] Use PuffeRL (not custom training loop if possible)
- [ ] Config file in `pufferlib/config/ocean/bloodbowl.ini`
- [ ] Register in `ocean/environment.py`
- [ ] Test with `puffer train bloodbowl`

### Self-Play
- [ ] Use PufferLib's built-in self-play mechanism
- [ ] Both agents always present in environment
- [ ] Rewards are zero-sum (team0 = -team1)

---

## Part 6: What to Update in Existing Docs

### 6.1 Update `pufferlib` Skill

The skill document has the **wrong pattern**. Need to update:
1. Remove internal buffer design
2. Add external buffer pattern
3. Fix multi-agent API
4. Add PufferEnv inheritance

### 6.2 Update `ARCHITECTURE.md`

1. Change self-play from "perspective flipping" to "true multi-agent"
2. Update observation space for dual-agent
3. Add PufferLib integration details

### 6.3 Create Integration Test

```python
def test_pufferlib_integration():
    """Verify Blood Bowl works with PufferLib."""
    import pufferlib
    from bloodbowl import make_bloodbowl

    # Test standalone
    env = make_bloodbowl()
    env.reset()
    for _ in range(100):
        env.actions[env._active_agent] = np.random.randint(256)
        env.step()
        if env.terminals[0]:
            env.reset()

    # Test vectorized
    envs = pufferlib.vector.make(
        make_bloodbowl,
        backend='Serial',
        num_envs=4,
    )
    obs = envs.reset()
    assert obs.shape == (4, 2, 2048)  # (envs, agents, obs_size)
```

---

## Summary

**Key Changes Required**:

1. **Multi-agent first**: Both teams are always agents, not single-agent with flipping
2. **External buffers**: C code writes to buffers provided by PufferLib
3. **PufferEnv inheritance**: Use their API, not gym.Env
4. **Built-in self-play**: Use PufferLib's mechanism
5. **Symmetric observations**: Each team sees board from their perspective

**Performance Impact**: These changes should IMPROVE performance because:
- No observation copying (write directly to training buffers)
- Native multi-agent support (no wrapper overhead)
- Leverages PufferLib's optimized vectorization
