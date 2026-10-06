#!/usr/bin/env bash
# Stage b3_identity of campaign longrun-20261002: qualify the b3 build before anything trains on it.
# Not a training stage. Used as the `launch` body of a tools/campaign_supervisor.py stage, or by hand.
#
# What it does, in order:
#   1. Terminal check: a pass marker for THIS build exits 0 at once; one for another build exits 4.
#   2. CPU checks: the install drift check, the venv entrypoint, the inputs' sha256, the pool identity.
#   3. Takes the shared GPU lock on fd 7 the way tools/chain_stage.sh does, and waits for it without limit.
#   4. Flag OFF: chain 42's first 382 epochs (50,069,504 steps) from chain 42's exact trainer arguments,
#      chain 41 warm, a copy of pool cc9b201e as the league preseed (tools/probe_train_identity.py).
#   5. Flag ON: a rollout trace of whole games (tools/probe_scripted_bank_skip.py trace), then 24 epochs of
#      rollout + PPO at the full layout with the real pool.
#   6. Verdict: the two saved weight files must be byte-equal to chain 42's stored checkpoints at 131,072 and
#      50,069,504 steps; the flag-off run must show end_turn_removed exactly 0; both flag-on runs must show
#      it above zero, the scripted-bank forward skip routed to bank 4, zero hard-integrity counters and
#      no out-of-support abort; and every probe must have imported THIS checkout's compiled module.
#      truncated_episodes (games cut by the decision cap) is recorded and reported, not judged.
#   7. Writes B3_IDENTITY_PASS.json only if every check passed.
#
# Fail closed: any failed or unreadable check exits non-zero and writes no pass marker. Safe to relaunch:
# each launch works in a new attemptN directory and never overwrites an earlier one.
#
# Exit status: 0 passed (now or earlier); 2 configuration error, nothing was run; 3 another b3_identity.sh
# holds this stage; 4 a pass marker exists for a different build; 1 a check failed.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/b3_common_env.sh"

log() { printf '%s b3_identity: %s\n' "$(date -u +%FT%TZ)" "$*"; }

OUT="$C/runs/b3-identity-20261006"
PASS="$B3_IDENTITY_PASS"
STATUS="$OUT/B3_IDENTITY_STATUS.json"
GPU_LOCK="${GPU_LOCK:-/home/rache/kt-e2e/kt-gpu.lock}"
GPU_LOCK_WAIT_SECONDS="${GPU_LOCK_WAIT_SECONDS:-600}"
PROBE_TIMEOUT_SECONDS="${B3_PROBE_TIMEOUT_SECONDS:-3600}"
LOCK_LABEL="bloodbowl-rl:b3-identity (flag-off identity + flag-on smoke, about 20 min)"

PUFFER="$C/vendor/PufferLib"
PY="$PUFFER/.venv/bin/python"
ENTRY="$PUFFER/.venv/bin/puffer"
RUN42="$LONGRUN/runs/ladder-d0-r0chain42-cont41-rr1-20261003"
MANIFEST="$RUN42/screen-attempt1/ladder-d0-s42-r0chain42-cont41-rr1-20261003-r0_poss_half-s42.log.manifest.json"
WARM="$LONGRUN/vendor/PufferLib/checkpoints/bloodbowl/1791097707780/0000002999975936.bin"
REF="$LONGRUN/vendor/PufferLib/checkpoints/bloodbowl/1791129357655"
REF_EPOCH1="$REF/0000000000131072.bin"
REF_EPOCH382="$REF/0000000050069504.bin"
POOL="$OUT/pool-cc9b201e"
# Pinned content. The B3_TEST_* overrides exist for tools/test_b3_stage_scripts.py only. With any of them
# set the result goes to B3_IDENTITY_PASS.unpinned.json, which no stage reads: the campaign's pass marker
# can only be written against the pinned digests.
WANT_WARM="${B3_TEST_WARM_SHA256:-b1830e2312a6252006de71f2835f3459f0a13f664d83ae3128182c48cb0b303b}"
WANT_EPOCH1="${B3_TEST_EPOCH1_SHA256:-a9efe0acbaa4794b7e830cef0e73a0bdc3af953d97caa39c129efd73d9b4ca73}"
WANT_EPOCH382="${B3_TEST_EPOCH382_SHA256:-6c079cdc60799cf176c040e344e8a899db8af563b21850c3303486076a72313f}"
WANT_POOL="${B3_TEST_POOL_SHA256:-$B3_POOL_HASH}"
PINNED=1
if [ -n "${B3_TEST_WARM_SHA256:-}${B3_TEST_EPOCH1_SHA256:-}${B3_TEST_EPOCH382_SHA256:-}${B3_TEST_POOL_SHA256:-}" ]; then
  PINNED=0
  PASS="$OUT/B3_IDENTITY_PASS.unpinned.json"
