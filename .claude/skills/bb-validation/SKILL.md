---
name: bb-validation
description: Validate Blood Bowl engine and environment changes with BB2025 spec tests, sanitizers, deterministic/property invariants, golden traces, statistical dice oracles, strict-edition FUMBBL replay differentials, and reward-semantic regressions. Use when changing rules/rewards/counters, triaging replay divergences, updating goldens, extracting oracle odds, or setting up the FFB/Jervis oracles.
---

# bb-validation — 7-layer engine validation

Validation is part of the product: rule and reward semantics must be correct before a
training curve means anything. Everything routes through `bb_rng` dice injection — seeded
PCG-64 or a recorded dice script — which is what makes statistical, golden, and
replay-differential checks possible.

`make test` and `make asan` are the authoritative local suite inventories; use the counts
printed by the head under review rather than copying a historical total. Hosted CI is
authoritative for the Torch-dependent BC tests. Not all seven planned layers are complete:
`[BUILT]` is runnable now, `[PARTIAL]` has useful coverage with known gaps, `[ORACLE]` is
external reference code, `[PLANNED]` is not implemented.

| # | Layer | Oracle | Cadence | Status |
|---|-------|--------|---------|--------|
| 1 | Rulebook spec unit tests | BB2025 mirror/FAQ + focused C tests | every change | BUILT, incomplete breadth |
| 2 | Statistical dice conformance | exact math + BloodBowlActionCalculator | targeted/nightly | PARTIAL (oracle built) |
| 3 | Property/metamorphic invariants | internal consistency + deterministic FNV | every engine/env change | PARTIAL |
| 4 | Fuzzing + ASan/UBSan | crash/UB freedom | every change + long runs | BUILT sanitizers; fuzz depth partial |
| 5 | Golden-trace regression | frozen known-good traces | explicit | PARTIAL |
| 6 | Rule-coverage gate | coverage + rule-path registry | release gate | PLANNED/PARTIAL |
| 7 | FUMBBL replay differential | strict BB2025 real games + FFB/Jervis | corpus conversion | PARTIAL, prefix-censored |

---

## Layer 1 — Rulebook spec unit tests

**Validates:** every rule clause in isolation — block dice selection, armour/injury modifier
stacks, skill triggers, push chains, passing ranges, turnover causes.

**Rule authority:** the BB2025 mirror under
`docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/`, including the inline May 2026
FAQ/errata. The November 2025 GW PDF is an older subset. FFB and Jervis are behavioral and
triangulation oracles, not authority over current rule text.

- FFB (primary oracle — the engine FUMBBL runs): `cd vendor/ffb && mvn test` (JUnit 5;
  single test `mvn test -Dtest=InjuryTypeBlockBB2025Test`). Only ~12 test files; FFB is
  weakly unit-tested, so treat it as a behavioral oracle, not a spec suite.
- Jervis (secondary): `cd vendor/jervis-ffb && ./gradlew :modules:jervis-engine:jvmTest` —
  ~174 test files with **parallel bb2020/ and bb2025/ suites**
  (`modules/jervis-engine/src/commonTest/kotlin/com/jervisffb/test/bb2025/`:
  `TurnOverTests.kt`, `ApothecaryTests.kt`, `KickOffTests.kt`, `ScatterTests.kt`, …).
  Diffing the bb2020 and bb2025 versions of one test file shows exactly what the edition
  changed. Needs Java 21; the first build generates code, so initial errors are normal.
- botbowl (BB2016, edition-invariant sanity only): `cd vendor/botbowl && pytest tests/`.
  Its `D6.fix(value)` queue pattern (`tests/game/test_dice.py`) is prior art for our
  dice-script injection.

**Ours:** `engine/tests/` holds focused C procedure/rule tests with forced dice. Expand it
for every semantic change and every reproduced defect. **Failure looks like:** an assertion
with forced dice plus expected state. **Triage:** rules cache first, then how FFB resolves
it (`vendor/ffb/ffb-server/.../server/step/` Step classes), then Jervis. If FFB and the
current rulebook disagree, implement the rulebook, record the FFB divergence, and keep the
incompatible replay prefix out of training truth.

