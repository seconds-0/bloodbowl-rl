#!/usr/bin/env python3
"""Advance a multi-stage training campaign one tick at a time.

Why this exists rather than tools/experiment_queue.py: the queue's plan is
SHA-pinned up front and each stage can receive exactly one path from its
predecessor, so a campaign whose later stages need a value COMPUTED by an
earlier stage (a candidate arm chosen by an analysis, a checkpoint selected by
step count) is not expressible -- editing the plan mid-flight halts the queue.
The queue is the right tool for a fully pre-authored chain; this is the right
tool for a chain that resolves its own inputs at launch time.

Why no model in the loop: the previous keeper of this GPU was a cron job that
dispatched `claude -p` every 30 minutes to decide whether to relaunch. It died
on 2026-06-12 when the account hit a weekly limit and sat dead for six weeks
while the GPU idled. Nothing here calls a model, a network, or an API.

Safety properties, all deliberate:

* It never kills, signals, or cleans up anything. A stalled trainer is reported,
  not terminated -- the screen's own live integrity guard owns that decision
  (MAX_PANEL_SILENCE_SECONDS), and a supervisor that kills on a heuristic is a
  supervisor that eventually kills a healthy run.
* It never launches while a trainer is alive, so it cannot put a second trainer
  on the GPU. Liveness uses the bracketed pgrep pattern (footgun 12) so the
  probe cannot match its own command line -- an unbracketed pattern has already
  reported dead processes as alive twice in this campaign.
* Each stage has an attempt cap. Exceeding it HALTS the campaign rather than
  relaunching for the rest of the week.
* A halt is sticky. Only a human (or a later session) clears it.
* One tick at a time, serialized by flock on the state file, so overlapping
  timer firings cannot both launch.

Run it from a systemd timer or a service loop:

    python3 tools/campaign_supervisor.py --plan CAMPAIGN_PLAN.json \
                                        --state CAMPAIGN_STATE.json

Exit status is 0 for every normal outcome including halt, because a halted
campaign is a decision, not a crash, and systemd should not restart-loop on it.
2 is reserved for a malformed plan or an unusable state file.
"""

from __future__ import annotations

import argparse
import datetime
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# A trainer liveness pattern MUST be bracketed so pgrep cannot match the shell
# or ssh command line that carries the pattern itself. `[p]uffer` matches the
# string "puffer" while the literal pattern text does not match itself.
DEFAULT_TRAINER_PGREP = r"[p]uffer_cuda_runtime.py train|[p]uffer train"


class PlanError(Exception):
    """The plan or state file cannot be used as given."""


