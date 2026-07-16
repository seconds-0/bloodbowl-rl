---
name: bb-validation
description: Validate Blood Bowl engine and environment changes with BB2025 spec tests, sanitizers, deterministic/property checks, golden traces, statistical oracles, strict-edition FUMBBL differentials, reward-semantic regressions, and experiment-integrity tests. Use when changing rules/rewards/counters, triaging replay divergences, updating goldens, extracting oracle odds, or setting up FFB/Jervis headless.
---

# bb-validation — 7-layer engine validation

Validation is part of the product: rule/reward semantics must be correct before a
training curve can be interpreted. Everything routes through `bb_rng` dice
injection: seeded PCG-64 or a recorded dice script. That design makes statistical,
golden, and replay-differential checks possible.

**Current status:** `make test` and `make asan` are the authoritative local
suite inventories; use the counts printed by the exact head under review rather
than copying a historical total into a new decision. Hosted CI remains
authoritative for the Torch-dependent BC tests.
This does not mean all seven originally planned layers are
complete. `[BUILT]` is runnable now, `[PARTIAL]` has useful coverage with known
gaps, `[ORACLE]` is external reference code, and `[PLANNED]` is not implemented.

## The 7 layers at a glance

| # | Layer | Oracle | Cadence | Status |
|---|-------|--------|---------|--------|
| 1 | Rulebook spec unit tests | current BB2025 mirror/FAQ + focused C tests | every change | BUILT, incomplete ruleset breadth |
| 2 | Statistical dice conformance | exact math + BloodBowlActionCalculator | targeted/nightly | PARTIAL (oracle built) |
| 3 | Property/metamorphic invariants | internal consistency + deterministic FNV | every engine/env change | PARTIAL |
| 4 | fuzzing + ASan/UBSan | crash/UB freedom | every change + long runs | BUILT sanitizer suite; fuzz depth partial |
| 5 | Golden-trace regression | frozen known-good traces | explicit | PARTIAL |
| 6 | Rule-coverage gate | coverage + rule-path registry | release gate | PLANNED/PARTIAL |
| 7 | FUMBBL replay differential | strict BB2025 real games + FFB/Jervis | corpus conversion | PARTIAL, prefix-censored |

---

## Layer 1 — Rulebook spec unit tests

**Validates:** every rule clause as an isolated test: block dice selection, armour/injury
modifier stacks, skill triggers, push chains, passing ranges, turnover causes.
**Rule authority:** current BB2025 mirror under
`docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/`, including the inline May
2026 FAQ/errata. The November 2025 GW PDF is an older subset. FFB/Jervis are
behavioral and triangulation oracles, not authority over current rule text.
Cross-check disputed mechanics against the two reference engines' own suites:

- FFB (primary oracle, the engine FUMBBL runs): `cd vendor/ffb && mvn test`
  (JUnit 5; single test: `mvn test -Dtest=InjuryTypeBlockBB2025Test`). Only ~12 test
  files — FFB is weakly unit-tested; treat it as a behavioral oracle, not a spec suite.
- Jervis (secondary): `cd vendor/jervis-ffb && ./gradlew :modules:jervis-engine:jvmTest`
  — ~174 test files with **parallel bb2020/ and bb2025/ suites**
  (`modules/jervis-engine/src/commonTest/kotlin/com/jervisffb/test/bb2025/` —
  `TurnOverTests.kt`, `ApothecaryTests.kt`, `KickOffTests.kt`, `ScatterTests.kt`, …).
  Diff bb2020 vs bb2025 versions of the same test file to see exactly what the
  edition changed. Needs Java 21; first build generates code, so initial errors are normal.
- botbowl (BB2016 sanity, edition-invariant only): `cd vendor/botbowl && pytest tests/`
  — `tests/game/test_block.py`, `test_armor.py`, `test_dodge.py`, `test_pass.py`, etc.
  Its `D6.fix(value)` queue pattern (`tests/game/test_dice.py`) is prior art for our
  dice-script injection.

**Ours:** `engine/tests/` contains focused C procedure/rule tests with forced dice;
expand it for every semantic change and every reproduced defect. **Failure looks like:** assertion with forced dice +
expected state. **Triage:** check rules cache first, then how FFB resolves it
(`vendor/ffb/ffb-server/.../server/step/` Step classes), then Jervis. If FFB and
the current rulebook disagree, implement the rulebook for the BB2025 engine,
record the FFB divergence, and prevent incompatible replay prefixes from silently
becoming training truth.

