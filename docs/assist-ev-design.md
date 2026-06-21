# Assist-EV reward — design for pressure-test (pre-build, 2026-06-21)

## Motivation (D163)
Measured: the agent brings ~0.5× the offensive assists humans do, on EVERY block tier (1d 0.28 vs
0.55, 2d 0.52 vs 0.94, 2d-red 0.09 vs 0.17). That is the structural cause of its poor dice-mix
(elevated 2d-red, depressed 2d-frac). Raising k_kd/k_turnover can't fix it (netblock2 proved: pricing
the block harder doesn't make the agent SET UP the block). The setup move (positioning a teammate to
assist, or removing an enemy assist) is unrewarded and distal from the block payoff → the agent never
learns the multi-step gang-up.

## The design (refined by Alex's bidirectionality pressure-test)
**REJECTED v0:** "credit a move by the offensive-assist EV it provides to a teammate's block." This is
ONE-DIRECTIONAL — it only rewards ADDING my assists; it ignores removing/displacing ENEMY assists, which
is half of real BB (block dice = my ST + my off-assists vs their ST + their def-assists). It would teach
offense-only assist play.

**PROPOSED v1 — a POTENTIAL on block favorability, telescoping + zero-sum:**
```
Φ(team T, state) = aggregate block-EV favorability for T
                 = Σ over T's standing, un-activated pieces of  best_p_def_down(piece's best legal block this turn)
                   (or a bounded key-block variant — see Open Questions)
reward_t(T) = k_assist * ( γ·Φ(T, s') − Φ(T, s) )   # telescoping potential, charged each own decision/turn-boundary
zero-sum:   the enemy gets the mirror (their Φ delta), so net ≈ 0 across teams.
```
DECISION-TIME / pre-dice: Φ uses bb_block_ev p_def_down (the EV oracle, no RNG) — cardinal-rule clean.

## Why this answers the bidirectionality test
Φ rises (→ reward) from EITHER:
- adding my offensive assist (teammate moves adjacent to the enemy my blocker can hit → my block p_def_down ↑), OR
- **removing/displacing an enemy assist** (blitz the enemy piece that was marking my blocker or assisting
  their block → my block p_def_down recovers → Φ ↑) — Alex's "move their assist because it frees up your
  assist." A flat one-directional bonus MISSES this; the Φ-delta captures it for free.
Φ falls (→ penalty, and enemy rewarded) when the enemy adds an assist against me. Symmetric.

## Why a POTENTIAL (not a flat bonus) — two critical properties
1. **No double-count with k_kd.** k_kd already pays the block at its current (assisted) EV. A flat
   "reward the assist setup" pays the SAME assist value twice (setup + block) = a farming hole. A
   telescoping potential nets to zero over the trajectory (Ng-Harada-Russell), so it does NOT add reward
   — it MOVES the credit earlier onto the setup decision. Exactly the multi-step credit-assignment fix
   we need.
2. **PBRS-safe** (D161 research): potential-based shaping is optimum-invariant — biases learning SPEED of
   the gang-up behavior, not the optimal policy. The hack-immune form.

## Open questions for the pressure-test (the real risks)
1. **Φ definition + COST (the threat-annuity over-engineering trap).** "Aggregate best-block-EV over all
   my pieces" recomputed per move = potentially O(pieces × candidate-blocks × bb_block_ev-clones) — the
   threat annuity was 8× SPS for less. Is a BOUNDED Φ enough (e.g., only the single best block, or only
   blocks on the carrier / adjacent contacts)? What's the cheapest Φ that still captures the
   add-mine/remove-theirs duality?
2. **Does telescoping REALLY cancel the k_kd double-count**, given Φ is over AVAILABLE blocks and k_kd
   fires on THROWN blocks — do the bookkeeping (when Φ drops as a block is consumed) and k_kd actually
   net out, or is there residual double-pay / a farming cycle (raise Φ, lower Φ, repeat)?
3. **Farming via Φ-churn:** can the agent oscillate pieces to pump γΦ'−Φ without committing blocks
   (the threat-annuity camping analogue)? Does the zero-sum + telescoping form prevent it, or need a
   per-turn-boundary measurement like the possession annuity?
4. **Self-play symmetry:** both teams experience it — does it net to a real gradient teaching BOTH
   "set up my assists" AND "disrupt theirs," or wash out?
5. **Interaction with the threat annuity / possession annuity / dist potentials** — another zero-sum
   board-EV annuity; double-count or conflict with existing terms? (carrier_threat is currently 0.)
6. **Marking vs assisting:** a defensive assist requires the enemy be adjacent to MY blocker; an
   offensive assist requires MY teammate adjacent to the enemy AND that teammate not itself marked. Does
   Φ correctly use bb_count_assists semantics (Guard, marked-assister exclusions) so it doesn't reward
   non-functional "assists"?
7. **Is a reward even the right tool**, vs BC-toward-human positioning (humans assist; block-decision-
   weighted BC-CE would teach it directly) or an obs "assistable-enemy" plane? The reward is fastest;
   pressure-test whether it's the RIGHT lever or a band-aid on a planning/representation gap.

## Build sketch (if it survives review)
`bb_team_block_favorability(m, team) -> float` in bb_reachability.c/bb_blockev.c (reuse bb_block_ev +
bb_count_assists, BOUNDED per Q1), a `reward_k_assist` knob (default 0 inert), telescoping hook at the
own-decision/turn-boundary like possession annuity, zero-sum. Then a warm-start probe from netblock_cap
watching the D163 telemetry: does offassist_{1d,2d,2dred} rise toward human, 2d-red fall, 2d-frac rise —
WITHOUT camping/farming (tds, advancement held; the Φ-churn canary).
