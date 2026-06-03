# NUFFLEBOT Technical Feasibility Report

**Subject:** Deploying the trained bloodbowl-rl policy as a declared bot on FUMBBL
**Scope:** Paper assessment + local-only experiments. No production contact made or planned before explicit FUMBBL admin permission.
**Inputs:** Three completed investigations (architecture, state/action mapping, prior art/governance) over `vendor/ffb` (MIT, the actual FUMBBL client+server monorepo), `vendor/jervis-ffb`, our engine (`engine/`, `puffer/bloodbowl/`), and `validation/normalize_replay.py`. The dedicated protocol deep-dive agent failed, but its scope (transport, wire format, command vocabulary, auth, dice authority) was independently established by the architecture investigation and is treated as covered. All file paths cited below were verified to exist in the working tree.

---

## 1. VERDICT

**Feasible. High confidence (~85%) on the technical side; the binding constraint is governance, not engineering — and governance looks unusually favorable.**

- **Technical:** The FUMBBL server is fully authoritative (all dice rolled server-side in `vendor/ffb/ffb-server/src/main/java/com/fumbbl/ffb/server/DiceRoller.java:39-50` via Fortuna CSPRNG; clients only receive results). A bot client never rolls a die and needs no entropy source. The protocol is JSON over WebSocket (`/command`), the entire client+server source is vendored under MIT, and the server runs **fully standalone locally** (`FantasyFootballServer.main`, `ffb-server/.../FantasyFootballServer.java:296`, `standalone` mode) with **scriptable dice** in test games (`/roll` chat command → `TalkHandlerRoll.java` → `DiceRoller.addTestRoll`). Every component can be built and validated with zero production contact.
- **Cost structure:** ~70% of the bot's code mass is the already-planned Phase-4 lockstep/differential harness (task #6). A FUMBBL replay's `gameLog.commandArray` is literally an archive of the same `serverModelSync` messages a live client receives (`validation/normalize_replay.py:305`; live transport in `vendor/jervis-ffb/modules/fumbbl-net/.../FumbblWebsocketConnection.kt`). Building Phase 4 first *is* building most of NUFFLEBOT.
- **Governance:** No bot has ever played on FUMBBL, but founder/admin Christer is **on record inviting exactly this** (Nov 2023, Developers' Den t=32780: "if you have a functional bot I'm very much interested in getting that to work on FUMBBL in some way... adding some kind of bot API is absolutely on my long-term wishlist"), while ruling out competitive divisions. Site rules contain no explicit bot ban; the path is a Discord conversation proposing an opt-in League-division group or test-server sandbox.

**Recommended architecture: Option A — a headless bot client built as a new sibling Maven module (`ffb-client-bot`) on top of upstream `ffb-client-logic`, bridging to the policy process over a localhost JSON-lines socket.** Rejected: (B) native Python/C protocol reimplementation — the cost is not serialization but re-deriving command *sequencing* choreography implicit in 36 LogicModules and server Step classes, with the highest drift brittleness; (C) jervis-ffb's FUMBBL adapter — its live websocket class is an unused stub referenced only by an `@Ignore`d test, it covers ~13/92 client commands, and no reverse (action→command) mapper exists. Jervis stays in our stack as an offline replay oracle.

---

## 2. Recommended architecture

### 2.1 Why Option A wins

Upstream already did the "strip the UI" split: `ffb-client-logic` (61 kLOC — protocol, `Game` model mirror, legality logic) vs `ffb-client` (9.4 kLOC — AWT shell). The abstract base `FantasyFootballClient` (`ffb-client-logic/.../client/FantasyFootballClient.java`, websocket setup at :213) owns the connection, command queue, `Game` model, and a pluggable `ClientStateFactory`; the AWT client (`FantasyFootballClientAwt.java`, main at :147) is just one implementation. Every human input funnels through exactly two seams:

1. **Board actions:** AWT events → `ClientStateAwt` subclasses → UI-agnostic `LogicModule.perform(Player, ClientAction)` (`ffb-client-logic/.../state/logic/LogicModule.java:72-81`; 36 modules, e.g. `MoveLogicModule.java:284`) → one of 92 typed `ClientCommunication.sendXxx()` methods (`client/net/ClientCommunication.java`).
2. **Server-driven choices:** server sets `game.dialogParameter` via model change (`gameSetDialogParameter`, `ModelChangeId.java:88`); the client dispatches on `DialogId` in `DialogManager.updateDialog()` (66 case labels: RE_ROLL, BLOCK_ROLL, USE_APOTHECARY, FOLLOWUP_CHOICE, TOUCHBACK, ...); each Swing `DialogHandler`'s close listener calls the matching `sendXxx()`.

Replace the Swing dialogs and mouse states with a policy bridge at those two seams and you have a bot, with **near-zero modified upstream lines** — protocol drift arrives as compilable Java and the compiler finds breakage on `git merge` upstream (FUMBBL runs this exact code; last upstream commit 2026-04-19).

**Known obstacle:** `UserInterface extends JFrame` (`ffb-client-logic/.../client/UserInterface.java:39`); 138/647 files import Swing and handlers call `getUserInterface().getLog()` unconditionally. Plan: no-op `UserInterface` subclass + Xvfb on Linux first (JFrame can't be constructed under `java.awt.headless=true`); a mechanical interface-extraction patch (~30-60 files, upstream-mergeable) as the clean long-term fix.

### 2.2 Components and data flow

```
fumbbl.com (or LOCAL ffb-server) — authoritative state + dice
        | ws(s) <host>:22223/command — FFB JSON (optionally LZString-UTF16,
        |        binary frames of UTF-8 JSON; CommandEndpoint.java:107-132)
+-------v--------------------------------------------------+
| ffb-client-bot (Java, sibling Maven module)              |
|  NuffleBotClient extends FantasyFootballClient (headless)|
|  - auth: MD5-HMAC challenge/response (PasswordChallenge) |
|  - applies ServerCommandModelSync -> Game model (upstream)|
|  - DialogManager replacement: serialize IDialogParameter |
|    + state digest -> bridge; reply -> sendXxx()          |
|  - turn driver: after each sync, if our turn/decision,   |
|    query bridge; LogicModules reused as legality oracle  |
+-------^----------------------v---------------------------+
        | {command,args}       | {state_digest, dialog_parameter |
        |                      |  turn_request, legal_actions}   (JSON-lines, localhost)
+-------+----------------------v---------------------------+
| Python policy shim                                       |
|  INGEST: IncrementalNormalizer (refactor of              |
|    validation/normalize_replay.py batch loop, line 271+) |
|  LOCKSTEP FOLLOWER: records -> (bb_action, dice script)  |
|    -> bb_apply/bb_advance on bb_match (== Phase-4 core)  |
|    own-echo dedup; per-sync state differ                 |
|  POLICY RUNNER: bbe_encode_obs_match + bb_legal_actions  |
|    + net forward + decode-snap-to-legal                  |
|    (bloodbowl.h:433 "exact -> same-type -> first")       |
|  REVERSE MAPPER: (bb_action, open DialogId, id tables)   |
|    -> ClientCommand spec                                 |
|  DESYNC MONITOR: bb_rng_error / BB_STATUS_ERROR / state  |
|    diff -> safe mode -> rejoin -> rebuild at boundary    |
+----------------------------------------------------------+
   shared tables: playerId<->slot, FUMBBL skill name<->skill id,
   reportId->dice-consumption-order, DialogId->decision type
```

### 2.3 Shared-cost ledger (the headline economic fact)

| Component | Shared with Phase-4 lockstep harness (task #6)? |
|---|---|
| `serverModelSync` parser / IncrementalNormalizer | **100%** — replay `commandArray` ≡ live stream |
| FFB `Game` JSON → `bb_match` builder (rosters, coords, `PlayerState` bits) | **100%** (gap for both: `bb_match_init_custom` is unimplemented — mentioned at `engine/include/bb/bb_match.h:131` — plus FUMBBL-skill-name → our-skill-id table) |
| reports/modelChanges → `bb_action` forward mapper | **~90%** (live adds own-echo dedup; jervis's 45 mappers under `vendor/jervis-ffb/.../fumbbl/net/adapter/impl/` are proven prior art) |
| report → dice-script extractor + per-report roll-order adapters | **100%** — `bb_rng` SCRIPT mode (`engine/include/bb/bb_rng.h`) was designed for this; extraction table exists in `normalize_replay.py` `extract_report` (lines 131-234) |
| per-sync state differ (double-entry bookkeeping vs our grid) | **100%** (replay: assert; live: trip recovery) |
| NUFFLEBOT-only | Java headless client + dialog router; reverse mapper; transport/auth; desync recovery; pacing/etiquette |

Rough split: **~70% of NUFFLEBOT's code mass is Phase-4 deliverables.** Sequencing Phase 4 first is not hygiene — it's most of the bot.

### 2.4 Mapping facts that shape the design

- **Easy 1:1 bulk (~25 commands we'd emit):** SETUP_PLACE→`ClientCommandSetupPlayer`; KICK_TARGET→`ClientCommandKickoff`; ACTIVATE+DECLARE fuse into one `ClientCommandActingPlayer`; BLOCK_TARGET→`ClientCommandBlock` (booleans absorb stab/chainsaw/vomit/breathe-fire); CHOOSE_DIE→`ClientCommandBlockChoice`; STEP→`ClientCommandMove` (length-1 paths valid); push chains map 1:1 (`ClientCommandPushback`, one square per prompt — clean, despite reputation).
- **One real granularity mismatch: blitz target pre-declaration.** FUMBBL requires the target at declaration (`CLIENT_BLITZ_TARGET_SELECTED`, `NetCommandId.java:16`); our engine declares a bare blitz (`proc_turn.c:228`) and picks the target later. **Required engine change:** insert a blitz-target decision after DECLARE (closer to tabletop anyway), so train-time and deploy-time action distributions match. Do not let the bridge guess the target — that's a divergence factory.
- **Dialog-context-sensitive dispatch:** ≥7 distinct reroll-ish reply commands map onto our 2 reroll actions; the correct command is a function of (our action, open `DialogId`, dialog payload). Several commands **echo** server-provided values (`ClientCommandApothecaryChoice`, `ClientCommandUseApothecary` carry `PlayerState`/`SeriousInjury` from the dialog), so the bridge must retain the last DialogParameter. This is why `gameSetDialogParameter` — currently deliberately skipped by `normalize_replay.py` (header lines 33-34) — must stop being skipped; it is *the* live decision trigger.
- **Asymmetric follow-direction risk:** things we never emit can be done *to* us (Multiple Block, wizards/cards/inducements — backlog #23, star players). The lockstep follower must understand ~100% of server traffic even though the reverse mapper covers only our action surface. The Phase-4 replay-corpus coverage gate is therefore also NUFFLEBOT's launch gate.
- **Policy runner change:** factor `bbe_encode_obs` (`puffer/bloodbowl/bloodbowl.h:251`, coupled to the env struct) into a `bb_match`-only variant `bbe_encode_obs_match(const bb_match*, int agent, uint8_t out[832])`.

---

## 3. Development plan — LOCAL ffb-server first, stage gates

All stages run against a private standalone FFB instance. Zero production contact through Stage 6. The only fumbbl.com touch in the entire plan is the documented one-time public `xml:roster`/`xml:team` fetches for current BB2025 team XMLs (vendored `ffb-server/rosters/*.xml` are legacy-era) — and even that can wait for the permission conversation.

**Stage 0 — Local rig up (≤1 week).**
Turnkey recipe already vendored: `vendor/jervis-ffb/docs/working-with-ffb.md`. MariaDB 10.4 (hard constraint: `mysql-connector-java 5.1.49`, `ffb-server/pom.xml:116-119` ⇒ MySQL ≤5.6/MariaDB ≤10.4; containerize `mariadb:10.4`), `standalone initDb` (`DbInitializer.java:108`), teams/rosters from local XML (`GameCache.init()`, `GameCache.java:71-85`), games auto-created and always test-mode (`ServerCommandHandlerJoinApproved.java:79`).
*Gate G0:* two stock AWT clients (`FantasyFootballClientAwt -player -coach X -teamId Y -server localhost -port 22227`) complete a full game; `/roll 6 5 ...` scripted dice verified; `GameStateServlet` (`/gamestate/*`, `FantasyFootballServer.java:211`) dumps state JSON.

**Stage 1 — Phase-4 lockstep harness (the shared core; already planned as task #6).**
IncrementalNormalizer refactor (`begin/feed/coverage`, byte-identical JSONL on the existing corpus as regression); forward mapper; dice-script extractor with roll-order adapters; `Game`-JSON→`bb_match` builder (requires implementing `bb_match_init_custom` + skill-name table); state differ. Run the full replay corpus through `bb_apply`/`bb_advance` in lockstep.
*Gate G1:* corpus lockstep replay with state-diff assertions passing at ~100% rule coverage (inducements/stars included — backlog #23 promoted to blocker); `bb_rng_error` rate = 0 on covered replays.

**Stage 2 — Engine prerequisites.**
Blitz-target declaration decision (+ obs ctx surface, retrain or fine-tune so distributions match); `bbe_encode_obs_match`.
*Gate G2:* engine spec tests + self-play sanity unchanged; new decision exercised in self-play.

**Stage 3 — Headless Java client.**
`ffb-client-bot` module: `NuffleBotClient` (~20 abstract methods), no-op `UserInterface` under Xvfb, dialog→bridge router over the 66 DialogIds, turn driver hooked after `ServerCommandModelSync` application, bridge protocol.
*Gate G3:* headless client joins the local server, mirrors a full human-vs-human game's model state byte-for-byte against `GameStateServlet` dumps, answers all dialogs with hardcoded defaults without stalling.

**Stage 4 — Policy integration, bot-vs-bot.**
Reverse mapper, policy runner, own-echo dedup, desync monitor.
*Gate G4:* **two NUFFLEBOTs complete N≥100 local games with zero desyncs and zero illegal-command rejections**, including games with scripted dice forcing rare branches (apothecary chains, kickoff events, push chains with Side Step, touchbacks).

**Stage 5 — Adversarial soak.**
Human (Alex) vs bot on the local rig; deliberately weird lines (Multiple Block, stalling, conceding, reconnect mid-game); kill/restart the bot mid-procedure to exercise recovery; verify the 4-minute turn clock (`TURNTIME` default 240 s, `GameOptionFactory.java:254-255`; timeout machinery `UtilServerTimer.java:36-40`) is never approached and in-opponent-turn decisions answer in seconds.
*Gate G5:* desync-recovery drill passes (rejoin → snapshot rebuild at quiet boundary); decision latency p99 < 5 s; no stalls.

**Stage 6 — Governance gate (hard stop).**
Permission conversation with Christer on Discord (agenda in §6), bringing the working bot + this report. **No production connection of any kind before explicit written/sanctioned arrangement.**

**Stage 7 — Sanctioned pilot** (shape determined by Stage 6): private League-division group or test-server sandbox, opt-in human opponents, human handler doing all scheduling, bot account clearly named/declared, kill switch, every game logged for the differential harness.

---

## 4. Effort estimate by component

| Component | New code | Est. effort | Notes |
|---|---|---|---|
| Local rig (Stage 0) | config only | 2-4 days | recipe vendored; MariaDB 10.4 container |
| IncrementalNormalizer refactor | ~0.3k Py | ~1 day | mechanical hoist of loop locals (`normalize_replay.py:271-304`); corpus = regression test |
| Lockstep follower + dice-script + state differ (Phase-4 core) | ~2-3k Py | 2-4 weeks | **shared with task #6, not marginal NUFFLEBOT cost**; roll-order alignment is the grind |
| `Game`-JSON→`bb_match` builder + `bb_match_init_custom` + skill table | ~1k C + ~0.5k Py | 1-2 weeks | shared; blocks both replay differential and bot |
| Engine: blitz-target decision (+ policy retrain pass) | ~0.3k C | ~1 week + retrain | the one decision-granularity fix |
| Headless Java client + dialog router + bridge | ~2.5-4k Java | 2-3 weeks | most of the 66 dialog cases are 5-liners; Xvfb workaround day-one |
| Reverse mapper + policy runner + `bbe_encode_obs_match` | ~1.5-2.5k Py/C | 1-2 weeks | dialog-context dispatch + echo retention is the subtle part |
| Desync monitor & recovery | ~0.5-1k Py | ~1 week | detection is nearly free (rng/apply/diff tripwires built in) |
| Soak + hardening (Stages 4-5) | tests | 1-2 weeks | scripted-dice rare-branch forcing |

**Totals: ≈ 8-12 kLOC new code. Marginal NUFFLEBOT cost over Phase 4: ~5-7 weeks. End-to-end including the shared Phase-4 work: ~2.5-4 months to Gate G5.** (Architecture investigator's "2-4 weeks to first full self-played game" for the Java side alone is consistent with this once Phase 4 exists.)

---

## 5. Risk register

### Technical

| Risk | Likelihood / Impact | Mitigation |
|---|---|---|
| **Mid-procedure desync unrecoverable from snapshot** — `serverGameState` rejoin re-sends the client-visible `Game` (turnMode, actingPlayer, dialogParameter) but **not** the server's internal step stack; our `bb_match.stack` can't be rebuilt mid-push-chain/mid-test. Protocol limit, not ours. | Med / Med | Three-tier policy: (i) full rebuild at quiet boundaries (between activations/turns/setup) — always safe; (ii) mid-procedure: dialog-driven minimal mode with conservative defaults (decline reroll/apo, push straight back, no follow-up) until next boundary; (iii) floor: `ClientCommandConcedeGame` rather than stall. Log every desync's full command window → automatic Phase-4 test case. |
| **Roll-order misalignment** (FFB reports armour as a 2-array, we call `bb_d6` twice; block-die pool ordering; scatter d8 sequences) | High initially / Low long-term | Deterministic and self-announcing: `bb_rng` SCRIPT mode errors are sticky and non-crashing (`bb_rng_error`). Fixed once in the Phase-4 differential, fixed forever for the bot — same code. |
| **Protocol drift / client updates** — client+server released in lockstep from one monorepo; jars re-fetched per launch via JNLP so the player population always runs current; BB2025 errata churn ongoing (May 2026 FAQ thread feeds straight into releases). A stale fork breaks at the next protocol-affecting release. | High / Med | Option A's core advantage: drift arrives as compilable Java; `git merge` upstream + compiler finds breakage. Keep upstream-modified lines ≈0 (sibling module). Version handshake is client-side-only (`LoginLogicModule.checkVersion`, :157-180; no server-side rejection found in ffb-server) — but track upstream anyway; long-term, co-design Christer's wishlist "bot API". |
| **Swing entanglement** (`UserInterface extends JFrame`; 138 files import Swing) | Certain / Low | Xvfb + no-op subclass now; mechanical interface-extraction patch offered upstream later. |
| **Unmapped opponent-side traffic** (Multiple Block, wizards, inducements done *to* us) | Med / High if unhandled | Launch gate = ~100% replay-corpus coverage incl. backlog #23; follower must parse everything even where we never emit it. |
| **Own-echo double-application** | Med / Med | Expected-echo queue: our action applied to `bb_match` once at decision time; the echoing `serverModelSync` consumed as dice + confirmation only. |
| **MariaDB 10.4 EOL / connector age** (local rig only) | Low / Low | Pin `mariadb:10.4` container; never production-facing. |

### Operational

| Risk | Likelihood / Impact | Mitigation |
|---|---|---|
| **Turn clock** — 4 min/turn, opponent-invoked timeout (`TURNTIME`=240 s; `UtilServerTimer.syncTime` sets `timeoutPossible`) | Low | Policy inference is milliseconds; generous vs Bot Bowl's 2 min. Gate G5 enforces p99 < 5 s including in-opponent-turn decisions (block die choice, skill use, apo) — politeness, not just legality. |
| **Scheduling is social** — Gamefinder is mutual-consent negotiation; Blackbox is the only automatable scheduler but is exactly the competitive context Christer ruled out, and Blackbox opponents cannot consent to a bot. | Certain / Med | Human handler (Alex) arranges all games; private League-division group where every member opted in. Never Blackbox, never Competitive. |
| **Availability expectations** — site rules: 90-min availability, 15-min no-response = disconnect, intentional delay banned | Low | Supervised sessions only during pilot; watchdog + concede-on-failure as hard floor; never leave the bot unattended in a live game. |

### Social / Governance

| Risk | Likelihood / Impact | Mitigation |
|---|---|---|
| **Playing without sanction** — Christer 2023: bots "certainly not OK in a competitive division context" | — | Absolute precondition: no production contact before explicit permission (Stage 6 hard stop). This report's plan is structured so everything up to that point is local. |
| **"One account per person" rule** — a separate NUFFLEBOT account itself needs dispensation | Certain / Low | Explicit agenda item in the admin conversation; don't create the account beforehand. |
| **Opponent consent / community optics** | Med / Med | Bot clearly named and declared in profile + pre-game chat; opt-in pool only; publish the project openly (precedent: jervis-ffb builds FUMBBL interop in the open; replay bulk-pull permissions were granted via Discord ask-first culture). |
| **Server-resource etiquette** | Low / Low | Existing project etiquette (`.claude/skills/fumbbl-data/SKILL.md` §7): API-only, ≤1 req/s, cache forever, descriptive UA, heads-up before any mass pull. A bot client is one ordinary game connection — negligible load, but say so explicitly when asking. |

---

## 6. Open questions — only answerable by FUMBBL admins (the Christer conversation agenda)

1. **Sanction & venue:** Will you sanction a declared bot account for a pilot? Preferred venue — private invitation-only League-division group, or a test-server arrangement like the historical "FFB Test Division" (t=21820; the protocol still carries `isTestServer` in `ServerCommandVersion`)? Any divisions/rulesets explicitly off-limits beyond Competitive/Blackbox?
2. **Account policy:** Dispensation from "one account per person" for a clearly-labeled `NUFFLEBOT` account owned by an identified human? Required profile disclosure text?
3. **Client policy:** Is a modified/headless build of the open-sourced FFB client acceptable on production, or do you require the bot controller to sit alongside an unmodified official client (the approach you sketched in t=32780)? Would you take an upstream PR extracting the `UserInterface` interface to make headless official?
4. **Bot API wishlist:** You mentioned a long-term bot API (step 1 = talk to the botbowl people). Is co-designing that with a working FFB-protocol bot in hand useful to you, and what would you want it to look like so NUFFLEBOT can be its first consumer rather than a one-off hack?
5. **Operational guardrails:** Required supervision level (human handler online for every game?), kill-switch expectations, acceptable decision latency, what happens to ratings/records of bot games (League `cr: 0` seems to make this moot — confirm), and incident protocol if the bot desyncs/stalls (we auto-concede — acceptable?).
6. **Data:** Blanket OK for the one-time BB2025 roster/team XML fetches for the local rig, and for continued throttled replay pulls feeding the validation corpus (per the t=32558 ask-first precedent)?
7. **Disclosure to opponents:** Is per-game chat declaration + profile labeling sufficient, or do you want a site-level marker (e.g., bot flag) before any game vs a human who didn't personally join the pilot group?

---

**Bottom line:** Build Phase 4 (it's 70% of the bot), add the headless Java module and reverse mapper against the local standalone server with scripted dice, hit the zero-desync soak gate — then take the working bot and this report to Christer, who has already asked for exactly this. Key sources: `vendor/ffb/ffb-client-logic/.../FantasyFootballClient.java`, `.../ClientCommunication.java`, `.../DialogManager.java`; `vendor/ffb/ffb-server/.../FantasyFootballServer.java`, `DiceRoller.java`, `TalkHandlerRoll.java`, `server.ini`; `vendor/jervis-ffb/docs/working-with-ffb.md`, `modules/fumbbl-net/.../FumbblWebsocketConnection.kt`; `validation/normalize_replay.py`; `engine/include/bb/bb_rng.h`, `bb_match.h`; `puffer/bloodbowl/bloodbowl.h`; FUMBBL forum threads t=32780 (admin invitation), t=32558 (ask-first precedent), t=21820 (test division precedent).