"""Pure-logic tests for tools/droplet_tournament.py. Nothing here touches the network:
the autouse fixture makes any urlopen, ssh or scp call fail the test."""
import hashlib
import io
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


def test_tournament_argv_adds_games_per_worker_only_when_batched():
    args = ({"x": f"/nope/{BLOB}"}, {"offense": "offense"}, [("x", "offense", 2)], 5, 8)
    assert "--games-per-worker" not in D.tournament_argv(*args)
    assert D.tournament_argv(*args) == D.tournament_argv(*args, games_per_worker=1)
    argv = D.tournament_argv(*args, games_per_worker=16)
    assert argv[argv.index("--games-per-worker") + 1] == "16"
    assert build_run_args(["--games-per-worker", "16"]).games_per_worker == 16
    assert build_run_args([]).games_per_worker == 1


def test_games_per_worker_is_refused_before_anything_is_created():
    """cmd_run must stop on a bad value before it reads the token or calls the API; the
    no-network fixture fails the test if it gets that far."""
    from play_harness import tournament as T
    assert D.MAX_GAMES_PER_WORKER == T.MAX_GAMES_PER_WORKER
    for bad in ("0", "-1", "257"):
        args = build_run_args(["--games-per-worker", bad, "--bot", "c=contact", "--bot",
                               "o=offense", "--pair", "c,o,2"])
        with pytest.raises(D.RunnerError, match="games-per-worker"):
            D.cmd_run(args)


def build_run_args(extra):
    return D.build_parser().parse_args(["run", "--name", "n", "--seed0", "1", *extra])


def test_verify_run_checks_games_per_worker():
    ok = dict(manifest=good_manifest_with_bot(), complete={"complete": True},
              games=scheduled_games(), commit="c0ffee", checkpoint_sha={"a": "ha", "b": "hb"},
              pairs=PAIRS, seed0=7, bots={"bot": "offense"})
    assert D.verify_run(**ok) == []                                  # no key counts as 1
    assert any("games_per_worker" in p for p in D.verify_run(**ok, games_per_worker=8))
    ok["manifest"]["games_per_worker"] = 8
    assert D.verify_run(**ok, games_per_worker=8) == []
    assert any("games_per_worker" in p for p in D.verify_run(**ok))


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
    sums = {name: write(tmp_path / name, name.encode())
            for name in D.RESULT_FILES + D.PROVENANCE_FILES}
    assert D.verify_files(str(tmp_path), sums) == []
    no_machine = {k: v for k, v in sums.items() if k != "machine.json"}
    assert "machine.json: not listed in SHA256SUMS" in D.verify_files(str(tmp_path), no_machine)
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


