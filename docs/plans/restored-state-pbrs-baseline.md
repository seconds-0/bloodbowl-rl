# Restored-state exact-PBRS `s0` baseline

Status: complete at runtime checkpoint
`ac3c4fecbf664774a5d8b471b5a2fb352ab45bc5`; watched-fail, independent
review, optimized, sanitizer, lineage, clean-install, and deterministic
validation green

Base: `3512e7c2ff2b64bad397586fcff55a54388ec1df`

## Problem statement

The exact discounted potential-based shaping path is intended to emit

```text
F(s_t, s_t+1) = gamma * Phi(s_t+1) - Phi(s_t)
```

on every transition. The reset path currently violates that identity on the
first transition of every episode:

1. `bbe_reset_match()` finishes constructing or restoring the episode's first
   policy-visible state `s0`;
2. it then sets all four `pot_fetch_prev` / `pot_carry_prev` histories to
   `NAN`;
3. after the first policy action, the exact-PBRS path computes `Phi(s1)`;
4. when the history is `NAN`, it substitutes that same `Phi(s1)` for the
   missing `Phi(s0)`.

The resulting first reward is `(gamma - 1) * Phi(s1)`, not
`gamma * Phi(s1) - Phi(s0)`. The two are equal only when `Phi(s0) == Phi(s1)`.
This is especially harmful for restored curriculum states, which deliberately
begin near useful decisions with a nonzero loose-ball or carry potential.

The independently reproduced loose-ball example is:

```text
coefficient = 0.05
gamma       = 0.995
dist(s0)    = 3  -> Phi(s0) = 0.05 * (25 - 3) = 1.10
dist(s1)    = 2  -> Phi(s1) = 0.05 * (25 - 2) = 1.15

correct = 0.995 * 1.15 - 1.10 = +0.04425
current = 0.995 * 1.15 - 1.15 = -0.00575
error   = -0.05
```

The state-bank and PBRS suites are separately green, but no existing test
composes a real bank load, `c_reset`, a nonzero restored `Phi(s0)`, and the
first real `c_step`.

## Intended contract

After `bbe_reset_match()` has selected a bank state or generated a fresh match,
seeded the in-match RNG, advanced the engine to its first policy-visible
decision, and refreshed legal actions:

- when `reward_dist_pbrs_gamma > 0`, each team's fetch and carry history is the
  finite total potential of the actual current match:

  ```text
  pot_fetch_prev[t] = Phi_fetch(s0, t)
  pot_carry_prev[t] = Phi_carry(s0, t)
  ```

  Inactive regimes and zero coefficients have potential `0.0`, not `NAN`.

- when `reward_dist_pbrs_gamma <= 0`, preserve the legacy raw-delta contract
  exactly: both histories begin as `NAN`, and the first in-regime transition
  only primes the relevant history without emitting a delta.

The exact contract applies uniformly to restored and procgen episodes. It must
not special-case `demo_started`: exact PBRS is a transition identity, and the
actual `s0` is authoritative regardless of how it was constructed.

A second reset must recompute from the new episode's `s0`; it must never carry
potential history across episodes. The same invariant must hold when
`bbe_finish_episode()` invokes `bbe_reset_match()` for autoreset. Terminal
composition must first consume the old episode's history, publish its terminal
reward/log entry, and only then install the new episode's baseline. The
terminal `reward_ptr` and `terminal_ptr` intentionally survive that internal
autoreset for the caller to observe; only new-episode scratch/history is reset.

## Scope and non-goals

In scope:

- exact-PBRS fetch/carry history initialization at the reset boundary;
- real BBS load + `c_reset` + `c_step` regressions;
- restored team-turn boundaries and the already-admitted pending-Dodge
  reroll boundary;
- finite-zero inactive-channel behavior;
- legacy `gamma <= 0` compatibility;
- repeated-reset isolation;
- a fresh procgen reset and a real truncation/autoreset transition;
- fail-fast enforcement if a supported exact-PBRS step ever reaches reward
  calculation with non-finite reset history;
- comments documenting the dual exact/legacy history semantics;
- deterministic, sanitizer, install, provenance, and lineage validation;
- a chronological decision entry after the implementation is proven.

Out of scope:

