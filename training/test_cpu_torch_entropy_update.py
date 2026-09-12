#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import unittest


PATH = Path(__file__).with_name("verify_cpu_torch_entropy_update.py")
SPEC = importlib.util.spec_from_file_location("entropy_update", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class EntropyUpdateOracleTest(unittest.TestCase):
    def test_schedule_endpoints_and_order(self):
        points = [MODULE.expected_schedule(i, MODULE.BASE_COEFFICIENT)
                  for i in MODULE.UPDATE_INDICES]
        self.assertAlmostEqual(points[0], MODULE.BASE_COEFFICIENT, places=7)
        self.assertGreater(points[0], points[1])
        self.assertGreater(points[1], points[2])
        self.assertGreater(points[2], MODULE.BASE_COEFFICIENT * MODULE.MIN_RATIO)

    def test_entropy_derivative_has_update_toward_uniform(self):
        p = 1.0 / (1.0 + math.exp(-MODULE.THETA))
        derivative = p * (1 - p) * math.log((1 - p) / p)
        self.assertLess(derivative, 0.0)
        self.assertLess(MODULE.LEARNING_RATE * MODULE.BASE_COEFFICIENT * derivative, 0.0)


if __name__ == "__main__":
    unittest.main()
