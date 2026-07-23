# bloodbowl-rl

RL training harness for **Blood Bowl Third Season Edition (BB2025)**:
deterministic C11 rules engine → PufferLib 4.0 native env → PPO + action
masking + self-play curriculum, with BC support from curated FUMBBL replays.

**Read `AGENTS.md` first.** Then read the tail of `DECISIONS.md` (currently
through D217) and, for reward/replay work,
`docs/reward-and-replay-audit-2026-07-09.md`. The ledger is chronological; the
July audit and D177–D192 supersede older prose that calls the June v4 reward
economy "settled." Where this file and newer ledger evidence disagree, the
newer evidence wins.

## Project skills — use them

| Skill | When |
|-------|------|
| `fleet-ops` | Tailscale RTX 2070 and optional Vast: live discovery, isolated checkout, process safety, sync/build, launch/monitor, artifacts |
| `training-experiments` | Designing/launching/reading controlled arms: immutable manifests, reward decomposition, integrity gates, transfer, metrics, tournaments |
| `puffer-env-dev` | PufferLib binding, build, training CLI, selfplay config |
| `bb-rules` | Implementing/verifying any game rule, skill, table; edition-delta questions |
| `fumbbl-data` | Fetching/parsing FUMBBL API data or replays; BC corpus curation |
| `bb-validation` | Running/triaging the 7 validation layers; oracle setup (FFB/Jervis/Calculator) |

## Current program state (reward/replay audit active, 2026-07-14)

- **NO PRODUCTION REWARD HAS BEEN PROMOTED.** R0 is the next-stage experimental
  baseline only. Do not silently change defaults, deploy, or touch the production
  evaluator/stream.
- **Distance is the learnability scaffold (D177):** across the repaired paired
  2×2, its main effect was `+0.76365 TD/game` and `+0.11130` match score. It
  also increased blocks and 2D-red rate. Raw `ΔΦ` is not exact PBRS at
  `gamma=0.995`; make it discounted-exact or anneal it away after capability
  exists.
- **R2 failed transfer (D178):** removing possession+gain made match score worse
  in all 8 paired seed/style/side cells, and raised losses plus opponent TDs in
  all 8. Retain R0 for the next screen, but decompose possession annuity from
  ball-gain before any confirmation.
- **Next reward screen:** distance on in all arms; `{possession+gain,
  possession-only, gain-only, neither}` at `500M × 2 seeds`; then learned
  opponents, roster macro, longer run, and second ancestry.
- **D182 integrity rejection:** the July 13–14 screen finished all eight arms,
  but one train emission crossed PPO's clamp by exactly `0.015`; the old schema
  cannot classify its sign or terminal context. The audit independently found
  an unsafe terminal result-plus-shaping path. It has no completion proof and
  must not feed transfer. Correct terminal composition, add split recurrence
  telemetry, then rerun every arm under the same reviewed semantics.
- **Replay edition/coverage gate (D179):** 15,347 raw = 11,580 BB2025 + 3,767
  BB2020. Use the strict 9,118-ID non-empty BB2025 allowlist. The 1,622,231
  joined BB2025 records are sharply opening-censored and rare-action poor.
- **Strict replay-state bank (D191):** the historical BBS bank contains 123
  BB2020-source records among 15,471. Future scenario/curriculum work must use
  the hash-pinned, manifest-producing `tools/filter_state_bank.py` subset: 15,348
  records from 5,328 strict BB2025 IDs. It remains all half one and opening-
  censored; filtering edition does not create passing or late-game coverage.
  The BBS1 fingerprint is an ABI/build guard, not content validation; preserve
  the loader's bounds, enum, grid/player, and ball-state checks for every raw
  snapshot before it can enter curriculum reset selection.
- **Strict-bank scenario coverage (D192):** `bank_scenario_scan` and
  `report_scenario_coverage.py` classify overlapping S1–S6 opportunity
  structures only; they do not label actions, outcomes, regret, or curriculum
  weights. Canonical raw counts are S1 5,023; S2 3,047; S3 12,661; S4 2,883;
  S5 3,605; and S6 11,763 across 15,348 records / 5,328 replay IDs. Preserve
  the exact bank/manifest/source/binary pins and replay-disjoint splits. Use
  the measured thin/empty regions to size authored fixtures; never wire this
  historical opening-censored bank into training without a separate review.