- changing distance definitions, potential signs, coefficients, gamma, reward
  clipping, terminal payback, or any other reward component;
- widening raw-BBS admission;
- changing the pending-Dodge state validator, which intentionally rejects a
  ball carried by the pending mover;
- typed/hash-pinned bank manifests, strict bank loading, pre-indexed strata, or
  rejection-sampling behavior;
- configuration validation;
- engine rules or procedure transitions;
- observation/action fields, sizes, offsets, enum numerics, or projection;
- BBS or BBP format changes;
- training, corpus generation/relabeling, checkpoint promotion, or launch.

The carry-channel nested case proposed during the initial audit is deliberately
translated into an ordinary admitted held-ball team-turn boundary. The live
validator rejects a pending-Dodge record whose mover is the carrier
(`bb_state_bank_dodge_reroll_valid`, `engine/src/bb_match.c`). Altering that
admission contract merely to manufacture a test would conflate two independent
changes.

## Watched-fail tests before production edits

All new behavior tests belong in `puffer/bloodbowl/test_state_bank.c`, where
the reset/restoration trust boundary is already tested. They must use the real
BBS writer/loader globals, `c_reset`, Puffer's action encoding, and `c_step`;
`setup_state_bank_env()` is insufficient because it directly copies a match
and skips the defective reset path.

At least the numeric oracles below must be fixture-derived literals. Tests must
not compute expected rewards by calling `bbe_potential`, `bbe_dist_fetch`, or
`bbe_dist_carry`, because a shared production defect could move result and
oracle together.

### 1. Nested loose-ball first transition

Construct an admitted pending-Dodge team-reroll record:

- Home mover starts at `(10, 7)`;
- `pending_dodge_reroll_match()` first creates its existing destination
  `(10, 6)`, then the test mutates the pending MOVE frame's `x` to `11`;
- the resulting pending successful destination is `(11, 6)`;
- an Away marker makes the original Dodge test necessary;
- after the pending state exists, the test places the loose ball at `(13, 7)`;
- `bb_state_bank_dodge_reroll_valid()` and
  `bb_state_bank_resumable_valid()` are asserted after both mutations and
  before the record is written;
- the loader is asserted to retain exactly one record before `c_reset`;
- the one-record bank is selected with `demo_reset_pct = 1`;
- `reward_dist_ball = 0.05`;
- every unrelated reward coefficient is explicitly zero;
- `reward_dist_pbrs_gamma = 0.995`;
- `reward_configured = 1`, so standalone defaults cannot add objective terms;
- the post-reset game RNG is replaced with one scripted successful reroll die,
  solely to make the first policy transition deterministic.

Assert before the action:

- `bbe_state_bank_n == 1` after loading;
- `demo_started == 1` after reset;
- the reset `env.match` is byte-identical to the admitted nested record, so
  watched failures cannot be loader/fallback failures;
- Home fetch distance is three by independently checking fixture coordinates;
- `pot_fetch_prev[HOME] == 1.10`;
- both carry histories are finite zero;
- no reset reward/component has been emitted.

Encode `USE_REROLL / TEAM` for the deciding agent and call `c_step`. Assert:

- the mover finishes at `(11, 6)`;
- Home's new fetch distance is two;
- Home's literal distance-ball component and total reward are `+0.04425`;
- Home history becomes `1.15`;
- Away remains at distance three, with literal `Phi(s0) == Phi(s1) == 1.10`,
  and receives only literal `-0.0055`;
- no unrelated reward component co-fires;
- total output reward, `ep_return`, and the component ledger reconcile with
  zero residual.

Against the base implementation, the reset-history assertion must fail as
`NAN`, and the first Home component must fail as approximately `-0.00575`.

### 2. Held-ball boundary carry baseline

Restore a normal team-turn boundary with a Home carrier at a fixed coordinate.
Use `reward_dist_endzone = 0.04`, exact gamma `0.995`, and zero every unrelated
coefficient. Set `reward_configured = 1`.

For a carrier at `x = 8` and Home endzone `x = 25`, independently pin:

```text
distance = 17
Phi(s0)  = 0.04 * (25 - 17) = 0.32
```

Assert immediately after `c_reset`:

