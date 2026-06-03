# Status — 2026-06-03 evening (Phase 6: experiment grid running)

**TL;DR:** Legacy 10B baseline trained (buggy engine, archived for reference). A 112-agent adversarial review found **31 confirmed issues (4 HIGH engine bugs)** — all fixed, tested, merged (277 tests, ASan clean). The box is now running **profile A (pure outcome)** then **profile B (event-shaped)** on the fixed engine, 10B steps each, unattended. Spectator shows real FUMBBL art with checkpoint progress.

## Tonight's deliverables
- **All 31 review findings fixed** — headline HIGHs: crowd-push stripped unrelated carriers' ball; Animal Savagery knockdown deferred (LIFO bug let "downed" mates keep assisting); TTM threw player slot 0 (grid corruption); Distracted never cleared for gaze victims. Plus Frenzy's second block existed only as dead wiring — now implemented.
- **Reward design doctrine** (with Alex, `docs/reward-audit-decision-time.md`): decision-time pricing everywhere; exposure-only boundary (own gambles → critic); profiles A/B/C; desperation handled by payoff spread + last-turn exemption; all knobs default 0.
- **Obs v2**: TZ-marking byte + pending-test-target byte (re-roll quality decisions!), team ids REMOVED (forces roster-reading → honest generalization tests).
- **Experiment toolkit**: `tools/train_profile.sh A|B`, holdout/forced-matchup procgen kwargs, `docs/homebrew-team-authoring.md` (Alex designs team id 30).
- **Spectator v2**: real FUMBBL pitch/sprites (159/159 positions mapped), training progress bar, `tools/spectate.sh`.

## In flight (box orchestrator, ~5-6h)
legacy eval tail → archive log → rebuild fixed engine → profile A 10B → profile B 10B. Then: `puffer match` A-vs-B arbitration.

## Queued
- #22 Alex's Windows 2070 box via WSL2 tonight (baseload; build `--float`)
- Phase 4 FUMBBL differential + BC corpus (the big lever)
- Backlog: wizards/stars (#23), team-composition meta (#24), profile C (gated on B>A)

## Spend: ~$8 total of $50.
