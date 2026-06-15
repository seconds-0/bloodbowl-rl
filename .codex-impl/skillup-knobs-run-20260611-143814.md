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
session id: 019eb89f-242d-7b91-a356-59a55bfadff2
--------
user
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
deprecated: `[features].collab` is deprecated. Use `[features].multi_agent` instead.
Enable it with `--enable multi_agent` or `[features].multi_agent` in config.toml. See https://developers.openai.com/codex/config-basic#feature-flags for details.
codex
I’ll wire this through as a focused C change and keep the touched files inside the requested map plus engine tests. First I’m locating the actual procgen declarations, current test harness, and any duplicate `bloodbowl.ini` copies so the edits land in the existing style.
exec
/bin/zsh -lc ls in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
CLAUDE.md
DECISIONS.md
MEMORIAL.md
Makefile
README.md
STATUS.md
build
checkpoints-backup
compile_flags.txt
docs
engine
puffer
render
stream
stream_backend
tools
training
validation
vendor

exec
/bin/zsh -lc "rg --files . | rg '("'^|/)bloodbowl'"\\.ini"'$|engine/tests|bb_procgen|gen_skills|bb_rng|Makefile$|build'"\\.sh"'$'"'" in /Users/alexanderhuth/Code/bloodbowl-rl
exec
/bin/zsh -lc 'rg -n "bb_match_init_random|bb_match_init_forced|procgen_squad|demo_pickup_maxdist|skillup" .' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 122ms:
./engine/src/bb_procgen.c
./engine/src/gen_skills.c
./engine/src/bb_rng.c
./engine/tests/bb_fixtures.h
./engine/tests/bb_test_main.c
./engine/tests/test_rng.c
./engine/tests/test_rules_injury.c
./engine/tests/test_gen_data.c
./engine/tests/test_replay.c
./engine/tests/test_skills_mutation_passing.c
./engine/tests/golden/golden_04.jsonl
./engine/tests/golden/golden_06.jsonl
./engine/tests/golden/golden_02.jsonl
./engine/tests/golden/golden_00.jsonl
./engine/tests/golden/golden_07.jsonl
./engine/tests/golden/golden_05.jsonl
./engine/tests/golden/golden_01.jsonl
./engine/tests/golden/golden_03.jsonl
./engine/tests/test_golden.c
./engine/tests/test_rules_blocking.c
./engine/tests/corpus/044bb3ab3a1d191285f3b0272017d2e9109d3d13
./engine/tests/corpus/b16d8398f7442d127705aecc199dc39dc5fa2b05
./engine/tests/corpus/392bb545e6d1caf34b12f014655f29e16c8efcf5
./engine/tests/corpus/8e6fb7c9356b26df424dd51001cdc2642c901283
./engine/tests/corpus/14f49da21e4c50274cbae495fdb1a5c0fd27eb5b
./engine/tests/corpus/971722c0f9583e75ad2d91fd1f3dc6eaae679f79
./engine/tests/corpus/0a672deb78f8ac27463ac07f7408fa8203e118d3
./engine/tests/corpus/d9123c651102af44c6fe15f708745f12d3ad98e8
./engine/tests/corpus/639cec87a83d944e3e6d987abce3f6ab166af843
./engine/tests/corpus/2867bbe91c9f7e626ee5d32f11b75bc9e89c4f19
./engine/tests/corpus/76779b8fe9114e2eb13e9e3059e61808a8d92123
./engine/tests/fuzz_match.c
./engine/tests/bb_test.h
./engine/tests/test_rules_structure.c
./engine/tests/test_match.c
./engine/tests/corpus/eb682b51e5c421374daa394e4f38514976603e2e
./engine/tests/test_rules_movement.c
./engine/tests/test_rules_ball.c
./engine/tests/test_skills_devious_traits.c
./engine/tests/test_blockev.c
./engine/tests/corpus/a52d8ffa5d1d0446f942122ec79a5eadcc0475a1
./engine/tests/corpus/ac858a2329aa27aa9e98fd1ec3bc67b2e78277fb
./engine/tests/corpus/4cd1b5fd1067c19b9007d67999b796a9a6a491d0
./engine/tests/corpus/b7b24e242f468e82b8a3a6aed984156cb267f4be
./engine/tests/corpus/13b8cbb475e414284789bb8f54d32ef9ca81c2c6
./engine/tests/corpus/6b50f666773f25e90bc3549484a8fd2d48a635da
./engine/tests/corpus/b7762376927e9b61d9e07d3a0cda914d72291935
./engine/tests/corpus/93289e786fdf924c356074b60ea6f5ae3e3c48ee
./engine/tests/corpus/1d646845394bf2fe333180f46fb5d2baaaacea79
./engine/tests/corpus/026c590040336671e4c7aba1a2b2349369c203f5
./engine/tests/corpus/bfe19d99556457c13e07e7e2eb25bdeaf6b8292c
./engine/tests/corpus/e84a51c594b30a5eb0c44bac9df79de1a3b8aa2d
./engine/tests/corpus/036de2156dcd1ecd8691492837fd78703d6feb5b
./engine/tests/corpus/26f9f877e45e83a5035a7f92c400a7efb4378c53
./engine/tests/corpus/89ab20556aa0cb6adf50b993a3daa3a62f66582c
./engine/tests/corpus/90f3ac0d2f54356a7df8cc1b79599f4fa431ba40
./engine/tests/corpus/caf7892295ac64c8569f5f46837cccf365acf306
./engine/tests/corpus/eb3e23449a7afcd35e211bc5f98d4a8436769dd6
./engine/tests/corpus/8991e3794b06dfc8d8b888dd93b1bfa0ad509610
./engine/tests/corpus/ba5a296e49a460a5ed6600059e3152b6c4a62b11
./engine/tests/corpus/4263452aa35ba3b52cc74cf941f57467741dab42
./engine/tests/corpus/fd3bbff9f38200b6b804ae483a9eb527a79856a5
./engine/tests/corpus/f4bf0beb459c85b1802e4928eddccfa4a14f6aeb
./engine/tests/corpus/97e514716453d341da83301e64a31403e8c4b30a
./engine/tests/corpus/97d09bc3749b1b6bea053f1f28fe9b833b15153d
./engine/tests/corpus/1d7b8e27c2aa212be802fbcdabbfac286ec54bef
./engine/tests/corpus/0fee2784c92c40b6aa2895e32ef57e5a97fb7d5f
./engine/tests/corpus/6ee20c3c6be72fbb9ce917f8781a855b8aeef3e5
./engine/tests/corpus/8bfc58558b084c51ae500387eb125a1b792c73a1
./engine/tests/corpus/f0da6a8e7ed4621bb17f6c84f23535f6f3a8533b
./engine/tests/corpus/1e51996cd4f8168f30057fca0a0962cc7dd65877
./engine/tests/corpus/c4e4ff29c568d8aa80635c799a017e54371494aa
./engine/tests/corpus/a1e4f411e7f89d4b01a1eefaed1d71020db216f4
./engine/tests/corpus/c82e3e48d1dad4aee391cf234332fb664bbe0c97
./engine/tests/corpus/57166742f11efa841c8e547cc8423059075e4b6f
./engine/tests/corpus/5d5156c27721f3d3af82aeabda928c6c75d7ad68
./engine/tests/corpus/a263b77ac271a257bb230534e07af6722b912ef8
./engine/tests/corpus/6143656c2b1bf6a2f3a1a1340301aaa58b574649
./engine/tests/corpus/4bfbd15fb588ddc14940ac0e9f1bec74a42e9f03
./engine/tests/corpus/fee9647c83470eabe491651aea63a24c534579c1
./engine/tests/corpus/44b85f837f7d20e2283ede679ee156bc47702972
./engine/tests/corpus/415dc56f3015d34a8c00a95eeeb9a7dde7070892
./engine/tests/corpus/30ff3a741ad5af8ef2cfd968c808009d8c6bd645
./engine/tests/corpus/cfc18b741ff9362e562aa9a0ccbaabd28ec9e44e
./engine/tests/corpus/9954f8c93e9e41054ea256c7c586643a9dec9dd4
./engine/tests/corpus/5855568ad4cd83f1fca845c62c4fcd63e12ab773
./engine/tests/corpus/1002ebe8ee0125e6fdbe75575c0776cbceaf7f62
./engine/tests/corpus/182713de79bec93a65ee27c348ae1486e0a765d7
./engine/tests/corpus/b04c4b7a45c94c3bc1bb8383000df9ec03e16a56
./engine/tests/corpus/dd994267269e9341993a1a7e504dd8bc6b9c75c9
./engine/tests/corpus/25af1faebc7b982096b24a9e50aa16461712be9c
./engine/tests/corpus/ed08a90e0769b4645cba641af685f85fd6b8f356
./engine/tests/corpus/c592524aa64b0e964c6332679ef6ae49b21d0a69
./engine/tests/corpus/f318411cebd4572a2bfff9cb6acace3a53733558
./engine/tests/corpus/0462587dbbdd4db0c9d047b69ca7c1d8e05fa77c
./engine/tests/corpus/b932e7e34cc4869ede082a09ce2c54bb3db58f22
./engine/tests/corpus/88be5483c1097a42dc8372d8adf7ba197f7f0230
./engine/tests/corpus/a30802e42adc6253ceedb3fd56b0df4de9238352
./engine/tests/corpus/8c10de2d5c76eba491a91166e04303bcd5bb0033
./engine/tests/corpus/18552b445e8aa952453bdd06b379f4a4c2c5771f
./engine/tests/corpus/d6619945a00180a2df630da41129ebe08eec86b3
./engine/tests/corpus/ed3464eface99f7fe1baeb459137fd14bdde465f
./engine/tests/corpus/89e1ccbae698dcc620e267c9b44ecd430bf36046
./engine/tests/corpus/6d2ffc3245878544bc928856dcc592a09f4a5d57
./engine/tests/corpus/8e641eb8ce78bb73bc9070d200054da0b19fa141
./engine/tests/corpus/0bec36ed37d63739dc59adec0868373612d57a9a
./engine/tests/corpus/b7d9a0d23b0f41da2265247069b72dd448695b74
./engine/tests/corpus/40706f0cf7d7828e6bd11792407b83b32b00fdf1
./engine/tests/corpus/eefc5886589b84cd51b1f0a2b39b471a0410c465
./engine/tests/corpus/04b8e35669b8c9a76a04924580d5a352b4eabf1f
./engine/tests/corpus/ecde8884b63e869a0eb38385ad9cf834321170cc
./engine/tests/corpus/12ee549c05e21ebef7813981c4772e0bad4b3644
./engine/tests/corpus/61eec0344ae62cf713ae4e660f6b1b5963161988
./engine/tests/corpus/c361c8977e7120dd2f8b69452674b078bcd73cdf
./engine/tests/corpus/788823dc9b186b15321c6f8f684893a76b6e578b
./engine/tests/corpus/41059a348b7e2e9768cad8d4a9052e9b9bfe2c32
./engine/tests/corpus/9332dac55deaa35969de50fe66c203f897d93307
./engine/tests/corpus/a517f298d753883001d97ee87ef17f58c87eea67
./engine/tests/corpus/94b75001a262d3534fb4f4f449f3a91261c66ee6
./engine/tests/corpus/ef12f40c581cbfc0be7bbca79cf64becc844c532
./engine/tests/corpus/8f2c9a5c654f4540c84a81003dee9f829710faf7
./engine/tests/corpus/658320423d421a63f2da94dc9a382626b39b303a
./engine/tests/corpus/7b01b900174b2218ad12106b90e9ae2d00289775
./engine/tests/corpus/ed9cfbcb6d89f89410370573c157fdd80e2d110d
./engine/tests/corpus/b6e91953ab009252ea154626794e1bd5b28ec8d3
./engine/tests/corpus/de01ee8ae8a65b06818c30c2937d9a2ffe70830e
./engine/tests/corpus/da9454c2a49148741b514499addd60a2f7b1d974
./engine/tests/corpus/195ea4ac013c8e9a9abba037053d8ce944ab012f
./engine/tests/corpus/aacdcfcbffc95d947647b248b0d753011eb48968
./engine/tests/corpus/bd95f7c56ed7838b72f2c31277edf6f7160b2052
./engine/tests/corpus/6445c3ba6cc38f227ae37ac1e85b17fe5b236634
./engine/tests/corpus/53971e029321245525450c681b018e32d922b74d
./engine/tests/corpus/59e9fa174c8ef29a169fdd3f67dae74a4a1fbf31
./engine/tests/corpus/8850d0062cbc5de1ef8bcafca92c2441ed8ce748
./engine/tests/corpus/448a7bf9cd45f405cd27c12c7169154dddaef82a
./engine/tests/corpus/5f461cd3662edf652e3de88076ca198539eba2f3
./engine/tests/corpus/ebabea0508da0a161ded5ee09614f7d754eb73af
./engine/tests/corpus/7ce1d66252c0f0d8f766e01a433799a509058f40
./engine/tests/corpus/6e5594e72569aabf7770f3ef878825756b238678
./engine/tests/corpus/d410fb436db4dc54e1403f59b4e49d614037b585
./engine/tests/corpus/926d61f59b12f30ac7d6df1a321a67ff62795d38
./engine/tests/corpus/dc7605dc9c5e8872f9a3e5b8484edaa82be99ca7
./engine/tests/corpus/b22023e07862682d72f6b55a3ef71e0ebdbe96a5
./engine/tests/corpus/4105ae5d203a573fe81578509e2036517328d3fa
./engine/tests/corpus/3a1fe3f5b514ca01cf83d97b21b554be16c3403c
./engine/tests/corpus/eaed0f3b215bc015a234887a3a744877ba22f6eb
./engine/tests/corpus/df84330eb91d11f52fca8992d6d3d4832b6aecff
./engine/tests/corpus/b7bc180f1440d83af8d8f48c0fe12c8067676203
./engine/tests/corpus/2b9dcd3598a73b35ac517960967690a3686241b8
./engine/tests/corpus/df2a61ccecf2341474a1a6c703434274b63ba865
./engine/tests/corpus/6ba819f974cfc7964f6ec5910a12d9b8a18aec3f
./engine/tests/corpus/4ed7b04e2bfdafe1f0721e0bd1bd7b3d9df2b001
./engine/tests/corpus/ac7e381244b18709869b91e72d960393b1325d0f
./engine/tests/corpus/2cf4d0b45ea91832fe1490637d59ac1add6af872
./engine/tests/corpus/a771a756e5736a6386ee7a5406485a7f832f8dfe
./engine/tests/corpus/83ca75750711cdf4ba103019ea8f5e89dfa15ab2
./engine/tests/corpus/a59685bac5757f03dbf4975f8ce8da7280766058
./engine/tests/corpus/109db8f8317b96d86c58327a9d407e900941902b
./engine/tests/corpus/0b42ed731171f69440a1f316a50ba50b23e289c3
./engine/tests/corpus/fc19d29c2924d371094c60c571249fc9f74f4f0c
./engine/tests/corpus/1c398ad33cce225d761d15a148a7e0516d4d72c4
./engine/tests/corpus/11ad9e286eef65fcc153c2652d592d6d05f40e97
./engine/tests/corpus/94bc2140fdb4d98a3251a342a0de831281482573
./engine/tests/corpus/6573eb26ee209ace7c6865ca2fd5bc9909ed3eeb
./engine/tests/corpus/8887a58a653d86f393805d152b921c828d8898a4
./engine/tests/corpus/0f1e90cf60898ddf662c602d055476436696c9c3
./engine/tests/corpus/2e1b6a7063c3049068218068b8325e48d20f84c2
./engine/tests/corpus/b20eb5f46d35ae4cf5df3cfceb57ae53eb303819
./engine/tests/corpus/40874a75090cdf003d359323f79e9e45a3171091
./engine/tests/corpus/9f4908215861a5a5ce2dd8c402e716e8e1015021
./engine/tests/corpus/d8d6da3e8efc9e03929497e0dd25c28a32a00126
./engine/tests/corpus/a71837672128284509084d0ac9b3fa2750c56aab
./engine/tests/corpus/30f5590133f8963e6b244b69843ab2c220894ac5
./engine/tests/corpus/79a7bd00f8c408095cbf7d5fef747327f9e289f0
./engine/tests/corpus/ed45135240b03e3df69f7172052394ad08596b76
./engine/tests/corpus/6a325f693ed04500af44b93f96eb617c13363676
./engine/tests/corpus/8a0aa2135cce7730c2e255e5709cf2d0d39bc057
./engine/tests/corpus/1531b93266fed53722731bcc5b0d976f33788a65
./engine/tests/corpus/cb411b424ae7ce5029dc027bb835668f713e100c
./engine/tests/corpus/1a999d19fb65fd961b27dc9441b35fd62d72393f
./engine/tests/corpus/b0c908734a0ca7077acb58bdec4636b35a50eaf5
./engine/tests/corpus/48286be0638503b8ee7ef943481897a0ccae9390
./engine/tests/corpus/197c19993705396edefebffdf7c81d025b2dd559
./engine/tests/corpus/8802e126a62650793a121846d6bf8d9de5f89c50
./engine/tests/corpus/7ef1c22f308347a3f302a12b5ffabce7550777ea
./engine/tests/corpus/f168aeaaf242845fd3efb18b4c7a13d59ad5a16d
./engine/tests/corpus/a919faf742291c89821f6a7047b9beab922797c5
./engine/tests/corpus/cb48bc286088501725183c90892536f334a2e015
./engine/tests/corpus/dd1cce7508f2298f3144799be2513248bca980cd
./engine/tests/corpus/647718acf7e132c49e08552511619562a1ff26b5
./engine/tests/corpus/1676e91652ef1d117965eb1453ae9e7965b234d4
./engine/tests/corpus/51e7d772ee872d08a4ad0ca9b50ca0cbde2765e6
./engine/tests/corpus/38589706169da8eb7ae8dfbddfcbb9098ffa4ee2
./engine/tests/corpus/de67e8f7feca056f90d7d0341d74e772d140efa2
./engine/tests/corpus/f814ba955f9d93dc1cc2a924bb2900d9bc804846
./engine/tests/corpus/a0eaff88c56e708047d5ffd5ada9398529932517
./engine/tests/corpus/9864a3d80cf6a6538adce7c343a2646df9c86806
./engine/tests/corpus/edb73c442bf2223fb3c6fb96b8f0e28d2fee21da
./engine/tests/corpus/5262de68ccf1925e03260989a456ed75f9176b35
./engine/tests/corpus/fc5465c573e9347734996ebf65b65a4f6eecf24d
./engine/tests/corpus/f72bc0d993037666d0fe0f7b9c57c62647b69ced
./engine/tests/corpus/f015de7bc7376aa48e3c24cef3ac7d0fab461db0
./engine/tests/corpus/2e55156811c4cd64630ce03b5c8d24bdc358210b
./engine/tests/corpus/55e486ae7de6f1f531b555bd016099049772d21f
./engine/tests/corpus/e137451187056b64e4c16dcbae1b693d625a8997
./engine/tests/corpus/9cca0b9fad5e267b45638a472fa1a19c7e78cc70
./engine/tests/corpus/5e9f5ff93c79d3ad395e327274e81a6ab555ac78
./engine/tests/corpus/458cba5ed17bb966681a8ee8b953c70c228322b1
./engine/tests/corpus/0d453a157ae76642b0b25190917de42dd47b839c
./engine/tests/corpus/4cbccc11c05aee2e73b257211c51eded54cde331
./engine/tests/corpus/f8cc93b74d15b2e7ac3f234122123e59ed3b62e2
./engine/tests/corpus/b7ba30b7862f1a36e9c48797244d8052ba150642
./engine/tests/corpus/6d5f285881b1578521b2a53eedf4ca8613ae15f8
./engine/tests/corpus/abb9d9965153a02972bd4367c3ecb3da869978e3
./engine/tests/corpus/c1d94c3ffac1968f5c5c23608ba11c48e42e2498
./engine/tests/corpus/d421689769bd57c18bcbfd10df5407cb4af28080
./engine/tests/corpus/21c4908fca68f3bb35fe5fd276818760ff3f757c
./engine/tests/corpus/7649feaa84c42e1cccead51881d5fd6acf75bb44
./engine/tests/corpus/02ff852ad9a7665e282680407ecd82cd12eb890d
./engine/tests/corpus/08a33659d8e2dc1c455d6d983574443895cd58e1
./engine/tests/corpus/d13fbded4c5189e176033481f0c679fed268c5f0
./engine/tests/corpus/ac499a37e170d4ea15b8c4f330382558fd43bb58
./engine/tests/corpus/9403395001d0a1cba8cbe28189134b9e17216b28
./engine/tests/corpus/d39b948de8de4dce72d38693a7f28fe08930f672
./engine/tests/corpus/8fa0968b47f92490b11000b456e08a724dcea9d0
./engine/tests/corpus/7d82622eb4b1ac41e69d2fa1931bbcf51628fa2e
./engine/tests/corpus/6ba5ede422dad1b264183317ea42dab7cfbb90fb
./engine/tests/corpus/160d7f78b41abb070a3b17edf17ae8c0096b29b9
./engine/tests/corpus/0085aed3fbd15737ae3d767c5dfb895a8ecbcc29
./engine/tests/corpus/454e4022d37159bc9c0a073ba9be2949dcc500c4
./engine/tests/corpus/0d8444a775aaa016f3a0829e01cbe2826aa90f16
./engine/tests/corpus/14b20ad0198f2246c51e39605d043e30a4eea24f
./engine/tests/corpus/c4f14ba363a65969fdc558a0dea9d9cc59a04c20
./Makefile
./engine/include/bb/bb_rng.h
./engine/include/bb/gen_skills.h
./engine/tests/corpus/d12a8f33cea6c1f87fdf01aa28bc5924e8773e64
./engine/tests/corpus/4eac6b56f932610b160190468b7100ab0478fae9
./engine/tests/corpus/96b982c40121ae08fde39538f8d8374593688a30
./engine/tests/corpus/06a5e01463a1ced2f11eb5d4504d4bc0769e8656
./engine/tests/corpus/f747614b3755014bc4286f9613d23fcfd87f7192
./engine/tests/corpus/0e219e7267ac0dc769edf212550ca23621f406f0
./engine/tests/corpus/1081fa8b07596dc37260fa215432ed7900bf8543
./engine/tests/corpus/4b9818f2daa2cbd48e946de9073faec7b097dbdc
./engine/tests/corpus/093908f61360036871264fbf199fb17d98b7ce96
./engine/tests/corpus/8ba345d06043d5915f3b7917fdd92aa8b29d95bf
./engine/tests/corpus/f39db88df7d61d9dce9acddd5a1785782fd5d83a
./engine/tests/corpus/4a549dd384c761a0282953408061b189aa7f9a20
./engine/tests/corpus/035fce978e815101d78368315a54d47803afd874
./engine/tests/corpus/cb2522b16c37a6473f6be0a049834b9e75a2560d
./engine/tests/corpus/8b408b8a931fb74a9987e3b9fcb9fd7ec049bac3
./engine/tests/corpus/8bc8c04f78bb58381f3f4a1e123aeb003e5e69ef
./engine/tests/corpus/cd0de52b4c5f197996462a44ab8e422f5110a84d
./engine/tests/corpus/da172ff63804f9fa5080e174c2d0aa3ef06e4079
./engine/tests/corpus/dccb9c6c8ca58fdff8fcc19d8d7e4bdbe989f10d
./engine/tests/corpus/7c19b2904ad88754985d9b92ea27053702186cac
./engine/tests/corpus/c28fe9c57475cb518d32ff6f22d0b1a323be0709
./engine/tests/corpus/8c2c7bd98bbfd77ad5f625da6270fa3b4cf2d01e
./engine/tests/corpus/f1b55959dccda0cca80f68c91397a372eaa4acaf
./engine/tests/corpus/95f362e7d46e9b7a38846b3dcc490f4891091478
./engine/tests/corpus/890d60e94cf4776a47607af329bbce5806aec031
./engine/tests/corpus/57240ecee9477ee17d8c4eda08e5910af43053a1
./engine/tests/corpus/6df9ed3f0af618ad5244dc720c913166c2a7bb1f
./engine/tests/corpus/5c88bf2c59cf04c0dd2922114fa34957afd909f2
./engine/tests/corpus/7fee1ac9e815ae8b4dc0d9a63be1b267426a7457
./engine/tests/corpus/4de9512851eb4247b913639c6c9ba4174413d220
./engine/tests/corpus/483d3bed22953b7fd824f3a7f1e643c462417814
./engine/tests/corpus/14b519112d527df4446cd40387edcbcbba82a5da
./engine/tests/corpus/e91a141db0dda8f757c1410bbb8da4021db09ad9
./engine/tests/corpus/f921132f3331e05e6bac1f6926b333e0c34b0690
./engine/tests/corpus/d642c0a6e2b03a0533a0481cc01010fdddd9faa7
./engine/tests/corpus/004707aef5d66b8f7e5055bc4701411a41e755d3
./engine/tests/corpus/0b9dcc8c862112487899605adc7438b04ecbbacb
./engine/tests/corpus/69c202e3f56432bacd2a323a6db5c3a00c106ae1
./engine/tests/corpus/9d4be50cc48e08dca8dc945bb0cfa262612669c2
./engine/tests/corpus/475b8717adbdc9488fba2ed8400a6951d85ff30a
./engine/tests/corpus/361271cf45692a4da5021d3474a1fd785b3cb695
./engine/tests/corpus/9039fa41c8834d0e72e6a75521d1f76c685257b2
./engine/tests/corpus/8884959d8fad53395d5bbdad042d4facdece4014
./engine/tests/corpus/1e05057a147153f4c8849744ac2cc2e8a08517a6
./engine/tests/corpus/2756ca9869f6136964732e9443dcaf9e71bfdadd
./engine/tests/corpus/3bccfd799e76155f1431852c2e5ad7c2d0fdb36f
./engine/tests/corpus/11de29e8fc5e4229eff0320f9af3e1baf227a918
./engine/tests/corpus/6654a2d77ad009efe49e4fdcf185b2e5020f6da1
./engine/tests/corpus/3ff0195a417eb14dd9da5fff2ae36b6fb83910c4
./engine/tests/corpus/fa88b2a265a481936a2dcdeb3bf6eef02f1a6d70
./engine/tests/corpus/c9176e8897b1a5f09a62ea7aa2bed6ea9ed587a9
./engine/tests/corpus/0ca14f5f7ea430efc5b458cc078b306a317aa8db
./engine/tests/corpus/93cee21becff5b819846269eb08549940924156a
./engine/tests/corpus/df5ef2eaeda9122161522502d2b6666abb0b7d91
./engine/tests/corpus/f034d18199839415b69a3f0eeee062dca897b6e9
./engine/tests/corpus/a6e137b6bc845feae5f5d855eb5472525231614f
./engine/tests/corpus/eb1298905380a324d82bfa650e91df35fb7c17aa
./engine/tests/corpus/1b68a97101db3efeb0a7522901c1ba74e1485515
./engine/tests/corpus/937c850ff16272ec78b11a83c1046e5175378c0f
./engine/tests/corpus/0f9beb0174c86d21cffe81536ba987331cf0d936
./engine/tests/corpus/c611807778e4786e269c814ed5656e12cea148b6
./engine/tests/corpus/0a4ae55f0991df15a5c99e9531940a89c50208f7
./engine/tests/corpus/c201e19ecc81ec2a6688a8c98c29959f2baaa1bb
./engine/tests/corpus/767f59df6b09448f7f12fd135de9ce3e0eef05ba
./engine/tests/corpus/153f1da315263458bae227abb056a4102c2304ae
./engine/tests/corpus/b7657b2aba506aedcc03cd14083374024ea6d57f
./engine/tests/corpus/7946cbf117c8e91a22c5e12516a7c84933e2a87d
./engine/tests/corpus/fe2e1ee11c29a08a70c998e195d9bbb3ae2525e6
./engine/tests/corpus/00a382d954fc8e9b6657563841840726cf8803a4
./engine/tests/corpus/8100b3aa426574b110c4614284b9bbe55762436f
./engine/tests/corpus/377a1c332038a88f90ea435025c23c947fe9bca1
./engine/tests/corpus/cbdbb7372eed4aad321019e65186837a2c4875ca
./engine/tests/corpus/ee78d1fbf6e608a56ced7667838c0a7ddad214dd
./engine/tests/corpus/5f0c59d16048341bd32581b72d5c00a66d73a4a6
./engine/tests/corpus/e4a16dc25b60c417697a073b7a8879d19b91ff2c
./engine/tests/corpus/00b9b907e2d89bda4892ac4728a6a4f6a6934d98
./engine/tests/corpus/f194ea9e31fe87bf73ebc7e32d878d5e8eb9f00f
./engine/tests/corpus/174ab36e6864f5468c4709622be78407384e75c2
./engine/tests/corpus/90861b48c6275365560086cc1a6f7ecc16c16b11
./engine/tests/corpus/e299b7b5aad2e835f2fa17cca415ee465038f6a3
./engine/tests/corpus/9c57483d0e2af00db3c01ccf2d38f8f7433ed3f0
./engine/tests/corpus/de48d559a51c9552965ce45c8800d08fc0d17d21
./engine/tests/corpus/448ff59dc7f75baff636b5aa18c1246c040f497f
./engine/tests/corpus/98f4a1dff5be49e58e73797908db0cd6cf4d086a
./engine/tests/corpus/bb1f9832307d7e1805a309ef1e0891de8c9f6934
./engine/tests/corpus/57b6afd8444df0673e73415dcb5965b213f95362
./engine/tests/corpus/021c190baad76a9041a9d6875a859e9687ddfaa7
./engine/tests/corpus/7fb22c4050093721d9c2fe162b52edced3d07943
./engine/tests/corpus/b0c954d5b8d4e990081417726da63a20860dc7f6
./engine/tests/corpus/fbd841fd2c8c5c47343d4bb79912e18ed5f41a17
./engine/tests/corpus/db9c0c8c6e2faec377e769cc5cd3ae1fb81d5eb2
./engine/tests/corpus/a05cd383904924897ff365738a0032d45f4a0a60
./engine/tests/corpus/44c417a993ff3a10419908cdc80d361b554ade11
./engine/tests/corpus/430dfe5c6249aff826d6dd965061be9a4f366dfc
./engine/tests/corpus/0df890fabe9f6c9f343d0e08d524c4df1e157f5c
./engine/tests/corpus/cb82d44b29cece38ce0c65dafe6565e4c737c8af
./engine/tests/corpus/994b02516502f101fc990bf90abcc367b634a485
./engine/tests/corpus/482e5bd3bf49e76c268b0bd8cd08a0ed83ea1b0d
./engine/tests/corpus/3d4b013a1030dfbe93a12a2b0877ab980415b98c
./engine/tests/corpus/6868a676f3b1cc7599cf8b31e8310dfc63ea316b
./engine/tests/corpus/26404592b68f261bbe94b40ff70ba8fe615c06ae
./engine/tests/corpus/5493eb0bfde32ae694988b6a09f03ec297856a61
./engine/tests/corpus/6752d9a4afcf0f300f8102ed6e2a432fe742581c
./engine/tests/corpus/ff32876dd8ecc4ea1ae0c7029d0dee923fe39f92
./engine/tests/corpus/08390a807f753a431d0b263792b02ef26cedb2f1
./engine/tests/corpus/ff84d2f0af1264296dc4a664bd03873e30dc207e
./engine/tests/corpus/db3aa0bd500237ff9b1ccf6f8ef0a35b7ac63d3d
./engine/tests/corpus/b3ca282bc3d3dfac806e6056570c4d8239e435a0
./engine/tests/corpus/8d770d74533f86256a9c5d563dd9f4ed4436fe6c
./engine/tests/corpus/743d35ae79764c19a09809aa0a81e64e57a27b5c
./engine/tests/corpus/bed1b5a168f4a3c07117a5a7a18a453de5656e03
./engine/tests/corpus/bc60808daa8f5c0c2edc1e9fcdd686cda7d8913e
./engine/tests/corpus/778b8f136ee7836f600859e952771d2d820e9164
./engine/tests/corpus/240b978863e6b0a934e6ddc18088165f5751c539
./engine/tests/corpus/ba5f89c3e61a2068263d121aa9636b9e135c774e
./engine/tests/corpus/c6e9dd743d5e567fefc575891df3db0ee86a3f55
./engine/tests/corpus/aabfa0aa866d364f9d4424b7ae0c2515ddb13554
./engine/tests/corpus/e8a7b795c8679ffe88d2f57b3cecc60851230c66
./engine/tests/corpus/1041855780a5a46fc8ba2663f3b7d31763e71699
./engine/tests/corpus/78f2ba44b1c86ddbe31ef04b552cfd77f271bb97
./engine/tests/corpus/cc4609b4283205a9073d876f21e6926d9302fc59
./engine/tests/corpus/6d62e3490a162bceddd6282328b436ff82a43731
./engine/tests/corpus/84d1ff94767b1dd0ef982cbb7e4e5891c899de83
./engine/tests/corpus/2cc0abc336f372decfc3b6c0bde18d259e7b761e
./engine/tests/corpus/be85ae56bc967361551e4510189c1ea09251b438
./engine/tests/corpus/f01ecc393cdf031e864b66eae495432f93c39559
./engine/tests/corpus/eb9feb5ed956172e7cd8d53a0c052e14c9b8bce0
./engine/tests/corpus/d42e0f5dd0b0463d59727ef3e8695c508fee9566
./engine/tests/corpus/b3466320aa105696aca49040ab77d034cd669db4
./engine/tests/corpus/2b3f1c71ecb8e44d478496b89fc797ad8b60c919
./engine/tests/corpus/d24d36b3eaabc03c4767019b4755777f5a38c1ee
./engine/tests/corpus/0796c779fec44fd0c0970bf93e51876ec781e0ae
./engine/tests/corpus/f6076295fd43b73bceb1c984b913de9fb29b0edc
./engine/tests/corpus/8b93b02f4c2feadb12fbf40d55a9a05255cacca2
./engine/tests/corpus/915f810298f5452758c6a6054e583c7f95026bfa
./engine/tests/corpus/c9618c74307e166f1cf1c98c15db277d906a8b6c
./engine/tests/corpus/239e124ce1e46c0ba9117ea1113371b3498c56b9
./engine/tests/corpus/c5a60ffcc08f04bea4f4fd020f5a1c1c0a6b9e53
./engine/tests/corpus/378b04fbd1b5ce1934f14e17b6b8c97d0055e963
./engine/tests/corpus/1d7e663d724cd8d7024bf9c68c44c05a1180289b
./engine/tests/corpus/824b23a57b007272d855674e3170fa00ad4bbce2
./engine/tests/corpus/51fda501d9cd6489bc9c7e0044f8bdbe3995cf32
./engine/tests/corpus/e1d006ddeb84637e96119473c79546f0f1a75a15
./engine/tests/corpus/0d9d339dfd15588e92107dab74e872d3747be5b5
./engine/tests/corpus/219615696e68cc060e3292041142095ca566740d
./engine/tests/corpus/b22440442c1e14df86975bccad7f7e21035af76a
./engine/tests/corpus/e8c8ecc0447e1b0243e1def204ca8804d2e08584
./engine/tests/corpus/af3b9e462f55ba5fdd58e9d0a353f539c56734ef
./engine/tests/corpus/e17e734c03b983582e2f867456263b8aeafc8a85
./engine/tests/corpus/8f00e056c4c8e14bdf35fdfae6692f561b404002
./engine/tests/corpus/679d1b13bd7a7ac9633157667958355041583de6
./engine/tests/corpus/06526807e52a56a0b41c357300e09c5478337a31
./engine/tests/corpus/4df2980c0e34988f53cbacf04633b324ae922ecb
./engine/tests/corpus/d931a5c3a464ec4659488e9ed1e8122a88d0ed27
./engine/tests/corpus/902abd068655d6e4f0a55a3ff4756b7d87923fb6
./engine/tests/corpus/2d4a79a9d0dd8456b49bf77edc9c70dbe7cdbfa6
./engine/tests/corpus/197f7eeef051792d97fa00d0894ab00a6bd13b00
./engine/tests/corpus/ef5163c88eb3a760557664d0e44ac5ff0c43f2f6
./engine/tests/corpus/5531551656730123294c00ce8a950c63d0bb6f64
./engine/tests/corpus/ff4302a554707f6339b355449df9d5fec9b27c55
./engine/tests/corpus/01a773710be5f40c2b5cd7d72e8770157749930a
./engine/tests/corpus/cf24eb78e5994b7c7fe0e9d1113382b08ac97247
./engine/tests/corpus/c382e27692f56ccee8e80c6461e865819e2570e7
./engine/tests/corpus/042cbece91732fe04171fbb2f7404fe40cd256ee
./engine/tests/corpus/ccf45f82d41cf1449a02f86afb997067e2de74c0
./engine/tests/corpus/52c18ecd7a8cacb998f59a80613031f089db0a78
./engine/tests/corpus/8c00f865e25d2214ecf3f906a51443edb8184170
./engine/tests/corpus/225ad76639d42895d67d31bfb0cf672e986decaa
./engine/tests/corpus/fbc3b3e03a8f10a2636394d48969a177e8bcc919
./engine/tests/corpus/2e3c724351d25347c41a5007adf22f16f876c4ca
./engine/tests/corpus/486c51726e2308da48f9f68f62e69759409de0cb
./engine/tests/corpus/f24a343ccbcd849bae3b75199103f6fc95901968
./engine/tests/corpus/11d0c8fc993ae8cdb3c8f68cac7a55c11ea230ac
./engine/tests/corpus/7fa89829a6a0c200d851c1df9dd183eba2348a03
./engine/tests/corpus/bc726180a6405ab53bdc601371e73af60c3101b9
./engine/tests/corpus/6eff4a246947f8e7aa294256be582fca11e06fd9
./engine/tests/corpus/d0dbed2f7782e8f303248cae944fd15d76079907
./engine/tests/corpus/295c1591548607913f5b415d0e6def786f229be6
./engine/tests/corpus/dd1192a73dd8c47be34c4653b0837952b74f279b
./engine/tests/corpus/470550aa135a58d02b164331dd091dba8377678d
./engine/tests/corpus/8997289f129b892022a255a8a43166c699d971aa
./engine/tests/corpus/03ab991b50f9ca60adfc43b07d77324ac5882ff4
./engine/tests/corpus/a8651d7bb557a9288de96a6ab4ad76843e5f9cde
./engine/tests/corpus/e7ad82f78e05e381e4ef95fc3e96931091408046
./engine/tests/corpus/f26896438dec16d4451e95c4dc154fc2acbc0819
./engine/tests/corpus/42019b356ded9cdcaf8ef7d813f79fe0f2158bc4
./engine/tests/corpus/2c456fe7e6590ce75bf6b8d24405ad4896e99922
./engine/tests/corpus/6ac18a278bd97a867fe5193e9147a51ea7081c90
./engine/tests/corpus/942f37b87513b142dffaa45d1bdb0c270f50a104
./engine/tests/corpus/3929544ce93029e8c74901ff9f837dfa95b9cc3d
./engine/tests/corpus/2a4944b0a710f2212360a063b05a2463078de8ed
./engine/tests/corpus/efc3eb250736c75558eb0ce1643ab2693d77faf6
./engine/tests/corpus/7abfcbb7052b33a0965ea44dc310228705ea8f1d
./engine/tests/corpus/7e7c5d121ca89d26b6e0ab0ed8fdb6b4635067cb
./engine/tests/corpus/4f4139a387969f2cb713367c59295d2b223ce551
./engine/tests/corpus/880fe48982488ccf2b235c3afca318414cc2e942
./engine/tests/corpus/e9ddb5d97b9a529d64bbe30481715d8843f5fbc0
./engine/tests/corpus/51f1883a0c4647bd639429910de9d5107a9be170
./engine/tests/corpus/bfbee8debc7f62b5c676b5c84d564483f6c10902
./engine/tests/corpus/383f95f970d2df35b02726243d0ce9dcf2d731ba
./engine/tests/corpus/6a31843a0e64314e22f08a52d794f1a7d7b7f860
./engine/tests/corpus/06e2dd1c1eee9700f0cdb3b59e8aedb6661bcbf7
./engine/tests/corpus/bfaade013734c03a3e94cd5d4a2384917ff4b33d
./engine/tests/corpus/47c0f95318c08b08ed2de6dcba5735c56b1a5dfb
./engine/tests/corpus/67ab02056b743cbfc05075c5aa8267378ccb6eb7
./engine/tests/corpus/0f8eafac3520570650596634678f9d40d2b862da
./engine/tests/corpus/9e47e8c10a7e7118dbc4c25b363aa8c08b8b1431
./engine/tests/corpus/7cc46e9c50c1818cd71b701ba72779a0a3fad78b
./engine/tests/corpus/6a7049c2f47dc8ca731c2d9a50ec3f3587eefe72
./engine/tests/corpus/1e855bf99591290167e9ac82ad0a5c10bc0eb8ea
./engine/tests/corpus/9c5552ea9d9a565f6ff4d92354e704a7d22626c7
./engine/tests/corpus/e625f5dbc1405bee84da9baf3dedc347f6da337f
./engine/tests/corpus/935722f1a61663f301caf1c92aec2e1b5a7513ea
./engine/tests/corpus/40e03b6c2cf9597265c72bb62c3a4ef9036cacf4
./engine/tests/corpus/931ab51badd3266ed1c403a5816d3fd99f7d354c
./engine/tests/corpus/f80262dc1ba7d9f4ddeb9de2e60ab0cbc215e89d
./engine/tests/corpus/7b607e0afb72f5f225c5eb0407731bf90fd6eca8
./engine/tests/corpus/343f0287b6e7976422bbc01a9592669dadd40f3a
./engine/tests/corpus/e6b8f312ba6fb561ed1785ec7a770ca6cfa23e29
./engine/tests/corpus/b3042d6f3563a4be0a07346238cb2dd8200afde1
./engine/tests/corpus/3e530d0fa759c824ccc5d761045da0aa9c9814d3
./engine/tests/corpus/aa37d88212d1dfb4b92607fb37741a7a16500ef0
./engine/tests/corpus/6c29675c728a8d3f95e668412f2135c8347ce661
./engine/tests/corpus/952871ee199198a3ce7260c73e0861f90cfa5678
./engine/tests/corpus/2bae1d415c06f25f9581c8b45eee1eef5e9f27cb
./engine/tests/corpus/3e12d88a528a6a8f0c35df9d603ae477df8b0537
./engine/tests/corpus/1515bf29daa5adaf28af2a9316a3cc3311d3d63a
./engine/tests/corpus/f11f4aaf4a18120248a0ae4e06a55d17c345d820
./engine/tests/corpus/833df5bdb044b3824059d0c8fdecf828618c82f5
./engine/tests/corpus/97d264a724cc4dff5b1e8eee039a2614ae8850f8
./engine/tests/corpus/3ce7b8ff23d48751b2421bfaa61dca870a47bcb1
./engine/tests/corpus/e0b2ac67b12b4b51869962109a795867e19eb9cc
./engine/tests/corpus/a94b127bc63b8b84fbc73e5bdc98b4b10d07e734
./engine/tests/corpus/86474ddff1ffac277c09a1c605914eb6acfcbca8
./engine/tests/corpus/f91c291a8a1ad0cfd76fc29fdeaf25c872d5c59f
./engine/tests/corpus/cd5f2e9d292bf1279d1fce2553647aa3e1ebb521
./engine/tests/corpus/77fd869e2b1b911d007c87b12c11b8e1c3f49b52
./engine/tests/corpus/cd60b64b5463aef30e726b6ff002fa0eead06973
./engine/tests/corpus/cdd35c5575298f095e43e2a03e5f16e9e4deb54f
./engine/tests/corpus/919b652e1004d7a96b44f5a28a28a94486203072
./engine/tests/corpus/6a873301af7180720518d297f31400ed041b3dc1
./engine/tests/corpus/d5d213cb0a65ea9c5bdc1b5dd12a5ff1d75e8cb9
./engine/tests/corpus/7b9b3d317b097b5eb6a0f03513dde54a83c2d0b3
./engine/tests/corpus/1da67a3f123f91a29661547d589eadc658f53df4
./engine/tests/corpus/2d7c855e5a2dc9abc261927b2eaa0d1a62cc6866
./engine/tests/corpus/06862f52c183ad49b793686b0cce648040eeb5b7
./engine/tests/corpus/df92bf28094d0377b09af9df2d86a1037b135d2d
./engine/tests/corpus/638a3654a2d35f1ee4fd31113e410ad73967c438
./engine/tests/corpus/e69bed9398cd33dd5919ee93b06eeda6ef292b29
./engine/tests/corpus/b3e23cfd5cb006a207f0d1cbae1d36a341145174
./engine/tests/corpus/709bb381ba51fe472eef4f6717a10ae966ab5f36
./engine/tests/corpus/e970bb356eedf9933497f8186d75a06c97854626
./engine/tests/corpus/6c882bb13eadf6e25f5653715addf56f7a5c4053
./engine/tests/corpus/1fc86f664f68c4ec29ade946f0d05dae35587602
./engine/tests/corpus/fd2b8ca9af4ce46c8bc36330c12acc9b4166eaaa
./engine/tests/corpus/bd86de5a45d999de5b0cc37c3710cb049d1d288b
./engine/tests/corpus/5470864f7b2452cceb321887cf0c4c75c9b91b3d
./engine/tests/corpus/17d2f12dce86a56c77fbcdf7c21ee45f9120b57b
./engine/tests/corpus/7269c1852357cdeeffe6d38b06cc60b39bf5d3f8
./engine/tests/corpus/5669ae53bc20f8a26cbd28e211b8a3438b234e25
./engine/tests/corpus/898b24aa4d2fda8088dad0555d6be55b0e1157ea
./engine/tests/corpus/c6e70dede9588b92fe9743d350fd96d7993963fe
./engine/tests/corpus/ffdbfcfa74bc19c585b2b524cc56c998f4e31a0b
./engine/tests/corpus/9e5111456523dc6d312099d5cfebf76d558007c2
./engine/tests/corpus/ca0d4dc067128113247b3ae729c29db41a89e663
./engine/tests/corpus/18afb92b48ef378346b2e0a17d9e51bb8c3d4f54
./engine/tests/corpus/a46433a465f77650b347009667cc513784c87893
./engine/tests/corpus/a2850ab4c6c65acf09afa174f525c8c8facc872f
./engine/tests/corpus/f15cff0d77f88edb6ee39066eca758b309f02ced
./engine/tests/corpus/b766bc7bebd0a721540a6806ba388b922d517fab
./engine/tests/corpus/8318a65f1bf68cf6f72e9bfbcc236611923b519d
./engine/tests/corpus/bec096dbe01e8e5288cc75bf7336540f0f26a5a8
./engine/tests/corpus/7a39cd10915427e70b15dd8c9b22e94aafcbc512
./engine/tests/corpus/7aee77b8a8f7a01d3b396285797720ec4a5584d7
./engine/tests/corpus/11474c9db44fd53611c81bb1e0b1e768938880d8
./engine/tests/corpus/1721ba1131ce368f630726f8e591f2f9fa64752f
./engine/tests/corpus/1dad66f44b7be5f905fc04332db28ac5d26eba93
./engine/tests/corpus/8b949cbc5e4b89683010accbacce6f45dbd91034
./engine/tests/corpus/8a4f9fa373057c723f8e8d88650326378218cf58
./engine/tests/corpus/53182e91105ca748ca144263554c254592e07b52
./engine/tests/corpus/79a5d80682b03b15dedb49f6d5ab417729fd32f5
./engine/tests/corpus/670d35bbdaf00ea11d01b5147dd57b4188de5268
./engine/tests/corpus/be51b271b88f83e88791e9d70c91a31905e2f9b6
./engine/tests/corpus/f8e9bb0d468400200be4d602d424ba0b48769761
./engine/tests/corpus/31a2aa6d3612b304d835465aa8d783e7ef48ed60
./engine/tests/corpus/83dcdd75d4c182642f838459e83a5f030abe88e3
./engine/tests/corpus/0a6741a5347b1db0136cb8741d25412f806c18ab
./engine/tests/corpus/d37b8ac7ddd0ebb5ce06816140ad90164f2c0486
./engine/tests/corpus/787409f3fa157eeec2ab9456ada0e107077c66b6
./engine/tests/corpus/597b6a1ca5de6fbc42b41066c2cfa436464e195f
./engine/tests/corpus/28204c17fc6d5219f63bab53bee5a995884793eb
./engine/tests/corpus/7cb4d10f561249856e18d9a272961727b0cca19b
./engine/tests/corpus/64b89a60009ea85065affc1bac0ae5262712ce0d
./engine/tests/corpus/17c6332f627fc2e50e0213a880f6b3e76db37a77
./engine/tests/corpus/b1a35acd1c7ec36735181745474c88ff832617ae
./engine/tests/corpus/8e3486e89ee031874c8e86333b0ff615c635b085
./engine/tests/corpus/d744787913e6d773afc5e429210ef3bf78599112
./engine/tests/corpus/2ad72acfbe5e7415d2dbd8f8b755d2516aa13fa2
./engine/tests/corpus/e828dbbe2ebef68a1f6847fe77e0fb5cc05d7ea1
./engine/tests/corpus/ef70ff3a14e3b5663564c9eb0bad65758f07bb67
./engine/tests/corpus/fb4911034ff0da6fbfaf3309103567687ece3574
./engine/tests/corpus/c53ca949f39e2aff4ee064d076025c22a29928a8
./engine/tests/corpus/add5a7d9bbe1243432d575cfe59d35059a82c44d
./engine/tests/corpus/84225485f4d9314eb712ebe6f6a0553367e6f2a7
./engine/tests/corpus/b64d295a4ca814d3951af385b62be724019c3c5a
./engine/tests/corpus/7d9bf2ef931f2bcc9ed37800382aa71ccb733640
./engine/tests/corpus/4911760f4678d0ac5cf17bfbabbaa6cf8e8b7a3b
./engine/tests/corpus/99ae66b09aa539497338ee8f1cd6e84c24e85771
./engine/tests/corpus/561a4ae12922891853a94e1ef0b5672bce6cb74d
./engine/tests/corpus/b68e4069bc6c5959597fd9bf6412d2344f5bea09
./engine/tests/corpus/adcaefcd0e0eb92f4df20efae65a6e7c01294eaf
./engine/tests/corpus/5be78f0b8c7784d1617aad78306a4e15be7bc56e
./engine/tests/corpus/1c9cf246ad112f9dd1343d8df7987f70cb5ac9fc
./engine/tests/corpus/e1f980e382caeb81ba46f62f3e143b7b79162acb
./engine/tests/corpus/8d3b19c31c16f8fd7730a75ede66bb75a4aac7f5
./engine/tests/corpus/d10c453702b75ebbd72d38523b10d985d3bfae80
./engine/tests/corpus/b35521e9ead8ca343a0d623861817a2785672ca7
./engine/tests/corpus/788576ab8ee58e3a098a4fe894de8973c136e1ba
./engine/tests/corpus/f62ba67ce426e31ed685f6513cd162dd4f71ea41
./engine/tests/corpus/6c1f919ff70c4bd5e3ac3db17e8d837aa43b91c1
./engine/tests/corpus/36ba9f27f7c2a1b6b7e498613c19723edf57e440
./engine/tests/corpus/d3bd9f28fd24f8fb7f65cb4b05c5451ac32380e3
./engine/tests/corpus/47e4646f79124af468b7a4827e4b1aacb4e40e26
./engine/tests/corpus/b9945d61e3ee396ce8986d8f5d13444294175c27
./engine/tests/corpus/d17b47ad510f75fdb4efb7549a9b6b1ae65b22e8
./engine/tests/corpus/3c9bd3874e112c3e00fae6eb6b0f381e2d929761
./engine/tests/corpus/260851a00d4eb464b0b27614152c5d778946f1aa
./engine/tests/corpus/3d354a63c972c77eaf724cdd51b8c4cbc6ccd682
./engine/tests/corpus/76ead74ce3733e7ea85d17e46f4350596ee6c672
./engine/tests/corpus/bf3f8519dc741ab5adee9c0931c7ad106be79a78
./engine/tests/corpus/2f68546145d2c354262ef1610cc92ca939b1cf46
./engine/tests/corpus/f68374362b51b15a29aa1929db6ae7e48b979264
./engine/tests/corpus/2546c18b7085a8abb014efde427ae66a546e671f
./engine/tests/corpus/2d975237ab665b61c47b5eeaa0919e9ae4fc2b41
./engine/tests/corpus/fe61e7ded2cb529c168c824afba138e0714142af
./engine/tests/corpus/e0118a509d0037df74b9c434a6f84a48b6566193
./engine/tests/corpus/ace7278ab7d5c6be19cc892781b125f530d7863e
./engine/tests/corpus/ce802cea0618d5818891e8603a4caee690dc2ea5
./engine/tests/corpus/1791fc015d99b82435772345838b1687c76ab756
./engine/tests/corpus/e9ffbea71c312a5c68cad04a4376320fa42e152b
./engine/tests/corpus/d0ab30d0ef47e5be2cda7977a5bc6af306cefaf1
./engine/tests/corpus/cbb31ab42aa29577ae07ac94ed99ff96500c11b5
./engine/tests/corpus/3c6b591d540e1d6b682eb60fe60a841e1bd2adcc
./engine/tests/corpus/124659e77eb8f43f455f694e029ba8f263cb33a9
./engine/tests/corpus/714a4bafb58becde9ad6df1b0d058a27ef9bd4a1
./engine/tests/corpus/20de42bcea343eda2edf322a5da0d39023ec8627
./engine/tests/corpus/8a5eb8e5dcd613567a7c4b24495c54b8139179c3
./engine/tests/corpus/20b57f9607aa01d5026fccf12e8d91efc0bd24d9
./engine/tests/corpus/b4df9cead972c73392fba8bdf564943819416405
./engine/tests/corpus/4fea73285694890672694a78d8fb6f0d7242a0a0
./engine/tests/corpus/a9a346f8ab2e792d0c7af0c3183ab3a4fd525e3f
./engine/tests/corpus/d04ab0deecbcfa8ce896e4f99d3c952a27b7b556
./engine/tests/corpus/e330775f4e42968653b42c7492c28b0992f7d1e9
./engine/tests/corpus/f35b08b6be924776193e5e7b26b89faa59a64be8
./engine/tests/corpus/8d4604c4f2a237422b0eafd3284cdd917d4552b2
./engine/tests/corpus/75372800dc7b80c52ab987ad7a5e909d9767064b
./engine/tests/corpus/1e7b788f6ab4c1be0961a80bf9b5c4f6d171be34
./engine/tests/corpus/e1a98c2e6efe7e3382bf130dbc1cc54f644d22df
./engine/tests/corpus/30199f51c5c9f6c159562f77f98a8156dabf99ca
./tools/mac_practice_build.sh
./engine/tests/corpus/80e34ff2e689e9cbed83e69043d09eef492d1735
./engine/tests/corpus/3c0a0d9f80589a3fafdf25343e4857a29532b12e
./engine/tests/corpus/3fd2f61c6efa1e44f994803503a39622710f18cf
./engine/tests/corpus/e4544c5ea32728e6650e6b766496c3f1375e8592
./engine/tests/corpus/d5169420ff3f32d0d2341a8e229eae0bff0b48ac
./engine/tests/corpus/258694c8734e01d80c3186918dec36e2fb9dbb94
./engine/tests/corpus/1dc53a22a3c869ecb9d9c14c4408b498e8b608bd
./engine/tests/corpus/a6b3981f38e0dd2210e441c12f9f0949a3154100
./engine/tests/corpus/7c8290911d7f343c126829f8c178b75a9ff2871a
./engine/tests/corpus/c8caf5d7441756836a31dcb4fa72360e4349d5ef
./engine/tests/corpus/8204e90f873898f44b44d0d8d58b84f7528352fd
./engine/tests/corpus/8ab27148c939c95da61262709dcc4593069da14c
./engine/tests/corpus/e25ed3fe7c0872050b2f091dab7e378241507427
./engine/tests/corpus/3698f59661c3ed4e68bd80b5b18b213b03c4378e
./engine/tests/corpus/2bc1ae8dd712bfced9c84ee4b7a87c30b15e2632
./engine/tests/corpus/7c990d9df79dc50c0aa1d44409a7c420d1b54071
./engine/tests/corpus/15445b63a39f366e95bec03cb89f0e6f57185e38
./engine/tests/corpus/ab6de719b25890e59dd474f85da38258869bc695
./engine/tests/corpus/303dbcec133b5334ac8213f20992e805069247e4
./engine/tests/corpus/b1f265b1b7b8b1c5d8322ce735ff2a5d544c0180
./engine/tests/corpus/b897345c7af95d43e2b03c09e57f28c002dce077
./engine/tests/corpus/01013ac1c1f3460aa1e2ae5f54442f02137eb8c8
./engine/tests/corpus/32b70c8815a00a70868eca8f150427699bb43b20
./engine/tests/corpus/d192f449b999045ff0cb638aedc8be60699b9131
./engine/tests/corpus/e8e60f90fa11224d258f4d9f4ff241fd6b468aca
./engine/tests/corpus/fe0fba3d07a1c5d7f8cce90609c0335645ee3383
./engine/tests/corpus/dc1565154bcea0f725f906da5eb2bd4c47547d17
./engine/tests/corpus/206d050cb4d8065d9ff25016945839b7aad80b3e
./engine/tests/corpus/532306893d6ed85ce1247e282990bfc667c4c790
./engine/tests/corpus/44f4081e34e787bb1ddb2c7161440efaeb5d96c1
./engine/tests/corpus/19b08633755eae68b816dd985ac906a5ff8afef3
./engine/tests/corpus/c59d158c0e96eacc550b61d781cf19127a636ea4
./engine/tests/corpus/9d9bd41bb5862a948557b63c404e670c35470ddd
./engine/tests/corpus/7479367a948b9bc8b8748c6887e47ca7488f1711
./puffer/config/bloodbowl.ini
./engine/tests/corpus/83289aa292d9fd5a28a3e6ac266d0de1dffa072f
./engine/tests/corpus/4c17993e9fd8972931959ef4a9269361490f4b93
./engine/tests/corpus/85b70bed5df07371fa8993b86a0969ede1761625
./engine/tests/corpus/4e3aa2945e4350cd02848e750ee6d2a9fd106e20
./engine/tests/corpus/8a83f7b75b6b4f6e5be51b03a9ff11dbfc3599b6
./engine/tests/corpus/f6080b865b6f9a6fa5376c5426a3d8749e31a5f9
./engine/tests/corpus/f016ad0feb3b0f4b1d3b1235f7050abff12c8c7c
./engine/tests/corpus/b6966584dc75a32656f9f4415faee27cfcfb5f2b
./engine/tests/corpus/044cb2cad0127805c08272e3042713c37b077d12
./engine/tests/corpus/5c92d895a47575bebb1966eecfb5f27b4b274b63
./engine/tests/corpus/f11d1ccf8c0141a5d31690658c22b11016275b8d
./engine/tests/corpus/022f36e30159ec10fbb94087ecce83a62dce33c4
./engine/tests/corpus/3774753eded8619249a70a1ee6126416eb992a5d
./engine/tests/corpus/2f74543e117cf860e56da4ceef5e06dda192feb4
./engine/tests/corpus/14a454721bcb553f7cacf22047bd1edb66a2ddf3
./engine/tests/corpus/50ccc9f5141333bcfb3435eec36f77b4ebdbfc83
./engine/tests/corpus/ac8aaa3cbbe2c914b631ab34688f72492d2a9e98
./engine/tests/corpus/95ac03c93ee6e6f13830abd997e21b760d98731d
./engine/tests/corpus/f8ca0dbbfe668005bdadf615665faabab95281a0
./engine/tests/corpus/af835bb7c01fb0e0716b5388bdb330a75ebd7b88
./engine/tests/corpus/7721a27b5838fc4226c20a248e61de62340b66df
./engine/tests/corpus/3f63c47e20a3d6b44a44312468aeaf4ccf060382
./engine/tests/corpus/57002608f6032a88c35ff6c10fc5b7ab8bd544ad
./engine/tests/corpus/57c3a3f18cc090e47df26e490a488d0a340a890f
./engine/tests/corpus/335c116f05e4d340506693d4afbc9bb05383d278
./engine/tests/corpus/a80648f84f25ed82fa639812f2c0db8aa487837c
./engine/tests/corpus/181e991800fa7dfaf1224adb90ca9fc022843b71
./engine/tests/corpus/69f04cd5e9522f3ef446c58b44234e3ca7741ae5
./engine/tests/corpus/b55ed01be9d35b61f952372ce0a3fdb8e14c58d0
./engine/tests/corpus/ec0b0b1314d31fe1e7ac4e2a415eb8afcda55119
./engine/tests/corpus/06ea190db9d04ccd58fbaead11ed2db3c5f84397
./engine/tests/corpus/2a2d685c6f978880c1bd009d5b921cf1073c6567
./engine/tests/corpus/520e9467f929ed9133813da27794c8b9029934f6
./engine/tests/corpus/f6f92a2c1a8105de499799cf91e7678126281984
./engine/tests/corpus/5c972f5a2c38724d5de632945589c12ac8a4f8d4
./engine/tests/corpus/e2d7172741b981fdec4c2de6d0ab851d1d07d624
./engine/tests/corpus/e94a360e551cea857b529a58e1835c48c13561c6
./engine/tests/corpus/26443e67ef3b0e4531dedb558faba65c65eac125
./engine/tests/corpus/ab34085e3141806d02a865fb37c5e8216cc25872
./engine/tests/corpus/42908162f2c9d4dd6de0e063cff216f1da65ca93
./engine/tests/corpus/920cadbea39a79cfb1d722295ade83696f9bd60a
./engine/tests/corpus/ed205796e846efa631e9b68f7914ff465f212867
./engine/tests/corpus/84b329c41ea4fe877cec79f9466349b7bdee5c83
./engine/tests/corpus/6944f6d8aab1947874e712bcb641670b7a361926
./engine/tests/corpus/35f088e469705e05fc6b3c2e60f282bda7fdeeb1
./engine/tests/corpus/5196fb704d47e773499912ea2f5332674f14326f
./engine/tests/corpus/215b567cea7c3912cf7aacde53eeb825f3df92f3
./engine/tests/corpus/d6cee8c134b96458cd8985026f914ff66ff108b0
./engine/tests/corpus/1fc4e0d1d9718b4afd7e2fed8edb52b6d42caa6e
./engine/tests/corpus/f596fce3cacb16a9e6c80e0837098d936a46cb3d
./engine/tests/corpus/ddaf526f8367bce47539c2360e634534fa996bbe
./engine/tests/corpus/0f2870053ea8b1db7b3f910eb4c7083af80ab5e9
./engine/tests/corpus/7cfb964a0d5fdd9d489fd78379ad9508424f8891
./engine/tests/corpus/83eacf1573e3bdf88bfde33d168084ad1afb52b0
./engine/tests/corpus/4147fd39ac12b8fbf30cc2124a7a0026f3989d07
./engine/tests/corpus/c3dfe56d0cd4bfa8fa89f793b67d8dec9e7797b2
./engine/tests/corpus/38132074f3787c029d2602517be2fda463b567b2
./engine/tests/corpus/baca0123a11ca472739c3a567ffdb972dfbd4a9e
./engine/tests/corpus/c658eefdd0985f8dfb020befe5ae81fc7a48fcc2
./engine/tests/corpus/43e964a339af562c2b2ef573bd92a0731df05c21
./engine/tests/corpus/c6eda6ed938a86d928e5b3877256f5dd18d75bbd
./engine/tests/corpus/9fbcf55355b1ebaa6ec4ce10267371946c7905e4
./engine/tests/corpus/2563267e2cb9d8fd92c5f76594a4af8c5ae5aebc
./engine/tests/corpus/e04fee6b888adb66779fac77b5ad3e2e4bbdc5a9
./engine/tests/corpus/8571e8b930cdc9c3f737ab873fae28f483b703c7
./engine/tests/corpus/610edb9b90d0dedd484da3824c90d00a2296022d
./engine/tests/corpus/fb35f44e33e00210d09b1a922c527e6f32741db3
./engine/tests/corpus/30a5351605f2ee5dd62ddf125b9b56ab66077a89
./engine/tests/corpus/32db75dc6453c307b8f481f99b1fe328afafa4db
./engine/tests/corpus/77144a632f77e4cd67ccc6e7527772d31afd42d7
./engine/tests/corpus/c42b429144d0d6dce2bdfd5b090cd96b85ac409a
./engine/tests/corpus/0150d6a90b907e7e2d06e2219529950ecbbe2bc8
./engine/tests/corpus/c7c125c2ff42558b9ec1ef5f3865bceffe8914ad
./engine/tests/corpus/03faf389cae50eb34639035ab366c3f984ad5096
./engine/tests/corpus/373f3c8db379109457f8a43fafaca7f4466b0714
./engine/tests/corpus/6666ddc326c5bfebb8499d52ccbffd168e7ac48d
./engine/tests/corpus/e8fb7e38f2b5c53a6526cba0efbbe065bbfe31f0
./engine/tests/corpus/73b92b018b7f6400ea0fb1d03fafaa1ec3e68746
./engine/tests/corpus/3d248c8db5918080d90a2b21a1bda72ac4c7e75e
./engine/tests/corpus/c0e746f3ab33af1899becef36b2b7e3507c67368
./engine/tests/corpus/ed580efe53b5ba177dbca397588720c31c500457
./engine/tests/corpus/62c84e56f87abcd4f206b54385134e3dcc6d6e2d
./engine/tests/corpus/2b56fc6275726f383464a2fd75f6d587af166388
./engine/tests/corpus/85b031d47ffde8d62b8ca0dba7399e61f229bcea
./engine/tests/corpus/ef72da682bc9b8eabbd34c1fe10630bc5d3daf26
./engine/tests/corpus/3a20672459d698ec9eb307bc1a31d67b2c6ae31e
./engine/tests/corpus/b8aeed133fc6d073d4301c993e1292611e0bf8a4
./engine/tests/corpus/518858e36b6b960cc22226dae4a9cc09e768ea62
./engine/tests/corpus/c7075bc17b149901a342ad0b83e0a3019883a9f5
./engine/tests/corpus/d1b96a2432f80d8e0dc70658b67b3a124ba99a50
./engine/tests/corpus/12c81fa26df4fcf3ad68bc515597ecd7c3c4541d
./engine/tests/corpus/a4d7feb03b6580f927d5f0129e95a8aa841a957c
./engine/tests/corpus/aa408b85e0acb52c7aef9e39024cc6c298bab5cf
./engine/tests/corpus/2077c1b44cfe1fc95088585dd49d46acc205a96b
./engine/tests/corpus/8472c5952c1ca72aab6b546c8d3468e459694916
./engine/tests/corpus/24accde2a36d1d81bb38f4b6d5c533ccd8427ad9
./engine/tests/corpus/39c4604772f03c01ffd54a689fd007a6c5c4439b
./engine/tests/corpus/151b96f0e1b6e5ae7ac00da6293ecab542f63508
./engine/tests/corpus/8db095a656b29672122ea3dc5381fa8a15871400
./engine/tests/corpus/832327e47d6e3390571ae58914b17e76b60085c2
./engine/tests/corpus/07a279343665fc20526d9521c1e0382945e11907
./engine/tests/corpus/7ace36298fcf4274846c0b15b311901960ae8faf
./engine/tests/corpus/d9563d4c27a6a78e23336b7691e13ada663d2f1d
./engine/tests/corpus/daa18a8015da8ac8fc9d8aae78a7405d1aeeb42b
./engine/tests/corpus/693a5f094701a38c7624b4566e66c251cf381cf1
./engine/tests/corpus/7281361af63b970cbc202908a08ed61e23cffaa4
./engine/tests/corpus/517eedb5130c82a7db86c1b7ece1f13f9272a6d4
./engine/tests/corpus/1ade60ce4faf26c8c9b367763b669ba7350da9aa
./engine/tests/corpus/5ce80c31b97a4dd9c5bdfd3ec7b095a3c58cba95
./engine/tests/corpus/72fcc257b4a5a948dcfd38dc9494a3964c1a9bab
./engine/tests/corpus/56b2cad519260fc6365a9c134f6e1edcd6568259
./engine/tests/corpus/ed04f7f3cfc904e99e959489392def6a3f5757d2
./engine/tests/corpus/81ec69cd1a5c99b982c720801487885858b66c03
./engine/tests/corpus/b2c2fae1f1c55df1978fb4017150f8d635d4445b
./engine/tests/corpus/2a92dbc6984ce7fe20a258ca2f969fb022dbf6cd
./engine/tests/corpus/5b8d3ee4ff323e0cc83587e2570da066b9e34fe4
./engine/tests/corpus/155fbc341b471b4d72b23e6a3813b432cd63a09e
./engine/tests/corpus/82297c0c344b0142501811f3de84e576de5b7907
./engine/tests/corpus/006ca1fe4b2defb6cfd0ac25dd18264b8028a9af
./engine/tests/corpus/e381703424c8c848a265c1cd225e8b7f95cd1f06
./engine/tests/corpus/23c2244ad5bcbed3f911983d902e46548bacc4f0
./engine/tests/corpus/c078cdf4a9fc04d89cd07faa564408aa4b4e5a0b
./engine/tests/corpus/a4e42bd0d3ac8abd2f27ff4e68d446009f29288b
./engine/tests/corpus/5b18c57c21c2032f8bd0284b75afbe0ca40e52b3
./engine/tests/corpus/874adee15ea24294a94c8c74cb7c87eff784bfdf
./engine/tests/corpus/eb18058d76686bbc03945ba302deea527499c14e
./engine/tests/corpus/03574631f3b365e6eebbd04bd8caee9acf14a79b
./engine/tests/corpus/6ac62c297ed3cd22498d8ec280bcc9cef6226236
./engine/tests/corpus/a4fc1642cd3696eff3755da93e91257255a8e804
./engine/tests/corpus/178241556c7a7ca38aa9b81174ae8a154e551008
./engine/tests/corpus/f35d32859dbfdefd19ef4c4dc3d6065f1c78c219
./engine/tests/corpus/7cb1a0adb92f33dcc146e9fcbe78606ec7354ba8
./engine/tests/corpus/27a9cdbb5e5dc04c4a254230b67f7bd23cabae25
./engine/tests/corpus/cd1ea734e33c69a479f8c5da8affccb9544b6289
./engine/tests/corpus/701e8e99f79f8752e1253db838da4084dddf25a6
./engine/tests/corpus/b5a831cdeef45975afe1a581e0cef6977f0d8db7
./engine/tests/corpus/500e6f10b0b44c77fcce579cedb09030a61bc613
./engine/tests/corpus/eaef0e57d845fce97b2f9eea4b5905b04121fac5
./engine/tests/corpus/1d23bbde81ae39591f70d1e5c724d1c55896afa4
./engine/tests/corpus/129332b25d89ce77de522b3e855abbc9a034fb2b
./engine/tests/corpus/c77d44bf8c415bf10fc66399f494bb670550a8c5
./engine/tests/corpus/5c7617114d745eaba40a12a389f421a3245fea5a
./engine/tests/corpus/3fe7521d622fa9bfb35703fd38ef17fe0321efec
./engine/tests/corpus/a630af5cac804a6d4bb1b9edd757c8f21f5c8a15
./engine/tests/corpus/70eb222922f11126efe70eeb3d0c5ea90cb7e4f4
./engine/tests/corpus/c335ddfb8e0eaaf4df395dc6dde932aae0b88bdd
./engine/tests/corpus/4673ca5bd7dddfb2b0fbd0bdc4653ba4e94059fe
./engine/tests/corpus/78b9a5a4981d3cd2ab7c59ead191dbf0e70f6ccf
./engine/tests/corpus/6c00b0a53d820fb7c11bfa0effbbf7c2f5679356
./engine/tests/corpus/2788e0a9c64c63e1435423f7bf9a998520a7a6e8
./engine/tests/corpus/4a0d6fd4b9f2572e02ed6404ba803fe7297e7d00
./engine/tests/corpus/c33b864fdeffb3d6f9e8c1affd5873ddc51fd643
./engine/tests/corpus/a34f75fbe3c4bf722cfab7bdb44095b4d29f7c9e
./engine/tests/corpus/a277ddbb8007112ce2158eca3698b552baa6a132
./engine/tests/corpus/b7e4dcc481418fcbeaf9ab85b75f4ee96040f1e7
./engine/tests/corpus/1823dc0e5315386ced39e3b8e3c410046ec3944a
./engine/tests/corpus/5d8b90541d948d54df3f51c8a157195ce47875b8
./engine/tests/corpus/8d291a9d916de1b734ebfd231a24294777acf65d
./engine/tests/corpus/9aec85cbe66cccc95e2f72c7f5a74739693a94a8
./engine/tests/corpus/bab1ec0108dca37449b7f37593e6f26dadba3973
./engine/tests/corpus/2932dacddd49a7931cba773d41e0839a5c7e60f5
./engine/tests/corpus/5f5a16954da2c56c14f7658848188d37d9b46b39
./engine/tests/corpus/b704d7800fe0859af0837ece7e3090633f5a37f5
./engine/tests/corpus/237e77a08183bd1936b6adfc259fe377bc0abb10
./engine/tests/corpus/c700ba5d98f1323d9d2f605206b0f40243f00b26
./engine/tests/corpus/9db5ff109e52fb0a5904a77f2aa11e1973eb13f7
./engine/tests/corpus/197844fcfdd40ba6e0e98c6836c9d49695e3c99a
./engine/tests/corpus/d5f8e0b0bf83b060e8c9727e8e487913ebec8b95
./engine/tests/corpus/9a50b0f9b864e8c6762804fc78fb706df151a527
./engine/tests/corpus/525cdeb63c4518ca15c25470c3ca1b164d2d6b08
./engine/tests/corpus/fb2b765278145c3be073df13e25075548c2d964c
./engine/tests/corpus/b451f6aae8ebd106ecbff739f94179458f057d94
./engine/tests/corpus/086fa9d3db53da55f0a427c76cabdb3cbb5401f9
./engine/tests/corpus/6d1f7f050a4304e457199f61538c493c5f6a9b89
./engine/tests/corpus/67948da0b4f562c8ea31f368a4ed4181e8063f2a
./engine/tests/corpus/20252ba9d92256ecc62363990d38f683c038dedf
./engine/tests/corpus/605c052726f12eb7d51fe8849b1660aa7c2e8df6
./engine/tests/corpus/4cb3fce928006be19d912a2f32c9495ec09b30d4
./engine/tests/corpus/2d7c5acee9374da2c95fb296e7979e44e82200c0
./engine/tests/corpus/cb0bb4665168afecd42e8818c11b7c998ec84586
./engine/tests/corpus/f27301e4e65f4dc089ff9127f4667187cd511e84
./engine/tests/corpus/68856577ebd8be6a04115bc1f8ff113730175f81
./engine/tests/corpus/08b6998e04d6a05b28a11972b5a3fe9180007145
./engine/tests/corpus/20242ac0711b36b17d69886a8e788cf944bbb9cb
./engine/tests/corpus/207383c723ee2b81d4d4ac4c4174adefee46fc69
./engine/tests/corpus/a1d244f87ef1fc89d5093f78631f7bc1a0a6d075
./engine/tests/corpus/a8b5795e88a008ea962a612725afc4c2258818aa
./engine/tests/corpus/759dc75d94c68bce34da493c8dd2f20912e0d161
./engine/tests/corpus/b24fa949bb5ed32962f125b51db600db9d44d516
./engine/tests/corpus/e0f2c4ffc35fc351eca2174f84bb9f6b97f5d58a
./engine/tests/corpus/1d200d48aac4a46a57c806e8f7e9789e07265baf
./engine/tests/corpus/aab2de00e482009fe1f5fe4d189b71e2c2acc83b
./engine/tests/corpus/8fffdb3d0d5ca6a432703aef1913a7a7323a09c9
./engine/tests/corpus/b9f471ea967c5249dba81fd89b8a0b414b72776c
./engine/tests/corpus/d7c7319dc7efc72d123166735714808165783e1a
./engine/tests/corpus/a9a5d7a7ee58fb7701e36188fc3cd8c4fcd880d1
./engine/tests/corpus/5ab224ac13adc8703838cc2d1644c06aee1e77aa
./engine/tests/corpus/862c3346b2c7437ef7096879585893261e1549d4
./engine/tests/corpus/e904c97e69355edc6bc69ff1a13df52011c78cae
./engine/tests/corpus/fe3a093db78f631861956c7d2457f757a3e8f207
./engine/tests/corpus/9d4419e8c213f0c9276cac0251a1ff45ba2fc593
./engine/tests/corpus/c23a73a4e15d1313904872138ddde9c19ca069c5
./engine/tests/corpus/eb888c63548aad706a182a075603225f963072d1
./engine/tests/corpus/f96b54c6f2a78de5328ce0fabc259449ad1e65e5
./engine/tests/corpus/1eec4a54757e53990207474ff0110669ad550674
./engine/tests/corpus/3d9f737ae97d68e4c5044fccd59b4ab6d56f5db0
./engine/tests/corpus/dd2ee61caf76e43339662d5b31ee73ea64b361c3
./engine/tests/corpus/15199e147e18ec27664f39c3e3ede4fb26bc8b1f
./engine/tests/corpus/31d4b4cb7cf31d8adccc91354dee4a4916eadfc9
./engine/tests/corpus/3d863d8bc1b29b1eed6f6485cdf96ae0adf1d07c
./engine/tests/corpus/94c2b92e598eb12a5f4b02865668925c42c8e655
./engine/tests/corpus/468e044f0a0c1b319a4e7bbab48b8f0fed7e4052
./engine/tests/corpus/9bd0f97178b37154bb2d1711c04f876653f358c8
./engine/tests/corpus/188deeb9abf42d270b445e3c8dba9a3065412986
./engine/tests/corpus/2b0a454946fcb9ce91a0707e365fa40e7c3287b5
./engine/tests/corpus/333c7b13ab8486643443033fb9d3a40c60d1b617
./engine/tests/corpus/1ca8d5387f1b6dc6eebed75d6121adc0824cd098
./engine/tests/corpus/1b5313e91ad035e4c69cb1f22ace1e4b2f40812c
./engine/tests/corpus/d0cbfbb1355d42a73086c5a4f2afc7c2e59b0f43
./engine/tests/corpus/e61ac1b800c1dc324f4fb48885776f8fe459e967
./engine/tests/corpus/e394a659dd0ffdb442922fd7616504f63a654a99
./engine/tests/corpus/36d2b79b1c21a02d355f69e193944bde15870705
./engine/tests/corpus/815a9c23481162c744fa7ac2e229dd52e5de7e77
./engine/tests/corpus/280e03c63b8397d010e2ddf00f1393100f7f29e0
./engine/tests/corpus/55485fee25526167779ec80b3c43b8554a71d189
./engine/tests/corpus/b5170fef921192d56e99a09517bf39a5d4150d25
./engine/tests/corpus/1fa196856596b14dfa49a3ecb570e13e4ca21962
./engine/tests/corpus/397f6d69f1b53b5c6478eefbf8550fc4e1d63e71
./engine/tests/corpus/ade38918548d1e9a32d03e76374523f049d00318
./engine/tests/corpus/0c0c058cfa709d1490e7a876781b62222fcbeaaa
./engine/tests/corpus/71c707a28027a7faf169e37b9dea5d3f6384e344
./engine/tests/corpus/499b4bb4e8f514bbb269c3453c52fd620c2e2250
./engine/tests/corpus/9d2cdac4d757101ffdd50854ea8b79b084c3fcbf
./engine/tests/corpus/0b6e1616eda8b44a0630e4b93feb1b23d1248c09
./engine/tests/corpus/160ad23d40ffa55d9623b92c67be29a67959377f
./engine/tests/corpus/83359b8f5fe02b0482e41589f85d5308c60fc5a7
./engine/tests/corpus/13387326291f2e74b6c2853538183258f61d4617
./engine/tests/corpus/a24aeec64923e65322719f0258c4a58f4f4a3401
./engine/tests/corpus/f680734d00b62f8c3e8cc677b3fe3ab8c60bbdfa
./engine/tests/corpus/2e27be1c443862cee11ffd1a8d5133679f1c7d33
./engine/tests/corpus/70af4586b06f85c51d8017d28d859c415da2f3c0
./engine/tests/corpus/1a3bd80ac2d6062926f6ee40086b6d6dc8da54d3
./engine/tests/corpus/ab732081ec0f414da8d11b7569a0dff2ea80d04a
./engine/tests/corpus/ad5f310419f8f88f5f1e1d2de17e11002e5ce38e
./engine/tests/corpus/77544c629e7df79ca1f618cb1e1954d18380f3cb
./engine/tests/corpus/c14ad0fd06c9b0ec74c83a766d859d43098d3eb3
./engine/tests/corpus/ae69f8b68c082551cad33c9def3e9ff2f3f0edfd
./engine/tests/corpus/e31acfd1c462f50493947c9c17412268d0915ff9
./engine/tests/corpus/ef2c45b6dce4f8374755e57e3891317355866440
./engine/tests/corpus/3bcdf98bbf9d7d7fdfa618be0aefea65d879be90
./engine/tests/corpus/9694c4ebd673a5e2fd26e4b2e64f92e914ebd95f
./engine/tests/corpus/223a2d337aede139548e5fe3372ab51981b13ff1
./engine/tests/corpus/7d688e03f5598e744e9e4d6651a97a89f4e1cc36
./engine/tests/corpus/1abe916f68f420bf416367358f697cc3e1d9816d
./engine/tests/corpus/d1d9ff069e8e3303266e82bcf91d7eae08e09ad5
./engine/tests/corpus/eb5129a075e01741562b7ffeb4d5207874905912
./engine/tests/corpus/9617e94564df13fa99ce04db8fdb1d50a220ea4e
./engine/tests/corpus/4b1c8d7a93fafde54ac08cf9ffc1d936e97ffeac
./engine/tests/corpus/1a66e6d03def671a47d56c89254bbe120779f9a0
./engine/tests/corpus/ff8bda6e5d380ac49696f05b9103fcf3ecde063d
./engine/tests/corpus/102f0d92ce0e12d9b0958e18ed39b592bcbf4152
./engine/tests/corpus/878d14a0e2d8691fe899a76a70112b040d02dc2e
./engine/tests/corpus/c1ef5d1a6117999a7e09778fff772ac522c90c79
./engine/tests/corpus/5947e14e96b861f13fc60f7ec862edbf50549dd9
./engine/tests/corpus/7316254459adb61e6e0cf4a272269490214f3395
./engine/tests/corpus/97d4808ea5729f5cdcc849858af4636322a06f9b
./engine/tests/corpus/ac5e5e534a7f8a592b4f2ef96e1e80b53b57d627
./engine/tests/corpus/2c05b8327831b86c8ee3a6ba59d518fc6c0cf528
./engine/tests/corpus/3641af0fbebfbec03cdbac70a02849ff9cce35be
./engine/tests/corpus/a7a737c67e52df223c5e665413ba6ab00318d4cf
./engine/tests/corpus/faa3374681cefd86ad3c7ac7c29d8b51f6a8e0e6
./engine/tests/corpus/1a0945c24e7f3ee691b7ae3b8ae5817a2ac3df7b
./engine/tests/corpus/7f0826bd7f263b382cfabf6c58da1513dcf859e6
./engine/tests/corpus/576a41a6936383c6fa15c6355ad7ff55ef77770d
./engine/tests/corpus/3acb43e5564cf6138455f92ee79feb8c4fe6885e
./engine/tests/corpus/1d933cdb5a4e542dae735eac235204e02ed8ca86
./engine/tests/corpus/624afaf55156a10ef2360f638175ebe3d383db05
./engine/tests/corpus/87a0587961861c5e820b8d3500885ddef7b18bf6
./engine/tests/corpus/6e9935f9df3eff6ba5c4be0ea66e63df475158be
./engine/tests/corpus/7f3d90ec743add18e9ccc59a807a6ed257787156
./engine/tests/corpus/574301a65358d1f40a3826231b858a3d80e22e88
./engine/tests/corpus/4ec311085773287b977b040e260183e92d0b90c0
./engine/tests/corpus/4e04bf78043616ad83eb6f5cda77baf2a16b12e4
./engine/tests/corpus/f499e71bbfeb271fe3ac7e834dfd925e120a5191
./engine/tests/corpus/c2a4354067d8b9acf6e88c26f9cc0ea2ab4d0438
./engine/tests/corpus/4b931741fe6db73dcf204e4727d070b2447eff79
./engine/tests/corpus/7a893da9e1599e359f9ec2c97945ac54d7685237
./engine/tests/corpus/bf0329c9490f4c2161d8055763da90cf8062d85a
./engine/tests/corpus/73f5c9495abf38a701316b8a0b3781a2a1829f53
./engine/tests/corpus/40f1a9b5db43d94858cd52bfc2c6c6e91cebd94c
./engine/tests/corpus/81d67bd0b2395fc4685ea0c0da5ada1fe5f0cf9e
./engine/tests/corpus/082b92ee4ad4b07329a6d790672a65bbd79a9d6a
./engine/tests/corpus/6b5451a2d345d23c2393b7d6fa3dff27cb536099
./engine/tests/corpus/9e7d13d31b21399ebe52e212d5ce81111bd318b3
./engine/tests/corpus/ba55b5b02dd512681c311c47475e253662eb60b9
./engine/tests/corpus/24adb796c4eebe5500d38e6b4304b96198b56f36
./engine/tests/corpus/19b9e58f4fe5dae379dcea09010ac9f47a3c1108
./engine/tests/corpus/079f0edf7967f8572b33fccb7273f8b463cd6a47
./engine/tests/corpus/07e42700f99a2e5bd96798b995d239944e3071bb
./engine/tests/corpus/f0ba72deab7bc35ceeffd61cf89fe815e108a34f
./engine/tests/corpus/e60a6ae1ace5f74100a611f2f4e4023ffa647843
./engine/tests/corpus/1086269b2ef45f96d10bc8c058cc98ac81b8c9b9
./engine/tests/corpus/3525ab4075b01ebc42688449e9b0fe526be8e317
./engine/tests/corpus/c944d1b0e9aef6602e7508c232ff96378c877a62
./engine/tests/corpus/241ba7d6781734073e95709b98ff26c6c6c7b620
./engine/tests/corpus/0b1faa0fd30da4e7234b08eaa59481ecb0f6c5c5
./engine/tests/corpus/dc9d6b2d9223f6d461208c6171768b6055fef4dc
./engine/tests/corpus/2beed0e8a9a5df04a9b1c302b0bde5fa051daca7
./engine/tests/corpus/9d3c57b01e6914dedac5157036e830fee1ea1da1
./engine/tests/corpus/9a01a444305cd30dfc6989255564a2d8ec31f529
./engine/tests/corpus/81e191b1f5225562e0ca3c40a2274472ecd395e6
./engine/tests/corpus/135a938a7835dc4c4deff77765ea3d470be14ebd
./engine/tests/corpus/f26bdf3df7f458c2c852c2d47abd0aab0173a147
./engine/tests/corpus/3c88aee4dda3e3d2606cfa8bf8cb22b61d19c44a
./engine/tests/corpus/0c6c8003693c70d79eb0c1f429c1a48c75db2cb5
./engine/tests/corpus/6af878e4a0eb17df3f1e798e1159e6a307747dfc
./engine/tests/corpus/65aeba51e1207593b3d4d420be1e26e7511fd7cc
./engine/tests/corpus/21709f986c3975e055b15a9e9ec0c48d0afbaf2b
./engine/tests/corpus/03c299b5e9214bb841dbe9e29617e4f416470730
./engine/tests/corpus/b9547b53795716b0298c65aec9c7c497cf2ef538
./engine/tests/corpus/87880d482ebafd4c11943fd94d46fb8a8f7f0df4
./engine/tests/corpus/45c1efd89fab9f361a79274549b0332f58e46a92
./engine/tests/corpus/8fc28665dd794738e7e4ee732c0ff8574cf6bf9d
./engine/tests/corpus/22621b43485f1ddf180857ed4642777833346d85
./engine/tests/corpus/d9fc3f2e4bf465c779da1f89468917f16e502f87
./engine/tests/corpus/64df3921874b2b4929ed6cae14ec66f60e1c0151
./engine/tests/corpus/02d252903443184e1e317767dc6687fe30967ab3
./engine/tests/corpus/4fad55f2b2c8e494c9c92200b49b5d4d185d60c7
./engine/tests/corpus/a32d9798bcc3c83595933c5fe06914815a193991
./engine/tests/corpus/0c4a87c4ed6273dcc354fed8af5090cd1c8b00b4
./engine/tests/corpus/c9e9ba1d1332acb623e3b27b3da7f3439eff94e8
./engine/tests/corpus/a40676e272e3b596d17def2320a34d386a47c4de
./engine/tests/corpus/5d1fcf24d2e39a42f7ededcdcd705cb62e0ba2aa
./engine/tests/corpus/c42f629fd2f57e521322f5356cb9b0b6d4efe735
./engine/tests/corpus/d351edf960a74c11627e9001b1a90644b73b9bb1
./engine/tests/corpus/0feb772ce2fc44b098c06ccf80929bcf437de77e
./engine/tests/corpus/a0af1e71d51f34a2e014f0d3a2dff6acbfd5f245
./engine/tests/corpus/b9f9940aae8a19a7d800ba8991bdf8bf40c9070d
./engine/tests/corpus/7fd7ad37a92b0f6ad2e5e8318ed39ba58209531b
./engine/tests/corpus/b5b7852c88087b3d388a7103a5e1083079b427d1
./engine/tests/corpus/376978f5713529c67a5849b9e6629c6c13631893
./engine/tests/corpus/4938545c8bcf97eab3d1b0f0481280cd0a19cbaa
./engine/tests/corpus/a61c1723ca79ec720737761f5368b87d673e9081
./engine/tests/corpus/07b1b0e468882fa8fd3ffb9f6b6a4fe6357f62a2
./engine/tests/corpus/a434ef82c0291e4e88d0ba3549760b7167bb7e5e
./engine/tests/corpus/3277d8d9296876775d653f5f27f3514b4e86d158
./engine/tests/corpus/e3a7898bd1a3647f4ef16ee383bdfd7297554e31
./engine/tests/corpus/5612498f6e6e285f3c7fd39922895dcbdda01aa5
./engine/tests/corpus/91f1335ff7c080f51475e5d96a10c50bd8cfd59f
./engine/tests/corpus/b68edb51751f85ba0d402eb2b0f53be893ac51ba
./engine/tests/corpus/39ddb86f52395ff9bc3876eacc2c100aa3f2fd10
./engine/tests/corpus/26df19d307e6b4b3eec3997d452bbf90b10ef04c
./engine/tests/corpus/966664ba93e862390b86d92de2a21ef9ff05d899
./engine/tests/corpus/34227dbbd4a6a202e07d63cd113bb80f3e35f93a
./engine/tests/corpus/e65c5599b4d52d7923ae596fa9a5044bd4da8d8d
./engine/tests/corpus/23d213e1d459482911741d18fdab5b1eb866f949
./engine/tests/corpus/da4e4add87ccf45e6e1bd33640024bc621399c00
./engine/tests/corpus/8ed6f9ad53184668b306668f3e7930d4aeb487e7
./engine/tests/corpus/4755e2c9c4ac4ea5417975818ad5b4440fdb74f8
./engine/tests/corpus/69b7c92f22b29ae35a80a59ac4ba6b24d90be5b3
./engine/tests/corpus/a3c6245cc4f0ebf493b3d4ef6510096cf4d7ab8f
./engine/tests/corpus/56c75bf4b5952142584b900105eaa0490dcfb86a
./engine/tests/corpus/3b31a1964e0c334e3868f564c5499d52daab3ab6
./engine/tests/corpus/6c4681d1de19d9525f71e943ffc7729c6f0c1437
./engine/tests/corpus/7cce6348eef4d6f2ad4ee4488d20f08b13671232
./engine/tests/corpus/3226bc7be5302fdb64db1e728180c292edec7b44
./engine/tests/corpus/360291a755aeff31515a7378ac53b84310a19b77
./engine/tests/corpus/b5ee6f447850a3e582c4e6ff26b4cf8b447a03c1
./engine/tests/corpus/3fe5de2e3c6c37ed4f2d41d03b1905e10294272a
./engine/tests/corpus/5024506763ae71e8d56448c50acf5d4970042277
./engine/tests/corpus/52fb9affc1d8e1b8092df41e508096c453a81318
./engine/tests/corpus/56deb5067bea939e41499f5180d9bd575bc257d8
./engine/tests/corpus/92b5bde5230a98f3db7bb0d2b150d8aef563b5ab
./engine/tests/corpus/0cec38c1892a4146bdfd75b54e8b045b2f4e996b
./engine/tests/corpus/86c73941e060980720f716cc26d8bf01766cce02
./engine/tests/corpus/24ee08462b276d2fa7c29b307a1a5992f875de80
./engine/tests/corpus/db345b71895cb5e5b6d50158ef337722c6f9c1f4
./engine/tests/corpus/3074a4706bc8b654da651f7b482ab986a4e31924
./engine/tests/corpus/85782458b0e4710cc7a2e44346fba2ab95df990c
./engine/tests/corpus/3835da71db86e2c9379de249ad1e6bbb3232c788
./engine/tests/corpus/daeb74c75788cf731bd4ed69105b676c9c8427c3
./engine/tests/corpus/0f94fbee29dadb788d0b22e0f4b8992810dae61a
./engine/tests/corpus/765e752e2e63bfda3942e8b66b57b953d9b9d6ff
./engine/tests/corpus/d33b77f476917f10a41f16e0889fa6e324fd0066
./engine/tests/corpus/553af043609f668b225b54a5bdf0ddedc75d91e8
./engine/tests/corpus/97c029859a2a379584cd7e30046577bfa3368e17
./engine/tests/corpus/7dc21efce28abd297c583ab02ed7bb096d40a3ca
./engine/tests/corpus/52f50340f119deab9a5ce493a2374848fa62cf6c
./engine/tests/corpus/43c231d27e43501864d5282637657abcf6d858b2
./engine/tests/corpus/10553b88287a5d20feca929b9a2f986fb63d21da
./engine/tests/corpus/a331b0ccf160a397cdb83079d650bfb8df080c92
./engine/tests/corpus/911ac0deed6f553d17cb21b9d14f172eb1793a6b
./engine/tests/corpus/9ec90a0e446fc80c917ce345ce633e7c4effe3d1
./engine/tests/corpus/e099f050a8eeb7daf54b612610782fa07c095983
./engine/tests/corpus/051441cfbafce4286fdd7b75bcd62dca5af3f168
./engine/tests/corpus/67452ed3ecb635891c3115899065b93a74875837
./engine/tests/corpus/89210ef7b3139f30c1902b1dcd149bab67924a0e
./engine/tests/corpus/583b59fbb8b672beaf444f9e8e5b991edceea472
./engine/tests/corpus/9eac6c42de2a52d284a15e1d9bde5f6efcfe9ef0
./engine/tests/corpus/e9d5786f37c6ea79ec7d75e145ebfa4ca464a38d
./engine/tests/corpus/92c16d844db4b06233d3663c7b7d326eb679f2c8
./engine/tests/corpus/c824e0db5afaa0a53c0acd0119010d267c47218a
./engine/tests/corpus/c2daf7301579f501ac7a0091a52e81ba4919064e
./engine/tests/corpus/31efc747ba734cb4d3ec280d2f21dac3cb14a65f
./engine/tests/corpus/ca8b8e3c28b050350a06e96dfbae59a3b261f4f8
./engine/tests/corpus/4d18459ad03ccc063d1e7375aed26778eec96d4a
./engine/tests/corpus/c9c1776868ceb829bffe4ac23154a6f53a091747
./engine/tests/corpus/f1132b679b54841d20ff9d7b8b99c132d966b599
./engine/tests/corpus/599b6093994a637e819935dc81b92cff61c018a7
./engine/tests/corpus/2f358c0ea3a1f09202c3fd674ec813999519245f
./engine/tests/corpus/e7b44e7d90eb1a34400d0de544f59bce7776b81a
./engine/tests/corpus/680bacef72902582cef8174b12508903e355a563
./engine/tests/corpus/34c687ed8c666142d3dde47de5eaa45174a59c52
./engine/tests/corpus/115411a31ee2094d85b4cd1235ff1bbe279a3fe9
./engine/tests/corpus/65303be29c56bcff043ab79153f4dc5f8ce25e92
./engine/tests/corpus/2e6858bff6fd31912107d26eb06c08a866c72a0d
./engine/tests/corpus/7252161dd463867e6dfb25b08050f3bfa36928fa
./engine/tests/corpus/3359db259a9b50732872c492141ca7e141b20383
./engine/tests/corpus/7dff6f9b658f866d911ea951305ff2948f0b83fc
./engine/tests/corpus/97174518b50923b69a4f740b9f51850e12ce0a89
./engine/tests/corpus/5470de2c1093bb88ae0a9574d195e80db15a314d
./engine/tests/corpus/8a5a8654b9aee6244f4dfe078db4d9a7b1d5aad9
./engine/tests/corpus/da3eb96dba43e6badbe098bd73b7242860f702e6
./engine/tests/corpus/87f3e9d754874233f5661f90d1545b85fc0d5e59
./engine/tests/corpus/335b1834ed3cef85e20bbe5f9dd512ec9be808d0
./engine/tests/corpus/95828b4ad6f1f451aa274b04d549ab6e7622db93
./engine/tests/corpus/0ba973361dafaec111d025c46af8bed43a50614e
./engine/tests/corpus/267191aacaee9fd6460b54f2684ddabd377e464b
./engine/tests/corpus/006779ed3fa631809940c9bebc190bee20ec3630
./engine/tests/corpus/e1af8e877c0317b261714ae94e88bab8ff415251
./engine/tests/corpus/d6a8e91b9569775324ad1cae24874a32669ec774
./engine/tests/corpus/5faac741628bf589aea4a22df500d6d674c6611a
./engine/tests/corpus/ef70351b4ce61abfa1a17604360b89d417fe7afb
./engine/tests/corpus/7f42b4f9bf94640f49e3b65eb13e8ac465a789e6
./engine/tests/corpus/ac41580acf9425c0df77f111365f4ea5017a652f
./engine/tests/corpus/331ae0f4c19e6c6982f53c42f810688d36a8a695
./engine/tests/corpus/a254ded6963dc77826a8890c32c92fd30ff6f883
./engine/tests/corpus/d9250ab95b85d404259ab7675d204927499a9e7c
./engine/tests/corpus/cd6f807f164d8d360b76d4b5b798291c23fb499e
./engine/tests/corpus/33d35cdad85cd800ce7504b60bded1efde767b5e
./engine/tests/corpus/e64020a26d8b061793dff31791171533ff95c5a8
./engine/tests/corpus/dd79ded041909b746f00e155b242d60715e76d65
./engine/tests/corpus/60b686c97ae99ef45ff03c987c16be17da4e6374
./engine/tests/corpus/75b117ded3660e51056ea33a6b9f2ca349544555
./engine/tests/corpus/607a316520458a355e39800f725dc3bdc1da4d79
./engine/tests/corpus/794bbf0c4269e975ed7b25270b30792f2cc9259b
./engine/tests/corpus/ab4ff5e5f6d2874914e51cc26c0120421fffbf18
./engine/tests/corpus/6aca3758d5295c97789b2e6a1ae0aff3b4613311
./engine/tests/corpus/ece67301bde627aec3b774c9257bcb9bd46aff83
./engine/tests/corpus/464d3dd675460770d8246a220ae5df6b50204539
./engine/tests/corpus/ec367c2aea4c86c9eca89fa43d314e135b861a28
./engine/tests/corpus/3acb7e1f05fde9cfa915829f8094977fa706e8e6
./engine/tests/corpus/e0d05eb7d10f65174605805f7786ce1374f447b3
./engine/tests/corpus/648b63c8a7d217e11705c84817d4696b9593f0c7
./engine/tests/corpus/ec08cc72ae90c5359a23d5ac6408941aa6626660
./engine/tests/corpus/5fb1abaa805ef57e89c26fba47a2e5f2ca5a58f6
./engine/tests/corpus/fe8fcadb62eb6b711f039a1b3638e8ce678066e1
./engine/tests/corpus/fdf0f5146f856547918ae5c8d3d6e9ea00837c18
./engine/tests/corpus/9aebfcbb07b21febf61217e0f8729493aa482a59
./engine/tests/corpus/41dce5834925acba212af42496f356ef1da6f563
./engine/tests/corpus/5f7cc0bdd68f344a429285f59169b246c7a8e279
./engine/tests/corpus/f9267b5042ca6bbf6a309bcde18122217ba16c72
./engine/tests/corpus/aab4f97179444f704e109c28c77a866a3acfd856
./engine/tests/corpus/34f7090107d3511cbede3b8241bf424b830cd13a
./engine/tests/corpus/ba61556bc9076f153922b810263878d325f77a9c
./engine/tests/corpus/458c848ff436a874827cd315d568087a7844adcb
./engine/tests/corpus/27046236abb71ee396f205ce3584d64991f29955
./engine/tests/corpus/7084d7224e1bba4a2ff0f8759caf23fbcead9b52
./engine/tests/corpus/8aa77439c5ed71dc020b4c45407a677d2f2f4492
./engine/tests/corpus/f440b02c312737047b23a977ee867f480f467400
./engine/tests/corpus/a55d78c4f86f0bf0749e97ecdc95a72ee701034c
./engine/tests/corpus/872ed1f12252d38e079a1b0a7a43915e2d722969
./engine/tests/corpus/c3b876cb4a1f17451ed9f4a38a3aa2c927a7e277
./engine/tests/corpus/185232ffacaaedcd7114d1d3d7c73475c9e6ac46
./engine/tests/corpus/e36e71a936dfd8cdca79370083159deb5ab08660
./engine/tests/corpus/70914a8a00e44cf3ad5dee524636b6eb0869bfde
./engine/tests/corpus/e32585813afa510f9618638f4f6b39c6045c2082
./engine/tests/corpus/31eeb96e8d6c6fa36f87f22994d686ad7c49cfb3
./engine/tests/corpus/02eff0d176d94384b74142c7c12844a8a0a723e1
./engine/tests/corpus/b30f1d6cb9ab997b16f1732c9d038f2b76506c16
./engine/tests/corpus/0a6182e8eebce3cd31ae2abb51d35e0c3b51988e
./engine/tests/corpus/3e5b6bfff566aa1eef0df34ba185ebe68b895a2c
./engine/tests/corpus/c7307fc44005f62b7f3fcac323c3d20d1e921069
./engine/tests/corpus/a380e7f62ade5935ce8c62509b64029b8584f8dc
./engine/tests/corpus/0ce1238eb0cbf7def3e53594b6404879d1306580
./engine/tests/corpus/d8d02689a870d4a6ea171533acf73962f89e04fb
./engine/tests/corpus/e7dee4d9cbae7a310ccd47163df283e211547b37
./engine/tests/corpus/449672b132d87f4f7edfacd2b7662272752b3166
./engine/tests/corpus/0708643a928f70da08376eefae6a704880c0f94e
./engine/tests/corpus/af7520171fb18846992b635630cc0f47c66bb19a
./engine/tests/corpus/22241ec8369e4803015fdb6b43bb2a16d1ea61a3
./engine/tests/corpus/3e4f5e31b9a1f4375953bd4a286d3874ff3d8ae6
./engine/tests/corpus/4b5f2ab53200d41cd37673cdfc4ed2dbd5569713
./engine/tests/corpus/a453b0249de113bf9ca23fc222a3f71958b3efc4
./engine/tests/corpus/1566fccf1ed2614f56f9aa706c3748cb60d09cbe
./engine/tests/corpus/bbd9a99c3103fa5d9db61232d4c701e7c27ec06b
./engine/tests/corpus/48b3ee88d2260048710ca49572248cd69f6ddbab
./engine/tests/corpus/91b87e9e9fab99b2b80c3250e673dd1127a396e6
./engine/tests/corpus/7da7be4879f5985dae4ae443a79087a3e4c93c53
./engine/tests/corpus/43cb2debcae7ca70a199fdc92ec0005cfca8773b
./engine/tests/corpus/b46f16c43bdebfa47d895c5212ac4f7925d8f030
./engine/tests/corpus/79ec918fad66602b12e2836e6df093828314a51b
./engine/tests/corpus/45e4b6adbd029c6e294e61f0a8f5506f2bc9d2aa
./engine/tests/corpus/361864e49a2ed78a3c7e07fd832e5f16a56c8571
./engine/tests/corpus/7395be606f66508e845239f203aa8d2d4b6a4edb
./engine/tests/corpus/839301ef55eb3c3972e6663ebc31b036e8537624
./engine/tests/corpus/5d0f12aec2f3b6bbf89b3cd2d929b780dd61971b
./engine/tests/corpus/0cd203d405d6c882f340212f5d5cf223607d7b46
./engine/tests/corpus/777b4886b41910b007e6976502eae3ed5e0472f9
./engine/tests/corpus/453fc898039c4c09df743cde8cf866ab0a54c155
./engine/tests/corpus/6649800420999d8d6ae709025419e74fc5a7a90d
./engine/tests/corpus/f0b176fe1cd654f37ad5531ce3565738787bb492
./engine/tests/corpus/b3e04e73dfa405032dace3d600cd9a94d411c7a8
./engine/tests/corpus/2ce5df2a5697166cf87957d55191c8cb903dc510
./engine/tests/corpus/f2f551ba63681fbed85fdd993e50d104ace74825
./engine/tests/corpus/c5c831b74d6e6bc6c3bc9af03332b15ae9a25fef
./engine/tests/corpus/3fd1185d547cfcc511795a04ecad665745acc940
./engine/tests/corpus/761acee0ef182b61e8bf2a30afa0643efdfc18e5
./engine/tests/corpus/cdbe2e3e5f5cb44e2c62bfeb12fbc2a20dee3fdb
./engine/tests/corpus/1c9e910367e3a2189029ecd3dba70a84838e2d2d
./engine/tests/corpus/7046b12ab17c6aa17088d5a046fd2b13d1007fa1
./engine/tests/corpus/a0d50ed686c195e190f31872d66bdddc71d24404
./engine/tests/corpus/4cf26967fa0572e35749c9bc2844d86abf046021
./engine/tests/corpus/197ccb42e5a90bf14586b7f90b281b0b85adc263
./engine/tests/corpus/ce5f101f3148250fc22f394ac4627810225289ff
./engine/tests/corpus/d39dfb1b0cf534d1ab1cce0e87fd5e9924b00b20
./engine/tests/corpus/ba65523d06eca5e0421a4d1fce544d37c00f0417
./engine/tests/corpus/7cc747e5a27993c78bc2a447a8c3ac7878e63907
./engine/tests/corpus/d6c957d73f0cd9f85c0f99c1d63226f525fd410e
./engine/tests/corpus/c6dbf0ea46fe7ab5b2b9c4be8f7962b8131b9074
./engine/tests/corpus/4856b6fcf3be23a15b53d223232c179d9c6a34d2
./engine/tests/corpus/9104f6d052fcfdcaf72a4e2838f8f0afa657d937
./engine/tests/corpus/be006a953e9ebcbb971cd7a71b4841c5760b899b
./engine/tests/corpus/0211cbe1af04322ece1f5e9e6fdc5bc37fba1174
./engine/tests/corpus/24bf5a426b754148e95a6cd92426e4123af42940
./engine/tests/corpus/35e67372c7459cfd54165005177afa112d437185
./engine/tests/corpus/af62c004e3e95668ed30c7e199b5173f1b36ac98
./engine/tests/corpus/1ae80b30586d21953a06aa35d29ba7337ba76ed4
./engine/tests/corpus/9a66b52566e0953c0f38637ea8b47bdeafb14c14
./engine/tests/corpus/d91f6ae4394dc747ef2539d01560279ab5237761
./engine/tests/corpus/98c236d9af3d369d742971e8b20f84e825d84f33
./engine/tests/corpus/d2f1bbee043177484f07c2c88df77b62a37db993
./engine/tests/corpus/61b63a89a511147b726fe8b51abb33ed4da45a0f
./engine/tests/corpus/02d4ab7ab74a93e7662a5fa301a033ebc225e5c5
./engine/tests/corpus/1198b01074e7f05186db8b9ff8adf24cb3e3514f
./engine/tests/corpus/6c326f3aa58108ce6459f5b53d37e6db8527f150
./engine/tests/corpus/24f3dae4cf2fbe445270e6f3e3dd32d0dda0e4c5
./engine/tests/corpus/225b6692e56ccf39aca71aa3d389e3bc78c6a09f
./engine/tests/corpus/c2929dc95dbe5ac88180da97b87ff41243f3c4ce
./engine/tests/corpus/9e8650ab51c5ce6c07ba647551dafbed4f5f19bd
./engine/tests/corpus/3d0387bf88d3e832007c6fccf5ee8564c9b25ae7
./engine/tests/corpus/57dcc6d405681215565dbffc4f03bce718a18300
./engine/tests/corpus/f9fcc83fbb599bddebb9cde50b7112cbaa43db5b
./engine/tests/corpus/d1fa86d0e2c14fd192a0a82e3cafdc2b2be0708a
./engine/tests/corpus/cd6d5f23791560e07c4850587123534ab6266192
./engine/tests/corpus/d1bc93980c793adffe00137d8fc8650034e93c6d
./engine/tests/corpus/e1a5d625ac6d6693b00ebcd5a2496573c86fe504
./engine/tests/corpus/7c397e8e48fada90f133ab9e26df15b91008b258
./engine/tests/corpus/84611b82632ba04aeb7b7a16d71f62a69542a03a
./engine/tests/corpus/e47c4690fd04611601675505b7dd4761dadc22d9
./engine/tests/corpus/7e3bcd531c370752e48e274af0467a35ee12f1d5
./engine/tests/corpus/dd35e445ec4e8f6c8bb068d17b1673bf86a0a15e
./engine/tests/corpus/597944984677fcd49ff0556133a5dc953478c615
./engine/tests/corpus/398014b16fbaf9da900280091622301108e6f604
./engine/tests/corpus/c1fd0e6d4d2839c8d406a6e02b65a7b8da8dbe18
./engine/tests/corpus/1ca24ad1c5f06fd7c7946c570c5ddfba247a5392
./engine/tests/corpus/560a11bc967e3e8ba051570ed77110075bf60799
./engine/tests/corpus/7d1fd6bb807ec0bf0291c484c97b4e81d07f4f32
./engine/tests/corpus/82e14f90e5d0e2c6e23445d61d39e751e319e861
./engine/tests/corpus/de7d98372f19927887a9ffb8e78a262535621241
./engine/tests/corpus/5cbcb737457c04b7b88c51fc2442686f8fd73f9a
./engine/tests/corpus/a2f072a60d337da720a2942e2bedf4f76002413f
./engine/tests/corpus/ff00bcdaac4a2fbe95e94aa2486f8a11a3656702
./engine/tests/corpus/820d62457c83f81fce7d7e93dab23bf11230e3ec
./engine/tests/corpus/a8ff44b246bf4b653eea60d2cf1da43e51aee15b
./engine/tests/corpus/a0c23cca80e99858b46f0cc7c28a4ca64d8a3d02
./engine/tests/corpus/907ec909a37bc9e200dbc0391d9966ad8cc7f664
./engine/tests/corpus/d1ee79a10262364d7cb84f1ceb26700dac03296c
./engine/tests/corpus/0a7bf5591b38dfd376d85c8e6ec2a74229973c47
./engine/tests/corpus/23c6f9c2ba5a9458dc38a049192ac818eb06848d
./engine/tests/corpus/aa08f3dd0ef2e757fc96759b22d15715d9e7ed57
./engine/tests/corpus/f61dcbe029648ac674470e6d0424958ad8ca6394
./engine/tests/corpus/9e2d1f910dd76c2b0e3251059892c5a91a1edc79
./engine/tests/corpus/8e52a5e325ccfd9586249d09782052d3bd63a8cc
./engine/tests/corpus/10e5b7e3d18e684d578491382601dcf48e46d5c5
./engine/tests/corpus/3a828c19133d51979b1aa80a48df43aa37856780
./engine/tests/corpus/1e10fe2ee4ba88f107252d4853d004288e512c63
./engine/tests/corpus/a93286098aaf2f6dc5cfa920fb3e8ccd37052a5b
./engine/tests/corpus/d4bf9df5e967d82281f291573509d4b59bb07c43
./engine/tests/corpus/aa4e9f7b4328c51cad3880b321825911003500f2
./engine/tests/corpus/f162feab7d98b2c43518ee9e6ae5f4ca349308f3
./engine/tests/corpus/9235ce04c4d7f676df3038f303ccf8a79c7da579
./engine/tests/corpus/36485648c48db45aa532c905d1ab67220ae690b0
./engine/tests/corpus/e6ca4dd9e6a94a1842e30e826a8ff9890bf8b63b
./engine/tests/corpus/ec822d392c8cfdc2f79a65d316d175fe1544a4cc
./engine/tests/corpus/d30682553a771fa9e524c05e1f691807b4216480
./engine/tests/corpus/07c01c3e06514deeea1b62fc3b50777500e5da66
./engine/tests/corpus/f29741222e6508d198f3648f14cfb930594b683c
./engine/tests/corpus/e223a33f174f3bc1fac1978f44f40c3f4a22d6e3
./engine/tests/corpus/70a70c6ceb07f4e3116f78e8dcdc9008b8779bd3
./engine/tests/corpus/3665072b8fc4cf275608591cdcd69f7847c9e98a
./engine/tests/corpus/b2e6a5e54c31f320d78a92417669bca8b5cf28fc
./engine/tests/corpus/ab333d5873c5c9df178708f9a49baacde963be34
./engine/tests/corpus/5e57e59adf3bc0107053dc98109357a72fb03c7b
./engine/tests/corpus/f54756cf732d684d03dbb4b39c5692810c7c024e
./engine/tests/corpus/2a0043930893255726a29b331c023e435e285d99
./engine/tests/corpus/6da057b622864d1d52e3eab1ff75dd0d414fbcc6
./engine/tests/corpus/ddaae718d895866851bf4b5848caa5ab74eb39fc
./engine/tests/corpus/1c6cfe4dd6a79f3a6cf4da40165e2ef4c1aa257b
./engine/tests/corpus/942ee9d443c9a4444fb5f2dd3d23ac010ada77ea
./engine/tests/corpus/c7a845cd5907f6127c69d1143e9b935554fbabda
./engine/tests/corpus/a826db954b6223a458aedca1a59bef3ac9f92f57
./engine/tests/corpus/0e0873ee2e7b46bd58ea2bb6720cc076dfff943b
./engine/tests/corpus/946ec50d2d0858c3e4969351497bd91f7b1b9c1c
./engine/tests/corpus/6dbb48c68c25c3d4b8c847877063c39c101b3ec7
./engine/tests/corpus/6605db8ba11650ce65bcb16760a22632f1aa4162
./engine/tests/corpus/450bfb2c3394a820207708bdf86950ef42a417fa
./engine/tests/corpus/84db50b160cbcc4abfe6c44028580f04ffca0168
./engine/tests/corpus/d7cf5e4085b03f8ba5c341f171aa412b57967ca4
./engine/tests/corpus/7cef40002dc04d1ac3872bdfe6fb7d16d9698a93
./engine/tests/corpus/063a400642a60605ade8f65e639ff0d7f0bbd561
./engine/tests/corpus/7320ce50d6bd4eea6a7d48b7014dc6d55148bdb9
./engine/tests/corpus/bc59ed3a1f9a502cd8f2aa89b0821af64ff06ede
./engine/tests/corpus/ef08f180d755ee929dc5e7ee6abc6d9fc55b9c45
./engine/tests/corpus/fda6c0d8355caa2360642a5970fc069230e3ee51
./engine/tests/corpus/063c4d8c9a1748802d281840ef2c981a33cd7f45
./engine/tests/corpus/9fae27c7239404858ea7ff88902b7f114be3ee26
./engine/tests/corpus/43320b8d33ff1cb883d3b90b93702d71c2196162
./engine/tests/corpus/794d200ee5899e1d85f43119452506f84f2f21c2
./engine/tests/corpus/044f898ef626bd24a7d4f4472b3fec3a667737ed
./engine/tests/corpus/c885fcddddebc6562401aa47b4e94607cbf478ea
./engine/tests/corpus/fce9f15d6ac6967ab7d75dc1f25ef8b1f0fbd208
./engine/tests/corpus/eec0cc597042a284a60e05c7a2717b423a73f034
./engine/tests/corpus/a3ffded5bfccbd5426ac704e5531aa9013d6faae
./engine/tests/corpus/cda0aace185ab3188ff1dce248f9f46891fb421a
./engine/tests/corpus/55f87c0c8f8c840b0398e08842a78e9ad64f7a2c
./engine/tests/corpus/8469e4f862ceee8e25659f49c66d6c9f5c8c38e5
./engine/tests/corpus/b551bad52ba4d832dbb0bef4a8cac01f1e35f0d6
./engine/tests/corpus/fe044ee001e42db8f357b3a415b2065e780f6193
./engine/tests/corpus/880d63f35cbbd0c2f7ccfc7f5df3675df41f7701
./engine/tests/corpus/f65bf8a26e2b1111729a2a47aac26a5b4650605d
./engine/tests/corpus/a2bc81b521ba02225f53510771427e947840d71b
./engine/tests/corpus/33ae4c9514b654c917e0c010435dbce872ac9fc9
./engine/tests/corpus/bee52494a1410af85c68875bdca4385afc2a2bae
./engine/tests/corpus/a1b0d9eaed383a39f5e1e812a279c0e888af1792
./engine/tests/corpus/105c0c45432d5d199093adfef8258201c508a84f
./engine/tests/corpus/1dfc343edf29d6b647ce04f3ba6728c303186095
./engine/tests/corpus/78130f3af70943437f5ca1aa6f11119e9d42f581
./engine/tests/corpus/2b2ffb5288e0326459f09f25f21a3f36077b692f
./engine/tests/corpus/a494009d4175b4261b3fc821fef111637b78c283
./engine/tests/corpus/4a894a420b7eacd9ec861f164531c7abb15e1d3f
./engine/tests/corpus/37e3eaa3a909ffcc1713d7fb1df767d162a4882e
./engine/tests/corpus/92dd6693aa0242cbd224082c934d037df5abec57
./engine/tests/corpus/e75ff2ddf3c2cced8fcc603cdbaf78dafbfaaaac
./engine/tests/corpus/b4cc326e8768bdffb287c94132f163fb91b90cdf
./engine/tests/corpus/bf31dbc20402c67c792ce9a19e26b56729851642
./engine/tests/corpus/d6b50c3594f31b53133c9c380f827c1b08862aa5
./engine/tests/corpus/d8e47cb86db1c6300b7f5124245ae803e86ef6fe
./engine/tests/corpus/f9328a5569f1f4622a2f63e985be17af9e4766f2
./engine/tests/corpus/88362bf06c640912c6b71527215193a31f137f56
./engine/tests/corpus/7b01ba51365991393f743d356e6922603c7ce0d0
./engine/tests/corpus/9f413b40d3487551ea2477ec126da439f71e01af
./engine/tests/corpus/e2a0eba31047039c935f178f84fde7c344f9ce99
./engine/tests/corpus/2527af833a35ec936840649a3783f77773581f65
./engine/tests/corpus/3dcc8ad530de06da79a7606b1928ba57b8b973f4
./engine/tests/corpus/b9e88db3d69059fce23547ee0da8d9e4eaf78bff
./engine/tests/corpus/a126228499a2fbcbf5d0bdc1d2530f68916ed5df
./engine/tests/corpus/1b8cb80cb6f94a309ac023cdd9d06d2545b703ea
./engine/tests/corpus/a051bb74f08c9f2dcb441c1a6ed526ddfee568f2
./engine/tests/corpus/792008eee2273a5113bf81629d614a89c6b4d7e8
./engine/tests/corpus/73b59a85027d40b4760424ef73cb4c453755bff1
./engine/tests/corpus/013c2c73b53a5ecb25059b77f5c93df7055d0429
./engine/tests/corpus/bcd7461d48c7bd6b0e9f68a0d903d4dd62d552c9
./engine/tests/corpus/ffd071af2614efedd4ae2c4feaac02a1e3ac2688
./engine/tests/corpus/95f2f5099cfe5d262cb7ee1d42527e953ec13a40
./engine/tests/corpus/07bf280a7c2ad77d08bbbbf399542f5bd12dac23
./engine/tests/corpus/bab46bdcc8c345c1aee57c8de05c70d83fd6ca6e
./engine/tests/corpus/e026ddd2843e862fd5009e1af95d4f9279826a7e
./engine/tests/corpus/42aa0185ea6ac5ad25813c1d650a3caa4d937688
./engine/tests/corpus/8987ebcda92b506e5e839caf46c6c5d0856afd86
./engine/tests/corpus/9eb3830f1a3b373830364e339d6f62e7a23a7600
./engine/tests/corpus/60a3e8a29b5cb2ca90b4a8aa95564833ff52e7c2
./engine/tests/corpus/0169f11ab1f1b9ff4a798f6005ae28840d49a955
./engine/tests/corpus/2c7588d2c41d80c7b646eae34c9bed1c332cecf2
./engine/tests/corpus/8f9df2bc5671f1f735e6788fd39b352c30e6d8b3
./engine/tests/corpus/21fb30111bd08399d8139edc055662d06dd335ed
./engine/tests/corpus/1e6a5c1409e585fe46818fe2cd9a9b1f6de4b72b
./engine/tests/corpus/6316b738cf84170ae536b73684c9bb9c1ad03054
./engine/tests/corpus/869bf3b77b649c0403081273c63e55f3f85e7ff6
./engine/tests/corpus/3d55c4f148c04fad590426ddb403d7c3bf75da9f
./engine/tests/corpus/a9206632d5c3dda8dfd032ec47ee07fbc6315c1a
./engine/tests/corpus/c02fbfe0b32b36cab078420498b41e4f2f4b9ea3
./engine/tests/corpus/fc374018811dc4aebb7fc89ad2d38999801e7396
./engine/tests/corpus/4b96cb5b53155a7c52e8b0bd6170fe71b829196f
./engine/tests/corpus/f89351f130af01b224641c7c48a72608652b7cfe
./engine/tests/corpus/63d8dfc281f1b9ab78698fe3d9be90663c091d65
./engine/tests/corpus/27e8ae9e2a58290ab83bac06ca13640211ead1f9
./engine/tests/corpus/f74ebbc6db1332a35557f7dff0e43d095fbe4d87
./engine/tests/corpus/b7f4bfd30c42a83e36b2a6cfaa37e4bf474d1134
./engine/tests/corpus/a493cec19106992bcc1a2f4cee01a9dd46bed092
./engine/tests/corpus/d728c55face753825e8fec0285a105c4e8ba1fe2
./engine/tests/corpus/57126d826219d6cd76d26979aab4057faeef4a6e
./engine/tests/corpus/c7ef883d330c865bff15a7806b6ac77f70044c4b
./engine/tests/corpus/6095912d2a317042ea68f93db5f041ae25446aff
./engine/tests/corpus/bea166076cb72beba2287c0ee85b07e03ab29e59
./engine/tests/corpus/bf3a1ea309679f3018a8a3d05335656a95a53235
./engine/tests/corpus/1dd4d3fb87285a101c9ca2417b777b44b564820c
./engine/tests/corpus/4c729b9e05345c7dcc4f0dec09a6df7dc451fef7
./engine/tests/corpus/9522c179f9fb83a6ddbce9f6f5a5493c7d90bb47
./engine/tests/corpus/2e6d261b379975b7b25993eb34fbdd01002a4427
./engine/tests/corpus/6bf5af9de48ab3ba2b11da64031133b56ce3c019
./engine/tests/corpus/3c1feb5408dce1d231400a6cace9ef64fea2672c
./engine/tests/corpus/0f9974543a0156be5738482b3f12a42c07fdc409
./engine/tests/corpus/42f26a20ef278136c3d2f9bb5562c01b1d285573
./engine/tests/corpus/a0aea5aeaecfc470b0214eca7e7f7ad930796e48
./engine/tests/corpus/fec611f04bb93dd35f169230475cc916be4dacc2
./engine/tests/corpus/d13bd7a58271fddd6e0b629168b6ae5f5633a7db
./engine/tests/corpus/e3c78ab4521201394fe27e60870e3bac4718c29e
./engine/tests/corpus/2121d0224f1a212cc863a6351b54e5ae3d0f1668
./engine/tests/corpus/6b803eec8492c2eb71b97d79b3aa6dfe01ad2fc2
./engine/tests/corpus/b0ca788ccb6f70ef181fff313bd825a2ec41fcc5
./engine/tests/corpus/b81fb90de6a963105bb43efb8c1351824005776a
./engine/tests/corpus/234f8d59acad198d90c52a6d8fe6812f175a584f
./engine/tests/corpus/778a80e6cb4d88b6cdd94b25556018b84a24bd4e
./engine/tests/corpus/8fa579a6398293b49d76ee66da17fbf9851bec49
./engine/tests/corpus/23e960709a4ce26f6acedbae2a81f773733b2e45
./engine/tests/corpus/c865c04d2a1a8fad80999c329bbd8eaae29402bc
./engine/tests/corpus/ceafa3d03df2aa237673f94f23262954233d012a
./engine/tests/corpus/4c96edc66d98407aa0a48bf3ed9b87d4a44fe139
./engine/tests/corpus/504ad9b0a0fb0b36d1dc122c04f35257d3d0306d
./engine/tests/corpus/1ddcbe1af4ade1e824b2abc99e991081241feecb
./engine/tests/corpus/61101bd4065143f5bd8dd8611bb6b330d7580783
./engine/tests/corpus/43a7eb26e8d0aaef883266d4c74c41e4adb76c68
./engine/tests/corpus/4e08037d00842f2cd4f6885d6d35c08bdfe18945
./engine/tests/corpus/441106695834c22ebfe6b320e47aee80b27a72ed
./engine/tests/corpus/676e9e289045287307a160eaffe2ae1788c6e116
./engine/tests/corpus/de47712fb184b71f514f7106c72114122843665f
./engine/tests/corpus/6ecece926e3821d9fe7a598aa3d4334cf3b83a4c
./engine/tests/corpus/7a438adebedfde82bc623ce7a962eb6f880f6ff0
./engine/tests/corpus/f40d95d88d3c5afc25695936654549e135b638b5
./engine/tests/corpus/a3a86efc736b9297dd7f78928b3d0152db680830
./engine/tests/corpus/cc1646c6a39a1ef015fc0dee175c8c3e82d9347c
./engine/tests/corpus/b1ebc2cdb967b902384c7de34bc01a5498e5f023
./engine/tests/corpus/3edfdcc35c784f4f7f4c715d7ce3d181dc124204
./engine/tests/corpus/62fde8c3b921edc3ddd7b97493335cbd59e8b365
./engine/tests/corpus/f56180360cffc52574d30e89566d8c73a160f50d
./engine/tests/corpus/c95b4dc0be98aa377297e0f4c4cd1770671f84cb
./engine/tests/corpus/c458861d2054f46d479831a837085f6121b038ef
./engine/tests/corpus/72f42c3efb483fd81929478d6390f4011b251b45
./engine/tests/corpus/c2529415b51acc73e693656c8de30ad86979ca11
./engine/tests/corpus/aae07f2da31370ce274b5060a553aaea2683e058
./engine/tests/corpus/e8acf500417f63caf09df84e635e1d86a4fd2805
./engine/tests/corpus/a1fbced4bb5d6a46439c3e71dba4b3a97a52c19d
./engine/tests/corpus/183589bc2d475c83d066604b75ec41204ecb3718
./engine/tests/corpus/2fe32ffc350c1f2d6d6fe3a68715cc902ce5b8e4
./engine/tests/corpus/26a769d68d6438157b9ebf546fac323623801431
./engine/tests/corpus/517d5660db416948d7b0d47e4306e5a85f74281e
./engine/tests/corpus/5c7438af8e093711df5730c6cecc1ae9a726101a
./engine/tests/corpus/af89332a64a630e24a191495bfb8a1e59c6f6f98
./engine/tests/corpus/6acbda435aa16043130bad27764e1ee0ad379811
./engine/tests/corpus/d894ae7ad5f71db1a1f376e1413b2120de171bf4
./engine/tests/corpus/3a711771215e418d98b821b2554a192e0bc4ebfb
./engine/tests/corpus/56854267a6b654336516fc6c86f91c2c54aa8f3d
./engine/tests/corpus/24fbcee1eca76a388512e4adda38372eb7433d3b
./engine/tests/corpus/e5496d4cb40f9b4be04957df9b03622b988b81c4
./engine/tests/corpus/3643b98f704746febce64490d1b78699baf0f2d4
./engine/tests/corpus/389acf4e82308f0087ea823d9b7a7cfda8114170
./engine/tests/corpus/85d7fc91f1e0aa1a562c81be2ff838d6ce7b9934
./engine/tests/corpus/f926ff3ba53a6f03e74fc36ad94a6b11e65093b2
./engine/tests/corpus/4eaa387ba5aab8aa9accc950bfefc6d09ef4b4e3
./engine/tests/corpus/a8e1f64da70678a452ea7666e8cae12afa68815e
./engine/tests/corpus/418158c1948ef4cb51822157b7364549f6d34e0e
./engine/tests/corpus/e4e47874454e6d5e42eab8b6df853f73d3233581
./engine/tests/corpus/835814fe74d7fff9542b3f41243b6f80d217431e
./engine/tests/corpus/b293ca8f27135ffae79124b2869c4bb9b36d2dcc
./engine/tests/corpus/c196e8a60efba65baf1d0f75c8cb97bdbb9665ed
./engine/tests/corpus/431102a3679307848c1a673b07d8a70197dbd0dd
./engine/tests/corpus/a27e8a1892ad60ec096d174891435a704a9465b6
./engine/tests/corpus/f1540236d464e47c346d3d96f885f618150b09a6
./engine/tests/corpus/b3080c68440e705a1772a18ccbe685891b092be2
./engine/tests/corpus/3556e3007795f91683752d61dcc9f5282dbda9f0
./engine/tests/corpus/0a3e9582bf32a329d56410dfee050fd5c4904e41
./engine/tests/corpus/31d204ad2d3a8f767b4bfb129d0a2ad111db8b14
./engine/tests/corpus/17cb46b8771fb6a8a8a916a48957ad8a5c955f1d
./engine/tests/corpus/5260dd1edfbd4e3d960951c9a729fe84922783da
./engine/tests/corpus/9198b81c8ff5afa30f5e9e3a7d747ea201377179
./engine/tests/corpus/96c76efa4bb968e6aec65051569dc4ae1f2396a1
./engine/tests/corpus/5c610cba148cb6a4f29bff32f51ea3fade8838d3
./engine/tests/corpus/b7560fa51704f410b7ce715cb201d082a20b4f58
./engine/tests/corpus/9ad1895838cf5925a5d4f4b00cc847222a126195
./engine/tests/corpus/6161c8467505f028b2924f94583e49ada08733cc
./engine/tests/corpus/0f6f4ca028f65c3c220a1d63572bb0eabb887895
./engine/tests/corpus/aa339444542dfee2449dc3efe3913165c4875188
./engine/tests/corpus/c4c5f4d5070ee79c75d13e280a7ab9c4b8020d56
./engine/tests/corpus/52df6a150a2183c3bc346d31f6f2635dc25538a0
./engine/tests/corpus/07b026702106da73ef12017bc4d2a13175380f73
./engine/tests/corpus/8f03294e375e711480fb803f9bbf35d87dbcf319
./engine/tests/corpus/dad627424d48155b6f2bd9a1fdfe0c05097290a9
./engine/tests/corpus/8c2bbce2d4deaa8b059cbf88afdcedd89e9fe744
./engine/tests/corpus/d448ee3fcddb8ffe77ce705ef9a201b810c644cb
./engine/tests/corpus/d643aa2ce8bcb536707cb2584714793f0a773446
./engine/tests/corpus/e27a65887809848122eb9f5bc87db6b825aa5d9c
./engine/tests/corpus/76b75f9a2aaad4f4693e3f157a352103c094e057
./engine/tests/corpus/7289008c06aec599e1ff0cbb09addfc63a6e14c2
./engine/tests/corpus/01c7610f21486af3ede0a8c592cb803a8de394e3
./engine/tests/corpus/d17f645e2eea482ed3af63f3188bb5051b543b2b
./engine/tests/corpus/059c1b6262aa2f332eb86445ca72b8186dc90486
./engine/tests/corpus/d5afee0edebb6a88e435e5c5d66eb5860090eac0
./engine/tests/corpus/bb196fe2079cb62877df4227318e3a19925bd44c
./engine/tests/corpus/2eee691e96b8f6e00c06af4b23526c568f12cb9d
./engine/tests/corpus/358732452d6bde8748507c7da4193f9897748d2a
./engine/tests/corpus/07c6f02e49dd2b9530a810184f7f0b4156f459d9
./engine/tests/corpus/6c1bf63e179214da0823bbadcba2692b3c965f1a
./engine/tests/corpus/855dc02145a6330a58f73ee43a03401407783bff
./engine/tests/corpus/926a4f07b59e4a9bb9209aa6d5a93dad61045f15
./engine/tests/corpus/8befe2105d3b3e231845e6bc15384f45685f088f
./engine/tests/corpus/e7f97f3b9116edf27b79ad87916d87a9e7eb170f
./engine/tests/corpus/91c0c2e82506ac3677bac024670d706a281d282d
./engine/tests/corpus/51dd5f44b8e355f384394ce75257594dfccb5435
./engine/tests/corpus/bc447e6ce299a96415c51003d751d9589037e291
./engine/tests/corpus/bce679ded07da565d60ddedf185d594d6515622c
./engine/tests/corpus/d3b6ba4e97556df48757805912ae5db4209f13e6
./engine/tests/corpus/b8649e0cff6ddbb45606f2a97129a268d7f007b0
./engine/tests/corpus/5f7235c29e2903d303edcdad9f76667f28365f7d
./engine/tests/corpus/f13e56e2908e8d1836752c6b605e22950f982b22
./engine/tests/corpus/c300ffaf10636a1d2b127303a96d8836d3c20c27
./engine/tests/corpus/8f1cbea93c9562976b0cc980f8cfc2e17c9ed1dc
./engine/tests/corpus/966c85b78acec10277722480e44dfbbed5826a83
./engine/tests/corpus/343c98adc63e57f75e0f7748b44bcbb294a76e6a
./engine/tests/corpus/facb0cd1a73a0a946f5226665ab171fa42a7afdc
./engine/tests/corpus/9d03bbbd09ab46896bfd6ca30ad015f42cf8d422
./engine/tests/corpus/556f6c1007ba173cc83b5ff293abe0148ab3c580
./engine/tests/corpus/f7a0b8f6ce078b9ff87402810855a451ef6ccac8
./engine/tests/corpus/85fd0e9ad723076c4ef818d220e6281dec5bf994
./engine/tests/corpus/a07f8655d79ac0e9e3248c52d7c2576fad50cc4f
./engine/tests/corpus/0423c4b4cb5c2e3b227f2ada9744b57558be4579
./engine/tests/corpus/e9726a1d25538ae94deabb746212169696fd6e45
./engine/tests/corpus/bc3346f79749ffafe4209c6fd3515ff54c351267
./engine/tests/corpus/6fb8de761923049dc5e4d3c089a4a4117c85e7b5
./engine/tests/corpus/216f225f1babe561fbb8f4bf41653ba55c3c78d5
./engine/tests/corpus/05aed004eab35f72bcee532332dec3b42e93324f
./engine/tests/corpus/04fdaba4ec37891af041187facaa7f8c88dde770
./engine/tests/corpus/9628a218fabfa08aaadf0d42de570549ab8763c1
./engine/tests/corpus/3d05adf14cf7f97873dcf477a07f2caaa5d6aa21
./engine/tests/corpus/e48443653ec791219d97726c3e0acf2f78817e5e
./engine/tests/corpus/efb290c7365aae4af661a446f01cc60391f4a10f
./engine/tests/corpus/c4452fc3c4f401d647ca48bca09a2823f9cdc1b8
./engine/tests/corpus/8e8bcb49f4cd6adf07325d9b4261742dec168cb1
./engine/tests/corpus/e839e956b214598acfbf55423352db9b3535b3fd
./engine/tests/corpus/c639af69f4ba4466a674c64600b9e9e5fc898f8c
./engine/tests/corpus/2d2c45a154dd97ef19d7402c1d7dc787cb2c74c1
./engine/tests/corpus/20bf24b291c77b31b46748749027d108f6afc0bb
./engine/tests/corpus/ccfd406db6fecadae374dbd1edc73c8a5805b4dc
./engine/tests/corpus/e9d1bcda67ee6b042ebb4d2d72b90fcb680462e5
./engine/tests/corpus/e0693f3f3f68eb51e98fd709149618ebaa95a94b
./engine/tests/corpus/e927388c27742a9162e94c9d3e30b414e9262444
./engine/tests/corpus/ae563284982b6d12d79823cd67ce542c45dae38c
./engine/tests/corpus/68f889337f0de37ae654f9f58a0271a4bde59083
./engine/tests/corpus/b84a154c21f5b522e072fc41b4d542cb47db09ce
./engine/tests/corpus/de2badca342b9bf010a7d21f4b936aa980368d5d
./engine/tests/corpus/2d88373b89b68cdf47c4ec2df81546f1eaaf494a
./engine/tests/corpus/2ef94f845019acccaf1f7b10da09cb82c8c69e7a
./engine/tests/corpus/ac5da2c0d52f4d92aacd31d14300accf659adb97
./engine/tests/corpus/5f369d6b6df1d7754d2a857ff529c2845679eb11
./engine/tests/corpus/ff0ad178912ab6a620ec667bdfd59e86de270c53
./engine/tests/corpus/41b481e9f783181b2f26a5a32375feaa4003ba45
./engine/tests/corpus/30e80744a0cae0f4440470d23bffb4f6a1180298
./engine/tests/corpus/e24c6672d4ca87ff6c255becbfe832f8eb6298d8
./engine/tests/corpus/cb8649ddd9ffbe590fac30bc6d7bb40597c2acb8
./engine/tests/corpus/0f9eb9e636dbd2de7b92446749338846dc4cdc8a
./engine/tests/corpus/1680763e59568009721512526e7c56a3845048e4
./engine/tests/corpus/b2461b6ba0d30ae8054ba4a7bf4fc42b38099ca4
./engine/tests/corpus/8e3642be51f445b772fb6f96be4fcf0d37f722f3
./engine/tests/corpus/a4c3bb4bd30a0ec006c8dd187661420fb6fd6984
./engine/tests/corpus/3b89385187da2706b63d6785010246cfbdb31b49
./engine/tests/corpus/0a2335327d812ef00844e857cd866b66b7203e2d
./engine/tests/corpus/e460f1106c22f52aec328f94530a94f6583b1f44
./engine/tests/corpus/8ab7df7bd7534ab29b6be893517aaece903ff01a
./engine/tests/corpus/ee872a413f5fd873d69d723ba6863d23635a1dbc
./engine/tests/corpus/ac7f7e79ab349631de045110b3c8e19c1d3e4fb7
./engine/tests/corpus/9a6b071c3fe16de6e0f4d26eeb4d253690645aac
./engine/tests/corpus/3e20f8b3cf61a2bbd26d1d7ece7a442089214c1c
./engine/tests/corpus/742ef393871dee8ed4463cf16d1cd02e3d0415f0
./engine/tests/corpus/25d2c5f4d5a397a6042c9523a480c648ab8d3df2
./engine/tests/corpus/4a5c0689b76de4fa2fd6980986abf65dd6033233
./engine/tests/corpus/d08f502ee83ca110542795f91f2534664e473e26
./engine/tests/corpus/6c124bead6b9ef8bf22d523d71ffb14bf7f78719
./engine/tests/corpus/a2111a76aad806bbfeebaf21e0a16f843d7c8892
./engine/tests/corpus/9f1457056d998ade3f876c2e749d13fad31b5fe9
./engine/tests/corpus/b4cb22aaad31afece615dd973a91ce9185577d18
./engine/tests/corpus/879f6d57897773f70fa42e9eb27e76d9bf68601d
./engine/tests/corpus/804a88cb3c6d8ef1339a450de0b309b5599b0d2b
./engine/tests/corpus/861b257d3ea6f2fcc0be2a82c6f94df870ee102a
./engine/tests/corpus/d6115889f2cab5e8744559315708364b3208d853
./engine/tests/corpus/40be8fab77557b6497f3d8dc006203d5c47e722d
./engine/tests/corpus/9dd3c1faa4e5930f3666245582803798e23b78de
./engine/tests/corpus/48917cc20bb2a7901beddea4456e1b9c2010cbf1
./engine/tests/corpus/27d7bef36350e87599e0f6ce9457414143dcaadd
./engine/tests/corpus/426533b227ce13ebd74dcc176ed92b832a807688
./engine/tests/corpus/95fc6626cef732ae5285dc3f99e31b7c04364e1d
./engine/tests/corpus/aeb15052a92e1c566237f97ee9ee0addc90d8dd2
./engine/tests/corpus/4d2728d9b13204d13b614895db9f21646098e7ca
./engine/tests/corpus/2ecf6c31ca348b23c649b2e5988e9529c1143539
./engine/tests/corpus/b643f5f62158bdce06dba1b8aa538773851d1b61
./engine/tests/corpus/2453dcb6e76724127625b0bc43acff4d20186170
./engine/tests/corpus/3665b70749277bf6c81175c50e8505e7d0ef4629
./engine/tests/corpus/966898d5ce76d33c4719afa63c63fc161b032d08
./engine/tests/corpus/06c489969b07dbba0825e660e0bc8cc9e3e557a2
./engine/tests/corpus/f2a61d26c0a915ad4b4d7389ea9d65994b82674e
./engine/tests/corpus/8d27ac1749bb8a2737ce15e83ac3ebf969098f18
./engine/tests/corpus/29a6aaceee98ae7448317560d5c0e944f0dc2a43
./engine/tests/corpus/5acfa53eb41aeb892739e8030dc79564fa63b0bb
./engine/tests/corpus/62d4caca70ee1e6e92e4e3030cde42b73420d976
./engine/tests/corpus/5afec8548676d1f3fd2f4f74d04b354a4003e660
./engine/tests/corpus/17d8d46d607eb38e48ed80842abe79a4a24d8159
./engine/tests/corpus/42323653e604d39bfece868b96566ab9e2515400
./engine/tests/corpus/50a06ca9ef873cd3d9c614b26311ca2538924530
./engine/tests/corpus/98f7262863b7a37f5f5b33cdeee9b5fbbc17f03b
./engine/tests/corpus/c413793f3c38dcd7e2ee9b0d363af5f4bd75614f
./engine/tests/corpus/14ac61e8cc2e4ee815d80b18d446eb4222ae5d9f
./engine/tests/corpus/e32e9a6929f10d71f3e7d26000bcda685f3c519f
./engine/tests/corpus/8b4f5e47cb4a7442890db7f254b4d72d95686522
./engine/tests/corpus/96ef6d5b5061cbc3b8ec0ab3fb3206fe6fddae0a
./engine/tests/corpus/9ee2d2ff8bf38a8d2c3043ae640b84241991a107
./engine/tests/corpus/f904653c697eee3663f219103018eef6a0d6754f
./engine/tests/corpus/cd63cc733653aea8c5765f4f4901aab5ebcb178c
./engine/tests/corpus/77069694f23377ffa4e46d985fbc001dc3a1d356
./engine/tests/corpus/37b8b4e536574bf425c0dad41c0550e21a15ed4c
./engine/tests/corpus/c0a51ad768574941f81dd35837ccfb71c3ed4c9f
./engine/tests/corpus/ea8c9a2745ef7466808403e73ff4a1a2cf887ee0
./engine/tests/corpus/5f060c34c4e4798a37e6a6f1fb11d9d7aeccffc9
./engine/tests/corpus/7443e28ffae26eee640b8ecb9e9987e43e766bff
./engine/tests/corpus/29b0f86012080cd7a5d10479a3b46dd054cb48f6
./engine/tests/corpus/247ad97a22ccb5ea1e073750db0e61adeb8dcf99
./engine/tests/corpus/a11c97715dc5327fa3a5356557d02bc5405c0921
./engine/tests/corpus/143baf6c6d6454b5b9130b8ee494460637f2888e
./engine/tests/corpus/0f59d38d37bd0f8a40cfbcbd6cfa1b3db1135ea1
./engine/tests/corpus/15cd0d2a252ecef2a9cc6d0767cf76a5b6549eb3
./engine/tests/corpus/cf1b6fc18000bc6b9de40617242dd79378612399
./engine/tests/corpus/7262e8062d7766fc8dd86e9628146a7f2928d172
./engine/tests/corpus/21be2fef3165dd66791fdd3afc77b2622bef6646
./engine/tests/corpus/8b9aef226e6ea307b96aabd7a71a6ecbdc0f28aa
./engine/tests/corpus/acc01e4edff5cb99f6d5985717ad913ecf350b8e
./engine/tests/corpus/034efee10369bddb9dd5cad42464d847c9785894
./engine/tests/corpus/875f7c015dec5322252294d2d78665f14960d49c
./engine/tests/corpus/9d1a5db1851ba31a8fbde6065fc55e6baa7e8b5c
./engine/tests/corpus/4d43b829861979d7cefd749e4623ffe900c6f1ad
./engine/tests/corpus/7f136c4d582540c6b80609a9c036fe5cb2b7662b
./engine/tests/corpus/4767a50b3043371a3c33ce50e44980889ae51007
./engine/tests/corpus/80588bc391988c1eae32de790cb506a9a18cb6aa
./engine/tests/corpus/0513fefbcc4a009cd01807b9ed592095a6de3293
./engine/tests/corpus/e801bf8856095e01faacf91b94c0999040f47240
./engine/tests/corpus/d8bb89168440d68ae0ee2f2936e899615622d966
./engine/tests/corpus/969ab86833ef5a9f3e291afca746afcfe4842aa3
./engine/tests/corpus/775dad8d46c970cb4eabc3b3728c5cafa88e9890
./engine/tests/corpus/36c1e5b42c1470626bf94dab57c49522081410ef
./engine/tests/corpus/a8e4eaf679ed8f571eabd0dceb4332d55498dccc
./engine/tests/corpus/03dd238ffa551932df7c484fa920d669b374a5fc
./engine/tests/corpus/3e07a8d34d65ee5c1e6aee36897576c6e3c57bca
./engine/tests/corpus/0564b404eb310695bcf09002108faf53515ff97d
./engine/tests/corpus/ac356666599d6ae102db5cf1e499a75404abdb63
./engine/tests/corpus/846815062ef1a348f233190703a73dcb96bb5232
./engine/tests/corpus/dfd81b671dd5028062aab5e68d244db1ae498780
./engine/tests/corpus/2fda71dd79c43e3ca3a4126a6a1fe10e0fe04bac
./engine/tests/corpus/d36c4becf17e953e9124d4b826ef48dc9954d04f
./engine/tests/corpus/3ab0fdfdfbc4562e3cce59b01e72a497130f86d5
./engine/tests/corpus/a8518158d8911d36561bbb2e41f8e6d4b4307e90
./engine/tests/corpus/a2ad47a1ab35986dcae4f7e51e827cb447d37714
./engine/tests/corpus/14a07c95de541019bb0b1f401bac2d0562de0de6
./engine/tests/corpus/6d2c51cc37507c1ccf6bcb84fde8b76549a07b27
./engine/tests/corpus/dbcf5c3351037cff230bd6815dc448f02931ee6f
./engine/tests/corpus/975716be8b245d08192988071ff8876f1e415343
./engine/tests/corpus/178ddba3b59ba449f06e6d948045c4eb0f9998c2
./engine/tests/corpus/7d72f4299b12a26c309073e96f88de160420b0cd
./engine/tests/corpus/ff39a362ffed962367381c1324d8e1299f730abd
./engine/tests/corpus/5832c646969f3cf63143b3e7a02f3a10df27061c
./engine/tests/corpus/37f0cf6ea6d3c4e96fac2f9676e3e140f3a14510
./engine/tests/corpus/6044ce55566b9163053d50df483bf39461d25fa8
./engine/tests/corpus/a50ca4b020c9dd578bbdde50aa7ad69ff1939c2e
./engine/tests/corpus/e89b02eb62adfbf552caa649e43a81130dd01ffa
./engine/tests/corpus/acf4b570199524c699ca5774a8f582c667d7b66d
./engine/tests/corpus/684f15c2dc36751d49d671b7ada9c680f9ad554e
./engine/tests/corpus/ab1ff47a7646eefe064574895f7b20e3cf5217ab
./engine/tests/corpus/d7c7563a737f1ebb3ff194e34a97b4bf44498f39
./engine/tests/corpus/2cd00c0314bd6ede929ef2af1052573a9607b059
./engine/tests/corpus/c0e46d4477a5df3e816aebf8799f205d207d16cf
./engine/tests/corpus/8a776f56f36405b067fdb81ea93da1d02a095e70
./engine/tests/corpus/8b9ff6e988992b35728335bd05e31af9f8203392
./engine/tests/corpus/1014ad60af122977b7c4d9c93bd2965371fa7655
./engine/tests/corpus/c879ad8b3f8fbecaae445ce011b83f1bb7c1e581
./engine/tests/corpus/dc2ba79abada7863644be78a9fff4f68339f3c8f
./engine/tests/corpus/e3f40bebc5447e9c9697be2f9cab48f9d328ec7f
./engine/tests/corpus/2c4d40825cb8e05c3475a6091acf4ac0449bb1be
./engine/tests/corpus/fe776e62f6a0a269ae8f36254fd3b1ed90824599
./engine/tests/corpus/b58a7604f9df78b1b72f049ec4f0a36f6c34ca0c
./engine/tests/corpus/c9880200e4a13bea411ce5974b9830e9205165e5
./engine/tests/corpus/265e9ea51556791af78957e97018b13f746de47e
./engine/tests/corpus/e295582e851b0a8a7e5b20d5256bb73a8b0d1e5d
./engine/tests/corpus/be10f32005f1868ec36ea92f11f908a3f63ca800
./engine/tests/corpus/3289a7e36a588b64deb656d2b3d5802da9a0b6a2
./engine/tests/corpus/5c4b150a198426133cef1fe3715dc1e91907d1a6
./engine/tests/corpus/baeeb2968c8040a87a4f31919ebb55baaa145477
./engine/tests/corpus/e8696afffea919d0ea47faf643c8bff53db89aae
./engine/tests/corpus/c65be1673184778ee0150782ba7cb32aed6ca42e
./engine/tests/corpus/33e8aef8af2f12a475b22557c0ed56b5721bae8b
./engine/tests/corpus/fd08775b250e98313910225ab69683af11c6081a
./engine/tests/corpus/60de963146bfbc22e6178446bd5c8af476a15edd
./engine/tests/corpus/6b438a394d5c1907dc33f4987a2b216fd202b7b8
./engine/tests/corpus/ef35e5e83623d44220a171fbdf249050b8df377d
./engine/tests/corpus/b5ea3cd4286df15e155ac2752afc736e0ad9759b
./engine/tests/corpus/96654bafb54f8c3e6f0a8677d90cc4b7560e1aa7
./engine/tests/corpus/8da4a90064ae0f87569f740bf29bf249c8961e28
./engine/tests/corpus/66b0c300a637009913fdca859c6fc86b24dbd299
./engine/tests/corpus/07e611759f088cb9ae05ce9dbe54e2f0edfe8e90
./engine/tests/corpus/ea0e7002093bed4e963dc681b068070b9d44f7ce
./engine/tests/corpus/1386ba50539a387b962a7965a99c9ef81775cc88
./engine/tests/corpus/f6446cf3d1fc86997c041345f6045e8600e21653
./engine/tests/corpus/81cd74879f9f1f68a471496ee2b5b9ca51749154
./engine/tests/corpus/a63d51986745c6a91f1ef95282fb1c62db6b7756
./engine/tests/corpus/4e95e48ff3ddf3938fdedf0190323b49ba2f30f9
./engine/tests/corpus/0c0191a58da2db363355d34c5e22dc6d274ad335
./engine/tests/corpus/6ae1abda2481c40e01de68d57dcfa294a2729033
./engine/tests/corpus/9cff5c6f0b6109e76a2279b2c7ebf5c90f629e9d
./engine/tests/corpus/ab7f6a680d6542b2d5a1447634b6fe7ffae22afb
./engine/tests/corpus/592bfc43671890a30b9d3b9b304628cb1d5bd246
./engine/tests/corpus/d329139ea9921f9d631d73b320693fa2147e863e
./engine/tests/corpus/4d3b003171559cdc45d820bab4fd94715680893a
./engine/tests/corpus/7676ecefb54dc8adc0708b946ef73a7722af5bf1
./engine/tests/corpus/67540a0b2907c45fab0e611ebd5ed2d1e8ad61cd
./engine/tests/corpus/30fce8b0f084e0ddb9ae7f7679624014e8f52c29
./engine/tests/corpus/f73d2feae47b9ad9a473506543d208bbd847fb29
./engine/tests/corpus/52c3a00dd5d1e45904be6746ccd20a37d2d91f22
./engine/tests/corpus/7f48c1d491b53d109d19053b92fa7fd181fd6c22
./engine/tests/corpus/864aa98c771b1df0de939095e66acdb529696d6c
./engine/tests/corpus/e0fe9815398190b263768ccd7c183cb5f0575138
./engine/tests/corpus/39fdd60e8b83c5701b227722d60813a410ca6818
./engine/tests/corpus/9f5aaee6895757ddfec50df0bc0b1a428768b960
./engine/tests/corpus/d89210e1f4b900e3dd2a0e4d73d92b65b5a42e3d
./engine/tests/corpus/bba36a9d2bc5a1493bfb316d33a53e8b24def404
./engine/tests/corpus/7e78126856178709b7e360a437b010306987afd9
./engine/tests/corpus/da7bf85251ad64cd3696efd1c11753ceeafb88de
./engine/tests/corpus/dd03c14a152c17ea0feaca502306a8b713d71bbf
./engine/tests/corpus/88711fd5347a18b95ddb93e995b1a6c277a71e45
./engine/tests/corpus/a8ad63f0797bdc7fcdbfbe34d9f7b9a98c579e31
./engine/tests/corpus/e92d9757c88c961d8000eabe101def6bd3a1f7f7
./engine/tests/corpus/2de100efa66d76a276818d9ace293696def1a066
./engine/tests/corpus/cf6d4250ae7cc3b4f46c79a4997e6072a12201e4
./engine/tests/corpus/6ea32182cfcf710fb0c6840d06d6f549974ab67f
./engine/tests/corpus/2ea77e4c8148b4a2763e83db6cde5992f8220a17
./engine/tests/corpus/a36de708dfb31212d7f1a9140dd2508d7d38749d
./engine/tests/corpus/92d9277de8d93dbb3694624de64121a9e9531225
./engine/tests/corpus/097a4b3b31f86ae36f4b35bbe5bb5cdda5ca4cba
./engine/tests/corpus/eb5c8b7bd1085128002c0e45e9aa002122f1b0d5
./engine/tests/corpus/3e554b3a54f95e6150030b998192c727aee69dfb
./engine/tests/corpus/843f97017d1c341e3e41b67729608c16eff8550d
./engine/tests/corpus/b9e944e8c43afa2b5f827042bfe12703afa43dee
./engine/tests/corpus/c3210e4b542f87fb49ec5e40166219493aee45c6
./engine/tests/corpus/dd95b459a315a9db0ba3ec78e9ce83a78965bb86
./engine/tests/corpus/7ef3ecc6df9bae16d01cd830dc1fd1cdbc70b0d7
./engine/tests/corpus/f61cf71c9e5d420359d669e58a5dc6ccc76a28e6
./engine/tests/corpus/8a284b0a65eaeae673591d0be9b755fc1b6e1b66
./engine/tests/corpus/62682eb12e4353ce57faac17787623698c2abd51
./engine/tests/corpus/ec94850f94e2928cec0ca06f81575b1033dcc722
./engine/tests/corpus/60ebb1eb485c26a67fa45f9431c9d241878f16a5
./engine/tests/corpus/2443889d8a039527e8a11348e03680cc2084deb8
./engine/tests/corpus/0e014229c9a0e58aa8c0a67a526129b93975b8f4
./engine/tests/corpus/2da0c76c96059d0259dfb73653e0bc9667b1752c
./engine/tests/corpus/9385d0f0229a48b5e4a24178e373db0ca56a97d3
./engine/tests/corpus/3a93238a96fd86820619ff01b888c4b7adee32eb
./engine/tests/corpus/c858a47f42caa26692a2ecf6b51f591f413a3188
./engine/tests/corpus/a395acfc36df897a0477a32f4e6cbda1bdeedb12
./engine/tests/corpus/040f669c3c71eb64bb6d014388500c889cb15795
./engine/tests/corpus/d5fbcac36406557ce73661eaa7bb1a9893d8f7ba
./engine/tests/corpus/26db31f81bd8fa25459c792301c8a70d5a152288
./engine/tests/corpus/e38c95d32913e481ed4525da63b4ca5b0aa9410a
./engine/tests/corpus/e477a46de623d1cd838417ef25a45df88276ae43
./engine/tests/corpus/a607e40c18e463714318dd7dfa4d5ca405db0f0a
./engine/tests/corpus/c3f629b0407a3b54191375a87760ae2616715574
./engine/tests/corpus/dd407e70f7ede43fe1e7a690ed7942e32ca2c61a
./engine/tests/corpus/826cb526862a68cb93bbce1469e05863a1b898f1
./engine/tests/corpus/29378097f6c2ca4cbed5eb7dfa80b5b4da951ab0
./engine/tests/corpus/3bcff929dfa292e7e8cf091dc1419bd83c2f3e64
./engine/tests/corpus/c68dd83b4a81c41fcb4e204ec5ab3fe198433aac
./engine/tests/corpus/87941617f40231c8afa32541b48479e49a408420
./engine/tests/corpus/ae684a88c84e295ac26df25f0e69e6c1a556b91d
./engine/tests/corpus/185661c4e068cf36c0a2bcf71a6f1222d93b2cea
./engine/tests/corpus/194765f9adb8bd8b79440474f94512157d66c140
./engine/tests/corpus/900432356ba5994cc9dba3c966657f4fcb1fdc05
./engine/tests/corpus/071e7c90ba614fc35a494af1b1381223333d959c
./engine/tests/corpus/d140f2f765e5b516c929660b6856406e55fc5d8d
./engine/tests/corpus/6e5db2c2177b3bc93afe70a3600eb18982b05bdd
./engine/tests/corpus/f605136b7a98e4f4feae1cd61829e81d1359f5e1
./engine/tests/corpus/9fb537813b4a3eebf7ace974047595af2c81f749
./engine/tests/corpus/ace6c2cd5a8d78baf2e54c121490490f44ef2a48
./engine/tests/corpus/e3fb96b48c882e23411457cdbfe7b904c33631a6
./engine/tests/corpus/90e4d43af0220a5b92939367bffc9be722e84b05
./engine/tests/corpus/8c3b859037209b2f66399c87fe6e27a90df9b2d5
./engine/tests/corpus/733ba0565aaa06973cdea4c5c3120442638d4e4f
./engine/tests/corpus/98273e7ab68251104de55b8a38c913bc134f36d4
./engine/tests/corpus/19b1cfa32ab0a47f910e09475d7ab20ad7254e57
./engine/tests/corpus/8340138b3e266d644e034d5da612178c5a36e62c
./engine/tests/corpus/3b59594139db194f9fc400b00357eb1745e201fa
./engine/tests/corpus/70aa3dcdffb48b711169d9ac5b8b17bf3bd84540
./engine/tests/corpus/c78e6b11a4a82dabb6d982f27eabf6f9a4663a31
./engine/tests/corpus/9f448664559812988b4518ec839f89f2e843734b
./engine/tests/corpus/fb88e50ff0f3b21e8775864a927a897c3fbdd355
./engine/tests/corpus/84f13008aa2bcc82f9aebd3e41dd6a4787b0c924
./engine/tests/corpus/fd942fbfe96263f39b1c9f88f2dcbbe85a6f99e2
./engine/tests/corpus/218581b1330c2b6eed41c5a777f59dfd68c6ff05
./engine/tests/corpus/366c1d8ba5e7b89b991fafb92a16b63813d640e4
./engine/tests/corpus/aeb091857a2a1fa04a64d6bb3de1a6bb03ed604d
./engine/tests/corpus/a1f4dc589fc0aca9246c65f47b4907a647e4bb8a
./engine/tests/corpus/827a3d49d8278388687179207e6799f375cfdb6c
./engine/tests/corpus/cbac1457cbd485cd240d1b58a29a405f04245be8
./engine/tests/corpus/3cfa4618f9896242e183e429b61e79bf5bd0da99
./engine/tests/corpus/96313783c8fc700e2451559374bb11595a495d2e
./engine/tests/corpus/b1c4f4952a102e713a50c31f263e6aa48633cadf
./engine/tests/corpus/42c0d5eb5a8e517570e2b77c92f8effc93404673
./engine/tests/corpus/539776872ed209cd198d216618695b123011bad3
./engine/tests/corpus/6c14c83de9aea5321a7f2ae3bcee842180b87cb2
./engine/tests/corpus/b5097950aae70cc4cdeef86dc9f66b67b7bf5cad
./engine/tests/corpus/d37095356933258f3465005136284b4334acbabb
./engine/tests/corpus/921f817e574c547ae34744da633404278709b4e6
./engine/tests/corpus/cd7190ca86fc1ca7519047b81ac4b34fe877e5c7
./engine/tests/corpus/35801526d36147d2f507a3a232def1d82a9c1643
./engine/tests/corpus/87262c42d1c872ca171f0e6f51ecb28a0b777e60
./engine/tests/corpus/2b38367be73196193daebc502da324401235eb5d
./engine/tests/corpus/636c26d99a43fdeeb4b591784b90df7fd8606b89
./engine/tests/corpus/506116881af387ce11f3101d466e56f02b697c37
./engine/tests/corpus/7c5bd6056c8edd72f953f38bdb450f3d22102278
./engine/tests/corpus/d5de5669843034a098f9c41f744820a692c5f707
./engine/tests/corpus/5fda30538c9c8898ed7ab7b3fd88f798c75b6f9b
./engine/tests/corpus/bdd07058aaa7ec9f918fd1e34c26652d933effaf
./engine/tests/corpus/7e8aedba8621ce4ab6a67c9479a4ee9e8efd6651
./engine/tests/corpus/2da6fb242da80aadaa2ef7228ed0a7894fe7af3b
./engine/tests/corpus/d29826f2ce8a1b676d2cffe8c2d0baf39b9f3abd
./engine/tests/corpus/023bc3e7c129b977a20fc36f8fcfde950bd3b166
./engine/tests/corpus/dba4f8e8af83d863b34d040ba0cbf8c163622f36
./engine/tests/corpus/d7df98def8088493480f0f5edd5729635bd73b83
./engine/tests/corpus/19a7a248295aeace70a3901a34788acc489d6aab
./engine/tests/corpus/01759c654401950ea71f5d69652f60688b96e811
./engine/tests/corpus/9078af06e85a6d5c12ff844fe1fe6fb9f084d9cc
./engine/tests/corpus/f7fd573aa30dfbb7fe9737e71c4670f878f51666
./engine/tests/corpus/ee83070c2164efbdae97db2ed2a095848f0a4e2b
./engine/tests/corpus/808b7b6ab820b48884a77b989f12ce6ef8afb4e8
./engine/tests/corpus/99c2ed7918e4b063dcc9822a11ef8e1dada85ab6
./engine/tests/corpus/56cc38afdf52b8d666def24169560c16d91d853e
./engine/tests/corpus/6b9c413e41e6eb1dd3c2e9943c5b53298af2590e
./engine/tests/corpus/ed2a13c8d9a1220020ed24abbb79e6e235142df9
./engine/tests/corpus/847551e96345c6fc9df060ada96a142c427d18a0
./engine/tests/corpus/32793e71faf71a586102b2231f7b8fbf0125e537
./engine/tests/corpus/76940dc873edace881df1d204bb2106e163809ec
./engine/tests/corpus/7cfafa59a02d831c1329e15da9d482492eee926d
./engine/tests/corpus/218c6aac294e6499962e2f7df123986b6bf1d085
./engine/tests/corpus/05ebef056f9436ba164dbfad4883e7e61b28267a
./engine/tests/corpus/58b14ef832612f227af05fe2ec995121fd80b583
./engine/tests/corpus/aeca55db60b37eb885ff58477bc79e080a27c48f
./engine/tests/corpus/90f0ce6f104b92bf3578f61da706a557cf8e8211
./engine/tests/corpus/0fc8d4a67460e6649a47ea7e9e7d34678a7c81ab
./engine/tests/corpus/8b83c7a2b84956aa5b1833647299de276abdd247
./engine/tests/corpus/0e8154c5fa29bd1c6f267eabf8271ce8582814ed
./engine/tests/corpus/543618d6da4cc91bf55e7e7ffa55f456369d5458
./engine/tests/corpus/161a218021eee34787dcd46e1d5a02b62e5af07b
./engine/tests/corpus/274fdf6bf67d797d8781555266ecb7c9e113c0d1
./engine/tests/corpus/37839008d064e917f67dc00eff5007a645c834a3
./engine/tests/corpus/d2a4ac0f7b7a3578b040ec8a53fc9154c1eb1695
./engine/tests/corpus/dbb10306763ca28d94a13a8873c9b3893d3135b3
./engine/tests/corpus/e9a4a5f6cf5dc73cd4ad8161950cff1064d9d215
./engine/tests/corpus/ee7aad12c202e5d2512f093305ff652e223c3bbf
./engine/tests/corpus/f04f100d47ac46cb3b77a775dcad72ba2957eb3b
./engine/tests/corpus/48dd9e2f18a0ab759d99fdfb0d92ad5dd4b6c672
./engine/tests/corpus/eecd864a59f935274d04c82506d08f3442d97de5
./engine/tests/corpus/70da4e973034ae6a53593b94ee48c54ef85e432e
./engine/tests/corpus/194f311e7ba86d175fd94e7c8f47a4e674bc5392
./engine/tests/corpus/aa4dfaf9d817884931e5ea7864a8da91e0990a5b
./engine/tests/corpus/b85b5c4fb820a2e807c49c70c7c724b9bf11c337
./engine/tests/corpus/911bc86e1588736f71b72f5eb47e7d291670cd87
./engine/tests/corpus/ca508405a8df0ea05b91b0267d1b121d201994ce
./engine/tests/corpus/1e39225de8a14294c296837be4aa7142ffb5108d
./engine/tests/corpus/11a0e95970ad484a358ac4c8787303e8516a56b7
./engine/tests/corpus/e2542369b8dcdf8b8e1b7733091e41ed9e054080
./engine/tests/corpus/40b5c0ac63c3c3bc138d03c60f971d7139c9faa3
./engine/tests/corpus/b25b68c5fa9f47236f998c72de79360c0ec898fd
./engine/tests/corpus/3936fa8ab0bbd94c92df4d6a82abb37f91297609
./engine/tests/corpus/ce6c0e8dacfa79a820b5bfabc96df4c17dc8dfb8
./engine/tests/corpus/f696a219894d5859583b132bde7a2c92091262b6
./engine/tests/corpus/57d43b27aea3bc4d4eae0c0d016fd114f0369eb5
./engine/tests/corpus/d3b95b8b113b68749bafd72305f7d5387ee2f75a
./engine/tests/corpus/d246419d05b158314a24f24c67f33c980c7d4d17
./engine/tests/corpus/631490b06d3462aec7d5072aff158d59862eeb97
./engine/tests/corpus/2f8469e50571a6f071280d683ff5126752f59f0f
./engine/tests/corpus/df26aa26987da0a22cce3efa2c7665e27b7f94c2
./engine/tests/corpus/b2a5d894fb15496151cfd6f3ac8e308531327be8
./engine/tests/corpus/0dcb34ce2fce3ad23c8c09401a7ca23320fa01ee
./engine/tests/corpus/c867b61df67a04771724a279df6f8f6ca8e68821
./engine/tests/corpus/1ab967dfd1c5665506f1ab965aef8e25b771b735
./engine/tests/corpus/648c887b35b9faae477f95e038f2c7023e324fdd
./engine/tests/corpus/1090ea20f0f2d9a2def5e16a02e8aa3f72bd24e1
./engine/tests/corpus/5c8e5bbb07a84b8119e4cac19fefac1b352c5855
./engine/tests/corpus/3797d74dd22af35ebef62937e1cdcaf9e165427f
./engine/tests/corpus/b125f03d98885a916f02f1ea500f0611f0dc857f
./engine/tests/corpus/37eeaa537aea5e779a37c78cfb68aa4998d3867b
./engine/tests/corpus/24452ef8fc9943cea4752c8babf2ff0b6e421eca
./engine/tests/corpus/465e84f5750e70653905702d2f249b07e1aac591
./engine/tests/corpus/bbdf79fbed3bafd2725e32abebd2174de1342b13
./engine/tests/corpus/b3f23c6acb37f922043a3ede9cf4ed33a50baab2
./engine/tests/corpus/a3de00c4b68fc000c831196426ae77332b38b703
./engine/tests/corpus/8b145187c10039878728def9270ec8f250c6a5a1
./engine/tests/corpus/eb081526948598dbef6dd17c0e754957ad8331cc
./engine/tests/corpus/3aa11209904ecd7a219fb935ce2b6cc3692f0b88
./engine/tests/corpus/14679b57d5da2b3652cb10191d88e419f862b84a
./engine/tests/corpus/da188f144ed4cb0c3892d52502d040df3045846b
./engine/tests/corpus/46fb7d6270b8d011c925806bf96469b2de206c13
./engine/tests/corpus/e9a816c5cfea3c191ed508fa1485df2d74781abf
./engine/tests/corpus/f7f9695ec2b243622b114c0d7b1c3266ae3d0918
./engine/tests/corpus/1acd6f95cfdea8b96769fdc55b404120ee90d9fc
./engine/tests/corpus/c810b1f607885e023294b9a6fdc99a1a4fed5d18
./engine/tests/corpus/1e5918072e05bcb53c78cb5cb9e6f55bd9458a2b
./engine/tests/corpus/5c7d7724c694afe4a5254d2624e2ef66c895048f
./engine/tests/corpus/031d604ab78aabee970eea0452b99be7fd2c346f
./engine/tests/corpus/c62bd32c3271153e37998e90814cc639cad1855c
./engine/tests/corpus/427712976002a0a6e0ff03912a9ebfb1e505db11
./engine/tests/corpus/94519423b7be9a50e1b7f8d694b2fe0ef8911bb9
./engine/tests/corpus/a416ea2bab3c0db894c96397bffc84b4894c2a28
./engine/tests/corpus/f0f20833bfa64bc141249687d0cde93384ca015c
./engine/tests/corpus/b0a721cb1a31ce027b00c7c5e8c2843ee34bfd70
./engine/tests/corpus/ead696516ef5930eff9e81c11ce6ef3c6a596db0
./engine/tests/corpus/32e43d303467417cd16b89c3d2ceda06cb4ee7a2
./engine/tests/corpus/7b1674d4949ce0242b9f9595b67a56bbc8d5db36
./engine/tests/corpus/a3ab28c2135aa9ef586bad23626906d7e6b19cd2
./engine/tests/corpus/4e410d10a9e256d42d02d8fe43455ac1fb2ec216
./engine/tests/corpus/6442f3f25e56ebe8f8cd95e99bbeca3290fcc3f1
./engine/tests/corpus/e44b20fd9642a3ac84dddb84710431c196ce385e
./engine/tests/corpus/7d39babb29c2f8810884d9955592f0e4253b8fa5
./engine/tests/corpus/5920b8c4166c395250f545d6098fefb22f8ecf26
./engine/tests/corpus/bacc0ed35556feaaa7bcf3a96a880c0bb4e44008
./engine/tests/corpus/413bae57aad41fb9ffff7039a446b8b6b4ff4919
./engine/tests/corpus/8406315500673999b0eac61327b81bea2806dd44
./engine/tests/corpus/aa0ab7b6fd854e33d71f6c9518354169941b0c8e
./engine/tests/corpus/002a68c1550728818189aa7eeeb9a7f81a895623
./engine/tests/corpus/1837f023a5227a2c6187971305182749b72fb8f3
./engine/tests/corpus/c6f55b3120bdefecbc910cb39653cdcaead33c94
./engine/tests/corpus/3647f8eab001589922925608af253fd5ef0dd087
./engine/tests/corpus/1509d5b24e153327e5a0ff52507bc49a8c9ccc02
./engine/tests/corpus/a24bdb6c69d27202182c1ba5346818725c2d9751
./engine/tests/corpus/eaa2902d9c200d33a69dff2e09d196e9d75f92f7
./engine/tests/corpus/0aa1860bcc5add4dc19a5f499bc5e491ff74b511
./engine/tests/corpus/384eae8067d5003d31dd5bd6d005133c52b0c2b0
./engine/tests/corpus/f76d1135676e460e58f6a1dd1fced620271fabb5
./engine/tests/corpus/d7e043c62ac8762e24443a7d7dec852992dd16fc
./engine/tests/corpus/31af272258c046fab0aad5c36dcad1186ee525eb
./engine/tests/corpus/352e82adfea0f42431456d43b9d787decfb43f66
./engine/tests/corpus/661d36a33ddaff0f7f82e4e60d43b41c1a57a987
./engine/tests/corpus/ecf54b577bbd1534ff9a85cd433f1e87643ed20e
./engine/tests/corpus/30e46f053a0900b99c56ae2f90ed47c863e4b5c9
./engine/tests/corpus/d4ea643c19ab7719fe018ef64118ae527e3393f5
./engine/tests/corpus/c02839b1f52a3c6af971938585b8b18d27a70811
./engine/tests/corpus/e9b9695bbecef694b5dd0a35743cfaba11d80b48
./engine/tests/corpus/4bc12a7bde78024c838a88f26273d6abe53bdcb2
./engine/tests/corpus/a830e614eb1dd703182706c677ea8be67fcabda1
./engine/tests/corpus/14a03e41600e5bdf10ac3a05fa1652075c4f594f
./engine/tests/corpus/9e1372ec7c7605c4158513b1ad3ae1ea9c0360a6
./engine/tests/corpus/4839dbfcd20ed19fd6a721610b5acddc757831ec
./engine/tests/corpus/3095866eeeabe8ea0f7d6cc6eb1da76f1ce34207
./engine/tests/corpus/1fbe873ddae0779f8d83548ed40c151794bba02e
./engine/tests/corpus/26888dd8a087412c22f8397c37561687102a3ffc
./engine/tests/corpus/ecfee38216acf9fe1795542dcebb1d04e1394587
./engine/tests/corpus/4da0d05641e6bb162fd360e072692d980f019a0b
./engine/tests/corpus/01af05e6185ebd30b9edc84abbdc3a364caf652d
./engine/tests/corpus/ffb84abe00b5b8f24c88cf7f30af66fe13c2f94e
./engine/tests/corpus/c18c8457eebc4ed74820e34d83ca7ed46d0b5d06
./engine/tests/corpus/6f6af3c7f2ebfcfc4730480f9b968cbad8b3d41a
./engine/tests/corpus/8feaa56d625570f6e21c1a2019fbdbb536807260
./engine/tests/corpus/66626ff3e228722c17dd35569faff8d9391d7c49
./engine/tests/corpus/9897f544033d45e5d9d0bb065a66a1ef3d0ff868
./engine/tests/corpus/9c228ca9e61899c3f9a895b9d661ec638ca862c8
./engine/tests/corpus/bf65f82cf27883ccb97c79e859d02c557cd83934
./engine/tests/corpus/40443f5692aa6a9c25ea0da6da5f3591e8a20652
./engine/tests/corpus/b26454c2ea71dddffb33308dc8aa7e41526c50bc
./engine/tests/corpus/7ff1c794fd1631ff107e6557c1cf96f8a1c3c202
./engine/tests/corpus/f399dd3ca3d743263bd24347e16aa6b0a2dea9f7
./engine/tests/corpus/e784b53e97555c44e47ec2d2bb1219f4e68ee4d9
./engine/tests/corpus/eb8fb43038ec76bc0cc1971ff685766f34716c1c
./engine/tests/corpus/f1d9545c7e0576c63a0df964bb179f3559ea1e10
./engine/tests/corpus/db9409a18fbcd69746b2d09c3845427084df73cb
./engine/tests/corpus/16812f0fe84112bc29359649cb3473c20e725431
./engine/tests/corpus/0c03539f828d6ba24d9efc3b3b997ef4f0f1fd72
./engine/tests/corpus/e25b365631fbe6da10ba18ef6b6f4c39e22508de
./engine/tests/corpus/6b3b582a47521365334347a8c0289fa9810f9d6a
./engine/tests/corpus/40c9c86479b8c57d2d70b742680e526225892d19
./engine/tests/corpus/a975d28d1a613453be02260397418cb9c5e23c3e
./engine/tests/corpus/b5c1ea04e3c920aca3a3b2489241766e58cd31d0
./engine/tests/corpus/87a0d2af1a2fd40460d0b7f020d2a632686c233d
./engine/tests/corpus/3a34c4755e003cb54aee92a68fcd8d60749be8aa
./engine/tests/corpus/902f83d9719bbb58923be3a3e751c1268ed1f585
./engine/tests/corpus/a0284bca5f71480579a370ace77f0c6b93ef1850
./engine/tests/corpus/a6552a483ec46e23eccb5c2df4e5688a7ed05f72
./engine/tests/corpus/7f3069a2ca5c81de3a45b9d0cc1622942e2490f8
./engine/tests/corpus/1c1ce7bafee65610d53b35ce7895e8e111fa9b37
./engine/tests/corpus/70c6da08b0f99f9bac5b8fdd22147a4759384b5a
./engine/tests/corpus/0b364be11fffd6827c7be7e248df4ff3314786cf
./engine/tests/corpus/5ff889d2c814ba0cf12b2884466cfb56a53631b2
./engine/tests/corpus/41cee39b454043bb1d04edf79039716b7a7faf90
./engine/tests/corpus/92a2f1cc884e17e90bcb9380f6b89b50a51b800e
./engine/tests/corpus/bc9e9210d4f09060cf5373777608a60b07c8b919
./engine/tests/corpus/dcff11d544d9915aa07ff92e6452deb90afc21cd
./engine/tests/corpus/77467763e8f8d792f8f626ba7299ab0fa52c4e44
./engine/tests/corpus/49fb47d04291c4a9ac5c9b0caa0594053686ebc7
./engine/tests/corpus/4ad86c7517b55c9fda9b963d9d111576150515c1
./engine/tests/corpus/583620dcac8eca76b6323c6cfa852c510ae6d7ca
./engine/tests/corpus/5ced4d602878b62d59e8ccd06635818ae3d3bd6c
./engine/tests/corpus/012dcbda5f8e8031c1900682edb5922142e3cbcc
./engine/tests/corpus/0235cabc697f8263b70596b648555a785118561a
./engine/tests/corpus/71b680985db72c970154ce43b267a62e1cce12bf
./engine/tests/corpus/fb283c4de0e604848928a8f5ddd93feef0ec5cfb
./engine/tests/corpus/9c4e735591e36fca1a43887c97aef487c970fbbf
./engine/tests/corpus/cf4e56b3db1710ad4a78967f0f50044c7b68099e
./engine/tests/corpus/d70a72e130ce552c42b1be22ee854d1932d6b945
./engine/tests/corpus/a590f05a276dc6ca442955eee6db8aff82d6eb27
./engine/tests/corpus/04e9aa1162696005af4f1f8ff79867953c5a70d3
./engine/tests/corpus/143cbda017c77a947ba362ff601234b669b82946
./engine/tests/corpus/6e2b9b63820eb692d6efc770333dec60629682c8
./engine/tests/corpus/d79722f94a42ca20608948eb46e1f464164e333f
./engine/tests/corpus/d306fa55fd97ec34558e903a04c3d82668d15b38
./engine/tests/corpus/c5b57a03a95c13bd522c51be6edd7f68c15d51e7
./engine/tests/corpus/0b4468d8934298bd9bf525f225ec4811377d3acc
./engine/tests/corpus/18e48962c79f46e39dfabb3e75f44a6917b480c8
./engine/tests/corpus/7900beca52cd40381718df9424b3c1476a715566
./engine/tests/corpus/47a8f56029dff9d94957c457bdae84144df00191
./engine/tests/corpus/ef63f4dfca169076dc850a8786908002dc53c6af
./engine/tests/corpus/1c72b8666fbf7d7099c61caae6774a6817ea40c7
./engine/tests/corpus/f95092cb42f846c534cb58bc71a044853a5c650c
./engine/tests/corpus/aaf3d3de5a1d887f95df20679bb969f9ad377171
./engine/tests/corpus/5068f56eed6edc9c8b31c81438477ac5cd0c7f63
./engine/tests/corpus/a5e1b22505c596d9360f2f00b03462ef99ecd958
./engine/tests/corpus/e6d1f7f33b5ebf0456f9e9d86e5bfa9a3b4f77cf
./engine/tests/corpus/370c6ed779101229fa2736f1ec364317791c601a
./engine/tests/corpus/9f4fa0bdb727c5a7e426a8c864adcc54fc452bf8
./engine/tests/corpus/c4115dd953d74c81948fe416ed90f6af8abcedfe
./engine/tests/corpus/0c904e2f9a80ab00f86e366c2e04754e9593fedc
./engine/tests/corpus/5ea59bdacca71b8ec8ebb0c92fd146ec2cb76285
./engine/tests/corpus/218bcf77699dffff92227d3cc707b4b52898f8c1
./engine/tests/corpus/372ce5b53a5dbf48012670de51fb709a7d381edf
./engine/tests/corpus/d695b7488eae35b69dd5acad75374e570159aa91
./engine/tests/corpus/89f8c10524a08626ddc3a05c19164221f777671a
./engine/tests/corpus/4718ff5af8ddc800c0b4695d46c8be6dd00a3a1d
./engine/tests/corpus/20d887c1a27bb330693c53b3a836f295866d2de9
./engine/tests/corpus/4402a66937fa37898a5900844802ab55d508d05d
./engine/tests/corpus/6cc99f62a467af8b87c4cbabe735e10d7a4df24f
./engine/tests/corpus/37520c96be79a8c10bba1915188ffc90895b678e
./engine/tests/corpus/54297c8e35a35d094ce05a8b360aede601b63913
./engine/tests/corpus/9e1f2c45a8ea3899c154cd221b47042c3c23f5b6
./engine/tests/corpus/e5a2379de04d1e2f0aa0daa6a96b3d07b2c01e1f
./engine/tests/corpus/3c7834f1181f26759d10b03a7d3d820feff81acd
./engine/tests/corpus/fa327fc84b96a98d8d088334d78324e10d1e2945
./engine/tests/corpus/9036fdd5167384ae0be533db7e94654313a63876
./engine/tests/corpus/a8b8a6aa78fba5115beb9204163b8c052c3f26f6
./engine/tests/corpus/f544ad56297a87ed34e580f19a2c3b6c17bc7821
./engine/tests/corpus/a615abccb8bb304feb4e6d12055f0824fbd4f7b8
./engine/tests/corpus/3e8ecb6128c8ea6b8c8ab49a71b29778dd5417d1
./engine/tests/corpus/8d01bd8dddc9fe3f87251cabe02fd256a982100e
./engine/tests/corpus/036b7a9dd0f5123e74c353027c71093daad935a5
./engine/tests/corpus/6fd963b5fecc44f2c02fa1690364bb23d2e4cc4f
./engine/tests/corpus/4340a5110e4c92ebaf6d050b1476e884d9255588
./engine/tests/corpus/d75e2513112fe12b98e42d542c9bb619a8f8edad
./engine/tests/corpus/9fed9fb3ab5f18284d011133b350e62ac191152b
./engine/tests/corpus/62f4b152d16bd57d46d518386637e62647659628
./engine/tests/corpus/41d737903a4e79c4058e2fb30b87fea30e0f7b53
./engine/tests/corpus/147f243c3348dd8b1538c1e297010540771e1852
./engine/tests/corpus/af1ad5847f85e350b9b5902db055ca27cd925838
./engine/tests/corpus/3040d857e06a69f9b45171e77d8f14f21ef42389
./engine/tests/corpus/586940484df19906fb5473d1ce38bdb09b5302f4
./engine/tests/corpus/d2e34512a06793118c217516bd9d5b0e538da22b
./engine/tests/corpus/62a8779177f9c501862fcf145cf73671ce75b188
./engine/tests/corpus/8d43b7ac829385702d96225138dc7a60abd7f92b
./engine/tests/corpus/a2d51fa8272183d1275f15b172e34caa78183578
./engine/tests/corpus/2c210b00adf0bf7cf00ce3f89fd8e2307ae1ae43
./engine/tests/corpus/192af506f72ae5e41f91afeea8795cc5a14780e2
./engine/tests/corpus/728de3a1129cbad002a36179ac6418ee905bbd1a
./engine/tests/corpus/4e952d7316ec0025307db86fa90287691a5a2987
./engine/tests/corpus/88d64b368f825a43e9093c16faa6d235b01f3d4f
./engine/tests/corpus/8923b5eb7ec9b71b90a43701bd29f4eb27fded8f
./engine/tests/corpus/31d754d00ed7689be43dc595ae19dbd3296e4e3a
./engine/tests/corpus/639814c71d52a34ea9df315cb1d5480221027d1c
./engine/tests/corpus/7d94dffabd07ff22ab2ca0e48b72bdd54a8cd899
./engine/tests/corpus/9ccacc7472122e7df3d6c011386b677be4190ed4
./engine/tests/corpus/9c618348754b28e6b3d05c18356bd9c52ed99839
./engine/tests/corpus/ca64fe2fe578352c9d3037c9ad7a68595831ee56
./engine/tests/corpus/f433cc507e57add9056aaee3d2f314d0b13a2de9
./engine/tests/corpus/3c197636b41b1967c854d7c02bd3bd35b1d8b53a
./engine/tests/corpus/3daed6b471927b45f7cb6e503b21441658e1ec69
./engine/tests/corpus/17dab2f799bb7af9675a21adddf3c018afa7ccef
./engine/tests/corpus/decfe6b8298d754c52637b06de3aea9aec132000
./engine/tests/corpus/9d387f0fd0c26b6b4f3ec091fdded73de946fb09
./engine/tests/corpus/af89f0c3d0e83939b8fae3bac77dd48041267f4f
./engine/tests/corpus/544229e9fa06ec30bbd720ff40003eaca11e3eb9
./engine/tests/corpus/d1a6fe378a00f6fffee23a01d0ca5b6ef2966573
./engine/tests/corpus/9d3e769cc323f8474c601cc6f70e92dca91c20ef
./engine/tests/corpus/f0aec4cb3da5904a2eb11f82d86ce0903f636992
./engine/tests/corpus/4760ec4ca7668078a2fa7420247b39346a8d83eb
./engine/tests/corpus/b0ab9feacd88603f7928ccd1289bc0e33ed26a42
./engine/tests/corpus/bd11da24a42ae98ab6233b81ee3de7d25e0bcb37
./engine/tests/corpus/8d1b0a5f8fce78b87281b32958dd48e33e03dcc8
./engine/tests/corpus/50238d102507ef7870beb559e3cea859759125b5
./engine/tests/corpus/b28bc9ea7ea8c607d497ee46748b893856dc0a0a
./engine/tests/corpus/f28028aa1afdad93ff3a1edcdd0e5ff4e83dd9be
./engine/tests/corpus/d375b130ba0e5453cf79636266f5db7e8a9481f1
./engine/tests/corpus/50e09e9d0144543f1ea6636d8c19fdbc8c7ba135
./engine/tests/corpus/be4790bdafeb5e9d847f4d878d8243575f150ccf
./engine/tests/corpus/702f9f5054ea8d297a9657d164077b76d2aed01b
./engine/tests/corpus/872152dc74321971486d54bb515369c9f42c78cb
./engine/tests/corpus/cd9c31a70cb4c388900700f7808cc613c9d62658
./engine/tests/corpus/acc2a5c5e3853c3dd8a45e24969274e2d90b624a
./engine/tests/corpus/04684b9d9d024f697b5f397b218078f80ac9a579
./engine/tests/corpus/90e3f6923b84b648037a4d67a500d29a46e8c8e6
./engine/tests/corpus/3f3ab7ee536ffda545a6c6bc2baa20ed6dd7ba53
./engine/tests/corpus/78493be9dea18a07048e686843866f8337716d65
./engine/tests/corpus/2aaa0bbb96cc947621e7a2499fa46aa5ee775531
./engine/tests/corpus/b19e78705a716ebdecb6f2e6a09dad26576f5f75
./engine/tests/corpus/5722a1529cb8fb50e199ec9da24c2d5462c4ea28
./engine/tests/corpus/f5720116234e6faf8af1972acb9d290c83916bdd
./engine/tests/corpus/096481cdb8dbdac6345e920bc11f04bfeb1971d2
./engine/tests/corpus/ca1b196730be9095a5c32cb94c2a17f2888125ed
./engine/tests/corpus/82d17941fb5ea9e96b4f673e3c02edcdb9fe6e4e
./engine/tests/corpus/4f184fa19a44fda2fd8f67ffa350c040d64d308b
./engine/tests/corpus/1350f876716a00df9a4407ed6118bbcaa453628d
./engine/tests/corpus/9219795d9aa7f228db00ceb2e85293e46d4d1a3d
./engine/tests/corpus/e25927087deb51717a1f5777625dc2b8c9ba134e
./engine/tests/corpus/34a5d5302e25124730ad1437da3e7386a0d9c9a4
./engine/tests/corpus/24d047f2573132234004787e59c8d45a3e5bab1b
./engine/tests/corpus/0fc26404314056046719248b39559d378ec86912
./engine/tests/corpus/4cb1a26a670298e8e0ce4762261ab002d3d6e1ba
./engine/tests/corpus/9f54f29c57697e74ead5f7895712b155db9b1b3b
./engine/tests/corpus/28d2643de4e189edf96dd84cc524c9438991c374
./engine/tests/corpus/dfc1c25f426a8d0df1e2b00d3fc2d066f742a9c1
./engine/tests/corpus/b880fd73e1e211611b07a45b3c8312d7ff22890b
./engine/tests/corpus/ed28837cbd0002a971b30a260fd607035d6c6e80
./engine/tests/corpus/4c7c3ce9592850054a0b5d9d51b7934e7011bd07
./engine/tests/corpus/d9acbdf7f296f075f9a4bc48de6d790d16f332c8
./engine/tests/corpus/43332f8cf7102385351846fa02f4f5be370ae828
./engine/tests/corpus/8815afa3259cbe56e868e12df3dc296abc21a893
./engine/tests/corpus/f71ea20b7f9264b5bf14666be040e38e5bfccd69
./engine/tests/corpus/cfa4d9686a5635922bedddbf3dfabda98d4284ae
./engine/tests/corpus/f28782ce4e8f48d248e726e9f508d6d0bb34eed8
./engine/tests/corpus/e28e450e767c1266c2e9351cf85949d494304eaf
./engine/tests/corpus/c6a9957bf48f6b82191120dc46fd49e36e60305d
./engine/tests/corpus/1d1516ba3b52a2642834868bfb5d5d483d526a37
./engine/tests/corpus/6aa03d70cfec5caf2cc7e7447af20970c2c93f18
./engine/tests/corpus/6ab98fcf9b5a3b1d481c7dda6a138b6670a1b331
./engine/tests/corpus/cbc6122447aae4d60e924b3f7a4402076f0e32f5
./engine/tests/corpus/f60dd1f1af0b1fd581b1e579d70aa892d6b8150a
./engine/tests/corpus/ffef1e62b65e7aac3e5cbcc2e8dde8d4cdd172d2
./engine/tests/corpus/defefd95e0c4a74042c3272ee07ceaf7fabcdfe4
./engine/tests/corpus/3730e6259f93035b681cb5af714dae9ef6a93c3c
./engine/tests/corpus/8dac1556d0c5ea29de25d251ff0c7e482b56fbdf
./engine/tests/corpus/85b6d7e190b9af09e220a7d6584889bf7c16e449
./engine/tests/corpus/a1a89c385169b6c4c03fb5ef2afc407dad5367d8
./engine/tests/corpus/db5ebafdf44e326287550db36aeee4e56b6bf32e
./engine/tests/corpus/9e06702f4c8d2c1b90c30f9408e07dbdad6c5c28
./engine/tests/corpus/833636c3edf5a233fba2dbaeb9cd296ab95a9143
./engine/tests/corpus/f55c1118964826c0097f44b765ebc7b82bf9f0f8
./engine/tests/corpus/7051632e92afc0a732e32d7e0fcfab8bf4104815
./engine/tests/corpus/4916fa5f2a1617c9b2d5763e357e610328244289
./engine/tests/corpus/752e3e3246b56a2387aaa67ec0312526eaf499ad
./engine/tests/corpus/c8dcb2e2e1293ba94c06418b10b7315dd2fd643a
./engine/tests/corpus/f73e9c75208c1a1d0ebd17c02881822ed21a6c57
./engine/tests/corpus/54a2ee8fdcdbc2ca4319c96b6d74e9caa5f4eeea
./engine/tests/corpus/dfded151267b7d4d949e4c3f70adf6ecc4dbdba2
./engine/tests/corpus/8d40068692e846e146d4a4d79e54f6a9117e74d9
./engine/tests/corpus/25088cdeac55fa103d679af8d0afc32b1963c9f4
./engine/tests/corpus/1eaa72939a61b92b34a17849d99aba9a26bbbb23
./engine/tests/corpus/fea3323d299c4d5e9946f048aa2cdef13bb9c750
./engine/tests/corpus/99d6602702c992721751ea5a73042809ddf6fb27
./engine/tests/corpus/f9e15bfdc8a05c6e97135accdf80ead81c59e912
./engine/tests/corpus/5d683078b3a58e004725289fe2d5a89b30e54e9e
./engine/tests/corpus/eb63e016729eb85bef6f3fd41ab8409d0ef064a9
./engine/tests/corpus/dc3da1193ee366af3a83cb4d4889c2d14106a7e5
./engine/tests/corpus/eeb2d5f3504d4404d2c88842d32ec5cc855ca4b3
./engine/tests/corpus/45ae00570afc15fb9072712b228cf70896ed2e09
./engine/tests/corpus/91ed3ffff36489e25dec76f03bcc3fbdc1f19dd6
./engine/tests/corpus/6f5151116d0e983cf21ed17f715d8ea6e5ef742e
./engine/tests/corpus/771d41f92bef6548c2da8cec54560ac157272adf
./engine/tests/corpus/de7ebbf3a84b865d7e0043e886bacbd9716cf182
./engine/tests/corpus/9a9971eff51794190781971d2730326fcb13f26b
./engine/tests/corpus/90e762b29a1d573cbd563221d41f30230716ce93
./engine/tests/corpus/5f821a57f5c3cdd9d64a36d75ff0f261dcec6612
./engine/tests/corpus/105db46c35bcb4d70df7202d5512b78475d5ba1d
./engine/tests/corpus/53cfc286608b0b96c460811bcecc1ac6dafddbc2
./engine/tests/corpus/d483fd7e985fdf140cb366b4c41b6a813eae534b
./engine/tests/corpus/64a96f3c780e26d162af9da91a2ad384d44abe53
./engine/tests/corpus/78e88dfe1b2f8098a6359bc097c1cf95db90a909
./engine/tests/corpus/298e3aed673b5726f75c4a44763b20c923833a4a
./engine/tests/corpus/6234f0f66e92501525053f5b48385afb1eb960b9
./engine/tests/corpus/383c28145bfd9863617fdc1d49020edd503430e6
./engine/tests/corpus/f109b8010eb134166e1db31c3de7afa59060e467
./engine/tests/corpus/3f5f924cd61d26b022b35bdb19f57be7e171a549
./engine/tests/corpus/d1ebb0698ced051d0657fbfd9a229c2bfca3cadd
./engine/tests/corpus/574da3647cc8ebc9b747ab7ddd0147ad87a472c6
./engine/tests/corpus/e169d53df8cf9039e6a1afef129c8d935ce952e2
./engine/tests/corpus/c791ba44162744c9d4becf1ab09acb5888f8ba89
./engine/tests/corpus/f0ffc661d7062ff18a2f1e880e2f28b1a127e324
./engine/tests/corpus/0263c58e80f31aca434437be11c202e9ff629d38
./engine/tests/corpus/b7311674d406c7d8d89a7509929de66edd4cb064
./engine/tests/corpus/ea7224506361f00a6532ade86498ed166a6817be
./engine/tests/corpus/ff86c8a328cc63f6e0f7e27823ec7c1f26fae9de
./engine/tests/corpus/ca5ec891a9800baafd2c6632be3410167f080fee
./engine/tests/corpus/f67864fe45512fb4cb1b85394b59643ad75488dd
./engine/tests/corpus/afc646cc8147aaeb8c9f830ca9a6048e0ae4fddb
./engine/tests/corpus/7c9ce08a19828a952e4e53d6ad466e182715fc96
./engine/tests/corpus/a1fdeda9c64db277e98ce1532d4137feb3d5c9ca
./engine/tests/corpus/065582b1e3d9d87c2c4df151fd47362556e19c79
./engine/tests/corpus/fb6c8720d5959cb897a94384ec410818aee50ee3
./engine/tests/corpus/e8058bb86bd61062a12fc40f12b2657adb9bf5ec
./engine/tests/corpus/a97d18482055676ed9e664b3145c2667edc051f0
./engine/tests/corpus/9f7479f0eb95dd6b4544e7bc85319e6a81e12188
./engine/tests/corpus/96fe185ec67a852c9c8d5c5054865084c0e161d9
./engine/tests/corpus/5d5f1ccc56ef9bc4b09c39f31ef209b07b7dfd49
./engine/tests/corpus/94e4a54b9b3ca27ac400b11de3a825f45c4707b7
./engine/tests/corpus/573d8d4394ba9f6028718047af9de9aa4bc24c50
./engine/tests/corpus/a928a421936d915535d44647c5260d059da2741c
./engine/tests/corpus/9a7460212590809197ad94bb19ace220fcaf86b9
./engine/tests/corpus/98de8b3232bb0848a7219c89c0ca1ed10d3dae9d
./engine/tests/corpus/75ae9d44e8f43142adcd0d8cb173d6ec4a995d20
./engine/tests/corpus/b3ef756a38dcd0cf02849e18ff7b9b7d1942f0af
./engine/tests/corpus/a3a1c213f1ac45f43bee5be1d83e8300846979e4
./engine/tests/corpus/0525a56a4d1e42e1e8278592faf8536ad323b3b7
./engine/tests/corpus/56877b21bcac0d74fcd4c50cf048441db172b3eb
./engine/tests/corpus/d81f916e5b1be551638921a6da78232d77b05c39
./engine/tests/corpus/6aa208cbec7e1b9e84546047e5d67c12f98d5b48
./engine/tests/corpus/f8eeec43d64237eb16a96f11cb86498d53dedaab
./engine/tests/corpus/c03a4e6b9730b0ed814ef3267fedb0100eedbbd0
./engine/tests/corpus/bd870957a4ae289cfceff03f0d01521faf4c0610
./engine/tests/corpus/1ef2c406a99c1767bab330b9b3024c1fd2fb7aa7
./engine/tests/corpus/e16280bfae5dcb4bee2a0476adf997b5f885d5bd
./engine/tests/corpus/76213a55d412bf0b7cbcc1fbadd8dd339020527a
./engine/tests/corpus/bb96dcd5aabe6255944e88394c926cfb1f00de8a
./engine/tests/corpus/6d22a8b94e21681071636df18f091376e7304699
./engine/tests/corpus/99696497c22c6cd62ca16a9bc3729b3baeae9a03
./engine/tests/corpus/7588ff9827456638961b799aa83bb53628d579d3
./engine/tests/corpus/5d0920343e00833cca86d460fcdc722db705b28a
./engine/tests/corpus/29d16d226def8ad4df21215513db9cd42e4e2234
./engine/tests/corpus/aba2d6dc1cd15ba27d01bd50b528a265c419562a
./engine/tests/corpus/6062c5b1e8e8291683d3b579fceefe77310cc6d9
./engine/tests/corpus/ba222a2bd6d16511e8b2bb6dcea54f5db65459ec
./engine/tests/corpus/d60925351c9b2b8675a4a59c176fe3d0b58a332b
./engine/tests/corpus/04b5999f1c83cbe0e7e5435867870d352a7bdc50
./engine/tests/corpus/8c21cb3d8c761fd1a65d62e4b6bc03fb8f2bf8e3
./engine/tests/corpus/9d9f9daa73f189edc299dba54bc82540e6b73821
./engine/tests/corpus/93d4755d0b878a2cd1f364d58aa4c62ebb863b80
./engine/tests/corpus/8fdfed1b8f9709f59d26c4404db34c601f5f5634
./engine/tests/corpus/5d105a5fd8ca2287586d88f35f678f52fcf1f780
./engine/tests/corpus/93b6b7aa5618face4e24f1a0a6567b603608c269
./engine/tests/corpus/f851bcb1cc35d5345fe11f3cc9ef6d323dfd9e50
./engine/tests/corpus/14ddc703533ae6267b73fede960dc75e6538b193
./engine/tests/corpus/828168fb409d61bf8cd84f33b48dc51deb0bbefc
./engine/tests/corpus/57878dd2377f218a165e4550b70671394a59b103
./engine/tests/corpus/12ef263925b58915eb15d5b4f439deda95042ae7
./engine/tests/corpus/166c757478f2549b0de4f067354cea535e91b9c9
./engine/tests/corpus/ba7850363ed84c0de301c5ba2d0c9a11c3106855
./engine/tests/corpus/95769ef3a391c209592a42a53d88d91e35b68ab6
./engine/tests/corpus/b298f81fbdfaafdd1ce9fa8118065003182bb23e
./engine/tests/corpus/a32705625629e777e2e4f1e91ca20211f0929785
./engine/tests/corpus/25e3fa49a4d715d60a6877ab95c3e901eaff47b1
./engine/tests/corpus/6c6885f44ca8cc0a400384e701f559db1b04efce
./engine/tests/corpus/0011b0dd2071e59be33c08dc1b59428ed8678d65
./engine/tests/corpus/dc2b07b88b9335550a610457d0fad9158a89a50e
./engine/tests/corpus/4fa5482a34208470952aa5eee5a54aa4d70ab123
./engine/tests/corpus/02c48ccbfac8c94115d0702150c54d518d1741f1
./engine/tests/corpus/d8761146d36cc8186dcf5b7708271c97356450ff
./engine/tests/corpus/9523806b6d009cbb4f960e0f60792e4bc38852c8
./engine/tests/corpus/7ca6def840e436b8cdbe2d23ef22a894bed9a7d5
./engine/tests/corpus/d65a59e3caa7a641cde076fb09525d35d2a91f2e
./engine/tests/corpus/fa802635b94fd759e0274316c789da144f0234cb
./engine/tests/corpus/9ef9b6d4c9f7214328f02a5ca29a27ea119a7c27
./engine/tests/corpus/c5b23679e71bca92bdb633370b65638f6d034206
./engine/tests/corpus/8aa23e3ac020accf236960dce59b6e3285f47fea
./engine/tests/corpus/21ad37fb7e1f511839dc43cbe719ce114bffb836
./engine/tests/corpus/9ec936d33cca45b8bf0096e8f46d8daefbb9b299
./engine/tests/corpus/168f8b9fc5064dcf113e5eab4aa4f05d2169232b
./engine/tests/corpus/a22d080082d7c4ba4d180e47bee80a1f89df94a7
./engine/tests/corpus/6c03d9f04a1752b78cb7971ef76a5848ad0489e3
./engine/tests/corpus/61c54c014a2536ac0ebbfd546f808063e6ac0581
./engine/tests/corpus/7996b063a675f6691d1ec635b743e1b8ed6d2dd8
./engine/tests/corpus/7a00ed85d4b86cc304cabf07a68c79235522271b
./engine/tests/corpus/74a9d30c4fda5aecfbd7ff4f9d1fcf95767541d0
./engine/tests/corpus/eb3d9051291844aa731e09d80b615b3cbfd89e1f
./engine/tests/corpus/3160a7fb8a2494119398efe4eeecbd5e9c2ef452
./engine/tests/corpus/6b4fcb674cec9947d3d27c9398890d32ebf12fb7
./engine/tests/corpus/299433a5d3319ffa9e7f0e8af144f228f7e59108
./engine/tests/corpus/770301a9158b1d80af10cca7d9d7e39cee8e0f21
./engine/tests/corpus/93578af1d81aae395b904967416c1065cafdda8e
./engine/tests/corpus/a1cf8805b99a97101d83f32cabd30ed33791e025
./engine/tests/corpus/1154f3b2e46e0fdd3ef7a33c7c6b6a1b4141a18e
./engine/tests/corpus/164874bcdc757c8157ecc6e91ec14812065706fb
./engine/tests/corpus/5c2c808847a02407347ebe39fe90fc4f8de51746
./engine/tests/corpus/5fe4eafd83c9dc98882396fe152b7d0fc85891b1
./engine/tests/corpus/f5c216068c2d2d21958d27706b47b9c437c6407c
./engine/tests/corpus/84ccb487ae9953124d4b7d66534068e840df8c70
./engine/tests/corpus/6f7b6cecbb82dfbdccf1f4d04b46d8be95631082
./engine/tests/corpus/cc1260f1ff92dcf72183e887b3a133587e75c75c
./engine/tests/corpus/3cb7831fe2fa0dabc184da68055e0605d18562a0
./engine/tests/corpus/522a0619903aef5072d4679e6b7ff520ad21bf13
./engine/tests/corpus/0ba53fd2ec3502e4cb45acf5145e2c7c9234e74e
./engine/tests/corpus/2cab63dc39ce55b51b9bce4d58f00bdd3b3feeac
./engine/tests/corpus/1623ef444b3b5887e0f33bed90c8ef39f829a5e1
./engine/tests/corpus/9b5ce57c81bb5e6a3a1f1a9ade889a1389cb25dd
./engine/tests/corpus/166b6f336e0a9362897eace9bd02a8e38095b0e6
./engine/tests/corpus/7bc527e3889d2d3e8f17886b66c40047663fa83c
./engine/tests/corpus/b677f6bac227f1d6830d4e647645f0d052da0215
./engine/tests/corpus/4dcab95e068f48f780f480f087a683f5c6fa43f4
./engine/tests/corpus/c3411a875fb9503291d175e215cbfa4099484149
./engine/tests/corpus/f83648717b82a58b0305fc582586d132be371173
./engine/tests/corpus/da6f64b9fe7f2f82616b8c16b23f0ebf30154866
./engine/tests/corpus/3a7910797d49b17b377b35ff97485a49b7c875cd
./engine/tests/corpus/5498cab40550315d4758657c6493814d1d91a504
./engine/tests/corpus/9b72fce5f712b2f63a66d5ad815b768154a3fa0f
./engine/tests/corpus/a4dafc32abc3a429ba7a8dab34ffe8637f617a9e
./engine/tests/corpus/9865ea706edcc07151c25121e992ef84071bfb5d
./engine/tests/corpus/5125a2006a9935a172038347ad9b7b04232432a5
./engine/tests/corpus/cd4efe2266e9a2317b08ff032e35456413be6ad5
./engine/tests/corpus/ffcea53e38dbc8c4f50db6f08ac88df88e13eaeb
./engine/tests/corpus/3d4b9a0486ebbe407f477ce0c9e92fdb7bc9ac25
./engine/tests/corpus/34b737cca3a1586cf526167d4cf5dd55ebc7aca8
./engine/tests/corpus/b894a90568835c824e2eae38ba262a92f9251b2a
./engine/tests/corpus/a80ec9e8d67ce3c28f880f998c6729cca8d979ab
./engine/tests/corpus/94340f894de78c83686697731afbaf0f487ab4aa
./engine/tests/corpus/0d8924b0bd4e337bba9816d0a20c1ea5af3fb6df
./engine/tests/corpus/25f7eed5bf78e332d74dcfbcfac6e2d71c1f1e21
./engine/tests/corpus/5c5031aa08f0f3c170da969ca1a198fd9b1a1a27
./engine/tests/corpus/856f17b0341c89232f478cba7673a97206627f64
./engine/tests/corpus/562a397969d6ae73b4b82a2cb8906670a4551223
./engine/tests/corpus/25a4534d0ddb0fa3643476dd6ec3e324c0072fb9
./engine/tests/corpus/325f7adc9f8245873c789a277916b69851c8d812
./engine/tests/corpus/b8973fa312b3f60ddb6bb4c8a34f8bd924d2f71d
./engine/tests/corpus/cfe9ae7e85818b10dfa6e22ddf224602f8cc985f
./engine/tests/corpus/fa1dec0cc96f89e28b779da2b27ecae1c7ac8c07
./engine/tests/corpus/e617c846d9d7ed125c4cd1144b1f8bf0491994f6
./engine/tests/corpus/af5b34b1c3e032ba7ba6fb2eb15b10b021294721
./engine/tests/corpus/64f619d677f7f6005ffa76c12d9c7b75ff548183
./engine/tests/corpus/6b7a2583f0a0debf5bfc6e3ff8fac61beed8ef97
./engine/tests/corpus/41e2c1b778fdb78ef1f3f0f33a1540b0f30df251
./engine/tests/corpus/6a41d631bb1c6bded805692f806dc6ef80c6cd9c
./engine/tests/corpus/023955a14686afdbfc80d83a0031c3d441a73a55
./engine/tests/corpus/53cf91933735ff4ee6d7ef85579cdcf41b3a4b96
./engine/tests/corpus/6a8e224a0e4ffbbf7aff737467d2d60b9998bcf9
./engine/tests/corpus/91dea05f6f92ca57767697c821fa1eaebf2d0bef
./engine/tests/corpus/4e3a7d2515ef7ef59a3d818b85637b4cdf4b1b3e
./engine/tests/corpus/cea14e528bce5bf150f65776e7db89ab73b33348
./engine/tests/corpus/1c273ebb4fef3dd28b7f5e78483343c16c361bbf
./engine/tests/corpus/c20937f5a8cf63fe735d8c9aeb8b25bb8646fc51
./engine/tests/corpus/64634b714b1f4c1ddfbfb2ec49e45d6f81e1c65c
./engine/tests/corpus/35449165a171984e76d9b9ea80f2e3deaad0f09e
./engine/tests/corpus/c2cb2013058f8e0e5a0804409678a7c7e0767b91
./engine/tests/corpus/7a2e793eff12cca12e631512d97e1a46073830fb
./engine/tests/corpus/40cf71a76c6dd392806012602a1792aee910725e
./engine/tests/corpus/1f71d992c3c20f8bec86c0f72b9e97178c1d2259
./engine/tests/corpus/6bd9bf977c59f569faa9bc6bebf1509534ce6486
./engine/tests/corpus/157d8b5b8042d9b0479a8522074758fb0524537f
./engine/tests/corpus/5adb8ccf2c9007388b629a900e2d66aca791ffda
./engine/tests/corpus/7338837c83ac2cbb33bf4642be20005bc298a865
./engine/tests/corpus/0a311bf23bd2588c431973d9f95dc43816b80347
./engine/tests/corpus/9f61ae9c5be1504de5437c0f63e1e1a1996f8999
./engine/tests/corpus/e9f1077b12a28ca74cbf1df724e8c488e6ce97fb
./engine/tests/corpus/23c24ce937e6d8665c9bb00fd07fdb22732756ab
./engine/tests/corpus/b11983fa2d42fd5b27f8d9b98190b176f4c8cf3e
./engine/tests/corpus/c0326eb53bb4a0654b7ba10f9c417ff3ae38b74f
./engine/tests/corpus/8a073b53d3fdd9a7fc163eb986be9990b746e033
./engine/tests/corpus/03a18343841c433348c777e351f64c18a561a9d7
./engine/tests/corpus/bcdd6f4fc1311b4445c1bb460814882e2cd8fdd5
./engine/tests/corpus/b3b2d18ae698f4a7ce84aa5495b9cb0e61eeec66
./engine/tests/corpus/addf3afe84023506c81b48c0b78b24cbb049983b
./engine/tests/corpus/93665f58eec1ad4833fe750af34fc4a6c2eebf79
./engine/tests/corpus/4eb91194c1f63f83ca32ffd8bfeb61b3cac56b1a
./engine/tests/corpus/682a96b8f159657e313955b936108822aaf1c3f7
./engine/tests/corpus/f07b3c43f8b5b16cbf8d33eebea4d7d5e065ecf1
./engine/tests/corpus/658eca2893ad5dcdd2f47fc5b171db009ab7e2df
./engine/tests/corpus/def70c1daf245c9df9ad716687ed6b3599699003
./engine/tests/corpus/0f0189828512e2146b8a4d5421c2a9d76569f02c
./engine/tests/corpus/88c582e11cd7946000f71b2a8e441d1c39c2ad2c
./engine/tests/corpus/3b807f6b99d4bda01a38b6d949fa7ac087bb82f9
./engine/tests/corpus/c51b7103fcd78044d0bb15c8f6c5ba4a6514272b
./engine/tests/corpus/2fc28e626c26b599a489c0ef1c000b24d122809e
./engine/tests/corpus/9abf0e638adafcd100dcc811f22343d9842624f3
./engine/tests/corpus/b2ff711f61f3df0c876cbe43d6f4044c62754048
./engine/tests/corpus/9304b7fda8219754ae917e34b21cac8507f1628e
./engine/tests/corpus/3e0a8af36d7bf0fb00a4b123a7163d97e76e9b6c
./engine/tests/corpus/af53d3a6aebfc398e9685616243bef9810916e23
./engine/tests/corpus/a02a54a822c63d46d753d43509d86e0864b6de8e
./engine/tests/corpus/6bba2f357e149552c49d9f1c7ad3866a5cc79260
./engine/tests/corpus/8dc5c197e5034d7d357a73fdb65688e77788ef48
./engine/tests/corpus/b58573fb091bb6bb8db0af836f6c240e9d844f34
./engine/tests/corpus/e1fd5b6685003caee5b7b9a35e9f05061cdf5b70
./engine/tests/corpus/ced5d0f5497f25f8d92ff5cf5664b634943d07d9
./engine/tests/corpus/92627e76f5b8a537183048f7d7986b70d65400cd
./engine/tests/corpus/0a0d14de23bbf6cfbf1cdc5c4a89d37cd3835fe3
./engine/tests/corpus/3118df6ade88a6bf18bca8602c5f78cf3aaa6a14
./engine/tests/corpus/d72a9f64922ada9accc23a6a0d68317a29290ce8
./engine/tests/corpus/2b7952df274bc932e5bd2922558e6d0e031b3bb6
./engine/tests/corpus/5b66a485ddabe371b942879f2882d90e0a682465
./engine/tests/corpus/023cd14aabafa0c1a9593f25445ef7c595647179
./engine/tests/corpus/f18fd131eaa5a38d7e117fa81df49fceb32887ee
./engine/tests/corpus/47a592eca0097d7ab1a4ca49b84f53ce9480a160
./engine/tests/corpus/6050e02a107c87c12f95aacda452f93648b42ee0
./engine/tests/corpus/25d7d597850dae5496f6867d5236b9fb89429ce9
./engine/tests/corpus/3989fad1cfea3e469ee5ec1dfee0d38467035821
./engine/tests/corpus/216a2b9d13100618761b9a368a6c412ba7e9ac9c
./engine/tests/corpus/bbaac3ef38c811bce69b5e67626eec0e1e9c3c8f
./engine/tests/corpus/ba136df051ebea8ecd6043959f2e4c20c1fc6d10
./engine/tests/corpus/2ffc154341fce7522991220187eafccf76ecd323
./engine/tests/corpus/4b33fd0a1eefe8aa03f033b9a8008c0e7dba16be
./engine/tests/corpus/5ae78444d5a988c753984bb1ab36987d360d3195
./engine/tests/corpus/f61502f125ba0b75839ab19d4820dff086f757aa
./engine/tests/corpus/181b02d1be6e09279e6cf1ae6a3d76eb5b3fdca1
./engine/tests/corpus/0f9caa7178a167d62da38face4a9c6b55bb788c6
./engine/tests/corpus/ea4d79f8eca5a7e6efad6a70b751b06279fcf4ff
./engine/tests/corpus/2d6f1fc1bcff38efd37deafe77ef0fd9370f690f
./engine/tests/corpus/81fdac30e6a30cd81a635248f6d45bc79ebb078e
./engine/tests/corpus/8ae170e889f0ff82cfaa1390ce4b2ff68b7e4745
./engine/tests/corpus/73cdecb7d208346231ccdf6428c059e3ec4e1f49
./engine/tests/corpus/1ff5f5a58d50d50529c976d98f0284055226a44c
./engine/tests/corpus/af1759eac0fdc41d743eeacb74606c2b529f7c2d
./engine/tests/corpus/577b0f5cc5631be5b0c3e100bc055838045c028d
./engine/tests/corpus/97b30a3f1d09e010869b7a3925989ba23c45e248
./engine/tests/corpus/73740ce0625ba746dae2ada6523eac0cedfd7985
./engine/tests/corpus/00c5da9e0f0e7e964c153fac7c9c6e778fb6b7da
./engine/tests/corpus/fa8df68d74acdc2bd6837c53f3c9de8cae062336
./engine/tests/corpus/fb2546a4bb3f775fcb1ae10201a9fdf902ccffa3
./engine/tests/corpus/fc75b192ce635433452675e52fd694bb2b0630de
./engine/tests/corpus/80d794691ebcaca88d53fd2566f298fa5c1f2855
./engine/tests/corpus/d6d5756437e0382ed6cacdb42342b67b0b306467
./engine/tests/corpus/79a24f996e658d6f9fda5939272040b069987b9f
./engine/tests/corpus/4121d567934dd27149b73898c8f09cbf96989e17
./engine/tests/corpus/2a57709c42a83c42b49707bb4af0ba085c30ab38
./engine/tests/corpus/da5e36187dc4fa189183291bae52dab608c5dc55
./engine/tests/corpus/7654743ef7de8cf3397069c960c9c49c16b3c8e1
./engine/tests/corpus/369cd497e215d657587c6a47c503bdc37f0670de
./engine/tests/corpus/13c22833e4a0ca83cad67be625b18ce753944313
./engine/tests/corpus/549d836392a812db49fac68735c73fb12524ece2
./engine/tests/corpus/8753c775f3a4af917875e74158ea1154b41d73dd
./engine/tests/corpus/f665af7f6c0a1f24e666fa3a7d4a99c776a65926
./engine/tests/corpus/edeba44eebf0f54693c82cececa44cfa674bc557
./engine/tests/corpus/fa0e23642171f96ce14236872b3273fb6677edbb
./engine/tests/corpus/2e2ff8558304c4f8e134636353a2bf8b8894d703
./engine/tests/corpus/7453b5edf0cb0c6aece8ec8a557992c192ee6009
./engine/tests/corpus/865b7b9b73571ff5c2863708fe515b06924019a5
./engine/tests/corpus/2171a4db4dab0141585bffd6efb10e37a6a71fdf
./engine/tests/corpus/32caf89d1ff2d3bc33caf183af6bb3f85ae2ee9c
./engine/tests/corpus/55dbd56df4f3ccc75ff0d5a9a9f446691a7aea32
./engine/tests/corpus/ffcd68836beb6c51e82e3860bb19065686d14e63
./engine/tests/corpus/099bee2bceaaa8ca43ab4dc45745518dcfec45aa
./engine/tests/corpus/5e0debc4531715986ea694c90b4edc2c56e3a7c9
./engine/tests/corpus/1f5d83fd3bc70bc4babaa833df05f9bbddfd28f1
./engine/tests/corpus/28cdcaa32f47868e72042e0f25abb07cc803e49f
./engine/tests/corpus/fa05f1201c379ed1c4c76bfbe5e108b93a12a241
./engine/tests/corpus/881802970c46a5a1d7db757fa6151c0f5bb433b9
./engine/tests/corpus/11483b156118e4842519e1faaedcf3b051f3a508
./engine/tests/corpus/beb0aff303170aa64c2834d9a3f1aa030cec3690
./engine/tests/corpus/b94111b41ff55fa972d1be5c6680b7faf47ea111
./engine/tests/corpus/767d51e115e608bb0b334cabc650d4da1717009c
./engine/tests/corpus/c9db89762cc7bbde4844f71a32b9e7777e3d8b44
./engine/tests/corpus/b73f1496072fa1550047dd3b7ffc2ee402ecdc88
./engine/tests/corpus/57cfebb56406653be02599b4d9f986f86bc4d762
./engine/tests/corpus/549682e1075cdaa23fc2d6e6b311c668bb41db26
./engine/tests/corpus/093c9f5b04236c3fa774fa7384b5cd9d87d2517b
./engine/tests/corpus/a9a796c4d3b0ed228af35e87099d2b3dcaef8439
./engine/tests/corpus/f92b0c3c1218ae094dd8fea360a7fbca3fc4a3e3
./engine/tests/corpus/b1bda49e06af818047ebbb6720793d631dfcab04
./engine/tests/corpus/b5ca6c7eabb16456a011312f6d0b10d903845d57
./engine/tests/corpus/0bba2bed115be1d17bacd2398d6aabfde0e1dc39
./engine/tests/corpus/9de688ddf2cb0af6c649b4defe54ff1ded4c85ed
./engine/tests/corpus/1de1911a4ebb448be3842d6faa92a1bd7d67ff3f
./engine/tests/corpus/1f9aba1f7e3bd463c3bed2890d0ea21de1f8bdea
./engine/tests/corpus/3bd38d9112641f33cd2b8fa40e0a20977a59b766
./engine/tests/corpus/18553db32923be01ffa68381a0d07f657c62f7d0
./engine/tests/corpus/c4c86b240ded3911a12f020a5e51e73d71889163
./engine/tests/corpus/5691514086c76f8e731dcb3347c0f3968aa81d99
./engine/tests/corpus/b85e3da2436cdf54127cd44a1fa74d798f747505
./engine/tests/corpus/e67593200efe109323df0f5b537c37dc5bf9fbaf
./engine/tests/corpus/2c87232e3bbabf4ead51293c04553acb0db3d73f
./engine/tests/corpus/e4b399ea19957061e759eadeeb3e13f3851810ea
./engine/tests/corpus/ba8e3eba52b6fe331f87cec5ad25658d2fbf729e
./engine/tests/corpus/9b25ce29f71cc69198f0590d143a6ca141bd012b
./engine/tests/corpus/136df20c2f6647ed098b05098a27164a1c40aa43
./engine/tests/corpus/7eb8382ed0820d31bed52b74010ba07d8d4da635
./engine/tests/corpus/745a2aad2facfdbcd19174f581372d688e2c85d8
./engine/tests/corpus/021acd72268e79b5c6e8c601475dcb9e9cd2070a
./engine/tests/corpus/69374a803287faf7648e51ef835643ee7c2889cc
./engine/tests/corpus/a55620d1debde18d80b41c0a1378139a86e321a6
./engine/tests/corpus/0702bf57a9103567ca0a8c5b27e366bcda209b1e
./engine/tests/corpus/77a7ca89e4b28f0c667f188b020e52fc34da4e86
./engine/tests/corpus/daf6cb25b48e16bdb50067e86382e1dab1684f85
./engine/tests/corpus/a2f9248a9f194913a8ec8d5672a629791c943e06
./engine/tests/corpus/cb840a311da5bdff6ee7a419281f7eabea62e9d8
./engine/tests/corpus/076531f4a2513d760e2e6e5c433a466384502155
./engine/tests/corpus/a8b59b3367126c85238f7773c6432ec5b2d6f8c9
./engine/tests/corpus/0e0a15aabc7262d9f873fb46a4b506cd476e3b0f
./engine/tests/corpus/da51f66cb6cfd7ae26aa98f096c555b1adcbdc6f
./engine/tests/corpus/5e41b66ea56f0550eff74df424c0087cead3af6f
./engine/tests/corpus/68ea634553392b8d0eef9fbff112256034e9ccd5
./engine/tests/corpus/9da470f9eb2b9c70ebe734a63c40e3caa59ed0b9
./engine/tests/corpus/526c7a71b71ca765c2ea6e29797211dcde0fe157
./engine/tests/corpus/72c03f51279b1b9d0321ed52190a6627a5e2aead
./engine/tests/corpus/5bcc2984aed702d27e08afa3f699d82d0d85558f
./engine/tests/corpus/1f49cf4fb76c40e9633ed08fa83479d75126d592
./engine/tests/corpus/d5654011c9135af5b20d92ed0863e9643f6c7e97
./engine/tests/corpus/e77badfbc45bab9dc2df439e2054baa3b6dd33f5
./engine/tests/corpus/98c3dbb03f012b2f8e3903edde8c88c2addfab17
./engine/tests/corpus/60ce5140e1a6f1febabf00b6ee4558b73c81d5bc
./engine/tests/corpus/cbdda8edbba1abffad4e620918ac96ca50056b9a
./engine/tests/corpus/ad72e6dda8fa868b48826fbc9746adc1fbb00997
./engine/tests/corpus/a0d72128c74dff4ee082413b12437cd34888e2dd
./engine/tests/corpus/5eede866fe3378cfd174365d0281126ae5eb86ed
./engine/tests/corpus/6ed1c1a8041394c6f610521116ebc342bb00a383
./engine/tests/corpus/55cdd2bd48f6a6655c527789c41d6f8327fe82ad
./engine/tests/corpus/ad9fb804e544a7f20bf3149e4e5c35f072e4e631
./engine/tests/corpus/f88877b71c9837bc70938694353fee46ffdd8aa4
./engine/tests/corpus/38a6150332a1bc978b560a9bc5dd25042265e399
./engine/tests/corpus/c35945db06c4294348149cd676f7c0d4ce6f22da
./engine/tests/corpus/264e5d6e394649112dade866b7cdd90d1f6efbd0
./engine/tests/corpus/0c598cbb475ff3e2ec6f58f42678ca9603f97b20
./engine/tests/corpus/479eeb66f36c79591e48aba78789b18f4041b63f
./engine/tests/corpus/a5e21b501273bd6d4100407f703301d2bb038e80
./engine/tests/corpus/a8cc7f03ac97289c1b0900645468aed1b128fbd3
./engine/tests/corpus/82e5433ca804b96ce493d8a9d1707368b4b34c7e
./engine/tests/corpus/95237155697e75b46066f8a82362ce39070428a0
./engine/tests/corpus/e6b1d9d7d70192bb7cb552b7565ec4442c73a991
./engine/tests/corpus/7c475b7f763f25e95034414870bd287d38dc67b1
./engine/tests/corpus/0f79a9977ddbe8a7ad8bd8e0ae3ad8fc13bdded3
./engine/tests/corpus/165a279d6c2bf053913fb6fb59590fe7a42fbd95
./engine/tests/corpus/540cc68dfbea14579ed55bb6ecc8a508bbaa39d2
./engine/tests/corpus/7936dca56ba0b001ed3cf67a75bfbe4430a282a4
./engine/tests/corpus/1b64b7a3e57696634255efb8a7c4effd370d0d54
./engine/tests/corpus/96999a201b49132c284f32112cb91bf101d2cc0c
./engine/tests/corpus/097d24f42b72bd85f53183ed4a937781374b466f
./engine/tests/corpus/6a314e4d7ab7a1e8c22bcf8cd6e682ce6ea855d1
./engine/tests/corpus/63436241140e3bf988d98e6c7b35e76e1600f9b1
./engine/tests/corpus/356ee70aa1e6879d6ae011a522732d29b8735ddb
./engine/tests/corpus/453b724e5aae5dbd118996f18d461fa5c6bda2dd
./engine/tests/corpus/0a99fe7070beeb9b0894a17771002d31e98300a6
./engine/tests/corpus/a21d3157d8d0a1f56fd46880aaa2939543d1d339
./engine/tests/corpus/c4719384f775e00c37b16022eaa024c84950e701
./engine/tests/corpus/c4dfefede65c527e173b07bcdd54433733ec47e8
./engine/tests/corpus/2f01a17715ad5ece2befa7ce1a21cafa92ee32fe
./engine/tests/corpus/ac7ea536a01fd534dbdd0fc200eaf0cac64dcfb9
./engine/tests/corpus/e175236d135f91efd16777d8da9de4d7090dddd3
./engine/tests/corpus/fe17054556ec35a01ee64e89f8ba7b2059b41628
./engine/tests/corpus/bb8745585ff645542f2c6f84c5ec02009e3643d2
./engine/tests/corpus/7aa78bf2d3438fbfe52ff4715cfc684ded325198
./engine/tests/corpus/215ed914d46fd823c9b34fe81defbd089f76ea63
./engine/tests/corpus/3f1c22fa71f4b9e03748793839f226db2413a1bf
./engine/tests/corpus/0308cebcf036c729c449a127102523da943da852
./engine/tests/corpus/9dc772a282515f3fb4d44452019633525154c540
./engine/tests/corpus/a599d714364db8889f8ef3c127d8cc04a5e2f424
./engine/tests/corpus/2339330278703359d3c80065ae7d31dcaa187f73
./engine/tests/corpus/4dd8464dd696015e0f0045379493c2b18589f8db
./engine/tests/corpus/1abaa47f6dea26551e457151f372a7b60029a688
./engine/tests/corpus/1f3172632bbf4757c85b324e2c2aa6b2a1c5da93
./engine/tests/corpus/0668d3ea2255ae0aeb591ed2f749e594949f05c1
./engine/tests/corpus/5de4af75787ddab0bb7cedcff35c59c3721e0548
./engine/tests/corpus/8a5e453d2120b40864bcb8fbe06a24773716f2fa
./engine/tests/corpus/46a9c4150cdadeeb0e33de91c7760f52e061b1c4
./engine/tests/corpus/e0f66ccd1be710e0bac6daf2814654baff63570b
./engine/tests/corpus/612e22568bed7203ac637be63f9e90ad0d2005fb
./engine/tests/corpus/e82388c9926b7912df95b8a13e2de7c1db020126
./engine/tests/corpus/0b63691aa591e5771daa564bb299140652ff3e52
./engine/tests/corpus/4d81c6269c2f8967a507923f82c1078e75dab865
./engine/tests/corpus/94ca43f37e6b747b940ea1a3158151bf7fc2bd13
./engine/tests/corpus/40dd9270656bc153096a93974093ee3a6c54b260
./engine/tests/corpus/7011b5ba7cffeae58765d77ee4491eefeb29af79
./engine/tests/corpus/d799972892d5fe8b32571ff691090223de6f8a47
./engine/tests/corpus/8ca5b35dffc3cd7752bf79e64ce748a86fe3d2a6
./engine/tests/corpus/7f22037687bce75f810a96b6ac1efc460f49934e
./engine/tests/corpus/13e1339cc97ee3641fd29ec16ee53b14ca955dfc
./engine/tests/corpus/bf6d614e913127ad1487d695f7eb52b68e430e3d
./engine/tests/corpus/decaf20f7b7c8367ba7f77cd571c7048635aa844
./engine/tests/corpus/c2fa239fcddc507b7e9f1388ae35adbff34783f0
./engine/tests/corpus/7ab1167f32d4e173ba8146911a0486c90fdf3b52
./engine/tests/corpus/f04bc8fecf9953aed3676a19d37e97760dca36ea
./engine/tests/corpus/7c93ba4dd590df314ec547beedf350efd1b3f9d4
./engine/tests/corpus/737a8f54c81016326fa323e85a02943aca0507c7
./engine/tests/corpus/00b07611d98f922fd3b5ac5d04f58f2822e0da8a
./engine/tests/corpus/38fd008210f2447f17512dc1f483050f1138a2eb
./engine/tests/corpus/491e9987306c9c802d465ff78646612cd19c7b03
./engine/tests/corpus/36d84a44008e4f586ef0568bc81338a957d989ae
./engine/tests/corpus/72a740158e59486d64c362c4e9169e8fa02a94ad
./engine/tests/corpus/219216c8a10ab54e3bb5e08872a7a0b3e4cd1cf3
./engine/tests/corpus/42b9ef3e53ce875186dc435005c28d1d89429f73
./engine/tests/corpus/93c041055ed8d7602c77961fb7d5fd9d1d38f6d3
./engine/tests/corpus/228e4f54f9ca00f696cb37afb19e679f8f2b4b0f
./engine/tests/corpus/98985167b6d03a075c255e9708e1f62666a462d0
./engine/tests/corpus/ab69cd8ece29eb8790a2e911328d2feba49e199f
./engine/tests/corpus/2a02ac2d02df25b27bf929de3afd9408c1fe1708
./engine/tests/corpus/cf97956c1b2f08465e32e58bd9a24e9cdff9dae7
./engine/tests/corpus/763c520448c7959df2f7f66fea6829915a41820b
./engine/tests/corpus/6c0452b869338a1bd00c4c32de89aa1fd6c7c6ee
./engine/tests/corpus/25369868fee900de2d12b2643269a11d8ac683a7
./engine/tests/corpus/d2d4a8713e7eb9925a3aee0f042badf971a6bdac
./engine/tests/corpus/54c52b52393a0c4100be61c3ca873db6660f8945
./engine/tests/corpus/425c9041b6323c19910bbe5e4a18d81e2f91865f
./engine/tests/corpus/feb8ffe574b0a92f6beadab110f5582c419f9cd8
./engine/tests/corpus/2f95fd8114142fc9b5ce2d47fb1f238b7f7f6e1e
./engine/tests/corpus/287dec0480be6e41641d7b7b55a83aa2fdfc378f
./engine/tests/corpus/bfbdd9ba36c40501b28bc39984c867793a2c2aab
./engine/tests/corpus/28a197f256583ed34f2a6110fb69cd15cba92a3b
./engine/tests/corpus/b8f41e1ab3e2fd65251887bf7284b9c32032eb08
./engine/tests/corpus/5294a70a41ad1c86697093db163a12728c4b770f
./engine/tests/corpus/acff4e9df881b181c56479132fe2afde069c9603
./engine/tests/corpus/7c84a872e1fadbe93a07c0e477d71ad94c1ed1e1
./engine/tests/corpus/07f7127357afe5215e01ced8e0dc36c3249e8d71
./engine/tests/corpus/a0410375207f1da1bf4a0b497a3c468baec992cc
./engine/tests/corpus/7da76722ba422b7210add51e92cda27e3e37c099
./engine/tests/corpus/268f1fd1122fa43c24e3a3e65cdf5aa2e9cdc035
./engine/tests/corpus/b3c98c61ec0085caa00624b08208b34ccf0640bc
./engine/tests/corpus/2b83dd31fbf4adc78aaab60e48c983d468bc033b
./engine/tests/corpus/3365570f69ed2aa741ba670d870243acfb572f99
./engine/tests/corpus/43d0d82cf75cb53471b2b0aac3ac1a79c76ae938
./engine/tests/corpus/d579ed415c7bc3d54f4e7ff64cf5c37808f7e33a
./engine/tests/corpus/321a9e2ebe66c94cfe03f26f41d5436ad969b473
./engine/tests/corpus/7b77000e73688e5dbd22bc7c5c4c291d3122951d
./engine/tests/corpus/22046b5366fa799566795768411fa92563fa1bb1
./engine/tests/corpus/76e49c05ecb557784eff0646e39977f30a2d46fd
./engine/tests/corpus/f3ef3e9ee4e83bb0781a5fab89b46a8b55a05507
./engine/tests/corpus/e906a2e424b89c6afe23e0d58558cb41af3bf126
./engine/tests/corpus/1943a47de012db4c1a07884a808bdc0eea6fb8fa
./engine/tests/corpus/8581e3d1c87158b4273afc0b5eb0cfb4399ec437
./engine/tests/corpus/3cbd9e9073383148d2665740bc83340a49c20365
./engine/tests/corpus/3351d732b9857d4cdf099ca61962f9c63ad87c64
./engine/tests/corpus/b7f393d0e29260424b523b03b90a9c09bdee8a3d
./engine/tests/corpus/9deedeaa182a43d579cdc38cc8e6aa6ac0fc5f88
./engine/tests/corpus/1b7a01dcef5043adc3bc3511583994e59c69bb78
./engine/tests/corpus/8ca13a1cf315488747d1568958b2f7c7d3f1b962
./engine/tests/corpus/47f9e8abc4359c5ae33b97a83f00c3ab56c7690d
./engine/tests/corpus/06c342e4bdceb0d271a6b406adc0c696bde56e03
./engine/tests/corpus/affb972f5aff060b0bc38913605113484aa60b96
./engine/tests/corpus/1c66101e885fef166f5ac949c38e74ae57bbbb31
./engine/tests/corpus/69cb1d69826dfcde6bfc9cd416187404f3f498f3
./engine/tests/corpus/4ce48f5a5436cec0ebdee5df77e1762a79ae8c97
./engine/tests/corpus/c1e9d3902cc6f7ba77bd0af5c26ed0c35baba7d1
./engine/tests/corpus/4ee047a53ea1e7ee6e2ed77982b82371e7122f5e
./engine/tests/corpus/41d28f30aeec715ccb6894be3bac796412ea26f3
./engine/tests/corpus/05ca19d7c24ae5572659e6a428a14b4c1f27210b
./engine/tests/corpus/62bdd4dfd6b91eb73528d75400b3776c7cfa57f9
./engine/tests/corpus/2cc322ae56b355324e8f80eb20bdc6c3cac03c96
./engine/tests/corpus/75ca48fa06dffbb51b30a58c8604b4cc3009cd3f
./engine/tests/corpus/a0076cfc6a1a97ff30c018e86d0a57fec7da4c84
./engine/tests/corpus/c4b922b3b3ff6ba8d425ab95fdf8737066faaaf7
./engine/tests/corpus/7882bbf0f91b373f090dd4d90a3dc3e534bdd7a7
./engine/tests/corpus/ecb706fe247e05026d633b99bec86193d515bf48
./engine/tests/corpus/63c171b3c598c3ab30b55b764c8f4a9586bc1a89
./engine/tests/corpus/cbcdf84c80cdf00334cf03a0e7eaa0f191dd1806
./engine/tests/corpus/c01734338e1562cae4f2faae9d0da16aa47fe348
./engine/tests/corpus/17774b303dd659d755834330ee9efae6ef18d787
./engine/tests/corpus/422848d3886e4c08853c3bfb4bf3f8576c96c41b
./engine/tests/corpus/715a1da31b35d436f19180bee67c208f6645ed13
./engine/tests/corpus/2ba137a6fb0b98f19ee85e00f089b336710803c1
./engine/tests/corpus/e1de3818c2309f9a80ba30a245aa075cd7c8a4b3
./engine/tests/corpus/87780d476a008f24fa7e39cc641610313de34476
./engine/tests/corpus/9d3752de636bc23016efc164e045a2c4859ff132
./engine/tests/corpus/e02cfbbafbf0500fc73994f4980fe71e9123de5b
./engine/tests/corpus/f20b2ae4c221dbe3e994841ae0d8f6ed491cdc8b
./engine/tests/corpus/3a10aa18d4e915245ace5277f25f344fa65edeef
./engine/tests/corpus/d7db6d1bb69a971cb052beaf40de7b1d0d36bf42
./engine/tests/corpus/7fb1a2d83df35fd1dcc3474f0fcadf8fc727a377
./engine/tests/corpus/e42a8bc2d787bc68c132cefd84fce5c05d9e3045
./engine/tests/corpus/40728d72c8079069e917eeadee828f7a19cadd95
./engine/tests/corpus/ff0ac465edf0588c68316f41c9d5dd53136d6838
./engine/tests/corpus/2acbd3b9a62599bbfe484379f6301c0b1c501bf7
./engine/tests/corpus/b35e67540484bd05a49cb2201c9fe7e01ef53623
./engine/tests/corpus/4d97359bada57fbddfcb55804ba758641b2135fd
./engine/tests/corpus/8ea3a124eec86a0e1135ca9bee371e8d920cea14
./engine/tests/corpus/dc0a0780a423743b3835885defa5468897fde5bb
./engine/tests/corpus/142050368dcd48a570fad1bca815cb3006126db2
./engine/tests/corpus/b88f1220da07d14da05108a1fc6d086e6206f3bd
./engine/tests/corpus/634fc23d6914089ffc74c83e32b158f10f1c7fb5
./engine/tests/corpus/369c163432dfdbc99ad506c6b7a3535f58871029
./engine/tests/corpus/a3546736ecc4ae59a8a24da25a78d50c60151c30
./engine/tests/corpus/7938acc073d13517abe068274268605f69e37c58
./engine/tests/corpus/5f163b3d1792d757a8d20a0ccb33de676608594d
./engine/tests/corpus/568e31767742e3fe295957fe250bb82e10845bd7
./engine/tests/corpus/990699ec80374181ee95b9476573e8ec95bac44a
./engine/tests/corpus/2be1cb6bc61d9f129864c80cdd3fe8822e4a9393
./engine/tests/corpus/d64f9ef55c3bf61a762342f22d9f11d9626c3b5b
./engine/tests/corpus/aae768b11fed1aaca56c3b05be102cc79cb76eb6
./engine/tests/corpus/64f609ebbefe0c880cb1b73903788a86283617cf
./engine/tests/corpus/84d1e2786b8a598f06638b6f76e5874a7aa18e8b
./engine/tests/corpus/13add0b8cbdf1c9162abb54c8c2226064a63ef52
./engine/tests/corpus/d73d1322098dbba9f21e98b87703db2c82682f24
./engine/tests/corpus/b2c38cb4345f23eb9824440fa23e881c490f3ed9
./engine/tests/corpus/26e444f58d668d40888d39186ddc3e1f39c61021
./engine/tests/corpus/9feb5f023e26f064928ccec4a751f030d6d564a4
./engine/tests/corpus/4a0aa1b683f9a232a1cde785b8eaa9a058908d4f
./engine/tests/corpus/2a7d8c33f89310709af6520dab13a3a10d4ee6b3
./engine/tests/corpus/e3a1a6b90b7df9aa5a897c39c884c7aaa77bf0d2
./engine/tests/corpus/fe7bd374103b1b30935b78fe4893b8d1f999ecbb
./engine/tests/corpus/0c6efa45b97f795523f99ff01b628039fd1ef953
./engine/tests/corpus/ec49ddc3111804a58fb9af5ab96ca2e4c7cb4d87
./engine/tests/corpus/851fe58c166f14008acdb7a8b9acacf3c233e0cd
./engine/tests/corpus/d2f7b4cc06cce14243ba76230031259123a8075b
./engine/tests/corpus/505e05dafa39ec074a8ae06f5e855f3d2cfda06f
./engine/tests/corpus/fdf211314a7994f4cf29bf75ac3a94486a99465e
./engine/tests/corpus/920115dd3ef546a609ece72418a125b27d3a2e20
./engine/tests/corpus/dd981ae1921869092acfeab8550f948ebe597a97
./engine/tests/corpus/98f0d53581ac7647dc8ebe0868f15b3ea1da1713
./engine/tests/corpus/425690d7069a65968ae3b723a3554c7c22ab8898
./engine/tests/corpus/24c1ce2f50c816327bf5895a3ee066b32318de3d
./engine/tests/corpus/9f48bb2d41f8ceb3e9f0465076657e38b0aa7d02
./engine/tests/corpus/0721541e4db866fa49fbc6bbc87b53906c954278
./engine/tests/corpus/724d038bea10e210a566f985c9019529f7a623c5
./engine/tests/corpus/812ec07bb0ec4296d02a3349ebe02c0cbe0c0026
./engine/tests/corpus/de1cfcedae1a9d76097e763caae06209ce8ac4c0
./engine/tests/corpus/6a556a59376d4a213f77eb9ecbdd2293915018d3
./engine/tests/corpus/97a1f9dee112d22faeae85d971d8ee8451cfa2b0
./engine/tests/corpus/4bd14ed8b5e6b7f7c22d2a1fafb4e5d3d5a04b0d
./engine/tests/corpus/66a71e1fc6fab751da2db2ed5f1d65c2e30e7762
./engine/tests/corpus/450639beb66306fe65f6bae5715fec6a24ad1cc1
./engine/tests/corpus/2706fc5e559fa2b4fcf1af1210ef515649aea2a6
./engine/tests/corpus/ba06d5b28fa347935cb7c35fb7752b5fd0a119ea
./engine/tests/corpus/0c39516a11d386188fec5c3779e12e58532a3724
./engine/tests/corpus/0bc6a956520b42cab9939eaf47733a356259cd50
./engine/tests/corpus/dc0aca8554485ebcfc71805662b1f7d133ef50db
./engine/tests/corpus/179519a7d3c236eb6ef0f82632ca54a0f813b598
./engine/tests/corpus/feb9bc49cf81111fd75ea1f8f0ed4ac8e2f50b6c
./engine/tests/corpus/4c804da5614562613afdb21063a9a07fea78d287
./engine/tests/corpus/fad6728eab6b07cad3e5ad7c61c41fed9ae42c9a
./engine/tests/corpus/e3ec87c1ca50d604ae72f73849b817e184d5fdd4
./engine/tests/corpus/1acebb1b96984cc004e98c61f0a0bc39561a010f
./engine/tests/corpus/11eb078b70576473453a7bca3f2a053b431d864e
./engine/tests/corpus/9a532dbba9c91d7c74b29b24415c12b9e0b61dae
./engine/tests/corpus/3dec71731e6bbdc6228a5e6d61ab176b8c064352
./engine/tests/corpus/7ce24db3ea9e05a8fff31cbe1f40acbcfb6f3edf
./engine/tests/corpus/11c3a44df6a17f29ea1ff75e04404ae075d74df8
./engine/tests/corpus/49b2869c70dc2277efaddb737a2d8131e35bb2a3
./engine/tests/corpus/239058929e3228d1d6df7d0aa9a646b25cc3f86a
./engine/tests/corpus/33840cb9af9b3222bb184022b380b020bbb27be5
./engine/tests/corpus/b3462f4945a501a8ff9828b3a13c67964e89d3dd
./engine/tests/corpus/e1edd3e9daf7bffeb884f471b2b7b5cf969870d2
./engine/tests/corpus/e2754825507681d4c85c6b6f8c170f79a9a51cad
./engine/tests/corpus/c490ffef684d9a48b8161e121b2c5584a7d1552e
./engine/tests/corpus/7f6a28bbc6f7f93559eb0bd30321fe1d4884181a
./engine/tests/corpus/8ba26dcea826a066c17176b24a85fcc21cdc1525
./engine/tests/corpus/df8d38862076a17f24e8e1d7b768b4ca6c384951
./engine/tests/corpus/12c9cf5dd672275b95671d50fbf22bc90ecca0d2
./engine/tests/corpus/d7395700474486f577d8c76db6d7eab50cba952e
./engine/tests/corpus/bd1385d12a890a89de06d189558b8090fc8bf93c
./engine/tests/corpus/ef51dc6576f41e73a6637ecfa8ecda12d980592a
./engine/tests/corpus/68c8c16670a320539b405a0d61335f97eab24c86
./engine/tests/corpus/c3960d8c4baa4a06269d51ab2b7faaf42a0b74d5
./engine/tests/corpus/a8e7e597716a5cecad4846d17ce6f96a5cb742c9
./engine/tests/corpus/a2f9b8df81de79ec6bbcdce86a9f3dddfb74385f
./engine/tests/corpus/5ce005be29123038c870d46f055f7c020b73d4bd
./engine/tests/corpus/7c860764765d85575a23a4e3fa9f86998e64f766
./engine/tests/corpus/8b55ffcfd69f5e818ddb122a71e255cfd6186dc2
./engine/tests/corpus/7eb8cc35189afb4ac5929331fc71ca1317b28b65
./engine/tests/corpus/ed4bd43e6dd07b7f53fa2c1e77f30c35b8fe8273
./engine/tests/corpus/056686bc82ba4b6f41a8045f7abf78bf3b291c75
./engine/tests/corpus/69b6d9a5b18d725d2072363a1171c8b9ff5a8d73
./engine/tests/corpus/f7463c85baf46c3cb2e51f221f78efea3b254dff
./engine/tests/corpus/d1268f2e12919b42e215798b7bd2f2fc58eeafbf
./engine/tests/corpus/0c4e37680010b306b9ab60d0318580f269074531
./engine/tests/corpus/407fe897be24358ed918366e7a3dffc90e8bf21f
./engine/tests/corpus/cd467f232daf3bcefd40ced669cc771850020a5a
./engine/tests/corpus/f2753727d39bd797acec172a01ea4c8a0f29dd94
./engine/tests/corpus/7b93f21b6b9156cb4dc81926bc07023611552d45
./engine/tests/corpus/be4d3f6a483de0faf9b70f960a78271436c79115
./engine/tests/corpus/c1c0e89d28f3c9b8d77fb150438f12e000d19fb4
./engine/tests/corpus/b2eff206c74321d339a705380785fe7b4dbdf265
./engine/tests/corpus/a89fba96f5d0b89970696a163c30a813aafd163f
./engine/tests/corpus/62d71b27a889d16f85e07f2157daf954180c00a9
./engine/tests/corpus/3bcbbcbb452540f1c37958dd3378bbac2aae5b24
./engine/tests/corpus/e3376508079de6f7120a7df29fc2fab0e0e7abcc
./engine/tests/corpus/495646659e74f303be12e45460501aeee0d0a8b9
./engine/tests/corpus/03536c03c8d457ce7ab1bdce4723b11e79b05ed6
./engine/tests/corpus/aeb76406c57021e4d28ddfdc5b2304c5125036eb
./engine/tests/corpus/dbaf90ed0b05091b7dbaf556633d30ae38ae0698
./engine/tests/corpus/d2e8691d3c3925f23d06d882c924c36db77f5d2f
./engine/tests/corpus/f66f8eb198a19d47ca855c0c11bb7df2eba5ada5
./engine/tests/corpus/3e1daa895d1c14419521f8f5b356e7b25483cb35
./engine/tests/corpus/ad8995cdfadc2fa97980314da8b5a2d54ab7d278
./engine/tests/corpus/a41606042f866cdfa557aaf962328f1f8c4e5087
./engine/tests/corpus/89c514c4e2e5b6ffbfcca04b5c97bc30bb7fa6c0
./engine/tests/corpus/e25970d413b761d3553a06cc4ca6378d718b3082
./engine/tests/corpus/cce064697e6630b2790c8a80739557ceb8214aeb
./engine/tests/corpus/407686f18b986f745e690b839e515bd27e47a371
./engine/tests/corpus/41950bd9b430800b9eeb7de755c5f3235d8ab97e
./engine/tests/corpus/23c5dd662ea9f288eb6832f77b0f6ce726749a1c
./engine/tests/corpus/83ce36de825df00fd78b9ad68655a2f24e8c3b4f
./engine/tests/corpus/d6096889db227bd1e9cac2fd2b5bd54c6acb540c
./engine/tests/corpus/09042773c3a0ac0e1c06a372e691b82dcad10a26
./engine/tests/corpus/d4f9840e8411f5cbefece378b8784a9e30999597
./engine/tests/corpus/8daa02494333ddbaccd64e30f83cdf17d6d859c0
./engine/tests/corpus/70b67f96aac6e73d84ed9b8349f58f43a2aff555
./engine/tests/corpus/be447c9fdde10dd0763b1b59cb531e673c4acb58
./engine/tests/corpus/59434a1bb3b8824d169c4fe642e57cdce465a093
./engine/tests/corpus/90d499bcb31ce1a2f1cfb504b52c7af88014cff0
./engine/tests/corpus/d37e4bae572ce010ce58232edf71c39e261dced0
./engine/tests/corpus/13ee475da38652eeb658002232ed754f36cdb40d
./engine/tests/corpus/dba267c650af8a141a07ecf6a45ab15ce958bd64
./engine/tests/corpus/7393f3bc8064a94502d9a691f8d405a5c5070a2f
./engine/tests/corpus/a7dbc9a9fedbaae05575d168e67ba558fd4a1234
./engine/tests/corpus/55da87956a505b82558ba66e53358dfa4544a75b
./engine/tests/corpus/c26c4933ae7157c337bf15159299fa562e2170e6
./engine/tests/corpus/43f3055b27c4d409f9701229d459eef145cad100
./engine/tests/corpus/13a8501de2451c992c73a924c599f2f5c0b8ed36
./engine/tests/corpus/98c83a01ade9efde1f0749fc1ed06097a7dea3e6
./engine/tests/corpus/00ed7d9345245e1a0298b152cbfc66b4f9db4e06
./engine/tests/corpus/663aed1369bf10980d30b6d3a4d09f9494e39b99
./engine/tests/corpus/47080d50534484c072201ee585e2a4492f92a34e
./engine/tests/corpus/8a48f5975e6b2f550b306948725501869565c2ab
./engine/tests/corpus/27c1a4f560619bab82a9d3653cc18aa7b40aaadb
./engine/tests/corpus/b2d99b00c3f3bc3a35dec04f473409fc21c746ad
./engine/tests/corpus/ed9be32a3ff9239ca4ae1d502ed78d5965e8a24c
./engine/tests/corpus/b0af3ab42e92688efcc785418c243ece74ea5e8b
./engine/tests/corpus/cc6a387667c87fc293a70bf92e0948cb7971b322
./engine/tests/corpus/a20487c887350910481320873cd9c111ea45d054
./engine/tests/corpus/31c7119f44bdc7b3c93416c055cc9723f0874575
./engine/tests/corpus/c260ed9ff9bd7d7106e1754be33b8829b68ffcd8
./engine/tests/corpus/1f66fb7fb9375980f3c7daf9ce2eb9da322c6237
./engine/tests/corpus/9120c3b946f0bd61e249af85be98163507663008
./engine/tests/corpus/5e1a5a21ca4d13d4b1836d99bd6089b269d35103
./engine/tests/corpus/6e36b0b1f13282dddee072df88e6583dc2951fdb
./engine/tests/corpus/7ba9199c54e518f1a4ef901a3a6071af6e3fa50c
./engine/tests/corpus/287cf425612bd6d6b2a96cd4070104137fb06b70
./engine/tests/corpus/436a10b01062aae5b73ed3b57bcd56975cc2f6c6
./engine/tests/corpus/3797d438240f4d6d34eaed81bec138d42e2bf802
./engine/tests/corpus/1c5ea735ca890f2d8017da72a98e02513a747098
./engine/tests/corpus/26eaab9a9c3ce3a94e16b7b62ba4f0785ab2578f
./engine/tests/corpus/0017123ca3f379677c740220c63dc7cbfbb963fc
./engine/tests/corpus/75b99d8bbdf33f03a581536242034c875d8fcd55
./engine/tests/corpus/37fcc963d5bf30a5bb5f4543551d92b2cb93002f
./engine/tests/corpus/7671632fb0893173eb8e639165eb1d74bb7649f4
./engine/tests/corpus/53dd685253df733d21c21a26450bd951ef2ec632
./engine/tests/corpus/cb9042c546e5ffe53b0d3aea4b6e0f18042b4482
./engine/tests/corpus/e9283367a38a83f744d6150a13a4aa6b82a7f90c
./engine/tests/corpus/f9069fe3662672ffddbfe63881612ca0b3d872c1
./engine/tests/corpus/3c84b077222a2c07c968964306b8af3736e76b98
./engine/tests/corpus/890c8f276f26cd0d572463985bfecbb29897c6d2
./engine/tests/corpus/ba1496ac22eed77c828d22c7bddeb6a81ce731b8
./engine/tests/corpus/bc721710a1d178ee126a47da207d950d57df5f39
./engine/tests/corpus/4754c892ef4101441e100138db330bc1741d2cdd
./engine/tests/corpus/99cab98924e456128be9d586f68aa6c80cbce300
./engine/tests/corpus/d737c1102a5c2ef1e42acbf1254cff573e43d156
./engine/tests/corpus/11fa919f08a6801f58e974cef438ba9d85992090
./engine/tests/corpus/eae68b7681376352472f0cc66358542976f0025a
./engine/tests/corpus/988d38908dbffd5538fe793cdce45781e1f418d3
./engine/tests/corpus/88e49dc6b2c28e8843c6e02981dff90650f73bc4
./engine/tests/corpus/c747b3d6c20d523a0af5789a04f2fbb65e53ac60
./engine/tests/corpus/f6e9a34205c919e94ebed93537946f50e765a4e0
./engine/tests/corpus/7a3382a6f8a15147af1551d7f3a213e6afbeab97
./engine/tests/corpus/e3d73bb8f18901ceda8a3da32731d941d76c37a8
./engine/tests/corpus/8c8ba19ea70de94cc47e59c511b7cc8e222f6f67
./engine/tests/corpus/3d66026259a2ab54383dbf370d29a97bc3bca6f8
./engine/tests/corpus/76d9b5ab8ef5e6a49ff308a405627483c27f8160
./engine/tests/corpus/9b5130e0051f0c2993c568b2982db2a28f83be5a
./engine/tests/corpus/fd792134bf66a3ac254a8b8fdd1b95ac35d2e946
./engine/tests/corpus/20cfc3724ee38fd2ce938e2c896a4d0193f9a10b
./engine/tests/corpus/e95e3d21fd5ae69f92d94baf69da97a916275df5
./engine/tests/corpus/6cb6ef480190eaf92ce9d216118e330d04545e14
./engine/tests/corpus/39c44b4bd8dd22ebe43be0774ef5eff84fb6f3e3
./engine/tests/corpus/7e5a505d6a1b0446ea07638fd37b3b3f89d5307b
./engine/tests/corpus/985874dc510aff2456c00c4b063b71c5bed0cfe6
./engine/tests/corpus/8d36df1eb85bcae8aa19250c3fe56945c8b3e350
./engine/tests/corpus/1fccb0c8dfaa8a6343c7fd1283689104c8f87157
./engine/tests/corpus/a341ba5a5392ed118338110ac9b85fe2a7dd8787
./engine/tests/corpus/689618c2d84581c2915d5eb5fdf78e57c52d41d4
./engine/tests/corpus/9c6a68bdc208da51aeecd2c610ba367256f148c4
./engine/tests/corpus/157907fb2c192a4a6f2725c06b2a11f3f5b6ae93
./engine/tests/corpus/1e634ecdfd8a65ae20800c26d999a4b3c3797b28
./engine/tests/corpus/5214c17af65efc26cb492bb7cf2e98d576914ded
./engine/tests/corpus/2db7789eca1a1b0fbaac285d5ad3eb9134d88314
./engine/tests/corpus/ff72f406833cc872f5c0a4edd3f35541a5d07156
./engine/tests/corpus/79af39ab416d6dd281475904d12c42dc100d5b7c
./engine/tests/corpus/b919128c0514db43a83149836139dba5cb53cc1d
./engine/tests/corpus/3edcc6899fed3745f3c10992f145e84dffef2a50
./engine/tests/corpus/dad206933325e3dc838f30ba31f7c4db285896aa
./engine/tests/corpus/8045f884fa61ace645a98b668c5ceb10c6e23305
./engine/tests/corpus/783a1098d331153895f5898103a645f591b01270
./engine/tests/corpus/fc2de3ad1a0f801da79996df988f3da11ed2a11d
./engine/tests/corpus/627fd31211aaad0ff5a988e59d34415773abe128
./engine/tests/corpus/7928559c40621f54b42291249f8b26fdbc02b4bf
./engine/tests/corpus/33d646b3265b8cd2420af862bc48eb1388754e28
./engine/tests/corpus/633d6643e51c481a6992139e5e377d9c4b62c53b
./engine/tests/corpus/301c3d3f50ee7aa4f554bcbae026d427338c254f
./engine/tests/corpus/669c32cc232b6c9a79f4f08b86e3ab679749366b
./engine/tests/corpus/c7c46760f752b856a921f4b655e28467694dee02
./engine/tests/corpus/2bafe61a9d7c3938d313d0220da69dd8a091317e
./engine/tests/corpus/4b410df3a7a883a8d97349c7946d1ce2d67b2767
./engine/tests/corpus/c485fffb49d8d064992b3b24c03b5bcc2a58ceba
./engine/tests/corpus/46fb0543b6a4aaaacd740541041b42e63f437648
./engine/tests/corpus/738ccb8d6752d525cc9dc259044652fe79206fc9
./engine/tests/corpus/c90e2bfc024ee26f9f31431342da38bceeb6cc20
./engine/tests/corpus/7871f5af26d0dc78e3dfb2cfb141f84a5f4222ce
./engine/tests/corpus/94ff4de0ac2920bf1fa1c143a4c5bfe36b150bb4
./engine/tests/corpus/98b1d9036e6ee0b36ed7eef00970c4d8ee67bf0f
./engine/tests/corpus/498d1c698733058e03fe5626534c4833dc723155
./engine/tests/corpus/157a38e18ad257187ebac252c2e9a0e512e84153
./engine/tests/corpus/1ce501dda31bf6e4b38d1723a5de3062b5301e5d
./engine/tests/corpus/ac5a83afb8a7b9faa2f7e7b4b848845278cd6fae
./engine/tests/corpus/919c251761d62525efed32d506acd7db51c1bb2e
./engine/tests/corpus/c4085ffdb781f0391b63210c5ca39d66664298af
./engine/tests/corpus/545fc027c073499da325b2b15868a7169e8e9879
./engine/tests/corpus/7c1bd88a98c45cd145dd705df7834fbb07fe3951
./engine/tests/corpus/204b0fbe1164bd256abdcb4f24d6d2125eddafba
./engine/tests/corpus/5720f642fc781c18201d727d6e77be511535ab29
./engine/tests/corpus/d343a61699d0d41dd28aa372d97907ead5d68183
./engine/tests/corpus/089e7f5da87185c720860676f2c3d5e71ccc5274
./engine/tests/corpus/defc15f901b61bd7d8420bfa71cebd807cd88ca4
./engine/tests/corpus/85ab0aaab9fa6a2bfd9e6dd31f6829274fc2e6d6
./engine/tests/corpus/40ded016793a61eef0b21867f13697e830a7ffff
./engine/tests/corpus/e892cdece268994649aedbdc72e67ec66a8ff71a
./engine/tests/corpus/6c7674bc886a488af3649a08da30fbf137eff730
./engine/tests/corpus/7d27849ff378739e00fbd8d712cbc4af6646c7f0
./engine/tests/corpus/bd26c40870bfc8cb2217b3ed43926ed67804d66c
./engine/tests/corpus/b732be7cfaff421778e266cb725a197d2adefbb9
./engine/tests/corpus/752f46518b618e884350e3c78b7aed458cf6a4b5
./engine/tests/corpus/6625c597ad0d1574bd508bcb1078c9f9b187b627
./engine/tests/corpus/d26d6a849bb5803d4f705fbbbf08cc81ba4d19f3
./engine/tests/corpus/efd5165f8ad238829e1a3ae85b2b482e79f63fa1
./engine/tests/corpus/adf15d0795369fa10edc3f2aad3b8e129efe238d
./engine/tests/corpus/fdb2dcd7285e44cac5709b34f538f420ccb03e03
./engine/tests/corpus/6b0229232722bddb72e8b5dcdea3612f9f492202
./engine/tests/corpus/2c895b2508355587f2d08cc36125ac856821e671
./engine/tests/corpus/7e32e27b930fd9c439c3d6efee4844d389e22fe5
./engine/tests/corpus/172520229ba6248026a23627d5bd52fea384f219
./engine/tests/corpus/93307159790f5021c85409c1fbf1f0c424954a6e
./engine/tests/corpus/3bad54bd3b1002703f32a9e1cf1db125ba7252e8
./engine/tests/corpus/3e889af92ecd01865844ef43d85781e0c72568c4
./engine/tests/corpus/edc165d295ddb1af3f0e916375f6037265e1107f
./engine/tests/corpus/debd4a16a73e002e2ad6c6691bc57c267ca016c9
./engine/tests/corpus/210e92dd128642fd310a3737834eafdfaf8731c8
./engine/tests/corpus/58f575bd6a8db39823a4a49a2f15cd3007ccaf96
./engine/tests/corpus/61568418f85d34c17d6e512c177e5996f1540963
./engine/tests/corpus/d6876887f363f435476edcdbf9da8d36ab3c079c
./engine/tests/corpus/22030602751ec20e599579e12e2eceff0de064b1
./engine/tests/corpus/1e97df10c38f35fd1e65f6922721f2adfb089dd2
./engine/tests/corpus/0d2731468859ebb5cbca53379e75f2fd69fd7788
./engine/tests/corpus/e2d02d40ecfd4e8e2d6d861006066447d027cee1
./engine/tests/corpus/7cf7d7ddf5b60be4968226dfc5e2ccf07a9680a3
./engine/tests/corpus/6a54e939a66008d488b6b79661d53c015765d506
./engine/tests/corpus/069a631488eb8fae12844acf1bac11d160e682d9
./engine/tests/corpus/d134007cc7fb8a677d0ed40ee7cf3e56a2345607
./engine/tests/corpus/6a049156cba7e3783e4e18f3c6c6e1ced8f21781
./engine/tests/corpus/1f0a81d5ccae75b5e7a2c4deefe5fe5b67bd1c58
./engine/tests/corpus/22e9d34c3bea7f773dee1abef4714ba28e315974
./engine/tests/corpus/b4e070cc10155824a8977a2fc1527fc214929737
./engine/tests/corpus/46a067e8b15e9fd604ad10f242795e22472af302
./engine/tests/corpus/a57fa75fc0b82ca95a1e984eb540f208513ba375
./engine/tests/corpus/a0a4031916edbbe3d891846b81c1d1cbf4f775fa
./engine/tests/corpus/33eb2573f63ca63b2b45fa106dacca04df2a42f9
./engine/tests/corpus/4d410e87dc8398eec0a328fc8afb46a9e88c6569
./engine/tests/corpus/b423d1571e5f0c6206c43ed4a12ac547ebfad67e
./engine/tests/corpus/457e341567ca4a6f22242ac64e13cfd923038ec5
./engine/tests/corpus/6d0b486ff0179a3a9db234e6f1cc9667fbecb1be
./engine/tests/corpus/c761d0ce146e79e6e2b59dea2adcb74d8f25aef2
./engine/tests/corpus/fe32b48abe54573c13f2cd0c13d61adbc93ce63f
./engine/tests/corpus/36bac0ec2a56d5857b7aaabf83ccf454d264f01e
./engine/tests/corpus/53607fc655361446a16a466c9fc9c914331e8a1b
./engine/tests/corpus/2686a918420bf43a6d6ca1fe0325b8b87538a78c
./engine/tests/corpus/172a695d018d647129bab0b38a4e31cc0e37fb63
./engine/tests/corpus/192fb7af05430d1cd55c0869eb85522d6e31238d
./engine/tests/corpus/891bd95d4b9a37accb9628fab51b32d4b5e3cede
./engine/tests/corpus/afbaf1fb8f7c079fb963beddda28961dc795547b
./engine/tests/corpus/bd0b4425993f9e279c04e3124b32aac0c6b525ed
./engine/tests/corpus/e6f11800644b51623cec1ff58d32e05fbd9f9d0f
./engine/tests/corpus/42e7178d4907b288987e6c00c9ff89a9353f2632
./engine/tests/corpus/7c27eda3b4c29a7e6eaf535d8be246596faf3406
./engine/tests/corpus/d9f208839bc56d6f6efaadaea12e7a50a4089e06
./engine/tests/corpus/157fa8ed5d904b9800b42da2c4f70b03df1ec846
./engine/tests/corpus/64c8f51689dbf66e432c56f2b6e28f9a910a6fa6
./engine/tests/corpus/cbe6338126f08e93e217fd91f286ba6a7f936479
./engine/tests/corpus/3aa93aca33e996e17cd9cd918f07fdf8c089e669
./engine/tests/corpus/1a73ebe06fa0939cf6ad11c21487a6dc9af1f4a1
./engine/tests/corpus/e6366aeaaac75866f0e0de2637dfb09c989591c8
./engine/tests/corpus/3f97e0914a74046646af441967d27e4ee04e2ef2
./engine/tests/corpus/de9031fdf23f77e74d82972c5d7174068a848c0a
./engine/tests/corpus/52581aa7da847d2d362f53adb64a7c8e1f98406e
./engine/tests/corpus/ee1c842927e0cae327a8df5bf6c56664207ed107
./engine/tests/corpus/3c9090948fbc2b9321c937875930bf0abe8ba14c
./engine/tests/corpus/529ffd9ff0c43eaa9782a443939b3de8937f1b96
./engine/tests/corpus/bf813b9d569de125c9df5a801abef203fd0fa0c0
./engine/tests/corpus/750df5414fc6bb55659ba4eaca3de2f8ebc1015f
./engine/tests/corpus/1165d33410a4d6520ccb92ca6925418a855f5b89
./engine/tests/corpus/23af01d1db52d5f2f59df5c66a35a20ebc303756
./engine/tests/corpus/58ac85a8658ea61d8058017e43d2217e6ec826ca
./engine/tests/corpus/2b93094d0cd8bc6c7812b2c52d85d637a98a30f0
./engine/tests/corpus/18ab3c1ac608d930c6e452a421a7eead06225087
./engine/tests/corpus/950c20ff06f01c48c0f5226a6b98d8bdba076506
./engine/tests/corpus/2afa3c62012878c489a24290e970415e1380f5b2
./engine/tests/corpus/3f6a9c1c2b010676febafd6933b42c9c5c1e20aa
./engine/tests/corpus/3065edd32e739a6b8d349ea9ea776cc4b6f43e6b
./engine/tests/corpus/c57822583ebeb9be2954f58657e3585dbd790543
./engine/tests/corpus/f3b2f41470bb4e85a500bdc52229145f600ce3ef
./engine/tests/corpus/57c5d9f560b8be7bffe2c8ff95d6d22de45a119a
./engine/tests/corpus/9ef4da2468976691b9c175ea4ab8aba4966fd031
./engine/tests/corpus/9c3e6a403c4241d98284835b267689579cfe8ac2
./engine/tests/corpus/d19252d80b905586817120cc1462442a28f64e87
./engine/tests/corpus/3c93b88d5fdbbb59073e77085dda8578a6eaa9ac
./engine/tests/corpus/a5857e61da76a8857c0fdcc037e1dd4220dde6a6
./engine/tests/corpus/98fb7a238903eac5905c925b30d11ebc16db635f
./engine/tests/corpus/466d6fc4e32086e0d681ced994eb24bece3aa390
./engine/tests/corpus/c9e5fbad118d9ab1c49f82f20e1d117732ab0b71
./engine/tests/corpus/c5c6176f0b0dfa2f9449bbdb3d9d277e16c91c09
./engine/tests/corpus/f43c18cda57851a0adcb53171e7a71b2722cf2cd
./engine/tests/corpus/7bd1b9fe376b9cdb9fa32c3f85ca25f5a5372046
./engine/tests/corpus/76db47aeb9786862f05f53d03d75066b18535790
./engine/tests/corpus/e157395add1c77749dbd64cc49d149af0f2af247
./engine/tests/corpus/e1ac9dd524558d274f1dd5e4bceee31e999f8490
./engine/tests/corpus/510ece4df9175496c1b04ea9e98df03e78cc1c62
./engine/tests/corpus/f1f88abe04419848607801089002f2a7631acd7a
./engine/tests/corpus/aab94b2dffdd3aa01dd5d1e47952257105e4c77e
./engine/tests/corpus/7a3865e34b943ac8ce47915e640892f5bf108ace
./engine/tests/corpus/9ad1910988017ce5567a82e58cbaa3c16766b428
./engine/tests/corpus/9e6610e45b3184f7eb6dfaec67445aaf05648720
./engine/tests/corpus/ea0ae4faec14984da7a06d5074107012413501c7
./engine/tests/corpus/1d7b5e3d3826ef115f15b6af00ccb21cd0747f54
./engine/tests/corpus/b411abd497a57cc51b004bee0c056aaafe1e9818
./engine/tests/corpus/94fb751f5a1715e86f74c94ec6f7fd4490b8259b
./engine/tests/corpus/5b3f93380d2138de24b9f3a98ae00e9e1b155233
./engine/tests/corpus/45625a8cf730d76d90f712b38b9db2988befd76a
./engine/tests/corpus/26d3b6a14c349d2dc5e1807123b99043569d0007
./engine/tests/corpus/beab7c168734d5934496db4fa9d8ef053e9cd4a0
./engine/tests/corpus/01cb495456e75d637330f773d7e0650532c1a8fc
./engine/tests/corpus/0c3a18cfefa3c7bf7abf0d07f91c8a97a15c8389
./engine/tests/corpus/da9b75e4948ae86793db7c28e833f8a6a97bc605
./engine/tests/corpus/59fdcceb832ca3f40e6a027414d7d4342ce11847
./engine/tests/corpus/875a80a29cbe71d2cd8be409fbaf5457310c4b50
./engine/tests/corpus/5dce853fbdacf29dae775954f6237d2b53bc0e96
./engine/tests/corpus/69071d809ba50fbbe7fa0a3f7e4c81617cc75fdd
./engine/tests/corpus/a0c304db0caa6925b1194a3e33492567ee909245
./engine/tests/corpus/0a8b096923dfd7461266c0b24deb48392017d514
./engine/tests/corpus/37e1fde054ca38c19a5fce19e1b92357d39ee378
./engine/tests/corpus/5e6146ad1b9690095d0e7eb4e208a1043a7a2a03
./engine/tests/corpus/943ae33c8c93cba9009b7cb8e46591f7a4d17be2
./engine/tests/corpus/924218086a5405d72cd2a44c0b7e59f299525b70
./engine/tests/corpus/d6448527e45f01c7b4fd26cf3bfac04764cf26c6
./engine/tests/corpus/7b8b6e5263750f937d52d0fede50bd87b885d44b
./engine/tests/corpus/0b56bb06f51b1472537ddc8bb0e82fb6278b7e89
./engine/tests/corpus/8fc3a662f3c12d4c0bb2ea7713563e5f0a3743eb
./engine/tests/corpus/6b5f0accfcf06e2992c69c5a69fa6d4bffafa9b2
./engine/tests/corpus/0110a4b9eae02b3486c2f15621cb339a952b5e15
./engine/tests/corpus/cfdeb87c6740ec70bb76e4f4c160dfd175b9174c
./engine/tests/corpus/52ca7f6d018b4edc053110ce3a347dbd92c078cd
./engine/tests/corpus/9cf756591b6c4968f1ef60130ce3e436a65425a7
./engine/tests/corpus/4f90df949c760a2ec55bc34213001d96f055631e
./engine/tests/corpus/b928a7859f1cd2712d06d966c27c6e04d31b040d
./engine/tests/corpus/8f292bf117c1ad0e956dbf5214ce8691f8094a95
./engine/tests/corpus/53e12ea636123bb63bb478a34d597705177a4dc9
./engine/tests/corpus/a838d2b4467b396d0e4fb06ea0903d32a26b24bd
./engine/tests/corpus/c56db5bfa5705374ee7e6b1d91b0de10eeb761a6
./engine/tests/corpus/d0fbdf9a0de52ee686cd2093a988800890912aa3
./engine/tests/corpus/0f4e3d560b689c277553dcbe16ed928fb770bfce
./engine/tests/corpus/54b9d8e7716b6175806aacde265f14e8065747d6
./engine/tests/corpus/9aab99c68e0795b27844ac6782bae9e3e11d815e
./engine/tests/corpus/31eef7f16286c68b72582cbbb3b332d757d5c0f3
./engine/tests/corpus/fd63c93695386bf5155e6037841ec5dd5c99c951
./engine/tests/corpus/cea1cc7d03cfb785dc7334efd412699d13abd91b
./engine/tests/corpus/d67c6510a6cb2758d84eb14448339c9fb3cd072f
./engine/tests/corpus/e000fa871e8a78a2ee8de172a3de84c183754e9b
./engine/tests/corpus/c3fd8e60f784adb8036ba6e09082a91511394344
./engine/tests/corpus/de45319f9cbd15b947110154a8733d8de3bca334
./engine/tests/corpus/81c59a1b4841ff03d1edc2877d30d542f101ac55
./engine/tests/corpus/7497b85c765d91abc779ecb9354fbb21644f4ffc
./engine/tests/corpus/d7f891893e179a15b4d081139ab8f27c748d1871
./engine/tests/corpus/0c47c9b593e0d64d5d121bcc8d9ea4e903756389
./engine/tests/corpus/658a2925634894ee427022f45f86997fbf620bed
./engine/tests/corpus/1e6b5290335f4f74fad930212d827b09e83d0adc
./engine/tests/corpus/7f828daf553f03c79d1f1c0e84fcd3c2e8fa5de8
./engine/tests/corpus/99a6e46d05ee5c8161f076ecdfb6d0eaf36818dd
./engine/tests/corpus/5a4dbfa9a8eb0cc38e8bfeb1f7d43a66e0bebad9
./engine/tests/corpus/82a3833a89ffe79e2edf2ff6419c8caea162ba44
./engine/tests/corpus/b0cc944fa6157cb6b2180d69c7381d505d66b3a6
./engine/tests/corpus/a6f886e507448ef31c33b01735b50c9f7f17847f
./engine/tests/corpus/1c31f145b63315f37007c06f6f4d4f17510735b3
./engine/tests/corpus/c172171916ef0632970de7852aa6451fdf0210f3
./engine/tests/corpus/d766335482740c4ebdb6ec1f1ca8f4ef11ab59ed
./engine/tests/corpus/1dfa9a8a3731e1946bc941a0ceefce5838a3e233
./engine/tests/corpus/b75cc6e4ebabdb34a83371e6b8eb755da49a680e
./engine/tests/corpus/d0ac2202c5a24976648284a57654d16c33361ba1
./engine/tests/corpus/54bff6b8bb53ecc6c6b78aa6a805ac3ff5764203
./engine/tests/corpus/3a25c5fc729bb743b1588755c60fac8707604a29
./engine/tests/corpus/7b1050b2e3806b0eae9f813639ecfda0f416ca61
./engine/tests/corpus/b4ae2b5f1ae3d0278173790ffa5f2f5a2052feec
./engine/tests/corpus/4fedaf5126f1aec4907bccfb96250c74da05fe87
./engine/tests/corpus/1bbe1b3153deb5271f9294d20b07443737156812
./engine/tests/corpus/3b75e3a336297939bb005db550b51d6421e1ff22
./engine/tests/corpus/9e65c92a582a89a6bb8b6bae2c036a7c54652644
./engine/tests/corpus/638259451aa8782a6a682dc5d61cef6b4298d020
./engine/tests/corpus/d80c689c7f289d1dfc308fadc43da4a166e41398
./engine/tests/corpus/23aa31c77988e44b4f5b70f0ecc98f21cb72ead2
./engine/tests/corpus/50ac396ed2912d10e08380cda9b97f691c35ff54
./engine/tests/corpus/3c4ddafbf9871367117f8a3e532b2f22109374e5
./engine/tests/corpus/9f90e7a48c80d82ff68a9c5d1f6693d1f46b686e
./engine/tests/corpus/1b8fbd7ecb9a60e377eb8cdc361dbbb4e790ebbf
./engine/tests/corpus/4027acec1e6f021dcac0b89effb88cb45ca6bd1a
./engine/tests/corpus/0417194cb65e4c22a7142a4849cb194d73e70efc
./engine/tests/corpus/0f84825fd5151bb7f91df3fba644dc7c483f6c72
./engine/tests/corpus/48b445ffd0fcd28f8ba3840171440345da429703
./engine/tests/corpus/032745e626b3d0ef531097cac129205039db3f6d
./engine/tests/corpus/d1f7d67ff6116a0b7619e83e401e69437cb3002d
./engine/tests/corpus/0921f036558e792e7c2af339690c15007a712bb9
./engine/tests/corpus/b9189239c2c082d93472fac86b6e312eb2da3a85
./engine/tests/corpus/a3388658156773f7e19e7ee31cbe85ab80a28175
./engine/tests/corpus/fddf9b73e09cc233cdd8be7d325d36fab1cc24cb
./engine/tests/corpus/4404efd681341f0ad4c0e0daaaa6ba9bf5007607
./engine/tests/corpus/3636788abc389a2a9af65a2c8d8700b60aa8ef60
./engine/tests/corpus/77b49bddb1dff129f7e941ca711cbb47961a301b
./engine/tests/corpus/7c82ba366ce64aab031096d942131c9c5b79895f
./engine/tests/corpus/209505b05824434dde2490e46080ab3ef1c7d597
./engine/tests/corpus/e0e87c726ce06b25f1c6fe964fb96a6f7c728162
./engine/tests/corpus/c8a13e840b0b265d13f1312fe73bb25c670371db
./engine/tests/corpus/bc232f7a0c820a8734c39d7590f7021fb5eb068f
./engine/tests/corpus/ad51190c317d91599d68c0e68fe6606e8fe13cc2
./engine/tests/corpus/6da0a9551dbe097fbddf9225ec7ac534d346dc98
./engine/tests/corpus/5420a8b3ee1ada2a222fa7482678ef4a4bcf8bef
./engine/tests/corpus/445cbb0733354e19ad526ad20e1e00d086e4a9ad
./engine/tests/corpus/4e0f4bc4f841f62f6aa8df586ae70d8dd7bfdb0b
./engine/tests/corpus/eb37225c01bb2259d8641e11dfc8d26030243721
./engine/tests/corpus/3f492899cee0755a7cd7627b77093162b88a9e96
./engine/tests/corpus/8b4e7c567ef23fa5dd63c22d813f9b27f0f5b2dc
./engine/tests/corpus/584f32e70bc7daa8dd5b8aac4f237d671209b730
./engine/tests/corpus/813cd7e7babf597cb34a600dc408a5aacb3ed8b9
./engine/tests/corpus/dc93d80c1fcce4527a0823eecae79417609e3142
./engine/tests/corpus/49be8f3f0e8c0cf6a490c39bfc4e14fd11ae7c94
./engine/tests/corpus/f15ea494890ea2e63da7f27dac8d64864ba476ca
./engine/tests/corpus/16ad089859a6a16204b9c743578227596b97f887
./engine/tests/corpus/b5821249fc7ebd77b675db36106f7dd3f0d8ab36
./engine/tests/corpus/4f73aee48d5c1cc58cd6b9c157a98127c661c920
./engine/tests/corpus/a459001b20b1c8df4ff7cc0616328c6241db189e
./engine/tests/corpus/718da5aa1f46b42bf24c9038cb65d74f260fc29e
./engine/tests/corpus/332bb5151f0eebdb7ca140cece28dd86f99a5d7a
./engine/tests/corpus/c9e07a1b8530ea6d217a4ffa5e54f3b13b922aca
./engine/tests/corpus/229b6892d6a0f26927861d61a20f9923b81eb6a4
./engine/tests/corpus/e6458a735baa013f514a0abfa80be44c36671e9d
./engine/tests/corpus/749392cbfe74e1361bd158b7a6bb7f6f06d48555
./engine/tests/corpus/86b0dc22e2766ce908c9d27118be5a5a3a7951b6
./engine/tests/corpus/22c1214e2c46da46aecec9bcd58b574350bfa8a0
./engine/tests/corpus/4f0f9a920e3d7242c66460b45ba783407b6c0d60
./engine/tests/corpus/c1352b42358138295ae515fbe4706cd66f86acad
./engine/tests/corpus/109eca4eddfbb1590dbb9847863e797cf1d57567
./engine/tests/corpus/77cef496e2e20894d92286296c82fc69afb0c504
./engine/tests/corpus/688737cfcfe0ab1f3da0f88b0bcdbceb4370cc22
./engine/tests/corpus/50958b6e0bc6022e540fbad6e07f659664c0c6a3
./engine/tests/corpus/90ac15e3618b7d5f745685d6ebd8e66b7d525854
./engine/tests/corpus/617e6700935cc435c68f6ac412147c10c1c361c5
./engine/tests/corpus/dc9d08ef0b6e56e4128d82d35948848f70432ae8
./engine/tests/corpus/8be7e7e0719bf90dde0c1f1da402b76558e58320
./engine/tests/corpus/2cd6dd271a7db1e9f21f17c2fb132cfa971f5072
./engine/tests/corpus/f75a0e79b08ed1cb90dd2b7fd33bcb151e89d896
./engine/tests/corpus/57cf671a644cdc7eecdc33797a3c77fb57064e18
./engine/tests/corpus/0b26edbf27addd5f17db631618e4662e29a3c0fd
./engine/tests/corpus/326f73226fe1a30498012f0fb7c24beaf168cecf
./engine/tests/corpus/8742f1e61e50a3a8d94022b86c65746013ab663b
./engine/tests/corpus/1300e3122976c687de0ec29f32fca94cf0c13135
./engine/tests/corpus/f81abe0629a2a91a57e87056a0a9a11182fa84dd
./engine/tests/corpus/423f4a408c03ccb570b9b889db6d09277745d7d6
./engine/tests/corpus/dce87ec118a95df6aee1a46abcae18c5b8d33de4
./engine/tests/corpus/72f33803a0e0200d3f863f0f70e36e20f005a552
./engine/tests/corpus/b82c7d1b96cc9ee00b7501edfefaef3886ef2a8f
./engine/tests/corpus/515b1e482392a9fcdf031802f8ef8808b36aaa07
./engine/tests/corpus/2bff3e758ba0e035722db16c628f6c6dcc211ece
./engine/tests/corpus/2baf5cc916d54696875d40264b424f029427c9b0
./engine/tests/corpus/f9579e900408256add52f0642d0770826f4f9210
./engine/tests/corpus/e62318929713d5b3516f48b6cd6aaf835a9d276a
./engine/tests/corpus/86be587ae4d8d5b2a53e263feafd7649ebd5c54b
./engine/tests/corpus/b9500123f90ca085afc620802228a26e9814da96
./engine/tests/corpus/2dfe6fefc4e2e50611e17aec399c9b51afc52375
./engine/tests/corpus/f5e3fead8d35e0c5c7de34ebc81c89038e22ff4c
./engine/tests/corpus/744fe700af3ac6ba89369fd09e8de7837b6f5aa6
./engine/tests/corpus/4a80ce820f4650e27d53abcbf90cd89e4751879f
./engine/tests/corpus/6cda4befa4cb91603e7f5f5595b61fe58675f3f3
./engine/tests/corpus/b9c00942a7cd9e6be60030a77429b170cacd0b84
./engine/tests/corpus/d9d002c625813e0669230eafb80da45afc3ef206
./engine/tests/corpus/fbbc6b7fff93a88f79742b19befc23221aeaae28
./engine/tests/corpus/0a1b4201066c8522e69e44045d1d84745fc5d659
./engine/tests/corpus/34411fb36801ac3181269dc9e0e3a818428f7072
./engine/tests/corpus/c3fdd88a9529529266c0794be8c3cf9d7014f8ab
./engine/tests/corpus/fd691f28504bf472efa4dfef82bff7c08071641f
./engine/tests/corpus/16e8588bd2f20f43ce21513f1b5dd96579ea48a6
./engine/tests/corpus/a89ad6e4f8303dff7fe1cca1965131d4eb76f0c7
./engine/tests/corpus/39d964fe80aa9f25560f13b182fd5602b2e9ff91
./engine/tests/corpus/3c86fdffc931d9ba0a60496f4cd1440f85eb904a
./engine/tests/corpus/c78cf2a142ab879a0bac3b629da7495e4e3df651
./engine/tests/corpus/e1f8af2d93ef70ad2a376f0dceb7a3aff08b597c
./engine/tests/corpus/ee77b2e6824df65bcc3e68e4080146f15ee51f17
./engine/tests/corpus/7aae260513d21fc523fb66b40ddccb5377874b69
./engine/tests/corpus/f882b0f058f1a92a76bd875436b2b010b74e1fd7
./engine/tests/corpus/c728b4acb5f4582335e7d3f87995967874867189
./engine/tests/corpus/2684fbb1175d6049f23c4830f80511a700fe47c2
./engine/tests/corpus/ae146a2da127769158359273d240ba10af9ead4a
./engine/tests/corpus/3f99d84fcd90d4e2ae2e5d31b7147f8c8f51e9a2
./engine/tests/corpus/25e4314653bf87c45a9a68a2fabb2b0c23ac92e3
./engine/tests/corpus/d4310eebd1ba55ec738c35cacc3535d3940ff523
./engine/tests/corpus/644107151086a1c2589874a5ee31e37d1ab59dbc
./engine/tests/corpus/d2d9ff4855c099eb53fb681fc17edd6a328d752d
./engine/tests/corpus/abd50aa5a63dff1ae46c7882b37421bb68a260d4
./engine/tests/corpus/2737403a60e2f6e78057353d5f986f537dd1249a
./engine/tests/corpus/a5b74bf2b1b52a9242e628e1686272003db66491
./engine/tests/corpus/781b1550bc8fe9fd09e4dadba76fdff8b1241e25
./engine/tests/corpus/a95804ee9d6a352ff2168c71dc785a2570150501
./engine/tests/corpus/45f6d204894cedf9a293d22de6e949c6eb6dfa1b
./engine/tests/corpus/2d4193d63ccb177cb618d4414d384733135f5a46
./engine/tests/corpus/3a47a526a09902d2e4e21379d1dbdf0bc1303f1e
./engine/tests/corpus/b42f99a50155ea90d61f884b10ac1d1779e041bf
./engine/tests/corpus/49c9f432c9a66badd5e2b32e41a6e3c8b44963f4
./engine/tests/corpus/ea65c794ecf372716e1e1a258864ebb093ef8a1a
./engine/tests/corpus/8cf9eb4d584721acb1c45e5b693b52f53ff7b6f4
./engine/tests/corpus/6ae1cf59e1a7f66722ec2bbbda984e26c6c5e43b
./engine/tests/corpus/4d841bccece0a965fcfaaa5366fd5572370fc34f
./engine/tests/corpus/e958441a81c7da173dde7aba9426945b99dbe842
./engine/tests/corpus/37f1c2aae11010845e5be14dc9c97e94c8ed8028
./engine/tests/corpus/c23ffadaef2b298c392842e6ea85250ca26078db
./engine/tests/corpus/726fcc75f2c52b1cca8cb00255ee196540a91b03
./engine/tests/corpus/2e86b2ef8d52cc475eab60f939dbc8f0aee06c9d
./engine/tests/corpus/10a42f2fe671c3935b13a76c0795ad582ad7147a
./engine/tests/corpus/733b53dceb302d9ada6be9a6d05c7d6dda157733
./engine/tests/corpus/7eacaf756a2bb01cee4cab8e51350da50afb1c4e
./engine/tests/corpus/bf4b871350f8fa13948fbca8a09df7a922abaf97
./engine/tests/corpus/47175a397cff1c36189d39b51b52ea4134bd3971
./engine/tests/corpus/820f0cafea81cd2dd295eaeab317967d2c963182
./engine/tests/corpus/33af26582e9d7cc2ed4a512f198b6724c1011f24
./engine/tests/corpus/552a93c3086880d297d97e09a3564d293b7af78e
./engine/tests/corpus/23d13fdb39aaebea05f615438d59986f679a9205
./engine/tests/corpus/77b648759200d73577d95882460e51cba18ce62e
./engine/tests/corpus/d0d66ae09f02159f4cca487036c29cb0e8efec23
./engine/tests/corpus/ce0cf4ae2a95863ab1b0f1ef1be6d02e4871389e
./engine/tests/corpus/820d12ac47c075f87cc99a10918bbbd90dc9ad75
./engine/tests/corpus/2db28ad1d39080a9115434c36b3ebb344a08d832
./engine/tests/corpus/2fee04ef388c6fca5b9656e4b3105a26aa27099f
./engine/tests/corpus/815fef7f7ff97037f5c1bc3ff8735e6bd2b7b09e
./engine/tests/corpus/0d46f1352347db98bf390d92674ae28eb7c0f969
./engine/tests/corpus/a40e2c85c2aab00030faef4159d91558851cb35d
./engine/tests/corpus/31be48f7cb4972612c3b2ae64bc80435babd748d
./engine/tests/corpus/6b239de6208871ee1fe6456feab6553094e91275
./engine/tests/corpus/0e239128adb4d2f21f5e9299808c253e99aff2b2
./engine/tests/corpus/77c5fcfd38fa92841d5567998a5c63fb95cf469b
./engine/tests/corpus/50f426983028f37b0cb98c6e91eda5553a8081cb
./engine/tests/corpus/6ad6c8b51624a20cbcccb480a2a5c17f71d5f5ff
./engine/tests/corpus/0afc6d53ae1842c19878871b5c18b5e40f8db0d1
./engine/tests/corpus/cebf1438159b0c1425bbcda19240db295dbd8437
./engine/tests/corpus/6caac25fbe61cc6b475dc0584a710863e0bf3201
./engine/tests/corpus/46f3456344dd43c1e9e7debd2780bad71a6c624b
./engine/tests/corpus/cb46e4ce13142b340515e047ba12532e2c6a15c4
./engine/tests/corpus/a54a7f7405d17fb6be37572a4cd983843aabee7b
./engine/tests/corpus/71b946bcc9fd57ae9531ac5bdcfa157e055f0b17
./engine/tests/corpus/2ce7082b1f7570addc100a45043f45ef894fea0c
./engine/tests/corpus/d856648c3410e4d391154d6c5f73debc76aefeb5
./engine/tests/corpus/10914839f6377b5bc0576c9b9f1dc4b5bff3347b
./engine/tests/corpus/33c560b018998ca6426c080620325901951bd9bc
./engine/tests/corpus/d0fb795016c1e0c476dbaef46303ea18ef23b354
./engine/tests/corpus/0b545ca6a3b294959723e677880cd3862b063bfe
./engine/tests/corpus/6f52fbcc33c67eade54be63ae9ebe0ed62b78c3b
./engine/tests/corpus/0d9f96f9e693283dce2cef9d3fdfc7550fa2b6b5
./engine/tests/corpus/341e37577f9e6866f76c80f377578460f62b59cf
./engine/tests/corpus/b3ea1920d1ea967c38ed88d92ba3353eec52a149
./engine/tests/corpus/f8561604b3474bba9684f05264183f3791736f28
./engine/tests/corpus/20e5432ce0abeb9f6b5b0e14cc685b06b26f38db
./engine/tests/corpus/7745998b79dde16388c0f51cf3626eed9c6a42b7
./engine/tests/corpus/6180336c0de86f0800e245888205369cfeee9413
./engine/tests/corpus/e5f8cad5879af5e5315bec1b6a996a92dc52b9c4
./engine/tests/corpus/12f715a04ce697a971c1bf53481580cbe4857940
./engine/tests/corpus/6ee0a324f76e2d3897e6abd027ca9aa543ef8458
./engine/tests/corpus/441d876c458ab0d3adbaabc9b9a530db7725d18c
./engine/tests/corpus/e78f43db4940f5091397847e77f56992093e1ba9
./engine/tests/corpus/62247d43348b9b59a581d9e60c457b5057bac31c
./engine/tests/corpus/823f936ac55cf5f017e96182764cfd9b727faedb
./engine/tests/corpus/29264abe63366f8892c0111310fabad883f8e548
./engine/tests/corpus/d90f4afb7bd1d352dbf1f82c6f38e6bb20b8bb0f
./engine/tests/corpus/bbd13497c977be203007908e4db4e41952979a06
./engine/tests/corpus/b89e3b4d57ab30ca904da9c2baabfb6a08306b52
./engine/tests/corpus/0766883b6fcc5f0427ca4e494e1038e33db479cb
./engine/tests/corpus/b673055c8bfdf7148d550ce9cb672aa1d9164d5b
./engine/tests/corpus/63d4ccf14f7066bd427b43a381022ad076019073
./engine/tests/corpus/c649b873fbc33623c1e5dc117d1be660f1a3f807
./engine/tests/corpus/df3d0fdd6665a96ea9c25feb4b384513c7ed7a21
./engine/tests/corpus/fa3edf1472fccdaeae233ed6431856212b15c2c5
./engine/tests/corpus/b30950c820436bb97e6c1832ca0d3629d9fc4037
./engine/tests/corpus/206dfda5d7272f9d65c3f3b0a147a50af339069b
./engine/tests/corpus/1e0b9d28098411c14a33442f0edf1630a8be6f9f
./engine/tests/corpus/f3222eedc5cc8769395ff21159d81dfa3440cf67
./engine/tests/corpus/5ddbbd77a5cc7ce41ded37fabb1fe205ef9d84d6
./engine/tests/corpus/cadba863ea1cc2a294fabcea98a24530f283024c
./engine/tests/corpus/9b5765acfff54aa640374843827c365a8570919a
./engine/tests/corpus/0437560883db15369a07ff1ddcaa1c771e5c7689
./engine/tests/corpus/2f9576d06a82465c245b28fec37754a8ee788737
./engine/tests/corpus/63eb0970c24af8ebca92c4e24f6138d0e029fd53
./engine/tests/corpus/056019ea7a3bf266e7b25c8d084373105e41be0d
./engine/tests/corpus/b63f53dce5607d0a56443d85dfb6879ff781a4f3
./engine/tests/corpus/6760fb168e6d7ea4b49006a0dd2b65037dc9a1f7
./engine/tests/corpus/9a5c7ab03754dbf8b36893046679f46827839b41
./engine/tests/corpus/9d80dae6aa4a3812fed6228fe8965cda233c8ef8
./engine/tests/corpus/6a51b9100b97b075fc79b9e1d85f087dddf756c1
./engine/tests/corpus/16280ac7157fedbc453b1dcd3535ec79b6b6bdcd
./engine/tests/corpus/df018efb54aa9f55f6c61ef471a4b4c362cef3cc
./engine/tests/corpus/733cdbf42311257b5b29d6312952c9992eaa584a
./engine/tests/corpus/7bb4e9de606620808b256b3f73691a98a65e3553
./engine/tests/corpus/1fea95273230a61fedda0daf77418179e5e424ad
./engine/tests/corpus/286d67275084ad9c6b49f5dfbfc9017d22ad6ca3
./engine/tests/corpus/95c677af10505a23029c255e8d87d111d6caf312
./engine/tests/corpus/c5e69f16b0ce91323baa7a8b1ce473acba61633e
./engine/tests/corpus/e41e0bc81a78a1961460828d472cfb1c1dc632f0
./engine/tests/corpus/095bdc2b286e9f63e463d3afd17e8ffc7a35b817
./engine/tests/corpus/7595ed93614c62bfcd0c92f27884a21dfb210c74
./engine/tests/corpus/75cbba35a4b8a67f8b9e91a2759b48bb471ff560
./engine/tests/corpus/6b88e61a313d9155326c5622c26feedad64cdcfb
./engine/tests/corpus/e4e1016fb54c6fae1175e0f12f82099a7ccc1b52
./engine/tests/corpus/20e7bd30fa761129b75cd285498a5a6114b07693
./engine/tests/corpus/556eea9c3d9d2f49944f8e841305392f19daf20a
./engine/tests/corpus/48b6015b29bddcb8ef205a74631547d699d50f29
./engine/tests/corpus/0710fbf3e73c87389367ab6c9ec419a7502f4ede
./engine/tests/corpus/41a0074e091a0ab373b995af786b8901cdf773af
./engine/tests/corpus/773d5e5874406fc303983784bea3f9bdc87cdad8
./engine/tests/corpus/1086dab82ea0eec3bcbc8e82ec65b4c7255f5d3e
./engine/tests/corpus/144bae2ea4ad3ad91eb9b9bafa453eb235517bdf
./engine/tests/corpus/b4049d10db6a653f1cfe80ae6cfbb8113b760373
./engine/tests/corpus/4ffbf53853b03ee5bc063ff52018bccada56325a
./engine/tests/corpus/3b87fb5a84a952eb413e3f3abce985275c769752
./engine/tests/corpus/6f2bc65b4a9525d8e5fca4f892dc763a3ba57ee7
./engine/tests/corpus/48be1cb389db2b0d59e2abc7e01a8554d5471b1d
./engine/tests/corpus/7901efed39dba8bb4a6fb73fa7221f6b9c92413f
./engine/tests/corpus/72aa45eb44c20155cb48e89e7e4d28c4430cc107
./engine/tests/corpus/3e6f928523f2c5798dd55b1f3cd5ef1718769443
./engine/tests/corpus/c247b958ed21a40bf8bc5c9a998ad41926b9bec4
./engine/tests/corpus/ae2dec7c7e3492477b49a7e518a72a29f252b3bf
./engine/tests/corpus/951fba5f44e20717b09a8a27c7280ba93102c0ae
./engine/tests/corpus/d2f769addd91b81d5a721bbbfda8d8eaf6676304
./engine/tests/corpus/3eca1c55d0dc9cafa421264d7cae16edc7551aeb
./engine/tests/corpus/1564a890ed08112d6d2d25d61af2a9c6cad0b04f
./engine/tests/corpus/2f64e0b51f88d3381308909967e33fea59268263
./engine/tests/corpus/b6a3bb5e9dd317f6d013116189aaf7dc16ad424c
./engine/tests/corpus/4e1e61cb35c70920c890f30b1b5e22db86c8ef9b
./engine/tests/corpus/4ebcf25fe4f5abee8f701f6ef9dd7acf9af9d2c1
./engine/tests/corpus/6700ed95316ae0842cbda811bc340da4668c1079
./engine/tests/corpus/26aae09f6c7c09868ac6329e4c7e8eace5458961
./engine/tests/corpus/f0eba857b43c17a41b5f5b42f14ea6ec3ab24e0d
./engine/tests/corpus/1148a5d01cf8a4719f6d6bf287a143acef368725
./engine/tests/corpus/13bdfca1ad7747b32ddb734a8e680f0a347c1aed
./engine/tests/corpus/3cee811b47a35d041ebc3d01b937909f427586da
./engine/tests/corpus/ffeca4b3bd0278b3dcdb143e0852ea5ab12a65f3
./engine/tests/corpus/d25740acc2d06644b2fb8d4f8b6ae52ad2e8cd94
./engine/tests/corpus/21b1900f6a887b33b5dac0ece80ae98efb74a0a9
./engine/tests/corpus/90736dedf5c4f52f837e11aec6ce31d98535c543
./engine/tests/corpus/fbccb13b03a54bc36d0e34aae6b45bd4f6750bdd
./engine/tests/corpus/7f0d1dc75cb11d8b24a1a1296b3a5e9564c76db2
./engine/tests/corpus/f2455e4e629b2011f4700140ccd39c11dcffac61
./engine/tests/corpus/44aa5d17068a252697084e7979e900d850d6ab64
./engine/tests/corpus/f26dab8b0c44f2f2ddfdf8441b5c19ee33b7f056
./engine/tests/corpus/b8bab429631c8eeb530edb4b59c72bd26003ad22
./engine/tests/corpus/0228b2d7fb30ce8d8ac48160733255ce2a03876f
./engine/tests/corpus/81b59f1de22936ca4004f84e6dc7cf34f47758c6
./engine/tests/corpus/a4b233ed63b06b9bb484a3720e2657a6728bc0ae
./engine/tests/corpus/769cc979e33e353fbcbd8082890e9c107a962392
./engine/tests/corpus/6fe81bd52c25428c60b28f914b47da241c55b176
./engine/tests/corpus/abd1301a2f5a7df014ab662b22c3dc653fc5eaa7
./engine/tests/corpus/27649c121b8cf48352fdcc64031f469179118ec7
./engine/tests/corpus/8750e94d18c38a90bc37fd6ba8dbffedbbe4bfc9
./engine/tests/corpus/7d65d3f28e54ed52e54eb4373853fef1f35a3601
./engine/tests/corpus/4caf3d85e71566eb3a8ab838605765bb1a6e202f
./engine/tests/corpus/db44cbe3240e0a7cf238c6ee589e4055737fd0c2
./engine/tests/corpus/300025682c2b21fd24f33d05cfcb1875a943ca6f
./engine/tests/corpus/17d8805e124fe913d4162c71bffa4afc16d13484
./engine/tests/corpus/0adf9ca8aa9c11ddcd43b67bb75412db3adfa81f
./engine/tests/corpus/67e317e08b11f1f34d6c6473c159439e4ddbd3be
./engine/tests/corpus/cd721a2b4faff4e8b922cf8bff9c6f18e8be2b57
./engine/tests/corpus/731eaf0fa0b0bc5034473749398a87272b6e6782
./engine/tests/corpus/952c7acc1f3250356c282540f2d281bdd270ca90
./engine/tests/corpus/8bdc8a94d6beb358b79493ef490528b910dd9b49
./engine/tests/corpus/f960c12f81d320a7f3b2517acf874ad4db9ed1d5
./engine/tests/corpus/904abd01b4c65b177ecbb82d81c2bc422c73e0d6
./engine/tests/corpus/bf040f65f7ee90527cf882d328c1752bff1287d3
./engine/tests/corpus/83d1c45fe6e48e3105c908f4d1eee6c267d47a9f
./engine/tests/corpus/9941900c1057bcdb400749357d999bc7ac56a0a9
./engine/tests/corpus/c63ed8a09484141648e8398933b94cf5120a52f8
./engine/tests/corpus/26ac7607699ba8fb2937533c5ec0debc2de08c6c
./engine/tests/corpus/8d2018ceaaca223ab5131af6c70b0c5d1ecc9d53
./engine/tests/corpus/819362a1d7440222c3741811dc7d5f3a768fdd05
./engine/tests/corpus/bb5ece8c1029bf9d720617b0368ec0c83c9d766b
./engine/tests/corpus/97bd218a8648fe63bfb2fc186db7623a11f079cb
./engine/tests/corpus/d82bd7799f0ff92a1468559877983c2a2921cc75
./engine/tests/corpus/c8f34fcbdaebca9afd3220780db0beca9e2ffde7
./engine/tests/corpus/677ae0f10d5cf5f355398a529b7c1e03de685f42
./engine/tests/corpus/9cc41dfcb427bcd65d4f69fa3829ff794e01b785
./engine/tests/corpus/2ef56e92f3d8b537f9926700727a274ea52d3e7d
./engine/tests/corpus/ec5a92bc89a603278ad96c3fbe3bd044d95b8304
./engine/tests/corpus/5fae9f7b37c9580edd844692ff0b2785076331e3
./engine/tests/corpus/c76d84b4fb81686f70ab8da382f6eb39f0b09092
./engine/tests/corpus/7aa1d513aa24c9032c1371e536b97804fad7759a
./engine/tests/corpus/d402d7e9ba8a8e2743ec7bc7b88a8f124e706cf7
./engine/tests/corpus/46ab7705f757e8fd0d3a58b96aa602b98e85b920
./engine/tests/corpus/ab36e11a2c7323f03c28af5351f1b73cbf35f5ef
./engine/tests/corpus/6879973bb4043777bb617262e76741f0eddab808
./engine/tests/corpus/621f48c5442337cfa3acbf64b492bd9f934124e6
./engine/tests/corpus/d246d668cd9403fef1631a5aabd4e52a9d6ae78b
./engine/tests/corpus/609da744cfa22604994a839f7c7e3461283dd584
./engine/tests/corpus/8083da0c7e64a3b19b3521079aefdfbb7885330f
./engine/tests/corpus/096c86cc55004681fad90a3bc1a515d027c5fc8b
./engine/tests/corpus/cf5494b4bf7c0922263380a2ec472a377148055c
./engine/tests/corpus/623b0433c7fb552d04cd31555e601bcac2f30e76
./engine/tests/corpus/abb3a510ff74121bbba909cfb8d9fe825ac4f6a2
./engine/tests/corpus/5ba93c9db0cff93f52b521d7420e43f6eda2784f
./engine/tests/corpus/1e8a72e9ff4227c5ba94637d70ed83b53f451e4c
./engine/tests/corpus/6157c2acb49f2f076e77e402ee5fab4c7d153759
./engine/tests/corpus/bcab8cf4b596b07236090793599db16d9ec86dce
./engine/tests/corpus/ae6b95751f39a46c364deb29b906f8d438257d7d
./engine/tests/corpus/822895db52dcd31156ca586f2ff222a69d673e5e
./engine/tests/corpus/ba6b4870fee171d72ac51bd0fa9c86978a5aee7e
./engine/tests/corpus/9387e27a0460153cb5dff3e378f5acb9d94ee200
./engine/tests/corpus/9b5e267014d729c41d7c15f010f37e994a7ae4c3
./engine/tests/corpus/c7329f2d5d29f230444f7f0a12cc41d98540e3cc
./engine/tests/corpus/4bb0847b7f2bd600b65e0574c6b73705fa6c862c
./engine/tests/corpus/b3adaf2408af3e844272895c5e4dd02f0f8e07f5
./engine/tests/corpus/3c8f7ae480e9fcc59931ae767754c80b10f07ea7
./engine/tests/corpus/73eef78d459e6bcab988be18e356df6e16d494bf
./engine/tests/corpus/80a29fe9a55d4433039a3ad2e980b373fdfc2349
./engine/tests/corpus/26e408d2e0256171c0cd3b2743dd2dc9411feeac
./engine/tests/corpus/54a7ddcab3ba916df4776a0205951231f21c4d59
./engine/tests/corpus/e7ec23628b1cc7f8869423a6dd39d36e4effe30a
./engine/tests/corpus/e12894f7e7f55cba4bb68c36b07fbf72399118b4
./engine/tests/corpus/22a838d89b371b645922ea516b06c70e290b1e43
./engine/tests/corpus/9a229d1073faefb18927ee7679104f3c5fdfaf9c
./engine/tests/corpus/1b281b1c41710bcd80e60a4be5ffbb7548e92023
./engine/tests/corpus/dbc0fad0652e7662c63509c6aa9159f3bba5427b
./engine/tests/corpus/ea8a5a8bc124f42e4a5b6be4ba921548312b5f70
./engine/tests/corpus/d0263cc2cc7cdccef907d8524419c30f6aa4b624
./engine/tests/corpus/8af7f7c1e910e15b3f153a53e962d3d6d0dfccd7
./engine/tests/corpus/a72fae5c7d2b191d1ec22ba986639c2e45f8a47c
./engine/tests/corpus/5138981d77e45237efcb25c24f6d1bc74cfba83a
./engine/tests/corpus/10d19c6fa41208a779030ca321f863362972313a
./engine/tests/corpus/76d8554e069c969831f7a3446d584dea67bed113
./engine/tests/corpus/9b2b11b9ae1efb4eefa1b717179db6d231115496
./engine/tests/corpus/c6dd824fb7ebb15c5788d0cf24d42a5e2c96bea6
./engine/tests/corpus/1a0b26363f67de66ae4735de01977e057cd288b3
./engine/tests/corpus/f21b6dffbb030227341b2f38e0e34f3bc996393e
./engine/tests/corpus/64bc620c9e08f853c87a53005f660b84ce1bcf57
./engine/tests/corpus/82a861873feb0b1b31bc87cb45b80586290fb7f1
./engine/tests/corpus/2c707db1c4e4be66cd7a9fb9c077dadbcc5a96f9
./engine/tests/corpus/0778be538f82259275b8bfbe0d766c2fc3d4bcb8
./engine/tests/corpus/8069497daaf83b7ddc5d4090891c105fd9d0f2ac
./engine/tests/corpus/d53093e527386a52e63f1557cbd6024a9f796753
./engine/tests/corpus/2210d4678fcbf36b868bb8b989828d7a1ba10266
./engine/tests/corpus/5bbb4be2894e0c6f04a11a90bb24945f5a73b227
./engine/tests/corpus/9e74e5722b0e85ea0e61918b882514bc4f0a67f0
./engine/tests/corpus/26880de20f31e8891545d65528bcb624901100e4
./engine/tests/corpus/4bde68076227f2fd5325d43cfdb5310430126308
./engine/tests/corpus/bc829030fb9b2200d1ce41ec8817c989904fe827
./engine/tests/corpus/d42d46d5a500694fbd5ca373a205d244e31b5443
./engine/tests/corpus/d8e608a1ba3be6f38eee8c90e765f141c4cd66ba
./engine/tests/corpus/3516d2fe5224fbb12cafdd5cde652ce1632537c1
./engine/tests/corpus/c90be0927e3c98d24dfe206b50006ad17fdfdd36
./engine/tests/corpus/261a7bf8f02ac68d53d713089dc74f57996f5701
./engine/tests/corpus/c25816a1bf30d16b10d65b14de21193780f8a376
./engine/tests/corpus/4f04a211e4b0ed517ba2c8011ac0260f6d3dc993
./engine/tests/corpus/ea7c17e411659042f799b887a65f6b53d66be3c2
./engine/tests/corpus/02730655aea5cc5b41f2bd23f5da72036db9fbe9
./engine/tests/corpus/0f1b0973109c3498b7d5ff406da1b0c449f25739
./engine/tests/corpus/73060de2e60a2803b9f23838a041c73d08db0a31
./engine/tests/corpus/b8cbd7470aee4b56758b92b013241cfec7a5eedc
./engine/tests/corpus/d247bc127ab41876f4ea34bbcc528a351e8cda15
./engine/tests/corpus/1f5d040f8a08ec65e4f8d4bc6893fa2ffc20c957
./engine/tests/corpus/d741b6f6a0341ccb764caa631112da7420814907
./engine/tests/corpus/049564ecd0341a00c17976586ad50d3391362584
./engine/tests/corpus/e4a4ec33fd27218bf11135099fd26b70b4a91564
./engine/tests/corpus/f25293fdb7919322bd14b3ebea9014d41bb36e78
./engine/tests/corpus/fd5b06e61c63bbd42c4053371bce65e55fd59194
./engine/tests/corpus/ef33c490d5c67b3fdffae3b6604aec37deaae5ac
./engine/tests/corpus/8944f8ebe3becb75f935249c375f15422aad6b76
./engine/tests/corpus/40e25a4f6326cf672aa6897b42fba38a856a5c40
./engine/tests/corpus/b72026ad1d8b33f71570bd9252e64643bcf14b09
./engine/tests/corpus/9d286bd0ea059d96f96b10db4a615a4db37a2bd5
./engine/tests/corpus/3052e0998ebf2c68201735a6f39318c93e57b40f
./engine/tests/corpus/f0074be474181e2164b3cbdf2d64c017d918ad61
./engine/tests/corpus/cad4834437ec8589721bb554b2a38a31cef28c39
./engine/tests/corpus/01a92a36dd68840c6210561ad4dea63cb3e9eda9
./engine/tests/corpus/2270311cc526e3b957af969ed5bc8c3e6036d755
./engine/tests/corpus/48d0394c95d6b202d575d6599a78ff2fcd7485c5
./engine/tests/corpus/92ffc544a85e65f087843e53ba310c5e995c623e
./engine/tests/corpus/ed6ca1664e9f04e7912d50d740fcf745e51bd1f5
./engine/tests/corpus/00c75679b6f58e7e71fc54be0700878d7826a4fd
./engine/tests/corpus/cb386e37234100fb1ab9f90c6746c99d2f9ed7e8
./engine/tests/corpus/e5b7d57d06fb714b6e7bf3855fc3aa119dfb1f6d
./engine/tests/corpus/a77e11c7aeb8de51abe0aa2cce429a6b54892808
./engine/tests/corpus/c50ce1a2a5945d1c980f7eb5db00be358ff55641
./engine/tests/corpus/fcc87be2a80597c8beae3979b964c2161afa7188
./engine/tests/corpus/53891b0629aaa528567071f8764d757ca0cd7b17
./engine/tests/corpus/0ab081c8e1e54e83dde2ed2fdf6d908f0899699d
./engine/tests/corpus/86ca0af61354b3c4e17ee7861f35dc8ba9776709
./engine/tests/corpus/0db12e4d71f1be6301650d2407b21518f21c527f
./engine/tests/corpus/b7e917a1271425ae79db39a2524729ac8b9872fa
./engine/tests/corpus/c9725248dfa349aac0a88f7280b0f099e098ca18
./engine/tests/corpus/c747e574ed183256624b2d74c92dc6e581e1262f
./engine/tests/corpus/991dad8ba3c62daa9eaddc910bb9f3e63a78b76a
./engine/tests/corpus/b797a011a194bf5b6fd510a16e1ca90493ec211d
./engine/tests/corpus/d2bb39844dcdd686c58704bcb3a7256d1b58833a
./engine/tests/corpus/4a3f6e7a2ac8dc37a81ce5c55b79876e77e55b2e
./engine/tests/corpus/c43bb71c6b2891f69ca8cc7c61bf9a78027cdf1e
./engine/tests/corpus/f959a8c36393f8061bb02a106ac4a888688b0610
./engine/tests/corpus/3c9dfbfe550f78ecf744d402f6937bc4a6fbffab
./engine/tests/corpus/0ec43006be80510bf2e984d66e493b5ae21e2507
./engine/tests/corpus/604ebb19d30797b614b33a36f8b6cebcab37d861
./engine/tests/corpus/944769fc6223cba99964909f48ad472d52470730
./engine/tests/corpus/ea60db99d870c297fe18774ddd7731901c0e1f0c
./engine/tests/corpus/f2e88fe7f36951c8df7d8395e0602dada8be37cd
./engine/tests/corpus/d1ba0332f4cc5f174720152eead6327297eec0e1
./engine/tests/corpus/a31c483e7a9bd802ba10a0cd9b18fe33bfe7de3e
./engine/tests/corpus/874db8e3e6f503d3c4ef6c3e2dc9dc20885e6c5e
./engine/tests/corpus/687b31902c6f81caaec6f0a8400f76f8aef2f869
./engine/tests/corpus/dd47028a6c66ca95f137b71eac829ea240bdc60a
./engine/tests/corpus/e1f54bdf87532f455fcc8876f3bb41314ec1486d
./engine/tests/corpus/2479c9ae6040d97031d826510e57b063ac6348a3
./engine/tests/corpus/d559de36cef456e39942e78260e1c8b34a63697a
./engine/tests/corpus/3873c8ba1e581c658fb981d991404b2ef1622ae6
./engine/tests/corpus/72a8fb77d08528ca68d55f92dd1ff2c523a23a33
./engine/tests/corpus/3d773c4e938d6d5791ce8a6b0855b509a977b1a7
./engine/tests/corpus/f26b8cdc923320e8a456d0eefc96c98cf8bfb3f7
./engine/tests/corpus/50c5b343ed81bbd1ebc2a39928b96d918331b0f5
./engine/tests/corpus/81cba82b57e789492e54ac31f066c6fd7dc9d14f
./engine/tests/corpus/3d21f71f7e75fe6b75f4d47b9fd997da4b6f3436
./engine/tests/corpus/40ab57a13763a462ebbc9113f2207cc432d99f19
./engine/tests/corpus/a9513e7930096979ddbd6821260bd294330704df
./engine/tests/corpus/bf3471eab28604b00fb89e8f839f2565905a7eed
./engine/tests/corpus/6a012f122091ca3fb91b20b0af281036770e8b3d
./engine/tests/corpus/9a5ee17c4ad536f7414e11aa575118fb3400c572
./engine/tests/corpus/982338fd0d42651606fd3ea806cadb3532886da3
./engine/tests/corpus/9fb80d5570760ba823024d79713d6d2a3fc3b1e0
./engine/tests/corpus/445b4a766d664a5d722e0b429491c87477a30e2b
./engine/tests/corpus/f5201aafae0b3b4117a7efd5147dbdae2a2564d7
./engine/tests/corpus/59d0be1f26d771e6ef51175492ba6e15b81da005
./engine/tests/corpus/b9c033e005ec999c9ed0367e09860af6d9a55c19
./engine/tests/corpus/8d9bcded324f856412ca275766347df319258198
./engine/tests/corpus/25603bff07445955ab0baa9d3ed4bbf4a843e67a
./engine/tests/corpus/63089eb55ba3bee89211d24674cafc87658a5fff
./engine/tests/corpus/9fadea552f9524a45579f7645dd8332c5e059ef2
./engine/tests/corpus/73cf3ab32d0829fada7465f8aa27d49c0d41585c
./engine/tests/corpus/3108d0c6b43eee117204bb992d8d6519acdaaa20
./engine/tests/corpus/903d0c8fb0e389831906ef12a31134d9afbae635
./engine/tests/corpus/aef89da978410e4bf4d815f3f143f0ad0d1f4ded
./engine/tests/corpus/d576449cd9e164befe6b2f30ba9306b822dd0844
./engine/tests/corpus/dc624182f61dc13e61e83ec881652c16877cd67e
./engine/tests/corpus/3a0eb68e3c1842a5b01ddd7148dac9ba234bb2ea
./engine/tests/corpus/29f82b07b432d80711193274f0d495ffbe57d3d1
./engine/tests/corpus/3863c796cebfd84f9ef086a896c8a579240be7bb
./engine/tests/corpus/c3d25694603ceefec2a7df95bd74a84f2b4279e9
./engine/tests/corpus/b3b35b685cd797d298176c2bd8fb5fa9cca38f2b
./engine/tests/corpus/7045e2fa018073a8af52f159f1241cbc298194be
./engine/tests/corpus/99576f3ed24659f661c4592a00a80bb2604143c9
./engine/tests/corpus/aeb14a8ebb6dae7d5f70f03b806e7993064c6608
./engine/tests/corpus/fedf2ecd1fda18d78646675fa021c9692eb812c6
./engine/tests/corpus/b6445ebc11102f68f2bd446d20b8a876efc1340a
./engine/tests/corpus/66b3dbd3fe898cbaf6732ef30ea771eddb306be9
./engine/tests/corpus/538523318e4df5512348d89e658ed94d1611e76c
./engine/tests/corpus/a4ad29dee1bbd294ce413054cb2d354a0c014e36
./engine/tests/corpus/01e0ee2adf0372d0d0e803dff934435373cfeb1b
./engine/tests/corpus/dcfb6063da1e666e9b53f0405cfcb839c215fd42
./engine/tests/corpus/cb44f661cbaa79cd3cc9d6dd86b6766c75130f91
./engine/tests/corpus/5179e3db294717d860a474a87b3eb9137faf62df
./engine/tests/corpus/42d2456ee7b4a2e79a7b026d0786355237a30fe2
./engine/tests/corpus/85c207189fbd5dd545a54998093075a6c96718eb
./engine/tests/corpus/ffde9951a872e43de812f4e0ce73dcd5e44e53d2
./engine/tests/corpus/2b87ffa067d54b7f3dbc47c2bc562ba36836515d
./engine/tests/corpus/d3fc8797232c2f3714f517e2f3154d6e1a9911bd
./engine/tests/corpus/0c44debc024f7accc57881b7f6c8a13b263fcf58
./engine/tests/corpus/dd37c9930b244d51cdada372f43f3fb864fb4876
./engine/tests/corpus/ecd0bdfa394a143dc9ad719125bc4afd1246f6cb
./engine/tests/corpus/87212ceed6d9d4e5fd66f35da3e196fc78268669
./engine/tests/corpus/036fa235ac29583df8e30f61b1b94ca8137c5f71
./engine/tests/corpus/54823add3078fc873a97fb68ebe62ae3bc996009
./engine/tests/corpus/961aa68f80d14b1290098aedf47eeb4b9854e039
./engine/tests/corpus/8d80bdd8987bcf658e23c81f6f0baaf7f087270c
./engine/tests/corpus/fde88f6a0bdec145022c650be0499f29b873b216
./engine/tests/corpus/7e5c1b45bcec372755275253ed59d3d0cba6b798
./engine/tests/corpus/24a87f514b781ee161cf19806a9bea8141e83513
./engine/tests/corpus/0aa52c4bb81a7a53af89e1cd24009bc6458df6dc
./engine/tests/corpus/a918d0465ea18f905834a0c26284b2de992f943d
./engine/tests/corpus/5cd64e3f2afc1f2b52f8424b78aef2a9bc82ae95
./engine/tests/corpus/1237911faf86f7fbed46aff95388bc1469daf93b
./engine/tests/corpus/9a7926ac7fe8e8b34b777a5ab58060f5a4867ac3
./engine/tests/corpus/725568338c6926380a8b32f46d26992e2194a693
./engine/tests/corpus/05808b7b1f5a14e934e661e91081fe0f04eca573
./engine/tests/corpus/61bb93c95f7c10cf21cc32b48371410a0ddc1ad6
./engine/tests/corpus/cb062f13711be52f7a417848323128f11b947166
./engine/tests/corpus/add8cf187706899b702b2d1be1abef4c640cf068
./engine/tests/corpus/51b7594f57ee5ccfd4a2686cd670d445b719c7cb
./engine/tests/corpus/44efbc017a178876ffe0ebbcc8bcdc9622cfd14b
./engine/tests/corpus/d499d587b0b39e95fe987817f8b726e0684f512e
./engine/tests/corpus/4a3d1c752f3ff0380e84421c1227c8d11d4d2335
./engine/tests/corpus/7c168859293ee188d87702ca8b2831c897c3c678
./engine/tests/corpus/c91c6ee0114243f52859a5ddb930c20f4102631c
./engine/tests/corpus/d283e3688a8ad8f0a04b2a9065e2cfc4f835a170
./engine/tests/corpus/62d5aa2be3f057c6c085aaece945c1760ca89e61
./engine/tests/corpus/d74424fd6a0190d286a7b00d978cc94e4e0a6224
./engine/tests/corpus/6046f8809cc01b2f9b7f72dacc2cab51a4022282
./engine/tests/corpus/3fa4094798c39fc35e46a29d6011ee678c0a161d
./engine/tests/corpus/eb79f2bf1ba29ffc20ff63a13bcd7f270ac61ec5
./engine/tests/corpus/556aaa54428e4f8e4904c4d5768eedb2c8c59a4e
./engine/tests/corpus/1dd198cfc77dcdaef6b1bd1f32bcdb4a28971e1b
./engine/tests/corpus/91bf83b3b6f13df65e84fd5bf16ee7765ea129ce
./engine/tests/corpus/da8ca82da0d051429b3fd6972a9e5d51cd675aad
./engine/tests/corpus/312baddb18f18fce78b1110152eb683e843af343
./engine/tests/corpus/a48841ff7bd5619a6df02cd176178218d85d9d17
./engine/tests/corpus/a1081b806170bbf6c5d774db5844bd5ac3f6e6ee
./engine/tests/corpus/3160758e4500a00af3dea4bdf739ba98de5c87ad
./engine/tests/corpus/7bbd03b0f4120925c01b5681582279f399be4e75
./engine/tests/corpus/edf3c2a8388ec1d3a586103962564b13e881303e
./engine/tests/corpus/4063c787ecf94869e62d6bec9a308fd8b246092b
./engine/tests/corpus/a0fa76e5366916c077b008ad60f4f0230e2ae7c4
./engine/tests/corpus/9e3677eb511b5aba6178bd8890e61038c918f548
./engine/tests/corpus/36f7db307805f45de02925e71e9a8e1909c804d5
./engine/tests/corpus/f3ee4af1efebd6c860014334a0dd5fdd6b1e962a
./engine/tests/corpus/491753c10d5f3471f383db459e49046d8f2d9862
./engine/tests/corpus/813d2e22a3ec3fbd9f7454bd4f708de9c05bb8c6
./engine/tests/corpus/e042eb43c9ffccdcd63f1d16254e289a439f52f1
./engine/tests/corpus/0d9498dcaf37e12f2048a268641661bba31add3f
./engine/tests/corpus/b844be37aadfd5a75a1481c581b71861e5165338
./engine/tests/corpus/4aa06ddf082c7271f924a8c7a93fca9913abce91
./engine/tests/corpus/e991fdffbb295126173a88834c576df1851d5c1e
./engine/tests/corpus/bc35b89261fbcfe47ebe8f3761e03a5b5ab3835a
./engine/tests/corpus/43d3d064d63de811761e67f9a7f7ecfa62e73376
./engine/tests/corpus/fa76e815e9d46e4e43bbe9b8e2b04f6bde6321f1
./engine/tests/corpus/84449c55194ca7b6baa7184bbbeac1065f0bfd3f
./engine/tests/corpus/56ffc8af819fd2fafc340d50eb097919744e0015
./engine/tests/corpus/474fac215ce04caaee70a69a485d20e9fabd9021
./engine/tests/corpus/8555434b2202e35aaf5cc24f14a933739c9c0c1f
./engine/tests/corpus/874decffdc80431b4baa9be780886d62ca78bde4
./engine/tests/corpus/79f2530cd811b7d744b11876416c3f8ee6c38768
./engine/tests/corpus/f58c628416e55cfd533053136f0a7ec0f858ac55
./engine/tests/corpus/e4c9434964af5db7fdc6e1e8528579470d9b5388
./engine/tests/corpus/ec32368e90c9a01a0ceb3092a21c175ffded58cb
./engine/tests/corpus/ba2a54c4543e844d8583825b77ff7de3837aa124
./engine/tests/corpus/2cebfcd02b954bc6774d5ab02fb42a83d6020a26
./engine/tests/corpus/0d2f2042961b8785b973ed0e750b2a3cfcac136f
./engine/tests/corpus/50302b98333a01a1539a6a6b495d4763f8f984d2
./engine/tests/corpus/a91c9f0f66322ff5a4f83a0214bc3d452771178d
./engine/tests/corpus/ac79541a4805cce1fdcdd88d59e3a6ca40f4000b
./engine/tests/corpus/7d98abbb813c56bff52b0a159e2b9a59ef7cf8e2
./engine/tests/corpus/74cdca74d7f339dc9376a0d5755a0bd1cef91aa4
./engine/tests/corpus/c4889bda80d577b6736e89642a7fcaad67da37d3
./engine/tests/corpus/bcd9cce17b7917cee89185248b74d0d88e7164e9
./engine/tests/corpus/692baae56258bd5c82c9555b0d8a634d44474ebd
./engine/tests/corpus/5c013d9bd7cdebc30ea5e3b86dc53c357a6afb54
./engine/tests/corpus/414d7b9fcf43abe1efb634a84b78b5d3f1c94f6a
./engine/tests/corpus/faf852c255e7d47a61097672fd5b292444cb62ff
./engine/tests/corpus/2a57ca3e8f03702b14cd125fbc79f833f385f6e2
./engine/tests/corpus/78ec6cdaef53433855b4a217f4222a5b6a8bbe1f
./engine/tests/corpus/54c64aa877f76ed3d7696b1eb939f61978a13339
./engine/tests/corpus/f5dbc36929a587307c7f002bedb2b24c33952077
./engine/tests/corpus/f709020257f1c865c55a356d4ef1fdc625ba2342
./engine/tests/corpus/86571d0698f784f85836539c3e4569f15cda5af4
./engine/tests/corpus/955ca3e62df5aa0c9eaa35dff05a5c86c2fdbd1c
./engine/tests/corpus/cb182e60ea1d54116adb649bcb6492247f15e72c
./engine/tests/corpus/4c6cdf600ebdc2652ce63cbabaeccad098f44690
./engine/tests/corpus/28e03ef15ea4349a9cf82abb84ef2e31b54c9297
./engine/tests/corpus/f67b1d17001c29420426df0575b8876ca71d6d85
./engine/tests/corpus/8a2d3f3f6082ecb61e439ee45dc308f19c83b043
./engine/tests/corpus/175518bd2581e710733bcd6fc9286bca13e73e7d
./engine/tests/corpus/9b3b3560bbfc30970c0681e752b66047a234240a
./engine/tests/corpus/52a311e6c4ce7474025543ec9b05ad03007b9897
./engine/tests/corpus/2fca3fbd4884d2801024071b240ca1e95ba7f969
./engine/tests/corpus/86cc72d725a1bb4d37e2756e01d63eb929164b2d
./engine/tests/corpus/e6cb893ec3d6ceb71639f5a1305ee3ef6c221e84
./engine/tests/corpus/e353adba22660e1edb516dbc20466fc646665d5a
./engine/tests/corpus/6942d35675482a2ff80598d9d1e93504880e8d46
./engine/tests/corpus/31c59ed56eac81afaa9c6e7bcebb5c47ae6764f4
./engine/tests/corpus/bf12a7d569e78f70b041a1477fff29219ca780e6
./engine/tests/corpus/ef7a91272657ea073bb1f178eb6d54d8232d39c3
./engine/tests/corpus/f8fb294af571a815bc004047053c7a67ac4e757a
./engine/tests/corpus/b66a37139ae556e6fa4516753d36edd9430c5e92
./engine/tests/corpus/9f9a5b8c0fd10bfe03f2fe6b575314bbc7e27048
./engine/tests/corpus/ec50c42c49b8c2263af3447f55c2d025833c46c2
./engine/tests/corpus/3bb44a7d7360ea4baeb1ebd048fff8692b66e874
./engine/tests/corpus/8e8c915f7684413de682f667e31fb708706a90b5
./engine/tests/corpus/d3a064ea3cb2555152c590bf7be415b72e2618f9
./engine/tests/corpus/0477d65a796b30989df97d8292b583b6fd27ce48
./engine/tests/corpus/ce83cc4f8a34ae7947e0de8a181f0995a48c959a
./engine/tests/corpus/83aeab99229b8f601ab707452920c290e10befb3
./engine/tests/corpus/3efe259910a2b05d18ed3993d1c38c606d0840ca
./engine/tests/corpus/ab99bfba4dd10d8f09fc63935768b9985cd60a2b
./engine/tests/corpus/4d774b4634f8ed9ab39718671604e1df3f781630
./engine/tests/corpus/089f5a1e709fb9287db75937a8ae14cb588e6674
./engine/tests/corpus/3daba738bb5ef66b179eae072e93a6e9e41bdf5b
./engine/tests/corpus/70b9bd60a5768538b535dab7784cabf0d052de4e
./engine/tests/corpus/1abaaeb0c86d5998aa2b7bab0651364ab54eb587
./engine/tests/corpus/bd445b62b5a6612905a0bbc921a8aad114ead4e2
./engine/tests/corpus/f55b7f045da6b57a4632185f87770bb54b09cb30
./engine/tests/corpus/1016d45979f47f39336a0a1abca17ee9bab8ad5b
./engine/tests/corpus/b52d11bfee6414398fd7853f59c8752c70c98650
./engine/tests/corpus/f9f23923be670e4877d3e03d9efc86bcccef0f49
./engine/tests/corpus/902193ee7e708395445a94cd3c298babb05d35f1
./engine/tests/corpus/52e53d6478bd8e7e9d1fcf40404566ce453bbdac
./engine/tests/corpus/d74a8e61634d40028bb5f08a542eafe225688035
./engine/tests/corpus/c5439ccaafa7f7e70b1dd7cff076d57c61bdd2b3
./engine/tests/corpus/777f50e6aabea608d90b56fd00e9c4bf7379abdb
./engine/tests/corpus/692f6a09a31ec77648f8f6374a80c7397e8e4372
./engine/tests/corpus/737ae3737c88113340b6bec63fb598f6a20ee50a
./engine/tests/corpus/eac3237d4af70e50c270dc9545ca6cc2cdd97d88
./engine/tests/corpus/1251ac7ee1d464187c0e8614b0c95da6b1b83c7c
./engine/tests/corpus/a549d42cce0cc0f2a34d332901bf5979aa7284cf
./engine/tests/corpus/d2a82371e7dc25157ef1b6cef5acaf6adcfca208
./engine/tests/corpus/0bb7bcf7e78a24f2dcec88830f9950d15cffb684
./engine/tests/corpus/616d2225ea179d21641bbc6bea57614fb3f8eaf1
./engine/tests/corpus/e904b0540ec94fc09d13e19620aa4f14231d7656
./engine/tests/corpus/37b0ae6e8eed2239f71c0a09d84a443aab062bb4
./engine/tests/corpus/daf912aff4f75c316c97dc9b847400c8a482a4b3
./engine/tests/corpus/ad12bda01d51b9ca9e6e36d6a4a62eff48f3ca76
./engine/tests/corpus/dcde883b2b24a6e4e4d82508d56bc88a41445e77
./engine/tests/corpus/5b009b78b6a73143c6003b37d82f2d8167df36ed
./engine/tests/corpus/f5a3a165ae99aa63910c62454c3c35783bb48066
./engine/tests/corpus/0a213454a3072e332566a098cef059258103200c
./engine/tests/corpus/5cf02067405d226b0fbf658b3a7611503f92213d
./engine/tests/corpus/0a9992fc52bb519ec60fac2f29d812ecfbc72289
./engine/tests/corpus/a03845223c85e4fa07b94b4d08afc27e9b569d1f
./engine/tests/corpus/a1f0355d2b8ff136cb6819092cda05133a259b69
./engine/tests/corpus/541914dee2f31cf7a1fb65e90522276ef39a24ac
./engine/tests/corpus/a88bd496e0c0c49c6358a0d4307acf06659a0fcf
./engine/tests/corpus/886c039d63ad4154801f596ebdfbfe70a42e4702
./engine/tests/corpus/367fdfae5509f02838a1e34578ffe6123e95df18
./engine/tests/corpus/8ac949182e260bc12605c82bd8080f1a26573c13
./engine/tests/corpus/fd6da6f8cead42806c9f607fa84465201c205de4
./engine/tests/corpus/1c7bafcd496f64a8d112ef294b3a18e32e86a255
./engine/tests/corpus/47394b1cbf961f25c8d136c00b488456215ebdba
./engine/tests/corpus/427832bc18e0bec6ce4d447e0783dada9c8b6dae
./engine/tests/corpus/bcc431fda4cc982b4749445b3d76da534bfeec33
./engine/tests/corpus/d3d87ebb4f871b3e8c8d9fd6cfc312db01938cee
./engine/tests/corpus/21b2802760bb73b95c9131c632bebaf4bd3a788f
./engine/tests/corpus/8ffee47a477b8bbfb15cc9685b623ed988323428
./engine/tests/corpus/82f35ae9b49685421d7d94760e3bb81a97988c60
./engine/tests/corpus/b2ddb7a060c53b1cd9dff40f2e202351c9aaeee9
./engine/tests/corpus/12aa1e133d48de0048327fcbfd12832aa010506a
./engine/tests/corpus/c381f96936829c54a1318b11c4d2d2f00c4df18c
./engine/tests/corpus/770186eba9093c588425ef70e458d65396501dcd
./engine/tests/corpus/f437dcb4b2dee348de7e71a3689ad0317edad7aa
./engine/tests/corpus/1c12a8a98a7405d704177ed3e1b92f5ff1241b7d
./engine/tests/corpus/8019723acbf9a33bc348aed75919db73d27be18e
./engine/tests/corpus/9a490e27b25a5637f244a89afd31495a11a8a419
./engine/tests/corpus/69dd5ffc0142432d0cc9ec6b7451e1adfbffe486
./engine/tests/corpus/9294dc5946e50d36bd3616a9b7ed30a8c831db72
./engine/tests/corpus/e2d3e9329d1088dc4a011d3e41c06ef76ba3f03b
./engine/tests/corpus/3ffb3b83338faba1ec11b7334451002f50c48ac2
./engine/tests/corpus/5b0f50d4cf4667d3a9859d4d480461826eb043c6
./engine/tests/corpus/d266a5c6d272b84bc6cb71ed7959d18189378f61
./engine/tests/corpus/19ebd16f6f28d01663cf0379bbf3cf086b47d5e1
./engine/tests/corpus/f5568e9f77ddbf2ba947e765cfafe24b9b49885f
./engine/tests/corpus/770f37fabc015e73c72c937f0c572b3175dbb5c1
./engine/tests/corpus/450ee832c57e915600913954bd04a3ac181cb126
./engine/tests/corpus/3bb04ceb899ef1e085f1f33d9aac86cf6256cc1d
./engine/tests/corpus/ac02675e60ce9482b59ace568c991ac34c10ebc0
./engine/tests/corpus/4c8ecbfe8b0d4f18036c0e80cb9cc79ae63c4f5a
./engine/tests/corpus/df347bf4d6209f3e879986c3a9d54c06d113e13f
./engine/tests/corpus/3ac6255a427d91d478a1af99307d587686a85f5d
./engine/tests/corpus/3f242718b45e19494b643dd02103c192d8eba7da
./engine/tests/corpus/71d8c70569b7d6c9c224a4964473fe8dde84751a
./engine/tests/corpus/17d42a424ff56ea8545d33298841a0a90876cb20
./engine/tests/corpus/38eb4c1db84d35085ea3dec79d30abc645d4c99f
./engine/tests/corpus/a1822a325f122273a64c2f63bc41e8ab7b611068
./engine/tests/corpus/17ab1380ff4b0c3cceb717cc6967b420b9e07b8a
./engine/tests/corpus/958b0b8e5b9de28e782cbe29b69037957f2c7cdf
./engine/tests/corpus/5d561f5110b9efc4d59f61e5cbc1f244fbf7e175
./engine/tests/corpus/495c87129c527a8bfe8077308b8599b65cb81178
./engine/tests/corpus/26a7ce1583cddf0df769b184ef33f3086096eb23
./engine/tests/corpus/fa52d8a594093227c635d3010d7bcab9aa851ab6
./engine/tests/corpus/a19d899cb91fd13cce5c359b4d0777eff28fff1d
./engine/tests/corpus/aab48b692efc0536a473fceaff85a075fe875aef
./engine/tests/corpus/6c5c071a1b9f1825ff9e63294bf1d4d27f1b1f10
./engine/tests/corpus/1bfd7cb625ab27e910d99f3f903c1d8db4d77a73
./engine/tests/corpus/e1c71c82debce3802ab25d9c8ea4c986d02c36d3
./engine/tests/corpus/2102e85fbf54b4d3e0b01c7327db630c13e44d5d
./engine/tests/corpus/64ec7cc39b34c3effd6ebcef96e912a05e2239db
./engine/tests/corpus/800f6a79d4652f6819ddce29ef2c432a1a5726e2
./engine/tests/corpus/af925cb80f32595537d8ddd2b84ae4e68ecf95b4
./engine/tests/corpus/890ec9d029161a00388dd45593b264e3be332582
./engine/tests/corpus/fef08f8e75fd5c7bc6d8fed107babb2b8c3b943e
./engine/tests/corpus/4ad68b47ecc24502e57cc6ad548bb9fce8de1877
./engine/tests/corpus/87bc3c5f322e022ade4d9115c4375ac7a844c629
./engine/tests/corpus/af49b01535a6daeb7338d135cc694f9fd798f522
./engine/tests/corpus/aaebe380a0c32657572c10a29d1fb6207a5d09c4
./engine/tests/corpus/0c1c4c9657d24c7a0eb09e108a84286206aa6a72
./engine/tests/corpus/3c7abf404d0f33940a789fdfa11c1bd77af8b83b
./engine/tests/corpus/cdc22aa1004874bec54099d772e385aa16f58635
./engine/tests/corpus/ab06f3c8f6df869974700fa965219905b5a361d3
./engine/tests/corpus/a7b0f5cf617acafc4bcd01c48ab0f5488051bff0
./engine/tests/corpus/c7e5d8eb5a68497639f78105ddf8aaed594ebb8a
./engine/tests/corpus/3d2977e32c5038dff83a46060c66329c74dae79f
./engine/tests/corpus/7a4b5188b54538ee1d2cfd6a2233eb6f9aa041ad
./engine/tests/corpus/c48a218697acb3a663807c9ebb0f09fdf020586f
./engine/tests/corpus/59eca8cf195eae9ca2adf8100f01b4510d0f40a5
./engine/tests/corpus/f00ff500f159c35b89ed1e3673327b2bfb4672a4
./engine/tests/corpus/b139480cfc3573bd9feec768dfd9cf11457a373a
./engine/tests/corpus/454dc4be61c28d418174169d730904b6895555fe
./engine/tests/corpus/7440becec41c270a7949ab7e001a47fe854b9087
./engine/tests/corpus/bfc8d12a7c1e0dc62079ef68746635cf7a849e58
./engine/tests/corpus/9b033f951b615a435f10ab0aa87e740455317bca
./engine/tests/corpus/d1be754c12e7a7ecc55b092af4dbe22e3d6a90c6
./engine/tests/corpus/ffa9b54adc346d2f3e23c67d3d58ab9299a2a3d4
./engine/tests/corpus/99c22e0a5cf22e22bfd85037c91631dda648eecc
./engine/tests/corpus/e90e047ba5d17bb91f630515eb9fab465b37c684
./engine/tests/corpus/80271099af44479d3dce559e07b2037ebab50f54
./engine/tests/corpus/f9297176add8f1aa8336b6331c5ba5ad034b7105
./engine/tests/corpus/f0876adbe630dbb9d5ea83c80769db04629c9a5a
./engine/tests/corpus/b9b9e1f063b602ae70f7933411813a20f9daf078
./engine/tests/corpus/40e891a37336fd356723e743e9177d8a81abfb09
./engine/tests/corpus/8f26f4a4144981e6f13624832453c8ab5703be41
./engine/tests/corpus/80062fb544c0d14560e734c022386259200f17df
./engine/tests/corpus/c9b00218b1f08f1d2bff56107afd7aab2bd7e81e
./engine/tests/corpus/60092b91577a0ae3e4630ff3f0c259040e03480a
./engine/tests/corpus/7cce7a83b05aa37ffe1eaa37ef9241cacb0876b3
./engine/tests/corpus/74e5ad595a1f6a982ed969cf37d7a13c2cb04202
./engine/tests/corpus/b16446fbbfe3de79ee85c78966dddbd7249d64d7
./engine/tests/corpus/dc4a3c3f8788af63a3d3fee18b04bd580489b5de
./engine/tests/corpus/53128c57d8e92b20d42b1239f6772aef59606caf
./engine/tests/corpus/c8cd05a1de3d79f68b219de85fdd3db4e2b3fa10
./engine/tests/corpus/e9805a33ef65486362d5fa96f9cd56054c505877
./engine/tests/corpus/9fa3869dd8837ee43688b65c2b37bd235d845f39
./engine/tests/corpus/cd27df2a47640f511cc956b2121444ffa345b01e
./engine/tests/corpus/6d998f698ca0cdc99433f2ef5fe2aca9c63c6222
./engine/tests/corpus/1fb8ea3d56169516979eff1e5ec54500bc57e5b3
./engine/tests/corpus/08fb6cca5fccab64bd085a0c3169aa45b628e941
./engine/tests/corpus/be89d8675bec84177ab70406b0fd9160dcd508f3
./engine/tests/corpus/b71f6d1b23a39e8caa07adb1b76d62a903e2942d
./engine/tests/corpus/fcc6ba62b0baae2722f463348eca2b63eba0f4d4
./engine/tests/corpus/eec6fbcbdfc001c7a5cf1b2bb0473a1ffc61f946
./engine/tests/corpus/df03825c0d2f05358b6292ff7278d229fa0e150d
./engine/tests/corpus/9bb45e1e455a35168e8adfac5183259a72be4c57
./engine/tests/corpus/32e52b7162e5a876ee3806f4269bbfeb359650d3
./engine/tests/corpus/4251011ec1ca057a8f9bbbdf38439ae6b55913c7
./engine/tests/corpus/de8e76853912decc502b83a64b8e45056618081b
./engine/tests/corpus/ee054520bc6d7fbe10b301c5788cc254e802b73c
./engine/tests/corpus/080817abeed2b753106e1cbc852f764573fcd504
./engine/tests/corpus/2b30044a702d1b560e49a212435bf0c0dd718d04
./engine/tests/corpus/817ec491d8b5684ff85951bedd92eeff01e06ed4
./engine/tests/corpus/5039ed1770b6a30d6a1df2806d65a543e7dc4f2c
./engine/tests/corpus/8ae5f0ec28a4f67c83c2d358b0988a5331494435
./engine/tests/corpus/4b08ae0f1df124ad56d35bfcd1d10ca952f65ed3
./engine/tests/corpus/1e768d60f8351abfee5899778f5ae4fe873b249f
./engine/tests/corpus/1b0ae5d7c68e32b5a06a028084f1312264083039
./engine/tests/corpus/cfa407d0632e2a89e964c8650229d502632fe7f1
./engine/tests/corpus/f3fc791567004ee70d76a78510a5a44114170b14
./engine/tests/corpus/1b9806c07f3ba4ad80c6aba338d182d866ec1091
./engine/tests/corpus/e7c0082f7657ee36dc7dced0ace55c3c09879635
./engine/tests/corpus/f6d716fe0d53a23f0b1e3b4ae1af259f4ede7f5e
./engine/tests/corpus/b458dc18245587ff01a94a54ad0ca29c73afcb3f
./engine/tests/corpus/42547f4989874142be874cf52ef58ed6ce800214
./engine/tests/corpus/53fa5a325c6169e22eba1d2df6dfce7816017364
./engine/tests/corpus/4ff14ba948d21a8eff30012f0c1357a0da5196a0
./engine/tests/corpus/1020eab6c29d43683ba2745e28e2cb2fd23ff902
./engine/tests/corpus/b3b6ffc2b21ef969744f6f7981c1f36799e608a8
./engine/tests/corpus/4c3ae2d33e4b0197593ae0a8213c3fd6540a932d
./engine/tests/corpus/265ae2c0c7479f31fc627e9f0bac27578d476de2
./engine/tests/corpus/444cc3f5e0687c9263f4a31292b345a458a68f00
./engine/tests/corpus/c7897020cc6beffcbcd6d9a24d8f30456f3c5ced
./engine/tests/corpus/6fb6f1c8c8f83593e55d0490669e6ef6e9f9e8db
./engine/tests/corpus/06f6b78cabbb6532fd5936ef808faa283e1f16b1
./engine/tests/corpus/ce72b65ba87bcfb229efb9e686821b7a86340292
./engine/tests/corpus/d2cf6c6aff903ef10b0974ea7d1b2584fa646f4e
./engine/tests/corpus/c3a99f6307ad7b8deda236673d2b24ede82fcc84
./engine/tests/corpus/e5f94f77881496067bd6b5c2be32b1d9bce1e71b
./engine/tests/corpus/dd6f4516c546c45ebb4ff14e6375ad2cc1afc964
./engine/tests/corpus/81fc0df347cff598dac58f3b0c0d7984b8fb88b3
./engine/tests/corpus/7321fd3d48486fd680f1d915d5bfd2941480fe3d
./engine/tests/corpus/98c3caeab3d804315a8c54b376c65678de0ada98
./engine/tests/corpus/82e278c887ee4f42d20b7ac934cd29c623a1cc56
./engine/tests/corpus/49dfd0fcc5edd26ec73271620062cc72f6d1bc29
./engine/tests/corpus/ee7b04c31693fba63ff75b49b2f0b533f2c4e376
./engine/tests/corpus/83ff2e9c27717d6f8ea132ca1fb64c9f2be9409e
./engine/tests/corpus/8c049df0d371903f4ff251b86bfee28d0645f31c
./engine/tests/corpus/f5cd0fe2e144f30fada5b343e250427927c0c90b
./engine/tests/corpus/1c35c2b3bdaec0f265e60ea90c41a47beefc18d1
./engine/tests/corpus/cdd2c8cb97a8b13f734dc169f93f06de64dd7490
./engine/tests/corpus/a4c1bf3700a728d11403749864e54970b1ac80ee
./engine/tests/corpus/44a47974ef72337a318a21112dec1226758c4062
./engine/tests/corpus/46fda8ab8017929519af3da38a52754d377475e9
./engine/tests/corpus/996d6e631cfaab800c5498949fb6601a965de3fa
./engine/tests/corpus/c2e02e87d2cc2291894ef82f341f9ff8bf4d4084
./engine/tests/corpus/f07c7faf6f89ecd8ded6dab9fa85fc86f74606d9
./engine/tests/corpus/6964fc01fe08109b3f241b2fa38a9342a246ee4b
./engine/tests/corpus/f25256b1eb6cabcac2ef06e851cfe1d076aefbbf
./engine/tests/corpus/ae4e9563e5f3c2501c8f322eabefd3f93b0feeb8
./engine/tests/corpus/d1bbd3248e664266b1c0887b5d56222a1cb147c1
./engine/tests/corpus/3118b5b8023726f66d37933495b505f843552e50
./engine/tests/corpus/fbf43d71424fd22f4d107bb2aef9cbea857337f4
./engine/tests/corpus/fcd740be58b4913824a8975e45285b6017921136
./engine/tests/corpus/58bb6782c2126dfff77502a8491954099c100c14
./engine/tests/corpus/75ed0602b2e0f1003cfca93ba8c2f4de413eda50
./engine/tests/corpus/e5046f32c627595126e0094a125020e3ae790f90
./engine/tests/corpus/a4b73bb9e4f6b1c10b1089c3ed253c38646cfc73

 succeeded in 166ms:
./DECISIONS.md:86:**D64 — Native WINS the matched-15B stage-3 A/B on both axes; rush-tax A/B closed (v4_s2tax capped 15B); fleet reorg (v3_tax retired, D60 isolation + pickup curriculum launched).** Matched-step native-vs-torch (both maxdist 12, stage-3, warm from their stage-2 finals): at 15B native_s3 tds ~0.39 / block_2dred 0.10 vs torch_s3 tds ~0.26 / 2dred 0.16 — native is BOTH higher-scoring AND lower red-dice at 3.4x the throughput (2.1M vs 0.61M SPS). The native architecture is now the production default on scoring AND block-rationality; torch's remaining role is bc_vN training + the D60 isolation control. RUSH-TAX: v4_s2tax (possession, reward_rush_cost 0.015) capped at 15B — taxed gfi held ~24/curric-ep across the whole run vs untaxed ~33; with D63's from-kickoff grounding (taxed 15 vs untaxed 33 vs human 17.4) the tax fixes a real 2x over-rush without over-correcting. ADOPT FINAL — rush tax 0.015 joins the settled v4 economy (still scaffolding per D46, revisit at graduation). FLEET REORG (Alex, this session): v3_tax (taiwan, legacy obs-v3 straggler) KILLED — obs-v3 lineage fully retired. Taiwan repurposed to the D60 ISOLATION ARM per the ledger's documented design: a TORCH arm (--float, obs-v4) with --train.bc-coef 0 + the torch flagship's frozen-enemy-path, maxdist 12 — single-variable test of the bc-anchor hypothesis (if its 2dred falls to ~0.11, the anchor held 2dred UP; if it stays ~0.16-0.18, the opponent mechanism is the cause). Requires obs-v4 restage on taiwan (was OBS_SIZE 1612). PICKUP CURRICULUM: Alex EXPLICITLY APPROVED (supersedes the D63 "awaiting approval" hold) — mirrors backplay but rejection-samples the predicate-agnostic bank for a LOOSE ball (BB_BALL_ON_GROUND) within N Chebyshev squares of a standing active-team player; new env knob demo_pickup_maxdist parallel to demo_endzone_maxdist; targets the D63 starkest gap (pickup_success 0.30 vs human 4.88). Launches on the possession box after v4_s2tax's cap frees it. Also this session: Alex onboarding the local RTX 2070 (task 22) as free baseload via SSH/Tailscale-direct — WSL2 + --float build, total_agents ~2048 for 8GB, ~1-2M SPS env-bound. Balance $40 (~15h runway, 12h elapsed mid-session).
./DECISIONS.md:87:**D65 — Session reorg SHIPPED + three launch footguns caught. Final fleet: 3 live arms + 1 stopped.** Executed the D64 plan. LIVE: (1) v4-pickup-s1 (possession, PID 25594) — native anchor-free pickup curriculum, demo_pickup_maxdist 2, warm from v4_s2tax, demo_fallbacks 0.000 (15471-state bank, abundant loose-ball coverage; bank_pickup_probe.c: 33.7% loose, 16% qualify @maxdist2); (2) v4-native-s4 (japan, PID 8603) — native flagship advanced to stage-4 UNIFORM (demo-endzone-maxdist 0), warm from the 30B stage-3 ckpt 0000030015750144.bin, coexists with scraper; (3) v4-d60-bccoef0 (taiwan, PID 2330) — D60 isolation: torch --float obs-v4, frozen-enemy bc_v4.bin, --train.bc-coef 0 (the SINGLE variable vs torch_s3's 1.0), maxdist 12, full v4 economy overriding synthesis-C's dead bake; started 2dred 0.159 — watch if it falls to native's ~0.11 (anchor was the cause) or holds ~0.16 (backend/opponent). STOPPED: ballhawk (idle after torch_s3 completed; conserve at $40 balance). THREE FOOTGUNS caught this session: (a) MONITOR STALENESS — the old fleet monitor grepped log CONTENT but never log MTIME, so it reported native_s3 (done 30B, 13h prior) + torch_s3 (done 15B, 8.5h prior) as "running" while their boxes idle-billed for hours; replaced with /tmp/fleet_liveness_monitor.sh that flags DEAD on log-mtime-age >360s OR pgrep -xc puffer == 0. (b) FLEET.SH BANK-OVERWRITE — fleet.sh setup rsync does NOT exclude validation/states or resources/bloodbowl, so it clobbers a box's demo bank with the Mac's (which held a stale 1057-state bank); shipped the 15471-state bank back to the Mac repo (gitignored) so future syncs ship the big one. (c) FLEET LABEL EXACT-MATCH — fleet.sh resolve exact-matches bb-<name>; the box is bb-taiwan-anchor not bb-taiwan, so `setup taiwan` silently no-ops ("no running instance labeled bb-taiwan") and the obs-v4 sync never ran — use `setup taiwan-anchor`. NOTE: native_s3 + torch_s3 both COMPLETED their planned runs cleanly (final ckpts saved) — not crashes; D64's recorded final numbers stand. Also: Alex onboarding local RTX 2070 via SSH/Tailscale-direct (awaiting host:port); balance $40 (~18h on 3 boxes after stopping ballhawk).
./puffer/bloodbowl/bloodbowl.h:304:    int demo_pickup_maxdist;
./puffer/bloodbowl/bloodbowl.h:1220:            } else if (env->demo_pickup_maxdist > 0) {
./puffer/bloodbowl/bloodbowl.h:1223:                // demo_pickup_maxdist (Chebyshev) — the scoop backplay skips.
./puffer/bloodbowl/bloodbowl.h:1240:                            if (d <= env->demo_pickup_maxdist) { hit = 1; break; }
./puffer/bloodbowl/bloodbowl.h:1311:            bb_match_init_forced(&env->match, &env->procgen,
./puffer/bloodbowl/bloodbowl.h:1315:            bb_match_init_random(&env->match, &env->procgen);
./docs/drills-design.md:26:   Proven pattern (`demo_endzone_maxdist`, `demo_pickup_maxdist` in
./docs/drills-design.md:42:2. Drives the engine from `bb_match_init_random`/`init_forced` through a
./engine/src/bb_procgen.c:33:static void procgen_squad(bb_match* m, int team, int team_id, bb_rng* rng) {
./engine/src/bb_procgen.c:146:    procgen_squad(m, BB_HOME, home, rng);
./engine/src/bb_procgen.c:147:    procgen_squad(m, BB_AWAY, away, rng);
./engine/src/bb_procgen.c:159:void bb_match_init_random(bb_match* m, bb_rng* rng) {
./engine/src/bb_procgen.c:170:void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude) {
./puffer/bloodbowl/binding.c:89:    env->demo_pickup_maxdist = (int)kw(kwargs, "demo_pickup_maxdist", 0.0);
./puffer/config/bloodbowl.ini:89:demo_pickup_maxdist = 0
./engine/tests/fuzz_match.c:5:// bb_match_init_random procgen — the exact path every training reset uses,
./engine/tests/fuzz_match.c:33:        bb_match_init_random(&m, &pg);
./engine/tests/test_match.c:194:        bb_match_init_random(&m, &pg);
./engine/tests/test_match.c:213:        bb_match_init_random(&m, &pg);
./engine/tests/test_match.c:291:        bb_match_init_random(&m, &pg);
./engine/tests/test_match.c:318:    bb_match_init_random(&m, &pg);
./engine/tests/test_match.c:329:        bb_match_init_random(&m, &pg2);
./engine/tests/test_match.c:349:        bb_match_init_forced(&m, &pg, 5, -1, 7);
./engine/tests/test_match.c:353:        bb_match_init_forced(&m, &pg, 12, 26, -1);
./engine/include/bb/bb_match.h:140:void bb_match_init_random(bb_match* m, bb_rng* rng);
./engine/include/bb/bb_match.h:142:void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);

codex
I found the public declarations in `engine/include/bb/bb_match.h`, and only one active `puffer/config/bloodbowl.ini` came back so far from the targeted file scan. I’m reading the procgen/test/data headers now; the trickiest part is making the tests robust without leaning on private procgen internals.
exec
/bin/zsh -lc "sed -n '1,230p' engine/src/bb_procgen.c" in /Users/alexanderhuth/Code/bloodbowl-rl
exec
/bin/zsh -lc "sed -n '1,220p' engine/include/bb/bb_match.h" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
// bb_match.h — the complete in-match state and the engine's step interface.
//
// Design rules:
//   * Fixed size, no pointers, memcpy-able. Copying a bb_match IS a forward
//     model snapshot (search, undo, golden traces).
//   * The engine is a PROCEDURE STACK machine. Blood Bowl resolves as nested
//     procedures with coach decision points (turn -> activation -> move step ->
//     dodge -> reroll offer -> ... ; block -> choose dice -> push chain ->
//     armour -> injury -> casualty -> apothecary ...). bb_advance() runs
//     procedures until a decision is required or the match ends.
//   * Every die roll goes through the bb_rng passed to bb_advance/bb_apply —
//     the state itself holds no RNG, so the same state can be advanced under
//     PRNG or under a replay dice script.
#ifndef BB_MATCH_H
#define BB_MATCH_H

#include "bb/bb_types.h"
#include "bb/bb_actions.h"
#include "bb/bb_rng.h"

// --- Procedure stack ---------------------------------------------------------
// Procedure ids. Each procedure is a small state machine over its `phase`
// byte; params live in a..d / data. Implementations in engine/src/proc_*.c.
typedef enum {
    BB_PROC_NONE = 0,
    BB_PROC_MATCH,        // whole-match driver (halves, drives)
    BB_PROC_PREGAME,      // weather, fans, (inducements/prayers when enabled)
    BB_PROC_SETUP,        // both coaches set up a drive
    BB_PROC_KICKOFF,      // kick + kickoff event + ball landing
    BB_PROC_TEAM_TURN,    // one team turn (activations until done/turnover)
    BB_PROC_ACTIVATION,   // a single player's activation
    BB_PROC_MOVE,         // movement sub-machine (steps, dodges, rushes, pickup)
    BB_PROC_DODGE,        // a dodge test for one step
    BB_PROC_RUSH,         // a rush (GFI) test for one step
    BB_PROC_PICKUP,
    BB_PROC_BLOCK,        // single block incl. dice pool & choice
    BB_PROC_PUSH,         // push (chain) resolution incl. square choice
    BB_PROC_KNOCKDOWN,    // a player is knocked down (ball, armour trigger)
    BB_PROC_ARMOUR,       // armour roll (incl. foul modifiers)
    BB_PROC_INJURY,       // injury roll
    BB_PROC_CASUALTY,     // D16 casualty + apothecary window
    BB_PROC_PASS,         // pass action: range, test, interception, scatter/catch
    BB_PROC_CATCH,
    BB_PROC_SCATTER,      // ball scatter / bounce resolution
    BB_PROC_THROW_IN,
    BB_PROC_HANDOFF,
    BB_PROC_FOUL,
    BB_PROC_TTM,          // throw team-mate
    BB_PROC_TEST,         // generic D6 test w/ reroll window (parameterized)
    BB_PROC_TOUCHDOWN,
    BB_PROC_TURNOVER,
    BB_PROC_END_DRIVE,
    BB_PROC_KO_RECOVERY,
    BB_PROC_COUNT
} bb_proc;

typedef struct {
    uint8_t proc;   // bb_proc
    uint8_t phase;  // step within the procedure's state machine
    uint8_t a, b;   // params: usually player slots
    uint8_t x, y;   // params: usually a square
    uint16_t data;  // procedure-specific extra state
} bb_frame;

#define BB_STACK_MAX 32

// --- Engine status -----------------------------------------------------------
typedef enum {
    BB_STATUS_RUNNING = 0,   // bb_advance may continue
    BB_STATUS_DECISION,      // a coach decision is required (see decision_team)
    BB_STATUS_MATCH_OVER,
    BB_STATUS_ERROR,         // illegal action applied / dice script divergence
} bb_status;

// --- Match state ---------------------------------------------------------------
typedef struct {
    // Players & pitch
    bb_player players[BB_NUM_PLAYERS];
    uint8_t grid[BB_PITCH_LEN][BB_PITCH_WID]; // player slot + 1; 0 = empty
    bb_ball ball;

    // Clock & score
    uint8_t half;           // 1..2 (3+ = overtime when enabled)
    uint8_t turn[2];        // team turn counters 1..8 per half
    uint8_t score[2];
    uint8_t active_team;    // team whose team turn it is
    uint8_t kicking_team;   // this drive
    uint8_t weather;        // bb_weather

    // Team-turn resources. BB2025: any number of team re-rolls per turn (the
    // only limit is that no single die/pool is ever re-rolled twice).
    uint8_t rerolls[2];
    uint8_t rerolls_start[2]; // purchased complement; replenished at half-time
    uint8_t bonus_rerolls[2]; // DRIVE-scoped bonus re-rolls currently in the
                              // pool (Brilliant Coaching): spent before any
                              // other re-roll; the remainder expires at
                              // END_DRIVE. The Leader re-roll has HALF scope
                              // and lives only in `rerolls` (granted at
                              // PREGAME and at half-time).
    uint8_t blitz_used;               // team blitz action used this turn
    uint8_t pass_used;                // pass action used this turn
    uint8_t handoff_used;
    uint8_t foul_used;
    uint8_t ttm_used;
    uint8_t ktm_used;                 // Kick Team-mate: its own per-turn budget
    uint8_t secure_used;              // BB2025 Secure the Ball: once per turn
    uint8_t bribes[2];                // bribe tokens (Get the Ref / inducements)
    uint8_t fan_factor[2];            // pregame Fan Factor (D3 + Dedicated
                                      // Fans); Pitch Invasion adds it to the
                                      // roll-off. 0 until the fans/inducement
                                      // work lands (replay init injects it)
    uint8_t cheer_assist[2];          // Cheering Fans: +1 assist on next block
    uint8_t surfs[2];                 // players of team t crowd-pushed off (cumulative)
    uint8_t apothecary[2];            // remaining uses
    uint8_t coach_ejected[2];         // "You're Outta Here": no more arguing

    // Procedure stack
    bb_frame stack[BB_STACK_MAX];
    uint8_t stack_top;      // number of frames

    // Decision surface (valid when status == BB_STATUS_DECISION)
    uint8_t status;         // bb_status
    uint8_t decision_team;  // which coach must act
    uint8_t turnover;       // pending turnover latch for the active team
    uint16_t ret;           // last popped child's result (child -> parent)

    // Bookkeeping
    uint32_t step_count;    // decisions resolved (sanity/timeout)
    uint8_t team_id[2];     // roster ids (codegen index) for obs/embeddings
} bb_match;

// --- Lifecycle -----------------------------------------------------------------
// Initialize a match between two rosters (codegen team ids) with default
// matchday squads (first 11+ players per roster definition). Procedural/custom
// squads come via bb_match_init_custom (Phase 5).
void bb_match_init(bb_match* m, int home_team_id, int away_team_id);

// Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
// (the procgen stream, not the in-match dice stream).
void bb_match_init_random(bb_match* m, bb_rng* rng);
// home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);

// Advance the engine until a coach decision is required or the match ends.
// All dice are drawn from `rng`. Returns the resulting status.
bb_status bb_advance(bb_match* m, bb_rng* rng);

// Enumerate legal actions for the current decision point into `out`
// (capacity BB_LEGAL_MAX). Returns the count. Only valid in BB_STATUS_DECISION.
int bb_legal_actions(const bb_match* m, bb_action* out);

// Apply one action for the current decision point, then advance.
// Applying an action not in bb_legal_actions sets BB_STATUS_ERROR.
bb_status bb_apply(bb_match* m, bb_action a, bb_rng* rng);

// Trusted fast path: bb_apply WITHOUT the legal-set re-validation. The caller
// must guarantee `a` is an element of bb_legal_actions for the CURRENT state.
// Only the RL binding's c_step qualifies (bbe_decode snaps onto the legal
// list it just enumerated, so membership holds by construction, and the
// re-validation was ~20% of env-step time). Everything else — tests, fuzzers,
// replay/lockstep harnesses, external drivers — must keep using bb_apply:
// its validation IS the mask-soundness invariant (adversarial review P1).
bb_status bb_apply_trusted(bb_match* m, bb_action a, bb_rng* rng);

// --- Queries (pure) --------------------------------------------------------------
static inline const bb_player* bb_at(const bb_match* m, int x, int y) {
    uint8_t v = m->grid[x][y];
    return v ? &m->players[v - 1] : 0;
}
static inline int bb_slot_at(const bb_match* m, int x, int y) {
    return m->grid[x][y] ? m->grid[x][y] - 1 : -1;
}

// Number of opposing tackle zones on square (x,y) for a player of `team`.
int bb_tackle_zones(const bb_match* m, int team, int x, int y);

// Does this player currently exert a tackle zone?
bool bb_exerts_tz(const bb_match* m, int slot);

// May this player attempt catches / receive hand-offs (standing, has TZ,
// not Distracted)?
bool bb_can_catch(const bb_match* m, int slot);

// Marked/Open (BB2025): a standing player is Marked while in an opposing TZ.
bool bb_is_marked(const bb_match* m, int slot);

#endif // BB_MATCH_H

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

// Build one team's squad: positionals first (random counts within limits),
// topped up with the first listed position; 0-4 players get 1-2 random
// advancement skills from their primary categories.
static void procgen_squad(bb_match* m, int team, int team_id, bb_rng* rng) {
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

    // Advancement: 0-4 players gain 1-2 random skills from a primary category
    // (the 2D6 random-skill table run "fairly" via the procgen stream).
    int advanced = pg_pick(rng, 5);
    for (int i = 0; i < advanced; i++) {
        int who = base + pg_pick(rng, n);
        bb_player* p = &m->players[who];
        const bb_position_def* pd = &td->positions[p->position_id];
        if (!pd->primary_mask) continue;
        int gains = 1 + pg_pick(rng, 2);
        for (int g = 0; g < gains; g++) {
            if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;
            // Pick a random primary category bit.
            int cats[BB_CAT_COUNT];
            int nc = 0;
            for (int c = 0; c < BB_CAT_COUNT; c++) {
                if (pd->primary_mask & (1 << c)) cats[nc++] = c;
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

static void pg_init_match(bb_match* m, bb_rng* rng, int home, int away) {
    m->team_id[BB_HOME] = (uint8_t)home;
    m->team_id[BB_AWAY] = (uint8_t)away;
    procgen_squad(m, BB_HOME, home, rng);
    procgen_squad(m, BB_AWAY, away, rng);
    for (int t = 0; t < 2; t++) {
        m->rerolls[t] = m->rerolls_start[t] = (uint8_t)(2 + pg_pick(rng, 3));
        m->apothecary[t] = bb_team_defs[m->team_id[t]].apothecary ? 1 : 0;
    }
    m->half = 1;
    m->ball.state = BB_BALL_OFF_PITCH;
    m->ball.carrier = BB_NO_PLAYER;
    m->status = BB_STATUS_RUNNING;
    bb_push(m, BB_PROC_MATCH, 0, 0, 0, 0);
}

void bb_match_init_random(bb_match* m, bb_rng* rng) {
    memset(m, 0, sizeof(*m));
    int home = pg_pick(rng, BB_TEAM_COUNT);
    int away = pg_pick(rng, BB_TEAM_COUNT);
    pg_init_match(m, rng, home, away);
}

// Holdout / fixed-matchup variant: home/away >= 0 pin that side's team;
// exclude >= 0 redraws any random side that lands on the excluded id (the
// held-out-team generalization experiments train with exclude set and
// evaluate with force_* set).
void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude) {
    memset(m, 0, sizeof(*m));
    int h = home;
    while (h < 0 || (home < 0 && h == exclude)) {
        h = pg_pick(rng, BB_TEAM_COUNT);
        if (home < 0 && h == exclude) h = -1;
    }
    int a = away;
    while (a < 0 || (away < 0 && a == exclude)) {
        a = pg_pick(rng, BB_TEAM_COUNT);
        if (away < 0 && a == exclude) a = -1;
    }
    pg_init_match(m, rng, h, a);
}

exec
/bin/zsh -lc "sed -n '1,260p' engine/include/bb/gen_skills.h" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
// gen_skills.h — GENERATED by tools/codegen.py from engine/data/spec/. DO NOT EDIT.
// spec-hash: 7eba72940493ad8d
#ifndef BB_GEN_SKILLS_H
#define BB_GEN_SKILLS_H

#include <stdint.h>

typedef enum {
    BB_CAT_GENERAL,
    BB_CAT_AGILITY,
    BB_CAT_STRENGTH,
    BB_CAT_PASSING,
    BB_CAT_MUTATION,
    BB_CAT_DEVIOUS,
    BB_CAT_COUNT
} bb_skill_cat;

typedef enum {
    BB_SK_CATCH,
    BB_SK_DIVING_CATCH,
    BB_SK_DIVING_TACKLE,
    BB_SK_DODGE,
    BB_SK_DEFENSIVE,
    BB_SK_HIT_AND_RUN,
    BB_SK_JUMP_UP,
    BB_SK_LEAP,
    BB_SK_SAFE_PAIR_OF_HANDS,
    BB_SK_SIDESTEP,
    BB_SK_SPRINT,
    BB_SK_SURE_FEET,
    BB_SK_DIRTY_PLAYER,
    BB_SK_EYE_GOUGE,
    BB_SK_FUMBLEROOSKI,
    BB_SK_LETHAL_FLIGHT,
    BB_SK_LONE_FOULER,
    BB_SK_PILE_DRIVER,
    BB_SK_PUT_THE_BOOT_IN,
    BB_SK_QUICK_FOUL,
    BB_SK_SABOTEUR,
    BB_SK_SHADOWING,
    BB_SK_SNEAKY_GIT,
    BB_SK_VIOLENT_INNOVATOR,
    BB_SK_BLOCK,
    BB_SK_DAUNTLESS,
    BB_SK_FEND,
    BB_SK_FRENZY,
    BB_SK_KICK,
    BB_SK_PRO,
    BB_SK_STEADY_FOOTING,
    BB_SK_STRIP_BALL,
    BB_SK_SURE_HANDS,
    BB_SK_TACKLE,
    BB_SK_TAUNT,
    BB_SK_WRESTLE,
    BB_SK_BIG_HAND,
    BB_SK_CLAWS,
    BB_SK_DISTURBING_PRESENCE,
    BB_SK_EXTRA_ARMS,
    BB_SK_FOUL_APPEARANCE,
    BB_SK_HORNS,
    BB_SK_IRON_HARD_SKIN,
    BB_SK_MONSTROUS_MOUTH,
    BB_SK_PREHENSILE_TAIL,
    BB_SK_TENTACLES,
    BB_SK_TWO_HEADS,
    BB_SK_VERY_LONG_LEGS,
    BB_SK_ACCURATE,
    BB_SK_CANNONEER,
    BB_SK_CLOUD_BURSTER,
    BB_SK_DUMP_OFF,
    BB_SK_GIVE_AND_GO,
    BB_SK_HAIL_MARY_PASS,
    BB_SK_LEADER,
    BB_SK_NERVES_OF_STEEL,
    BB_SK_ON_THE_BALL,
    BB_SK_PASS,
    BB_SK_PUNT,
    BB_SK_SAFE_PASS,
    BB_SK_ARM_BAR,
    BB_SK_BRAWLER,
    BB_SK_BREAK_TACKLE,
    BB_SK_BULLSEYE,
    BB_SK_GRAB,
    BB_SK_GUARD,
    BB_SK_JUGGERNAUT,
    BB_SK_MIGHTY_BLOW,
    BB_SK_MULTIPLE_BLOCK,
    BB_SK_STAND_FIRM,
    BB_SK_STRONG_ARM,
    BB_SK_THICK_SKULL,
    BB_SK_ALWAYS_HUNGRY,
    BB_SK_ANIMAL_SAVAGERY,
    BB_SK_ANIMOSITY,
    BB_SK_BALL_AND_CHAIN,
    BB_SK_BLOODLUST,
    BB_SK_BOMBARDIER,
    BB_SK_BONE_HEAD,
    BB_SK_BREATHE_FIRE,
    BB_SK_CHAINSAW,
    BB_SK_DECAY,
    BB_SK_DRUNKARD,
    BB_SK_HATRED,
    BB_SK_HYPNOTIC_GAZE,
    BB_SK_INSIGNIFICANT,
    BB_SK_KICK_TEAM_MATE,
    BB_SK_LONER,
    BB_SK_MY_BALL,
    BB_SK_NO_BALL,
    BB_SK_PICK_ME_UP,
    BB_SK_PLAGUE_RIDDEN,
    BB_SK_POGO,
    BB_SK_PROJECTILE_VOMIT,
    BB_SK_REALLY_STUPID,
    BB_SK_REGENERATION,
    BB_SK_RIGHT_STUFF,
    BB_SK_SECRET_WEAPON,
    BB_SK_STAB,
    BB_SK_STUNTY,
    BB_SK_SWOOP,
    BB_SK_TAKE_ROOT,
    BB_SK_THROW_TEAM_MATE,
    BB_SK_TIMMM_BER,
    BB_SK_TITCHY,
    BB_SK_TRICKSTER,
    BB_SK_UNCHANNELLED_FURY,
    BB_SK_UNSTEADY,
    BB_SKILL_COUNT
} bb_skill_id;

#define BB_NUM_SKILLS 72   // learnable skills; ids >= this are traits

typedef struct {
    const char* id;       // snake_case
    const char* display;
    uint8_t category;     // bb_skill_cat; 0xFF for traits
    uint8_t active;       // ACTIVE (1) / PASSIVE (0) per mirror annotation
    uint8_t compulsory;   // asterisk: use is compulsory
    uint8_t elite;
    int8_t value;         // default X parameter; -1 = none
    uint8_t is_trait;
} bb_skill_def;

extern const bb_skill_def bb_skill_defs[BB_SKILL_COUNT];

// Random-skill table per category. The 2D6 roll encodes a key 1..12:
// first D6 1-3 selects keys 1-6, 4-6 selects keys 7-12; second D6 = row.
// Index [cat][key-1] -> skill id.
extern const uint8_t bb_random_skill_table[BB_CAT_COUNT][12];

#endif // BB_GEN_SKILLS_H

exec
/bin/zsh -lc "sed -n '1,430p' engine/tests/test_match.c" in /Users/alexanderhuth/Code/bloodbowl-rl
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
    }
    // Sanity: the known aura carriers are in the mask.
    BB_CHECK(bb_has_skill(&bb_aura_skills, BB_SK_DISTURBING_PRESENCE));
    BB_CHECK(bb_has_skill(&bb_aura_skills, BB_SK_TITCHY));
    BB_CHECK(bb_has_skill(&bb_aura_skills, BB_SK_PREHENSILE_TAIL));
}

// Procgen players must carry the roster's parameterized skill values
// (Loner X+, Bloodlust X+) exactly as bb_match_init players do — the lineman
// top-up path used to drop them (review LOW). Latent until a roster's first
// position carries Loner/Bloodlust; this pins the invariant for every slot.
BB_TEST(match_procgen_keeps_roster_skill_values) {
    for (uint64_t seed = 1; seed <= 60; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 1237, 11);
        bb_match_init_random(&m, &pg);
        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
            const bb_player* p = &m.players[s];
            if (p->location == BB_LOC_ABSENT) continue;
            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
            const bb_position_def* pd = &td->positions[p->position_id];
            int want_loner = 4, want_bloodlust = 0;
            for (int k = 0; k < pd->num_skills; k++) {
                if (pd->skill_values[k] <= 0) continue;
                if (pd->skills[k] == BB_SK_LONER) want_loner = pd->skill_values[k];
                if (pd->skills[k] == BB_SK_BLOODLUST) want_bloodlust = pd->skill_values[k];
            }
            BB_CHECK_EQ(p->p_loner, want_loner);
            BB_CHECK_EQ(p->p_bloodlust, want_bloodlust);
            if (p->p_loner != want_loner || p->p_bloodlust != want_bloodlust) return;
        }
    }
}

// Pre-game injuries are dealt to DISTINCT players (review LOW): sampling the
// raw slot range with replacement could hit the same player twice. At seed
// 49 / stream 5 the home squad rolled 2 injuries but the old code
// double-picked one player, leaving a single casualty.
BB_TEST(match_procgen_pregame_injuries_without_replacement) {
    bb_match m;
    bb_rng pg;
    bb_rng_seed(&pg, 49, 5);
    bb_match_init_random(&m, &pg);
    int cas = 0;
    for (int s = 0; s < BB_TEAM_SLOTS; s++) {
        if (m.players[s].location == BB_LOC_CAS) cas++;
    }
    BB_CHECK_EQ(cas, 2);
    // Invariants: at most 2 pre-game casualties, and at least 11 healthy
    // players always remain.
    for (uint64_t seed = 1; seed <= 200; seed++) {
        bb_rng pg2;
        bb_rng_seed(&pg2, seed, 5);
        bb_match_init_random(&m, &pg2);
        for (int t = 0; t < 2; t++) {
            int ncas = 0, healthy = 0;
            for (int s = t * BB_TEAM_SLOTS; s < (t + 1) * BB_TEAM_SLOTS; s++) {
                if (m.players[s].location == BB_LOC_CAS) ncas++;
                if (m.players[s].location == BB_LOC_RESERVES) healthy++;
            }
            BB_CHECK(ncas <= 2);
            BB_CHECK(healthy >= 11);
        }
    }
}

// Holdout / fixed-matchup procgen controls (generalization experiments).
BB_TEST(match_procgen_forced_and_excluded) {
    for (uint64_t seed = 1; seed <= 40; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 4241, 9);
        // Pin home to team 5, exclude team 7 from the random away draw.
        bb_match_init_forced(&m, &pg, 5, -1, 7);
        BB_CHECK_EQ(m.team_id[0], 5);
        BB_CHECK(m.team_id[1] != 7);
        // Fully pinned matchup.
        bb_match_init_forced(&m, &pg, 12, 26, -1);
        BB_CHECK_EQ(m.team_id[0], 12);
        BB_CHECK_EQ(m.team_id[1], 26);
    }
}

exec
/bin/zsh -lc "sed -n '1,220p' engine/include/bb/bb_rng.h" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
// bb_rng.h — deterministic dice. Every die in the engine rolls through here.
//
// Two modes:
//   PRNG   — PCG32 seeded stream (seed, stream-id) for training & simulation.
//   SCRIPT — consumes an injected sequence of pre-recorded values; used by the
//            replay harness (FUMBBL differential, golden traces) and tests.
//
// An optional `sink` callback observes every roll in either mode — the replay
// writer uses it to record the dice log.
//
// In SCRIPT mode, exhausting the script or reading a value outside [1, sides]
// is a hard error reported via bb_rng_error(); callers treat it as a
// divergence (test failure), never as a crash.
#ifndef BB_RNG_H
#define BB_RNG_H

#include <stdint.h>
#include <stdbool.h>

typedef enum {
    BB_RNG_PRNG = 0,
    BB_RNG_SCRIPT,
} bb_rng_mode;

typedef void (*bb_dice_sink)(void* user, int sides, int value);

typedef struct {
    // PCG32
    uint64_t state;
    uint64_t inc;
    // Script
    const uint8_t* script;
    int script_len;
    int script_pos;
    // Common
    uint8_t mode;     // bb_rng_mode
    uint8_t error;    // sticky: script exhausted / out-of-range value
    bb_dice_sink sink;
    void* sink_user;
} bb_rng;

// Seed a PRNG-mode generator. `stream` selects an independent sequence
// (use the env index for vectorized training).
void bb_rng_seed(bb_rng* rng, uint64_t seed, uint64_t stream);

// Configure SCRIPT mode over `values` (each entry is the face value rolled).
void bb_rng_script(bb_rng* rng, const uint8_t* values, int len);

// Attach/detach a dice observer (replay recording).
void bb_rng_set_sink(bb_rng* rng, bb_dice_sink sink, void* user);

// Roll a fair die with `sides` faces; returns 1..sides. Unbiased (rejection
// sampling) in PRNG mode.
int bb_roll(bb_rng* rng, int sides);

static inline int bb_d3(bb_rng* r)  { return bb_roll(r, 3); }
static inline int bb_d6(bb_rng* r)  { return bb_roll(r, 6); }
static inline int bb_d8(bb_rng* r)  { return bb_roll(r, 8); }
static inline int bb_d16(bb_rng* r) { return bb_roll(r, 16); }
static inline int bb_2d6(bb_rng* r) { return bb_d6(r) + bb_d6(r); }

// Block dice are d6 mapped onto faces (1=skull .. 6=pow); rolled as d6 so
// scripts/replays record the raw face index.
static inline int bb_roll_block_die(bb_rng* r) { return bb_d6(r); }

// True if a SCRIPT-mode generator hit an error (exhausted / bad value).
static inline bool bb_rng_error(const bb_rng* rng) { return rng->error != 0; }

// Raw 32-bit output (used by procedural generation, not by game rules).
uint32_t bb_rng_next(bb_rng* rng);

#endif // BB_RNG_H

exec
/bin/zsh -lc "sed -n '1,220p' engine/tests/bb_test.h" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
// bb_test.h — minimal single-header test harness for the engine.
//
// Usage:
//   #include "bb_test.h"
//   BB_TEST(rng_is_deterministic) { ... BB_CHECK(x == y); ... }
//   ...
//   int main(void) { return bb_test_run_all(); }
//
// Tests self-register via constructor attributes (clang/gcc).
#ifndef BB_TEST_H
#define BB_TEST_H

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

typedef void (*bb_test_fn)(void);

typedef struct {
    const char* name;
    bb_test_fn fn;
} bb_test_case;

#define BB_TEST_MAX 4096
extern bb_test_case bb_tests[BB_TEST_MAX];
extern int bb_test_count;
extern int bb_test_failures;
extern const char* bb_test_current;

#define BB_TEST(id)                                                       \
    static void bb_test_##id(void);                                       \
    __attribute__((constructor)) static void bb_test_reg_##id(void) {     \
        if (bb_test_count >= BB_TEST_MAX) { /* no silent OOB write */     \
            fprintf(stderr, "bb_test: too many tests (max %d) at %s\n",   \
                    BB_TEST_MAX, #id);                                    \
            abort();                                                      \
        }                                                                 \
        bb_tests[bb_test_count] = (bb_test_case){#id, bb_test_##id};      \
        bb_test_count++;                                                  \
    }                                                                     \
    static void bb_test_##id(void)

#define BB_CHECK(cond)                                                          \
    do {                                                                        \
        if (!(cond)) {                                                          \
            printf("FAIL %s (%s:%d): %s\n", bb_test_current, __FILE__, __LINE__, #cond); \
            bb_test_failures++;                                                 \
        }                                                                       \
    } while (0)

#define BB_CHECK_EQ(a, b)                                                       \
    do {                                                                        \
        long long _a = (long long)(a), _b = (long long)(b);                     \
        if (_a != _b) {                                                         \
            printf("FAIL %s (%s:%d): %s == %s (%lld != %lld)\n", bb_test_current, \
                   __FILE__, __LINE__, #a, #b, _a, _b);                         \
            bb_test_failures++;                                                 \
        }                                                                       \
    } while (0)

#ifdef BB_TEST_MAIN
bb_test_case bb_tests[BB_TEST_MAX];
int bb_test_count = 0;
int bb_test_failures = 0;
const char* bb_test_current = "";

static int bb_test_run_all(const char* filter) {
    int ran = 0;
    for (int i = 0; i < bb_test_count; i++) {
        if (filter && !strstr(bb_tests[i].name, filter)) continue;
        bb_test_current = bb_tests[i].name;
        int before = bb_test_failures;
        bb_tests[i].fn();
        ran++;
        if (bb_test_failures == before) printf("ok   %s\n", bb_tests[i].name);
    }
    printf("%d tests, %d failures\n", ran, bb_test_failures);
    return bb_test_failures ? 1 : 0;
}

int main(int argc, char** argv) {
    return bb_test_run_all(argc > 1 ? argv[1] : 0);
}
#endif // BB_TEST_MAIN

#endif // BB_TEST_H

codex
The current advancement block is isolated, and the RNG parity path is straightforward: the default values can preserve the exact old `pg_pick(rng, 5)`, `pg_pick(rng, 2)`, category-pick, skill-pick sequence. I’m checking generated roster structures next so the new tests can compare against base skills and masks directly.
exec
/bin/zsh -lc "sed -n '1,240p' engine/include/bb/gen_teams.h" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
// gen_teams.h — GENERATED by tools/codegen.py from engine/data/spec/. DO NOT EDIT.
// spec-hash: 6f80e7cba73cd837
#ifndef BB_GEN_TEAMS_H
#define BB_GEN_TEAMS_H

#include "bb/gen_skills.h"

typedef enum {
    BB_TEAM_AMAZON,
    BB_TEAM_BLACK_ORC,
    BB_TEAM_BRETONNIAN,
    BB_TEAM_CHAOS_CHOSEN,
    BB_TEAM_CHAOS_DWARF,
    BB_TEAM_CHAOS_RENEGADES,
    BB_TEAM_DARK_ELF,
    BB_TEAM_DWARF,
    BB_TEAM_ELVEN_UNION,
    BB_TEAM_GNOME,
    BB_TEAM_GOBLIN,
    BB_TEAM_HALFLING,
    BB_TEAM_HIGH_ELF,
    BB_TEAM_HUMAN,
    BB_TEAM_IMPERIAL_NOBILITY,
    BB_TEAM_KHORNE,
    BB_TEAM_LIZARDMEN,
    BB_TEAM_NECROMANTIC_HORROR,
    BB_TEAM_NORSE,
    BB_TEAM_NURGLE,
    BB_TEAM_OGRE,
    BB_TEAM_OLD_WORLD_ALLIANCE,
    BB_TEAM_ORC,
    BB_TEAM_SHAMBLING_UNDEAD,
    BB_TEAM_SKAVEN,
    BB_TEAM_SNOTLING,
    BB_TEAM_TOMB_KINGS,
    BB_TEAM_UNDERWORLD_DENIZENS,
    BB_TEAM_VAMPIRE,
    BB_TEAM_WOOD_ELF,
    BB_TEAM_COUNT
} bb_team_id;

#define BB_MAX_POSITIONS 12  // Old World Alliance has 11
#define BB_POS_MAX_SKILLS 10

typedef struct {
    const char* display;
    uint8_t qty_min, qty_max;
    uint16_t cost_k;
    int8_t ma, st, ag, pa, av; // ag/pa/av target numbers; pa 0 = '-'
    uint8_t num_skills;
    uint8_t skills[BB_POS_MAX_SKILLS];      // bb_skill_id
    int8_t skill_values[BB_POS_MAX_SKILLS]; // X param per skill; -1 none
    uint8_t primary_mask;   // bit i = category i (bb_skill_cat)
    uint8_t secondary_mask;
    uint8_t big_guy;
} bb_position_def;

typedef struct {
    const char* id;
    const char* display;
    uint8_t tier;
    uint8_t reroll_cost_k;  // 50/60/70
    uint8_t apothecary;
    uint8_t num_positions;
    bb_position_def positions[BB_MAX_POSITIONS];
} bb_team_def;

extern const bb_team_def bb_team_defs[BB_TEAM_COUNT];

#endif // BB_GEN_TEAMS_H

exec
/bin/zsh -lc "sed -n '270,360p' puffer/bloodbowl/bloodbowl.h" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
    // then destroys nothing the whistle wasn't about to). v1 scope: block
    // declarations only (movement-roll sequencing is a follow-up).
    float reward_k_seq;
    // Possession annuity (Alex, 2026-06-06 — the reward-chain redesign):
    // ending your own team turn HOLDING the ball pays +p to the holder and
    // -p to the opponent (zero-sum transfer at the turn boundary). Holding
    // is an income STREAM, not a lump sum: the free kickoff scoop becomes
    // the entry ticket, protecting the carrier protects the income, and the
    // defense bleeds until it takes the ball away. Max 16 events/side/game,
    // binary each — structurally unfarmable. Replaces the ball_loss fine
    // (the measured possession-poison: every masked arm converged to
    // rational ball-avoidance under loss-fines; kzero@1.7B attempted ZERO
    // kickoff pickups).
    float reward_possession;
    // Rush (GFI) tax: charged per rush square AT DECLARATION (decision-time,
    // dice-independent — the exposure-pricing family). Exists because under
    // scoring scarcity the critic prices failed GFIs at ~nothing (the
    // opponent can't convert turnovers either), so potentials make rushing
    // free income and the policy GFI-spams (~17/ep observed; humans ~2-5).
    float reward_rush_cost;
    // Backplay curriculum (D47): when >0, demo resets rejection-sample the
    // bank for SCORING-PROXIMAL states — a standing carrier within this
    // many squares of their endzone — so the policy experiences touchdowns
    // densely before the start distribution expands backward. 0 = uniform
    // bank sampling (default). Stages launched manually (6 -> 12 -> 0),
    // like the k-anneal chain.
    int demo_endzone_maxdist;
    // Pickup curriculum (D64): when >0, demo resets rejection-sample the bank
    // for BALL-ACQUISITION states — a LOOSE ball (on the ground) within this
    // many Chebyshev squares of a standing player of the team-to-move — so the
    // policy densely experiences the scoop that backplay skips (backplay starts
    // with the ball already HELD). 0 = off (default). Mutually exclusive with
    // demo_endzone_maxdist (backplay takes precedence if both >0). Stages
    // launched manually, expanding outward like the backplay ladder.
    int demo_pickup_maxdist;
    // Post-kickoff pickup drill (Alex, D68): when >0, demo resets
    // rejection-sample the bank for the natural game opening — a LOOSE ball
    // with the team-to-move on team-turn <= this value (1 = strict
    // post-kickoff scoop, 2 = + early recoveries). Unlike the mid-game pickup
    // drill (D67 context-lock failure), the drill state here IS the game's
    // real starting context — 28.5% of the bank qualifies at maxturn 1.
    // Precedence: endzone > pickup > postkick (first nonzero wins).
    int demo_postkick_maxturn;
    // Passing ladder (D72): >0 = demo resets prefer states where the
    // team-to-move holds the ball with a standing downfield receiver within
    // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
    int demo_pass_maxrange;
    // v5 path-actions (D82): when 1, the STEP square head selects ANY
    // reachable destination; the env routes a min-risk path (Dijkstra over
    // dodge/rush costs) and auto-applies it step-by-step, returning control
    // on any interruption (TEST window, knockdown, activation end). The
    // ENGINE is untouched — steps stay atomic and validated. 0 = v4
    // semantics, bit-identical (all macro code is gated on this knob).
    int macro_moves;
    // macro scratch: planned path + reachability of the current MOVE window
    uint8_t macro_px[40], macro_py[40];
    int macro_len, macro_pos, macro_mover;
    int reach_mover, reach_blitz;        // -1 = reach arrays invalid
    float reach_cost[390];
    uint8_t reach_p255[390];             // approx P(path succeeds) for obs B
    int16_t reach_parent[390];           // square idx -> predecessor idx
    uint8_t reach_len[390];
    // Demo-state reset curriculum (Backplay / chess fen_curric pattern,
    // docs/rl-best-practices.md hole #2): with probability demo_reset_pct
    // each episode starts from a uniformly drawn banked mid-game state
    // (resources/bloodbowl/state_bank.bbs, built by
    // validation/build_state_bank.py from FUMBBL replays) instead of a
    // procgen kickoff. 0 = off (default). demo_started flags the CURRENT
    // episode for the Log.
    float demo_reset_pct;
    int demo_started;
    // Procgen controls: held-out-team experiments and fixed-matchup eval.
    // -1 = unconstrained.
    int exclude_team;
    int force_home_team;
    int force_away_team;
    int max_decisions;
    // Spectator rendering (bbe_render.h); NULL until c_render is first called.
    int render_fps;
    void* client;

    bb_match match;
    bb_rng rng;     // in-match dice
    bb_rng procgen; // roster generation stream
    uint64_t seed;
    uint32_t episode;
    int decisions;
    int illegal;
    // Behavioral micro-stat counters for the CURRENT episode (summed into
    // the Log by bbe_finish_episode, zeroed by bbe_reset_match).
    int ep_blocks, ep_blitzes;

exec
/bin/zsh -lc "sed -n '70,100p' puffer/config/bloodbowl.ini" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
# own team turn holding the ball pays +p / -p zero-sum. Holding = income
# stream; suggested 0.03 (full-game control ~ 0.5 ~ one TD). When using it,
# set reward_ball_loss = 0 — the loss-fine was the measured possession
# poison (rational ball-avoidance in every masked arm).
reward_possession = 0.0
# Rush (GFI) tax per square at declaration — decision-time exposure pricing
# for recklessness (under scoring scarcity the critic prices failed GFIs at
# ~zero and potentials make rushing free income). Suggested 0.01-0.02.
reward_rush_cost = 0.0
# Backplay curriculum (D47): >0 = demo resets prefer states with a standing
# carrier within this many squares of their endzone (rejection-sampled), so
# touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
# 0=uniform) like the k-anneal chain.
demo_endzone_maxdist = 0
# Pickup curriculum (D64): >0 = demo resets prefer states with a LOOSE ball
# within this many Chebyshev squares of a standing player of the team-to-move
# (rejection-sampled), so the scoop is experienced densely (backplay skips it
# by starting with the ball held). Expand outward in stages like backplay.
# Mutually exclusive with demo_endzone_maxdist (backplay wins if both >0).
demo_pickup_maxdist = 0
# Post-kickoff scoop drill (D68): >0 = demo resets prefer the natural game
# opening — a LOOSE ball with the team-to-move on team-turn <= N. The drill
# state IS the real game-start context, sidestepping the D67 context-lock
# failure. Bank coverage: turn-1 4,405 states (28.5%), turn-2 748. USE 2 as
# the default stage (Alex): slow teams (dwarves, MV4-5) frequently need two
# turns to reach the ball — maxturn 2 banks the mid-approach "still loose at
# turn 2" continuations so the finish gets dense reps, not just the kick.
# Precedence: endzone > pickup > postkick.
demo_postkick_maxturn = 0
# Passing ladder (D72): >0 = demo resets prefer held-ball states with a
# standing downfield receiver within this Chebyshev pass-range (a state where

exec
/bin/zsh -lc "sed -n '1280,1330p' puffer/bloodbowl/bloodbowl.h" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
                                p->stance != BB_STANCE_STANDING) continue;
                            int rx = tgt0 ? p->x : (BB_PITCH_LEN - 1 - p->x);
                            if (rx >= cx) continue;  // not downfield of carrier
                            int dx = (int)p->x - cp->x; if (dx < 0) dx = -dx;
                            int dy = (int)p->y - cp->y; if (dy < 0) dy = -dy;
                            int rng = dx > dy ? dx : dy;
                            if (rng <= env->demo_pass_maxrange) { hit = 1; break; }
                        }
                        if (hit) break;
                    }
                    idx = (int)(bb_rng_next(&env->procgen) %
                                (uint32_t)bbe_state_bank_n);
                }
            }
            env->match = bbe_state_bank[idx];
            if (env->match.status == BB_STATUS_DECISION &&
                env->match.stack_top > 0) {
                env->demo_started = 1;
            } else {
                env->log.demo_fallbacks += 1.0f;
            }
        }
    }
    if (!env->demo_started) {
        // Procgen controls: exclude_team bars a team from training draws
        // (holdout); force_* pins a side for fixed-matchup eval. NOTE: banked
        // demo states carry their FUMBBL rosters — neither constraint is
        // enforced on the demo path (keep demo_reset_pct = 0 for holdout
        // evals).
        if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
            env->force_away_team >= 0) {
            bb_match_init_forced(&env->match, &env->procgen,
                                 env->force_home_team, env->force_away_team,
                                 env->exclude_team);
        } else {
            bb_match_init_random(&env->match, &env->procgen);
        }
    }
    // Fresh in-match dice stream either way; a resumed state replays under
    // new dice. bb_advance is a no-op for a banked state (already at a
    // DECISION) and runs procgen kickoffs to their first decision.
    bb_rng_seed(&env->rng, env->seed + env->episode * 7919u, 1);
    bb_advance(&env->match, &env->rng);
    bbe_refresh_legal(env);
    env->decisions = 0; // max_decisions budgets from the resume point
    env->illegal = 0;
    env->ep_blocks = env->ep_blitzes = 0;
    env->ep_blocks_thrown = 0;
    memset(env->ep_block_tier, 0, sizeof env->ep_block_tier);
    env->ep_pickup_success = 0;
    env->pending_pickup_slot = -1;

exec
/bin/zsh -lc "sed -n '70,105p' puffer/bloodbowl/binding.c" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
    env->reward_dist_endzone = (float)kw(kwargs, "reward_dist_endzone", 0.0);
    env->reward_injury_inflicted = (float)kw(kwargs, "reward_injury_inflicted", 0.0);
    env->reward_injury_taken = (float)kw(kwargs, "reward_injury_taken", 0.0);
    env->reward_injury_value_scaled = (int)kw(kwargs, "reward_injury_value_scaled", 0.0);
    env->reward_surf_taken = (float)kw(kwargs, "reward_surf_taken", 0.0);
    env->reward_surf_inflicted = (float)kw(kwargs, "reward_surf_inflicted", 0.0);
    // Profile C exposure-EV + sequencing knobs (bb_blockev; spec defaults
    // when enabled: k_kd 0.06, k_value 0.5, k_ball 0.3, k_seq ~0.02).
    env->reward_k_kd = (float)kw(kwargs, "reward_k_kd", 0.0);
    env->reward_k_value = (float)kw(kwargs, "reward_k_value", 0.0);
    env->reward_k_ball = (float)kw(kwargs, "reward_k_ball", 0.0);
    env->reward_k_seq = (float)kw(kwargs, "reward_k_seq", 0.0);
    // Possession annuity transfer per own-turn-ended-holding (suggested 0.03)
    env->reward_possession = (float)kw(kwargs, "reward_possession", 0.0);
    // Rush tax per GFI square at declaration (suggested 0.01-0.02)
    env->reward_rush_cost = (float)kw(kwargs, "reward_rush_cost", 0.0);
    // Backplay curriculum: scoring-proximal demo resets (0 = uniform)
    env->demo_endzone_maxdist = (int)kw(kwargs, "demo_endzone_maxdist", 0.0);
    // Pickup curriculum (D64): loose-ball-near-mover demo resets (0 = off)
    env->demo_pickup_maxdist = (int)kw(kwargs, "demo_pickup_maxdist", 0.0);
    // Post-kickoff scoop drill (D68): loose ball at team-turn <= N (0 = off)
    env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
    // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
    env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
    // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
    env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
    env->reach_mover = -1;
    env->macro_mover = -1;
    env->demo_reset_pct = (float)kw(kwargs, "demo_reset_pct", 0.0);
    env->exclude_team = (int)kw(kwargs, "exclude_team", -1.0);
    env->force_home_team = (int)kw(kwargs, "force_home_team", -1.0);
    env->force_away_team = (int)kw(kwargs, "force_away_team", -1.0);
    env->max_decisions = (int)kw(kwargs, "max_decisions", BBE_MAX_DECISIONS);
    if (env->max_decisions <= 0 || env->max_decisions > BBE_MAX_DECISIONS) {
        env->max_decisions = BBE_MAX_DECISIONS;
    }

exec
/bin/zsh -lc "find . -path './.git' -prune -o -name bloodbowl.ini -print" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 498ms:
./puffer/config/bloodbowl.ini
./vendor/PufferLib/config/bloodbowl.ini

codex
There is a second config copy at `vendor/PufferLib/config/bloodbowl.ini`, so I’ll update both configs as requested. The generated roster header exposes exactly what the tests need: position base skills, primary/secondary category masks, and skill categories through `bb_skill_defs`.
exec
/bin/zsh -lc "sed -n '70,105p' vendor/PufferLib/config/bloodbowl.ini" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
# own team turn holding the ball pays +p / -p zero-sum. Holding = income
# stream; suggested 0.03 (full-game control ~ 0.5 ~ one TD). When using it,
# set reward_ball_loss = 0 — the loss-fine was the measured possession
# poison (rational ball-avoidance in every masked arm).
reward_possession = 0.0
# Rush (GFI) tax per square at declaration — decision-time exposure pricing
# for recklessness (under scoring scarcity the critic prices failed GFIs at
# ~zero and potentials make rushing free income). Suggested 0.01-0.02.
reward_rush_cost = 0.0
# Backplay curriculum (D47): >0 = demo resets prefer states with a standing
# carrier within this many squares of their endzone (rejection-sampled), so
# touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
# 0=uniform) like the k-anneal chain.
demo_endzone_maxdist = 0
# Surfs: charged at the deterministic crowd-push event, dice-independent.
# Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
reward_surf_taken = 0.0
reward_surf_inflicted = 0.0
# --- Profile C: exposure-EV transfer + sequencing charge (D33) -------------
# Zero-sum transfer at every block/blitz DECLARATION, priced by the
# closed-form skill-transformed block tree (engine bb_blockev, validated by
# make blockev-mc + 12 unit tests): k_kd * P(def down) + k_value *
# P(def removed) * cost/100k + k_ball * P(ball dislodged). Dice outcomes
# carry no shaping. Spec values: k_kd 0.06 (routine 2d+Block ~ +0.03),
# k_value 0.5 (Wardancer-vs-MB ~ -0.08/block), k_ball 0.3. Per-step
# magnitude (panel-recomputed): a realistic strong case — 3d MB+Claws blitz
# on a 140k AV8 carrier — reaches ~0.5; the theoretical P=1 bound on a 140k
# victim is 1.06, at the clamp edge ALONE. No realistic step in this config
# exceeds the [-1,1] clamp (declaration and resolution rewards land on
# different decision steps), but budget any NEW knob against ~0.5/step.
reward_k_kd = 0.0
reward_k_value = 0.0
reward_k_ball = 0.0
# Sequencing charge: k_seq * P(turnover of this block) * pending safe
# activations, charged to the acting team at declaration; exempt on the
# team's last turn of the half. Suggested 0.02 (10-pending worst case 0.2).

exec
/bin/zsh -lc "sed -n '1,200p' Makefile" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
# bloodbowl-rl engine build
#
# Targets:
#   make            -> build libbb.a + test runner, run tests
#   make test       -> run unit tests (optionally TEST=<filter>)
#   make asan       -> rebuild + run tests under ASan/UBSan
#   make fuzz       -> build libFuzzer harnesses (clang only)
#   make clean
CC      ?= clang
BUILD   ?= build
CFLAGS  ?= -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include
LDFLAGS ?=

SAN_FLAGS = -fsanitize=address,undefined -fno-omit-frame-pointer -O1

SRC      := $(wildcard engine/src/*.c)
OBJ      := $(SRC:engine/src/%.c=$(BUILD)/obj/%.o)
TEST_SRC := $(wildcard engine/tests/test_*.c)
LIB      := $(BUILD)/libbb.a
TESTBIN  := $(BUILD)/bb_tests

.PHONY: all test asan fuzz coverage coverage-run lockstep blockev-mc clean

all: test

$(BUILD)/obj/%.o: engine/src/%.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -MMD -MP -c $< -o $@

-include $(OBJ:.o=.d)

# libbb.a is built from ONE relocatable object (ld -r) so constructor-based
# skill registrations are never dropped by archive member selection — plain
# `-lbb` consumers get the full engine (Codex finding).
$(LIB): $(OBJ)
	@mkdir -p $(BUILD)
	ld -r $(OBJ) -o $(BUILD)/bb_all.o
	ar rcs $@ $(BUILD)/bb_all.o

# NOTE: tests link the object files directly (not libbb.a) — skill hook
# registrations live in constructor-only objects that a static archive would
# drop. External consumers of libbb.a must use -force_load / --whole-archive.
$(TESTBIN): $(TEST_SRC) engine/tests/bb_test.h engine/tests/bb_fixtures.h engine/tests/bb_test_main.c $(OBJ)
	$(CC) $(CFLAGS) -Iengine/tests engine/tests/bb_test_main.c $(TEST_SRC) $(OBJ) -o $@ $(LDFLAGS)

test: $(TESTBIN)
	./$(TESTBIN) $(TEST)

blockev-mc: $(OBJ)
	$(CC) $(CFLAGS) -Iengine/tests tools/blockev_mc.c $(OBJ) -o $(BUILD)/blockev_mc -lm
	./$(BUILD)/blockev_mc

asan:
	$(MAKE) BUILD=build/asan CFLAGS="-std=c11 $(SAN_FLAGS) -Wall -Wextra -Werror -Iengine/include" test

# libFuzzer harness. Apple clang has no libFuzzer: use Homebrew LLVM
# (brew install llvm) on macOS, or any stock clang on Linux (CI nightly).
FUZZ_CC ?= $(shell test -x /opt/homebrew/opt/llvm/bin/clang && echo /opt/homebrew/opt/llvm/bin/clang || echo clang)
fuzz:
	@mkdir -p build/fuzz engine/tests/corpus
	$(FUZZ_CC) -std=c11 -O1 -g -fsanitize=fuzzer,address,undefined -Iengine/include \
		engine/tests/fuzz_match.c $(SRC) -o build/fuzz/bb_fuzz
	@echo "run: ./build/fuzz/bb_fuzz -max_total_time=300 engine/tests/corpus/"

# FUMBBL lockstep differential runner (validation layer 7).
# Single-TU build through the PufferLib env amalgamation (bloodbowl.h includes
# every engine .c) so the runner carries the EXACT training encoders for
# --dump-pairs. -Wno-unused-function: the env header defines the full binding
# surface (c_step, c_render, ...); the runner only uses the encoders.
lockstep:
	$(CC) $(CFLAGS) -Ipuffer/bloodbowl -Wno-unused-function \
		tools/bb_lockstep.c -o $(BUILD)/bb_lockstep
	@echo "run: ./$(BUILD)/bb_lockstep validation/lockstep/<id>.jsonl"

# Regenerate golden traces (explicit; goldens change when rules change).
# Links objects directly (constructor-registered skill hooks would be dropped
# from a static archive).
goldens: $(OBJ)
	$(CC) $(CFLAGS) tools/gen_goldens.c $(OBJ) -o $(BUILD)/gen_goldens
	./$(BUILD)/gen_goldens engine/tests/golden

# Coverage counters are compiled in ONLY here (-DBB_COVERAGE): the OpenMP
# training build must not share-write the process-global counters (review P3).
coverage:
	$(MAKE) BUILD=build/coverage \
		CFLAGS="-std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -DBB_COVERAGE" \
		coverage-run

coverage-run: $(OBJ)
	$(CC) $(CFLAGS) tools/coverage_report.c $(OBJ) -o $(BUILD)/coverage_report
	./$(BUILD)/coverage_report

clean:
	rm -rf $(BUILD)

exec
/bin/zsh -lc "find engine -maxdepth 2 -name Makefile -print -exec sed -n '1,220p' {} \\;" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
exec
/bin/zsh -lc "sed -n '1,180p' engine/include/bb/bb_skills.h" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
// bb_skills.h — skill hook surface.
//
// Phase 2 implements a STARTER SET of game-defining skills wired into the core
// procedures: loner, dodge (reroll + stumble), block, wrestle, tackle, guard,
// thick_skull, stunty, sure_feet, sure_hands, sure hands, pass, catch, sprint.
// The full ~108 skill/trait set lands in Phase 3 through these same hooks —
// procedures never test skill ids directly except via this module.
#ifndef BB_SKILLS_H
#define BB_SKILLS_H

#include "bb/bb_match.h"
#include "bb/gen_skills.h"

// Test kinds used by the generic TEST procedure.
typedef enum {
    BB_TEST_DODGE = 0,
    BB_TEST_RUSH,
    BB_TEST_PICKUP,
    BB_TEST_PASS,
    BB_TEST_CATCH,
    BB_TEST_LONER,      // internal: team-reroll gate
    BB_TEST_JUMP,       // jumping over a prone/stunned player (or Leap/Pogo)
    BB_TEST_STANDUP,    // MA<3 stand-up roll (Timmm-ber! modifies)
    BB_TEST_GENERIC,
    BB_TEST_TTM,        // Throw/Kick Team-mate PA test (rolled inline in
                        // proc_ttm; hook seam for auras like Disturbing
                        // Presence — review M12)
    BB_TEST_KIND_COUNT
} bb_test_kind;

// reroll_kinds (bb_hooks.h) and skill_rr_used (bb_types.h) are uint16 masks
// indexed by bb_test_kind; a kind >= 16 would silently truncate to bit 0.
_Static_assert(BB_TEST_KIND_COUNT <= 16,
               "bb_test_kind must fit the uint16 re-roll masks");

// Skill-granted self-rerolls live in the hook table: see bb_hook_reroll
// (bb_hooks.h), which takes the test ctx so interceptions are excluded.

// Loner (X+) gate value for team rerolls; 0 if player has no Loner.
int bb_loner_value(const bb_match* m, int slot);

// Max rushes (GFIs) this activation (2, or 3 with Sprint).
int bb_max_rushes(const bb_match* m, int slot);

// Whether `slot` uses the Stunty injury bands.
bool bb_is_stunty(const bb_match* m, int slot);

// Block-face interactions (starter set).
bool bb_has_block(const bb_match* m, int slot);
bool bb_has_wrestle(const bb_match* m, int slot);
bool bb_has_tackle_adjacent(const bb_match* m, int slot); // any standing adjacent opponent with Tackle
bool bb_has_dodge_skill(const bb_match* m, int slot);

// Guard: assist even while marked.
bool bb_can_assist(const bb_match* m, int assister, int target_slot);

#endif // BB_SKILLS_H

exec
/bin/zsh -lc "rg -n \"selftest|test:|bb_test|engine_self|fuzz\" Makefile engine puffer -g 'Makefile' -g '*.sh' -g '*.py'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
Makefile:7:#   make fuzz       -> build libFuzzer harnesses (clang only)
Makefile:20:TESTBIN  := $(BUILD)/bb_tests
Makefile:22:.PHONY: all test asan fuzz coverage coverage-run lockstep blockev-mc clean
Makefile:43:$(TESTBIN): $(TEST_SRC) engine/tests/bb_test.h engine/tests/bb_fixtures.h engine/tests/bb_test_main.c $(OBJ)
Makefile:44:	$(CC) $(CFLAGS) -Iengine/tests engine/tests/bb_test_main.c $(TEST_SRC) $(OBJ) -o $@ $(LDFLAGS)
Makefile:46:test: $(TESTBIN)
Makefile:59:fuzz:
Makefile:60:	@mkdir -p build/fuzz engine/tests/corpus
Makefile:61:	$(FUZZ_CC) -std=c11 -O1 -g -fsanitize=fuzzer,address,undefined -Iengine/include \
Makefile:62:		engine/tests/fuzz_match.c $(SRC) -o build/fuzz/bb_fuzz
Makefile:63:	@echo "run: ./build/fuzz/bb_fuzz -max_total_time=300 engine/tests/corpus/"

exec
/bin/zsh -lc 'rg -n "typedef.*bb_skillset|bb_has_skill|bb_add_skill|BB_TEAM_SLOTS|BB_TEAM_OF|BB_LOC_" engine/include/bb/bb_types.h engine/include/bb/*.h' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
engine/include/bb/bb_types.h:18:#define BB_TEAM_SLOTS 16   // max players on a matchday roster per team
engine/include/bb/bb_types.h:25:#define BB_TEAM_OF(p) ((p) >> 4)         // player slot -> team
engine/include/bb/bb_types.h:38:static inline bool bb_has_skill(const bb_skillset* s, int id) {
engine/include/bb/bb_types.h:41:static inline void bb_add_skill(bb_skillset* s, int id) {
engine/include/bb/bb_types.h:50:    BB_LOC_ON_PITCH = 0,
engine/include/bb/bb_types.h:51:    BB_LOC_RESERVES,
engine/include/bb/bb_types.h:52:    BB_LOC_KO,
engine/include/bb/bb_types.h:53:    BB_LOC_CAS,       // casualty box (out for the match)
engine/include/bb/bb_types.h:54:    BB_LOC_SENT_OFF,  // ejected by the ref
engine/include/bb/bb_types.h:55:    BB_LOC_ABSENT,    // empty roster slot
engine/include/bb/bb_types.h:86:    uint8_t x, y;              // valid when location == BB_LOC_ON_PITCH
engine/include/bb/bb_types.h:18:#define BB_TEAM_SLOTS 16   // max players on a matchday roster per team
engine/include/bb/bb_types.h:25:#define BB_TEAM_OF(p) ((p) >> 4)         // player slot -> team
engine/include/bb/bb_types.h:38:static inline bool bb_has_skill(const bb_skillset* s, int id) {
engine/include/bb/bb_types.h:41:static inline void bb_add_skill(bb_skillset* s, int id) {
engine/include/bb/bb_types.h:50:    BB_LOC_ON_PITCH = 0,
engine/include/bb/bb_types.h:51:    BB_LOC_RESERVES,
engine/include/bb/bb_types.h:52:    BB_LOC_KO,
engine/include/bb/bb_types.h:53:    BB_LOC_CAS,       // casualty box (out for the match)
engine/include/bb/bb_types.h:54:    BB_LOC_SENT_OFF,  // ejected by the ref
engine/include/bb/bb_types.h:55:    BB_LOC_ABSENT,    // empty roster slot
engine/include/bb/bb_types.h:86:    uint8_t x, y;              // valid when location == BB_LOC_ON_PITCH
engine/include/bb/bb_hooks.h:95:        bb_add_skill(&bb_aura_skills, BB_SK_##skill);                        \

exec
/bin/zsh -lc "sed -n '1,170p' engine/include/bb/bb_types.h" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
// bb_types.h — core constants and plain types for the BB2025 engine.
// Everything in the engine is fixed-size and memcpy-able; no heap in the hot loop.
#ifndef BB_TYPES_H
#define BB_TYPES_H

#include <stdint.h>
#include <stdbool.h>

// --- Pitch ----------------------------------------------------------------
// x runs along the length of the pitch (0..25), y across the width (0..14).
// x == 0 is the HOME end zone column; x == 25 is the AWAY end zone column.
// Home team attacks toward x == 25 (scores there); away scores at x == 0.
// Wide zones: y in [0,3] and [11,14]. Centre field: y in [4,10].
// Line of scrimmage columns: x == 12 (home side) / x == 13 (away side).
#define BB_PITCH_LEN 26
#define BB_PITCH_WID 15

#define BB_TEAM_SLOTS 16   // max players on a matchday roster per team
#define BB_NUM_PLAYERS 32  // slots 0..15 home, 16..31 away
#define BB_ON_PITCH_MAX 11

#define BB_HOME 0
#define BB_AWAY 1
#define BB_NO_PLAYER 0xFF
#define BB_TEAM_OF(p) ((p) >> 4)         // player slot -> team
#define BB_SLOT_OF(p) ((p) & 0x0F)       // player slot -> index within team

// --- Skills / traits ------------------------------------------------------
// Skill and trait ids are generated from engine/data/spec/skills.yaml by
// tools/codegen.py into gen_skills.h (BB_SK_* enum). The bitmask must hold
// every skill + trait + star-player bespoke rule.
#define BB_SKILL_WORDS 3   // 192 bits

typedef struct {
    uint64_t w[BB_SKILL_WORDS];
} bb_skillset;

static inline bool bb_has_skill(const bb_skillset* s, int id) {
    return (s->w[id >> 6] >> (id & 63)) & 1u;
}
static inline void bb_add_skill(bb_skillset* s, int id) {
    s->w[id >> 6] |= (uint64_t)1 << (id & 63);
}
static inline void bb_clear_skill(bb_skillset* s, int id) {
    s->w[id >> 6] &= ~((uint64_t)1 << (id & 63));
}

// --- Player ----------------------------------------------------------------
typedef enum {
    BB_LOC_ON_PITCH = 0,
    BB_LOC_RESERVES,
    BB_LOC_KO,
    BB_LOC_CAS,       // casualty box (out for the match)
    BB_LOC_SENT_OFF,  // ejected by the ref
    BB_LOC_ABSENT,    // empty roster slot
} bb_loc;

typedef enum {
    BB_STANCE_STANDING = 0,
    BB_STANCE_PRONE,
    BB_STANCE_STUNNED,
    BB_STANCE_STUNNED_USED, // stunned players flip to prone at the END of their
                            // team's next turn; this marks the intermediate step
} bb_stance;

// Transient per-activation / per-turn player flags.
enum {
    BB_PF_USED          = 1 << 0,  // has activated this team turn
    BB_PF_ACTIVATING    = 1 << 1,  // currently the active player
    BB_PF_DISTRACTED    = 1 << 2,  // BB2025 Distracted status (until end of next activation)
    BB_PF_HAS_BALL      = 1 << 3,
    BB_PF_BLITZED       = 1 << 4,  // performed the team blitz action this turn
    BB_PF_ROOTED        = 1 << 5,  // Take Root etc.: may not move
    BB_PF_HYPNOTIZED    = 1 << 6,
    BB_PF_USED_SKILL_A  = 1 << 7,  // generic once-per-X skill-use latches; the
    BB_PF_USED_SKILL_B  = 1 << 8,  // mapping is procedure-specific
    BB_PF_SECURED_BALL  = 1 << 9,  // BB2025 Secure the Ball performed
    BB_PF_NO_TZ         = 1 << 10, // currently exerts no tackle zone (computed conditions
                                   // also apply; this latches e.g. Hypnotic Gaze)
    BB_PF_EYE_GOUGED    = 1 << 11, // cannot assist until next activated
} ;

typedef struct {
    bb_skillset skills;
    int8_t ma, st, ag, pa, av; // effective stats; ag/pa/av are target numbers, pa 0 = "-"
    uint8_t x, y;              // valid when location == BB_LOC_ON_PITCH
    uint8_t location;          // bb_loc
    uint8_t stance;            // bb_stance
    uint16_t flags;            // BB_PF_*
    uint8_t moved;             // squares moved this activation
    uint8_t rushes;            // rushes (GFIs) used this activation
    uint8_t position_id;       // index into the roster's position table (for obs)
    uint8_t star_id;           // 0 = regular player, else star player id + 1
    int8_t niggling;           // accumulated niggling injuries (league play)
    uint8_t spp_game;          // SPP events this match (for league mode)
    uint16_t skill_rr_used;    // bitmask by bb_test_kind: skill re-rolls are
                               // once per TURN per player (cleared at turn start)
    int8_t p_loner;            // Loner (X+) parameter (default 4; Ogres 3)
    int8_t p_bloodlust;        // Bloodlust (X+) parameter (0 = none)
} bb_player;

// --- Ball -------------------------------------------------------------------
typedef enum {
    BB_BALL_OFF_PITCH = 0, // pre-kickoff / out of bounds being thrown in
    BB_BALL_ON_GROUND,
    BB_BALL_HELD,          // carried by .carrier
    BB_BALL_IN_AIR,        // mid-pass/kick scatter resolution
} bb_ball_state;

typedef struct {
    uint8_t state;   // bb_ball_state
    uint8_t x, y;
    uint8_t carrier; // player slot or BB_NO_PLAYER
} bb_ball;

// --- Dice -------------------------------------------------------------------
// Block dice faces.
typedef enum {
    BB_BD_ATTACKER_DOWN = 1, // "skull"
    BB_BD_BOTH_DOWN,
    BB_BD_PUSH_1,            // two push faces on the die
    BB_BD_PUSH_2,
    BB_BD_STUMBLE,           // "defender stumbles"
    BB_BD_POW,               // "defender down"
} bb_block_die;

// --- Weather ----------------------------------------------------------------
typedef enum {
    BB_WEATHER_SWELTERING = 0,
    BB_WEATHER_SUNNY,
    BB_WEATHER_PERFECT,
    BB_WEATHER_RAIN,
    BB_WEATHER_BLIZZARD,
} bb_weather;

#endif // BB_TYPES_H

codex
I’m going to make the code edits now: add the parameter struct/API in the match header, thread it through procgen, add env fields and config keys, then extend `test_match.c` with procgen-specific assertions. Keeping the changes local and in the house style.
apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/engine/include/bb/bb_match.h
diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.

diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.

apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/engine/src/bb_procgen.c
diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }

diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }

codex
The engine wrappers are in place, and the default wrapper path still enters with `{4, 2, 0.0f}` before any procgen draws. I’ve also gated the new float draw strictly behind `skillup_secondary_pct > 0.0f`, which is the important parity guard.
apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/puffer/bloodbowl/bloodbowl.h
diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under

diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under

apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/puffer/bloodbowl/binding.c
diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under

diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under

exec
/bin/zsh -lc "sed -n '84,120p' puffer/config/bloodbowl.ini && sed -n '84,125p' vendor/PufferLib/config/bloodbowl.ini" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
# Pickup curriculum (D64): >0 = demo resets prefer states with a LOOSE ball
# within this many Chebyshev squares of a standing player of the team-to-move
# (rejection-sampled), so the scoop is experienced densely (backplay skips it
# by starting with the ball held). Expand outward in stages like backplay.
# Mutually exclusive with demo_endzone_maxdist (backplay wins if both >0).
demo_pickup_maxdist = 0
# Post-kickoff scoop drill (D68): >0 = demo resets prefer the natural game
# opening — a LOOSE ball with the team-to-move on team-turn <= N. The drill
# state IS the real game-start context, sidestepping the D67 context-lock
# failure. Bank coverage: turn-1 4,405 states (28.5%), turn-2 748. USE 2 as
# the default stage (Alex): slow teams (dwarves, MV4-5) frequently need two
# turns to reach the ball — maxturn 2 banks the mid-approach "still loose at
# turn 2" continuations so the finish gets dense reps, not just the kick.
# Precedence: endzone > pickup > postkick.
demo_postkick_maxturn = 0
# Passing ladder (D72): >0 = demo resets prefer held-ball states with a
# standing downfield receiver within this Chebyshev pass-range (a state where
# throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
# D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
demo_pass_maxrange = 0
# v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
# destination; the env routes a min-risk path and auto-executes it, returning
# control on interruptions. 0 = v4 stepwise semantics (bit-identical).
macro_moves = 0
# Surfs: charged at the deterministic crowd-push event, dice-independent.
# Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
reward_surf_taken = 0.0
reward_surf_inflicted = 0.0
# --- Profile C: exposure-EV transfer + sequencing charge (D33) -------------
# Zero-sum transfer at every block/blitz DECLARATION, priced by the
# closed-form skill-transformed block tree (engine bb_blockev, validated by
# make blockev-mc + 12 unit tests): k_kd * P(def down) + k_value *
# P(def removed) * cost/100k + k_ball * P(ball dislodged). Dice outcomes
# carry no shaping. Spec values: k_kd 0.06 (routine 2d+Block ~ +0.03),
# k_value 0.5 (Wardancer-vs-MB ~ -0.08/block), k_ball 0.3. Per-step
# magnitude (panel-recomputed): a realistic strong case — 3d MB+Claws blitz
# on a 140k AV8 carrier — reaches ~0.5; the theoretical P=1 bound on a 140k
# Surfs: charged at the deterministic crowd-push event, dice-independent.
# Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
reward_surf_taken = 0.0
reward_surf_inflicted = 0.0
# --- Profile C: exposure-EV transfer + sequencing charge (D33) -------------
# Zero-sum transfer at every block/blitz DECLARATION, priced by the
# closed-form skill-transformed block tree (engine bb_blockev, validated by
# make blockev-mc + 12 unit tests): k_kd * P(def down) + k_value *
# P(def removed) * cost/100k + k_ball * P(ball dislodged). Dice outcomes
# carry no shaping. Spec values: k_kd 0.06 (routine 2d+Block ~ +0.03),
# k_value 0.5 (Wardancer-vs-MB ~ -0.08/block), k_ball 0.3. Per-step
# magnitude (panel-recomputed): a realistic strong case — 3d MB+Claws blitz
# on a 140k AV8 carrier — reaches ~0.5; the theoretical P=1 bound on a 140k
# victim is 1.06, at the clamp edge ALONE. No realistic step in this config
# exceeds the [-1,1] clamp (declaration and resolution rewards land on
# different decision steps), but budget any NEW knob against ~0.5/step.
reward_k_kd = 0.0
reward_k_value = 0.0
reward_k_ball = 0.0
# Sequencing charge: k_seq * P(turnover of this block) * pending safe
# activations, charged to the acting team at declaration; exempt on the
# team's last turn of the half. Suggested 0.02 (10-pending worst case 0.2).
reward_k_seq = 0.0
# Demo-state reset curriculum (Backplay / chess fen_curric_pct pattern,
# docs/rl-best-practices.md hole #2): fraction of episodes that start from a
# banked FUMBBL mid-game state (resources/bloodbowl/state_bank.bbs — built by
# validation/build_state_bank.py, staged by tools/install_puffer_env.sh)
# instead of a procgen kickoff. Missing bank = plain procgen resets. Keep a
# held-out from-kickoff eval (pct 0) to watch critic distribution skew; keep
# 0 for holdout evals — banked states carry their FUMBBL rosters, so
# exclude/force_team are not enforced on demo episodes. Chess trains at 0.9.
demo_reset_pct = 0.0
# Holdout / fixed-matchup controls (-1 = off): exclude_team bars a team id
# from training draws; force_*_team pins a side for evaluation.
exclude_team = -1
force_home_team = -1
force_away_team = -1
max_decisions = 4096
# Spectator playback speed: decisions/sec when rendering (puffer eval).
render_fps = 60

[policy]

diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under

apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/puffer/config/bloodbowl.ini
/Users/alexanderhuth/Code/bloodbowl-rl/vendor/PufferLib/config/bloodbowl.ini
diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

codex
The env binding now passes procgen params into both forced and random reset paths, and both config files have matching defaults. I’m adding the test spine next: old/new default parity, off switch, primary/secondary mask guarantees, catalogue coverage, cap/structure, and deterministic same-seed behavior.
apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/engine/tests/test_match.c
diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..7e4f0bb0bdb0299b06bd352e53b6fd191e7f61e7
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,184 @@
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
+    BB_CHECK_EQ(memcmp(&r1, &r2, sizeof(bb_rng)), 0);
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
+    BB_CHECK_EQ(memcmp(&r1, &r2, sizeof(bb_rng)), 0);
+}
+
 BB_TEST(match_procgen_games_complete) {
     for (uint64_t seed = 1; seed <= 12; seed++) {
         bb_match m;
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..7e4f0bb0bdb0299b06bd352e53b6fd191e7f61e7
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,184 @@
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
+    BB_CHECK_EQ(memcmp(&r1, &r2, sizeof(bb_rng)), 0);
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
+    BB_CHECK_EQ(memcmp(&r1, &r2, sizeof(bb_rng)), 0);
+}
+
 BB_TEST(match_procgen_games_complete) {
     for (uint64_t seed = 1; seed <= 12; seed++) {
         bb_match m;
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

codex
The new procgen tests are in the existing constructor-based harness, alongside the existing match/procgen tests. I’m running the engine test target now; if anything shakes loose it should be either C warning strictness or a test expectation that needs to match the live roster data more carefully.
exec
/bin/zsh -lc 'make test' in /Users/alexanderhuth/Code/bloodbowl-rl
diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..7e4f0bb0bdb0299b06bd352e53b6fd191e7f61e7
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,184 @@
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
+    BB_CHECK_EQ(memcmp(&r1, &r2, sizeof(bb_rng)), 0);
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
+    BB_CHECK_EQ(memcmp(&r1, &r2, sizeof(bb_rng)), 0);
+}
+
 BB_TEST(match_procgen_games_complete) {
     for (uint64_t seed = 1; seed <= 12; seed++) {
         bb_match m;
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

 exited 2 in 3699ms:
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -MMD -MP -c engine/src/bb_hooks.c -o build/obj/bb_hooks.o
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -MMD -MP -c engine/src/bb_match.c -o build/obj/bb_match.o
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -MMD -MP -c engine/src/bb_procgen.c -o build/obj/bb_procgen.o
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -MMD -MP -c engine/src/bb_skills.c -o build/obj/bb_skills.o
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -MMD -MP -c engine/src/proc_ball.c -o build/obj/proc_ball.o
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -MMD -MP -c engine/src/proc_block.c -o build/obj/proc_block.o
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -MMD -MP -c engine/src/proc_match.c -o build/obj/proc_match.o
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -MMD -MP -c engine/src/proc_move.c -o build/obj/proc_move.o
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -MMD -MP -c engine/src/proc_table.c -o build/obj/proc_table.o
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -MMD -MP -c engine/src/proc_test.c -o build/obj/proc_test.o
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -MMD -MP -c engine/src/proc_ttm.c -o build/obj/proc_ttm.o
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -MMD -MP -c engine/src/proc_turn.c -o build/obj/proc_turn.o
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -MMD -MP -c engine/src/skills_agility.c -o build/obj/skills_agility.o
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -MMD -MP -c engine/src/skills_core.c -o build/obj/skills_core.o
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -MMD -MP -c engine/src/skills_devious_traits.c -o build/obj/skills_devious_traits.o
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -MMD -MP -c engine/src/skills_mutation_passing.c -o build/obj/skills_mutation_passing.o
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -Iengine/tests engine/tests/bb_test_main.c engine/tests/test_blockev.c engine/tests/test_gen_data.c engine/tests/test_golden.c engine/tests/test_match.c engine/tests/test_replay.c engine/tests/test_rng.c engine/tests/test_rules_ball.c engine/tests/test_rules_blocking.c engine/tests/test_rules_injury.c engine/tests/test_rules_movement.c engine/tests/test_rules_structure.c engine/tests/test_skills_devious_traits.c engine/tests/test_skills_mutation_passing.c build/obj/bb_blockev.o build/obj/bb_hooks.o build/obj/bb_match.o build/obj/bb_procgen.o build/obj/bb_replay.o build/obj/bb_rng.o build/obj/bb_skills.o build/obj/gen_skills.o build/obj/gen_tables.o build/obj/gen_teams.o build/obj/proc_ball.o build/obj/proc_block.o build/obj/proc_match.o build/obj/proc_move.o build/obj/proc_table.o build/obj/proc_test.o build/obj/proc_ttm.o build/obj/proc_turn.o build/obj/skills_agility.o build/obj/skills_core.o build/obj/skills_devious_traits.o build/obj/skills_mutation_passing.o -o build/bb_tests 
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
FAIL match_procgen_default_params_match_legacy_api (engine/tests/test_match.c:282): memcmp(&r1, &r2, sizeof(bb_rng)) == 0 (1 != 0)
ok   match_procgen_skillups_off_keeps_base_skills
ok   match_procgen_primary_only_uses_primary_categories
ok   match_procgen_secondary_only_uses_secondary_or_primary_fallback
ok   match_procgen_skillups_reach_full_learnable_catalogue
ok   match_procgen_cranked_params_respect_cap_and_structure
FAIL match_procgen_params_are_deterministic (engine/tests/test_match.c:383): memcmp(&r1, &r2, sizeof(bb_rng)) == 0 (1 != 0)
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
345 tests, 2 failures
make: *** [test] Error 1

codex
The first test run built cleanly and the new behavior tests passed, but two rng-struct memcmp checks failed while the match memcmp checks passed. That looks like padding or callback pointer representation in `bb_rng`, not procgen behavior, so I’m tightening those tests to compare the deterministic state fields instead of raw struct bytes.
exec
/bin/zsh -lc "sed -n '1,120p' engine/src/bb_rng.c" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
#include "bb/bb_rng.h"

// PCG32 (Melissa O'Neill, pcg-random.org; Apache-2.0 reference algorithm).
static uint32_t pcg32_next(bb_rng* rng) {
    uint64_t old = rng->state;
    rng->state = old * 6364136223846793005ULL + rng->inc;
    uint32_t xorshifted = (uint32_t)(((old >> 18u) ^ old) >> 27u);
    uint32_t rot = (uint32_t)(old >> 59u);
    return (xorshifted >> rot) | (xorshifted << ((-rot) & 31));
}

void bb_rng_seed(bb_rng* rng, uint64_t seed, uint64_t stream) {
    rng->mode = BB_RNG_PRNG;
    rng->error = 0;
    rng->script = 0;
    rng->script_len = rng->script_pos = 0;
    rng->sink = 0;
    rng->sink_user = 0;
    rng->state = 0u;
    rng->inc = (stream << 1u) | 1u;
    pcg32_next(rng);
    rng->state += seed;
    pcg32_next(rng);
}

void bb_rng_script(bb_rng* rng, const uint8_t* values, int len) {
    rng->mode = BB_RNG_SCRIPT;
    rng->error = 0;
    rng->script = values;
    rng->script_len = len;
    rng->script_pos = 0;
    rng->sink = 0;
    rng->sink_user = 0;
    rng->state = rng->inc = 0;
}

void bb_rng_set_sink(bb_rng* rng, bb_dice_sink sink, void* user) {
    rng->sink = sink;
    rng->sink_user = user;
}

uint32_t bb_rng_next(bb_rng* rng) {
    return pcg32_next(rng);
}

int bb_roll(bb_rng* rng, int sides) {
    int value;
    if (rng->mode == BB_RNG_SCRIPT) {
        if (rng->script_pos >= rng->script_len) {
            rng->error = 1;
            return 1; // keep the engine well-defined; caller checks bb_rng_error
        }
        value = rng->script[rng->script_pos++];
        if (value < 1 || value > sides) {
            rng->error = 1;
            return 1;
        }
    } else {
        // Rejection sampling for an unbiased 1..sides.
        uint32_t bound = (uint32_t)sides;
        uint32_t threshold = -bound % bound; // (2^32 - bound) % bound
        uint32_t r;
        do {
            r = pcg32_next(rng);
        } while (r < threshold);
        value = (int)(r % bound) + 1;
    }
    if (rng->sink) rng->sink(rng->sink_user, sides, value);
    return value;
}

diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..7e4f0bb0bdb0299b06bd352e53b6fd191e7f61e7
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,184 @@
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
+    BB_CHECK_EQ(memcmp(&r1, &r2, sizeof(bb_rng)), 0);
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
+    BB_CHECK_EQ(memcmp(&r1, &r2, sizeof(bb_rng)), 0);
+}
+
 BB_TEST(match_procgen_games_complete) {
     for (uint64_t seed = 1; seed <= 12; seed++) {
         bb_match m;
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/engine/tests/test_match.c
diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..99774f8dfb71f3f99dfd14ddaa48a8432093ee30
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,192 @@
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
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..99774f8dfb71f3f99dfd14ddaa48a8432093ee30
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,192 @@
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
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

codex
I replaced the raw `bb_rng` memcmp with an explicit field comparison, since the RNG API seeds the fields deterministically but the struct may still have padding bytes. Running the full test target again now.
exec
/bin/zsh -lc 'make test' in /Users/alexanderhuth/Code/bloodbowl-rl
diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..99774f8dfb71f3f99dfd14ddaa48a8432093ee30
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,192 @@
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
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

 succeeded in 1996ms:
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
345 tests, 0 failures

codex
Full `make test` is green now: `345 tests, 0 failures`, including the seven new procgen cases. I’m checking the puffer build path next and will try the local binding build without launching anything.
exec
/bin/zsh -lc "find . -maxdepth 3 \\( -name build.sh -o -name Makefile -o -name pyproject.toml -o -name setup.py \\) -print" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
./Makefile
./vendor/botbowl/setup.py
./vendor/PufferLib/pyproject.toml
./vendor/PufferLib/build.sh
./vendor/fumbbl_replays/pyproject.toml
./vendor/fumbbl_replays/setup.py

exec
/bin/zsh -lc "ls puffer && find puffer -maxdepth 2 -type f | sed -n '1,80p'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
bloodbowl
config
puffer/config/bloodbowl.ini
puffer/bloodbowl/bbe_microstats_probe.c
puffer/bloodbowl/binding.c
puffer/bloodbowl/bloodbowl.c
puffer/bloodbowl/bbe_render.h
puffer/bloodbowl/bbe_profile.c
puffer/bloodbowl/bloodbowl.h

exec
/bin/zsh -lc "rg -n \"build\\.sh|setup.py|pip install|puffer\" README.md CLAUDE.md puffer vendor/PufferLib -g '*.md' -g '*.sh' -g 'Makefile' -g '*.py'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
README.md:19:puffer/       PufferLib binding (ocean/bloodbowl pattern)
CLAUDE.md:11:| `puffer-env-dev` | PufferLib binding, build, training CLI, selfplay config |
CLAUDE.md:31:- **obs-v4 = 2782 bytes** (probability planes A1/A2/B; spec `docs/obs-v4-spec.md`). **Three OBS_SIZE sync points must agree** (static asserts catch 2 of 3): `BBE_OBS_SIZE` in `puffer/bloodbowl/bloodbowl.h`, `#define OBS_SIZE` in `puffer/bloodbowl/binding.c:8`, `--obs-size` in `training/convert_checkpoint.py` (default 2782; v3 ckpts need `--obs-size 1612`). Old obs-v3-lineage checkpoints are input-shape **incompatible**.
CLAUDE.md:32:- **`puffer/bloodbowl/` is the SOURCE OF TRUTH; `vendor/PufferLib/ocean/bloodbowl/` is an installed snapshot** written by `tools/install_puffer_env.sh` — the build compiles the snapshot, NOT your edit. The snapshot can lag (the Mac checkout's may still say 1612). Drift guard: `tools/install_puffer_env.sh --check` (exit 1 = re-install). Run it before any build on a training box.
CLAUDE.md:33:- After ANY env code change, ON THE BOX: `bash tools/install_puffer_env.sh` THEN `cd vendor/PufferLib && rm -rf build && ./build.sh bloodbowl --float` (torch needs `--float`; plain build = bf16 for native CUDA; **never skip `rm -rf build`**). Mac = standalone C binaries only (`build.sh <env> --local`, strip `-mavx2 -mfma`); all training/conversion happens on boxes at `/root/bloodbowl-rl`.
CLAUDE.md:34:- **Launch contract** (`tools/run_synthesis_c.sh`, run on the box from `~/bloodbowl-rl`): `ANCHOR=<path>` (default bc_v3b; >13MB dead-lineage size guard), `LOG=`, `STEPS=` (default 10B; asymmetric runs overshoot ~1.5x, known, benign), trailing args are appended LAST and override (last-wins). **WARNING: the script hard-codes the DEAD synthesis-C economy** (`reward-ball-loss -0.2`, `reward-ball-gain 0.1`, full-k, `demo-reset-pct 0.5`, `--tag profile-synthesis-c`, `--vec.num-threads 20`). For ANY v4 arm you MUST override the full settled knob set as trailing args — at minimum `--env.reward-ball-loss 0 --env.reward-ball-gain 0.05 --env.reward-possession 0.03` plus k-half, dist potentials, stage knob, `--tag`. **Safest: copy the exact command line of a live v4 twin** (`ps aux | grep 'puffer [t]rain'` or head of `/tmp/<tag>.log` on its box) and change only the stage knob, anchor, and tag. Asymmetric: `--train.frozen-enemy-path <ckpt>`. The script requires the demo bank at `vendor/PufferLib/resources/bloodbowl/state_bank.bbs` (a missing bank is SILENT — env trains procgen-only) and prints LIVE/TRAINER DIED at 40s — read it before walking away.
CLAUDE.md:46:- **Tournament procedure** (runs on box-1's judge GPU): ship both ckpts to box-1 box-to-box, convert BOTH sides — `python training/convert_checkpoint.py --to-cuda A.bin -o A_cuda.bin` (**mind `--obs-size`: 2782 default, 1612 for v3 lineage**; conversion drops biases, so equal treatment of both sides matters, D45) — then `puffer match bloodbowl --load-model-path A_cuda.bin --load-enemy-model-path B_cuda.bin --num-games 4096`. Read the decisive-game split, not the draw rate.
CLAUDE.md:63:4. Partial code syncs (header without binding.c) build stale mixtures — sync `engine/` AND `puffer/` together (`fleet.sh setup`), re-run `install_puffer_env.sh` (or `--check`), and grep the changed symbol on the box.
CLAUDE.md:70:11. **CPU thread cap (D59):** `nproc` (visible CPUs) ≫ cgroup quota (allowed CPUs) on some boxes → unpinned torch/BLAS pools thrash (5x SPS loss). `tools/cpu_cap.sh` fixes it and is auto-sourced by all launch scripts + `~/.bashrc`; any manual `puffer train` must `. tools/cpu_cap.sh` first. Verify: live trainer's `OMP_NUM_THREADS` == quota, thread count ~150-190 not hundreds.
CLAUDE.md:71:12. **A run completes/dies but the box keeps billing — detect via LOG MTIME, not log content (D65).** A finished `puffer train` leaves its log frozen at the final dashboard; any monitor that greps log *content* reports it "running" forever. Two flagship arms idle-billed 8–13h this way. ALWAYS gate liveness on `stat -c %Y <log>` age (>360s stale = dead/done) AND `pgrep -xc puffer` (the trainer process is named exactly `puffer`; `pgrep -f "puffer [t]rain"` matches its own shell). A run hitting its STEPS cap exits cleanly (not a crash) — advance the ladder or reassign/stop the box.
vendor/PufferLib/pufferlib/sweep.py:9:import pufferlib
vendor/PufferLib/pufferlib/sweep.py:141:def _params_from_puffer_sweep(sweep_config, only_include=None):
vendor/PufferLib/pufferlib/sweep.py:154:            param_spaces[name] = _params_from_puffer_sweep(param, only_include)
vendor/PufferLib/pufferlib/sweep.py:186:        self.spaces = _params_from_puffer_sweep(config)
vendor/PufferLib/pufferlib/sweep.py:757:        # NOTE: Changed pufferl to use the train args, NOT the sweep hyperparam search center
vendor/PufferLib/pufferlib/selfplay.py:2:snapshot, the rest are pure selfplay. Used by `_train` in pufferl.py — gated on
vendor/PufferLib/pufferlib/selfplay.py:25:from pufferlib import _C
vendor/PufferLib/pufferlib/selfplay.py:67:    The C-side bank_layout (pufferlib.cu:1798-1806) lays banks out sequentially
vendor/PufferLib/pufferlib/selfplay.py:120:def setup(pufferl, backend, args, run_id):
vendor/PufferLib/pufferlib/selfplay.py:137:    num_envs = backend.num_envs(pufferl)
vendor/PufferLib/pufferlib/selfplay.py:152:    # frozen_bank_pct is per-bank (matches C-side: pufferlib.cu:2069). Each bank
vendor/PufferLib/pufferlib/selfplay.py:167:    backend.set_agent_perm(pufferl, perm)
vendor/PufferLib/pufferlib/selfplay.py:168:    backend.set_env_tags(pufferl, tags)
vendor/PufferLib/pufferlib/selfplay.py:177:    # (pufferl_load_frozen_bank, pufferlib.cu:1830) only fprintf-warns on a
vendor/PufferLib/pufferlib/selfplay.py:180:    # reapply after a re-clone; see .claude/skills/puffer-env-dev/SKILL.md).
vendor/PufferLib/pufferlib/selfplay.py:199:            backend.load_frozen_bank(pufferl, b, path)
vendor/PufferLib/pufferlib/selfplay.py:204:        bootstrap_path = os.path.join(pool_dir, f'{pufferl.global_step:016d}.bin')
vendor/PufferLib/pufferlib/selfplay.py:205:        backend.save_weights(pufferl, bootstrap_path)
vendor/PufferLib/pufferlib/selfplay.py:208:            backend.load_frozen_bank(pufferl, b, bootstrap_path)
vendor/PufferLib/pufferlib/selfplay.py:225:            'opp_started_step': int(pufferl.global_step),
vendor/PufferLib/pufferlib/selfplay.py:246:        'last_snapshot_step': int(pufferl.global_step),
vendor/PufferLib/pufferlib/selfplay.py:250:def step(pufferl, backend, pool_state, flat_logs, epoch):
vendor/PufferLib/pufferlib/selfplay.py:280:            and pufferl.global_step - pool_state['last_snapshot_step']
vendor/PufferLib/pufferlib/selfplay.py:283:            f'{pufferl.global_step:016d}.bin')
vendor/PufferLib/pufferlib/selfplay.py:284:        backend.save_weights(pufferl, snap_path)
vendor/PufferLib/pufferlib/selfplay.py:287:        pool_state['last_snapshot_step'] = int(pufferl.global_step)
vendor/PufferLib/pufferlib/selfplay.py:299:            and pufferl.global_step - bank['opp_started_step']
vendor/PufferLib/pufferlib/selfplay.py:304:            if backend.count_aligned(pufferl, tag_value, 0) >= bank['num_hist_envs']:
vendor/PufferLib/pufferlib/selfplay.py:305:                backend.load_frozen_bank(pufferl, b, bank['pending_opp_path'])
vendor/PufferLib/pufferlib/selfplay.py:306:                backend.count_aligned(pufferl, tag_value, 1)
vendor/PufferLib/pufferlib/selfplay.py:313:                bank['opp_started_step'] = int(pufferl.global_step)
vendor/PufferLib/pufferlib/selfplay.py:321:                    f'{pufferl.global_step:016d}.bin')
vendor/PufferLib/pufferlib/selfplay.py:322:                backend.save_weights(pufferl, snap_path)
vendor/PufferLib/pufferlib/selfplay.py:325:                pool_state['last_snapshot_step'] = int(pufferl.global_step)
vendor/PufferLib/profile.sh:1:nsys profile --force-overwrite true --capture-range=cudaProfilerApi --cuda-graph-trace=node --sample=none -o profile python -m pufferlib.pufferl train breakout --vec.num-buffers 1 --profile True
vendor/PufferLib/README.md:1:![figure](https://pufferai.github.io/source/resource/header.png)
vendor/PufferLib/README.md:6:PufferLib is a fast and sane reinforcement learning library that can train tiny, super-human models in seconds. The included learning algorithm, hyperparameter tuning, and simulation methods are the product of our own research. All our tools are free and open source. Need a high performance environment for your application? We build them professionally and offer training + extended support. Contact jsuarez🐡puffer🐡ai.
vendor/PufferLib/README.md:8:All of our documentation is hosted at [puffer.ai](https://puffer.ai "PufferLib Documentation"). @jsuarez5341 on [Discord](https://discord.gg/puffer) for support. Post there before opening issues. We're always looking for new contributors!
vendor/PufferLib/README.md:12:<a href="https://star-history.com/#pufferai/pufferlib&Date">
vendor/PufferLib/README.md:14:   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=pufferai/pufferlib&type=Date&theme=dark" />
vendor/PufferLib/README.md:15:   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=pufferai/pufferlib&type=Date" />
vendor/PufferLib/README.md:16:   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=pufferai/pufferlib&type=Date" />
vendor/PufferLib/build.sh:5:#   ./build.sh breakout              # Build _C.so with breakout statically linked
vendor/PufferLib/build.sh:6:#   ./build.sh breakout --float      # float32 precision (required for --slowly)
vendor/PufferLib/build.sh:7:#   ./build.sh breakout --cpu        # CPU fallback, torch only
vendor/PufferLib/build.sh:8:#   ./build.sh breakout --debug      # Debug build
vendor/PufferLib/build.sh:9:#   ./build.sh breakout --local      # Standalone executable (debug, sanitizers)
vendor/PufferLib/build.sh:10:#   ./build.sh breakout --fast       # Standalone executable (optimized)
vendor/PufferLib/build.sh:11:#   ./build.sh breakout --web        # Emscripten web build
vendor/PufferLib/build.sh:12:#   ./build.sh breakout --profile    # Kernel profiling binary
vendor/PufferLib/build.sh:13:#   ./build.sh all                   # Build all envs with default and --float
vendor/PufferLib/build.sh:16:    echo "Usage: ./build.sh ENV_NAME [--float] [--debug] [--local|--fast|--web|--profile|--cpu|--all]"
vendor/PufferLib/build.sh:254:OUTPUT="pufferlib/_C${EXT_SUFFIX}"
vendor/PufferLib/examples/gym_env.py:2:import pufferlib.emulation
vendor/PufferLib/examples/gym_env.py:17:    gymnasium_env = pufferlib.GymToGymnasium(gym_env)
vendor/PufferLib/examples/gym_env.py:18:    puffer_env = pufferlib.emulation.GymnasiumPufferEnv(gymnasium_env)
vendor/PufferLib/examples/gym_env.py:19:    observations, info = puffer_env.reset()
vendor/PufferLib/examples/gym_env.py:20:    action = puffer_env.action_space.sample()
vendor/PufferLib/examples/gym_env.py:21:    observation, reward, terminal, truncation, info = puffer_env.step(action)
vendor/PufferLib/tests/craftax_convergence_bench.py:3:Runs both envs through `uv run puffer train` back-to-back (default 10M env
vendor/PufferLib/tests/craftax_convergence_bench.py:4:steps each), then parses pufferlib's per-run JSON log and plots:
vendor/PufferLib/tests/craftax_convergence_bench.py:47:    # pufferlib._C is compiled for one env at a time; rebuild before each run.
vendor/PufferLib/tests/craftax_convergence_bench.py:50:        "./build.sh", env_name,
vendor/PufferLib/tests/craftax_convergence_bench.py:52:    print(f"\n=== rebuilding pufferlib._C for {env_name} ===")
vendor/PufferLib/tests/craftax_convergence_bench.py:57:        "puffer", "train", env_name,
vendor/PufferLib/pufferlib/pufferl.py:1:## puffer [train | eval | sweep] [env_name] [optional args] -- See https://puffer.ai for full details
vendor/PufferLib/pufferlib/pufferl.py:2:# This is the same as python -m pufferlib.pufferl [train | eval | sweep] [env_name] [optional args]
vendor/PufferLib/pufferlib/pufferl.py:22:import pufferlib
vendor/PufferLib/pufferlib/pufferl.py:24:    from pufferlib import _C
vendor/PufferLib/pufferlib/pufferl.py:28:from pufferlib import selfplay
vendor/PufferLib/pufferlib/pufferl.py:174:        f'build.sh was run for {compiled_env}, not {args["env_name"]}'
vendor/PufferLib/pufferlib/pufferl.py:176:        from pufferlib.torch_pufferl import PuffeRL
vendor/PufferLib/pufferlib/pufferl.py:182:    pufferl = backend.create_pufferl(args)
vendor/PufferLib/pufferlib/pufferl.py:184:    while pufferl.global_step < args['train']['total_timesteps']:
vendor/PufferLib/pufferlib/pufferl.py:185:        backend.rollouts(pufferl)
vendor/PufferLib/pufferlib/pufferl.py:186:        backend.train(pufferl)
vendor/PufferLib/pufferlib/pufferl.py:188:    backend.close(pufferl)
vendor/PufferLib/pufferlib/pufferl.py:220:        pufferl = backend.create_pufferl(args)
vendor/PufferLib/pufferlib/pufferl.py:236:        backend.load_weights(pufferl, _load)
vendor/PufferLib/pufferlib/pufferl.py:240:    model_size = pufferl.num_params()
vendor/PufferLib/pufferlib/pufferl.py:242:        flat_logs = dict(unroll_nested_dict(backend.log(pufferl)))
vendor/PufferLib/pufferlib/pufferl.py:249:        pool_state = selfplay.setup(pufferl, backend, args, run_id)
vendor/PufferLib/pufferlib/pufferl.py:252:        backend.close(pufferl)
vendor/PufferLib/pufferlib/pufferl.py:262:        backend.rollouts(pufferl)
vendor/PufferLib/pufferlib/pufferl.py:265:            backend.train(pufferl)
vendor/PufferLib/pufferlib/pufferl.py:273:            model_path = os.path.join(checkpoint_dir, f'{pufferl.global_step:016d}.bin')
vendor/PufferLib/pufferlib/pufferl.py:274:            backend.save_weights(pufferl, model_path)
vendor/PufferLib/pufferlib/pufferl.py:277:        if time.time() < pufferl.last_log_time + 0.6 and epoch < train_epochs - 1:
vendor/PufferLib/pufferlib/pufferl.py:280:        logs = backend.eval_log(pufferl) if epoch >= train_epochs else backend.log(pufferl)
vendor/PufferLib/pufferlib/pufferl.py:284:            selfplay.step(pufferl, backend, pool_state, flat_logs, epoch)
vendor/PufferLib/pufferlib/pufferl.py:299:                    and pufferl.global_step > min(0.20*total_timesteps, 100_000_000) and
vendor/PufferLib/pufferlib/pufferl.py:310:        model_path = os.path.join(checkpoint_dir, f'{pufferl.global_step:016d}.bin')
vendor/PufferLib/pufferlib/pufferl.py:311:        backend.save_weights(pufferl, model_path)
vendor/PufferLib/pufferlib/pufferl.py:312:    backend.close(pufferl)
vendor/PufferLib/pufferlib/pufferl.py:320:    # fixed enemy. Score is slot 0's average winrate. Creates its own pufferl
vendor/PufferLib/pufferlib/pufferl.py:428:    import pufferlib.sweep
vendor/PufferLib/pufferlib/pufferl.py:430:        sweep_cls = getattr(pufferlib.sweep, method)
vendor/PufferLib/pufferlib/pufferl.py:432:        raise ValueError(f'Invalid sweep method {method}. See pufferlib.sweep')
vendor/PufferLib/pufferlib/pufferl.py:487:    pufferl = backend.create_pufferl(args)
vendor/PufferLib/pufferlib/pufferl.py:500:        backend.load_weights(pufferl, load_path)
vendor/PufferLib/pufferlib/pufferl.py:504:        backend.render(pufferl, 0)
vendor/PufferLib/pufferlib/pufferl.py:505:        backend.rollouts(pufferl)
vendor/PufferLib/pufferlib/pufferl.py:507:    backend.close(pufferl)
vendor/PufferLib/pufferlib/pufferl.py:546:    # holds policy B (owns second half). Bank is created inside create_pufferl
vendor/PufferLib/pufferlib/pufferl.py:561:    pufferl = backend.create_pufferl(args)
vendor/PufferLib/pufferlib/pufferl.py:573:    backend.set_agent_perm(pufferl, perm)
vendor/PufferLib/pufferlib/pufferl.py:575:    backend.load_weights(pufferl, policy_a_path)
vendor/PufferLib/pufferlib/pufferl.py:576:    backend.load_frozen_bank(pufferl, 0, policy_b_path)
vendor/PufferLib/pufferlib/pufferl.py:580:        backend.rollouts(pufferl)
vendor/PufferLib/pufferlib/pufferl.py:581:        logs = dict(unroll_nested_dict(backend.eval_log(pufferl)))
vendor/PufferLib/pufferlib/pufferl.py:594:    backend.close(pufferl)
vendor/PufferLib/pufferlib/pufferl.py:602:        help='Path to opponent checkpoint for `puffer match` (slot 1 / black in chess)')
vendor/PufferLib/pufferlib/pufferl.py:604:        help='Number of games to play in `puffer match`')
vendor/PufferLib/pufferlib/pufferl.py:614:    parser.add_argument('--wandb-project', type=str, default='puffer4')
vendor/PufferLib/pufferlib/pufferl.py:621:    parser.description = f':blowfish: PufferLib [bright_cyan]{pufferlib.__version__}[/]' \
vendor/PufferLib/pufferlib/pufferl.py:625:    puffer_config_dir = os.path.join(repo_dir, 'config/**/*.ini')
vendor/PufferLib/pufferlib/pufferl.py:626:    puffer_default_config = os.path.join(repo_dir, 'config/default.ini')
vendor/PufferLib/pufferlib/pufferl.py:627:    #CC: Remove the default. Just raise an error on "puffer train" etc with no env (think we already do)
vendor/PufferLib/pufferlib/pufferl.py:630:        p.read(puffer_default_config)
vendor/PufferLib/pufferlib/pufferl.py:632:        for path in glob.glob(puffer_config_dir, recursive=True):
vendor/PufferLib/pufferlib/pufferl.py:634:            p.read([puffer_default_config, path])
vendor/PufferLib/pufferlib/pufferl.py:674:    err = 'Usage: puffer [train, eval, sweep, paretosweep, match] [env_name] [optional args]. --help for more info'
vendor/PufferLib/pufferlib/pufferl.py:692:            raise ValueError('puffer match requires --load-model-path and --load-enemy-model-path')
vendor/PufferLib/examples/gymnasium_env.py:2:import pufferlib.emulation
vendor/PufferLib/examples/gymnasium_env.py:17:    puffer_env = pufferlib.emulation.GymnasiumPufferEnv(gymnasium_env)
vendor/PufferLib/examples/gymnasium_env.py:18:    observation, info = puffer_env.reset()
vendor/PufferLib/examples/gymnasium_env.py:19:    action = puffer_env.action_space.sample()
vendor/PufferLib/examples/gymnasium_env.py:20:    observation, reward, terminal, truncation, info = puffer_env.step(action)
vendor/PufferLib/pufferlib/torch_pufferl.py:1:## puffer [train | eval | sweep] [env_name] [optional args] -- See https://puffer.ai for full detail0
vendor/PufferLib/pufferlib/torch_pufferl.py:2:# This is the same as python -m pufferlib.pufferl [train | eval | sweep] [env_name] [optional args]
vendor/PufferLib/pufferlib/torch_pufferl.py:3:# Distributed example: torchrun --standalone --nnodes=1 --nproc-per-node=6 -m pufferlib.pufferl train puffer_nmmo3
vendor/PufferLib/pufferlib/torch_pufferl.py:17:import pufferlib
vendor/PufferLib/pufferlib/torch_pufferl.py:18:import pufferlib.pufferl
vendor/PufferLib/pufferlib/torch_pufferl.py:19:from pufferlib.muon import Muon
vendor/PufferLib/pufferlib/torch_pufferl.py:20:from pufferlib import _C
vendor/PufferLib/pufferlib/torch_pufferl.py:24:        'The PyTorch backend requires float32. Rerun build.sh with --float'
vendor/PufferLib/pufferlib/torch_pufferl.py:147:# the unwrapped module (create_pufferl), bypassing gradient sync — the BC
vendor/PufferLib/pufferlib/torch_pufferl.py:150:# Patch copy: training/torch_pufferl_bcreg.patch (reapply after a vendor
vendor/PufferLib/pufferlib/torch_pufferl.py:151:# re-clone; see .claude/skills/puffer-env-dev/SKILL.md).
vendor/PufferLib/pufferlib/torch_pufferl.py:159:    root above vendor/PufferLib (puffer train usually runs from there).'''
vendor/PufferLib/pufferlib/torch_pufferl.py:164:    for _ in range(4):  # pufferlib/ -> PufferLib/ -> vendor/ -> <repo root>
vendor/PufferLib/pufferlib/torch_pufferl.py:381:            pufferlib.pufferl.print_dashboard(args, self.model_size, {}, clear=True)
vendor/PufferLib/pufferlib/torch_pufferl.py:673:    def create_pufferl(cls, args):
vendor/PufferLib/pufferlib/torch_pufferl.py:674:        '''Matches _C.create_pufferl(args) interface.'''
vendor/PufferLib/pufferlib/torch_pufferl.py:711:    '''Matches pufferlib.cu profiling: accumulate ms, report seconds.'''
vendor/PufferLib/pufferlib/torch_pufferl.py:741:    import pufferlib.models
vendor/PufferLib/pufferlib/torch_pufferl.py:743:    network_cls = getattr(pufferlib.models, args['torch']['network'])
vendor/PufferLib/pufferlib/torch_pufferl.py:744:    encoder_cls = getattr(pufferlib.models, args['torch']['encoder'])
vendor/PufferLib/pufferlib/torch_pufferl.py:745:    decoder_cls = getattr(pufferlib.models, args['torch']['decoder'])
vendor/PufferLib/pufferlib/torch_pufferl.py:750:    policy = pufferlib.models.Policy(encoder, decoder, network)
vendor/PufferLib/tests/craftax_parity.py:188:    import pufferlib._C as cmod
vendor/PufferLib/tests/craftax_parity.py:193:            f"pufferlib._C is compiled for {env_name!r}, expected 'craftax'. "
vendor/PufferLib/tests/craftax_parity.py:194:            "Run: uv run --with pybind11 --with rich_argparse ./build.sh craftax"
vendor/PufferLib/tests/test_puffernet.py:9:        'pufferlib/extensions',
vendor/PufferLib/tests/test_puffernet.py:13:from pufferlib.extensions import puffernet
vendor/PufferLib/tests/test_puffernet.py:34:def test_puffernet_relu(batch_size=16, input_size=128):
vendor/PufferLib/tests/test_puffernet.py:35:    input_puffer = make_dummy_data(batch_size, input_size)
vendor/PufferLib/tests/test_puffernet.py:37:    input_torch = torch.from_numpy(input_puffer)
vendor/PufferLib/tests/test_puffernet.py:41:    puffernet.puf_relu(input_puffer, input_puffer, batch_size*input_size)
vendor/PufferLib/tests/test_puffernet.py:43:    assert_near(input_puffer, output_torch.numpy())
vendor/PufferLib/tests/test_puffernet.py:45:def test_puffernet_gelu(batch_size=16, input_size=128):
vendor/PufferLib/tests/test_puffernet.py:46:    input_puffer = make_dummy_data(batch_size, input_size)
vendor/PufferLib/tests/test_puffernet.py:48:    input_torch = torch.from_numpy(input_puffer)
vendor/PufferLib/tests/test_puffernet.py:52:    puffernet.puf_gelu(input_puffer, input_puffer, batch_size*input_size)
vendor/PufferLib/tests/test_puffernet.py:54:    assert_near(input_puffer, output_torch.numpy())
vendor/PufferLib/tests/test_puffernet.py:56:def test_puffernet_sigmoid(n=1024, epsilon=1e-4):
vendor/PufferLib/tests/test_puffernet.py:64:        out_puffer = puffernet.puf_sigmoid(input_np[i])
vendor/PufferLib/tests/test_puffernet.py:65:        assert abs(out_puffer - out_torch) < epsilon
vendor/PufferLib/tests/test_puffernet.py:67:def test_puffernet_linear_layer(batch_size=16, input_size=128, hidden_size=128):
vendor/PufferLib/tests/test_puffernet.py:71:    output_puffer = np.zeros((batch_size, hidden_size), dtype=np.float32)
vendor/PufferLib/tests/test_puffernet.py:72:    puffernet.puf_linear_layer(input_np, weights_np, bias_np, output_puffer,
vendor/PufferLib/tests/test_puffernet.py:83:    assert_near(output_puffer, output_torch.numpy())
vendor/PufferLib/tests/test_puffernet.py:85:def test_puffernet_convolution_layer(batch_size=16, in_width=11, in_height=11,
vendor/PufferLib/tests/test_puffernet.py:92:    output_puffer = np.zeros((batch_size, out_channels, out_height, out_width), dtype=np.float32)
vendor/PufferLib/tests/test_puffernet.py:93:    puffernet.puf_convolution_layer(input_np, weights_np, bias_np, output_puffer,
vendor/PufferLib/tests/test_puffernet.py:104:    assert_near(output_puffer, output_torch.numpy())
vendor/PufferLib/tests/test_puffernet.py:106:def test_puffernet_convolution_3d_layer(batch_size=4096, in_width=9, in_height=5, in_depth=5,
vendor/PufferLib/tests/test_puffernet.py:115:    output_puffer = np.zeros((batch_size, out_channels, out_depth, out_height, out_width), dtype=np.float32)
vendor/PufferLib/tests/test_puffernet.py:117:    puffernet.puf_convolution_3d_layer(input_np, weights_np, bias_np, output_puffer,
vendor/PufferLib/tests/test_puffernet.py:128:    assert_near(output_puffer, output_torch.numpy())
vendor/PufferLib/tests/test_puffernet.py:130:def test_puffernet_lstm(batch_size=16, input_size=128, hidden_size=128):
vendor/PufferLib/tests/test_puffernet.py:157:    puffernet.puf_lstm(input_np, state_h_np, state_c_np, weights_input_np,
vendor/PufferLib/tests/test_puffernet.py:164:def test_puffernet_embedding(batch_size=16, num_embeddings=128, embedding_dim=32):
vendor/PufferLib/tests/test_puffernet.py:167:    output_puffer = np.zeros((batch_size, embedding_dim), dtype=np.float32)
vendor/PufferLib/tests/test_puffernet.py:168:    puffernet.puf_embedding(input_np, weights_np, output_puffer,
vendor/PufferLib/tests/test_puffernet.py:181:    assert_near(output_puffer, output_torch.numpy())
vendor/PufferLib/tests/test_puffernet.py:183:def test_puffernet_layernorm(batch_size=16, input_size=128):
vendor/PufferLib/tests/test_puffernet.py:187:    output_puffer = np.zeros((batch_size, input_size), dtype=np.float32)
vendor/PufferLib/tests/test_puffernet.py:188:    puffernet.puf_layernorm(input_np, weights_np, bias_np, output_puffer,
vendor/PufferLib/tests/test_puffernet.py:199:    assert_near(output_puffer, output_torch.numpy())
vendor/PufferLib/tests/test_puffernet.py:201:def test_puffernet_one_hot(batch_size=16, input_size=128, num_classes=10):
vendor/PufferLib/tests/test_puffernet.py:203:    output_puffer = np.zeros((batch_size, input_size, num_classes), dtype=np.int32)
vendor/PufferLib/tests/test_puffernet.py:204:    puffernet.puf_one_hot(input_np, output_puffer, batch_size, input_size, num_classes)
vendor/PufferLib/tests/test_puffernet.py:209:    assert_near(output_puffer, output_torch.numpy())
vendor/PufferLib/tests/test_puffernet.py:211:def test_puffernet_cat_dim1(batch_size=16, x_size=32, y_size=64):
vendor/PufferLib/tests/test_puffernet.py:214:    output_puffer = np.zeros((batch_size, x_size + y_size), dtype=np.float32)
vendor/PufferLib/tests/test_puffernet.py:215:    puffernet.puf_cat_dim1(x_np, y_np, output_puffer, batch_size, x_size, y_size)
vendor/PufferLib/tests/test_puffernet.py:221:    assert_near(output_puffer, output_torch.numpy())
vendor/PufferLib/tests/test_puffernet.py:223:def test_puffernet_argmax_multidiscrete(batch_size=16, logit_sizes=[5,7,2]):
vendor/PufferLib/tests/test_puffernet.py:227:    output_puffer = np.zeros((batch_size, num_actions), dtype=np.int32)
vendor/PufferLib/tests/test_puffernet.py:228:    puffernet.puf_argmax_multidiscrete(input_np, output_puffer, batch_size, logit_sizes, num_actions)
vendor/PufferLib/tests/test_puffernet.py:234:    assert_near(output_puffer, output_torch.numpy())
vendor/PufferLib/tests/test_puffernet.py:240:    from pufferlib.ocean.torch import NMMO3, NMMO3LSTM
vendor/PufferLib/tests/test_puffernet.py:241:    from pufferlib.ocean import env_creator
vendor/PufferLib/tests/test_puffernet.py:242:    env = env_creator('puffer_nmmo3')()
vendor/PufferLib/tests/test_puffernet.py:258:    test_puffernet_relu()
vendor/PufferLib/tests/test_puffernet.py:259:    test_puffernet_gelu()
vendor/PufferLib/tests/test_puffernet.py:260:    test_puffernet_sigmoid()
vendor/PufferLib/tests/test_puffernet.py:261:    test_puffernet_linear_layer()
vendor/PufferLib/tests/test_puffernet.py:262:    test_puffernet_convolution_layer()
vendor/PufferLib/tests/test_puffernet.py:263:    test_puffernet_convolution_3d_layer()
vendor/PufferLib/tests/test_puffernet.py:264:    test_puffernet_lstm()
vendor/PufferLib/tests/test_puffernet.py:265:    test_puffernet_embedding()
vendor/PufferLib/tests/test_puffernet.py:266:    test_puffernet_layernorm()
vendor/PufferLib/tests/test_puffernet.py:267:    test_puffernet_one_hot()
vendor/PufferLib/tests/test_puffernet.py:268:    test_puffernet_cat_dim1()
vendor/PufferLib/tests/test_puffernet.py:269:    test_puffernet_argmax_multidiscrete()
vendor/PufferLib/tests/test_nmmo3_encoder.py:23:        "-I", os.path.join(os.path.dirname(__file__), "..", "pufferlib", "src"),
vendor/PufferLib/ocean/drive/dataset.py:4:  https://huggingface.co/datasets/daphne-cornelisse/pufferdrive_womd_train_1000
vendor/PufferLib/ocean/drive/dataset.py:6:  uv pip install huggingface_hub
vendor/PufferLib/ocean/drive/dataset.py:7:  python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='daphne-cornelisse/pufferdrive_womd_train_1000', repo_type='dataset', local_dir='drive_data')"
vendor/PufferLib/ocean/drive/dataset.py:11:    tar xzf drive_data/pufferdrive_womd_train_1000.tar.gz --strip-components=1 -C drive_data/training/
vendor/PufferLib/tests/microbench.py:7:import pufferlib
vendor/PufferLib/tests/microbench.py:9:    from pufferlib import _C
vendor/PufferLib/examples/pettingzoo_env.py:3:import pufferlib.emulation
vendor/PufferLib/examples/pettingzoo_env.py:30:    puffer_env = pufferlib.emulation.PettingZooPufferEnv(env)
vendor/PufferLib/examples/pettingzoo_env.py:31:    observations, infos = puffer_env.reset()
vendor/PufferLib/examples/pettingzoo_env.py:32:    actions = {agent: puffer_env.action_space(agent).sample() for agent in puffer_env.agents}
vendor/PufferLib/examples/pettingzoo_env.py:33:    observations, rewards, terminals, truncations, infos = puffer_env.step(actions)
vendor/PufferLib/tests/test_sweep.py:10:import pufferlib
vendor/PufferLib/tests/test_sweep.py:11:import pufferlib.sweep
vendor/PufferLib/tests/test_sweep.py:53:        sweep = pufferlib.sweep.Random(args['sweep'])
vendor/PufferLib/tests/test_sweep.py:55:        sweep = pufferlib.sweep.ParetoGenetic(args['sweep'])
vendor/PufferLib/tests/test_sweep.py:57:        sweep = pufferlib.sweep.Protein(
vendor/PufferLib/tests/test_sweep.py:110:    pareto, pareto_idx = pufferlib.sweep.pareto_points(sweep.success_observations)
vendor/PufferLib/tests/test_sweep.py:167:    from pufferlib import pufferl
vendor/PufferLib/tests/test_sweep.py:169:    parser = pufferl.make_parser()
vendor/PufferLib/tests/test_sweep.py:176:    args = pufferl.load_config('default', parser=parser)
vendor/PufferLib/tests/test_import_performance.py:5:    import pufferlib
vendor/PufferLib/tests/test_import_performance.py:7:    print(end - start, ' seconds to import pufferlib')
vendor/PufferLib/tests/test_sweep_hyper.py:14:from pufferlib import pufferl
vendor/PufferLib/tests/test_sweep_hyper.py:15:from pufferlib.sweep import Protein
vendor/PufferLib/tests/test_sweep_hyper.py:163:        print("Install matplotlib to visualize results: pip install matplotlib")
vendor/PufferLib/tests/test_sweep_hyper.py:284:    parser = pufferl.make_parser()
vendor/PufferLib/tests/test_sweep_hyper.py:312:    env_name = "puffer_breakout"
vendor/PufferLib/tests/test_sweep_hyper.py:313:    args = pufferl.load_config(env_name, parser)
vendor/PufferLib/examples/pufferl.py:2:import pufferlib.vector
vendor/PufferLib/examples/pufferl.py:3:import pufferlib.ocean
vendor/PufferLib/examples/pufferl.py:4:from pufferlib import pufferl
vendor/PufferLib/examples/pufferl.py:7:# Equivalent to running puffer train puffer_breakout
vendor/PufferLib/examples/pufferl.py:9:    pufferl.train('puffer_breakout')
vendor/PufferLib/examples/pufferl.py:11:# Simple trainer based on pufferl functions
vendor/PufferLib/examples/pufferl.py:12:def simple_trainer(env_name='puffer_breakout'):
vendor/PufferLib/examples/pufferl.py:13:    args = pufferl.load_config(env_name)
vendor/PufferLib/examples/pufferl.py:15:    # You can customize the puffer-provided config
vendor/PufferLib/examples/pufferl.py:25:    # args = pufferl.load_config_file(<YOUR_OWN_CONFIG.ini>, fill_in_default=True)
vendor/PufferLib/examples/pufferl.py:27:    vecenv = pufferl.load_env(env_name, args)
vendor/PufferLib/examples/pufferl.py:28:    policy = pufferl.load_policy(args, vecenv, env_name)
vendor/PufferLib/examples/pufferl.py:30:    trainer = pufferl.PuffeRL(args['train'], vecenv, policy)
vendor/PufferLib/examples/pufferl.py:43:            pufferlib.pytorch.layer_init(torch.nn.Linear(env.single_observation_space.shape[0], 128)),
vendor/PufferLib/examples/pufferl.py:45:            pufferlib.pytorch.layer_init(torch.nn.Linear(128, 128)),
vendor/PufferLib/examples/pufferl.py:62:    env_name = 'puffer_breakout'
vendor/PufferLib/examples/pufferl.py:63:    env_creator = pufferlib.ocean.env_creator(env_name)
vendor/PufferLib/examples/pufferl.py:64:    vecenv = pufferlib.vector.make(env_creator, num_envs=2, num_workers=2, batch_size=1,
vendor/PufferLib/examples/pufferl.py:65:        backend=pufferlib.vector.Multiprocessing, env_kwargs={'num_envs': 4096})
vendor/PufferLib/examples/pufferl.py:67:    args = pufferl.load_config('default')
vendor/PufferLib/examples/pufferl.py:70:    trainer = pufferl.PuffeRL(args['train'], vecenv, policy)
vendor/PufferLib/tests/test_muon.py:12:from pufferlib.muon import Muon as TorchMuon
vendor/PufferLib/tests/test_api.py:3:import pufferlib
vendor/PufferLib/tests/test_api.py:4:import pufferlib.emulation
vendor/PufferLib/tests/test_api.py:5:import pufferlib.vector
vendor/PufferLib/tests/test_api.py:6:from pufferlib.exceptions import APIUsageError, InvalidAgentError
vendor/PufferLib/tests/test_api.py:7:from pufferlib.environments import test
vendor/PufferLib/tests/test_api.py:16:    env = pufferlib.emulation.GymnasiumPufferEnv(
vendor/PufferLib/tests/test_api.py:43:    env = pufferlib.emulation.PettingZooPufferEnv(
vendor/PufferLib/tests/test_api.py:86:    gymnasium_creator = lambda: pufferlib.emulation.GymnasiumPufferEnv(
vendor/PufferLib/tests/test_api.py:88:    pettingzoo_creator = lambda: pufferlib.emulation.PettingZooPufferEnv(
vendor/PufferLib/tests/test_api.py:92:        pufferlib.vector.Serial,
vendor/PufferLib/tests/test_api.py:93:        pufferlib.vector.Multiprocessing,
vendor/PufferLib/tests/test_api.py:94:        pufferlib.vector.Ray]:
vendor/PufferLib/tests/test_api.py:97:            vec = pufferlib.vector.make(creator, num_envs=6,
vendor/PufferLib/tests/test_api.py:107:            vec = pufferlib.vector.make(creator, num_envs=8,
vendor/PufferLib/tests/test_api.py:116:            vec = pufferlib.vector.make(test.GymnasiumTestEnv)
vendor/PufferLib/tests/test_api.py:121:            vec = pufferlib.vector.make(gymnasium_creator,
vendor/PufferLib/tests/test_api.py:127:            vec = pufferlib.vector.make(gymnasium_creator,
vendor/PufferLib/ocean/overcooked/README.md:236:python setup.py build_overcooked --inplace
vendor/PufferLib/ocean/overcooked/README.md:239:python pufferlib/ocean/overcooked/overcooked.py
vendor/PufferLib/examples/render.py:2:from pufferlib.ocean.breakout import breakout
vendor/PufferLib/examples/vectorization.py:2:import pufferlib.emulation
vendor/PufferLib/examples/vectorization.py:3:import pufferlib.vector
vendor/PufferLib/examples/vectorization.py:5:class SamplePufferEnv(pufferlib.PufferEnv):
vendor/PufferLib/examples/vectorization.py:29:    serial_vecenv = pufferlib.vector.make(
vendor/PufferLib/examples/vectorization.py:30:        SamplePufferEnv, num_envs=2, backend=pufferlib.vector.Serial)
vendor/PufferLib/examples/vectorization.py:41:    serial_vecenv = pufferlib.vector.make(
vendor/PufferLib/examples/vectorization.py:42:        SamplePufferEnv, num_envs=2, backend=pufferlib.vector.Serial,
vendor/PufferLib/examples/vectorization.py:49:    serial_vecenv = pufferlib.vector.make(
vendor/PufferLib/examples/vectorization.py:50:        [SamplePufferEnv, SamplePufferEnv], num_envs=2, backend=pufferlib.vector.Serial,
vendor/PufferLib/examples/vectorization.py:56:    vecenv = pufferlib.vector.make(SamplePufferEnv,
vendor/PufferLib/examples/vectorization.py:57:        num_envs=2, num_workers=2, batch_size=1, backend=pufferlib.vector.Multiprocessing)
vendor/PufferLib/examples/vectorization.py:73:        vecenv = pufferlib.vector.make(SamplePufferEnv,
vendor/PufferLib/examples/vectorization.py:74:            num_envs=1, num_workers=2, batch_size=3, backend=pufferlib.vector.Multiprocessing)
vendor/PufferLib/examples/structured_env.py:2:import pufferlib.emulation
vendor/PufferLib/examples/structured_env.py:20:    puffer_env = pufferlib.emulation.GymnasiumPufferEnv(gymnasium_env)
vendor/PufferLib/examples/structured_env.py:21:    flat_observation, info = puffer_env.reset()
vendor/PufferLib/examples/structured_env.py:22:    flat_action = puffer_env.action_space.sample()
vendor/PufferLib/examples/structured_env.py:23:    flat_observation, reward, terminal, truncation, info = puffer_env.step(flat_action)
vendor/PufferLib/examples/structured_env.py:26:    observation = flat_observation.view(puffer_env.obs_dtype)
vendor/PufferLib/examples/structured_env.py:30:    import pufferlib.pytorch
vendor/PufferLib/examples/structured_env.py:32:    torch_dtype = pufferlib.pytorch.nativize_dtype(puffer_env.emulated)
vendor/PufferLib/examples/structured_env.py:33:    torch_observation = pufferlib.pytorch.nativize_tensor(flat_torch_observation, torch_dtype)
vendor/PufferLib/examples/puffer_env.py:2:import pufferlib.emulation
vendor/PufferLib/examples/puffer_env.py:4:class SamplePufferEnv(pufferlib.PufferEnv):
vendor/PufferLib/examples/puffer_env.py:21:    puffer_env = SamplePufferEnv()
vendor/PufferLib/examples/puffer_env.py:22:    observations, infos = puffer_env.reset()
vendor/PufferLib/examples/puffer_env.py:23:    actions = puffer_env.action_space.sample()
vendor/PufferLib/examples/puffer_env.py:24:    observations, rewards, terminals, truncations, infos = puffer_env.step(actions)
vendor/PufferLib/ocean/craftax/PORT_NOTES.md:527:- `uv run puffer train craftax` currently reaches rollout/train work, but a
vendor/PufferLib/ocean/craftax/PORT_NOTES.md:533:- `build.sh` now embeds rpaths for wheel-provided CUDA libraries so
vendor/PufferLib/ocean/craftax/PORT_NOTES.md:534:  `pufferlib._C` can find `libnccl.so.2`. The parity harness still preloads NCCL
vendor/PufferLib/ocean/nethack/README.md:28:pip install -e ".[nethack]"    # installs pufferlib + nethack deps (torch, numpy, wandb, etc.)
vendor/PufferLib/ocean/nethack/README.md:33:pip install -e .
vendor/PufferLib/ocean/nethack/README.md:34:pip install bz2file           # if system libbz2 headers missing
vendor/PufferLib/ocean/nethack/README.md:49:- **clang** (optional but preferred): `build.sh` uses clang flags by default. Set `CC=gcc` if clang isn't available, but note `-ferror-limit` must be removed from `build.sh`.
vendor/PufferLib/ocean/nethack/README.md:73:bash build.sh nethack          # auto-detects CUDA; falls back to CPU
vendor/PufferLib/ocean/nethack/README.md:76:Produces `pufferlib/_C.cpython-*.so`. If you get linker errors about
vendor/PufferLib/ocean/nethack/README.md:91:puffer train nethack \
vendor/PufferLib/ocean/nethack/README.md:107:puffer train nethack --wandb \
vendor/PufferLib/ocean/nethack/README.md:116:bash build.sh nethack                               # always (relinks _C.so)
vendor/PufferLib/ocean/nethack/README.md:128:bash build.sh nethack
vendor/PufferLib/ocean/nethack/README.md:162:build.sh's `EXTRA_CFLAGS`.

diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..99774f8dfb71f3f99dfd14ddaa48a8432093ee30
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,192 @@
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
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

codex
The repo notes say `vendor/PufferLib/ocean/bloodbowl/` is the compiled snapshot and is normally refreshed by `tools/install_puffer_env.sh`, but your hard rules keep me from touching extra files outside the edit map. I’m checking whether the snapshot is a symlink/current enough to build as-is; if not, I’ll report the binding build as skipped rather than silently broadening the change set.
exec
/bin/zsh -lc "rg -n \"skillup_max|bb_match_init_random_p|demo_pickup_maxdist|bb_match_init_random\\(\" vendor/PufferLib/ocean/bloodbowl puffer/bloodbowl" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
puffer/bloodbowl/bloodbowl.h:304:    int demo_pickup_maxdist;
puffer/bloodbowl/bloodbowl.h:319:    int skillup_max_players;
puffer/bloodbowl/bloodbowl.h:320:    int skillup_max_each;
puffer/bloodbowl/bloodbowl.h:1225:            } else if (env->demo_pickup_maxdist > 0) {
puffer/bloodbowl/bloodbowl.h:1228:                // demo_pickup_maxdist (Chebyshev) — the scoop backplay skips.
puffer/bloodbowl/bloodbowl.h:1245:                            if (d <= env->demo_pickup_maxdist) { hit = 1; break; }
puffer/bloodbowl/bloodbowl.h:1317:                env->skillup_max_players,
puffer/bloodbowl/bloodbowl.h:1318:                env->skillup_max_each,
puffer/bloodbowl/bloodbowl.h:1326:                env->skillup_max_players,
puffer/bloodbowl/bloodbowl.h:1327:                env->skillup_max_each,
puffer/bloodbowl/bloodbowl.h:1330:            bb_match_init_random_p(&env->match, &env->procgen, &pp);
puffer/bloodbowl/binding.c:89:    env->demo_pickup_maxdist = (int)kw(kwargs, "demo_pickup_maxdist", 0.0);
puffer/bloodbowl/binding.c:94:    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
puffer/bloodbowl/binding.c:95:    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
vendor/PufferLib/ocean/bloodbowl/engine/bb/bb_match.h:140:void bb_match_init_random(bb_match* m, bb_rng* rng);
vendor/PufferLib/ocean/bloodbowl/engine/bb_procgen.c:159:void bb_match_init_random(bb_match* m, bb_rng* rng) {
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:844:            bb_match_init_random(&env->match, &env->procgen);
vendor/PufferLib/ocean/bloodbowl/bb/bb_match.h:140:void bb_match_init_random(bb_match* m, bb_rng* rng);

exec
/bin/zsh -lc "ls -l vendor/PufferLib/ocean | rg bloodbowl || true && find vendor/PufferLib/ocean/bloodbowl -maxdepth 2 -type f | sed -n '1,80p'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
drwxr-xr-x@ 11 alexanderhuth  staff  352 Jun  6 18:06 bloodbowl
vendor/PufferLib/ocean/bloodbowl/bb/gen_teams.h
vendor/PufferLib/ocean/bloodbowl/bb/bb_skills.h
vendor/PufferLib/ocean/bloodbowl/bb/bb_proc.h
vendor/PufferLib/ocean/bloodbowl/bb/bb_hooks.h
vendor/PufferLib/ocean/bloodbowl/bb/gen_tables.h
vendor/PufferLib/ocean/bloodbowl/bb/bb_types.h
vendor/PufferLib/ocean/bloodbowl/bb/bb_blockev.h
vendor/PufferLib/ocean/bloodbowl/bb/bb_actions.h
vendor/PufferLib/ocean/bloodbowl/bb/gen_skills.h
vendor/PufferLib/ocean/bloodbowl/bb/bb_rng.h
vendor/PufferLib/ocean/bloodbowl/bb/bb_match.h
vendor/PufferLib/ocean/bloodbowl/bb/bb_replay.h
vendor/PufferLib/ocean/bloodbowl/.content_hash
vendor/PufferLib/ocean/bloodbowl/bbe_microstats_probe.c
vendor/PufferLib/ocean/bloodbowl/binding.c
vendor/PufferLib/ocean/bloodbowl/bloodbowl.c
vendor/PufferLib/ocean/bloodbowl/bbe_render.h
vendor/PufferLib/ocean/bloodbowl/bbe_profile.c
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h
vendor/PufferLib/ocean/bloodbowl/engine/bb_rng.c
vendor/PufferLib/ocean/bloodbowl/engine/proc_test.c
vendor/PufferLib/ocean/bloodbowl/engine/proc_ttm.c
vendor/PufferLib/ocean/bloodbowl/engine/proc_ball.c
vendor/PufferLib/ocean/bloodbowl/engine/gen_skills.c
vendor/PufferLib/ocean/bloodbowl/engine/bb_replay.c
vendor/PufferLib/ocean/bloodbowl/engine/bb_match.c
vendor/PufferLib/ocean/bloodbowl/engine/proc_move.c
vendor/PufferLib/ocean/bloodbowl/engine/gen_teams.c
vendor/PufferLib/ocean/bloodbowl/engine/skills_devious_traits.c
vendor/PufferLib/ocean/bloodbowl/engine/bb_skills.c
vendor/PufferLib/ocean/bloodbowl/engine/proc_turn.c
vendor/PufferLib/ocean/bloodbowl/engine/skills_agility.c
vendor/PufferLib/ocean/bloodbowl/engine/skills_mutation_passing.c
vendor/PufferLib/ocean/bloodbowl/engine/bb_blockev.c
vendor/PufferLib/ocean/bloodbowl/engine/proc_match.c
vendor/PufferLib/ocean/bloodbowl/engine/skills_core.c
vendor/PufferLib/ocean/bloodbowl/engine/bb_hooks.c
vendor/PufferLib/ocean/bloodbowl/engine/gen_tables.c
vendor/PufferLib/ocean/bloodbowl/engine/bb_procgen.c
vendor/PufferLib/ocean/bloodbowl/engine/proc_table.c
vendor/PufferLib/ocean/bloodbowl/engine/proc_block.c

exec
/bin/zsh -lc "sed -n '1,80p' puffer/bloodbowl/bloodbowl.c && sed -n '220,330p' vendor/PufferLib/build.sh" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
// bloodbowl.c — standalone driver for the PufferLib env (build.sh --local /
// --fast, or direct clang on Mac). Plays random-policy matches end-to-end
// through the exact c_reset/c_step path training uses, then reports
// aggregate stats + steps/sec. Heads are sampled from the legality mask
// (like the CUDA masked sampler); pass --unmasked to sample uniformly over
// each head instead, stress-testing the decode snap-to-legal path the
// maskless torch backend relies on.
#include "bloodbowl.h"
#include <stdio.h>
#include <time.h>

// Sample a uniformly random set bit in mask[0..len); -1 if none.
static int sample_masked(const unsigned char* mask, int len, bb_rng* rng) {
    int n = 0;
    for (int i = 0; i < len; i++) n += mask[i];
    if (n == 0) return -1;
    int k = (int)(bb_rng_next(rng) % (uint32_t)n);
    for (int i = 0; i < len; i++) {
        if (mask[i] && k-- == 0) return i;
    }
    return -1;
}

// --- Self-test (--selftest) --------------------------------------------------
// Binding-level regression checks, run over seeded random-policy episodes.
// Expectations are re-derived here straight from engine state (the bb_frame
// semantics documented in each proc_*.c header comment), independent of the
// encoder's own helper tables, so encoder regressions fail loudly.

static int st_failures;
static long st_tz_nonzero;    // marking-TZ bytes observed > 0 (coverage)
static long st_plane_nonzero; // obs-v3 TZ-plane bytes observed > 0 (coverage)
#define ST_CHECK(cond, ...)                                                    \
    do {                                                                       \
        if (!(cond)) {                                                         \
            st_failures++;                                                     \
            printf("SELFTEST FAIL (bloodbowl.c:%d): ", __LINE__);              \
            printf(__VA_ARGS__);                                               \
            printf("\n");                                                      \
        }                                                                      \
    } while (0)

// Independent restatement of the per-proc frame-param semantics (review M14:
// PREGAME stores the toss winner, SETUP/KICKOFF the kicking team and
// TEAM_TURN the acting team — TEAM IDS, not slots — in a; MOVE/TEST store
// kinds and CASUALTY/KO_RECOVERY flags in b). 1 = player slot.
static void st_frame_param_kinds(int proc, int* a_is_slot, int* b_is_slot) {
    *a_is_slot = 0;
    *b_is_slot = 0;
    switch (proc) {
    case BB_PROC_BLOCK: // a = attacker, b = defender
    case BB_PROC_PUSH:  // a = pusher, b = pushee
    case BB_PROC_FOUL:  // a = fouler, b = victim
        *a_is_slot = 1;
        *b_is_slot = 1;
        return;
    case BB_PROC_ACTIVATION:  // a = activating player
    case BB_PROC_MOVE:        // a = mover, b = bb_act_kind
    case BB_PROC_TEST:        // a = tested player, b = bb_test_kind
    case BB_PROC_CASUALTY:    // a = victim, b = apothecary-window flag
    case BB_PROC_KO_RECOVERY: // a = patched player, b = crowd flag
    case BB_PROC_PASS:        // a = thrower, b = interceptor (post-window)
        *a_is_slot = 1;
        return;
    default: // PREGAME / SETUP / KICKOFF / TEAM_TURN: a = team id
        return;
    }
}

// Validate both agents' encoded observations against the current decision
// state. Called when env obs/masks correspond to env->match (loop top).
static long st_v4_b_bytes, st_v4_a_bytes;

static void st_check_obs(const Bloodbowl* env) {
    const bb_match* m = &env->match;
    if (m->status != BB_STATUS_DECISION || m->stack_top == 0) return;
    const bb_frame* top = &m->stack[m->stack_top - 1];
    int a_is_slot, b_is_slot;
    st_frame_param_kinds(top->proc, &a_is_slot, &b_is_slot);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
# Needed when NCCL is provided by the nvidia-nccl-cu12 wheel in the active venv.
NCCL_IFLAG=""
NCCL_LFLAG=""
for dir in /usr/include /usr/local/cuda/include; do
    if [ -f "$dir/nccl.h" ]; then NCCL_IFLAG="-I$dir"; break; fi
done
for dir in /usr/lib/x86_64-linux-gnu /usr/local/cuda/lib64; do
    if [ -f "$dir/libnccl.so" ] || [ -f "$dir/libnccl.so.2" ]; then NCCL_LFLAG="-L$dir"; break; fi
done
if [ -z "$NCCL_IFLAG" ]; then
    NCCL_IFLAG=$(python -c "import nvidia.nccl, os; print('-I' + os.path.join(nvidia.nccl.__path__[0], 'include'))" 2>/dev/null || echo "")
fi
if [ -z "$NCCL_LFLAG" ]; then
    NCCL_LFLAG=$(python -c "import nvidia.nccl, os; print('-L' + os.path.join(nvidia.nccl.__path__[0], 'lib'))" 2>/dev/null || echo "")
fi

WHEEL_RPATH_FLAGS=()
for lib_flag in "$CUDNN_LFLAG" "$NCCL_LFLAG"; do
    if [[ "$lib_flag" == -L* ]]; then
        WHEEL_RPATH_FLAGS+=("-Wl,-rpath,${lib_flag#-L}")
    fi
done

export CCACHE_DIR="${CCACHE_DIR:-$HOME/.ccache}"
export CCACHE_BASEDIR="$(pwd)"
export CCACHE_COMPILERCHECK=content
NVCC="ccache $CUDA_HOME/bin/nvcc"
CC="${CC:-$(command -v ccache >/dev/null && echo 'ccache clang' || echo 'clang')}"
ARCH=${NVCC_ARCH:-native}

PYTHON_INCLUDE=$(python -c "import sysconfig; print(sysconfig.get_path('include'))")
PYBIND_INCLUDE=$(python -c "import pybind11; print(pybind11.get_include())")
NUMPY_INCLUDE=$(python -c "import numpy; print(numpy.get_include())")
EXT_SUFFIX=$(python -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))")
OUTPUT="pufferlib/_C${EXT_SUFFIX}"

BINDING_SRC="$SRC_DIR/binding.c"
mkdir -p build
STATIC_OBJ="build/libstatic_${ENV}.o"
STATIC_LIB="build/libstatic_${ENV}.a"

if [ ! -f "$BINDING_SRC" ]; then
    echo "Error: $BINDING_SRC not found"
    exit 1
fi

echo "Compiling static library for $ENV..."
${CC:-clang} -c "${CLANG_OPT[@]}" $EXTRA_CFLAGS \
    -I. -Isrc -I$SRC_DIR -Ivendor \
    "${INCLUDES[@]}" \
    -I./$RAYLIB_NAME/include -I$CUDA_HOME/include \
    -DPLATFORM_DESKTOP \
    -fno-semantic-interposition -fvisibility=hidden \
    -fPIC -fopenmp \
    "$BINDING_SRC" -o "$STATIC_OBJ"
ar rcs "$STATIC_LIB" "$STATIC_OBJ"

# Brittle hack: have to extract the tensor type from the static lib to build trainer
OBS_TENSOR_T=$(awk '/^#define OBS_TENSOR_T/{print $3}' "$BINDING_SRC")
if [ -z "$OBS_TENSOR_T" ]; then
    echo "Error: Could not find OBS_TENSOR_T in $BINDING_SRC"
    exit 1
fi

if [ -z "$MODE" ]; then
    echo "Compiling CUDA ($ARCH) training backend..."
    $NVCC -c -arch=$ARCH -Xcompiler -fPIC \
        -Xcompiler=-D_GLIBCXX_USE_CXX11_ABI=1 \
        -Xcompiler=-DNPY_NO_DEPRECATED_API=NPY_1_7_API_VERSION \
        -Xcompiler=-DPLATFORM_DESKTOP \
        -std=c++17 \
        -I. -Isrc \
        -I$PYTHON_INCLUDE -I$PYBIND_INCLUDE -I$NUMPY_INCLUDE \
        -I$CUDA_HOME/include $CUDNN_IFLAG $NCCL_IFLAG -I$RAYLIB_NAME/include \
        -Xcompiler=-fopenmp \
        -DOBS_TENSOR_T=$OBS_TENSOR_T \
        -DENV_NAME=$ENV \
        $PRECISION $NVCC_OPT \
        src/bindings.cu -o build/bindings.o

    LINK_CMD=(
        ${CXX:-g++} -shared -fPIC -fopenmp
        build/bindings.o "$STATIC_LIB" "$RAYLIB_A"
        -L$CUDA_HOME/lib64 $CUDNN_LFLAG $NCCL_LFLAG
        "${WHEEL_RPATH_FLAGS[@]}"
        "${EXTRA_LDFLAGS[@]}"
        -lcudart -lnccl -lnvidia-ml -lcublas -lcusolver -lcurand -lcudnn
        $OMP_LIB $LINK_OPT
        "${SHARED_LDFLAGS[@]}"
        -o "$OUTPUT"
    )
    "${LINK_CMD[@]}"
    echo "Built: $OUTPUT"

elif [ "$MODE" = "cpu" ]; then
    echo "Compiling CPU training backend..."
    ${CXX:-g++} -c -fPIC -fopenmp \
        -D_GLIBCXX_USE_CXX11_ABI=1 \
        -DPLATFORM_DESKTOP \
        -std=c++17 \
        -I. -Isrc \
        -I$PYTHON_INCLUDE -I$PYBIND_INCLUDE \
        -DOBS_TENSOR_T=$OBS_TENSOR_T \
        -DENV_NAME=$ENV \
        $PRECISION $LINK_OPT \
        src/bindings_cpu.cpp -o build/bindings_cpu.o
    LINK_CMD=(
        ${CXX:-g++} -shared -fPIC -fopenmp
        build/bindings_cpu.o "$STATIC_LIB" "$RAYLIB_A"
        "${EXTRA_LDFLAGS[@]}"
        -lm -lpthread $OMP_LIB $LINK_OPT

diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..99774f8dfb71f3f99dfd14ddaa48a8432093ee30
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,192 @@
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
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

codex
The snapshot is stale and not a symlink, so the normal `vendor/PufferLib/build.sh bloodbowl ...` would compile old code unless I refreshed files outside the allowed edit set. I’m doing a narrower compile check against `puffer/bloodbowl/bloodbowl.c` directly, which exercises the edited binding header without modifying the snapshot.
exec
/bin/zsh -lc "rg -n \"#include \\\".*\\.c\\\"|engine/src|bb_procgen\" puffer/bloodbowl/bloodbowl.h puffer/bloodbowl/bloodbowl.c vendor/PufferLib/ocean/bloodbowl/bloodbowl.h | head -80" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
puffer/bloodbowl/bloodbowl.h:66:#include "engine/bb_match.c"
puffer/bloodbowl/bloodbowl.h:67:#include "engine/bb_rng.c"
puffer/bloodbowl/bloodbowl.h:68:#include "engine/bb_replay.c"
puffer/bloodbowl/bloodbowl.h:69:#include "engine/bb_skills.c"
puffer/bloodbowl/bloodbowl.h:70:#include "engine/bb_hooks.c"
puffer/bloodbowl/bloodbowl.h:71:#include "engine/bb_procgen.c"
puffer/bloodbowl/bloodbowl.h:72:#include "engine/gen_skills.c"
puffer/bloodbowl/bloodbowl.h:73:#include "engine/gen_teams.c"
puffer/bloodbowl/bloodbowl.h:74:#include "engine/gen_tables.c"
puffer/bloodbowl/bloodbowl.h:75:#include "engine/skills_core.c"
puffer/bloodbowl/bloodbowl.h:76:#include "engine/skills_agility.c"
puffer/bloodbowl/bloodbowl.h:77:#include "engine/skills_devious_traits.c"
puffer/bloodbowl/bloodbowl.h:78:#include "engine/skills_mutation_passing.c"
puffer/bloodbowl/bloodbowl.h:79:#include "engine/proc_table.c"
puffer/bloodbowl/bloodbowl.h:80:#include "engine/proc_test.c"
puffer/bloodbowl/bloodbowl.h:81:#include "engine/proc_turn.c"
puffer/bloodbowl/bloodbowl.h:82:#include "engine/proc_move.c"
puffer/bloodbowl/bloodbowl.h:83:#include "engine/proc_block.c"
puffer/bloodbowl/bloodbowl.h:84:#include "engine/proc_ttm.c"
puffer/bloodbowl/bloodbowl.h:85:#include "engine/bb_blockev.c"
puffer/bloodbowl/bloodbowl.h:88:#include "engine/proc_ball.c"
puffer/bloodbowl/bloodbowl.h:91:#include "engine/proc_match.c"
puffer/bloodbowl/bloodbowl.h:548:        // roster list (10) plus the procgen advancement cap (bb_procgen.c
puffer/bloodbowl/bloodbowl.h:1316:            bb_procgen_params pp = {
puffer/bloodbowl/bloodbowl.h:1325:            bb_procgen_params pp = {
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:66:#include "engine/bb_match.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:67:#include "engine/bb_rng.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:68:#include "engine/bb_replay.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:69:#include "engine/bb_skills.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:70:#include "engine/bb_hooks.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:71:#include "engine/bb_procgen.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:72:#include "engine/gen_skills.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:73:#include "engine/gen_teams.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:74:#include "engine/gen_tables.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:75:#include "engine/skills_core.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:76:#include "engine/skills_agility.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:77:#include "engine/skills_devious_traits.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:78:#include "engine/skills_mutation_passing.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:79:#include "engine/proc_table.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:80:#include "engine/proc_test.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:81:#include "engine/proc_turn.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:82:#include "engine/proc_move.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:83:#include "engine/proc_block.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:84:#include "engine/proc_ttm.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:85:#include "engine/bb_blockev.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:88:#include "engine/proc_ball.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:91:#include "engine/proc_match.c"
vendor/PufferLib/ocean/bloodbowl/bloodbowl.h:441:        // roster list (10) plus the procgen advancement cap (bb_procgen.c

diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..99774f8dfb71f3f99dfd14ddaa48a8432093ee30
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,192 @@
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
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

exec
/bin/zsh -lc 'find puffer/bloodbowl -maxdepth 2 -type d -print && ls -l puffer/bloodbowl/engine puffer/bloodbowl/bb 2>/dev/null || true' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
puffer/bloodbowl
lrwxr-xr-x@ 1 alexanderhuth  staff  23 Jun  4 17:57 puffer/bloodbowl/bb -> ../../engine/include/bb
lrwxr-xr-x@ 1 alexanderhuth  staff  16 Jun  3 07:20 puffer/bloodbowl/engine -> ../../engine/src

exec
/bin/zsh -lc "sed -n '1,110p' puffer/bloodbowl/bloodbowl.h" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
// bloodbowl.h — PufferLib 4.0 native env wrapping the BB2025 engine.
//
// Two agents per match (home/away coach). Each c_step applies the DECIDING
// agent's action (the other agent's action is ignored that step), advances the
// engine to the next decision, and emits observations + per-head legality
// masks. Episodes are full matches over procedurally generated rosters.
//
// Observation (uint8, BBE_OBS_SIZE = 2782B, obs v4), egocentric: each agent
// sees its own players first and the pitch x-mirrored for the away coach, so
// "forward" is always +x. Layout (offsets from the BBE_* macros below):
//   [0..767]   32 players x BBE_PLAYER_BYTES (24): rows 0-15 = my team,
//              16-31 = opponent (row = slot, XOR 16 for the away agent):
//                [0]  x+1, [1] y+1 (0 = off pitch; x mirrored for away)
//                [2]  location (bb_loc), [3] stance (bb_stance)
//                [4]  flags low byte, [5] flags high byte (BB_PF_*)
//                [6..10]  ma, st, ag, pa, av
//                [11..22] skill ids x BBE_SKILL_SLOTS (12) (id+1, 0 = none)
//                [23] opposing tackle zones marking the player's square
//                     (on-pitch only, else 0)
//   [768..783] ball + decision context (BBE_CTX_OFF):
//                [0]  ball state (bb_ball_state)
//                [1]  ball x+1, [2] ball y+1 (0 = off pitch)
//                [3]  carrier row+1 (0 = none)
//                [4]  top-frame proc (bb_proc), [5] its phase
//                [6]  frame a as row+1 when the proc stores a player slot
//                     there (bbe_frame_a_is_slot), else 0
//                [7]  frame b likewise (bbe_frame_b_is_slot)
//                [8]  pending TEST target number (2..6 when the top frame
//                     is a TEST reroll window, else 0)
//                [9]  spare
//                [10] I am the deciding coach, [11] my team is active
//                [12..15] spare
//   [784..831] scalars (BBE_SCALAR_OFF):
//                [0]  half, [1] my turn, [2] opp turn
//                [3]  my score, [4] opp score
//                [5]  my rerolls, [6] opp rerolls, [7] weather
//                [8..13] blitz/pass/handoff/foul/ttm/secure used this turn
//                [14] my apothecaries, [15] opp apothecaries
//                [16] my bribes, [17] opp bribes, [18] I am kicking
//                [19..47] spare (team ids deliberately NOT observed — see
//                         the encoder comment; forces roster-reading)
//   [832..1611] tackle-zone planes (obs v3, BBE_TZ_OFF): two per-square
//              TZ-count planes of 390 bytes each (index y*26 + x, x
//              mirrored for the away agent like every spatial feature):
//                [832..1221]  TZs exerted by MY players on each square
//                [1222..1611] TZs exerted by OPPONENT players on each square
//              The opponent plane is destination danger: dodging into /
//              out of coverage was unobservable per-square before v3 (only
//              the mover's own marked count, player byte [23], was visible).
//
// Action heads (ACT_SIZES {30, 33, 391}): bb_action type | arg (0-31 direct,
// 32 = sentinel for 0xFE/0xFF args) | square (y*26+x, 390 = none).
// Decoding snaps to the nearest legal action (exact -> same-type -> first),
// so even maskless backends (torch/MPS practice runs) stay legal.
#pragma once

#include <stdlib.h>
#include <string.h>

// --- Engine amalgamation (build.sh compiles binding.c as a single TU) -------
// `engine/` and `bb/` next to this header are symlinks in the dev tree
// (-> ../../engine/{src,include/bb}) and real copies in the installed
// vendor/PufferLib/ocean/bloodbowl/ tree (tools/install_puffer_env.sh uses
// cp -RL). Three sources define a file-local DIR8 table; rename per "TU".
#define DIR8 DIR8_match_tu
#include "engine/bb_match.c"
#include "engine/bb_rng.c"
#include "engine/bb_replay.c"
#include "engine/bb_skills.c"
#include "engine/bb_hooks.c"
#include "engine/bb_procgen.c"
#include "engine/gen_skills.c"
#include "engine/gen_teams.c"
#include "engine/gen_tables.c"
#include "engine/skills_core.c"
#include "engine/skills_agility.c"
#include "engine/skills_devious_traits.c"
#include "engine/skills_mutation_passing.c"
#include "engine/proc_table.c"
#include "engine/proc_test.c"
#include "engine/proc_turn.c"
#include "engine/proc_move.c"
#include "engine/proc_block.c"
#include "engine/proc_ttm.c"
#include "engine/bb_blockev.c"
#undef DIR8
#define DIR8 DIR8_ball_tu
#include "engine/proc_ball.c"
#undef DIR8
#define DIR8 DIR8_kick_tu
#include "engine/proc_match.c"
#undef DIR8

#define BBE_PLAYER_BYTES 24    // 11 stat/state bytes + 12 skill-id slots + TZ byte
#define BBE_SKILL_SLOTS 12     // >= max base-roster skills (10) + procgen cap
#define BBE_OBS_SIZE 2782      // v3 1612 + 3*390 decision-support planes (obs v4)
#define BBE_CTX_OFF (BB_NUM_PLAYERS * BBE_PLAYER_BYTES) // 768
#define BBE_SCALAR_OFF (BBE_CTX_OFF + 16)               // 784
#define BBE_TZ_OFF (BBE_SCALAR_OFF + 48)                // 832
#define BBE_TZ_PLANE (BB_PITCH_LEN * BB_PITCH_WID)      // 390 bytes per plane
#define BBE_HEAD_TYPE 30
#define BBE_HEAD_ARG 33
#define BBE_HEAD_SQ 391
#define BBE_MASK_SIZE (BBE_HEAD_TYPE + BBE_HEAD_ARG + BBE_HEAD_SQ)
#define BBE_AGENTS 2
#define BBE_MAX_DECISIONS 4096 // episode safety bound
#define BBE_MAX_BANKS 8        // frozen selfplay-pool banks (matches selfplay.py)

_Static_assert(BBE_HEAD_TYPE == BB_A_TYPE_COUNT,
               "action-type head out of sync with bb_actions.h");

diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..99774f8dfb71f3f99dfd14ddaa48a8432093ee30
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,192 @@
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
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

exec
/bin/zsh -lc 'cc -std=c11 -O2 -g -Wall -Wextra -Werror -Ipuffer/bloodbowl puffer/bloodbowl/bloodbowl.c -o build/bloodbowl_local_check' in /Users/alexanderhuth/Code/bloodbowl-rl
 exited 1 in 0ms:
In file included from puffer/bloodbowl/bloodbowl.c:8:
puffer/bloodbowl/bloodbowl.h:1586:20: error: unused function 'bbe_team_archetype' [-Werror,-Wunused-function]
 1586 | static const char* bbe_team_archetype(const Bloodbowl* env, int t) {
      |                    ^~~~~~~~~~~~~~~~~~
puffer/bloodbowl/bloodbowl.h:2003:13: error: unused function 'c_render' [-Werror,-Wunused-function]
 2003 | static void c_render(Bloodbowl* env) {
      |             ^~~~~~~~
2 errors generated.

diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..99774f8dfb71f3f99dfd14ddaa48a8432093ee30
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,192 @@
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
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

codex
The direct local compile hit existing unused-function warnings in the standalone header (`bbe_team_archetype`, `c_render`) under `-Werror`; the repo’s own lockstep build already uses `-Wno-unused-function` for this header style. I’m rerunning the same compile with that existing suppression.
exec
/bin/zsh -lc 'cc -std=c11 -O2 -g -Wall -Wextra -Werror -Wno-unused-function -Ipuffer/bloodbowl puffer/bloodbowl/bloodbowl.c -o build/bloodbowl_local_check' in /Users/alexanderhuth/Code/bloodbowl-rl
diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..99774f8dfb71f3f99dfd14ddaa48a8432093ee30
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,192 @@
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
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

 succeeded in 1124ms:
codex
The edited Puffer env standalone compile passed with the repo’s usual `-Wno-unused-function` suppression. I’m running its `--selftest` next, since that appears to be the binding-level selftest available here.
exec
/bin/zsh -lc './build/bloodbowl_local_check --selftest' in /Users/alexanderhuth/Code/bloodbowl-rl
diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..99774f8dfb71f3f99dfd14ddaa48a8432093ee30
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,192 @@
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
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

 succeeded in 243ms:
bloodbowl selftest: 64 episodes, 0 failure(s), v4 planes B=22237 A=406

codex
Binding selftest passed: `64 episodes, 0 failure(s)`. I’m doing a final readback of the touched hunks and line numbers now so the handoff has the exact edit map and any caveats, including the stale vendor snapshot build constraint.
exec
/bin/zsh -lc "nl -ba engine/include/bb/bb_match.h | sed -n '130,155p'" in /Users/alexanderhuth/Code/bloodbowl-rl
exec
/bin/zsh -lc "nl -ba engine/src/bb_procgen.c | sed -n '20,190p'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
   130	} bb_match;
   131	
   132	// --- Lifecycle -----------------------------------------------------------------
   133	// Initialize a match between two rosters (codegen team ids) with default
   134	// matchday squads (first 11+ players per roster definition). Procedural/custom
   135	// squads come via bb_match_init_custom (Phase 5).
   136	void bb_match_init(bb_match* m, int home_team_id, int away_team_id);
   137	
   138	// Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
   139	// (the procgen stream, not the in-match dice stream).
   140	typedef struct {
   141	    int skillup_max_players;   // advancement draws per team, with replacement
   142	    int skillup_max_each;      // max skills gained per draw, uniform 1..N
   143	    float skillup_secondary_pct; // P(draw category from secondary_mask)
   144	} bb_procgen_params;
   145	
   146	bb_procgen_params bb_procgen_params_default(void);
   147	void bb_match_init_random(bb_match* m, bb_rng* rng);
   148	void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
   149	// home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
   150	void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
   151	void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
   152	                            const bb_procgen_params* pp);
   153	
   154	// Advance the engine until a coach decision is required or the match ends.
   155	// All dice are drawn from `rng`. Returns the resulting status.

 succeeded in 0ms:
    20	// the largest base roster list is 10, so capping advancement at 12 keeps the
    21	// obs lossless. Raise both together if star players ever exceed this.
    22	#define PG_MAX_SKILLS 12
    23	
    24	static int pg_skill_count(const bb_skillset* s) {
    25	    int n = 0;
    26	    for (int sk = bb_next_skill(s, 0); sk >= 0; sk = bb_next_skill(s, sk + 1)) n++;
    27	    return n;
    28	}
    29	
    30	static float pg_float01(bb_rng* rng) {
    31	    return (float)(bb_rng_next(rng) >> 8) * (1.0f / 16777216.0f);
    32	}
    33	
    34	bb_procgen_params bb_procgen_params_default(void) {
    35	    return (bb_procgen_params){4, 2, 0.0f};
    36	}
    37	
    38	// Build one team's squad: positionals first (random counts within limits),
    39	// topped up with the first listed position; then configured random
    40	// advancement skills from primary/secondary categories.
    41	static void procgen_squad(bb_match* m, int team, int team_id, bb_rng* rng,
    42	                          const bb_procgen_params* pp) {
    43	    const bb_team_def* td = &bb_team_defs[team_id];
    44	    int base = team * BB_TEAM_SLOTS;
    45	    int n = 0;
    46	    int counts[BB_MAX_POSITIONS] = {0};
    47	
    48	    // Roster size 11-14.
    49	    int squad = 11 + pg_pick(rng, 4);
    50	
    51	    // Fill positional slots (positions[1..]) with random counts.
    52	    for (int pi = td->num_positions - 1; pi >= 1 && n < squad; pi--) {
    53	        const bb_position_def* pd = &td->positions[pi];
    54	        int want = pg_pick(rng, pd->qty_max + 1);
    55	        while (want-- > 0 && n < squad) {
    56	            // init_player_from_position equivalent (kept local to this TU):
    57	            bb_player* p = &m->players[base + n];
    58	            memset(p, 0, sizeof(*p));
    59	            p->ma = pd->ma;
    60	            p->st = pd->st;
    61	            p->ag = pd->ag;
    62	            p->pa = pd->pa;
    63	            p->av = pd->av;
    64	            p->position_id = (uint8_t)pi;
    65	            p->location = BB_LOC_RESERVES;
    66	            p->stance = BB_STANCE_STANDING;
    67	            p->p_loner = 4;
    68	            for (int s = 0; s < pd->num_skills; s++) {
    69	                bb_add_skill(&p->skills, pd->skills[s]);
    70	                int v = pd->skill_values[s];
    71	                if (v > 0) {
    72	                    if (pd->skills[s] == BB_SK_LONER) p->p_loner = (int8_t)v;
    73	                    if (pd->skills[s] == BB_SK_BLOODLUST) p->p_bloodlust = (int8_t)v;
    74	                }
    75	            }
    76	            counts[pi]++;
    77	            n++;
    78	        }
    79	    }
    80	    // Top up with the first-listed position (linemen).
    81	    while (n < squad) {
    82	        const bb_position_def* pd = &td->positions[0];
    83	        bb_player* p = &m->players[base + n];
    84	        memset(p, 0, sizeof(*p));
    85	        p->ma = pd->ma;
    86	        p->st = pd->st;
    87	        p->ag = pd->ag;
    88	        p->pa = pd->pa;
    89	        p->av = pd->av;
    90	        p->position_id = 0;
    91	        p->location = BB_LOC_RESERVES;
    92	        p->stance = BB_STANCE_STANDING;
    93	        p->p_loner = 4;
    94	        for (int s = 0; s < pd->num_skills; s++) {
    95	            bb_add_skill(&p->skills, pd->skills[s]);
    96	            // Keep the roster's parameterized skill values, like the
    97	            // positional path above — dropping them left p_bloodlust 0
    98	            // (gate silently inert) and p_loner at the default (review LOW).
    99	            int v = pd->skill_values[s];
   100	            if (v > 0) {
   101	                if (pd->skills[s] == BB_SK_LONER) p->p_loner = (int8_t)v;
   102	                if (pd->skills[s] == BB_SK_BLOODLUST) p->p_bloodlust = (int8_t)v;
   103	            }
   104	        }
   105	        n++;
   106	    }
   107	    for (int s = n; s < BB_TEAM_SLOTS; s++) {
   108	        memset(&m->players[base + s], 0, sizeof(bb_player));
   109	        m->players[base + s].location = BB_LOC_ABSENT;
   110	    }
   111	
   112	    // Advancement: players gain random skills from configured category access
   113	    // (the 2D6 random-skill table run "fairly" via the procgen stream).
   114	    int advanced = pp->skillup_max_players > 0 ? pg_pick(rng, pp->skillup_max_players + 1) : 0;
   115	    for (int i = 0; i < advanced; i++) {
   116	        int who = base + pg_pick(rng, n);
   117	        bb_player* p = &m->players[who];
   118	        const bb_position_def* pd = &td->positions[p->position_id];
   119	        if (!(pd->primary_mask || pd->secondary_mask)) continue;
   120	        int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
   121	        for (int g = 0; g < gains; g++) {
   122	            if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;
   123	            uint8_t mask = pd->primary_mask;
   124	            if (pp->skillup_secondary_pct > 0.0f &&
   125	                pg_float01(rng) < pp->skillup_secondary_pct) {
   126	                mask = pd->secondary_mask;
   127	            }
   128	            if (!mask) {
   129	                mask = (mask == pd->primary_mask) ? pd->secondary_mask : pd->primary_mask;
   130	            }
   131	            if (!mask) continue;
   132	            // Pick a random category bit.
   133	            int cats[BB_CAT_COUNT];
   134	            int nc = 0;
   135	            for (int c = 0; c < BB_CAT_COUNT; c++) {
   136	                if (mask & (1 << c)) cats[nc++] = c;
   137	            }
   138	            int cat = cats[pg_pick(rng, nc)];
   139	            int sk = bb_random_skill_table[cat][pg_pick(rng, 12)];
   140	            bb_add_skill(&p->skills, sk);
   141	        }
   142	    }
   143	
   144	    // Pre-game injuries: 0-2 players start in the casualty box (simulating
   145	    // league attrition) — only if the squad stays >= 11. Picks are WITHOUT
   146	    // replacement: sampling the raw slot range could hit the same player
   147	    // twice, under-delivering 2-casualty squads ~7-9% (review LOW).
   148	    int hurt = pg_pick(rng, 3);
   149	    for (int i = 0; i < hurt && n - i > 11; i++) {
   150	        int pick = pg_pick(rng, n - i); // index among the still-healthy
   151	        for (int s = base; s < base + n; s++) {
   152	            if (m->players[s].location == BB_LOC_CAS) continue;
   153	            if (pick-- == 0) {
   154	                m->players[s].location = BB_LOC_CAS;
   155	                break;
   156	            }
   157	        }
   158	    }
   159	}
   160	
   161	static void pg_init_match(bb_match* m, bb_rng* rng, int home, int away,
   162	                          const bb_procgen_params* pp) {
   163	    m->team_id[BB_HOME] = (uint8_t)home;
   164	    m->team_id[BB_AWAY] = (uint8_t)away;
   165	    procgen_squad(m, BB_HOME, home, rng, pp);
   166	    procgen_squad(m, BB_AWAY, away, rng, pp);
   167	    for (int t = 0; t < 2; t++) {
   168	        m->rerolls[t] = m->rerolls_start[t] = (uint8_t)(2 + pg_pick(rng, 3));
   169	        m->apothecary[t] = bb_team_defs[m->team_id[t]].apothecary ? 1 : 0;
   170	    }
   171	    m->half = 1;
   172	    m->ball.state = BB_BALL_OFF_PITCH;
   173	    m->ball.carrier = BB_NO_PLAYER;
   174	    m->status = BB_STATUS_RUNNING;
   175	    bb_push(m, BB_PROC_MATCH, 0, 0, 0, 0);
   176	}
   177	
   178	void bb_match_init_random(bb_match* m, bb_rng* rng) {
   179	    bb_procgen_params pp = bb_procgen_params_default();
   180	    bb_match_init_random_p(m, rng, &pp);
   181	}
   182	
   183	void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp) {
   184	    memset(m, 0, sizeof(*m));
   185	    int home = pg_pick(rng, BB_TEAM_COUNT);
   186	    int away = pg_pick(rng, BB_TEAM_COUNT);
   187	    pg_init_match(m, rng, home, away, pp);
   188	}
   189	
   190	// Holdout / fixed-matchup variant: home/away >= 0 pin that side's team;

exec
/bin/zsh -lc "nl -ba engine/tests/test_match.c | sed -n '218,390p'" in /Users/alexanderhuth/Code/bloodbowl-rl
exec
/bin/zsh -lc "nl -ba puffer/bloodbowl/binding.c | sed -n '86,98p'" in /Users/alexanderhuth/Code/bloodbowl-rl
exec
/bin/zsh -lc "nl -ba puffer/bloodbowl/bloodbowl.h | sed -n '310,325p'; nl -ba puffer/bloodbowl/bloodbowl.h | sed -n '1308,1334p'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
    86	    // Backplay curriculum: scoring-proximal demo resets (0 = uniform)
    87	    env->demo_endzone_maxdist = (int)kw(kwargs, "demo_endzone_maxdist", 0.0);
    88	    // Pickup curriculum (D64): loose-ball-near-mover demo resets (0 = off)
    89	    env->demo_pickup_maxdist = (int)kw(kwargs, "demo_pickup_maxdist", 0.0);
    90	    // Post-kickoff scoop drill (D68): loose ball at team-turn <= N (0 = off)
    91	    env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
    92	    // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
    93	    env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
    94	    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
    95	    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
    96	    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
    97	    // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
    98	    env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);

 succeeded in 0ms:
   310	    // real starting context — 28.5% of the bank qualifies at maxturn 1.
   311	    // Precedence: endzone > pickup > postkick (first nonzero wins).
   312	    int demo_postkick_maxturn;
   313	    // Passing ladder (D72): >0 = demo resets prefer states where the
   314	    // team-to-move holds the ball with a standing downfield receiver within
   315	    // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
   316	    int demo_pass_maxrange;
   317	    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
   318	    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
   319	    int skillup_max_players;
   320	    int skillup_max_each;
   321	    float skillup_secondary_pct;
   322	    // v5 path-actions (D82): when 1, the STEP square head selects ANY
   323	    // reachable destination; the env routes a min-risk path (Dijkstra over
   324	    // dodge/rush costs) and auto-applies it step-by-step, returning control
   325	    // on any interruption (TEST window, knockdown, activation end). The
  1308	    if (!env->demo_started) {
  1309	        // Procgen controls: exclude_team bars a team from training draws
  1310	        // (holdout); force_* pins a side for fixed-matchup eval. NOTE: banked
  1311	        // demo states carry their FUMBBL rosters — neither constraint is
  1312	        // enforced on the demo path (keep demo_reset_pct = 0 for holdout
  1313	        // evals).
  1314	        if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
  1315	            env->force_away_team >= 0) {
  1316	            bb_procgen_params pp = {
  1317	                env->skillup_max_players,
  1318	                env->skillup_max_each,
  1319	                env->skillup_secondary_pct
  1320	            };
  1321	            bb_match_init_forced_p(&env->match, &env->procgen,
  1322	                                   env->force_home_team, env->force_away_team,
  1323	                                   env->exclude_team, &pp);
  1324	        } else {
  1325	            bb_procgen_params pp = {
  1326	                env->skillup_max_players,
  1327	                env->skillup_max_each,
  1328	                env->skillup_secondary_pct
  1329	            };
  1330	            bb_match_init_random_p(&env->match, &env->procgen, &pp);
  1331	        }
  1332	    }
  1333	    // Fresh in-match dice stream either way; a resumed state replays under
  1334	    // new dice. bb_advance is a no-op for a banked state (already at a

 succeeded in 0ms:
   218	        if (m->players[s].location != BB_LOC_ABSENT) n++;
   219	    }
   220	    return n;
   221	}
   222	
   223	static void check_procgen_structure(const bb_match* m) {
   224	    for (int t = 0; t < 2; t++) {
   225	        int counts[BB_MAX_POSITIONS] = {0};
   226	        const bb_team_def* td = &bb_team_defs[m->team_id[t]];
   227	        int total = 0;
   228	        for (int s = t * BB_TEAM_SLOTS; s < (t + 1) * BB_TEAM_SLOTS; s++) {
   229	            const bb_player* p = &m->players[s];
   230	            if (p->location == BB_LOC_ABSENT) continue;
   231	            BB_CHECK(p->position_id < td->num_positions);
   232	            if (p->position_id < td->num_positions) counts[p->position_id]++;
   233	            total++;
   234	        }
   235	        BB_CHECK(total >= 11);
   236	        BB_CHECK(total <= 14);
   237	        for (int pi = 0; pi < td->num_positions; pi++) {
   238	            BB_CHECK(counts[pi] <= td->positions[pi].qty_max);
   239	        }
   240	    }
   241	}
   242	
   243	static int procgen_count_skills(const bb_skillset* s) {
   244	    int n = 0;
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
   281	BB_TEST(match_procgen_default_params_match_legacy_api) {
   282	    bb_procgen_params pp = bb_procgen_params_default();
   283	    bb_match a, b;
   284	    bb_rng r1, r2;
   285	    bb_rng_seed(&r1, 0x515A5EEDu, 17);
   286	    bb_rng_seed(&r2, 0x515A5EEDu, 17);
   287	    bb_match_init_random(&a, &r1);
   288	    bb_match_init_random_p(&b, &r2, &pp);
   289	    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
   290	    BB_CHECK(procgen_rng_same_state(&r1, &r2));
   291	}
   292	
   293	BB_TEST(match_procgen_skillups_off_keeps_base_skills) {
   294	    bb_procgen_params pp = {0, 2, 0.0f};
   295	    for (uint64_t seed = 1; seed <= 50; seed++) {
   296	        bb_match m;
   297	        bb_rng pg;
   298	        bb_rng_seed(&pg, seed * 2654435761u, 23);
   299	        bb_match_init_random_p(&m, &pg, &pp);
   300	        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
   301	            const bb_player* p = &m.players[s];
   302	            if (p->location == BB_LOC_ABSENT) continue;
   303	            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
   304	            bb_skillset base = base_position_skills(&td->positions[p->position_id]);
   305	            BB_CHECK_EQ(memcmp(&p->skills, &base, sizeof(bb_skillset)), 0);
   306	        }
   307	    }
   308	}
   309	
   310	BB_TEST(match_procgen_primary_only_uses_primary_categories) {
   311	    bb_procgen_params pp = {11, 3, 0.0f};
   312	    for (uint64_t seed = 1; seed <= 250; seed++) {
   313	        bb_match m;
   314	        bb_rng pg;
   315	        bb_rng_seed(&pg, seed * 7919, 29);
   316	        bb_match_init_random_p(&m, &pg, &pp);
   317	        check_procgen_grants_in_mask(&m, 0);
   318	    }
   319	}
   320	
   321	BB_TEST(match_procgen_secondary_only_uses_secondary_or_primary_fallback) {
   322	    bb_procgen_params pp = {11, 3, 1.0f};
   323	    for (uint64_t seed = 1; seed <= 250; seed++) {
   324	        bb_match m;
   325	        bb_rng pg;
   326	        bb_rng_seed(&pg, seed * 104729, 31);
   327	        bb_match_init_random_p(&m, &pg, &pp);
   328	        check_procgen_grants_in_mask(&m, 1);
   329	    }
   330	}
   331	
   332	BB_TEST(match_procgen_skillups_reach_full_learnable_catalogue) {
   333	    bb_procgen_params pp = {11, 3, 0.5f};
   334	    uint8_t seen[BB_NUM_SKILLS] = {0};
   335	    int nseen = 0;
   336	    for (uint64_t seed = 1; seed <= 10000 && nseen < BB_NUM_SKILLS; seed++) {
   337	        bb_match m;
   338	        bb_rng pg;
   339	        bb_rng_seed(&pg, 0xC0FFEEu + seed * 17, 37);
   340	        bb_match_init_random_p(&m, &pg, &pp);
   341	        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
   342	            const bb_player* p = &m.players[s];
   343	            if (p->location == BB_LOC_ABSENT) continue;
   344	            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
   345	            const bb_position_def* pd = &td->positions[p->position_id];
   346	            bb_skillset base = base_position_skills(pd);
   347	            for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
   348	                 sk = bb_next_skill(&p->skills, sk + 1)) {
   349	                if (sk >= BB_NUM_SKILLS || bb_has_skill(&base, sk)) continue;
   350	                if (!seen[sk]) {
   351	                    seen[sk] = 1;
   352	                    nseen++;
   353	                }
   354	            }
   355	        }
   356	    }
   357	    BB_CHECK_EQ(nseen, BB_NUM_SKILLS);
   358	    if (nseen != BB_NUM_SKILLS) {
   359	        for (int sk = 0; sk < BB_NUM_SKILLS; sk++) {
   360	            if (!seen[sk]) printf("  missing skill %d (%s)\n", sk, bb_skill_defs[sk].id);
   361	        }
   362	    }
   363	}
   364	
   365	BB_TEST(match_procgen_cranked_params_respect_cap_and_structure) {
   366	    bb_procgen_params pp = {16, 12, 0.5f};
   367	    for (uint64_t seed = 1; seed <= 200; seed++) {
   368	        bb_match m;
   369	        bb_rng pg;
   370	        bb_rng_seed(&pg, seed * 16127, 41);
   371	        bb_match_init_random_p(&m, &pg, &pp);
   372	        check_procgen_structure(&m);
   373	        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
   374	            if (m.players[s].location == BB_LOC_ABSENT) continue;
   375	            BB_CHECK(procgen_count_skills(&m.players[s].skills) <= 12);
   376	        }
   377	        BB_CHECK(procgen_squad_total(&m, BB_HOME) >= 11);
   378	        BB_CHECK(procgen_squad_total(&m, BB_AWAY) >= 11);
   379	    }
   380	}
   381	
   382	BB_TEST(match_procgen_params_are_deterministic) {
   383	    bb_procgen_params pp = {11, 3, 0.35f};
   384	    bb_match a, b;
   385	    bb_rng r1, r2;
   386	    bb_rng_seed(&r1, 0x12345678u, 43);
   387	    bb_rng_seed(&r2, 0x12345678u, 43);
   388	    bb_match_init_random_p(&a, &r1, &pp);
   389	    bb_match_init_random_p(&b, &r2, &pp);
   390	    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);

exec
/bin/zsh -lc "nl -ba puffer/config/bloodbowl.ini | sed -n '104,116p'; nl -ba vendor/PufferLib/config/bloodbowl.ini | sed -n '84,98p'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
   104	# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
   105	# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
   106	# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
   107	skillup_max_players = 4
   108	skillup_max_each = 2
   109	skillup_secondary_pct = 0.0
   110	# v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
   111	# destination; the env routes a min-risk path and auto-executes it, returning
   112	# control on interruptions. 0 = v4 stepwise semantics (bit-identical).
   113	macro_moves = 0
   114	# Surfs: charged at the deterministic crowd-push event, dice-independent.
   115	# Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
   116	reward_surf_taken = 0.0
    84	# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
    85	# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
    86	# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
    87	skillup_max_players = 4
    88	skillup_max_each = 2
    89	skillup_secondary_pct = 0.0
    90	# Surfs: charged at the deterministic crowd-push event, dice-independent.
    91	# Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
    92	reward_surf_taken = 0.0
    93	reward_surf_inflicted = 0.0
    94	# --- Profile C: exposure-EV transfer + sequencing charge (D33) -------------
    95	# Zero-sum transfer at every block/blitz DECLARATION, priced by the
    96	# closed-form skill-transformed block tree (engine bb_blockev, validated by
    97	# make blockev-mc + 12 unit tests): k_kd * P(def down) + k_value *
    98	# P(def removed) * cost/100k + k_ball * P(ball dislodged). Dice outcomes

diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..99774f8dfb71f3f99dfd14ddaa48a8432093ee30
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,192 @@
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
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

exec
/bin/zsh -lc "nl -ba engine/tests/test_match.c | sed -n '200,218p;390,394p'; nl -ba engine/src/bb_procgen.c | sed -n '190,220p'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
   200	                n++;
   201	            }
   202	            BB_CHECK(n <= 12);
   203	            if (n > 12) return;
   204	        }
   205	    }
   206	}
   207	
   208	static bb_skillset base_position_skills(const bb_position_def* pd) {
   209	    bb_skillset s;
   210	    memset(&s, 0, sizeof s);
   211	    for (int i = 0; i < pd->num_skills; i++) bb_add_skill(&s, pd->skills[i]);
   212	    return s;
   213	}
   214	
   215	static int procgen_squad_total(const bb_match* m, int team) {
   216	    int n = 0;
   217	    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
   218	        if (m->players[s].location != BB_LOC_ABSENT) n++;
   390	    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
   391	    BB_CHECK(procgen_rng_same_state(&r1, &r2));
   392	}
   393	
   394	BB_TEST(match_procgen_games_complete) {
   190	// Holdout / fixed-matchup variant: home/away >= 0 pin that side's team;
   191	// exclude >= 0 redraws any random side that lands on the excluded id (the
   192	// held-out-team generalization experiments train with exclude set and
   193	// evaluate with force_* set).
   194	void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude) {
   195	    bb_procgen_params pp = bb_procgen_params_default();
   196	    bb_match_init_forced_p(m, rng, home, away, exclude, &pp);
   197	}
   198	
   199	void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
   200	                            const bb_procgen_params* pp) {
   201	    memset(m, 0, sizeof(*m));
   202	    int h = home;
   203	    while (h < 0 || (home < 0 && h == exclude)) {
   204	        h = pg_pick(rng, BB_TEAM_COUNT);
   205	        if (home < 0 && h == exclude) h = -1;
   206	    }
   207	    int a = away;
   208	    while (a < 0 || (away < 0 && a == exclude)) {
   209	        a = pg_pick(rng, BB_TEAM_COUNT);
   210	        if (away < 0 && a == exclude) a = -1;
   211	    }
   212	    pg_init_match(m, rng, h, a, pp);
   213	}

diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..99774f8dfb71f3f99dfd14ddaa48a8432093ee30
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,192 @@
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
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

codex
One subtle thing I noticed in readback: the direct PufferLib snapshot under `vendor/PufferLib/ocean/bloodbowl/` is stale relative to `puffer/bloodbowl/`, which matches the repo warning in `CLAUDE.md`. I did not refresh it because that would modify a wider installed snapshot outside the allowed edit map.
exec
/bin/zsh -lc 'git diff -- engine/include/bb/bb_match.h engine/src/bb_procgen.c puffer/bloodbowl/bloodbowl.h puffer/bloodbowl/binding.c puffer/config/bloodbowl.ini vendor/PufferLib/config/bloodbowl.ini engine/tests/test_match.c' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a7..9a3de20 100644
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@ void bb_match_init(bb_match* m, int home_team_id, int away_team_id);
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
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
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc9..5101216 100644
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@ static void apply_kwargs(Env* env, Dict* kwargs) {
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15..b57de13 100644
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@ typedef struct {
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@ static void bbe_reset_match(Bloodbowl* env) {
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a..d623440 100644
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@ demo_postkick_maxturn = 0
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).

exec
/bin/zsh -lc 'rg -n "skillup_max|skillup_secondary|bb_match_init_random_p|bb_match_init_forced_p|bb_procgen_params" engine puffer vendor/PufferLib/config/bloodbowl.ini vendor/PufferLib/ocean/bloodbowl | head -100' in /Users/alexanderhuth/Code/bloodbowl-rl
diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..99774f8dfb71f3f99dfd14ddaa48a8432093ee30
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,192 @@
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
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

 succeeded in 120ms:
vendor/PufferLib/config/bloodbowl.ini:87:skillup_max_players = 4
vendor/PufferLib/config/bloodbowl.ini:88:skillup_max_each = 2
vendor/PufferLib/config/bloodbowl.ini:89:skillup_secondary_pct = 0.0
puffer/bloodbowl/bloodbowl.h:319:    int skillup_max_players;
puffer/bloodbowl/bloodbowl.h:320:    int skillup_max_each;
puffer/bloodbowl/bloodbowl.h:321:    float skillup_secondary_pct;
puffer/bloodbowl/bloodbowl.h:1316:            bb_procgen_params pp = {
puffer/bloodbowl/bloodbowl.h:1317:                env->skillup_max_players,
puffer/bloodbowl/bloodbowl.h:1318:                env->skillup_max_each,
puffer/bloodbowl/bloodbowl.h:1319:                env->skillup_secondary_pct
puffer/bloodbowl/bloodbowl.h:1321:            bb_match_init_forced_p(&env->match, &env->procgen,
puffer/bloodbowl/bloodbowl.h:1325:            bb_procgen_params pp = {
puffer/bloodbowl/bloodbowl.h:1326:                env->skillup_max_players,
puffer/bloodbowl/bloodbowl.h:1327:                env->skillup_max_each,
puffer/bloodbowl/bloodbowl.h:1328:                env->skillup_secondary_pct
puffer/bloodbowl/bloodbowl.h:1330:            bb_match_init_random_p(&env->match, &env->procgen, &pp);
engine/src/bb_procgen.c:34:bb_procgen_params bb_procgen_params_default(void) {
engine/src/bb_procgen.c:35:    return (bb_procgen_params){4, 2, 0.0f};
engine/src/bb_procgen.c:42:                          const bb_procgen_params* pp) {
engine/src/bb_procgen.c:114:    int advanced = pp->skillup_max_players > 0 ? pg_pick(rng, pp->skillup_max_players + 1) : 0;
engine/src/bb_procgen.c:120:        int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
engine/src/bb_procgen.c:124:            if (pp->skillup_secondary_pct > 0.0f &&
engine/src/bb_procgen.c:125:                pg_float01(rng) < pp->skillup_secondary_pct) {
engine/src/bb_procgen.c:162:                          const bb_procgen_params* pp) {
engine/src/bb_procgen.c:179:    bb_procgen_params pp = bb_procgen_params_default();
engine/src/bb_procgen.c:180:    bb_match_init_random_p(m, rng, &pp);
engine/src/bb_procgen.c:183:void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp) {
engine/src/bb_procgen.c:195:    bb_procgen_params pp = bb_procgen_params_default();
engine/src/bb_procgen.c:196:    bb_match_init_forced_p(m, rng, home, away, exclude, &pp);
engine/src/bb_procgen.c:199:void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
engine/src/bb_procgen.c:200:                            const bb_procgen_params* pp) {
puffer/bloodbowl/binding.c:94:    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
puffer/bloodbowl/binding.c:95:    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
puffer/bloodbowl/binding.c:96:    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
puffer/config/bloodbowl.ini:107:skillup_max_players = 4
puffer/config/bloodbowl.ini:108:skillup_max_each = 2
puffer/config/bloodbowl.ini:109:skillup_secondary_pct = 0.0
engine/tests/test_match.c:282:    bb_procgen_params pp = bb_procgen_params_default();
engine/tests/test_match.c:288:    bb_match_init_random_p(&b, &r2, &pp);
engine/tests/test_match.c:294:    bb_procgen_params pp = {0, 2, 0.0f};
engine/tests/test_match.c:299:        bb_match_init_random_p(&m, &pg, &pp);
engine/tests/test_match.c:311:    bb_procgen_params pp = {11, 3, 0.0f};
engine/tests/test_match.c:316:        bb_match_init_random_p(&m, &pg, &pp);
engine/tests/test_match.c:322:    bb_procgen_params pp = {11, 3, 1.0f};
engine/tests/test_match.c:327:        bb_match_init_random_p(&m, &pg, &pp);
engine/tests/test_match.c:333:    bb_procgen_params pp = {11, 3, 0.5f};
engine/tests/test_match.c:340:        bb_match_init_random_p(&m, &pg, &pp);
engine/tests/test_match.c:366:    bb_procgen_params pp = {16, 12, 0.5f};
engine/tests/test_match.c:371:        bb_match_init_random_p(&m, &pg, &pp);
engine/tests/test_match.c:383:    bb_procgen_params pp = {11, 3, 0.35f};
engine/tests/test_match.c:388:    bb_match_init_random_p(&a, &r1, &pp);
engine/tests/test_match.c:389:    bb_match_init_random_p(&b, &r2, &pp);
engine/include/bb/bb_match.h:141:    int skillup_max_players;   // advancement draws per team, with replacement
engine/include/bb/bb_match.h:142:    int skillup_max_each;      // max skills gained per draw, uniform 1..N
engine/include/bb/bb_match.h:143:    float skillup_secondary_pct; // P(draw category from secondary_mask)
engine/include/bb/bb_match.h:144:} bb_procgen_params;
engine/include/bb/bb_match.h:146:bb_procgen_params bb_procgen_params_default(void);
engine/include/bb/bb_match.h:148:void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
engine/include/bb/bb_match.h:151:void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
engine/include/bb/bb_match.h:152:                            const bb_procgen_params* pp);

codex
Implemented the configurable procgen skillup knobs end to end, with default behavior pinned to the legacy procgen stream. No git state was touched: no commit, push, checkout, stash, or reset.

**Edit Map**
- [engine/include/bb/bb_match.h](/Users/alexanderhuth/Code/bloodbowl-rl/engine/include/bb/bb_match.h:140): added `bb_procgen_params`, `bb_procgen_params_default`, and `_p` procgen init APIs.
- [engine/src/bb_procgen.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/src/bb_procgen.c:30): added default params, secondary-roll float helper, param threading through match/squad init, and configurable advancement logic.
- [engine/src/bb_procgen.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/src/bb_procgen.c:178): kept legacy `bb_match_init_random` / `bb_match_init_forced` as thin wrappers around defaults.
- [puffer/bloodbowl/bloodbowl.h](/Users/alexanderhuth/Code/bloodbowl-rl/puffer/bloodbowl/bloodbowl.h:317): added env fields `skillup_max_players`, `skillup_max_each`, `skillup_secondary_pct`.
- [puffer/bloodbowl/bloodbowl.h](/Users/alexanderhuth/Code/bloodbowl-rl/puffer/bloodbowl/bloodbowl.h:1316): reset now builds `bb_procgen_params` and calls `_p` variants for both forced and random procgen paths.
- [puffer/bloodbowl/binding.c](/Users/alexanderhuth/Code/bloodbowl-rl/puffer/bloodbowl/binding.c:94): added kwarg reads with defaults `4`, `2`, `0.0`.
- [puffer/config/bloodbowl.ini](/Users/alexanderhuth/Code/bloodbowl-rl/puffer/config/bloodbowl.ini:104): added documented skill-entropy config defaults.
- [vendor/PufferLib/config/bloodbowl.ini](/Users/alexanderhuth/Code/bloodbowl-rl/vendor/PufferLib/config/bloodbowl.ini:84): added same config keys to the duplicate config copy found by `find`.
- [engine/tests/test_match.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/tests/test_match.c:208): added procgen helper assertions and seven focused tests for parity, off switch, category routing, catalogue coverage, cap/structure, and determinism.

**New Tests**
All passed under `make test`:
- `match_procgen_default_params_match_legacy_api`
- `match_procgen_skillups_off_keeps_base_skills`
- `match_procgen_primary_only_uses_primary_categories`
- `match_procgen_secondary_only_uses_secondary_or_primary_fallback`
- `match_procgen_skillups_reach_full_learnable_catalogue`
- `match_procgen_cranked_params_respect_cap_and_structure`
- `match_procgen_params_are_deterministic`

**Verification**
`make test` from repo root passed. The output is long because the harness prints every test; the exact procgen section and final summary were:

```text
ok   match_procgen_skill_cap
ok   match_procgen_default_params_match_legacy_api
ok   match_procgen_skillups_off_keeps_base_skills
ok   match_procgen_primary_only_uses_primary_categories
ok   match_procgen_secondary_only_uses_secondary_or_primary_fallback
ok   match_procgen_skillups_reach_full_learnable_catalogue
ok   match_procgen_cranked_params_respect_cap_and_structure
ok   match_procgen_params_are_deterministic
ok   match_procgen_games_complete
...
345 tests, 0 failures
```

The full `make test` command also rebuilt the touched engine objects and linked `build/bb_tests` cleanly under `-Wall -Wextra -Werror`.

I also ran a binding-level local compile check against the edited source tree:

```text
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Wno-unused-function -Ipuffer/bloodbowl puffer/bloodbowl/bloodbowl.c -o build/bloodbowl_local_check
```

That compile produced no output and exited `0`.

Then I ran the available binding selftest:

```text
./build/bloodbowl_local_check --selftest
bloodbowl selftest: 64 episodes, 0 failure(s), v4 planes B=22237 A=406
```

**Deviations**
- I did not run `vendor/PufferLib/build.sh bloodbowl --float`. The compiled PufferLib env uses `vendor/PufferLib/ocean/bloodbowl/`, and that installed snapshot is stale relative to `puffer/bloodbowl/`. Refreshing it would modify many snapshot files outside the allowed edit map. I therefore did the narrower local compile plus `--selftest` against `puffer/bloodbowl/`, which exercises the edited binding path without broadening the working-tree changes.
- The secondary probability helper uses one raw 32-bit `bb_rng_next` draw converted to a float in `[0,1)`. `bb_rng.h` exposes a 32-bit procgen raw draw, not a 64-bit helper; the draw is still gated behind `skillup_secondary_pct > 0.0f`, so default RNG parity is preserved.
- For the “500 squads” category tests I used 250 matches, which is exactly 500 squads. The full-catalogue coverage test uses a hard cap of 10,000 matches, i.e. 20,000 squads.

**Pre-Existing Footguns Noticed**
- `vendor/PufferLib/ocean/bloodbowl/` is stale relative to `puffer/bloodbowl/`. `CLAUDE.md` already warns this installed snapshot is what `build.sh` compiles and must normally be refreshed with `tools/install_puffer_env.sh`; I did not run that because of the file-scope restriction.
- The standalone Puffer env header has existing unused static functions under a plain `-Werror` compile (`bbe_team_archetype`, `c_render`). The repo’s own lockstep build uses `-Wno-unused-function` for this full-header binding style, and the local compile passed with the same suppression.
diff --git a/engine/include/bb/bb_match.h b/engine/include/bb/bb_match.h
index 45297a76956faa99d8b396c7f6c605c530f79adf..9a3de208996eed0f6e6281b47e88c37569830550
--- a/engine/include/bb/bb_match.h
+++ b/engine/include/bb/bb_match.h
@@ -137,9 +137,19 @@
 
 // Procedural match: random rosters/skills/injuries/re-rolls drawn from `rng`
 // (the procgen stream, not the in-match dice stream).
+typedef struct {
+    int skillup_max_players;   // advancement draws per team, with replacement
+    int skillup_max_each;      // max skills gained per draw, uniform 1..N
+    float skillup_secondary_pct; // P(draw category from secondary_mask)
+} bb_procgen_params;
+
+bb_procgen_params bb_procgen_params_default(void);
 void bb_match_init_random(bb_match* m, bb_rng* rng);
+void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp);
 // home/away >= 0 pin that side; exclude >= 0 bars a team from random draws.
 void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude);
+void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
+                            const bb_procgen_params* pp);
 
 // Advance the engine until a coach decision is required or the match ends.
 // All dice are drawn from `rng`. Returns the resulting status.
diff --git a/engine/src/bb_procgen.c b/engine/src/bb_procgen.c
index 8a7f9ee622d55ea05adbaede3635db4e9222602f..4819137323d1ece180f5c27b7ae1114d9ad9d81f
--- a/engine/src/bb_procgen.c
+++ b/engine/src/bb_procgen.c
@@ -27,10 +27,19 @@
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
@@ -100,22 +109,31 @@
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
@@ -140,11 +158,12 @@
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
@@ -157,10 +176,15 @@
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
@@ -168,6 +192,12 @@
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
@@ -179,5 +209,5 @@
         a = pg_pick(rng, BB_TEAM_COUNT);
         if (away < 0 && a == exclude) a = -1;
     }
-    pg_init_match(m, rng, h, a);
+    pg_init_match(m, rng, h, a, pp);
 }
diff --git a/engine/tests/test_match.c b/engine/tests/test_match.c
index 5e7fba3046244e0086798d06c76f5012c18c6964..99774f8dfb71f3f99dfd14ddaa48a8432093ee30
--- a/engine/tests/test_match.c
+++ b/engine/tests/test_match.c
@@ -205,6 +205,192 @@
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
diff --git a/puffer/bloodbowl/binding.c b/puffer/bloodbowl/binding.c
index f5a5fc967d49da6a9166a961d83c5c7c53c76dc8..5101216799c7ece32182fc2a554816fb71cf6ca2
--- a/puffer/bloodbowl/binding.c
+++ b/puffer/bloodbowl/binding.c
@@ -91,6 +91,9 @@
     env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
     // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
     env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
+    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
+    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
+    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
     // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
     env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
     env->reach_mover = -1;
diff --git a/puffer/bloodbowl/bloodbowl.h b/puffer/bloodbowl/bloodbowl.h
index 8553f15ab72f046e70948e3b10580e49ea55c5f8..b57de13441e085858282c9120ee49d09aca693af
--- a/puffer/bloodbowl/bloodbowl.h
+++ b/puffer/bloodbowl/bloodbowl.h
@@ -314,6 +314,11 @@
     // team-to-move holds the ball with a standing downfield receiver within
     // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
     int demo_pass_maxrange;
+    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
+    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+    int skillup_max_players;
+    int skillup_max_each;
+    float skillup_secondary_pct;
     // v5 path-actions (D82): when 1, the STEP square head selects ANY
     // reachable destination; the env routes a min-risk path (Dijkstra over
     // dodge/rush costs) and auto-applies it step-by-step, returning control
@@ -1308,11 +1313,21 @@
         // evals).
         if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
             env->force_away_team >= 0) {
-            bb_match_init_forced(&env->match, &env->procgen,
-                                 env->force_home_team, env->force_away_team,
-                                 env->exclude_team);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_forced_p(&env->match, &env->procgen,
+                                   env->force_home_team, env->force_away_team,
+                                   env->exclude_team, &pp);
         } else {
-            bb_match_init_random(&env->match, &env->procgen);
+            bb_procgen_params pp = {
+                env->skillup_max_players,
+                env->skillup_max_each,
+                env->skillup_secondary_pct
+            };
+            bb_match_init_random_p(&env->match, &env->procgen, &pp);
         }
     }
     // Fresh in-match dice stream either way; a resumed state replays under
diff --git a/puffer/config/bloodbowl.ini b/puffer/config/bloodbowl.ini
index b30273a24793f4b6756c4a76be4bff0dca215141..d62344092d5096805ded84215deed8910e0aaf7b
--- a/puffer/config/bloodbowl.ini
+++ b/puffer/config/bloodbowl.ini
@@ -101,6 +101,12 @@
 # throwing is live). Pure ladder, graduate to kickoff (demo_reset_pct->0) per
 # D69. ~15%% of bank qualifies at range 6. Precedence: endzone>pickup>postkick>pass.
 demo_pass_maxrange = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # v5 path-actions (D82): 1 = the STEP square head selects ANY reachable
 # destination; the env routes a min-risk path and auto-executes it, returning
 # control on interruptions. 0 = v4 stepwise semantics (bit-identical).
diff --git a/vendor/PufferLib/config/bloodbowl.ini b/vendor/PufferLib/config/bloodbowl.ini
index 210ca14705125b8188e68ca9a036d4f500fd6956..4c0ee0dc788056a79a779bbe6e4a07a8d094fc75
--- a/vendor/PufferLib/config/bloodbowl.ini
+++ b/vendor/PufferLib/config/bloodbowl.ini
@@ -81,6 +81,12 @@
 # touchdowns are experienced densely; expand backward in stages (6 -> 12 ->
 # 0=uniform) like the k-anneal chain.
 demo_endzone_maxdist = 0
+# Procgen skill-entropy knobs. Defaults reproduce historical behavior:
+# 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
+# Crank for developed-league rosters, e.g. 11 / 3 / 0.35.
+skillup_max_players = 4
+skillup_max_each = 2
+skillup_secondary_pct = 0.0
 # Surfs: charged at the deterministic crowd-push event, dice-independent.
 # Suggested when shaped: taken -0.1, inflicted +0.1 (zero-sum pair)
 reward_surf_taken = 0.0

tokens used
137,749
Implemented the configurable procgen skillup knobs end to end, with default behavior pinned to the legacy procgen stream. No git state was touched: no commit, push, checkout, stash, or reset.

**Edit Map**
- [engine/include/bb/bb_match.h](/Users/alexanderhuth/Code/bloodbowl-rl/engine/include/bb/bb_match.h:140): added `bb_procgen_params`, `bb_procgen_params_default`, and `_p` procgen init APIs.
- [engine/src/bb_procgen.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/src/bb_procgen.c:30): added default params, secondary-roll float helper, param threading through match/squad init, and configurable advancement logic.
- [engine/src/bb_procgen.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/src/bb_procgen.c:178): kept legacy `bb_match_init_random` / `bb_match_init_forced` as thin wrappers around defaults.
- [puffer/bloodbowl/bloodbowl.h](/Users/alexanderhuth/Code/bloodbowl-rl/puffer/bloodbowl/bloodbowl.h:317): added env fields `skillup_max_players`, `skillup_max_each`, `skillup_secondary_pct`.
- [puffer/bloodbowl/bloodbowl.h](/Users/alexanderhuth/Code/bloodbowl-rl/puffer/bloodbowl/bloodbowl.h:1316): reset now builds `bb_procgen_params` and calls `_p` variants for both forced and random procgen paths.
- [puffer/bloodbowl/binding.c](/Users/alexanderhuth/Code/bloodbowl-rl/puffer/bloodbowl/binding.c:94): added kwarg reads with defaults `4`, `2`, `0.0`.
- [puffer/config/bloodbowl.ini](/Users/alexanderhuth/Code/bloodbowl-rl/puffer/config/bloodbowl.ini:104): added documented skill-entropy config defaults.
- [vendor/PufferLib/config/bloodbowl.ini](/Users/alexanderhuth/Code/bloodbowl-rl/vendor/PufferLib/config/bloodbowl.ini:84): added same config keys to the duplicate config copy found by `find`.
- [engine/tests/test_match.c](/Users/alexanderhuth/Code/bloodbowl-rl/engine/tests/test_match.c:208): added procgen helper assertions and seven focused tests for parity, off switch, category routing, catalogue coverage, cap/structure, and determinism.

**New Tests**
All passed under `make test`:
- `match_procgen_default_params_match_legacy_api`
- `match_procgen_skillups_off_keeps_base_skills`
- `match_procgen_primary_only_uses_primary_categories`
- `match_procgen_secondary_only_uses_secondary_or_primary_fallback`
- `match_procgen_skillups_reach_full_learnable_catalogue`
- `match_procgen_cranked_params_respect_cap_and_structure`
- `match_procgen_params_are_deterministic`

**Verification**
`make test` from repo root passed. The output is long because the harness prints every test; the exact procgen section and final summary were:

```text
ok   match_procgen_skill_cap
ok   match_procgen_default_params_match_legacy_api
ok   match_procgen_skillups_off_keeps_base_skills
ok   match_procgen_primary_only_uses_primary_categories
ok   match_procgen_secondary_only_uses_secondary_or_primary_fallback
ok   match_procgen_skillups_reach_full_learnable_catalogue
ok   match_procgen_cranked_params_respect_cap_and_structure
ok   match_procgen_params_are_deterministic
ok   match_procgen_games_complete
...
345 tests, 0 failures
```

The full `make test` command also rebuilt the touched engine objects and linked `build/bb_tests` cleanly under `-Wall -Wextra -Werror`.

I also ran a binding-level local compile check against the edited source tree:

```text
cc -std=c11 -O2 -g -Wall -Wextra -Werror -Wno-unused-function -Ipuffer/bloodbowl puffer/bloodbowl/bloodbowl.c -o build/bloodbowl_local_check
```

That compile produced no output and exited `0`.

Then I ran the available binding selftest:

```text
./build/bloodbowl_local_check --selftest
bloodbowl selftest: 64 episodes, 0 failure(s), v4 planes B=22237 A=406
```

**Deviations**
- I did not run `vendor/PufferLib/build.sh bloodbowl --float`. The compiled PufferLib env uses `vendor/PufferLib/ocean/bloodbowl/`, and that installed snapshot is stale relative to `puffer/bloodbowl/`. Refreshing it would modify many snapshot files outside the allowed edit map. I therefore did the narrower local compile plus `--selftest` against `puffer/bloodbowl/`, which exercises the edited binding path without broadening the working-tree changes.
- The secondary probability helper uses one raw 32-bit `bb_rng_next` draw converted to a float in `[0,1)`. `bb_rng.h` exposes a 32-bit procgen raw draw, not a 64-bit helper; the draw is still gated behind `skillup_secondary_pct > 0.0f`, so default RNG parity is preserved.
- For the “500 squads” category tests I used 250 matches, which is exactly 500 squads. The full-catalogue coverage test uses a hard cap of 10,000 matches, i.e. 20,000 squads.

**Pre-Existing Footguns Noticed**
- `vendor/PufferLib/ocean/bloodbowl/` is stale relative to `puffer/bloodbowl/`. `CLAUDE.md` already warns this installed snapshot is what `build.sh` compiles and must normally be refreshed with `tools/install_puffer_env.sh`; I did not run that because of the file-scope restriction.
- The standalone Puffer env header has existing unused static functions under a plain `-Werror` compile (`bbe_team_archetype`, `c_render`). The repo’s own lockstep build uses `-Wno-unused-function` for this full-header binding style, and the local compile passed with the same suppression.
