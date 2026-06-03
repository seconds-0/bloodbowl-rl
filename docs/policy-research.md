# Policy Architecture Research — Blood Bowl RL on PufferLib 4.0

*Research date: 2026-06-03. All file:line citations are into `vendor/PufferLib` (branch 4.0)
unless otherwise noted. Verified by reading the actual source, not docs.*

---

## 0. Executive summary

**PufferLib 4.0's native CUDA trainer has a fixed policy skeleton: `Encoder → MinGRU stack →
fused Decoder` (`src/pufferlib.cu:1679-1726`). Only the encoder is replaceable (per-env CUDA
vtable override, `src/ocean.cu:574-590`). There is no native LSTM, no attention, and no
autoregressive action heads — heads in a MultiDiscrete space are sampled independently from one
forward pass.** Chess — the closest analog to BB (2-player, masked, self-play pool) — ships a
**compact 167-byte observation through the stock Linear encoder** and handles its huge action
space by **decomposing each move into sequential single-head decisions across env steps**
("pick piece" → "pick destination", `ocean/chess/chess.h:469,1666-1716`), not by factored heads.

**Primary recommendation (implementable today, zero trainer changes):** stock policy
(Linear → MinGRU×3 → Linear, `hidden_size=512`) over a **compact entity-centric observation
(~2.0-2.5 KB)** that embeds engine-computed legality and spatial summaries, with action heads
**`ACT_SIZES {30, 33, 391}`** (type / option-arg / fused-square, each with an always-legal
null index) and **chess-style phase-splitting** whenever type↔square legality is coupled.
≈3.7 M params, est. 0.5-1.5 M agent-steps/s on one 4090-class GPU.

**Stretch:** a custom CUDA encoder (`create_custom_encoder("bloodbowl", ...)`) that
scatter-builds 26×15 board planes on-GPU from the compact obs (the nmmo3 multihot trick,
`src/ocean.cu:29-39`) and runs a small conv trunk + per-player embeddings — MimicBot-informed,
~7 M params, ~600-900 lines of CUDA forward+backward modeled on `ocean.cu`.

The torch path (`--slowly`/`--cpu`) is **disqualified for real training**: it has **zero
action-mask plumbing** (grep `mask` in `pufferlib/torch_pufferl.py` → no hits) and the cached
4.0 docs say `--cpu` runs "under 200k sps" (`docs/vendor/pufferlib/docs.html`). Use it only
for debugging and as the BC-pretraining harness.

---

## 1. What a PufferLib 4.0 policy actually is

### 1.1 The native CUDA path (the real trainer)

There is **one** policy architecture in the CUDA backend, assembled by `build_policy`
(`src/pufferlib.cu:1679-1726`):

| Component | Implementation | Parameterization |
|---|---|---|
| Encoder | single `puf_mm` (Linear, **no bias, no activation**) `obs → hidden` (`src/models.cu:412-418`) | `in_dim = OBS_SIZE`, `out_dim = hidden_size`; **replaceable per env** via `create_custom_encoder(env_name, &encoder)` (`src/pufferlib.cu:1695`, `src/ocean.cu:574-590`) |
| Network | MinGRU stack with fused gate + highway connection (`src/models.cu:106-137,703-754`); training uses a checkpointed parallel log-space scan (`mingru_scan_forward/backward`, `src/models.cu:153-386`) | `hidden_size`, `num_layers`, `horizon` — **MinGRU only**; no LSTM/GRU/MLP option on the native path |
| Decoder | single Linear `hidden → sum(ACT_SIZES)+1`; **value head fused as the last output column** (`src/models.cu:485-493,506`; consumed at `src/pufferlib.cu:463,565`) | `output_dim = sum(ACT_SIZES)` (discrete) |

Config flow: only `[policy] hidden_size` and `num_layers` reach the C trainer
(`src/bindings.cu:402-403`). `expansion_factor` in `config/chess.ini:35` is **dead config** —
nothing reads it (verified by grep across `src/` and `pufferlib/`).

The components are C structs of function pointers (`Encoder`/`Decoder`/`Network`,
`src/models.cu:35-75`). A custom component supplies forward, backward, weight-init,
param-registration, and train/rollout activation-registration callbacks. Upstream's own
comment: *"You probably only ever need a custom Encoder"* (`src/models.cu:12-15`). Exactly one
custom encoder exists today: **nmmo3** (`src/ocean.cu`), which proves out the full menu of
reusable machinery:

- `n3_multihot_kernel` (`ocean.cu:29-39`): expand compact byte codes into one-hot **board
  planes on the GPU** — obs stays small, conv input gets built per batch.
- `gemm_conv_forward/backward` (`ocean.cu:299-370`): generic im2col + cuBLAS conv2d (NCHW,
  arbitrary K/stride, **no padding support** — plan output sizes as `(H-K)/S+1`).
- `n3_embedding_kernel` + scatter-add backward (`ocean.cu:41-51,147-161`): learned embeddings
  of categorical bytes.
- concat / bias+ReLU / bias-grad kernels (`ocean.cu:53-134`).

Everything must be CUDA-graph-capturable (rollout is captured at epoch `cudagraphs=10`,
`config/default.ini:16`, `src/pufferlib.cu:573-697`): no allocation or sync inside forward.
nmmo3 complies; copy its patterns.

### 1.2 What chess does (our template)

`ocean/chess/binding.c:4-8`: `OBS_SIZE 167` (ByteTensor), `NUM_ATNS 1`, `ACT_SIZES {97}`,
`MY_ACTION_MASK 97`. `config/chess.ini:32-35`: `hidden_size=512, num_layers=3`. So the
strongest 2-player masked self-play env in the tree uses the **stock Linear+MinGRU+Linear**
(≈2.5 M params: 167×512 + 3×512×1536 + 98×512) — no custom encoder, no board planes (a
768-plane obs mode exists in `chess.h:316-330` but is disabled; the shipped obs is a compact
**token format**: 16 piece tokens + side/castle/EP + **explicit legality features**
`O_VALID_PIECES/O_VALID_DESTS/O_VALID_PROMOS` + phase flags, `chess.h:279-296`).

Chess's action space: `NUM_ACTIONS 97` = 64 squares + 32 promotion slots + 1 pass
(`chess.h:357-358`). A move is **two sequential decisions** — `pick_phase 0`: choose the
from-square (mask = movable pieces); `pick_phase 1`: choose the destination (mask = legal
destinations of the selected piece) (`chess.h:469,1666-1716,2431-2465`). The partial selection
is **encoded in the observation** (`O_PICK_PHASE`, `O_SELECTED_PIECE`, `chess.h:1703-1716`),
and the MinGRU carries it through time as well. This is the supported substitute for
autoregressive heads: **autoregression through the environment.**

2-player handling: nothing in the policy. Both slots route through the same net; obs are
egocentric per side (square flip), slot↔color randomized per env at init
(`ocean/chess/binding.c:126-132`). Policy is side-agnostic by construction.

### 1.3 Other ocean references

- **drive**: `NUM_ATNS 2`, `ACT_SIZES {7,13}`, FloatTensor obs, no mask — stock policy.
- **moba**: `NUM_ATNS 6`, `ACT_SIZES {7,7,3,2,2,2}`, ByteTensor 510 obs, no mask — stock policy.
- **nmmo3**: `OBS_SIZE 1707` ByteTensor, single 26-way head, custom CUDA encoder (above).
- No `[torch]` overrides exist for any of these; `config/default.ini:55-58` sets the torch-path
  classes (`network=MinGRU, encoder=DefaultEncoder, decoder=DefaultDecoder`) and only
  `double_pendulum` overrides (`network=MLP`).

### 1.4 The torch path (`--slowly` / `--cpu` builds)

`pufferl.py:171-178` routes to `pufferlib/torch_pufferl.py`, which builds
`pufferlib.models.Policy(encoder, decoder, network)` by **name lookup in `pufferlib.models`**
(`torch_pufferl.py:475-485`). `pufferlib/models.py` offers: `DefaultEncoder` (Linear),
`MinimalEntityEncoder` (shared-MLP + max-pool over 16 points — a tiny AlphaStar-style entity
encoder, `models.py:38-58`), `NatureEncoder`, `ImpalaEncoder`, and networks `MLP`, `MinGRU`,
`LSTM`, `GRU` (`models.py:88-245`). So yes, **LSTM exists in 4.0 — but only on the torch
path**; the native path is MinGRU-only.

Disqualifiers for training BB on it:
1. **No action-mask plumbing whatsoever** (zero `mask` references in `torch_pufferl.py`;
   confirmed by the project skill §5). Invalid actions get sampled.
2. Throughput: cached 4.0 docs — `--cpu`: "Expect under 200k sps"; "you should really, really
   use our native backend if you are going to scale"; torch is "not stable in bf16" (use
   `--float`) (`docs/vendor/pufferlib/docs.html`).

**Verdict on Q2:** fit within the native path. Use torch only for (a) sanity-debugging the
binding on the Mac, (b) BC pretraining (standalone, outside pufferl entirely — §7.3).

---

## 2. Exactly how MY_ACTION_MASK maps to multi-head sampling

The semantics, end to end (this answers the CRITICAL item):

1. **Env side**: `MY_ACTION_MASK N` with `N == sum(ACT_SIZES)` allocates
   `total_agents × N` uchars (`src/vecenv.h:448-459`); each slot's mask row is the
   **concatenation of per-head masks** in head order. Head `h` owns bytes
   `[Σ_{i<h} ACT_SIZES[i], Σ_{i≤h} ACT_SIZES[i])`. 1 = legal.
2. **Upload**: copied H2D each step (`vecenv.h:574-576`), cast to `precision_t` into the
   rollout buffer `(horizon, agents, N)` (`src/pufferlib.cu:614-626,60,86-89`).
3. **Sampling** (`sample_logits`, `src/pufferlib.cu:443-569`): for each head `h`, a running
   `logits_offset` walks the fused decoder output; `masked_logit` (`pufferlib.cu:431-440`)
   sets masked entries to **−1e4**; the head is softmax-sampled by inverse CDF; per-head
   logprobs are **summed** into one joint logprob (`pufferlib.cu:502-562`). Heads are
   **independent given the observation** — the sample of head 0 cannot influence head 1's
   distribution within a step. **No autoregressive conditioning exists.**
4. **Training** (`ppo_loss_compute`, `src/pufferlib.cu:763+`): identical per-head walk with
   identical masking (`load_logit_masked`/`ppo_discrete_head`, `pufferlib.cu:702-750,841-855`)
   for new logprob, entropy (entropy is computed **over the masked softmax**, so a
   single-legal-action head contributes exactly 0 entropy and 0 logprob), and gradients.
   Rollout-time and train-time masks are therefore consistent (mask is stored in the rollout
   and minibatch buffers, `pufferlib.cu:60,106`).
5. Limits/edge cases: `MAX_ATN_HEADS 16` (`src/kernels.cu:79`); all-zero mask degrades to
   uniform sampling over −1e4 logits (never let it happen — keep ≥1 bit set); float-rounding
   fallback picks the **last legal** action (`pufferlib.cu:536-546`).

**Consequence for factored heads:** per-head masks can only express **product sets**. A legal
set like "these 7 scattered squares" is exact in one fused head, but `x∈{...}×y∈{...}` as two
heads admits illegal (x,y) combinations. This single fact drives the action design in §5.

---

## 3. Memory & throughput budget (drives the obs design)

Rollout storage is `precision_t` (bf16 = 2 B by default): obs `(horizon, total_agents,
OBS_SIZE)`, mask `(horizon, total_agents, sum(ACT_SIZES))` (`src/pufferlib.cu:51-90`), plus
transposed minibatch copies (`pufferlib.cu:95-138`) and a float `grad_logits (N,T,A_total)`
(`pufferlib.cu:179-199`). With chess-like settings (`total_agents=8192, horizon=64`):

| OBS_SIZE | rollout obs VRAM | verdict |
|---|---|---|
| 2,048 (compact, recommended) | 2.1 GB | fine |
| 4,096 (compact + a few engine-computed value maps) | 4.3 GB | fine on 24 GB |
| 19,500 (50 raw board planes — the naive plan) | **20.4 GB** | **infeasible**; also 160 MB/step H2D |

Mask `{30,33,391}` = 454 → 64×8192×454×2 ≈ 0.5 GB (+0.5 GB minibatch copy). Fine.

**Hard rule: do not put raw board planes in the observation buffer.** If a conv trunk is
wanted, ship compact entities and **expand to planes on-GPU inside a custom encoder**
(nmmo3's multihot pattern). This is the deciding argument between candidates A and B.

Throughput reference points: native backend trains chess 2.5 M-param nets for 7-15 B steps per
sweep trial (`config/chess.ini:77-82`); the 3.0 blog cites 2-3 M-param nets at 500k-1M sps and
150k-param nets at 2-4 M sps on one RTX 5090 (`docs/vendor/pufferlib/blog.html`); 4.0's CUDA
trainer is the successor to that. FLOP math for candidate A (§7.1): ≈7.3 MFLOP/agent-step
forward → rollout-forward bound ≈10 M steps/s at 50% bf16 utilization; with train pass
(≈4× forward at `replay_ratio=1`) the compute ceiling is ≈3 M sps; expect 0.5-1.5 M sps
end-to-end. The BB engine (2.34 M engine-steps/s/core, STATUS.md) will not be the bottleneck.

---

## 4. Architecture survey distilled for a 26×15 board

- **Justesen et al. 2019 (FFAI baseline)**: 28 spatial layers + 50 scalars; conv stream =
  16×3×3 then 32×2×2 (stride 1, padded); scalars → FC-25; concat → FC → masked-softmax actor +
  critic. Tiny, and it learned (with reward shaping) on the full board
  (`docs/vendor/papers/bloodbowl-challenge-justesen2019.pdf`; same net in
  `vendor/botbowl/examples/a2c/a2c_agent.py:28-41`).
- **MimicBot (Bot Bowl III winner, Pezzotti 2021)**: 43×17×28 spatial + 116 scalars. Cinit →
  128 ch → **4 residual blocks** (3 convs + leaky ReLU each) → concat input → 3 convs with
  **channel attention** (scalars → 1024-d latent → multiplicative channel gates) → **fully
  convolutional spatial action planes (17 types × board)** + non-spatial logits; value from
  the scalar latent. Key lessons: (1) keep the policy head spatial (don't flatten before the
  action logits); (2) inject global context multiplicatively; (3) **imitation warm-start is
  what made RL work at all**; (4) scripting away no-brainer decisions (block-die picks)
  shrinks the effective action space (arXiv 2108.09478 §3; cached PDF is truncated — re-fetch).
- **AlphaStar**: per-entity encoder (transformer) + spatial trunk + autoregressive heads with
  pointer networks. The *pointer* idea survives contact with PufferLib as chess's
  phase-decomposition; the entity-transformer does not (no attention kernels in the native
  backend) — its cheap cousin is per-entity shared MLP/embedding + pooling
  (`models.py:38-58` is exactly this).
- **OpenAI Five**: huge LSTM over mostly flat features; proves a strong recurrent core over
  engineered features beats clever spatial nets when the obs already encodes relations. This
  is the chess/candidate-A bet.
- **KataGo**: pre-activation ResNet trunk + global-pooling bias layers + convolutional policy
  head. Right shape for board games, but its value comes at depths (10-40 blocks) that are
  pointless at 26×15 with dice noise; the global-pooling-bias idea ≈ MimicBot's channel
  attention. Relevant only to candidate B, scaled to 2-4 blocks.
- **Bot Bowl consensus**: 2-conv baselines learn; the winner's edge came from imitation +
  hybrid scripting + fully-conv heads, not parameter count. For 26×15, 3-5 conv layers at
  32-64 channels is the sweet spot; pooling hurts (the board is already tiny); flatten-then-FC
  is acceptable at this scale.
- **Entity transformer verdict**: not worth it here. Native backend can't run it (would need
  hand-written attention fwd+bwd in CUDA); 32 entities with rich features are well served by
  embedding + shared linear + concat/pool (nmmo3 embeds 47 categorical bytes × 32 dims and
  concatenates all of them, `ocean.cu:12-13,41-51`).

---

## 5. Action-head design

### 5.1 The engine's decision surface

`engine/include/bb/bb_actions.h`: `bb_action = {type(1B), arg(1B), x(1B), y(1B)}`;
`bb_action_type` has **30 values** (incl. `BB_A_NONE`); the engine already advances until a
coach decision and surfaces one decision at a time (procedure-stack design, bb_actions.h:1-10).
Decisions cluster as: type-only (END_TURN, STAND_UP...), type+arg (ACTIVATE slot, DECLARE kind,
CHOOSE_DIE, USE_REROLL, APOTHECARY, CHOOSE_OPTION...), type+square (STEP, JUMP, BLOCK_TARGET,
PUSH_SQUARE, KICK_TARGET...), and type+arg+square (SETUP_PLACE, SPECIAL_TARGET).

### 5.2 Why the drafted `{~30, ~256, 26, 15}` layout is wrong, in two ways

1. **Split x/y heads cannot mask non-product square sets** (§2). Block targets, push squares,
   jump landings are scattered squares; `x`-mask × `y`-mask over-approximates and samples
   jointly-illegal squares. Fuse x,y into **one 390-way square head** — exact masks, identical
   total logit count (26+15 → 390 costs only +349 logits ≈ +0.7 MB mask VRAM at 8192 agents).
2. **A 256-way arg head is waste**: the only large `arg` domain is skill ids (~108), but at any
   decision window only a handful of skills/options are offerable. Surface them as an
   **option index** (the engine already has `BB_A_CHOOSE_OPTION` = "index into a
   procedure-defined option list", bb_actions.h:57-59). 32 option slots cover every window
   (player slots 16, act kinds 14, dice 3, reroll sources 4, binary 2). The binding maps
   option-index ↔ canonical `bb_action.arg` for replay/BC fidelity.

### 5.3 Recommended layout

```c
// puffer/bloodbowl/binding.c
#define NUM_ATNS 3
#define ACT_SIZES {30, 33, 391}     // type | arg-option (null+32) | square (null+390)
#define MY_ACTION_MASK 454          // == 30+33+391, indexed by flattened offset
```

- **Head 0 — type (30)**: `bb_action_type` verbatim; `BB_A_NONE=0` doubles as the null.
- **Head 1 — arg (33)**: index 0 = null (always legal when no arg is needed); 1..32 = option
  slots for the current window.
- **Head 2 — square (391)**: index 0 = null; `1 + y*26 + x` for board squares.
- **Inactive heads are masked to exactly their null index** → they sample deterministically
  and contribute 0 logprob and 0 entropy (§2.4), so the joint PPO objective sees only the real
  decision.

**Phase protocol (resolves type↔square coupling exactly):**
- If exactly one type is legal (the overwhelmingly common case: push squares, die picks,
  reroll windows, kick target...): one RL step — type head masked to that type, arg/square
  head masked exactly. No coupling possible.
- If ≥2 types are legal **and** at least one carries a square/arg whose legal set differs by
  type (mid-activation STEP/JUMP/BLOCK/PASS/END; turn-level ACTIVATE/END_TURN): **split into
  two RL steps** chess-style — step 1: type only (other heads → null); step 2: the committed
  type's square/arg with its exact mask. Write the pending type into the obs (analog of
  `O_PICK_PHASE`/`O_SELECTED_PIECE`) and let MinGRU carry it too.
- SETUP_PLACE may sample arg(slot)+square jointly in one step: its legal set is near-product
  (slot choice ⊥ square legality given counts), and the D1 setup budget + auto-fix already
  tolerates noise. Optional simplification: phase-split it anyway.

This adds roughly one extra step per multi-type decision window — engine throughput
(2.34 M steps/s/core) absorbs it without noticing.

**Alternative considered and rejected — AlphaZero/MimicBot-style spatial action planes**
(~17 types × 390 = 6.6k+ logits, exact joint masking in one step): mask + grad_logits buffers
balloon (≈7 GB at 8192 agents) and `sample_logits`' serial per-agent loop walks every logit
twice per step. Viable only at ≤2048 agents with a conv head the native decoder can't express
anyway. The phase-split design gets the same exactness for 454 logits.

**Equally valid minimal variant:** chess-pure single head `ACT_SIZES {454}` with the same
index space. Pros: one softmax, simplest possible binding. Cons: setup needs an extra phase,
and per-head semantics (BC cross-entropy per head, per-head entropy logging) are lost. Either
works; the 3-head version maps 1:1 onto `bb_action` and onto FUMBBL replay actions.

### 5.4 Mask-writing rules (binding contract)

Write fresh obs + masks **for both slots every step** (chess pattern,
`chess.h:1577-1587`); memset the slot's 454 mask bytes then set legal bits of *the next
decision*; never leave a head all-zero; the torch path ignores masks, so `c_step` must treat
any in-range triple as "illegal → small negative reward + no-op" (chess's
`reward_invalid_*` pattern, `ocean/chess/binding.c`).

---

## 6. Observation design implications (policy-facing)

The stock encoder is a **single biasless Linear into MinGRU** — every feature must be linearly
usable. Chess's compact-token format shows the way; budget ≈2.0-2.5 KB/slot (ByteTensor, all
values 0/1 or small ints — obs are cast raw to bf16, **no normalization layer exists**;
skill §9 warns a magnitude-1000 feature stalls training):

| Block | Size (B) | Content |
|---|---|---|
| 32 player entities | 32×~48 ≈ 1536 | per player: slot one-hot-ish id, team, x, y (plus x/26, y/15 quantized), status, MA/ST/AG/PA/AV, used/activated flags, ball flag, **skill mask compressed**: 24 bytes of the 192-bit mask *or* (better for candidate B) up to 8 skill-id bytes for embedding |
| Egocentric flip | — | away team sees the pitch mirrored (chess's `sq^56` analog); slot↔side randomized at init (`binding.c:126-132` pattern) |
| Global scalars | ~100 | score, half, turn, rerolls, weather, KO/CAS counts, turnover flag, phase one-hots |
| Decision context | ~80 | current decision type one-hots, **pending phase type** (§5.3), active player slot, option-slot descriptors (what arg 1..32 means: option kind + payload) |
| Legality projection | 390 + 30 + 33 | the current mask itself, copied into obs (chess does exactly this — `O_VALID_PIECES/O_VALID_DESTS`; the net never sees the sampler's mask, skill §5) |
| Optional spatial summaries | k×390 (k≤2) | engine-computed per-square bytes: opponent tackle-zone count, ball square — cheap linear substitutes for convs |

Total ≈ 2.2-2.6 KB → 2.3-2.7 GB rollout VRAM at 8192 agents. Use `OBS_TENSOR_T ByteTensor`.

---

## 7. Recommendations

### 7.1 PRIMARY — "Puffer-stock BB" (config-only; ship today)

Architecture (all existing code): `Linear(OBS≈2304 → 512)` → `MinGRU ×3 (512)` →
`Linear(512 → 454+1)`.

- **Params**: enc 2304×512 = 1.18 M; MinGRU 3×512×1536 = 2.36 M; dec 455×512 = 0.23 M →
  **≈3.8 M params** (1.5× chess).
- **Est. cost**: ≈7.3 MFLOP/agent-step forward; ≈3 M sps compute ceiling on a 4090-class GPU,
  **realistic 0.5-1.5 M sps** end-to-end (chess-calibrated). Policy will not bottleneck; the
  mask/obs H2D and env decision density set the pace.
- **Risk**: linear encoder discards spatial adjacency — mitigated by legality-in-obs,
  egocentric coords, engine-computed tackle-zone summaries, and BC warm-start (the
  botbowl baseline showed even 2 convs suffice; a linear over richer engineered features plus
  a 512-wide recurrent core is in the same class, and chess validates it at scale).
- **Why MinGRU ×3 and not less**: BB has real cross-step state even with full observability —
  phase-split pending decisions (§5.3), multi-step block/push chains, opponent tendencies in
  self-play. Sweep `num_layers ∈ {1..4}` later (`[sweep.policy.num_layers]` already exists,
  `config/default.ini:123-127`).

`config/bloodbowl.ini` (delta from `config/default.ini`; chess values as priors):

```ini
[base]
env_name = bloodbowl

