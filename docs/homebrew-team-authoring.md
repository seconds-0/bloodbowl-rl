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