- **Authored drill bank plan:** use
  `docs/plans/authored-drill-state-bank.md`. Every state starts from an engine
  initializer and is reached only through legal `bb_apply` actions; discovery
  records every action/die, and exact replay must reproduce the raw match bytes
  with `bb_rng_script`. Before serialization, independently rediscover the full
  recipe from configuration-only fields and require byte identity, binding the
  declared procgen and game seeds, plus each controller stream actually used,
  to the action/dice transcript. Controller fields unused by a recipe kind are
  canonical zeroes; exact replay alone is not seed provenance. Never construct late-game context by writing score,
  half, turn, players, grid, ball, or procedure frames. Split by recipe-template
  group and quarantine paired counterfactual outcomes from training inputs.
  BBS1 production reset admission currently admits the shared
  `MATCH -> TEAM_TURN` boundary plus one exact nested shape: a failed first-step,
  non-Rush Dodge reroll window under
  `MATCH -> TEAM_TURN -> ACTIVATION(Move) -> MOVE -> TEST(Dodge)`. The nested
  validator recomputes the target, requires real Use/Decline actions and
  ordinary MA remaining, rejects Rooted/Distracted/Eye Gouged movers, and
  rejects all other TEST/parent shapes and malformed skill bits. A resolved
  Rush leaves provenance in `match.ret` and is outside this first shape. The
  pending destination is exposed egocentrically in observation context bytes
  9/12 so reset observations are transition-complete. Tackle suppresses the
  Dodge skill reroll while leaving Team Re-roll and Pro independent. Scenario
  scanners remain fresh-team-turn-only; do not substitute the broader resumable
  gate where a classifier assumes that boundary. The authored writer may use
  resumable admission only for the exact F4 pending-Dodge recipe kind; every
  F1/F2/F3/F5 record remains fresh-team-turn-only. Later target/reroll decisions
  need their own procedure-specific
  validation before the writer or loader may accept them. Every emitted
  authored record must also
  pass the canonical one-action continuation gate after loading; the gate is a
  resumability check and must never be interpreted as an action label. The F1
  proof privately verifies a non-dash-PA, non-No-Ball carrier's zero-die legal
  activation -> Pass declaration -> standing, tackle-zone-capable, non-No-Ball
  teammate target while serializing only the fresh-team-turn state. The raw
  match keeps its ordinary ball-carrier field, but no separate probe metadata,
  chosen action, target, or nested frame is serialized or labeled.
  The fixed F2 proof applies the same fresh-team-turn/private-probe contract to
  Hand-off: the carrier's legal activation and Hand-off declaration consume
  zero dice and expose at least one adjacent catch-capable teammate. A target
  set containing only rules-legal No Ball teammates is rejected as an authored
  transfer opportunity, without changing engine Hand-off legality.
  The fixed F5 proof likewise serializes only a fresh team-turn state. Its
  active carrier must satisfy `bb_can_score_without_dice`; a private zero-die
  activation and Move declaration must still offer End Activation. This proves
  that score-now and Stall are available, never which choice is better, and no
  path/action/preference metadata is stored.
  The fixed F4 proof uses controller seed 1 and legally reaches the exact
  pending-Dodge reroll window after 384 decisions and 110 dice. Its transcript
  ends with the failed Step before Team/Dodge/Decline is selected; no reroll
  action, result, reward, regret, or policy label is stored. Independent
  rediscovery, exact replay, deterministic BBS bytes, mixed-batch preflight,
  production-loader byte identity, decision masks, and continuation are
  mandatory. This selective writer exception does not authorize any other
  nested frame or any training/publication artifact.
  The first F3 axis remains on the ordinary fresh-turn boundary and requires
  exactly 16 half-two cells: turns 1-8 for each of the two active-side
  orientations. The requested turn and side are stored provenance, must be zero
  for every non-axis recipe, and are independently rediscovered. Use
  `BB_HOME..BB_AWAY`, never the 30-entry roster catalogue, when sizing this
  orientation axis. Its quota validator proves one structurally valid recipe
  per cell; the writer still owns full provenance, exact replay, boundary, and
  continuation admission. Distinct controller seeds 1000-1015 prove the fixed
  matrix, while matching optimized/sanitized 256-seed x 16-cell sweeps yield
  4,088 captures, 8 clean ends, and no unexpected failure. Score, possession,
  receiving, material, reroll, roster/race, and tactical-quality diversity plus
  sidecars, publication, training, rewards, evaluation, and deployment remain
  separate contracts.
  The first F2 axis remains on that same fresh-turn boundary and requires four
  cells: Home/Away active-side orientation crossed with exactly one versus
  two-or-more legal catch-capable Hand-off targets. Its input-preserving counter
  first validates the complete raw boundary, then privately performs the legal
  zero-die carrier activation and Hand-off declaration. Count only targets that
  can attempt the Catch; a rules-legal No Ball target is not included. Store
  side and bucket as rediscovered provenance, reject the bucket on non-axis
  recipes, and never treat two-or-more as exactly two. Fixed seeds 4/2/8/13
  bind the four cells. Matching optimized and sanitizer sweeps over 4,096 seeds
  per cell yield 1,246/994/1,189/1,291 exact-replayable captures and zero
  unexpected failures. This proves structural opportunity diversity only; it
  does not label Hand-off, a receiver, or tactical quality and does not
  authorize publication, training, reward changes, evaluation, or deployment.
  The first F1 axis likewise stays at the fresh-team-turn boundary and requires
  four cells: Home/Away active-side orientation crossed with an open or marked
  carrier who still satisfies the complete Pass-opportunity predicate. Derive
  pressure with `bb_is_marked` only after full raw-boundary and F1 validation;
  geometric adjacency is not a substitute for engine Tackle-Zone semantics.
  Store and independently rediscover both side and pressure, reject the
  pressure field on non-axis recipes, and keep the private Pass declaration and
  target probe out of the serialized record. This proves state-level
  opportunity structure only. The optimized 4,096-seed-per-cell sweep yields
  Home/open 1,323, Home/marked 948, Away/open 1,464, and Away/marked 996 exact
  captures, with complementary clean ends and zero unexpected failure; the
  ASan/UBSan sweep matches every count without a sanitizer finding. The axis
  labels neither Pass nor any receiver/target and authorizes no publication,
  training, reward,
  evaluation, deployment, BBTV, or frozen-queue change.
  The cross-family proof-bundle validator composes exactly 26 existing proofs:
  F1 4, F2 4, F3 16, F4 1, and F5 1. Primary family is the exact recipe kind,
  not overlapping state predicates; input order is irrelevant. The validator
  reuses the complete typed axis/predicate gates and remains structural only.
  The 4/4/16/1/1 mix is intentionally not balanced and is not a canonical bank,
  publication transaction, or training input. The ordinary writer remains the
  provenance/replay/admission/continuation authority; sidecars, splits, reports,
  manifest-last publication, staging, and training stay separately gated.
  Use `ad_build_authored_proof_bundle` as the only owner of the fixed proof
  configuration, seed schedule, order, and positional A9 record metadata. It
  builds in temporary checked storage and commits atomically into caller-owned
  arrays. `0xA9000000 + index` preserves the reviewed proof bytes but is not a
  persistent identity or sidecar key; the later metadata schema must define a
  collision-audited recipe/version/variant registry before publication.
  Identity schema 1 reserves opaque durable authored IDs
  `0xAE000001..0xAE00001A` for those exact 26 recipes while deliberately
  preserving the legacy A9 BBS bytes. Resolve identities only through the
  immutable template/allocation ledger and separate frozen proof schedule;
  never derive meaning from AE bits or proof position. The defining projection
  is every discovery configuration field, including bit-exact procgen float
  bits; transcripts and raw states remain writer provenance, not identity.
  Schema 1 is closed at 26 rows and revision 1. Do not append a row, reinterpret
  an ID, edit the ledger/schedule/oracle/authority bundle, or weaken the
  writer's fresh/resumable/continuation gateways. Any future revision or cell
  requires the separately reviewed general compiler contract. Run
  `make authored-identity-verify`; the protected Linux authority must also
  verify every newly reachable commit in a fresh tokenless, networkless,
  read-only-source container. The immutable mapper probe must reject every
  defining configuration field through the public API, including paired
  composition-valid swaps for every semantic axis. Its authority also freezes
  the public result ABI, function signatures, and constants. Recipe, identity,
  and error storage are mutually disjoint; alias rejection over the greater
  supplied/fixed extents precedes every error write. The Linux writer probe
  must cover every canonical record at count one,
  every family's provenance, the writer's exact allowed `count` uses, and
  complete-batch admission/continuation before its first write callback. This
  registry still authorizes no
  sidecar, bank publication, training input, reward, evaluation, or deployment.
  The next reviewed design is `docs/plans/authored-sidecar-schema.md`: paired
  26-line `records.jsonl`/`recipes.jsonl` schemas reconcile frozen A9 record
  order with AE identity and bind canonical transcript, dice, legal-action,
  and raw-state hashes. They carry no action, receiver, or target selected or
  recommended at or after capture and no separate receiver/target, reward,
  outcome, regret, value, split, or curriculum label. Pre-capture packed actions
  stop before capture, may retain historical arguments/receivers/targets, serve
  replay provenance only, and are forbidden as BC/policy/receiver-target
  labels. This is a schema plan,
  not a serializer or publisher; filesystem transactions, manifests, bank
  consumers, training, evaluation, and deployment remain later gates. Keep the
  D209 identity authority byte-immutable: bootstrap a separate sidecar
  authority first, then implement serialization only after its workflow exists
  on the trusted base. Both F5 facts are false outside F5 and independently
  required true on the fixed F5 row. The serializer must exercise the unchanged
  public BBS writer exactly once through serializer-owned memory-backed
  `FILE *` storage, compare and discard its frozen bytes, and must not refactor
  D209's immutable writer into a new preflight API. Both complete streams stage
  privately before the two final non-failing caller-output copies. The
  serializer-free bootstrap must freeze the future ABI, exact memory-stream
  length/NUL and BBS oracle semantics, malicious candidates, and full D210
  isolation before implementation; its protected workflow covers exact-SHA
  `pull_request_target`, `merge_group`, and main push.
