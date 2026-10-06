#!/usr/bin/env python3
"""Write the stage wrappers and CAMPAIGN_PLAN.json for the 2026-10-02 long run from one list (D407).

    python3 make_plan.py OUT_DIR      # OUT_DIR gets common_env.sh's siblings: sNN_<name>.sh and CAMPAIGN_PLAN.json

Stage 0 is a disposable 50M-step canary of chain 37's exact launch path. Stages 1 and 2 are the registered
restart-scale arms (chains 37 and 38). After D409 (chain 36 Positive, chain 37 Flat) stage 3 is chain 40, the
registered continuation from chain 36 on the standard recipe. Stage 4 is chain 46, the opponent-seat arm of
D410 (control: chain 40). Stages 5 and 6 are chains 41 and 42, continuations. Stages 7 and 8 are the
second-seed opponent-seat pair of D412 (chains 47 and 48). Stage 9 is chain 49 (D413): chain 42's rung with
the bot on tag 1, control chain 42. Chains 43 to 45 are not run: chain 42 read Flat. Stages 10 to 13 are
chains 50 to 53, the compounding test of D414.
Chain 39 (the third restart-scale arm) is not run: chain 38 read Negative (D410).
"""
import json
import pathlib
import sys

CAMPAIGN = "longrun-20261002"
HOME = "/home/rache/longrun"
C = "/home/rache/bloodbowl-rl-longrun-20261002"
OLD = "/home/rache/bloodbowl-rl-qualification-candidate-10619e2"
POOL_C36 = "51a19cff01f7701e10a4aeeca842cfb398b30c461e09c13af158362afd51ab80"
POOL_C35 = "ff4c0552cb9e6b6a21a49c484a750958521391110a06c23c6f7904ad348660b1"
MARKER_C34 = f"{OLD}/runs/ladder-d0-r0chain34-cont30-rr1-20260916/LADDER_RUNG_COMPLETE.json"
MARKER_C30 = f"{OLD}/runs/ladder-d0-r0chain30-rr1-20260914/LADDER_RUNG_COMPLETE.json"
MARKER_C36 = f"{OLD}/runs/ladder-d0-r0chain36-cont34-rr1-20260917/LADDER_RUNG_COMPLETE.json"
# D405's drift guard pinned to chain 30 (fires only when all three hold), for the registered continuation.
GUARD_C30 = {"EXAM_GUARD_FLOOR_S42": "0.541", "EXAM_GUARD_FLOOR_S43": "0.551", "EXAM_GUARD_FLOOR_MEAN": "0.546"}
# Speculative rungs halt when the two-seed mean of offense AWAY champion touchdowns is below 0.536. The verdict
# tool fires only when all three clauses hold, so the per-seed floors are set where they always hold.
GUARD_MEAN = {"EXAM_GUARD_FLOOR_S42": "9.0", "EXAM_GUARD_FLOOR_S43": "9.0", "EXAM_GUARD_FLOOR_MEAN": "0.536"}
ARM = ("0.5", "2.0")       # restart learning-rate scale, entropy scale (entropy coefficient stays 0.009)
STANDARD = ("1.0", "1.0")


# D416: the b3 stages run from their own checkout (hand-written wrappers under {HOME}/b3, from branch
# feat/no-early-end-turn-20261005). They sit right after chain 50: identity check, canary, then chain 54.
B3 = "/home/rache/bloodbowl-rl-b3-20261006/runs"
B3_STAGES = [
    {"name": "b3_identity", "launch": f"bash {HOME}/b3/b3_identity.sh",
     "success": f"{B3}/b3-identity-20261006/B3_IDENTITY_PASS.json",
     "progress": f"{B3}/b3-identity-20261006/B3_IDENTITY_STATUS.json",
     "max_attempts": 2, "max_stale_seconds": 6000},
    {"name": "b3_canary54", "launch": f"bash {HOME}/b3/b3_canary54.sh",
     "success": f"{B3}/ladder-d0-canary54-noearlyend-from41-s42-20261006/EXAM_VERDICT_PASS.json",
     "progress": f"{B3}/ladder-d0-canary54-noearlyend-from41-s42-20261006/SCREEN_STATUS.json",
     "max_attempts": 3, "max_stale_seconds": 6000},
    {"name": "b3_chain54", "launch": f"bash {HOME}/b3/b3_chain54.sh",
     "success": f"{B3}/ladder-d0-r0chain54-noearlyend-from41-s42-20261006/EXAM_VERDICT_PASS.json",
     "progress": f"{B3}/ladder-d0-r0chain54-noearlyend-from41-s42-20261006/SCREEN_STATUS.json",
     "max_attempts": 3, "max_stale_seconds": 6000},
]


