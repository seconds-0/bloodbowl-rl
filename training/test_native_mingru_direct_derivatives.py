import importlib.util, tempfile, unittest
from pathlib import Path
import numpy as np
MODULE_PATH=Path(__file__).with_name("verify_native_mingru_direct_derivatives.py")
SPEC=importlib.util.spec_from_file_location("native_mingru_runner",MODULE_PATH)
RUNNER=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(RUNNER)
class NativeMingruEvidenceTest(unittest.TestCase):
    def test_nonfinite_fails_after_raw_artifact_is_preserved(self):
        arrays={"combined":np.array([1.0,np.nan],dtype=np.float32)}
        with tempfile.TemporaryDirectory() as temporary:
            identity=RUNNER.persist_raw_case(temporary,2,1,arrays)
            with self.assertRaisesRegex(RuntimeError,"non-finite"): RUNNER.require_finite_arrays(arrays,"native")
            artifact=Path(identity["path"]); self.assertTrue(artifact.is_file()); self.assertEqual(identity["sha256"],RUNNER.q.sha256(artifact))
            with np.load(artifact) as retained: self.assertTrue(np.isnan(retained["combined"][1]))
if __name__=="__main__": unittest.main()
