# Vendored reference repos (read-only, gitignored)

Shallow clones for reference. Re-clone with `tools/vendor_sync.sh`. Pinned SHAs as of 2026-06-02:

| Repo | SHA | Date | Branch | Role |
|------|-----|------|--------|------|
| [PufferAI/PufferLib](https://github.com/PufferAI/PufferLib) | `9836f0d2e78889c1aaf189c04d161b6fc61a9386` | 2026-05-25 | 4.0 | RL framework target. **4.0 ABI**: `src/vecenv.h` macro binding (not 3.0's `env_binding.h`); native `MY_ACTION_MASK`, MultiDiscrete `ACT_SIZES`, built-in selfplay pool (`pufferlib/selfplay.py`). Best template: `ocean/chess/` (2-player, masked, perm'd, curriculum) |
| [christerk/ffb](https://github.com/christerk/ffb) | `c98fd120229b55846b3c1c38ec279ec729d78a6f` | 2026-04-19 | master | **Primary oracle** — the engine FUMBBL runs (BB2025 at HEAD). Java, MIT. Headless: `com.fumbbl.ffb.server.FantasyFootballServer` standalone + MySQL |
| [cmelchior/jervis-ffb](https://github.com/cmelchior/jervis-ffb) | `2063a286da1239fb694b20302d6071012e41c484` | 2026-06-02 | main | Secondary oracle — standalone Kotlin rules engine, FUMBBL replay converter (`replay-analyzer`) |
| [gsverhoeven/fumbbl_replays](https://github.com/gsverhoeven/fumbbl_replays) | `e73776b19f056ed62798df033ae845c73ae4d42d` | 2026-05-25 | master | Replay fetch/parse reference (Python). API endpoints in `src/fumbbl_replays/fetch_*.py` |
| [njustesen/botbowl](https://github.com/njustesen/botbowl) | `3e550bda3666c39efe478fb9465646af24576665` | 2023-08-25 | main | BB2016 prior art — obs/action encoding reference, GrodBot, edition-invariant sanity oracle |
| [BloodBowlDave/BloodBowlActionCalculator](https://github.com/BloodBowlDave/BloodBowlActionCalculator) | `5baa0ee760734735689382c44104242614ec1cef` | 2026-05-10 | master | Probability oracle (C#, ~200 param tests, Season toggle) for statistical conformance |
