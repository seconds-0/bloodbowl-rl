# bloodbowl-rl

RL training harness for **Blood Bowl Third Season Edition (BB2025)**: deterministic C11 rules engine → PufferLib 4.0 native env → PPO + action masking + self-play league, BC warm-start from curated FUMBBL replays. Full plan: `~/.claude/plans/i-need-you-to-merry-naur.md`.

## Project skills — use them

| Skill | When |
|-------|------|
| `puffer-env-dev` | Anything touching the PufferLib binding, build, training CLI, selfplay config |
| `bb-rules` | Implementing/verifying any game rule, skill, table; edition-delta questions |
| `fumbbl-data` | Fetching/parsing FUMBBL API data or replays; BC corpus curation |
| `bb-validation` | Running/triaging the 7 validation layers; oracle setup (FFB/Jervis/Calculator) |

## Hard-won facts (verified against sources — don't relearn these)

- **PufferLib 4.0** (`vendor/PufferLib`, branch 4.0) is the target. The `env_binding.h` ABI in online articles is the dead 3.0 pattern; 4.0 uses `src/vecenv.h` macros. **Action masks and the selfplay pool exist ONLY in the CUDA backend** — `--cpu`/`--slowly` ignores masks. So: Mac = standalone C binaries (`build.sh <env> --local`, strip `-mavx2 -mfma` on Apple Silicon); real training = Linux GPU. The env must tolerate illegal sampled actions gracefully.
- `ocean/chess/` is our template (2-player, masked, perm'd self-play, curriculum). `ocean/drive/` for MultiDiscrete. `ocean/convert/` is stale — don't copy it.
- **BB2025 has 30 teams**, a new **Devious** skill category (fouling), and **Elite Skills** (Block/Dodge/Guard/Mighty Blow; 0–4 cap in Matched Play). 6 categories × 12 skills + 36 traits.
- **Rules spec source**: `docs/vendor/bloodbowlbase/` mirror (May 2026 FAQ included, inline `<del>` errata — second sentence is current law). The GW Nov 2025 PDF is superseded by the mirror's FAQ page.
- May 2026 errata: **the "D6 never modified below 1" floor is removed** (above-6 cap remains).
- **FUMBBL replays**: `game` object = END-of-game snapshot; reconstruct kickoff state from setup-phase `fieldModelSetPlayerCoordinate`. Dice/decisions live in `reportList.reports`, not modelChanges (~95% UI noise). The python package's PlayerState bit table is stale — `vendor/ffb/ffb-common/.../PlayerState.java` is authoritative.
- **Jervis** ships parallel `bb2020/` + `bb2025/` test suites (~174 files — diff twins to see BB2025 deltas) and a seeded `FuzzTester` (100k games). Its FUMBBL adapter reads websocket-log format only (not REST JSON) and its **foul conversion is broken** (@Ignore) — don't trust Jervis on fouls.
- **ActionCalculator** (281 test rows) defaults to Season3 = BB2025 — odds rows are valid oracle values nearly as-is.
- **FFB headless** needs MySQL ≤5.6 / MariaDB ≤10.4 (connector 5.1.49) — containerize; `gamestate/get` servlet returns full game JSON (cleanest differential extraction point).

## Conventions

- Engine: C11, zero hot-loop allocation, every die through `bb_rng` (PCG-64 or injected script). Deterministic always.
- Vendored clones are read-only, pinned in `vendor/PINS.md` (re-clone: `tools/vendor_sync.sh`). Doc cache: `docs/SOURCES.md` / `tools/fetch_docs.sh`.
- Atomic commits, no attribution footers, `--no-gpg-sign` if Yubikey absent.
- No GW rulebook text or assets in the repo.
