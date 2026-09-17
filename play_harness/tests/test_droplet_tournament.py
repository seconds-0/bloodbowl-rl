"""Pure-logic tests for tools/droplet_tournament.py. Nothing here touches the network:
the autouse fixture makes any urlopen, ssh or scp call fail the test."""
import hashlib
import json
import os
import subprocess

import pytest

from tools import droplet_tournament as D

BLOB = "0000002999975936.bin"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(f"network or subprocess use in a unit test: {args[:1]}")
    monkeypatch.setattr(D.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)


def game(pair=("a", "b"), index=0, leg="A_home", result="W", a_td=1, b_td=0, digest="d0",
         trail="t0", integrity=None, **over):
    rec = {"pair": list(pair), "game_index": index, "leg": leg, "result_a": result,
           "a_td": a_td, "b_td": b_td, "score": [a_td, b_td] if leg == "A_home" else [b_td, a_td],
           "engine_seed": 100 + index, "sampling_seeds": [1, 2], "team_ids": [3, 4],
           "final_digest": digest, "action_trail_sha256": trail, "c_steps": 500,
           "forwards": [500, 500], "natural": True,
           "integrity": integrity or {k: 0 for k in D.HARD_COUNTERS}}
    rec.update(over)
    return rec


# ---- names, token, arguments ------------------------------------------------------
def test_names_are_prefixed_and_validated():
    assert D.droplet_name("c35-gate-20260917") == "bb-harness-c35-gate-20260917"
    for bad in ("", "Caps", "has space", "semi;colon", "-lead", "x" * 41, "../up"):
        with pytest.raises(D.RunnerError):
            D.validate_name(bad)


def test_token_parsing_handles_quotes_export_and_absence():
    assert D.parse_token("A=1\nDIGITALOCEAN_TOKEN=dop_v1_abc\n") == "dop_v1_abc"
    assert D.parse_token('export DIGITALOCEAN_TOKEN="dop_v1_q"\n') == "dop_v1_q"
    assert D.parse_token("DIGITALOCEAN_TOKEN='dop_v1_s'") == "dop_v1_s"
    assert D.parse_token("OTHER_DIGITALOCEAN_TOKEN=x\nDIGITALOCEAN_TOKEN=\n") is None
    assert D.parse_token("") is None


