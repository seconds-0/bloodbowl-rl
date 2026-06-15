# Brief: configurable skill-advancement entropy in procgen (skillup knobs)

You are implementing a focused feature in a C11 Blood Bowl rules engine + PufferLib env binding.
Repo root: /Users/alexanderhuth/Code/bloodbowl-rl

## Hard rules
- Do NOT commit, push, checkout, stash, or touch git state in any way. Leave changes in the working tree; the architect reviews and commits.
- Do NOT modify DECISIONS.md, training/ scripts, tools/, or any file not listed in the edit map below (tests excepted).
- Do NOT reformat or refactor surrounding code. Match existing style exactly (comment density, naming like `pg_*`, `bbe_*`).
- All existing tests must stay green: run `make test` from engine/ (or repo root — check the Makefile) and the engine selftest target if one exists. Report the exact output.

## Context
At env reset, `procgen_squad` (engine/src/bb_procgen.c:33-141) builds each squad from codegen'd
roster tables. Lines 103-124 already grant random advancements: `advanced = pg_pick(rng, 5)`
players (0-4, WITH replacement) each gain `1 + pg_pick(rng, 2)` skills (1-2), drawn ONLY from
the position's `primary_mask` categories via `bb_random_skill_table[cat][pg_pick(rng, 12)]`.
This is too thin (≈3 advancements/team vs 15-25 in developed human leagues) and primary-only
(cross-category combos like a Block mummy or Guard elf can never be generated). We are making
the intensity and secondary-access configurable via env knobs, with defaults that reproduce the
CURRENT behavior bit-for-bit (identical RNG call sequence — this matters, see Constraints).

## Design

### 1. Engine: `bb_procgen_params`
In the header that declares `bb_match_init_random` / `bb_match_init_forced` (find it under
engine/include/bb/ — likely bb_procgen.h or similar; locate the actual declarations first):

```c
typedef struct {
    int skillup_max_players;   // advancement draws per team, picks WITH replacement (default 4)
    int skillup_max_each;      // max skills gained per draw, uniform 1..max_each (default 2)
    float skillup_secondary_pct; // P(draw category from secondary_mask instead of primary) (default 0.0)
} bb_procgen_params;

bb_procgen_params bb_procgen_params_default(void);
void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
                            const bb_procgen_params* pp);
```

In engine/src/bb_procgen.c:
- Thread `const bb_procgen_params* pp` through `pg_init_match` and `procgen_squad`.
- Keep the old `bb_match_init_random` / `bb_match_init_forced` signatures as thin wrappers
  calling the `_p` variants with `bb_procgen_params_default()` (other callers — tests, demo-bank
  tools, eval — must keep working unchanged).
- Rewrite the advancement block (current lines 103-124) as:
  - `int advanced = pp->skillup_max_players > 0 ? pg_pick(rng, pp->skillup_max_players + 1) : 0;`
    (note: current code is `pg_pick(rng, 5)` = 0..4, so default max_players=4 gives the identical
    draw `pg_pick(rng, 5)` — preserve that exact arithmetic)
  - gains: `1 + pg_pick(rng, pp->skillup_max_each)` when max_each >= 2; for max_each <= 1 use
    gains = max_each (no rng draw needed... actually simplest: `int gains = pp->skillup_max_each >= 2 ?
    1 + pg_pick(rng, pp->skillup_max_each) : pp->skillup_max_each;` — wait, `1 + pg_pick(rng, 2)`
    yields 1..2, so the general form `1 + pg_pick(rng, max_each)` yields 1..max_each. Use that
    form whenever max_each >= 2; it matches current default exactly. For max_each == 1 use gains=1
    without an rng call ONLY if that keeps default-path parity — default is max_each=2 so the
    rng call happens, parity holds. For max_each==1, calling `1 + pg_pick(rng, 1)` also yields 1
    and is simpler — prefer that (one consistent code path, always calls rng).)
  - Category selection per gain: when `pp->skillup_secondary_pct > 0`, draw a float
    (use the existing procgen float/uniform helper if one exists in bb_procgen.c — check how
    other probabilistic knobs draw; if none, use `(bb_rng_next(rng) >> 11) * (1.0/9007199254740992.0)`
    style or an existing bb_rng uniform helper — find what bb_rng.h offers and use the idiomatic
    one). If the draw < secondary_pct use `pd->secondary_mask`, else `pd->primary_mask`.
    If the chosen mask is 0, fall back to the other mask; if both are 0, `continue` (matches
    current `if (!pd->primary_mask) continue;` guard — keep that early-continue ONLY for the
    both-masks-empty case now, and keep it BEFORE any per-gain rng draws so the default path
    (secondary_pct==0, primary-only) makes exactly the same rng calls as today).
  - CRITICAL RNG-parity rule: when `skillup_secondary_pct == 0.0`, the function must make
    EXACTLY the same sequence of rng calls as the current code (same pg_pick counts and bounds).
    Guard the secondary-roll behind `if (pp->skillup_secondary_pct > 0.0f)` so no extra draw
    happens at defaults. There are determinism-sensitive tests and banked demo states; default
    procgen streams must not shift.
  - Keep `pg_skill_count(&p->skills) >= PG_MAX_SKILLS` cap and `bb_add_skill` dedup semantics
    (re-granting an owned skill wastes the gain — that is current behavior, keep it).

