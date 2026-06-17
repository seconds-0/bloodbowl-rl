# Contact / attrition reward economy — strategic-blocking design (FOR REVIEW)

Pressure-test target. The question: **how do we reward *strategic* blocking** — not "hit
things" but "win the assist/tackle-zone battle and only fight favorable matchups"?

## Where we are (factual)
- Agents barely block (6.8/game vs human 88.8) and never foul. Root cause D141: the
  league lineage trained with `injury_inflicted=0` (whole attrition paycheck deleted);
  restoring it + R3 send-off penalty is implemented (committed, not yet live).
- Engine ground truth: `engine/src/bb_blockev.c` already computes block-dice EV from
  **ST ± assists** (`bb_count_assists` both directions), Horns, Cheering Fans, and skill
  effects; Guard and Diving Tackle are modeled skills. The reward already prices block
  *declarations* by real EV: `k_kd · p_def_down` and `k_value · p_def_removed · def_cost/100`.
  So matchup/assist-aware pricing EXISTS; `k_value` just weights removal by **gold cost**.

## v0 proposal (the thing being pressure-tested)
Weight knockdown/removal value by a **threat scalar** (ST + Mighty Blow/Claw/Guard/Block/
Tackle/Diving Tackle/Frenzy/mobility) instead of gold cost.

## Alex's enrichment — threat is RELATIONAL and MATCHUP-DEPENDENT, not a per-piece scalar
1. **Assist economy is the game.** A piece's threat = the assists it *gives* enemy blocks
   + the assists it *denies* you + the tackle zones it projects (disabling your dodges and
   assists, enabling theirs). Managing your assists and the opponent's is most of the game.
2. **Guard-next-to-Treeman.** You cannot get a 2-die block on the Treeman while a Guard
   lineman sits beside it — the Guard both *adds* a defensive assist and *cancels* your
   offensive assist. You must remove the Guard FIRST, then set up the Treeman. So a piece's
   threat is positional/contextual, not intrinsic — the Guard lineman's "threat" here
   exceeds the Treeman's.
3. **Diving Tackle** raises a marker's stickiness (taxes dodging away) — part of TZ/threat.
4. **Follow-up + tempo.** Knock a player down and choose to follow up or not — prone players
   can't hit you; when they stand they must blitz (or you've denied their next-turn threat
   on your ball). Sometimes you dodge away rather than confront, unless you can get 2 dice.
5. **Matchup-dependent contact (elves into chaos).** Vs ST4 Block+MB pieces, elves do NOT
   attrit: only blitz/block with War Dancers / Wrestle linemen at the *exact* needed moment,
   otherwise look at the block, dodge away, and force THEM to dodge — minimize blocks thrown
   *at* you. Blocking value depends on the dice YOU get (relative ST + assists).

## My position (pressure-test THIS, don't just agree)
- **The EV foundation is right; do NOT replace it with a static threat scalar.** A static
  per-piece weight mis-prices the Guard-next-to-Treeman case entirely; the assist-aware
  `bb_blockev` EV already encodes matchup + assists. Extend the EV pricing, don't bypass it.
- **Fix 1 (small):** weight removal by *threat* (assist-provision + TZ-denial + skills),
  not gold cost — `k_value`'s weight function only.
- **Fix 2 (the real gap):** the **second-order value of removing an assist-provider** —
  knocking the Guard down makes your OTHER blocks 2-dice — is invisible to independent
  per-block pricing. This is the Guard example's whole point and nothing prices it.
- **Fix 3 (maybe nothing):** the matchup-avoidance + follow-up/tempo behaviors plausibly
  EMERGE from correctly-calibrated EV + the win signal (a 1-die block into ST4-Block is
  already negative EV; a War-Dancer 2-die is positive) — we may need NO new term, just EV
  pricing strong enough (we HALVED it at D39 and zeroed injury). Verify emergence before
  adding terms.
- **Open:** is a telescoping board-threat potential the right home for the positional/
  relational value, and can it be assist/TZ-aware without combinatorial blowup?

## Questions for the reviewers
1. Static threat scalar vs EV-grounded pricing — is "extend bb_blockev pricing" right, and
   is the static-scalar v0 a trap?
2. The second-order assist-provider-removal value (Fix 2): how to reward it WITHOUT farming
   or a combinatorial blowup? (Re-running bb_blockev on neighbors after a hypothetical
   knockdown? A TZ/assist potential?)
