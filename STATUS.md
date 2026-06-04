# Status — 2026-06-04 morning (experiment grid: COMPLETE, verdict in)

**THE NIGHT'S RESULT:** Four 10B arms + tournament (20K games). The 0-0 avoidance equilibrium is UNIVERSAL — every cross-population match ≈100% draws. Decisive finding: **BC-init beats BC-final** — selfplay PPO actively eroded the human prior (D27). Your bootstrap potentials (profile D) were the only thing that ever made selfplay score (tds 0→0.06), but cold-anneal decayed it (D26). NEXT (in order): BC-regularized PPO (KL-anchor to human policy during RL — the AlphaStar fix), gradual anneal, asymmetric offense-vs-frozen-defense curriculum. All checkpoints + 24K-pair human corpus banked; box idle at $0.64/hr; total spend ~$18.

--- (previous status below) ---


**TL;DR:** Legacy 10B baseline trained (buggy engine, archived for reference). A 112-agent adversarial review found **31 confirmed issues (4 HIGH engine bugs)** — all fixed, tested, merged (277 tests, ASan clean). The box is now running **profile A (pure outcome)** then **profile B (event-shaped)** on the fixed engine, 10B steps each, unattended. Spectator shows real FUMBBL art with checkpoint progress.

## Tonight's deliverables
- **All 31 review findings fixed** — headline HIGHs: crowd-push stripped unrelated carriers' ball; Animal Savagery knockdown deferred (LIFO bug let "downed" mates keep assisting); TTM threw player slot 0 (grid corruption); Distracted never cleared for gaze victims. Plus Frenzy's second block existed only as dead wiring — now implemented.
- **Reward design doctrine** (with Alex, `docs/reward-audit-decision-time.md`): decision-time pricing everywhere; exposure-only boundary (own gambles → critic); profiles A/B/C; desperation handled by payoff spread + last-turn exemption; all knobs default 0.
- **Obs v2**: TZ-marking byte + pending-test-target byte (re-roll quality decisions!), team ids REMOVED (forces roster-reading → honest generalization tests).
- **Experiment toolkit**: `tools/train_profile.sh A|B`, holdout/forced-matchup procgen kwargs, `docs/homebrew-team-authoring.md` (Alex designs team id 30).
- **Spectator v2**: real FUMBBL pitch/sprites (159/159 positions mapped), training progress bar, `tools/spectate.sh`.

## EXPERIMENT VERDICT (both profiles complete, 10B each, fixed engine)
**Both arms converged to the mutual ball-avoidance draw equilibrium** (tds=0.000, perf=0.500 in A AND B; B's knobs shortened episodes 905→605 but did not break the basin). Decisive negative result: selfplay-from-scratch at 10B/γ=0.995 doesn't discover football regardless of event shaping → **BC warm-start from human replays is the main line** (Bot Bowl literature reproduced). The lockstep differential doubles as the BC extractor (every locked op = an (obs, human-action) pair).

## Performance (measured, shipped)
Env: 176K → 546K steps/sec/core today (setup discipline + perf prototypes, bit-identical, 280 tests). Vec config 8/1 → 20/2 (est. 1.5-2.7× more). Full plan: docs/sps-optimization-plan.md. Box ceiling est. 3-5M SPS.

## Queued
- #22 Alex's Windows 2070 box via WSL2 tonight (baseload; build `--float`)
- Phase 4 FUMBBL differential + BC corpus (the big lever)
- Backlog: wizards/stars (#23), team-composition meta (#24), profile C (gated on B>A)

## Spend: ~$8 total of $50.
