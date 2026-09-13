"""Drift guard: bbplay_create mirrors apply_kwargs (binding.c) by hand."""
import os
import re

from .conftest import ROOT

# Set explicitly in bbp_create at the bloodbowl.ini defaults or as parameters.
MIRRORED = {
    "demo_endzone_maxdist", "demo_pickup_maxdist", "demo_postkick_maxturn",
    "demo_pass_maxrange", "skillup_max_players", "skillup_max_each",
    "skillup_secondary_pct", "macro_moves", "demo_reset_pct", "exclude_team",
    "force_home_team", "force_away_team", "scripted_opponent", "scripted_opponent_team",
    "scripted_opponent_type", "scripted_bank_tag", "max_decisions", "render_fps", "seed",
    "reward_td", "reward_win", "reward_draw",
}


def test_every_env_kwarg_is_classified():
    src = open(os.path.join(ROOT, "puffer", "bloodbowl", "binding.c")).read()
    keys = set(re.findall(r'kw\(\s*(?:env_)?kwargs,\s*"([a-z0-9_]+)"', src))
    assert keys, "no kwargs parsed from binding.c"
    # Shaping rewards are not observed and do not change legality or rosters.
    shaping = {k for k in keys if k.startswith("reward_")} - MIRRORED
    unclassified = keys - MIRRORED - shaping
    assert not unclassified, f"new env kwargs need a bbp_create decision: {unclassified}"


def test_shim_sets_the_mirrored_fields():
    shim = open(os.path.join(ROOT, "play_harness", "native", "bbplay.c")).read()
    for key in MIRRORED - {"reward_td", "reward_win", "reward_draw"}:
        assert f"env->{key}" in shim, key