fi

sha() { sha256sum "$1" | awk '{print $1}'; }

# --- configuration -------------------------------------------------------------
for tool in flock python3 timeout sha256sum cmp; do
  command -v "$tool" >/dev/null 2>&1 || { log "$tool is required"; exit 2; }
done
[ -d "$C/tools" ] || { log "C is not a checkout root: $C"; exit 2; }
[ -x "$PY" ] || { log "vendored Python missing: $PY"; exit 2; }
for path in "$MANIFEST" "$WARM" "$REF_EPOCH1" "$REF_EPOCH382" "$RUN42/pool/league_seeds.json" \
            "$C/tools/probe_train_identity.py" "$C/tools/probe_scripted_bank_skip.py"; do
  [ -f "$path" ] || { log "missing input: $path"; exit 2; }
done
case "$GPU_LOCK_WAIT_SECONDS:$PROBE_TIMEOUT_SECONDS" in
  *[!0-9:]*|:*|*:) log "GPU_LOCK_WAIT_SECONDS and B3_PROBE_TIMEOUT_SECONDS must be positive integers"; exit 2 ;;
esac
[ -d "$(dirname "$GPU_LOCK")" ] || { log "GPU lock directory is missing: $(dirname "$GPU_LOCK")"; exit 2; }
mkdir -p "$OUT" || exit 2

MODULE="$(ls "$PUFFER"/pufferlib/_C*.so 2>/dev/null | head -n 2)"
[ -n "$MODULE" ] && [ "$(printf '%s\n' "$MODULE" | wc -l)" -eq 1 ] || {
  log "expected exactly one compiled module under $PUFFER/pufferlib, found: ${MODULE:-none}"; exit 2; }
MODULE_SHA="$(sha "$MODULE")"
SOURCE_SHA="$(cat "$PUFFER/ocean/bloodbowl/.content_hash" 2>/dev/null)"
[[ "$SOURCE_SHA" =~ ^[0-9a-f]{64}$ ]] || { log "no installed source digest at $PUFFER/ocean/bloodbowl/.content_hash"; exit 2; }

# One b3_identity.sh at a time. The supervisor only sees this stage as alive when the plan's trainer_pgrep
# names it (README); this lock keeps a second launch from running beside the first either way.
exec 6>"$OUT/.b3_identity.lock" || exit 2
flock -n 6 || { log "another b3_identity.sh holds $OUT/.b3_identity.lock; not starting a second"; exit 3; }

phase() {
  local tmp="$STATUS.tmp.$$"
  printf '{"phase":"%s","exit_code":%s,"pid":%d,"utc":"%s"}\n' \
    "$1" "${2:-null}" "$$" "$(date -u +%FT%TZ)" > "$tmp" && mv "$tmp" "$STATUS"
}

# --- terminal state --------------------------------------------------------------
if [ -f "$PASS" ]; then
  if python3 - "$PASS" "$MODULE_SHA" "$SOURCE_SHA" <<'PY'
import json, sys
marker = json.load(open(sys.argv[1], encoding="utf-8"))
ok = (marker.get("pass") is True and marker.get("compiled_module_sha256") == sys.argv[2]
      and marker.get("source_sha256") == sys.argv[3])