def _utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlanError(f"{label} not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanError(f"{label} is unreadable: {path}: {exc}") from exc


def _write_json_atomic(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def validate_plan(plan: Any) -> dict:
    """Reject a plan we cannot execute, rather than half-executing it."""
    if not isinstance(plan, dict):
        raise PlanError("plan is not an object")
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise PlanError(
            f"plan schema_version must be {SCHEMA_VERSION}, got "
            f"{plan.get('schema_version')!r}"
        )
    for key in ("campaign_id", "root", "stages"):
        if not plan.get(key):
            raise PlanError(f"plan is missing required key: {key}")
    root = Path(plan["root"])
    if not root.is_absolute():
        raise PlanError(f"plan root must be absolute: {root}")

    pattern = plan.get("trainer_pgrep", DEFAULT_TRAINER_PGREP)
    if "[" not in pattern:
        # Refuse the footgun outright instead of documenting it.
        raise PlanError(
            "trainer_pgrep must use the bracketed form (e.g. '[p]uffer train') "
            "so the probe cannot match its own command line"
        )

    stages = plan["stages"]
    if not isinstance(stages, list) or not stages:
        raise PlanError("plan stages must be a non-empty list")
    seen: set[str] = set()
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            raise PlanError(f"stage {index} is not an object")
        name = stage.get("name")
        if not name or not isinstance(name, str):
            raise PlanError(f"stage {index} has no name")
        if name in seen:
            raise PlanError(f"duplicate stage name: {name}")
        seen.add(name)
        if not stage.get("success"):
            raise PlanError(f"stage {name} has no success artifact path")
        launch = stage.get("launch")
        if not isinstance(launch, str) or not launch.strip():
            raise PlanError(f"stage {name} has no launch command string")
        attempts = stage.get("max_attempts", 3)
        if not isinstance(attempts, int) or attempts < 1:
            raise PlanError(f"stage {name} has an invalid max_attempts")
        stale = stage.get("max_stale_seconds", 1800)
        if not isinstance(stale, int) or stale < 60:
            raise PlanError(f"stage {name} has an invalid max_stale_seconds")
    return plan


def trainer_is_alive(pattern: str) -> bool:
    """True when a trainer process matches. Absence of proof is not proof."""
    try:
        done = subprocess.run(
            ["pgrep", "-f", pattern],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        # If we cannot probe, assume something IS running. Launching a second
        # trainer onto a busy GPU is far worse than idling one tick.
        return True
    return done.returncode == 0 and bool(done.stdout.strip())


def stage_progress_age(root: Path, stage: dict) -> float | None:
    """Seconds since the stage's progress file was last written, if declared."""
    progress = stage.get("progress")
    if not progress:
        return None
    path = root / progress if not Path(progress).is_absolute() else Path(progress)
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def stage_is_complete(root: Path, stage: dict) -> bool:
    success = stage["success"]
    path = root / success if not Path(success).is_absolute() else Path(success)
    return path.exists()


def _blank_state(plan: dict) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": plan["campaign_id"],
        "halted": False,
        "halt_reason": None,
        "complete": False,
        "stages": {},
        "history": [],
        "updated_utc": _utc(),
    }


def _stage_state(state: dict, name: str) -> dict:
    entry = state["stages"].setdefault(
        name, {"attempts": 0, "launched_utc": None, "last_pid": None}
    )
    return entry


def _record(state: dict, message: str, keep: int = 200) -> None:
    state["history"].append({"utc": _utc(), "event": message})
    if len(state["history"]) > keep:
        del state["history"][:-keep]


def launch_stage(root: Path, stage: dict, log_dir: Path, attempt: int) -> int:
    """Start a stage detached so it outlives this tick and its SSH session.

    setsid+nohup is correct HERE because this supervisor is the top-level owner
    -- it is not running inside an experiment_queue job, where an inner detach
    would let the trainer escape the job's process-group guards. A stage that
    the queue owns must set ARM_DETACH=0 and must not be launched from here.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{stage['name']}-attempt{attempt}.log"
    env = dict(os.environ)
    # A detached, non-interactive shell does not source the login profile, so
    # anything the launcher demands must be set explicitly. run_reward_ablation
    # refuses to start unless CUDA_VISIBLE_DEVICES is exactly "0"; losing that
    # silently killed a relaunch already.
    env.setdefault("CUDA_VISIBLE_DEVICES", "0")
    for key, value in (stage.get("env") or {}).items():
        env[str(key)] = str(value)

    with log_path.open("ab") as sink:
        sink.write(
            f"\n=== attempt {attempt} launched {_utc()} ===\n".encode("utf-8")
        )
        sink.flush()
        proc = subprocess.Popen(
            ["setsid", "nohup", "bash", "-lc", stage["launch"]],
            cwd=str(root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=sink,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return proc.pid


def tick(plan: dict, state: dict, *, dry_run: bool = False) -> str:
    """Advance the campaign at most one step. Returns a one-line verdict."""
    root = Path(plan["root"])
    pattern = plan.get("trainer_pgrep", DEFAULT_TRAINER_PGREP)
    log_dir = Path(plan.get("log_dir") or (root / "runs" / "campaign-logs"))
    if not log_dir.is_absolute():
        log_dir = root / log_dir

    if state.get("halted"):
        return f"HALTED {state.get('halt_reason')}"

    stages: list[dict] = plan["stages"]
    current = None
    for stage in stages:
        if not stage_is_complete(root, stage):
            current = stage
            break

    if current is None:
        if not state.get("complete"):
            state["complete"] = True
            _record(state, "campaign complete: every stage success artifact present")
        return "COMPLETE all stages have their success artifact"

    entry = _stage_state(state, current["name"])

    if trainer_is_alive(pattern):
        age = stage_progress_age(root, current)
        if age is not None and age > current.get("max_stale_seconds", 1800):
            # Report, never kill. The run's own integrity guard owns termination.
            _record(
                state,
                f"stage {current['name']}: trainer alive but progress stale "
                f"{age:.0f}s (> {current.get('max_stale_seconds', 1800)}s) -- "
                f"reported, not terminated",
            )
            return (
                f"STALE stage={current['name']} progress_age={age:.0f}s "
                f"(trainer alive; not touching it)"
            )
        return f"BUSY stage={current['name']} trainer alive; nothing to do"

    max_attempts = current.get("max_attempts", 3)
    if entry["attempts"] >= max_attempts:
        state["halted"] = True
        state["halt_reason"] = (
            f"stage {current['name']} reached its attempt cap "
            f"({entry['attempts']}/{max_attempts}) without producing "
            f"{current['success']}"
        )
        _record(state, state["halt_reason"])
        return f"HALT {state['halt_reason']}"

    attempt = entry["attempts"] + 1
    if dry_run:
        return (
            f"WOULD-LAUNCH stage={current['name']} attempt={attempt}/"
            f"{max_attempts} cmd={shlex.quote(current['launch'])[:120]}"
        )

    pid = launch_stage(root, current, log_dir, attempt)
    entry["attempts"] = attempt
    entry["launched_utc"] = _utc()
    entry["last_pid"] = pid
    _record(
        state,
        f"stage {current['name']}: launched attempt {attempt}/{max_attempts} pid={pid}",
    )
    return f"LAUNCHED stage={current['name']} attempt={attempt}/{max_attempts} pid={pid}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="decide and print, but do not launch or write state",
    )
    args = parser.parse_args(argv)

    try:
        plan = validate_plan(_load_json(args.plan, "plan"))
    except PlanError as exc:
        print(f"campaign supervisor: {exc}", file=sys.stderr)
        return 2

    lock_path = args.state.with_suffix(args.state.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("BUSY another supervisor tick holds the state lock")
            return 0

        if args.state.exists():
            try:
                state = _load_json(args.state, "state")
            except PlanError as exc:
                print(f"campaign supervisor: {exc}", file=sys.stderr)
                return 2
            if state.get("campaign_id") != plan["campaign_id"]:
                print(
                    "campaign supervisor: state belongs to campaign "
                    f"{state.get('campaign_id')!r}, plan is {plan['campaign_id']!r}",
                    file=sys.stderr,
                )
                return 2
            state.setdefault("stages", {})
            state.setdefault("history", [])
        else:
            state = _blank_state(plan)

        verdict = tick(plan, state, dry_run=args.dry_run)
        print(verdict)
        if not args.dry_run:
            state["updated_utc"] = _utc()
            _write_json_atomic(args.state, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
