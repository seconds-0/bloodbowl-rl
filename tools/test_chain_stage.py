#!/usr/bin/env python3
"""tools/chain_stage.sh: one rung, its exam and a verdict, safe to relaunch.

Runs the real script on a fake checkout in a temp dir. tools/ladder_stage.sh
and tools/eval_vs_contact_bot.sh are stubs that record how they were called,
nvidia-smi is a fake on PATH, and the GPU lock is a temp file. The verdict
tool, the sampler and the stage script are the real ones. No GPU, no build.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL_TOOLS = ROOT / "tools"
STAMP = "teststage-20261002"
POOL_HASH = "5" * 64

# The as-run chain 36 recipe (rig r0chain36.sh) with D407's restart scales.
# The stage must hand every one of these to ladder_stage.sh unchanged.
RECIPE = {
    "RUNG": "0", "RESET_PCT": "0", "SEED": "42", "STAMP": STAMP,
    "STEPS": "3000000000", "LADDER_ARM": "r0_poss_half",
    "SCRIPTED_BANK_TAG": "4", "SCRIPTED_BOT_TYPE": "0",
    "FROZEN_BANK_PCT": "0.12", "LADDER_CHAIN_LR_SCALE": "0.5",
    "LADDER_CHAIN_ENT_SCALE": "2.0",
    "LADDER_GAMMA": "0.999", "LADDER_GAE_LAMBDA": "0.95",
    "LADDER_REPLAY_RATIO": "1.0", "DEADLINE_HOURS": "16", "NUM_THREADS": "16",
    "PREV_COMPLETE": "/prev/LADDER_RUNG_COMPLETE.json",
}
OPTIONAL = {
    "POOL_KEEP": "3", "POOL_ANCHOR": "/anchor.bin", "NUM_FROZEN_BANKS": "4",
    "LADDER_PROFILE": "graft",
    "GRAFT_FROM_SOURCE_SHA256": "a" * 64,
    "GRAFT_FROM_PATCH_BUNDLE_SHA256": "b" * 64,
    "GRAFT_REASON": "D407 long run, one rebuild",
    "PUFFER_SKIP_SCRIPTED_BANK_FORWARD": "1", "BBE_DECIDING_ROW_TELEMETRY": "1",
}

STUB_LADDER = r"""#!/usr/bin/env bash
# Stand-in for tools/ladder_stage.sh.
set -uo pipefail
OUT="$C/runs/ladder-d${RUNG}-${STAMP}"
mkdir -p "$OUT" "$C/stub"
if [ "${PLAN_ONLY:-0}" = "1" ]; then
  echo plan >> "$C/stub/ladder_calls"
  [ -f "$OUT/POOL_IDENTITY.env" ] || echo "EXPECTED_POOL_HASH=${STUB_POOL_HASH}" > "$OUT/POOL_IDENTITY.env"
  if [ "${STUB_PLAN_FAILS:-0}" = "1" ]; then echo "drift check failed"; exit 1; fi
  echo "SCREEN PLAN VERIFIED: $OUT/screen-attempt1/SCREEN_MANIFEST.json"
  echo "LADDER_RUNG_SCREEN_EXIT=0"
  echo "screen exited 0 without SCREEN_COMPLETE.json" >&2
  exit 1
fi
echo train >> "$C/stub/ladder_calls"
env > "$C/stub/ladder_env"
# The trainer must inherit the GPU lock: fd 7 is open here and the lock is held.
if [ -e /dev/fd/7 ] && ! flock -n "$GPU_LOCK" -c true 2>/dev/null; then
  echo held > "$C/stub/lock_seen"
else
  echo free > "$C/stub/lock_seen"
fi
n=1; while [ -d "$OUT/screen-attempt$n" ] && [ -e "$OUT/screen-attempt$n/x.log" ]; do n=$((n + 1)); done
attempt="$OUT/screen-attempt$n"
mkdir -p "$attempt"
echo "partial" > "$attempt/x.log"
case "${STUB_LADDER_MODE:-ok}" in
  fail-status)
    echo '{"exit_code":1,"pid":1,"completed_utc":"x"}' > "$attempt/x.log.status.json"
    echo "LADDER_RUNG_SCREEN_EXIT=1"
    exit 1 ;;
  host-death)
    exit 9 ;;
  slow)
    sleep 3 ;;
  kill-parent)
    kill -KILL "$PPID"
    exit 9 ;;
esac
echo '{"exit_code":0,"pid":1,"completed_utc":"x"}' > "$attempt/x.log.status.json"
[ -f "$OUT/POOL_IDENTITY.env" ] || echo "EXPECTED_POOL_HASH=${STUB_POOL_HASH}" > "$OUT/POOL_IDENTITY.env"
mkdir -p "$C/ckpt"
printf 'weights' > "$C/ckpt/final.bin"
python3 - "$OUT" "$C/ckpt/final.bin" "$STUB_POOL_HASH" <<'PY'
import hashlib, json, sys
out, ckpt, pool = sys.argv[1:]
sha = hashlib.sha256(open(ckpt, "rb").read()).hexdigest()
json.dump({"checkpoint": ckpt, "checkpoint_sha256": sha, "trainer_exit": 0,
           "pool_hash": pool}, open(out + "/LADDER_RUNG_COMPLETE.json", "w"))
