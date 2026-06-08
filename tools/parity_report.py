#!/usr/bin/env python3
"""parity_report.py — native-vs-torch A/B verdict harness (D57).

Compares two PufferLib training logs (the rich dashboard output captured to a
file) and prints a matched-step comparison table, SPS ratio, per-metric
verdicts, and wall-clock-to-target-tds projections. Pure stdlib, no deps.

CURRENT A/B (the D57 native-asym parity question):
    LOG A (native): /tmp/profile-v4-native-asym.log on box-1 (bb-japan-native)
        native CUDA backend, no bc aux, frozen bc_v4 teacher via 1-seed league
        pool, ~2.1M SPS.
    LOG B (torch):  /tmp/profile-v4-s2.log on bb-ballhawk (box-3)
        torch flagship v4_s2, maxdist 9, ~0.6M SPS.

Fetch the FULL logs to your Mac first (key ~/.ssh/id_ed25519). Full files,
not tail slices: a tail of A and a tail of B usually cover DIFFERENT step
windows, so the matched-step table comes up empty.

    scp -i ~/.ssh/id_ed25519 -P 12464 root@ssh3.vast.ai:/tmp/profile-v4-native-asym.log /tmp/native.log
    scp -i ~/.ssh/id_ed25519 -P 25430 root@ssh4.vast.ai:/tmp/profile-v4-s2.log /tmp/torch.log

Mac->ssh4 can be pathologically slow. If the second scp crawls, hop via
box-1 instead (3 commands; the -A hop needs the key in your agent):

    ssh-add ~/.ssh/id_ed25519
    ssh -A -i ~/.ssh/id_ed25519 -p 12464 root@ssh3.vast.ai \
        "scp -o StrictHostKeyChecking=no -P 25430 root@ssh4.vast.ai:/tmp/profile-v4-s2.log /tmp/torch.log"
    scp -i ~/.ssh/id_ed25519 -P 12464 root@ssh3.vast.ai:/tmp/torch.log /tmp/torch.log

Then:

    tools/parity_report.py /tmp/native.log /tmp/torch.log
    # or, if the exec bit got lost in transit:
    python3 tools/parity_report.py /tmp/native.log /tmp/torch.log

READING THE VERDICT (metric semantics, see CLAUDE.md / training-experiments):
  - tds: per-episode TDs FROM CURRICULUM STARTS. Only comparable because both
    arms run demo-endzone-maxdist 9; do NOT feed logs from different stages.
    Higher = better. PARITY within the band = the 3.5x SPS lever ships.
  - block_2dred_frac: fraction of blocks thrown at 2-dice-against. LOWER =
    better (falling = probability planes working; human 0.017). The native arm
    reading ~0.105 vs torch ~0.20 would be a major finding, not a regression.
  - gfi_attempts: informational/artifact per D46 (human 2-5/ep, agent 25-35)
    unless tournament-grounded. Lower = nominally better; weigh lightly.
  - Step counts are parsed from the dashboard's abbreviated display (e.g.
    "1.8B"), so alignment granularity is ~100M at B scale — well within the
    default 200M match tolerance.

CAVEATS for the successor:
  - The asymmetric native run overshoots total steps ~1.5x (known, benign).
  - tds parity at matched STEPS is the question; the native arm wins wall-clock
    regardless (see the per-1B wall-cost lines).
  - This reads the live dashboard frames, so a freshly relaunched log restarts
    at low steps (warm-start reloads weights but global_step resets). The
    report detects step-count regressions, warns, and uses only the final
    monotonic segment for SPS/projections; the matched-step table still uses
    everything. For a clean read, pass only the segment you want judged.

VERIFIED 2026-06-08 against the live logs on box-1/box-3 (682- and 479-frame
tails parsed; tds/block_2dred_frac/gfi_attempts/SPS all matched the dashboard)
and against rich-rendered synthetic fixtures at width 80 (no color, redirected
output) and 120 (tmux capture). Metric names are the binding.c my_log keys as
displayed by pufferl.py print_dashboard (env/ prefix stripped, %.3f).
"""
import argparse
import math
import re
import statistics
import sys

ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07')
MULT = {'': 1.0, 'K': 1e3, 'M': 1e6, 'B': 1e9, 'T': 1e12}

