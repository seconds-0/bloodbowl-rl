# Status — 2026-06-03 (Phase 5 complete, GPU provisioning in progress)

**TL;DR: The harness is end-to-end.** The BB2025 engine (full ruleset, 229 tests, 6 validation layers) is now a PufferLib 4.0 env that **trains**: a 2.9M-param MinGRU policy ran 12 PPO epochs on the Mac torch backend with stats flowing (perf/tds/episode_length/illegal_frac). Env throughput: **206K env-steps/sec/core**, ~2.1M/sec aggregate on 12 Mac cores (target was 500K). A Vast.ai 4090 ($0.53/hr, 32 vCPU, $50 cap) is booting for the real masked CUDA self-play run.

## Where each phase stands
- **Phase 0–3: DONE.** Docs/skills; YAML spec → codegen; full BB2025 ruleset (~95 of ~108 skills/traits; the rest are documented auto-policies/deferrals in DECISIONS.md D21); 229 rulebook-grounded tests; fuzzing caught 6 real bugs cumulative (~140K fuzzed matches), all fixed + regression-tested.
- **Phase 4: harness built, differential queued.** Throttled FUMBBL fetcher + replay normalizer (99% report coverage) + chi-square conformance vs analytic odds & ActionCalculator (44/44). The engine↔FUMBBL lockstep action-mapper is the remaining milestone (task #6) — independent of training start.
- **Phase 5: DONE tonight.**
  - `puffer/bloodbowl/bloodbowl.h` — env over the amalgamated engine (single-TU; DIR8 renamed per pseudo-TU; the 4 `skills_*.c` constructor files included — almost lost ALL skill hooks to the archive-drop bug again, caught at review).
  - Obs: 576B/agent egocentric uint8 (32 players × 16B + ball/proc ctx + scalars), x-mirrored for away.
  - Actions: 3 masked heads {30 type, 33 arg, 391 square}; decode snaps illegal samples to legal (3-pass), so maskless backends stay sound.
  - `binding.c` (MY_VEC_INIT/PERM/TAGS + hist-bank logs → selfplay pool compatible), `bloodbowl.c` standalone driver/benchmark, `config/bloodbowl.ini`, `tools/install_puffer_env.sh` (symlink-dereferencing; zero build.sh patches needed on Linux).
  - Verified: ASan/UBSan clean over 500 random matches (incl. 99.8%-illegal stress); binding compiles under build.sh-equivalent flags; **torch practice run trained end-to-end on the Mac** (147K steps, exit 0). Mac quirks documented in D24 + the puffer-env-dev skill (dual-libomp segfault, selfplay silent-exit trap).
- **Phase 6: IN PROGRESS.** Vast 4090 instance #39307539 creating (pytorch 2.9 cu12.8 devel image). Next: rsync → `tools/gpu_box_setup.sh` → CUDA smoke (20M steps, verify masks ⇒ illegal_frac≈0 + selfplay banks) → real run (2B steps, checkpoints). BC warm-start deferred until the Phase 4 action-mapper exists.

## Spend
- Vast: $0 spent before tonight; instance bills $0.5333/hr against your $50 cap (~93h budget). I'll destroy the instance whenever it's idle.

## For your review
- `DECISIONS.md` — now D1–D24 (new: D23 snap-bias artifact, D24 Mac practice-run path)
- `puffer/bloodbowl/` — the whole binding is ~600 lines, readable in one sitting
- Quick local demo: `clang -O2 -Ipuffer/bloodbowl puffer/bloodbowl/bloodbowl.c -o /tmp/bbe && /tmp/bbe 64`