- Home carry history is literal `0.32`;
- Away carry and both fetch histories are finite zero;
- the restored possessor remains Home;
- no reset reward was emitted.

Take a legal activation that does not move the ball. Assert the exact first
carry component is literal `-0.0016`, i.e. `(0.995 - 1) * 0.32`, not zero and
not a re-anchored value. Pin the same literal in total output reward and
`ep_return`, and assert zero component residual. This covers the carry channel
without widening nested state admission.

### 3. Loose-ball team-turn boundary and both team views

Start from `valid_bank_match()`: Home stands at `(8, 7)`, Away at `(17, 7)`.
Place the loose ball at `(11, 7)`, set `reward_dist_ball = 0.05`, exact gamma
`0.995`, `reward_configured = 1`, and zero every unrelated coefficient.
Independently pin:

```text
Home distance = 3 -> Phi(s0) = 1.10 -> no-motion reward = -0.0055
Away distance = 6 -> Phi(s0) = 0.95 -> no-motion reward = -0.00475
```

Assert both teams' fetch histories equal those literal values immediately after
reset. Take a ball-preserving legal Home activation and assert that each team
receives its own literal discounted no-motion term in the component, total
output reward, and `ep_return`, with zero component residual.

This prevents an implementation that initializes only the active team.

### 4. Exact inactive/zero controls

Restore an admitted off-pitch-ball team-turn boundary with exact gamma enabled.
Assert all four histories are finite `0.0`, not `NAN`, both with:

- nonzero distance coefficients whose regimes are inactive; and
- zero coefficients.

This pins total-potential semantics at reset without depending on procgen's
kickoff shape.

### 5. Fresh procgen control

With `demo_reset_pct = 0`, a fixed seed, exact gamma, nonzero fetch/carry
coefficients, and `reward_configured = 1`, call the real `c_reset`. Assert:

- `demo_started == 0`;
- the first procgen policy state has the expected off-pitch ball;
- all four histories are finite zero;
- all rewards, terminals, and reward-component scratch remain zero.

This is deliberately separate from the restored off-pitch record. It proves the
implementation is not accidentally nested under the bank-selection branch.

### 6. Legacy compatibility control

Restore a nonzero loose-ball boundary with `reward_dist_pbrs_gamma = 0`.
Set `reward_configured = 1`.
Assert:

- all histories are `NAN` immediately after `c_reset`;
- the first unchanged legal activation emits no distance component;
- the legacy fetch history becomes the historical raw value `-k * distance`;
- carry remains `NAN` while inactive.

The base should already pass this control. It must remain byte-for-byte green
after the exact-path fix.

### 7. Reset isolation

Using one environment:

1. load/reset from the loose-ball bank and assert its exact histories;
2. replace the process-local test bank with a one-record held-ball bank;
3. call `c_reset` again;
4. assert histories now equal only the held-ball `s0` values, with the prior
   fetch values cleared to finite zero.

Also set the first episode's histories to impossible finite sentinels before
the second reset so accidental carry-over cannot pass by coincidence. This
directly exercises the same `bbe_reset_match()` that autoreset calls. Assert
the resulting `env.match` is byte-identical to the second one-record bank so a
process-global loader error cannot masquerade as a history error.

### 8. Real terminal/autoreset ordering

Reuse the admitted nested loose-ball record from case 1 with exact gamma and
`max_decisions = 1`. The successful reroll moves Home's potential from `1.10`
to `1.15`, so the first ordinary shaping term would be `+0.04425`. The
truncation terminal must then remove `gamma * 1.15`, producing the old episode's
literal terminal payback:

```text
+0.04425 - 0.995 * 1.15 = -1.10
```

After the same `c_step`, assert:

- both `terminal_ptr` values are `1.0`;
- Home's returned `reward_ptr` remains literal `-1.10` despite autoreset;
- the durable log's distance-ball component and episode return record the old
  episode's literal `-1.10` payback;
- the environment has already reset to the banked pending state;
- the new episode's Home fetch history is finite literal `1.10`, not the old
  episode's `1.15`;
- new-episode reward-component scratch and episode return are zero even though
  the terminal output pointers still expose the completed episode.