raise SystemExit(0 if ok else 1)
PY
  then
    log "already passed for this build (module $MODULE_SHA): $PASS"
    exit 0
  fi
  log "a pass marker exists for a DIFFERENT build than the one installed (module $MODULE_SHA, source $SOURCE_SHA): $PASS"
  log "the checkout was rebuilt after it passed; move the marker away to qualify the new build"
  exit 4
fi

# --- CPU checks ------------------------------------------------------------------
phase cpu-checks
if ! bash "$C/tools/install_puffer_env.sh" --check; then
  log "drift check failed: the installed env is not this checkout's source"; phase exited 1; exit 1
fi
# A venv made with cp -a keeps the entrypoint shebangs of the venv it was copied from, and an exam cell
# started through such an entrypoint imports the OTHER checkout's pufferlib and compiled env.
ENTRY_INTERPRETER="$(head -n 1 "$ENTRY" 2>/dev/null | sed -n 's/^#![[:space:]]*//p')"
case "$ENTRY_INTERPRETER" in
  "$PUFFER/.venv/bin/"*) ;;
  *) log "the venv entrypoint $ENTRY runs under '$ENTRY_INTERPRETER', not this checkout's venv; fix the shebangs (make_b3_checkout.sh does)"
     phase exited 1; exit 1 ;;
esac
[ "$(sha "$WARM")" = "$WANT_WARM" ] || { log "warm start $WARM is not chain 41 ($WANT_WARM)"; phase exited 1; exit 1; }
[ "$(sha "$REF_EPOCH1")" = "$WANT_EPOCH1" ] || { log "$REF_EPOCH1 is not chain 42's 131,072-step checkpoint ($WANT_EPOCH1)"; phase exited 1; exit 1; }
[ "$(sha "$REF_EPOCH382")" = "$WANT_EPOCH382" ] || { log "$REF_EPOCH382 is not chain 42's 50,069,504-step checkpoint ($WANT_EPOCH382)"; phase exited 1; exit 1; }
# The league preseed is a private copy, so the probe cannot write into chain 42's own pool.
[ -d "$POOL" ] || cp -a "$RUN42/pool" "$POOL" || { log "could not copy the pool to $POOL"; phase exited 1; exit 1; }
HAVE_POOL="$(python3 - "$POOL" <<'PY'
import hashlib, json, pathlib, sys
pool = pathlib.Path(sys.argv[1])
identity = []
for index, seed in enumerate(json.loads((pool / "league_seeds.json").read_text())["seeds"]):
    blob = (pool / seed["file"]).read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if seed.get("bank") != index or seed.get("sha256") != digest or seed.get("bytes") != len(blob):
        raise SystemExit(f"pool bank {index} does not match its manifest entry")
    identity.append({"bank": index, "name": seed["name"], "bytes": len(blob), "sha256": digest})
print(hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
PY
)" || { log "the pool copy at $POOL is not a valid pool"; phase exited 1; exit 1; }
[ "$HAVE_POOL" = "$WANT_POOL" ] || { log "pool copy identity $HAVE_POOL is not $WANT_POOL"; phase exited 1; exit 1; }

ATTEMPT=1
while [ -e "$OUT/attempt$ATTEMPT" ]; do ATTEMPT=$((ATTEMPT + 1)); done
A="$OUT/attempt$ATTEMPT"
mkdir -p "$A" || { phase exited 1; exit 1; }
log "attempt $ATTEMPT in $A (module $MODULE_SHA, source $SOURCE_SHA)"

# Chain 42's trainer arguments, as /home/rache/bbopt-20261001/replicate_c36.sh took chain 36's.
python3 - "$MANIFEST" > "$A/chain42-full.args" <<'PY' || { log "could not read chain 42's trainer arguments from $MANIFEST"; phase exited 1; exit 1; }
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
argv = m["command"][m["command"].index("bloodbowl") + 1:]
drop = {"--tag", "--eval-episodes", "--checkpoint-interval", "--selfplay.league-preseed", "--load-model-path"}
pairs = [argv[i:i + 2] for i in range(0, len(argv), 2)]
assert all(p[0].startswith("--") and len(p) == 2 for p in pairs)
assert not any(p[0] == "--env.no-early-end-turn" for p in pairs)
for flag, value in pairs:
    if flag not in drop:
        print(flag); print(value)
