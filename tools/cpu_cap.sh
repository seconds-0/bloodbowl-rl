# tools/cpu_cap.sh — single source of truth for the CPU thread-pool cap (D59).
#
# SOURCE this (do NOT execute) before any `puffer train`/`puffer match`:
#     . "$(dirname "$0")/cpu_cap.sh"      # from a script in tools/
#     source /root/bloodbowl-rl/tools/cpu_cap.sh
#
# WHY (D59, measured): vast.ai boxes report VISIBLE logical CPUs via `nproc`
# (e.g. 255 on a 128-core HT box) but cap CPU TIME via cgroup CFS quota
# (e.g. 61 CPUs). With OMP_NUM_THREADS unset, PyTorch + OpenBLAS auto-size
# their intra-op pools to nproc, spawning hundreds of threads that thrash on
# the quota — a measured 5x SPS loss (114K vs 592K on identical configs).
# This caps the MATH-LIBRARY pools to the real quota. The env-stepping OMP
# is independent (PufferLib vec num_threads, explicit pragma) and untouched.
#
# Idempotent and safe on every box: derives the quota from cgroup v1 or v2,
# clamps to nproc, never below 1. Honors a pre-set OMP_NUM_THREADS (so you
# can override with `OMP_NUM_THREADS=N source cpu_cap.sh`-style env if ever
# needed) by only setting when unset.

bb_cpu_cap() {
    local q p quota np
    quota=0
    if [ -r /sys/fs/cgroup/cpu.max ]; then            # cgroup v2
        read -r q p < /sys/fs/cgroup/cpu.max
        [ "$q" != "max" ] && quota=$(( q / p ))
    fi
    if [ "${quota:-0}" -lt 1 ] && [ -r /sys/fs/cgroup/cpu/cpu.cfs_quota_us ]; then  # cgroup v1
        q=$(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us)
        p=$(cat /sys/fs/cgroup/cpu/cpu.cfs_period_us)
        [ "${q:-0}" -gt 0 ] && quota=$(( q / p ))
    fi
    np=$(nproc 2>/dev/null || echo 1)
    [ "${quota:-0}" -ge 1 ] || quota=$np
    [ "$quota" -gt "$np" ] && quota=$np
    : "${OMP_NUM_THREADS:=$quota}"
    export OMP_NUM_THREADS
    export OPENBLAS_NUM_THREADS="$OMP_NUM_THREADS"
    export MKL_NUM_THREADS="$OMP_NUM_THREADS"
    export NUMEXPR_NUM_THREADS="$OMP_NUM_THREADS"
    echo "cpu thread cap: $OMP_NUM_THREADS (nproc=$np, cgroup-quota-derived)" >&2
}
bb_cpu_cap