This distinguishes terminal consumption of old `Phi(s1)` from initialization
of new `Phi(s0)` and pins the intended output-preservation semantics.

### 9. Exact-history invariant is loud

Start a supported exact-PBRS episode through `c_reset`, then deliberately
corrupt one exact history to `NAN` before a potential-producing legal action.
Run the action in a child process and assert it terminates with `SIGABRT`.
Against the base implementation the child completes through the silent
`Phi(s1)` re-anchor, so this is also a watched failure.

The legacy control must demonstrate that `NAN` remains valid when
`reward_dist_pbrs_gamma <= 0`; the fail-fast check is exact-path only.

### Watched-fail acceptance

Before touching production code:

- compile the state-bank test binary from the exact base;
- run the new `restored_pbrs` filter;
- record the exact failure count and representative values;
- confirm the legacy control is already green;
- confirm failures are reset-baseline/reward assertions rather than malformed
  state-bank fixtures, illegal policy tuples, RNG exhaustion, or unrelated
  reward defaults.

Only after that evidence is recorded may production code change.

## Watched-fail evidence

Captured against the exact base with only this plan and
`test_state_bank.c` changed:

- the test binary compiled cleanly under the optimized `-Wall -Wextra -Werror`
  target;
- the `restored_pbrs` filter ran 9 tests and produced 53 expected assertions;
- `restored_pbrs_legacy_reset_preserves_nan_priming` was green on the base;
- every one-record bank loaded and the post-reset identity/admission assertions
  passed;
- the nested reroll consumed the one scripted die and reached `(11, 6)`;
- the nested reset histories were `NAN`, and Home emitted
  `-0.00574999442` rather than literal `+0.04425`;
- the terminal/autoreset case returned/logged `-1.14999998` rather than
  literal `-1.10`, then installed `NAN` rather than the new finite `1.10/0`
  histories;
- the corrupted exact-history child exited normally, so the expected
  `SIGABRT` assertion failed;
- the procgen, inactive, held, loose, repeated-reset, and both-team failures
  were all potential-history/value assertions, not malformed fixtures, policy
  projection failures, RNG exhaustion, or unrelated reward defaults.

Focused reruns recorded:

```text
restored_pbrs_nested_loose_first_transition_uses_s0:
  1 test, 7 expected failures
restored_pbrs_terminal_autoreset_consumes_old_history:
  1 test, 7 expected failures
restored_pbrs_legacy_reset_preserves_nan_priming:
  1 test, 0 failures
```

## Implementation hypothesis

Introduce one small reset helper adjacent to the distance/potential helpers or
the reset lifecycle:

```text
if exact gamma:
    for each team:
        fetch_prev = Phi(reward_dist_ball, dist_fetch(current_match, team))
        carry_prev = Phi(reward_dist_endzone, dist_carry(current_match, team))
else:
    all histories = NAN
```

Call it exactly once in `bbe_reset_match()` after the current match has been
fully selected/advanced to its initial decision and before control returns to
the policy. Replace the obsolete comment that says all potentials always start
inactive with the exact/legacy contract.

Do not branch on `demo_started`. Do not emit reward during reset. Do not mutate
the match. Do not add cached state to `bb_match`.

Remove the exact-path `isnan(prev) ? Phi(s1) : prev` re-anchor. Immediately
before exact-PBRS arithmetic, require all histories consumed by that path to be
finite; report the channel/team and abort if the invariant is broken. Then use
the stored histories directly. This makes a future reset regression loud
instead of silently recreating the same reward corruption.

Audit every manual exact-PBRS `c_step` fixture. A fixture that intentionally
skips `c_reset` must explicitly initialize its total histories from its
constructed state before stepping. Static scalar/envelope tests and direct
`bbe_finish_episode()` arithmetic tests do not traverse this invariant and
need no artificial lifecycle setup. Legacy `gamma <= 0` retains `NAN` and
never enters the exact check.

## Lineage and version analysis

Expected version decision: no numeric ABI or corpus-format bump.

- Engine transition state is unchanged.
- `bb_match`, BBS header/records, and the state-bank fingerprint are unchanged.
- Observation bytes, meanings, dimensions, and `BBE_OBS_VERSION` are
  unchanged.
