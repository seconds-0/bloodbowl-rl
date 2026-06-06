# Eval probes wishlist — behavioral judgment metrics

Selfplay dashboards measure volume; these probes measure *judgment*. Run
offline against checkpoints (local masked eval or `puffer eval`) or, where a
counter exists, read live. Human baselines come from the 1M-pair corpus —
the same .bbp records carry obs (who) + action (what), so every demographic
below is computable for humans with a pairs-scan script.

## Carrier quality (Alex, 2026-06-06 — the ballhawk-arm watch)

1. **Dropped-pickup rate** (the counterfactual headline): pickup FAILURES /
   attempts. If carrier selection improves, this falls — outcome-level, no
   demographics needed. Live counter `ep_pickup_success` added to the env
   (deploys next build cycle; until then derive offline). Human baseline:
   strong coaches fail rarely (designated AG3+/Sure Hands scoopers).
2. **Pickup demographics**: histogram pickup attempts by scooper archetype —
   buckets over (MA, AG target, has Sure Hands). Compare vs the human
   distribution from the pairs. Failure mode to catch: "nearest player
   scoops" (the fetch potential is quality-blind; the critic/anchor/discount
   are supposed to dominate — verify, don't assume).
3. **Carry demographics**: squares advanced while carrying, by carrier MA.
   The discount should favor fast carriers organically (γ math, D-profile
   doctrine); flat-by-MA = the speed channel isn't biting.

## Risk judgment (from the dodge-doctrine discussion, 2026-06-05)

4. **AG-stratified dodge curve**: dodge_attempts/ep bucketed by dodger AG ×
   TZ count. Judgment = elves dodge several times the Black Orc rate, orc
   rate spikes only late-half-behind. Flat across AG = global propensity,
   not judgment.
5. **Blocks on demo episodes** ("does it fight when it should"): blocks_thrown
   on demo-started episodes vs from-kickoff — human mid-game positions
   demand contact; avoidance there is the tell.
6. **Block-dice quality distribution**: thrown blocks by dice tier
   (2dB/2d/1d/2d-against) — the D34 conversion claim done right
   (blocks_thrown denominators, panel finding #3).

## Outcome wiring (existing, for reference)

- `blocks_thrown` (CHOOSE_DIE) — clean conversion denominator (D36)
- `bb_casualty_hook` — per-casualty causer/roll/ctx (memorial; also usable
  by a headless coroner eval for attrition-quality stats)
- Tournament arbitration (`puffer match`, 4096 games) — the only
  selfplay-confound-free skill measure (D27/D39)