PY
mapfile -t ARGS < "$A/chain42-full.args"
[ "${#ARGS[@]}" -gt 0 ] || { log "chain 42's trainer arguments came back empty"; phase exited 1; exit 1; }
# Whole games for the trace: 512 agents, 32 rollouts of 64 steps, about 2,000 decisions an env.
TRACE=(--vec.total-agents 512 --vec.num-threads 8 --train.horizon 64 --train.minibatch-size 4096)

# --- GPU lock --------------------------------------------------------------------
LOCK_HELD=0
cleanup() {
  local rc=$?
  trap - EXIT
  if [ "$LOCK_HELD" = "1" ]; then
    printf '%s %s released(exit %s) %s\n' "$(date -u +%FT%TZ)" "$$" "$rc" "$LOCK_LABEL" >> "$GPU_LOCK.log" 2>/dev/null
  fi
  phase exited "$rc"
  log "exit $rc"
  exit "$rc"
}
trap cleanup EXIT
trap 'log "caught TERM; stopping"; exit 143' TERM
trap 'log "caught INT; stopping"; exit 130' INT
trap 'log "caught HUP; stopping"; exit 129' HUP

exec 7>>"$GPU_LOCK" || { log "cannot open GPU lock $GPU_LOCK"; exit 2; }
phase waiting-gpu-lock
while :; do
  flock -w "$GPU_LOCK_WAIT_SECONDS" 7
  lock_rc=$?
  [ "$lock_rc" -ne 0 ] || break
  [ "$lock_rc" -eq 1 ] || { log "flock failed with status $lock_rc on $GPU_LOCK"; exit 2; }
  log "waiting on $GPU_LOCK (another GPU job holds it)"
  phase waiting-gpu-lock
done
LOCK_HELD=1
printf '%s %s acquired(lock=%s) %s\n' "$(date -u +%FT%TZ)" "$$" "$GPU_LOCK" "$LOCK_LABEL" >> "$GPU_LOCK.log" 2>/dev/null \
  || log "could not append to $GPU_LOCK.log (the lock itself is held)"
log "acquired $GPU_LOCK on fd 7"

# --- the three probes --------------------------------------------------------------
# Each records its exit status and the verdict below reads it: a failed probe is a failed check, and the
# later probes still run so one attempt shows everything that is wrong. The probes inherit fd 7, so the
# lock stays with whatever is using the GPU even if this script dies.
phase identity-flag-off
log "flag OFF: replicating chain 42's first 382 epochs"
timeout --signal=TERM --kill-after=60 "$PROBE_TIMEOUT_SECONDS" \
  "$PY" "$C/tools/probe_train_identity.py" run --puffer-root "$PUFFER" \
  --output "$A/replicate-c42.json" --weights-dir "$A/replicate-c42-w" --epochs 382 --save-at 1,382 -- \
  "${ARGS[@]}" --load-model-path "$WARM" --selfplay.league-preseed "$POOL" --checkpoint-dir "$A/ckpt" \
  > "$A/replicate-c42.out" 2>&1
echo "$?" > "$A/replicate-c42.rc"
log "flag OFF probe exit $(cat "$A/replicate-c42.rc")"

phase trace-flag-on
log "flag ON: rollout trace of whole games"
timeout --signal=TERM --kill-after=60 "$PROBE_TIMEOUT_SECONDS" \
  "$PY" "$C/tools/probe_scripted_bank_skip.py" trace --puffer-root "$PUFFER" \
  --output "$A/trace-flag-on.json" --rollouts 32 -- \
  "${ARGS[@]}" "${TRACE[@]}" --env.no-early-end-turn 1 --load-model-path "$WARM" --checkpoint-dir "$A/ckpt" \
  > "$A/trace-flag-on.out" 2>&1
