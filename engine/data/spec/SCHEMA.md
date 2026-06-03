# Rules spec schema (YAML → codegen → C tables)

Hand-extracted from the BB2025 reference mirror (`docs/vendor/bloodbowlbase/bloodbowlbase.ru/bb2025/`), reviewable line-by-line against it. `tools/codegen.py` compiles these into `engine/src/gen_*.c` / `engine/include/bb/gen_*.h` (checked in — engine builds with zero deps).

Conventions: names are `snake_case` ASCII; stats are integers (AG/PA/AV stored as the target number, e.g. `3` means 3+; PA `0` = no passing ability "-"); costs in thousands of gold (k); `null` for N/A.

## skills.yaml
```yaml
skills:                  # the 6×12 learnable skills
  - name: block          # canonical snake_case id
    display: Block
    category: general    # general|agility|strength|passing|mutation|devious
    mode: passive        # active|passive (mirror annotation)
    compulsory: false    # asterisk in mirror (use is compulsory)
    elite: true          # Elite Skill (Block/Dodge/Guard/Mighty Blow only)
    value: null          # X+ / (X) parameter if the skill is parameterized, else null
traits:                  # the 36 traits (not learnable)
  - name: loner
    display: Loner (X+)
    mode: passive
    compulsory: true
    value: 4             # default X where the trait is parameterized per-player
random_table:            # the 2D6 random-skill table {category: {roll: skill}}
  general: {2: dauntless, 3: dirty_player, ...}
```

## teams.yaml
```yaml
teams:
  - name: human
    display: Human
    tier: 1              # May 2026 tier (1..4)
    reroll_cost: 50
    apothecary: true
    special_rules: []    # team special rules (e.g. low_cost_linemen, bribery_and_corruption)
    positions:
      - name: human_lineman
        display: Lineman
        qty: [0, 12]     # min,max allowed on roster
        cost: 50
        ma: 6
        st: 3
        ag: 3            # 3+
        pa: 4            # 4+
        av: 9            # 9+
        skills: []       # starting skills/traits (snake_case ids)
        primary: [general]            # primary skill-access categories
        secondary: [agility, defensive_or_other...]
        big_guy: false
```

## starplayers.yaml
```yaml
starplayers:
  - name: griff_oberwald
    display: Griff Oberwald
    cost: 280
    ma: 7
    st: 4
    ag: 2
    pa: 3
    av: 9
    skills: [block, dodge, fend, sure_feet]
    special_rule: <name>          # snake_case id of bespoke rule
    special_rule_text: "..."      # one-paragraph paraphrase
    plays_for: [human, ...]       # team list or special-rule keyword groups as listed
    mega_star: false              # per May 2026 FAQ Mega-Stars list
```

## tables.yaml
```yaml
kickoff:                 # 2D6 → event id + params
  2: {event: get_the_ref}
  ...
prayers:                 # D16 prayers to nuffle
weather:                 # 2D6 weather table
injury:  {stun: [2,7], ko: [8,9], casualty: [10,12]}     # 2D6 ranges
injury_stunty: {stun: [2,6], ko: [7,8], badly_hurt: [9,9], casualty: [10,12]}
casualty:                # D16 → outcome ranges
  badly_hurt: [1, 8]
  seriously_hurt: [9, 10]
  serious_injury: [11, 12]
  lasting_injury: [13, 14]
  dead: [15, 16]
lasting_injury:          # D6 → characteristic reduction
argue_the_call: ...
```

## inducements.yaml
```yaml
inducements:
  - name: team_rerolls
    display: Extra Team Training
    qty: [0, 8]
    cost: 100            # or per-team formula noted in `cost_note`
    cost_note: null
```
