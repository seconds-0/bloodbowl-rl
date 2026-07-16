#!/usr/bin/env python3
"""Verify immutable sidecar authority and every newly reachable candidate."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import selectors


MAX_COMMITS = 64
MIN_COMPLETE_VERIFIER_SECONDS = 300
PER_COMMIT_SECONDS = 300
AGGREGATE_SECONDS = 900
CONTAINER_IMAGE = (
    "silkeh/clang@sha256:"
    "9388794775d1393c16b6897b4775b6d3e29459319de0bfafec59a20262e1fa68"
)
MAX_VERIFIER_OUTPUT_BYTES = 4 * 1024 * 1024


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, check=False, timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(arguments)} failed: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def run_process(command: list[str], timeout: float) -> None:
    process = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, start_new_session=True,
    )
    require(process.stdout is not None, "verifier output pipe is missing")
    os.set_blocking(process.stdout.fileno(), False)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    output = bytearray()
    deadline = time.monotonic() + timeout
    failure: str | None = None
    while selector.get_map():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            failure = f"command exceeded {timeout:.1f}s"
            break
        for key, _ in selector.select(min(remaining, 0.25)):
            chunk = os.read(key.fileobj.fileno(), 65536)
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            output.extend(chunk)
            if len(output) > MAX_VERIFIER_OUTPUT_BYTES:
                failure = "verifier exceeded bounded output allowance"
                break
        if failure is not None:
            break
    if failure is not None:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=30)
    rendered = bytes(output).decode("utf-8", errors="replace")
    if failure is not None:
        raise RuntimeError(f"{failure}: {' '.join(command)}\n{rendered}")
    if process.returncode != 0:
        raise RuntimeError(
            f"command failed ({process.returncode}): {' '.join(command)}\n{rendered}"
        )


def same_file(left: Path, right: Path) -> bool:
    return (left.is_file() and right.is_file() and
            not left.is_symlink() and not right.is_symlink() and
            left.read_bytes() == right.read_bytes())


def run_candidate_verifier(
    verifier: Path, candidate: Path, authority: Path, timeout: float,
    container_runtime: str | None, container_name: str,
) -> None:
    if container_runtime is None:
        run_process([sys.executable, str(verifier), str(candidate)], timeout)
        return
    runtime = shutil.which(container_runtime)
    require(runtime is not None,
            f"container runtime not found: {container_runtime}")
    command = [
        runtime, "run", "--rm", "--pull=never", "--name", container_name,
        "--platform", "linux/amd64", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "512", "--memory", "4g", "--cpus", "2.0",
        "--ulimit", "nofile=1024:1024", "--ulimit", "core=0:0",
        "--user", "65534:65534",
        "--env", "HOME=/tmp", "--env", "LANG=C",
        "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=2147483648,mode=1777",
        "--mount", f"type=bind,src={authority},dst=/authority,readonly",
        "--mount", f"type=bind,src={candidate},dst=/candidate,readonly",
        "--workdir", "/tmp", "--entrypoint", "python3", CONTAINER_IMAGE,
        "/authority/tools/authored_sidecar_authority/verify_candidate.py",
        "/candidate", "--compiler", "clang",
    ]
    try:
        run_process(command, timeout)
    finally:
        subprocess.run(
            [runtime, "rm", "-f", container_name],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False, timeout=30,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    parser.add_argument("authority", type=Path)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--container-runtime", choices=("docker", "podman"))
    args = parser.parse_args()
    require(PER_COMMIT_SECONDS >= MIN_COMPLETE_VERIFIER_SECONDS,
            "per-commit limit cannot contain one complete verifier")
    require(AGGREGATE_SECONDS >= PER_COMMIT_SECONDS,
            "aggregate limit is shorter than one complete verifier")
    repository = args.repository.resolve()
    authority = args.authority.resolve()
    trusted = authority / "tools" / "authored_sidecar_authority"
    oracle_path = authority / "tools" / "authored_sidecar_oracle.json"
    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    immutable = set(oracle["authority_files"])
    immutable.add("tools/authored_sidecar_oracle.json")
    immutable.add(".github/workflows/authored-sidecar-authority.yml")
    production_source = str(oracle["production_source"])
    if args.bootstrap:
        require(not (authority / production_source).exists() and
                not (authority / production_source).is_symlink(),
                "bootstrap authority already contains production serializer")

    before = git(repository, "rev-parse", "--verify", f"{args.before}^{{commit}}")
    after = git(repository, "rev-parse", "--verify", f"{args.after}^{{commit}}")
    ancestor = subprocess.run(
        ["git", "-C", str(repository), "merge-base", "--is-ancestor",
         before, after], check=False, timeout=60,
    )
    require(ancestor.returncode == 0,
            "before authority is not an ancestor of after")
    commits = [line for line in
               git(repository, "rev-list", "--reverse", f"{before}..{after}").splitlines()
               if line]
    require(commits, "newly reachable commit range is empty")
    require(len(commits) <= MAX_COMMITS,
            f"newly reachable range has {len(commits)} commits; squash to 64")
    verifier = trusted / "verify_candidate.py"
    require(verifier.is_file(), "trusted candidate verifier is missing")

    began = time.monotonic()
    introduced = not args.bootstrap
    verified = 0
    with tempfile.TemporaryDirectory(prefix="authored-sidecar-history-") as raw:
        root = Path(raw)
        for number, commit in enumerate(commits):
            require(time.monotonic() - began < AGGREGATE_SECONDS,
                    "sidecar history exhausted aggregate time")
            worktree = root / f"commit-{number:02d}"
            git(repository, "worktree", "add", "--detach", str(worktree), commit)
            try:
                present = [relative for relative in immutable
                           if (worktree / relative).is_file()]
                if args.bootstrap and not introduced:
                    if not present:
                        continue
                    require(len(present) == len(immutable),
                            "first sidecar commit contains a partial authority set")
                    introduced = True
                if args.bootstrap and introduced:
                    source = worktree / production_source
                    require(not source.exists() and not source.is_symlink(),
                            "bootstrap range contains production serializer")
                require(introduced,
                        "normal history unexpectedly lacks sidecar authority")
                for relative in sorted(immutable):
                    require(same_file(authority / relative,
                                      worktree / relative),
                            f"immutable sidecar authority differs at {commit}: {relative}")
                remaining = AGGREGATE_SECONDS - (time.monotonic() - began)
                timeout = min(PER_COMMIT_SECONDS, remaining)
                require(timeout > 0,
                        "sidecar history exhausted aggregate time")
                name = f"sidecar-history-{os.getpid()}-{number:02d}-{commit[:12]}"
                run_candidate_verifier(
                    verifier, worktree, authority, timeout,
                    args.container_runtime, name)
                verified += 1
            finally:
                git(repository, "worktree", "remove", "--force", str(worktree))
    require(introduced, "bootstrap range never introduced sidecar authority")
    require(verified > 0, "no sidecar-authority commit was verified")
    print(f"authored sidecar history verified: {verified}/{len(commits)} commits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
