#!/usr/bin/env python3
"""CPU-only tests for the CUDA library contract in tools/puffer5/bench_queue.sh."""
import os
import re
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(HERE, "bench_queue.sh")
NV = "/venv/nvidia"
CUDA_LIBS = ("libcudart.so.12", "libcublas.so.12", "libcublasLt.so.12", "libcusolver.so.11",
             "libcurand.so.10", "libcusparse.so.12", "libnvJitLink.so.12", "libnccl.so.2")


def queue_text():
    with open(QUEUE) as handle:
        return handle.read()


def libs_check_function():
    match = re.search(r"^p5_libs_check\(\) \{.*?^\}$", queue_text(), re.S | re.M)
    if match is None:
        raise AssertionError("bench_queue.sh defines no p5_libs_check function")
    return match.group(0)


def run_libs_check(ldd_lines, ldd_rc=0):
    with tempfile.TemporaryDirectory() as tmp:
        fake = os.path.join(tmp, "ldd")
        with open(fake, "w") as handle:
            handle.write("#!/bin/sh\ncat <<'EOF'\n" + "\n".join(ldd_lines) + "\nEOF\n")
            handle.write(f"exit {ldd_rc}\n")
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        script = "\n".join([
            f"NV={NV}", "P5=/p5", "P5_LD_LIBRARY_PATH=unused",
            'log() { echo "$*"; }', libs_check_function(), "p5_libs_check",
        ])
        env = dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"])
        return subprocess.run(["bash", "-c", script], env=env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def venv_lines():
    return [f"\t{lib} => {NV}/pkg/lib/{lib} (0x00007f0000000000)" for lib in CUDA_LIBS] + [
        "\tlibc.so.6 => /usr/lib/x86_64-linux-gnu/libc.so.6 (0x00007f0000000000)",
        "\tlibomp.so.5 => /usr/lib/x86_64-linux-gnu/libomp.so.5 (0x00007f0000000000)",
    ]


class LibraryPathContractTests(unittest.TestCase):
    def test_p5_library_path_lists_only_venv_directories_runtime_first(self):
        match = re.search(r"^P5_LD_LIBRARY_PATH=(\S+)$", queue_text(), re.M)
        self.assertIsNotNone(match)
        entries = match.group(1).split(":")
        self.assertEqual(entries[0], "$NV/cuda_runtime/lib")
        self.assertIn("$NV/cublas/lib", entries)
        for entry in entries:
            self.assertTrue(entry.startswith("$NV/") or entry == "$NCCL_LIB", entry)
        self.assertNotIn("${LD_LIBRARY_PATH", match.group(1))

    def test_p5_probe_uses_the_venv_path_without_inheriting_the_caller(self):
        body = re.search(r"^probe_p5\(\) \{.*?^\}$", queue_text(), re.S | re.M).group(0)
        self.assertIn('"LD_LIBRARY_PATH=$P5_LD_LIBRARY_PATH"', body)
        self.assertNotIn("${LD_LIBRARY_PATH", body)

    def test_libs_check_runs_before_any_probe_outside_dry_run(self):
        text = queue_text()
        check = text.index('[ "$DRY_RUN" != 1 ] && ! p5_libs_check')
        self.assertLess(check, text.index("\nprobe_ref40 ref40_rr1"))
        self.assertIn("exit 7", text[check:check + 200])

    def test_libs_check_accepts_venv_resolution(self):
        result = run_libs_check(venv_lines())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_libs_check_rejects_system_cublaslt(self):
        lines = venv_lines()
        lines[2] = "\tlibcublasLt.so.12 => /usr/lib/x86_64-linux-gnu/libcublasLt.so.12 (0x0)"
        result = run_libs_check(lines)
        self.assertEqual(result.returncode, 1)
        self.assertIn("libcublasLt.so.12", result.stdout)

    def test_libs_check_rejects_missing_library(self):
        lines = venv_lines()
        lines[7] = "\tlibnccl.so.2 => not found"
        result = run_libs_check(lines)
        self.assertEqual(result.returncode, 1)
        self.assertIn("libnccl.so.2", result.stdout)

    def test_libs_check_rejects_ldd_failure(self):
        result = run_libs_check(["\tnot a dynamic executable"], ldd_rc=1)
        self.assertEqual(result.returncode, 1)

    def test_libs_check_rejects_a_sibling_directory_sharing_the_prefix(self):
        lines = venv_lines()
        lines[0] = f"\tlibcudart.so.12 => {NV}-old/lib/libcudart.so.12 (0x0)"
        result = run_libs_check(lines)
        self.assertEqual(result.returncode, 1)
        self.assertIn("libcudart.so.12", result.stdout)


if __name__ == "__main__":
    unittest.main()
