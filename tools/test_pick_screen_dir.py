#!/usr/bin/env python3
"""pick_screen_dir must read liveness from the screen lock, not a stale PID.

tools/launch_ladder_rung.sh picks the screen attempt directory for a rung. A
partial attempt (a log, no atomic status) is reused only while its trainer is
alive. The recorded PID cannot say that after a host restart, because PIDs
start low again and another process of the same user can hold the number
(review LP6, 2026-10-02). The screen lock can: the screen holds
<attempt>/.screen.lock and its detached trainer inherits it.

These tests run the function exactly as the launcher defines it.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNG = ROOT / "tools/launch_ladder_rung.sh"
TAG = "ladder-d0-s42-test-r0_poss_half-s42"


def pick(out: Path) -> subprocess.CompletedProcess:
    source = RUNG.read_text(encoding="utf-8")
    match = re.search(r"^pick_screen_dir\(\) \{\n.*?^\}\n", source, re.S | re.M)
    assert match, "pick_screen_dir not found in launch_ladder_rung.sh"
    script = match.group(0) + "pick_screen_dir\n"
    env = dict(os.environ, OUT=str(out), TAG=TAG)
    return subprocess.run(
        ["bash", "-c", "set -uo pipefail\n" + script], env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=60)


def partial_attempt(out: Path, n: int, pid: int) -> Path:
    attempt = out / f"screen-attempt{n}"
    attempt.mkdir(parents=True)
    log = attempt / f"{TAG}.log"
    log.write_text("partial trainer output\n", encoding="utf-8")
    Path(str(log) + ".process.json").write_text(
        json.dumps({"pid": pid, "process_group": pid}), encoding="utf-8")
    return attempt


class PickScreenDirTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dead_partial_attempt_with_a_live_recorded_pid_opens_the_next(self):
        # The recorded PID is this test process: alive and owned by this user,
        # which is the only kind of PID `kill -0` accepted. (PID 1 would make
        # the test pass against the old code too: signalling another user's
        # process fails.) No one holds the screen lock, so the attempt is dead.
        attempt = partial_attempt(self.out, 1, os.getpid())
        (attempt / ".screen.lock").write_text("", encoding="utf-8")
        result = pick(self.out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.out / "screen-attempt2"))
        self.assertIn("holds a dead partial arm", result.stderr)

    def test_dead_partial_attempt_without_a_lock_file_opens_the_next(self):
        partial_attempt(self.out, 1, os.getpid())
        result = pick(self.out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.out / "screen-attempt2"))

    def test_held_screen_lock_keeps_the_attempt_even_with_a_dead_pid(self):
        # A PID that cannot exist: liveness must come from the lock alone.
        attempt = partial_attempt(self.out, 1, 2 ** 22 + 12345)
        lock = attempt / ".screen.lock"
        with lock.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            result = pick(self.out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(attempt))

    def test_unchanged_cases_fresh_planned_complete_clean_and_failed(self):
        # Fresh: no directory yet.
        self.assertEqual(pick(self.out).stdout.strip(),
                         str(self.out / "screen-attempt1"))
        # Planned, never launched: the directory exists without a log.
        first = self.out / "screen-attempt1"
        first.mkdir()
        self.assertEqual(pick(self.out).stdout.strip(), str(first))
        # A non-zero status opens the next attempt.
        log = first / f"{TAG}.log"
        log.write_text("x\n", encoding="utf-8")
        status = Path(str(log) + ".status.json")
        status.write_text(json.dumps({"exit_code": 1}), encoding="utf-8")
        result = pick(self.out)
        self.assertEqual(result.stdout.strip(), str(self.out / "screen-attempt2"))
        self.assertIn("holds a failed arm", result.stderr)
        # A clean status is recoverable: reuse it.
        status.write_text(json.dumps({"exit_code": 0}), encoding="utf-8")
        self.assertEqual(pick(self.out).stdout.strip(), str(first))
        # A completed screen is reused whatever else is there.
        status.unlink()
        (first / "SCREEN_COMPLETE.json").write_text("{}", encoding="utf-8")
        self.assertEqual(pick(self.out).stdout.strip(), str(first))

    def test_launcher_no_longer_trusts_the_recorded_pid(self):
        source = RUNG.read_text(encoding="utf-8")
        match = re.search(r"^pick_screen_dir\(\) \{\n.*?^\}\n", source, re.S | re.M)
        self.assertIsNotNone(match)
        self.assertNotIn("kill -0", match.group(0))
        self.assertIn('flock -n "$dir/.screen.lock" -c true', match.group(0))
        # A missing flock must not read as "lock held".
        self.assertLess(source.index("command -v flock"),
                        source.index('SCREEN_DIR="$(pick_screen_dir)"'))


if __name__ == "__main__":
    unittest.main()
