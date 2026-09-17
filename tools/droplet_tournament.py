#!/usr/bin/env python3
"""Run a play-harness tournament on a throwaway DigitalOcean droplet.

The droplet is created, used for one tournament and destroyed. Teardown runs on
every exit path (success, failure, Ctrl-C, SIGTERM) unless --keep is given.

  tools/droplet_tournament.py run --name c35-gate-20260917 \\
      --checkpoint chain35=.play-artifacts/checkpoints/chain35/0000002999975936.bin \\
      --checkpoint chain30=... --bot offense=offense \\
      --pair chain35,chain30,3200 --pair chain35,offense,3200 --seed0 20700000
  tools/droplet_tournament.py status            # leak check: every tagged droplet
  tools/droplet_tournament.py destroy --name c35-gate-20260917
  tools/droplet_tournament.py compare --run-dir NEW/main --ref-dir OLD/main
  tools/droplet_tournament.py merge --out ALL/main --shard S1/main --shard S2/main

What `run` does: price check, disposable ssh key, one tagged droplet, CPU-only
torch, `git archive` of a pinned commit plus only the named checkpoints, shim
build on the droplet, tournament and stats under nohup, polling, copy back,
sha256 and manifest verification, teardown, cost. A whole run lives on one
machine because the manifest pins the compiled shim and a resume refuses another.

The DigitalOcean token is read at run time from DIGITALOCEAN_TOKEN or the env
file; it is never written to disk, logs or the droplet. Stdlib only.
"""
from __future__ import annotations

import argparse
import calendar
import fcntl
import hashlib
import json
import math
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.digitalocean.com/v2"
TAG = "bb-harness-tournament"
NAME_PREFIX = "bb-harness-"
DEFAULT_ENV_FILE = "~/code/killteam-3d/.env"
TOKEN_VAR = "DIGITALOCEAN_TOKEN"
# The largest non-GPU size this account could create on 2026-09-17 (no CPU-optimized
# size above c-4 was offered). Pass --size c-16 / c-32 once the account allows it.
DEFAULT_SIZE = "s-8vcpu-16gb-amd"
DEFAULT_REGION = "sfo3"
IMAGE = "ubuntu-24-04-x64"          # python 3.12.3, the Mac harness venv's version
TORCH_VERSION = "2.14.0"            # the Mac harness venv's torch; installed CPU-only
NUMPY_VERSION = "2.5.3"
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
REMOTE_ROOT = "/srv/bb"
REMOTE_SRC = REMOTE_ROOT + "/src"
REMOTE_RUN = REMOTE_ROOT + "/run"
REMOTE_OUT = REMOTE_RUN + "/main"
REMOTE_PY = REMOTE_ROOT + "/venv/bin/python"
SYNC_PATHS = ("play_harness", "engine", "puffer", "training/convert_checkpoint.py")
RESULT_FILES = ("games.jsonl", "manifest.json", "COMPLETE.json", "report.json")
EXTRA_FILES = ("report.txt", "machine.json", "SHA256SUMS")
LOG_FILES = ("job.log", "tournament.log", "report.txt", "setup.log")
HARD_COUNTERS = ("illegal", "projection_collision", "error_episodes",
                 "rejected_submissions", "precheck_collisions")
STATE_ROOT = "~/.cache/bb-droplet-tournament"
MIN_CHARGE = 0.01
MAX_HOURLY_DEFAULT = 1.0
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
PLAYER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+){1,3}$")
PROVENANCE_FILES = ("machine.json",)
RETRY_STATUSES = (429, 500, 502, 503, 504)


class RunnerError(RuntimeError):
    pass


class Interrupted(BaseException):
    """Raised from a signal handler so `finally` teardown runs."""


# ---- pure logic ---------------------------------------------------------------
def validate_name(name):
    if not NAME_RE.match(name or ""):
        raise RunnerError(f"--name must be lowercase letters, digits and hyphens "
                          f"(1-40 chars), got {name!r}")
    return name


def droplet_name(name):
    return NAME_PREFIX + validate_name(name)


def parse_token(text):
    """DIGITALOCEAN_TOKEN from dotenv text, quotes stripped; None when absent."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if line.startswith(TOKEN_VAR + "="):
            value = line.split("=", 1)[1].strip().strip("'\"")
            return value or None
    return None


def read_token(environ=None, env_file=DEFAULT_ENV_FILE):
    environ = os.environ if environ is None else environ
    if environ.get(TOKEN_VAR):
        return environ[TOKEN_VAR]
    path = os.path.expanduser(env_file)
    if os.path.exists(path):
        with open(path) as f:
            token = parse_token(f.read())
        if token:
            return token
    raise RunnerError(f"no {TOKEN_VAR} in the environment or {env_file}")


def parse_assignment(item, what):
    name, sep, value = item.partition("=")
    if not sep or not name or not value:
        raise RunnerError(f"--{what} wants NAME=VALUE, got {item!r}")
    if not PLAYER_RE.match(name):
        raise RunnerError(f"--{what} name {name!r} must match {PLAYER_RE.pattern}")
    return name, value


def parse_pair(text):
    parts = text.split(",")
    if len(parts) not in (2, 3):
        raise RunnerError(f"--pair wants A,B or A,B,N, got {text!r}")
    n = None
    if len(parts) == 3:
        try:
            n = int(parts[2])
        except ValueError:
            raise RunnerError(f"--pair game count must be an integer, got {text!r}")
    return parts[0], parts[1], n


def plan_pairs(pairs, players, games_per_pair):
    """[(a, b, n)] with every n resolved; the same rules tournament.schedule enforces."""
    if not pairs:
        raise RunnerError("name every pair with --pair A,B[,N]")
    out, seen = [], set()
    for a, b, n in pairs:
        n = games_per_pair if n is None else n
        if n is None or n <= 0 or n % 2:
            raise RunnerError(f"games for pair {a},{b} must be a positive even number")
        if a == b or a not in players or b not in players:
            raise RunnerError(f"pair {a},{b} needs two distinct known players")
        if frozenset((a, b)) in seen:
            raise RunnerError(f"duplicate pair {a},{b}")
        seen.add(frozenset((a, b)))
        out.append((a, b, int(n)))
    return out


def expected_tasks(pairs):
    return sum(n for _, _, n in pairs)


def remote_checkpoint_path(name, local_path):
    return f"{REMOTE_ROOT}/checkpoints/{name}/{os.path.basename(local_path)}"


def tournament_argv(checkpoints, bots, pairs, seed0, workers, out_dir=REMOTE_OUT,
                    extra=(), games_per_worker=1):
    """argv after `python -m play_harness.tournament`, with droplet-side blob paths.

    games_per_worker 1 adds nothing, so an unbatched run's command line is unchanged."""
    argv = []
    for name, local in checkpoints.items():
        argv += ["--checkpoint", f"{name}={remote_checkpoint_path(name, local)}"]
    for name, kind in bots.items():
        argv += ["--bot", f"{name}={kind}"]
    for a, b, n in pairs:
        argv += ["--pair", f"{a},{b},{n}"]
    argv += ["--seed0", str(int(seed0)), "--workers", str(int(workers)),
             "--out-dir", out_dir]
    if int(games_per_worker) != 1:
        argv += ["--games-per-worker", str(int(games_per_worker))]
    return argv + list(extra)