- Action masks/projection and `BBE_MASK_SIZE` are unchanged.
- BBP v6 records contain observation, mask, and exact action target data, not
  environment reward output; the writer's tuple therefore remains
  `v6/2782/454`.

However, the reward behavior and environment source identity do change.
Installed source/module hashes must change and be recorded. Any training
checkpoint using exact PBRS must be treated as belonging to the new source
identity. No old checkpoint or BBP shard may be relabelled.

The deterministic default FNV is expected to remain the D236 value
`ea1d720e69f5a491`, because the standard smoke has curriculum and distance
rewards disabled. Equality is a valid negative control here; any movement
requires investigation. The exact-PBRS state-bank regressions, rather than the
default smoke, prove that the corrected path is reached.

## Required implementation review sequence

1. Adversarial subagent reviews this plan before watched-fail tests or
   production edits.
2. Revise the plan to resolve every P0/P1 finding; obtain explicit approval.
3. Add tests only and capture watched-fail evidence.
4. Implement the smallest reset-baseline change.
5. Run focused optimized and sanitizer tests.
6. Self-review the complete diff for semantics, test independence, scope, and
   versioning.
7. Independent adversarial subagent reviews the implemented diff and evidence.
8. Resolve every P0/P1 and rerun affected gates.
9. Kimi CLI review is waived by the user for this and subsequent items.
10. Create a clean local checkpoint only after all mandatory gates are green.

No push, PR, merge, training launch, or corpus mutation is authorized.

## Validation gates

Focused:

- new `restored_pbrs` state-bank filter;
- exact-history fail-fast child-process case;
- complete `puffer/bloodbowl/test_state_bank.c`;
- focused existing exact-PBRS and terminal-payback reward filters;
- complete Puffer reward suite.

Repository:

- complete optimized `make test`;
- complete ASan/UBSan `make asan`;
- BBP v6 writer and current/historical lineage tests;
- state-bank producer/consumer and authored identity tests;
- generated-source/manifests consistency checks;
- shell syntax checks for touched or provenance-sensitive scripts;
- `git diff --check`;
- no unexpected tracked or untracked build products.

Installed environment:

- clean install against the repository's pinned PufferLib commit;
- install/check reports `obs-v6/6`, `exact-joint-v1`, CPU/fp32;
- standalone module builds and imports;
- environment/exact-action/module/standalone hashes recorded;
- deterministic seed-42, 100-episode FNV run repeated twice;
- zero illegal actions;
- FNV equals D236 unless a separately explained default-path effect is found.

## Acceptance criteria

This item is complete only when:

- a real restored nested loose-ball first transition emits literal
  `+0.04425`, not `-0.00575`;
- exact fetch and carry histories equal the actual restored `Phi(s0)` before
  the first action;
- both teams and inactive channels are initialized;
- reset emits no reward;
- the procgen path initializes the same invariant;
- repeated resets recompute from the new state;
- terminal composition publishes the old episode's literal payback before
  installing the new finite `s0` history, without clearing terminal outputs;
- corrupted exact history aborts instead of silently re-anchoring;
- legacy gamma-zero tests remain unchanged;
- no engine, observation, mask, BBS, or BBP version changes are introduced;
- optimized, sanitizer, lineage, install, import, and deterministic gates pass;
- self-review and independent implementation review have no unresolved P0/P1;
- evidence and the new chronological decision entry match the final committed
  tree.

## Implementation and evidence

The production change is deliberately narrow:

- `bbe_reset_potential_history()` now derives both teams' fetch and carry
  histories from the fully constructed first policy-visible match when exact
  PBRS is active, and preserves historical `NAN` priming for the legacy form;
- `bbe_reset_match()` invokes that helper after state-bank/procgen selection,
  in-match RNG seeding, `bb_advance()`, and legal-action refresh;
- the exact step path no longer substitutes `Phi(s1)` for a missing history;
  it requires both stored channel histories to be finite and aborts loudly if
  the lifecycle invariant has been bypassed or corrupted;
- comments now distinguish exact total-potential history from the legacy
  inactive/unprimed sentinel contract.