## Layer 2 — Statistical dice conformance

**Validates:** empirical outcome frequencies of every compound roll path (dodge w/
re-roll, 2D block w/ Brawler, armour+MB+Claw, …) against exact probabilities.
**Oracle:** `vendor/BloodBowlActionCalculator/` (C#) — exact-probability engine with
**281 `[InlineData]` rows** in `ActionCalculator.Tests/ActionCalculatorTests.cs`
encoding (notation, rerolls, expected p per re-roll budget), e.g.
`[InlineData("CL,MB:2D3,K8,J8", 0, 0.18229)]` = Claw+Mighty Blow, 2D block needing 3+,
armour 8+, injury 8+. Notation grammar is documented in the repo's `CLAUDE.md`.
**Season toggle:** `ActionCalculator.Models/Season.cs` (`Season2`/`Season3`);
`Calculation.cs` defaults to `Season.Season3` — which IS BB2025 (Third Season) — and
notation suffix `~S2` selects old behavior. Season only affects Pro/Consummate Pro and
The Ballista, so nearly all rows are valid BB2025 oracle values as-is.

**Extracting odds:** run `dotnet test ActionCalculator.Tests` to verify the oracle,
then parse the InlineData rows into `validation/fixtures/calculator_odds.json`
(notation → scenario mapping table lives in `reference/oracles.md`). For scenarios not
in the 281 rows, drive `ICalculator` via a tiny C# console harness (DI setup is the
first 20 lines of `ActionCalculatorTests.cs`).

**Ours (planned):** `validation/dice_conformance` — Monte-Carlo each scenario with
PCG-64, chi-square against exact odds, ≥10k rolls per outcome cell. **Failure looks
like:** cell with p<0.05 after confirm re-run. **Triage:** (a) wrong modifier stack —
re-derive by hand; (b) RNG misuse (reuse/bias) — check `bb_rng` consumption counts;
(c) oracle wrong (rare) — confirm vs closed-form. See **Statistical power** below.

## Layer 3 — Property/metamorphic invariants

**Validates:** ~15–20 invariants over 10k+ random-action traces with auto-shrink
(custom C harness — the Theft library is abandoned, do not depend on it).
**Invariant catalog** (the canonical list; add here as new ones land):

1. **Ball conservation** — exactly one ball; carrier slot ↔ grid back-pointer consistent.
2. **Player conservation** — 16/team across pitch + dogout boxes (Reserves/KO/CAS/sent-off);
   pitch-grid ↔ player-slot bijection (no dupes, no orphans).
3. **Turn alternation** — turn counters monotonic; active team alternates except
   rule-defined exceptions (Blitz!/riot kickoff events, touchdown turn handling).
4. **Turnover causality** — turnover flag set only by an enumerated cause (failed
   dodge/rush/pickup, carrier KD, failed pass chain, sent-off, …) and always ends activation.
5. **Re-roll conservation** — team re-rolls never increase mid-half except
   enumerated one-drive/Leader gains; BB2025 permits multiple team re-rolls in
   one turn, but each die or dice pool may be re-rolled at most once.
6. **Mask-soundness** — `step()` accepts action ⟺ bit set in legal mask. Metamorphic
   half: sampled masked-out actions are rejected *without state mutation* (memcmp).
7. **Dice-script conformance** — injected script consumed exactly; over/under-read = bug.
8. **Determinism** — same seed + action trace ⇒ identical state hash. The
   binding-level harness for this is the standalone's `--fnv` mode
   (`puffer/bloodbowl/bloodbowl.c`): from repo root,
   `bash tools/install_puffer_env.sh && cd vendor/PufferLib &&
   ./build.sh bloodbowl --fast && ./bloodbowl --fnv --seed 42 100` — folds
   obs, action masks, legal-action buffers, and sampled actions into one
   FNV-1a hash. The install step is mandatory (build.sh compiles the
   installed snapshot, not puffer/) and the run must happen from
   vendor/PufferLib with the same seed/episode count both times (the state
   bank resolves cwd-relative; a missing bank silently changes the hash).
   Run before AND after every env change: intended-no-op refactor ⇒
   identical hash; intended obs/mask change ⇒ hash changes and nothing
   else does. Full liturgy: puffer-env-dev skill, footgun 14.
