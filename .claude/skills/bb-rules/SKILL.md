---
name: bb-rules
description: BB2025 (Blood Bowl Third Season Edition) rules lookup for engine implementation — where each rule lives in the local mirror, the skill/trait catalogue, edition deltas vs BB2016/BB2020, and how to consult errata/FAQ when implementing a mechanic.
---

# BB2025 Rules Lookup

The engine implements **BB2025 / Third Season Edition** (released 2025). Never implement a
mechanic from memory of BB2016 or BB2020 — the editions differ in load-bearing ways
(see "Edition deltas" below). Always read the local mirror first.

## Sources on disk (paths relative to repo root)

| Source | Path | Notes |
|---|---|---|
| Full BB2025 rules mirror | `docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/` | Polite local mirror of bloodbowlbase.ru. 113 HTML pages, complete. |
| GW Designer's Commentary Nov 2025 | `docs/vendor/gw/bb-faq-errata-nov2025.pdf` | Tiny (3 roster errata items). Fully superseded by mirror's `latest_faq` page (May 2026). Read with `pdftotext`. |
| botbowl (BB2016 engine) | `vendor/botbowl/` | Edition-delta awareness only. Its ruleset data is `vendor/botbowl/botbowl/data/rules/BB2016.xml`. Do NOT copy rules from it. |

If a page seems missing from the mirror, fetch the live page at
`https://bloodbowlbase.ru/bb2025/<same path>` via WebFetch — but prefer local files.

### Reading mirror pages

Pages are mkdocs-material HTML; content lives in `<article>`. Quick extraction:

```bash
python3 - "$PAGE/index.html" <<'EOF'
import re, html, sys
src = open(sys.argv[1]).read()
m = re.search(r'<article[^>]*>(.*?)</article>', src, re.S)
body = re.sub(r'<(h[1-6])[^>]*>', '\n\n## ', m.group(1))
body = re.sub(r'<(tr|p|li|div|br)[^>]*>', '\n', body)
body = re.sub(r'<(td|th)[^>]*>', ' | ', body)
print(re.sub(r'\n\s*\n+', '\n', html.unescape(re.sub(r'<[^>]+>', '', body))))
EOF
```