echo "$?" > "$A/trace-flag-on.rc"
log "flag ON trace exit $(cat "$A/trace-flag-on.rc")"

phase ppo-flag-on
log "flag ON: 24 epochs of rollout + PPO"
timeout --signal=TERM --kill-after=60 "$PROBE_TIMEOUT_SECONDS" \
  "$PY" "$C/tools/probe_train_identity.py" run --puffer-root "$PUFFER" \
  --output "$A/smoke-flag-on.json" --weights-dir "$A/smoke-flag-on-w" --epochs 24 --save-at 24 -- \
  "${ARGS[@]}" --env.no-early-end-turn 1 --load-model-path "$WARM" --selfplay.league-preseed "$POOL" \
  --checkpoint-dir "$A/ckpt" > "$A/smoke-flag-on.out" 2>&1
echo "$?" > "$A/smoke-flag-on.rc"
log "flag ON PPO exit $(cat "$A/smoke-flag-on.rc")"

# The GPU work is over: release the lock before the verdict.
exec 7>&-
printf '%s %s released(probes done) %s\n' "$(date -u +%FT%TZ)" "$$" "$LOCK_LABEL" >> "$GPU_LOCK.log" 2>/dev/null
LOCK_HELD=0

# --- verdict ---------------------------------------------------------------------
phase verdict
python3 - "$A" "$PASS" "$MODULE_SHA" "$SOURCE_SHA" "$REF_EPOCH1" "$REF_EPOCH382" \
    "$WANT_EPOCH1" "$WANT_EPOCH382" "$WANT_WARM" "$WANT_POOL" "$PINNED" "$C" "$ATTEMPT" <<'PY'
import datetime, filecmp, hashlib, json, os, pathlib, subprocess, sys

(attempt, pass_path, module_sha, source_sha, ref1, ref382, want1, want382,
 want_warm, want_pool, pinned, checkout, attempt_number) = sys.argv[1:]
attempt = pathlib.Path(attempt)
failures = []


def sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load(name):
    try:
        rc = int((attempt / f"{name}.rc").read_text().strip())
    except (OSError, ValueError):
        rc = None
    if rc != 0:
        failures.append(f"{name}: probe exit status {rc}")
    try:
        payload = json.loads((attempt / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        failures.append(f"{name}: no readable output ({exc!r})")
        return None
    try:
        out = (attempt / f"{name}.out").read_text(encoding="utf-8", errors="replace")
    except OSError:
        out = ""
    if "outside exact joint support" in out:
        failures.append(f"{name}: the env aborted on a tuple outside exact joint support")
    return payload


def number(payload, key):
    value = (payload.get("env") or {}).get(key)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def common(name, payload, flag):
    """Checks every probe output must pass; returns its summary."""
    summary = {"module_sha256": (payload.get("identity") or {}).get("module_sha256"),
               "skip": payload.get("skip"),
               "hard_integrity_zero": (payload.get("hard_integrity") or {}).get("zero"),
               "no_early_end_turn": ((payload.get("config") or {}).get("env") or {}).get("no_early_end_turn"),
               "episodes": number(payload, "n"),
               "end_turn_removed": number(payload, "end_turn_removed"),
               "truncated_episodes": number(payload, "truncated_episodes")}
    if summary["module_sha256"] != module_sha:
        failures.append(f"{name}: the probe imported module {summary['module_sha256']}, "
                        f"this checkout's is {module_sha}")
    if summary["hard_integrity_zero"] is not True:
        failures.append(f"{name}: hard-integrity counters are not all zero")
    skip = summary["skip"] or {}
    if skip.get("bank") != 4 or skip.get("routed") is not True:
        failures.append(f"{name}: the scripted-bank forward skip is not routed to bank 4: {skip}")
    try:
        configured = float(summary["no_early_end_turn"])
    except (TypeError, ValueError):
        configured = None
    if configured != float(flag):
        failures.append(f"{name}: config env.no_early_end_turn is {summary['no_early_end_turn']!r}, "
                        f"this run needs {flag}")
    if not summary["episodes"] or summary["episodes"] <= 0:
        failures.append(f"{name}: no completed episode in the env panel")
    removed = summary["end_turn_removed"]
    if flag == 0 and removed != 0:
        failures.append(f"{name}: end_turn_removed is {removed!r} with the flag off; it must be "
                        "present and exactly 0")
    if flag == 1 and not (removed is not None and removed > 0):
        failures.append(f"{name}: end_turn_removed is {removed!r} with the flag on; the env did not "
                        "apply the rule")
    # Recorded and reported, not a failure: how often ordinary play reaches the decision cap has never
    # been measured, and the identity and the rule's evidence do not depend on it.
    if summary["truncated_episodes"] is None:
        failures.append(f"{name}: the env panel has no truncated_episodes; this is not the b3 build")
    elif summary["truncated_episodes"] != 0:
        print(f"NOTE: {name}: truncated_episodes is {summary['truncated_episodes']!r} per episode "
              "(games cut by the max_decisions cap)")
    return summary


report = {}
replicate = load("replicate-c42")
if replicate is not None:
    report["flag_off_identity"] = common("replicate-c42", replicate, 0)
    weights = {}
    for label, saved, reference, want in (
            ("131072", attempt / "replicate-c42-w/epoch-0001.bin", ref1, want1),
            ("50069504", attempt / "replicate-c42-w/epoch-0382.bin", ref382, want382)):
        if not saved.is_file():
            failures.append(f"replicate-c42: no saved weights at {saved}")
            continue
        got = sha(saved)
        weights[label] = {"replicated_sha256": got, "reference_sha256": want}
        if got != want or not filecmp.cmp(saved, reference, shallow=False):
            failures.append(f"replicate-c42: weights at {label} steps differ from chain 42's "
                            f"({got} != {want})")
    if len(weights) != 2:
        failures.append("replicate-c42: fewer than two saved weight files were compared")
    report["flag_off_identity"]["weights"] = weights
    steps = {c.get("epoch"): c.get("agent_steps") for c in replicate.get("checkpoints", [])}
    if steps != {1: 131072, 382: 50069504}:
        failures.append(f"replicate-c42: saved epochs/steps are {steps}, not 1 and 382 at "
                        "131,072 and 50,069,504 steps")
for name, key in (("trace-flag-on", "flag_on_trace"), ("smoke-flag-on", "flag_on_ppo")):
    payload = load(name)
    if payload is not None:
        report[key] = common(name, payload, 1)

head = subprocess.run(["git", "-C", checkout, "rev-parse", "HEAD"], text=True,
                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
marker = {
    "schema_version": 1,
    "stage": "b3_identity",
    "pass": not failures,
    "failures": failures,
    "attempt": int(attempt_number),
    "attempt_dir": str(attempt),
    "checkout": checkout,
    "checkout_head": head.stdout.strip() if head.returncode == 0 else None,
    "source_sha256": source_sha,
    "compiled_module_sha256": module_sha,
    "warm_sha256": want_warm,
    "pool_identity_sha256": want_pool,
    # False when a B3_TEST_* override replaced a pinned digest: not a campaign pass.
    "reference_pinned": pinned == "1",
    "checks": report,
    "written_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
target = attempt / "B3_IDENTITY_RESULT.json"
target.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")
for line in failures:
    print(f"FAILED: {line}")
if failures:
    raise SystemExit(1)
tmp = pass_path + f".tmp.{os.getpid()}"
with open(tmp, "w", encoding="utf-8") as handle:
    json.dump(marker, handle, indent=2, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.replace(tmp, pass_path)
print(f"PASS: {pass_path}")
PY
verdict_rc=$?
if [ "$verdict_rc" -ne 0 ]; then
  log "NOT PASSED: see $A/B3_IDENTITY_RESULT.json; no pass marker was written"
  exit 1
fi
[ -f "$PASS" ] || { log "the verdict exited 0 without $PASS"; exit 1; }
log "PASSED: $PASS"
exit 0