9. **Procedure-stack sanity** — bounded depth; empty between activations; no leaks.
10. **Stat bounds** — MA/ST/AG/PA/AV within rulebook ranges; score monotonic.
11. **Raw snapshot admission** — BBS1 size/fingerprint proves ABI compatibility,
    not safe content. Scenario scanners use `bb_state_bank_boundary_valid`.
    Authored writers use that boundary for F1/F2/F3/F5 and may use
    `bb_state_bank_resumable_valid` only for the exact F4 pending-Dodge recipe;
    production reset admission and continuation also use the resumable gate.
    The resumable union is intentionally
    limited to the exact fresh-turn shape and the exact failed first-step,
    non-Rush Dodge TEST reroll stack. The latter requires remaining ordinary
    MA, rejects movement-prohibiting or activation-cleared flags, and exposes
    its parent MOVE destination egocentrically in observation context bytes
    9/12. A resolved Rush retains nonzero `match.ret` provenance and is not the
    same admitted shape. Every new nested shape needs complete lower-frame,
    index, observation-alias, legal-mask, both-branch continuation,
    loader-byte, deterministic-writer, mixed-batch preflight, and malformed-
    record tests before widening the shared gate. For authored nested captures,
    also prove that the transcript ends before the pending choice and outcome so
    no continuation action becomes an implicit label.
12. **Authored axis quotas** — bind every requested axis cell inside the recipe
    and independently rediscover it; never accept a test-only or out-of-band
    cell label. For the exact F3 half-two turn axis, require one fresh-boundary
    record for turns 1-8 under each active-side orientation (`BB_HOME` and
    `BB_AWAY`), exactly 16 total. Do not size an orientation axis with
    `BB_TEAM_COUNT`, which is the 30-entry roster catalogue. Reject axis fields
    on non-axis recipes. Treat the quota validator as structural coverage only:
    the authored writer must still preflight full provenance, byte-exact replay,
    raw-snapshot admission, and one-action continuation before byte zero.
    For the exact F2 Hand-off target-count axis, require one fresh-boundary
    record for each Home/Away active-side orientation crossed with exactly one
    or two-or-more legal catch-capable targets, exactly four total. Count only
    after full raw-boundary validation and a private legal zero-die
    `ACTIVATE -> DECLARE HAND-OFF` probe; do not count a rules-legal No Ball
    target that cannot attempt the Catch, and do not relabel two-or-more as
    exactly two. Store both side and bucket in the recipe and independently
    rediscover them. This quota proves opportunity structure, not that Hand-off
    or any receiver is a correct policy label.
    For the exact F1 Pass carrier-pressure axis, require one fresh-boundary
    record for each Home/Away active-side orientation crossed with open/marked
    carrier pressure, exactly four total. First run the complete input-preserving
    F1 Pass-opportunity validation; only then classify the validated carrier with
    `bb_is_marked`. Do not infer pressure from raw adjacency, and do not select a
    receiver to define the state bucket. Store side and pressure in the recipe,
    reject pressure on non-axis kinds, and independently rediscover the exact
    cell. This quota proves structural Pass-opportunity context only, never that
    Pass or any receiver/target is tactically correct.
13. **Authored proof-bundle composition** — accept exactly 26 supported proof
    recipes: complete F1/F2/F3 axes (4/4/16) plus one exact F4 and one exact F5.
    Partition only by exact recipe kind so overlapping state facts cannot double
    count a record; accept arbitrary input order. Reuse the typed family quota
    validators and exact opportunity predicates after complete configuration
    validation. This is a structural proof bundle, not a balanced/canonical
    bank and not publication or training authorization. Every serialized batch
    still goes through independent writer rediscovery, exact replay, raw-state
    admission, and one-action continuation. Sidecars, splits, reports,
    manifest-last publication, staging, and training remain separate gates.
