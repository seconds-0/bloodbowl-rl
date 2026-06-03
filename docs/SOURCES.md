# External doc cache — sources index

`docs/vendor/` is gitignored. Re-fetch with the commands below (or `tools/fetch_docs.sh` once it exists). Cached 2026-06-02.

## Papers (`docs/vendor/papers/`)

| File | Source |
|------|--------|
| `bloodbowl-challenge-justesen2019.pdf` | https://njustesen.github.io/njustesen/publications/justesen2019blood.pdf — "Blood Bowl: A New Board Game Challenge and Competition for AI" (IEEE CoG 2019) |
| `bloodbowl-deeprl-justesen2018.pdf` | https://njustesen.github.io/njustesen/publications/justesen2018blood.pdf — deep RL approach to Blood Bowl |
| `roe-rarity-of-events-justesen2018.pdf` | https://arxiv.org/pdf/1803.07131 — Rarity of Events reward shaping |
| `mimicbot-2108.09478.pdf` | https://arxiv.org/pdf/2108.09478 — MimicBot (BC warm-start, Bot Bowl III winner) |
| `invalid-action-masking-2006.14171.pdf` | https://arxiv.org/pdf/2006.14171 — Huang & Ontañón, invalid action masking in PPO |
| `stochastic-muzero-iclr2022.pdf` | https://openreview.net/pdf?id=X6D9bAHhBQ1 — Antonoglou et al., planning with chance/afterstates |
| `pufferlib-2406.12905.pdf` | https://arxiv.org/pdf/2406.12905 — PufferLib paper |
| `mini-alphastar-2104.06890.pdf` | https://arxiv.org/pdf/2104.06890 — mini-AlphaStar (autoregressive action heads reference) |

## GW official (`docs/vendor/gw/`)

| File | Source |
|------|--------|
| `bb-faq-errata-nov2025.pdf` | https://assets.warhammer-community.com/eng_14-11_bloodbowl_faq_errata-ngh7bivuzu-vslz4fw2nm.pdf — Designer's Commentary + Errata, Third Season, Nov 2025. GW posts updates each May/Nov at https://www.warhammer-community.com/en-gb/downloads/blood-bowl/ (JS-rendered; find asset URLs via search or community mirrors) |

## BB2025 rules reference (`docs/vendor/bloodbowlbase/`)

Polite mirror (wget, rate-limited) of https://bloodbowlbase.ru/bb2025/ — full Third Season rules reference: core rules, skills & traits (with ACTIVE/PASSIVE annotations), inducements, 31 team rosters, star players, latest FAQ (May 2026). Re-mirror: see command in git history or `tools/fetch_docs.sh`.

## PufferLib (`docs/vendor/pufferlib/`)

`docs.html`, `blog.html`, `ocean.html` from https://puffer.ai/. NOTE: much online material describes the 3.0 `env_binding.h` ABI; we target the **4.0 branch** `src/vecenv.h` macro ABI (see `vendor/PINS.md` and the `puffer-env-dev` skill).

## FUMBBL (`docs/vendor/fumbbl/`)

`api-notes-730.html` from https://fumbbl.com/p/notes?op=view&id=730 (official API doc). Verified live 2026-06-02: `GET /api/match/get/<id>` (tournamentId, division, coach rating cr/bracket, conceded, replayId), `GET /api/replay/get/<replayId>/gz` — public, no auth. Etiquette: throttle ~1 req/s, cache locally, courtesy heads-up to Christer before mass pulls.