[policy]
hidden_size = 512
num_layers = 3

[vec]
total_agents = 8192          ; 4096 envs x 2 slots
num_buffers = 2
num_threads = 16
num_frozen_banks = 1
frozen_bank_pct = 0.1

[selfplay]
enabled = 1
max_size = 500
swap_winrate = 0.6
min_games = 4096
snapshot_interval = 1_000_000_000
opp_timeout_steps = 4_000_000_000

[env]
; every key here must be dict_get-readable in my_init (vecenv.h:47-52)
reward_invalid = -0.02
reward_td = 1.0
reward_shaping_pct = 1.0     ; anneal-able dense shaping (Justesen-style)
render_fps = 30

[train]
; start from chess.ini's tuned block (horizon 64, minibatch 32768, vtrace,
; ent_coef 0.0985 annealed) and re-sweep once the env is stable
horizon = 64
minibatch_size = 32768
ent_coef = 0.0984801
anneal_ent_coef = 1

[torch]                      ; debug path only
network = MinGRU
encoder = DefaultEncoder
decoder = DefaultDecoder
```

PyTorch reference implementation (BC pretraining + `--slowly` debugging; matches
`pufferlib/models.py:7-28`'s interface exactly — `encoder(B, obs) → (B,H)`;
`network.forward_eval/(forward_train)`; `decoder → (logit_splits, values)`):

```python
import torch, torch.nn as nn
from pufferlib.models import Policy, MinGRU, DefaultDecoder