- **BC loader (D180):** use the bounded streaming loader and replay-disjoint
  split. Replay-first is the current default, not the final sampler; next
  stratify by roster/matchup, depth, and action family.
- **Long-horizon curve (D187/D188):** the frozen seed-42 0–6B curve improves against
  its four static training banks but is non-monotonic, in-pool evidence. Do not
  select the newest checkpoint or reward from it. Post-run selection uses the
  fixed paired milestone protocol; future reward work needs gamma-corrected
  distance/anneal and no-rush A/Bs plus replay-derived rare-action scenarios.
  D190 supplies per-component emitted-reward attribution for future builds.
  It is not present in, and must not trigger a rebuild of, the pinned vacation
  queues; do not make retroactive component claims about their panels.
- Canonical artifacts:
  `runs/reward-screens/reward-screen-20260709-v1/SCREEN_COMPLETE.json`,
  `runs/reward-transfer-20260713-v1/ANALYSIS.json`, and
  `runs/replay-audit-20260713/`.

### Historical v5/path-actions context (2026-06-11; not current reward authority)

- **v5 PATH-ACTIONS (D85/D91 — status REVISED):** macro_moves=1 = STEP head selects any reachable destination, env auto-routes (engine untouched). Wins MIRROR offense evals (+26%, 1.625 from-kickoff) but LOST the first head-to-head tournament to the v4 lineage (~45% of decisive games, both env configs, D91). Mirror evals = offense diagnostics only; TOURNAMENTS are the strength scoreboard. Macro question re-opens under contested training (D90): v5-contested (ballhawk, macro) vs v4-contested (japan, stepwise) settle it at matched caps. Eval/launch macro ckpts with trailing `--env.macro-moves 1`.
- v4 kickoff lineage (training tds): 0.616→...→1.360 (D88, 240B, still climbing) — head-to-head CHAMPION as of D91. CONTESTED ERA (D90): frozen-bc_v4-teacher era over; arms now train vs their own caps; possession metric counts TD-ends as held (pre/post-D90 not comparable).

### v4 lineage reference (2026-06-08)

- **Era: obs-v4 + bc_v4.** Sighted stage-1 dominated the v3 lineage on every axis at matched 15B (D55: ~6x faster tds, 2dred falling through the v3 plateau). Mid-curriculum kickoff tournament drew 98.8% — expected per D50/D56, not failure.
- **Then-running historical arms:** `v4_s2`, `v4_s2tax`, `v3_tax`, and
  `profile-v4-native-asym`. They are not live-state claims; consult newer ledger
  entries and host discovery.
- **Curriculum ladder** (stage knob = `--env.demo-endzone-maxdist`): 6 → 9 → 12 → 0 (= "uniform": any demo-bank start, no endzone filter) → kickoff starts (`--env.demo-reset-pct 0`). +3 squares per stage, never more (D51: 6→12 overshot). Advance at tds plateau; warm-start each stage from the previous stage's highest-STEP ckpt.
- The June queue is superseded by the July queue in
  `.claude/skills/training-experiments/SKILL.md` and D177–D188.

## Hard-won facts (verified — don't relearn these)

