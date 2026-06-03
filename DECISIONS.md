# Decisions scratchpad — autonomous calls for Alex to review

Running log of judgment calls made while you were away. Newest at the bottom.
Format: **D# — decision** · rationale · revisit?

---

**D1 — Setup action budget (64) + deterministic auto-fix.** Random/untrained agents livelock in the setup phase (can't randomly satisfy "exactly 11, 3+ on LoS, ≤2 per wide zone" and pick DONE). Real BB has setup clocks; FUMBBL enforces them. After 64 placement actions, only `SETUP_DONE` is legal and the engine deterministically repairs the formation (no dice → replay-safe). Full setup expressiveness retained below the budget. *Revisit:* budget size; whether RL policies should see a penalty signal for hitting autofix.

**D2 — `BB_LEGAL_MAX` = 4096.** Setup enumerates ~3000 player×square placements. The RL action heads never materialize this list (factored heads); it's for replay validation/fuzzing/tests. 16KB stack per enumeration is fine.

**D3 — Starter skill set in Phase 2 core** (loner, dodge, block, tackle, guard, thick_skull, stunty, sure_feet, sure_hands, pass, catch, sprint) wired through `bb_skills.h` hooks; everything else lands Phase 3 through the same hooks. Wrestle/Frenzy/Mighty Blow/apothecary deliberately deferred (decision windows not yet modeled) — each marked `TODO(phase3)` in source.

**D4 — Kickoff events: 4 of 11 implemented** (Time-Out, Brilliant Coaching, Changing Weather, Pitch Invasion); the decision-heavy ones (Solid Defence, Quick Snap, High Kick, Charge, Cheering Fans→prayers, Get the Ref→bribes, Dodgy Snack) are rule-shaped no-ops marked `TODO(phase3)`. Phase 4 differential validation will quantify the gap.

**D5 — Pass mechanics v1 approximations** (flagged for the rulebook-test campaign to correct): Euclidean range bands; natural-1≈fumble folded into the inaccurate path; interception deferred. The rulebook tests being written right now will force exactness; FUMBBL replays are the final word.

**D6 — Golden traces: 8 matchups committed** (incl. Ogre vs Snotling for stunty/big-guy coverage). Regenerating goldens is an explicit `make goldens` — rules fixes are EXPECTED to break goldens; that's their job.

**D7 — Vast.ai**: key stored at `~/.vast_api_key`, verified live ($96.26 credit). Spend capped at your authorized $50. No GPU spend until the PufferLib binding smoke test (Phase 5).

**D8 — GitHub remote deferred.** Repo is local-only so far; creating a private GH repo is outward-facing and can wait for your morning review (CI workflow file is ready to go when pushed).

**D9 — Wrestle auto-applies on Both Down.** Rules make it optional ("may choose"); since declining is almost never right and the rulebook tests expect auto-application, the engine applies it when either player has it. Revisit if FUMBBL replays show declines.
**D10 — Single-candidate interceptions auto-attempt.** Attempting is cost-free (no failure penalty), so with one eligible interceptor there's no real decision; with several, the defending coach chooses. Matches the rulebook tests.
**D11 — Crowd-push dice order.** Crowd injury + throw-in resolve at relocation time, BEFORE the follow-up decision — FFB's order, and what the blocking tests encode. GAME/FOLLOW-UP's "decision before any other dice" reading is a known minor divergence to check against FUMBBL replays.
**D12 — Pitch Invasion victim selection** uses the raw PRNG (not the scripted dice stream) — FUMBBL records selections as separate commands, so replay alignment handles it at the harness level. Fan-factor modifiers TODO with the fans/inducements work.
**D13 — Secure the Ball failure = bounce + turnover** (consistent with the failed-pickup family). Rule text doesn't settle it; flagged for FFB differential adjudication.
**D14 — Test-vs-test conflicts resolved toward the mirror**: throw-in direction die is a D6 over the 3 template arrows (corners: D3); distance counts the boundary square as the first; no bounce on an empty landing square. Two agent tests written with d3/full-distance/bounce assumptions were corrected.
**D15 — BB2025 team re-rolls are UNLIMITED per turn** (the BB2020 once-per-turn cap is gone) and replenish at half-time; skill re-rolls (Dodge/Sure Feet/...) are once per TURN per player. Engine restructured accordingly.
**D16 — Mighty Blow auto-policy.** MB(+1) is rules-wise a choice of armour OR injury roll. Engine auto-applies: to the armour roll only when that converts a miss into a break, otherwise to the injury roll — the strictly dominant line in >99% of cases (exception: fishing for specific injury bands). Claws+MB on the same roll disallowed per rules; Claws' 8+ auto-break consumes the slot. Revisit if FUMBBL replays show deviating choices.
**D17 — Stand Firm always-on** (no decline window; declining is never beneficial absent edge interactions). Same for auto-attempting cost-free single-candidate interceptions (D10).
**D18 — Kick auto-applies** (halve deviation) when any on-pitch kicking-team player has Kick — kicker nomination (not adjacent to LoS/wide zone) is folded into the fans/nomination TODO. **Break Tackle** is always-on per-dodge (rules: once per activation) — flagged for the FUMBBL differential. **Secret Weapon** send-off uses on-pitch-at-drive-end as "took part" approximation.
**D19 — Interrupt auto-policies.** Tentacles: every eligible tentacled marker attempts (cost-free, compulsory-shaped); one attempt per step. Diving Tackle: auto-applied when the -2 flips a passing dodge (the only rational use), never with a ball-carrying diver; first eligible marker dives. Shadowing still pending (needs per-turn MA-use counter). These become real decision windows if the RL action space wants them; FUMBBL differential will adjudicate fidelity.
**D20 — Apothecary casualty pick auto-selects the better band** (strictly dominant given equal in-match effect); KO-patch remains a real decision (saving the apo matters). Casualty outcomes now recorded in spp_game for league mode.
**D21 — More auto-policies (Drop B):** Trickster auto-relocates only when it fully escapes the blocker (else stays); Dump-Off auto-throws to the least-marked quick-range teammate; Saboteur always triggers (cost: auto-KO — debatable, FUMBBL will adjudicate); SPOH places in the first empty adjacent square; Solid Defence/Quick Snap/Charge roll their D3 for dice-stream fidelity but reposition no one yet (decision windows TODO); Dodgy Snack's stat debuff persists for the match (drive-end restoration comes with procedural squads); Bloodlust thrall-bite + Animosity keyword targeting need keyword data (gate fires on declaration as approximation). Multiple Block + Pile Driver deferred (no default-roster carriers).
**D22 — Phase 5 design pivot per policy research** (docs/policy-research.md): compact ~640B entity-centric obs (NOT board planes — 20GB rollout buffer at bf16 otherwise); ACT_SIZES {type, arg, fused-391-square} each with a null index; stock Linear→MinGRU×3 policy (config-only, ~3.8M params); env-phase decision decomposition (the engine already provides it).