ACT_SIZES = (30, 33, 391)

class BloodBowlEncoder(nn.Module):
    """Mirror of the native encoder: ONE biasless Linear (src/models.cu:412-418).
    Keep it exactly this shape so BC weights export 1:1 to the native trainer."""
    def __init__(self, obs_size, hidden_size=512):
        super().__init__()
        self.encoder = nn.Linear(obs_size, hidden_size, bias=False)
    def forward(self, obs):                      # obs: (B, OBS_SIZE) uint8
        return self.encoder(obs.float())         # native casts bytes raw; no /255

def make_policy(obs_size=2304, hidden=512, layers=3):
    return Policy(
        encoder=BloodBowlEncoder(obs_size, hidden),
        decoder=DefaultDecoder(ACT_SIZES, hidden),   # per-head split, models.py:60-86
        network=MinGRU(hidden_size=hidden, num_layers=layers),
    )

def masked_bc_loss(logits_split, mask, target):   # mask: (B,454) bool, target: (B,3) long
    loss, off = 0.0, 0
    for h, (lg, A) in enumerate(zip(logits_split, ACT_SIZES)):
        lg = lg.masked_fill(~mask[:, off:off+A], -1e4)   # match pufferlib.cu:437
        loss = loss + nn.functional.cross_entropy(lg, target[:, h]); off += A
    return loss