### Obs / checkpoints / build
- **obs-v5 = 2782 bytes** (obs-v4 probability planes plus decision-window truth; spec `docs/obs-v5-spec.md`). Rolled block faces are visible at reroll/choose windows, TEST kind and active movement expenditure are explicit, invalid ball coordinates zero, and Touchback placements are spatially addressable. **Three OBS_SIZE sync points must agree** (static asserts catch 2 of 3): `BBE_OBS_SIZE` in `puffer/bloodbowl/bloodbowl.h`, `#define OBS_SIZE` in `puffer/bloodbowl/binding.c:8`, `--obs-size` in `training/convert_checkpoint.py` (default 2782; v3 ckpts need `--obs-size 1612`). Obs-v4 has the same shape but different semantics: blob size cannot distinguish it, so require source/module provenance and no v4 warm-start, replay mixing, or direct curve comparison without a reviewed bridge. Obs-v3 and older checkpoints remain input-shape **incompatible**.
- **Current checkpoint lineage is external and mandatory.** A flat blob has no
  header; require its canonical `.lineage.json` from
  `tools/checkpoint_lineage.py`, which binds obs-v5/exact-joint-v1, policy
  shape, checkpoint hash, producer manifest, source/module/Puffer patch hashes,
  and eligibility. Repaired warm/pool launchers reject missing, mismatched, or
  qualification-only sidecars. Build current pools with `tools/build_league.py`;
  `--legacy-unlabeled` is historical reconstruction only. Launch the disposable
  exact-action canary with `WARM` and `POOL` unset: it is fresh, pool-free, and
  permanently ineligible as ancestry.
- **Recurrent evaluation has an explicit boundary contract.** The installed
  patch stack applies `puffer_recurrent_eval_state.patch` after exact actions.
  Graph warmup restores primary and every frozen-bank state to exact zero;
  train→eval starts fresh games and clears state once; nonterminal evaluation
  state persists across rollout calls; terminal rows clear before the next
  game's observation. Graph-enabled qualification cells use `cudagraphs=10`,
  exactly matching the frozen Puffer/canary warmup boundary. Reject `0` because
  it captures the first execution before CUDA lazy initialization; reserve `-1`
  for the explicit graph-off parity cell. Training is allowed only with
  `reset_state=True` and
  evaluation mode off. Do not ship a hidden-state-sized no-op reset launch:
  keep the captured gate row-sized, then measure graph-on/off parity, target-GPU
  throughput, primary/frozen post-terminal parity, and zero-update ratios before
  any canary.
- **The target-GPU recurrent gate is executable and fail closed.** Install
  `puffer_frozen_prio_mask.patch` after recurrent state hardening and
  `puffer_recurrent_cuda_qualification.patch` last,
  then run `tools/qualify_recurrent_cuda.py` in an isolated checkout. Its two
  native evidence calls are size-bounded and unused by ordinary execution. The
  qualification build must be fp32; BF16 behavior-log-probability storage does
  not satisfy this gate's strict recomputation-ratio contract. The
  run command requires predeclared clean source-commit, candidate-module,
  backend-source, and environment hashes and rejects a merely self-consistent
  unexpected build. The final verdict requires all-bank construction zero,
  graph parity,
  primary/frozen post-terminal automatic/manual-zero parity, full observed
  learner-row ratio coverage with unchanged weight bytes and zero frozen-row
  selections even at `prio_alpha=0`, all 16 control hard counters at literal
  zero in every transition-executing cell (construction emits no episode
  telemetry), and a strictly wrapped,
  hashed same-host/config/precision predecessor throughput control whose
  module/backend/runtime/environment hashes were declared at capture and
  consumption.
  The predecessor is a fresh isolated fp32 build of exact commit
  `afc8008933548438ca93c41341f5f08fdd294386` (obs-v5/exact-joint-v1, no
  qualification surface) after the recovery boundary. The former exact
  candidate `a52fc6e2f4ece5a7ff16bb4791e3aca4dd72f2e3` used a different isolated
  source checkout and Puffer tree but is now permanently rejected. Use a clean
  merged schema-3 control-runner checkout
  that records and revalidates both source commits and installer checks. Never
  modify or reuse the recovery Puffer tree; the live marginal-action module is
  historical evidence only.
  No baseline,
  incomplete coverage, malformed/non-finite data, or failed gate means no 50M
  canary. All outputs are qualification-only and ancestry-ineligible. Never
  launch from the rejected `a52fc6e2` checkout. Historical merged commit
  `ee7ace4` rejects that profile before creating output. D226 uses two separate
  immutable records: a plan authorization binds a fresh accepted schema-3
  qualification before the two-file plan can exist, and a launch authorization
  binds that plan plus the exact disabled one-shot unit and empty stopped-
  validation output. Rebuild and independently requalify the exact final merged
  authorization commit; the accepted parent qualification does not cover changed
  launcher bytes. Follow
  `docs/replacement-exact-action-canary-2070-execution-checklist.md`.
  The frozen screen launcher intentionally creates and retains
  `$OUT_DIR/.screen.lock` before plan freezing. Plan-only closure is exactly two
  regular files: `SCREEN_MANIFEST.json` plus a zero-byte, empty-digest,
  nonblocking-`flock`-verified released `.screen.lock`, with both modes, sizes,
  and hashes bound. Do not delete the lock to satisfy a stale one-file
  checklist; any missing, held, nonempty, or extra entry rejects the canary.
  Systemd unit commands have a second escape boundary: use `$$` for a literal
  Bash dollar and `%%` for a literal Bash percent. The intended `printf "%s"`
  must appear as `printf "%%s"` in unit bytes; bare `%s` is systemd's user-shell
  specifier. Require disposable empty/fixed/command-failure probes before real
  unit installation.
  The sole `a52fc6e2` canary start is rejected and non-retryable: its last
  preflight found `training/selfplay_league.patch` unapplied in vendored
  `selfplay.py`, before GPU use. Qualification schema 3 makes the replacement
  candidate and control runner use the same operator-predeclared merged commit
  in different isolated source checkouts and rejects a value unequal to the
  control runner's clean `HEAD`. It binds the patch file, hashes patched `selfplay.py`
  into backend identity, and requires full reverse applicability. Recapture predecessor
  `afc8008933548438ca93c41341f5f08fdd294386` with the schema-3 runner and use
  all-new qualification/canary authority identities. Never modify or reuse the
  recovery Puffer tree. The v4 launcher remains fail-closed without both exact
  authorities, accepts only the fixed 50M seed-42 fresh contract, and binds the
  shared CUDART path/hash/count through the trainer's same-process evidence.
  Any failed identity is terminal and never retried.
  The first schema-3 predecessor capture is also rejected and non-retryable: it
  compared the immutable predecessor's historical compiled digest against the
  newer expanded source registry and failed before timing or GPU work. Under
  D224, preserve the role-correct historical compiled-source digest separately
  from a mandatory complete runtime-source digest. The latter always includes
  the exact on-disk `pufferlib/selfplay.py` and is separately predeclared for
  the predecessor, so runtime drift still fails closed. Preserve the
  predecessor's historical upstream/unpatched self-play file; only the current
  candidate receives the league patch. Use
  a fresh output directory and a newly merged clean control/candidate commit;
  never rebuild the predecessor to manufacture a modern compiled identity.
  D225 also rejects both `predecessor-throughput-v2` and
  `predecessor-throughput-v3` before a transition. The shared cause is a
  process-local CUDA initialization order: importing `_C` before the first
  CUDART call leaves that fresh WSL process at `cudaErrorNoDevice`, while a
  successful CUDART probe before import preserves the device. Do not retry an
  unchanged capture or treat `nvidia-smi`, Torch, or a different probe process
  as proof for the worker. Every qualification worker and the actual Puffer
  trainer must use `tools/puffer_cuda_runtime.py` in the same process: require
  `cudaSuccess` and a positive count before `_C`, retain the exact resolved
  CUDART handle, import `_C` or the CLI, then require the same count afterward.
  Bind the wrapper, CUDART path/hash, both probe records, and
  `CUDA_VISIBLE_DEVICES` into provenance; compare the same runtime hash/count
  across predecessor and candidate throughput. A failure terminates the fresh
  process without repair. Replace the candidate binding's ignored return plus
  assertion with a Python-visible CUDA name/string error. Before a new timed
  capture, merge/review the contract, create fresh control/candidate roots,
  and pass one construction-only target check. The current screen launcher is
  still frozen and unauthorized; only a later post-qualification change may
  bind this wrapper into a new canary authority.
  The construction gate is a required executable input to both predecessor
  timing and full qualification, not a checklist-only dependency. Each command
  revalidates and binds the same path/hash before output or worker dispatch.
  The predecessor worker must receive the full frozen module/backend/runtime/
  environment declaration and validate its own imported identity before
  `create_pufferl`, warmup, or rollout; a comparison performed only after
  timing is too late for the exact-zero compute budget.
  For training, label the early launcher probe only as an expectation: the
  wrapper explicitly imports `_C`, publishes the actual trainer process's full
  pre/post evidence before optimization, requires it to match the expectation,
  and atomically embeds it in the run manifest plus a hash-bound checkpoint
  sidecar.
