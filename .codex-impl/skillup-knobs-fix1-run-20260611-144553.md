Reading additional input from stdin...
OpenAI Codex v0.139.0
--------
workdir: /Users/alexanderhuth/Code/bloodbowl-rl
model: gpt-5.5
provider: openai
approval: never
sandbox: danger-full-access
reasoning effort: medium
reasoning summaries: none
session id: 019eb8a6-230d-7d01-87d2-5101a4516ef0
--------
user
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
deprecated: `[features].collab` is deprecated. Use `[features].multi_agent` instead.
Enable it with `--enable multi_agent` or `[features].multi_agent` in config.toml. See https://developers.openai.com/codex/config-basic#feature-flags for details.
codex
I’ll make the narrow parity fix and harden the tests exactly in the two named files. I’ll first inspect the current procgen/test shapes so the edits land cleanly and don’t disturb the uncommitted work around them.
exec
/bin/zsh -lc 'git diff -- engine/src/bb_procgen.c engine/tests/test_match.c' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee..4819137 100644
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@ static int pg_skill_count(const bb_skillset* s) {
     return n;
 }
 
+static float pg_float01(bb_rng* rng) {
+    return (float)(bb_rng_next(rng) >> 8) * (1.0f / 16777216.0f);
+}
+
+bb_procgen_params bb_procgen_params_default(void) {
+    return (bb_procgen_params){4, 2, 0.0f};
+}
+
 // Build one team's squad: positionals first (random counts within limits),
-// topped up with the first listed position; 0-4 players get 1-2 random
-// advancement skills from their primary categories.
-static void procgen_squad(bb_match* m, int team, int team_id, bb_rng* rng) {
+// topped up with the first listed position; then configured random
+// advancement skills from primary/secondary categories.
+static void procgen_squad(bb_match* m, int team, int team_id, bb_rng* rng,
+                          const bb_procgen_params* pp) {
     const bb_team_def* td = &bb_team_defs[team_id];
     int base = team * BB_TEAM_SLOTS;
     int n = 0;
@@ -100,22 +109,31 @@ static void procgen_squad(bb_match* m, int team, int team_id, bb_rng* rng) {
         m->players[base + s].location = BB_LOC_ABSENT;
     }
 
-    // Advancement: 0-4 players gain 1-2 random skills from a primary category
+    // Advancement: players gain random skills from configured category access
     // (the 2D6 random-skill table run "fairly" via the procgen stream).
-    int advanced = pg_pick(rng, 5);
+    int advanced = pp->skillup_max_players > 0 ? pg_pick(rng, pp->skillup_max_players + 1) : 0;
     for (int i = 0; i < advanced; i++) {
         int who = base + pg_pick(rng, n);
         bb_player* p = &m->players[who];
         const bb_position_def* pd = &td->positions[p->position_id];
-        if (!pd->primary_mask) continue;
-        int gains = 1 + pg_pick(rng, 2);
+        if (!(pd->primary_mask || pd->secondary_mask)) continue;
+        int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
         for (int g = 0; g < gains; g++) {
             if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;
-            // Pick a random primary category bit.
+            uint8_t mask = pd->primary_mask;
+            if (pp->skillup_secondary_pct > 0.0f &&
+                pg_float01(rng) < pp->skillup_secondary_pct) {
+                mask = pd->secondary_mask;
+            }
+            if (!mask) {
+                mask = (mask == pd->primary_mask) ? pd->secondary_mask : pd->primary_mask;
+            }
+            if (!mask) continue;
+            // Pick a random category bit.
             int cats[BB_CAT_COUNT];
             int nc = 0;
             for (int c = 0; c < BB_CAT_COUNT; c++) {
-                if (pd->primary_mask & (1 << c)) cats[nc++] = c;
+                if (mask & (1 << c)) cats[nc++] = c;
             }
             int cat = cats[pg_pick(rng, nc)];
             int sk = bb_random_skill_table[cat][pg_pick(rng, 12)];
@@ -140,11 +158,12 @@ static void procgen_squad(bb_match* m, int team, int team_id, bb_rng* rng) {
     }
 }
 
-static void pg_init_match(bb_match* m, bb_rng* rng, int home, int away) {
+static void pg_init_match(bb_match* m, bb_rng* rng, int home, int away,
+                          const bb_procgen_params* pp) {
     m->team_id[BB_HOME] = (uint8_t)home;
     m->team_id[BB_AWAY] = (uint8_t)away;
-    procgen_squad(m, BB_HOME, home, rng);
-    procgen_squad(m, BB_AWAY, away, rng);
+    procgen_squad(m, BB_HOME, home, rng, pp);
+    procgen_squad(m, BB_AWAY, away, rng, pp);
     for (int t = 0; t < 2; t++) {
         m->rerolls[t] = m->rerolls_start[t] = (uint8_t)(2 + pg_pick(rng, 3));
         m->apothecary[t] = bb_team_defs[m->team_id[t]].apothecary ? 1 : 0;
@@ -157,10 +176,15 @@ static void pg_init_match(bb_match* m, bb_rng* rng, int home, int away) {
 }
 
 void bb_match_init_random(bb_match* m, bb_rng* rng) {
+    bb_procgen_params pp = bb_procgen_params_default();
+    bb_match_init_random_p(m, rng, &pp);
+}
+
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp) {
     memset(m, 0, sizeof(*m));
     int home = pg_pick(rng, BB_TEAM_COUNT);
     int away = pg_pick(rng, BB_TEAM_COUNT);
-    pg_init_match(m, rng, home, away);
+    pg_init_match(m, rng, home, away, pp);
 }
 
 // Holdout / fixed-matchup variant: home/away >= 0 pin that side's team;
@@ -168,6 +192,12 @@ void bb_match_init_random(bb_match* m, bb_rng* rng) {
 // held-out-team generalization experiments train with exclude set and
 // evaluate with force_* set).
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude) {
+    bb_procgen_params pp = bb_procgen_params_default();
+    bb_match_init_forced_p(m, rng, home, away, exclude, &pp);
+}
+
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp) {
     memset(m, 0, sizeof(*m));
     int h = home;
     while (h < 0 || (home < 0 && h == exclude)) {
@@ -179,5 +209,5 @@ void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int excl
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3..99774f8 100644
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,192 @@ BB_TEST(match_procgen_skill_cap) {
     }
 }
 
+static bb_skillset base_position_skills(const bb_position_def* pd) {
+    bb_skillset s;
+    memset(&s, 0, sizeof s);
+    for (int i = 0; i < pd->num_skills; i++) bb_add_skill(&s, pd->skills[i]);
+    return s;
+}
+
+static int procgen_squad_total(const bb_match* m, int team) {
+    int n = 0;
+    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
+        if (m->players[s].location != BB_LOC_ABSENT) n++;
+    }
+    return n;
+}
+
+static void check_procgen_structure(const bb_match* m) {
+    for (int t = 0; t < 2; t++) {
+        int counts[BB_MAX_POSITIONS] = {0};
+        const bb_team_def* td = &bb_team_defs[m->team_id[t]];
+        int total = 0;
+        for (int s = t * BB_TEAM_SLOTS; s < (t + 1) * BB_TEAM_SLOTS; s++) {
+            const bb_player* p = &m->players[s];
+            if (p->location == BB_LOC_ABSENT) continue;
+            BB_CHECK(p->position_id < td->num_positions);
+            if (p->position_id < td->num_positions) counts[p->position_id]++;
+            total++;
+        }
+        BB_CHECK(total >= 11);
+        BB_CHECK(total <= 14);
+        for (int pi = 0; pi < td->num_positions; pi++) {
+            BB_CHECK(counts[pi] <= td->positions[pi].qty_max);
+        }
+    }
+}
+
+static int procgen_count_skills(const bb_skillset* s) {
+    int n = 0;
+    for (int sk = bb_next_skill(s, 0); sk >= 0; sk = bb_next_skill(s, sk + 1)) n++;
+    return n;
+}
+
+static int procgen_rng_same_state(const bb_rng* a, const bb_rng* b) {
+    return a->state == b->state && a->inc == b->inc &&
+           a->script == b->script && a->script_len == b->script_len &&
+           a->script_pos == b->script_pos && a->mode == b->mode &&
+           a->error == b->error && a->sink == b->sink &&
+           a->sink_user == b->sink_user;
+}
+
+static void check_procgen_grants_in_mask(const bb_match* m, int secondary_only) {
+    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+        const bb_player* p = &m->players[s];
+        if (p->location == BB_LOC_ABSENT) continue;
+        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
+        const bb_position_def* pd = &td->positions[p->position_id];
+        bb_skillset base = base_position_skills(pd);
+        uint8_t want = secondary_only && pd->secondary_mask ? pd->secondary_mask : pd->primary_mask;
+        if (!want) want = secondary_only ? pd->primary_mask : pd->secondary_mask;
+        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
+             sk = bb_next_skill(&p->skills, sk + 1)) {
+            if (bb_has_skill(&base, sk)) continue;
+            uint8_t cat = bb_skill_defs[sk].category;
+            BB_CHECK(cat < BB_CAT_COUNT);
+            BB_CHECK(want & (1 << cat));
+            if (!(want & (1 << cat))) {
+                printf("  team %d pos %d skill %d cat %d want 0x%x\n",
+                       m->team_id[BB_TEAM_OF(s)], p->position_id, sk, cat, want);
+                return;
+            }
+        }
+    }
+}
+
+BB_TEST(match_procgen_default_params_match_legacy_api) {
+    bb_procgen_params pp = bb_procgen_params_default();
+    bb_match a, b;
+    bb_rng r1, r2;
+    bb_rng_seed(&r1, 0x515A5EEDu, 17);
+    bb_rng_seed(&r2, 0x515A5EEDu, 17);
+    bb_match_init_random(&a, &r1);
+    bb_match_init_random_p(&b, &r2, &pp);
+    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
+    BB_CHECK(procgen_rng_same_state(&r1, &r2));
+}
+
+BB_TEST(match_procgen_skillups_off_keeps_base_skills) {
+    bb_procgen_params pp = {0, 2, 0.0f};
+    for (uint64_t seed = 1; seed <= 50; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 2654435761u, 23);
+        bb_match_init_random_p(&m, &pg, &pp);
+        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+            const bb_player* p = &m.players[s];
+            if (p->location == BB_LOC_ABSENT) continue;
+            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
+            bb_skillset base = base_position_skills(&td->positions[p->position_id]);
+            BB_CHECK_EQ(memcmp(&p->skills, &base, sizeof(bb_skillset)), 0);
+        }
+    }
+}
+
+BB_TEST(match_procgen_primary_only_uses_primary_categories) {
+    bb_procgen_params pp = {11, 3, 0.0f};
+    for (uint64_t seed = 1; seed <= 250; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 7919, 29);
+        bb_match_init_random_p(&m, &pg, &pp);
+        check_procgen_grants_in_mask(&m, 0);
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_uses_secondary_or_primary_fallback) {
+    bb_procgen_params pp = {11, 3, 1.0f};
+    for (uint64_t seed = 1; seed <= 250; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 104729, 31);
+        bb_match_init_random_p(&m, &pg, &pp);
+        check_procgen_grants_in_mask(&m, 1);
+    }
+}
+
+BB_TEST(match_procgen_skillups_reach_full_learnable_catalogue) {
+    bb_procgen_params pp = {11, 3, 0.5f};
+    uint8_t seen[BB_NUM_SKILLS] = {0};
+    int nseen = 0;
+    for (uint64_t seed = 1; seed <= 10000 && nseen < BB_NUM_SKILLS; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, 0xC0FFEEu + seed * 17, 37);
+        bb_match_init_random_p(&m, &pg, &pp);
+        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+            const bb_player* p = &m.players[s];
+            if (p->location == BB_LOC_ABSENT) continue;
+            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
+            const bb_position_def* pd = &td->positions[p->position_id];
+            bb_skillset base = base_position_skills(pd);
+            for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
+                 sk = bb_next_skill(&p->skills, sk + 1)) {
+                if (sk >= BB_NUM_SKILLS || bb_has_skill(&base, sk)) continue;
+                if (!seen[sk]) {
+                    seen[sk] = 1;
+                    nseen++;
+                }
+            }
+        }
+    }
+    BB_CHECK_EQ(nseen, BB_NUM_SKILLS);
+    if (nseen != BB_NUM_SKILLS) {
+        for (int sk = 0; sk < BB_NUM_SKILLS; sk++) {
+            if (!seen[sk]) printf("  missing skill %d (%s)\n", sk, bb_skill_defs[sk].id);
+        }
+    }
+}
+
+BB_TEST(match_procgen_cranked_params_respect_cap_and_structure) {
+    bb_procgen_params pp = {16, 12, 0.5f};
+    for (uint64_t seed = 1; seed <= 200; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 16127, 41);
+        bb_match_init_random_p(&m, &pg, &pp);
+        check_procgen_structure(&m);
+        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+            if (m.players[s].location == BB_LOC_ABSENT) continue;
+            BB_CHECK(procgen_count_skills(&m.players[s].skills) <= 12);
+        }
+        BB_CHECK(procgen_squad_total(&m, BB_HOME) >= 11);
+        BB_CHECK(procgen_squad_total(&m, BB_AWAY) >= 11);
+    }
+}
+
+BB_TEST(match_procgen_params_are_deterministic) {
+    bb_procgen_params pp = {11, 3, 0.35f};
+    bb_match a, b;
+    bb_rng r1, r2;
+    bb_rng_seed(&r1, 0x12345678u, 43);
+    bb_rng_seed(&r2, 0x12345678u, 43);
+    bb_match_init_random_p(&a, &r1, &pp);
+    bb_match_init_random_p(&b, &r2, &pp);
+    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
+    BB_CHECK(procgen_rng_same_state(&r1, &r2));
+}
+
 BB_TEST(match_procgen_games_complete) {
     for (uint64_t seed = 1; seed <= 12; seed++) {
         bb_match m;

exec
/bin/zsh -lc 'rg -n "primary_mask|secondary_mask|skillup_secondary_pct|match_procgen_default_params_match_legacy_api|bb_match_init_forced_p|procgen_rng_same_state" engine/src/bb_procgen.c engine/tests/test_match.c' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 109ms:
engine/tests/test_match.c:249:static int procgen_rng_same_state(const bb_rng* a, const bb_rng* b) {
engine/tests/test_match.c:264:        uint8_t want = secondary_only && pd->secondary_mask ? pd->secondary_mask : pd->primary_mask;
engine/tests/test_match.c:265:        if (!want) want = secondary_only ? pd->primary_mask : pd->secondary_mask;
engine/tests/test_match.c:281:BB_TEST(match_procgen_default_params_match_legacy_api) {
engine/tests/test_match.c:290:    BB_CHECK(procgen_rng_same_state(&r1, &r2));
engine/tests/test_match.c:391:    BB_CHECK(procgen_rng_same_state(&r1, &r2));
engine/src/bb_procgen.c:119:        if (!(pd->primary_mask || pd->secondary_mask)) continue;
engine/src/bb_procgen.c:123:            uint8_t mask = pd->primary_mask;
engine/src/bb_procgen.c:124:            if (pp->skillup_secondary_pct > 0.0f &&
engine/src/bb_procgen.c:125:                pg_float01(rng) < pp->skillup_secondary_pct) {
engine/src/bb_procgen.c:126:                mask = pd->secondary_mask;
engine/src/bb_procgen.c:129:                mask = (mask == pd->primary_mask) ? pd->secondary_mask : pd->primary_mask;
engine/src/bb_procgen.c:196:    bb_match_init_forced_p(m, rng, home, away, exclude, &pp);
engine/src/bb_procgen.c:199:void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,

codex
I found the regression point and the existing helper tests from the prior knob work. The fix itself is tiny; the heavier part is adding the two roster-data-driven checks so future roster changes fail loudly instead of quietly drifting RNG parity.
exec
/bin/zsh -lc "sed -n '1,170p' engine/src/bb_procgen.c" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
// bb_procgen.c — procedural match generation for RL training.
//
// Every reset samples a fresh matchup: random rosters, squad compositions,
// advancement skills and re-roll counts, drawn from the codegen'd team
// definitions. This is what forces the policy to generalize across the
// trillions of team states instead of memorizing one matchup.
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb/bb_hooks.h"
#include "bb/gen_teams.h"
#include <string.h>

// Uniform integer in [0, n) from the procgen stream.
static int pg_pick(bb_rng* rng, int n) {
    return n > 0 ? (int)(bb_rng_next(rng) % (uint32_t)n) : 0;
}

// Total-skill cap for procgen players. The RL observation encodes skills as
// a fixed list of 12 id slots (puffer/bloodbowl/bloodbowl.h BBE_SKILL_SLOTS);
// the largest base roster list is 10, so capping advancement at 12 keeps the
// obs lossless. Raise both together if star players ever exceed this.
#define PG_MAX_SKILLS 12

static int pg_skill_count(const bb_skillset* s) {
    int n = 0;
    for (int sk = bb_next_skill(s, 0); sk >= 0; sk = bb_next_skill(s, sk + 1)) n++;
    return n;
}

static float pg_float01(bb_rng* rng) {
    return (float)(bb_rng_next(rng) >> 8) * (1.0f / 16777216.0f);
}

bb_procgen_params bb_procgen_params_default(void) {
    return (bb_procgen_params){4, 2, 0.0f};
}

// Build one team's squad: positionals first (random counts within limits),
// topped up with the first listed position; then configured random
// advancement skills from primary/secondary categories.
static void procgen_squad(bb_match* m, int team, int team_id, bb_rng* rng,
                          const bb_procgen_params* pp) {
    const bb_team_def* td = &bb_team_defs[team_id];
    int base = team * BB_TEAM_SLOTS;
    int n = 0;
    int counts[BB_MAX_POSITIONS] = {0};

    // Roster size 11-14.
    int squad = 11 + pg_pick(rng, 4);

    // Fill positional slots (positions[1..]) with random counts.
    for (int pi = td->num_positions - 1; pi >= 1 && n < squad; pi--) {
        const bb_position_def* pd = &td->positions[pi];
        int want = pg_pick(rng, pd->qty_max + 1);
        while (want-- > 0 && n < squad) {
            // init_player_from_position equivalent (kept local to this TU):
            bb_player* p = &m->players[base + n];
            memset(p, 0, sizeof(*p));
            p->ma = pd->ma;
            p->st = pd->st;
            p->ag = pd->ag;
            p->pa = pd->pa;
            p->av = pd->av;
            p->position_id = (uint8_t)pi;
            p->location = BB_LOC_RESERVES;
            p->stance = BB_STANCE_STANDING;
            p->p_loner = 4;
            for (int s = 0; s < pd->num_skills; s++) {
                bb_add_skill(&p->skills, pd->skills[s]);
                int v = pd->skill_values[s];
                if (v > 0) {
                    if (pd->skills[s] == BB_SK_LONER) p->p_loner = (int8_t)v;
                    if (pd->skills[s] == BB_SK_BLOODLUST) p->p_bloodlust = (int8_t)v;
                }
            }
            counts[pi]++;
            n++;
        }
    }
    // Top up with the first-listed position (linemen).
    while (n < squad) {
        const bb_position_def* pd = &td->positions[0];
        bb_player* p = &m->players[base + n];
        memset(p, 0, sizeof(*p));
        p->ma = pd->ma;
        p->st = pd->st;
        p->ag = pd->ag;
        p->pa = pd->pa;
        p->av = pd->av;
        p->position_id = 0;
        p->location = BB_LOC_RESERVES;
        p->stance = BB_STANCE_STANDING;
        p->p_loner = 4;
        for (int s = 0; s < pd->num_skills; s++) {
            bb_add_skill(&p->skills, pd->skills[s]);
            // Keep the roster's parameterized skill values, like the
            // positional path above — dropping them left p_bloodlust 0
            // (gate silently inert) and p_loner at the default (review LOW).
            int v = pd->skill_values[s];
            if (v > 0) {
                if (pd->skills[s] == BB_SK_LONER) p->p_loner = (int8_t)v;
                if (pd->skills[s] == BB_SK_BLOODLUST) p->p_bloodlust = (int8_t)v;
            }
        }
        n++;
    }
    for (int s = n; s < BB_TEAM_SLOTS; s++) {
        memset(&m->players[base + s], 0, sizeof(bb_player));
        m->players[base + s].location = BB_LOC_ABSENT;
    }

    // Advancement: players gain random skills from configured category access
    // (the 2D6 random-skill table run "fairly" via the procgen stream).
    int advanced = pp->skillup_max_players > 0 ? pg_pick(rng, pp->skillup_max_players + 1) : 0;
    for (int i = 0; i < advanced; i++) {
        int who = base + pg_pick(rng, n);
        bb_player* p = &m->players[who];
        const bb_position_def* pd = &td->positions[p->position_id];
        if (!(pd->primary_mask || pd->secondary_mask)) continue;
        int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
        for (int g = 0; g < gains; g++) {
            if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;
            uint8_t mask = pd->primary_mask;
            if (pp->skillup_secondary_pct > 0.0f &&
                pg_float01(rng) < pp->skillup_secondary_pct) {
                mask = pd->secondary_mask;
            }
            if (!mask) {
                mask = (mask == pd->primary_mask) ? pd->secondary_mask : pd->primary_mask;
            }
            if (!mask) continue;
            // Pick a random category bit.
            int cats[BB_CAT_COUNT];
            int nc = 0;
            for (int c = 0; c < BB_CAT_COUNT; c++) {
                if (mask & (1 << c)) cats[nc++] = c;
            }
            int cat = cats[pg_pick(rng, nc)];
            int sk = bb_random_skill_table[cat][pg_pick(rng, 12)];
            bb_add_skill(&p->skills, sk);
        }
    }

    // Pre-game injuries: 0-2 players start in the casualty box (simulating
    // league attrition) — only if the squad stays >= 11. Picks are WITHOUT
    // replacement: sampling the raw slot range could hit the same player
    // twice, under-delivering 2-casualty squads ~7-9% (review LOW).
    int hurt = pg_pick(rng, 3);
    for (int i = 0; i < hurt && n - i > 11; i++) {
        int pick = pg_pick(rng, n - i); // index among the still-healthy
        for (int s = base; s < base + n; s++) {
            if (m->players[s].location == BB_LOC_CAS) continue;
            if (pick-- == 0) {
                m->players[s].location = BB_LOC_CAS;
                break;
            }
        }
    }
}

static void pg_init_match(bb_match* m, bb_rng* rng, int home, int away,
                          const bb_procgen_params* pp) {
    m->team_id[BB_HOME] = (uint8_t)home;
    m->team_id[BB_AWAY] = (uint8_t)away;
    procgen_squad(m, BB_HOME, home, rng, pp);
    procgen_squad(m, BB_AWAY, away, rng, pp);
    for (int t = 0; t < 2; t++) {
        m->rerolls[t] = m->rerolls_start[t] = (uint8_t)(2 + pg_pick(rng, 3));
        m->apothecary[t] = bb_team_defs[m->team_id[t]].apothecary ? 1 : 0;
    }

exec
/bin/zsh -lc "sed -n '1,460p' engine/tests/test_match.c" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
// End-to-end engine tests: full random-agent matches must complete without
// errors, deterministically, with invariants holding at every decision point.
#include "bb/bb_match.h"
#include "bb/bb_hooks.h"
#include "bb/gen_teams.h"
#include "bb_fixtures.h"
#include "bb_test.h"
#include <string.h>

// Setup-aware action picker: random play cannot stumble into a legal
// formation (exactly 11 placed, 3+ on LoS, <=2 per wide zone), so during the
// setup phase the agent (a) takes SETUP_DONE the moment it is legal, and
// (b) places reserves on the line of scrimmage first, then centre-field
// squares. Everything else is uniform random — exactly how an RL policy would
// face the env.
static int pick_action(const bb_match* m, bb_action* legal, int n, bb_rng* pick) {
    for (int i = 0; i < n; i++) {
        if (legal[i].type == BB_A_SETUP_DONE) return i;
    }
    bool in_setup = n > 0 && (legal[0].type == BB_A_SETUP_PLACE || legal[0].type == BB_A_SETUP_REMOVE);
    if (in_setup) {
        // Prefer: place a RESERVES player onto the LoS centre; then any centre
        // (non-wide-zone) square in their half.
        int best = -1;
        for (int i = 0; i < n; i++) {
            if (legal[i].type != BB_A_SETUP_PLACE) continue;
            if (m->players[legal[i].arg].location != BB_LOC_RESERVES) continue;
            bool los = (legal[i].x == 12 || legal[i].x == 13) && legal[i].y >= 4 && legal[i].y <= 10;
            bool centre = legal[i].y >= 4 && legal[i].y <= 10;
            if (los) return i;
            if (centre && best < 0) best = i;
        }
        if (best >= 0) return best;
    }
    return (int)(bb_rng_next(pick) % (uint32_t)n);
}

// Play a full match with both coaches picking uniformly random legal actions.
// Returns the final status; asserts engine invariants at every decision.
static bb_status play_random_match(uint64_t seed, bb_match* out, int* decisions) {
    bb_match m;
    bb_match_init(&m, BB_TEAM_HUMAN, BB_TEAM_ORC);
    bb_rng rng, pick;
    bb_rng_seed(&rng, seed, 1);
    bb_rng_seed(&pick, seed ^ 0xABCDEF, 2);

    bb_status st = bb_advance(&m, &rng);
    int n_decisions = 0;
    while (st == BB_STATUS_DECISION && n_decisions < 200000) {
        bb_action legal[BB_LEGAL_MAX];
        int n = bb_legal_actions(&m, legal);
        BB_CHECK(n > 0);
        if (n <= 0) break;

        // Invariants at every decision point:
        // ball carrier consistency
        if (m.ball.state == BB_BALL_HELD) {
            BB_CHECK(m.ball.carrier != BB_NO_PLAYER);
            const bb_player* c = &m.players[m.ball.carrier];
            BB_CHECK(c->location == BB_LOC_ON_PITCH);
            BB_CHECK(c->flags & BB_PF_HAS_BALL);
            BB_CHECK_EQ(m.ball.x, c->x);
            BB_CHECK_EQ(m.ball.y, c->y);
        }
        // grid <-> player position consistency
        int on_grid = 0;
        for (int x = 0; x < BB_PITCH_LEN; x++) {
            for (int y = 0; y < BB_PITCH_WID; y++) {
                int s = m.grid[x][y] ? m.grid[x][y] - 1 : -1;
                if (s >= 0) {
                    on_grid++;
                    BB_CHECK_EQ(m.players[s].location, BB_LOC_ON_PITCH);
                    BB_CHECK_EQ(m.players[s].x, x);
                    BB_CHECK_EQ(m.players[s].y, y);
                }
            }
        }
        int on_pitch = 0;
        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
            if (m.players[s].location == BB_LOC_ON_PITCH) on_pitch++;
        }
        BB_CHECK_EQ(on_grid, on_pitch);

        int i = pick_action(&m, legal, n, &pick);
        st = bb_apply(&m, legal[i], &rng);
        n_decisions++;
    }
    if (out) *out = m;
    if (decisions) *decisions = n_decisions;
    return st;
}

BB_TEST(match_random_game_completes) {
    bb_match m;
    int decisions = 0;
    bb_status st = play_random_match(1234, &m, &decisions);
    BB_CHECK_EQ(st, BB_STATUS_MATCH_OVER);
    BB_CHECK(decisions > 50);
    BB_CHECK(m.turn[0] >= 8);
    BB_CHECK(m.turn[1] >= 8);
    BB_CHECK_EQ(m.half, 2);
}

BB_TEST(match_many_seeds_complete) {
    for (uint64_t seed = 1; seed <= 25; seed++) {
        bb_status st = play_random_match(seed * 7919, 0, 0);
        BB_CHECK_EQ(st, BB_STATUS_MATCH_OVER);
        if (st != BB_STATUS_MATCH_OVER) {
            printf("  seed %llu failed\n", (unsigned long long)seed);
            break;
        }
    }
}

BB_TEST(match_deterministic_replay) {
    bb_match m1, m2;
    int d1, d2;
    bb_status s1 = play_random_match(42, &m1, &d1);
    bb_status s2 = play_random_match(42, &m2, &d2);
    BB_CHECK_EQ(s1, s2);
    BB_CHECK_EQ(d1, d2);
    BB_CHECK_EQ(m1.score[0], m2.score[0]);
    BB_CHECK_EQ(m1.score[1], m2.score[1]);
    BB_CHECK_EQ(memcmp(&m1, &m2, sizeof(bb_match)), 0);
}

// bb_apply_trusted is the RL binding's fast path (no legal-set
// re-validation; ~20% of env-step time). For every LEGAL action it must be
// bit-identical to checked bb_apply — state, rng stream, and status — or the
// binding's trajectories silently diverge from every validation layer that
// replays through bb_apply. Differential over full matches.
BB_TEST(apply_trusted_matches_checked_apply) {
    for (uint64_t seed = 1; seed <= 6; seed++) {
        bb_match m;
        bb_match_init(&m, BB_TEAM_HUMAN, BB_TEAM_ORC);
        bb_rng rng, pick;
        bb_rng_seed(&rng, seed * 104729, 1);
        bb_rng_seed(&pick, seed ^ 0xD1FF, 2);
        bb_status st = bb_advance(&m, &rng);
        int steps = 0;
        while (st == BB_STATUS_DECISION && steps < 200000) {
            bb_action legal[BB_LEGAL_MAX];
            int n = bb_legal_actions(&m, legal);
            BB_CHECK(n > 0);
            if (n <= 0) break;
            bb_action a = legal[fx_pick_smart(&m, legal, n, &pick)];
            bb_match mt;
            bb_rng rt;
            memcpy(&mt, &m, sizeof m);
            memcpy(&rt, &rng, sizeof rng);
            st = bb_apply(&m, a, &rng);
            bb_status st_t = bb_apply_trusted(&mt, a, &rt);
            BB_CHECK_EQ(st, st_t);
            BB_CHECK_EQ(memcmp(&m, &mt, sizeof(bb_match)), 0);
            BB_CHECK_EQ(memcmp(&rng, &rt, sizeof(bb_rng)), 0);
            if (st != st_t || memcmp(&m, &mt, sizeof(bb_match)) != 0) return;
            steps++;
        }
        BB_CHECK_EQ(st, BB_STATUS_MATCH_OVER);
    }
}

// Misusing the trusted path must degrade to BB_STATUS_ERROR (the binding's
// defensive-reset trigger), never UB on a stale frame.
BB_TEST(apply_trusted_guards_non_decision) {
    bb_match m;
    bb_match_init(&m, BB_TEAM_HUMAN, BB_TEAM_ORC);
    bb_rng rng;
    bb_rng_seed(&rng, 7, 1);
    // Status is RUNNING (no decision demanded yet).
    bb_status st = bb_apply_trusted(&m, (bb_action){BB_A_NONE, 0, 0, 0}, &rng);
    BB_CHECK_EQ(st, BB_STATUS_ERROR);
}

BB_TEST(match_init_well_formed) {
    bb_match m;
    bb_match_init(&m, BB_TEAM_HUMAN, BB_TEAM_ORC);
    int avail[2] = {0, 0};
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        if (m.players[s].location == BB_LOC_RESERVES) avail[BB_TEAM_OF(s)]++;
    }
    BB_CHECK(avail[0] >= 11);
    BB_CHECK(avail[1] >= 11);
}

// The RL observation has exactly 12 skill-id slots per player
// (BBE_SKILL_SLOTS); procgen advancement must never exceed that or the env
// silently drops skills from the obs (Codex review HIGH, 2026-06-03).
BB_TEST(match_procgen_skill_cap) {
    for (uint64_t seed = 1; seed <= 200; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 977, 9);
        bb_match_init_random(&m, &pg);
        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
            if (m.players[s].location == BB_LOC_ABSENT) continue;
            int n = 0;
            for (int sk = bb_next_skill(&m.players[s].skills, 0); sk >= 0;
                 sk = bb_next_skill(&m.players[s].skills, sk + 1)) {
                n++;
            }
            BB_CHECK(n <= 12);
            if (n > 12) return;
        }
    }
}

static bb_skillset base_position_skills(const bb_position_def* pd) {
    bb_skillset s;
    memset(&s, 0, sizeof s);
    for (int i = 0; i < pd->num_skills; i++) bb_add_skill(&s, pd->skills[i]);
    return s;
}

static int procgen_squad_total(const bb_match* m, int team) {
    int n = 0;
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        if (m->players[s].location != BB_LOC_ABSENT) n++;
    }
    return n;
}

static void check_procgen_structure(const bb_match* m) {
    for (int t = 0; t < 2; t++) {
        int counts[BB_MAX_POSITIONS] = {0};
        const bb_team_def* td = &bb_team_defs[m->team_id[t]];
        int total = 0;
        for (int s = t * BB_TEAM_SLOTS; s < (t + 1) * BB_TEAM_SLOTS; s++) {
            const bb_player* p = &m->players[s];
            if (p->location == BB_LOC_ABSENT) continue;
            BB_CHECK(p->position_id < td->num_positions);
            if (p->position_id < td->num_positions) counts[p->position_id]++;
            total++;
        }
        BB_CHECK(total >= 11);
        BB_CHECK(total <= 14);
        for (int pi = 0; pi < td->num_positions; pi++) {
            BB_CHECK(counts[pi] <= td->positions[pi].qty_max);
        }
    }
}

static int procgen_count_skills(const bb_skillset* s) {
    int n = 0;
    for (int sk = bb_next_skill(s, 0); sk >= 0; sk = bb_next_skill(s, sk + 1)) n++;
    return n;
}

static int procgen_rng_same_state(const bb_rng* a, const bb_rng* b) {
    return a->state == b->state && a->inc == b->inc &&
           a->script == b->script && a->script_len == b->script_len &&
           a->script_pos == b->script_pos && a->mode == b->mode &&
           a->error == b->error && a->sink == b->sink &&
           a->sink_user == b->sink_user;
}

static void check_procgen_grants_in_mask(const bb_match* m, int secondary_only) {
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        const bb_player* p = &m->players[s];
        if (p->location == BB_LOC_ABSENT) continue;
        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
        const bb_position_def* pd = &td->positions[p->position_id];
        bb_skillset base = base_position_skills(pd);
        uint8_t want = secondary_only && pd->secondary_mask ? pd->secondary_mask : pd->primary_mask;
        if (!want) want = secondary_only ? pd->primary_mask : pd->secondary_mask;
        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
             sk = bb_next_skill(&p->skills, sk + 1)) {
            if (bb_has_skill(&base, sk)) continue;
            uint8_t cat = bb_skill_defs[sk].category;
            BB_CHECK(cat < BB_CAT_COUNT);
            BB_CHECK(want & (1 << cat));
            if (!(want & (1 << cat))) {
                printf("  team %d pos %d skill %d cat %d want 0x%x\n",
                       m->team_id[BB_TEAM_OF(s)], p->position_id, sk, cat, want);
                return;
            }
        }
    }
}