## Layer 2 — Statistical dice conformance

**Validates:** empirical outcome frequencies of every compound roll path (dodge with
re-roll, 2D block with Brawler, armour+MB+Claw, …) against exact probabilities.

**Oracle:** `vendor/BloodBowlActionCalculator/` (C#) — exact-probability engine with **281
`[InlineData]` rows** in `ActionCalculator.Tests/ActionCalculatorTests.cs` encoding
(notation, rerolls, expected p per re-roll budget), e.g.
`[InlineData("CL,MB:2D3,K8,J8", 0, 0.18229)]` = Claw+Mighty Blow, 2D block needing 3+,
armour 8+, injury 8+. Notation grammar is in that repo's `CLAUDE.md`.
**Season toggle:** `ActionCalculator.Models/Season.cs`; `Calculation.cs` defaults to
`Season.Season3`, which IS BB2025, and the `~S2` notation suffix selects old behavior.
Season only affects Pro/Consummate Pro and The Ballista, so nearly every row is a valid
BB2025 oracle value as-is.

**Extracting odds:** `dotnet test ActionCalculator.Tests` to verify the oracle, then parse
the InlineData rows into `validation/fixtures/calculator_odds.json` (notation → scenario
mapping in `reference/oracles.md`). For scenarios outside the 281 rows, drive `ICalculator`
from a small C# console harness (the DI setup is the first 20 lines of the test file).

**Ours (planned):** `validation/dice_conformance` — Monte-Carlo each scenario with PCG-64,
chi-square against exact odds, ≥10k rolls per outcome cell. **Failure looks like:** a cell
at p<0.05 after a confirm re-run. **Triage:** (a) wrong modifier stack — re-derive by hand;
(b) RNG misuse (reuse/bias) — check `bb_rng` consumption counts; (c) oracle wrong (rare) —
confirm against closed form. See **Statistical power** below.

## Layer 3 — Property/metamorphic invariants

**Validates:** ~15–20 invariants over 10k+ random-action traces with auto-shrink (custom C
harness — the Theft library is abandoned, do not depend on it).

1. **Ball conservation** — exactly one ball; carrier slot ↔ grid back-pointer consistent.
2. **Player conservation** — 16/team across pitch + dogout boxes (Reserves/KO/CAS/sent-off);
   pitch-grid ↔ player-slot bijection (no dupes, no orphans).
3. **Turn alternation** — turn counters monotonic; active team alternates except rule-defined
   exceptions (Blitz!/riot kickoff events, touchdown turn handling).
4. **Turnover causality** — the turnover flag is set only by an enumerated cause (failed
   dodge/rush/pickup, carrier KD, failed pass chain, sent-off, …) and always ends activation.
5. **Re-roll conservation** — team re-rolls never increase mid-half except enumerated
   one-drive/Leader gains; BB2025 permits multiple team re-rolls in one turn, but each die or
   dice pool may be re-rolled at most once.
6. **Mask soundness** — `step()` accepts an action ⟺ its bit is set in the legal mask.
   Metamorphic half: sampled masked-out actions are rejected *without state mutation*
   (memcmp).
7. **Dice-script conformance** — an injected script is consumed exactly; over- or under-read
   is a bug.
8. **Determinism** — same seed + action trace ⇒ identical state hash. The binding-level
   harness is the standalone's `--fnv` mode (`puffer/bloodbowl/bloodbowl.c`): from repo root,
   `bash tools/install_puffer_env.sh && cd vendor/PufferLib && ./build.sh bloodbowl --fast
   && ./bloodbowl --fnv --seed 42 100`, folding obs, action masks, legal-action buffers, and
   sampled actions into one FNV-1a hash. The install step is mandatory (build.sh compiles the
   installed snapshot) and the run must happen from vendor/PufferLib with the same
   seed/episode count both times (the state bank resolves cwd-relative; a missing bank
   silently changes the hash). Run before AND after every env change: intended-no-op
   refactor ⇒ identical hash; intended obs/mask change ⇒ hash changes and nothing else does.
   The obs-v5 boundary is a pinned example: the 100-episode seed-42 hash intentionally moved
   from v4 `afb3850b011cc9f2` to v5 `b12a03950a1cdd28`, and repeat v5 runs must match. The
   obs-v6 batch is the same shape of change and moves the hash again; re-pin it on the
   first v6 build. Equal 2,782-byte shape does not establish semantic compatibility across
   ANY of v4/v5/v6 — record `BBE_OBS_VERSION` plus imported-module/source identity.
9. **Procedure-stack sanity** — bounded depth; empty between activations; no leaks.
10. **Stat bounds** — MA/ST/AG/PA/AV within rulebook ranges; score monotonic.
11. **Raw snapshot admission** — the BBS1 size/fingerprint proves ABI compatibility, **not
    safe content**, so preserve the loader's bounds, enum, grid/player, and ball-state checks
    for every raw snapshot before it can enter curriculum reset selection. Two gates exist:
    `bb_state_bank_boundary_valid` (fresh `MATCH -> TEAM_TURN` boundary) is what scenario
    scanners and most authored recipes use; `bb_state_bank_resumable_valid` additionally
    admits exactly one nested shape — a failed first-step, non-Rush Dodge reroll window under
    `MATCH -> TEAM_TURN -> ACTIVATION(Move) -> MOVE -> TEST(Dodge)`. The nested validator
    recomputes the target, requires real Use/Decline actions and ordinary MA remaining,
    rejects Rooted/Distracted/Eye Gouged movers, and rejects every other TEST/parent shape.
    A resolved Rush leaves provenance in `match.ret` and is a different shape. The pending
    destination is exposed egocentrically in observation context bytes 9/12 so reset
    observations are transition-complete. Any new nested shape needs lower-frame, index,
    observation-alias, legal-mask, both-branch continuation, loader-byte,
    deterministic-writer, mixed-batch preflight, and malformed-record tests before the shared
    gate widens.
12. **Authored records carry no implicit labels** — the invariant that protects the science.
    An authored capture proves *opportunity structure* (a Pass, Hand-off, or score-now option
    existed), never that the action is correct. So the discovery probe runs privately and is
    not serialized; the transcript ends **before** the pending choice and its outcome, so no
    continuation action can be read back as supervision; and no chosen action, receiver,
    target, reward, outcome, regret, value, split, or curriculum weight is stored. Axis fields
    (side, carrier pressure, target-count bucket, turn) are provenance: bind them in the recipe
    and independently rediscover them, and reject them on non-axis recipes. Size an
    active-side axis with `BB_HOME..BB_AWAY`, never `BB_TEAM_COUNT` (the 30-entry roster
    catalogue). Every record still passes independent rediscovery, byte-exact replay,
    raw-snapshot admission, and the one-action continuation check — which is a resumability
    proof, not an action label.
13. **Scenario scanners are fresh-team-turn-only** — never substitute the broader resumable
    gate where a classifier assumes that boundary. `bank_scenario_scan` and
    `report_scenario_coverage.py` classify overlapping S1–S6 opportunity structures only.

**Failure looks like:** a shrunken minimal action trace plus the seed reproducing the
violation. **Triage:** replay the shrunken trace under a debugger; the violated invariant
names the subsystem (ball ⇒ scatter/catch/push; conservation ⇒ injury/box transitions).

## Layer 4 — Fuzzing + sanitizers

**Validates:** crash-freedom, UB-freedom, OOB on adversarial action/dice streams.
**Ours:** `make asan` runs the current suite under sanitizers; `engine/tests/fuzz_match.c`
is the fuzz entry surface. Keep the planned long-lived corpus/minimization work separate
from the already-green sanitizer suite — ASan success is not exhaustive fuzz coverage.
**Prior art:** Jervis ships a fuzzer
(`modules/jervis-engine/src/commonTest/kotlin/com/jervisffb/test/FuzzTester.kt`, 100k seeded
random games, `@Ignore`d; their perf finding: log level and action validation dominate
runtime, 4–5 ms/game on M3 — our C target is ~µs).
**Triage:** ASan report → minimize with `-minimize_crash=1` → becomes a layer-1 regression
test.

## Layer 5 — Golden-trace regression

**Validates:** byte-identical end-to-end behavior on ~500 canonical traces (initial state +
dice script + action list + per-step state hashes).
**Failure looks like:** the first diverging step index plus a state field diff.
**Update protocol:**

1. A golden diff is a **failure by default** — never auto-regenerate.
2. Inspect the first divergence; classify intended rule fix vs regression.
3. If intended: re-run with `UPDATE_GOLDENFILES=1` (planned env var) to regenerate only the
   affected traces, and commit them **in the same commit** as the engine change with the rule
   justification (rulebook section / FFB behavior) in the message.
4. Never update goldens in a commit that also "fixes" layer-1 tests by weakening them.

## Layer 6 — Rule-coverage gate

**Validates:** every skill, procedure, and dice path actually exercised by layers 1+3+5, plus
llvm-cov ≥85% branch coverage on `engine/src/`.
**Ours (planned):** a `BB_RULE_PATH("dodge.breaktackle.reroll")`-style registry macro compiled
into a table; tests union their hit sets; the gate diffs against the full registry.
**Failure looks like:** named un-exercised rule paths, not just cold lines — that is the
point: a skill that is *implemented* but never *tested* is indistinguishable from broken.
**Triage:** write the missing layer-1 test; post-Phase-3 gaps usually mean a skill hook is
registered but unreachable (a wiring bug).

## Layer 7 — FUMBBL replay differential

**Validates:** that our engine reproduces real FUMBBL BB2025 games — inject recorded dice and
actions, diff state trajectories turn by turn.

Filter candidates by embedded `gameOptions.rulesVersion` **before** any differential or pair
extraction, and use the strict non-empty BB2025 allowlist in `runs/replay-audit-20260713/`
(endpoints, parsers, corpus counts, and throttling live in the `fumbbl-data` skill).
Converted pairs stop at the first divergence and are sharply opening-censored, so a large
pair count is not proof of full-game lockstep correctness.

**Triangulation oracles** for ambiguous divergences: headless FFB (below) and Jervis replay
tooling (`modules/replay-analyzer` dumps a replay's commands as JSON; `modules/fumbbl-cli`
`DownloadGame` fetches one game's websocket data — **never bulk**, its own help text warns it
stresses the server). **Known gaps:** pre-match inducements/prayers may be under-captured, so
validate post-kickoff or join team API data. FFB itself has bugs; on FFB-vs-rulebook conflict,
triangulate FFB vs Jervis vs rulebook before concluding our engine is wrong.

### Divergence triage taxonomy

Classify every divergence as exactly one of these (the first diverging field tells you which):

| Class | Symptom | First move |
|-------|---------|------------|
| **Legality bug** | Replay action not in our legal mask (or we allow what FUMBBL refused) | Diff mask-gen against FFB `server/step/` Step + `SequenceGenerator` for that procedure |
| **RNG/dice mismatch** | Our consumed dice count/order ≠ recorded script | Off-by-one in roll count or order; FFB rolls server-side via `Fortuna` and we only consume recorded results, so this is always a consumption-order or parser bug |
| **State corruption** | Same action+dice, wrong resulting state | Re-run the trace prefix under layer-3 invariants; usually push-chain, box-transition, or ball-scatter code |
| **Skill interaction** | Divergence only where skill X meets skill Y | Reproduce as a minimal layer-1 test with forced dice; check stacking/order against the rules cache + Jervis bb2025 tests; record the verdict in the quirks ledger |

Every triaged divergence must end as a layer-1 regression test, a quirks-ledger entry (FFB
deviates from rulebook), or a parser fix — never "re-ran, passed".

---

## Reward and experiment-semantic validation

Reward changes need more than the seven engine layers. Engine correctness does not establish
reward usefulness — that takes paired seeds and held-out W/D/L plus TD for/against (see
`training-experiments`). What belongs *here* is the test work:

1. Focused tests at true-turn, possession, turnover, catch, touchdown, and episode
   boundaries; count each semantic event exactly once.
2. Manifest tests proving explicit zero and missing do **not** collapse to the same fallback
   path.
3. Full-pitch/sentinel edge cases, and rejection of non-finite potentials.
4. Clip/non-finite/error/demo/fallback counters exposed in both train and eval.
5. `tools/test_reward_manifest.py`, `tools/test_experiment_contracts.py`, and the
   screen/transfer analyzer tests, before accepting an arm.

The current semantic audit is `docs/reward-and-replay-audit-2026-07-09.md`; durable reward
findings are D177–D185.

---

## FFB headless setup (from `vendor/ffb` sources)

FFB = Java 8 multi-module Maven (build order ffb-common → ffb-tools → ffb-server →
ffb-client-logic → ffb-resources → ffb-client; see `vendor/ffb/AGENTS.md`).

1. **Build:** `cd vendor/ffb && mvn clean install -DskipTests` (on JDK 21 add `-Pmockito5`
   if running tests). Shaded server jar: `ffb-server/target/FantasyFootballServer.jar`.
2. **Database (required even standalone):** MySQL ≤5.6 or MariaDB ≤10.4 only (the pom
   bundles mysql-connector 5.1.49). Easiest:
   `docker run -d -p 3306:3306 -e MARIADB_ROOT_PASSWORD=ffb -e MARIADB_DATABASE=ffblive mariadb:10.4`
3. **Config:** copy `ffb-server/server.ini` and set `db.url=jdbc:mysql://localhost/ffblive`,
   `db.user`, `db.password`, `db.type=mariadb`, `server.port=22227`, plus real paths for
   `server.log.file`/`server.log.folder`. Fumbbl/admin/backup connector keys can stay
   placeholder in standalone. Use `-override` for env-specific deltas.
4. **Init schema:**
   `java -jar ffb-server/target/FantasyFootballServer.jar standalone initDb -inifile my-server.ini`
5. **Run:** the same command without `initDb`. Websocket on `server.port`; game state is
   extractable via the GameState servlet (`gamestate.url.get=gamestate/get?...` in
   server.ini — challenge/response auth, see
   `ffb-server/src/main/java/com/fumbbl/ffb/server/admin/GameStateConnector.java`).
6. **Client (visual replay inspection):** `com.fumbbl.ffb.client.FantasyFootballClientAwt`
   with `-replay -server localhost -port 22227` (full arg table in `vendor/ffb/Readme.md`).

Driving FFB headlessly = local teams in `ffb-server/teams/` XML + a scripted websocket client
speaking its command protocol (`ffb-common` command classes). Jervis's `fumbbl-net` module is
a working Kotlin implementation of that protocol — crib from it.

## Statistical power (layer 2 sample sizes)

Rules of thumb (α=0.05, power 80%, two-sided; n = (1.96+0.84)²·p(1−p)/δ² per cell):

| Detect | n needed |
|--------|----------|
| 1pp absolute bias on a d6 face (chi-square df=5) | ~11k rolls |
| 1pp absolute on p≈1/2 outcome | ~20k |
| 10% relative error on p=1/36 (e.g. double skulls) | ~28k |
| 10% relative error on p=1/216 path | ~170k |

So **≥10k rolls per outcome** ≈ 80% power for 1pp d6-face bias; rare compound paths need
30k–200k → nightly tier. **Re-run-to-confirm:** a battery of ~200 cells at p<0.05 yields ~10
false flags per run. On a flag, auto re-run that cell with a fresh seed at 10× samples and
fail only if the confirm run also rejects (joint α≈0.0025) with the deviation *direction*
matching. Persistent same-direction near-misses across nights are a real small bias —
investigate even at p>0.05.

## CI shape

**PR gate (~30 min):** layers 1, 3 (10k traces), 4 (5-min fuzz, informational), 5, 6
(coverage + rule-path diff), plus lint and a perft-style state-count check.
**Nightly:** layer 2 full battery (incl. 100k+ rare-path cells), layer 4 multi-hour corpus
fuzz, layer 7 replay diff over the current replay set, golden-trace re-verify.
**Weekly:** divergence-rate dashboard. The **training gate** is all 7 green + ~100%
rule-coverage report + replay divergence rate ≈ 0 on held-out games.

## Reference

- `reference/oracles.md` — per-oracle detail: ActionCalculator notation table, Jervis module
  map, FFB internals (Step/SequenceGenerator, Fortuna, replay plumbing), botbowl test
  inventory, odds-extraction recipes.
