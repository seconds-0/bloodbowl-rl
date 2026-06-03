# Oracle deep detail (vendor sources, pinned in vendor/PINS.md)

All paths relative to repo root. Re-clone with `tools/vendor_sync.sh`.

## 1. FFB (`vendor/ffb/`) — primary oracle, the engine FUMBBL runs

Java 8, Maven multi-module: `ffb-common`, `ffb-tools`, `ffb-server`,
`ffb-client-logic`, `ffb-resources`, `ffb-client` (build in that order;
`vendor/ffb/AGENTS.md` has build/test commands).

- **Server main:** `ffb-server/src/main/java/com/fumbbl/ffb/server/FantasyFootballServer.java`.
  `_USAGE`: `java -jar FantasyFootballServer.jar standalone [initDb]` / `fumbbl [initDb]`,
  `-inifile <path>` (template: `ffb-server/server.ini`), `-override <path>`.
  Mode parsing: `ffb-server/.../server/ServerMode.java` —
  `STANDALONE("standalone")`, `STANDALONE_INIT_DB("standaloneInitDb")`; two-token
  `standalone initDb` also maps to `STANDALONE_INIT_DB` via `fromArguments`.
- **Shaded jar:** maven-shade-plugin `finalName=FantasyFootballServer` in
  `ffb-server/pom.xml` → `ffb-server/target/FantasyFootballServer.jar`; assembly
  zip `ffb-server.zip` also produced.
- **DB:** hard requirement even standalone. `server.ini` keys: `db.driver=com.mysql.jdbc.Driver`,
  `db.url=jdbc:mysql://localhost/ffblive`, `db.user`, `db.password`, `db.type=mariadb`.
  Bundled connector is mysql-connector 5.1.49 (`ffb-server/pom.xml`); FFB's `Readme.md`
  states MySQL ≤5.6 or MariaDB ≤10.4 only are supported.
  Schema init: `DbInitializer.initDb()` (called from `FantasyFootballServer.run()` in
  init-db modes).
- **Game-flow logic (where rules actually live):** server Step / SequenceGenerator
  classes under `ffb-server/src/main/java/com/fumbbl/ffb/server/step/`. Steps sit on a
  stack per game, consume client commands from a queue — structurally similar to our
  planned procedure stack, which makes side-by-side reading easy.
- **RNG:** `ffb-server/.../server/util/rng/Fortuna.java`. Never try to reproduce its
  stream — layer 7 always *injects recorded results* from replays.
- **Replay/state plumbing:** `ReplayCache`, `ServerReplayer`,
  `net/ReplaySessionManager` (all in `ffb-server/.../server/`); GameState HTTP API
  (`admin/GameStateConnector.java`, servlet routes in `server.ini`:
  `gamestate.url.get=gamestate/get?response=$1&gameId=$2&fromDb=$3&includeLog=$4`,
  also `gamestate/set`, `gamestate/reset`, `gamestate/result`, challenge/response
  auth like the admin endpoints). `gamestate/get` returns full game JSON — the
  cleanest state-extraction point for differential testing.
- **Client replay mode:** `com.fumbbl.ffb.client.FantasyFootballClientAwt -replay
  -server <host> -port <port>` (arg table in `vendor/ffb/Readme.md`). Local teams:
  XML in `ffb-server/teams/`.
- **Tests:** only ~12 files. Notable for us:
  `ffb-server/src/test/java/com/fumbbl/ffb/server/injury/injuryType/InjuryTypeBlockBB2025Test.java`
  (BB2025 block-injury mechanics), `ffb-common/.../RulesTest.java`.
  Run: `mvn test` (add `-Pmockito5` on JDK ≥21), single: `mvn test -Dtest=Class#method`.

## 2. Jervis (`vendor/jervis-ffb/`) — secondary oracle + replay converter

Kotlin Multiplatform, Gradle (Java 21 required; first build generates settings code).
Modules under `modules/`: `jervis-engine`, `jervis-net`, `jervis-ui`, `jervis-test-utils`,
`jervis-resources`, `fumbbl-net`, `fumbbl-cli`, `replay-analyzer`, `tourplay-net`,
`platform-utils`.

- **Rules engine:** `modules/jervis-engine` — UI-agnostic BB2025 + BB2020 rules.
  Engine entry: `com.jervisffb.engine.GameEngineController`; rulesets
  `StandardBB2025Rules` / `StandardBB2020Rules` / `BB72020Rules`
  (see imports in `FuzzTester.kt` below).