BB_TEST(match_procgen_default_params_match_legacy_api) {
    bb_procgen_params pp = bb_procgen_params_default();
    bb_match a, b;
    bb_rng r1, r2;
    bb_rng_seed(&r1, 0x515A5EEDu, 17);
    bb_rng_seed(&r2, 0x515A5EEDu, 17);
    bb_match_init_random(&a, &r1);
    bb_match_init_random_p(&b, &r2, &pp);
    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
    BB_CHECK(procgen_rng_same_state(&r1, &r2));
}

BB_TEST(match_procgen_skillups_off_keeps_base_skills) {
    bb_procgen_params pp = {0, 2, 0.0f};
    for (uint64_t seed = 1; seed <= 50; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 2654435761u, 23);
        bb_match_init_random_p(&m, &pg, &pp);
        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
            const bb_player* p = &m.players[s];
            if (p->location == BB_LOC_ABSENT) continue;
            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
            bb_skillset base = base_position_skills(&td->positions[p->position_id]);
            BB_CHECK_EQ(memcmp(&p->skills, &base, sizeof(bb_skillset)), 0);
        }
    }
}

BB_TEST(match_procgen_primary_only_uses_primary_categories) {
    bb_procgen_params pp = {11, 3, 0.0f};
    for (uint64_t seed = 1; seed <= 250; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 7919, 29);
        bb_match_init_random_p(&m, &pg, &pp);
        check_procgen_grants_in_mask(&m, 0);
    }
}

BB_TEST(match_procgen_secondary_only_uses_secondary_or_primary_fallback) {
    bb_procgen_params pp = {11, 3, 1.0f};
    for (uint64_t seed = 1; seed <= 250; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 104729, 31);
        bb_match_init_random_p(&m, &pg, &pp);
        check_procgen_grants_in_mask(&m, 1);
    }
}

BB_TEST(match_procgen_skillups_reach_full_learnable_catalogue) {
    bb_procgen_params pp = {11, 3, 0.5f};
    uint8_t seen[BB_NUM_SKILLS] = {0};
    int nseen = 0;
    for (uint64_t seed = 1; seed <= 10000 && nseen < BB_NUM_SKILLS; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, 0xC0FFEEu + seed * 17, 37);
        bb_match_init_random_p(&m, &pg, &pp);
        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
            const bb_player* p = &m.players[s];
            if (p->location == BB_LOC_ABSENT) continue;
            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
            const bb_position_def* pd = &td->positions[p->position_id];
            bb_skillset base = base_position_skills(pd);
            for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
                 sk = bb_next_skill(&p->skills, sk + 1)) {
                if (sk >= BB_NUM_SKILLS || bb_has_skill(&base, sk)) continue;
                if (!seen[sk]) {
                    seen[sk] = 1;
                    nseen++;
                }
            }
        }
    }
    BB_CHECK_EQ(nseen, BB_NUM_SKILLS);
    if (nseen != BB_NUM_SKILLS) {
        for (int sk = 0; sk < BB_NUM_SKILLS; sk++) {
            if (!seen[sk]) printf("  missing skill %d (%s)\n", sk, bb_skill_defs[sk].id);
        }
    }
}

BB_TEST(match_procgen_cranked_params_respect_cap_and_structure) {
    bb_procgen_params pp = {16, 12, 0.5f};
    for (uint64_t seed = 1; seed <= 200; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 16127, 41);
        bb_match_init_random_p(&m, &pg, &pp);
        check_procgen_structure(&m);
        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
            if (m.players[s].location == BB_LOC_ABSENT) continue;
            BB_CHECK(procgen_count_skills(&m.players[s].skills) <= 12);
        }
        BB_CHECK(procgen_squad_total(&m, BB_HOME) >= 11);
        BB_CHECK(procgen_squad_total(&m, BB_AWAY) >= 11);
    }
}

BB_TEST(match_procgen_params_are_deterministic) {
    bb_procgen_params pp = {11, 3, 0.35f};
    bb_match a, b;
    bb_rng r1, r2;
    bb_rng_seed(&r1, 0x12345678u, 43);
    bb_rng_seed(&r2, 0x12345678u, 43);
    bb_match_init_random_p(&a, &r1, &pp);
    bb_match_init_random_p(&b, &r2, &pp);
    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
    BB_CHECK(procgen_rng_same_state(&r1, &r2));
}

BB_TEST(match_procgen_games_complete) {
    for (uint64_t seed = 1; seed <= 12; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 31337, 9);
        bb_match_init_random(&m, &pg);
        bb_rng rng, pick;
        bb_rng_seed(&rng, seed, 1);
        bb_rng_seed(&pick, seed ^ 0xFACE, 2);
        bb_status st = bb_advance(&m, &rng);
        int steps = 0;
        while (st == BB_STATUS_DECISION && steps < 200000) {
            bb_action legal[BB_LEGAL_MAX];
            int n = bb_legal_actions(&m, legal);
            BB_CHECK(n > 0);
            if (n <= 0) break;
            st = bb_apply(&m, legal[fx_pick_smart(&m, legal, n, &pick)], &rng);
            steps++;
        }
        BB_CHECK_EQ(st, BB_STATUS_MATCH_OVER);
        if (st != BB_STATUS_MATCH_OVER) {
            printf("  procgen seed %llu failed (teams %d vs %d)\n",
                   (unsigned long long)seed, m.team_id[0], m.team_id[1]);
            break;
        }
    }
}

// bb_fixtures self-test (review T1): fx_player's memset left the fresh
// player looking ON_PITCH at (0,0), so bb_place's stale-square cleanup wiped
// grid[0][0] on every fixture placement — silently corrupting any test that
// stations a player at the origin.
BB_TEST(fixtures_player_at_origin_survives_later_placements) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int a = fx_lineman(&m, 0, 0, 0, 0);
    int b = fx_lineman(&m, 0, 1, 5, 5);
    int c = fx_lineman(&m, 1, 0, 20, 10);
    BB_CHECK_EQ(bb_slot_at(&m, 0, 0), a);
    BB_CHECK_EQ(bb_slot_at(&m, 5, 5), b);
    BB_CHECK_EQ(bb_slot_at(&m, 20, 10), c);
    BB_CHECK_EQ(m.players[a].location, BB_LOC_ON_PITCH);
}

// bb_match_init indexes bb_team_defs[] with its team ids; out-of-range ids
// (file-derived, e.g. replay INIT records) must be rejected, not looked up
// out of bounds (review Hd1).
BB_TEST(match_init_rejects_out_of_range_team_ids) {
    bb_match m;
    bb_match_init(&m, -1, BB_TEAM_ORC);
    BB_CHECK_EQ(m.status, BB_STATUS_ERROR);
    BB_CHECK_EQ(bb_advance(&m, 0), BB_STATUS_ERROR); // stays in ERROR
    bb_match_init(&m, BB_TEAM_HUMAN, BB_TEAM_COUNT);
    BB_CHECK_EQ(m.status, BB_STATUS_ERROR);
    bb_match_init(&m, 0x7FFFFFFF, 0);
    BB_CHECK_EQ(m.status, BB_STATUS_ERROR);
    // Boundary ids are valid.
    bb_match_init(&m, 0, BB_TEAM_COUNT - 1);
    BB_CHECK_EQ(m.status, BB_STATUS_RUNNING);
}