Ten real reset/step regressions cover the nested restored transition, mirrored
Home and Away carry boundaries, loose-ball views for both teams, inactive and
zero channels, fresh procgen, zero and negative-gamma legacy compatibility,
repeated reset, terminal/autoreset ordering, and the fail-fast invariant. The
key independently pinned result moved from the watched failure
`-0.00574999442` to literal `+0.04425`; the terminal/autoreset case moved from
`-1.14999998` with a new `NAN` history to literal `-1.10` with the next episode
re-baselined at literal `1.10`.

The first independent implementation review found one P1 in the tests:
`c_reset`/`c_step` attach the engine's thread-local stalling telemetry sink to
the environment, so a stack fixture could leave that pointer dangling after a
test. The common bank cleanup plus the procgen and reset-isolation custom
teardowns now call `bb_stall_attach(0)` before their fixtures leave scope.
After that repair, the complete optimized state-bank binary passes 21/21 and
the complete ASan/UBSan state-bank binary passes 21/21, including every
authored-record case that follows the new fixtures.

A second independent oracle audit found that the original evidence proved
nonzero carry initialization only for Home and that off-pitch zero expectations
could accidentally inherit `memset` zeroes. The final matrix adds an admitted
Away-active/Away-carrier boundary at `x=17`, passes its projected action through
real `c_step`, and pins literal Away `Phi(s0)=0.32` and reward `-0.0016`.
Restored off-pitch and procgen cases poison all four histories with mixed
`NAN`/impossible finite values before reset, and restored cases pin
`demo_started` plus byte identity. A negative-gamma reset and step additionally
pin the documented `gamma <= 0` legacy branch. After those corrections, both
reviewers returned explicit APPROVE with no unresolved P0/P1; independently
rerun focused and complete state-bank results are 10/10 and 22/22 under both
optimized and ASan/UBSan builds.

One nonblocking P2 remains deliberately outside this bounded item: the
defensive `BB_STATUS_ERROR` / empty-legal-set terminal path skips the ordinary
potential transition, so its existing terminal reconstruction can forgive a
nonfinite history and would use `-gamma*Phi(s0)` rather than `-Phi(s0)`. That
path is declared unreachable and is not a supported bank, procgen, vectorized,
natural-terminal, or truncation lifecycle; it should be hardened as a separate
test-first item rather than hidden in this checkpoint.

Final repository validation is green: optimized and ASan/UBSan each pass 476
engine, 64 Puffer reward, 2 contact-bot, 22 state-bank, 26 observation, and
numeric BBP-v6 writer tests; the replay/reward/tool suite passes 205 tests with
2 expected dependency skips; the CI-equivalent BC/lineage/producer suite passes
90 tests; and code generation, all reward manifests, shell syntax, and
`git diff --check` pass.

The runtime/test/plan checkpoint is
`ac3c4fecbf664774a5d8b471b5a2fb352ab45bc5`. A clean install into PufferLib
commit `9836f0d2e78889c1aaf189c04d161b6fc61a9386`, followed by a from-scratch
CPU build and installer drift check, records:

- environment source SHA-256
  `2f1b9ebab1ee42d8dfe96b157a0feb2ae7df50467e38660a74ae94cf11fdd61c`;
- unchanged exact-action source SHA-256
  `1414c9041d1942bdd049eb257338c3a2df3cf72240015e58e5eab095ff691ca7`;
- imported CPU/fp32 module SHA-256
  `7a8a46e96d28251438058270107c93e467324c9bd9d47a16a576b9900b370aee`;
- standalone SHA-256
  `2daf6a2e67cd9dc0c7f2dba35393bc5e9bef4bc5656e9f2d95f6d21f5fdfbb66`;
- advertised `bloodbowl`, CPU, fp32, `obs-v6/6`, and `exact-joint-v1`.

The seed-42, 100-episode deterministic smoke repeats byte-identically as
`ea1d720e69f5a491`, with 26,251 steps and `illegal_frac 0.0000`. Equality with
D236 is the expected negative control: the smoke has bank curriculum and
distance shaping disabled. The real restored-state exact-PBRS regressions are
the positive proof that the changed source path executes.

Kimi CLI review is omitted under the user's explicit waiver. No push, PR,
merge, training launch, corpus mutation, observation/record version bump, or
historical relabelling occurred. D237 records the final chronological decision
and evidence.