def setup_script(torch=TORCH_VERSION, numpy=NUMPY_VERSION):
    """First-boot install: compiler, venv, CPU-only torch. Idempotent."""
    for what, version in (("torch", torch), ("numpy", numpy)):
        if not VERSION_RE.match(str(version)):            # the text lands in a shell script
            raise RunnerError(f"--{what} must be a plain version like 2.14.0, got {version!r}")
    return f"""#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
cloud-init status --wait >/dev/null 2>&1 || true
APT="apt-get -o DPkg::Lock::Timeout=600 -y"
$APT update
$APT install --no-install-recommends python3-venv gcc libc6-dev
mkdir -p {REMOTE_ROOT} {REMOTE_SRC} {REMOTE_RUN}
python3 -m venv {REMOTE_ROOT}/venv
{REMOTE_ROOT}/venv/bin/pip install --no-cache-dir --quiet numpy=={numpy}
{REMOTE_ROOT}/venv/bin/pip install --no-cache-dir --quiet --index-url {TORCH_INDEX} torch=={torch}
{REMOTE_PY} -c 'import torch, numpy; assert torch.__version__.split("+")[0] == "{torch}", torch.__version__; assert not torch.cuda.is_available(); print("torch", torch.__version__, "numpy", numpy.__version__)'
echo SETUP_OK
"""


def build_script(commit):
    """Build the shim from the synced sources and record the machine."""
    return f"""#!/bin/bash
set -euo pipefail
cd {REMOTE_SRC}
test "$(cat SOURCE_COMMIT)" = {shlex.quote(commit)}
bash play_harness/native/build.sh
OMP_NUM_THREADS=1 {REMOTE_PY} - <<'PY'
import hashlib, json, os, platform, subprocess, sys
import numpy, torch
from play_harness import engine as E
lib = E.load_library()
sha = hashlib.sha256(open(E.DEFAULT_LIB, "rb").read()).hexdigest()
cpu = [l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")]
info = {{"host": platform.node(), "cpu_model": cpu[0] if cpu else None, "nproc": os.cpu_count(),
        "kernel": platform.release(), "python": sys.version.split()[0],
        "torch": torch.__version__, "numpy": numpy.__version__,
        "cc": subprocess.run(["cc", "--version"], capture_output=True, text=True).stdout.splitlines()[0],
        "library_sha256": sha, "abi": lib.bbp_abi_version(), "obs_size": lib.bbp_obs_size(),
        "source_commit": open("SOURCE_COMMIT").read().strip()}}
json.dump(info, open("{REMOTE_RUN}/machine.json", "w"), indent=1)
print(json.dumps(info))
PY
echo BUILD_OK
"""


def job_script(argv, workers, stats_reps=None):
    """The detached job: tournament, stats, checksums, then an atomic EXIT file."""
    cmd = " ".join(shlex.quote(a) for a in argv)
    reps = f" --reps {int(stats_reps)}" if stats_reps is not None else ""
    names = " ".join(RESULT_FILES)
    return f"""#!/bin/bash
set -uo pipefail
cd {REMOTE_SRC}
export OMP_NUM_THREADS=1 BBPLAY_MAX_WORKERS={int(workers)}
finish() {{ echo "$1" > {REMOTE_RUN}/EXIT.tmp && mv {REMOTE_RUN}/EXIT.tmp {REMOTE_RUN}/EXIT; exit "$1"; }}
echo tournament > {REMOTE_RUN}/STAGE
date -u +%s > {REMOTE_RUN}/STARTED
head -1 /proc/stat > {REMOTE_RUN}/cpu-before
{REMOTE_PY} -m play_harness.tournament {cmd} > {REMOTE_RUN}/tournament.log 2>&1 || finish $?
head -1 /proc/stat > {REMOTE_RUN}/cpu-after
test -f {REMOTE_OUT}/COMPLETE.json || finish 3
echo stats > {REMOTE_RUN}/STAGE
date -u +%s > {REMOTE_RUN}/STATS_STARTED
{REMOTE_PY} -m play_harness.tournament_stats --run-dir {REMOTE_OUT} --json {REMOTE_OUT}/report.json{reps} > {REMOTE_RUN}/report.txt 2>&1 || finish $?
cp {REMOTE_RUN}/report.txt {REMOTE_RUN}/machine.json {REMOTE_OUT}/
(cd {REMOTE_OUT} && sha256sum {names} report.txt machine.json > SHA256SUMS) || finish 4
date -u +%s > {REMOTE_RUN}/STATS_DONE
echo done > {REMOTE_RUN}/STAGE
finish 0
"""


def droplet_body(name, region, size, key_fingerprint):
    return {"name": droplet_name(name), "region": region, "size": size, "image": IMAGE,
            "ssh_keys": [key_fingerprint], "tags": [TAG], "monitoring": False,
            "ipv6": False, "backups": False}


def pick_size(sizes, slug, region, max_hourly=MAX_HOURLY_DEFAULT):
    """The size record for slug, refusing one the account cannot create or afford."""
    found = [s for s in sizes if s.get("slug") == slug]
    if not found:
        raise RunnerError(f"size {slug} is not offered to this account")
    size = found[0]
    if not size.get("available", True):
        raise RunnerError(f"size {slug} is not available")
    if region not in size.get("regions", []):
        raise RunnerError(f"size {slug} is not in {region} "
                          f"(regions: {','.join(size.get('regions', []))})")
    if float(size["price_hourly"]) > max_hourly:
        raise RunnerError(f"size {slug} costs ${size['price_hourly']}/h, above the "
                          f"--max-hourly cap of ${max_hourly}")
    return size


def cost(seconds, price_hourly):
    """Prorated droplet cost in dollars, never below DigitalOcean's minimum charge."""
    if seconds < 0 or price_hourly < 0:
        raise ValueError("seconds and price must be non-negative")
    return max(MIN_CHARGE, seconds / 3600.0 * price_hourly)


def estimate(games, games_per_second, price_hourly, overhead_seconds=0.0):
    """Wall time and cost of a tournament of `games` at a measured rate."""
    if games_per_second <= 0:
        raise ValueError("games_per_second must be positive")
    play = games / games_per_second
    total = play + overhead_seconds
    return {"games": int(games), "games_per_second": games_per_second,
            "play_seconds": play, "total_seconds": total,
            "total_minutes": total / 60.0, "cost": cost(total, price_hourly)}


def cpu_steal_fraction(before, after):
    """Steal share of all CPU time between two `head -1 /proc/stat` lines."""
    a = [int(v) for v in before.split()[1:]]
    b = [int(v) for v in after.split()[1:]]
    if len(a) < 8 or len(b) < 8:
        raise ValueError("expected a full 'cpu' line from /proc/stat")
    delta = [y - x for x, y in zip(a[:8], b[:8])]
    total = sum(delta)
    return delta[7] / total if total > 0 else 0.0


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_sha256sums(text):
    out = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([0-9a-f]{64}) [ *](.+)$", line)
        if not m:
            raise RunnerError(f"malformed SHA256SUMS line: {line!r}")
        out[m.group(2)] = m.group(1)
    return out


def verify_files(directory, sums, required=RESULT_FILES + PROVENANCE_FILES):
    """Problems with the copied files: missing from the list, absent, or wrong hash."""
    problems = [f"{name}: not listed in SHA256SUMS" for name in required if name not in sums]
    for name, want in sums.items():
        path = os.path.join(directory, name)
        if not os.path.exists(path):
            problems.append(f"{name}: not copied")
            continue
        got = sha256_file(path)
        if got != want:
            problems.append(f"{name}: sha256 {got} != droplet {want}")
    return problems


