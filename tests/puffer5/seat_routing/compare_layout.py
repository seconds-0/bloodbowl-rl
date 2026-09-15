#!/usr/bin/env python3
"""Compare the 5.0 port's league row layout with 4.0 selfplay.build_perm_tags.

Usage: compare_layout.py SELFPLAY40_PY P5_LAYOUT_OUTPUT TOTAL_AGENTS NUM_BUFFERS \
           NUM_FROZEN_BANKS FROZEN_BANK_PCT SCRIPTED_BANK_TAG

SELFPLAY40_PY is a copy of the live 4.0 pufferlib/selfplay.py; only the
build_perm_tags function is extracted (the module imports the native
extension). Checks, for every env: the same tag, the same physical row for
seat 0 and seat 1, the policy-slice boundaries, and that the scripted bank's
bot seats are exactly the rows of 5.0 frozen policy SCRIPTED_BANK_TAG.
"""
import ast
import sys

import numpy as np


def load_build_perm_tags(path):
    tree = ast.parse(open(path).read())
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "build_perm_tags")
    namespace = {"np": np}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), path, "exec"), namespace)
    return namespace["build_perm_tags"]


def main():
    sp_path, out_path = sys.argv[1], sys.argv[2]
    total, buffers, banks = int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
    pct, bot_tag = float(sys.argv[6]), int(sys.argv[7])
    apb = total // buffers
    frozen_size = int(apb * pct)  # team_size 1
    build = load_build_perm_tags(sp_path)
    perm, tags, _ = build(buffers, apb, 2, [frozen_size] * banks, total // 2)

    p5 = {}
    layout = None
    for line in open(out_path):
        parts = line.split()
        if parts[0] == "env":
            p5[int(parts[1])] = (int(parts[3]), int(parts[5]), int(parts[6]))
        elif parts[0] == "layout":
            layout = [int(x) for x in parts[1:]]
    failures = 0
    for e in range(total // 2):
        want = (int(tags[e]), int(perm[2 * e]), int(perm[2 * e + 1]))
        if p5.get(e) != want:
            failures += 1
            if failures <= 5:
                print(f"env {e}: 5.0 {p5.get(e)} != 4.0 {want}")
    want_layout = [0, apb - banks * frozen_size] + [
        apb - banks * frozen_size + (b + 1) * frozen_size for b in range(banks)]
    if layout != want_layout:
        failures += 1
        print(f"layout 5.0 {layout} != 4.0 bank slices {want_layout}")
    lo, hi = layout[bot_tag], layout[bot_tag + 1]
    bot_rows = sorted(r for e, (t, _, r) in p5.items() if t == bot_tag)
    slice_rows = sorted(b * apb + c for b in range(buffers) for c in range(lo, hi))
    if bot_rows != slice_rows:
        failures += 1
        print("scripted bank seats do not tile the skipped policy slice")
    print(f"envs={total // 2} banks={banks} per_bank_rows={frozen_size} "
          f"layout={layout} bot_seats={len(bot_rows)} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
