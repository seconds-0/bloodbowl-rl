#!/usr/bin/env python3
"""One-shot health report for the long-run chain (campaign longrun-20261002). Exit 1 if anything needs attention."""
import glob
import json
import os
import subprocess
import time

C = "/home/rache/bloodbowl-rl-longrun-20261002"
CAMPAIGN = "longrun-20261002"


def sh(command):
    return subprocess.run(command, shell=True, capture_output=True, text=True).stdout.strip()


def main():
    alerts = []
    try:
        state = json.load(open(f"{C}/runs/campaigns/{CAMPAIGN}/CAMPAIGN_STATE.json"))
    except Exception as exc:
        print("ALERT cannot read campaign state:", exc)
        return 1
    if state.get("halted"):
        alerts.append(f"campaign HALTED: {state.get('halt_reason')}")
    if state.get("complete"):
        alerts.append("campaign COMPLETE: no stage left, the GPU will idle")
    last = state["history"][-1]
    print("last event:", last["event"], "at", last["utc"][:19])
    timer = sh(f"systemctl --user is-enabled chain-supervisor@{CAMPAIGN}.timer")
    if timer != "enabled":
        alerts.append(f"supervisor timer is {timer or 'missing'}: nothing will launch the next stage")
    statuses = sorted(glob.glob(f"{C}/runs/ladder-d0-*/CHAIN_STAGE_STATUS.json"), key=os.path.getmtime)
    if statuses:
        status = json.load(open(statuses[-1]))
        run = os.path.dirname(statuses[-1])
        age = time.time() - os.path.getmtime(statuses[-1])
        print("stage:", status["stamp"], "phase:", status["phase"], "exit:", status["exit_code"])
        if status["phase"] == "training":
            logs = glob.glob(f"{run}/screen-attempt*/*-s4[0-9].log")
            if logs:
                log = max(logs, key=os.path.getmtime)
                silent = time.time() - os.path.getmtime(log)
                line = sh(f"tail -c 3000000 '{log}' | grep -a '^PUFFER_LOSS_JSON' | tail -1")
                try:
                    j = json.loads(line.split(" ", 1)[1])
                    print("steps %.3fB of 3.000B  kl %.5f  clipfrac %.5f  explained_variance %.3f  grad_norm %.2f"
                          % (j["_puffer_agent_steps"] / 1e9, j["kl"], j["clipfrac"],
                             j["explained_variance"], j["grad_norm"]))
                except Exception as exc:
                    print("could not parse the latest loss line:", exc)
                sps = sh(f"tail -c 200000 '{log}' | sed 's/\\x1b\\[[0-9;]*[A-Za-z]//g' | grep -a -o 'SPS *[0-9.]*K' | tail -1")
                print("throughput:", sps or "unknown")
                if silent > 600:
                    alerts.append(f"trainer log silent for {silent / 60:.0f} min")
        if status["phase"] == "exited" and status["exit_code"] not in (0, None):
            alerts.append(f"stage {status['stamp']} exited {status['exit_code']}")
        if status["phase"] == "waiting-gpu-lock" and age > 5400:
            alerts.append("stage has waited over 90 min for the GPU lock")
    print("gpu:", sh("nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,power.draw --format=csv,noheader"))
    alive = sh("pgrep -f '[p]uffer_cuda_runtime.py train|[c]hain_stage.sh|[e]val_vs_contact_bot.sh'").split()
    if not alive and not state.get("complete") and not state.get("halted"):
        print("no trainer or stage process right now (normal for up to 5 min between stages)")
    for verdict in sorted(glob.glob(f"{C}/runs/ladder-d0-*/EXAM_VERDICT.json"), key=os.path.getmtime):
        j = json.load(open(verdict))
        offense = [c["champion_tds"] for c in j["cells"] if c["cell"] == "offense_away"]
        name = os.path.basename(os.path.dirname(verdict)).replace("ladder-d0-", "")
        print("verdict:", name, "PASS" if j["pass"] else "FAIL", "offense AWAY",
              " / ".join("%.3f" % x for x in offense))
    for alert in alerts:
        print("ALERT", alert)
    return 1 if alerts else 0


if __name__ == "__main__":
    raise SystemExit(main())