PY
"""

STUB_EVAL = r"""#!/usr/bin/env bash
# Stand-in for tools/eval_vs_contact_bot.sh: CKPT STEPS LOG.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CKPT="$1"; STEPS="$2"; LOG="$3"
echo "$SEED $BOT_TYPE $BOT_TEAM $STEPS $LOG omp=${OMP_NUM_THREADS-unset} native=${NATIVE:-} float=${RIG_ALLOW_FLOAT:-} cuda=${CUDA_VISIBLE_DEVICES:-} episodes=${EVAL_EPISODES:-} path0=${PATH%%:*}" >> "$ROOT/stub/eval_calls"
[ ! -e "$LOG" ] || { echo "refusing to overwrite existing log: $LOG" >&2; exit 1; }
if [ -f "$ROOT/stub/fail_eval" ] && [ "$(cat "$ROOT/stub/fail_eval")" = "$SEED $BOT_TYPE $BOT_TEAM" ]; then
  echo "half a log" > "$LOG"
  echo "scripted eval integrity gate failed" >&2
  exit 1
fi
tds="${STUB_TDS:-0.56}"
python3 - "$STUB_REAL_TOOLS" "$LOG" "$SEED" "$BOT_TYPE" "$BOT_TEAM" "$tds" "$CKPT" <<'PY'
import hashlib, sys
sys.path.insert(0, sys.argv[1])
from test_chain_exam_verdict import write_cell_log
log, seed, bot_type, bot_team, tds, ckpt = sys.argv[2:]
write_cell_log(log, seed=int(seed), bot_type=int(bot_type),
               bot_team=int(bot_team), champion_tds=float(tds),
               checkpoint_sha=hashlib.sha256(open(ckpt, "rb").read()).hexdigest())
