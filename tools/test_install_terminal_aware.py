"""Focused installer contracts for the terminal-aware recurrent patch pair."""
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "tools" / "install_puffer_env.sh"


class TerminalAwareInstallerTests(unittest.TestCase):
    def test_patch_pair_is_mandatory_last_and_hashed(self):
        source = INSTALLER.read_text()
        torch_name = "puffer_terminal_aware_torch.patch"
        native_name = "puffer_terminal_aware_native.patch"
        torch_apply = source.index('TERMINAL_AWARE_TORCH_PATCH="$ROOT/training/')
        native_apply = source.index('TERMINAL_AWARE_NATIVE_PATCH="$ROOT/training/')
        generated_hash = source.index('EXACT_BACKEND_HASH="$(exact_backend_hash)"')
        self.assertIn(torch_name, source)
        self.assertIn(native_name, source)
        self.assertLess(torch_apply, native_apply)
        self.assertLess(native_apply, generated_hash)
        registry = (ROOT / "training" /
                    "puffer_compiled_backend_sources.txt").read_text().splitlines()
        for path in ("pufferlib/torch_pufferl.py", "src/models.cu",
                     "src/pufferlib.cu", "src/bindings.cu",
                     "src/bindings_cpu.cpp", "src/kernels.cu"):
            self.assertIn(path, registry)

    def test_check_requires_exact_pair_and_compiled_contract(self):
        source = INSTALLER.read_text()
        check = source[source.index('if [ "$MODE" = "check" ]; then'):
                       source.index('\nrm -rf "$DST"')]
        self.assertIn('puffer_terminal_aware_torch.patch', check)
        self.assertIn('puffer_terminal_aware_native.patch', check)
        self.assertIn('patch_reverse_checks_beneath_later', check)
        self.assertIn('terminal-aware-tbptt-v1', check)
        self.assertIn('compiled_rollout_transition_contract', check)
        self.assertIn('"terminal-aware-tbptt-v1"', check)


if __name__ == "__main__":
    unittest.main()
