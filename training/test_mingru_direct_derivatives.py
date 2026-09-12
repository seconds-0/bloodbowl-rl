import unittest
try:
    from training.verify_mingru_direct_derivatives import run
except ModuleNotFoundError:
    run = None

@unittest.skipIf(run is None, "Torch is unavailable in the source-tree Python")
class DirectMinGRUDerivativeTests(unittest.TestCase):
    def test_autograd_and_directional_derivatives_t1_t2_t7_t64(self):
        result = run()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual([case["T"] for case in result["cases"]], [1,2,7,64])
        self.assertTrue(result["hidden_zero_excluded"])
        self.assertAlmostEqual(result["hidden_zero_one_sided"]["left"], .25, places=7)
        self.assertAlmostEqual(result["hidden_zero_one_sided"]["right"], 1.0, places=7)
        self.assertEqual(result["negative_saturation_derivative"], 0.0)
        self.assertTrue(result["bf16_rounding_order"]["output_bits_match"])

if __name__ == "__main__": unittest.main()