```

**BC → native weight export**: the native checkpoint format is the flat fp32
`master_weights` blob (`src/bindings.cu:180-218`), in registration order
encoder → decoder → MinGRU layers (`src/models.cu:836-845`), each tensor 16-byte-aligned
(`src/kernels.cu:424-431,445-458`). With `hidden_size` a multiple of 8 every tensor's numel is
already 16-byte aligned, so the file is a plain concatenation of
`[enc (512,2304)] [dec (455,512)] [gru0 (1536,512)] [gru1] [gru2]` row-major fp32 —
**but verify empirically** by diffing against a fresh `save_weights` dump
(`pufferl.num_params()` gives the expected element count). Note the native decoder's last row
is the value head and the native MinGRU differs from `nn.GRU` — use `pufferlib.models.MinGRU`
(same math as `models.cu:106-137`, cross-tested by upstream) for BC, never a vanilla GRU.

### 7.2 STRETCH — custom CUDA "bloodbowl" encoder (conv trunk + entity embeddings)

When/if candidate A plateaus on spatial play (screening, cage formation, path safety), add a
case to `create_custom_encoder` (`src/ocean.cu:574-590`) — the only trainer file that needs
touching, ~600-900 lines patterned on the nmmo3 encoder:

```
obs (compact, ~2.3KB as in §6, skills as ≤8 id-bytes/player)
├─ bb_scatter_kernel: build (B, 24, 26, 15) planes on-GPU from entity bytes
│    [team occ ×2, prone/stunned ×2, ball, MA/ST/AG/AV quantized, TZ counts,
│     legal-square plane from the obs legality block, pending-type broadcast]
├─ gemm_conv_forward: 24→48 ch, k5 s2 → (48, 11, 6), ReLU        (~29k w)
├─ gemm_conv_forward: 48→48 ch, k3 s1 → (48, 9, 4), ReLU         (~21k w)   → flatten 1728
├─ bb_embedding_kernel: skill-id bytes → 16-d learned embeddings, sum per player → 32×16=512
├─ concat [conv 1728 | skills 512 | entity scalars ~1024 | globals+context ~210]
└─ Linear+ReLU → hidden 512                                       (~1.8M w)
   → stock MinGRU ×3 → stock decoder (454+1)
