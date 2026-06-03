# Status — morning of 2026-06-03 (night-shift summary)

**TL;DR: The BB2025 engine is real.** Full matches run end-to-end at **2.34M steps/sec/core**, with ~83 of ~108 skills/traits implemented (incl. Stab/Hypnotic Gaze special actions), 228 rulebook-grounded tests green, continuous fuzzing clean (~120K total fuzzed matches — it caught 4 real ball-invariant bugs tonight, all fixed), and a deep Codex review (4 High/3 Med/2 Low) fully resolved. 35 commits.

## Where each phase stands
- **Phase 0–2: DONE.** Repo+docs+skills; YAML spec → codegen; core engine with exact BB2025 core rules (194 rulebook tests from the mirror found 34 divergences in my first implementation — all fixed; biggest: BB2025 made team re-rolls UNLIMITED per turn).
- **Phase 3: ~85%.** Skill-hook framework (constructor-registered; `libbb.a` now partial-linked so consumers can't silently lose skills). Implemented beyond core: Frenzy, Dauntless, Jump/Leap/Pogo, Tentacles, Diving Tackle, Shadowing, Foul Appearance, Jump Up, Brawler, apothecary windows, Argue the Call, Secure the Ball, interceptions, Hail Mary, Cloud Burster, Give and Go, full foul family, Take Root, Kick, Leader, Secret Weapon, Regeneration, Decay, Iron Hard Skin, Pick-me-up… **Remaining** (task #10): the special-actions cluster (Stab/Chainsaw/Gaze/Bombardier/Ball & Chain/TTM…), Dump-Off/On the Ball/Trickster/Saboteur windows, skill params + keywords (Bloodlust/Animosity/Hatred), 4 kickoff events, Pro.
- **Phase 4–6: queued** (FUMBBL replay differential → PufferLib binding → training). Vast key verified ($96 credit; $50 cap respected — $0 spent).

## For your review
- `DECISIONS.md` — 20 judgment calls (auto-policies for Wrestle/MB/interceptions, setup budget, etc.)
- `.codex-reviews/engine-phase3-*.md` — the full review; all findings addressed in commit 455a323+
- `make BUILD=build/main test && make asan && make BUILD=build/main coverage` — see it all green yourself