PY
echo "validated scripted eval: 2010 games; cumulative gate 2010"
"""

FAKE_NVIDIA_SMI = "#!/usr/bin/env bash\necho '79, 95, 135.11'\n"


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class ChainStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.checkout = base / "checkout"
        tools = self.checkout / "tools"
        tools.mkdir(parents=True)
        for name in ("chain_stage.sh", "chain_gpu_sampler.sh",
                     "chain_exam_verdict.py", "contact_bot_stats.py",
                     "game_stats.py"):
            shutil.copy(REAL_TOOLS / name, tools / name)
        (tools / "ladder_stage.sh").write_text(STUB_LADDER, encoding="utf-8")
        (tools / "eval_vs_contact_bot.sh").write_text(STUB_EVAL, encoding="utf-8")
        (self.checkout / "stub").mkdir()
        fake_bin = base / "bin"
        fake_bin.mkdir()
        smi = fake_bin / "nvidia-smi"
        smi.write_text(FAKE_NVIDIA_SMI, encoding="utf-8")
        smi.chmod(0o755)
        (base / "lock").mkdir()
        self.lock = base / "lock" / "kt-gpu.lock"
        self.run_dir = self.checkout / "runs" / f"ladder-d0-{STAMP}"
        self.stub = self.checkout / "stub"
        self.fake_bin = fake_bin
        self.held = None
        self.strays: list[int] = []

    def tearDown(self):
        self.release_lock()
        for pid in self.strays:
            if pid_alive(pid):
                os.kill(pid, signal.SIGTERM)
        self.tmp.cleanup()

    # -- helpers ------------------------------------------------------------
    def env(self, **overrides):
        clean = {k: v for k, v in os.environ.items()
                 if k not in RECIPE and k not in OPTIONAL
                 and not k.startswith(("EXAM_", "STUB_", "GRAFT_", "LADDER_"))
                 and k not in ("EXPECTED_POOL_HASH", "PLAN_ONLY", "WARM",
                               "PREV_POOL", "HOST_BOOT_EPOCH")}
        clean.update(RECIPE)
        clean.update({
            "C": str(self.checkout), "EXAM_RULE": "none",
            "GPU_LOCK": str(self.lock), "GPU_LOCK_WAIT_SECONDS": "1",
            "GPU_SAMPLE_SECONDS": "1", "STUB_POOL_HASH": POOL_HASH,
            "STUB_REAL_TOOLS": str(REAL_TOOLS),
            "PATH": f"{self.fake_bin}{os.pathsep}{os.environ['PATH']}",
        })
        for key, value in overrides.items():
            if value is None:
                clean.pop(key, None)
            else:
                clean[key] = value
        return clean

    def stage(self, **overrides):
        return subprocess.run(
            ["bash", str(self.checkout / "tools/chain_stage.sh")],
            env=self.env(**overrides), cwd="/", text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
            timeout=120)

    def calls(self, name):
        path = self.stub / name
        return path.read_text().splitlines() if path.exists() else []

    def hold_lock(self):
        self.held = self.lock.open("a")
        fcntl.flock(self.held, fcntl.LOCK_EX)

    def release_lock(self):
        if self.held is not None:
            self.held.close()
            self.held = None

    def lock_is_free(self) -> bool:
        with self.lock.open("a") as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return False
        return True

    def sampler_pid(self, output: str) -> int:
        match = re.search(r"gpu sampler pid=(\d+)", output)
        self.assertIsNotNone(match, output)
        return int(match.group(1))

    def wait_gone(self, pid: int, seconds: float = 10.0) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if not pid_alive(pid):
                return True
            time.sleep(0.1)
        return False

    def exam_logs(self, attempt: int):
        root = self.run_dir / f"exam-attempt{attempt}"
        return sorted(str(p.relative_to(root)) for p in root.rglob("*.log"))

    # -- the happy path -------------------------------------------------------
    def test_fresh_run_trains_examines_and_registers_a_pass(self):
        result = self.stage(OMP_NUM_THREADS="3", **OPTIONAL)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.calls("ladder_calls"), ["train"])
        # Six cells, seed-major, in rig_exam.sh's cell order and settings.
        cells = [line.split() for line in self.calls("eval_calls")]
        exam = self.run_dir / "exam-attempt1"
        self.assertEqual(
            [cell[:5] for cell in cells],
            [[seed, bot_type, bot_team, "12000000", f"{exam}/s{seed}/{name}.log"]
             for seed in ("42", "43")
             for name, bot_type, bot_team in (("contact_away", "0", "1"),
                                              ("contact_home", "0", "0"),
                                              ("offense_away", "1", "1"))])
        for cell in cells:
            # OMP_NUM_THREADS was 3 in the caller; cells must not see it.
            self.assertEqual(cell[5:], [
                "omp=unset", "native=1", "float=1", "cuda=0", "episodes=2000",
                f"path0={self.checkout}/vendor/PufferLib/.venv/bin"])
        self.assertEqual(len(self.exam_logs(1)), 6)
        self.assertEqual(len(list(exam.rglob("*.out"))), 6)
        self.assertTrue((exam / "EXAM_CELLS_COMPLETE.json").is_file())
        verdict = json.loads((self.run_dir / "EXAM_VERDICT.json").read_text())
        self.assertTrue(verdict["pass"])
        self.assertEqual(verdict["exam_dir"], str(exam))
        self.assertEqual(len(verdict["cells"]), 6)
        self.assertTrue((self.run_dir / "EXAM_VERDICT_PASS.json").is_file())
        # The rung ran under the lock, on an inherited descriptor.
        self.assertEqual(self.calls("lock_seen"), ["held"])
        lock_log = Path(str(self.lock) + ".log").read_text().splitlines()
        self.assertEqual(len(lock_log), 2)
        self.assertRegex(
            lock_log[0],
            rf"^\d{{4}}-\d\d-\d\dT\d\d:\d\d:\d\dZ \d+ acquired\(lock={re.escape(str(self.lock))}\) "
            rf"bloodbowl-rl:chain-stage-{STAMP} ")
        self.assertRegex(lock_log[1], r"Z \d+ released\(exit 0\) bloodbowl-rl:chain-stage-")
        # Telemetry: a header and at least one sample, no unit suffixes.
        samples = (self.run_dir / "gpu_samples.csv").read_text().splitlines()
        self.assertEqual(samples[0], "utc,temperature_c,utilization_pct,power_w")
        self.assertRegex(samples[1], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ,79,95,135\.11$")
        status = json.loads((self.run_dir / "CHAIN_STAGE_STATUS.json").read_text())
        self.assertEqual((status["phase"], status["exit_code"]), ("exited", 0))
        # Every line the stage itself prints carries a UTC timestamp.
        own = [line for line in result.stdout.splitlines() if "chain_stage:" in line]
        self.assertGreater(len(own), 15)
        for line in own:
            self.assertRegex(line, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ chain_stage: ")
        # The recipe reaches ladder_stage.sh untouched; the stage's own pool
        # check input and plan flag do not.
        seen = dict(line.split("=", 1) for line in self.calls("ladder_env")
                    if "=" in line)
        for key, value in {**RECIPE, **OPTIONAL, "C": str(self.checkout)}.items():
            self.assertEqual(seen.get(key), value, key)
        self.assertNotIn("EXPECTED_POOL_HASH", seen)
        self.assertNotIn("PLAN_ONLY", seen)

    def test_run_dir_is_the_directory_ladder_stage_uses(self):
        expression = '"$C/runs/ladder-d${RUNG}-${STAMP}"'
        self.assertIn(f"OUT={expression}",
                      (REAL_TOOLS / "ladder_stage.sh").read_text())
        self.assertIn(f"RUN_DIR={expression}",
                      (REAL_TOOLS / "chain_stage.sh").read_text())

    # -- relaunch after a terminal state -------------------------------------
    def test_relaunch_after_pass_is_a_no_op_that_needs_no_lock(self):
        self.assertEqual(self.stage().returncode, 0)
        self.hold_lock()  # a relaunch must not even wait for the GPU
        again = self.stage()
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertIn("verdict already registered and passed", again.stdout)
        self.assertEqual(self.calls("ladder_calls"), ["train"])
        self.assertEqual(len(self.calls("eval_calls")), 6)
        self.assertFalse((self.run_dir / "exam-attempt2").exists())

    def test_relaunch_after_a_failed_verdict_exits_3_and_runs_nothing(self):
        floors = {"EXAM_RULE": "drift-guard", "EXAM_GUARD_FLOOR_S42": "0.541",
                  "EXAM_GUARD_FLOOR_S43": "0.551", "EXAM_GUARD_FLOOR_MEAN": "0.546",
                  "STUB_TDS": "0.50"}
        first = self.stage(**floors)
        self.assertEqual(first.returncode, 3, first.stdout)
        self.assertIn("VERDICT FAIL", first.stdout)
        self.assertTrue((self.run_dir / "EXAM_VERDICT.json").is_file())
        self.assertFalse((self.run_dir / "EXAM_VERDICT_PASS.json").exists())
        self.hold_lock()
        # Even a relaunch whose rule would pass must not run a second exam.
        again = self.stage()
        self.assertEqual(again.returncode, 3, again.stdout)
        self.assertIn("final; no exam is run again", again.stdout)
        self.assertEqual(self.calls("ladder_calls"), ["train"])
        self.assertEqual(len(self.calls("eval_calls")), 6)
        self.assertFalse((self.run_dir / "exam-attempt2").exists())
        self.assertFalse((self.run_dir / "EXAM_VERDICT_PASS.json").exists())

    def test_relaunch_after_a_failed_trainer_status_exits_4_without_retraining(self):
        first = self.stage(STUB_LADDER_MODE="fail-status")
        self.assertEqual(first.returncode, 1, first.stdout)  # the rung's status
        self.assertEqual(self.calls("eval_calls"), [])
        self.hold_lock()
        # Boot time unknown (no /proc/stat here) or older than the status: the
        # failure happened on this boot and is final.
        for boot in (None, "1000"):
            again = self.stage(HOST_BOOT_EPOCH=boot)
            self.assertEqual(again.returncode, 4, again.stdout)
            self.assertIn("recorded trainer status 1 on this boot", again.stdout)
        self.assertEqual(self.calls("ladder_calls"), ["train"])
        self.assertEqual(self.calls("eval_calls"), [])
        self.assertFalse((self.run_dir / "EXAM_VERDICT.json").exists())
        # The documented manual retry: open the next attempt directory.
        self.release_lock()
        (self.run_dir / "screen-attempt2").mkdir()
        retry = self.stage()
        self.assertEqual(retry.returncode, 0, retry.stdout)
        self.assertEqual(self.calls("ladder_calls"), ["train", "train"])

    def test_live_integrity_failure_exits_4_even_across_a_reboot(self):
        attempt = self.run_dir / "screen-attempt1"
        attempt.mkdir(parents=True)
        (attempt / "x.log").write_text("partial\n")
        (attempt / "LIVE_INTEGRITY_FAILURE.json").write_text("{}")
        result = self.stage(HOST_BOOT_EPOCH=str(int(time.time()) + 3600))
        self.assertEqual(result.returncode, 4, result.stdout)
        self.assertIn("LIVE_INTEGRITY_FAILURE.json", result.stdout)
        self.assertEqual(self.calls("ladder_calls"), [])

    def test_status_written_before_this_boot_is_a_host_shutdown_and_retrains(self):
        # A clean host shutdown sends TERM; the trainer wrapper records 143.
        attempt = self.run_dir / "screen-attempt1"
        attempt.mkdir(parents=True)
        (attempt / "x.log").write_text("partial\n")
        (attempt / "x.log.status.json").write_text('{"exit_code":143}')
        result = self.stage(HOST_BOOT_EPOCH=str(int(time.time()) + 3600))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("recorded trainer status 143 before this boot", result.stdout)
        self.assertEqual(self.calls("ladder_calls"), ["train"])

    def test_partial_attempt_without_a_status_falls_through_to_the_rung(self):
        first = self.stage(STUB_LADDER_MODE="host-death")
        self.assertEqual(first.returncode, 9, first.stdout)
        self.assertFalse(list(self.run_dir.glob("screen-attempt1/*.status.json")))
        again = self.stage()
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertIn("has no trainer status", again.stdout)
        self.assertEqual(self.calls("ladder_calls"), ["train", "train"])

    # -- exam failures ---------------------------------------------------------
    def test_exam_cell_failure_exits_5_and_the_next_launch_uses_a_new_dir(self):
        (self.stub / "fail_eval").write_text("43 0 0")  # seed 43 contact HOME
        first = self.stage()
        self.assertEqual(first.returncode, 5, first.stdout)
        self.assertIn("EXAM CELL FAILED seed=43 contact_home", first.stdout)
        self.assertIn("scripted eval integrity gate failed", first.stdout)
        self.assertFalse((self.run_dir / "EXAM_VERDICT.json").exists())
        self.assertFalse((self.run_dir / "EXAM_VERDICT_PASS.json").exists())
        self.assertEqual(len(self.calls("eval_calls")), 5)  # stopped at the failure
        self.assertFalse(
            (self.run_dir / "exam-attempt1" / "EXAM_CELLS_COMPLETE.json").exists())
        before = self.exam_logs(1)

        (self.stub / "fail_eval").unlink()
        again = self.stage()
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertEqual(self.calls("ladder_calls"), ["train"])  # no retraining
        self.assertEqual(self.exam_logs(1), before)  # the half-written dir is left alone
        self.assertEqual(len(self.exam_logs(2)), 6)
        verdict = json.loads((self.run_dir / "EXAM_VERDICT.json").read_text())
        self.assertEqual(verdict["exam_dir"], str(self.run_dir / "exam-attempt2"))
        self.assertTrue((self.run_dir / "EXAM_VERDICT_PASS.json").is_file())

    def test_checkpoint_that_no_longer_matches_the_marker_exits_7(self):
        self.assertEqual(self.stage(STUB_LADDER_MODE="ok").returncode, 0)
        for name in ("EXAM_VERDICT.json", "EXAM_VERDICT_PASS.json"):
            (self.run_dir / name).unlink()
        (self.checkout / "ckpt" / "final.bin").write_bytes(b"other weights")
        result = self.stage()
        self.assertEqual(result.returncode, 7, result.stdout)
        self.assertIn("the marker recorded", result.stdout)
        self.assertEqual(len(self.calls("eval_calls")), 6)  # no new cells

    # -- the GPU lock -----------------------------------------------------------
    def start(self, log_path: Path, **overrides):
        handle = log_path.open("w")
        proc = subprocess.Popen(
            ["bash", str(self.checkout / "tools/chain_stage.sh")],
            env=self.env(**overrides), cwd="/", stdout=handle,
            stderr=subprocess.STDOUT)
        handle.close()
        return proc

    def wait_for(self, log_path: Path, text: str, count: int = 1, seconds: float = 30.0):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if log_path.read_text().count(text) >= count:
                return
            time.sleep(0.1)
        self.fail(f"{text!r} x{count} never appeared in:\n{log_path.read_text()}")

    def test_lock_held_by_another_process_makes_the_stage_wait_not_abort(self):
        self.hold_lock()
        log_path = self.stub / "stage.log"
        proc = self.start(log_path)
        try:
            # More than one one-second round: it keeps waiting, it does not give up.
            self.wait_for(log_path, "waiting on", count=2)
            self.assertIsNone(proc.poll())
            self.assertEqual(self.calls("ladder_calls"), [])
            status = json.loads((self.run_dir / "CHAIN_STAGE_STATUS.json").read_text())
            self.assertEqual(status["phase"], "waiting-gpu-lock")
            self.assertFalse(Path(str(self.lock) + ".log").exists())
            self.release_lock()
            self.assertEqual(proc.wait(timeout=60), 0, log_path.read_text())
        finally:
            if proc.poll() is None:
                proc.kill()
        self.assertEqual(self.calls("ladder_calls"), ["train"])
        self.assertTrue((self.run_dir / "EXAM_VERDICT_PASS.json").is_file())

    def test_terminal_state_is_checked_again_once_the_lock_is_acquired(self):
        self.hold_lock()
        log_path = self.stub / "stage.log"
        proc = self.start(log_path)
        try:
            self.wait_for(log_path, "waiting on")
            # Another launch of the same stage finishes while this one waits.
            (self.run_dir / "EXAM_VERDICT_PASS.json").write_text("{}")
            self.release_lock()
            self.assertEqual(proc.wait(timeout=60), 0, log_path.read_text())
        finally:
            if proc.poll() is None:
                proc.kill()
        self.assertEqual(self.calls("ladder_calls"), [])
        self.assertEqual(self.calls("eval_calls"), [])

    def test_sampler_is_gone_and_the_lock_is_free_after_exit(self):
        result = self.stage(GPU_SAMPLE_SECONDS="30")
        self.assertEqual(result.returncode, 0, result.stdout)
        pid = self.sampler_pid(result.stdout)
        self.strays.append(pid)
        self.assertTrue(self.lock_is_free())
        # Killed by the EXIT trap in the middle of its 30 second sleep.
        self.assertTrue(self.wait_gone(pid), f"sampler {pid} outlived the stage")

    def test_sampler_never_holds_the_lock_even_when_the_stage_is_killed(self):
        # kill -KILL skips the EXIT trap, so the sampler is still alive when
        # the stage is gone. It must hold neither the lock (or the next stage
        # waits forever) nor a command line the supervisor's `[c]hain_stage.sh`
        # liveness pattern matches (or the supervisor reports BUSY forever).
        log_path = self.stub / "stage.log"
        proc = self.start(log_path, STUB_LADDER_MODE="kill-parent",
                          GPU_SAMPLE_SECONDS="5")
        self.assertEqual(proc.wait(timeout=60), -signal.SIGKILL, log_path.read_text())
        pid = self.sampler_pid(log_path.read_text())
        self.strays.append(pid)
        deadline = time.time() + 5
        while not self.lock_is_free() and time.time() < deadline:
            time.sleep(0.05)  # the stub rung is still exiting
        self.assertTrue(pid_alive(pid), "sampler should still be mid-sleep")
        self.assertTrue(self.lock_is_free(), "an orphaned sampler holds the GPU lock")
        command = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                                 text=True, stdout=subprocess.PIPE).stdout
        self.assertIn("chain_gpu_sampler.sh", command)
        self.assertNotIn("chain_stage.sh", command)
        # And it notices its owner is gone and leaves on its own.
        self.assertTrue(self.wait_gone(pid, 15), f"sampler {pid} never exited")

    def test_term_during_the_rung_waits_for_the_rung_then_exits_143(self):
        # The stage must not die under a live trainer that holds the lock, and
        # must not log a release it has not made. It stops after the rung,
        # before the exam, and the next launch only runs the exam.
        log_path = self.stub / "stage.log"
        proc = self.start(log_path, STUB_LADDER_MODE="slow")
        try:
            self.wait_for(log_path, "rung start")
            time.sleep(0.5)
            proc.send_signal(signal.SIGTERM)
            time.sleep(1.0)
            self.assertIsNone(proc.poll(), "the stage died under its rung")
            self.assertEqual(proc.wait(timeout=60), 143, log_path.read_text())
        finally:
            if proc.poll() is None:
                proc.kill()
        output = log_path.read_text()
        # The trap runs as soon as the rung child returns.
        self.assertIn("caught TERM; stopping", output)
        self.assertNotIn("exam start", output)
        self.assertEqual(self.calls("eval_calls"), [])
        self.assertTrue((self.run_dir / "LADDER_RUNG_COMPLETE.json").is_file())
        lock_log = Path(str(self.lock) + ".log").read_text().splitlines()
        self.assertRegex(lock_log[-1], r"released\(exit 143\)")
        status = json.loads((self.run_dir / "CHAIN_STAGE_STATUS.json").read_text())
        self.assertEqual((status["phase"], status["exit_code"]), ("exited", 143))
        self.assertTrue(self.lock_is_free())
        again = self.stage()
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertEqual(self.calls("ladder_calls"), ["train"])
        self.assertEqual(len(self.calls("eval_calls")), 6)

    # -- pool identity and plan-only -------------------------------------------
    def test_pool_mismatch_aborts_before_any_training(self):
        result = self.stage(EXPECTED_POOL_HASH="6" * 64)
        self.assertEqual(result.returncode, 6, result.stdout)
        self.assertIn("POOL MISMATCH", result.stdout)
        self.assertEqual(self.calls("ladder_calls"), ["plan"])
        self.assertFalse((self.run_dir / "LADDER_RUNG_COMPLETE.json").exists())
        # The published identity makes every relaunch fail the same way, fast.
        again = self.stage(EXPECTED_POOL_HASH="6" * 64)
        self.assertEqual(again.returncode, 6, again.stdout)
        self.assertEqual(self.calls("ladder_calls"), ["plan"])

    def test_matching_pool_plans_first_then_trains(self):
        result = self.stage(EXPECTED_POOL_HASH=POOL_HASH)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("plan-only pass verified", result.stdout)
        self.assertEqual(self.calls("ladder_calls"), ["plan", "train"])
        self.assertTrue((self.run_dir / "chain-plan-only.log").is_file())

    def test_plan_pass_that_does_not_verify_aborts_before_training(self):
        result = self.stage(EXPECTED_POOL_HASH=POOL_HASH, STUB_PLAN_FAILS="1")
        self.assertEqual(result.returncode, 6, result.stdout)
        self.assertIn("did NOT verify the screen plan", result.stdout)
        self.assertEqual(self.calls("ladder_calls"), ["plan"])

    def test_plan_only_mode_stops_before_training_and_takes_no_lock(self):
        self.hold_lock()
        result = self.stage(PLAN_ONLY="1", EXPECTED_POOL_HASH=POOL_HASH)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(f"pool identity {POOL_HASH}; stopping before any training",
                      result.stdout)
        self.assertEqual(self.calls("ladder_calls"), ["plan"])
        self.assertEqual(self.calls("eval_calls"), [])
        self.assertFalse((self.run_dir / "gpu_samples.csv").exists())
        mismatch = self.stage(PLAN_ONLY="1", EXPECTED_POOL_HASH="6" * 64)
        self.assertEqual(mismatch.returncode, 6, mismatch.stdout)

    # -- configuration ------------------------------------------------------------
    def test_unset_recipe_knobs_fail_loudly_before_anything_runs(self):
        for key in ("C", "STAMP", "EXAM_RULE", "STEPS", "LADDER_ARM",
                    "FROZEN_BANK_PCT", "DEADLINE_HOURS", "NUM_THREADS",
                    "LADDER_GAMMA", "LADDER_REPLAY_RATIO", "SCRIPTED_BANK_TAG",
                    "LADDER_CHAIN_LR_SCALE", "LADDER_CHAIN_ENT_SCALE"):
            result = self.stage(**{key: None})
            self.assertEqual(result.returncode, 2, f"{key}: {result.stdout}")
            self.assertRegex(result.stdout, rf"refusing to start; unset: .*\b{key}\b")
        result = self.stage(PREV_COMPLETE=None)
        self.assertEqual(result.returncode, 2)
        self.assertIn("PREV_COMPLETE (or both WARM and PREV_POOL)", result.stdout)
        self.assertEqual(self.calls("ladder_calls"), [])
        self.assertFalse(self.lock.exists())
        # Exported empty is a deliberate "take the screen's fixed value".
        result = self.stage(LADDER_GAMMA="", LADDER_GAE_LAMBDA="")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_exam_rule_is_validated_before_the_rung_trains(self):
        result = self.stage(EXAM_RULE="drift-guard", EXAM_GUARD_FLOOR_S42="0.541",
                            EXAM_GUARD_FLOOR_S43="0.551")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("needs EXAM_GUARD_FLOOR_MEAN", result.stdout)
        result = self.stage(EXAM_RULE="veto")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("EXAM_RULE must be none or drift-guard", result.stdout)
        result = self.stage(GRAFT_REASON="x")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("GRAFT_* is set but LADDER_PROFILE is 'ladder-rung'", result.stdout)
        self.assertEqual(self.calls("ladder_calls"), [])


class ChainStageRealLadderTests(unittest.TestCase):
    """The plan-only pass through the REAL ladder scripts on a stand-in build.

    chain_stage.sh reads the plan pass from two lines printed two scripts
    below it and expects exit status 1. Only the real ladder_stage.sh,
    launch_ladder_rung.sh and run_reward_screen.sh can confirm that, so this
    borrows the stand-in checkout of tools/test_ladder_rung_profile.py (fake
    `_C`, real lineage sidecar, the per-arm launcher stubbed out).
    """

    def setUp(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from tools.test_ladder_rung_profile import stand_in_checkout
        self.tmp = tempfile.TemporaryDirectory()
        self.root, self.warm, self.pool = stand_in_checkout(self.tmp.name)
        (self.root / "POOL_IDENTITY.env").write_text(
            f"EXPECTED_POOL_HASH={POOL_HASH}\n")
        self.lock = self.root / "kt-gpu.lock"

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self, stamp, **overrides):
        env = {k: v for k, v in os.environ.items()
               if k not in RECIPE
               and not k.startswith(("EXAM_", "GRAFT_", "LADDER_", "SCRIPTED_",
                                     "BRIDGE_"))
               and k not in ("EXPECTED_POOL_HASH", "PLAN_ONLY", "WARM", "POOL",
                             "PREV_POOL", "OUT", "OUT_DIR", "PREFIX")}
        env.update(RECIPE)
        del env["PREV_COMPLETE"]  # a first rung: explicit warm and pool
        env.update({
            "C": str(self.root), "STAMP": stamp, "EXAM_RULE": "none",
            "WARM": str(self.warm), "PREV_POOL": str(self.pool),
            "EXPECTED_POOL_HASH": POOL_HASH, "GPU_LOCK": str(self.lock),
            "HORIZON_DUMP": str(self.root / "arm.dump"), "POLL_SECONDS": "1",
        })
        env.update(overrides)
        return subprocess.run(
            ["bash", str(self.root / "tools/chain_stage.sh")], env=env, cwd="/",
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=False, timeout=300)

    def test_plan_only_mode_verifies_the_real_screen_plan(self):
        result = self.stage("plan-a", PLAN_ONLY="1")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("SCREEN PLAN VERIFIED: ", result.stdout)
        self.assertIn("plan-only pass verified (ladder_stage.sh exit 1", result.stdout)
        self.assertIn(f"pool identity {POOL_HASH}; stopping before any training",
                      result.stdout)
        run_dir = self.root / "runs/ladder-d0-plan-a"
        self.assertTrue((run_dir / "screen-attempt1/SCREEN_MANIFEST.json").is_file())
        self.assertFalse((self.root / "arm.dump").exists())  # no arm launched
        self.assertFalse(self.lock.exists())
        # A wrong expectation is caught here, before any training.
        wrong = self.stage("plan-a", PLAN_ONLY="1", EXPECTED_POOL_HASH="6" * 64)
        self.assertEqual(wrong.returncode, 6, wrong.stdout)
        self.assertIn("POOL MISMATCH", wrong.stdout)

    def test_stage_plans_then_launches_the_rung_into_the_planned_attempt(self):
        result = self.stage("plan-b")
        out = result.stdout
        # The stand-in arm launcher exits without a trainer, so the rung fails
        # right after the hand-off; what matters is the order before that.
        self.assertNotEqual(result.returncode, 0, out)
        for needle in ("plan-only pass verified", "pool identity matches",
                       "rung start: bash tools/ladder_stage.sh", "START index="):
            self.assertIn(needle, out)
        self.assertLess(out.index("plan-only pass verified"),
                        out.index("rung start: bash tools/ladder_stage.sh"))
        self.assertLess(out.index("rung start: bash tools/ladder_stage.sh"),
                        out.index("START index="))
        # The real pass reused the planned attempt and its manifest.
        run_dir = self.root / "runs/ladder-d0-plan-b"
        self.assertEqual(out.count(f"screen {run_dir}/screen-attempt1\n"), 2)
        self.assertFalse((run_dir / "screen-attempt2").exists())
        # The recipe reached the arm launcher through three real scripts.
        self.assertEqual((self.root / "arm.dump").read_text(),
                         "GAMMA=0.999\nGAE_LAMBDA=0.95\n")
        self.assertIn("REPLAY_RATIO=1.0\n",
                      (self.root / "arm.dump.update").read_text())
        self.assertFalse(list(run_dir.glob("exam-attempt*")))
        self.assertFalse((run_dir / "EXAM_VERDICT.json").exists())
        lock_log = Path(str(self.lock) + ".log").read_text().splitlines()
        self.assertRegex(lock_log[-1], r"released\(exit \d+\) bloodbowl-rl:chain-stage-plan-b")


class ChainSupervisorWiringTests(unittest.TestCase):
    """The units and the supervisor hand the build flags to the stage."""

    UNITS = ROOT / "training/systemd"
    CHECKOUT = "%h/bloodbowl-rl-longrun-20261002"

    def test_service_keeps_the_campaign_unit_shape_on_the_long_run_checkout(self):
        unit = (self.UNITS / "chain-supervisor@.service").read_text()
        lines = [line for line in unit.splitlines() if not line.startswith("#")]
        for line in ("Type=oneshot", "KillMode=process", "TimeoutStopSec=45",
                     "StartLimitIntervalSec=3600", "StartLimitBurst=20",
                     f"WorkingDirectory={self.CHECKOUT}",
                     "Environment=CUDA_VISIBLE_DEVICES=0",
                     "Environment=PUFFER_SKIP_SCRIPTED_BANK_FORWARD=1",
                     "Environment=BBE_DECIDING_ROW_TELEMETRY=1"):
            self.assertIn(line, lines)
        campaign = f"{self.CHECKOUT}/runs/campaigns/%i"
        self.assertIn(
            f"ExecStart={self.CHECKOUT}/vendor/PufferLib/.venv/bin/python "
            f"{self.CHECKOUT}/tools/campaign_supervisor.py "
            f"--plan {campaign}/CAMPAIGN_PLAN.json "
            f"--state {campaign}/CAMPAIGN_STATE.json "
            "--timer-unit chain-supervisor@%i.timer", lines)
        self.assertNotIn("qualification-candidate", unit)

    def test_timer_keeps_the_five_minute_tick(self):
        unit = (self.UNITS / "chain-supervisor@.timer").read_text()
        lines = unit.splitlines()
        for line in ("OnBootSec=2min", "OnUnitActiveSec=5min", "AccuracySec=30s",
                     "Persistent=true", "Unit=chain-supervisor@%i.service",
                     "WantedBy=timers.target"):
            self.assertIn(line, lines)

    def test_supervisor_passes_its_environment_and_the_stage_env_to_the_stage(self):
        import sys
        from unittest import mock
        sys.path.insert(0, str(REAL_TOOLS))
        import campaign_supervisor as sup

        seen = {}

        class FakePopen:
            pid = 4242

            def __init__(self, argv, **kwargs):
                seen.update(argv=argv, **kwargs)

        flags = {"PUFFER_SKIP_SCRIPTED_BANK_FORWARD": "1",
                 "BBE_DECIDING_ROW_TELEMETRY": "1", "FROM_UNIT": "kept"}
        stage = {"name": "r01", "launch": "bash /home/rache/chain/r01.sh",
                 "env": {"FROM_UNIT": "stage wins", "STAGE_ONLY": 7}}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, flags), \
                mock.patch.object(sup.subprocess, "Popen", FakePopen):
            os.environ.pop("CUDA_VISIBLE_DEVICES", None)
            pid = sup.launch_stage(Path(tmp), stage, Path(tmp) / "logs", 1)
        self.assertEqual(pid, 4242)
        self.assertEqual(seen["argv"], ["setsid", "nohup", "bash", "-lc",
                                        "bash /home/rache/chain/r01.sh"])
        env = seen["env"]
        self.assertEqual(env["PUFFER_SKIP_SCRIPTED_BANK_FORWARD"], "1")
        self.assertEqual(env["BBE_DECIDING_ROW_TELEMETRY"], "1")
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "0")
        self.assertEqual(env["FROM_UNIT"], "stage wins")
        self.assertEqual(env["STAGE_ONLY"], "7")


if __name__ == "__main__":
    unittest.main()