- **Tests (~174 files):** `modules/jervis-engine/src/commonTest/kotlin/com/jervisffb/test/`
  with **parallel `bb2020/` and `bb2025/` directories** of the same test names
  (`TurnOverTests.kt`, `KickOffTests.kt`, `ScatterTests.kt`, `BounceTests.kt`,
  `ApothecaryTests.kt`, `ThrowInTests.kt`, `TestAgainstCharacteristicsTests.kt`,
  `ActivatePlayerTests.kt`, `RecoverKnockedOutPlayersTests.kt`, …). Diffing a bb2020
  file against its bb2025 twin is the fastest way to see what the edition changed.
  Top-level: `JervisGameBB2025Test.kt`, `GameEngineControllerTests.kt`,
  `SerializationTests.kt`. Run: `./gradlew :modules:jervis-engine:jvmTest`.
- **Fuzzer:** `modules/jervis-engine/src/commonTest/kotlin/com/jervisffb/test/FuzzTester.kt`
  — seeded random games (100k, batched), `@Ignore`-gated. Their perf notes: log level
  (`DEFAULT_LOG_LEVEL`) and `GameEngineController(validateActions=...)` dominate;
  4–5 ms/game on Apple M3. `createRandomAction` in
  `com.jervisffb.engine.utils` is their random-legal-action generator (our layer-3 analog).
- **FUMBBL replay adapter:** `modules/fumbbl-net/src/commonMain/kotlin/com/jervisffb/fumbbl/net/`
  — `adapter/FumbblReplayAdapter.kt` (websocket-log replay file → Jervis commands, flag
  `checkCommandsWhenLoading`; NOT the REST `/api/replay/get` JSON), `FumbblFileReplayAdapter.kt`
  (file reader it delegates to), `ModelChangeProcessor.kt`, `adapter/MapperChain.kt`,
  `adapter/impl/*Mapper.kt`
  (per-command mappers — a complete inventory of FUMBBL command semantics).
  Tests: `modules/fumbbl-net/src/jvmTest/kotlin/fumbbl/net/ReplayFileTests.kt`
  (`@Ignore`d, run manually; note their comment that fouling conversion was broken —
  check before trusting Jervis on foul sequences).
- **replay-analyzer:** `modules/replay-analyzer/src/jvmMain/kotlin/com/jervisffb/analyzer/Main.kt`
  — reads a downloaded game JSON (e.g. `replays/game-1624379.json`), deserializes
  `NetCommand`s, dumps as JSON for analysis. Handles both websocket-traffic captures
  and replay arrays.
- **fumbbl-cli:** `modules/fumbbl-cli/src/main/kotlin/com/jervisffb/fumbbl/cli/MainCli.kt`
  (clikt): `DownloadGame --game-id <id>` (websocket data for one game; its help text:
  "DO NOT use this to download bulk games"), `PrepareDebugClient` (injects debug code
  into the FUMBBL client jar — pairs with `Debug-FantasyFootballClient/`).

## 3. BloodBowlActionCalculator (`vendor/BloodBowlActionCalculator/`) — probability oracle

C# / .NET, xUnit. `dotnet build`; `dotnet test ActionCalculator.Tests`;
web UI `dotnet run --project ActionCalculator.Web/Server/ActionCalculator.Web.Server.csproj`
(→ localhost:5000). Full developer reference in its `CLAUDE.md` (architecture,
notation, season rules, skills bitmask semantics).

- **Test corpus:** `ActionCalculator.Tests/ActionCalculatorTests.cs` — **281
  `[InlineData]` rows**, shape `(notation, rerolls, p0, p1, …)` where `pK` =
  cumulative P(success using ≤K team re-rolls) — `CalculationResult.Results` indexed
  by re-rolls consumed, aggregated cumulatively. Grouped by commented sections:
  rerollable, leap, block, frenzy, brawler, break tackle, hatred, catch, claw, dodge,
  star skills, etc. (`BlastItTests.cs` is a skipped scatter-enumeration experiment —
  its D8 scatter table is a handy spot-check for our deviate/scatter geometry.)