14. **Authored proof-bundle construction** — use
    `ad_build_authored_proof_bundle` rather than duplicating the fixed base
    configuration, cell seeds, or order. Require exact capacities for both
    caller-owned arrays, no caller-output write on failure, checked temporary
    staging, complete composition validation before commit, and record pointers
    rebound to their caller recipes. Preserve the proof-local positional
    `0xA9000000 + index` metadata only for byte compatibility. It is not a
    durable recipe/template/version/variant identity or sidecar join key.
15. **Authored identity and sidecar boundary** — schema 1's closed immutable
    registry allocates only `0xAE000001..0xAE00001A` for the fixed 26 proofs;
    resolve those identities through the public mapper and never decode AE bits
    or use positional A9 values as durable identity. The first metadata design
    is `docs/plans/authored-sidecar-schema.md`: paired canonical 26-line record
    and recipe streams must reconcile A9 order, AE identity, record pointers,
    decision indices, complete rediscovery/replay, safe boundary validation,
    and one-action continuation before byte zero. The future serializer must
    call the unchanged public BBS writer exactly once through
    serializer-owned memory-backed `FILE *` storage, compare and discard its
    frozen bytes, and must not refactor D209's immutable writer into a new
    preflight API. Hash actions together with
    decision teams, hash dice sides together with faces, and domain-separate
    sorted legal actions. No action, receiver, or target selected or recommended
    at or after capture, nor any separate receiver/target, reward, regret,
    outcome, value, split, curriculum-weight, or policy label may enter either
    schema. Pre-capture packed actions stop before capture, may retain historical
    action arguments/receivers/targets, remain replay provenance only, and are
    forbidden as BC/policy/receiver-target supervision.
    The design itself authorizes no serializer, file I/O, manifest, bank,
    consumer, training, evaluation, BBTV, or deployment. Do not extend D209's
    immutable authority files: add a sidecar-only authority in a serializer-free
    bootstrap PR, then implement only after its workflow is trusted on the
    base. Non-F5 rows use false/false for the two F5 facts; the fixed F5 row
    must independently prove true/true. Both complete streams stage in
    serializer-owned checked storage before the two final non-failing
    caller-output copies. Before implementation, the serializer-free authority
    bootstrap freezes the complete future ABI, memory-stream length/NUL and BBS
    oracle contract, malicious candidates, and D210 isolation; its protected
    workflow handles exact-SHA `pull_request_target`, `merge_group`, and main
    push.
    The implemented bootstrap authority is `tools/authored_sidecar.h`,
    `tools/authored_sidecar_oracle.json`,
    `tools/authored_sidecar_authority/`, and
    `.github/workflows/authored-sidecar-authority.yml`. Run
    `make authored-sidecar-authority-verify`. Those bytes become immutable on
    merge; the bootstrap must have no `tools/authored_sidecar.c`, and the later
    serializer may add only that owned source without changing the frozen
    ABI/oracles/probes/fixtures/verifiers/workflow. Its public paired lengths
    are 39,460/119,389 bytes with no output NUL. The trusted fact path binds all
    30 generated team IDs and the complete 58,568-byte BBS writer result before
    independently canonicalizing both 26-line streams.
    Require exact numeric assertions for every schema enum, direct execution of
    the candidate C SHA/action/dice/legal framing helpers on NIST and
    empty/single/multi vectors and every-index A9/AE reconciliation mutations,
    including a fully backed byte-identical recipe outside the supplied
    extent. Require exact caller-recipe pointer provenance and
    serializer-owned writer records. Test candidate-owned same-translation-unit
    helpers directly; linker wrapping cannot intercept their internal calls.
    Bind each family predicate to its admitted row, force both categorical
    directions, and make the F5 helper bind the carrier-selected Activate and
    Declare Move actions while proving zero scripted-die consumption after both
    transitions. Separately count and perturb the captured-match legal-set
    enumeration for every row; family-internal legal queries are not hash
    evidence. An F5-false transform must use the dedicated atomic-rejection mode
    for the mandatory fixed-row fact. That mode must observe a normal serializer
    failure, preserve both outputs, returned lengths, caller inputs, and every
    byte in the allocated guards beyond the declared capacities, verify
    applicable writer/stream cleanup, and exit zero only after those checks.
    Run every transformed F5/hash binary optimized and under ASan/UBSan;
    crashes, aborts, in-guard overwrites, out-of-allocation writes, and
    corrupt-then-error paths reject. Zeroed hash transforms
    must preserve serializer success and
    match exact trusted 52/52/26-field JSONL changes so hard-coded-output and
    rejection-only hash canaries fail. Keep normal builds fully strict; suppress
    only unused parameter/function/variable/const-variable warnings while
    separately compiling the transformed candidate object, never trusted
    probe/engine sources. The seven-role
    alias matrix covers greater-of-supplied/fixed input extents crossed with
    oversized capacities, capacity-only suffixes, short-capacity diagnostic
    aliases, overflow, and both ordered public-success half-open endpoint
    orientations at exact and oversized capacities before any diagnostic write.
    Reject serializer symbols outside the exact owned/authority paths,
    shadowable system-header lookup, conditional-preprocessor decoys, duplicate
    protected definitions, unknown source calls, unapproved functional object
    imports (sanitized builds additionally admit only compiler ASan/UBSan
    runtime namespaces), and
    any serializer-object global export beyond the eight reviewed public helper/
    serializer symbols in optimized and sanitized builds. For every other
    candidate object linked into a probe, audit both build variants against the
    trusted probes' actual platform/compiler imports minus a frozen allowlist of
    intentional candidate APIs. Self-test ordinary, sanitizer-conditional, and
    ELF GNU-unique exports including `memcmp`, `fputc`, wrapper, fortified, and
    runtime names so candidate code cannot interpose on trusted probe behavior;
    then inspect the trusted compiler's active macro-expanded protected bodies
    for forbidden identifiers, actual call ordering, and result use. The pure
    serializer is limited to 64 candidate-visible heap allocations per call.
    Mere lexical call presence is not behavioral proof.

