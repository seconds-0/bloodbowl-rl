# Blood Bowl RL Environment Research
## Building an Obscenely Fast Training Environment with PufferLib and Raylib

*Research compiled for high-performance reinforcement learning environment development*

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Blood Bowl Game Mechanics](#blood-bowl-game-mechanics)
3. [PufferLib Architecture](#pufferlib-architecture)
4. [Raylib for Visualization](#raylib-for-visualization)
5. [Performance Optimization Techniques](#performance-optimization-techniques)
6. [Recommended Architecture](#recommended-architecture)
7. [Implementation Roadmap](#implementation-roadmap)
8. [References](#references)

---

## Executive Summary

This document presents comprehensive research on building an extremely fast Blood Bowl reinforcement learning environment. The target is **1M+ steps per second** for training loops, achieved through:

- **Native C implementation** of game logic (following PufferLib's Ocean pattern)
- **Zero-copy shared memory** between environment and training
- **Optional Raylib rendering** that can be completely disabled during training
- **Vectorized environments** with async stepping for maximum throughput

### Key Findings

| Aspect | Challenge | Solution |
|--------|-----------|----------|
| Action Space | ~10^50 branching factor | Action masking, hierarchical actions |
| Stochasticity | Every action involves dice | Fast PRNG, precomputed probability tables |
| Sparse Rewards | Touchdowns are rare | Reward shaping, curriculum learning |
| Visualization | Rendering slows training | Raylib with headless mode toggle |
| Performance | Python overhead | C implementation with Cython bindings |

---

## Blood Bowl Game Mechanics

### Core Rules Overview

Blood Bowl is a turn-based fantasy football game played on a **26×15 grid** (or 17×28 in some implementations). Two teams of 11 players attempt to score touchdowns by carrying the ball into the opponent's end zone.

**Game Structure:**
- Two halves of 8 turns each (16 turns per team per half)
- Turn-based activation: each coach activates players one at a time
- **Turnover system**: Any failed dice roll immediately ends your turn

### State Space

The state representation from BotBowl provides a template:

```
Spatial Observation: (44, 17, 28) - 44 feature layers on 17×28 grid
├── Player positions (own team, opponent)
├── Player tackle zones
├── Ball location
├── Movement ranges
├── Player states (standing, prone, stunned)
└── Player stats and skills

Non-Spatial Observation: (116,) vector
├── Game metadata (half, turn number)
├── Scores
├── Weather conditions
├── Re-rolls remaining
└── Team value information

Procedure State: (19,) one-hot
└── Current game phase encoding
```

**Estimated state size:** ~22,000 floats for full observation

### Action Space

Blood Bowl has an extraordinarily large action space:

| Action Type | Description | Frequency |
|-------------|-------------|-----------|
| Move | Move player up to MA squares | Unlimited (once per player) |
| Block | Attack adjacent opponent | Unlimited (different players) |
| Blitz | Move + Block combination | Once per turn |
| Pass | Throw ball to another square | Once per turn |
| Hand-off | Give ball to adjacent player | Once per turn |
| Foul | Illegal attack on downed player | Once per turn |

**Action representation:** `ActionType + Position/Player target`
**Estimated action space:** ~8,117 discrete actions with masking

### Dice Mechanics

```c
// Block dice probabilities (critical for simulation)
typedef enum {
    PLAYER_DOWN,    // 1/6 - Attacker knocked down
    BOTH_DOWN,      // 1/6 - Both players down (skill dependent)
    PUSH,           // 2/6 - Defender pushed back
    STUMBLE,        // 1/6 - Defender pushed (or down without Dodge)
    POW             // 1/6 - Defender knocked down
} BlockResult;

// Strength comparison determines dice count
// Equal: 1 die, +1 ST: 2 dice (choose), +2 ST: 3 dice (choose)
```

**Key insight:** Probability chains multiply, making multi-action sequences increasingly risky.

### Why Blood Bowl is Hard for AI

1. **Massive branching factor (~10^50)** - larger than Go (~300) or Chess (~30)
2. **Extreme stochasticity** - every action involves dice rolls
3. **Sparse rewards** - touchdowns are rare (0 in 350k random games)
4. **Dynamic action space** - available actions change each state
5. **Long-term planning** - 16 turns per half requires strategy
6. **Credit assignment** - hard to attribute success to specific actions

---

## PufferLib Architecture

### Design Philosophy

PufferLib achieves **1M+ steps/second** through:

1. **Emulation Layer** - Flattens complex observations/actions into simple tensors
2. **Zero-copy Operations** - Environments write directly to training buffers
3. **Native C Environments** - Game logic in C with Python bindings
4. **Async Vectorization** - Overlaps simulation with model inference

### Ocean Environment Pattern

PufferLib's "Ocean" environments demonstrate the native C approach:

```
pufferlib/ocean/
├── myenv.h      # Environment logic (C header)
├── myenv.c      # Testing main function
├── myenv.pyx    # Cython binding
└── myenv.py     # Python wrapper with spaces
```

**Key characteristics:**
- Single .h file per environment
- Only dependency: raylib (for optional rendering)
- Direct observation writing to shared memory batches
- ~100 lines for the C API

### Performance Tiers

| Tier | Implementation | Performance | Use Case |
|------|----------------|-------------|----------|
| 1 | Pure Python | ~100k-500k sps | Prototyping |
| 2 | Python + NumPy optimized | ~500k-1M sps | Development |
| 3 | C with Cython binding | **1M-100M+ sps** | Production |

### Vectorization Backends

```python
import pufferlib.vector

envs = pufferlib.vector.make(
    make_env,
    backend='Multiprocessing',  # or 'Serial', 'Ray'
    num_envs=64,
    num_workers=8
)
```

**Optimization pathways:**
1. **Synchronous** - Zero-copy, environments split across cores
2. **Asynchronous** - Data from first-finishing workers, overlaps with inference
3. **Environment Pooling** - Run M >> N environments, sample first N to finish
4. **Zero-Copy Circular Buffer** - Direct loading from shared memory

### Memory Architecture

```python
# Shared memory layout (zero-copy)
shared_mem = [
    Array('d', agents_per_worker * (3 + observation_size))
    for _ in range(num_workers)
]

# Data in shared memory: observations, rewards, terminals, truncations
# Data on pipes (lightweight): actions, infos
```

**Critical optimization:** `np.asarray(tensor)` creates shared memory view allowing 10x faster NumPy indexing while updating PyTorch tensors.

---

## Raylib for Visualization

### Why Raylib

- **Written in C99** - minimal overhead, direct hardware access
- **Zero external dependencies** - all libraries bundled
- **Hardware accelerated** - OpenGL 1.1 to 4.3, ES 2.0/3.0
- **Automatic render batching** - groups draw calls efficiently
- **Simple API** - ~100 functions for most game dev needs

### Python Bindings

```python
# Two options in raylib-python-cffi
import raylib  # Direct C API (slightly faster)
import pyray   # Pythonic snake_case API

# Installation
pip install raylib==5.5.0.3
```

**Performance note:** PyPy achieves ~53% of native C performance vs CPython's ~5.8%

### Headless vs Visual Rendering

```python
class BloodBowlEnv:
    def __init__(self, render_mode='headless'):
        self.render_mode = render_mode

        if render_mode == 'human':
            InitWindow(800, 600, "Blood Bowl")
            SetTargetFPS(60)
        elif render_mode == 'rgb_array':
            SetConfigFlags(FLAG_WINDOW_HIDDEN)
            InitWindow(800, 600, "Blood Bowl")
            self.render_texture = LoadRenderTexture(800, 600)
        # 'headless': No window initialization at all

    def step(self, action):
        # Game logic ALWAYS runs
        self._update_game_state(action)

        # Rendering is OPTIONAL
        if self.render_mode == 'human':
            self._render_to_screen()
        elif self.render_mode == 'rgb_array':
            return self._render_to_texture()
```

### Performance Modes

| Mode | Window | Rendering | Speed | Use Case |
|------|--------|-----------|-------|----------|
| `headless` | None | None | **Fastest** | Training |
| `rgb_array` | Hidden | To texture | Medium | Vision RL |
| `human` | Visible | To screen | Slowest | Debug/Demo |

### Fixed Timestep Pattern

For deterministic simulation separate from rendering:

```c
// Simulation runs at fixed rate (e.g., 200 Hz)
while (accumulator >= dt) {
    previous_state = current_state;
    integrate(&current_state, dt, action);
    accumulator -= dt;
}

// Rendering interpolates for smooth visuals (only when enabled)
if (render_enabled) {
    float alpha = accumulator / dt;
    state_t interpolated = interpolate(previous_state, current_state, alpha);
    render(&interpolated);
}
```

---

## Performance Optimization Techniques

### Memory Layout: Structure of Arrays (SoA)

```c
// BAD: Array of Structures (cache-hostile)
typedef struct { float x, y, ma, st, ag, av; } Player;
Player players[22];

// GOOD: Structure of Arrays (cache-friendly)
typedef struct {
    float x[22], y[22];
    uint8_t ma[22], st[22], ag[22], av[22];
} Players;
```

**Performance gain:** 40-60% improvement in batch operations

### Precomputed Probability Tables

```c
// Precompute all dice probabilities at initialization
static float block_success_1d[6];      // 1 die block outcomes
static float block_success_2d[36];     // 2 dice block outcomes
static float armor_break[11][11];      // Armor vs roll outcomes
static float injury_table[36];         // 2d6 injury outcomes

void init_probability_tables(void) {
    // Compute once, lookup always
}
```

### Fast Random Number Generation

```c
// Use fast PRNG (xoshiro256** or PCG)
static inline uint64_t xoshiro256ss(uint64_t *state) {
    uint64_t result = rotl(state[1] * 5, 7) * 9;
    uint64_t t = state[1] << 17;
    state[2] ^= state[0];
    state[3] ^= state[1];
    state[1] ^= state[2];
    state[0] ^= state[3];
    state[2] ^= t;
    state[3] = rotl(state[3], 45);
    return result;
}

// Roll d6: (xoshiro256ss(&state) % 6) + 1
```

### Zero Dynamic Allocations

```c
// Allocate everything at initialization
typedef struct {
    // Fixed-size game state
    Player players[2][16];      // Max 16 players per team
    uint8_t board[17][28];      // Board state
    Ball ball;

    // Preallocated buffers
    Action valid_actions[8192]; // Max possible actions
    int num_valid_actions;

    // Observation buffer (written directly to shared memory)
    float *obs_buffer;          // Pointer to shared memory
} BloodBowlEnv;
```

### SIMD Vectorization

```c
// Use AVX for batch operations (8 floats at once)
#include <immintrin.h>

void update_positions_simd(float *x, float *y, float *dx, float *dy, int n) {
    for (int i = 0; i < n; i += 8) {
        __m256 vx = _mm256_load_ps(&x[i]);
        __m256 vy = _mm256_load_ps(&y[i]);
        __m256 vdx = _mm256_load_ps(&dx[i]);
        __m256 vdy = _mm256_load_ps(&dy[i]);
        _mm256_store_ps(&x[i], _mm256_add_ps(vx, vdx));
        _mm256_store_ps(&y[i], _mm256_add_ps(vy, vdy));
    }
}
```

### Compilation Optimizations

```bash
# Compile with aggressive optimizations
gcc -O3 -march=native -ffast-math -flto bloodbowl.c -o bloodbowl

# For Cython
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True
```

---

## Recommended Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────────────────┐
│                        Python Interface                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Gym/PufferLib│  │  Training   │  │   Visualization         │  │
│  │   Wrapper   │  │   (PPO)     │  │   (Optional Raylib)     │  │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬─────────────┘  │
│         │                │                      │                │
│  ┌──────▼────────────────▼──────────────────────▼─────────────┐  │
│  │                    Cython Binding                          │  │
│  │  - Observation space/action space definitions              │  │
│  │  - Shared memory pointer management                        │  │
│  │  - Action mask generation                                  │  │
│  └──────────────────────────┬─────────────────────────────────┘  │
└─────────────────────────────┼───────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│                         C Core Engine                            │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐   │
│  │  Game Logic    │  │  Dice Engine   │  │  Action Validator │   │
│  │  - Turn flow   │  │  - Fast PRNG   │  │  - Legal moves    │   │
│  │  - Rules       │  │  - Prob tables │  │  - Action mask    │   │
│  └────────────────┘  └────────────────┘  └──────────────────┘   │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐   │
│  │  Board State   │  │  Player State  │  │  Observation Gen  │   │
│  │  - SoA layout  │  │  - Skills/stats│  │  - Feature layers │   │
│  │  - Pathfinding │  │  - Injuries    │  │  - Direct write   │   │
│  └────────────────┘  └────────────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### File Structure

```
bloodbowl-rl/
├── src/
│   ├── core/                    # C implementation
│   │   ├── bloodbowl.h          # Main header (game logic)
│   │   ├── bloodbowl.c          # Implementation + test main()
│   │   ├── dice.h               # Dice mechanics
│   │   ├── pathfinding.h        # A* or precomputed paths
│   │   ├── actions.h            # Action validation
│   │   └── observations.h       # Observation generation
│   │
│   ├── binding/                 # Python binding
│   │   ├── bloodbowl.pyx        # Cython wrapper
│   │   └── bloodbowl.py         # Space definitions
│   │
│   ├── render/                  # Visualization (optional)
│   │   ├── renderer.h           # Raylib rendering
│   │   └── assets/              # Sprites, fonts
│   │
│   └── python/                  # Pure Python utilities
│       ├── env.py               # PufferLib environment wrapper
│       ├── policy.py            # Neural network policy
│       └── train.py             # Training script
│
├── tests/
│   ├── test_rules.py            # Rule correctness tests
│   ├── test_performance.py      # Benchmark tests
│   └── test_determinism.py      # Reproducibility tests
│
├── configs/
│   ├── teams/                   # Team configurations
│   └── training/                # Hyperparameter configs
│
└── docs/
    ├── RESEARCH.md              # This document
    └── API.md                   # API documentation
```

### Core Data Structures

```c
// bloodbowl.h

#define MAX_PLAYERS_PER_TEAM 16
#define BOARD_WIDTH 28
#define BOARD_HEIGHT 17
#define MAX_ACTIONS 8192

typedef struct {
    // Position (SoA for cache efficiency)
    int8_t x[MAX_PLAYERS_PER_TEAM];
    int8_t y[MAX_PLAYERS_PER_TEAM];

    // Stats
    uint8_t ma[MAX_PLAYERS_PER_TEAM];  // Movement Allowance
    uint8_t st[MAX_PLAYERS_PER_TEAM];  // Strength
    uint8_t ag[MAX_PLAYERS_PER_TEAM];  // Agility
    uint8_t av[MAX_PLAYERS_PER_TEAM];  // Armor Value

    // State flags (bitpacked)
    uint8_t state[MAX_PLAYERS_PER_TEAM];  // standing, prone, stunned, etc.
    uint8_t activated[MAX_PLAYERS_PER_TEAM];

    // Skills (bitfield per player)
    uint32_t skills[MAX_PLAYERS_PER_TEAM];

    int num_players;
} Team;

typedef struct {
    int8_t x, y;
    uint8_t carrier;  // Player index or 255 if on ground
    uint8_t state;    // held, loose, etc.
} Ball;

typedef struct {
    Team teams[2];
    Ball ball;

    // Game state
    uint8_t half;
    uint8_t turn;
    uint8_t active_team;
    uint8_t phase;

    // Resources
    uint8_t rerolls[2];
    uint8_t score[2];

    // Action tracking
    uint8_t blitz_used;
    uint8_t pass_used;
    uint8_t handoff_used;
    uint8_t foul_used;

    // Board cache (for fast lookups)
    int8_t board[BOARD_HEIGHT][BOARD_WIDTH];  // -1 empty, else player_id
    uint8_t tackle_zones[BOARD_HEIGHT][BOARD_WIDTH];

    // Preallocated action buffer
    uint16_t valid_actions[MAX_ACTIONS];
    int num_valid_actions;

    // RNG state
    uint64_t rng_state[4];

    // Observation buffer (points to shared memory)
    float *obs_spatial;      // (44, 17, 28)
    float *obs_nonspatial;   // (116,)
    float *action_mask;      // (8192,)
} BloodBowlGame;

// Core API
void bb_init(BloodBowlGame *game, uint64_t seed);
void bb_reset(BloodBowlGame *game);
int bb_step(BloodBowlGame *game, int action, float *reward, int *done);
void bb_get_valid_actions(BloodBowlGame *game);
void bb_generate_obs(BloodBowlGame *game);

// Optional rendering
void bb_render_init(int width, int height);
void bb_render(BloodBowlGame *game);
void bb_render_close(void);
```

### Observation Generation (Direct Write)

```c
void bb_generate_obs(BloodBowlGame *game) {
    float *obs = game->obs_spatial;

    // Zero the buffer (single memset)
    memset(obs, 0, 44 * 17 * 28 * sizeof(float));

    // Layer 0-1: Own team positions
    for (int i = 0; i < game->teams[game->active_team].num_players; i++) {
        int x = game->teams[game->active_team].x[i];
        int y = game->teams[game->active_team].y[i];
        if (x >= 0) {
            obs[0 * 17 * 28 + y * 28 + x] = 1.0f;  // Position
            obs[1 * 17 * 28 + y * 28 + x] = game->teams[game->active_team].ma[i] / 9.0f;
            // ... more features
        }
    }

    // Layer 2-3: Opponent positions
    int opp = 1 - game->active_team;
    for (int i = 0; i < game->teams[opp].num_players; i++) {
        // ... similar
    }

    // Layer 4: Ball position
    if (game->ball.x >= 0) {
        obs[4 * 17 * 28 + game->ball.y * 28 + game->ball.x] = 1.0f;
    }

    // ... continue for all 44 layers

    // Non-spatial observations
    float *ns = game->obs_nonspatial;
    ns[0] = game->half / 2.0f;
    ns[1] = game->turn / 8.0f;
    ns[2] = game->score[0] / 4.0f;
    ns[3] = game->score[1] / 4.0f;
    // ... etc
}
```

### PufferLib Integration

```python
# src/python/env.py
import numpy as np
import gymnasium as gym
from pufferlib import PufferEnv

class BloodBowlEnv(PufferEnv):
    def __init__(self, render_mode='headless'):
        super().__init__()

        # Import C extension
        from bloodbowl_binding import BloodBowlGame
        self.game = BloodBowlGame()

        self.render_mode = render_mode

        # Define spaces
        self.observation_space = gym.spaces.Dict({
            'spatial': gym.spaces.Box(
                low=-1, high=1,
                shape=(44, 17, 28),
                dtype=np.float32
            ),
            'nonspatial': gym.spaces.Box(
                low=-1, high=1,
                shape=(116,),
                dtype=np.float32
            )
        })

        self.action_space = gym.spaces.Discrete(8192)

    def reset(self, seed=None):
        if seed is not None:
            self.game.seed(seed)
        self.game.reset()
        return self._get_obs(), {}

    def step(self, action):
        reward, done = self.game.step(action)

        if self.render_mode == 'human':
            self.game.render()

        return self._get_obs(), reward, done, False, {}

    def _get_obs(self):
        # Observations written directly by C code
        return {
            'spatial': self.game.get_spatial_obs(),
            'nonspatial': self.game.get_nonspatial_obs()
        }

    def action_mask(self):
        return self.game.get_action_mask()
```

### Training Configuration

```python
# src/python/train.py
import pufferlib
import pufferlib.vector
import pufferlib.frameworks.cleanrl

def make_env():
    from bloodbowl_env import BloodBowlEnv
    return pufferlib.emulation.GymnasiumPufferEnv(
        env_creator=lambda: BloodBowlEnv(render_mode='headless')
    )

# Vectorized environments
envs = pufferlib.vector.make(
    make_env,
    backend='Multiprocessing',
    num_envs=128,      # Total environments
    num_workers=16,    # CPU workers
    envs_per_worker=8  # Environments per worker
)

# Training with PPO
config = {
    'total_timesteps': 100_000_000,
    'learning_rate': 2.5e-4,
    'num_steps': 128,
    'num_minibatches': 4,
    'update_epochs': 4,
    'clip_coef': 0.1,
    'ent_coef': 0.01,
    'vf_coef': 0.5,
    'max_grad_norm': 0.5,
    'gamma': 0.99,
    'gae_lambda': 0.95,
}
```

---

## Implementation Roadmap

### Phase 1: Core Engine (C)
1. Implement basic game state structures
2. Implement turn flow and phase management
3. Implement dice mechanics with fast PRNG
4. Implement action validation and masking
5. Implement observation generation
6. Write comprehensive tests for rule correctness

### Phase 2: Python Integration
1. Create Cython bindings
2. Implement PufferEnv wrapper
3. Validate observation/action space correctness
4. Benchmark single-environment performance
5. Target: **100k+ steps/second single-threaded**

### Phase 3: Vectorization
1. Integrate with PufferLib vectorization
2. Implement shared memory observation writes
3. Test multiprocessing backend
4. Optimize for async stepping
5. Target: **1M+ steps/second with 16 workers**

### Phase 4: Visualization
1. Implement Raylib renderer
2. Add toggle for headless/visual modes
3. Create debug visualization tools
4. Implement replay system

### Phase 5: Training
1. Implement neural network policy
2. Add curriculum learning (smaller boards first)
3. Implement reward shaping
4. Train and evaluate agents
5. Compare against BotBowl baselines

---

## References

### Blood Bowl
- [BotBowl GitHub](https://github.com/njustesen/botbowl) - Primary reference implementation
- [Blood Bowl: A New Board Game Challenge for AI (IEEE 2019)](https://ieeexplore.ieee.org/document/8848063/)
- [MimicBot: Combining Imitation and RL (Bot Bowl III Winner)](https://www.researchgate.net/publication/354088448)
- [Blood Bowl Rules](https://bloodbowlbase.ru/core_rules/the_rules_of_blood_bowl/)

### PufferLib
- [PufferLib GitHub](https://github.com/PufferAI/PufferLib)
- [PufferLib Documentation](https://puffer.ai/docs.html)
- [PufferLib Paper (ArXiv)](https://arxiv.org/html/2406.12905v1)

### Raylib
- [Raylib Official](https://www.raylib.com/)
- [raylib-python-cffi](https://electronstudio.github.io/raylib-python-cffi/)
- [Raylib Cheatsheet](https://www.raylib.com/cheatsheet/cheatsheet.html)

### Performance
- [EnvPool (High-Performance Vectorization)](https://github.com/sail-sg/envpool)
- [Sample Factory (Async RL)](https://www.samplefactory.dev/)
- [PureJaxRL (End-to-End GPU Training)](https://github.com/luchris429/purejaxrl)
- [Fix Your Timestep (Game Loop Pattern)](https://gafferongames.com/post/fix_your_timestep/)

### Academic
- [NetHack Learning Environment](https://github.com/facebookresearch/nle)
- [Madrona Engine (GPU ECS)](https://madrona-engine.github.io/)
- [Griddly (Fast Grid Environments)](https://griddly.readthedocs.io/)

---

*This research document provides the foundation for building an extremely fast Blood Bowl RL environment. The key insight is that achieving 1M+ steps/second requires native C implementation with zero-copy memory management, following the patterns established by PufferLib's Ocean environments.*