def schedule_problems(games, pairs, seed0):
    """Problems unless the games are exactly the schedule: every pair's indices
    0..n/2-1, both legs, once each, on engine seed seed0 + index."""
    want = {((a, b), i, leg) for a, b, n in pairs for i in range(int(n) // 2)
            for leg in ("A_home", "B_home")}
    got = [_key(g) for g in games]
    problems = []
    if len(set(got)) != len(got):
        problems.append(f"{len(got) - len(set(got))} duplicate (pair, game_index, leg) records")
    missing, extra = want - set(got), set(got) - want
    if missing:
        problems.append(f"{len(missing)} scheduled games missing, e.g. {sorted(missing)[0]}")
    if extra:
        problems.append(f"{len(extra)} games outside the schedule, e.g. {sorted(extra)[0]}")
    bad_seed = [g for g in games if g.get("engine_seed") != int(seed0) + int(g["game_index"])]
    if bad_seed:
        problems.append(f"{len(bad_seed)} games on the wrong engine seed, e.g. "
                        f"{_key(bad_seed[0])} on {bad_seed[0].get('engine_seed')}")
    return problems


def manifest_games_per_worker(manifest):
    """A manifest written before batching existed was played one game per worker."""
    value = manifest.get("games_per_worker")
    return 1 if value is None else value


def verify_run(manifest, complete, games, commit, checkpoint_sha, pairs, seed0, bots=None,
               games_per_worker=1):
    """Problems that mean the copied run is not the tournament that was asked for."""
    problems = []
    if manifest_games_per_worker(manifest) != int(games_per_worker):
        problems.append(f"manifest games_per_worker {manifest.get('games_per_worker')} != "
                        f"requested {games_per_worker}")
    tasks = expected_tasks(pairs)
    game_lines = len(games)
    got_bots = {n: (b or {}).get("kind") for n, b in (manifest.get("bots") or {}).items()}
    if got_bots != dict(bots or {}):
        problems.append(f"manifest bots {got_bots} != requested {dict(bots or {})}")
    if manifest.get("harness_git_head") != commit:
        problems.append(f"manifest commit {manifest.get('harness_git_head')} != pinned {commit}")
    got_sha = {n: c.get("sha256") for n, c in (manifest.get("checkpoints") or {}).items()}
    if got_sha != dict(checkpoint_sha):
        problems.append(f"manifest checkpoint hashes {got_sha} != local {dict(checkpoint_sha)}")
    if manifest.get("seed0") != int(seed0):
        problems.append(f"manifest seed0 {manifest.get('seed0')} != {seed0}")
    want_pairs = sorted([a, b, n] for a, b, n in pairs)
    if sorted(manifest.get("pairs") or []) != want_pairs:
        problems.append(f"manifest pairs {manifest.get('pairs')} != {want_pairs}")
    if manifest.get("tasks") != tasks:
        problems.append(f"manifest tasks {manifest.get('tasks')} != {tasks}")
    if not complete.get("complete"):
        problems.append(f"COMPLETE.json does not say complete: {complete}")
    if game_lines != tasks:
        problems.append(f"games.jsonl has {game_lines} games, expected {tasks}")
    return problems + schedule_problems(games, pairs, seed0)


def integrity_totals(games):
    totals = {k: 0 for k in HARD_COUNTERS}
    for g in games:
        for k in HARD_COUNTERS:
            totals[k] += int((g.get("integrity") or {}).get(k, 1))
    totals["unnatural"] = sum(not g.get("natural") for g in games)
    totals["forward_mismatch"] = sum(g.get("forwards") != [g.get("c_steps")] * 2 for g in games)
    return totals


def _key(g):
    return (tuple(g["pair"]), int(g["game_index"]), g["leg"])


def _summary(games):
    n = len(games)
    if not n:
        return {"games": 0}
    w = sum(g["result_a"] == "W" for g in games)
    d = sum(g["result_a"] == "D" for g in games)
    scores = [1.0 if g["result_a"] == "W" else 0.5 if g["result_a"] == "D" else 0.0
              for g in games]
    mean = sum(scores) / n
    var = sum((s - mean) ** 2 for s in scores) / (n - 1) if n > 1 else 0.0
    return {"games": n, "W": w, "D": d, "L": n - w - d, "score_rate": mean,
            "score_var": var,
            "a_td_per_game": sum(g["a_td"] for g in games) / n,
            "b_td_per_game": sum(g["b_td"] for g in games) / n,
            "c_steps_per_game": sum(g["c_steps"] for g in games) / n}


def _z(x, y):
    """Welch z of the score-rate difference between two summaries. Descriptive only:
    it treats games as independent and ignores shared seeds and paired legs."""
    if not x.get("games") or not y.get("games"):
        return None
    se = math.sqrt(x["score_var"] / x["games"] + y["score_var"] / y["games"])
    diff = x["score_rate"] - y["score_rate"]
    if se > 0:
        return diff / se
    return 0.0 if diff == 0 else math.copysign(math.inf, diff)


def compare_runs(games, ref_games):
    """Game-by-game and distribution agreement of a run against a reference run.

    Games are matched on (pair, game_index, leg). `exact` counts games whose
    final_digest AND action_trail_sha256 both match. The distribution block sets
    this run beside the reference's same games and the reference's full pairs.
    The action trail is the sharp test: a game that took other actions can still
    end on the same final_digest. max_logprob_sum_drift_same_actions is the float
    drift between machines over games that chose identical actions.
    """
    ref = {_key(g): g for g in ref_games}
    matched = [(g, ref[_key(g)]) for g in games if _key(g) in ref]
    counts = {"games": len(games), "matched_keys": len(matched),
              "missing_in_reference": len(games) - len(matched),
              "seeds_equal": 0, "rosters_equal": 0, "final_digest_equal": 0,
              "action_trail_equal": 0, "exact": 0, "score_equal": 0,
              "logprob_sum_equal": 0}
    drift = 0.0
    for g, r in matched:
        counts["seeds_equal"] += (g["engine_seed"] == r["engine_seed"]
                                  and g["sampling_seeds"] == r["sampling_seeds"])
        counts["rosters_equal"] += g["team_ids"] == r["team_ids"]
        dig = g["final_digest"] == r["final_digest"]
        trail = g["action_trail_sha256"] == r["action_trail_sha256"]
        counts["final_digest_equal"] += dig
        counts["action_trail_equal"] += trail
        counts["exact"] += dig and trail
        counts["score_equal"] += g["score"] == r["score"]
        counts["logprob_sum_equal"] += g.get("logprob_sum") == r.get("logprob_sum")
        if trail and g.get("logprob_sum") and r.get("logprob_sum"):
            drift = max(drift, *(abs(x - y) for x, y in zip(g["logprob_sum"], r["logprob_sum"])))
    pairs = {}
    for label in sorted({tuple(g["pair"]) for g in games}):
        mine = _summary([g for g in games if tuple(g["pair"]) == label])
        same = _summary([r for g, r in matched if tuple(g["pair"]) == label])
        full = _summary([r for r in ref_games if tuple(r["pair"]) == label])
        pairs[",".join(label)] = {"run": mine, "reference_same_games": same,
                                  "reference_full": full, "z_vs_reference_full": _z(mine, full)}
    labels = {tuple(g["pair"]) for g in games}
    pooled_run = _summary(games)
    pooled_full = _summary([r for r in ref_games if tuple(r["pair"]) in labels])
    verdict = ("every game took the same actions to the same final state"
               if matched and counts["exact"] == len(games) else
               f"{len(games) - counts['exact']} of {len(games)} games differ from the reference")
    counts["diverged_games"] = len(matched) - counts["action_trail_equal"]
    counts["max_logprob_sum_drift_same_actions"] = drift
    return {"verdict": verdict, "counts": counts, "pairs": pairs,
            "pooled": {"run": pooled_run,
                       "reference_same_games": _summary([r for _, r in matched]),
                       "reference_full": pooled_full,
                       "z_vs_reference_full": _z(pooled_run, pooled_full)},
            "integrity": integrity_totals(games)}


MERGE_EQUAL_KEYS = ("schema", "seed0", "mode", "kernel", "max_decisions", "omp_num_threads",
                    "rosters", "legs", "sampling_seed", "harness_git_head", "torch", "python")


def merge_shards(shards):
    """One manifest and game list from shards that split a tournament by pair.

    shards: [{"name", "manifest", "complete", "games", "machine"}]. A game depends
    only on (pair, engine seed, leg), never on which other pairs share its run, and
    droplets of one image build a byte-identical shim, so shards may run on
    different droplets. Refused unless
    the shards share the commit, seed block, settings, torch and compiled shim,
    give shared players the same checkpoint and spec, and cover disjoint pairs.
    Returns (manifest, complete, games); raises RunnerError listing every problem.
    """
    if len(shards) < 2:
        raise RunnerError("merge needs at least two shards")
    problems = []
    first = shards[0]
    checkpoints, bots, players, pairs, games, seen_pairs = {}, {}, {}, [], [], {}
    for shard in shards:
        name, m = shard["name"], shard["manifest"]
        for key in MERGE_EQUAL_KEYS:
            if m.get(key) != first["manifest"].get(key):
                problems.append(f"{name}: {key} {m.get(key)!r} != {first['name']}'s "
                                f"{first['manifest'].get(key)!r}")
        if manifest_games_per_worker(m) != manifest_games_per_worker(first["manifest"]):
            problems.append(f"{name}: games_per_worker {manifest_games_per_worker(m)} != "
                            f"{first['name']}'s {manifest_games_per_worker(first['manifest'])} "
                            f"(batching changes float rounding, so the shards are not one sampler)")
        lib = (shard.get("machine") or {}).get("library_sha256")
        if not lib or lib != (first.get("machine") or {}).get("library_sha256"):
            problems.append(f"{name}: compiled shim {lib} differs from {first['name']}'s")
        if m.get("bot_library_sha256") not in (None, lib):
            problems.append(f"{name}: manifest bot library {m.get('bot_library_sha256')} "
                            f"is not the recorded shim {lib}")
        if not (shard.get("complete") or {}).get("complete"):
            problems.append(f"{name}: not complete")
        if len(shard["games"]) != m.get("tasks"):
            problems.append(f"{name}: {len(shard['games'])} games, manifest says {m.get('tasks')}")
        bad = {k: v for k, v in integrity_totals(shard["games"]).items() if v}
        if bad:
            problems.append(f"{name}: nonzero integrity counters {bad}")
        for group, merged, ident in (("checkpoints", checkpoints, lambda v: v.get("sha256")),
                                     ("bots", bots, lambda v: v), ("players", players, lambda v: v)):
            for player, value in (m.get(group) or {}).items():
                if player in merged and ident(merged[player]) != ident(value):
                    problems.append(f"{name}: {group}[{player}] differs from an earlier shard")
                merged.setdefault(player, value)
        for a, b, n in m.get("pairs") or []:
            key = frozenset((a, b))
            if key in seen_pairs:
                problems.append(f"{name}: pair {a},{b} is also in {seen_pairs[key]}")
            seen_pairs[key] = name
            pairs.append([a, b, n])
        problems += [f"{name}: {p}" for p in schedule_problems(
            shard["games"], [tuple(p) for p in m.get("pairs") or []], m.get("seed0", 0))]
        games += shard["games"]
    if len({_key(g) for g in games}) != len(games):
        problems.append("duplicate (pair, game_index, leg) across shards")
    if problems:
        raise RunnerError("shards do not merge:\n  " + "\n  ".join(problems))
    lib = first["machine"]["library_sha256"]
    manifest = {key: first["manifest"].get(key) for key in MERGE_EQUAL_KEYS}
    manifest.update({
        "checkpoints": checkpoints, "bots": bots, "players": players, "pairs": pairs,
        "bot_library_sha256": lib if bots else None, "library_sha256": lib,
        "games_per_pair": None, "tasks": len(games), "host": "merged",
        "games_per_worker": manifest_games_per_worker(first["manifest"]),
        "workers": [s["manifest"].get("workers") for s in shards],
        "merged_from": [{"name": s["name"], "host": s["manifest"].get("host"),
                         "tasks": s["manifest"].get("tasks"),
                         "pairs": s["manifest"].get("pairs"),
                         "cpu_model": (s.get("machine") or {}).get("cpu_model"),
                         "games_sha256": s.get("games_sha256"),
                         "wall_seconds": (s.get("complete") or {}).get("wall_seconds"),
                         "games_per_second_wall": (s.get("complete") or {}).get("games_per_second_wall")}
                        for s in shards]})
    walls = [(s.get("complete") or {}).get("wall_seconds") or 0.0 for s in shards]
    rates = [(s.get("complete") or {}).get("games_per_second_wall") or 0.0 for s in shards]
    complete = {"played": len(games), "complete": True, "shards": len(shards),
                "wall_seconds": max(walls), "shard_games_per_second_wall_sum": round(sum(rates), 3)}
    return manifest, complete, games


def limit_refusal(existing, limit):
    """A blocker message when the account has no free droplet slot, else None."""
    if existing >= limit:
        return (f"BLOCKER: the account already runs {existing} of its {limit} droplets. "
                "Nothing was created. Do not delete another project's droplet to make room; "
                "wait for a slot or ask the owner.")
    return None


def compare_row(label, row):
    run, same, full = row["run"], row["reference_same_games"], row["reference_full"]
    text = (f"{label:24s} run W/D/L {run['W']}/{run['D']}/{run['L']} score "
            f"{run['score_rate']:.3f} TD {run['a_td_per_game']:.2f}-{run['b_td_per_game']:.2f}")
    if not full.get("games"):
        return text + " | pair absent from the reference"
    z = row["z_vs_reference_full"]
    return (text + f" | same games in ref {same.get('W')}/{same.get('D')}/{same.get('L')} | "
            f"full ref score {full['score_rate']:.3f} TD {full['a_td_per_game']:.2f}-"
            f"{full['b_td_per_game']:.2f} (n={full['games']}) z={z:+.2f}")


def adoptable(droplets, name, attempted_at, slack=120):
    """Droplets an ambiguous create of `name` must have made: our tag, our exact
    name, created no earlier than the attempt. Names are unique per locked run."""
    out = []
    for d in filter_tagged(droplets):
        created = calendar.timegm(time.strptime(d["created_at"], "%Y-%m-%dT%H:%M:%SZ"))
        if d.get("name") == droplet_name(name) and created >= int(attempted_at) - slack:
            out.append(d)
    return out


def filter_tagged(droplets, tag=TAG):
    return [d for d in droplets if tag in (d.get("tags") or [])]


def destroy_refusal(droplet, recorded_id=None, name=None):
    """Why this droplet must not be destroyed, or None when every guard passes.

    A droplet is ours only if it carries the tag and the name prefix; with state
    it must also be the recorded id under the recorded name.
    """
    if TAG not in (droplet.get("tags") or []):
        return f"droplet {droplet.get('id')} lacks the {TAG} tag"
    if not str(droplet.get("name", "")).startswith(NAME_PREFIX):
        return f"droplet {droplet.get('id')} is named {droplet.get('name')!r}, not {NAME_PREFIX}*"
    if recorded_id is not None and int(droplet.get("id", -1)) != int(recorded_id):
        return f"droplet {droplet.get('id')} is not the recorded id {recorded_id}"
    if name is not None and droplet.get("name") != droplet_name(name):
        return f"droplet {droplet.get('id')} is named {droplet.get('name')!r}, not {droplet_name(name)}"
    return None


def describe_droplet(d, now=None):
    now = time.time() if now is None else now
    created = calendar.timegm(time.strptime(d["created_at"], "%Y-%m-%dT%H:%M:%SZ"))
    age = max(0.0, now - created)
    price = float((d.get("size") or {}).get("price_hourly") or 0.0)
    return (f"{d['id']}  {d['name']}  {d.get('size_slug')}  {(d.get('region') or {}).get('slug')}  "
            f"{d.get('status')}  created {d['created_at']}  age {age / 60:.0f} min  "
            f"accrued about ${cost(age, price):.2f}")


# ---- DigitalOcean API -----------------------------------------------------------
class Api:
    """retries: extra attempts after a network error, for GET and DELETE only. A POST
    is never repeated, because a create that timed out may still have happened."""

    def __init__(self, token, base=API, timeout=30, retries=5, retry_sleep=5.0):
        self._token, self.base, self.timeout = token, base, timeout
        self.retries, self.retry_sleep = retries, retry_sleep

    def call(self, method, path, body=None):
        """(HTTP status, decoded body). Never raises on an HTTP error status."""
        data = json.dumps(body).encode() if body is not None else None
        attempts = 1 + (self.retries if method in ("GET", "DELETE") else 0)
        for attempt in range(1, attempts + 1):
            req = urllib.request.Request(self.base + path, data=data, method=method, headers={
                "Authorization": "Bearer " + self._token, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    status, raw = resp.status, resp.read()
                break
            except urllib.error.HTTPError as exc:
                status, raw = exc.code, exc.read()
                if status not in RETRY_STATUSES or attempt == attempts:
                    break
                time.sleep(self.retry_sleep)
            except OSError as exc:                         # URLError, timeouts, resets
                if attempt == attempts:
                    raise RunnerError(f"{method} {path}: network error after {attempt} "
                                      f"attempt(s): {type(exc).__name__}")
                time.sleep(self.retry_sleep)
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            payload = {"message": raw[:200].decode("utf-8", "replace")}
        return status, payload

    def get(self, path):
        status, payload = self.call("GET", path)
        if status != 200:
            raise RunnerError(f"GET {path}: HTTP {status} {payload.get('message', '')}")
        return payload

    def tagged_droplets(self):
        return filter_tagged(self.get(f"/droplets?tag_name={TAG}&per_page=200")["droplets"])


# ---- ssh ------------------------------------------------------------------------
class Remote:
    def __init__(self, state_dir, ip):
        self.ip = ip
        self.opts = ["-i", os.path.join(state_dir, "key"),
                     "-o", "StrictHostKeyChecking=accept-new",
                     "-o", "UserKnownHostsFile=" + os.path.join(state_dir, "known_hosts"),
                     "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
                     "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=8",
                     "-o", "LogLevel=ERROR"]

    def run(self, command, check=True, timeout=600, stdin_text=None):
        """Every remote command has a timeout, so a hung ssh cannot bill forever."""
        try:
            proc = subprocess.run(["ssh", *self.opts, f"root@{self.ip}", command],
                                  input=stdin_text,
                                  stdin=None if stdin_text is not None else subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            if not check:
                raise
            raise RunnerError(f"remote command timed out after {timeout} s: {command[:80]}")
        if check and proc.returncode != 0:
            raise RunnerError(f"remote command failed ({proc.returncode}): {command[:80]}\n"
                              f"{proc.stdout[-2000:]}{proc.stderr[-2000:]}")
        return proc

    def script(self, text, log_name, timeout):
        """Run a bash script from stdin, keeping its output in a droplet-side log."""
        return self.run(f"mkdir -p {REMOTE_RUN} && bash -s 2>&1 | tee {REMOTE_RUN}/{log_name}; "
                        f"exit ${{PIPESTATUS[0]}}", stdin_text=text, timeout=timeout)

    def put(self, local, remote, timeout=1800):
        try:
            proc = subprocess.run(["scp", "-q", *self.opts, local, f"root@{self.ip}:{remote}"],
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RunnerError(f"scp timed out after {timeout} s: {remote}")
        if proc.returncode != 0:
            raise RunnerError(f"scp to droplet failed: {local}\n{proc.stderr[-1000:]}")

    def get(self, remote, local, check=True, timeout=1800):
        try:
            proc = subprocess.run(["scp", "-q", *self.opts, f"root@{self.ip}:{remote}", local],
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RunnerError(f"scp timed out after {timeout} s: {remote}")
        if check and proc.returncode != 0:
            raise RunnerError(f"scp from droplet failed: {remote}\n{proc.stderr[-1000:]}")
        return proc.returncode == 0


# ---- state ----------------------------------------------------------------------
class State:
    """Ids this run created, written the moment they exist, so destroy can find them."""

    def __init__(self, name, root=STATE_ROOT):
        self.dir = os.path.join(os.path.expanduser(root), validate_name(name))

    def path(self, key):
        return os.path.join(self.dir, key)

    def read(self, key):
        try:
            with open(self.path(key)) as f:
                return f.read().strip() or None
        except OSError:
            return None

    def write(self, key, value):
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        with open(self.path(key), "w") as f:
            f.write(str(value))

    def lock(self):
        """Exclusive per-name lock for a whole lifecycle; the handle must stay alive."""
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        handle = open(self.path("lock"), "w")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise RunnerError(f"another droplet_tournament process holds {self.path('lock')}; "
                              "to stop a live run send it SIGINT and it tears down")
        return handle

    def clear(self, *keys):
        for key in keys:
            try:
                os.remove(self.path(key))
            except OSError:
                pass


def log(msg):
    try:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
    except OSError:                                          # a closed pipe must not stop teardown
        pass


# ---- lifecycle --------------------------------------------------------------------
def create_key(api, state, name):
    state.clear("key", "key.pub", "known_hosts")
    os.makedirs(state.dir, mode=0o700, exist_ok=True)
    subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", droplet_name(name),
                    "-f", state.path("key"), "-q"], check=True, stdin=subprocess.DEVNULL)
    out = subprocess.run(["ssh-keygen", "-E", "md5", "-lf", state.path("key.pub")],
                         check=True, capture_output=True, text=True).stdout
    fingerprint = out.split()[1].replace("MD5:", "")
    with open(state.path("key.pub")) as f:
        public = f.read().strip()
    status, payload = api.call("POST", "/account/keys",
                               {"name": droplet_name(name), "public_key": public})
    if status not in (200, 201) or "ssh_key" not in payload:
        raise RunnerError(f"ssh key registration failed: HTTP {status} {payload.get('message', '')}")
    state.write("key-id", payload["ssh_key"]["id"])
    log(f"registered disposable ssh key {payload['ssh_key']['id']}")
    return fingerprint


def create_droplet(api, state, name, region, size, fingerprint):
    body = droplet_body(name, region, size, fingerprint)
    for attempt in range(1, 9):
        state.write("create-attempted", int(time.time()))    # teardown reconciles from this
        status, payload = api.call("POST", "/droplets", body)
        if status in (200, 201, 202) and "droplet" in payload:
            droplet_id = payload["droplet"]["id"]
            state.write("droplet-id", droplet_id)          # recorded before anything else
            state.write("created-at", int(time.time()))
            log(f"created droplet {droplet_id} ({body['name']}, {size}, {region}, tag {TAG})")
            return droplet_id
        message = str(payload.get("message", ""))
        if status == 422:
            state.clear("create-attempted")                  # refused outright: nothing exists
        if "invalid key identifiers" not in message:       # a fresh key needs a few seconds
            raise RunnerError(f"droplet create failed: HTTP {status} {message}")
        log(f"ssh key not usable yet (attempt {attempt} of 8), retrying in 5 s")
        time.sleep(5)
    raise RunnerError("droplet create failed: the new ssh key never became usable")


def wait_active(api, droplet_id, timeout=600):
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = api.get(f"/droplets/{droplet_id}")["droplet"]
        ips = [n["ip_address"] for n in d["networks"]["v4"] if n["type"] == "public"]
        if d["status"] == "active" and ips:
            return ips[0]
        time.sleep(5)
    raise RunnerError(f"droplet {droplet_id} never became active")


def wait_ssh(remote, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if remote.run("echo up", check=False, timeout=30).stdout.strip() == "up":
                return
        except subprocess.TimeoutExpired:
            pass
        time.sleep(5)
    raise RunnerError("ssh never came up")


def teardown(api, state, name):
    """Destroy the recorded droplet and key and verify both are gone. True when clean."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)            # teardown must finish
    api.retries = max(api.retries, 120)                     # ride out a 10 minute outage
    droplet_id, key_id = state.read("droplet-id"), state.read("key-id")
    attempted = state.read("create-attempted")
    ok = True
    if not droplet_id and attempted:
        # The create was sent but its id never reached state (timeout, signal, full disk).
        # A droplet it made carries our tag and exact name; give the API time to list it.
        found = []
        for _ in range(7):
            found = adoptable(api.get(f"/droplets?tag_name={TAG}&per_page=200")["droplets"],
                              name, attempted)
            if found:
                break
            time.sleep(10)
        if len(found) > 1:
            raise RunnerError(f"{len(found)} droplets named {droplet_name(name)}: "
                              f"{[d['id'] for d in found]}; destroy them with `destroy --id`")
        if found:
            droplet_id = str(found[0]["id"])
            state.write("droplet-id", droplet_id)
            log(f"adopted droplet {droplet_id} from a create whose answer was lost")
        else:
            log("the unanswered create made no droplet")
    if droplet_id:
        status, payload = api.call("GET", f"/droplets/{droplet_id}")
        if status == 404:
            log(f"droplet {droplet_id} already gone")
        elif status != 200:
            raise RunnerError(f"cannot read droplet {droplet_id}: HTTP {status}; NOT destroyed")
        else:
            refusal = destroy_refusal(payload["droplet"], recorded_id=droplet_id, name=name)
            if refusal:
                raise RunnerError(f"refusing to destroy: {refusal}")
            status, _ = api.call("DELETE", f"/droplets/{droplet_id}")
            log(f"delete droplet {droplet_id}: HTTP {status}")
        code = None
        for attempt in range(36):
            code, _ = api.call("GET", f"/droplets/{droplet_id}")
            if code == 404:
                break
            if attempt % 6 == 5:                             # still there: ask again
                api.call("DELETE", f"/droplets/{droplet_id}")
            time.sleep(5)
        log(f"verify droplet {droplet_id}: HTTP {code} (404 = gone)")
        if code != 404:
            raise RunnerError(f"droplet {droplet_id} STILL EXISTS; destroy it in the console")
        created, price = state.read("created-at"), state.read("price-hourly")
        if created and price:
            seconds = time.time() - int(created)
            state.write("cost", f"{cost(seconds, float(price)):.4f}")
            log(f"lifetime {seconds / 60:.1f} min at ${float(price):.5f}/h: cost about "
                f"${cost(seconds, float(price)):.3f}")
    if key_id:
        api.call("DELETE", f"/account/keys/{key_id}")
        code = None
        for _ in range(12):
            code, _ = api.call("GET", f"/account/keys/{key_id}")
            if code == 404:
                break
            time.sleep(5)
        log(f"verify ssh key {key_id}: HTTP {code} (404 = gone)")
        ok = ok and code == 404
    state.clear("key", "key.pub", "known_hosts", "ip")
    if ok:
        state.clear("droplet-id", "key-id", "create-attempted")
    return ok


def print_status(api):
    droplets = api.tagged_droplets()
    print(f"droplets tagged {TAG}: {len(droplets)}")
    for d in droplets:
        print("  " + describe_droplet(d))
    keys = [k for k in api.get("/account/keys?per_page=200")["ssh_keys"]
            if k["name"].startswith(NAME_PREFIX)]
    print(f"ssh keys named {NAME_PREFIX}*: {len(keys)}")
    for k in keys:
        print(f"  {k['id']}  {k['name']}")
    root = os.path.expanduser(STATE_ROOT)
    recorded = []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            did = State(name).read("droplet-id") if NAME_RE.match(name) else None
            if did:
                recorded.append((name, did))
    print(f"local state with a live droplet id: {len(recorded)}")
    for name, did in recorded:
        print(f"  {name}: droplet {did}")
    return droplets


def git(*args):
    return subprocess.run(["git", "-C", ROOT, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def poll(remote, tasks, deadline, stale_seconds, interval=30, lost_polls=60):
    """Wait for the detached job's EXIT file. Liveness is the log's mtime, not its text."""
    failures, last_report = 0, 0.0
    probe = (f"cat {REMOTE_RUN}/EXIT 2>/dev/null || echo -; cat {REMOTE_RUN}/STAGE 2>/dev/null || echo -; "
             f"wc -l < {REMOTE_OUT}/games.jsonl 2>/dev/null || echo 0; "
             f"echo $(( $(date +%s) - $(stat -c %Y {REMOTE_RUN}/tournament.log 2>/dev/null || date +%s) )); "
             f"tail -n 1 {REMOTE_RUN}/tournament.log 2>/dev/null")
    while True:
        if time.time() > deadline:
            raise RunnerError("the run passed --max-hours; giving up so the droplet stops billing")
        try:
            proc = remote.run(probe, check=False, timeout=60)
            lines = proc.stdout.splitlines() if proc.returncode == 0 else []
        except subprocess.TimeoutExpired:
            lines = []
        if len(lines) < 4:
            failures += 1
            if failures == 1 or failures % 10 == 0:
                log(f"no answer from the droplet ({failures} poll(s) in a row); the job "
                    f"runs detached, still waiting")
            if failures >= lost_polls:
                raise RunnerError(f"lost contact with the droplet for {failures} polls in a row")
            time.sleep(interval)
            continue
        failures = 0
        exit_code, stage, games, age = lines[0].strip(), lines[1].strip(), lines[2].strip(), lines[3].strip()
        if time.time() - last_report >= 120 or exit_code != "-":
            log(f"stage {stage}, {games}/{tasks} games, log age {age} s"
                + (f" | {lines[4].strip()}" if len(lines) > 4 else ""))
            last_report = time.time()
        if exit_code != "-":
            return int(exit_code)
        if stage == "tournament" and age.isdigit() and int(age) > stale_seconds:
            raise RunnerError(f"tournament log silent for {age} s with no EXIT file")
        time.sleep(interval)


def cmd_run(args):
    name = validate_name(args.name)
    checkpoints = dict(parse_assignment(c, "checkpoint") for c in args.checkpoint)
    bots = dict(parse_assignment(b, "bot") for b in args.bot)
    clash = set(checkpoints) & set(bots)
    if clash:
        raise RunnerError(f"names used by both a checkpoint and a bot: {sorted(clash)}")
    pairs = plan_pairs([parse_pair(p) for p in args.pair], set(checkpoints) | set(bots),
                       args.games_per_pair)
    tasks = expected_tasks(pairs)
    checkpoints = {n: os.path.abspath(os.path.expanduser(p)) for n, p in checkpoints.items()}
    for n, p in checkpoints.items():
        for path in (p, p + ".lineage.json"):
            if not os.path.isfile(path):
                raise RunnerError(f"checkpoint {n}: missing {path}")
    unused = [n for n in list(checkpoints) + list(bots) if not any(n in (a, b) for a, b, _ in pairs)]
    if unused:
        raise RunnerError(f"players in no pair (they would be uploaded for nothing): {unused}")

    commit = git("rev-parse", "--verify", args.commit + "^{commit}")
    dirty = git("status", "--porcelain", "--", *SYNC_PATHS)
    if dirty and args.commit == "HEAD":
        raise RunnerError("uncommitted changes under the synced paths; the droplet gets "
                          f"commit {commit[:12]}, so commit them first:\n{dirty}")
    out_dir = os.path.abspath(os.path.join(args.out_root, name, "main"))
    if os.path.exists(out_dir):
        raise RunnerError(f"{out_dir} already exists; pick a new --name")

    state = State(name)
    lock = state.lock()                                     # held until the process exits
    if state.read("droplet-id") or state.read("create-attempted"):
        raise RunnerError(f"state already records droplet {state.read('droplet-id')} or an "
                          f"unresolved create for {name}; run `destroy --name {name}` first")
    api = Api(read_token(env_file=args.env_file))
    size = pick_size(api.get("/sizes?per_page=200")["sizes"], args.size, args.region,
                     args.max_hourly)
    price = float(size["price_hourly"])
    workers = args.workers or int(size["vcpus"])
    log(f"size {args.size}: {size['vcpus']} vCPU, {size['memory']} MB, ${price:.5f}/h; "
        f"{tasks} games on {workers} workers; commit {commit[:12]}")
    log(f"spend guard: --max-hours {args.max_hours} caps this run at about "
        f"${cost(args.max_hours * 3600, price):.2f}")
    limit = int(api.get("/account")["account"]["droplet_limit"])
    existing = api.get("/droplets?per_page=200")["droplets"]
    refusal = limit_refusal(len(existing), limit)
    if refusal:
        raise RunnerError(refusal)
    others = filter_tagged(existing)
    if others:
        log(f"note: {len(others)} droplet(s) already carry the {TAG} tag: "
            + ", ".join(f"{d['id']} {d['name']}" for d in others))
    state.write("price-hourly", price)
    checkpoint_sha = {n: sha256_file(p) for n, p in checkpoints.items()}

    def on_signal(signum, _frame):
        raise Interrupted(f"signal {signum}")
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_signal)

    t_start = time.time()
    deadline = t_start + args.max_hours * 3600
    result, remote, failed = None, None, True
    try:
        fingerprint = create_key(api, state, name)
        droplet_id = create_droplet(api, state, name, args.region, args.size, fingerprint)
        ip = wait_active(api, droplet_id)
        state.write("ip", ip)
        remote = Remote(state.dir, ip)
        wait_ssh(remote)
        log(f"droplet {droplet_id} up at {ip} after {time.time() - t_start:.0f} s; installing")
        remote.script(setup_script(args.torch, args.numpy), "setup.log", timeout=1500)
        t_setup = time.time()

        archive = state.path("src.tar.gz")
        with open(archive, "wb") as f:
            subprocess.run(["git", "-C", ROOT, "archive", "--format=tar.gz", commit, "--",
                            *SYNC_PATHS], check=True, stdout=f)
        remote.put(archive, f"{REMOTE_ROOT}/src.tar.gz")
        remote.run(f"tar -xzf {REMOTE_ROOT}/src.tar.gz -C {REMOTE_SRC} && "
                   f"echo {commit} > {REMOTE_SRC}/SOURCE_COMMIT")
        for n, p in checkpoints.items():
            target = remote_checkpoint_path(n, p)
            remote.run(f"mkdir -p {shlex.quote(os.path.dirname(target))}")
            remote.put(p, target)
            remote.put(p + ".lineage.json", target + ".lineage.json")
        log(f"synced commit {commit[:12]} and {len(checkpoints)} checkpoint(s)")
        built = remote.script(build_script(commit), "build.log", timeout=900)
        machine = json.loads([l for l in built.stdout.splitlines() if l.startswith("{")][-1])
        log(f"shim built: {machine['cpu_model']}, {machine['nproc']} cores, {machine['cc']}, "
            f"torch {machine['torch']}, library {machine['library_sha256'][:12]}")

        argv = tournament_argv(checkpoints, bots, pairs, args.seed0, workers,
                               extra=args.tournament_arg,
                               games_per_worker=args.games_per_worker)
        remote.run(f"cat > {REMOTE_RUN}/job.sh", stdin_text=job_script(argv, workers, args.stats_reps))
        # No `cd &&` in front: a backgrounded list runs in a subshell that keeps ssh's
        # stdout open, and the launch would block until the tournament ends.
        remote.run(f"nohup setsid bash {REMOTE_RUN}/job.sh > {REMOTE_RUN}/job.log 2>&1 "
                   f"< /dev/null & echo started", timeout=60)
        t_launch = time.time()
        log(f"tournament launched under nohup ({t_launch - t_start:.0f} s after create)")
        rc = poll(remote, tasks, deadline, args.stale_seconds)
        if rc != 0:
            raise RunnerError(f"droplet job exited {rc}; logs are copied to {out_dir}.failed")
        t_done = time.time()

        partial = out_dir + ".partial"
        os.makedirs(partial, exist_ok=True)
        for fname in RESULT_FILES + EXTRA_FILES:
            remote.get(f"{REMOTE_OUT}/{fname}", os.path.join(partial, fname))
        for fname in ("tournament.log", "cpu-before", "cpu-after", "STATS_STARTED", "STATS_DONE"):
            remote.get(f"{REMOTE_RUN}/{fname}", os.path.join(partial, fname), check=False)
        with open(os.path.join(partial, "SHA256SUMS")) as f:
            sums = parse_sha256sums(f.read())
        problems = verify_files(partial, sums)
        with open(os.path.join(partial, "manifest.json")) as f:
            manifest = json.load(f)
        with open(os.path.join(partial, "COMPLETE.json")) as f:
            complete = json.load(f)
        with open(os.path.join(partial, "games.jsonl")) as f:
            games = [json.loads(line) for line in f if line.strip()]
        problems += verify_run(manifest, complete, games, commit, checkpoint_sha, pairs,
                               args.seed0, bots=bots, games_per_worker=args.games_per_worker)
        bad = {k: v for k, v in integrity_totals(games).items() if v}
        if bad:
            problems.append(f"nonzero integrity counters: {bad}")
        if problems:
            raise RunnerError("verification failed:\n  " + "\n  ".join(problems))
        log(f"verified {len(sums)} files by sha256, the manifest, {len(games)} games and "
            f"zero integrity counters")
        steal = None
        try:
            with open(os.path.join(partial, "cpu-before")) as f1, \
                    open(os.path.join(partial, "cpu-after")) as f2:
                steal = cpu_steal_fraction(f1.read(), f2.read())
        except (OSError, ValueError):
            pass
        stats_seconds = None
        try:
            with open(os.path.join(partial, "STATS_STARTED")) as f1, \
                    open(os.path.join(partial, "STATS_DONE")) as f2:
                stats_seconds = int(f2.read()) - int(f1.read())
        except (OSError, ValueError):
            pass
        result = {"schema": "bbplay-droplet-run-v1", "name": name, "droplet_id": droplet_id,
                  "size": args.size, "region": args.region, "price_hourly": price,
                  "vcpus": size["vcpus"], "workers": workers,
                  "games_per_worker": args.games_per_worker, "commit": commit,
                  "machine": machine, "tasks": tasks,
                  "games_per_second_wall": complete.get("games_per_second_wall"),
                  "tournament_wall_seconds": complete.get("wall_seconds"),
                  "cpu_steal_fraction": steal, "stats_seconds": stats_seconds,
                  "seconds": {"create_to_setup_done": round(t_setup - t_start, 1),
                              "setup_done_to_launch": round(t_launch - t_setup, 1),
                              "launch_to_done": round(t_done - t_launch, 1)},
                  "sha256": sums}
        os.rename(partial, out_dir)
        with open(os.path.join(out_dir, "droplet_run.json"), "w") as f:
            json.dump(result, f, indent=1)
        failed = False
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)               # teardown must finish
        try:                                                 # nothing here may stop teardown
            if failed and remote is not None:
                fail_dir = out_dir + ".failed"
                os.makedirs(fail_dir, exist_ok=True)
                for fname in LOG_FILES + ("build.log", "EXIT", "STAGE"):
                    try:
                        remote.get(f"{REMOTE_RUN}/{fname}", os.path.join(fail_dir, fname),
                                   check=False, timeout=120)
                    except Exception:
                        pass
                log(f"failure logs (what could be fetched) are in {fail_dir}")
        except Exception:
            pass
        if args.keep:
            log(f"--keep: droplet {state.read('droplet-id')} at {state.read('ip')} is STILL "
                f"BILLING. ssh -i {state.path('key')} root@{state.read('ip')}; "
                f"then: tools/droplet_tournament.py destroy --name {name}")
        else:
            try:
                teardown(api, state, name)
            except BaseException:
                try:
                    print(f"TEARDOWN FAILED: droplet {state.read('droplet-id')} may STILL BE "
                          f"BILLING. Run: tools/droplet_tournament.py destroy --name {name}",
                          file=sys.stderr, flush=True)
                except Exception:
                    pass
                raise
            if result is not None:
                result["cost"] = float(state.read("cost") or 0.0)
                result["lifetime_seconds"] = round(time.time() - t_start, 1)
                with open(os.path.join(out_dir, "droplet_run.json"), "w") as f:
                    json.dump(result, f, indent=1)
            try:
                print_status(api)
            except RunnerError as exc:
                log(f"leak check could not run ({exc}); run `status` by hand")
    log(f"results in {out_dir}: {result['games_per_second_wall']} games/s wall on "
        f"{workers} workers, steal {result['cpu_steal_fraction']}")
    return 0


def cmd_status(args):
    print_status(Api(read_token(env_file=args.env_file)))
    return 0


def cmd_destroy(args):
    api = Api(read_token(env_file=args.env_file))
    if args.name:
        state = State(args.name)
        lock = state.lock()                                 # noqa: F841 (held for the call)
        if not (state.read("droplet-id") or state.read("key-id")
                or state.read("create-attempted")):
            raise RunnerError(f"no recorded droplet or key for {args.name} in {state.dir}")
        teardown(api, state, args.name)
    else:
        status, payload = api.call("GET", f"/droplets/{int(args.id)}")
        if status == 404:
            log(f"droplet {args.id} does not exist")
        else:
            refusal = destroy_refusal(payload["droplet"])
            if refusal:
                raise RunnerError(f"refusing to destroy: {refusal}")
            code, _ = api.call("DELETE", f"/droplets/{int(args.id)}")
            log(f"delete droplet {args.id} ({payload['droplet']['name']}): HTTP {code}")
            for _ in range(24):
                code, _ = api.call("GET", f"/droplets/{int(args.id)}")
                if code == 404:
                    break
                time.sleep(5)
            log(f"verify droplet {args.id}: HTTP {code} (404 = gone)")
    print_status(api)
    return 0


def cmd_compare(args):
    def load(d):
        with open(os.path.join(d, "games.jsonl")) as f:
            return [json.loads(line) for line in f if line.strip()]
    report = compare_runs(load(args.run_dir), load(args.ref_dir))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=1)
    c = report["counts"]
    print(f"verdict: {report['verdict']}")
    print(f"games {c['games']}, matched on (pair, game_index, leg) {c['matched_keys']}, "
          f"seeds equal {c['seeds_equal']}, rosters equal {c['rosters_equal']}")
    print(f"final_digest equal {c['final_digest_equal']}, action_trail_sha256 equal "
          f"{c['action_trail_equal']}, both {c['exact']}, score equal {c['score_equal']}")
    print(f"games that took different actions: {c['diverged_games']}; logprob_sum equal "
          f"{c['logprob_sum_equal']}, largest drift over same-action games "
          f"{c['max_logprob_sum_drift_same_actions']:.4g}")
    print(f"integrity: {report['integrity']}")
    rows = list(report["pairs"].items()) + [("POOLED", report["pooled"])]
    for label, row in rows:
        print(compare_row(label, row))
    return 0


def cmd_merge(args):
    out_dir = os.path.abspath(args.out)
    if os.path.exists(out_dir):
        raise RunnerError(f"{out_dir} already exists")
    shards = []
    for d in args.shard:
        d = os.path.abspath(d)
        shard = {"name": os.path.basename(os.path.dirname(d)) if os.path.basename(d) == "main"
                 else os.path.basename(d)}
        with open(os.path.join(d, "SHA256SUMS")) as f:
            problems = verify_files(d, parse_sha256sums(f.read()))
        if problems:
            raise RunnerError(f"{d} fails its own SHA256SUMS:\n  " + "\n  ".join(problems))
        for key, fname in (("manifest", "manifest.json"), ("complete", "COMPLETE.json"),
                           ("machine", "machine.json")):
            with open(os.path.join(d, fname)) as f:
                shard[key] = json.load(f)
        with open(os.path.join(d, "games.jsonl")) as f:
            shard["lines"] = [line for line in f if line.strip()]
        shard["games"] = [json.loads(line) for line in shard["lines"]]
        shard["games_sha256"] = sha256_file(os.path.join(d, "games.jsonl"))
        shards.append(shard)
    manifest, complete, games = merge_shards(shards)
    os.makedirs(out_dir)
    with open(os.path.join(out_dir, "games.jsonl"), "w") as f:
        for shard in shards:
            f.writelines(line if line.endswith("\n") else line + "\n" for line in shard["lines"])
    for fname, payload in (("manifest.json", manifest), ("COMPLETE.json", complete)):
        with open(os.path.join(out_dir, fname), "w") as f:
            json.dump(payload, f, indent=1)
    log(f"merged {len(shards)} shards, {len(games)} games, {len(manifest['pairs'])} pairs into "
        f"{out_dir}")
    print(f"next: OMP_NUM_THREADS=1 .venv/bin/python -m play_harness.tournament_stats "
          f"--run-dir {out_dir} --json {out_dir}/report.json")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--env-file", default=DEFAULT_ENV_FILE,
                    help=f"dotenv file holding {TOKEN_VAR} (the environment wins)")
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="create a droplet, run one tournament, destroy it")
    run.add_argument("--name", required=True, help="run name; results land in OUT_ROOT/NAME/main")
    run.add_argument("--checkpoint", action="append", default=[], metavar="NAME=LOCAL_BLOB")
    run.add_argument("--bot", action="append", default=[], metavar="NAME=KIND")
    run.add_argument("--pair", action="append", default=[], metavar="A,B[,N]")
    run.add_argument("--games-per-pair", type=int, default=None)
    run.add_argument("--seed0", type=int, required=True)
    run.add_argument("--workers", type=int, default=None, help="default: the size's vCPU count")
    run.add_argument("--games-per-worker", type=int, default=1, metavar="N",
                     help="games each worker batches into one forward (default 1 = unbatched; "
                          "registered gates run at 1)")
    run.add_argument("--size", default=DEFAULT_SIZE)
    run.add_argument("--region", default=DEFAULT_REGION)
    run.add_argument("--max-hourly", type=float, default=MAX_HOURLY_DEFAULT,
                     help="refuse a size above this hourly price")
    run.add_argument("--max-hours", type=float, default=4.0,
                     help="give up and destroy the droplet after this long")
    run.add_argument("--stale-seconds", type=int, default=900,
                     help="fail when the tournament log is silent this long")
    run.add_argument("--commit", default="HEAD", help="harness commit to sync (default HEAD)")
    run.add_argument("--out-root", default=os.path.join(ROOT, ".play-artifacts", "tournaments"))
    run.add_argument("--torch", default=TORCH_VERSION)
    run.add_argument("--numpy", default=NUMPY_VERSION)
    run.add_argument("--stats-reps", type=int, default=None,
                     help="bootstrap reps for tournament_stats (default: its own)")
    run.add_argument("--tournament-arg", action="append", default=[],
                     help="repeatable; extra argument passed to play_harness.tournament")
    run.add_argument("--keep", action="store_true",
                     help="debugging: leave the droplet running (it keeps billing)")
    run.set_defaults(func=cmd_run)
    status = sub.add_parser("status", help="list every droplet carrying the tag (leak check)")
    status.set_defaults(func=cmd_status)
    destroy = sub.add_parser("destroy", help="destroy a droplet this tool created")
    group = destroy.add_mutually_exclusive_group(required=True)
    group.add_argument("--name", help="a run name with recorded state")
    group.add_argument("--id", type=int, help="a tagged, bb-harness-* droplet whose state is lost")
    destroy.set_defaults(func=cmd_destroy)
    compare = sub.add_parser("compare", help="game-by-game and distribution agreement of two runs")
    compare.add_argument("--run-dir", required=True)
    compare.add_argument("--ref-dir", required=True)
    compare.add_argument("--json", default=None)
    compare.set_defaults(func=cmd_compare)
    merge = sub.add_parser("merge", help="join runs that split one tournament by pair")
    merge.add_argument("--out", required=True, help="new run directory, e.g. .../NAME/main")
    merge.add_argument("--shard", action="append", required=True, metavar="RUN_DIR",
                       help="repeatable; a verified run directory from `run`")
    merge.set_defaults(func=cmd_merge)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except RunnerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    except Interrupted as exc:
        print(f"INTERRUPTED: {exc} (teardown has run)", file=sys.stderr, flush=True)
        return 130


if __name__ == "__main__":
    sys.exit(main())
