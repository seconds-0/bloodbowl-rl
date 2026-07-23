# obs-v6 blind-spot inventory

Read-only audit of every decision window for the shape: **the policy can ADDRESS a
distinction in its action space that it cannot SEE in its observation.** Two prior
instances of this shape were real defects — rolled block dice (fixed, D217) and the
executed-action mismatch (fixed, D218) — and both invalidated reward conclusions
drawn before them.

The point of auditing everything at once is that each observation change costs a
lineage break: a new revision, three `OBS_SIZE` sync points, and no warm-start
across it. Shipping these piecemeal would be strictly worse than batching.

Nothing in here is implemented. This is the work list.

Audited against `main` plus the reward-PBRS branch. Read-only; nothing was modified.

## 1. Method and the exact test applied

A window is a **blind spot** iff: (a) it is a real top-of-stack decision, (b) some state feature *varies* across instances of that window, (c) that feature changes the value or consequence of an action the policy can select, and (d) the feature is neither in the 2782 obs bytes nor recomputable from them. Action *legality* does not count as a blind spot — `bbe_fill_mask` (`puffer/bloodbowl/bloodbowl.h:1378`) hands the policy the exact joint support, so anything that only gates legality is already visible.

## 2. Which procedures can be the decision

`bb_legal_actions` dispatches through `vt->legal` (`engine/src/bb_match.c:448-454`), so only procs with a non-null `legal` slot in the vtable list at `engine/src/proc_table.c` can ever be the top-of-stack decision. Exactly **13** qualify:

`PREGAME, SETUP, KICKOFF, TEAM_TURN, ACTIVATION, MOVE, BLOCK, PUSH, CASUALTY, PASS, FOUL, TEST, KO_RECOVERY` — vtables at `proc_match.c:1016-1019,1058`, `proc_turn.c:699-700`, `proc_move.c:992`, `proc_block.c:1262-1263,1267-1268`, `proc_ball.c:424`, `proc_test.c:186`.

The other 12 (`MATCH, TOUCHDOWN, END_DRIVE, TURNOVER, KNOCKDOWN, ARMOUR, INJURY, SCATTER, THROW_IN, CATCH, HANDOFF, TTM`) have `{advance, 0, 0}` — **no decision, nothing to audit**. This directly answers four items on your watch list:

- **SCATTER / THROW_IN direction** — `proc_ball.c:421-422`. Pure RNG, never a decision. Nothing to fix, ever.
- **CATCH** — `proc_ball.c:423`. Not a decision proc; the only catch decision is the nested `TEST(BB_TEST_CATCH)` reroll window, audited under TEST below.
- **TTM** — `proc_ttm.c:193`, and `grep bb_need_decision engine/src/proc_ttm.c` is empty. All TTM choices happen in `MOVE` (`BB_A_SPECIAL_TARGET` arg 7 = mate pick, `BB_A_TTM_TARGET` = square).
- **HANDOFF** — `proc_ball.c:425`. Auto-resolves into `CATCH`.

## 3. Findings, prioritised

### P0-1 — PASS interception window: the candidate list is 100% unobservable
**Window:** `BB_PROC_PASS` phase 2, `pass_legal` (`engine/src/proc_ball.c:358-372`). The defending coach picks among `nc ≤ 16` interceptors addressed **by list index**: `{BB_A_CHOOSE_OPTION, arg=i}` for `i < nc`, plus `arg=0xFE` decline.

**Invisible:**
1. **Which player each index is.** The list comes from `interception_candidates` → `ruler_candidates` (`proc_ball.c:200-227`), a 64-step float march along the thrower→target segment. Nothing in the obs identifies index→slot.
2. **The pass target square.** It is the PASS frame's `x/y` (set at `proc_move.c:847`), and top-frame `x/y` are unexposed (`bloodbowl.h:1023-1029`). So the policy cannot even *reconstruct* the ruler path — it does not know where the ball is going.
3. **The accurate/inaccurate latch** (`f->data & 0x100`, `proc_ball.c:301`), which sets the interception modifier to −2 vs −3 (`proc_ball.c:379`).

`bbe_frame_a_is_slot` does whitelist PASS (`bloodbowl.h:906`) so `ctx[6]` = thrower, but PASS is *not* in `bbe_frame_b_is_slot` (`:913-922`) and `f->b` is only written at phase 3 anyway. This is the purest instance of the bug shape in the codebase: up to 17 distinct addressable options, zero observational content separating them.

