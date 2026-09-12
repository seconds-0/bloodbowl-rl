"""Reject a shape-compatible runtime with the previous memory semantics."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import qualify_recurrent_cuda as qualification


class TerminalContractConsumerTests(unittest.TestCase):
    def identity(self, contract):
        return {
            'module': '/puffer/pufferlib/_C.so', 'puffer_root': '/puffer',
            'module_sha256': 'a' * 64, 'compiled_backend_sha256': 'b' * 64,
            'backend_sources_sha256': 'b' * 64, 'environment_sha256': 'c' * 64,
            'installed_snapshot_sha256': 'c' * 64, 'observation_abi': 'obs-v7',
            'observation_version': 7, 'action_abi': 'exact-joint-v1',
            'rollout_transition_contract': contract,
            'entropy_schedule_contract': qualification.ENTROPY_SCHEDULE_CONTRACT,
            'precision_bytes': 4, 'compiled_env': 'bloodbowl',
            'qualification_surface': True,
        }

    def test_old_memory_runtime_cannot_qualify_as_current(self):
        with self.assertRaisesRegex(qualification.QualificationError, 'rollout-transition'):
            qualification.validate_module_identity(self.identity('tail-bootstrap-v1'))

    def test_new_memory_runtime_can_pass_identity_gate_only(self):
        identity = self.identity('terminal-aware-tbptt-v1')
        self.assertEqual(qualification.validate_module_identity(identity), identity)


if __name__ == '__main__':
    unittest.main()