- **Season toggle:** `ActionCalculator.Models/Season.cs` → `Season2 | Season3`;
  `Calculation.cs` defaults `Season.Season3`; notation suffix `~S2`. Season3 = Third
  Season = BB2025. Differences are confined to Consummate Professional/Pro
  (`ActionCalculator/Strategies/ProHelper.cs`) and The Ballista
  (`Strategies/BallHandling/PassStrategy.cs`), plus UI-only items — so all non-Pro
  rows are valid BB2025 oracle values.
- **Notation cheat sheet** (full grammar in vendor CLAUDE.md):
  `SKILLS:ACTIONS` per player, `;` = next player. Actions: `Rn` rush, `Dn` dodge
  (`¬`=forced Break Tackle, `"`=non-rerollable), `Un` pickup, `Pn` pass, `Cn` catch,
  `nDm` block (n dice, m success faces; negative n = against), `Bn` armour break,
  `Jn` injury, `Fn` foul, `Hn` TTM, `Gn` landing. Block suffixes: `!k` frenzy,
  `*` Pro used, `^` Brawler, `%` Hatred, `'` no-reroll-non-crit. Branches: `{...}`
  rerollable success-branch, `[...]` non-rerollable, `(a/b)` alternates.
- **Odds extraction recipes:**
  1. *Static (preferred):* parse the InlineData rows into
     `validation/fixtures/calculator_odds.json` — regex over
     `\[InlineData\("([^"]+)", (\d+)((?:, [\d.]+)+)\)\]`; keep the comment-section
     name as the scenario tag. 281 ready-made compound-path probabilities.
  2. *Dynamic:* console harness — copy the DI setup from `ActionCalculatorTests.cs`
     ctor (`services.AddActionCalculatorServices()`; resolve `ICalculator` +
     `ICalculationBuilder`), feed notation strings, print `Results[]`. Use for
     scenarios missing from the corpus.
  3. Map each notation to a concrete engine scenario (player skills, target numbers)
     in the fixture so the Monte-Carlo side is generated, not hand-written.

## 4. botbowl (`vendor/botbowl/`) — BB2016 sanity oracle

Python; `pip install -e vendor/botbowl && pytest vendor/botbowl/tests/`.
**Edition warning:** BB2016 rules — use only for edition-invariant mechanics
(block dice distribution, d8 scatter/throw-in geometry, armour/injury roll structure,
adjacency/tackle zones) and as obs/action-encoding prior art, never for BB2020/25
specifics (passing, rushes, casualty table differ).

- Tests: `tests/game/` (29 files: `test_block.py`, `test_armor.py`, `test_dodge.py`,
  `test_pass.py`, `test_catch.py`, `test_injury.py`, `test_frenzy.py`,
  `test_throw_in.py`, `test_full_game.py`, …), `tests/kickoff/`
  (`test_kickoff_table.py`, `test_setup.py`), plus `tests/ai/`, `tests/performance/`.
- **Dice-fixing pattern** (prior art for our dice scripts):
  `tests/game/test_dice.py` — `D6.fix(value)` queues forced results consumed in
  order; `BBDie` for block dice. Our `bb_rng` script mode is the C analog.

## 5. fumbbl_replays (`vendor/fumbbl_replays/`) — replay parsing prior art

Python package `src/fumbbl_replays/`: `fetch_match.py`, `fetch_replay.py`,
`fetch_roster.py`, `fetch_team.py` (API access incl. caching via `get_cache_dir.py`);
per-roll parsers `parse_blockchoice.py`, `parse_dodgeroll.py`, `parse_catchroll.py`,
`parse_GFIroll.py`, `parse_injury.py`, `parse_kickoff_scatter.py`,
`parse_confusionroll.py`, `parse_boardpos.py`; trajectory builder
`from_steps_to_trajectories.py`. Read these before writing our replay normalizer —
they document where each dice value hides in the replay JSON report structure.

## FUMBBL API quick facts (from docs/SOURCES.md, verified 2026-06-02)

- `GET https://fumbbl.com/api/match/get/<id>` — tournamentId, division, coach rating
  (cr/bracket), conceded flag, **replayId**. No auth.
- `GET https://fumbbl.com/api/replay/get/<replayId>/gz` — gzipped replay JSON. No auth.
- Etiquette: ~1 req/s, cache locally (`docs/vendor/fumbbl/api-notes-730.html`),
  courtesy heads-up to Christer before mass pulls.
