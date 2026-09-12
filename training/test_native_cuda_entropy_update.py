#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

import numpy as np

PATH = Path(__file__).with_name("verify_native_cuda_entropy_update.py")
SPEC = importlib.util.spec_from_file_location("native_entropy", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class NativeEntropyOracleTest(unittest.TestCase):
    def test_config_modes_are_explicit(self):
        self.assertEqual(MODULE.config(graphs=False, coefficient=.2,
                                       updates=20, learning_rate=0)["cudagraphs"], -1)
        self.assertEqual(MODULE.config(graphs=True, coefficient=.2,
                                       updates=20, learning_rate=0)["cudagraphs"], 10)

    def test_gradient_oracle_accepts_known_binary_case(self):
        def state(coefficient):
            logits = np.array([[[0.4, 0.0, 0.0]]], dtype=np.float32)
            mask = np.array([[[1, 1]]], dtype=np.float32)
            p = np.exp([.4, 0.0]); p /= p.sum()
            logp = np.log(p); entropy = -(p * logp).sum()
            dh = p * (-entropy - logp)
            grad = (-coefficient * dh).reshape(1, 1, 2).astype(np.float32)
            common = {name: np.zeros((1,), dtype=np.float32)
                      for name in MODULE.INVARIANTS}
            common.update(decoder_output=logits, mb_action_mask=mask,
                          act_sizes=np.array([2], dtype=np.int32))
            return {**common, "grad_logits": grad,
                    "entropy_coefficient": np.array([coefficient], dtype=np.float32)}
        signal, error = MODULE.expected_gradient_delta(state(.2), state(0.0))
        self.assertGreater(signal, 2e-7)
        self.assertLess(error, 1e-7)

    def test_independent_cosine_oracle(self):
        values = [MODULE.expected_coefficient(index, MODULE.BASE)
                  for index in range(MODULE.TOTAL_UPDATES)]
        self.assertEqual(values[0], np.float32(MODULE.BASE))
        self.assertTrue(all(left > right
                            for left, right in zip(values, values[1:])))
        self.assertGreater(values[-1], MODULE.BASE * MODULE.MIN_RATIO)


if __name__ == "__main__": unittest.main()