**Errata are applied inline in the mirror with `<del>` tags**: the struck-through old text
is followed by the corrected text. Plain-text extraction shows BOTH sentences back-to-back
(e.g. dice modification in `rules_and_regulations` shows the pre-errata "never below 1 or
above 6" AND the current "never above 6"). When two near-duplicate sentences appear,
check the HTML — the `<del>` one is dead, the second one is law.

## Topic → file map

All paths below are under `docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/`.

| Topic | File |
|---|---|
| Pitch zones, dugout, dice (D3/D6/D8/D16/Block), templates, tokens (Prone/Stunned/Distracted/Rooted/Chomped...) | `core_rules/game_essentials/index.html` |
| Dice rules, re-roll rules, Deviate/Scatter/Bounce, keywords, **Turnover causes**, player profile (MA/ST/AG/PA/AV), characteristic min/max, **player statuses, Tackle Zones, Marked/Open/Distracted**, Placed Prone vs Falls Over vs Knocked Down | `core_rules/rules_and_regulations/index.html` |
| Pre-game (fans, weather, kicking team), Start of Drive (setup, kick-off, **Kick-off Event Table**), turn/round structure, all 8 action types, Move/Dodge/Jump/Rush/pickup, Secure the Ball, **Block (dice, assists, pushes, follow-up)**, Blitz, **Armour/Injury/Casualty tables**, Apothecary, Foul + Sent-off + Argue the Call, **Pass (ranges, accuracy, interception)**, catching, throw-ins, Hand-off, Throw Team-mate, Touchdown, Stalling/Crowd Takes Action, End of Drive, extra time/penalties | `core_rules/the_game_of_blood_bowl/index.html` |
| **All skills & traits** (Active/Passive, compulsory `*`, Elite, the 2D6 random-skill table) | `core_rules/skills_and_traits/index.html` |
| Team rosters: drafting, treasury, Team Value, re-roll cost, sideline staff | `core_rules/drafting_a_blood_bowl_team/index.html` |
| Leagues (Badlands Brawl, Old World Classic, ...), **team special rules** (Brawlin' Brutes, Bribery and Corruption, Favoured of..., Low Cost Linemen, Masters of Undeath, Swarming, Team Captain), tier system | `core_rules/the_teams/index.html` |
| League play: Journeymen, inducement budget, post-game, SPP earning/spending, advancement, characteristic improvement, hiring/firing | `core_rules/league_play/index.html` |
| Matched play (tournament): draft budget, Skill Points, **Elite Skill 4x cap**, Star Player limits | `core_rules/matched_play/index.html` |
| Exhibition play | `core_rules/exhibition_play/index.html` |
| **Inducements**: 0-3 Prayers to Nuffle, 0-8 Extra Team Training, 0-3 Bribes (0-6 with B&C), Halfling Master Chef, Wizard, Biased Referee, Mercenaries, 0-2 Star Players, etc. | `core_rules/inducements/index.html` |
| Condensed tables (sequences, weather, kick-off, injury, casualty, SPP) | `core_rules/cheat_sheet/index.html` |
| **Errata + FAQ (May 2026)** + current team tiers + Mega-Star list | `core_rules/latest_faq/index.html` |
| Per-team rosters (positionals, stats, skills, primaries, costs) | `teams/<Team_Name>/index.html` (30 dirs) |
| Star players (63) | `starplayers/<Name>/index.html` |
| Spike! Journal 19–21 (league variants: Jolly Jouster Cup, Khemri Classic, Flame Spectacle — not engine-core) | `spike_journal/issue_NN/index.html` |

## Glossary of core mechanics (BB2025 definitions)

- **Structure**: 2 halves x 8 rounds; each round = 1 turn per coach → 16 turns per coach
  per game (8 per half). A **Drive** = kick-off → score or end of half.
- **Statuses**: Standing / **Distracted** (Standing but no Tackle Zone; cannot use Active
  skills/traits, intercept, or catch; cleared when next activated — *before* declaring the
  action, per FAQ) / Prone / Stunned (skips activation; flips to Prone at end of own team's
  turn if it *started* the turn Stunned).
- **Tackle Zone**: the 8 adjacent squares of a Standing, non-Distracted player. **Marking** =
  having an opponent in your TZ; **Marked** = being in an opponent's TZ. **Open** = Standing
  and not Marked.
- **Going down**: *Placed Prone* (no Armour Roll), *Falls Over* (self-inflicted: failed
  Dodge/Jump/Rush; Armour Roll; Turnover if active team), *Knocked Down* (by opponent;
  Armour Roll; Turnover if during own team's turn). Ball always bounces from the square.
- **Armour → Injury → Casualty flow**: Armour Roll = opposing coach rolls 2D6 vs AV target
  (e.g. 9+); success = armour **broken** → Injury Roll 2D6: 2-7 Stunned, 8-9 KO'd, 10-12
  Casualty. Stunty table instead: 2-6 Stunned, 7-8 KO, 9 Badly Hurt (auto), 10-12 Casualty.
  Casualty Roll = **D16**: 1-8 Badly Hurt, 9-10 Seriously Hurt (MNG), 11-12 Serious Injury
  (Niggling + MNG), 13-14 Lasting Injury (stat reduction, D6 table), 15-16 Dead.
- **Block dice** (5 icons on D6): Player Down (attacker KD), Both Down (both KD; Block skill
  opts out, Wrestle makes both Placed Prone), Push Back, Stumble (= Push Back if target has
  Dodge, else POW), POW (push then KD). Dice count from modified ST compare: equal=1,
  higher=2, more-than-double=3; stronger side's coach picks. Assists: +1 ST each; assisting
  player must Mark the relevant target and not be Marked by anyone else (Guard ignores that).
- **Rush** (the BB2016 "GFI"): up to 2 extra squares per activation, 2+ each, nat 1 = Fall
  Over. Sprint allows a 3rd; Sure Feet rerolls one.
- **Dodge**: AG test when leaving a Marked square; -1 per opponent Marking the *destination*
  square. Jump (over Prone/Stunned, costs 2 MA), Leap skill = jump over any square.
- **Standing up**: costs 3 MA; MA ≤ 2 players roll 4+ instead.
- **Pass**: ranges Quick/Short/Long/Long Bomb (0/-1/-2/-3), -1 per player Marking thrower.
  PA test → Accurate (target square) / Inaccurate (Scatter(3)) / Fumbled (modified result 1
  or natural 1; bounce + Turnover). **No Wildly Inaccurate, no Deflections** in BB2025.
  Interception = single AG test by one player under the ruler: -3 vs accurate pass, -2 vs
  inaccurate, -1 per marker; success = possession + Turnover.
- **Deviate** = D6 squares in D8 direction. **Scatter(n)** = n successive D8 moves.
  **Bounce** = Scatter(1).
- **Turnover causes** (full list in `rules_and_regulations`, post-errata): active player
  Falls Over or is Knocked Down; active ball-carrier Placed Prone or pushed off pitch;
  failed pickup; Fumbled pass; failed catch after Pass/Hand-off coming to rest (carve-out:
  bounce directly to an active-team player who catches = no Turnover); pass ends in inactive
  team's possession or interception; thrown team-mate with ball fails landing / lands in
  crowd / is eaten; Sent-off for a Foul; Touchdown scored. Turnover ends the turn immediately.
- **Dice modification (May 2026 errata)**: a D6 result can never be modified **above 6**,
  but CAN now go below 1 (a natural 6 always succeeds, a natural 1 always fails).
- **Stalling**: a ball-carrier who could score without rolling dice but doesn't = Stalling;
  roll D6 at end of activation, ≥ current turn number → Knocked Down by crowd, Turnover.
- **Secure the Ball Action** (new in BB2025): 1/turn, ball on ground with no Standing
  non-Distracted opponent within 2 squares at declaration; pick up on flat 2+ (not an AG
  test), activation ends. Big Guys and `Unsteady*` players cannot declare it.
- **Characteristic bounds**: MA 1-9, ST 1-8, AG/PA 6+..1+, AV 3+..11+; no characteristic may
  be improved more than twice.

## Skills & traits system

- Six skill categories: **Agility, Devious, General, Mutation, Passing, Strength** — exactly
  12 skills each (the 2D6 random-selection table) — plus 36 **Traits** (innate, not learnable).
- Every skill/trait is **ACTIVE** (usable only while Standing and not Distracted, unless its
  text says otherwise) or **PASSIVE** (always on). An asterisk `*` = compulsory use.
- Four **Elite Skills**: **Block, Dodge, Guard, Mighty Blow** (in Matched Play each may be
  bought at most 4 times per team, per the May 2026 FAQ).
- Full annotated catalogue: `reference/skills-and-traits.md` in this skill directory.
- "Devious" is NEW in BB2025 — it collects fouling/dirty play (Dirty Player, Sneaky Git,
  Shadowing moved here; Eye Gouge, Pile Driver, Lone Fouler, Quick Foul, Saboteur etc. added).

## The teams (30 in BB2025, with May 2026 tiers)

The mirror and the current tier list both have exactly **30 teams**
(May 2026 tier table in `latest_faq`, read column-wise — 9/11/5/5):

- **Tier 1** (9): Amazon, Chaos Dwarf, Dark Elf, High Elf, Lizardmen, Norse,
  Old World Alliance, Underworld Denizens, Wood Elf
- **Tier 2** (11): Bretonnian, Dwarf, Elven Union, Human, Imperial Nobility,
  Necromantic Horror, Orc, Shambling Undead, Skaven, Tomb Kings, Vampire
- **Tier 3** (5): Black Orc, Chaos Chosen, Chaos Renegades, Khorne, Nurgle
- **Tier 4** (Stunty, 5): Gnome, Goblin, Halfling, Ogre, Snotling

Roster page format (`teams/<Name>/index.html`): tier, then positional table with
Qty / Position (keywords) / MA / ST / AG / PA / AV / Skills / Primary / Secondary / Cost.
Note "Tomb Kings" (BB2020's "Khemri" naming is gone) and "Chaos Renegades" (plural dir name).

## Edition deltas that matter for the engine

### BB2016 → BB2020 (why botbowl ≠ our rules)
botbowl implements `BB2016.xml`. Major changes in BB2020: **PA stat added** (passing tests
moved off AG); AG and AV became target numbers (AG 4 → 2+, AV 8 → 9+); "Go For It" renamed
**Rush**; casualty roll became a **D16 table** (was D68); interceptions became a two-step
Deflection→Interception; large skill rework (Piling On removed, Brawler/Arm Bar/Cannoneer/
Cloud Burster etc. added); kick-off table revised. Use botbowl only for architecture ideas
(board representation, pathfinding), never rule text.

### BB2020 → BB2025 (what to re-check even if you know BB2020)
- **Passing simplified**: Wildly Inaccurate result REMOVED (now just Accurate / Inaccurate
  Scatter(3) / Fumbled). Deflection→Interception two-step REMOVED — single direct
  interception AG test (-3/-2, success = possession + Turnover).
- **New skill category "Devious"** (12 skills); categories now A/D/G/M/P/S. Dirty Player,
  Sneaky Git, Shadowing relocated into it; new skills Eye Gouge, Fumblerooski (moved from
  Passing), Lethal Flight, Lone Fouler, Pile Driver (from Strength), Put the Boot In,
  Quick Foul, Saboteur, Violent Innovator.
- **New skills elsewhere**: Hit and Run (A), **Steady Footing** (G: nat 6 to ignore any
  Knocked Down/Fall Over — see FAQ for exact trigger list), Taunt (G), Give and Go (P,
  replaces BB2020 Running Pass), Punt (P), Bullseye (S). New traits: Trickster, Pick-Me-Up,
  Insignificant*, My Ball*, No Ball*, Unsteady*, Hatred (X)*, Drunkard*, Breathe Fire,
  Monstrous Mouth (Mutation skill) — see catalogue.
- **Elite Skill** concept added (Block/Dodge/Guard/Mighty Blow; Matched Play cap 4x each).
- **Secure the Ball Action** added (8th action type) + `Unsteady*` trait gating it.
- **Distracted** is now a formal token/status replacing BB2020's "loses Tackle Zone" wording
  (Bone Head, Hypnotic Gaze, Really Stupid etc. now confer Distracted).
- **Casualty table softened**: Badly Hurt is 1-8 (BB2020: 1-6); Seriously Hurt 9-10,
  Serious Injury 11-12, Lasting 13-14, Dead 15-16.
- **Stalling / "Crowd Takes Action"** rule is new (D6 ≥ turn number → KD + Turnover).
- **Kick-off table revised**: 10 = "Charge!" (was Blitz; selected players may also TTM/KTM),
  11 = "Dodgy Snack" (was Officious Ref), Solid Defence/Quick Snap are D3+3 players.
- **Prayers to Nuffle** moved from underdog pre-game roll to a purchasable inducement (0-3).
- **Throw Team-mate reworked**: Quick/Short Throw ranges only; results Superb / Subpar /
  Fumbled; landing AG test with -1 per Subpar/Fumble and per marker; Bullseye/Swoop modify
  scatter. Kick Team-mate is a separate Special Action that can coexist with TTM in a turn.
- **Dice modification floor removed** (May 2026 errata): results can be modified below 1.
- **Block dice naming**: "POW!" / "Stumble" / "Push Back" / "Both Down" / "Player Down" —
  Both Down + Wrestle = both *Placed Prone* (no armour roll), Block opts out entirely.
- **Getting Even** (league): casualties can grant the victim Hatred (X) vs the offender.
- Roster revisions throughout (e.g. Human team has 0-3 Halfling Hopefuls; Orc Goblin
  Lineman PA 4+; Ogres lost Mutation secondary access — these specific ones are errata,
  see below). Always read the team page, not a BB2020 roster.

## Errata + FAQ workflow when implementing a mechanic

1. **Read the rule** in the relevant `core_rules/` page (it already has errata applied
   inline; watch for `<del>` blocks as described above).
2. **Grep the May 2026 FAQ** — `core_rules/latest_faq/index.html` — for the skill/mechanic
   name. It contains (a) the errata list (page-referenced rulebook corrections), (b) ~40
   Q&As that pin down timing/sequencing, (c) the current team tier table, (d) the Mega-Star
   list. Timing answers worth knowing exist for: Secure the Ball, Blitz + Special Action MA
   cost, Distracted-removal sequence, the Dodge-out skill order
   (**Tentacles → move → Dodge roll+rerolls → Diving Tackle → Shadowing**), Brawler/Grab not
   working on Blitz, Multiple Block exclusions, Pile Driver stacking ("yes to all"),
   Steady Footing trigger list, Dump-off timing, Stand Firm vs Strip Ball/Eye Gouge.
3. The GW PDF (`docs/vendor/gw/bb-faq-errata-nov2025.pdf`, read via
   `pdftotext <pdf> -`) is an older strict subset (3 roster errata items: Chaos Renegade
   Ogre +Mighty Blow; Human/Imperial Nobility/OWA Ogres lose Mutation secondary; OWA
   Halfling Hopeful 0-3). Only useful to date when a change landed.
4. **Skill interaction guards live in the skill text itself** — e.g. Frenzy excludes
   Grab/Hit and Run/Multiple Block; Ball & Chain lists 10 forbidden skills; Leap excludes
   Pogo; Bullseye/Strong Arm require Throw Team-mate; Saboteur requires Secret Weapon.
   Encode these as roster-validation constraints, with the Star Player exception (e.g. Grim
   Ironjaw legally has Frenzy + Multiple Block; FAQ: Frenzy is ignored while using MB).
5. For rosters, the team pages under `teams/` are already errata-current; cross-check
   any QTY/stat oddity against the errata section of `latest_faq`.
