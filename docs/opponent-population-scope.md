# Scope: reopening the opponent population (frozen bank count)

Written 2026-08-27, from the D282 handoff. Scope only, no code changed.

## Summary

The campaign parked "opponent population" as blocked by the 0.124 frozen bank
ceiling, needing an env or launcher change. That is half right, and the half
that is wrong is the important half.

**0.124 is a ceiling on per bank share at four banks. It is not a ceiling on
the number of opponents.** The bank count is a separate axis, it is a first
class flag in the vec backend, the engine supports 8, and this project ran
8 bank pools for a month in June. Nothing in the env or the engine needs to
change. What needs to change is roughly 6 lines in two launcher scripts,
plus building an obs-v6 pool.

The single number that carries the argument:

| config | per bank rows | total frozen rows | total frozen share |
|---|---|---|---|
| today (chain 9): 4 banks x 0.12 | 122 | 488 | 47.7% |
| proposed: 8 banks x 0.06 | 61 | 488 | 47.7% |

Same opponent share of every buffer, double the opponents.

## Where the ceiling actually comes from

`tools/run_reward_ablation.sh:409-427` computes, in an embedded Python guard:

```
apb        = TOTAL_AGENTS // NUM_BUFFERS      # 2048 // 2 = 1024
per_bank   = int(apb * pct)
total_frozen = 4 * per_bank
if total_frozen >= apb // 2: fail
```

The invariant is **the frozen banks together must occupy less than half of
every buffer**, so learner rows keep the majority. With the `4` hardcoded,
`4 * int(1024 * pct) < 512` solves to `pct < 0.125`, which is where 0.124
comes from. D274 hit this correctly when it tried to raise bot share to 0.18
at four banks: that is genuinely impossible. The error was carrying "0.124 is
the ceiling" forward as if it capped the population, when it caps per bank
share at a fixed population of four.

Rewritten without the hardcode, the constraint is just:

```
N_banks * per_bank_share < 0.5
```

Four banks at 0.12 and eight banks at 0.06 both sit at 0.48, both legal.

## The engine already supports 8

- `puffer/bloodbowl/bloodbowl.h:185`: `#define BBE_MAX_BANKS 8`, commented
  "matches selfplay.py".
- `bloodbowl.h:373-374`: `hist_score_bank[BBE_MAX_BANKS]` and
  `hist_n_bank[BBE_MAX_BANKS]`, telemetry already sized for 8.
- `puffer/bloodbowl/binding.c:217`: validates `scripted_bank_tag` against
  `BBE_MAX_BANKS`, fails closed.
- D97-A records the Python side: "selfplay.py hard RuntimeError above 8".

8 is the hard cap. We are using 4 of it.

## This is not new infrastructure, it is disused infrastructure

The June league campaign ran 8 bank curated pools as its normal mode:

- D97-A: "H2 pool capped at <=8 frozen banks ... frozen_bank_pct must drop to
  ~0.06 for 8 banks vs 0.08 for 5 to stay under the apb/2 cap". The exact
  arithmetic in this document was already written down two months ago.
- D105: league-4 relaunched on an 8 bank pool, `frozen_bank_pct 0.06`, 30B.
- D109-A/D110-A: league-6 and league-6B, same 8 bank design, different warm
  starts, run as a deliberate A/B.
- D109 reports a causal read worth revisiting: curated tier-1 pool composition
  is what drove league5's jump, and the composition principle was explicitly
  "one weak anchor, one kickoff era specialist, one macro artifact, one older
  ratchet, one latest ratchet, one league cap, one exploiter slot", not every
  checkpoint ever made.

Other launchers in the tree still carry it: `tools/run_league.sh:181` runs 5
banks, `tools/run_league9_attrition_ab.sh:25` and `tools/launch_statmatch1.sh:67`
run `--vec.num-frozen-banks 8 --vec.frozen-bank-pct 0.06`, and
`tools/build_league.py:240` emits `--vec.num-frozen-banks {len(seeds)}` for an
arbitrary pool size.

The ladder-rung screen profile, which is what the whole 19 rung hill climb
runs on, is the one path that hardcodes 4.

## What today's four banks actually hold

From the live chain 19 script on the rig: `SCRIPTED_BANK_TAG=4`,
`SCRIPTED_BOT_TYPE=0`, `FROZEN_BANK_PCT=0.12`.