3. Do matchup-avoidance + follow-up/tempo EMERGE from EV+win, or need an explicit term?
   What experiment distinguishes "emerges" from "needs a term"?
4. Goodhart/farming: the memo (line 92) rejected per-knockdown rewards (LOS punch-fests
   that ignore the ball, "win on casualties lose the game"). Which of these terms reintroduce
   that, and does the telescoping/EV-at-declaration framing actually prevent it?
5. Tractability: bb_blockev already has assists/Guard/Diving Tackle. What's the cheapest
   change that captures the most of Alex's model? What's over-engineering?
6. What is MISSING from this whole model? (Self-play zero-sum on attrition; tackle-zone
   *denial* as offense-enabler; the fact that all of this is mirror self-play with no
   external opponent that plays the assist game.)

---

## VERDICT (Codex + adversarial snickerdoodle pressure-test, 2026-06-17 — D142)

Both reviewers converged. Outcome: **the static threat scalar (v0) is killed; no new
positive contact term is built now; the work sequences behind the D141 injury-restore A/B.**

**Accepted:**
1. **Kill v0 (static threat scalar).** Both CRITICAL: it flattens the relational/positional
   context (`bb_blockev` already computes ST-after-assists both ways; Guard-beside-Treeman
   is contextual). A "better scalar" is still wrong.
2. **Sequence behind the D141 A/B, and isolate it.** Restoring injury AND bumping k toward
   Profile-C at once = two density increases → re-triggers the D39 contact-crowds-out-scoring
   failure and confounds the read. The committed `run_league9_attrition_ab.sh` was AMENDED to
   keep **k-half** (0.03/0.25); injury-restore (+send-off) is the single isolated variable.
   Profile-C k-bump is a separate follow-up arm gated on this one retaining scoring.
3. **The assist/TZ second-order value already has a home: R6v1.5 / R6v2a fragility** (memo
   lines 51-59) — penalty-side, `bb_blockev`-based, current-adjacency-only, no enumeration.
   Do NOT build a parallel positive contact term; if telemetry later shows R6 misses a hole
   (high actual sack rate despite low priced exposure), extend R6v2a, not a new scalar.
4. **Diving Tackle correction:** it is NOT a `bb_blockev` skill (movement/dodge interrupt,
   `proc_move.c`); "extend bb_blockev" can't price its stickiness. It belongs in R6v1.5
   reach-path probability-weighting (dodge/Tackle/Diving-Tackle on the path).
5. **Fix-2 done safely (if ever):** pay `p_down(target)·max(0, old_penalty − new_penalty)`
   against a CAPPED positional penalty (one-ply, adjacent-only re-price), NOT raw future-block
   value (farmable: agents manufacture scrums). Compute is trivial (216-face max, EV overhead
   "unmeasurable" per D34); the real risk is the farm + mutating `bb_match` in the hot encode
   path with no save/restore helper. Prototype as TELEMETRY first.
6. **Define success before building (snickerdoodle CRITICAL):** attrition is zero-sum in mirror
   self-play, so win-rate can't move on assist-economy alone. Success = scenario boards
   (Guard/Treeman, elf-vs-ST4-Block/MB-chaos) + metrics (block-tier mix, dodge-away rate,
   sack rate, carrier exposure, voluntary follow-up, next-turn free-2D conceded, TD/win) AND
   an asymmetric/scripted-contact opponent (the through-line to D141's "needs an opponent").

**Where I pushed back (didn't just accept):** R6 is carrier-DEFENSE-centric; it does NOT
price the OFFENSIVE assist-clearing (clear the Guard so YOU can 2-die the Treeman) or the
matchup-avoidance (elves dodging ST4 bash). So R6 isn't literally a superset. BUT the right
response is still NOT a new positive term — that offensive matchup play should EMERGE from the
restored EV economy + win signal + a competent contact opponent, and gets TESTED (the scenario
probe) before any term is added. Follow-up/tempo is the one behavior that plausibly does NOT
emerge from current EV (it doesn't price voluntary post-push positioning) — that's the single
candidate for a future explicit term, gated on the probe showing EV+win can't learn it.

**Net plan:** (1) run the isolated D141 injury-restore A/B after league9 caps; (2) build the
scenario-eval harness + a scripted contact opponent (also the absolute-signal anchor from D140);
(3) only THEN, if the probe shows a real hole, extend R6v2a fragility (defense) / add a tempo
term (follow-up) — never a static threat scalar or a positive contact bounty.