**Failure looks like:** shrunken minimal action trace + seed reproducing the violation.
**Triage:** replay the shrunken trace under a debugger; the violated invariant names
the subsystem (ball ⇒ scatter/catch/push code; conservation ⇒ injury/box transitions).

## Layer 4 — Fuzzing + sanitizers

**Validates:** crash-freedom, UB-freedom, OOB on adversarial action/dice streams.
**Ours:** `make asan` exercises the current test suite under sanitizers;
`engine/tests/fuzz_match.c` provides the fuzz entry surface. Keep the planned
long-lived corpus/minimization work separate from the already-green sanitizer
suite; do not describe ASan success as exhaustive fuzz coverage.
**Prior art:** Jervis ships a fuzzer —
`vendor/jervis-ffb/modules/jervis-engine/src/commonTest/kotlin/com/jervisffb/test/FuzzTester.kt`
(100k seeded random games, `@Ignore`d, run manually; note their perf findings: log
level and action validation dominate runtime; 4–5 ms/game on M3 — our C target is ~µs).
**Triage:** ASan report → minimize with `-minimize_crash=1` → becomes a layer-1 regression test.

## Layer 5 — Golden-trace regression

**Validates:** byte-identical end-to-end behavior on ~500 canonical traces (replay
format: initial state + dice script + action list + per-step state hashes).
**Failure looks like:** first diverging step index + state field diff.
**Update protocol (explicit-approval, UPDATE_GOLDENFILES-style):**

1. A golden diff is a **failure by default** — never auto-regenerate.
2. Inspect the first divergence; classify: intended rule fix vs regression.
3. If intended: re-run with `UPDATE_GOLDENFILES=1` (planned env var) to regenerate
   only the affected traces; commit regenerated traces **in the same commit** as the
   engine change, with the rule justification (rulebook section / FFB behavior) in the
   commit message.
4. Never update goldens in a commit that also "fixes" layer-1 tests by weakening them.

## Layer 6 — Rule-coverage gate

**Validates:** every skill, procedure, and dice path actually exercised by layers 1+3+5,
plus llvm-cov ≥85% branch coverage on `engine/src/`.
**Ours (planned):** `BB_RULE_PATH("dodge.breaktackle.reroll")`-style registry macro
compiled into a table; tests union their hit sets; gate diffs against the full registry.
**Failure looks like:** named un-exercised rule paths (not just cold lines) — that's the
point: a skill that's *implemented* but never *tested* is indistinguishable from broken.
**Triage:** write the missing layer-1 test; coverage gaps after Phase 3 usually mean a
skill hook is registered but unreachable (wiring bug).

