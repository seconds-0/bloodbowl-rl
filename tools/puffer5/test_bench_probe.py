#!/usr/bin/env python3
"""CPU-only tests for tools/puffer5/bench_probe.py (fake trainer, fake nvidia-smi)."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bench_probe as bp  # noqa: E402

PROBE = os.path.join(HERE, "bench_probe.py")


def fake_smi(directory, temp):
    path = os.path.join(directory, "nvidia-smi")
    with open(path, "w") as handle:
        handle.write("#!/bin/sh\n")
        handle.write('case "$*" in *name*) echo "FAKE GPU, 0.0, 40, 100, 8192";; '
                     f'*) echo "{temp}, 5630, 97";; esac\n')
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class ParseTests(unittest.TestCase):
    def test_ref40_bench_line(self):
        line = 'BENCH40_JSON {"SPS": 91000.0, "agent_steps": 131072, "epoch": 1, ' \
               '"uptime": 3.0, "perf/eval_gpu": 0.2, "t": 5.0}'
        s = bp.parse_ref40_line(line, 10.0)
        self.assertEqual(s["agent_steps"], 131072.0)
        self.assertEqual(s["perf/eval_gpu"], 0.2)
        self.assertEqual(s["t_arrival"], 10.0)
        self.assertEqual(s["source"], "bench40")

    def test_ref40_env_panel_fallback_and_eval_rejected(self):
        s = bp.parse_ref40_line('PUFFER_ENV_JSON {"_puffer_agent_steps": 262144, '
                                '"_puffer_epoch": 2, "_puffer_phase_eval": 0}', 1.0)
        self.assertEqual(s["agent_steps"], 262144.0)
        self.assertEqual(s["epoch"], 2.0)
        self.assertIsNone(bp.parse_ref40_line('PUFFER_ENV_JSON {"_puffer_agent_steps": 1,'
                                              ' "_puffer_phase_eval": 1}', 1.0))

    def test_ref40_garbage(self):
        self.assertIsNone(bp.parse_ref40_line("| SPS 91.0K |", 1.0))
        self.assertIsNone(bp.parse_ref40_line("BENCH40_JSON {not json", 1.0))
        self.assertIsNone(bp.parse_ref40_line('BENCH40_JSON {"SPS": 1}', 1.0))

    def test_p5_line_drops_env_and_nan(self):
        s = bp.parse_p5_line('{"SPS": 1.0, "agent_steps": 5, "env/tds": 1.0, '
                             '"loss/kl": NaN, "perf/eval_env": 0.5}', 2.0)
        self.assertNotIn("env/tds", s)
        self.assertNotIn("loss/kl", s)
        self.assertEqual(s["perf/eval_env"], 0.5)
        self.assertIsNone(bp.parse_p5_line("", 2.0))
        self.assertIsNone(bp.parse_p5_line('{"SPS": 1.0}', 2.0))

    def test_parse_smi(self):
        self.assertEqual(bp.parse_smi("80, 5630, 97\n"), (80.0, 5630.0, 97.0))
        self.assertIsNone(bp.parse_smi("[N/A], 1, 2"))


class LogicTests(unittest.TestCase):
    def test_thermal(self):
        self.assertEqual(bp.thermal_action(85.9, 86), "ok")
        self.assertEqual(bp.thermal_action(86.0, 86), "kill")
        self.assertEqual(bp.thermal_action(None, 86), "ok")

    def test_warmup_end_waits_for_positive_steps(self):
        samples = [{"agent_steps": 0, "t_arrival": 5.0}]
        self.assertIsNone(bp.warmup_end(0.0, 10.0, samples))
        samples.append({"agent_steps": 10, "t_arrival": 30.0})
        self.assertEqual(bp.warmup_end(0.0, 10.0, samples), 30.0)
        self.assertEqual(bp.warmup_end(0.0, 60.0, samples), 60.0)

    def test_window_stats(self):
        samples = []
        for i in range(10):
            samples.append({"t_arrival": 100.0 + i, "uptime": 50.0 + i,
                            "agent_steps": 1000.0 * i, "epoch": 2.0 * i, "SPS": 999.0,
                            "perf/eval_model": 0.25, "perf/eval_env": 0.5,
                            "util/vram_used_gb": 6.0 + 0.1 * i})
        st = bp.window_stats(samples, 102.0, 106.0, "p5")
        self.assertEqual(st["samples_in_window"], 5)
        self.assertAlmostEqual(st["sps_window"], 1000.0)
        self.assertAlmostEqual(st["sps_trainer_mean"], 999.0)
        self.assertEqual(st["epochs_in_window"], 8.0)
        # 4 intervals after the first sample, 0.25 s each over 8 epochs -> 125 ms/epoch
        self.assertAlmostEqual(st["perf_ms_per_epoch"]["gpu_forward_ms"], 125.0)
        self.assertAlmostEqual(st["perf_ms_per_epoch"]["env_ms"], 250.0)
        self.assertIsNone(st["perf_ms_per_epoch"]["copy_ms"])
        self.assertAlmostEqual(st["trainer_vram_used_gb_max"], 6.6)

    def test_window_stats_arrival_clock_and_too_few(self):
        samples = [{"t_arrival": 0.0, "agent_steps": 0.0},
                   {"t_arrival": 2.0, "agent_steps": 500.0}]
        st = bp.window_stats(samples, 0.0, 2.0, "ref40")
        self.assertEqual(st["clock"], "t_arrival")
        self.assertAlmostEqual(st["sps_window"], 250.0)
        st = bp.window_stats(samples[:1], 0.0, 2.0, "ref40")
        self.assertIn("error", st)

    def test_summarize_ratio(self):
        probes = [{"name": "ref40_rr1", "status": "ok", "sps_window": 100.0},
                  {"name": "p5_async0_rr1", "status": "ok", "sps_window": 150.0},
                  {"name": "p5_async1_rr1", "status": "missing_binary"}]
        summary = bp.summarize(probes, {"x": 1}, "ref40_rr1")
        ratios = {r["name"]: r["sps_ratio_vs_baseline"] for r in summary["probes"]}
        self.assertAlmostEqual(ratios["p5_async0_rr1"], 1.5)
        self.assertIsNone(ratios["p5_async1_rr1"])


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, kind, temp, duration=6.0, rc=0, warmup=1.0, window=2.0, cmd=None):
        smi = fake_smi(self.dir, temp)
        out = os.path.join(self.dir, f"{kind}.json")
        metrics = os.path.join(self.dir, f"{kind}.metrics.jsonl")
        cmd = cmd or [sys.executable, PROBE, "fake-trainer", "--kind", kind,
                      "--duration", str(duration), "--interval", "0.2", "--rc", str(rc)]
        args = ["run", "--name", kind, "--kind", kind,
                "--log", os.path.join(self.dir, f"{kind}.log"), "--out", out,
                "--metrics-jsonl", metrics, "--cwd", self.dir,
                "--warmup", str(warmup), "--window", str(window), "--grace", "0.5",
                "--sample-interval", "0.5", "--poll", "0.1", "--kill-grace", "5",
                "--startup-timeout", "5", "--nvidia-smi", smi, "--"] + cmd
        rc_probe = bp.main(args)
        with open(out) as handle:
            return rc_probe, json.load(handle)

    def test_ref40_ok(self):
        rc, res = self._run("ref40", 45)
        self.assertEqual(rc, 0, res)
        self.assertEqual(res["status"], "ok")
        self.assertAlmostEqual(res["sps_window"], 100000.0, delta=15000.0)
        self.assertGreater(res["perf_ms_per_epoch"]["gpu_forward_ms"], 0)
        self.assertEqual(res["gpu_temp_max_c"], 45.0)
        self.assertEqual(res["kill_reason"], "sigterm")

    def test_p5_ok(self):
        rc, res = self._run("p5", 50)
        self.assertEqual(res["status"], "ok", res)
        self.assertAlmostEqual(res["sps_window"], 100000.0, delta=15000.0)
        self.assertIsNotNone(res["perf_ms_per_epoch"]["copy_ms"])

    def test_thermal_kill(self):
        rc, res = self._run("p5", 90)
        self.assertEqual(rc, 1)
        self.assertEqual(res["status"], "killed_thermal")
        self.assertIn("log_tail", res)

    def test_exited_early(self):
        rc, res = self._run("ref40", 45, duration=0.5, rc=3)
        self.assertEqual(res["status"], "exited_early")
        self.assertEqual(res["exit_code"], 3)

    def test_missing_binary(self):
        rc, res = self._run("p5", 45, cmd=["./puffer", "train"])
        self.assertEqual(res["status"], "missing_binary")

    def test_process_group_cleaned(self):
        marker = os.path.join(self.dir, "child.pid")
        script = (f"import os,subprocess,sys,time;"
                  f"c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
                  f"open({marker!r},'w').write(str(c.pid));"
                  f"os.execv(sys.executable,[sys.executable,{PROBE!r},'fake-trainer',"
                  f"'--kind','ref40','--duration','30','--interval','0.2'])")
        rc, res = self._run("ref40", 45, cmd=[sys.executable, "-c", script])
        self.assertEqual(res["status"], "ok", res)
        with open(marker) as handle:
            pid = int(handle.read())
        time.sleep(0.3)
        alive = subprocess.run(["ps", "-p", str(pid), "-o", "stat="],
                               capture_output=True, text=True).stdout.strip()
        self.assertTrue(alive == "" or alive.startswith("Z"), alive)

    def test_wait_cool(self):
        smi = fake_smi(self.dir, 70)
        self.assertEqual(bp.main(["wait-cool", "--below", "58", "--poll", "0.1",
                                  "--timeout", "0.3", "--nvidia-smi", smi]), 3)
        smi = fake_smi(self.dir, 40)
        self.assertEqual(bp.main(["wait-cool", "--below", "58", "--poll", "0.1",
                                  "--timeout", "5", "--nvidia-smi", smi]), 0)


if __name__ == "__main__":
    unittest.main()
