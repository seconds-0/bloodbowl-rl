# bloodbowl-rl — Final Adversarial Review Report

Every finding below was independently traced against the current tree by 3 adversarial refuters (lenses: code-path verification, reachability, design-intent vs DECISIONS.md/CLAUDE.md) and survived at least 2 of 3. Line numbers re-verified against source at report time. Findings that were submitted multiple times by different reviewers are merged and marked.

## Executive summary

**27 distinct confirmed findings** (31 raw submissions, 4 merged as duplicates). **0 killed outright.**

| Severity | bug | perf | hardening | total |
|---|---|---|---|---|
| HIGH | 4 | — | — | **4** |
| MEDIUM | 18 | 3 | 2 | **23** |

Plus ~40 unverified LOW notes (not adversarially checked) listed at the end.

**The three most important items:**

1. **Crowd-push strips the ball from an unrelated carrier anywhere on the pitch** (`engine/src/proc_block.c:426`). Any crowd surf of a *non*-carrier silently clears the global ball carrier, leaving the ball ON_GROUND under a still-standing carrier who can never score or re-pick it up. Routine sideline play; corrupts possession state for the rest of the drive in a meaningful fraction of training matches. One-line fix.
2. **TTM/KTM mate slot clobbered by BB_A_JUMP → engine throws player slot 0, including off-pitch players → grid corruption** (`engine/src/proc_move.c:680` vs `:825-828`/`:816`). A legal declare→pick-mate→jump→throw sequence zeroes the stashed mate slot; `proc_ttm.c` does zero validation, clears `grid[stale x][stale y]` (erasing another on-pitch player's entry) and `bb_place`s a reserve/KO/CAS player onto the board. Memory-safe, invariant-blind — invisible to ASan and the fuzzer.
3. **Distracted is permanent for the drive for any player without a gate negatrait** (`engine/src/proc_move.c:899`, `proc_turn.c:357`; sole clear at `proc_turn.c:199` gated on `bb_hook_activation_gate >= 0`). Every Hypnotic Gaze victim (all three Vampire positionals carry GAZE) and every isolated Animal Savagery lash-out loses TZ/catch/assist/Block/Wrestle for up to 16 team turns instead of one activation. A learnable, drive-long debuff-stacking exploit in self-play.

All four HIGHs share a property worth internalizing: they produce *internally consistent but wrong* states, which is exactly the class the current validation stack (ASan/UBSan, 140K-match legality fuzzing, ball-carrier invariants, golden traces that encode the buggy behavior) is structurally blind to. The Phase-4 FUMBBL differential would catch most of them; fixing them first will keep that signal clean.

---

## HIGH

### H1. Crowd push calls `bb_drop_ball` unconditionally — strips an unrelated carrier
`engine/src/proc_block.c:426` — bug — **upheld 3/3**

`push_advance` phase 2, `PSH_CROWD` branch (proc_block.c:420-431): `had_ball` is computed from the pushed player's flags (:424) and correctly gates the THROW_IN (:429-431), but `bb_drop_ball(m)` at :426 is unconditional. `bb_drop_ball` (bb_match.c:95-101) operates on the **global** `m->ball.carrier`: if the surfed player is not the carrier but anyone else is, that carrier loses `BB_PF_HAS_BALL`, `ball.carrier` becomes `BB_NO_PLAYER`, and the ball goes `BB_BALL_ON_GROUND` at the carrier's own square — no bounce, no turnover, no way to re-pick it up while standing there, and `bb_check_td` (bb_match.c:107-115) returns false forever. The attacker-carrier-surfs-a-defender case strips the attacker himself and orphans the ball after follow-up (the phase-3 ball tracking checks the now-cleared flag).

Every other `bb_drop_ball` site in the engine guards on the affected player's flag (proc_block.c:646, :680, :785, :964, :1003; proc_ttm.c; proc_move.c) — :426 is the lone unguarded exception. Reachable via `push_legal` arg=1 crowd actions (proc_block.c:561-573), including chain pushes. D11 covers crowd dice *order* only.

Why nothing caught it: the corrupted state satisfies the fuzzer's only ball invariant (fuzz_match.c:41-48 fires only when `state == BB_BALL_HELD`); the three crowd-push tests field either no carrier or the surfed player as carrier.

**Fix:** `if (had_ball) bb_drop_ball(m);` at proc_block.c:426. Unit test: surf a non-carrier while a teammate elsewhere holds the ball; assert carrier keeps `BB_PF_HAS_BALL` and `ball.state == BB_BALL_HELD`.

**Consensus notes:** all three refuters verified the full chain including downstream non-repair (`bb_remove_from_pitch`, INJURY proc never re-give the ball). One nit: arg=1 emission is per off-pitch candidate when no empty on-pitch square exists, not strictly "all three off-pitch" — immaterial.

### H2. Animal Savagery lash-out KNOCKDOWN deferred until after the whole declared action
`engine/src/proc_turn.c:355` — bug — **upheld 3/3**

`activation_apply` pushes the mate's KNOCKDOWN (:355) *before* pushing the MOVE frame (:385), leaving the LIFO stack `[..., ACTIVATION, KNOCKDOWN(mate), MOVE]`. The entire Move/Block/Blitz resolves first. Consequences, each verified:

- **Every lash-out:** the "downed" mate is still Standing during the action — exerts TZ/assists (bb_match.c:134-140), can legally receive a hand-off (bb_can_catch, bb_match.c:156-162); the deferred knockdown then bounces the ball and latches a turnover (`BB_KD_TTM_LANDING` cause, proc_block.c:655-657).
- **Off-pitch firing:** if the mate is chain-pushed into the crowd mid-action (KO/CAS/RESERVES), `knockdown_advance` (proc_block.c:627-688) has no `BB_LOC_ON_PITCH` guard — sets PRONE on an off-pitch player and rolls ARMOUR→INJURY; the KO branch's `else p->location = BB_LOC_KO` (proc_block.c:827-828) overwrites a CAS location, and END_DRIVE's KO recovery (proc_match.c:694-696) **resurrects the casualty to RESERVES on 4+**.
- **TD discard:** `touchdown_advance` (proc_match.c:667-674) truncates the stack to the MATCH frame, silently deleting the pending KNOCKDOWN — score a TD, the lash-out never happens. An RL-exploitable loophole.

Rat Ogre (ANIMAL_SAVAGERY) is in three default rosters (gen_teams.c:65, :259, :292), so fuzz and training hit this constantly; the lash-out fires 50% per non-Block declaration with an adjacent standing mate. The project's own rules mirror says the chosen player is knocked down *immediately*; the codebase's own resolve_face shows the author knows the correct reverse-push LIFO idiom (proc_block.c:307-310). No DECISIONS.md cover (D21 omits AS timing).

**Fix:** push the KNOCKDOWN *after* the MOVE frame so it resolves first (a resulting turnover then correctly aborts the action via the `m->turnover` check at proc_move.c:375-378). Hardening: make `knockdown_advance` a no-op when `m->players[f.a].location != BB_LOC_ON_PITCH`.

**Consensus notes:** 3/3, every sub-claim traced. One evidence nit (proc_block.c:288-306 reads live skill/Distracted flags, not stance — the substantive point stands via bb_exerts_tz/bb_can_catch). The stray PRONE stance on an off-pitch player is transient (drive-end reset); the durable corruption is the CAS→KO→RESERVES resurrection plus the every-occurrence ordering divergence.

### H3. BB_A_JUMP clobbers the stashed TTM/KTM mate slot → throws slot 0, grid corruption
`engine/src/proc_move.c:680` — bug — **upheld 3/3**

The picked team-mate is stashed in MOVE-frame data bits 9-13 (`BB_A_SPECIAL_TARGET` arg 7, proc_move.c:825-828). `BB_A_JUMP` unconditionally rewrites those same bits with the pending rush count (:680), which ends at 0. The interleave is legal: TTM/KTM activations may move (:421), the just-picked **Prone** Right-Stuff mate itself qualifies as the jump-over target (:439-462), and `BB_A_TTM_TARGET` stays offered because `MV_BLOCK_DONE` is set-only. The throw then reads `mate = (f->data >> 9) & 31` = 0 (:816) and pushes `BB_PROC_TTM` for **home slot 0** with zero validation — no team/adjacency/Right-Stuff/location check anywhere in proc_ttm.c.

If slot 0 is off-pitch: `bb_remove_from_pitch` never resets x/y (bb_types.h documents them stale), so proc_ttm.c:84's `m->grid[ox][oy] = 0` erases whichever player now occupies that square, then `bb_place` (proc_ttm.c:157) teleports the off-pitch player onto the board. All indices in-bounds → ASan silent; fuzzer checks only ball invariants → fuzz silent. Even the benign on-pitch case throws the wrong player — an *opponent* when the away team throws (`BB_TEAM_OF(0) == HOME`). 17 TTM + 18 Right Stuff positions across default rosters; zero TTM test coverage.

**Fix:** re-validate the mate at `BB_A_TTM_TARGET` time (same team, adjacent, Right Stuff, ON_PITCH; `BB_STATUS_ERROR` otherwise), and/or stop offering bits-9-13 writers (BB_A_JUMP) once `MV_BLOCK_DONE` is set for kind TTM/KTM. Regression test: declare → pick mate → jump → throw; assert the picked mate is thrown and the grid stays consistent.

**Consensus notes:** 3/3. Refuters confirmed bits 9-13 are an undocumented third overload of a field documented only as "rush count" (proc_move.c:34 comment), and that never-deployed reserves sit at memset (0,0) — a *valid* pitch square, so the corruption mechanism holds in every variant.

### H4. Distracted never clears for players without an activation-gate negatrait
`engine/src/proc_move.c:899` (set), `engine/src/proc_turn.c:199` (only clear) — bug — **upheld 3/3 + 3/3** (two independent submissions, merged)

Exhaustive write-inventory: `BB_PF_DISTRACTED` is set at proc_move.c:899 (Gaze 3+), proc_turn.c:190 (gate failure), proc_turn.c:357 (Savagery, no mate). It is cleared **only** at proc_turn.c:199 — nested inside `if (bb_hook_activation_gate(...) >= 0 ...)` (:180-181), reachable only for BONE_HEAD/REALLY_STUPID/UNCHANNELLED_FURY/TAKE_ROOT carriers (skills_core.c:88-129) — and at the drive-end `p->flags = 0` (proc_match.c:697). `turn_start`'s clear mask (proc_turn.c:21-22) and the activation wrap-up (:208-211) never touch it. Engine's own doc says "until end of next activation" (bb_types.h:70); the mirror and May-2026 FAQ say the condition is removed when the player is next activated, before declaring.

Effect: a gazed gate-less player (i.e. nearly every Gaze victim) loses TZ (bb_match.c:138), catching (bb_match.c:160), assists (bb_skills.c:60), Block/Wrestle/Dodge block-face effects (proc_block.c:288-306, :325) for the rest of the drive — up to 16 team turns. GAZE has no once-per-turn latch, so a Vampire side (~6.6% of procgen episodes; all three positionals carry it, gen_teams.c:299-301) can stack drive-long TZ removal across multiple defenders. Rat Ogre self-inflicts the same via Savagery.

**Fix:** clear `BB_PF_DISTRACTED` unconditionally at the **start** of activation (phase 0, next to the `BB_PF_EYE_GOUGED` clear at proc_turn.c:176) — refuters note start-of-activation matches the FAQ, not the wrap-up branch one submission suggested. The gate-failure re-set at :190 already runs after that point, so gate semantics survive; delete the now-redundant :197-200 clear. Unit tests: gazed player activates → flag gone; regains TZ next turn.

**Consensus notes:** 6/6 across both submissions. Bonus from a refuter: TAKE_ROOT carriers also never clear (the `gk != BB_GATE_ROOTED` guard skips them) — the bug is slightly *worse* than claimed.

---

## MEDIUM — engine rules bugs

### M1. Pro re-roll unreachable whenever it's the only re-roll source
`engine/src/proc_test.c:51` — **upheld 3/3**

`test_advance`'s window gate is `team_rr || skill_rr` (:52); Pro registers no reroll hook (only DODGE/SURE_FEET/SURE_HANDS/PASS/CATCH exist, skills_core.c:13-22), and `team_reroll_available` (:29-33) requires rerolls>0 **and** own turn. So a Pro player with 0 team re-rolls (routine late-half) has a failed test popped with no decision — even though `test_legal` (:93-97) offers `BB_RR_PRO` and `test_apply` (:119-128) fully implements it whenever the window happens to open for another reason. Default-roster carriers: Imperial Thrower/Noble Blitzer (gen_teams.c:153/:155); Pro is also in the General random-skill row.
**Fix:** add a `pro_rr` term to the gate (`!(f->data & TF_TEAM_USED) && bb_has_skill(..., BB_SK_PRO) && !(flags & BB_PF_USED_SKILL_B)`). **Refuter caveat:** Pro is once-per-activation and rules-wise unusable outside the player's own activation — add an is-own-activation guard rather than mirroring `test_legal`'s current (already over-broad) condition. Sibling gap noted: the block reroll window (proc_block.c:233) offers only `BB_RR_TEAM`.

### M2. Leader's per-half re-roll wiped by the Brilliant Coaching clamp at first drive end
`engine/src/proc_match.c:705` — **upheld 3/3**

PREGAME grants Leader via `m->rerolls[t]++` (:115) without touching `rerolls_start`; END_DRIVE clamps `rerolls` down to `rerolls_start` after **every** drive (:703-706); the only re-grant is the half-time branch (:74-87, whose own comment says "per-half"). Any half with a mid-half TD silently deletes an unused Leader re-roll for the rest of the half. Internal inconsistency provable without the rulebook (comments at :110 and :76 vs the clamp); `BB_RR_LEADER` exists in bb_actions.h but is never wired — separate tracking was planned.
**Fix:** track the Leader bonus separately (flag per team) or clamp to `rerolls_start + (leader alive && unused ? 1 : 0)`. Test: TD ends drive 1 with bonus unused → still available in drive 2.

### M3. `ktm_used` never reset — first Kick Team-Mate disables KTM for both teams for the match
`engine/src/proc_turn.c:12` (turn_start) — **upheld 3/3**

`turn_start` (:9-33) resets blitz/pass/handoff/foul/**ttm**/secure/turnover but not `ktm_used`; the only zeroing is match-init memset. It is also a single field shared by both teams, latched on declaration (:382) and gating legality (:295) — contradicting bb_match.h:101's own "its own per-turn budget". Reachable in the committed Ogre-vs-Snotling golden (Runt Punter, gen_teams.c:212).
**Fix:** add `m->ktm_used = 0;` to turn_start. **Note:** the vendored training copy `vendor/PufferLib/ocean/bloodbowl/engine/proc_turn.c` has the identical defect — re-sync after fixing.

### M4. Team re-rolls offered during kickoff resolution
`engine/src/proc_test.c:32` — **upheld 3/3**

MATCH phase 2 sets `active_team = 1 - kicking_team` **before** pushing KICKOFF (proc_match.c:39-40), so for the entire kickoff (landing catch, bounce catches, High Kick catch → TEST at proc_ball.c:149) `team_reroll_available` returns true for the receiver. BB2025: team re-rolls only during your own team turn; the kick-off precedes turn 1. The engine already has the exact predicate, used for throw-in suppression (`bb_in_kickoff`, proc_match.c:356-361; consumed at proc_ball.c:34). Existing kickoff tests are blind (fixtures memset rerolls to 0).
**Fix:** `&& !bb_in_kickoff(m)` in `team_reroll_available`. Test: failed kickoff catch with rerolls in stock → no decision window.

### M5. POW/Stumble knockdowns drop the causer — Mighty Blow/Claws/Saboteur dead on the main path
`engine/src/proc_block.c:518` — **upheld 3/3**

push_advance phase 5 resolves POW with `bb_knockdown(m, def, BB_KD_BLOCK, 0)` — the no-causer variant (y=0 → `causer = -1` in armour_advance, proc_block.c:697). All causer-gated effects are skipped: Saboteur gate (:640), MB-on-armour (:737-745), Claws 8+ (:747-751), MB-on-injury (:790-792). Only ATTACKER_DOWN (:270) and BOTH_DOWN (:309-310) carry the causer via `bb_knockdown2` — but an MB/Claws attacker virtually always picks POW/Stumble, so the skills are near-inert in normal play despite D16's documented MB auto-policy and D21's "Saboteur always triggers". Git archaeology (one refuter): commit cc9c9a7 upgraded only ATTACKER_DOWN/BOTH_DOWN to `bb_knockdown2` and missed the POW site — incomplete wiring, not a decision.
**Fix:** snapshot `int att = f->a;` before the pop in phase 5 (PSH_POW exists only on root non-chain frames, where f->a is the attacker) and call `bb_knockdown2(m, def, BB_KD_BLOCK, 0, att)`. Tests: MB armour conversion and Claws 8+ through a chosen POW. **Refuter corrections:** the Dirty Player and chain_mod legs of the original claim are vacuous (DP is foul-path-only and the foul path passes the causer correctly at :934; no skill registers armour/injury hooks today) — the MB/Claws/Saboteur core stands.

### M6. Frenzy second block is dead wiring
`engine/src/proc_block.c:50` — **upheld 3/3**

`BLK_FRENZY_2ND` (bit 15) is read and propagated (:316, :328, :338 → PUSH bit 7) but **never set** anywhere (repo-wide grep + git pickaxe across all history: born dead in commit 9063f8f, whose message claims "forced follow-up + second block" but whose diff contains only the follow-up). PUSH bit 7 has no reader (PSH_* enum stops at bit 6), and the phase-0 data rebuild (:188) preserves only `BLK_IS_BLITZ`, so the flag couldn't survive even if set. Frenzy currently only forces the follow-up (phase 3, :492-504); the mandatory second block — required by the mirror and the project's own bb-rules reference — never happens. 12 default-roster player types carry Frenzy; zero frenzy tests exist.
**Fix:** implement it (after a non-POW frenzy push with the defender still standing and attacker adjacent, push a second BLOCK; set `BLK_FRENZY_2ND` *after* the :188 rebuild point; use PUSH bit 7 to stop a third) — and mind the Blitz movement/Rush cost on the second block — or delete the dead flags and log the gap for the FUMBBL differential. Add a double-block spec test.

### M7. Inaccurate pass landing empty never takes its final bounce
`engine/src/proc_ball.c:59` — **upheld 2/3** (third vote not recorded against it; both recorded votes upheld)

After the 3-hop pass-flight SCATTER, an empty landing square "comes to rest (scatter and bounce alike)" (:59) — directly contradicting the file's own header contract (:18-20, "empty square after a SCATTER → one final bounce") and the mirror's RESOLVE PASS ACTION ("If the ball lands in an unoccupied square, then it will Bounce"). The engine already bounces ACCURATE passes to empty squares (pass_resolve_flight, :231) — an internal asymmetry with no rules basis. D14's "no bounce" note is throw-in-scoped only. Every inaccurate pass to open ground ends one D8 hop short → guaranteed dice/position divergence in the Phase-4 differential.
**Fix:** when `!is_bounce` and the post-hop square is empty: `bb_ball_to(m,x,y); bb_push(m, BB_PROC_SCATTER, 0, 1, x, y);`. **Remediation caveat (refuters):** 2-4 currently-green tests pin the buggy behavior (test_rules_ball.c ~105-121, ~170-186, ~322-340, ~424-433, scripted with exactly 3 scatter dice) and must be corrected toward the mirror; goldens regenerate per D6.

### M8. Side Step with no free square hands the attacker's push choice to the defending coach
`engine/src/proc_block.c:407` — **upheld 3/3**

push_advance phase 0 assigns decision ownership to the defender on skill possession alone (:402-407, no availability check); push_legal's Side Step branch falls through to the normal three candidates when no adjacent square is free (:548) — which in that situation are *always* chain/crowd entries (:550-573), the highest-stakes choice in the game, now made by the wrong coach. The mirror: "If there are no adjacent unoccupied squares, then this Skill cannot be used." The inline comment at :404-406 itself presumes a free square. bb_apply validates membership only; the binding routes the prompt to `decision_team`'s policy — so the defending policy genuinely picks crowd-vs-chain for the attacker, also corrupting decision_team attribution for BC extraction.
**Fix:** compute availability before assigning ownership (`side_step = side_step && exists adjacent on-pitch empty square`); fall back to `m->active_team`. Mirror the same predicate in push_legal so legal/advance can never disagree.

### M9. Stunty dodger vs Titchy marker: double cancellation → net +1
`engine/src/skills_devious_traits.c:39` — **upheld 3/3**

Both skills cancel the *same* base -1: STUNTY's own-mod refunds the full destination TZ count, Titchy markers included (skills_core.c:175-178; bb_tackle_zones has no skill filter), and the TITCHY aura adds another +1 per marking Titchy opponent (:39-49). `bb_hook_mods` sums both — net +1 where two "withhold the -1" effects must combine to 0. Violates the aura's own documented invariant ("no -1 to cancel, therefore no +1", :33-38). Carriers of both skills on stock rosters (Snotling/Gnoblar linemen, Beer Boar, Fungus Flinga); the existing Titchy tests use only skill-less dodgers.
**Fix:** aura-side guard: `if (bb_has_skill(&m->players[c->player].skills, BB_SK_STUNTY)) return 0;`. **Refuter nuance:** the [2,6] clamp absorbs the error for some AG2+ dodgers; the real shift is e.g. Goblin/Halfling (Stunty, no Titchy) dodging into a single Titchy TZ: buggy 2+ vs correct 3+.

### M10. Diving Tackle fires on dodges that don't leave the diver's TZ
`engine/src/proc_move.c:217` — **upheld 3/3**

The D19 auto-interrupt scans divers adjacent to the mover's **current** square (:217-229) and never consults the destination (`f->x/f->y`, live in the frame). A dodge between two squares of the same DT player's TZ wrongly flips a passing dodge to a fail (:230) → knockdown + turnover + prone diver. The parallel Shadowing code performs exactly the missing check (proc_move.c:80), and FFB — the project's stated layer-7 oracle — defaults `DIVING_TACKLE_LEAVING_TZ_ONLY = true`. Dwarf Blitzers carry DT natively (gen_teams.c:83, :225); ~1/3 flip chance per within-TZ dodge next to one.
**Fix:** in the diver scan, `if (bb_adjacent(m->players[dts].x, m->players[dts].y, f->x, f->y)) continue;`. **Refuter note:** the BB2025 wording has genuine ambiguity (Jervis applies no filter), but FUMBBL's default — the ground truth for the differential — is the leaving-TZ-only reading.

### M11. Catch reroll + Nerves of Steel incorrectly apply to interception attempts
`engine/src/skills_core.c:22` — **upheld 3/3**

Interceptions are dispatched as `BB_TEST_CATCH` with `ctx.other = thrower` (proc_ball.c:355-366). `bb_hook_reroll` sees only the kind (bb_hooks.c:55-66), so `BB_SKILL_REROLL(CATCH, ...)` grants interceptors a free reroll; the NoS mod (skills_core.c:61-65) gates only on PASS/CATCH and cancels the interceptor's per-marker penalty (:360). BB2025 treats Intercept as distinct (Catch text: "attempting to Catch the ball"; NoS has no Intercept clause; DP/Extra Arms name Intercept separately). The in-source NoS comment quoting "...or attempt to Intercept" is a stale BB2020-style misquote of the mirror. STUNTY and VLL already use the `other != BB_NO_PLAYER` discriminator — internal inconsistency, not design. Single-candidate intercepts auto-fire (D10), so this is exercised regularly (~1.7-1.8x interception odds for Catch carriers, not the claimed 2x).
**Fix:** NoS: `if (c->kind == BB_TEST_CATCH && c->other != BB_NO_PLAYER) return 0;`. Reroll: pass the ctx into `bb_hook_reroll` (preferred — a new `BB_TEST_INTERCEPT` kind would be bit 9 of the uint8 `reroll_kinds`/`skill_rr_used` masks, see LOW notes). Test: Catch-skill interceptor gets no reroll; marked NoS interceptor keeps its -1.

### M12. Disturbing Presence can never fire on Throw Team-mate
`engine/src/skills_core.c:71` — **upheld 3/3**

The BB2025 DP text explicitly covers "Throw Team-mate Action", but `ttm_advance` computes the PA test fully inline (proc_ttm.c:59-75 — range, marking, Strong Arm, direct `bb_d6`; verified: zero `bb_ctx`/`bb_hook_mods`/`BB_PROC_TEST` in the file), and the DP aura filter accepts only PASS/CATCH (:72). No `BB_TEST_TTM` kind exists, so no registered mod, aura, or reroll window can touch a TTM throw at all. DP carriers exist on base rosters that meet TTM teams routinely ('Ooligan on Goblin — a TTM-core roster — Yhetee, Bloater/Rotspawn, Flamesmith). The project's own bb-rules reference documents DP as covering TTM.
**Fix:** add a `BB_TEST_TTM` kind, build a ctx at proc_ttm.c:59 and route through `bb_hook_mods`; extend the DP filter (keep Accurate/Cannoneer/Pass-reroll excluded — TTM is not a Pass Action). This also creates the seam for the missing team-reroll window on TTM tests. Test: opposing DP within 3 squares → one pip worse.

### M13. Big Hand fails to cancel the Pouring Rain pickup modifier
`engine/src/skills_core.c:41` — **upheld 3/3**

BB2025 Big Hand: "ignores **all** negative modifiers when attempting to pick up the ball." The hook returns only the marking TZ count (:41-44; its comment paraphrases "Marking modifiers", diverging from the mirror), and both pickup sites apply `if (weather == RAIN) mod -= 1` **after** `bb_hook_mods` returns (proc_move.c:116-122, :194-197) — structurally hook-invisible. Marking and rain are the only negative pickup modifiers in the engine, so the divergence is exactly the rain case (AG3 Big Hand in rain: 4+ instead of 3+). Reachable: Big Hand is mutation-row index 0 in procgen advancement; rain via the pregame 2d6 weather roll and the implemented Changing Weather kickoff.
**Fix:** apply the weather -1 before the hook call and have BIG_HAND return `marking_tz + (weather==RAIN ? 1 : 0)`, or add a `bb_pickup_ignores_negmods()` query consulted at both sites. Test: Big Hand pickup, double-marked, in rain → plain AG target.

## MEDIUM — RL binding bugs

### M14. Obs bytes b[6]/b[7] ego-remap team ids and flags as if they were player slots
`puffer/bloodbowl/bloodbowl.h:223-224` (comment :218) — **upheld 3/3**

The encoder treats top-frame a/b as slots whenever `< BB_NUM_PLAYERS` (32). But the four highest-frequency decision procs store **team ids** (0/1) in `a`: PREGAME (proc_match.c:121-123), SETUP (:34), KICKOFF (:40), TEAM_TURN (:61, surfacing every ACTIVATE decision via proc_turn.c:100); CASUALTY puts a flag in `b` (proc_block.c:868). 0/1 pass the `< 32` check and get XOR-16 remapped: at its own turn the home agent sees `b[6] = 1` ("my player 0") and the away agent sees `b[6] = 18` ("opponent row 17") for the *same semantic state* — breaking the egocentric invariant on the modal decision type and aliasing genuine slot encodings used by BLOCK/TEST/PUSH on the same channel. The justifying comment at :218 ("Frame a/b are player slots in every proc that surfaces decisions") is simply false.
**Fix:** per-proc whitelist (`bbe_frame_a_is_slot(proc)` / `_b_is_slot`) emitting 0 for PREGAME/SETUP/KICKOFF/TEAM_TURN a and non-slot b params; or store `BB_NO_PLAYER` in non-slot frame params engine-side. Test: `b[6] == 0` at an ACTIVATE decision for both agents.
**Consensus notes:** 3/3; refuters confirmed this is a residual of the previously-fixed ego-arg HIGH class (action side has `bbe_arg_is_slot`, obs side has no analogue) and that D22's design doc specifies slots, not team ids.

### M15. CHOOSE_OPTION args that are player slots bypass the ego remap
`puffer/bloodbowl/bloodbowl.h:277` (`bbe_arg_is_slot`) — **upheld 3/3**

Two decisions emit `BB_A_CHOOSE_OPTION` with raw player-slot payloads to the coach who owns those players: the multi-candidate interception pick (proc_ball.c:349, defending coach per :296-297) and High Kick placement (proc_match.c:595, receiving coach). `bbe_arg_is_slot` lists only SETUP_PLACE/SETUP_REMOVE/TOUCHBACK/ACTIVATE, so away-team slots 16..31 pass through `bbe_action_arg` (:303-309) verbatim — the away agent must select *its own* interceptor via arg indices 16-31, the range that means "opponent" in its obs rows and every other slot-typed action; home gets 0-15 for the identical decision. Encode and decode share the mapping, so nothing is illegal — the semantics just flip by side, degrading the weight-shared policy on every multi-candidate interception and every High Kick (~11% of kickoffs). Decisive inconsistency proof (refuter): the *same kickoff proc's* touchback path emits identical raw receiving-team slots via `BB_A_TOUCHBACK` — which **is** remapped.
**Fix:** cleanest is engine-side — emit the candidate index (0..nc-1) per bb_actions.h's documented CHOOSE_OPTION contract and resolve the slot in pass_apply/kickoff_apply (no binding change needed). Otherwise consult the top proc in `bbe_action_arg`/`bbe_decode`. Both-sides test: interception candidate's arg-head index equals its obs row.

## MEDIUM — performance

### P1. Legal set enumerated twice per applied action (bb_apply revalidation); worst case is setup
`engine/src/bb_match.c:288` + `engine/src/proc_match.c:295` + `puffer/bloodbowl/bloodbowl.h:135-139` — **3 overlapping submissions, each upheld 2/3** (merged)

Mechanics verified by all refuters: `bbe_decode` returns only members of `env->legal` (all return paths), `env->legal` is refreshed from the identical state, all 13 legal enumerators are pure functions of `const bb_match*` — so `bb_apply`'s internal re-enumeration (16KB stack buffer + linear `bb_action_eq` scan, bb_match.c:287-295) provably reproduces the list and the membership check cannot fail on the RL or fuzz paths. Setup is the expensive case: `setup_legal` is 16 slots × 195 own-half squares = 3,120 iterations emitting ~2-3K actions, paid twice per placement, with D1's 64-action budget making setup decisions plentiful under untrained policies; `pass_legal` re-runs the 64-step interception ruler march inside the revalidation.

**The recurring dissent (one REFUTED vote on each submission) is substantive and should gate the fix:** the check is the *documented* mask-soundness invariant (bb_match.c:286 comment; bb_match.h:142 API contract; validation-architecture invariant #6), the binding's defensive episode-reset only has teeth because bb_apply validates, and the measured budget already includes the duplication with ~4x headroom over the 500K target (STATUS.md: 206K env-steps/s/core) while training is policy-forward-bound. **Recommendation:** treat as an optional optimization, not a defect. If pursued: add `bb_apply_trusted` (or an index-based variant) used *only* by `c_step`, keep the checked `bb_apply` as the default for replay/tests, and do **not** convert the fuzzer — the in-apply check is the only mechanism that fuzzes enumerator determinism. A binding-side setup fast-path that re-derives legality conditions is the one variant to avoid (second source of truth — the exact divergence class the prior review fixed as HIGH).

### P2. `bb_hook_mods` aura scan walks all 32 players' skill bitsets for 3 registered aura hooks
`engine/src/bb_hooks.c:37-51` — **upheld 3/3**

Every test-modifier query of any kind runs the 32-slot loop with a per-bit `bb_next_skill` walk and `bb_hooks[sk].aura` probe. Exactly three aura hooks exist (DISTURBING_PRESENCE: PASS/CATCH; TITCHY: DODGE; PREHENSILE_TAIL: DODGE/JUMP), so for RUSH/PICKUP/STANDUP/GENERIC the whole scan is provably dead work, and for DODGE only 2 of 108 skills are live. Call sites are the hottest paths (every dodge/pickup/rush/jump/stand-up/pass/catch/interception; 13+ sites verified).
**Fix:** at `BB_SKILL_AURA` registration, union an `aura_kinds` mask and a global `bb_aura_mask` skillset; early-out the loop when the ctx kind has no registered aura, and skip players whose `skills & bb_aura_mask` intersection is empty. **Refuter calibration:** the engine is already 4x over its perf target, so this mostly buys fuzz/replay-differential throughput (~3-5% of env step time); one refuter flags that duplicating kind checks in a registration mask is a silent-divergence footgun — the per-player skillset∩mask AND alone is the safe portion. Note the stale comment at skills_devious_traits.c:21-24 (see LOW) claiming rush sites don't consult hooks — they do.

### P3. `bb_cover()` counters: non-atomic shared writes across OpenMP env workers
`engine/include/bb/bb_hooks.h:120` / `engine/src/bb_hooks.c:6` — **two submissions: upheld 2/3 and 3/3** (merged)

`bb_skill_exercised[]` is one process-global array; the binding amalgamates bb_hooks.c into the single TU, and the Linux CUDA path steps 2048 envs under `#pragma omp parallel for num_threads(8)` (vecenv.h:291-294; build.sh compiles with -fopenmp; D24's no-OpenMP workaround is Mac-only). Concurrent unsynchronized `uint64_t++` from 8 threads on the same cache lines is a genuine C11 data race (UB, lost increments) plus coherence traffic, never exercisable by the single-threaded fuzzer/ASan. **Refuter corrections that trim the claim:** nothing in the training process ever *reads* the counters (layer 6 is the standalone sequential `tools/coverage_report` binary playing its own matches), so the "corrupted coverage metric" leg is dead — the surviving substance is formal UB + modest cache ping-pong (low single-digit % of step cost at worst), and the side-finding that `bb_hook_reroll` covers on *query* rather than on use (inflating counts and mutating globals from const-qualified `bb_legal_actions`).
**Fix:** `#ifdef BB_COVERAGE` around bb_cover's body (coverage builds define it; the binding build doesn't) — zero hot-path cost, race gone. Independently, move the reroll cover to the consumption site (test_apply skill-reroll branch).

## MEDIUM — hardening

### Hd1. `bb_match_init` indexes `bb_team_defs[]` with unvalidated team ids; replay loader feeds it file-derived values
`engine/src/bb_match.c:199` — **upheld 2/3**

`bb_replay.c:101-104` parses home/away with no range check (and int64→int truncation: 4294967299→3); `test_golden.c:71` checks only `home < 0` — away is never checked at all (a missing key yields -1 → `bb_team_defs[-1]`); `bb_match_init` stores `(uint8_t)`-truncated ids but indexes the 30-entry array with the full int (:199, :236-237). Every other caller mods by `BB_TEAM_COUNT`, confirming an expected-but-unenforced invariant.
**Consensus notes:** the dissenting refuter proved no untrusted input channel exists *today* (goldens are repo-committed; training uses procgen; normalize_replay.py emits a different schema with no C consumer) — so this is defense-in-depth for the Phase-4 FUMBBL/BC harness, not a present-tense vulnerability. **Fix:** validate `(unsigned)id < BB_TEAM_COUNT` in `bb_match_init` (memset + `BB_STATUS_ERROR` on failure — callers handle ERROR), and reject out-of-range INIT records in replay loaders. Do this before the Phase-4 harness lands, since a normalizer bug (e.g. -1 unmapped-roster sentinel) flows straight into the OOB index.

### Hd2. Fuzzer never exercises `bb_match_init_random` — the exact init path every training reset uses
`engine/tests/fuzz_match.c:27` — **upheld 3/3**

The ~140K-match sanitized fuzz corpus covers only `bb_match_init` default squads; the env resets exclusively through procgen (bloodbowl.h:351), which produces states the fuzzer never sees: 11-14-player squads, pre-game CAS, maxed positionals, 2-4 rerolls, and advancement skills — including Multiple Block and Pile Driver from `bb_random_skill_table` (gen_skills.c:119/:122), which have **zero hooks/procedures anywhere** (grep-verified), invalidating D21's "no default-roster carriers" deferral premise every time they're granted (silently inert). Procgen's only full-game test coverage is 12 matches (test_match.c:160-186). The standalone driver does run procgen end-to-end, but unsanitized and without invariant aborts.
**Fix:** add an init-mode byte to fuzz_match.c (procgen mode seeds a separate `bb_rng` from input bytes), keeping the same aborts. Separately reconcile D21: implement MB/PD decision windows or update D21 explicitly — do **not** edit `gen_skills.c` directly (codegen'd from spec; one refuter flagged the original "remove from table" fix variant as a design-intent violation).

## MEDIUM — test & tooling integrity

### T1. `fx_player`'s memset makes every fixture placement wipe `grid[0][0]`
`engine/tests/bb_fixtures.h:50` — **upheld 2/3**

`memset(p, 0, ...)` sets `location = 0 = BB_LOC_ON_PITCH`, `x = y = 0`; `bb_place`'s stale-square cleanup (bb_match.c:52-54) then clears `grid[0][0]` on every call. Live trigger: test_rules_movement.c:137 places the mover at (0,0), line 138's second fixture call erases its grid entry — the test passes green while asserting against a corrupt position. The dissenting refuter proved the corruption is outcome-neutral at the single existing trigger site and unreachable from production/fuzz/training (fixtures are test-only) — valid as test-infrastructure hygiene, not state corruption.
**Fix:** `p->location = BB_LOC_ABSENT;` after the memset, before `bb_place`. Add a fixture self-test (place at (0,0), place another, assert `grid[0][0]` still maps to the first).

### T2. `build_dist_dump` prefers stale `build/main/obj` over `build/obj`
`validation/conformance.py:176-181` — **upheld 2/3**

First-hit-wins over `("build/main/obj", "build/obj")` with no freshness comparison; nothing in the repo rebuilds build/main (Makefile BUILD defaults to `build`), and the staleness check (:186-189) compares only against the *chosen* dir. On disk, build/main is stale by exactly commit 1533627 — one of the prior review's HIGH fixes (procgen 12-skill cap). The dissenting refuter proved the *current* verdicts are unaffected (the only divergent object, bb_procgen.o, is dead code in the dist_dump link — byte-compared all other objects), but the mechanism guarantees monotonic staleness: the next dice-path source change rebuilt via plain `make` has conformance silently validating an old engine.
**Fix:** select the candidate whose newest .o is most recent (something out-of-band does build build/main, so prefer freshness comparison over dropping the candidate), and include `engine/tests/bb_fixtures.h` (included by dist_dump.c) in the `newest_dep` computation.

### T3. Test binary has no dependency on `bb_fixtures.h` — fixture-only edits run a stale binary green
`Makefile:43` — **upheld 3/3**

The `$(TESTBIN)` rule lists TEST_SRC, bb_test.h, bb_test_main.c, $(OBJ) — bb_fixtures.h (included by 8 test TUs and no engine source) is absent, and the test compile has no `-MMD`. One refuter proved it conclusively with a read-only dry run: `make -n -W engine/tests/bb_fixtures.h test` outputs only `./build/bb_tests` (no recompile), while the same probe on bb_test.h triggers the full rebuild. This directly bites T1's fix: patch bb_fixtures.h, `make test`, stale binary "confirms" nothing changed. `make asan` inherits the gap; CI is immune only via fresh checkouts.
**Fix:** add `engine/tests/bb_fixtures.h` to the line-43 prerequisite list (one word), or compile tests with `-MMD -MP` per-TU (which also fixes the monolithic-recompile LOW note).

---

## LOW / unverified notes

Not adversarially checked; triage before acting. Duplicates merged.

**Engine rules (likely real, small blast radius):**
- `proc_match.c:444` — Cheering Fans `cheer_assist` never expires (only cleared on consumption); lingers across turns/drives/halves. Fix: clear in `turn_end` + drive end.
- `proc_block.c:113` — Dump-Off once-only latch checked (`BLK_RR_USED`) but never set in the dump-off path; bounce-back to the defender re-triggers it. Needs a dedicated frame bit.
- `bb_hooks.c:57` — skill-reroll once-per-turn latch only cleared for the team whose turn starts; persists through the opponent's turn, denying e.g. a Catch reroll on a bounce catch.
- `proc_move.c:471` — `kind == BB_ACT_STAB` inside the `kind == BB_ACT_BLITZ` branch is statically dead; blitz+Stab lacks rush parity with blitz+Block.
- `bb_procgen.c:85` — lineman top-up path drops `skill_values` (p_loner/p_bloodlust); latent until a team's positions[0] carries Loner/Bloodlust (p_bloodlust=0 makes the gate silently inert).
- `bb_procgen.c:121` — pre-game injury picks with replacement; 2-casualty squads under-delivered ~7-9%.
- `proc_match.c:374` vs DECISIONS.md D12 — Pitch Invasion victim selection consumes the *scripted* dice stream while D12 documents raw-PRNG; one of code/decision is stale and the Phase-4 harness contract depends on which.
- `validation/normalize_replay.py:325` — `turnDataSetTurnNr` ignores the home/away modelChangeKey; one `turn` variable multiplexes both teams' counters.

**Engine hardening:**
- `bb_replay.c:98` — one-byte OOB read on a truncated final line; `:68` — unbounded digit accumulation (signed-overflow UB) and silent numeric truncation (`"v":257` → legal d6 face 1); `:28` — writer ignores all fprintf/fclose errors (truncated golden/BC shard exits 0). Parser has no fuzz harness.
- `bb_rng.c:42` — `bb_rng_next` under a SCRIPT rng silently returns 0 forever and bypasses the sink (trap armed for anyone following D12 verbatim); `:61` — two hardware divisions per die roll (Lemire multiply-shift would drop both; golden regen required).
- `bb_hooks.h:57` + `bb_types.h:96` + `proc_test.c:145` — `bb_test_kind` has 9 values but reroll masks are uint8: `1u << 8` truncates to 0 (latent; becomes live the day an INTERCEPT/TTM kind or GENERIC reroll lands — see M11/M12 fixes). Widen to uint16 + `_Static_assert`.
- `proc_ttm.c:150` — crash-landing loop pushes one KNOCKDOWN per bounce with no `BB_STACK_MAX` headroom check (astronomically rare ERROR tail risk).
- `proc_ball.c:193-196` — double-precision lerp in the interception ruler; FMA contraction (arm64 default) vs SSE2 can vary candidate sets across the documented Mac/Linux split. Integer supercover walk fixes both this and the perf note below.
- `bb_test.h:33` — constructor-time test registration writes past `bb_tests[]` with no bound check.
- `tools/codegen.py:294` — casualty/prayer table gaps silently map to band 0 instead of failing codegen (kickoff/weather tables do hard-fail).
- `skills_devious_traits.c:21-24` — stale "Drunkard is dead code" NOTE; the BB_TEST_RUSH registration is live at all four rush sites. Fix the comment before someone double-wires the -1.
- `tools/install_puffer_env.sh:19` — no drift guard between engine/src and the vendored snapshot the GPU run compiles (byte-identical today; add a content hash check). Relevant to M3's vendored-copy note.
- `tools/fetch_docs.sh:4` — cd into gitignored docs/vendor before creating it (fails on fresh clone); `:20` — curl without `-f` caches HTTP error pages as PDFs; wget mirror failure swallowed by `|| true`.
- `validation/fetch_replays.py:265` — `"coach": null` crashes team_info (dict-default doesn't guard JSON null; line 270 already uses the safe idiom).

**Binding:**
- `bloodbowl.h:237/:305` — touchback no-standing-receivers fallback collapses ~195 distinct placement actions into one head triple; decode silently always picks the corner-most square and the policy can't express the choice (same class as the fixed spatial-discriminator HIGH, surviving in a rare branch). Either make arg==0xFF touchbacks spatial or document as a D-series auto-policy.
- `bloodbowl.h:415` — DECISION with `n_legal == 0` livelocks the env forever (defended in the mask path, not the step path); currently unreachable, terminate the episode defensively.
- `bloodbowl.h:432` — `BB_STATUS_ERROR` episodes are logged as normal results with no error counter (and `c_reset`'s initial `bb_advance` is unchecked).
- `bloodbowl.h:361` + `binding.c:70` — reward-default heuristic clobbers an explicit `reward_td=0, reward_win=0` ablation; negative seed kwarg is a double→uint64 UB cast; max_decisions silently clamped.
- `bloodbowl.h:8-16` — header obs-layout doc describes the previous 576B/16B/5-skill layout; actual is 832B/24B/12-skill. Every documented offset is wrong; regenerate from the BBE_* macros.
- `binding.c:10` — `ACT_SIZES {30,33,391}` literal is not asserted against `BBE_HEAD_*` (only the 454 total is); a sum-preserving drift ships mis-partitioned masks silently.
- `bloodbowl.h:326` — decode performs up to 3 full legal-list scans on a head miss (~every step on the maskless practice path); fold into one scan recording first-fallback indices.
- `bloodbowl.h:177` — per-step recomputation of episode-constant skill bytes (~300 `bb_next_skill` iterations/step, both agents); cache at reset.

**Engine perf micro-items** (all in the "already 4x over target" bucket; bundle opportunistically): `bb_hooks.h:33`/`skills_core.c:177` bb_ctx lacks precomputed TZ counts so STUNTY/BIG_HAND/NoS/POGO re-scan what the caller just computed; `proc_block.c:390` push_flags recomputed up to 4x per push frame; `bb_hooks.c:104` chain_mod walks both skillsets though zero armour/injury hooks are registered; `proc_block.c:13` assist counting scans 16 roster slots instead of 8 neighbors; `proc_turn.c:277`/`:36` activation_legal and pick_me_up scan-before-gate orderings; `proc_move.c:525` TTM/pass target loops scan all 390 squares instead of the range bounding box; `proc_ball.c:195` 64-step ruler march recomputed up to 4x per interception window; `proc_block.c:407` single-option pushes still cost a full RL env step (consistent with the D10/D17 auto-policy philosophy to collapse — but gate on Phase-4 replay-alignment needs); `Makefile:44` monolithic serial test recompile (fixing via per-TU objects also closes T3 properly).

---

## Killed claims

None. Every claim that reached the adversarial panel survived at least 2 of 3 refuters; the only full-on REFUTED votes were minority dissents on the three perf/hardening items noted inline (P1 ×3 design-intent, P3 metric-corruption leg, Hd1 present-tense reachability, T1 reachability, T2 current-impact), each of which trimmed the claim's scope rather than killing it.