STEPS_RE = re.compile(r'(?<![\w/])Steps\s+([0-9]+(?:\.[0-9]+)?)\s*([KMBT]?)(?![\w.])')
SPS_RE = re.compile(r'(?<![\w/])SPS\s+([0-9]+(?:\.[0-9]+)?)\s*([KMBT]?)(?![\w.])')
USER_METRICS = ('tds', 'block_2dred_frac', 'gfi_attempts')
USER_RES = {m: re.compile(r'(?<![\w/])' + re.escape(m) + r'\s+(-?[0-9]+\.[0-9]+)')
            for m in USER_METRICS}

# (display_name, higher_is_better, note)
VERDICT_SPEC = [
    ('tds', True, 'curriculum-start TDs'),
    ('block_2dred_frac', False, 'lower = planes working'),
    ('gfi_attempts', False, 'informational (D46 artifact)'),
]


def parse_log(path):
    """Return list of frame dicts: {'steps','sps','tds',...} in file order."""
    with open(path, 'r', errors='replace') as f:
        text = f.read()
    text = ANSI_RE.sub('', text).replace('\r', '\n')

    frames = []
    cur = None
    for line in text.split('\n'):
        m = STEPS_RE.search(line)
        if m:
            if cur is not None and cur.get('steps', 0) > 0:
                frames.append(cur)
            cur = {'steps': float(m.group(1)) * MULT[m.group(2)]}
            continue
        if cur is None:
            continue
        m = SPS_RE.search(line)
        if m and 'sps' not in cur:
            cur['sps'] = float(m.group(1)) * MULT[m.group(2)]
        for name, rx in USER_RES.items():
            if name not in cur:
                m2 = rx.search(line)
                if m2:
                    cur[name] = float(m2.group(1))
    if cur is not None and cur.get('steps', 0) > 0:
        frames.append(cur)
    # Drop frames with no metrics at all beyond steps (startup banners etc.)
    return [fr for fr in frames if len(fr) > 1]


def final_segment(frames):
    """(n_restarts, frames after the last steps regression).

    The dashboard's abbreviated step display is monotone non-decreasing for a
    single run, so any strict decrease means the box was relaunched and the
    log keeps both runs. Trend/SPS math should only see the final run.
    """
    start, restarts = 0, 0
    for i in range(1, len(frames)):
        if frames[i]['steps'] < frames[i - 1]['steps']:
            start, restarts = i, restarts + 1
    return restarts, frames[start:]


def nearest_frame(frames, target, tol):
    """Frame whose steps is closest to target within tol, preferring later."""
    best, best_d = None, None
    for fr in frames:
        d = abs(fr['steps'] - target)
        if d <= tol and (best_d is None or d <= best_d):
            best, best_d = fr, d
    return best


def median_sps(frames, tail=50):
    vals = [fr['sps'] for fr in frames if fr.get('sps', 0) > 0]
    if not vals:
        return 0.0
    return statistics.median(vals[-tail:])


def fmt_steps(s):
    if s >= 1e9:
        return f'{s / 1e9:.1f}B'
    if s >= 1e6:
        return f'{s / 1e6:.0f}M'
    return f'{s:.0f}'


def fmt_val(fr, key):
    if fr is None or key not in fr:
        return '--'
    return f'{fr[key]:.3f}'


def fmt_dur(seconds):
    if seconds < 0 or math.isinf(seconds) or math.isnan(seconds):
        return 'n/a'
    h = seconds / 3600.0
    if h < 1:
        return f'{seconds / 60:.0f}m'
    if h < 48:
        return f'{h:.1f}h'
    return f'{h / 24:.1f}d'


def linfit(xs, ys):
    """Least-squares slope/intercept; returns (m, b) or None."""
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    m = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return m, my - m * mx