**Minimal fix:** (a) generalize `ctx[9]/ctx[12]` — currently the Dodge-destination-only pair (`bloodbowl.h:1041-1052`) — to a per-proc "pending consequence square", ego-mirrored exactly as now, gated to include `proc == BB_PROC_PASS` → **0 bytes**; (b) a 16-byte `CHOOSE_OPTION` candidate table, option `i` → `1 + bbe_ego_slot(me, slot)`, 0 = not a player option → **16 bytes**; (c) fold the inaccurate latch into the window-flags byte below → **0 extra**.

**Cost: 16 bytes. Load-bearing: yes.**

### P0-2 — PUSH window: whether the block was a POW is unrecoverable
**Windows:** `push_legal` (`proc_block.c:719-775`): phase 0 square choice (normal / crowd `arg=1` / chain `arg=2` / Side Step), phase 3 follow-up, phase 4 Stand Firm.

`resolve_face` **pops the BLOCK frame before pushing PUSH** (`proc_block.c:389-421`), stamping `PSH_POW` for POW and for un-Dodged Stumble. So at every PUSH decision the block face is gone from the state and the only trace is `f->data` bit 0 — and `bbe_encode_obs` reads `top->data` at exactly one place, the block-face block at `bloodbowl.h:1057-1064` (verified: `grep '\->data' bloodbowl.h` hits only `:2748`, `:2749`, `:3098`, all in telemetry/reward, none in the encoder).

**Invisible and consequential:**
- `PSH_POW` — decides whether the pushee ends prone (`proc_block.c:688-690`) and, with a crowd push, whether the surf lands on a downed player. Changes the value of *every* square in the window and the follow-up.
- `PSH_FROM_BLITZ` — gates Juggernaut, Fend cancellation, and the Frenzy second block (`proc_block.c:611-613, 653-683`).
- The **vacated square** at phase 3. It is `f->x/f->y` (`proc_block.c:593-594`, and `:559-560` on the crowd path). Recoverable only for a straight push; with Side Step (`push_legal:732-744`) the pushee's destination is any adjacent square, so two squares are adjacent to both attacker and pushee and the vacated square is genuinely ambiguous; after a crowd push the pushee is off-pitch entirely and it is unrecoverable.

Meanwhile `test_observation.c:361-382` proves crowd and chain variants are exactly addressable in the arg head. Confirmed diagnosis.

