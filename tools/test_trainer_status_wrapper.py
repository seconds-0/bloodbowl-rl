import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "tools" / "trainer_status_wrapper.sh"
GUARD = ROOT / "tools" / "live_integrity_guard.py"


def bad_panel():
    from tools.live_integrity_guard import HARD_INTEGRITY_KEYS

    values = {key: 0.0 for key in HARD_INTEGRITY_KEYS}
    values.update({
        "_puffer_schema": 2,
        "_puffer_agent_steps": 131072.0,
        "illegal_frac": 1.0,
    })
    return "PUFFER_ENV_JSON " + json.dumps(values, sort_keys=True)


class TrainerStatusWrapperTests(unittest.TestCase):
    def guard_environment(self, root, status):
        return {
            **os.environ,
            "LIVE_INTEGRITY_GUARD": str(GUARD),
            "LIVE_INTEGRITY_PYTHON": os.environ.get(
                "PYTHON", "/usr/bin/python3"),
            "LIVE_INTEGRITY_STATE": str(root / "guard-state.json"),
            "LIVE_INTEGRITY_FAILURE": str(root / "guard-failure.json"),
            "LIVE_INTEGRITY_MAX_SILENCE": "5",
            "LIVE_INTEGRITY_POLL_SECONDS": "0.05",
            "LIVE_INTEGRITY_MARKER": str(status) + ".guard-failed",
        }

    def test_term_reaches_child_and_publishes_nonzero_status(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            status = root / "status.json"
            log = root / "trainer.log"
            child_pid_file = root / "child.pid"
            command = (
                'printf "%d\\n" "$$" > "$1"; '
                'trap "exit 0" TERM; while :; do sleep 1; done'
            )
            process = subprocess.Popen(
                [
                    "/bin/bash", str(WRAPPER), str(status), str(log),
                    "/bin/bash", "-c", command, "bash", str(child_pid_file),
                ],
                start_new_session=True,
            )
            deadline = time.time() + 5
            while time.time() < deadline and not child_pid_file.exists():
                time.sleep(0.01)
            self.assertTrue(child_pid_file.is_file())
            child_pid = int(child_pid_file.read_text(encoding="utf-8"))

            process.send_signal(signal.SIGTERM)
            self.assertEqual(process.wait(timeout=5), 143)
            payload = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(payload["exit_code"], 143)
            self.assertEqual(payload["pid"], process.pid)
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)

    def test_embedded_watchdog_stops_bad_trainer_and_publishes_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = root / "status.json"
            log = root / "trainer.log"
            command = f"printf '%s\\n' '{bad_panel()}'; while :; do sleep 1; done"
            process = subprocess.Popen(
                [
                    "/bin/bash", str(WRAPPER), str(status), str(log),
                    "/bin/bash", "-c", command,
                ],
                env=self.guard_environment(root, status),
                start_new_session=True,
            )
            self.assertNotEqual(process.wait(timeout=5), 0)
            payload = json.loads(status.read_text(encoding="utf-8"))
            self.assertNotEqual(payload["exit_code"], 0)
            failure = json.loads(
                (root / "guard-failure.json").read_text(encoding="utf-8"))
            self.assertEqual(failure["kind"], "hard_integrity_nonzero")

    def test_watchdog_survives_wrapper_loss_and_stops_later_bad_trainer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = root / "status.json"
            log = root / "trainer.log"
            child_pid_file = root / "child.pid"
            command = (
                'printf "%d\\n" "$$" > "$1"; sleep 0.5; '
                f"printf '%s\\n' '{bad_panel()}'; while :; do sleep 1; done"
            )
            process = subprocess.Popen(
                [
                    "/bin/bash", str(WRAPPER), str(status), str(log),
                    "/bin/bash", "-c", command, "bash", str(child_pid_file),
                ],
                env=self.guard_environment(root, status),
                start_new_session=True,
            )
            deadline = time.time() + 3
            while time.time() < deadline and not child_pid_file.exists():
                time.sleep(0.01)
            self.assertTrue(child_pid_file.is_file())
            child_pid = int(child_pid_file.read_text(encoding="utf-8"))
            os.kill(process.pid, signal.SIGKILL)
            process.wait(timeout=3)

            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
            self.assertTrue((root / "guard-failure.json").is_file())
            self.assertFalse(status.exists())


if __name__ == "__main__":
    unittest.main()