// bb_aura_skills must agree exactly with the registered aura hooks — it is
// the fast-path mask that lets bb_hook_mods skip players with no aura skills;
// a divergence would silently disable (or fail to skip) an aura (review P2).
BB_TEST(aura_mask_matches_registered_aura_hooks) {
    for (int sk = 0; sk < BB_SKILL_COUNT; sk++) {
        BB_CHECK_EQ(bb_has_skill(&bb_aura_skills, sk), bb_hooks[sk].aura != 0);

exec
/bin/zsh -lc 'rg -n "typedef struct bb_team_def|bb_team_defs|BB_TEAM_COUNT|secondary_mask|primary_mask|BB_CAT" engine/include engine/src engine/tests' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
engine/src/bb_procgen.c:43:    const bb_team_def* td = &bb_team_defs[team_id];
engine/src/bb_procgen.c:119:        if (!(pd->primary_mask || pd->secondary_mask)) continue;
engine/src/bb_procgen.c:123:            uint8_t mask = pd->primary_mask;
engine/src/bb_procgen.c:126:                mask = pd->secondary_mask;
engine/src/bb_procgen.c:129:                mask = (mask == pd->primary_mask) ? pd->secondary_mask : pd->primary_mask;
engine/src/bb_procgen.c:133:            int cats[BB_CAT_COUNT];
engine/src/bb_procgen.c:135:            for (int c = 0; c < BB_CAT_COUNT; c++) {
engine/src/bb_procgen.c:169:        m->apothecary[t] = bb_team_defs[m->team_id[t]].apothecary ? 1 : 0;
engine/src/bb_procgen.c:185:    int home = pg_pick(rng, BB_TEAM_COUNT);
engine/src/bb_procgen.c:186:    int away = pg_pick(rng, BB_TEAM_COUNT);
engine/src/bb_procgen.c:204:        h = pg_pick(rng, BB_TEAM_COUNT);
engine/src/bb_procgen.c:209:        a = pg_pick(rng, BB_TEAM_COUNT);
engine/include/bb/bb_match.h:143:    float skillup_secondary_pct; // P(draw category from secondary_mask)
engine/tests/test_gen_data.c:12:    int per_cat[BB_CAT_COUNT] = {0};
engine/tests/test_gen_data.c:14:        BB_CHECK(bb_skill_defs[i].category < BB_CAT_COUNT);
engine/tests/test_gen_data.c:18:    for (int c = 0; c < BB_CAT_COUNT; c++) BB_CHECK_EQ(per_cat[c], 12);
engine/tests/test_gen_data.c:34:    BB_CHECK_EQ(BB_TEAM_COUNT, 30);
engine/tests/test_gen_data.c:35:    const bb_team_def* hum = &bb_team_defs[BB_TEAM_HUMAN];
engine/tests/test_gen_data.c:51:    for (int t = 0; t < BB_TEAM_COUNT; t++) {
engine/tests/test_gen_data.c:52:        const bb_team_def* td = &bb_team_defs[t];
engine/tests/test_gen_data.c:103:    for (int c = 0; c < BB_CAT_COUNT; c++) {
engine/include/bb/gen_skills.h:9:    BB_CAT_GENERAL,
engine/include/bb/gen_skills.h:10:    BB_CAT_AGILITY,
engine/include/bb/gen_skills.h:11:    BB_CAT_STRENGTH,
engine/include/bb/gen_skills.h:12:    BB_CAT_PASSING,
engine/include/bb/gen_skills.h:13:    BB_CAT_MUTATION,
engine/include/bb/gen_skills.h:14:    BB_CAT_DEVIOUS,
engine/include/bb/gen_skills.h:15:    BB_CAT_COUNT
engine/include/bb/gen_skills.h:148:extern const uint8_t bb_random_skill_table[BB_CAT_COUNT][12];
engine/tests/test_replay.c:109:// INIT records carry file-derived team ids that flow into bb_team_defs[]
engine/src/bb_blockev.c:49:    if (tid < 0 || tid >= BB_TEAM_COUNT) return 0.5f;
engine/src/bb_blockev.c:50:    const bb_team_def* td = &bb_team_defs[tid];
engine/include/bb/gen_teams.h:39:    BB_TEAM_COUNT
engine/include/bb/gen_teams.h:53:    uint8_t primary_mask;   // bit i = category i (bb_skill_cat)
engine/include/bb/gen_teams.h:54:    uint8_t secondary_mask;
engine/include/bb/gen_teams.h:68:extern const bb_team_def bb_team_defs[BB_TEAM_COUNT];
engine/src/gen_teams.c:5:const bb_team_def bb_team_defs[BB_TEAM_COUNT] = {
engine/src/bb_match.c:199:    const bb_team_def* td = &bb_team_defs[team_id];
engine/src/bb_match.c:231:    // flow here; an out-of-range id would index bb_team_defs[] out of bounds
engine/src/bb_match.c:233:    if ((unsigned)home_team_id >= (unsigned)BB_TEAM_COUNT ||
engine/src/bb_match.c:234:        (unsigned)away_team_id >= (unsigned)BB_TEAM_COUNT) {
engine/src/bb_match.c:244:    m->apothecary[BB_HOME] = bb_team_defs[home_team_id].apothecary ? 1 : 0;
engine/src/bb_match.c:245:    m->apothecary[BB_AWAY] = bb_team_defs[away_team_id].apothecary ? 1 : 0;
engine/src/bb_replay.c:123:        // bb_team_defs[] lookups via bb_match_init (review Hd1).
engine/src/bb_replay.c:124:        if (!ok || home < 0 || home >= BB_TEAM_COUNT ||
engine/src/bb_replay.c:125:            away < 0 || away >= BB_TEAM_COUNT) {
engine/tests/test_match.c:226:        const bb_team_def* td = &bb_team_defs[m->team_id[t]];
engine/tests/test_match.c:261:        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
engine/tests/test_match.c:264:        uint8_t want = secondary_only && pd->secondary_mask ? pd->secondary_mask : pd->primary_mask;
engine/tests/test_match.c:265:        if (!want) want = secondary_only ? pd->primary_mask : pd->secondary_mask;
engine/tests/test_match.c:270:            BB_CHECK(cat < BB_CAT_COUNT);
engine/tests/test_match.c:303:            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
engine/tests/test_match.c:344:            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
engine/tests/test_match.c:438:// bb_match_init indexes bb_team_defs[] with its team ids; out-of-range ids
engine/tests/test_match.c:446:    bb_match_init(&m, BB_TEAM_HUMAN, BB_TEAM_COUNT);
engine/tests/test_match.c:451:    bb_match_init(&m, 0, BB_TEAM_COUNT - 1);
engine/tests/test_match.c:481:            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
engine/src/gen_skills.c:6:    {"catch", "Catch", BB_CAT_AGILITY, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:7:    {"diving_catch", "Diving Catch", BB_CAT_AGILITY, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:8:    {"diving_tackle", "Diving Tackle", BB_CAT_AGILITY, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:9:    {"dodge", "Dodge", BB_CAT_AGILITY, 1, 0, 1, -1, 0},
engine/src/gen_skills.c:10:    {"defensive", "Defensive", BB_CAT_AGILITY, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:11:    {"hit_and_run", "Hit and Run", BB_CAT_AGILITY, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:12:    {"jump_up", "Jump Up", BB_CAT_AGILITY, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:13:    {"leap", "Leap", BB_CAT_AGILITY, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:14:    {"safe_pair_of_hands", "Safe Pair of Hands", BB_CAT_AGILITY, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:15:    {"sidestep", "Sidestep", BB_CAT_AGILITY, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:16:    {"sprint", "Sprint", BB_CAT_AGILITY, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:17:    {"sure_feet", "Sure Feet", BB_CAT_AGILITY, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:18:    {"dirty_player", "Dirty Player", BB_CAT_DEVIOUS, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:19:    {"eye_gouge", "Eye Gouge", BB_CAT_DEVIOUS, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:20:    {"fumblerooski", "Fumblerooski", BB_CAT_DEVIOUS, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:21:    {"lethal_flight", "Lethal Flight", BB_CAT_DEVIOUS, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:22:    {"lone_fouler", "Lone Fouler", BB_CAT_DEVIOUS, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:23:    {"pile_driver", "Pile Driver", BB_CAT_DEVIOUS, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:24:    {"put_the_boot_in", "Put the Boot In", BB_CAT_DEVIOUS, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:25:    {"quick_foul", "Quick Foul", BB_CAT_DEVIOUS, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:26:    {"saboteur", "Saboteur", BB_CAT_DEVIOUS, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:27:    {"shadowing", "Shadowing", BB_CAT_DEVIOUS, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:28:    {"sneaky_git", "Sneaky Git", BB_CAT_DEVIOUS, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:29:    {"violent_innovator", "Violent Innovator", BB_CAT_DEVIOUS, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:30:    {"block", "Block", BB_CAT_GENERAL, 1, 0, 1, -1, 0},
engine/src/gen_skills.c:31:    {"dauntless", "Dauntless", BB_CAT_GENERAL, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:32:    {"fend", "Fend", BB_CAT_GENERAL, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:33:    {"frenzy", "Frenzy", BB_CAT_GENERAL, 1, 1, 0, -1, 0},
engine/src/gen_skills.c:34:    {"kick", "Kick", BB_CAT_GENERAL, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:35:    {"pro", "Pro", BB_CAT_GENERAL, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:36:    {"steady_footing", "Steady Footing", BB_CAT_GENERAL, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:37:    {"strip_ball", "Strip Ball", BB_CAT_GENERAL, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:38:    {"sure_hands", "Sure Hands", BB_CAT_GENERAL, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:39:    {"tackle", "Tackle", BB_CAT_GENERAL, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:40:    {"taunt", "Taunt", BB_CAT_GENERAL, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:41:    {"wrestle", "Wrestle", BB_CAT_GENERAL, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:42:    {"big_hand", "Big Hand", BB_CAT_MUTATION, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:43:    {"claws", "Claws", BB_CAT_MUTATION, 0, 0, 0, -1, 0},
engine/src/gen_skills.c:44:    {"disturbing_presence", "Disturbing Presence", BB_CAT_MUTATION, 0, 1, 0, -1, 0},
engine/src/gen_skills.c:45:    {"extra_arms", "Extra Arms", BB_CAT_MUTATION, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:46:    {"foul_appearance", "Foul Appearance", BB_CAT_MUTATION, 0, 1, 0, -1, 0},
engine/src/gen_skills.c:47:    {"horns", "Horns", BB_CAT_MUTATION, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:48:    {"iron_hard_skin", "Iron Hard Skin", BB_CAT_MUTATION, 0, 0, 0, -1, 0},
engine/src/gen_skills.c:49:    {"monstrous_mouth", "Monstrous Mouth", BB_CAT_MUTATION, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:50:    {"prehensile_tail", "Prehensile Tail", BB_CAT_MUTATION, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:51:    {"tentacles", "Tentacles", BB_CAT_MUTATION, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:52:    {"two_heads", "Two Heads", BB_CAT_MUTATION, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:53:    {"very_long_legs", "Very Long Legs", BB_CAT_MUTATION, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:54:    {"accurate", "Accurate", BB_CAT_PASSING, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:55:    {"cannoneer", "Cannoneer", BB_CAT_PASSING, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:56:    {"cloud_burster", "Cloud Burster", BB_CAT_PASSING, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:57:    {"dump_off", "Dump-off", BB_CAT_PASSING, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:58:    {"give_and_go", "Give and Go", BB_CAT_PASSING, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:59:    {"hail_mary_pass", "Hail Mary Pass", BB_CAT_PASSING, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:60:    {"leader", "Leader", BB_CAT_PASSING, 0, 0, 0, -1, 0},
engine/src/gen_skills.c:61:    {"nerves_of_steel", "Nerves of Steel", BB_CAT_PASSING, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:62:    {"on_the_ball", "On the Ball", BB_CAT_PASSING, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:63:    {"pass", "Pass", BB_CAT_PASSING, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:64:    {"punt", "Punt", BB_CAT_PASSING, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:65:    {"safe_pass", "Safe Pass", BB_CAT_PASSING, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:66:    {"arm_bar", "Arm Bar", BB_CAT_STRENGTH, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:67:    {"brawler", "Brawler", BB_CAT_STRENGTH, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:68:    {"break_tackle", "Break Tackle", BB_CAT_STRENGTH, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:69:    {"bullseye", "Bullseye", BB_CAT_STRENGTH, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:70:    {"grab", "Grab", BB_CAT_STRENGTH, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:71:    {"guard", "Guard", BB_CAT_STRENGTH, 1, 0, 1, -1, 0},
engine/src/gen_skills.c:72:    {"juggernaut", "Juggernaut", BB_CAT_STRENGTH, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:73:    {"mighty_blow", "Mighty Blow", BB_CAT_STRENGTH, 1, 0, 1, -1, 0},
engine/src/gen_skills.c:74:    {"multiple_block", "Multiple Block", BB_CAT_STRENGTH, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:75:    {"stand_firm", "Stand Firm", BB_CAT_STRENGTH, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:76:    {"strong_arm", "Strong Arm", BB_CAT_STRENGTH, 1, 0, 0, -1, 0},
engine/src/gen_skills.c:77:    {"thick_skull", "Thick Skull", BB_CAT_STRENGTH, 0, 0, 0, -1, 0},
engine/src/gen_skills.c:116:const uint8_t bb_random_skill_table[BB_CAT_COUNT][12] = {
engine/tests/fuzz_match.c:35:        int home = data[9] % BB_TEAM_COUNT;
engine/tests/fuzz_match.c:36:        int away = data[10] % BB_TEAM_COUNT;

codex
I’m going to patch just `bb_procgen.c` and `test_match.c` now. The test additions will scan `bb_team_defs` rather than baking in enum names, which matches the brief and keeps the assertions tied to the generated roster data.
apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/engine/src/bb_procgen.c
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 4819137323d1ece180f5c27b7ae1114d9ad9d81f..a37c95440728c41e5efb206931426ea4a6d75691
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -116,7 +116,9 @@
         int who = base + pg_pick(rng, n);
         bb_player* p = &m->players[who];
         const bb_position_def* pd = &td->positions[p->position_id];
-        if (!(pd->primary_mask || pd->secondary_mask)) continue;
+        uint8_t access = pd->primary_mask;
+        if (pp->skillup_secondary_pct > 0.0f) access |= pd->secondary_mask;
+        if (!access) continue;
         int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
         for (int g = 0; g < gains; g++) {
             if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;

diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 4819137323d1ece180f5c27b7ae1114d9ad9d81f..a37c95440728c41e5efb206931426ea4a6d75691
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -116,7 +116,9 @@
         int who = base + pg_pick(rng, n);
         bb_player* p = &m->players[who];
         const bb_position_def* pd = &td->positions[p->position_id];
-        if (!(pd->primary_mask || pd->secondary_mask)) continue;
+        uint8_t access = pd->primary_mask;
+        if (pp->skillup_secondary_pct > 0.0f) access |= pd->secondary_mask;
+        if (!access) continue;
         int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
         for (int g = 0; g < gains; g++) {
             if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;

apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/engine/tests/test_match.c
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 4819137323d1ece180f5c27b7ae1114d9ad9d81f..a37c95440728c41e5efb206931426ea4a6d75691
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -116,7 +116,9 @@
         int who = base + pg_pick(rng, n);
         bb_player* p = &m->players[who];
         const bb_position_def* pd = &td->positions[p->position_id];
-        if (!(pd->primary_mask || pd->secondary_mask)) continue;
+        uint8_t access = pd->primary_mask;
+        if (pp->skillup_secondary_pct > 0.0f) access |= pd->secondary_mask;
+        if (!access) continue;
         int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
         for (int g = 0; g < gains; g++) {
             if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 99774f8dfb71f3f99dfd14ddaa48a8432093ee30..bcf304109b9ca2b04bcd6a13f0b300f85a1c5fa5
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -278,16 +278,122 @@
     }
 }
 
+static int procgen_find_secondary_only_teams(int* out, int cap) {
+    int n = 0;
+    for (int t = 0; t < BB_TEAM_COUNT; t++) {
+        const bb_team_def* td = &bb_team_defs[t];
+        int has_secondary_only = 0;
+        for (int pi = 0; pi < td->num_positions; pi++) {
+            const bb_position_def* pd = &td->positions[pi];
+            if (pd->primary_mask == 0 && pd->secondary_mask != 0) {
+                has_secondary_only = 1;
+                break;
+            }
+        }
+        if (has_secondary_only && n < cap) out[n++] = t;
+    }
+    return n;
+}
+
+static int procgen_check_secondary_only_grants(const bb_match* m) {
+    int seen = 0;
+    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+        const bb_player* p = &m->players[s];
+        if (p->location == BB_LOC_ABSENT) continue;
+        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
+        const bb_position_def* pd = &td->positions[p->position_id];
+        if (pd->primary_mask != 0) continue;
+        bb_skillset base = base_position_skills(pd);
+        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
+             sk = bb_next_skill(&p->skills, sk + 1)) {
+            if (bb_has_skill(&base, sk)) continue;
+            uint8_t cat = bb_skill_defs[sk].category;
+            BB_CHECK(cat < BB_CAT_COUNT);
+            BB_CHECK(pd->secondary_mask & (1 << cat));
+            if (!(pd->secondary_mask & (1 << cat))) {
+                printf("  team %d pos %d skill %d cat %d secondary 0x%x\n",
+                       m->team_id[BB_TEAM_OF(s)], p->position_id, sk, cat,
+                       pd->secondary_mask);
+                return seen;
+            }
+            seen = 1;
+        }
+    }
+    return seen;
+}
+
 BB_TEST(match_procgen_default_params_match_legacy_api) {
     bb_procgen_params pp = bb_procgen_params_default();
-    bb_match a, b;
-    bb_rng r1, r2;
-    bb_rng_seed(&r1, 0x515A5EEDu, 17);
-    bb_rng_seed(&r2, 0x515A5EEDu, 17);
-    bb_match_init_random(&a, &r1);
-    bb_match_init_random_p(&b, &r2, &pp);
-    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
-    BB_CHECK(procgen_rng_same_state(&r1, &r2));
+    for (uint64_t seed = 1; seed <= 300; seed++) {
+        bb_match a, b;
+        bb_rng r1, r2;
+        bb_rng_seed(&r1, seed * 0x515A5EEDu, 17 + seed);
+        bb_rng_seed(&r2, seed * 0x515A5EEDu, 17 + seed);
+        bb_match_init_random(&a, &r1);
+        bb_match_init_random_p(&b, &r2, &pp);
+        BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
+        BB_CHECK(procgen_rng_same_state(&r1, &r2));
+        if (memcmp(&a, &b, sizeof(bb_match)) != 0 ||
+            !procgen_rng_same_state(&r1, &r2)) {
+            printf("  seed %llu failed\n", (unsigned long long)seed);
+            break;
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_inert_at_defaults) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = bb_procgen_params_default();
+    for (uint64_t seed = 1; seed <= 100; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 2654435761u, 53 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+            const bb_player* p = &m.players[s];
+            if (p->location == BB_LOC_ABSENT) continue;
+            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
+            const bb_position_def* pd = &td->positions[p->position_id];
+            if (pd->primary_mask != 0) continue;
+            bb_skillset base = base_position_skills(pd);
+            BB_CHECK_EQ(memcmp(&p->skills, &base, sizeof(bb_skillset)), 0);
+            if (memcmp(&p->skills, &base, sizeof(bb_skillset)) != 0) {
+                printf("  seed %llu team %d pos %d gained at defaults\n",
+                       (unsigned long long)seed, m.team_id[BB_TEAM_OF(s)],
+                       p->position_id);
+                return;
+            }
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_advance_with_pct) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = {11, 3, 0.5f};
+    int seen = 0;
+    for (uint64_t seed = 1; seed <= 2000 && !seen; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 11400714819323198485ull, 59 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        seen = procgen_check_secondary_only_grants(&m);
+    }
+    BB_CHECK(seen);
+    if (!seen) printf("  no secondary-only position advanced within 2000 seeds\n");
 }
 
 BB_TEST(match_procgen_skillups_off_keeps_base_skills) {

diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 4819137323d1ece180f5c27b7ae1114d9ad9d81f..a37c95440728c41e5efb206931426ea4a6d75691
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -116,7 +116,9 @@
         int who = base + pg_pick(rng, n);
         bb_player* p = &m->players[who];
         const bb_position_def* pd = &td->positions[p->position_id];
-        if (!(pd->primary_mask || pd->secondary_mask)) continue;
+        uint8_t access = pd->primary_mask;
+        if (pp->skillup_secondary_pct > 0.0f) access |= pd->secondary_mask;
+        if (!access) continue;
         int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
         for (int g = 0; g < gains; g++) {
             if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 99774f8dfb71f3f99dfd14ddaa48a8432093ee30..bcf304109b9ca2b04bcd6a13f0b300f85a1c5fa5
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -278,16 +278,122 @@
     }
 }
 
+static int procgen_find_secondary_only_teams(int* out, int cap) {
+    int n = 0;
+    for (int t = 0; t < BB_TEAM_COUNT; t++) {
+        const bb_team_def* td = &bb_team_defs[t];
+        int has_secondary_only = 0;
+        for (int pi = 0; pi < td->num_positions; pi++) {
+            const bb_position_def* pd = &td->positions[pi];
+            if (pd->primary_mask == 0 && pd->secondary_mask != 0) {
+                has_secondary_only = 1;
+                break;
+            }
+        }
+        if (has_secondary_only && n < cap) out[n++] = t;
+    }
+    return n;
+}
+
+static int procgen_check_secondary_only_grants(const bb_match* m) {
+    int seen = 0;
+    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+        const bb_player* p = &m->players[s];
+        if (p->location == BB_LOC_ABSENT) continue;
+        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
+        const bb_position_def* pd = &td->positions[p->position_id];
+        if (pd->primary_mask != 0) continue;
+        bb_skillset base = base_position_skills(pd);
+        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
+             sk = bb_next_skill(&p->skills, sk + 1)) {
+            if (bb_has_skill(&base, sk)) continue;
+            uint8_t cat = bb_skill_defs[sk].category;
+            BB_CHECK(cat < BB_CAT_COUNT);
+            BB_CHECK(pd->secondary_mask & (1 << cat));
+            if (!(pd->secondary_mask & (1 << cat))) {
+                printf("  team %d pos %d skill %d cat %d secondary 0x%x\n",
+                       m->team_id[BB_TEAM_OF(s)], p->position_id, sk, cat,
+                       pd->secondary_mask);
+                return seen;
+            }
+            seen = 1;
+        }
+    }
+    return seen;
+}
+
 BB_TEST(match_procgen_default_params_match_legacy_api) {
     bb_procgen_params pp = bb_procgen_params_default();
-    bb_match a, b;
-    bb_rng r1, r2;
-    bb_rng_seed(&r1, 0x515A5EEDu, 17);
-    bb_rng_seed(&r2, 0x515A5EEDu, 17);
-    bb_match_init_random(&a, &r1);
-    bb_match_init_random_p(&b, &r2, &pp);
-    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
-    BB_CHECK(procgen_rng_same_state(&r1, &r2));
+    for (uint64_t seed = 1; seed <= 300; seed++) {
+        bb_match a, b;
+        bb_rng r1, r2;
+        bb_rng_seed(&r1, seed * 0x515A5EEDu, 17 + seed);
+        bb_rng_seed(&r2, seed * 0x515A5EEDu, 17 + seed);
+        bb_match_init_random(&a, &r1);
+        bb_match_init_random_p(&b, &r2, &pp);
+        BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
+        BB_CHECK(procgen_rng_same_state(&r1, &r2));
+        if (memcmp(&a, &b, sizeof(bb_match)) != 0 ||
+            !procgen_rng_same_state(&r1, &r2)) {
+            printf("  seed %llu failed\n", (unsigned long long)seed);
+            break;
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_inert_at_defaults) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = bb_procgen_params_default();
+    for (uint64_t seed = 1; seed <= 100; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 2654435761u, 53 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+            const bb_player* p = &m.players[s];
+            if (p->location == BB_LOC_ABSENT) continue;
+            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
+            const bb_position_def* pd = &td->positions[p->position_id];
+            if (pd->primary_mask != 0) continue;
+            bb_skillset base = base_position_skills(pd);
+            BB_CHECK_EQ(memcmp(&p->skills, &base, sizeof(bb_skillset)), 0);
+            if (memcmp(&p->skills, &base, sizeof(bb_skillset)) != 0) {
+                printf("  seed %llu team %d pos %d gained at defaults\n",
+                       (unsigned long long)seed, m.team_id[BB_TEAM_OF(s)],
+                       p->position_id);
+                return;
+            }
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_advance_with_pct) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = {11, 3, 0.5f};
+    int seen = 0;
+    for (uint64_t seed = 1; seed <= 2000 && !seen; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 11400714819323198485ull, 59 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        seen = procgen_check_secondary_only_grants(&m);
+    }
+    BB_CHECK(seen);
+    if (!seen) printf("  no secondary-only position advanced within 2000 seeds\n");
 }
 
 BB_TEST(match_procgen_skillups_off_keeps_base_skills) {

codex
The code now restores the legacy access guard before the `gains` draw, and the tests are in place. Next I’m going to compile/run the suite, then identify the binding self-test command from the repo so I can rerun it the same local way.
exec
/bin/zsh -lc 'rg -n "selftest|--selftest|binding|bindings|bb_env|bloodbowl" .' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
./DECISIONS.md:20:**D7 — Vast.ai**: key stored at `~/.vast_api_key`, verified live ($96.26 credit). Spend capped at your authorized $50. No GPU spend until the PufferLib binding smoke test (Phase 5).
./DECISIONS.md:49:**D33 — blocks 0.000 on the synthesis run is REAL behavior, not a broken counter — and the mechanism is quantified.** Suspicion: bc_acc 0.80 (teacher-forced, on human pairs full of blocks) with on-policy blocks 0.000 looked like instrument failure. Probe (puffer/bloodbowl/bbe_microstats_probe.c, masked-random policy, 200 eps): blocks 1.875/ep, blitzes 6.14/ep — the counter ticks fine under any non-degenerate policy; verified wired at c_step→bbe_count_action on every applied decision. So the synthesis policy has actively zeroed block declarations. WHY: the same probe shows random contact is net self-harm — kd_own 1.75 vs kd_inflicted 0.61 (~3:1 against). PPO descends that gradient immediately ("all blocks bad") and cannot climb to "selective 2dB-with-Block blocks are +EV" — a textbook shaping valley, exactly Alex's spectator observation. The BC anchor doesn't prevent it: block declarations are a thin slice of the pair distribution, so the policy keeps 0.80 aggregate accuracy while zeroing them on-policy (knowledge-behavior gap; anchor CE is state-averaged, not behavior-coverage-weighted). Implications: (1) Profile C decision-time exposure pricing (k_kd × P(knockdown) etc. — spec in docs/reward-audit-decision-time.md Addendum 3, 2dB(2.8%)-vs-3d(3.7%) inversion test) is now empirically motivated, not just theorized — ungated. (2) Candidate anchor upgrade: weight BC loss by decision type (or oversample DECLARE pairs) so block judgment transfers; pairs already carry the action type. (3) Eval-suite metric: blocks/ep on demo-started episodes is the cleanest "does it fight when it should" probe.
./DECISIONS.md:58:**D38 — THE UNMASKED-SAMPLER BUG: the torch backend never applied action masks; every BC-anchored run played via decode fallback (illegal_frac 1.000).** Found chasing synthesis+C's blocks 0.000 AND blitzes 0.000 at 200M (exact zeros — structure, not behavior). Mechanism: bc_pretrain (and the bc_acc aux loss) train/score MASK-RESTRICTED logits; the torch backend samples RAW logits (masks were CUDA-only); the BC policy never had to learn raw-logit legality, so on-policy it sampled ~100% illegal and bbe_decode's fallback (same-type → legal[0]) played a MOVE-biased shadow policy. Measured: bc_v3b lr~0 probe — unmasked: illegal 0.999, blocks 0.000, blitzes 0.000; MASKED: illegal 0.235 (residual = joint arg×sq misses across independent head masks), blocks 12.4/ep, blocks_thrown 13.6/ep, blitzes 2.8/ep — HUMAN-RANGE contact from the same weights. Fix (training/torch_pufferl_bcreg.patch + puffer_dict_capacity.patch regenerated): bindings expose vec action_mask (cpu+gpu); torch_pufferl applies per-head masked_fill(-inf) BEFORE rollout sampling, stores masks in experience, and re-applies at train-time recompute (mask-consistent ratios/entropy; all-zero head row guard). REINTERPRETATIONS: D33's knowledge-behavior gap = largely this artifact; D32/synthesis-v4 "anchor holds" results stand as experiments but measured fallback-shadow dynamics (their tds/pickups arose through legal[0]-snapping, with PPO slowly re-learning legality in raw logits); the avoidance-basin conclusions (D26-D28, CUDA, masked) unaffected; D34's Profile C result (CUDA, masked) unaffected. Unmasked synthesis+C control killed at ~300M (preserved in log); SYNTHESIS+C-MASKED relaunched 16:25 PDT — the first torch run whose behavior and knowledge share a distribution. Viewer inherits the fix (same patch) — on-screen play is now the real policy.
./DECISIONS.md:65:**D45 — Asym 10B verdict: behavioral divergence WITHOUT win conversion; the prior is the bottleneck.** poss-asym (annuity config vs FROZEN bc_v3b, 647K SPS, 10B in ~4.5h): EIGHT consecutive nonzero tds ticks (0.004-0.018 band) and pickup_success up to 0.14-0.22 while the symmetric twin held absolute zero tds with possession decaying — the asymmetry effect is real and directional. BUT the arbitration tournament (4096 games vs its own frozen opponent, both bias-drop-converted): 97.1% draws, decisive 48.5/51.5 — after 10B steps of practice against a defense that NEVER ADAPTS, the learner cannot beat it. Synthesis of the week's evidence (D35 capacity, D39/D43 possession poison, this): the binding constraint is THE PRIOR — a 0.40-exact iid imitation is a bad Blood Bowl player; the anchor (bc_acc pinned at its 0.396 ceiling throughout) holds the policy at that level; and PPO cannot discover multi-step drives from there even unopposed-by-adaptation. Levers, ranked: (1) anchor RELEASE — bc_coef_floor now configurable (was hard-coded 0.1); ASYM-RELEASE launched overnight from the asym-10B checkpoint with floor 0 (does the policy outgrow its teacher when allowed to leave the human manifold vs a static defense?); (2) sequence-context bc_v4 (the D35 lever — iid zero-state BC is the known ceiling); (3) bigger policy. Tournament caveat noted: CUDA bias-drop conversion applied to both sides equally.
./DECISIONS.md:66:**D46 — Discovery-vs-artifact doctrine (Alex, 2026-06-07): do not patch out inhuman behaviors by aesthetics.** RL's value is uncovering inhuman-but-optimal play (TD-Gammon's doubles, AlphaStar's worker saturation); "looks absurd" is not a valid filter. Discriminator before patching any weird behavior: (1) does it survive GROUNDING — persist when wins/TDs against a competent opponent are the binding currency, not shaped income? (2) is its profit causally routed THROUGH the objective or around it? (3) human rates are evidence, not law. Case study, GFI-spam (~17/ep vs human ~2-5): currently routed AROUND the objective (farms potential income while degrading drives; failed GFIs priced ~zero because under scoring scarcity the opponent can't convert turnovers) — so PRESUMED artifact, but the verdict belongs to the tournament, not taste. Consequences: reward_rush_cost is ANTI-DEGENERACY SCAFFOLDING (k-knob category, to be annealed away once the economy works), never a permanent value statement; deploy taxed-vs-untaxed as an A/B; if the untaxed twin keeps high GFI AND wins, absurd is correct and the tax dies.
./DECISIONS.md:67:**D46-addendum (Alex, 03:32): the real GFI price is positional, and that unifies the disease.** GFIs are individually high-success (5/6); IRL the binding cost is TZ-coverage preservation — a prone player projects no tackle zones, so you GFI only when the squares net something AND that player being down is acceptable. Standing presence is defensive currency (constrains opponent ball movement); under scoring scarcity defense has nothing to defend, so the agent CORRECTLY prices prone-ness at ~zero — GFI-spam is accurate pricing of a worthless asset, not ignorance. Unifies ball-avoidance, scrum-hovering, and GFI-spam as ONE disease: positional value is denominated in points and there are no points. Flat rush tax therefore doubly a crutch (true GFI price is context-dependent: last screener vs idle player); cure remains a working scoring economy. GFI gradient observed across arms: anneal 8.5 → possession 14 → asym-10B 29.7/ep — rushing scales with optimization depth in the broken economy, not with winning (artifact signature per the D46 discriminator).
./DECISIONS.md:69:**D47 — Anchor release verdict: NO breakout, NO collapse — the anchor was never the binding constraint.** asym-release2 (from asym-10B ckpt, frozen bc_v3b defense, bc_coef 0.5 -> 0.000 corrected cosine, capped ~6.03B continuation; stop-condition overshoot noted: runner global_step advances train-batch-width under asymmetry — patch with epoch-based stop or full-width accounting): bc_acc HELD ~0.39-0.42 throughout including ~1.3B steps at bc_coef<0.1 (no manifold drift — PPO updates too local to leave the basin), tds band unchanged (0.004-0.018), gfi ~30/ep unchanged. Tournament 4096 games vs frozen bc_v3b: 96.8% draws, decisive 48.4/51.6 — IDENTICAL to the anchored result (97.1%, 48.5/51.5). D45's anchor-over-binding hypothesis REFUTED: with the leash fully off, against a defense that cannot adapt, PPO still cannot find multi-step scoring play from this prior at this capacity. Remaining levers, now cleanly ranked: (1) BACKPLAY CURRICULUM — filter the demo bank for carrier-near-endzone states so the policy EXPERIENCES scoring densely, expand backward (the bank was literally built for this pattern; cheapest lever, untested); (2) bc_v4 sequence-context prior (D35); (3) bigger policy. The asym infrastructure + annuity economy remain the training architecture; they removed every confound that used to hide this conclusion.
./DECISIONS.md:71:**D49 — The backplay program: three-arm controlled experiment from one checkpoint.** Anneal chain closed (s1-s4, full->zero k, tds 0.000 throughout: exposure-anneal alone never scores) and possession-symmetric capped at 10.1B scoreless (the annuity alone, mirror play: rational ball-avoidance persisted) — both boxes reassigned. ALL THREE FLEET ARMS now branch from the SAME backplay-s1 checkpoint (5.24B, tds ~0.29 rising): bp_s1 flagship (ballhawk box, maxdist 6, untaxed — how far does stage 1 climb), bp_s2 preview (possession box, maxdist 12 — does skill survive backward expansion, parallel instead of serial staging), bp_tax twin (box-2, maxdist 6 + rush_cost 0.015 — the D46 A/B: does pricing GFIs help or does the grounding effect alone suffice). Tier-distribution exports (2d:2d-red) live on all three after fixing a stale binding.c on the flagship box (header synced, binding didn't — partial-sync footgun; counters existed but were never exported). Sweep tracks tds/gfi/2d/2dred per arm.
./DECISIONS.md:76:**D54 — FIRST SIGHTED ARM LIVE: profile-v4-backplay.** s2-deep capped at 15.0B (stage-2-deep band ~0.20-0.22 — converged faster than s2b but to a similar level so far; the depth question stays open in the v3 lineage while v4 supersedes). The flagship box now runs the full v4 stack: obs-v4 probability planes + bc_v4 anchor (val 0.508) + bc_v4 FROZEN enemy + 2.09M-pair BC aux corpus (pairs symlink -> pairs_v4) + backplay stage 1 (demo 0.9, maxdist 6) + annuity economy + k-half. One build snag en route: binding.c's OBS_SIZE literal (vecenv.h requirement) still said 1612 — the _Static_assert added in obs-v3 caught it exactly as designed; fixed to 2782. Headline metrics for this arm: bc_acc vs the 0.51 ceiling, tds vs the v3 stage-1 curve (0.045->0.38 over 15B), and block_2dred_frac vs both the v3 plateau (~0.20) and the human 0.017 — the planes' entire purpose.
./DECISIONS.md:87:**D65 — Session reorg SHIPPED + three launch footguns caught. Final fleet: 3 live arms + 1 stopped.** Executed the D64 plan. LIVE: (1) v4-pickup-s1 (possession, PID 25594) — native anchor-free pickup curriculum, demo_pickup_maxdist 2, warm from v4_s2tax, demo_fallbacks 0.000 (15471-state bank, abundant loose-ball coverage; bank_pickup_probe.c: 33.7% loose, 16% qualify @maxdist2); (2) v4-native-s4 (japan, PID 8603) — native flagship advanced to stage-4 UNIFORM (demo-endzone-maxdist 0), warm from the 30B stage-3 ckpt 0000030015750144.bin, coexists with scraper; (3) v4-d60-bccoef0 (taiwan, PID 2330) — D60 isolation: torch --float obs-v4, frozen-enemy bc_v4.bin, --train.bc-coef 0 (the SINGLE variable vs torch_s3's 1.0), maxdist 12, full v4 economy overriding synthesis-C's dead bake; started 2dred 0.159 — watch if it falls to native's ~0.11 (anchor was the cause) or holds ~0.16 (backend/opponent). STOPPED: ballhawk (idle after torch_s3 completed; conserve at $40 balance). THREE FOOTGUNS caught this session: (a) MONITOR STALENESS — the old fleet monitor grepped log CONTENT but never log MTIME, so it reported native_s3 (done 30B, 13h prior) + torch_s3 (done 15B, 8.5h prior) as "running" while their boxes idle-billed for hours; replaced with /tmp/fleet_liveness_monitor.sh that flags DEAD on log-mtime-age >360s OR pgrep -xc puffer == 0. (b) FLEET.SH BANK-OVERWRITE — fleet.sh setup rsync does NOT exclude validation/states or resources/bloodbowl, so it clobbers a box's demo bank with the Mac's (which held a stale 1057-state bank); shipped the 15471-state bank back to the Mac repo (gitignored) so future syncs ship the big one. (c) FLEET LABEL EXACT-MATCH — fleet.sh resolve exact-matches bb-<name>; the box is bb-taiwan-anchor not bb-taiwan, so `setup taiwan` silently no-ops ("no running instance labeled bb-taiwan") and the obs-v4 sync never ran — use `setup taiwan-anchor`. NOTE: native_s3 + torch_s3 both COMPLETED their planned runs cleanly (final ckpts saved) — not crashes; D64's recorded final numbers stand. Also: Alex onboarding local RTX 2070 via SSH/Tailscale-direct (awaiting host:port); balance $40 (~18h on 3 boxes after stopping ballhawk).
./vendor/PINS.md:7:| [PufferAI/PufferLib](https://github.com/PufferAI/PufferLib) | `9836f0d2e78889c1aaf189c04d161b6fc61a9386` | 2026-05-25 | 4.0 | RL framework target. **4.0 ABI**: `src/vecenv.h` macro binding (not 3.0's `env_binding.h`); native `MY_ACTION_MASK`, MultiDiscrete `ACT_SIZES`, built-in selfplay pool (`pufferlib/selfplay.py`). Best template: `ocean/chess/` (2-player, masked, perm'd, curriculum) |
./validation/fetch_replays.py:53:USER_AGENT = "bloodbowl-rl-research/0.1 (alexander.t.huth@gmail.com)"
./validation/README.md:409:planes appended after the unchanged 832 layout; `.bbp` v2; selftest plane
./validation/README.md:438:unmasked + ASan/UBSan clean; `--selftest` (TZ-plane spot-checks, micro-stat
./validation/README.md:440:resumes banked states with 0 fallbacks (ASan too); binding compiles under
./validation/README.md:449:through `puffer/bloodbowl/bloodbowl.h`, so `bbe_encode_obs`/`bbe_fill_mask`
./validation/README.md:483:The action targets are the binding's head projections of the applied
./validation/README.md:554:`resources/bloodbowl/state_bank.bbs`).
./validation/build_state_bank.py:9:resources/bloodbowl/state_bank.bbs for the env's demo-state reset curriculum
./CLAUDE.md:1:# bloodbowl-rl
./CLAUDE.md:11:| `puffer-env-dev` | PufferLib binding, build, training CLI, selfplay config |
./CLAUDE.md:31:- **obs-v4 = 2782 bytes** (probability planes A1/A2/B; spec `docs/obs-v4-spec.md`). **Three OBS_SIZE sync points must agree** (static asserts catch 2 of 3): `BBE_OBS_SIZE` in `puffer/bloodbowl/bloodbowl.h`, `#define OBS_SIZE` in `puffer/bloodbowl/binding.c:8`, `--obs-size` in `training/convert_checkpoint.py` (default 2782; v3 ckpts need `--obs-size 1612`). Old obs-v3-lineage checkpoints are input-shape **incompatible**.
./CLAUDE.md:32:- **`puffer/bloodbowl/` is the SOURCE OF TRUTH; `vendor/PufferLib/ocean/bloodbowl/` is an installed snapshot** written by `tools/install_puffer_env.sh` — the build compiles the snapshot, NOT your edit. The snapshot can lag (the Mac checkout's may still say 1612). Drift guard: `tools/install_puffer_env.sh --check` (exit 1 = re-install). Run it before any build on a training box.
./CLAUDE.md:33:- After ANY env code change, ON THE BOX: `bash tools/install_puffer_env.sh` THEN `cd vendor/PufferLib && rm -rf build && ./build.sh bloodbowl --float` (torch needs `--float`; plain build = bf16 for native CUDA; **never skip `rm -rf build`**). Mac = standalone C binaries only (`build.sh <env> --local`, strip `-mavx2 -mfma`); all training/conversion happens on boxes at `/root/bloodbowl-rl`.
./CLAUDE.md:34:- **Launch contract** (`tools/run_synthesis_c.sh`, run on the box from `~/bloodbowl-rl`): `ANCHOR=<path>` (default bc_v3b; >13MB dead-lineage size guard), `LOG=`, `STEPS=` (default 10B; asymmetric runs overshoot ~1.5x, known, benign), trailing args are appended LAST and override (last-wins). **WARNING: the script hard-codes the DEAD synthesis-C economy** (`reward-ball-loss -0.2`, `reward-ball-gain 0.1`, full-k, `demo-reset-pct 0.5`, `--tag profile-synthesis-c`, `--vec.num-threads 20`). For ANY v4 arm you MUST override the full settled knob set as trailing args — at minimum `--env.reward-ball-loss 0 --env.reward-ball-gain 0.05 --env.reward-possession 0.03` plus k-half, dist potentials, stage knob, `--tag`. **Safest: copy the exact command line of a live v4 twin** (`ps aux | grep 'puffer [t]rain'` or head of `/tmp/<tag>.log` on its box) and change only the stage knob, anchor, and tag. Asymmetric: `--train.frozen-enemy-path <ckpt>`. The script requires the demo bank at `vendor/PufferLib/resources/bloodbowl/state_bank.bbs` (a missing bank is SILENT — env trains procgen-only) and prints LIVE/TRAINER DIED at 40s — read it before walking away.
./CLAUDE.md:35:- **bc anchors live per-box only**: `fleet.sh setup` excludes `training/*.bin`; the repo tops out at bc_v3b. `bc_v4.bin` (val exact 0.508; bc_v3b was 0.371) sits in `/root/bloodbowl-rl/training/` on the v4 boxes — ship box-to-box, never re-derive. 2.09M pairs in `validation/pairs_v4` (`pairs` symlink on v4 boxes). bc_acc ceiling ~0.51 in v4 arms.
./CLAUDE.md:46:- **Tournament procedure** (runs on box-1's judge GPU): ship both ckpts to box-1 box-to-box, convert BOTH sides — `python training/convert_checkpoint.py --to-cuda A.bin -o A_cuda.bin` (**mind `--obs-size`: 2782 default, 1612 for v3 lineage**; conversion drops biases, so equal treatment of both sides matters, D45) — then `puffer match bloodbowl --load-model-path A_cuda.bin --load-enemy-model-path B_cuda.bin --num-games 4096`. Read the decisive-game split, not the draw rate.
./CLAUDE.md:49:- 4 Vast.ai boxes, **labels are state** (`vastai show instances --raw`): box-1 = bb-japan-native (24c; scraper + judge GPU + **SOLE COPY of the ~27K-file replay cache** — protect above all), box-2 = bb-taiwan-anchor (28c), box-3 = bb-ballhawk (64c FAST), box-4 = bb-possession (64c FAST). Key `~/.ssh/id_ed25519`, repo `/root/bloodbowl-rl`. Mac→ssh4 can be pathologically slow: **ship big payloads box-to-box via `ssh -A`** from a fast box. `tools/fleet.sh`: search/ls/setup/launch/status/collect (setup excludes venv/raylib/build/`training/*.bin` — rebuilt or shipped per-box; don't "fix" the excludes).
./CLAUDE.md:53:- PufferLib 4.0 (`vendor/PufferLib`, branch 4.0) uses `src/vecenv.h` macros — the online `env_binding.h` ABI is dead 3.0. `ocean/chess/` is the template; `ocean/convert/` is stale.
./CLAUDE.md:54:- Rules source: `docs/vendor/bloodbowlbase/` mirror (May 2026 FAQ, inline `<del>` errata — second sentence is current law). BB2025: 30 teams, Devious category, Elite Skills 0–4 cap. May 2026 errata removed the "D6 never below 1" floor. Team re-rolls UNLIMITED per turn (D15).
./CLAUDE.md:63:4. Partial code syncs (header without binding.c) build stale mixtures — sync `engine/` AND `puffer/` together (`fleet.sh setup`), re-run `install_puffer_env.sh` (or `--check`), and grep the changed symbol on the box.
./CLAUDE.md:72:13. **`fleet.sh setup` clobbers a box's demo bank with the Mac's (D65).** The rsync excludes don't cover `validation/states/` or `resources/bloodbowl/`, so setup overwrites the box's `state_bank.bbs` with whatever the Mac repo holds. Keep the canonical (largest) bank in the Mac's `validation/states/bank.bbs` (gitignored) so syncs ship it; after any setup, re-check `Loaded N demo states` / bank byte-size on the box.
./engine/src/bb_procgen.c:19:// a fixed list of 12 id slots (puffer/bloodbowl/bloodbowl.h BBE_SKILL_SLOTS);
./engine/src/skills_devious_traits.c:4:// Each entry quotes the BB2025 reference (docs/vendor/bloodbowlbase mirror,
./engine/src/skills_core.c:3:// Each entry quotes the BB2025 reference (docs/vendor/bloodbowlbase mirror,
./engine/src/bb_match.c:314:    // binding's defensive-reset path) instead of indexing a stale frame.
./engine/data/spec/tables.yaml:1:# BB2025 game tables — hand-extracted from the bloodbowlbase.ru mirror (errata applied inline there;
./README.md:1:# bloodbowl-rl
./README.md:19:puffer/       PufferLib binding (ocean/bloodbowl pattern)
./engine/data/spec/teams_b.yaml:2:# Hand-extracted from docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/teams/<Team>/index.html
./engine/src/skills_agility.c:3:// Each entry quotes the BB2025 reference (docs/vendor/bloodbowlbase mirror,
./engine/data/spec/SCHEMA.md:3:Hand-extracted from the BB2025 reference mirror (`docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/`), reviewable line-by-line against it. `tools/codegen.py` compiles these into `engine/src/gen_*.c` / `engine/include/bb/gen_*.h` (checked in — engine builds with zero deps).
./engine/data/spec/inducements.yaml:1:# BB2025 common inducements — hand-extracted from the bloodbowlbase.ru mirror,
./engine/include/bb/bb_match.h:168:// Only the RL binding's c_step qualifies (bbe_decode snaps onto the legal
./engine/data/spec/skills.yaml:2:# docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/core_rules/skills_and_traits/index.html
./stream_backend/decoder.py:3:Byte map per the 2026-06-10 obs-v4 layout audit (puffer/bloodbowl/bloodbowl.h):
./stream_backend/game.py:77:            args = pufferl_mod.load_config("bloodbowl")
./training/puffer_dict_capacity.patch:1:diff --git a/src/bindings.cu b/src/bindings.cu
./training/puffer_dict_capacity.patch:3:--- a/src/bindings.cu
./training/puffer_dict_capacity.patch:4:+++ b/src/bindings.cu
./training/puffer_dict_capacity.patch:10:+    Dict* out = create_dict(64); // bloodbowl my_log emits 36 keys + "n"; 32 overflowed (heap corruption)
./training/puffer_dict_capacity.patch:28:diff --git a/src/bindings_cpu.cpp b/src/bindings_cpu.cpp
./training/puffer_dict_capacity.patch:30:--- a/src/bindings_cpu.cpp
./training/puffer_dict_capacity.patch:31:+++ b/src/bindings_cpu.cpp
./training/puffer_dict_capacity.patch:37:+    Dict* out = create_dict(64); // bloodbowl my_log emits 36 keys + "n"; 32 overflowed (heap corruption)
./training/puffer_dict_capacity.patch:58:+// Local patch (bloodbowl-rl): under PRECISION_FLOAT precision_t == float and
./engine/data/spec/starplayers.yaml:1:# BB2025 Star Players — extracted from docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/starplayers/
./training/torch_pufferl_bcreg.patch:10:+    """LOCAL PATCH (bloodbowl-rl): restrict per-head logits to the env's
./training/torch_pufferl_bcreg.patch:38:+# LOCAL PATCH (bloodbowl-rl): BC-regularized PPO — human-imitation anchor.
./training/torch_pufferl_bcreg.patch:46:+# Config ([train] in config/bloodbowl.ini):
./training/torch_pufferl_bcreg.patch:62:+# anchor is single-process-only for now (all bloodbowl runs are).
./training/torch_pufferl_bcreg.patch:149:+        # LOCAL PATCH (bloodbowl-rl): legal-action masks for masked sampling.
./training/torch_pufferl_bcreg.patch:163:+        # LOCAL PATCH (bloodbowl-rl): ASYMMETRIC TRAINING (frozen enemy).
./training/torch_pufferl_bcreg.patch:196:+        # LOCAL PATCH (bloodbowl-rl): per-step masks stored so the train-time
./training/torch_pufferl_bcreg.patch:228:+        # --- LOCAL PATCH (bloodbowl-rl): BC-regularized PPO ----------------
./training/torch_pufferl_bcreg.patch:296:+        # --- LOCAL PATCH (bloodbowl-rl): BC-regularized PPO ----------------
./training/torch_pufferl_bcreg.patch:311:+        # LOCAL PATCH (bloodbowl-rl): masks alongside, same agent-major layout.
./training/torch_pufferl_bcreg.patch:318:+        # LOCAL PATCH (bloodbowl-rl): asymmetric — train on learner rows only.
./training/torch_pufferl_bcreg.patch:344:+            # LOCAL PATCH (bloodbowl-rl): score the SAME masked distribution
./training/torch_pufferl_bcreg.patch:358:+            # --- LOCAL PATCH (bloodbowl-rl): BC-regularized PPO ------------
./engine/src/skills_mutation_passing.c:4:// Each entry quotes the BB2025 reference (docs/vendor/bloodbowlbase mirror,
./training/selfplay_league.patch:24:+    # LOCAL PATCH (bloodbowl-rl): heterogeneous league seeding. When
./engine/data/spec/teams_a.yaml:2:# Source: docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/teams/<Team>/index.html
./engine/include/bb/bb_hooks.h:132:// array, and the Linux training binding steps environments from multiple
./training/test_selfplay_league.py:61:    '''Records the backend calls setup() makes (bindings.cu surface).'''
./training/test_selfplay_league.py:121:        'env_name': 'bloodbowl',
./training/test_selfplay_league.py:183:        # bloodbowl flat-fp32 artifact (training/test_convert_checkpoint.py)
./training/test_selfplay_league.py:271:        boot = os.path.join(self.tmp, 'bloodbowl', 'runid', 'pool',
./puffer/bloodbowl/bloodbowl.h:1:// bloodbowl.h — PufferLib 4.0 native env wrapping the BB2025 engine.
./puffer/bloodbowl/bloodbowl.h:60:// --- Engine amalgamation (build.sh compiles binding.c as a single TU) -------
./puffer/bloodbowl/bloodbowl.h:63:// vendor/PufferLib/ocean/bloodbowl/ tree (tools/install_puffer_env.sh uses
./puffer/bloodbowl/bloodbowl.h:182:    // else means the engine/binding contract broke mid-training.
./puffer/bloodbowl/bloodbowl.h:214:    // Reward shaping / episode bound ([env] kwargs in config/bloodbowl.ini).
./puffer/bloodbowl/bloodbowl.h:340:    // (resources/bloodbowl/state_bank.bbs, built by
./puffer/bloodbowl/bloodbowl.h:780:// are visible: the binding compiles env+engine as one TU.
./puffer/bloodbowl/bloodbowl.h:1054:// Shared, lazily loaded once per process (per TU — binding.c is the single
./puffer/bloodbowl/bloodbowl.h:1062:#define BBE_STATE_BANK_PATH "resources/bloodbowl/state_bank.bbs"
./puffer/bloodbowl/bloodbowl.h:1075:// Load the bank once. Call sites: the binding's init entry points (before
./puffer/bloodbowl/bloodbowl.h:1090:                "bloodbowl: state bank %s incompatible with this engine build "
./puffer/bloodbowl/bloodbowl.h:1104:        fprintf(stderr, "bloodbowl: state bank %s malformed (%ld bytes) — "
./puffer/bloodbowl/binding.c:1:// binding.c — PufferLib 4.0 vecenv glue for the Blood Bowl env.
./puffer/bloodbowl/binding.c:6:#include "bloodbowl.h"
./puffer/bloodbowl/binding.c:20:_Static_assert(OBS_SIZE == BBE_OBS_SIZE, "OBS_SIZE out of sync with bloodbowl.h");
./puffer/bloodbowl/binding.c:22:               "MY_ACTION_MASK out of sync with bloodbowl.h");
./puffer/bloodbowl/binding.c:47:                "bloodbowl: ACT_SIZES {%d, %d, %d} out of sync with BBE_HEAD_* "
./puffer/bloodbowl/binding.c:139:                "bloodbowl: total_agents (%d) must be divisible by "
./puffer/bloodbowl/binding.c:197:    // CAPACITY: vec_log (src/bindings_cpu.cpp / bindings.cu) hands us a
./training/convert_checkpoint.py:8:  * CUDA backend (src/bindings.cu save_weights/load_weights): a raw
./training/convert_checkpoint.py:13:This tool converts between them so `puffer train bloodbowl
./training/convert_checkpoint.py:66:      --to-cuda training/checkpoints/bc_bloodbowl.bin -o bc_cuda.bin
./training/convert_checkpoint.py:68:      --to-torch checkpoints/bloodbowl/<run>/<step>.bin -o run_torch.bin
./training/convert_checkpoint.py:81:# Mirrors ACT_SIZES in puffer/bloodbowl/binding.c and bc_pretrain.py.
./training/convert_checkpoint.py:88:DEFAULT_CONFIG = os.path.join(ROOT, "puffer", "config", "bloodbowl.ini")
./Makefile:1:# bloodbowl-rl engine build
./Makefile:66:# Single-TU build through the PufferLib env amalgamation (bloodbowl.h includes
./Makefile:68:# --dump-pairs. -Wno-unused-function: the env header defines the full binding
./Makefile:71:	$(CC) $(CFLAGS) -Ipuffer/bloodbowl -Wno-unused-function \
./puffer/config/bloodbowl.ini:6:env_name = bloodbowl
./puffer/config/bloodbowl.ini:139:# banked FUMBBL mid-game state (resources/bloodbowl/state_bank.bbs — built by
./puffer/bloodbowl/bbe_render.h:6://     resources/bloodbowl/ by tools/stage_spectator_art.py. Sheet format
./puffer/bloodbowl/bbe_render.h:323:    snprintf(c->art_dir, sizeof(c->art_dir), "%s", art ? art : "resources/bloodbowl");
./engine/tests/test_rules_movement.c:8:// docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/:
./puffer/bloodbowl/bbe_profile.c:6:// untimed driver (bloodbowl.c), this file explains WHERE the time goes.
./puffer/bloodbowl/bbe_profile.c:8:// Build: clang -O2 -Ipuffer/bloodbowl puffer/bloodbowl/bbe_profile.c -o bbe_profile
./puffer/bloodbowl/bbe_profile.c:9:#include "bloodbowl.h"
./engine/tests/test_rules_ball.c:4://   GAME = docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/core_rules/the_game_of_blood_bowl/index.html
./puffer/bloodbowl/bbe_microstats_probe.c:8:// Build: clang -O2 -Ipuffer/bloodbowl puffer/bloodbowl/bbe_microstats_probe.c -o /tmp/bbe_microstats_probe
./puffer/bloodbowl/bbe_microstats_probe.c:10:#include "bloodbowl.h"
./tools/train_profile.sh:54:  d=$(ls -td checkpoints/bloodbowl/*/ 2>/dev/null | head -1)
./tools/train_profile.sh:58:exec puffer train bloodbowl --tag "profile-$PROFILE" "${ARGS[@]}" "$@"
./puffer/bloodbowl/bloodbowl.c:1:// bloodbowl.c — standalone driver for the PufferLib env (build.sh --local /
./puffer/bloodbowl/bloodbowl.c:8:#include "bloodbowl.h"
./puffer/bloodbowl/bloodbowl.c:24:// --- Self-test (--selftest) --------------------------------------------------
./puffer/bloodbowl/bloodbowl.c:37:            printf("SELFTEST FAIL (bloodbowl.c:%d): ", __LINE__);              \
./puffer/bloodbowl/bloodbowl.c:206:static int bbe_selftest(uint64_t seed, int episodes) {
./puffer/bloodbowl/bloodbowl.c:332:    printf("bloodbowl selftest: %d episodes, %d failure(s), v4 planes B=%ld A=%ld\n",
./puffer/bloodbowl/bloodbowl.c:380:    int selftest = 0;
./puffer/bloodbowl/bloodbowl.c:387:        else if (strcmp(argv[i], "--selftest") == 0) selftest = 1;
./puffer/bloodbowl/bloodbowl.c:397:    if (selftest) return bbe_selftest(seed, episodes);
./puffer/bloodbowl/bloodbowl.c:476:    printf("bloodbowl standalone: %d episodes, %ld steps in %.2fs (%s)\n",
./docs/drills-design.md:27:   `puffer/bloodbowl/bloodbowl.h` reset logic). Cost: ~30 lines of C per
./docs/drills-design.md:28:   predicate + 1 ini/binding knob. Limited to states that occur in human play.
./docs/drills-design.md:54:`vendor/PufferLib/resources/bloodbowl/` and an arm points at it.
./engine/tests/test_rules_blocking.c:6:// docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/:
./engine/tests/test_skills_devious_traits.c:4:// Authoritative source, under docs/vendor/bloodbowlbase/bloodbowlbase.ru/
./engine/tests/test_rules_injury.c:5://   docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/
./training/bc_pretrain.py:12:[policy]/[torch] sections of config/bloodbowl.ini layered over PufferLib's
./training/bc_pretrain.py:14:PuffeRL.save_weights writes and `puffer train bloodbowl --load-model-path
./training/bc_pretrain.py:28:save/load_weights (src/bindings.cu) is a raw flat-fp32 master_weights blob
./training/bc_pretrain.py:66:# Mirrors ACT_SIZES in puffer/bloodbowl/binding.c (asserted against the .bbp
./training/bc_pretrain.py:232:                                                     "bloodbowl.ini"))
./training/bc_pretrain.py:234:                                                  "bc_bloodbowl.bin"))
./engine/tests/test_rules_structure.c:5://   docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/
./engine/tests/test_match.c:127:// bb_apply_trusted is the RL binding's fast path (no legal-set
./engine/tests/test_match.c:130:// binding's trajectories silently diverge from every validation layer that
./engine/tests/test_match.c:163:// Misusing the trusted path must degrade to BB_STATUS_ERROR (the binding's
./training/test_bcreg_torch_pufferl.py:54:    args = load_config("bloodbowl")
./training/test_bcreg_torch_pufferl.py:111:    if "LOCAL PATCH (bloodbowl-rl): BC-regularized PPO" not in patched:
./engine/tests/test_skills_mutation_passing.c:6:// test). Authoritative source, under docs/vendor/bloodbowlbase/
./engine/tests/test_skills_mutation_passing.c:7:// bloodbowlbase.ru/bb2025/core_rules/:
./docs/sps-optimization-plan.md:3:Synthesized from four measurement/analysis passes (env hot-path profiling + prototypes on Mac M-series; code-traced vec/trainer/GPU analysis; PufferLib 4.x field lore). Config verified on disk: `vendor/PufferLib/config/bloodbowl.ini` [vec] = `total_agents=4096, num_buffers=1, num_threads=8`; upstream `default.ini` ships `2/16`. Env prototype branch verified present: worktree `worktree-wf_7ddff3ba-252-1` @ `b5a48de`.
./docs/sps-optimization-plan.md:15:### 1b. Inside one c-step (Mac M-series, clang -O2, masked random play, 513K steps, instrumented driver `puffer/bloodbowl/bbe_profile.c` + `sample` corroboration; baseline 2295 ns)
./docs/sps-optimization-plan.md:29:**Net measured result of the prototype stack:** 389,425 → 692,558 c-steps/s masked (+77.8%); 697,706 → 1,337,959 unmasked (+91.8%). Trajectories bit-identical to baseline (illegal_frac, all aggregate stats, seeds 42+1337). 280/280 tests incl. ASan/UBSan, selftest 300 eps clean, 90 s libFuzzer clean.
./docs/sps-optimization-plan.md:90:2. `config/bloodbowl.ini` [vec]: `num_threads = 20`, `num_buffers = 2`. Sight-unseen floor ~1.5×, ceiling ~2.7×; worst plausible case flat (P1 would expose memory-boundedness at zero cost). If single-variable conservatism is wanted: `num_threads = 20` alone is strictly safe.
./docs/sps-optimization-plan.md:114:Key files: `vendor/PufferLib/src/vecenv.h` (:239-334, :258, :284, :291), `vendor/PufferLib/src/pufferlib.cu` (:573-699, :1457, :1550, :2102-2170), `vendor/PufferLib/config/bloodbowl.ini`, `puffer/bloodbowl/bloodbowl.h`, `puffer/bloodbowl/bbe_profile.c` (worktree), `engine/src/proc_match.c`, `.reviews/adversarial-20260603.md`, worktree `/Users/alexanderhuth/Code/bloodbowl-rl/.claude/worktrees/wf_7ddff3ba-252-1` (branch `worktree-wf_7ddff3ba-252-1`).
./docs/stream-protocol.md:5:built separately in the bloodbowl-rl repo against this same spec — build the
./docs/stream-protocol.md:7:server. Protocol version: `1`. Owner: bloodbowl-rl repo, docs/stream-plan.md.*
./docs/stream-protocol.md:129:  win-prob bar. The bloodbowl-rl raylib viewer is the visual reference; match
./docs/stream-protocol.md:144:   line (snapshot + ~2000 deltas + match_end). *The bloodbowl-rl side will
./docs/stream-protocol.md:162:- This file is the single source of truth (lives in bloodbowl-rl:
./docs/stream-protocol.md:165:- The bloodbowl-rl side owes: the game server, the sprite pack at
./tools/fetch_docs.sh:5:mkdir -p papers gw pufferlib fumbbl bloodbowlbase
./tools/fetch_docs.sh:9:curl -sL -o bloodbowl-challenge-justesen2019.pdf "https://njustesen.github.io/njustesen/publications/justesen2019blood.pdf"
./tools/fetch_docs.sh:10:curl -sL -o bloodbowl-deeprl-justesen2018.pdf "https://njustesen.github.io/njustesen/publications/justesen2018blood.pdf"
./tools/fetch_docs.sh:20:curl -sL -o gw/bb-faq-errata-nov2025.pdf "https://assets.warhammer-community.com/eng_14-11_bloodbowl_faq_errata-ngh7bivuzu-vslz4fw2nm.pdf"
./tools/fetch_docs.sh:31:cd bloodbowlbase
./tools/fetch_docs.sh:34:  --domains=bloodbowlbase.ru --include-directories=/bb2025 \
./tools/fetch_docs.sh:35:  --user-agent="bloodbowl-rl-research (personal project; polite mirror)" \
./tools/fetch_docs.sh:36:  "https://bloodbowlbase.ru/bb2025/" || true
./tools/long_scrape.sh:8:cd ~/bloodbowl-rl
./docs/SOURCES.md:9:| `bloodbowl-challenge-justesen2019.pdf` | https://njustesen.github.io/njustesen/publications/justesen2019blood.pdf — "Blood Bowl: A New Board Game Challenge and Competition for AI" (IEEE CoG 2019) |
./docs/SOURCES.md:10:| `bloodbowl-deeprl-justesen2018.pdf` | https://njustesen.github.io/njustesen/publications/justesen2018blood.pdf — deep RL approach to Blood Bowl |
./docs/SOURCES.md:22:| `bb-faq-errata-nov2025.pdf` | https://assets.warhammer-community.com/eng_14-11_bloodbowl_faq_errata-ngh7bivuzu-vslz4fw2nm.pdf — Designer's Commentary + Errata, Third Season, Nov 2025. GW posts updates each May/Nov at https://www.warhammer-community.com/en-gb/downloads/blood-bowl/ (JS-rendered; find asset URLs via search or community mirrors) |
./docs/SOURCES.md:24:## BB2025 rules reference (`docs/vendor/bloodbowlbase/`)
./docs/SOURCES.md:26:Polite mirror (wget, rate-limited) of https://bloodbowlbase.ru/bb2025/ — full Third Season rules reference: core rules, skills & traits (with ACTIVE/PASSIVE annotations), inducements, 31 team rosters, star players, latest FAQ (May 2026). Re-mirror: see command in git history or `tools/fetch_docs.sh`.
./docs/SOURCES.md:30:`docs.html`, `blog.html`, `ocean.html` from https://puffer.ai/. NOTE: much online material describes the 3.0 `env_binding.h` ABI; we target the **4.0 branch** `src/vecenv.h` macro ABI (see `vendor/PINS.md` and the `puffer-env-dev` skill).
./docs/reward-audit-decision-time.md:100:  Elo. `[sweep.train.gamma]` in config/bloodbowl.ini for Protein sweeps;
./docs/rl-best-practices.md:1:# RL Best Practices — bloodbowl-rl Reference Library
./docs/rl-best-practices.md:12:**Finding:** Both trainers clamp rewards *before* advantage computation: `vendor/PufferLib/pufferlib/torch_pufferl.py:411` (`rew = self.rewards.T.contiguous().clamp(-1, 1)`) and `vendor/PufferLib/src/pufferlib.cu:1509-1510` (`clamp_precision_kernel`). Our `reward_win = 3.0` in `puffer/config/bloodbowl.ini` is clamped to **+1.0**, so the agent has trained under Win(±1) = TD(±1), not the documented Win(±3) ≫ TD(±1). A game-winning TD (+1 TD, +3 win → +4) clamps to +1, making the win bonus invisible exactly when it matters. The effective win-vs-draw gap was 1.5, not 3.5 — directly favoring the draw equilibrium. The clamp also breaks the [Ng et al. 1999] PBRS telescoping invariance on any step where shaping + event rewards saturate.
./docs/rl-best-practices.md:16:**Literature:** PufferLib's own flagship 2-player selfplay env (chess) escapes sparse-reward basins not with shaping but by starting **90% of episodes from non-initial positions** (`vendor/PufferLib/config/chess.ini` `fen_curric_pct = 0.9`; `ocean/chess/chess.h:2318-2333`, `binding.c:106-133`). Same mechanism solved Montezuma with plain PPO ([Salimans & Chen 2018](https://arxiv.org/abs/1812.03381)), and **beat both reward shaping and BC head-to-head in a stochastic zero-sum multiplayer game** ([Backplay, Resnick et al. 2018](https://arxiv.org/abs/1807.06919), Pommerman). Success-band gating per [Florensa et al. 2017](https://arxiv.org/abs/1707.05300).
./docs/rl-best-practices.md:18:**Action:** Dump mid-game states from human replays into a state file; add a `state_curric_pct` reset path to the BB env mirroring chess's `SHARED_FEN_CURRICULUM` pattern in `binding.c` (single shared load in `my_vec_init`). Anneal start points backward from near-TD states (Salimans-Chen). Keep a held-out from-kickoff eval to detect critic distribution skew. **Effort: ~2-4 days.**
./docs/rl-best-practices.md:135:1. **Run a Protein sweep** (100-200 trials, broad→narrow, match-mode scored against a frozen reference enemy — the curriculum-stage-1 or BC checkpoint). Fix `[sweep] metric = perf` in `puffer/config/bloodbowl.ini` (default is `score`; see [issue #577](https://github.com/PufferAI/PufferLib/issues/577)). *Days of GPU time, hours of setup.*
./docs/rl-best-practices.md:139:5. Verify our binding randomizes home/away (kick/receive) per env like chess's `binding.c:120-131` slot↔color randomization, so each policy trains and evals on both sides equally.
./docs/rl-best-practices.md:180:Single entry point (`tools/eval_suite.py`) → `eval_report.json` + cross-table heatmap. Engine speed makes everything cheap except C. Current `Log` struct (`puffer/bloodbowl/bloodbowl.h:106-127`) is selfplay-internal only — that is why 0-0 looked like convergence.
./docs/stream-plan.md:1:# bloodbowl.live — 24/7 AI Blood Bowl stream (plan)
./docs/stream-plan.md:5:seconds0.com (or a subdomain, e.g. `bloodbowl.seconds0.com`) with a live,
./docs/stream-plan.md:39:| Game state | direct `env->match` fields (players x/y/stance, ball, score, half, turn, active_team) | `puffer/bloodbowl/bloodbowl.h:335` |
./docs/stream-plan.md:43:| Move odds overlay | obs-v4 B plane (step success per square), A1/A2 (block outcome per square) | `bloodbowl.h:114-122` |
./docs/stream-plan.md:45:| Pacing | `--env.render-fps` kwarg (decisions/sec) | `bbe_render.h:319`, binding kwarg |
./docs/nufflebot-feasibility.md:3:**Subject:** Deploying the trained bloodbowl-rl policy as a declared bot on FUMBBL
./docs/nufflebot-feasibility.md:5:**Inputs:** Three completed investigations (architecture, state/action mapping, prior art/governance) over `vendor/ffb` (MIT, the actual FUMBBL client+server monorepo), `vendor/jervis-ffb`, our engine (`engine/`, `puffer/bloodbowl/`), and `validation/normalize_replay.py`. The dedicated protocol deep-dive agent failed, but its scope (transport, wire format, command vocabulary, auth, dice authority) was independently established by the architecture investigation and is treated as covered. All file paths cited below were verified to exist in the working tree.
./docs/nufflebot-feasibility.md:11:**Feasible. High confidence (~85%) on the technical side; the binding constraint is governance, not engineering — and governance looks unusually favorable.**
./docs/nufflebot-feasibility.md:61:|    (bloodbowl.h:433 "exact -> same-type -> first")       |
./docs/nufflebot-feasibility.md:90:- **Policy runner change:** factor `bbe_encode_obs` (`puffer/bloodbowl/bloodbowl.h:251`, coupled to the env struct) into a `bb_match`-only variant `bbe_encode_obs_match(const bb_match*, int agent, uint8_t out[832])`.
./docs/nufflebot-feasibility.md:192:**Bottom line:** Build Phase 4 (it's 70% of the bot), add the headless Java module and reverse mapper against the local standalone server with scripted dice, hit the zero-desync soak gate — then take the working bot and this report to Christer, who has already asked for exactly this. Key sources: `vendor/ffb/ffb-client-logic/.../FantasyFootballClient.java`, `.../ClientCommunication.java`, `.../DialogManager.java`; `vendor/ffb/ffb-server/.../FantasyFootballServer.java`, `DiceRoller.java`, `TalkHandlerRoll.java`, `server.ini`; `vendor/jervis-ffb/docs/working-with-ffb.md`, `modules/fumbbl-net/.../FumbblWebsocketConnection.kt`; `validation/normalize_replay.py`; `engine/include/bb/bb_rng.h`, `bb_match.h`; `puffer/bloodbowl/bloodbowl.h`; FUMBBL forum threads t=32780 (admin invitation), t=32558 (ask-first precedent), t=21820 (test division precedent).
./tools/rig_babysitter.sh:11:cd "$HOME/bloodbowl-rl" || exit 1
./tools/rig_babysitter.sh:14:LOG="$HOME/bloodbowl-rl/rig-babysitter.log"
./tools/cpu_cap.sh:5:#     source /root/bloodbowl-rl/tools/cpu_cap.sh
./docs/policy-research.md:26:**Stretch:** a custom CUDA encoder (`create_custom_encoder("bloodbowl", ...)`) that
./docs/policy-research.md:52:(`src/bindings.cu:402-403`). `expansion_factor` in `config/chess.ini:35` is **dead config** —
./docs/policy-research.md:76:`ocean/chess/binding.c:4-8`: `OBS_SIZE 167` (ByteTensor), `NUM_ATNS 1`, `ACT_SIZES {97}`,
./docs/policy-research.md:94:(`ocean/chess/binding.c:126-132`). Policy is side-agnostic by construction.
./docs/policy-research.md:123:binding on the Mac, (b) BC pretraining (standalone, outside pufferl entirely — §7.3).
./docs/policy-research.md:193:  (`docs/vendor/papers/bloodbowl-challenge-justesen2019.pdf`; same net in
./docs/policy-research.md:247:   (player slots 16, act kinds 14, dice 3, reroll sources 4, binary 2). The binding maps
./docs/policy-research.md:253:// puffer/bloodbowl/binding.c
./docs/policy-research.md:290:index space. Pros: one softmax, simplest possible binding. Cons: setup needs an extra phase,
./docs/policy-research.md:294:### 5.4 Mask-writing rules (binding contract)
./docs/policy-research.md:300:`reward_invalid_*` pattern, `ocean/chess/binding.c`).
./docs/policy-research.md:314:| Egocentric flip | — | away team sees the pitch mirrored (chess's `sq^56` analog); slot↔side randomized at init (`binding.c:126-132` pattern) |
./docs/policy-research.md:345:`config/bloodbowl.ini` (delta from `config/default.ini`; chess values as priors):
./docs/policy-research.md:349:env_name = bloodbowl
./docs/policy-research.md:426:`master_weights` blob (`src/bindings.cu:180-218`), in registration order
./docs/policy-research.md:436:### 7.2 STRETCH — custom CUDA "bloodbowl" encoder (conv trunk + entity embeddings)
./docs/policy-research.md:467:Read of `pufferlib/selfplay.py` + `src/pufferlib.cu:1728-1865` + `src/bindings.cu:180-229`:
./docs/policy-research.md:476:- Policy/binding obligations are all env-side: `MY_USES_PERM` + per-slot pointer arrays,
./docs/policy-research.md:518:| Fixed Encoder/MinGRU/Decoder policy; only hidden/layers configurable | `src/pufferlib.cu:1679-1726`, `src/bindings.cu:402-403` |
./docs/policy-research.md:523:| Chess: 167-byte token obs, 97-action single head, two-phase pick, legality-in-obs | `ocean/chess/binding.c:4-8`, `ocean/chess/chess.h:279-296,357-358,469,1666-1716` |
./docs/policy-research.md:525:| Frozen banks = same build_policy, load flat-fp32 save_weights snapshots | `src/pufferlib.cu:1728-1865`, `src/bindings.cu:180-229`, `pufferlib/selfplay.py:119-211,267-277` |
./docs/policy-research.md:529:| Botbowl baselines / MimicBot architecture | `docs/vendor/papers/bloodbowl-challenge-justesen2019.pdf`, arXiv 2108.09478, `vendor/botbowl/examples/a2c/a2c_agent.py:28-41` |
./tools/build_league.py:33:(vendor/PufferLib/src/bindings.cu:180: raw fwrite of master_weights, no
./tools/build_league.py:37:seed's size up front. 13,670,400 bytes = the bloodbowl policy (obs 1612 =
./docs/homebrew-team-authoring.md:68:clang -std=c11 -O2 -Ipuffer/bloodbowl puffer/bloodbowl/bloodbowl.c -o /tmp/bbe \
./docs/homebrew-team-authoring.md:69:  && /tmp/bbe --selftest                             # binding-level checks
./docs/homebrew-team-authoring.md:79:puffer eval bloodbowl --slowly --selfplay.enabled 0 \
./docs/bbtv-subdomain-handoff.md:296:from the rig — the live copy is at `~/bloodbowl-rl/stream/web/app.js` on the rig):
./docs/bbtv-subdomain-handoff.md:334:sure the **rig's** `~/bloodbowl-rl/stream/web/app.js` is the one that changed,
./docs/bbtv-subdomain-handoff.md:337:> Do not change anything else in `app.js` or anywhere else in `~/bloodbowl-rl`.
./docs/bbtv-subdomain-handoff.md:438:  anything in `~/bloodbowl-rl` **except** the single `WS_URL` default in
./docs/bbtv-subdomain-handoff.md:471:| Page file to patch | `stream/web/app.js` (rig: `~/bloodbowl-rl/stream/web/app.js`), `WS_URL` default → same-origin `/ws` |
./tools/gpu_box_setup.sh:16:echo "=== [3/5] install bloodbowl env into PufferLib tree ==="
./tools/gpu_box_setup.sh:19:# build.sh's standalone (--fast/--local) path compiles ocean/bloodbowl/bloodbowl.c
./tools/gpu_box_setup.sh:20:# WITHOUT -I$SRC_DIR (the binding path has it), so the engine's "bb/*.h"
./tools/gpu_box_setup.sh:22:if ! grep -q 'ocean/bloodbowl' "$ROOT/vendor/PufferLib/build.sh"; then
./tools/gpu_box_setup.sh:23:    sed -i 's|^INCLUDES=(-I./\$RAYLIB_NAME/include -I./src -I./vendor)$|INCLUDES=(-I./$RAYLIB_NAME/include -I./src -I./vendor -I./ocean/bloodbowl)|' \
./tools/gpu_box_setup.sh:25:    grep -q 'ocean/bloodbowl' "$ROOT/vendor/PufferLib/build.sh" || { echo "build.sh include patch failed" >&2; exit 1; }
./tools/gpu_box_setup.sh:29:./build.sh bloodbowl --fast
./tools/gpu_box_setup.sh:30:./bloodbowl 64
./tools/gpu_box_setup.sh:39:./build.sh bloodbowl
./tools/gpu_box_setup.sh:44:if ! grep -q 'bloodbowl-rl/tools/cpu_cap.sh' ~/.bashrc 2>/dev/null; then
./tools/gpu_box_setup.sh:45:    echo '[ -f /root/bloodbowl-rl/tools/cpu_cap.sh ] && . /root/bloodbowl-rl/tools/cpu_cap.sh' >> ~/.bashrc
./tools/gpu_box_setup.sh:50:echo "  cd vendor/PufferLib && puffer train bloodbowl --train.total-timesteps 20000000"
./docs/stream-connect.md:10:| Piece | Path (bloodbowl-rl repo) | Status |
./docs/stream-connect.md:39:   build step, no dependencies) — serve at `/bloodbowl` or embed via iframe.
./docs/stream-server-brief.md:4:(bloodbowl-rl). The wire contract is `docs/stream-protocol.md` (v1, frozen —
./docs/stream-server-brief.md:24:| Env + engine | `puffer/bloodbowl/` (source of truth) → installed snapshot in `vendor/PufferLib/ocean/bloodbowl/` | build with `--float` (torch path) |
./docs/stream-server-brief.md:27:| Game state | `env->match` via the binding; players `players[32].{x,y,stance,location}`, `ball.{x,y,state,carrier}`, `score`, `half`, `turn[2]`, `active_team` | serialize from match fields, not obs bytes |
./docs/stream-server-brief.md:31:| Checkpoints | newest flagship ckpt BY STEP NUMBER in `vendor/PufferLib/checkpoints/bloodbowl/<newest dir>/` | footgun 10: mtime ≠ step |
./docs/stream-server-brief.md:38:  instance through the binding, or simplest: a 2-agent `puffer` env with
./docs/stream-server-brief.md:55:  the binding the same way the Log dict is exposed (see binding.c dict_set
./docs/stream-server-brief.md:57:  binding change is needed, it follows the 3-sync-point rule (bloodbowl.h /
./docs/stream-server-brief.md:58:  binding.c / ini — see CLAUDE.md).
./tools/install_puffer_env.sh:2:# Install/refresh the bloodbowl env into the vendored PufferLib tree.
./tools/install_puffer_env.sh:4:# puffer/bloodbowl/ holds the source of truth; its engine/ and bb/ symlinks
./tools/install_puffer_env.sh:6:# installed ocean/bloodbowl/ is self-contained — build.sh's stock
./tools/install_puffer_env.sh:29:DST="$PUFFER/ocean/bloodbowl"
./tools/install_puffer_env.sh:31:# Content hash of a tree with symlinks dereferenced (the puffer/bloodbowl
./tools/install_puffer_env.sh:43:    want="$(snapshot_hash "$ROOT/puffer/bloodbowl")"
./tools/install_puffer_env.sh:49:    echo "drift check: STALE snapshot — engine/src or puffer/bloodbowl changed since install" >&2
./tools/install_puffer_env.sh:57:cp -RL "$ROOT/puffer/bloodbowl/." "$DST/"
./tools/install_puffer_env.sh:58:cp "$ROOT/puffer/config/bloodbowl.ini" "$PUFFER/config/bloodbowl.ini"
./tools/install_puffer_env.sh:60:snapshot_hash "$ROOT/puffer/bloodbowl" > "$DST/.content_hash"
./tools/install_puffer_env.sh:71:# it from resources/bloodbowl/state_bank.bbs and degrades to plain procgen
./tools/install_puffer_env.sh:74:    mkdir -p "$PUFFER/resources/bloodbowl"
./tools/install_puffer_env.sh:75:    cp "$ROOT/validation/states/bank.bbs" "$PUFFER/resources/bloodbowl/state_bank.bbs"
./tools/install_puffer_env.sh:76:    echo "staged:    $PUFFER/resources/bloodbowl/state_bank.bbs"
./tools/install_puffer_env.sh:80:echo "           $PUFFER/config/bloodbowl.ini"
./tools/install_puffer_env.sh:81:echo "build:     cd $PUFFER && ./build.sh bloodbowl          # CUDA training backend"
./tools/install_puffer_env.sh:82:echo "           cd $PUFFER && ./build.sh bloodbowl --fast   # standalone benchmark"
./tools/run_synthesis_c.sh:7:# Run ON the box from ~/bloodbowl-rl:  bash tools/run_synthesis_c.sh
./tools/run_synthesis_c.sh:15:#   - demo bank staged at vendor/PufferLib/resources/bloodbowl/state_bank.bbs
./tools/run_synthesis_c.sh:36:BANK="resources/bloodbowl/state_bank.bbs"
./tools/run_synthesis_c.sh:47:nohup puffer train bloodbowl --slowly --selfplay.enabled 0 \
./tools/run_synthesis_c.sh:69:  d=$(ls -td checkpoints/bloodbowl/*/ 2>/dev/null | head -1)
./tools/spectate.sh:45:        "$HOST:~/bloodbowl-rl/vendor/PufferLib/checkpoints/bloodbowl/" \
./tools/spectate.sh:46:        checkpoints/bloodbowl/ 2>/dev/null \
./tools/spectate.sh:49:    newest=$(find checkpoints/bloodbowl -name '*.bin' -print0 2>/dev/null \
./tools/spectate.sh:66:    timeout "$CYCLE" puffer eval bloodbowl --slowly \
./tools/run_bcreg.sh:11:#   * _C must be built with ./build.sh bloodbowl --float (torch backend
./tools/run_bcreg.sh:39:$PYBIN - <<'EOF' || { echo "fix: ./build.sh bloodbowl --float" >&2; exit 1; }
./tools/run_bcreg.sh:41:assert getattr(_C, 'env_name', None) == 'bloodbowl', f"_C built for {getattr(_C, 'env_name', None)}, not bloodbowl"
./tools/run_bcreg.sh:42:assert _C.precision_bytes == 4, "torch backend needs fp32: rebuild with ./build.sh bloodbowl --float"
./tools/run_bcreg.sh:43:assert _C.gpu, "_C is a CPU build — rebuild on the CUDA box with ./build.sh bloodbowl --float"
./tools/run_bcreg.sh:55:  d=$(ls -td checkpoints/bloodbowl/*/ 2>/dev/null | head -1)
./tools/run_bcreg.sh:59:exec puffer train bloodbowl --slowly --tag profile-BCreg \
./tools/eval_game_stats.sh:8:#                   _cuda flat blob). Run ON a box from /root/bloodbowl-rl.
./tools/eval_game_stats.sh:40:puffer train bloodbowl --slowly --selfplay.enabled 0 \
./tools/stage_spectator_art.py:5:vendor/PufferLib/resources/bloodbowl/ (the renderer's cwd-relative default)
./tools/stage_spectator_art.py:26:OUT = ROOT / "vendor/PufferLib/resources/bloodbowl"
./tools/setup_arm.sh:47:    "cd /root/bloodbowl-rl/vendor/PufferLib && rm -rf build && \
./tools/setup_arm.sh:48:     ./build.sh bloodbowl --float > /tmp/build_float.log 2>&1 && \
./tools/setup_arm.sh:54:         /root/bloodbowl-rl/validation/pairs/ root@$HOST:/root/bloodbowl-rl/validation/pairs/ && \
./tools/setup_arm.sh:56:         /root/bloodbowl-rl/validation/states/bank.bbs root@$HOST:/root/bloodbowl-rl/validation/states/bank.bbs && \
./tools/setup_arm.sh:58:         /root/bloodbowl-rl/vendor/PufferLib/resources/bloodbowl/state_bank.bbs \
./tools/setup_arm.sh:59:         root@$HOST:/root/bloodbowl-rl/vendor/PufferLib/resources/bloodbowl/state_bank.bbs && \
./tools/setup_arm.sh:61:         /root/bloodbowl-rl/training/bc_v3b.bin root@$HOST:/root/bloodbowl-rl/training/"
./tools/setup_arm.sh:65:    "cd /root/bloodbowl-rl && LOG=/tmp/$TAG.log bash tools/run_synthesis_c.sh --tag '$TAG' $* 2>&1 | tail -5"
./tools/run_native_asym.sh:10:# Run ON the box from ~/bloodbowl-rl:  TAG=<name> bash tools/run_native_asym.sh
./tools/run_native_asym.sh:48:#       rm -rf build && ./build.sh bloodbowl     # NO --float, never skip rm).
./tools/run_native_asym.sh:49:#     (bindings.cu:509 exports sizeof(precision_t).)
./tools/run_native_asym.sh:56:#   - installed config/bloodbowl.ini has the league_preseed key (load_config
./tools/run_native_asym.sh:58:#   - demo bank at vendor/PufferLib/resources/bloodbowl/state_bank.bbs
./tools/run_native_asym.sh:106:  echo "ON a training box (/root/bloodbowl-rl), never the Mac checkout." >&2
./tools/run_native_asym.sh:115:# not your edit; a drifted puffer/bloodbowl means the .so may be stale) ----
./tools/run_native_asym.sh:118:    echo "puffer/bloodbowl drifted from the installed snapshot. Fix:" >&2
./tools/run_native_asym.sh:119:    echo "  bash $ROOT/tools/install_puffer_env.sh && cd $ROOT/vendor/PufferLib && rm -rf build && ./build.sh bloodbowl" >&2
./tools/run_native_asym.sh:128:grep -q '^league_preseed' config/bloodbowl.ini || {
./tools/run_native_asym.sh:129:  echo "refreshing config/bloodbowl.ini (league_preseed key)"
./tools/run_native_asym.sh:130:  cp "$ROOT/puffer/config/bloodbowl.ini" config/bloodbowl.ini
./tools/run_native_asym.sh:132:grep -q '^league_preseed' config/bloodbowl.ini || {
./tools/run_native_asym.sh:133:  echo "config/bloodbowl.ini still lacks league_preseed — pull latest repo" >&2; exit 1; }
./tools/run_native_asym.sh:155:# ---- guard: NATIVE bloodbowl GPU build (the .so WITHOUT --float) ------------
./tools/run_native_asym.sh:165:  echo "  bash $ROOT/tools/install_puffer_env.sh && cd $ROOT/vendor/PufferLib && rm -rf build && ./build.sh bloodbowl" >&2
./tools/run_native_asym.sh:167:elif [ "$cenv" != "bloodbowl" ]; then
./tools/run_native_asym.sh:168:  echo "_C is built for '$cenv', not bloodbowl — rebuild:  rm -rf build && ./build.sh bloodbowl" >&2
./tools/run_native_asym.sh:175:  echo "rebuild native:  cd $ROOT/vendor/PufferLib && rm -rf build && ./build.sh bloodbowl   # NO --float, never skip rm -rf build" >&2
./tools/run_native_asym.sh:181:echo "build: native bf16 bloodbowl GPU (_C.precision_bytes=2) — correct for this architecture"
./tools/run_native_asym.sh:207:BANK="resources/bloodbowl/state_bank.bbs"
./tools/run_native_asym.sh:261:#       per-game score is {1.0 win, 0.5 draw, 0.0 loss} (bloodbowl.h:1144),
./tools/run_native_asym.sh:294:setsid nohup puffer train bloodbowl --tag "$TAG" \
./tools/run_native_asym.sh:318:    d=$(ls -td checkpoints/bloodbowl/*/ 2>/dev/null | head -1)
./tools/mac_practice_build.sh:3:# with the bloodbowl env statically linked. NOT for real training — that's
./tools/mac_practice_build.sh:4:# the Linux CUDA box. This exists to shake out env/binding/policy integration
./tools/mac_practice_build.sh:7:# Why not ./build.sh bloodbowl --cpu on Mac:
./tools/mac_practice_build.sh:10:#     Fix: compile WITHOUT -fopenmp (vecenv/bindings_cpu use only `#pragma omp`,
./tools/mac_practice_build.sh:12:#   * Run with: puffer train bloodbowl --slowly --selfplay.enabled 0
./tools/mac_practice_build.sh:29:echo "[1/3] binding.c (env static lib, no OpenMP)"
./tools/mac_practice_build.sh:31:    -I. -Isrc -Iocean/bloodbowl -Ivendor -Iraylib-5.5_macos/include -I"$OMP_INC" \
./tools/mac_practice_build.sh:33:    ocean/bloodbowl/binding.c -o build/libstatic_bloodbowl.o
./tools/mac_practice_build.sh:34:ar rcs build/libstatic_bloodbowl.a build/libstatic_bloodbowl.o
./tools/mac_practice_build.sh:36:echo "[2/3] bindings_cpu.cpp (torch backend, no OpenMP)"
./tools/mac_practice_build.sh:39:    -DOBS_TENSOR_T=ByteTensor -DENV_NAME=bloodbowl -DPRECISION_FLOAT -O2 \
./tools/mac_practice_build.sh:40:    src/bindings_cpu.cpp -o build/bindings_cpu.o
./tools/mac_practice_build.sh:43:$CXX -shared -fPIC build/bindings_cpu.o build/libstatic_bloodbowl.a \
./tools/mac_practice_build.sh:50:echo "  puffer train bloodbowl --slowly --selfplay.enabled 0 \\"
./tools/run_league.sh:18:# under checkpoints/bloodbowl/ whose PROFILE matches, highest-step .bin in
./tools/run_league.sh:60:grep -q '^league_preseed' config/bloodbowl.ini || {
./tools/run_league.sh:61:  echo "refreshing config/bloodbowl.ini (league_preseed key)"
./tools/run_league.sh:62:  cp "$ROOT/puffer/config/bloodbowl.ini" config/bloodbowl.ini
./tools/run_league.sh:64:grep -q '^league_preseed' config/bloodbowl.ini || {
./tools/run_league.sh:65:  echo "config/bloodbowl.ini still lacks league_preseed — pull latest repo" >&2; exit 1; }
./tools/run_league.sh:82:$PYBIN - <<'EOF' || { echo "fix: ./build.sh bloodbowl (on the CUDA box)" >&2; exit 1; }
./tools/run_league.sh:84:assert getattr(_C, 'env_name', None) == 'bloodbowl', f"_C built for {getattr(_C, 'env_name', None)}, not bloodbowl"
./tools/run_league.sh:97:  for d in $(ls -td checkpoints/bloodbowl/*/ 2>/dev/null); do
./tools/run_league.sh:114:      grep -H . checkpoints/bloodbowl/*/PROFILE >&2 2>/dev/null || echo "  (none)" >&2
./tools/run_league.sh:143:LEAGUE_DIR="$PUFFER/checkpoints/bloodbowl/league-$(date +%Y%m%d-%H%M%S)"
./tools/run_league.sh:158:    d=$(ls -td checkpoints/bloodbowl/*/ 2>/dev/null | head -1)
./tools/run_league.sh:166:exec puffer train bloodbowl --tag profile-league \
./tools/fleet.sh:16:# Conventions: ssh key ~/.ssh/id_ed25519; repo lands at /root/bloodbowl-rl;
./tools/fleet.sh:86:        --exclude .git "$ROOT/" "root@$host:/root/bloodbowl-rl/"
./tools/fleet.sh:88:        "cd /root/bloodbowl-rl && bash tools/gpu_box_setup.sh"
./tools/fleet.sh:96:        "cd /root/bloodbowl-rl/vendor/PufferLib && \
./tools/fleet.sh:97:         . /root/bloodbowl-rl/tools/cpu_cap.sh && \
./tools/fleet.sh:98:         nohup puffer train bloodbowl --tag '$tag' $* > /tmp/$tag.log 2>&1 < /dev/null & \
./tools/fleet.sh:102:         d=\$(ls -td checkpoints/bloodbowl/*/ 2>/dev/null | head -1); \
./tools/fleet.sh:134:        "root@$host:/root/bloodbowl-rl/vendor/PufferLib/checkpoints/bloodbowl/" \
./tools/parity_report.py:62:output) and 120 (tmux capture). Metric names are the binding.c my_log keys as
./tools/bb_lockstep.c:21:// (bloodbowl.h #includes every engine .c): the runner links no objects and
./tools/bb_lockstep.c:24:#include "bloodbowl.h"
./tools/bb_lockstep.c:244:// The targets are the binding's OWN head projections of the applied

exec
/bin/zsh -lc 'make test' in /Users/alexanderhuth/Code/bloodbowl-rl
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 4819137323d1ece180f5c27b7ae1114d9ad9d81f..a37c95440728c41e5efb206931426ea4a6d75691
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -116,7 +116,9 @@
         int who = base + pg_pick(rng, n);
         bb_player* p = &m->players[who];
         const bb_position_def* pd = &td->positions[p->position_id];
-        if (!(pd->primary_mask || pd->secondary_mask)) continue;
+        uint8_t access = pd->primary_mask;
+        if (pp->skillup_secondary_pct > 0.0f) access |= pd->secondary_mask;
+        if (!access) continue;
         int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
         for (int g = 0; g < gains; g++) {
             if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 99774f8dfb71f3f99dfd14ddaa48a8432093ee30..bcf304109b9ca2b04bcd6a13f0b300f85a1c5fa5
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -278,16 +278,122 @@
     }
 }
 
+static int procgen_find_secondary_only_teams(int* out, int cap) {
+    int n = 0;
+    for (int t = 0; t < BB_TEAM_COUNT; t++) {
+        const bb_team_def* td = &bb_team_defs[t];
+        int has_secondary_only = 0;
+        for (int pi = 0; pi < td->num_positions; pi++) {
+            const bb_position_def* pd = &td->positions[pi];
+            if (pd->primary_mask == 0 && pd->secondary_mask != 0) {
+                has_secondary_only = 1;
+                break;
+            }
+        }
+        if (has_secondary_only && n < cap) out[n++] = t;
+    }
+    return n;
+}
+
+static int procgen_check_secondary_only_grants(const bb_match* m) {
+    int seen = 0;
+    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+        const bb_player* p = &m->players[s];
+        if (p->location == BB_LOC_ABSENT) continue;
+        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
+        const bb_position_def* pd = &td->positions[p->position_id];
+        if (pd->primary_mask != 0) continue;
+        bb_skillset base = base_position_skills(pd);
+        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
+             sk = bb_next_skill(&p->skills, sk + 1)) {
+            if (bb_has_skill(&base, sk)) continue;
+            uint8_t cat = bb_skill_defs[sk].category;
+            BB_CHECK(cat < BB_CAT_COUNT);
+            BB_CHECK(pd->secondary_mask & (1 << cat));
+            if (!(pd->secondary_mask & (1 << cat))) {
+                printf("  team %d pos %d skill %d cat %d secondary 0x%x\n",
+                       m->team_id[BB_TEAM_OF(s)], p->position_id, sk, cat,
+                       pd->secondary_mask);
+                return seen;
+            }
+            seen = 1;
+        }
+    }
+    return seen;
+}
+
 BB_TEST(match_procgen_default_params_match_legacy_api) {
     bb_procgen_params pp = bb_procgen_params_default();
-    bb_match a, b;
-    bb_rng r1, r2;
-    bb_rng_seed(&r1, 0x515A5EEDu, 17);
-    bb_rng_seed(&r2, 0x515A5EEDu, 17);
-    bb_match_init_random(&a, &r1);
-    bb_match_init_random_p(&b, &r2, &pp);
-    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
-    BB_CHECK(procgen_rng_same_state(&r1, &r2));
+    for (uint64_t seed = 1; seed <= 300; seed++) {
+        bb_match a, b;
+        bb_rng r1, r2;
+        bb_rng_seed(&r1, seed * 0x515A5EEDu, 17 + seed);
+        bb_rng_seed(&r2, seed * 0x515A5EEDu, 17 + seed);
+        bb_match_init_random(&a, &r1);
+        bb_match_init_random_p(&b, &r2, &pp);
+        BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
+        BB_CHECK(procgen_rng_same_state(&r1, &r2));
+        if (memcmp(&a, &b, sizeof(bb_match)) != 0 ||
+            !procgen_rng_same_state(&r1, &r2)) {
+            printf("  seed %llu failed\n", (unsigned long long)seed);
+            break;
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_inert_at_defaults) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = bb_procgen_params_default();
+    for (uint64_t seed = 1; seed <= 100; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 2654435761u, 53 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+            const bb_player* p = &m.players[s];
+            if (p->location == BB_LOC_ABSENT) continue;
+            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
+            const bb_position_def* pd = &td->positions[p->position_id];
+            if (pd->primary_mask != 0) continue;
+            bb_skillset base = base_position_skills(pd);
+            BB_CHECK_EQ(memcmp(&p->skills, &base, sizeof(bb_skillset)), 0);
+            if (memcmp(&p->skills, &base, sizeof(bb_skillset)) != 0) {
+                printf("  seed %llu team %d pos %d gained at defaults\n",
+                       (unsigned long long)seed, m.team_id[BB_TEAM_OF(s)],
+                       p->position_id);
+                return;
+            }
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_advance_with_pct) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = {11, 3, 0.5f};
+    int seen = 0;
+    for (uint64_t seed = 1; seed <= 2000 && !seen; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 11400714819323198485ull, 59 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        seen = procgen_check_secondary_only_grants(&m);
+    }
+    BB_CHECK(seen);
+    if (!seen) printf("  no secondary-only position advanced within 2000 seeds\n");
 }
 
 BB_TEST(match_procgen_skillups_off_keeps_base_skills) {

 succeeded in 2184ms:
./build/bb_tests 
ok   blockev_addendum3_turnover_inversion
ok   blockev_1d_no_skills
ok   blockev_2d_chooser_dominance
ok   blockev_def_chooses_minimizes
ok   blockev_dodge_vs_tackle
ok   blockev_strip_ball_prices_pushes
ok   blockev_wrestle_d29_decline_judgment
ok   blockev_armour_break_av9
ok   blockev_removal_av9
ok   blockev_thick_skull_band
ok   blockev_frenzy_compounds
ok   blockev_assists_shift_pool
ok   blockev_mb_claws_leaves_mb_for_injury
ok   blockev_sure_hands_blocks_strip_ball
ok   blockev_juggernaut_blitz_cancels_stand_firm_strip
ok   blockev_brawler_rerolls_lone_both_down
ok   blockev_fend_cancels_frenzy_second_block
ok   casualty_hook_block_kill_attribution
ok   gen_skill_counts
ok   gen_elite_skills_are_exactly_four
ok   gen_team_count_and_human_roster
ok   gen_all_teams_well_formed
ok   gen_casualty_table_bb2025
ok   gen_injury_bands
ok   gen_weather_table
ok   gen_random_skill_table_resolves
ok   golden_traces_resimulate_exactly
ok   match_random_game_completes
ok   match_many_seeds_complete
ok   match_deterministic_replay
ok   apply_trusted_matches_checked_apply
ok   apply_trusted_guards_non_decision
ok   match_init_well_formed
ok   match_procgen_skill_cap
ok   match_procgen_default_params_match_legacy_api
ok   match_procgen_secondary_only_positions_inert_at_defaults
ok   match_procgen_secondary_only_positions_advance_with_pct
ok   match_procgen_skillups_off_keeps_base_skills
ok   match_procgen_primary_only_uses_primary_categories
ok   match_procgen_secondary_only_uses_secondary_or_primary_fallback
ok   match_procgen_skillups_reach_full_learnable_catalogue
ok   match_procgen_cranked_params_respect_cap_and_structure
ok   match_procgen_params_are_deterministic
ok   match_procgen_games_complete
ok   fixtures_player_at_origin_survives_later_placements
ok   match_init_rejects_out_of_range_team_ids
ok   aura_mask_matches_registered_aura_hooks
ok   match_procgen_keeps_roster_skill_values
ok   match_procgen_pregame_injuries_without_replacement
ok   match_procgen_forced_and_excluded
ok   replay_roundtrip
ok   replay_action_pack_roundtrip
ok   replay_parse_error_on_garbage
ok   replay_dice_sink_integration
ok   replay_init_rejects_out_of_range_team_ids
ok   replay_truncated_final_line_no_oob
ok   replay_rejects_overflowing_and_out_of_band_numbers
ok   rng_deterministic_same_seed
ok   rng_streams_differ
ok   rng_range_and_uniformity
ok   rng_script_mode_replays_exact_values
ok   rng_script_exhaustion_is_sticky_error
ok   rng_script_out_of_range_is_error
ok   rng_sink_observes_every_roll
ok   ball_pass_move_then_quick_accurate_caught
ok   ball_pass_quick_short_boundary
ok   ball_pass_long_and_bomb_band_modifiers
ok   ball_pass_max_range_legality
ok   ball_pass_natural_six_accurate
ok   ball_pass_fumble_bounces_from_thrower
ok   ball_pass_fumble_turnover_even_if_teammate_catches
ok   ball_pass_marked_thrower_modifier
ok   ball_pass_accurate_to_empty_square_bounces
ok   ball_pass_inaccurate_to_empty_square_bounces
ok   ball_pass_rain_does_not_modify_pa_test
ok   ball_pass_rain_catch_minus_one
ok   ball_pass_very_sunny_minus_one
ok   ball_pass_blizzard_quick_short_only
ok   ball_pass_interception_accurate_minus_three
ok   ball_pass_caught_by_opponent_is_turnover
ok   ball_catch_marking_modifier_and_natural_one
ok   ball_catch_bounced_minus_one
ok   ball_catch_scattered_inaccurate_pass_unmodified
ok   ball_catch_distracted_auto_fails
ok   ball_bounce_onto_prone_player_bounces_again
ok   ball_catch_fail_bounce_to_teammate_no_turnover
ok   ball_handoff_unmodified_catch_once_per_turn
ok   ball_handoff_target_legality
ok   ball_handoff_distracted_receiver_illegal
ok   ball_handoff_failed_catch_rest_turnover
ok   ball_handoff_catch_pro_not_offered_outside_own_activation
ok   ball_declare_pass_handoff_without_possession
ok   ball_pickup_success_continues_activation
ok   ball_pickup_modifiers_and_failure_turnover
ok   ball_pushed_onto_loose_ball_bounces_no_turnover
ok   ball_carrier_falls_over_ball_bounces_turnover
ok   ball_carrier_powed_in_opponents_turn_no_turnover
ok   ball_throw_in_distance_counts_boundary_square
ok   ball_throw_in_lands_on_player_direct_catch
ok   ball_corner_throw_in_inward_directions
ok   ball_secure_the_ball_declarable
ok   ball_interception_options_are_candidate_indices
ok   blocking_basics_equal_st_one_die
ok   blocking_higher_st_two_dice_attacker_chooses
ok   blocking_exactly_double_st_two_dice
ok   blocking_over_double_st_three_dice
ok   blocking_defender_stronger_chooses_skull_turnover
ok   blocking_offensive_assist_grants_second_die
ok   blocking_marked_assister_needs_guard
ok   blocking_defensive_assist_defender_chooses
ok   blocking_prone_players_neither_assist_nor_deny
ok   blocking_distracted_player_cannot_assist
ok   blocking_both_down_plain_defender_resolves_first
ok   blocking_both_down_attacker_block_stays_up
ok   blocking_both_down_defender_block_only
ok   blocking_both_down_both_block_nothing_happens
ok   blocking_both_down_wrestle_defender_window_use_places_both_prone
ok   blocking_both_down_wrestle_defender_declines_forces_turnover
ok   blocking_both_down_wrestle_attacker_window_then_defender
ok   blocking_both_down_wrestle_distracted_defender_no_window
ok   blocking_both_down_wrestle_active_carrier_turnover
ok   blocking_stand_firm_window_use_not_moved
ok   blocking_stand_firm_window_decline_normal_push
ok   blocking_stand_firm_pow_use_knockdown_in_place
ok   blocking_stand_firm_juggernaut_blitz_no_window
ok   blocking_stand_firm_distracted_no_window
ok   blocking_stand_firm_chain_occupant_absorbs_push
ok   blocking_stumble_dodge_becomes_push_carrier_keeps_ball
ok   blocking_stumble_tackle_cancels_dodge
ok   blocking_stumble_without_dodge_is_pow
ok   blocking_pow_mighty_blow_converts_armour
ok   blocking_pow_claws_breaks_high_av
ok   blocking_distracted_defender_active_skills_disabled
ok   blocking_push_candidate_squares
ok   blocking_push_must_choose_unoccupied
ok   blocking_side_step_defender_picks_any_free_square
ok   blocking_side_step_unusable_without_free_square
ok   blocking_chain_push_prone_not_knocked_down
ok   blocking_crowd_push_injury_no_armour
ok   blocking_crowd_push_carrier_ball_thrown_in
ok   blocking_crowd_push_noncarrier_keeps_unrelated_carrier_ball
ok   blocking_active_team_chain_pushed_into_crowd_turnover
ok   blocking_push_onto_ball_bounces
ok   blocking_follow_up_choice
ok   blocking_follow_up_decided_before_armour
ok   blocking_push_carrier_into_endzone_scores
ok   blocking_blitz_block_costs_ma_and_once_per_turn
ok   blocking_blitz_may_rush_for_the_block
ok   blocking_frenzy_second_block_after_push
ok   blocking_frenzy_blitz_second_block_costs_movement
ok   blocking_frenzy_blitz_second_block_rush_pass
ok   blocking_frenzy_blitz_second_block_rush_fail
ok   blocking_frenzy_blitz_second_block_cannot_rush
ok   blocking_team_reroll_rerolls_whole_pool
ok   blocking_second_team_reroll_in_same_turn_allowed
ok   blocking_loner_gates_team_reroll
ok   blocking_defensive_cancels_offensive_guard_assist
ok   blocking_defensive_no_cancel_on_own_turn_guard_assist
ok   rules_armour_2d6_below_av_holds
ok   rules_armour_2d6_at_av_breaks
ok   rules_injury_2_to_7_stunned
ok   rules_injury_8_to_9_knocked_out
ok   rules_injury_10_to_12_casualty
ok   rules_casualty_d16_always_out_for_match
ok   rules_stunty_bands_stun_6_ko_7_8
ok   rules_stunty_9_badly_hurt_no_casualty_roll
ok   rules_stunty_10_casualty_rolls_d16
ok   rules_thick_skull_injury_8_is_stunned
ok   rules_thick_skull_injury_9_is_always_ko
ok   rules_stunty_thick_skull_injury_7_is_stunned
ok   rules_crowd_injury_stunned_goes_to_reserves
ok   rules_crowd_injury_ko_goes_to_ko_box
ok   rules_crowd_injury_casualty
ok   rules_carrier_knockdown_armour_injury_then_bounce
ok   rules_active_carrier_falls_over_bounce_and_turnover
ok   rules_stunned_flips_prone_at_end_of_own_team_turn
ok   rules_stunned_during_own_turn_does_not_flip_same_turn
ok   rules_ko_recovery_4plus_at_end_of_drive
ok   rules_foul_armour_holds_no_injury_no_sendoff
ok   rules_foul_breaks_armour_injury_resolves
ok   rules_foul_offensive_assist_plus1
ok   rules_foul_defensive_assist_minus1
ok   rules_foul_natural_double_on_unbroken_armour_sends_off
ok   rules_foul_double_breaks_armour_injury_still_resolves
ok   rules_foul_natural_double_on_injury_sends_off
ok   rules_foul_once_per_team_turn
ok   rules_foul_target_must_be_prone_or_stunned
ok   rules_foul_ends_activation_no_more_movement
ok   rules_foul_sendoff_offers_argue_the_call
ok   rules_apothecary_casualty_pick_original_result
ok   rules_apothecary_casualty_pick_new_badly_hurt_reserves
ok   rules_apothecary_casualty_worse_pick_is_legal
ok   rules_apothecary_casualty_decline_keeps_apothecary
ok   movement_ma_budget_no_dice
ok   movement_zero_squares_voluntary_end
ok   movement_occupied_square_illegal_ball_square_legal
ok   movement_cannot_step_off_pitch
ok   movement_rush_two_per_activation_2plus
ok   movement_rush_natural_one_falls_in_destination
ok   movement_rush_fail_ball_carrier_bounce
ok   movement_rush_blizzard_minus1
ok   movement_dodge_only_when_leaving_marked_square
ok   movement_no_dodge_leaving_downed_opponents
ok   movement_dodge_origin_markers_no_modifier
ok   movement_dodge_destination_marker_minus1
ok   movement_dodge_fail_falls_in_destination
ok   movement_dodge_natural_six_always_succeeds
ok   movement_dodge_marked_destination_fail
ok   movement_dodge_each_marked_square
ok   movement_rush_roll_before_dodge_roll
ok   movement_rush_fail_skips_dodge_roll
ok   movement_prone_stand_first_costs_three
ok   movement_standup_ma2_roll_4plus
ok   movement_standup_ma2_fail_no_turnover
ok   movement_standup_ma3_no_roll_then_rush
ok   movement_pickup_on_entering_ball_square
ok   movement_pickup_marked_minus1
ok   movement_pickup_fail_bounce_turnover
ok   movement_pickup_after_rush_roll
ok   movement_pickup_rain_minus1
ok   movement_team_reroll_on_failed_dodge
ok   movement_decline_reroll_falls
ok   movement_team_rerolls_not_limited_per_turn
ok   movement_loner_gate_fail_wastes_reroll
ok   movement_loner_gate_pass
ok   movement_dodge_skill_self_reroll
ok   movement_pro_reroll_sole_source
ok   movement_pro_reroll_gate_fail_result_stands
ok   movement_pro_reroll_once_per_activation
ok   movement_dodge_skill_once_per_turn
ok   movement_sure_feet_reroll
ok   movement_sprint_third_rush
ok   movement_distracted_opponent_not_marking
ok   gate_bone_head_fail_distracted_ends_activation
ok   gate_rolls_after_declaration_burns_blitz
ok   gate_really_stupid_helper_gives_plus2
ok   gate_really_stupid_rs_helper_does_not_count
ok   gate_unchannelled_fury_block_gets_plus2
ok   gate_unchannelled_fury_move_no_bonus_fails
ok   gate_failure_offers_team_reroll_window
ok   gate_reroll_declined_failure_stands
ok   gate_reroll_loner_waste
ok   gate_take_root_prone_no_roll
ok   gate_take_root_fail_rooted_continues_in_place
ok   struct_setup_kicking_team_sets_up_first
ok   struct_setup_done_requires_three_on_los_centre
ok   struct_setup_max_two_per_wide_zone
ok   struct_setup_max_eleven_no_twelfth_placement
ok   struct_setup_own_half_only
ok   struct_setup_short_squad_fields_all_available
ok   struct_setup_three_or_fewer_all_on_los
ok   struct_pregame_toss_winner_chooses_kick_or_receive
ok   struct_kick_target_only_receiving_half
ok   struct_kick_deviates_then_bounces_then_receiver_plays_first
ok   struct_kick_landing_on_receiver_is_caught
ok   struct_kickoff_catch_no_team_reroll_window
ok   struct_kickoff_catch_skill_reroll_still_offered
ok   struct_kick_touchback_when_ball_exits_pitch
ok   struct_kick_touchback_when_ball_lands_in_kicking_half
ok   struct_kick_touchback_after_bounce_across_los
ok   struct_kick_touchback_no_standing_receivers_places_ball
ok   struct_kickoff_event_time_out
ok   struct_kickoff_event_brilliant_coaching
ok   struct_kickoff_event_high_kick_offers_placement
ok   struct_kickoff_event_changing_weather_scatters_three
ok   struct_kickoff_changing_weather_gust_stops_at_touchback
ok   struct_kickoff_event_pitch_invasion_rolloff
ok   struct_kickoff_event_pitch_invasion_fan_factor
ok   struct_turnover_failed_dodge
ok   struct_turnover_failed_rush
ok   struct_turnover_failed_pickup
ok   struct_turnover_block_attacker_down
ok   struct_turnover_block_both_down
ok   struct_no_turnover_block_pow_defender_down
ok   struct_no_turnover_block_push_back
ok   struct_turnover_foul_sent_off
ok   struct_no_turnover_foul_unspotted
ok   struct_turnover_pass_incomplete
ok   struct_turnover_pass_caught_by_opponent
ok   struct_no_turnover_pass_caught_by_teammate
ok   struct_turnover_handoff_dropped
ok   struct_no_turnover_bounce_caught_by_teammate
ok   struct_no_turnover_inactive_carrier_knocked_down
ok   struct_turnover_active_carrier_chain_pushed_into_crowd
ok   struct_one_blitz_per_team_turn
ok   struct_blitz_declaration_counts_even_if_not_performed
ok   struct_one_pass_per_team_turn
ok   struct_one_handoff_per_team_turn
ok   struct_one_foul_per_team_turn
ok   struct_players_activate_once_end_turn_available
ok   struct_end_turn_passes_play_and_increments_marker
ok   struct_stunned_cannot_activate_and_flips_at_own_turn_end
ok   struct_stunned_during_own_turn_not_flipped_early
ok   struct_multiple_team_rerolls_in_one_turn
ok   struct_touchdown_move_into_end_zone
ok   struct_touchdown_pickup_in_end_zone
ok   struct_no_touchdown_for_prone_carrier_in_end_zone
ok   struct_touchdown_by_push_during_opponent_turn
ok   struct_opponent_turn_scorer_skips_next_turn
ok   struct_second_half_kicker_is_first_half_receiver
ok   struct_match_over_after_two_halves
ok   struct_each_team_gets_eight_turns_per_half
ok   struct_ko_recovery_between_drives
ok   struct_team_rerolls_replenish_at_half_time
ok   struct_leader_reroll_survives_mid_half_drive_end
ok   struct_brilliant_coaching_reroll_expires_at_drive_end
ok   struct_bonus_reroll_spent_before_leader
ok   struct_sent_off_offers_argue_the_call
ok   struct_cheering_fans_assist_expires_at_turn_end
ok   struct_cheering_fans_assist_expires_at_drive_end
ok   structure_setup_reserves_first_discipline
ok   struct_pick_me_up_5plus_stands_prone_teammate
ok   struct_pick_me_up_4_fails_stays_prone
ok   struct_pick_me_up_rolls_for_just_rolled_over_stunned
ok   struct_pick_me_up_stood_owner_cannot_help_same_turn
ok   struct_kickoff_solid_defence_reposition_window
ok   struct_kickoff_solid_defence_marked_player_ineligible
ok   struct_kickoff_quick_snap_one_square_each_any_direction
ok   struct_kickoff_quick_snap_player_budget
ok   struct_kickoff_charge_move_and_single_blitz
ok   struct_kickoff_charge_ends_when_player_falls
ok   struct_kickoff_charge_team_reroll_available
ok   skdt_titchy_dodge_plus1
ok   skdt_titchy_aura_cancels_own_destination_minus1
ok   skdt_titchy_prone_no_aura
ok   skdt_stunty_dodger_titchy_marker_no_double_cancel
ok   skdt_drunkard_rush_mod_registered
ok   skdt_insignificant_no_match_time_effect
ok   skdt_animal_savagery_lashout_resolves_before_action
ok   skdt_knockdown_offpitch_is_noop
ok   skdt_ttm_pick_locks_movement_and_throws_picked_mate
ok   skdt_distracted_clears_on_next_activation_gateless
ok   skdt_stab_blitz_rush_pays_for_stab
ok   skdt_stab_blitz_failed_rush_knocks_down_no_stab
ok   skmp_prehensile_tail_dodge_minus_one
ok   skmp_prehensile_tail_only_one_applies
ok   skmp_prehensile_tail_inapplicable_squares
ok   skmp_very_long_legs_intercept_plus_two
ok   skmp_catch_skill_no_reroll_on_interception
ok   skmp_catch_skill_reroll_on_regular_catch
ok   skmp_nerves_of_steel_no_effect_on_interception
ok   skmp_nerves_of_steel_still_ignores_markers_on_catch
ok   skmp_very_long_legs_no_bonus_on_regular_catch
ok   skmp_big_hand_ignores_rain_and_markers_on_pickup
ok   skmp_rain_pickup_minus1_without_big_hand
ok   skmp_big_hand_rain_pickup_after_jump
ok   skmp_disturbing_presence_applies_to_ttm
347 tests, 0 failures

exec
/bin/zsh -lc "sed -n '1,120p' docs/homebrew-team-authoring.md" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
# Authoring a homebrew team (the generalization holdout)

The pipeline: add your team to the spec YAML → codegen → rebuild → the eval
binary can pit any trained checkpoint against it via `force_*_team`, with the
policy having never seen the roster. The obs carries no team ids, so the
policy must read your roster the same way it reads every other one: from the
visible per-player stats and skills.

## Where it goes

Append to `engine/data/spec/teams_b.yaml` under `teams:` (APPEND ONLY — team
ids are positional and stable; inserting mid-list breaks replays/goldens).
Your team becomes id 30 (current count: 30, ids 0-29).

## Schema (per team)

```yaml
  - name: alexs_marauders          # snake_case identifier
    display: "Alex's Marauders"    # what the spectator HUD shows
    tier: 1                        # 1-3, informational
    reroll_cost: 60                # k-gold; affects procgen nothing today
    apothecary: true
    special_rules: []              # informational today
    positions:
      - name: marauder_lineman     # FIRST position = the lineman top-up
        display: "Marauder Lineman"
        qty: [0, 16]               # min, max on the roster
        cost: 50                   # k-gold — feeds value-scaled rewards
        ma: 6
        st: 3
        ag: 3                      # TARGET number (3 means "3+")
        pa: 4                      # 0 means "-" (no passing)
        av: 9
        skills: []                 # names from skills_*.yaml, exact match
        primary: [general]         # advancement categories (procgen uses)
        secondary: [strength]
        big_guy: false
      - name: marauder_basher
        display: "Marauder Basher"
        qty: [0, 4]
        cost: 90
        ma: 5
        st: 4
        ag: 4
        pa: 5
        av: 10
        skills: [mighty_blow]      # values: "skill: X" form for Loner (X+) etc.
        primary: [general, strength]
        secondary: [agility]
        big_guy: false
```

Constraints the codegen enforces / assumes:
- Skill names must exist in `engine/data/spec/skills_*.yaml` (codegen fails
  loudly on unknown names — that's your spellcheck).
- Max 10 base skills per position (obs has 12 slots; procgen adds up to 2).
- Stats are BB2025-style target numbers (ag/pa/av) and raw values (ma/st).
- Use EXISTING skills only: a brand-new ability is untrained vocabulary —
  the policy can only generalize over skills it has experienced (see
  docs/reward-audit-decision-time.md discussion). New stat lines and new
  COMBINATIONS are exactly what the experiment tests.

## Build + validate

```bash
vendor/PufferLib/.venv/bin/python tools/codegen.py   # regenerates gen_teams.*
make test                                            # 277+ tests incl. procgen sweeps
clang -std=c11 -O2 -Ipuffer/bloodbowl puffer/bloodbowl/bloodbowl.c -o /tmp/bbe \
  && /tmp/bbe --selftest                             # binding-level checks
```

The procgen completion tests (`match_procgen_games_complete`) will exercise
your team automatically once it's in the table.

## Evaluate against a trained checkpoint

```bash
# Your team (id 30) as home, random opponents, trained policy plays both:
puffer eval bloodbowl --slowly --selfplay.enabled 0 \
  --load-model-path latest \
  --vec.total-agents 2 --vec.num-buffers 1 --vec.num-threads 1 \
  --train.minibatch-size 2 --env.force-home-team 30
```

The spectator window shows it live (your positions render as FUMBBL fallback
disks unless you map icons in tools/stage_spectator_art.py ALIASES).

## Honest-test checklist

- [ ] Trained run used `exclude_team = -1` (your team didn't exist) or
      explicitly excluded it
- [ ] No team-id bytes in obs (default since 2026-06-03)
- [ ] Compare: win rate vs random-policy and vs same-tier trained teams;
      qualitative spectator review ("does it lean on the team's strengths?")

exec
/bin/zsh -lc "sed -n '1,90p' tools/mac_practice_build.sh" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
#!/usr/bin/env bash
# Mac (Apple Silicon) practice-run build of the PufferLib torch-CPU backend
# with the bloodbowl env statically linked. NOT for real training — that's
# the Linux CUDA box. This exists to shake out env/binding/policy integration
# locally before paying for GPU time.
#
# Why not ./build.sh bloodbowl --cpu on Mac:
#   * torch ships its own libomp; linking homebrew's into _C.so makes two
#     OpenMP runtimes in-process -> segfault in __kmp_suspend_initialize_thread.
#     Fix: compile WITHOUT -fopenmp (vecenv/bindings_cpu use only `#pragma omp`,
#     no omp_* API, so pragmas degrade to single-threaded loops).
#   * Run with: puffer train bloodbowl --slowly --selfplay.enabled 0
#     (selfplay pool + action masks are CUDA-backend only; the env's
#     decode-snap-to-legal keeps maskless sampling legal.)
set -euo pipefail

cd "$(dirname "$0")/../vendor/PufferLib"
source .venv/bin/activate

tools_dir="$(cd .. && pwd)"
CC=/opt/homebrew/opt/llvm/bin/clang
CXX=/opt/homebrew/opt/llvm/bin/clang++
OMP_INC=/opt/homebrew/opt/libomp/include   # for #include <omp.h> only; no lib linked
PYTHON_INCLUDE=$(python -c "import sysconfig; print(sysconfig.get_path('include'))")
PYBIND_INCLUDE=$(python -c "import pybind11; print(pybind11.get_include())")
EXT_SUFFIX=$(python -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))")

mkdir -p build
echo "[1/3] binding.c (env static lib, no OpenMP)"
$CC -c -O2 -DNDEBUG -Wall \
    -I. -Isrc -Iocean/bloodbowl -Ivendor -Iraylib-5.5_macos/include -I"$OMP_INC" \
    -DPLATFORM_DESKTOP -fvisibility=hidden -fPIC \
    ocean/bloodbowl/binding.c -o build/libstatic_bloodbowl.o
ar rcs build/libstatic_bloodbowl.a build/libstatic_bloodbowl.o

echo "[2/3] bindings_cpu.cpp (torch backend, no OpenMP)"
$CXX -c -fPIC -D_GLIBCXX_USE_CXX11_ABI=1 -DPLATFORM_DESKTOP -std=c++17 \
    -I. -Isrc -I"$PYTHON_INCLUDE" -I"$PYBIND_INCLUDE" -I"$OMP_INC" \
    -DOBS_TENSOR_T=ByteTensor -DENV_NAME=bloodbowl -DPRECISION_FLOAT -O2 \
    src/bindings_cpu.cpp -o build/bindings_cpu.o

echo "[3/3] link pufferlib/_C${EXT_SUFFIX}"
$CXX -shared -fPIC build/bindings_cpu.o build/libstatic_bloodbowl.a \
    raylib-5.5_macos/lib/libraylib.a -lm -lpthread -O2 \
    -framework Cocoa -framework OpenGL -framework IOKit -undefined dynamic_lookup \
    -o "pufferlib/_C${EXT_SUFFIX}"

echo "ok. practice run:"
echo "  cd vendor/PufferLib && source .venv/bin/activate"
echo "  puffer train bloodbowl --slowly --selfplay.enabled 0 \\"
echo "      --train.total-timesteps 100000 --vec.total-agents 128 --train.minibatch-size 2048"

exec
/bin/zsh -lc 'ls -la puffer/bloodbowl vendor/PufferLib 2>/dev/null' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
puffer/bloodbowl:
total 392
drwxr-xr-x@ 10 alexanderhuth  staff    320 Jun 10 00:48 .
drwxr-xr-x@  4 alexanderhuth  staff    128 Jun  3 07:24 ..
lrwxr-xr-x@  1 alexanderhuth  staff     23 Jun  4 17:57 bb -> ../../engine/include/bb
-rw-r--r--@  1 alexanderhuth  staff   4133 Jun  4 19:23 bbe_microstats_probe.c
-rw-r--r--@  1 alexanderhuth  staff   9055 Jun  4 17:53 bbe_profile.c
-rw-r--r--@  1 alexanderhuth  staff  29301 Jun  6 18:06 bbe_render.h
-rw-r--r--@  1 alexanderhuth  staff  12486 Jun 11 14:40 binding.c
-rw-r--r--@  1 alexanderhuth  staff  24833 Jun  8 13:40 bloodbowl.c
-rw-r--r--@  1 alexanderhuth  staff  99238 Jun 11 14:39 bloodbowl.h
lrwxr-xr-x@  1 alexanderhuth  staff     16 Jun  3 07:20 engine -> ../../engine/src

vendor/PufferLib:
total 64
drwxr-xr-x@ 26 alexanderhuth  staff    832 Jun  3 07:27 .
drwxr-xr-x@  9 alexanderhuth  staff    288 Jun  2 21:57 ..
drwxr-xr-x@ 13 alexanderhuth  staff    416 Jun  6 18:42 .git
drwxr-xr-x@  3 alexanderhuth  staff     96 Jun  2 21:55 .github
-rw-r--r--@  1 alexanderhuth  staff   2426 Jun  2 21:55 .gitignore
drwxr-xr-x@  9 alexanderhuth  staff    288 Jun  3 07:26 .venv
-rw-r--r--@  1 alexanderhuth  staff   1065 Jun  2 21:55 LICENSE
-rw-r--r--@  1 alexanderhuth  staff   1493 Jun  2 21:55 README.md
drwxr-xr-x@  5 alexanderhuth  staff    160 Jun  6 18:06 build
-rwxr-xr-x@  1 alexanderhuth  staff  12228 Jun  3 07:26 build.sh
drwxr-xr-x@  3 alexanderhuth  staff     96 Jun  3 07:27 checkpoints
drwxr-xr-x@ 67 alexanderhuth  staff   2144 Jun  4 19:53 config
drwxr-xr-x@  4 alexanderhuth  staff    128 Jun  2 21:55 constellation
drwxr-xr-x@ 10 alexanderhuth  staff    320 Jun  2 21:55 examples
drwxr-xr-x@  3 alexanderhuth  staff     96 Jun  3 07:27 logs
drwxr-xr-x@ 63 alexanderhuth  staff   2016 Jun  6 18:06 ocean
-rw-r--r--@  1 alexanderhuth  staff   1645 Jun  2 21:55 profile.sh
drwxr-xr-x@ 11 alexanderhuth  staff    352 Jun  6 18:06 pufferlib
drwxr-xr-x@  8 alexanderhuth  staff    256 Jun  3 07:26 pufferlib.egg-info
-rw-r--r--@  1 alexanderhuth  staff   1036 Jun  2 21:55 pyproject.toml
drwxr-xr-x@  7 alexanderhuth  staff    224 Nov 18  2024 raylib-5.5_macos
drwxr-xr-x@ 41 alexanderhuth  staff   1312 Jun  3 10:44 resources
drwxr-xr-x@ 14 alexanderhuth  staff    448 Jun  4 18:34 src
drwxr-xr-x@ 22 alexanderhuth  staff    704 Jun  2 21:55 tests
drwxr-xr-x@  3 alexanderhuth  staff     96 Jun  2 21:55 trailer
drwxr-xr-x@ 12 alexanderhuth  staff    384 Jun  2 21:55 vendor

exec
/bin/zsh -lc 'rg -n "int main|selftest" puffer/bloodbowl vendor/PufferLib/ocean/bloodbowl 2>/dev/null' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
puffer/bloodbowl/bbe_profile.c:57:int main(int argc, char** argv) {
puffer/bloodbowl/bloodbowl.c:24:// --- Self-test (--selftest) --------------------------------------------------
puffer/bloodbowl/bloodbowl.c:206:static int bbe_selftest(uint64_t seed, int episodes) {
puffer/bloodbowl/bloodbowl.c:332:    printf("bloodbowl selftest: %d episodes, %d failure(s), v4 planes B=%ld A=%ld\n",
puffer/bloodbowl/bloodbowl.c:377:int main(int argc, char** argv) {
puffer/bloodbowl/bloodbowl.c:380:    int selftest = 0;
puffer/bloodbowl/bloodbowl.c:387:        else if (strcmp(argv[i], "--selftest") == 0) selftest = 1;
puffer/bloodbowl/bloodbowl.c:397:    if (selftest) return bbe_selftest(seed, episodes);
puffer/bloodbowl/bbe_microstats_probe.c:25:int main(int argc, char** argv) {
vendor/PufferLib/ocean/bloodbowl/engine/proc_block.c:469:    int main_dir = 0;
vendor/PufferLib/ocean/bloodbowl/bbe_microstats_probe.c:25:int main(int argc, char** argv) {
vendor/PufferLib/ocean/bloodbowl/bloodbowl.c:24:// --- Self-test (--selftest) --------------------------------------------------
vendor/PufferLib/ocean/bloodbowl/bloodbowl.c:168:static int bbe_selftest(uint64_t seed, int episodes) {
vendor/PufferLib/ocean/bloodbowl/bloodbowl.c:291:    printf("bloodbowl selftest: %d episodes, %d failure(s)\n", done, st_failures);
vendor/PufferLib/ocean/bloodbowl/bloodbowl.c:335:int main(int argc, char** argv) {
vendor/PufferLib/ocean/bloodbowl/bloodbowl.c:338:    int selftest = 0;
vendor/PufferLib/ocean/bloodbowl/bloodbowl.c:343:        else if (strcmp(argv[i], "--selftest") == 0) selftest = 1;
vendor/PufferLib/ocean/bloodbowl/bloodbowl.c:353:    if (selftest) return bbe_selftest(seed, episodes);
vendor/PufferLib/ocean/bloodbowl/bbe_profile.c:57:int main(int argc, char** argv) {

diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 4819137323d1ece180f5c27b7ae1114d9ad9d81f..a37c95440728c41e5efb206931426ea4a6d75691
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -116,7 +116,9 @@
         int who = base + pg_pick(rng, n);
         bb_player* p = &m->players[who];
         const bb_position_def* pd = &td->positions[p->position_id];
-        if (!(pd->primary_mask || pd->secondary_mask)) continue;
+        uint8_t access = pd->primary_mask;
+        if (pp->skillup_secondary_pct > 0.0f) access |= pd->secondary_mask;
+        if (!access) continue;
         int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
         for (int g = 0; g < gains; g++) {
             if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 99774f8dfb71f3f99dfd14ddaa48a8432093ee30..bcf304109b9ca2b04bcd6a13f0b300f85a1c5fa5
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -278,16 +278,122 @@
     }
 }
 
+static int procgen_find_secondary_only_teams(int* out, int cap) {
+    int n = 0;
+    for (int t = 0; t < BB_TEAM_COUNT; t++) {
+        const bb_team_def* td = &bb_team_defs[t];
+        int has_secondary_only = 0;
+        for (int pi = 0; pi < td->num_positions; pi++) {
+            const bb_position_def* pd = &td->positions[pi];
+            if (pd->primary_mask == 0 && pd->secondary_mask != 0) {
+                has_secondary_only = 1;
+                break;
+            }
+        }
+        if (has_secondary_only && n < cap) out[n++] = t;
+    }
+    return n;
+}
+
+static int procgen_check_secondary_only_grants(const bb_match* m) {
+    int seen = 0;
+    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+        const bb_player* p = &m->players[s];
+        if (p->location == BB_LOC_ABSENT) continue;
+        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
+        const bb_position_def* pd = &td->positions[p->position_id];
+        if (pd->primary_mask != 0) continue;
+        bb_skillset base = base_position_skills(pd);
+        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
+             sk = bb_next_skill(&p->skills, sk + 1)) {
+            if (bb_has_skill(&base, sk)) continue;
+            uint8_t cat = bb_skill_defs[sk].category;
+            BB_CHECK(cat < BB_CAT_COUNT);
+            BB_CHECK(pd->secondary_mask & (1 << cat));
+            if (!(pd->secondary_mask & (1 << cat))) {
+                printf("  team %d pos %d skill %d cat %d secondary 0x%x\n",
+                       m->team_id[BB_TEAM_OF(s)], p->position_id, sk, cat,
+                       pd->secondary_mask);
+                return seen;
+            }
+            seen = 1;
+        }
+    }
+    return seen;
+}
+
 BB_TEST(match_procgen_default_params_match_legacy_api) {
     bb_procgen_params pp = bb_procgen_params_default();
-    bb_match a, b;
-    bb_rng r1, r2;
-    bb_rng_seed(&r1, 0x515A5EEDu, 17);
-    bb_rng_seed(&r2, 0x515A5EEDu, 17);
-    bb_match_init_random(&a, &r1);
-    bb_match_init_random_p(&b, &r2, &pp);
-    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
-    BB_CHECK(procgen_rng_same_state(&r1, &r2));
+    for (uint64_t seed = 1; seed <= 300; seed++) {
+        bb_match a, b;
+        bb_rng r1, r2;
+        bb_rng_seed(&r1, seed * 0x515A5EEDu, 17 + seed);
+        bb_rng_seed(&r2, seed * 0x515A5EEDu, 17 + seed);
+        bb_match_init_random(&a, &r1);
+        bb_match_init_random_p(&b, &r2, &pp);
+        BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
+        BB_CHECK(procgen_rng_same_state(&r1, &r2));
+        if (memcmp(&a, &b, sizeof(bb_match)) != 0 ||
+            !procgen_rng_same_state(&r1, &r2)) {
+            printf("  seed %llu failed\n", (unsigned long long)seed);
+            break;
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_inert_at_defaults) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = bb_procgen_params_default();
+    for (uint64_t seed = 1; seed <= 100; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 2654435761u, 53 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+            const bb_player* p = &m.players[s];
+            if (p->location == BB_LOC_ABSENT) continue;
+            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
+            const bb_position_def* pd = &td->positions[p->position_id];
+            if (pd->primary_mask != 0) continue;
+            bb_skillset base = base_position_skills(pd);
+            BB_CHECK_EQ(memcmp(&p->skills, &base, sizeof(bb_skillset)), 0);
+            if (memcmp(&p->skills, &base, sizeof(bb_skillset)) != 0) {
+                printf("  seed %llu team %d pos %d gained at defaults\n",
+                       (unsigned long long)seed, m.team_id[BB_TEAM_OF(s)],
+                       p->position_id);
+                return;
+            }
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_advance_with_pct) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = {11, 3, 0.5f};
+    int seen = 0;
+    for (uint64_t seed = 1; seed <= 2000 && !seen; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 11400714819323198485ull, 59 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        seen = procgen_check_secondary_only_grants(&m);
+    }
+    BB_CHECK(seen);
+    if (!seen) printf("  no secondary-only position advanced within 2000 seeds\n");
 }
 
 BB_TEST(match_procgen_skillups_off_keeps_base_skills) {

codex
`make test` is already green: `347 tests, 0 failures`. I found the local binding self-test command documented in the repo and am rerunning that now against the source binding path, which pulls in the edited engine code through the existing symlinks.
exec
/bin/zsh -lc 'clang -std=c11 -O2 -Ipuffer/bloodbowl puffer/bloodbowl/bloodbowl.c -o /tmp/bbe && /tmp/bbe --selftest' in /Users/alexanderhuth/Code/bloodbowl-rl
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 4819137323d1ece180f5c27b7ae1114d9ad9d81f..a37c95440728c41e5efb206931426ea4a6d75691
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -116,7 +116,9 @@
         int who = base + pg_pick(rng, n);
         bb_player* p = &m->players[who];
         const bb_position_def* pd = &td->positions[p->position_id];
-        if (!(pd->primary_mask || pd->secondary_mask)) continue;
+        uint8_t access = pd->primary_mask;
+        if (pp->skillup_secondary_pct > 0.0f) access |= pd->secondary_mask;
+        if (!access) continue;
         int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
         for (int g = 0; g < gains; g++) {
             if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 99774f8dfb71f3f99dfd14ddaa48a8432093ee30..bcf304109b9ca2b04bcd6a13f0b300f85a1c5fa5
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -278,16 +278,122 @@
     }
 }
 
+static int procgen_find_secondary_only_teams(int* out, int cap) {
+    int n = 0;
+    for (int t = 0; t < BB_TEAM_COUNT; t++) {
+        const bb_team_def* td = &bb_team_defs[t];
+        int has_secondary_only = 0;
+        for (int pi = 0; pi < td->num_positions; pi++) {
+            const bb_position_def* pd = &td->positions[pi];
+            if (pd->primary_mask == 0 && pd->secondary_mask != 0) {
+                has_secondary_only = 1;
+                break;
+            }
+        }
+        if (has_secondary_only && n < cap) out[n++] = t;
+    }
+    return n;
+}
+
+static int procgen_check_secondary_only_grants(const bb_match* m) {
+    int seen = 0;
+    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+        const bb_player* p = &m->players[s];
+        if (p->location == BB_LOC_ABSENT) continue;
+        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
+        const bb_position_def* pd = &td->positions[p->position_id];
+        if (pd->primary_mask != 0) continue;
+        bb_skillset base = base_position_skills(pd);
+        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
+             sk = bb_next_skill(&p->skills, sk + 1)) {
+            if (bb_has_skill(&base, sk)) continue;
+            uint8_t cat = bb_skill_defs[sk].category;
+            BB_CHECK(cat < BB_CAT_COUNT);
+            BB_CHECK(pd->secondary_mask & (1 << cat));
+            if (!(pd->secondary_mask & (1 << cat))) {
+                printf("  team %d pos %d skill %d cat %d secondary 0x%x\n",
+                       m->team_id[BB_TEAM_OF(s)], p->position_id, sk, cat,
+                       pd->secondary_mask);
+                return seen;
+            }
+            seen = 1;
+        }
+    }
+    return seen;
+}
+
 BB_TEST(match_procgen_default_params_match_legacy_api) {
     bb_procgen_params pp = bb_procgen_params_default();
-    bb_match a, b;
-    bb_rng r1, r2;
-    bb_rng_seed(&r1, 0x515A5EEDu, 17);
-    bb_rng_seed(&r2, 0x515A5EEDu, 17);
-    bb_match_init_random(&a, &r1);
-    bb_match_init_random_p(&b, &r2, &pp);
-    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
-    BB_CHECK(procgen_rng_same_state(&r1, &r2));
+    for (uint64_t seed = 1; seed <= 300; seed++) {
+        bb_match a, b;
+        bb_rng r1, r2;
+        bb_rng_seed(&r1, seed * 0x515A5EEDu, 17 + seed);
+        bb_rng_seed(&r2, seed * 0x515A5EEDu, 17 + seed);
+        bb_match_init_random(&a, &r1);
+        bb_match_init_random_p(&b, &r2, &pp);
+        BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
+        BB_CHECK(procgen_rng_same_state(&r1, &r2));
+        if (memcmp(&a, &b, sizeof(bb_match)) != 0 ||
+            !procgen_rng_same_state(&r1, &r2)) {
+            printf("  seed %llu failed\n", (unsigned long long)seed);
+            break;
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_inert_at_defaults) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = bb_procgen_params_default();
+    for (uint64_t seed = 1; seed <= 100; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 2654435761u, 53 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+            const bb_player* p = &m.players[s];
+            if (p->location == BB_LOC_ABSENT) continue;
+            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
+            const bb_position_def* pd = &td->positions[p->position_id];
+            if (pd->primary_mask != 0) continue;
+            bb_skillset base = base_position_skills(pd);
+            BB_CHECK_EQ(memcmp(&p->skills, &base, sizeof(bb_skillset)), 0);
+            if (memcmp(&p->skills, &base, sizeof(bb_skillset)) != 0) {
+                printf("  seed %llu team %d pos %d gained at defaults\n",
+                       (unsigned long long)seed, m.team_id[BB_TEAM_OF(s)],
+                       p->position_id);
+                return;
+            }
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_advance_with_pct) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = {11, 3, 0.5f};
+    int seen = 0;
+    for (uint64_t seed = 1; seed <= 2000 && !seen; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 11400714819323198485ull, 59 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        seen = procgen_check_secondary_only_grants(&m);
+    }
+    BB_CHECK(seen);
+    if (!seen) printf("  no secondary-only position advanced within 2000 seeds\n");
 }
 
 BB_TEST(match_procgen_skillups_off_keeps_base_skills) {

 succeeded in 1127ms:
bloodbowl selftest: 64 episodes, 0 failure(s), v4 planes B=22237 A=406

exec
/bin/zsh -lc "nl -ba engine/src/bb_procgen.c | sed -n '112,132p'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
   112	    // Advancement: players gain random skills from configured category access
   113	    // (the 2D6 random-skill table run "fairly" via the procgen stream).
   114	    int advanced = pp->skillup_max_players > 0 ? pg_pick(rng, pp->skillup_max_players + 1) : 0;
   115	    for (int i = 0; i < advanced; i++) {
   116	        int who = base + pg_pick(rng, n);
   117	        bb_player* p = &m->players[who];
   118	        const bb_position_def* pd = &td->positions[p->position_id];
   119	        uint8_t access = pd->primary_mask;
   120	        if (pp->skillup_secondary_pct > 0.0f) access |= pd->secondary_mask;
   121	        if (!access) continue;
   122	        int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
   123	        for (int g = 0; g < gains; g++) {
   124	            if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;
   125	            uint8_t mask = pd->primary_mask;
   126	            if (pp->skillup_secondary_pct > 0.0f &&
   127	                pg_float01(rng) < pp->skillup_secondary_pct) {
   128	                mask = pd->secondary_mask;
   129	            }
   130	            if (!mask) {
   131	                mask = (mask == pd->primary_mask) ? pd->secondary_mask : pd->primary_mask;
   132	            }

exec
/bin/zsh -lc 'git diff -- engine/src/bb_procgen.c engine/tests/test_match.c' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee..a37c954 100644
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@ static int pg_skill_count(const bb_skillset* s) {
     return n;
 }
 
+static float pg_float01(bb_rng* rng) {
+    return (float)(bb_rng_next(rng) >> 8) * (1.0f / 16777216.0f);
+}
+
+bb_procgen_params bb_procgen_params_default(void) {
+    return (bb_procgen_params){4, 2, 0.0f};
+}
+
 // Build one team's squad: positionals first (random counts within limits),
-// topped up with the first listed position; 0-4 players get 1-2 random
-// advancement skills from their primary categories.
-static void procgen_squad(bb_match* m, int team, int team_id, bb_rng* rng) {
+// topped up with the first listed position; then configured random
+// advancement skills from primary/secondary categories.
+static void procgen_squad(bb_match* m, int team, int team_id, bb_rng* rng,
+                          const bb_procgen_params* pp) {
     const bb_team_def* td = &bb_team_defs[team_id];
     int base = team * BB_TEAM_SLOTS;
     int n = 0;
@@ -100,22 +109,33 @@ static void procgen_squad(bb_match* m, int team, int team_id, bb_rng* rng) {
         m->players[base + s].location = BB_LOC_ABSENT;
     }
 
-    // Advancement: 0-4 players gain 1-2 random skills from a primary category
+    // Advancement: players gain random skills from configured category access
     // (the 2D6 random-skill table run "fairly" via the procgen stream).
-    int advanced = pg_pick(rng, 5);
+    int advanced = pp->skillup_max_players > 0 ? pg_pick(rng, pp->skillup_max_players + 1) : 0;
     for (int i = 0; i < advanced; i++) {
         int who = base + pg_pick(rng, n);
         bb_player* p = &m->players[who];
         const bb_position_def* pd = &td->positions[p->position_id];
-        if (!pd->primary_mask) continue;
-        int gains = 1 + pg_pick(rng, 2);
+        uint8_t access = pd->primary_mask;
+        if (pp->skillup_secondary_pct > 0.0f) access |= pd->secondary_mask;
+        if (!access) continue;
+        int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
         for (int g = 0; g < gains; g++) {
             if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;
-            // Pick a random primary category bit.
+            uint8_t mask = pd->primary_mask;
+            if (pp->skillup_secondary_pct > 0.0f &&
+                pg_float01(rng) < pp->skillup_secondary_pct) {
+                mask = pd->secondary_mask;
+            }
+            if (!mask) {
+                mask = (mask == pd->primary_mask) ? pd->secondary_mask : pd->primary_mask;
+            }
+            if (!mask) continue;
+            // Pick a random category bit.
             int cats[BB_CAT_COUNT];
             int nc = 0;
             for (int c = 0; c < BB_CAT_COUNT; c++) {
-                if (pd->primary_mask & (1 << c)) cats[nc++] = c;
+                if (mask & (1 << c)) cats[nc++] = c;
             }
             int cat = cats[pg_pick(rng, nc)];
             int sk = bb_random_skill_table[cat][pg_pick(rng, 12)];
@@ -140,11 +160,12 @@ static void procgen_squad(bb_match* m, int team, int team_id, bb_rng* rng) {
     }
 }
 
-static void pg_init_match(bb_match* m, bb_rng* rng, int home, int away) {
+static void pg_init_match(bb_match* m, bb_rng* rng, int home, int away,
+                          const bb_procgen_params* pp) {
     m->team_id[BB_HOME] = (uint8_t)home;
     m->team_id[BB_AWAY] = (uint8_t)away;
-    procgen_squad(m, BB_HOME, home, rng);
-    procgen_squad(m, BB_AWAY, away, rng);
+    procgen_squad(m, BB_HOME, home, rng, pp);
+    procgen_squad(m, BB_AWAY, away, rng, pp);
     for (int t = 0; t < 2; t++) {
         m->rerolls[t] = m->rerolls_start[t] = (uint8_t)(2 + pg_pick(rng, 3));
         m->apothecary[t] = bb_team_defs[m->team_id[t]].apothecary ? 1 : 0;
@@ -157,10 +178,15 @@ static void pg_init_match(bb_match* m, bb_rng* rng, int home, int away) {
 }
 
 void bb_match_init_random(bb_match* m, bb_rng* rng) {
+    bb_procgen_params pp = bb_procgen_params_default();
+    bb_match_init_random_p(m, rng, &pp);
+}
+
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp) {
     memset(m, 0, sizeof(*m));
     int home = pg_pick(rng, BB_TEAM_COUNT);
     int away = pg_pick(rng, BB_TEAM_COUNT);
-    pg_init_match(m, rng, home, away);
+    pg_init_match(m, rng, home, away, pp);
 }
 
 // Holdout / fixed-matchup variant: home/away >= 0 pin that side's team;
@@ -168,6 +194,12 @@ void bb_match_init_random(bb_match* m, bb_rng* rng) {
 // held-out-team generalization experiments train with exclude set and
 // evaluate with force_* set).
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude) {
+    bb_procgen_params pp = bb_procgen_params_default();
+    bb_match_init_forced_p(m, rng, home, away, exclude, &pp);
+}
+
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp) {
     memset(m, 0, sizeof(*m));
     int h = home;
     while (h < 0 || (home < 0 && h == exclude)) {
@@ -179,5 +211,5 @@ void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int excl
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3..bcf3041 100644
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,298 @@ BB_TEST(match_procgen_skill_cap) {
     }
 }
 
+static bb_skillset base_position_skills(const bb_position_def* pd) {
+    bb_skillset s;
+    memset(&s, 0, sizeof s);
+    for (int i = 0; i < pd->num_skills; i++) bb_add_skill(&s, pd->skills[i]);
+    return s;
+}
+
+static int procgen_squad_total(const bb_match* m, int team) {
+    int n = 0;
+    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
+        if (m->players[s].location != BB_LOC_ABSENT) n++;
+    }
+    return n;
+}
+
+static void check_procgen_structure(const bb_match* m) {
+    for (int t = 0; t < 2; t++) {
+        int counts[BB_MAX_POSITIONS] = {0};
+        const bb_team_def* td = &bb_team_defs[m->team_id[t]];
+        int total = 0;
+        for (int s = t * BB_TEAM_SLOTS; s < (t + 1) * BB_TEAM_SLOTS; s++) {
+            const bb_player* p = &m->players[s];
+            if (p->location == BB_LOC_ABSENT) continue;
+            BB_CHECK(p->position_id < td->num_positions);
+            if (p->position_id < td->num_positions) counts[p->position_id]++;
+            total++;
+        }
+        BB_CHECK(total >= 11);
+        BB_CHECK(total <= 14);
+        for (int pi = 0; pi < td->num_positions; pi++) {
+            BB_CHECK(counts[pi] <= td->positions[pi].qty_max);
+        }
+    }
+}
+
+static int procgen_count_skills(const bb_skillset* s) {
+    int n = 0;
+    for (int sk = bb_next_skill(s, 0); sk >= 0; sk = bb_next_skill(s, sk + 1)) n++;
+    return n;
+}
+
+static int procgen_rng_same_state(const bb_rng* a, const bb_rng* b) {
+    return a->state == b->state && a->inc == b->inc &&
+           a->script == b->script && a->script_len == b->script_len &&
+           a->script_pos == b->script_pos && a->mode == b->mode &&
+           a->error == b->error && a->sink == b->sink &&
+           a->sink_user == b->sink_user;
+}
+
+static void check_procgen_grants_in_mask(const bb_match* m, int secondary_only) {
+    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+        const bb_player* p = &m->players[s];
+        if (p->location == BB_LOC_ABSENT) continue;
+        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
+        const bb_position_def* pd = &td->positions[p->position_id];
+        bb_skillset base = base_position_skills(pd);
+        uint8_t want = secondary_only && pd->secondary_mask ? pd->secondary_mask : pd->primary_mask;
+        if (!want) want = secondary_only ? pd->primary_mask : pd->secondary_mask;
+        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
+             sk = bb_next_skill(&p->skills, sk + 1)) {
+            if (bb_has_skill(&base, sk)) continue;
+            uint8_t cat = bb_skill_defs[sk].category;
+            BB_CHECK(cat < BB_CAT_COUNT);
+            BB_CHECK(want & (1 << cat));
+            if (!(want & (1 << cat))) {
+                printf("  team %d pos %d skill %d cat %d want 0x%x\n",
+                       m->team_id[BB_TEAM_OF(s)], p->position_id, sk, cat, want);
+                return;
+            }
+        }
+    }
+}
+
+static int procgen_find_secondary_only_teams(int* out, int cap) {
+    int n = 0;
+    for (int t = 0; t < BB_TEAM_COUNT; t++) {
+        const bb_team_def* td = &bb_team_defs[t];
+        int has_secondary_only = 0;
+        for (int pi = 0; pi < td->num_positions; pi++) {
+            const bb_position_def* pd = &td->positions[pi];
+            if (pd->primary_mask == 0 && pd->secondary_mask != 0) {
+                has_secondary_only = 1;
+                break;
+            }
+        }
+        if (has_secondary_only && n < cap) out[n++] = t;
+    }
+    return n;
+}
+
+static int procgen_check_secondary_only_grants(const bb_match* m) {
+    int seen = 0;
+    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+        const bb_player* p = &m->players[s];
+        if (p->location == BB_LOC_ABSENT) continue;
+        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
+        const bb_position_def* pd = &td->positions[p->position_id];
+        if (pd->primary_mask != 0) continue;
+        bb_skillset base = base_position_skills(pd);
+        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
+             sk = bb_next_skill(&p->skills, sk + 1)) {
+            if (bb_has_skill(&base, sk)) continue;
+            uint8_t cat = bb_skill_defs[sk].category;
+            BB_CHECK(cat < BB_CAT_COUNT);
+            BB_CHECK(pd->secondary_mask & (1 << cat));
+            if (!(pd->secondary_mask & (1 << cat))) {
+                printf("  team %d pos %d skill %d cat %d secondary 0x%x\n",
+                       m->team_id[BB_TEAM_OF(s)], p->position_id, sk, cat,
+                       pd->secondary_mask);
+                return seen;
+            }
+            seen = 1;
+        }
+    }
+    return seen;
+}
+
+BB_TEST(match_procgen_default_params_match_legacy_api) {
+    bb_procgen_params pp = bb_procgen_params_default();
+    for (uint64_t seed = 1; seed <= 300; seed++) {
+        bb_match a, b;
+        bb_rng r1, r2;
+        bb_rng_seed(&r1, seed * 0x515A5EEDu, 17 + seed);
+        bb_rng_seed(&r2, seed * 0x515A5EEDu, 17 + seed);
+        bb_match_init_random(&a, &r1);
+        bb_match_init_random_p(&b, &r2, &pp);
+        BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
+        BB_CHECK(procgen_rng_same_state(&r1, &r2));
+        if (memcmp(&a, &b, sizeof(bb_match)) != 0 ||
+            !procgen_rng_same_state(&r1, &r2)) {
+            printf("  seed %llu failed\n", (unsigned long long)seed);
+            break;
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_inert_at_defaults) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = bb_procgen_params_default();
+    for (uint64_t seed = 1; seed <= 100; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 2654435761u, 53 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+            const bb_player* p = &m.players[s];
+            if (p->location == BB_LOC_ABSENT) continue;
+            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
+            const bb_position_def* pd = &td->positions[p->position_id];
+            if (pd->primary_mask != 0) continue;
+            bb_skillset base = base_position_skills(pd);
+            BB_CHECK_EQ(memcmp(&p->skills, &base, sizeof(bb_skillset)), 0);
+            if (memcmp(&p->skills, &base, sizeof(bb_skillset)) != 0) {
+                printf("  seed %llu team %d pos %d gained at defaults\n",
+                       (unsigned long long)seed, m.team_id[BB_TEAM_OF(s)],
+                       p->position_id);
+                return;
+            }
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_advance_with_pct) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = {11, 3, 0.5f};
+    int seen = 0;
+    for (uint64_t seed = 1; seed <= 2000 && !seen; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 11400714819323198485ull, 59 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        seen = procgen_check_secondary_only_grants(&m);
+    }
+    BB_CHECK(seen);
+    if (!seen) printf("  no secondary-only position advanced within 2000 seeds\n");
+}
+
+BB_TEST(match_procgen_skillups_off_keeps_base_skills) {
+    bb_procgen_params pp = {0, 2, 0.0f};
+    for (uint64_t seed = 1; seed <= 50; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 2654435761u, 23);
+        bb_match_init_random_p(&m, &pg, &pp);
+        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+            const bb_player* p = &m.players[s];
+            if (p->location == BB_LOC_ABSENT) continue;
+            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
+            bb_skillset base = base_position_skills(&td->positions[p->position_id]);
+            BB_CHECK_EQ(memcmp(&p->skills, &base, sizeof(bb_skillset)), 0);
+        }
+    }
+}
+
+BB_TEST(match_procgen_primary_only_uses_primary_categories) {
+    bb_procgen_params pp = {11, 3, 0.0f};
+    for (uint64_t seed = 1; seed <= 250; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 7919, 29);
+        bb_match_init_random_p(&m, &pg, &pp);
+        check_procgen_grants_in_mask(&m, 0);
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_uses_secondary_or_primary_fallback) {
+    bb_procgen_params pp = {11, 3, 1.0f};
+    for (uint64_t seed = 1; seed <= 250; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 104729, 31);
+        bb_match_init_random_p(&m, &pg, &pp);
+        check_procgen_grants_in_mask(&m, 1);
+    }
+}
+
+BB_TEST(match_procgen_skillups_reach_full_learnable_catalogue) {
+    bb_procgen_params pp = {11, 3, 0.5f};
+    uint8_t seen[BB_NUM_SKILLS] = {0};
+    int nseen = 0;
+    for (uint64_t seed = 1; seed <= 10000 && nseen < BB_NUM_SKILLS; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, 0xC0FFEEu + seed * 17, 37);
+        bb_match_init_random_p(&m, &pg, &pp);
+        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+            const bb_player* p = &m.players[s];
+            if (p->location == BB_LOC_ABSENT) continue;
+            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
+            const bb_position_def* pd = &td->positions[p->position_id];
+            bb_skillset base = base_position_skills(pd);
+            for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
+                 sk = bb_next_skill(&p->skills, sk + 1)) {
+                if (sk >= BB_NUM_SKILLS || bb_has_skill(&base, sk)) continue;
+                if (!seen[sk]) {
+                    seen[sk] = 1;
+                    nseen++;
+                }
+            }
+        }
+    }
+    BB_CHECK_EQ(nseen, BB_NUM_SKILLS);
+    if (nseen != BB_NUM_SKILLS) {
+        for (int sk = 0; sk < BB_NUM_SKILLS; sk++) {
+            if (!seen[sk]) printf("  missing skill %d (%s)\n", sk, bb_skill_defs[sk].id);
+        }
+    }
+}
+
+BB_TEST(match_procgen_cranked_params_respect_cap_and_structure) {
+    bb_procgen_params pp = {16, 12, 0.5f};
+    for (uint64_t seed = 1; seed <= 200; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 16127, 41);
+        bb_match_init_random_p(&m, &pg, &pp);
+        check_procgen_structure(&m);
+        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+            if (m.players[s].location == BB_LOC_ABSENT) continue;
+            BB_CHECK(procgen_count_skills(&m.players[s].skills) <= 12);
+        }
+        BB_CHECK(procgen_squad_total(&m, BB_HOME) >= 11);
+        BB_CHECK(procgen_squad_total(&m, BB_AWAY) >= 11);
+    }
+}
+
+BB_TEST(match_procgen_params_are_deterministic) {
+    bb_procgen_params pp = {11, 3, 0.35f};
+    bb_match a, b;
+    bb_rng r1, r2;
+    bb_rng_seed(&r1, 0x12345678u, 43);
+    bb_rng_seed(&r2, 0x12345678u, 43);
+    bb_match_init_random_p(&a, &r1, &pp);
+    bb_match_init_random_p(&b, &r2, &pp);
+    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
+    BB_CHECK(procgen_rng_same_state(&r1, &r2));
+}
+
 BB_TEST(match_procgen_games_complete) {
     for (uint64_t seed = 1; seed <= 12; seed++) {
         bb_match m;

exec
/bin/zsh -lc "nl -ba engine/tests/test_match.c | sed -n '245,380p'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
   245	    for (int sk = bb_next_skill(s, 0); sk >= 0; sk = bb_next_skill(s, sk + 1)) n++;
   246	    return n;
   247	}
   248	
   249	static int procgen_rng_same_state(const bb_rng* a, const bb_rng* b) {
   250	    return a->state == b->state && a->inc == b->inc &&
   251	           a->script == b->script && a->script_len == b->script_len &&
   252	           a->script_pos == b->script_pos && a->mode == b->mode &&
   253	           a->error == b->error && a->sink == b->sink &&
   254	           a->sink_user == b->sink_user;
   255	}
   256	
   257	static void check_procgen_grants_in_mask(const bb_match* m, int secondary_only) {
   258	    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
   259	        const bb_player* p = &m->players[s];
   260	        if (p->location == BB_LOC_ABSENT) continue;
   261	        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
   262	        const bb_position_def* pd = &td->positions[p->position_id];
   263	        bb_skillset base = base_position_skills(pd);
   264	        uint8_t want = secondary_only && pd->secondary_mask ? pd->secondary_mask : pd->primary_mask;
   265	        if (!want) want = secondary_only ? pd->primary_mask : pd->secondary_mask;
   266	        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
   267	             sk = bb_next_skill(&p->skills, sk + 1)) {
   268	            if (bb_has_skill(&base, sk)) continue;
   269	            uint8_t cat = bb_skill_defs[sk].category;
   270	            BB_CHECK(cat < BB_CAT_COUNT);
   271	            BB_CHECK(want & (1 << cat));
   272	            if (!(want & (1 << cat))) {
   273	                printf("  team %d pos %d skill %d cat %d want 0x%x\n",
   274	                       m->team_id[BB_TEAM_OF(s)], p->position_id, sk, cat, want);
   275	                return;
   276	            }
   277	        }
   278	    }
   279	}
   280	
   281	static int procgen_find_secondary_only_teams(int* out, int cap) {
   282	    int n = 0;
   283	    for (int t = 0; t < BB_TEAM_COUNT; t++) {
   284	        const bb_team_def* td = &bb_team_defs[t];
   285	        int has_secondary_only = 0;
   286	        for (int pi = 0; pi < td->num_positions; pi++) {
   287	            const bb_position_def* pd = &td->positions[pi];
   288	            if (pd->primary_mask == 0 && pd->secondary_mask != 0) {
   289	                has_secondary_only = 1;
   290	                break;
   291	            }
   292	        }
   293	        if (has_secondary_only && n < cap) out[n++] = t;
   294	    }
   295	    return n;
   296	}
   297	
   298	static int procgen_check_secondary_only_grants(const bb_match* m) {
   299	    int seen = 0;
   300	    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
   301	        const bb_player* p = &m->players[s];
   302	        if (p->location == BB_LOC_ABSENT) continue;
   303	        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
   304	        const bb_position_def* pd = &td->positions[p->position_id];
   305	        if (pd->primary_mask != 0) continue;
   306	        bb_skillset base = base_position_skills(pd);
   307	        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
   308	             sk = bb_next_skill(&p->skills, sk + 1)) {
   309	            if (bb_has_skill(&base, sk)) continue;
   310	            uint8_t cat = bb_skill_defs[sk].category;
   311	            BB_CHECK(cat < BB_CAT_COUNT);
   312	            BB_CHECK(pd->secondary_mask & (1 << cat));
   313	            if (!(pd->secondary_mask & (1 << cat))) {
   314	                printf("  team %d pos %d skill %d cat %d secondary 0x%x\n",
   315	                       m->team_id[BB_TEAM_OF(s)], p->position_id, sk, cat,
   316	                       pd->secondary_mask);
   317	                return seen;
   318	            }
   319	            seen = 1;
   320	        }
   321	    }
   322	    return seen;
   323	}
   324	
   325	BB_TEST(match_procgen_default_params_match_legacy_api) {
   326	    bb_procgen_params pp = bb_procgen_params_default();
   327	    for (uint64_t seed = 1; seed <= 300; seed++) {
   328	        bb_match a, b;
   329	        bb_rng r1, r2;
   330	        bb_rng_seed(&r1, seed * 0x515A5EEDu, 17 + seed);
   331	        bb_rng_seed(&r2, seed * 0x515A5EEDu, 17 + seed);
   332	        bb_match_init_random(&a, &r1);
   333	        bb_match_init_random_p(&b, &r2, &pp);
   334	        BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
   335	        BB_CHECK(procgen_rng_same_state(&r1, &r2));
   336	        if (memcmp(&a, &b, sizeof(bb_match)) != 0 ||
   337	            !procgen_rng_same_state(&r1, &r2)) {
   338	            printf("  seed %llu failed\n", (unsigned long long)seed);
   339	            break;
   340	        }
   341	    }
   342	}
   343	
   344	BB_TEST(match_procgen_secondary_only_positions_inert_at_defaults) {
   345	    int teams[BB_TEAM_COUNT];
   346	    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
   347	    BB_CHECK(nteams >= 2);
   348	    if (nteams < 2) {
   349	        printf("  found %d teams with secondary-only positions\n", nteams);
   350	        return;
   351	    }
   352	
   353	    bb_procgen_params pp = bb_procgen_params_default();
   354	    for (uint64_t seed = 1; seed <= 100; seed++) {
   355	        bb_match m;
   356	        bb_rng pg;
   357	        bb_rng_seed(&pg, seed * 2654435761u, 53 + seed);
   358	        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
   359	        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
   360	            const bb_player* p = &m.players[s];
   361	            if (p->location == BB_LOC_ABSENT) continue;
   362	            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
   363	            const bb_position_def* pd = &td->positions[p->position_id];
   364	            if (pd->primary_mask != 0) continue;
   365	            bb_skillset base = base_position_skills(pd);
   366	            BB_CHECK_EQ(memcmp(&p->skills, &base, sizeof(bb_skillset)), 0);
   367	            if (memcmp(&p->skills, &base, sizeof(bb_skillset)) != 0) {
   368	                printf("  seed %llu team %d pos %d gained at defaults\n",
   369	                       (unsigned long long)seed, m.team_id[BB_TEAM_OF(s)],
   370	                       p->position_id);
   371	                return;
   372	            }
   373	        }
   374	    }
   375	}
   376	
   377	BB_TEST(match_procgen_secondary_only_positions_advance_with_pct) {
   378	    int teams[BB_TEAM_COUNT];
   379	    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
   380	    BB_CHECK(nteams >= 2);

diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 4819137323d1ece180f5c27b7ae1114d9ad9d81f..a37c95440728c41e5efb206931426ea4a6d75691
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -116,7 +116,9 @@
         int who = base + pg_pick(rng, n);
         bb_player* p = &m->players[who];
         const bb_position_def* pd = &td->positions[p->position_id];
-        if (!(pd->primary_mask || pd->secondary_mask)) continue;
+        uint8_t access = pd->primary_mask;
+        if (pp->skillup_secondary_pct > 0.0f) access |= pd->secondary_mask;
+        if (!access) continue;
         int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
         for (int g = 0; g < gains; g++) {
             if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 99774f8dfb71f3f99dfd14ddaa48a8432093ee30..bcf304109b9ca2b04bcd6a13f0b300f85a1c5fa5
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -278,16 +278,122 @@
     }
 }
 
+static int procgen_find_secondary_only_teams(int* out, int cap) {
+    int n = 0;
+    for (int t = 0; t < BB_TEAM_COUNT; t++) {
+        const bb_team_def* td = &bb_team_defs[t];
+        int has_secondary_only = 0;
+        for (int pi = 0; pi < td->num_positions; pi++) {
+            const bb_position_def* pd = &td->positions[pi];
+            if (pd->primary_mask == 0 && pd->secondary_mask != 0) {
+                has_secondary_only = 1;
+                break;
+            }
+        }
+        if (has_secondary_only && n < cap) out[n++] = t;
+    }
+    return n;
+}
+
+static int procgen_check_secondary_only_grants(const bb_match* m) {
+    int seen = 0;
+    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+        const bb_player* p = &m->players[s];
+        if (p->location == BB_LOC_ABSENT) continue;
+        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
+        const bb_position_def* pd = &td->positions[p->position_id];
+        if (pd->primary_mask != 0) continue;
+        bb_skillset base = base_position_skills(pd);
+        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
+             sk = bb_next_skill(&p->skills, sk + 1)) {
+            if (bb_has_skill(&base, sk)) continue;
+            uint8_t cat = bb_skill_defs[sk].category;
+            BB_CHECK(cat < BB_CAT_COUNT);
+            BB_CHECK(pd->secondary_mask & (1 << cat));
+            if (!(pd->secondary_mask & (1 << cat))) {
+                printf("  team %d pos %d skill %d cat %d secondary 0x%x\n",
+                       m->team_id[BB_TEAM_OF(s)], p->position_id, sk, cat,
+                       pd->secondary_mask);
+                return seen;
+            }
+            seen = 1;
+        }
+    }
+    return seen;
+}
+
 BB_TEST(match_procgen_default_params_match_legacy_api) {
     bb_procgen_params pp = bb_procgen_params_default();
-    bb_match a, b;
-    bb_rng r1, r2;
-    bb_rng_seed(&r1, 0x515A5EEDu, 17);
-    bb_rng_seed(&r2, 0x515A5EEDu, 17);
-    bb_match_init_random(&a, &r1);
-    bb_match_init_random_p(&b, &r2, &pp);
-    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
-    BB_CHECK(procgen_rng_same_state(&r1, &r2));
+    for (uint64_t seed = 1; seed <= 300; seed++) {
+        bb_match a, b;
+        bb_rng r1, r2;
+        bb_rng_seed(&r1, seed * 0x515A5EEDu, 17 + seed);
+        bb_rng_seed(&r2, seed * 0x515A5EEDu, 17 + seed);
+        bb_match_init_random(&a, &r1);
+        bb_match_init_random_p(&b, &r2, &pp);
+        BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
+        BB_CHECK(procgen_rng_same_state(&r1, &r2));
+        if (memcmp(&a, &b, sizeof(bb_match)) != 0 ||
+            !procgen_rng_same_state(&r1, &r2)) {
+            printf("  seed %llu failed\n", (unsigned long long)seed);
+            break;
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_inert_at_defaults) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = bb_procgen_params_default();
+    for (uint64_t seed = 1; seed <= 100; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 2654435761u, 53 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+            const bb_player* p = &m.players[s];
+            if (p->location == BB_LOC_ABSENT) continue;
+            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
+            const bb_position_def* pd = &td->positions[p->position_id];
+            if (pd->primary_mask != 0) continue;
+            bb_skillset base = base_position_skills(pd);
+            BB_CHECK_EQ(memcmp(&p->skills, &base, sizeof(bb_skillset)), 0);
+            if (memcmp(&p->skills, &base, sizeof(bb_skillset)) != 0) {
+                printf("  seed %llu team %d pos %d gained at defaults\n",
+                       (unsigned long long)seed, m.team_id[BB_TEAM_OF(s)],
+                       p->position_id);
+                return;
+            }
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_advance_with_pct) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = {11, 3, 0.5f};
+    int seen = 0;
+    for (uint64_t seed = 1; seed <= 2000 && !seen; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 11400714819323198485ull, 59 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        seen = procgen_check_secondary_only_grants(&m);
+    }
+    BB_CHECK(seen);
+    if (!seen) printf("  no secondary-only position advanced within 2000 seeds\n");
 }
 
 BB_TEST(match_procgen_skillups_off_keeps_base_skills) {

exec
/bin/zsh -lc "nl -ba engine/tests/test_match.c | sed -n '377,410p'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
   377	BB_TEST(match_procgen_secondary_only_positions_advance_with_pct) {
   378	    int teams[BB_TEAM_COUNT];
   379	    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
   380	    BB_CHECK(nteams >= 2);
   381	    if (nteams < 2) {
   382	        printf("  found %d teams with secondary-only positions\n", nteams);
   383	        return;
   384	    }
   385	
   386	    bb_procgen_params pp = {11, 3, 0.5f};
   387	    int seen = 0;
   388	    for (uint64_t seed = 1; seed <= 2000 && !seen; seed++) {
   389	        bb_match m;
   390	        bb_rng pg;
   391	        bb_rng_seed(&pg, seed * 11400714819323198485ull, 59 + seed);
   392	        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
   393	        seen = procgen_check_secondary_only_grants(&m);
   394	    }
   395	    BB_CHECK(seen);
   396	    if (!seen) printf("  no secondary-only position advanced within 2000 seeds\n");
   397	}
   398	
   399	BB_TEST(match_procgen_skillups_off_keeps_base_skills) {
   400	    bb_procgen_params pp = {0, 2, 0.0f};
   401	    for (uint64_t seed = 1; seed <= 50; seed++) {
   402	        bb_match m;
   403	        bb_rng pg;
   404	        bb_rng_seed(&pg, seed * 2654435761u, 23);
   405	        bb_match_init_random_p(&m, &pg, &pp);
   406	        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
   407	            const bb_player* p = &m.players[s];
   408	            if (p->location == BB_LOC_ABSENT) continue;
   409	            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
   410	            bb_skillset base = base_position_skills(&td->positions[p->position_id]);

diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 4819137323d1ece180f5c27b7ae1114d9ad9d81f..a37c95440728c41e5efb206931426ea4a6d75691
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -116,7 +116,9 @@
         int who = base + pg_pick(rng, n);
         bb_player* p = &m->players[who];
         const bb_position_def* pd = &td->positions[p->position_id];
-        if (!(pd->primary_mask || pd->secondary_mask)) continue;
+        uint8_t access = pd->primary_mask;
+        if (pp->skillup_secondary_pct > 0.0f) access |= pd->secondary_mask;
+        if (!access) continue;
         int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
         for (int g = 0; g < gains; g++) {
             if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 99774f8dfb71f3f99dfd14ddaa48a8432093ee30..bcf304109b9ca2b04bcd6a13f0b300f85a1c5fa5
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -278,16 +278,122 @@
     }
 }
 
+static int procgen_find_secondary_only_teams(int* out, int cap) {
+    int n = 0;
+    for (int t = 0; t < BB_TEAM_COUNT; t++) {
+        const bb_team_def* td = &bb_team_defs[t];
+        int has_secondary_only = 0;
+        for (int pi = 0; pi < td->num_positions; pi++) {
+            const bb_position_def* pd = &td->positions[pi];
+            if (pd->primary_mask == 0 && pd->secondary_mask != 0) {
+                has_secondary_only = 1;
+                break;
+            }
+        }
+        if (has_secondary_only && n < cap) out[n++] = t;
+    }
+    return n;
+}
+
+static int procgen_check_secondary_only_grants(const bb_match* m) {
+    int seen = 0;
+    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+        const bb_player* p = &m->players[s];
+        if (p->location == BB_LOC_ABSENT) continue;
+        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
+        const bb_position_def* pd = &td->positions[p->position_id];
+        if (pd->primary_mask != 0) continue;
+        bb_skillset base = base_position_skills(pd);
+        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
+             sk = bb_next_skill(&p->skills, sk + 1)) {
+            if (bb_has_skill(&base, sk)) continue;
+            uint8_t cat = bb_skill_defs[sk].category;
+            BB_CHECK(cat < BB_CAT_COUNT);
+            BB_CHECK(pd->secondary_mask & (1 << cat));
+            if (!(pd->secondary_mask & (1 << cat))) {
+                printf("  team %d pos %d skill %d cat %d secondary 0x%x\n",
+                       m->team_id[BB_TEAM_OF(s)], p->position_id, sk, cat,
+                       pd->secondary_mask);
+                return seen;
+            }
+            seen = 1;
+        }
+    }
+    return seen;
+}
+
 BB_TEST(match_procgen_default_params_match_legacy_api) {
     bb_procgen_params pp = bb_procgen_params_default();
-    bb_match a, b;
-    bb_rng r1, r2;
-    bb_rng_seed(&r1, 0x515A5EEDu, 17);
-    bb_rng_seed(&r2, 0x515A5EEDu, 17);
-    bb_match_init_random(&a, &r1);
-    bb_match_init_random_p(&b, &r2, &pp);
-    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
-    BB_CHECK(procgen_rng_same_state(&r1, &r2));
+    for (uint64_t seed = 1; seed <= 300; seed++) {
+        bb_match a, b;
+        bb_rng r1, r2;
+        bb_rng_seed(&r1, seed * 0x515A5EEDu, 17 + seed);
+        bb_rng_seed(&r2, seed * 0x515A5EEDu, 17 + seed);
+        bb_match_init_random(&a, &r1);
+        bb_match_init_random_p(&b, &r2, &pp);
+        BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
+        BB_CHECK(procgen_rng_same_state(&r1, &r2));
+        if (memcmp(&a, &b, sizeof(bb_match)) != 0 ||
+            !procgen_rng_same_state(&r1, &r2)) {
+            printf("  seed %llu failed\n", (unsigned long long)seed);
+            break;
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_inert_at_defaults) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = bb_procgen_params_default();
+    for (uint64_t seed = 1; seed <= 100; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 2654435761u, 53 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+            const bb_player* p = &m.players[s];
+            if (p->location == BB_LOC_ABSENT) continue;
+            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
+            const bb_position_def* pd = &td->positions[p->position_id];
+            if (pd->primary_mask != 0) continue;
+            bb_skillset base = base_position_skills(pd);
+            BB_CHECK_EQ(memcmp(&p->skills, &base, sizeof(bb_skillset)), 0);
+            if (memcmp(&p->skills, &base, sizeof(bb_skillset)) != 0) {
+                printf("  seed %llu team %d pos %d gained at defaults\n",
+                       (unsigned long long)seed, m.team_id[BB_TEAM_OF(s)],
+                       p->position_id);
+                return;
+            }
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_advance_with_pct) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = {11, 3, 0.5f};
+    int seen = 0;
+    for (uint64_t seed = 1; seed <= 2000 && !seen; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 11400714819323198485ull, 59 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        seen = procgen_check_secondary_only_grants(&m);
+    }
+    BB_CHECK(seen);
+    if (!seen) printf("  no secondary-only position advanced within 2000 seeds\n");
 }
 
 BB_TEST(match_procgen_skillups_off_keeps_base_skills) {

codex
Implemented the secondary-only parity fix and the requested test hardening. No git state changes, and I only edited the two named files.

**Edit Map**
- [engine/src/bb_procgen.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/src/bb_procgen.c:119)
  Restored default RNG parity by computing advancement access from `primary_mask` first, only OR-ing `secondary_mask` when `skillup_secondary_pct > 0.0f`, and continuing before the `gains` draw when access is empty.
  This makes default params behave like legacy for Woodland Fox / Beer Boar: no `gains` draw, no per-gain draws, no granted skills.

- [engine/tests/test_match.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/tests/test_match.c:281)
  Added `procgen_find_secondary_only_teams`, scanning `bb_team_defs` for teams with any `primary_mask == 0 && secondary_mask != 0` position.

- [engine/tests/test_match.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/tests/test_match.c:298)
  Added `procgen_check_secondary_only_grants`, which verifies grants on primary-empty positions land only in that position’s `secondary_mask`.

- [engine/tests/test_match.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/tests/test_match.c:325)
  Strengthened `match_procgen_default_params_match_legacy_api` to loop seeds `1..300`, varying both seed and stream id, and checking both full `bb_match` `memcmp` and `procgen_rng_same_state` each iteration.

- [engine/tests/test_match.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/tests/test_match.c:344)
  Added `match_procgen_secondary_only_positions_inert_at_defaults`, forced secondary-only teams home/away for 100 seeds, and asserted every `primary_mask == 0` player’s skillset matches base position skills exactly.

- [engine/tests/test_match.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/tests/test_match.c:377)
  Added `match_procgen_secondary_only_positions_advance_with_pct`, forced the same matchup with `{11, 3, 0.5f}`, searched up to 2000 deterministic seeds for a secondary-only grant, and verified all such grants are within the secondary mask.

**Verification**
`make test` passed:

```text
347 tests, 0 failures
```

Binding local compile + selftest rerun exactly via:

```bash
clang -std=c11 -O2 -Ipuffer/bloodbowl puffer/bloodbowl/bloodbowl.c -o /tmp/bbe && /tmp/bbe --selftest
```

Output:

```text
bloodbowl selftest: 64 episodes, 0 failure(s), v4 planes B=22237 A=406
```

No deviations from the requested semantics. The only thing worth noting is that `git diff` against HEAD still includes the broader uncommitted skillup-knobs work from before this follow-up, so the raw diff is larger than this fix brief; within this turn I touched only `engine/src/bb_procgen.c` and `engine/tests/test_match.c`.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 4819137323d1ece180f5c27b7ae1114d9ad9d81f..a37c95440728c41e5efb206931426ea4a6d75691
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -116,7 +116,9 @@
         int who = base + pg_pick(rng, n);
         bb_player* p = &m->players[who];
         const bb_position_def* pd = &td->positions[p->position_id];
-        if (!(pd->primary_mask || pd->secondary_mask)) continue;
+        uint8_t access = pd->primary_mask;
+        if (pp->skillup_secondary_pct > 0.0f) access |= pd->secondary_mask;
+        if (!access) continue;
         int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
         for (int g = 0; g < gains; g++) {
             if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 99774f8dfb71f3f99dfd14ddaa48a8432093ee30..bcf304109b9ca2b04bcd6a13f0b300f85a1c5fa5
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -278,16 +278,122 @@
     }
 }
 
+static int procgen_find_secondary_only_teams(int* out, int cap) {
+    int n = 0;
+    for (int t = 0; t < BB_TEAM_COUNT; t++) {
+        const bb_team_def* td = &bb_team_defs[t];
+        int has_secondary_only = 0;
+        for (int pi = 0; pi < td->num_positions; pi++) {
+            const bb_position_def* pd = &td->positions[pi];
+            if (pd->primary_mask == 0 && pd->secondary_mask != 0) {
+                has_secondary_only = 1;
+                break;
+            }
+        }
+        if (has_secondary_only && n < cap) out[n++] = t;
+    }
+    return n;
+}
+
+static int procgen_check_secondary_only_grants(const bb_match* m) {
+    int seen = 0;
+    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+        const bb_player* p = &m->players[s];
+        if (p->location == BB_LOC_ABSENT) continue;
+        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
+        const bb_position_def* pd = &td->positions[p->position_id];
+        if (pd->primary_mask != 0) continue;
+        bb_skillset base = base_position_skills(pd);
+        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
+             sk = bb_next_skill(&p->skills, sk + 1)) {
+            if (bb_has_skill(&base, sk)) continue;
+            uint8_t cat = bb_skill_defs[sk].category;
+            BB_CHECK(cat < BB_CAT_COUNT);
+            BB_CHECK(pd->secondary_mask & (1 << cat));
+            if (!(pd->secondary_mask & (1 << cat))) {
+                printf("  team %d pos %d skill %d cat %d secondary 0x%x\n",
+                       m->team_id[BB_TEAM_OF(s)], p->position_id, sk, cat,
+                       pd->secondary_mask);
+                return seen;
+            }
+            seen = 1;
+        }
+    }
+    return seen;
+}
+
 BB_TEST(match_procgen_default_params_match_legacy_api) {
     bb_procgen_params pp = bb_procgen_params_default();
-    bb_match a, b;
-    bb_rng r1, r2;
-    bb_rng_seed(&r1, 0x515A5EEDu, 17);
-    bb_rng_seed(&r2, 0x515A5EEDu, 17);
-    bb_match_init_random(&a, &r1);
-    bb_match_init_random_p(&b, &r2, &pp);
-    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
-    BB_CHECK(procgen_rng_same_state(&r1, &r2));
+    for (uint64_t seed = 1; seed <= 300; seed++) {
+        bb_match a, b;
+        bb_rng r1, r2;
+        bb_rng_seed(&r1, seed * 0x515A5EEDu, 17 + seed);
+        bb_rng_seed(&r2, seed * 0x515A5EEDu, 17 + seed);
+        bb_match_init_random(&a, &r1);
+        bb_match_init_random_p(&b, &r2, &pp);
+        BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
+        BB_CHECK(procgen_rng_same_state(&r1, &r2));
+        if (memcmp(&a, &b, sizeof(bb_match)) != 0 ||
+            !procgen_rng_same_state(&r1, &r2)) {
+            printf("  seed %llu failed\n", (unsigned long long)seed);
+            break;
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_inert_at_defaults) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = bb_procgen_params_default();
+    for (uint64_t seed = 1; seed <= 100; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 2654435761u, 53 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
+            const bb_player* p = &m.players[s];
+            if (p->location == BB_LOC_ABSENT) continue;
+            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
+            const bb_position_def* pd = &td->positions[p->position_id];
+            if (pd->primary_mask != 0) continue;
+            bb_skillset base = base_position_skills(pd);
+            BB_CHECK_EQ(memcmp(&p->skills, &base, sizeof(bb_skillset)), 0);
+            if (memcmp(&p->skills, &base, sizeof(bb_skillset)) != 0) {
+                printf("  seed %llu team %d pos %d gained at defaults\n",
+                       (unsigned long long)seed, m.team_id[BB_TEAM_OF(s)],
+                       p->position_id);
+                return;
+            }
+        }
+    }
+}
+
+BB_TEST(match_procgen_secondary_only_positions_advance_with_pct) {
+    int teams[BB_TEAM_COUNT];
+    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
+    BB_CHECK(nteams >= 2);
+    if (nteams < 2) {
+        printf("  found %d teams with secondary-only positions\n", nteams);
+        return;
+    }
+
+    bb_procgen_params pp = {11, 3, 0.5f};
+    int seen = 0;
+    for (uint64_t seed = 1; seed <= 2000 && !seen; seed++) {
+        bb_match m;
+        bb_rng pg;
+        bb_rng_seed(&pg, seed * 11400714819323198485ull, 59 + seed);
+        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
+        seen = procgen_check_secondary_only_grants(&m);
+    }
+    BB_CHECK(seen);
+    if (!seen) printf("  no secondary-only position advanced within 2000 seeds\n");
 }
 
 BB_TEST(match_procgen_skillups_off_keeps_base_skills) {

tokens used
71,326
Implemented the secondary-only parity fix and the requested test hardening. No git state changes, and I only edited the two named files.

**Edit Map**
- [engine/src/bb_procgen.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/src/bb_procgen.c:119)
  Restored default RNG parity by computing advancement access from `primary_mask` first, only OR-ing `secondary_mask` when `skillup_secondary_pct > 0.0f`, and continuing before the `gains` draw when access is empty.
  This makes default params behave like legacy for Woodland Fox / Beer Boar: no `gains` draw, no per-gain draws, no granted skills.

- [engine/tests/test_match.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/tests/test_match.c:281)
  Added `procgen_find_secondary_only_teams`, scanning `bb_team_defs` for teams with any `primary_mask == 0 && secondary_mask != 0` position.

- [engine/tests/test_match.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/tests/test_match.c:298)
  Added `procgen_check_secondary_only_grants`, which verifies grants on primary-empty positions land only in that position’s `secondary_mask`.

- [engine/tests/test_match.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/tests/test_match.c:325)
  Strengthened `match_procgen_default_params_match_legacy_api` to loop seeds `1..300`, varying both seed and stream id, and checking both full `bb_match` `memcmp` and `procgen_rng_same_state` each iteration.

- [engine/tests/test_match.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/tests/test_match.c:344)
  Added `match_procgen_secondary_only_positions_inert_at_defaults`, forced secondary-only teams home/away for 100 seeds, and asserted every `primary_mask == 0` player’s skillset matches base position skills exactly.

- [engine/tests/test_match.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/tests/test_match.c:377)
  Added `match_procgen_secondary_only_positions_advance_with_pct`, forced the same matchup with `{11, 3, 0.5f}`, searched up to 2000 deterministic seeds for a secondary-only grant, and verified all such grants are within the secondary mask.

**Verification**
`make test` passed:

```text
347 tests, 0 failures
```

Binding local compile + selftest rerun exactly via:

```bash
clang -std=c11 -O2 -Ipuffer/bloodbowl puffer/bloodbowl/bloodbowl.c -o /tmp/bbe && /tmp/bbe --selftest
```

Output:

```text
bloodbowl selftest: 64 episodes, 0 failure(s), v4 planes B=22237 A=406
```

No deviations from the requested semantics. The only thing worth noting is that `git diff` against HEAD still includes the broader uncommitted skillup-knobs work from before this follow-up, so the raw diff is larger than this fix brief; within this turn I touched only `engine/src/bb_procgen.c` and `engine/tests/test_match.c`.
