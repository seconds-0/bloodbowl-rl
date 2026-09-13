import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("OMP_NUM_THREADS", "4")

import torch  # noqa: E402

torch.set_num_threads(4)

CHAIN25 = os.environ.get(
    "BBPLAY_CHECKPOINT",
    os.path.join(ROOT, ".play-artifacts", "checkpoints", "chain25", "0000002999975936.bin"))
PUFFER_MODELS = os.environ.get(
    "BBPLAY_PUFFER_MODELS",
    os.path.join(os.path.dirname(ROOT), "bloodbowl-rl", "vendor", "PufferLib", "pufferlib",
                 "models.py"))


@pytest.fixture(scope="session")
def lib():
    from play_harness import engine
    return engine.load_library()


@pytest.fixture(scope="session")
def chain25():
    if not os.path.exists(CHAIN25):
        pytest.skip(f"checkpoint not present: {CHAIN25}")
    from play_harness.policy import load_checkpoint
    return load_checkpoint(CHAIN25)


@pytest.fixture(scope="session")
def best_policy():
    """Chain 25 when present, else a seeded random policy of the same shape."""
    from play_harness.policy import load_checkpoint, random_policy
    if os.path.exists(CHAIN25):
        return load_checkpoint(CHAIN25)
    return random_policy(seed=1, scale=0.05), {"random_policy": True}