def test_read_token_prefers_the_environment_and_names_no_secret(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DIGITALOCEAN_TOKEN=from_file\n")
    assert D.read_token(environ={"DIGITALOCEAN_TOKEN": "from_env"}, env_file=str(env)) == "from_env"
    assert D.read_token(environ={}, env_file=str(env)) == "from_file"
    with pytest.raises(D.RunnerError) as err:
        D.read_token(environ={}, env_file=str(tmp_path / "missing"))
    assert "from_file" not in str(err.value)


def test_assignments_and_pairs_parse_or_refuse():
    assert D.parse_assignment("chain35=/x/y.bin", "checkpoint") == ("chain35", "/x/y.bin")
    assert D.parse_assignment("a=b=c", "checkpoint") == ("a", "b=c")
    for bad in ("noequals", "=value", "name=", "bad name=x", "a;b=x"):
        with pytest.raises(D.RunnerError):
            D.parse_assignment(bad, "checkpoint")
    assert D.parse_pair("a,b") == ("a", "b", None)
    assert D.parse_pair("a,b,3200") == ("a", "b", 3200)
    for bad in ("a", "a,b,c,d", "a,b,many"):
        with pytest.raises(D.RunnerError):
            D.parse_pair(bad)


def test_plan_pairs_matches_the_tournament_schedule_rules():
    players = {"a", "b", "bot"}
    assert D.plan_pairs([("a", "b", None), ("a", "bot", 40)], players, 3200) == \
        [("a", "b", 3200), ("a", "bot", 40)]
    assert D.expected_tasks([("a", "b", 3200), ("a", "bot", 40)]) == 3240
    for pairs, gpp in (([], 2), ([("a", "b", None)], None), ([("a", "b", 3)], None),
                       ([("a", "b", 0)], None), ([("a", "a", 2)], None),
                       ([("a", "zz", 2)], None), ([("a", "b", 2), ("b", "a", 2)], None)):
        with pytest.raises(D.RunnerError):
            D.plan_pairs(pairs, players, gpp)


def test_plan_pairs_agrees_with_the_real_scheduler():
    from play_harness import tournament as T
    pairs = [("a", "b", 6), ("a", "bot", 2)]
    assert len(T.schedule(["a", "b", "bot"], None, 7, pairs=pairs)) == D.expected_tasks(pairs)


def test_tournament_argv_uses_droplet_paths_and_keeps_order():
    argv = D.tournament_argv({"chain35": f"/Users/me/ckpt/chain35/{BLOB}", "chain30": f"/else/{BLOB}"},
                             {"offense": "offense"},
                             [("chain35", "chain30", 3200), ("chain35", "offense", 3200)],
                             seed0=20700000, workers=8, extra=["--mode", "sample"])
    assert argv == ["--checkpoint", f"chain35=/srv/bb/checkpoints/chain35/{BLOB}",
                    "--checkpoint", f"chain30=/srv/bb/checkpoints/chain30/{BLOB}",
                    "--bot", "offense=offense",
                    "--pair", "chain35,chain30,3200", "--pair", "chain35,offense,3200",
                    "--seed0", "20700000", "--workers", "8", "--out-dir", "/srv/bb/run/main",
                    "--mode", "sample"]
    assert not any("/Users/" in a for a in argv)


def test_tournament_argv_is_accepted_by_the_real_parser(tmp_path, monkeypatch):
    """The generated argv must parse; stop at the checkpoint load so nothing runs."""
    from play_harness import tournament as T
    argv = D.tournament_argv({"x": f"/nope/{BLOB}"}, {"offense": "offense"},
                             [("x", "offense", 2)], 5, 8, out_dir=str(tmp_path / "o"))
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.delenv(T.MAX_WORKERS_ENV, raising=False)
    with pytest.raises(SystemExit) as err:                # 8 workers need the raised cap
        T.main(argv)
    assert "--workers must be 1..4" in str(err.value)
    monkeypatch.setenv(T.MAX_WORKERS_ENV, "8")
    with pytest.raises(FileNotFoundError):                # past parsing, at the missing blob
        T.main(argv)


def test_worker_cap_default_override_and_garbage():
    from play_harness import tournament as T
    assert T.worker_cap({}) == T.MAX_WORKERS == 4
    assert T.worker_cap({T.MAX_WORKERS_ENV: ""}) == 4
    assert T.worker_cap({T.MAX_WORKERS_ENV: "32"}) == 32
    for bad in ("0", "-2", "many", "4.5"):
        with pytest.raises(ValueError):
            T.worker_cap({T.MAX_WORKERS_ENV: bad})


def test_git_head_falls_back_to_the_source_commit_file(tmp_path, monkeypatch):
    from play_harness import tournament as T

    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")
    monkeypatch.setattr(T.subprocess, "run", no_git)
    assert T._git_head(str(tmp_path)) is None
    (tmp_path / T.SOURCE_COMMIT_FILE).write_text("abc123\n")
    assert T._git_head(str(tmp_path)) == "abc123"


# ---- droplet-side scripts ---------------------------------------------------------
def test_job_script_runs_detached_stages_and_writes_exit_atomically():
    argv = D.tournament_argv({"x": f"/l/{BLOB}"}, {}, [("x", "y z", 2)], 1, 16)
    text = D.job_script(argv, 16, stats_reps=200)
    assert "export OMP_NUM_THREADS=1 BBPLAY_MAX_WORKERS=16" in text
    assert "'x,y z,2'" in text                           # shell-quoted, never split
    assert "-m play_harness.tournament --checkpoint" in text
    assert "-m play_harness.tournament_stats --run-dir /srv/bb/run/main --json /srv/bb/run/main/report.json --reps 200" in text
    assert "EXIT.tmp && mv" in text
    assert "sha256sum games.jsonl manifest.json COMPLETE.json report.json" in text
    assert text.index("play_harness.tournament ") < text.index("tournament_stats") < text.index("sha256sum")
    assert "--reps" not in D.job_script(argv, 16)


def test_setup_script_pins_cpu_only_torch():
    text = D.setup_script("2.14.0", "2.5.3")
    assert "--index-url https://download.pytorch.org/whl/cpu torch==2.14.0" in text
    assert "numpy==2.5.3" in text and "set -euo pipefail" in text
    assert "not torch.cuda.is_available()" in text
    assert "DPkg::Lock::Timeout" in text


def test_build_script_checks_the_pinned_commit():
    text = D.build_script("deadbeef")
    assert 'test "$(cat SOURCE_COMMIT)" = deadbeef' in text
    assert "bash play_harness/native/build.sh" in text and "library_sha256" in text


def test_scripts_and_request_bodies_never_carry_the_token():
    secret = "dop_v1_secret"
    blob = (D.setup_script() + D.build_script("c") + D.job_script(["--seed0", "1"], 8)
            + json.dumps(D.droplet_body("n", "sfo3", "c-16", "aa:bb")))
    assert secret not in blob and "DIGITALOCEAN" not in blob and "Bearer" not in blob


# ---- droplet request, size, cost --------------------------------------------------
def test_droplet_body_is_tagged_and_named():
    body = D.droplet_body("c35-gate", "sfo3", "c-16", "aa:bb")
    assert body["name"] == "bb-harness-c35-gate" and body["tags"] == ["bb-harness-tournament"]
    assert body["ssh_keys"] == ["aa:bb"] and body["size"] == "c-16" and body["backups"] is False


SIZES = [{"slug": "s-8vcpu-16gb-amd", "vcpus": 8, "price_hourly": 0.16667, "available": True,
          "regions": ["sfo3", "nyc1"]},
         {"slug": "c-32", "vcpus": 32, "price_hourly": 1.0, "available": False, "regions": ["sfo3"]},
         {"slug": "gpu-h100x1-80gb", "vcpus": 20, "price_hourly": 4.41, "available": True,
          "regions": ["sfo3"]}]


def test_pick_size_refuses_unknown_unavailable_wrong_region_and_pricey():
    assert D.pick_size(SIZES, "s-8vcpu-16gb-amd", "sfo3")["vcpus"] == 8
    for slug, region in (("c-16", "sfo3"), ("c-32", "sfo3"), ("s-8vcpu-16gb-amd", "fra1"),
                         ("gpu-h100x1-80gb", "sfo3")):
        with pytest.raises(D.RunnerError):
            D.pick_size(SIZES, slug, region)
    assert D.pick_size(SIZES, "gpu-h100x1-80gb", "sfo3", max_hourly=5)["vcpus"] == 20


def test_cost_is_prorated_with_a_minimum_charge():
    assert D.cost(3600, 0.5) == pytest.approx(0.5)
    assert D.cost(1800, 0.16667) == pytest.approx(0.083335)
    assert D.cost(10, 0.16667) == 0.01
    assert D.cost(0, 0) == 0.01
    with pytest.raises(ValueError):
        D.cost(-1, 1)


def test_estimate_adds_overhead_and_prices_the_whole_lifetime():
    est = D.estimate(22400, 5.0, 0.16667, overhead_seconds=420)
    assert est["play_seconds"] == pytest.approx(4480)
    assert est["total_minutes"] == pytest.approx((4480 + 420) / 60)
    assert est["cost"] == pytest.approx(4900 / 3600 * 0.16667)
    with pytest.raises(ValueError):
        D.estimate(10, 0, 1)


def test_cpu_steal_fraction_reads_the_eighth_field():
    before = "cpu  100 0 100 800 0 0 0 0 0 0"
    after = "cpu  900 0 100 900 0 0 0 100 0 0"
    assert D.cpu_steal_fraction(before, after) == pytest.approx(100 / 1000)
    assert D.cpu_steal_fraction(before, before) == 0.0
    with pytest.raises(ValueError):
        D.cpu_steal_fraction("cpu 1 2", "cpu 3 4")


# ---- sha256 and manifest verification ---------------------------------------------
def write(path, data):
    with open(path, "wb") as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest()


def test_sha256sums_round_trip_and_reject_garbage(tmp_path):
    h = write(tmp_path / "games.jsonl", b"{}\n")
    assert D.sha256_file(str(tmp_path / "games.jsonl")) == h
    assert D.parse_sha256sums(f"{h}  games.jsonl\n\n{h} *manifest.json\n") == \
        {"games.jsonl": h, "manifest.json": h}
    with pytest.raises(D.RunnerError):
        D.parse_sha256sums("nothex  games.jsonl\n")


def test_verify_files_catches_a_corrupt_missing_or_unlisted_file(tmp_path):
    sums = {name: write(tmp_path / name, name.encode()) for name in D.RESULT_FILES}
    assert D.verify_files(str(tmp_path), sums) == []
    write(tmp_path / "games.jsonl", b"truncated")
    os.remove(tmp_path / "report.json")
    problems = D.verify_files(str(tmp_path), sums)
    assert len(problems) == 2
    assert any(p.startswith("games.jsonl: sha256") for p in problems)
    assert "report.json: not copied" in problems
    unlisted = {k: v for k, v in sums.items() if k != "COMPLETE.json"}
    assert "COMPLETE.json: not listed in SHA256SUMS" in D.verify_files(str(tmp_path), unlisted)


PAIRS = [("a", "b", 4), ("a", "bot", 2)]


def good_manifest():
    return {"harness_git_head": "c0ffee", "seed0": 7, "tasks": 6,
            "pairs": [["a", "bot", 2], ["a", "b", 4]],
            "checkpoints": {"a": {"sha256": "ha"}, "b": {"sha256": "hb"}}}


def test_verify_run_accepts_the_requested_tournament():
    assert D.verify_run(good_manifest(), {"complete": True}, 6, "c0ffee",
                        {"a": "ha", "b": "hb"}, PAIRS, 7) == []


@pytest.mark.parametrize("mutate, lines, needle", [
    (lambda m: m.update(harness_git_head="other"), 6, "commit"),
    (lambda m: m.update(harness_git_head=None), 6, "commit"),
    (lambda m: m["checkpoints"]["b"].update(sha256="swapped"), 6, "checkpoint hashes"),
    (lambda m: m["checkpoints"].pop("b"), 6, "checkpoint hashes"),
    (lambda m: m.update(seed0=8), 6, "seed0"),
    (lambda m: m.update(pairs=[["a", "b", 4]]), 6, "pairs"),
    (lambda m: m.update(tasks=5), 6, "tasks"),
    (lambda m: None, 5, "games.jsonl has 5"),
])
def test_verify_run_flags_each_mismatch(mutate, lines, needle):
    manifest = good_manifest()
    mutate(manifest)
    problems = D.verify_run(manifest, {"complete": True}, lines, "c0ffee",
                            {"a": "ha", "b": "hb"}, PAIRS, 7)
    assert any(needle in p for p in problems), problems


def test_verify_run_needs_a_complete_marker():
    problems = D.verify_run(good_manifest(), {"complete": False}, 6, "c0ffee",
                            {"a": "ha", "b": "hb"}, PAIRS, 7)
    assert any("COMPLETE.json" in p for p in problems)


# ---- determinism comparison ---------------------------------------------------------
def test_compare_runs_reports_bit_identity():
    ref = [game(index=i, leg=leg, digest=f"d{i}{leg}", trail=f"t{i}{leg}")
           for i in range(3) for leg in ("A_home", "B_home")]
    report = D.compare_runs([dict(g) for g in ref[:4]], ref)
    assert report["verdict"].startswith("every game took the same actions")
    assert report["counts"]["exact"] == report["counts"]["matched_keys"] == 4
    assert report["pairs"]["a,b"]["reference_full"]["games"] == 6
    assert not any(report["integrity"].values())


def test_compare_runs_counts_digest_and_trail_separately():
    ref = [game(index=i, digest=f"d{i}", trail=f"t{i}") for i in range(4)]
    run = [game(index=0, digest="d0", trail="t0"),
           game(index=1, digest="d1", trail="DIFF"),
           game(index=2, digest="DIFF", trail="DIFF", result="L", a_td=0, b_td=2),
           game(index=9, digest="x", trail="y")]
    c = D.compare_runs(run, ref)["counts"]
    assert D.compare_runs(run, ref)["verdict"] == "3 of 4 games differ from the reference"
    assert (c["matched_keys"], c["missing_in_reference"]) == (3, 1)
    assert (c["final_digest_equal"], c["action_trail_equal"], c["exact"]) == (2, 1, 1)
    assert c["score_equal"] == 2 and c["rosters_equal"] == 3 and c["seeds_equal"] == 3
    assert c["diverged_games"] == 2


def test_compare_runs_measures_float_drift_only_over_same_action_games():
    ref = [game(index=0, logprob_sum=[-10.0, -20.0]), game(index=1, logprob_sum=[-5.0, -6.0]),
           game(index=2, logprob_sum=[-1.0, -1.0])]
    run = [game(index=0, logprob_sum=[-10.0, -20.0]), game(index=1, logprob_sum=[-5.0004, -6.0]),
           game(index=2, logprob_sum=[-9.0, -1.0], trail="DIVERGED")]
    c = D.compare_runs(run, ref)["counts"]
    assert c["logprob_sum_equal"] == 1 and c["diverged_games"] == 1
    assert c["max_logprob_sum_drift_same_actions"] == pytest.approx(0.0004)


def test_compare_runs_keys_on_pair_index_and_leg():
    ref = [game(pair=("a", "b"), index=0, leg="A_home", digest="one"),
           game(pair=("a", "b"), index=0, leg="B_home", digest="two"),
           game(pair=("a", "c"), index=0, leg="A_home", digest="three")]
    run = [game(pair=("a", "c"), index=0, leg="A_home", digest="three"),
           game(pair=("a", "b"), index=0, leg="B_home", digest="two")]
    report = D.compare_runs(run, ref)
    assert report["counts"]["exact"] == 2 and set(report["pairs"]) == {"a,b", "a,c"}
    assert report["pooled"]["reference_full"]["games"] == 3


def test_compare_runs_an_unmatched_run_is_never_called_identical():
    assert D.compare_runs([game(index=5)], [game(index=0)])["verdict"].startswith("1 of 1 games differ")


def test_compare_runs_distribution_and_z():
    ref = [game(index=i, result="W") for i in range(50)] + \
          [game(index=50 + i, result="L", a_td=0, b_td=1) for i in range(50)]
    run = [game(index=i, result="W", digest="other") for i in range(25)] + \
          [game(index=50 + i, result="L", a_td=0, b_td=1, digest="other") for i in range(25)]
    pooled = D.compare_runs(run, ref)["pooled"]
    assert pooled["run"]["score_rate"] == pytest.approx(0.5)
    assert pooled["z_vs_reference_full"] == pytest.approx(0.0)
    lopsided = D.compare_runs(run[:25], ref)["pooled"]
    assert lopsided["run"]["score_rate"] == 1.0 and lopsided["z_vs_reference_full"] > 5


def test_integrity_totals_count_every_hard_counter_and_missing_fields():
    clean = [game(index=0), game(index=1)]
    assert not any(D.integrity_totals(clean).values())
    dirty = [game(index=0, integrity={**{k: 0 for k in D.HARD_COUNTERS}, "illegal": 2}),
             game(index=1, natural=False), game(index=2, forwards=[499, 500])]
    dirty.append({k: v for k, v in game(index=3).items() if k != "integrity"})
    totals = D.integrity_totals(dirty)
    assert totals["illegal"] == 3 and totals["unnatural"] == 1 and totals["forward_mismatch"] == 1
    assert totals["precheck_collisions"] == 1            # a missing block counts as nonzero


def test_hard_counters_match_the_tournament_contract():
    from play_harness import tournament as T
    assert D.HARD_COUNTERS == T.HARD_COUNTERS
    assert set(D.RESULT_FILES) >= {"games.jsonl", "manifest.json", "COMPLETE.json"}


# ---- leak check and destroy guards ---------------------------------------------------
def droplet(**over):
    d = {"id": 42, "name": "bb-harness-c35", "tags": ["bb-harness-tournament"],
         "size_slug": "c-16", "region": {"slug": "sfo3"}, "status": "active",
         "created_at": "2026-09-17T17:00:00Z", "size": {"price_hourly": 0.5}}
    d.update(over)
    return d


def test_filter_tagged_ignores_other_projects():
    others = [droplet(id=1, name="serena", tags=["serena"]),
              droplet(id=2, name="do-e2e-x", tags=["do-e2e"]), droplet(id=3, tags=None)]
    assert [d["id"] for d in D.filter_tagged(others + [droplet()])] == [42]


def test_destroy_refuses_anything_not_provably_ours():
    assert D.destroy_refusal(droplet(), recorded_id=42, name="c35") is None
    assert D.destroy_refusal(droplet(), recorded_id="42", name="c35") is None
    assert D.destroy_refusal(droplet()) is None
    assert "tag" in D.destroy_refusal(droplet(tags=["do-e2e"]), recorded_id=42, name="c35")
    assert "tag" in D.destroy_refusal(droplet(tags=None))
    assert "named" in D.destroy_refusal(droplet(name="serena"))
    assert "recorded id" in D.destroy_refusal(droplet(id=43), recorded_id=42, name="c35")
    assert "named" in D.destroy_refusal(droplet(), recorded_id=42, name="other-run")


def test_describe_droplet_shows_age_and_accrued_cost():
    import calendar
    import time
    now = calendar.timegm(time.strptime("2026-09-17T19:00:00Z", "%Y-%m-%dT%H:%M:%SZ"))
    line = D.describe_droplet(droplet(), now=now)
    assert "42  bb-harness-c35  c-16  sfo3" in line
    assert "age 120 min" in line and "$1.00" in line


def test_state_records_and_clears_ids(tmp_path):
    state = D.State("run-a", root=str(tmp_path))
    assert state.read("droplet-id") is None
    state.write("droplet-id", 601)
    assert D.State("run-a", root=str(tmp_path)).read("droplet-id") == "601"
    assert oct(os.stat(state.dir).st_mode & 0o777) == "0o700"
    state.clear("droplet-id", "never-written")
    assert state.read("droplet-id") is None
    with pytest.raises(D.RunnerError):
        D.State("../escape", root=str(tmp_path))


def test_run_refuses_bad_requests_before_any_network_call(tmp_path):
    """Each of these must fail in argument checks; the fixture fails any API or ssh use."""
    blob = tmp_path / BLOB
    blob.write_bytes(b"x")
    base = ["run", "--seed0", "1", "--out-root", str(tmp_path / "out")]
    cases = [
        ["--name", "Bad_Name", "--bot", "o=offense", "--pair", "o,o,2"],
        ["--name", "ok", "--checkpoint", f"a={blob}", "--bot", "a=offense", "--pair", "a,a,2"],
        ["--name", "ok", "--bot", "o=offense", "--bot", "c=contact", "--pair", "o,c,3"],
        ["--name", "ok", "--bot", "o=offense", "--bot", "c=contact"],
        ["--name", "ok", "--checkpoint", f"a={blob}", "--bot", "o=offense", "--pair", "a,o,2"],
    ]
    for extra in cases:
        assert D.main(base + extra) == 1, extra


# ---- merging shards that split a tournament by pair -----------------------------------
def shard(name, pairs, games, **manifest_over):
    manifest = {"schema": "bbplay-tournament-v1", "seed0": 7, "mode": "sample", "kernel": "native",
                "max_decisions": 4096, "omp_num_threads": 1, "rosters": "procgen", "legs": ["A_home", "B_home"],
                "sampling_seed": "keyed", "harness_git_head": "c0ffee", "torch": "2.14.0+cpu",
                "python": "3.12.3", "host": name, "workers": 8, "tasks": len(games),
                "pairs": [list(p) for p in pairs], "bot_library_sha256": None, "bots": {},
                "checkpoints": {"a": {"sha256": "ha", "path": "/srv/a"}},
                "players": {"a": {"mode": "sample", "temperature": 1.0}}}
    manifest.update(manifest_over)
    return {"name": name, "manifest": manifest, "games": games, "games_sha256": "g" + name,
            "complete": {"complete": True, "wall_seconds": 100.0 + len(games),
                         "games_per_second_wall": 1.5},
            "machine": {"library_sha256": "lib1", "cpu_model": "DO-Premium-AMD"}}


def two_shards():
    s1 = shard("s1", [("a", "b", 2)], [game(pair=("a", "b"), index=0, leg=leg) for leg in ("A_home", "B_home")])
    s2 = shard("s2", [("a", "bot", 2)],
               [game(pair=("a", "bot"), index=0, leg=leg) for leg in ("A_home", "B_home")],
               bots={"bot": {"kind": "offense"}}, bot_library_sha256="lib1")
    s1["manifest"]["checkpoints"]["b"] = {"sha256": "hb", "path": "/srv/b"}
    return s1, s2


def test_merge_joins_disjoint_shards_and_keeps_provenance():
    manifest, complete, games = D.merge_shards(list(two_shards()))
    assert len(games) == 4 and manifest["tasks"] == 4 and complete["played"] == 4
    assert manifest["pairs"] == [["a", "b", 2], ["a", "bot", 2]]
    assert set(manifest["checkpoints"]) == {"a", "b"} and set(manifest["bots"]) == {"bot"}
    assert manifest["bot_library_sha256"] == "lib1" and manifest["harness_git_head"] == "c0ffee"
    assert [m["name"] for m in manifest["merged_from"]] == ["s1", "s2"]
    assert manifest["merged_from"][0]["games_sha256"] == "gs1"
    assert complete["complete"] and complete["wall_seconds"] == 102.0
    assert complete["shard_games_per_second_wall_sum"] == 3.0


@pytest.mark.parametrize("mutate, needle", [
    (lambda a, b: b["manifest"].update(harness_git_head="other"), "harness_git_head"),
    (lambda a, b: b["manifest"].update(seed0=8), "seed0"),
    (lambda a, b: b["manifest"].update(torch="2.13.0"), "torch"),
    (lambda a, b: b["machine"].update(library_sha256="lib2"), "compiled shim"),
    (lambda a, b: b.update(machine=None), "compiled shim"),
    (lambda a, b: b["manifest"].update(bot_library_sha256="elsewhere"), "bot library"),
    (lambda a, b: b["complete"].update(complete=False), "not complete"),
    (lambda a, b: b["games"].pop(), "manifest says"),
    (lambda a, b: b["manifest"]["checkpoints"]["a"].update(sha256="swapped"), "checkpoints[a]"),
    (lambda a, b: b["manifest"]["players"]["a"].update(temperature=0.5), "players[a]"),
    (lambda a, b: b["manifest"].update(pairs=[["b", "a", 2]]), "is also in s1"),
    (lambda a, b: b["games"][0].update(pair=["a", "zz"]), "outside its manifest"),
    (lambda a, b: b["games"][0]["integrity"].update(illegal=1), "integrity"),
])
def test_merge_refuses_shards_that_are_not_one_tournament(mutate, needle):
    s1, s2 = two_shards()
    mutate(s1, s2)
    with pytest.raises(D.RunnerError) as err:
        D.merge_shards([s1, s2])
    assert needle in str(err.value), str(err.value)


def test_merge_needs_two_shards():
    with pytest.raises(D.RunnerError):
        D.merge_shards([two_shards()[0]])


def test_a_full_account_is_a_blocker_not_a_reason_to_delete():
    assert D.limit_refusal(5, 10) is None and D.limit_refusal(9, 10) is None
    for existing in (10, 11):
        message = D.limit_refusal(existing, 10)
        assert message.startswith("BLOCKER") and "Do not delete" in message
