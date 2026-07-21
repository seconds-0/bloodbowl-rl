#!/usr/bin/env python3
"""Exercise the trusted timeout and output bounds against hostile processes."""

from __future__ import annotations

import sys

import verify_candidate
import verify_history


def require_rejected(call, expected: str) -> None:
    try:
        call()
    except RuntimeError as error:
        if expected not in str(error):
            raise RuntimeError(f"wrong isolation rejection: {error}") from error
    else:
        raise RuntimeError(f"isolation self-test accepted: {expected}")


def main() -> int:
    quiet = [sys.executable, "-c", "pass"]
    noisy = [
        sys.executable, "-c",
        f"import os; os.write(1,b'x'*{verify_candidate.MAX_COMMAND_OUTPUT_BYTES + 1})",
    ]
    slow = [sys.executable, "-c", "import time; time.sleep(60)"]
    verify_candidate.run(quiet, timeout=5)
    require_rejected(
        lambda: verify_candidate.run(noisy, timeout=10),
        "bounded output allowance",
    )
    require_rejected(
        lambda: verify_candidate.run(slow, timeout=1),
        "command exceeded 1s",
    )

    outer_noisy = [
        sys.executable, "-c",
        f"import os; os.write(1,b'x'*{verify_history.MAX_VERIFIER_OUTPUT_BYTES + 1})",
    ]
    verify_history.run_process(quiet, timeout=5)
    require_rejected(
        lambda: verify_history.run_process(outer_noisy, timeout=10),
        "bounded output allowance",
    )
    require_rejected(
        lambda: verify_history.run_process(slow, timeout=1),
        "command exceeded 1.0s",
    )
    print("sidecar verifier isolation self-tests passed: 6")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