def scheduled_games(pairs=PAIRS, seed0=7):
    return [game(pair=(a, b), index=i, leg=leg, engine_seed=seed0 + i)
            for a, b, n in pairs for i in range(n // 2) for leg in ("A_home", "B_home")]


def good_manifest_with_bot():
    return {**good_manifest(), "bots": {"bot": {"kind": "offense"}}}


def test_verify_run_accepts_the_requested_tournament():
    assert D.verify_run(good_manifest_with_bot(), {"complete": True}, scheduled_games(), "c0ffee",
                        {"a": "ha", "b": "hb"}, PAIRS, 7, bots={"bot": "offense"}) == []


@pytest.mark.parametrize("mutate, lines, needle", [
    (lambda m: m.update(harness_git_head="other"), 6, "commit"),
    (lambda m: m.update(harness_git_head=None), 6, "commit"),
    (lambda m: m["checkpoints"]["b"].update(sha256="swapped"), 6, "checkpoint hashes"),
    (lambda m: m["checkpoints"].pop("b"), 6, "checkpoint hashes"),
    (lambda m: m.update(seed0=8), 6, "seed0"),
    (lambda m: m.update(pairs=[["a", "b", 4]]), 6, "pairs"),
    (lambda m: m.update(tasks=5), 6, "tasks"),
    (lambda m: None, 5, "games.jsonl has 5"),
    (lambda m: m.update(bots={"bot": {"kind": "contact"}}), 6, "bots"),
    (lambda m: m.update(bots={}), 6, "bots"),
])
def test_verify_run_flags_each_mismatch(mutate, lines, needle):
    manifest = good_manifest_with_bot()
    mutate(manifest)
    problems = D.verify_run(manifest, {"complete": True}, scheduled_games()[:lines], "c0ffee",
                            {"a": "ha", "b": "hb"}, PAIRS, 7, bots={"bot": "offense"})
    assert any(needle in p for p in problems), problems


def test_verify_run_needs_a_complete_marker():
    problems = D.verify_run(good_manifest_with_bot(), {"complete": False}, scheduled_games(),
                            "c0ffee", {"a": "ha", "b": "hb"}, PAIRS, 7, bots={"bot": "offense"})
    assert any("COMPLETE.json" in p for p in problems)


def test_schedule_problems_accept_exactly_the_schedule():
    assert D.schedule_problems(scheduled_games(), PAIRS, 7) == []
    from play_harness import tournament as T
    real = {((a, b), i, leg) for a, b, i, leg in
            T.schedule(["a", "b", "bot"], None, 7, pairs=[("a", "b", 4), ("a", "bot", 2)])}
    assert real == {D._key(g) for g in scheduled_games()}


def test_schedule_problems_catch_the_right_count_of_the_wrong_games():
    games = scheduled_games()
    wrong_index = [dict(g, game_index=987, engine_seed=7 + 987) if g["pair"] == ["a", "bot"] else g
                   for g in games]
    problems = D.schedule_problems(wrong_index, PAIRS, 7)
    assert any("missing" in p for p in problems) and any("outside the schedule" in p for p in problems)
    wrong_seed = [dict(games[0], engine_seed=1)] + games[1:]
    assert any("wrong engine seed" in p for p in D.schedule_problems(wrong_seed, PAIRS, 7))
    assert any("duplicate" in p for p in D.schedule_problems(games + games[:1], PAIRS, 7))
    one_leg = [g for g in games if not (g["pair"] == ["a", "bot"] and g["leg"] == "B_home")]
    assert any("missing" in p for p in D.schedule_problems(one_leg, PAIRS, 7))


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
    s1 = shard("s1", [("a", "b", 2)], [game(pair=("a", "b"), index=0, leg=leg, engine_seed=7)
                                       for leg in ("A_home", "B_home")])
    s2 = shard("s2", [("a", "bot", 2)],
               [game(pair=("a", "bot"), index=0, leg=leg, engine_seed=7)
                for leg in ("A_home", "B_home")],
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
    (lambda a, b: b["manifest"].update(games_per_worker=8), "games_per_worker"),
    (lambda a, b: (a["manifest"].update(games_per_worker=8),
                   b["manifest"].update(games_per_worker=16)), "games_per_worker"),
    (lambda a, b: b["machine"].update(library_sha256="lib2"), "compiled shim"),
    (lambda a, b: b.update(machine=None), "compiled shim"),
    (lambda a, b: b["manifest"].update(bot_library_sha256="elsewhere"), "bot library"),
    (lambda a, b: b["complete"].update(complete=False), "not complete"),
    (lambda a, b: b["games"].pop(), "manifest says"),
    (lambda a, b: b["manifest"]["checkpoints"]["a"].update(sha256="swapped"), "checkpoints[a]"),
    (lambda a, b: b["manifest"]["players"]["a"].update(temperature=0.5), "players[a]"),
    (lambda a, b: b["manifest"].update(pairs=[["b", "a", 2]]), "is also in s1"),
    (lambda a, b: b["games"][0].update(pair=["a", "zz"]), "outside the schedule"),
    (lambda a, b: [g.update(game_index=987, engine_seed=994) for g in b["games"]], "missing"),
    (lambda a, b: b["games"][0].update(engine_seed=1), "wrong engine seed"),
    (lambda a, b: b["games"][0]["integrity"].update(illegal=1), "integrity"),
])
def test_merge_refuses_shards_that_are_not_one_tournament(mutate, needle):
    s1, s2 = two_shards()
    mutate(s1, s2)
    with pytest.raises(D.RunnerError) as err:
        D.merge_shards([s1, s2])
    assert needle in str(err.value), str(err.value)


def test_merge_carries_games_per_worker_and_reads_a_missing_key_as_one():
    s1, s2 = two_shards()
    s1["manifest"]["games_per_worker"] = 1                           # s2 has no key
    assert D.merge_shards([s1, s2])[0]["games_per_worker"] == 1
    for s in (s1, s2):
        s["manifest"]["games_per_worker"] = 16
    assert D.merge_shards([s1, s2])[0]["games_per_worker"] == 16


def test_merge_needs_two_shards():
    with pytest.raises(D.RunnerError):
        D.merge_shards([two_shards()[0]])


# ---- a run from a later game index (run --index0) --------------------------------------
def test_tournament_argv_adds_index0_only_when_set(tmp_path, monkeypatch):
    from play_harness import tournament as T
    args = ({"x": f"/nope/{BLOB}"}, {"offense": "offense"}, [("x", "offense", 4)], 5, 2)
    assert "--index0" not in D.tournament_argv(*args)
    assert D.tournament_argv(*args) == D.tournament_argv(*args, index0=0)
    argv = D.tournament_argv(*args, index0=200, out_dir=str(tmp_path / "o"), extra=["--mode", "sample"])
    assert argv[argv.index("--index0") + 1] == "200" and argv[-2:] == ["--mode", "sample"]
    assert build_run_args(["--index0", "200"]).index0 == 200 and build_run_args([]).index0 == 0
    # The real parser takes it and schedules from that index, then stops at the missing blob.
    seen = {}
    real = T.schedule

    def spy(*a, **kw):
        seen["tasks"] = real(*a, **kw)
        return seen["tasks"]
    monkeypatch.setattr(T, "schedule", spy)
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.delenv(T.GAMES_PER_WORKER_ENV, raising=False)
    with pytest.raises(FileNotFoundError):
        T.main(argv)
    assert seen["tasks"] == [("x", "offense", i, leg) for i in (200, 201)
                             for leg in ("A_home", "B_home")]


@pytest.mark.parametrize("extra, needle", [
    (["--tournament-arg=--index0", "--tournament-arg=4"], "not --tournament-arg"),
    (["--tournament-arg=--index0=4"], "not --tournament-arg"),
    (["--index0", "4", "--tournament-arg=--index0=4"], "not --tournament-arg"),
    (["--index0", "-1"], "--index0 must be 0 or more"),
])
def test_an_index0_request_is_refused_before_anything_is_created(extra, needle):
    """Argument checks only: the no-network fixture fails the test if cmd_run reads the
    token, calls the API or runs git."""
    args = build_run_args(["--bot", "c=contact", "--bot", "o=offense", "--pair", "c,o,2", *extra])
    with pytest.raises(D.RunnerError, match=needle):
        D.cmd_run(args)
    assert D.index0_refusal(4, ["--mask", "S=m1"]) is None and D.index0_refusal(0, []) is None


def sliced_games(pairs=PAIRS, seed0=7, index0=0):
    return [game(pair=(a, b), index=i, leg=leg, engine_seed=seed0 + i)
            for a, b, n in pairs for i in range(index0, index0 + n // 2)
            for leg in ("A_home", "B_home")]


def test_verify_run_holds_a_slice_to_its_index0():
    ok = dict(complete={"complete": True}, commit="c0ffee", checkpoint_sha={"a": "ha", "b": "hb"},
              pairs=PAIRS, seed0=7, bots={"bot": "offense"})
    manifest = {**good_manifest_with_bot(), "index0": 10}
    games = sliced_games(index0=10)
    assert {g["game_index"] for g in games} == {10, 11}
    assert D.verify_run(manifest, games=games, index0=10, **ok) == []
    # The request was another index, or none.
    for asked in (0, 9, 11):
        problems = D.verify_run(manifest, games=games, index0=asked, **ok)
        assert any(f"manifest index0 10 != requested {asked}" in p for p in problems)
        assert any("missing" in p for p in problems) and any("outside the schedule" in p for p in problems)
    # The manifest says the index and the games are from 0, or the other way round.
    problems = D.verify_run(manifest, games=sliced_games(), index0=10, **ok)
    assert any("6 scheduled games missing" in p for p in problems)
    assert not any("manifest index0" in p for p in problems)
    problems = D.verify_run(good_manifest_with_bot(), games=games, index0=10, **ok)
    assert problems == ["manifest index0 0 != requested 10"]
    # A game inside the range on a seed that is not seed0 + its index.
    moved = [dict(games[0], engine_seed=7)] + games[1:]
    assert any("wrong engine seed" in p for p in D.verify_run(manifest, games=moved, index0=10, **ok))
    for bad in (-1, "10", 1.5, True, None):
        assert any("manifest index0" in p for p in D.verify_run(
            {**good_manifest_with_bot(), "index0": bad}, games=games, index0=10, **ok)), bad


def test_schedule_problems_at_an_index0_agree_with_the_real_scheduler():
    from play_harness import tournament as T
    real = {((a, b), i, leg) for a, b, i, leg in
            T.schedule(["a", "b", "bot"], None, 7, pairs=PAIRS, index0=10)}
    assert real == {D._key(g) for g in sliced_games(index0=10)}
    assert D.schedule_problems(sliced_games(index0=10), PAIRS, 7, 10) == []
    assert D.schedule_problems(sliced_games(index0=10), PAIRS, 7, index0=10) == []
    assert D.schedule_problems(sliced_games(), PAIRS, 7) == D.schedule_problems(sliced_games(), PAIRS, 7, 0) == []
    assert any("outside the schedule" in p for p in D.schedule_problems(sliced_games(index0=10), PAIRS, 7))


# ---- merging slices: one pair split by game index ---------------------------------------
def slice_shard(name, index0, n=4, pair=("a", "b"), **manifest_over):
    """A shard that holds game indexes index0 .. index0 + n/2 - 1 of one pair."""
    if index0:
        manifest_over.setdefault("index0", index0)
    out = shard(name, [(*pair, n)], sliced_games([(*pair, n)], index0=index0), **manifest_over)
    out["manifest"]["checkpoints"]["b"] = {"sha256": "hb", "path": "/srv/b"}
    return out


def three_slices():
    return slice_shard("s0", 0), slice_shard("s2", 2), slice_shard("s4", 4)


def test_merge_joins_the_slices_of_one_pair_into_a_run_from_index_0():
    manifest, complete, games = D.merge_shards(list(three_slices()))
    assert manifest["pairs"] == [["a", "b", 12]] and manifest["tasks"] == 12 == len(games)
    assert "index0" not in manifest and manifest["seed0"] == 7
    assert sorted(D._key(g) for g in games) == sorted(
        (("a", "b"), i, leg) for i in range(6) for leg in ("A_home", "B_home"))
    assert D.schedule_problems(games, [("a", "b", 12)], 7) == []        # one run from index 0
    assert [(m["name"], m.get("index0"), m["pairs"]) for m in manifest["merged_from"]] == \
        [("s0", None, [["a", "b", 4]]), ("s2", 2, [["a", "b", 4]]), ("s4", 4, [["a", "b", 4]])]
    assert "index0" not in manifest["merged_from"][0]
    assert complete == {"played": 12, "complete": True, "shards": 3, "wall_seconds": 104.0,
                        "shard_games_per_second_wall_sum": 4.5}
    # The order of the shard arguments does not matter: the slices are joined by index.
    s0, s2, s4 = three_slices()
    again = D.merge_shards([s4, s0, s2])
    assert again == (manifest, complete, games)
    assert [g["game_index"] for g in again[2]] == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    assert [s["name"] for s in D.slice_order([s4, s0, s2])] == ["s0", "s2", "s4"]


def test_merge_takes_slices_of_unequal_length_and_whole_pairs_beside_them():
    s0 = slice_shard("s0", 0, n=2)
    s1 = slice_shard("s1", 1, n=6)
    whole = two_shards()[1]                                  # a,bot from index 0, one shard
    manifest, _, games = D.merge_shards([whole, s1, s0])
    assert manifest["pairs"] == [["a", "bot", 2], ["a", "b", 8]] and len(games) == 10
    assert [m["name"] for m in manifest["merged_from"]] == ["s2", "s0", "s1"]
    # A shard may hold a slice of one pair and the whole of another only from index 0.
    both = shard("s0", [("a", "b", 2), ("a", "bot", 2)],
                 sliced_games([("a", "b", 2), ("a", "bot", 2)]),
                 bots={"bot": {"kind": "offense"}}, bot_library_sha256="lib1")
    both["manifest"]["checkpoints"]["b"] = {"sha256": "hb", "path": "/srv/b"}
    manifest, _, games = D.merge_shards([both, slice_shard("s1", 1, n=6)])
    assert manifest["pairs"] == [["a", "b", 8], ["a", "bot", 2]] and len(games) == 10


@pytest.mark.parametrize("build, needle", [
    # overlap
    (lambda: [slice_shard("s0", 0), slice_shard("s1", 1)],
     "pair a,b: game index ranges overlap: s0 [0, 2), s1 [1, 3)"),
    (lambda: [slice_shard("s0", 0), slice_shard("again", 0)],
     "pair a,b: game index ranges overlap: s0 [0, 2), again [0, 2)"),
    (lambda: [slice_shard("s0", 0, n=8), slice_shard("s2", 2), slice_shard("s4", 4)],
     "pair a,b: game index ranges overlap: s0 [0, 4), s2 [2, 4), s4 [4, 6)"),
    # a gap
    (lambda: [slice_shard("s0", 0), slice_shard("s3", 3)],
     "pair a,b: game index ranges leave a gap: s0 [0, 2), s3 [3, 5)"),
    (lambda: [slice_shard("s0", 0), slice_shard("s4", 4), slice_shard("s8", 8)],
     "pair a,b: game index ranges leave a gap: s0 [0, 2), s4 [4, 6), s8 [8, 10)"),
    # not from index 0, as slices and as a pair that one shard holds
    (lambda: [slice_shard("s2", 2), slice_shard("s4", 4)],
     "pair a,b: game indexes do not start at 0: s2 [2, 4), s4 [4, 6)"),
    (lambda: [two_shards()[1], slice_shard("s2", 2)],
     "pair a,b: game indexes do not start at 0: s2 [2, 4)"),
    # the same pair the other way round is another pair's records
    (lambda: [slice_shard("s0", 0), slice_shard("s2", 2, pair=("b", "a"))],
     "s2: pair b,a is also in s0 as a,b"),
])
def test_merge_refuses_slices_that_do_not_tile_the_pair_from_index_0(build, needle):
    with pytest.raises(D.RunnerError) as err:
        D.merge_shards(build())
    assert needle in str(err.value), str(err.value)


@pytest.mark.parametrize("mutate, needle", [
    (lambda a, b: b["manifest"]["players"]["a"].update(temperature=0.5), "players[a]"),
    (lambda a, b: b["manifest"]["players"]["a"].update(masks=["m1"]), "players[a]"),
    (lambda a, b: (a["manifest"]["players"].update(b={"mode": "sample", "temperature": 1.0}),
                   b["manifest"]["players"].update(b={"mode": "argmax", "temperature": 1.0})),
     "players[b]"),
    (lambda a, b: b["manifest"].update(games_per_worker=8), "games_per_worker"),
    (lambda a, b: (a["manifest"].update(games_per_worker=8),
                   b["manifest"].update(games_per_worker=16)), "games_per_worker"),
    (lambda a, b: b["manifest"].update(seed0=8), "seed0"),
    (lambda a, b: b["manifest"].update(harness_git_head="other"), "harness_git_head"),
    (lambda a, b: b["machine"].update(library_sha256="lib2"), "compiled shim"),
    (lambda a, b: b["manifest"]["checkpoints"]["b"].update(sha256="swapped"), "checkpoints[b]"),
    (lambda a, b: b["manifest"].update(index0=-2), "index0 -2 is not a game index"),
    (lambda a, b: b["manifest"].update(index0="2"), "index0 '2' is not a game index"),
    (lambda a, b: b["manifest"].update(pairs=[["a", "b", 3]]), "odd game count 3"),
    # The slice's own games are not the indexes its manifest names.
    (lambda a, b: b["manifest"].update(index0=3), "s2: 2 scheduled games missing"),
    (lambda a, b: b["games"][0].update(engine_seed=7), "s2: 1 games on the wrong engine seed"),
    (lambda a, b: b["games"].pop(), "manifest says"),
    (lambda a, b: b["complete"].update(complete=False), "not complete"),
])
def test_merge_holds_slices_to_everything_it_held_shards_to(mutate, needle):
    s0, s2 = slice_shard("s0", 0), slice_shard("s2", 2)
    mutate(s0, s2)
    with pytest.raises(D.RunnerError) as err:
        D.merge_shards([s0, s2])
    assert needle in str(err.value), str(err.value)


def test_merge_writes_the_slices_in_index_order(tmp_path):
    """cmd_merge end to end on files: shards given out of order come out as one
    run from index 0 with the games in index order."""
    dirs = []
    for s in three_slices()[::-1]:
        d = tmp_path / s["name"] / "main"
        d.mkdir(parents=True)
        (d / "games.jsonl").write_text("".join(json.dumps(g) + "\n" for g in s["games"]))
        for fname, payload in (("manifest.json", s["manifest"]), ("COMPLETE.json", s["complete"]),
                               ("machine.json", s["machine"]), ("report.json", {})):
            (d / fname).write_text(json.dumps(payload))
        (d / "SHA256SUMS").write_text("".join(
            f"{D.sha256_file(str(d / f))}  {f}\n" for f in D.RESULT_FILES + D.PROVENANCE_FILES))
        dirs.append(str(d))
    out = tmp_path / "all" / "main"
    assert D.main(["merge", "--out", str(out), *(a for d in dirs for a in ("--shard", d))]) == 0
    games = [json.loads(line) for line in (out / "games.jsonl").read_text().splitlines()]
    assert [(g["game_index"], g["leg"]) for g in games] == [
        (i, leg) for i in range(6) for leg in ("A_home", "B_home")]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["pairs"] == [["a", "b", 12]] and "index0" not in manifest
    assert [m["name"] for m in manifest["merged_from"]] == ["s0", "s2", "s4"]
    assert [m["games_sha256"] for m in manifest["merged_from"]] == [
        D.sha256_file(os.path.join(d, "games.jsonl")) for d in dirs[::-1]]
    assert json.loads((out / "COMPLETE.json").read_text())["complete"] is True


def test_a_merge_cannot_see_a_missing_last_slice_and_gate_acceptance_can(tmp_path):
    """Slices [0, 2) and [2, 4) of a pair registered for indexes 0..5 tile a run
    from index 0, so they merge. Only the registered plan knows the pair's total:
    tools/gate_acceptance.py rejects the merged run."""
    from tools import gate_acceptance as GA
    s0, s2, s4 = three_slices()
    plan = {"seed0": 7, "games_per_worker": 1, "commit": "c0ffee", "pairs": [("a", "b", 12)],
            "checkpoints": {"a": "ha", "b": "hb"}}

    def accept(shards, name):
        manifest, complete, games = D.merge_shards(shards)
        folder = tmp_path / name
        folder.mkdir()
        rows = [dict(g, modes=["sample", "sample"], temperatures=[1.0, 1.0]) for g in games]
        (folder / "games.jsonl").write_text("".join(json.dumps(g) + "\n" for g in rows))
        (folder / "manifest.json").write_text(json.dumps(manifest))
        (folder / "COMPLETE.json").write_text(json.dumps(complete))
        return GA.accept(str(folder), plan)

    assert accept([s0, s2, s4], "all") == []
    problems = accept([s0, s2], "short")
    assert any("pairs differ from the registered plan" in p for p in problems)
    assert any("4 scheduled games missing" in p for p in problems)
    assert any("8 games recorded != 12 registered" in p for p in problems)


def test_a_full_account_is_a_blocker_not_a_reason_to_delete():
    assert D.limit_refusal(5, 10) is None and D.limit_refusal(9, 10) is None
    for existing in (10, 11):
        message = D.limit_refusal(existing, 10)
        assert message.startswith("BLOCKER") and "Do not delete" in message


# ---- API retries (urlopen is faked; nothing leaves the process) ------------------------
class FakeResponse:
    status = 200

    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def flaky_urlopen(monkeypatch, failures):
    calls = []

    def urlopen(req, timeout=None):
        calls.append(req.get_method())
        if len(calls) <= failures:
            raise D.urllib.error.URLError("network down")
        return FakeResponse({"ok": True})
    monkeypatch.setattr(D.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(D.time, "sleep", lambda s: None)
    return calls


def test_api_retries_reads_and_deletes_through_an_outage(monkeypatch):
    calls = flaky_urlopen(monkeypatch, failures=3)
    assert D.Api("tok", retries=5).call("DELETE", "/droplets/1") == (200, {"ok": True})
    assert calls == ["DELETE"] * 4


def test_api_never_repeats_a_create(monkeypatch):
    calls = flaky_urlopen(monkeypatch, failures=1)
    with pytest.raises(D.RunnerError) as err:
        D.Api("tok", retries=5).call("POST", "/droplets", {"name": "x"})
    assert calls == ["POST"] and "tok" not in str(err.value)


def test_api_gives_up_with_a_runner_error_and_no_token(monkeypatch):
    calls = flaky_urlopen(monkeypatch, failures=99)
    with pytest.raises(D.RunnerError) as err:
        D.Api("secret-token", retries=2).call("GET", "/account")
    assert len(calls) == 3 and "secret-token" not in str(err.value)


# ---- review fixes: z, compare rendering, versions, adoption, lock ----------------------
def test_z_is_not_zero_when_a_constant_run_disagrees_with_a_constant_reference():
    wins = D._summary([game(index=i, result="W") for i in range(5)])
    losses = D._summary([game(index=i, result="L") for i in range(5)])
    assert D._z(wins, losses) == float("inf") and D._z(losses, wins) == float("-inf")
    assert D._z(wins, wins) == 0.0 and D._z(wins, D._summary([])) is None


def test_compare_row_renders_a_pair_the_reference_never_played():
    report = D.compare_runs([game(pair=("a", "new"), index=0)], [game(pair=("a", "b"), index=0)])
    assert "absent from the reference" in D.compare_row("a,new", report["pairs"]["a,new"])
    assert "absent" in D.compare_row("POOLED", report["pooled"])
    both = D.compare_runs([game(index=0), game(index=1, result="L")],
                          [game(index=0), game(index=1, result="L")])
    assert "z=+0.00" in D.compare_row("a,b", both["pairs"]["a,b"])


def test_setup_script_refuses_versions_that_are_not_plain():
    for bad in ("2.14.0; rm -rf /", "2.14.0 --pre", "$(id)", "", "latest"):
        with pytest.raises(D.RunnerError):
            D.setup_script(bad, "2.5.3")
        with pytest.raises(D.RunnerError):
            D.setup_script("2.14.0", bad)


def test_adoptable_needs_our_tag_exact_name_and_a_creation_after_the_attempt():
    import calendar
    import time
    at = calendar.timegm(time.strptime("2026-09-17T17:00:30Z", "%Y-%m-%dT%H:%M:%SZ"))
    ours = droplet(id=7, name="bb-harness-c35", created_at="2026-09-17T17:00:31Z")
    candidates = [ours,
                  droplet(id=8, name="bb-harness-c35-s2", created_at="2026-09-17T17:00:31Z"),
                  droplet(id=9, name="bb-harness-c35", created_at="2026-09-17T12:00:00Z"),
                  droplet(id=10, name="bb-harness-c35", tags=["do-e2e"],
                          created_at="2026-09-17T17:00:31Z"),
                  droplet(id=11, name="serena", tags=["serena"], created_at="2026-09-17T17:00:31Z")]
    assert [d["id"] for d in D.adoptable(candidates, "c35", at)] == [7]


def test_a_second_process_cannot_take_the_same_run_name(tmp_path):
    first = D.State("gate", root=str(tmp_path)).lock()
    with pytest.raises(D.RunnerError):
        D.State("gate", root=str(tmp_path)).lock()
    other = D.State("gate-s2", root=str(tmp_path)).lock()
    first.close()
    other.close()
    D.State("gate", root=str(tmp_path)).lock().close()


def test_api_retries_a_rate_limit_on_delete_but_not_on_create(monkeypatch):
    calls = []

    def urlopen(req, timeout=None):
        calls.append(req.get_method())
        if len(calls) < 3:
            raise D.urllib.error.HTTPError(req.full_url, 429, "slow down", {},
                                           io.BytesIO(b'{"message": "limited"}'))
        return FakeResponse({"ok": True})
    monkeypatch.setattr(D.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(D.time, "sleep", lambda s: None)
    assert D.Api("tok").call("DELETE", "/droplets/1")[0] == 200 and calls == ["DELETE"] * 3
    calls.clear()
    assert D.Api("tok").call("POST", "/droplets", {})[0] == 429 and calls == ["POST"]


# ---- the search seat ------------------------------------------------------------------
def test_search_settings_parse_as_the_tournament_parses_them():
    from play_harness import search as S
    assert D.DEFAULT_SEARCH == (S.DEFAULT_K, S.DEFAULT_N, S.DEFAULT_DELTA)
    for text in ("default", "4:16:0.1", "2:2:0", "4:16:inf", "3:8:0.02", "2:2:0.0"):
        theirs = S.parse_setting(text)
        assert D.parse_search(text) == {key: theirs[key] for key in ("k", "n", "delta")}
    for bad in ("", "4:16", "1:16:0.1", "4:1:0.1", "4:16:-1", "4:16:nan", "a:b:c", "4:16:0.1:2",
                "4.5:16:0.1"):
        with pytest.raises(D.RunnerError, match="--search"):
            D.parse_search(bad)
        with pytest.raises(ValueError):
            S.parse_setting(bad)


def test_extra_assignments_read_both_spellings_of_a_flag():
    extra = ["--mask", "S=m1", "--mask=C=m1,m3", "--sampling-offset", "C=1", "--mode", "sample",
             "--mask"]
    assert D.extra_assignments(extra, "--mask") == {"S": "m1", "C": "m1,m3"}
    assert D.extra_assignments(extra, "--sampling-offset") == {"C": "1"}
    assert D.extra_assignments(extra, "--temperature") == {}


SEARCH_EXTRA = ["--mask", "S=m1", "--mask", "I=m1", "--mask", "C=m1", "--sampling-offset", "C=1"]


def test_tournament_argv_carries_the_search_flag_the_real_parser_accepts(tmp_path, monkeypatch):
    from play_harness import search as S
    from play_harness import tournament as T
    search = {"S": D.parse_search("default"), "I": D.parse_search("2:8:inf")}
    blobs = {name: f"/nope/{name}/{BLOB}" for name in ("S", "I", "C")}
    pairs = [("S", "C", 2), ("I", "C", 2)]
    argv = D.tournament_argv(blobs, {}, pairs, 5, 2, out_dir=str(tmp_path / "o"),
                             extra=SEARCH_EXTRA, search=search)
    at = argv.index("--search")
    assert argv[at:at + 4] == ["--search", "S=4:16:0.1", "--search", "I=2:8:inf"]
    assert argv[at + 4:] == SEARCH_EXTRA and "--games-per-worker" not in argv
    assert D.tournament_argv(blobs, {}, pairs, 5, 2) == \
        D.tournament_argv(blobs, {}, pairs, 5, 2, search={})       # no flag without a seat
    # The real parser takes it, builds the full settings, and stops at the missing blob.
    seen = {}
    real = T.player_specs

    def spy(*args, **kwargs):
        seen["specs"] = real(*args, **kwargs)
        return seen["specs"]
    monkeypatch.setattr(T, "player_specs", spy)
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.delenv(T.GAMES_PER_WORKER_ENV, raising=False)
    with pytest.raises(FileNotFoundError):
        T.main(argv)
    assert seen["specs"]["S"]["search"] == S.search_setting()
    assert seen["specs"]["I"]["search"] == S.search_setting(2, 8, float("inf"))
    assert "search" not in seen["specs"]["C"] and seen["specs"]["C"]["seed_offset"] == 1
    # Batched, the tournament itself refuses the search seat.
    batched = D.tournament_argv(blobs, {}, pairs, 5, 2, out_dir=str(tmp_path / "b"),
                                extra=SEARCH_EXTRA, search=search, games_per_worker=8)
    with pytest.raises(SystemExit, match="unbatched path only"):
        T.main(batched)
    assert not (tmp_path / "b").exists()


@pytest.mark.parametrize("extra, needle", [
    (["--search", "S=4:16"], "NAME=default or NAME=k:n:delta"),
    (["--search", "S"], "--search wants NAME=VALUE"),
    (["--search", "o=default"], "a scripted bot does not search"),
    (["--search", "Z=default"], "not a checkpoint of this run"),
    (["--search", "idle=default", "--tournament-arg=--mask", "--tournament-arg=idle=m1"],
     "is in no pair"),
    (["--search", "S=default"], "plays under a mask"),
    (["--search", "S=default", "--tournament-arg=--mask", "--tournament-arg=C=m1"],
     "plays under a mask"),
    (["--search", "S=default", "--tournament-arg=--mask", "--tournament-arg=S=m1",
      "--games-per-worker", "32"], "unbatched path only"),
    (["--search", "S=default", "--tournament-arg=--mask", "--tournament-arg=S=m1",
      "--tournament-arg=--temperature", "--tournament-arg=S=0.5"], "temperature 1"),
    (["--search", "S=default", "--tournament-arg=--mask", "--tournament-arg=S=m1",
      "--tournament-arg=--player-mode", "--tournament-arg=S=argmax"], "sample mode"),
    (["--tournament-arg=--search", "--tournament-arg=S=default"], "not --tournament-arg"),
    (["--tournament-arg=--search=S=default"], "not --tournament-arg"),
])
def test_a_search_request_is_refused_before_anything_is_created(tmp_path, extra, needle):
    """Argument checks only: the no-network fixture fails the test if cmd_run reads the
    token, calls the API or runs git."""
    args = build_run_args(["--checkpoint", f"S={tmp_path / 'S.bin'}", "--checkpoint",
                           f"C={tmp_path / 'C.bin'}", "--checkpoint", f"idle={tmp_path / 'i.bin'}",
                           "--bot", "o=offense", "--pair", "S,C,2", "--pair", "S,o,2", *extra])
    with pytest.raises(D.RunnerError, match=needle):
        D.cmd_run(args)


def test_a_good_search_request_passes_the_search_checks(tmp_path):
    args = build_run_args(["--checkpoint", f"S={tmp_path / 'S.bin'}", "--checkpoint",
                           f"C={tmp_path / 'C.bin'}", "--pair", "S,C,2", "--search", "S=default",
                           "--tournament-arg=--mask", "--tournament-arg=S=m1"])
    with pytest.raises(D.RunnerError, match="checkpoint S: missing"):   # the next check
        D.cmd_run(args)
    # A searched game takes minutes: the silence allowed before a run is called dead.
    assert args.stale_seconds is None
    assert (D.STALE_SECONDS, D.STALE_SECONDS_SEARCH) == (900, 1800)
    assert build_run_args(["--stale-seconds", "600"]).stale_seconds == 600


SETTING = {"scope": ["turn", "after_declare"], "k": 4, "n": 16, "delta": 0.1,
           "max_rollout_steps": 200, "gamma": 0.999}
SEARCH_PAIRS = [("a", "b", 4)]


def searched_manifest():
    return {**good_manifest(), "tasks": 4, "pairs": [["a", "b", 4]], "games_per_worker": 1,
            "players": {"a": {"mode": "sample", "temperature": 1.0, "masks": ["m1"],
                              "search": dict(SETTING)},
                        "b": {"mode": "sample", "temperature": 1.0}},
            "search": {"players": ["a"], "reward_manifest": {"name": "r0", "sha256": "r" * 64},
                       "integrity_checks": ["one", "two"]}}


def searched_games():
    out = []
    for g in scheduled_games(SEARCH_PAIRS):
        side = 0 if g["leg"] == "A_home" else 1
        names = ("a", "b") if side == 0 else ("b", "a")
        settings, stats = [None, None], [None, None]
        settings[side] = dict(SETTING)
        stats[side] = {"error_rollouts": 0, "shadow_forwards": 500, "rollouts": 640}
        out.append(dict(g, home=names[0], away=names[1], search=settings, search_stats=stats,
                        integrity_checks=["one", "two"], reward_manifest_sha256="r" * 64))
    return out


def verify_searched(manifest, games, search):
    return D.verify_run(manifest, {"complete": True}, games, "c0ffee", {"a": "ha", "b": "hb"},
                        SEARCH_PAIRS, 7, search=search)


def test_verify_run_accepts_the_requested_search():
    request = {"a": D.parse_search("default")}
    assert verify_searched(searched_manifest(), searched_games(), request) == []
    assert D.search_problems(searched_manifest(), searched_games(), request) == []
    # A run without a search seat is verified as before, with or without the argument.
    assert D.search_problems(good_manifest_with_bot(), scheduled_games()) == []
    assert D.search_problems(good_manifest_with_bot(), scheduled_games(), {}) == []


@pytest.mark.parametrize("mutate, request_, needle", [
    (lambda m, g: None, {"a": "4:16:0.02"}, "manifest search settings"),
    (lambda m, g: None, {"a": "4:32:0.1"}, "manifest search settings"),
    (lambda m, g: None, {"a": "2:16:0.1"}, "manifest search settings"),
    (lambda m, g: None, {"a": "4:16:inf"}, "manifest search settings"),
    (lambda m, g: None, {}, "manifest search settings"),
    (lambda m, g: None, {"a": "default", "b": "default"}, "manifest search settings"),
    (lambda m, g: m["players"]["a"].pop("search"), {"a": "default"}, "manifest search settings"),
    (lambda m, g: m["players"]["b"].update(search=dict(SETTING)), {"a": "default"},
     "manifest search settings"),
    (lambda m, g: m.pop("search"), {"a": "default"}, "the manifest has no search entry"),
    (lambda m, g: m["search"].update(players=["a", "b"]), {"a": "default"}, "search players"),
    (lambda m, g: m["search"].update(reward_manifest={}), {"a": "default"},
     "names no reward manifest hash"),
    (lambda m, g: m["search"].update(integrity_checks=[]), {"a": "default"},
     "lists no integrity checks"),
    (lambda m, g: g[0].update(search=[None, None]), {"a": "default"},
     "search settings are not its players'"),
    (lambda m, g: g[0].pop("search"), {"a": "default"}, "search settings are not its players'"),
    (lambda m, g: g[0]["search"][0].update(n=32), {"a": "default"},
     "search settings are not its players'"),
    (lambda m, g: g[1].update(search=[dict(SETTING), dict(SETTING)]), {"a": "default"},
     "search settings are not its players'"),
    (lambda m, g: g[0].update(integrity_checks=["one"]), {"a": "default"},
     "integrity checks are not the manifest's"),
    (lambda m, g: g[0].update(reward_manifest_sha256="x" * 64), {"a": "default"},
     "reward manifest is not the manifest's"),
    (lambda m, g: g[0]["search_stats"][0].update(error_rollouts=2), {"a": "default"},
     "reports a failed rollout"),
    (lambda m, g: g[0]["search_stats"][0].update(shadow_forwards=499), {"a": "default"},
     "missing opponent-view forward"),
    (lambda m, g: g[0].update(search_stats=[None, None]), {"a": "default"},
     "search statistics do not match"),
])
def test_verify_run_flags_each_search_mismatch(mutate, request_, needle):
    manifest, games = searched_manifest(), searched_games()
    mutate(manifest, games)
    request = {name: D.parse_search(text) for name, text in request_.items()}
    problems = verify_searched(manifest, games, request)
    assert any(needle in p for p in problems), problems


def test_verify_run_names_the_first_few_bad_games_and_counts_the_rest():
    manifest = {**searched_manifest(), "tasks": 16, "pairs": [["a", "b", 16]]}
    games = []
    for i, g in enumerate(searched_games() * 4):
        games.append(dict(g, game_index=i // 2, engine_seed=7 + i // 2, integrity_checks=[]))
    problems = D.search_problems(manifest, games, {"a": D.parse_search("default")})
    assert len(problems) == 6 and problems[-1] == "... and 11 more games with search problems"


def test_verify_run_flags_search_fields_nobody_asked_for():
    manifest, games = good_manifest_with_bot(), scheduled_games()
    manifest["search"] = {"players": []}
    assert any("no player searches" in p for p in D.search_problems(manifest, games))
    games[0]["search"] = [dict(SETTING), None]
    assert any("a game carries a search setting" in p
               for p in D.search_problems(good_manifest_with_bot(), games))


def searching_shards():
    """s1 holds the searched pair, s2 a pair without a search seat."""
    entry = {"players": ["a"], "reward_manifest": {"sha256": "r" * 64},
             "integrity_checks": ["one", "two"]}
    spec = {"mode": "sample", "temperature": 1.0, "masks": ["m1"], "search": dict(SETTING)}
    s1, s2 = two_shards()
    s1["manifest"].update(search=entry)
    for s in (s1, s2):
        s["manifest"]["players"]["a"] = json.loads(json.dumps(spec))    # no shared setting
    return s1, s2


def test_merge_carries_the_search_entry_of_the_shards_that_have_one():
    s1, s2 = searching_shards()
    manifest, _, games = D.merge_shards([s1, s2])
    assert manifest["search"] == {"players": ["a"], "reward_manifest": {"sha256": "r" * 64},
                                  "integrity_checks": ["one", "two"]}
    assert manifest["players"]["a"]["search"] == SETTING and len(games) == 4
    assert "search" not in D.merge_shards(list(two_shards()))[0]       # as before without one
    # Two shards that both search: one entry, the players joined.
    s1, s2 = searching_shards()
    s2["manifest"].update(search=dict(s1["manifest"]["search"], players=["c"]))
    s2["manifest"]["players"]["c"] = json.loads(json.dumps(s2["manifest"]["players"]["a"]))
    assert D.merge_shards([s1, s2])[0]["search"]["players"] == ["a", "c"]


@pytest.mark.parametrize("mutate, needle", [
    (lambda a, b: b["manifest"].update(search={
        "players": ["a"], "reward_manifest": {"sha256": "x" * 64},
        "integrity_checks": ["one", "two"]}), "the search entry"),
    (lambda a, b: b["manifest"].update(search={
        "players": ["a"], "reward_manifest": {"sha256": "r" * 64},
        "integrity_checks": ["one"]}), "the search entry"),
    (lambda a, b: a["manifest"].pop("search"), "players with a search setting ['a']"),
    (lambda a, b: a["manifest"]["search"].update(players=["a", "zz"]),
     "players with a search setting ['a']"),
    (lambda a, b: b["manifest"]["players"]["a"]["search"].update(n=32), "players[a]"),
    (lambda a, b: b["manifest"]["players"]["a"].pop("search"), "players[a]"),
    (lambda a, b: b["manifest"].update(games_per_worker=32), "games_per_worker"),
])
def test_merge_refuses_shards_whose_search_differs(mutate, needle):
    s1, s2 = searching_shards()
    mutate(s1, s2)
    with pytest.raises(D.RunnerError) as err:
        D.merge_shards([s1, s2])
    assert needle in str(err.value), str(err.value)
