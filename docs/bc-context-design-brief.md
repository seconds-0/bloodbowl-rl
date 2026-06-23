# BC temporal-context — design brief (Codex builds from this)

**Decision (Alex, 2026-06-23):** add temporal context to behavioral cloning via **frame-stacked
within-turn context features first** (single-step BC, cheap, surgical), with **recurrent BC as a
second head-to-head A/B**. This brief is loop 1 of a research→design→build→review×3 cycle. Codex
designs the detailed approach (use the plan tool) and implements; Claude + a Codex review critique it.

## Why this, not recurrence-first (research synthesis, loop-1)

Five parallel research agents (SOTA recurrent BC, game-AI precedent, our pipeline, our prior
decisions, build-vs-alternatives). The load-bearing findings:

1. **AlphaStar Unplugged (the authoritative BC ablation): "no memory performs better than LSTM for
   behavior cloning"**, and for BC total samples M×K dominate — K=1 tied K=64. Direct evidence that
   recurrence does not help *cloning accuracy* at scale. (arXiv:2308.03526)
2. **MimicBot (Bot Bowl winner, the real Blood Bowl BC precedent) is single-frame / no memory** and
   still cloned well + bootstrapped past its scripted expert. (arXiv:2108.09478)
3. Blood Bowl is **fully observable**; the genuinely-missing info is **short-horizon, within-turn**
   (which player am I mid-cage-with, have I thrown blocks in order, is the team reroll spent) — the
   regime where a short **history window matches recurrence** at a fraction of the cost.
4. **Copycat / causal confusion** (de Haan 2019; Wen 2020): feeding history (esp. raw last-action)
   can raise *validation accuracy* while *rollout play gets worse*. Prefer **structural** features
   over raw last-action; **the screen metric (val accuracy) is exactly what copycat inflates** — so
   a positive accuracy result must be confirmed by rollout strength, not trusted on its own.
5. D35 literally says "sequence **context** > bigger policy > more data" — *context*, not
   *recurrence*. Our own D47/D140 ranked this lever below backplay-curriculum and demoted it to "BC
   research." (Recurrence stays on deck as the A/B because we reuse that LSTM in RL — warm-start
   fidelity is its real justification, per AlphaStar's BC→RL handoff.)

Also independently re-confirmed across AlphaStar (persistent KL-to-supervised), MimicBot (hybrid
BC-loss during RL), and Diplomacy piKL: **keep a KL-to-BC anchor THROUGH RL, don't anneal to zero**
— that is a *separate* workstream (D172 lever b) but the research strongly endorses it; note it, do
not fold it into this build.

## Candidate context features (Codex: verify which already exist in obs-v4, add only the new ones)

obs-v4 = 2782B and (per docs/obs-v4-spec.md) carries score/turn/half/**rerolls-remaining** scalars
and player stance/moved — so some of these may already be present. The genuinely-new, low-copycat,
high-value signal is mostly *within-turn sequencing*:

- **activation index within the current team-turn** (the Nth activation since the last END_TURN) — structural.
- **team reroll used this turn** (bool) — structural (check if derivable from existing rerolls scalar + history).
- **per-player "already-activated-this-turn"** flag/plane — structural; Blood Bowl enforces one
  activation/player/turn, so derivable from the action stream. High value for cage-sequencing.
- **last action(s)** (type [+ target] of the previous 1–3 decisions for the same coach) — the
  copycat-risky one; include but with **dropout on this feature**, and prefer the structural three above.

## The cheap-screen vs engine-integrate tension (Codex: design the call, recommend in the plan)

The pairs already carry `replay_id`(u32), `cmd`(u32 FUMBBL commandNr = temporal order), `agent`(u8),
and the action targets (`type/arg/sq`) — see `training/bc_pretrain.py` `rec_dtype` (~L74-84). So the
history features can be computed **at BC-load time** from pairs sorted by `(replay_id, agent, cmd)`,
**with no C engine change and no re-extraction** — a fast accuracy *screen*.

- **Path A (cheap screen):** compute features from ordered pairs, append to the obs vector, retrain
  single-step BC, A/B vs the iid baseline on the **fixed D172 val set** (val exact ~0.451 @ 3000
  steps, seed 42, val-frac 0.2). Fast; but **measures accuracy only** — cannot do an env rollout
  because the env doesn't supply these features, so it **cannot rule out copycat by itself**.
- **Path B (engine-integrate, obs-v5):** add the winning features to the C obs encoder
  (`bbe_encode_obs`), bump the 3 OBS_SIZE sync points, re-extract pairs, retrain — then the env
  supplies them at RL time and we can rollout/Elo-confirm. Bigger build; gated on Path-A showing a
  real accuracy lift.

Recommended staging: **Path A as a screen** (if the structural features give a meaningful val-exact
lift over iid, and the lift is NOT carried solely by the copycat-prone last-action feature →
ablate it), then **Path B** to integrate + rollout-confirm. Codex: validate or revise this staging
in the plan.

## A/B protocol + measurement discipline

- Reuse the **D172 fixed-val harness** (identical val set, checksum-verified; seed 42, 3000 steps
  cosine, batch 256, lr 1e-3) so the comparison isolates the feature change.
- Report per arm: val **exact** + per-head acc (type/arg/sq). Arms: (1) iid baseline, (2) +structural
  features, (3) +structural+last-action, (4) +last-action-only (the copycat ablation — if (4) ≈ (3)
  the gain is copycat, not planning).
- Keep **log-loss** (cross-entropy) — theoretically favorable for horizon (Foster 2024); do not switch.
- **Per-head applicability masks:** arg/square heads are only meaningful for some action-types; do
  not train them on garbage labels where they don't apply (matters more once context flows).
- Copycat caveat stated in every result: a Path-A accuracy win is a *screen*, confirmed only by
  Path-B rollout strength.

## Codebase map (from research, file:line — verify before relying)

- `training/bc_pretrain.py`: `rec_dtype` L74-84 (replay/cmd/agent/obs/mask/type/arg/sq);
  `load_shards` L87-109; `split_by_replay` L147-154; `forward_heads` L168-172 (zero state, the iid
  limitation); `masked_losses` L175-184; `evaluate` L187-205 (the `exact` metric); train loop L278-283.
- ACT_SIZES = (30, 33, 391), mask 454 bits.
- Pairs `.bbp` v2: 16B header + records; `cmd` = FUMBBL commandNr (order), `replay_id` groups games.
- `validation/pairs_v4` (6.4G) + `bc_pretrain.py` live on box-1 (ssh3.vast.ai:12464, repo /root/bloodbowl-rl).
- The edited harness from D172 (`--train-frac`, fixed val) is in box-1 `/tmp/bc_pretrain.py` + the
  D172 artifacts — reuse for the controlled A/B.

## Constraints

- Box-1 runs a live `puffer train` defense1 + a `server.py` BBTV stream — **do not disturb them**;
  BC shares the GPU (~17G free). Never delete cloud resources not created in-task; on a quota/disk
  blocker STOP and report.
- Implementation can be developed/unit-tested on the Mac repo; full BC training/A-B runs on box-1.
- Atomic commits, no attribution footers, `--no-gpg-sign`.