def marker(stamp):
    return f"{C}/runs/ladder-d0-{stamp}/LADDER_RUNG_COMPLETE.json"


STAGES = [
    dict(name="s00_canary", stamp="canary37-lr05-from34-20261002", seed=42, prev=MARKER_C34,
         pool=POOL_C36, rule="none", scales=ARM, extra={"STEPS": "50000000"}),
    dict(name="s01_chain37", stamp="r0chain37-lr05-from34-20261002", seed=42, prev=MARKER_C34,
         pool=POOL_C36, rule="none", scales=ARM),
    dict(name="s02_chain38", stamp="r0chain38-lr05-from30-s44-20261002", seed=44, prev=MARKER_C30,
         pool=POOL_C35, rule="none", scales=ARM),
    dict(name="s03_chain40", stamp="r0chain40-cont36-rr1-20261003", seed=42, prev=MARKER_C36,
         pool=None, rule="drift-guard", scales=STANDARD, extra=dict(GUARD_C30)),
]
# D410: the opponent-seat arm. Same warm start, seed and pool files as chain 40; the scripted bot takes bank
# tag 1 (the anchor's seat), so chains 30, 34 and 36 are all active learned opponents. Control: chain 40.
STAGES.append(dict(name="s04_chain46", stamp="r0chain46-botseat1-from36-20261003", seed=42, prev=MARKER_C36,
                   pool="23342e2bcf322af17b4083de466db4adb87358bc55a41c86cb4f7b11dce31ffc", rule="drift-guard",
                   scales=STANDARD, extra=dict(GUARD_C30, SCRIPTED_BANK_TAG="1")))
STAGES.append(dict(name="s05_chain41", stamp="r0chain41-cont40-rr1-20261003", seed=42,
                   prev=marker("r0chain40-cont36-rr1-20261003"), pool=None, rule="drift-guard",
                   scales=STANDARD, extra=dict(GUARD_MEAN)))
STAGES.append(dict(name="s06_chain42", stamp="r0chain42-cont41-rr1-20261003", seed=42,
                   prev=marker("r0chain41-cont40-rr1-20261003"), pool=None, rule="drift-guard",
                   scales=STANDARD, extra=dict(GUARD_MEAN)))
# D412: the second-seed pair for the opponent seat, both from chain 41 (the accepted warm start) at training
# seed 2042 (env seed streams disjoint from seeds 42 and 44). Chain 47 has the bot on tag 1, chain 48 on tag 4.
MARKER_C41 = marker("r0chain41-cont40-rr1-20261003")
POOL_C42 = "cc9b201e619aab3dedb2577eeac273a3b70a346a5e87d30fa9ab432c068d3be6"  # the pool every child of chain 41 builds (chain 42's)
STAGES.append(dict(name="s07_chain47", stamp="r0chain47-botseat1-from41-s2042-20261004", seed=2042,
                   prev=MARKER_C41, pool=POOL_C42, rule="drift-guard", scales=STANDARD,
                   extra=dict(GUARD_C30, SCRIPTED_BANK_TAG="1")))