def project_to_target(frames, target, sps):
    """(description string) for wall-clock to reach target tds."""
    pts = [(fr['steps'], fr['tds']) for fr in frames if 'tds' in fr]
    if len(pts) < 5:
        return 'insufficient tds samples (<5)'
    cur_tds = statistics.mean(v for _, v in pts[-3:])
    cur_steps = pts[-1][0]
    if cur_tds >= target:
        return f'already at target (tds {cur_tds:.3f} >= {target:.2f})'
    # Fit the most recent half of the series (>=5 points) for local trend.
    tail = pts[max(len(pts) // 2, len(pts) - 200):]
    if len(tail) < 5:
        tail = pts[-5:]
    fit = linfit([p[0] for p in tail], [p[1] for p in tail])
    if fit is None or fit[0] <= 1e-15:
        return (f'no upward tds trend in recent window '
                f'(now {cur_tds:.3f}, target {target:.2f}) — not projectable')
    m, b = fit
    steps_at_target = (target - b) / m
    remaining = steps_at_target - cur_steps
    if remaining <= 0:
        return f'trend says target imminent (now {cur_tds:.3f})'
    if sps <= 0:
        return f'+{fmt_steps(remaining)} steps needed, but no SPS parsed'
    return (f'+{fmt_steps(remaining)} steps -> ~{fmt_dur(remaining / sps)} '
            f'wall-clock (now {cur_tds:.3f}, slope {m * 1e9:.3f}/B, '
            f'sps {sps / 1e6:.2f}M)')


def main():
    ap = argparse.ArgumentParser(
        description='Native-vs-torch parity verdict from two training logs.')
    ap.add_argument('log_a', help='log A (native arm), local path')
    ap.add_argument('log_b', help='log B (torch arm), local path')
    ap.add_argument('--label-a', default=None, help='display label for log A')
    ap.add_argument('--label-b', default=None, help='display label for log B')
    ap.add_argument('--interval', type=float, default=1e9,
                    help='comparison grid spacing in steps (default 1e9)')
    ap.add_argument('--tolerance', type=float, default=2e8,
                    help='max |steps - gridpoint| to count as matched (default 2e8)')
    ap.add_argument('--parity-band', type=float, default=15.0,
                    help='PARITY if |relative delta| <= this percent (default 15)')
    ap.add_argument('--target-tds', type=float, default=0.45,
                    help='tds level for the wall-clock projection (default 0.45, '
                         'the v4_s1_final band)')
    args = ap.parse_args()

    la = args.label_a or re.sub(r'\.log$', '', args.log_a.split('/')[-1])
    lb = args.label_b or re.sub(r'\.log$', '', args.log_b.split('/')[-1])

    fa = parse_log(args.log_a)
    fb = parse_log(args.log_b)
    for label, frames, path in ((la, fa, args.log_a), (lb, fb, args.log_b)):
        if not frames:
            sys.exit(f'ERROR: no dashboard frames parsed from {path} ({label}). '
                     f'Is this a puffer train log?')

    # Trend/SPS math must only see the final run if the box was relaunched
    # mid-log; the matched-step grid still uses every frame (old coverage
    # is real coverage).
    restarts_a, seg_a = final_segment(fa)
    restarts_b, seg_b = final_segment(fb)
    min_a = min(fr['steps'] for fr in fa)
    min_b = min(fr['steps'] for fr in fb)
    max_a = max(fr['steps'] for fr in fa)
    max_b = max(fr['steps'] for fr in fb)
    sps_a, sps_b = median_sps(seg_a), median_sps(seg_b)

    print('=' * 78)
    print('PARITY REPORT  (native-asym vs torch — D57 verdict harness)')
    print('=' * 78)
    print(f'A = {la:<24} frames {len(fa):>5}  covers {fmt_steps(min_a):>7} - '
          f'{fmt_steps(max_a):>7}  median SPS {sps_a / 1e6:.2f}M')
    print(f'B = {lb:<24} frames {len(fb):>5}  covers {fmt_steps(min_b):>7} - '
          f'{fmt_steps(max_b):>7}  median SPS {sps_b / 1e6:.2f}M')
    for label, n, seg in ((la, restarts_a, seg_a), (lb, restarts_b, seg_b)):
        if n:
            print(f'  WARNING: {label} has {n} step-count regression(s) — box '
                  f'relaunch(es) in-log. SPS/projection use only the final '
                  f'{len(seg)}-frame segment (from '
                  f'{fmt_steps(seg[0]["steps"])}); slice the log for a clean read.')

    # (a) matched-step table
    grid = []
    g = args.interval
    while g <= max(max_a, max_b) + args.tolerance:
        grid.append(g)
        g += args.interval

    hdr = (f'{"Steps":>7} |'
           + ''.join(f' {"A " + m:>19} {"B " + m:>19} |' for m in USER_METRICS))
    print('\n(a) MATCHED-STEP COMPARISON (grid '
          f'{fmt_steps(args.interval)}, tol {fmt_steps(args.tolerance)})')
    print(hdr)
    print('-' * len(hdr))
    matched = []  # (gridpoint, frame_a, frame_b)
    for gp in grid:
        ra = nearest_frame(fa, gp, args.tolerance)
        rb = nearest_frame(fb, gp, args.tolerance)
        if ra is None and rb is None:
            continue  # outside both logs' coverage; don't print -- spam
        if ra is not None and rb is not None:
            matched.append((gp, ra, rb))
        row = f'{fmt_steps(gp):>7} |'
        for m in USER_METRICS:
            row += f' {fmt_val(ra, m):>19} {fmt_val(rb, m):>19} |'
        print(row)
    if not matched:
        print(f'  (no gridpoint covered by BOTH logs: A covers '
              f'{fmt_steps(min_a)}-{fmt_steps(max_a)}, B covers '
              f'{fmt_steps(min_b)}-{fmt_steps(max_b)}. If these windows are '
              f'disjoint you probably fetched tail slices — fetch the FULL '
              f'logs and re-run.)')

    # (b) SPS ratio
    print('\n(b) THROUGHPUT')
    if sps_b > 0:
        print(f'  A SPS {sps_a / 1e6:.2f}M   B SPS {sps_b / 1e6:.2f}M   '
              f'ratio A/B = {sps_a / sps_b:.2f}x')
    else:
        print('  B SPS unparseable')
    if sps_a > 0 and sps_b > 0:
        print(f'  wall-clock per 1B steps:  A {fmt_dur(1e9 / sps_a)}   '
              f'B {fmt_dur(1e9 / sps_b)}')

    # (c) verdicts at the latest matched gridpoint
    print(f'\n(c) VERDICTS (at latest matched step, parity band '
          f'+/-{args.parity_band:.0f}%)')
    if not matched:
        print('  NO VERDICT — no overlapping matched steps. Re-run when both '
              'logs cover a common gridpoint.')
    else:
        for name, higher_better, note in VERDICT_SPEC:
            pt = next(((gp, ra, rb) for gp, ra, rb in reversed(matched)
                       if name in ra and name in rb), None)
            if pt is None:
                print(f'  {name:<18} NO DATA in both logs')
                continue
            gp, ra, rb = pt
            va, vb = ra[name], rb[name]
            if vb == 0:
                rel = math.inf if va != 0 else 0.0
            else:
                rel = 100.0 * (va - vb) / abs(vb)
            if abs(rel) <= args.parity_band:
                verdict = 'PARITY'
            else:
                good = (rel > 0) == higher_better
                verdict = 'A AHEAD' if good else 'A BEHIND'
            arrow = 'higher=better' if higher_better else 'lower=better'
            print(f'  {name:<18} {verdict:<9} @ {fmt_steps(gp):>5}  '
                  f'A {va:.3f} vs B {vb:.3f}  '
                  f'delta {rel:+.1f}%  ({arrow}; {note})')

    # (d) wall-clock projections
    print(f'\n(d) WALL-CLOCK TO tds >= {args.target_tds:.2f}')
    print(f'  A ({la}): {project_to_target(seg_a, args.target_tds, sps_a)}')
    print(f'  B ({lb}): {project_to_target(seg_b, args.target_tds, sps_b)}')
    print('=' * 78)


if __name__ == '__main__':
    main()
