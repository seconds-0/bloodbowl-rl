#!/usr/bin/env python3
"""tools/install_puffer_env.sh must upgrade an installed v1 scripted guard.

The scripted-training guard patch was revised for scripted_bank_tag. Its first
hunk occupies the same lines as the previous revision, so a vendored tree that
already carries the v1 guard can neither take the new patch nor pass its
reverse-check. The installer keeps the retired revision as
training/pufferl_scripted_training_guard.v1.patch, reverse-applies it when it
is what the tree holds, then applies the new one. These tests build a
synthetic pufferlib/pufferl.py from the patches' own context lines (no
vendored tree exists on a Mac checkout) and drive the installer's guard/warm
block and its --check counterpart through the three tree states: fresh,
old-guard, new-guard.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "tools/install_puffer_env.sh"
GUARD = ROOT / "training/pufferl_scripted_training_guard.patch"
GUARD_V1 = ROOT / "training/pufferl_scripted_training_guard.v1.patch"
WARM = ROOT / "training/pufferl_warm_start.patch"


def old_side_hunks(patch_path):
    """[(old_start, [old-side lines])] for a unified diff of one file."""
    hunks = []
    current = None
    for line in patch_path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^@@ -(\d+),\d+ \+\d+,\d+ @@", line)
        if match:
            current = (int(match.group(1)), [])
            hunks.append(current)
            continue
        if current is None:
            continue
        if line.startswith(" ") or line.startswith("-"):
            current[1].append(line[1:])
        elif line == "":
            current[1].append("")
    return hunks


def synthetic_pufferl():
    """Reconstruct the pre-patch pufferl.py regions both patches touch."""
    hunks = sorted(old_side_hunks(GUARD) + old_side_hunks(WARM))
    body = []
    line_number = 1
    for start, lines in hunks:
        while line_number < start:
            body.append(f"# filler {line_number}")
            line_number += 1
        body.extend(lines)
        line_number += len(lines)
    body.append("# tail")
    text = "\n".join(body) + "\n"
    assert "require_training_state_reset" in text
    return text


def installer_block(start_marker, end_marker):
    source = INSTALLER.read_text(encoding="utf-8")
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


class InstallGuardPatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.puffer = pathlib.Path(self.temp.name) / "PufferLib"
        (self.puffer / "pufferlib").mkdir(parents=True)
        self.pufferl = self.puffer / "pufferlib/pufferl.py"
        self.pufferl.write_text(synthetic_pufferl(), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def git_apply(self, patch, *flags):
        return subprocess.run(
            ["git", "-C", str(self.puffer), "apply", *flags, "--no-index",
             str(patch)], text=True, capture_output=True, check=False)

    def run_install_block(self):
        block = installer_block(
            "if grep -Fq 'require_training_state_reset' "
            "\"$PUFFER/pufferlib/pufferl.py\" 2>/dev/null; then",
            "\nEXACT_BACKEND_HASH=")
        return subprocess.run(
            ["bash", "-c", "set -euo pipefail\n" + block],
            env={"ROOT": str(ROOT), "PUFFER": str(self.puffer),
                 "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
            text=True, capture_output=True, check=False)

    def run_check_block(self):
        block = installer_block(
            "    # The two local pufferl.py patches (scripted-training guard, "
            "warm start)",
            "\n    # D234: BOTH backends")
        return subprocess.run(
            ["bash", "-c", "set -euo pipefail\n" + block],
            env={"ROOT": str(ROOT), "PUFFER": str(self.puffer),
                 "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
            text=True, capture_output=True, check=False)

    def assert_new_guard_installed(self):
        self.assertEqual(self.git_apply(GUARD, "--reverse", "--check").returncode, 0)
        self.assertEqual(self.git_apply(WARM, "--reverse", "--check").returncode, 0)
        self.assertNotEqual(
            self.git_apply(GUARD_V1, "--reverse", "--check").returncode, 0)
        text = self.pufferl.read_text(encoding="utf-8")
        self.assertIn("scripted_bank_tag", text)
        self.assertEqual(text.count("def guard_scripted_training"), 1)
        self.assertEqual(text.count("Warm-started training from"), 1)
        check = self.run_check_block()
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_v1_patch_is_the_retired_revision(self):
        # The v1 file is exactly what shipped before, and it differs from the
        # new one only in the guard body (same context, same call sites).
        v1 = GUARD_V1.read_text(encoding="utf-8")
        self.assertIn("@@ -204,6 +204,26 @@", v1)
        self.assertNotIn("scripted_bank_tag", v1)
        self.assertIn("scripted_bank_tag", GUARD.read_text(encoding="utf-8"))
        self.assertEqual(
            [lines for _, lines in old_side_hunks(GUARD_V1)],
            [lines for _, lines in old_side_hunks(GUARD)])

    def test_fresh_tree_gets_the_new_guard(self):
        result = self.run_install_block()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("reversed:", result.stdout)
        self.assertIn("applied:   pufferl_scripted_training_guard.patch", result.stdout)
        self.assertIn("applied:   pufferl_warm_start.patch", result.stdout)
        self.assert_new_guard_installed()

    def test_old_guard_tree_is_upgraded_in_place(self):
        self.assertEqual(self.git_apply(GUARD_V1).returncode, 0)
        self.assertEqual(self.git_apply(WARM).returncode, 0)
        # Before: the drift check names the stale guard.
        stale = self.run_check_block()
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("local pufferl.py patch is missing or stale", stale.stderr)
        self.assertIn("pufferl_scripted_training_guard.patch", stale.stderr)
        result = self.run_install_block()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reversed:  pufferl_scripted_training_guard.v1.patch",
                      result.stdout)
        self.assertIn("applied:   pufferl_scripted_training_guard.patch", result.stdout)
        self.assertNotIn("applied:   pufferl_warm_start.patch", result.stdout)
        self.assert_new_guard_installed()

    def test_new_guard_tree_is_idempotent(self):
        first = self.run_install_block()
        self.assertEqual(first.returncode, 0, first.stderr)
        before = self.pufferl.read_bytes()
        second = self.run_install_block()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("reversed:", second.stdout)
        self.assertNotIn("applied:", second.stdout)
        self.assertEqual(self.pufferl.read_bytes(), before)
        self.assert_new_guard_installed()

    def test_installer_wires_v1_reverse_and_check_verifies_both_patches(self):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('GUARD_V1_PATCH="$ROOT/training/pufferl_scripted_training_guard.v1.patch"',
                      source)
        self.assertIn('git -C "$PUFFER" apply --reverse --no-index "$GUARD_V1_PATCH"',
                      source)
        check = installer_block('if [ "$MODE" = "check" ]; then',
                                "\n# Record the source content hash")
        self.assertIn('"$ROOT/training/pufferl_scripted_training_guard.patch" \\\n'
                      '            "$ROOT/training/pufferl_warm_start.patch"; do',
                      check)
        self.assertIn("local pufferl.py patch is missing or stale", check)


if __name__ == "__main__":
    unittest.main()