- **`puffer/bloodbowl/` is the SOURCE OF TRUTH; `vendor/PufferLib/ocean/bloodbowl/` is an installed snapshot** written by `tools/install_puffer_env.sh` — the build compiles the snapshot, NOT your edit. The snapshot can lag (the Mac checkout's may still say 1612). Drift guard: `tools/install_puffer_env.sh --check` (exit 1 = re-install). Run it before any build on a training box.
- After ANY env code change, ON THE TARGET: `bash tools/install_puffer_env.sh`,
  `bash tools/install_puffer_env.sh --check`, then
  `cd vendor/PufferLib && rm -rf build && ./build.sh bloodbowl --float` (torch
  needs `--float`; plain build = bf16 native CUDA). Never skip the install or
  clean rebuild. Audit runs used `/home/rache/bloodbowl-rl-audit` on the
  Tailscale `wsl-ubuntu` host; `/home/rache/bloodbowl-rl` may serve production
  evaluation and must not be disturbed without authorization.
- **Reward experiment launch contract:** use complete JSON manifests under
  `puffer/config/rewards/`, `tools/run_reward_screen.sh`, and immutable plan/
  status/completion records. Never launch a July reward arm through bare
  `run_synthesis_c.sh`; it carries historical inherited reward defaults and
  cannot provide the audited provenance/integrity contract.
- **BC corpus:** the historical 12,304 shards/2,085,330 records are mixed
  edition at the raw-replay layer. The strict current training surface is 9,118
  non-empty BB2025 replay IDs / 1,622,231 records, selected from embedded
  `rulesVersion`; use `runs/replay-audit-20260713/bb2025-nonempty.ids` and the
  streaming loader.
- Warm relaunch: ANCHOR=newest ckpt, but **newest mtime ≠ highest step across run dirs** — check the step number embedded in the filename.
- **Exact joint sampling is the accepted action contract in BOTH backends**
  (D218). The env transports the current packed joint support; native/Torch
  sample type, then arg conditioned on type, then square conditioned on both.
  The selected 454-bit conditional masks are stored and reused by PPO. Inactive
  heads are singleton sentinels, so they contribute zero log-probability and
  entropy. `bbe_decode` rejects instead of repairing. Historical marginal-mask
  checkpoints/corpora are a distinct behavior lineage; new pairs are BBP v4.
- **Exact-action error budget:** scientific contamination tolerance remains
  zero, but detection is fail-fast. The engine aborts on the first decode/support
  violation; reward screens incrementally guard every complete machine panel,
  include `illegal_frac` and the reward/error counters in final train/eval
  integrity, fail after 180 seconds without an integrity-bearing panel, and use
  an embedded watchdog that survives outer-screen loss to terminate the trainer
  through a status-publishing wrapper. The screen and embedded watchdog must use
  independent incremental state files. Before a long post-v5 run, require
  provenance, CUDA graph/zero-update checks, deterministic full games, then a
  disposable 50M-step reward-frozen canary. Never continue from its checkpoint.
  Rejected candidate `a52fc6e2` retains its original 11-key live registry only
  as historical evidence. The replacement v4 manifest, live guards,
  qualification, and stopped analyzer all require the complete 16-key registry
  at literal zero, including signed clamp delta, clipped samples, terminal and
  non-terminal clipped samples, and non-finite samples per episode. Those five
  are redundant under coherent telemetry, but any disagreement invalidates the
  evidence. Never relabel the old candidate as the replacement.

### Reward economy (July-audited interpretation)
- **Reward objective outcomes or decision quality, not lucky dice.** Realized
  injury, pickup, scatter, send-off, and similar shaping pays variance and is
  normally invalid. Where a tactical scaffold is justified, price the declared
  decision from pre-roll expected value (`bb_block_ev`) or a settled state. This
  is necessary but not sufficient: EV/state shaping can still redefine the
  policy objective and must pass held-out match-utility and transfer gates.
  Win/loss/draw and touchdowns are genuine objective outcomes. Possession,
  ball-gain/loss, distance, threat, contact, and similar dense terms are
  experimental shaping—not mini-terminals whose legitimacy can be assumed.
  Any term advertised as PBRS must use the discounted form
  `beta*(gamma*Phi(s')-Phi(s))`, telescope in tests, and handle terminals
  correctly; raw `Phi(s')-Phi(s)` is not exact at `gamma != 1`.
- R0's repaired manifest is the current experimental baseline. Its combined
  possession-annuity/ball-gain family survived scripted transfer, but the audit
  has not identified which component helps defense. Decompose it before
  retuning coefficients.
- Future builds expose a 28-channel emitted-reward ledger from the team-0/home
  perspective. Interpret component totals as pre-clamp raw reward. Require
  `sum(components) + residual` to match raw `episode_return`, then require
  `episode_return - reward_clip_signed_delta` to match
  `reward_postclip_return`, within float tolerance. A nonzero clamp delta fails
  integrity independently even when both identities hold; mismatch/non-finite
  counters also fail. This is diagnostic attribution, not evidence that any
  shaping term is beneficial.
- Distance shaping is required for present learnability, not validated as final
  utility. Raw `Phi(s')-Phi(s)` is not exact PBRS under `gamma=0.995`; prefer
  `beta*(gamma*Phi(s')-Phi(s))` or demonstrate non-inferiority while annealing.
- Anti-farming invariants remain: no ball-loss double fine with the annuity,
  exact telescoping for any claimed potential, blitz exposure rush-gated, and
  terminal emissions composed from explicit objective plus result rather than
  incidental same-action shaping, and no reward clipping/non-finite values.
  Human-looking statistics remain
  canaries, not goals.

### Metric semantics
- `tds` from curriculum starts is not comparable across maxdist stages.
  `block_2dred_frac` and action rates are diagnostic canaries, not objectives.
  Corrected genuine-turn BB2025 human possession is `0.47394` turn-weighted
  (`0.47453` per-game mean); old `~0.15` values used different/poisoned
  semantics and must not be reused as a target.
- **Graduation rule (D50/D56):** kickoff-start tournament win-rate is the FINAL exam only; mid-curriculum tournaments draw 97–99% and that is EXPECTED. Draw rate rises with prior strength.
- **Tournament procedure** (runs on box-1's judge GPU): ship both ckpts to box-1 box-to-box, convert BOTH sides — `python training/convert_checkpoint.py --to-cuda A.bin -o A_cuda.bin` (**mind `--obs-size`: 2782 default, 1612 for v3 lineage**; conversion drops biases, so equal treatment of both sides matters, D45) — then `puffer match bloodbowl --load-model-path A_cuda.bin --load-enemy-model-path B_cuda.bin --num-games 4096`. Read the decisive-game split, not the draw rate.

### Compute and remote operations
- The four-box Vast table below this project's history is stale; discover live
  state rather than restarting old IDs. The current free lightweight target is
  the Tailscale `wsl-ubuntu` RTX 2070. Use the isolated audit checkout for
  experiments and keep the production checkout/process separate.
- Before launching, record GPU/driver/CUDA/Python/Torch/compiler versions, free
  disk, imported `_C.__file__`, precision, and module hash. Do not kill or
  replace an existing `server.py` evaluator unless the user asks.
- BBTV on the 2070 follows the newest complete manifested reward-screen
  checkpoint against that run's frozen warm start. Use the isolated float viewer
  and reversible service override in `docs/bbtv-latest-checkpoint.md`; never
  rebuild the trainer's Puffer tree or read a checkpoint still being written.
  For the armed vacation overflow, its match child must load the separate
  CPU/fp32 `_C` and remain absent from the exact pinned compute-PID parser.
  `CUDA_VISIBLE_DEVICES=` alone makes a GPU-built `_C` fail (D189).
- Unattended vacation runs use a literal hash-pinned queue, not an adaptive
  experiment-generating agent. `tools/experiment_queue.py` must halt on plan
  drift, failed validation, stale/absent progress, runtime, disk/inodes, or sustained
  thermal limits; only explicitly restart-validating jobs are `resume_safe`.
  Commands, validators, and job environment inputs use typed literal/pinned/
  mutable/predecessor-artifact values; replay-pool directories require recursive
  tree pins. Never encode a path in a literal or use an untyped environment path.
  Every invocation is a pinned executable plus pinned runner file. Literals are
  only numbers, lowercase SHA-256 digests, or long flags; put other strings in
  a pinned runner/config.
  Never change a production default from unattended evidence. Operational
  details and the departure smoke gate are in
  `docs/vacation-autonomy-2026-07.md`.
  The concise fault/return procedure is
  `docs/vacation-operator-runbook.md`; follow its state-to-action table rather
  than improvising a restart or manual overflow start.
- The accepted-candidate vacation queue is frozen by
  `tools/freeze_vacation_queue.py` only after the main `1B x 2` paired
  confirmation, scripted transfer, and learned-anchor transfer are complete.
  It runs the same confirmation from `league9`, gates both lineages, then (only
  on pass) runs matched `6B x 3`
  reference/candidate screens from both ancestries. `paired-final` means seeds
  42/43/44, not a live choice of candidate. Screen jobs are not resume-safe;
  atomic transfer/gate jobs are. One predeclared R0 route applies when the
  decomposition transfer recommends `both` with no eligible simplification,
  the freezer requires null learned inputs plus a fully provenance-complete
  decomposition screen and emits two non-resume-safe
  `control-final` jobs, each R0-only at `12B x seeds 42/43/44`, preserving the
  same `72B` total without training a rejected objective. A legacy screen that
  omitted the config-tree, default-config, or full runtime-file identity cannot
  authorize this route and must be rerun under the complete contract. Its
  scripted transfer must use reference `both` and contain all three
  simplification candidates; rejecting a subset is not “all rejected.”
  A distinct `confirmation-rejected-baseline` route applies only when the
  already-selected candidate fails the unchanged paired self-play gate. The
  freezer independently regenerates that failure, matches the screen's exact
  embedded selection-transfer proof, writes a pinned authorization record, and
  emits only the same two R0 `control-final` jobs. It is not a candidate switch,
  all-candidates-rejected evidence, or promotion. Vacation specs always name
  the route explicitly; never infer it from `candidate_arm`.
- Queue-owned screens run with `ARM_DETACH=0`. The queue's new-session process
  group must contain the screen, arm wrapper, Puffer trainer, and descendants;
  never add nested `setsid`/daemonization that would evade queue guard cleanup.
- Maintain `docs/vacation-progress.md` at least hourly during the active
  preparation/run with current status, completed work, blockers, and next
  steps. Treat it as an operational journal, not experiment evidence.
- D186's only reviewed post-primary work is one separately frozen R0
  `control-final` screen from the exact netblock pool-bank ancestry. Use
  `tools/freeze_vacation_overflow.py`; its completion proof and delayed starter
  must observe the exact primary plan complete, both success validators, an
  inactive primary service, unchanged pins, no prior overflow state, and no GPU
  compute PID. The overflow is third-ancestry characterization, never a reward
  rescue, candidate switch, promotion, or permission to edit the active plan.
- D215/D216 record that the July overflow terminally halted after seed 42
  finished exactly 10,000 evaluation games against its frozen 10,001 minimum.
  Keep the old audit root and queue byte-unchanged. The only reviewed recovery
  shape is `tools/freeze_vacation_overflow_recovery.py` in the separate
  `/home/rache/bloodbowl-rl-recovery-20260719` root: a restart-safe exact
  terminal-evidence proof followed by a fresh, ordinary, non-resume-safe R0
  `control-final` run for seeds 42/43/44 from netblock. Never reuse the old
  result/checkpoint as accepted output, restart the old queue, or start
  milestone evaluation from the rejected artifact.
  Use only the separately rooted `experiment-recovery-queue@.service`. Require
  the exact reviewed recovery root, all seven Puffer patch files, and an empty
  exact-pinned `nvidia-smi` compute-process result in the proof validation that
  runs immediately before PPO. BBTV may read manifested checkpoints from both
  roots, but writes its selection/cache in the recovery root and switches only
  after a newer checkpoint is complete. Its launcher and follower execute from
  the exact merged recovery checkout; `BBTV_ROOT=/home/rache/bloodbowl-rl`
  supplies only the unchanged production runtime assets.
- Post-run R0 trajectory evaluation is frozen in
  `docs/plans/r0-milestone-evaluation.md` and implemented by
  `tools/run_checkpoint_milestone_eval.py`. It accepts only a completed,
  revalidated `control-final` screen; resolves 0/1/2/4/6/8/10/12B native
  checkpoints by embedded step; hashes spec, implementation, results,
  checkpoints, anchors, cells, analysis, and completion; uses common match
  seeds and both backend roles; and fails closed unless the GPU is exclusive
  and the BBTV follower was explicitly quiesced.
  Static-pool metrics are in-sample, exact historical anchors are
  lineage-connected rather than independently held out, and a forced roster
  grid is stratification because training sampled every roster. Plateau
  nomination is for Stage-B compression only, never automatic selection or
  promotion. Do not deploy this tool over the pinned live audit snapshot or
  start it while primary/overflow is live or BBTV remains active.

### Engine / rules / oracles (stable since v1)
- PufferLib 4.0 (`vendor/PufferLib`, branch 4.0) uses `src/vecenv.h` macros — the online `env_binding.h` ABI is dead 3.0. `ocean/chess/` is the template; `ocean/convert/` is stale.
- Rules source: `docs/vendor/bloodbowlbase/` mirror (May 2026 FAQ, inline `<del>` errata — second sentence is current law). BB2025: 30 teams, Devious category, Elite Skills 0–4 cap. May 2026 errata removed the "D6 never below 1" floor. Team re-rolls UNLIMITED per turn (D15). Stalling eligibility is snapshotted at carrier activation: a no-Dodge/no-Rush/no-gate scoring path plus retained possession invokes the non-rerollable crowd D6 at activation end; voluntarily ending the team turn before activating that carrier also invokes it, while an earlier Turnover or a successful Pass/Hand-off transfer does not (D193). The roll is still consumed on turns 7–8. The distinct policy choice to forego one player but continue with others is not yet represented in the 454-way action interface. A PA- player cannot declare Pass but may Hand-off. No Ball players cannot catch, intercept, or receive a Touchback; they remain legal Hand-off targets when otherwise eligible but auto-fail the required Catch without a catch die, and their square remains a legal Pass target before the ball Bounces (D198). Keep rules legality in engine semantics, never duplicate it as a reward fine.
- FUMBBL replays: `game` = END-of-game snapshot; kickoff state from setup-phase `fieldModelSetPlayerCoordinate`; dice/decisions in `reportList.reports`. `vendor/ffb/.../PlayerState.java` is the authoritative bit table.
- Jervis: parallel bb2020/bb2025 suites (~174 files, diff for deltas); foul conversion broken (@Ignore). ActionCalculator (281 rows) defaults Season3=BB2025 — valid oracle odds. FFB headless needs MySQL ≤5.6/MariaDB ≤10.4; `gamestate/get` is the differential extraction point.

## Top footguns (each cost real hours)

1. `python str.replace` silently no-ops on anchor mismatch — ALWAYS grep the file after scripted edits.
2. zsh does NOT word-split unquoted vars (`set -- $hp` fails).
3. `pkill -f` matches its own watcher commands — use `[b]racket` patterns.
4. Partial code syncs (header without binding.c) build stale mixtures — sync `engine/` AND `puffer/` together (`fleet.sh setup`), re-run `install_puffer_env.sh` (or `--check`), and grep the changed symbol on the box.
5. Vast stopped instances can be RECLAIMED (GPU re-rented) — restart promptly or accept replacement.
6. Launching a "v4" arm via `run_synthesis_c.sh` without overriding its baked-in synthesis-C knobs ships the poisoned ball_loss fine — diff your trailing args against a live twin's command line before launch.
7. Memorial/feed render hooks: NEVER format strings or do I/O from env-stepping threads — POD staging slot + render-thread consumer (two SIGSEGVs).
8. raylib `InitWindow` segfaults when the Mac display is asleep — `spectate.sh` gates on display-awake.
9. Monitor/SSH loops need `ssh -n` and `ConnectTimeout`.
10. "Newest checkpoint" by mtime ≠ highest step across run dirs — check the step number in the filename before warm-relaunching.
11. **CPU thread cap (D59):** `nproc` (visible CPUs) ≫ cgroup quota (allowed CPUs) on some boxes → unpinned torch/BLAS pools thrash (5x SPS loss). `tools/cpu_cap.sh` fixes it and is auto-sourced by all launch scripts + `~/.bashrc`; any manual `puffer train` must `. tools/cpu_cap.sh` first. Verify: live trainer's `OMP_NUM_THREADS` == quota, thread count ~150-190 not hundreds.
12. **A run completes/dies but the box keeps billing — detect via LOG MTIME, not log content (D65).** A finished `puffer train` leaves its log frozen at the final dashboard; any monitor that greps log *content* reports it "running" forever. Two flagship arms idle-billed 8–13h this way. ALWAYS gate liveness on `stat -c %Y <log>` age (>360s stale = dead/done) AND `pgrep -xc puffer` (the trainer process is named exactly `puffer`; `pgrep -f "puffer [t]rain"` matches its own shell). A run hitting its STEPS cap exits cleanly (not a crash) — advance the ladder or reassign/stop the box.
13. **`fleet.sh setup` clobbers a box's demo bank with the Mac's (D65).** The rsync excludes don't cover `validation/states/` or `resources/bloodbowl/`, so setup overwrites the box's `state_bank.bbs` with whatever the Mac repo holds. Keep the canonical (largest) bank in the Mac's `validation/states/bank.bbs` (gitignored) so syncs ship it; after any setup, re-check `Loaded N demo states` / bank byte-size on the box.
14. **`fleet.sh <cmd> <name>` exact-matches `bb-<name>` and SILENTLY no-ops on a miss (D65).** `bb-taiwan-anchor` ≠ `bb-taiwan` → `setup taiwan` prints "no running instance labeled bb-taiwan" and the sync never runs (the box stays on stale code, e.g. obs-v3). Always pass the exact label suffix (`taiwan-anchor`) and confirm the rsync/build actually ran.
15. **A reward field omitted from a launcher/config is not the same as explicit
    zero.** Use a complete canonical reward manifest and validate its SHA; never
    inherit old synthesis defaults into a causal arm.
16. **A final Steps line is not an accepted result.** Require explicit eval phase,
    the explicitly requested completed games, final cumulative reprint,
    checkpoint hash, and zero integrity counters. The acceptance floor must
    equal the request; exact completion is valid and cannot rely on vectorized
    overshoot. Use the screen/transfer analyzers.
17. **Directory names are not edition proof.** Filter replay IDs from embedded
    `rulesVersion`; never mix BB2020 into BB2025 because a shard happens to parse.
18. **Replay-first is not depth-balanced.** It removes long-replay dominance but
    the corpus remains opening-censored; stratify/cap before claiming late-game
    or rare-action competence.
19. **Do not touch the production checkout or evaluator while using the 2070 audit
    checkout.** Confirm paths and processes before sync, build, kill, or launch.
20. **Do not infer Stalling from distance alone.** Use
    `bb_can_score_without_dice` at activation start and preserve its exemptions;
    checking only the end position misclassifies Rush/Dodge/Trait paths, prior
    Turnovers, and successful possession transfers. Crowd and Steady Footing
    dice must remain in the engine RNG stream.

## Conventions

- Engine: C11, zero hot-loop allocation, every die through `bb_rng` (PCG-64 or injected script). Deterministic always.
- Every rulebook "may" is policy surface (D29); discovery-vs-artifact discriminator before patching weird behavior (D46); gradual anneal, never cold-off (D28); `make goldens` is explicit — rules fixes are EXPECTED to break goldens (D6).
- Reward claims require immutable manifests, paired seeds, held-out transfer,
  integrity gates, and ledger entries. Do not promote from attractive behavior
  or training metrics alone.
- Replay splits are replay-disjoint and edition-exact. Use bounded streaming;
  never restore eager all-corpus materialization.
- Vendored clones read-only, pinned in `vendor/PINS.md` (`tools/vendor_sync.sh`). Doc cache: `docs/SOURCES.md` / `tools/fetch_docs.sh`.
- Atomic commits, no attribution footers, `--no-gpg-sign` if Yubikey absent. No GW rulebook text or assets in the repo.
