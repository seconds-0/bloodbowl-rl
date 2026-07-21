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


class TrainerStatusWrapperTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