### 2. Env binding: 3 knobs
Follow the existing 3-sync-point pattern (reference example: `demo_pickup_maxdist` at
puffer/bloodbowl/bloodbowl.h:304, puffer/bloodbowl/binding.c:88-89, puffer/config/bloodbowl.ini:84-89):

- puffer/bloodbowl/bloodbowl.h: add to the Env struct (near the other curriculum knobs ~line 296-345):
  `int skillup_max_players; int skillup_max_each; float skillup_secondary_pct;`
  In `bbe_reset_match` (~lines 1303-1316), build a `bb_procgen_params` from the env fields and
  call the `_p` variants at BOTH call sites (`bb_match_init_forced` and `bb_match_init_random`).
- puffer/bloodbowl/binding.c (~lines 87-101, near the other kw() reads):
  ```c
  env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
  env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
  env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
  ```
- puffer/config/bloodbowl.ini: add the three keys with defaults (4, 2, 0.0) and a short comment
  block explaining: skill-entropy knobs; defaults = historical behavior; crank for
  developed-league rosters (e.g. 11 / 3 / 0.35).
- IMPORTANT: search the repo for OTHER copies of bloodbowl.ini (e.g. under vendor/PufferLib/)
  and add the same keys to every copy you find. A stale installed copy causes
  "unrecognized arguments" at launch (known footgun).

### 3. Tests (engine, rigorous — this is the deliverable's spine)
Add to the existing engine test suite (find how current procgen/unit tests are organized under
engine/tests/ and follow that harness's conventions). Required cases:

1. **Default parity**: with a fixed seed, `bb_match_init_random(m, rng)` (old API) and
   `bb_match_init_random_p(m, rng2, &defaults)` from the same seed produce byte-identical
   `bb_match` (memcmp). This pins wrapper correctness AND rng parity.
2. **Off switch**: params {0, 2, 0.0} → for many seeds (≥100 squads), every player's skillset
   equals exactly their position's base roster skills (no extra bits set).
3. **Primary-only at secondary_pct=0**: params {11, 3, 0.0}, ≥500 squads: every granted skill
   (set-diff vs base position skills) belongs to a category in that position's primary_mask
   (use the skill→category table; find how the engine exposes skill categories — gen_skills.h).
4. **Secondary-only at secondary_pct=1**: params {11, 3, 1.0}, ≥500 squads: every granted skill's
   category is in secondary_mask, EXCEPT positions with secondary_mask==0 where primary fallback
   applies (assert those grants are in primary_mask).
5. **Full-catalogue coverage**: params {11, 3, 0.5}, iterate random matches with a fixed seed
   until every one of the 72 learnable skills (category != 0xFF) has been granted at least once
   across all squads, with a hard iteration cap (e.g. 20000 squads → fail if not all seen;
   deterministic seed so it cannot flake). This proves the entropy knobs reach the whole catalogue.
6. **Cap respected**: cranked params never push `pg_skill_count` past PG_MAX_SKILLS, and squads
   stay structurally valid (>= 11 players, qty bounds — reuse any existing squad-validity asserts).
7. **Determinism**: same seed + same params twice → memcmp-identical matches.

### 4. Sanity: throughput
After building the puffer binding (`bash build.sh` pattern or however puffer/ builds — check
the repo's build scripts / project skill docs; if the puffer vendor build isn't available on this
Mac, skip the binding build and say so), confirm engine tests pass. Do NOT launch any training.

## Constraints recap
- Defaults (4, 2, 0.0) must reproduce current behavior with an identical RNG stream.
- No changes to observation encoding (the 12 skill-byte slots already truncate; PG_MAX_SKILLS guards).
- Parametrized skill values: `bb_add_skill` semantics as-is (same as current line 122); do not
  invent per-player value storage.
- C11, no allocations in hot paths, fixed-size everything — match the engine's idiom.

## Report back (final message)
1. Edit map: every file touched with line ranges and a one-line purpose each.
2. Full `make test` (and selftest) output, plus the new tests' names and pass status.
3. Any deviation from this brief, with reasoning.
4. Anything you noticed that looks like a pre-existing bug (do not fix it — report it).