`SCRIPTED_BANK_TAG=b+1` replaces that bank's seat with the scripted bot
(`run_reward_screen.sh:61-64`), so the composition per buffer is:

- 536 rows (52.3%) learner
- 3 banks x 122 rows (35.7%) historical self play snapshots
- 1 bank x 122 rows (11.9%) scripted contact bot, which is the "bot share 0.12"
  the campaign log refers to

Three distinct historical opponents. That is the population the last ten
rejected rungs were trained against.

## Change list: DONE

Implemented on branch `scope/frozen-bank-ceiling`, two atomic commits, default
unchanged at 4 so every existing chain script is inert to it.

- `5d7ecf8` launchers. `NUM_FROZEN_BANKS` becomes an env var validated to
  1..8 in `run_reward_screen.sh` and `run_reward_ablation.sh`, the ablation
  guard takes the count instead of assuming four, `--vec.num-frozen-banks`
  takes the variable, and `SCRIPTED_BANK_TAG` validates against the count
  (single digit, so the pre-existing refusal of non-canonical forms like "01"
  is preserved).
- `6bd9fb2` pool builder. Both `len(out) != 4` gates and the pad loop in
  `ladder_stage.sh` take the requested width, and `POOL_KEEP` defaults to one
  less than the bank count.

Tests: `tools.test_ladder_rung_profile` gains bank-count validation and
scripted-tag range cases; `tools.test_ladder_stage` gains an 8-bank
composition test (anchor sticks, oldest non-anchor retires, warm promoted) and
a too-narrow-pool case. 55 tests green across
`test_ladder_rung_profile`, `test_ladder_knobs`, `test_ladder_stage`,
`test_scripted_training_guard`, plus 39 in `test_reward_manifest` and
`test_experiment_contracts` from inside `tools/`. Every other suite in
`tools/` was run against pristine `origin/main` and this branch: the failure
sets are identical (6 environment dependent suites fail both ways), so nothing
regressed.

The 8-bank composition test earned its place immediately: the first draft of
the resolver change shadowed the existing `banks` seed-list variable and the
test caught it as a TypeError.

## How the pool is actually built, and why 8 is a continuation of D244

`tools/ladder_stage.sh` resolves WARM and POOL from `PREV_COMPLETE` and builds
a **fresh pool every rung**: the weak anchor, plus the newest `POOL_KEEP - 1`
banks of the previous pool, plus the previous rung's accepted checkpoint as the
newest bank. Identity is published to `POOL_IDENTITY.env` so a relaunch reuses
it. `build_league.py` writes `pool/league_seeds.json` plus one flat fp32 `.bin`
per seat, and the loader raises when seed count is not equal to
`num_frozen_banks` or when a seed's byte size is wrong.

The anchor exists because of a failure this project already had. From the
comment at `ladder_stage.sh:160-166`, citing D244 and D166: "a pool that is
four near-identical recent selves is the mutually permissive equilibrium D166
warned about; the first r25-chain collapsed into the abstinence basin against
exactly that pool. Bank 0 is therefore a WEAK ANCHOR that never rotates."

That is the strongest argument for this change. **Pool homogeneity is a known
collapse mode here, and the existing mitigation is one anchor seat out of
four.** Raising the population to 8 is an extension of a fix the project
already believes in, not a new hypothesis.

Worth noting what the four seats actually hold today. Composition order is
[anchor, kept, kept, warm], and `SCRIPTED_BANK_TAG=4` replaces bank index 3,
which is the warm seat. So the learner currently trains against the weak
anchor, two older selves, and the contact bot, and never against its immediate
predecessor.

### Pool work required

The rotation machinery is parameterized by `POOL_KEEP` (default 3), so steady
state at 8 banks is `POOL_KEEP=7`. Two things still need doing:

1. **A one time 8 seed pool build.** Rotation can only ever emit as many banks
   as its predecessor holds, so the first 8 bank rung needs a pool built
   directly with `build_league.py --seeds name=path ...` and 8 entries.
2. **Choosing the 4 new seats.** They must be obs-v6 and byte size compatible.
   The June league seeds are pre obs-v6 and cannot be reused. Candidates, all
   on the rig: the chain lineage (chains 2, 9, 14, 16, 17, 18, and 19 tonight),
   and the August 15-17 backplay ladder accepts (rung 6, 9, 12, uniform), which
   are a different behavioral era and the closest thing available to D109's
   weak anchor and specialist slots.