## Layer 7 — FUMBBL replay differential (compatibility and data-quality layer)

**Validates:** our engine reproduces real FUMBBL BB2025 games: inject recorded dice +
actions, diff state trajectories turn-by-turn.
Filter candidates by embedded `gameOptions.rulesVersion` before differential or
pair extraction. The audited raw set contains 11,580 BB2025 and 3,767 BB2020
replays; use the strict 9,118-ID non-empty BB2025 allowlist in
`runs/replay-audit-20260713/`. Current converted pairs stop at first divergence and
are sharply opening-censored, so a large pair count is not proof of full-game
lockstep correctness.
**Data:** `GET https://fumbbl.com/api/replay/get/<replayId>/gz` (replayId from
`/api/match/get/<id>`), no auth — throttle ~1 req/s (see `docs/SOURCES.md` and the
`fumbbl-data` skill). Parser prior art: `vendor/fumbbl_replays/src/fumbbl_replays/`
(`fetch_replay.py`, `parse_blockchoice.py`, `parse_dodgeroll.py`, `parse_injury.py`, …)
and Jervis's full command-level adapter
`vendor/jervis-ffb/modules/fumbbl-net/src/commonMain/kotlin/com/jervisffb/fumbbl/net/adapter/FumbblReplayAdapter.kt`.
**Triangulation oracles** for ambiguous divergences: headless FFB (setup below) and
Jervis replay tooling (`modules/replay-analyzer` dumps a FUMBBL replay's commands as
JSON; `modules/fumbbl-cli` `DownloadGame` fetches one game's websocket data — **never
bulk**, its own help text warns it stresses the server).
**Known gaps:** pre-match (inducements/prayers) may be under-captured in replays —
validate post-kickoff or join team API data. FFB itself has bugs; on FFB-vs-rulebook
conflict, triangulate FFB vs Jervis vs rulebook before concluding our engine is wrong.

### Divergence triage taxonomy

Classify every divergence as exactly one of (first diverging field tells you which):

| Class | Symptom | First move |
|-------|---------|------------|
| **Legality bug** | Replay action not in our legal mask (or we allow what FUMBBL refused) | Diff mask-gen vs FFB `server/step/` Step + `SequenceGenerator` logic for that procedure |
| **RNG/dice mismatch** | Our consumed dice count/order ≠ recorded script | Off-by-one in roll count or roll *order*; FFB rolls server-side via `Fortuna` — we never simulate its RNG, only consume recorded results, so this is always a consumption-order bug or a parser bug |
| **State corruption** | Same action+dice, wrong resulting state (position/status/score) | Re-run trace prefix under layer-3 invariants; usually push-chain, box-transition, or ball-scatter code |
| **Skill interaction** | Divergence only in games where skill X meets skill Y | Reproduce as a minimal layer-1 test with forced dice; check stacking/order vs rules cache + Jervis bb2025 tests; record verdict in the quirks ledger |

Every triaged divergence must end as: a layer-1 regression test, a quirks-ledger
entry (FFB deviates from rulebook), or a parser fix — never just "re-ran, passed".

---

## Reward and experiment-semantic validation

Reward changes require more than the seven engine layers:

1. Add focused tests at true turn, possession, turnover, catch, touchdown, and
   episode boundaries. Count a semantic event exactly once.
2. Validate complete reward manifests; explicit zero and missing must not collapse
   to the same fallback path.
3. Exercise full-pitch/sentinel edge cases and reject non-finite potentials.
4. Expose clip/non-finite/error/demo/fallback counters in both train and eval.
5. Require explicit phase, minimum complete games, final cumulative reprint,
   checkpoint hash, and imported-module provenance.
6. Run `tools/test_reward_manifest.py`, `tools/test_experiment_contracts.py`, and
   the screen/transfer analyzer tests before accepting an arm.
7. Validate policy effects with paired seeds and held-out W/D/L plus TD
   for/against. Engine correctness does not establish reward usefulness.

The canonical current semantic audit is
`docs/reward-and-replay-audit-2026-07-09.md`; durable reward findings are
D177–D185, and D186 is the operational post-primary overflow constraint.

---

## FFB headless setup (from `vendor/ffb` sources)

