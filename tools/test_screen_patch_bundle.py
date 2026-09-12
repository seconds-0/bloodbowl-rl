"""The frozen screen and per-arm launcher must bind every new trainer patch."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class PatchBundleTests(unittest.TestCase):
    def test_same_order_and_complete_september_semantics(self):
        screen = (ROOT / 'tools/run_reward_screen.sh').read_text()
        launcher = (ROOT / 'tools/run_reward_ablation.sh').read_text()
        screen_block = screen.split('patches = [', 1)[1].split('\n]', 1)[0]
        launch_block = launcher.split('PATCH_HASH="$({', 1)[1].split('} | sha256sum', 1)[0]
        screen_paths = re.findall(r'root / "(training/[^\"]+)"', screen_block)
        launch_paths = re.findall(r'sha256sum "\$ROOT/(training/[^\"]+)"', launch_block)
        self.assertEqual(screen_paths, launch_paths)
        self.assertEqual(len(screen_paths), len(set(screen_paths)))
        for name in ('puffer_rollout_transition_closure.patch',
                     'puffer_mingru_direct_recurrence_candidate.patch',
                     'puffer_entropy_schedule_parity.patch',
                     'puffer_native_entropy_diagnostics.patch',
                     'puffer_compact_qualification_snapshot.patch',
                     'puffer_terminal_aware_torch.patch',
                     'puffer_terminal_aware_native.patch'):
            self.assertIn('training/' + name, screen_paths)
        for relative in screen_paths:
            self.assertTrue((ROOT / relative).is_file(), relative)

        direct = 'training/puffer_mingru_direct_recurrence_candidate.patch'
        self.assertLess(screen_paths.index(direct), screen_paths.index(
            'training/puffer_recurrent_cuda_qualification.patch'))
        self.assertNotIn('training/puffer_dual_forward_qualification.patch', screen_paths)
        self.assertNotIn('training/puffer_mingru_direct_derivative_fixture.patch', screen_paths)


if __name__ == '__main__':
    unittest.main()
