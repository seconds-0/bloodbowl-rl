# Fix brief: skillup knobs — restore RNG parity for secondary-only positions

Follow-up to the skillup-knobs implementation you just completed in
/Users/alexanderhuth/Code/bloodbowl-rl (working tree, uncommitted). Same hard rules:
no git state changes of any kind, no files beyond those named here, match existing style,
`make test` must end green, report back with edit map + test output.

## The bug (review finding)
Two roster positions have EMPTY primary_mask but non-empty secondary_mask:
gnome `Woodland Fox` and norse `Beer Boar` (secondary = agility only).

Legacy code: `if (!pd->primary_mask) continue;` — these positions NEVER advanced and the
`gains` rng draw never happened for them.

Your new guard in engine/src/bb_procgen.c (`if (!(pd->primary_mask || pd->secondary_mask)) continue;`)
lets them through, so AT DEFAULTS (skillup_secondary_pct == 0.0) a gnome/norse squad that
draws a fox/boar for advancement now (a) consumes extra rng (`gains` draw + per-gain draws),
shifting the default procgen stream vs legacy, and (b) grants agility skills via the
mask-fallback that legacy never granted. This violates the default-parity requirement.
The single-seed parity test didn't sample a gnome/norse advancement so it passed.

## Fix
In the advancement block of `procgen_squad` (engine/src/bb_procgen.c), replace the guard:

```c
if (!(pd->primary_mask || pd->secondary_mask)) continue;
```

with:

```c
uint8_t access = pd->primary_mask;
if (pp->skillup_secondary_pct > 0.0f) access |= pd->secondary_mask;
if (!access) continue;
```

Semantics: at defaults (pct == 0) this is exactly the legacy guard — secondary-only positions
`continue` BEFORE the `gains` rng draw, bit-identical stream. With pct > 0 they may advance,
and the existing per-gain roll+fallback already routes them to secondary correctly (mask
starts at primary==0; either the roll sets secondary or the fallback flips to it). Leave the
per-gain logic untouched.

## Test hardening (engine/tests/test_match.c)
1. **Strengthen `match_procgen_default_params_match_legacy_api`**: loop seeds 1..300
   (vary both seed and stream-id like the other tests do) instead of the single seed;
   memcmp the matches AND `procgen_rng_same_state` each iteration. 300 random matches will
   include gnome/norse squads with advancement draws, pinning the fox/boar parity forever.
2. **New test `match_procgen_secondary_only_positions_inert_at_defaults`**: locate the
   gnome and norse team ids at runtime by scanning `bb_team_defs` for any position with
   `primary_mask == 0 && secondary_mask != 0` (assert you find >= 2 such team ids — fail
   loudly if roster data changes). For ~100 seeds, `bb_match_init_forced_p(home=<gnome>,
   away=<norse>, exclude=-1, defaults)`: every player whose position has
   `primary_mask == 0` must have skillset memcmp-equal to their base position skills.
3. **New test `match_procgen_secondary_only_positions_advance_with_pct`**: same forced
   gnome-vs-norse matchup, params {11, 3, 0.5f}, iterate seeds until a player with
   `primary_mask == 0` has a granted skill (cap ~2000 seeds, deterministic; fail if never
   seen). Assert every such grant's category is in that position's secondary_mask.

## Verify + report
- `make test` full suite green (state the final "N tests, 0 failures" line).
- Re-run the binding local compile + `--selftest` exactly as you did before; report output.
- Edit map with file:line, any deviations, anything that looks off.