STAGES.append(dict(name="s08_chain48", stamp="r0chain48-botseat4-from41-s2042-20261004", seed=2042,
                   prev=MARKER_C41, pool=POOL_C42, rule="drift-guard", scales=STANDARD,
                   extra=dict(GUARD_C30)))
# D413: chain 42 read Flat, so chains 43 to 45 are not run. Chain 49 is a third opponent-seat arm with an
# existing control: the same rung as chain 42 (chain 41 warm, seed 42, pool cc9b201e) with the bot on tag 1.
STAGES.append(dict(name="s09_chain49", stamp="r0chain49-botseat1-from41-s42-20261004", seed=42,
                   prev=MARKER_C41, pool=POOL_C42, rule="drift-guard", scales=STANDARD,
                   extra=dict(GUARD_C30, SCRIPTED_BANK_TAG="1")))


# D414: the compounding test. Chains 42 and 48 both read Flat against chain 41 (+12.5 and +11.0), so a single
# further rung is not retained. Chains 50 to 53 continue from chain 42 on the standard recipe and only chain 53,
# five rungs past chain 41, is gated against chain 41.
previous = "r0chain42-cont41-rr1-20261003"
for number in range(50, 54):
    stamp = f"r0chain{number}-compound-cont{42 if number == 50 else number - 1}-20261005"
    STAGES.append(dict(name=f"s{number - 40:02d}_chain{number}", stamp=stamp, seed=42,
                       prev=marker(previous), pool=None, rule="drift-guard", scales=STANDARD,
                       extra=dict(GUARD_MEAN)))
    previous = stamp


def wrapper(stage):
    lines = ["#!/usr/bin/env bash",
             f"# Stage {stage['name']} of campaign {CAMPAIGN} (D407). Generated by make_plan.py; edit the list there.",
             "set -uo pipefail",
             f"source {HOME}/common_env.sh",
             f"export SEED={stage['seed']} STAMP={stage['stamp']}",
             f"export PREV_COMPLETE={stage['prev']}",
             f"export LADDER_CHAIN_LR_SCALE={stage['scales'][0]} LADDER_CHAIN_ENT_SCALE={stage['scales'][1]}",
             f"export EXAM_RULE={stage['rule']}"]
    if stage.get("pool"):
        lines.append(f"export EXPECTED_POOL_HASH={stage['pool']}")
    for key, value in (stage.get("extra") or {}).items():
        lines.append(f"export {key}={value}")
    lines.append('exec bash "$C/tools/chain_stage.sh"')
    return "\n".join(lines) + "\n"


def main():
    out = pathlib.Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    stamps = [stage["stamp"] for stage in STAGES]
    assert len(set(stamps)) == len(stamps), "duplicate STAMP"
    plan = {"schema_version": 1, "campaign_id": CAMPAIGN, "root": C,
            "trainer_pgrep": "[p]uffer_cuda_runtime.py train|[p]uffer train|[c]hain_stage.sh|"
                             "[l]adder_stage.sh|[r]un_reward_screen.sh|[e]val_vs_contact_bot.sh|"
                             "[b]3_identity.sh",
            "stages": []}
    for stage in STAGES:
        path = out / f"{stage['name']}.sh"
        path.write_text(wrapper(stage))
        path.chmod(0o755)
        plan["stages"].append({
            "name": stage["name"], "launch": f"bash {HOME}/{stage['name']}.sh",
            "success": f"runs/ladder-d0-{stage['stamp']}/EXAM_VERDICT_PASS.json",
            "progress": f"runs/ladder-d0-{stage['stamp']}/SCREEN_STATUS.json",
            "max_attempts": 3, "max_stale_seconds": 6000})
        if stage["name"] == "s10_chain50":
            plan["stages"].extend(B3_STAGES)
    (out / "CAMPAIGN_PLAN.json").write_text(json.dumps(plan, indent=2) + "\n")
    for stage in STAGES:
        print(stage["name"], stage["stamp"], "<-", stage["prev"].split("/runs/")[1].split("/")[0], stage["rule"])


if __name__ == "__main__":
    main()