Honest subtractions: `PSH_CROWD` at phase 3 *is* derivable (the pushee's `location` byte `t[2]` is no longer `ON_PITCH`, `proc_block.c:553`); `PSH_CHAIN` never reaches phase 3 (`:603-605`); `PSH_STOOD_FIRM` skips to phase 5, no decision. So only POW + FROM_BLITZ + the vacated square are real.

**Minimal fix:** one **window-flags byte** (proc-disambiguated by `ctx[4]`, as `ctx[8]` already is) carrying POW / FROM_BLITZ / SF_DECLINED for PUSH; plus the generalized `ctx[9]/ctx[12]` pending square covering PUSH phase 3.

**Cost: 1 byte (+0 for the square). Load-bearing: yes.**

### P0-3 — the declared activation kind (`bb_act_kind`) is nowhere in the observation
`MOVE` stores the declared kind in `f->b` (`move_legal` branches on it at `proc_move.c:421+`: `kind == BB_ACT_BLOCK/BLITZ/PASS/HANDOFF/FOUL/TTM/KTM/STAB/GAZE/CHAINSAW/...`). `bbe_frame_b_is_slot` returns true only for BLOCK/PUSH/FOUL (`bloodbowl.h:913-922`), so `ctx[7] = 0` at every MOVE decision — correct per the documented whitelist, but the kind then appears in **no** other byte. The encoder reads it internally (`bloodbowl.h:1127`, `is_blitz`) and never emits it. `s[21]` covers `BB_TEST_KIND` only (`:1094-1096`). `ACTIVATION` has the same problem: `f->b = a.arg` is the declared kind (`proc_turn.c` `activation_apply`), invisible at the phase-2 gate reroll window; `BLOCK` inherits it as `BLK_IS_BLITZ` (`proc_move.c:838`), invisible at phase 1/2/4/5.

Consequences the policy cannot see: whether a STEP still leaves a blitz block available; whether an `ATTACKER_DOWN` sits inside a blitz (Juggernaut / Frenzy-second-block paths, `proc_block.c:360-369, 653-683`); Unchannelled Fury's +2 on the negatrait gate reroll (`proc_turn.c` `gate_modifier`). `m->blitz_used` (`s[8]`) is a *team-turn* flag, not the current activation's kind, so it does not substitute.

An LSTM could carry this from its own DECLARE two steps earlier — but not across a demo-bank reset, which drops the policy into a live mid-match stack with no history. That is the exact argument the code already makes for the Dodge destination at `bloodbowl.h:1026-1029`.

**Minimal fix:** one byte, `bb_act_kind + 1` from the nearest MOVE/ACTIVATION frame, reusing the `bbe_active_move_slot` stack walk (`bloodbowl.h:928-936`). Mirrors the `s[21]` precedent exactly. **Cost: 1 byte. Load-bearing: yes.**

### P0-4 — CASUALTY apothecary: both casualty rolls are invisible
**Windows:** `casualty_legal` (`proc_block.c:1119-1128`). Phase 1 = `APOTHECARY 1/0`; phase 2 = `CHOOSE_OPTION 0` (roll A, `f->x`) vs `1` (roll B, `f->y`).

The outcomes genuinely differ: declining always sends the player to `BB_LOC_CAS`, out for the match (`casualty_resolve`, `proc_block.c` — `bb_remove_from_pitch(..., BB_LOC_CAS)`), while at phase 2 a pick whose `bb_casualty_table[]` entry is `BB_CAS_BADLY_HURT` goes to **Reserves** instead (`casualty_apply`, `proc_block.c:1155-1160`) — available next drive. The table is monotone: rolls 1–8 are Badly Hurt, 9+ are not (`engine/src/gen_tables.c:5`).

So the optimal play is a pure threshold: at phase 1 use the apothecary iff `roll1 ≤ 8` (a guaranteed save) or accept a 50% gamble; at phase 2 pick whichever roll is ≤ 8. **Neither roll is observed.** `ctx[8]` exposes `top->x` only when `proc == BB_PROC_TEST` (`bloodbowl.h:1040`), so the D16 in `f->x` is suppressed, and `f->y` is never read. `ctx[6]` correctly gives the victim (CASUALTY is whitelisted, `:903`) and `s[14]/s[15]` give the apothecary counts — but the policy is asked to burn a once-per-match resource, and then to choose between two numbers, with zero sight of either.

Because the table is monotone the raw rolls are directly learnable; no severity-band byte is needed.

**Cost: 2 bytes (roll A, roll B; gated to `proc == BB_PROC_CASUALTY`). Load-bearing: yes.**

### P1-5 — the turnover latch and the Charge! context
`m->turnover` (`bb_match.h:124`) is not encoded anywhere. Decisions *are* surfaced with it already set: the crowd-push path calls `bb_turnover` then hands over the phase-3 follow-up (`proc_block.c:548, 558`), and the whole ARMOUR→INJURY→CASUALTY/KO_RECOVERY chain runs after an attacker-down turnover. With the turn already lost, positioning for future turns is what matters, and the policy cannot tell.

Separately, `bb_in_kickoff_charge` (`proc_match.c:430-437`) changes the rules materially — team rerolls become available mid-kickoff (`proc_test.c:48-49`), and a turnover ends only the free activations (`proc_match.c` `charge_end`) — but the Charge! `KICKOFF` frame is buried below the top of stack and `ACTIVATION`'s charge marker is `f->x` (`activation_legal`, `f->x == 1`), unexposed.

**Cost: 1 byte (stack-flags: `turnover | in_kickoff_charge | in_kickoff`). Load-bearing: yes, and cheap.**

### P1-6 — placement-window budgets are invisible
- `SETUP`: `f->data` is the action counter against `SETUP_ACTION_BUDGET 24` (`proc_match.c:268, 286`). Past the budget only DONE is legal and the engine autofixes the formation (which the reward economy prices via `reward_setup_autofix`, `bloodbowl.h:809`). With ~1354 legal actions per setup decision, "how many placements do I have left" is a first-order feature and it is invisible.
- `KICKOFF` phase 5 Solid Defence: `f->x` = remaining fresh picks, `f->y` = action budget, `f->data` = selected bitmask (`proc_match.c:385-388`, `kickoff_legal` `fresh_ok = ko_popcount16(f->data) < f->x`).
- `KICKOFF` phase 6 Quick Snap: same fields.
- `KICKOFF` phase 7 Charge!: `f->x` = remaining activations.

The mask reveals *whether* a fresh pick is currently legal, but not that this is the last one.

**Cost: 1 byte (remaining primary budget, computed per window). Load-bearing: yes for SETUP; nice-to-have for the three kickoff events.**

### P1-7 — TEST reroll windows expose the Dodge destination only
`test_legal` (`proc_test.c:114-134`) offers `USE_REROLL{TEAM|PRO|SKILL}` / `DECLINE_REROLL`. Well covered already: `ctx[6]` = tested player, `ctx[8]` = the needed target with modifiers applied, `s[21]` = `bb_test_kind + 1`, `s[19]/s[20]` = the mover's `moved`/`rushes`, and `s[5]/s[6]` = reroll stocks. Which sources are on offer is in the mask, and `BB_PF_USED_SKILL_B` (Pro spent) is visible because all 16 `flags` bits are encoded (`bloodbowl.h:980-981` vs `bb_types.h:68-80`).

What is missing is the **spatial consequence** for kinds other than Dodge. The `ctx[9]/ctx[12]` fill is hard-gated to `top->b == BB_TEST_DODGE` (`bloodbowl.h:1041`), yet the parent MOVE frame's `x/y` is the destination for `BB_TEST_RUSH` and `BB_TEST_JUMP` too (`proc_move.c:770-771` for STEP, `:715-716` for JUMP), and the PASS frame's `x/y` is the target for `BB_TEST_PASS`. Rush is roughly as common as Dodge; a failed rush drops the player at the destination and turns the ball over (`proc_move.c:281-301`).

**Trap to respect when generalizing:** the parent MOVE frame's `x/y` is **stale** for `BB_TEST_STANDUP` (`proc_move.c:706`) and for the Jump-Up prone-block `BB_TEST_GENERIC` (`:812`, which parks the target in `f->data` bits 9–13 instead). Gate the generalization to `{DODGE, RUSH, JUMP}` plus PASS/PUSH, not "all kinds". `BB_TEST_PICKUP` needs nothing — the pickup square is the player's own square and the ball's, both already visible.

**Cost: 0 bytes (widen the existing `ctx[9]/ctx[12]` gate). Load-bearing: yes — free, and Rush is high-frequency.**

### P2-8 — MOVE's stashed target slot
`f->data` bits 9–13 hold a stashed player slot in three situations, and no board state changes when it is set:
- TTM/KTM mate pick, `BB_A_SPECIAL_TARGET arg=7` (`proc_move.c:878-881`) — the mate stays put, so the *next* decision (`BB_A_TTM_TARGET`, up to ~60 squares) is made without knowing which team-mate is being thrown, hence without their ST/AG/skills or whether they hold the ball.
- Jump-Up prone block target (`proc_move.c:811`).
- Blitz/Stab rush-for-block target (`proc_move.c:832, 953-956`).

Same shape as the block-dice fix that already shipped. Rare skills, so lower priority.

**Cost: 1 byte (ego slot + 1, gated on proc/kind/`MV_BLOCK_DONE`). Load-bearing: technically yes; frequency low.**

### P2-9 — `ktm_used` is the one once-per-turn flag not encoded
`s[8..13]` carry `blitz_used, pass_used, handoff_used, foul_used, ttm_used, secure_used` (`bloodbowl.h:1078-1083`). `m->ktm_used` (`bb_match.h:105`, latched at `activation_apply`) is simply omitted. Addressable via `DECLARE BB_ACT_KTM`. An inconsistency more than a defect — the mask covers the immediate window; it matters only for cross-activation planning. **Cost: 1 byte.**

### P2-10 — ACTIVATION negatrait gate reroll: the gate kind
`activation_legal` phase 2 offers `USE_REROLL(TEAM)` / `DECLINE`. The reroll's *stake* depends on `gk`: `BB_GATE_ROOTED` failure keeps the declared action but roots the player, while `BB_GATE_LOSE_ACT_AND_TZ` loses the activation and applies Distracted (`gate_fail`, `proc_turn.c`). Mostly derivable — Take Root vs Bone Head vs Really Stupid are distinct skills in the visible 12 skill-id bytes — and ambiguous only for a player carrying two gate traits. The target number is recoverable free by widening `ctx[8]` to also carry ACTIVATION's pending target. **Cost: 0–1 byte. Nice-to-have.**

### P3 — checked, genuinely does not matter (do **not** spend v6 bytes)
| Item | Why it is fine |
|---|---|
| **TOUCHBACK placement** (`kickoff_legal` phase 2) | Both forms are exactly addressable (`bbe_action_sq`, `bloodbowl.h:1244-1250`; tests `test_observation.c:198,227`). The ball is deliberately `OFF_PITCH` here (`kickoff_advance` phase 3), so zeroed ball coords are *correct*. Choosing the recipient is fully determined by the visible board. **Nothing missing.** |
| **KO_RECOVERY crowd flag** (`f->b == 1`) | Derivable: a crowd KO already moved the victim off the pitch (`proc_block.c:553`), so the victim's `location` byte `t[2]` discriminates it. |
| **PREGAME kick/receive** | `arg` semantics are constant; weather (`s[7]`), score, half all visible. |
| **FOUL argue-the-call** (`foul_legal`, `proc_block.c:1229-1234`) | A pure gamble with no hidden state; the fouler is `ctx[6]` (FOUL whitelisted, `:904`); bribes at `s[16]/s[17]` are auto-spent before the window. |
| **BLOCK Wrestle windows** (phase 4/5) | The face is Both Down by definition; `ctx[5]` = phase distinguishes attacker's from defender's window; both slots are in `ctx[6]/ctx[7]`. |
| **`BLK_DEF_CHOOSES` (2D-red)** | Derivable from `decision_team == me` (`ctx[10]`) against the attacker/defender slots. `ndice` is directly readable as the count of nonzero face bytes `ctx[13..15]`. |
| **The failed die value at a TEST reroll** | The reroll replaces it. Irrelevant. |
| **`skill_rr_used`** (`bb_types.h:96`) | Only gates legality at the current window, which the mask already covers. Exposing it for planning costs 64 bytes (2/player) — far too expensive for the value. |
| **`p_loner` / `p_bloodlust`** | The skill's *presence* is in the skill row; only the X+ parameter varies (Ogres 3 vs default 4). 32 bytes for a rare 1-pip difference. No. |
| **High Kick candidate identities** | Ordered by ascending slot over on-pitch + standing + unmarked — all three predicates are in the player rows (`t[2]`, `t[3]`, `t[23]`), so it is derivable in principle, just as an ordinal count. Covered free by the P0-1 option table; not worth its own mechanism. The landing square *is* visible (`ball.state == IN_AIR`, not `OFF_PITCH`, so `ctx[1]/ctx[2]` are written). |

## 4. Reverse errors and egocentric symmetry

I found **no** HOME/AWAY asymmetry bug. Specifically verified:
- `ctx[6]/ctx[7]` remap only for whitelisted procs (`bloodbowl.h:896-922`) — the M14 finding recorded at `:886-895` is correctly fixed, and the whitelist matches the engine: MOVE's `b` is a kind, TEST's `b` is a kind, CASUALTY/KO_RECOVERY's `b` is a flag, PREGAME/SETUP/KICKOFF/TEAM_TURN's `a` is a team id — all correctly excluded.
- `ctx[8]` carries `top->x` **only** for TEST, where it is a view-independent target number. For every other proc `top->x` is a square or a payload and is correctly suppressed.
- `ctx[13..15]` block faces are view-independent, and `bbe_public_block_face` (`:942-945`) collapses `PUSH_2` so the RNG's sixth side is not a side channel. Test `test_observation.c:64-66` asserts byte-identical faces across views.
- `bbe_compute_tz` (`:1777-1801`) computes counts in absolute coordinates; the away view mirrors by index at `:1108-1119`, and `t[23]` is view-independent by construction.
- `s[1..6, 14..18]` are all ego-indexed pairs. `s[8..13]` are single active-team flags, disambiguated by `ctx[11] = (active_team == me)` — consistent, if slightly indirect.

Two deliberate asymmetries, both correct: the v4/v5 probability planes are filled only for the deciding agent (`:1124`), and `team_id` is deliberately never encoded (`:1097-1099`).

**Encoded-but-not-addressable:** `s[16]/s[17]` bribes (auto-spent in `foul_advance`) and `ctx[9]/ctx[12]` (nonspatial window). Both are legitimate — they are consequence/probability information, not addressability. No reverse errors to fix.

## 5. Two non-obs side findings (report, do not bundle into v6)

1. **Redundant crowd-push actions.** `push_legal` clamps off-board crowd candidates into on-pitch coordinates (`proc_block.c:760-763`) while `push_apply` ignores `x/y` entirely for `arg == 1` (`:795-798`). Two crowd candidates off the same edge therefore become two distinct legal actions with identical behaviour, splitting the policy's probability mass. Harmless for correctness (the corner case where all three clamp identically produces byte-identical actions, which `bbe_decode` explicitly tolerates, `bloodbowl.h:1621-1623`) but it is avoidable dilution.
2. **The `CHOOSE_OPTION`-by-index encoding is the root cause of P0-1.** The 16-byte table is a workaround for an action encoding that throws away the referent. `BB_A_TOUCHBACK` already demonstrates the alternative — a dual-form type where a marker arg switches the referent to the square head (`bbe_action_sq`, `:1247-1249`). Giving player-valued `CHOOSE_OPTION` options a spatial form would cost **0 obs bytes** and be strictly more learnable, at the price of an action-space/BBP lineage break on top of the obs break. Worth deciding deliberately rather than by default.

## 6. Byte budget — does it fit 2782?

**Yes, with room to spare. No `OBS_SIZE` change, so none of the three sync points move** (`BBE_OBS_SIZE` `bloodbowl.h:111`, `OBS_SIZE` `binding.c:8`, `--obs-size` `training/convert_checkpoint.py:88`), and checkpoint input shape is preserved.

Current occupancy: player rows 24/24 full (`t[0..23]`), decision context **16/16 full** (`ctx[0..15]`, faces took the last three), scalars **22/48 used** (`s[0..21]`). `docs/obs-v5-spec.md:53-65` documents no reservation past `s[21]`, and `memset(o, 0, BBE_TZ_OFF)` (`bloodbowl.h:953`) guarantees `s[22..47]` are currently always zero.

**Free: 26 bytes at obs offsets 806–831.**

| # | Item | Bytes |
|---|---|---|
| P0-1 | `CHOOSE_OPTION` candidate → ego-slot table (16 entries) | 16 |
| P0-1/2/7 | Generalized pending-consequence square (widen `ctx[9]/ctx[12]` gate) | **0** |
| P0-2 | Window-flags byte (PUSH POW/FROM_BLITZ/SF_DECLINED; PASS inaccurate latch) | 1 |
| P0-3 | Declared `bb_act_kind + 1` from the nearest MOVE/ACTIVATION frame | 1 |
| P0-4 | Casualty roll A, roll B | 2 |
| P1-5 | Stack flags (`turnover`, `in_kickoff_charge`, `in_kickoff`) | 1 |
| P1-6 | Remaining placement budget (SETUP / KO 5,6,7) | 1 |
| P2-8 | Stashed MOVE target slot (TTM mate / Jump-Up / rush-for-block) | 1 |
| P2-9 | `ktm_used` | 1 |
| P2-10 | Widen `ctx[8]` to ACTIVATION's pending gate target | **0** |
| | **Total** | **24 / 26** |

2 bytes slack. If you take the action-space route from side finding 2 instead of the option table, the total drops to **8 bytes**, freeing 18 — enough to also carry the genuine nice-to-haves (`cheer_assist` ×2, `bonus_rerolls` ×2, `coach_ejected` ×2, `rerolls_start` ×2 = 8 bytes) plus real headroom for v7. I'd take that trade if you're willing to break the action lineage in the same revision; if not, ship the table and accept 2 bytes of slack.

## 7. Lineage warning — v6 will collide with v5 exactly as v5 collided with v4

Every fix above lands in bytes that are currently written as zero, so **obs-v6 will also be 2782 bytes with different semantics**. That is the same trap that cost the 12B-step run (`CLAUDE.md`, obs section) — three same-shape revisions in a row, distinguishable only by source/module provenance. Before this ships:

- bump `BBE_OBS_VERSION` to 6 (`bloodbowl.h:108`) and make `tools/checkpoint_lineage.py` refuse a v5 sidecar against a v6 module, since blob size will not catch it;
- update the `BB_CHECK_EQ(BBE_OBS_VERSION, 5)` assertion at `test_observation.c:47`;
- add a per-window encode test in the style of `test_observation.c:46` and `:83` for each new byte, including a negative test that the pending-square generalization stays **zero** for `BB_TEST_STANDUP` and the Jump-Up `BB_TEST_GENERIC`, where the parent MOVE frame's `x/y` is stale (`proc_move.c:706, 812`). That stale-square case is the one way this batch can silently ship a lie.

**Recommended v6 scope:** P0-1 through P0-4 plus P1-5 and P1-6 (the six that change behaviour), the two zero-cost gate generalizations, and P2-8/P2-9 only because they are 1 byte each and you are already paying the lineage break. Leave `skill_rr_used`, `p_loner`, and the per-player planning features out — they are 32–64 bytes for information the mask already supplies at the moment of decision.