```

≈ **7 M params**; +~14 MFLOP/agent-step → est. **0.4-0.8 M sps** (nmmo3 precedent: 2-3 M-param
custom-encoder nets at 500k-1M sps). Constraints to respect: im2col conv has **no padding**
(`ocean.cu:217-234`) — sizes above account for it; all buffers pre-registered via
`reg_train/reg_rollout` (graph-capture safe); backward must be hand-written (copy
`nmmo3_encoder_backward`'s structure, `ocean.cu:433-476`). The sweep's `hidden_size` knob must
keep flowing into the projection width (nmmo3 honors `e->out_dim`).

A torch twin of this encoder slots into §7.1's `make_policy` for BC; weight export then
needs the conv/embedding tensors prepended in the same registration order.

### 7.3 Self-play pool requirements on the policy (Q5)

Read of `pufferlib/selfplay.py` + `src/pufferlib.cu:1728-1865` + `src/bindings.cu:180-229`:

- **No puffernet export requirement.** Frozen banks are full GPU `WeightBank`s built by the
  *same* `build_policy` (custom encoder included, `pufferlib.cu:1742`) and loaded from the
  trainer's own flat-fp32 `save_weights` snapshots (`selfplay.py:172-175,269`;
  size-checked at `pufferlib.cu:1845-1850`). Anything the primary can be, a frozen opponent
  can be. Banks may differ in `hidden_size/num_layers` only via
  `frozen_bank_hidden_size/num_layers` (`pufferlib.cu:2079-2084`) — encoder shape is
  env-keyed and shared.
- Policy/binding obligations are all env-side: `MY_USES_PERM` + per-slot pointer arrays,
  `MY_USES_TAGS` + `boundary_reached` at game end, and `hist_score_bank_<b>/hist_n_bank_<b>`
  log fields (consumed at `selfplay.py:224-225`; swap alignment via `count_aligned`,
  `selfplay.py:267-270`). Banks are forwarded separately per rollout step over their
  `bank_layout` slice (`pufferlib.cu:628-687`) — sizable `frozen_bank_pct` slightly reduces
  SPS (extra forward per bank), another reason to keep the net lean.
- `puffernet.h` *does* cover our stack if we ever want pure-C inference on the Mac (demo
  binary, scripted-opponent harness): `make_linear/make_mingru/make_conv2d/make_embedding/
  make_cat_dim1/_softmax_multidiscrete` all exist (`puffernet.h:457,948-1000,563,681,757,370`)
  and `get_weights_aligned` matches the trainer's 16-byte layout (`puffernet.h:74-80`).
  Worth doing for candidate A (≈100 lines, mirror `ocean/squared/squared.c`).

### 7.4 What NOT to build

- **Autoregressive heads in one forward pass** — not supported by `sample_logits`; the
  phase-split protocol is the sanctioned equivalent (chess proves it trains).
- **Entity transformer on the native path** — no attention kernels exist; hand-writing fused
  attention fwd+bwd in bf16 CUDA is weeks of work for marginal gain at 32 entities.
- **Raw board planes in OBS** — 20 GB rollout buffer (§3).
- **Torch-path training for the real runs** — no masks, <200k sps.
- **Separate x/y heads** — non-product legal sets (§5.2).

---

## 8. Open items / verification hooks

1. Decision-density measurement: instrument the engine to count coach decisions/game (plan
   estimates ~340) — fixes the real SPS target and the phase-split overhead (+1 step per
   multi-type window).
2. Empirically diff a fresh `save_weights` blob against the torch replica's expected layout
   before trusting BC export (§7.1, alignment caveat).
3. `docs/vendor/papers/mimicbot-2108.09478.pdf` and `invalid-action-masking-2006.14171.pdf`
   are **truncated/corrupt** (no PDF trailer; the latter is 1 page) — re-fetch via
   `tools/fetch_docs.sh` (findings in §4 were taken from a fresh arXiv copy).
4. Sweep `hidden_size {256..1024} × num_layers {1..4}` once the env is stable — the harness
   already supports it (`config/default.ini:117-127`), and match-mode scoring vs a fixed
   checkpoint (`chess.ini:68-75` pattern) is the right metric for BB too.

## Source map (key citations)

| Claim | Where |
|---|---|
| Fixed Encoder/MinGRU/Decoder policy; only hidden/layers configurable | `src/pufferlib.cu:1679-1726`, `src/bindings.cu:402-403` |
| Custom encoder hook + nmmo3 example (conv/embedding/multihot machinery) | `src/ocean.cu:574-590,29-51,217-370,398-476` |
| Encoder = biasless Linear; Decoder = Linear with fused value column | `src/models.cu:412-418,485-493,506`; value read `src/pufferlib.cu:463,565` |
| Mask semantics: flattened per-head offsets, −1e4, independent heads, joint logprob | `src/pufferlib.cu:431-440,443-569` (sample), `:702-750,841-899` (train), `src/vecenv.h:448-459` |
| MAX_ATN_HEADS=16 | `src/kernels.cu:79` |
| Chess: 167-byte token obs, 97-action single head, two-phase pick, legality-in-obs | `ocean/chess/binding.c:4-8`, `ocean/chess/chess.h:279-296,357-358,469,1666-1716` |
| LSTM/GRU only on torch path; torch path has no masks, <200k sps on --cpu | `pufferlib/models.py:105-245`, `pufferlib/torch_pufferl.py:475-515`, `docs/vendor/pufferlib/docs.html` |
| Frozen banks = same build_policy, load flat-fp32 save_weights snapshots | `src/pufferlib.cu:1728-1865`, `src/bindings.cu:180-229`, `pufferlib/selfplay.py:119-211,267-277` |
| Rollout buffer sizing (obs/mask in bf16 × horizon × agents) | `src/pufferlib.cu:51-138` |
| Weight file layout / 16-byte alignment | `src/kernels.cu:424-458`, `src/puffernet.h:49-80` |
| Engine decision interface (30 action types, 4-byte action) | `engine/include/bb/bb_actions.h` |
| Botbowl baselines / MimicBot architecture | `docs/vendor/papers/bloodbowl-challenge-justesen2019.pdf`, arXiv 2108.09478, `vendor/botbowl/examples/a2c/a2c_agent.py:28-41` |