FFB = Java 8 multi-module Maven (`pom.xml`; build order ffb-common → ffb-tools →
ffb-server → ffb-client-logic → ffb-resources → ffb-client; see `vendor/ffb/AGENTS.md`).

1. **Build:** `cd vendor/ffb && mvn clean install -DskipTests`
   (on JDK 21 add `-Pmockito5` if running tests). Shaded server jar:
   `ffb-server/target/FantasyFootballServer.jar` (finalName in `ffb-server/pom.xml`).
2. **Database (required even standalone):** MySQL ≤5.6 or MariaDB ≤10.4 only (per FFB's
   `Readme.md`; the pom actually bundles mysql-connector 5.1.49). Easiest:
   `docker run -d -p 3306:3306 -e MARIADB_ROOT_PASSWORD=ffb -e MARIADB_DATABASE=ffblive mariadb:10.4`
3. **Config:** copy `ffb-server/server.ini` (template) and set `db.url=jdbc:mysql://localhost/ffblive`,
   `db.user`, `db.password`, `db.type=mariadb`, `server.port=22227`, plus real paths for
   `server.log.file`/`server.log.folder`. Fumbbl/admin/backup connector keys can stay
   placeholder in standalone. Use `-override` for env-specific deltas.
4. **Init schema:** `java -jar ffb-server/target/FantasyFootballServer.jar standalone initDb -inifile my-server.ini`
   (`ServerMode.java`: `standalone initDb` → `STANDALONE_INIT_DB`; the single-token
   `standaloneInitDb` form also parses).
5. **Run:** same command without `initDb`. Websocket on `server.port`; game state is
   extractable via the GameState servlet (`gamestate.url.get=gamestate/get?...&gameId=$2&fromDb=$3&includeLog=$4`
   in server.ini — challenge/response auth like admin endpoints, see
   `ffb-server/src/main/java/com/fumbbl/ffb/server/admin/GameStateConnector.java`).
6. **Client (for visual replay inspection):** main class
   `com.fumbbl.ffb.client.FantasyFootballClientAwt` with `-replay -server localhost -port 22227`
   (full arg table in `vendor/ffb/Readme.md`).

Driving FFB headlessly = local teams in `ffb-server/teams/` XML + scripted websocket
client speaking its command protocol (`ffb-common` command classes). Jervis's
`fumbbl-net` module is a working Kotlin implementation of that protocol — crib from it.

## Statistical power (layer 2 sample sizes)

Rules of thumb (α=0.05, power 80%, two-sided; n = (1.96+0.84)²·p(1−p)/δ² per cell):

| Detect | n needed |
|--------|----------|
| 1pp absolute bias on a d6 face (chi-square df=5) | ~11k rolls |
| 1pp absolute on p≈1/2 outcome | ~20k |
| 10% relative error on p=1/36 (e.g. double-skulls) | ~28k |
| 10% relative error on p=1/216 path | ~170k |

So the spec's **≥10k rolls per outcome** ≈ 80% power for 1pp d6-face bias; rare
compound paths need 30k–200k → nightly tier. **Re-run-to-confirm protocol:** a battery
of ~200 cells at p<0.05 yields ~10 false flags/run. On flag: auto re-run that cell with
a fresh seed at 10× samples; fail CI only if the confirm run also rejects (joint
α≈0.0025) — and require the deviation *direction* to match. Persistent same-direction
near-misses across nights = real small bias; investigate even if individually p>0.05.

## CI shape

**PR gate (~30 min):** layers 1, 3 (10k traces), 4 (5-min fuzz, informational), 5,
6 (coverage + rule-path diff), plus lint + a perft-style state-count check.
**Nightly:** layer 2 full battery (incl. 100k+ rare-path cells), layer 4 multi-hour
corpus fuzz, layer 7 replay diff over the current replay set, golden-trace re-verify.
**Weekly:** divergence-rate dashboard; the **training gate** is: all 7 green + ~100%
rule-coverage report + replay divergence rate ≈ 0 on held-out games.

## Reference

- `reference/oracles.md` — per-oracle deep detail: ActionCalculator notation table,
  Jervis module map, FFB internals (Step/SequenceGenerator, Fortuna, replay plumbing),
  botbowl test inventory, odds-extraction recipes.
