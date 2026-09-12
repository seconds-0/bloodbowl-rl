"""Exercise the real overlapping-patch checker against immutable source files."""
import pathlib
import subprocess
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).with_name('install_puffer_env.sh')


class PatchShadowTests(unittest.TestCase):
    @staticmethod
    def _function_command():
        text = SCRIPT.read_text()
        function = text[text.index('patch_reverse_checks_beneath_later() {'):
                        text.index('\nif [ "$MODE" = "check" ]; then')]
        return (function +
                '\nPUFFER="$1"\nshift\n'
                'if patch_reverse_checks_beneath_later "$@"; then '
                'exit 0; else exit 1; fi\n')

    @staticmethod
    def _patch(path, rel, before, after):
        path.write_text(
            f'diff --git a/{rel} b/{rel}\n'
            f'--- a/{rel}\n+++ b/{rel}\n'
            f'@@ -1 +1 @@\n-{before}\n+{after}\n')

    def test_readonly_overlap_is_quiet_and_tampering_still_rejects(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            vendor = root / 'vendor'
            vendor.mkdir()
            source = vendor / 'same.txt'
            source.write_text('second\n')
            source.chmod(0o444)
            patches = []
            for index, before, after in [(1, 'original', 'first'), (2, 'first', 'second')]:
                patch = root / f'p{index}.patch'
                patch.write_text(f'diff --git a/same.txt b/same.txt\n--- a/same.txt\n+++ b/same.txt\n@@ -1 +1 @@\n-{before}\n+{after}\n')
                patches.append(patch)
            command = self._function_command()
            args = ['bash', '-c', command, 'test', str(vendor), *map(str, patches)]
            result = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            self.assertEqual(source.read_text(), 'second\n')
            self.assertEqual(source.stat().st_mode & 0o222, 0)
            source.chmod(0o644)
            source.write_text('tampered\n')
            source.chmod(0o444)
            rejected = subprocess.run(args, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)

    def test_strips_multiple_later_patches_in_reverse_install_order(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            vendor = root / 'vendor'
            vendor.mkdir()
            source = vendor / 'same.txt'
            source.write_text('third\n')
            source.chmod(0o444)
            patches = []
            for index, before, after in [
                    (1, 'original', 'first'),
                    (2, 'first', 'second'),
                    (3, 'second', 'third')]:
                patch = root / f'p{index}.patch'
                self._patch(patch, 'same.txt', before, after)
                patches.append(patch)
            args = ['bash', '-c', self._function_command(), 'test',
                    str(vendor), *map(str, patches)]
            result = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(source.read_text(), 'third\n')
            self.assertEqual(source.stat().st_mode & 0o222, 0)

    def test_later_nonoverlapping_paths_are_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            vendor = root / 'vendor'
            vendor.mkdir()
            (vendor / 'earlier.txt').write_text('installed\n')
            (vendor / 'later.txt').write_text('later-installed\n')
            earlier = root / 'earlier.patch'
            later = root / 'later.patch'
            self._patch(earlier, 'earlier.txt', 'base', 'installed')
            self._patch(later, 'later.txt', 'later-base', 'later-installed')
            args = ['bash', '-c', self._function_command(), 'test',
                    str(vendor), str(earlier), str(later)]
            result = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((vendor / 'later.txt').read_text(), 'later-installed\n')


if __name__ == '__main__':
    unittest.main()
