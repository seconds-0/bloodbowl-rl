"""Drift guard: bbplay_create mirrors apply_kwargs (binding.c) by hand."""
import os
import re

import numpy as np
import pytest

from play_harness import engine as E

from .conftest import ROOT

# Set explicitly in bbp_create_env at the bloodbowl.ini defaults or as parameters.
MIRRORED = {
    "demo_endzone_maxdist", "demo_pickup_maxdist", "demo_postkick_maxturn",
    "demo_pass_maxrange", "skillup_max_players", "skillup_max_each",
    "skillup_secondary_pct", "macro_moves", "demo_reset_pct", "exclude_team",
    "force_home_team", "force_away_team", "scripted_opponent", "scripted_opponent_team",
    "scripted_opponent_type", "scripted_bank_tag", "max_decisions", "render_fps", "seed",
}


def _binding_kwargs():
    src = open(os.path.join(ROOT, "puffer", "bloodbowl", "binding.c")).read()
    keys = set(re.findall(r'kw\(\s*(?:env_)?kwargs,\s*"([a-z0-9_]+)"', src))
    assert keys, "no kwargs parsed from binding.c"
    return keys


def test_every_env_kwarg_is_classified():
    keys = _binding_kwargs()
    rewards = {k for k in keys if k.startswith("reward_")}
    unclassified = keys - MIRRORED - rewards
    assert not unclassified, f"new env kwargs need a bbp_create decision: {unclassified}"


def test_shim_sets_the_mirrored_fields():
    shim = open(os.path.join(ROOT, "play_harness", "native", "bbplay.c")).read()
    for key in MIRRORED:
        assert f"env->{key}" in shim, key


def test_the_reward_table_covers_every_reward_kwarg(lib):
    """A coefficient binding.c reads and the shim's table lacks would stay zero."""
    fields = E.reward_fields(lib)
    assert len(fields) == len(set(fields)) == lib.bbp_reward_field_count()
    assert set(fields) == {k for k in _binding_kwargs() if k.startswith("reward_")}
    assert lib.bbp_reward_field_name(-1) is None
    assert lib.bbp_reward_field_name(len(fields)) is None


def _distinct_table(fields, **override):
    table = {name: (i + 1) / 100.0 for i, name in enumerate(fields)}
    table.update(reward_injury_value_scaled=1, reward_dist_pbrs_gamma=0.0,
                 reward_carrier_threat=0.0)
    table.update(override)
    return table


def test_every_coefficient_reaches_its_own_field(lib):
    fields = E.reward_fields(lib)
    tables = [_distinct_table(fields),
              # The carrier-threat arm excludes the exposure and assist arms.
              _distinct_table(fields, reward_carrier_threat=0.77, reward_k_assist=0.0,
                              reward_carrier_exposure=0.0, reward_carrier_exposure_soft=0.0),
              _distinct_table(fields, reward_dist_pbrs_gamma=0.999, reward_td=0.4,
                              reward_win=0.6, reward_draw=0.0)]
    for table in tables:
        eng = E.Engine(7, rewards=table)
        got = eng.reward_table()
        assert got == {k: float(np.float32(v)) for k, v in table.items()}
        eng.close()
    plain = E.Engine(7).reward_table()
    assert {k: v for k, v in plain.items() if v} == {
        "reward_td": float(np.float32(0.4)), "reward_win": float(np.float32(0.6))}


def test_the_shim_repeats_every_check_of_the_aborting_validator():
    """bbp_reward_config_error numbers the header's checks 1 to 5; a sixth abort
    there would be a way to kill the Python process with a manifest."""
    header = open(os.path.join(ROOT, "puffer", "bloodbowl", "bloodbowl.h")).read()
    body = header.split("static void bbe_validate_reward_config(const Bloodbowl* env) {")[1]
    body = body.split("\n}\n")[0]
    assert body.count("abort();") == 5
    shim = open(os.path.join(ROOT, "play_harness", "native", "bbplay.c")).read()
    mirror = shim.split("static int bbp_reward_config_error(const Bloodbowl* env) {")[1]
    mirror = mirror.split("\n}\n")[0]
    assert re.findall(r"return (\d);", mirror) == ["1", "2", "3", "4", "5", "6", "0"]
    for check in ("bbe_reward_config_scalars_valid", "bbe_reward_potential_sign_valid",
                  "bbe_reward_envelope_valid"):
        assert check in body and check in mirror


@pytest.mark.parametrize("code,override", [
    (1, {"reward_k_kd": 1.5}),
    (1, {"reward_possession": float("nan")}),
    (2, {"reward_carrier_threat": 0.2, "reward_k_assist": 0.0}),
    (3, {"reward_carrier_threat": 0.2, "reward_carrier_exposure": 0.0,
         "reward_carrier_exposure_soft": 0.0}),
    (4, {"reward_dist_pbrs_gamma": 0.999, "reward_dist_ball": -0.02}),
    (5, {"reward_dist_pbrs_gamma": 0.999, "reward_dist_ball": 1.0, "reward_dist_endzone": 1.0,
         "reward_td": 1.0, "reward_win": 1.0}),
    (6, {"reward_dist_pbrs_gamma": 1.5}),
    (6, {"reward_dist_pbrs_gamma": float("nan")}),
    # The flag is converted to int: anything but 0 or 1 is refused before that.
    (7, {"reward_injury_value_scaled": 0.9}),
    (7, {"reward_injury_value_scaled": 1.9}),
    (7, {"reward_injury_value_scaled": -1.0}),
    (7, {"reward_injury_value_scaled": 3e9}),
    (7, {"reward_injury_value_scaled": float("nan")}),
    (7, {"reward_injury_value_scaled": float("inf")}),
])
def test_a_bad_reward_table_is_refused_without_abort(lib, code, override):
    fields = E.reward_fields(lib)
    table = _distinct_table(fields, **override)
    with pytest.raises(ValueError, match=re.escape(E.REWARD_TABLE_ERRORS[code])):
        E.Engine(3, rewards=table)
    import ctypes
    raw = (ctypes.c_float * len(fields))(*[float(table[n]) for n in fields])
    assert lib.bbp_reward_table_error(raw, len(fields)) == code
    assert lib.bbp_reward_table_error(raw, len(fields) - 1) == -1
    assert not lib.bbp_create_rewards(ctypes.c_uint64(3), 0, -1, -1, 4, 2, 0.0, 4096,
                                      raw, len(fields))


def test_the_flag_check_runs_before_the_table_is_converted():
    """bbp_reward_table_error must look at the raw value: bbp_set_rewards casts it."""
    shim = open(os.path.join(ROOT, "play_harness", "native", "bbplay.c")).read()
    body = shim.split("int bbp_reward_table_error(const float* table, int n) {")[1].split("\n}\n")[0]
    assert body.index("bbp_reward_flags_valid(table)") < body.index("bbp_set_rewards(")
    create = shim.split("bbp_session* bbp_create_rewards(")[1].split("\n}\n")[0]
    assert create.index("bbp_reward_table_error(rewards, n)") < create.index("bbp_create_env(")
    assert E.REWARD_INT_FIELDS == ("reward_injury_value_scaled",)
    assert shim.count("I(reward_") == len(E.REWARD_INT_FIELDS)


def test_a_reward_table_must_name_every_coefficient(lib):
    table = _distinct_table(E.reward_fields(lib))
    short = {k: v for k, v in table.items() if k != "reward_rush_cost"}
    with pytest.raises(ValueError, match="missing"):
        E.Engine(3, rewards=short)
    with pytest.raises(ValueError, match="unknown"):
        E.Engine(3, rewards=dict(table, reward_bogus=0.0))