Verify the blob size of every candidate that is not from the chain lineage
before including it, the backplay accepts included. The July R0 s42 checkpoint
is obs-v4 era and should be excluded from v1.

Per D244 and D109, the four new seats should be picked for behavioral spread.
Filling them with the 7 most recent chain checkpoints would be near-identical
siblings from one plateau, which is precisely the homogeneity the anchor rule
exists to prevent, and would buy population in name only.

## Experiment design

Chain 9 is already the matched control. It is 4 banks x 0.12 with the bot at
tag 4, measured on three exam seeds, and it is the standing frontier. So only
one new arm has to run:

**Arm B: 8 banks x 0.06, bot at tag 8, everything else the kept chain 9
recipe** (`r0_poss_half`, LR 2.8e-4, contact bot, 3B steps, warm from the
chain 9 marker).

| | chain 9 (control, measured) | arm B |
|---|---|---|
| total frozen share | 47.7% | 47.7% |
| distinct historical opponents | 3 | 7 |
| historical share | 35.7% | 41.6% |
| scripted bot share | 11.9% | 6.0% |

Total opponent share is held fixed. Two things move: population 3 to 7, and
bot exposure 12% to 6%. **Those cannot be separated in one run**, because
`SCRIPTED_BANK_TAG` is a single integer and the bot can hold exactly one seat.
Halving per bank share necessarily halves the bot's seat with it.

The honest way to handle that is sequencing, not a binding.c edit:

- If arm B loses, stop. The lever is dead at matched share and no control is
  needed.
- If arm B wins, run **arm C: 4 banks x 0.06, bot at tag 4** (bot 6%,
  3 historical at 18%). C shares arm B's bot exposure with chain 9's
  population, so B vs C isolates population and C vs chain 9 isolates bot
  exposure.

Adding a second bot seat would need a `scripted_bank_tag` to bitmask change in
`binding.c` and `bloodbowl.h` and would re-scope this from a launcher change to
an engine change. Not worth it before arm B says anything.

## Decision rule, pre-registered

This campaign's own standards from D277 and D281 apply, and anything less will
be bounced:

- Two training seeds per arm. One training seed is not a result (D281 had to
  retract D279a for exactly this).
- Exam at seeds 42 and 43, a third seed if the two-seed read lands inside
  noise.
- Champion cells only. Conceded cells move 0.086 from reseeding alone (D277)
  and are unscorable.
- Use the operator's existing D268 rule verbatim rather than a second rule it
  has to reconcile: no cell against the baseline by more than 0.02 AND no net
  differential down by more than 0.02, and to accept, the arm must improve
  outside noise on the cells it targets.
- Verify the launch, in the campaign's usual style, before trusting the run:
  the run manifest shows `num_frozen_banks 8`, the state report covers all 9
  bank buffer groups (1 learner + 8 frozen), and first window telemetry is
  sane. The June evidence for 8 banks predates the current recurrent native
  trainer, which has only been exercised at 4 banks or fewer.
- **`hist_score_bank` telemetry is not evidence here.** It is already one seat
  panel noise at 122 rows per bank, and arm B halves that to 61. The native
  kickoff exam remains the only acceptance metric.

## Cost

About 7 hours per 3B rung on the rig, so roughly 16 hours for arm B at two
training seeds including exams, and the same again for arm C only if B wins.
The rig is owned hardware, so no cash spend. Pool build and script staging is
well under an hour.

## Handoff

D282 item 4 puts this above the operator loop, correctly. Suggested split:

1. A session (not the tick) makes the launcher change, builds and hashes the
   pool, and stages the arm B chain script, the same way chain scripts are
   staged today.
2. `OPERATOR.md` gets an addendum describing arm B and the decision rule above,
   in the same style as the seed re-exam rule added on 2026-08-23.
3. The operator then monitors, exams, and journals under its existing rules.

Nothing should launch until chain 19's verdict is journaled as D283, per the
standing rule against starting a rung while an exam runs.

## Open questions for Alex

1. Pool composition. Curated for behavioral spread per D109, or the 7 most
   recent chain checkpoints? Curated is the stronger experiment and the slower
   one.
2. Whether to include the August backplay ladder accepts, which are obs-v6 but
   from a different reward era and a much older policy generation.
3. Whether an 8 bank pool should also become the default for future ladder
   rungs if arm B wins, or stay an arm.
