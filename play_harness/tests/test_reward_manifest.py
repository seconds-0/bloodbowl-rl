"""The reward manifest loader: the fixture is the pinned training manifest and
its digest is the one the manifest tool and the ledger use."""
import hashlib
import importlib.util
import json
import os

import pytest

from play_harness import engine as E

from .conftest import ROOT

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "r0_poss_half.json")
# The fixture is a copy of puffer/config/rewards/r0_poss_half.json.
FIXTURE_FILE_SHA256 = "16900416cfe8d32ee49bead8c2fcddb989c13e232b7a279d24df86f00d64c0ea"
# The canonical digest tools/reward_manifest.py prints; the ledger's name for it.
FIXTURE_SHA256 = "433c792018acdc01f8c7168e824c9389bf99df2307d3260283b7877df3f69d5c"


@pytest.fixture(scope="module")
def manifest(lib):
    return E.load_reward_manifest(FIXTURE, lib)


def test_the_fixture_is_the_pinned_training_manifest(manifest):
    assert manifest["name"] == "r0_poss_half"
    assert manifest["file_sha256"] == FIXTURE_FILE_SHA256
    assert manifest["sha256"] == FIXTURE_SHA256
    assert manifest["rewards"]["reward_td"] == 0.4
    assert manifest["rewards"]["reward_possession"] == 0.015
    assert manifest["rewards"]["reward_dist_pbrs_gamma"] == 0.0       # schema 1: legacy form
    source = os.path.join(ROOT, "puffer", "config", "rewards", "r0_poss_half.json")
    if os.path.exists(source):
        assert hashlib.sha256(open(source, "rb").read()).hexdigest() == FIXTURE_FILE_SHA256


def test_the_loader_and_the_manifest_tool_agree_on_the_digest(manifest):
    tool = os.path.join(ROOT, "tools", "reward_manifest.py")
    if not os.path.exists(tool):
        pytest.skip("tools/reward_manifest.py is not in this checkout")
    spec = importlib.util.spec_from_file_location("reward_manifest_tool", tool)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loaded, digest = module.load_manifest(FIXTURE)
    assert digest == manifest["sha256"]
    assert {k: v for k, v in manifest["rewards"].items()
            if k not in E.SCHEMA1_ABSENT_REWARDS} == loaded["reward"]
    assert set(E.reward_fields()) == set(module.REQUIRED_KEYS)
    assert set(E.SCHEMA1_ABSENT_REWARDS) == set(module.SCHEMA2_ONLY_FLOAT_KEYS)
    assert set(E.REWARD_INT_FIELDS) == set(module.REWARD_INT_KEYS)


def test_a_schema_1_manifest_may_not_carry_the_schema_2_key(tmp_path, manifest):
    raw = json.load(open(FIXTURE))
    raw["reward"]["reward_dist_pbrs_gamma"] = 0.999
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="schema 1"):
        E.load_reward_manifest(str(path))
    raw["schema_version"] = 2
    path.write_text(json.dumps(raw))
    assert E.load_reward_manifest(str(path))["rewards"]["reward_dist_pbrs_gamma"] == 0.999


def _tool():
    tool = os.path.join(ROOT, "tools", "reward_manifest.py")
    if not os.path.exists(tool):
        pytest.skip("tools/reward_manifest.py is not in this checkout")
    spec = importlib.util.spec_from_file_location("reward_manifest_tool", tool)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("flag", [0.9, 1.9, -1, 2, 0.5, "1", None, [1]])
def test_a_malformed_flag_is_refused_not_truncated(tmp_path, flag):
    """0.9 must not load as 0, nor 1.9 as 1: the loader would then hand out the
    digest of a valid manifest for a file the manifest tool refuses."""
    raw = json.load(open(FIXTURE))
    raw["reward"]["reward_injury_value_scaled"] = flag
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="reward_injury_value_scaled must be 0 or 1"):
        E.load_reward_manifest(str(path))
    with pytest.raises(ValueError):
        _tool().load_manifest(str(path))


@pytest.mark.parametrize("flag", [0, 1, 1.0, True, False])
def test_a_valid_flag_hashes_as_the_manifest_tool_hashes_it(tmp_path, flag):
    raw = json.load(open(FIXTURE))
    raw["reward"]["reward_injury_value_scaled"] = flag
    path = tmp_path / "ok.json"
    path.write_text(json.dumps(raw))
    loaded = E.load_reward_manifest(str(path))
    assert loaded["rewards"]["reward_injury_value_scaled"] == int(flag)
    assert type(loaded["rewards"]["reward_injury_value_scaled"]) is int
    assert loaded["sha256"] == _tool().load_manifest(str(path))[1]
    assert (loaded["sha256"] == FIXTURE_SHA256) == (int(flag) == 0)


@pytest.mark.parametrize("key,value", [("reward_td", True), ("reward_k_kd", "0.1"),
                                       ("reward_possession", None)])
def test_a_non_numeric_coefficient_is_refused(tmp_path, key, value):
    raw = json.load(open(FIXTURE))
    raw["reward"][key] = value
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="must be numeric"):
        E.load_reward_manifest(str(path))
