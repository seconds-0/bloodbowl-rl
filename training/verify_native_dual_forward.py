#!/usr/bin/env python3
"""Attribute native fp32 PPO ratio drift to MinGRU scan or action-head math.

Qualification-only: one LR-zero rollout/update, then the native diagnostic reruns
that selected minibatch with direct step recurrence from the exact scan inputs.
"""
from __future__ import annotations
import argparse, copy, hashlib, importlib.util, json, math, sys
from pathlib import Path
from typing import Any
import numpy as np

CONTRACT = "min-gru-scan-vs-direct-fp32-v1"
FIELDS = ("scan_logits", "direct_logits", "scan_head_logprobs",
          "direct_head_logprobs", "scan_total_logprobs", "direct_total_logprobs", "scan_ratio", "direct_ratio", "actions", "action_mask", "old_logprobs",
          "initial_state", "terminals", "selected_rows", "act_sizes")

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load_runtime_helper(path: Path):
    spec=importlib.util.spec_from_file_location("dual_cuda_runtime_helper",path)
    if spec is None or spec.loader is None: raise RuntimeError("cannot load CUDA runtime helper")
    module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module)
    return module

def decode(d: dict[str, Any]) -> np.ndarray:
    if d.get("present") is not True or d.get("dtype") not in {"f32", "i32"}:
        raise RuntimeError("invalid tensor descriptor")
    dt = "<f4" if d["dtype"] == "f32" else "<i4"
    a = np.frombuffer(d["data"], dtype=dt).copy()
    shape = tuple(d["shape"])
    if a.size != math.prod(shape):
        raise RuntimeError("tensor shape/byte mismatch")
    return a.reshape(shape)

def persist_result(path: Path, result: dict[str, Any], error: str | None) -> None:
    path.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    if error is not None:
        raise RuntimeError(error + "; raw evidence preserved")

def quantiles(x: np.ndarray) -> dict[str, float]:
    x = np.abs(np.asarray(x, dtype=np.float64).ravel())
    return {"p50": float(np.quantile(x, .5)), "p90": float(np.quantile(x, .9)),
            "p99": float(np.quantile(x, .99)), "max": float(x.max(initial=0))}

def cpu_head_logprobs(logits, actions, mask, sizes):
    B,T,_ = logits.shape; H = len(sizes)
    out = np.empty((B,T,H), dtype=np.float64); off = 0
    for h,A0 in enumerate(sizes.tolist()):
        A=int(A0); enabled=mask[:,:,off:off+A] != 0
        block=logits[:,:,off:off+A].astype(np.float64)
        masked=np.where(enabled, block, -np.inf)
        mx=np.max(masked, axis=2)
        lse=mx+np.log(np.sum(np.exp(masked-mx[:,:,None]), axis=2))
        act=actions[:,:,h].astype(np.int64)
        if np.any(act < 0) or np.any(act >= A) or np.any(~np.take_along_axis(enabled,act[:,:,None],2)):
            raise RuntimeError("stored action is outside stored mask")
        out[:,:,h]=np.take_along_axis(block,act[:,:,None],2)[:,:,0]-lse
        off += A
    if off != logits.shape[2]-1 or mask.shape[2] != off:
        raise RuntimeError("action-head layout mismatch")
    return out

def main() -> None:
    ap=argparse.ArgumentParser(); ap.add_argument("--construction",type=Path,required=True)
    ap.add_argument("--frozen-manifest",type=Path,required=True)
    ap.add_argument("--expected-initial-sha256",required=True)
    ap.add_argument("--runtime-helper",type=Path,required=True)
    ap.add_argument("--source-bundle-sha256",required=True)
    ap.add_argument("--output",type=Path,required=True); args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    for label,value in (("expected initial",args.expected_initial_sha256),("source bundle",args.source_bundle_sha256)):
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value): raise RuntimeError(f"{label} sha256 is invalid")
    raw=json.loads(args.construction.read_text()); cfg=copy.deepcopy(raw.get("config",raw))
    if float(cfg["train"].get("learning_rate",float("nan"))) != 0.0 or float(cfg["train"].get("replay_ratio",float("nan"))) != 1.0:
        raise RuntimeError("construction must already declare LR=0 and replay_ratio=1")
    helper=load_runtime_helper(args.runtime_helper.resolve())
    runtime,runtime_evidence=helper.begin_cuda_runtime_preflight()
    from pufferlib import _C
    runtime_evidence=helper.finish_cuda_runtime_preflight(runtime,runtime_evidence)
    runtime_evidence=helper.validate_cuda_runtime_evidence(runtime_evidence)
    if not bool(_C.gpu) or int(_C.precision_bytes) != 4:
        raise RuntimeError("dual-forward requires native GPU fp32")
    if not hasattr(_C,"qualification_dual_forward"):
        raise RuntimeError("native dual-forward qualification surface is absent")
    trainer=_C.create_pufferl(cfg)
    try:
        manifest=json.loads(args.frozen_manifest.read_text())
        seeds=manifest.get("seeds")
        if not isinstance(seeds,list) or len(seeds) != 8:
            raise RuntimeError("frozen manifest must contain exactly eight banks")
        loaded=[]
        expected_bytes=int(manifest.get("expected_bytes",0))
        for bank,entry in enumerate(seeds):
            if entry.get("bank") != bank or Path(entry.get("file","")).name != entry.get("file"):
                raise RuntimeError("frozen bank order/path is not canonical")
            path=args.frozen_manifest.resolve().parent/entry["file"]
            if not path.is_file() or path.stat().st_size != expected_bytes or sha(path) != entry.get("sha256"):
                raise RuntimeError(f"frozen bank {bank} identity mismatch")
            _C.load_frozen_bank(trainer,bank,str(path)); loaded.append(sha(path))
        before=args.output/"weights-before.bin"; after_train=args.output/"weights-after-train.bin"
        after_diag=args.output/"weights-after-diagnostic.bin"
        _C.save_weights(trainer,str(before))
        if sha(before) != args.expected_initial_sha256:
            raise RuntimeError("initial primary checkpoint identity mismatch")
        _C.rollouts(trainer); _C.train(trainer)
        _C.save_weights(trainer,str(after_train))
        evidence=_C.qualification_dual_forward(trainer,128 << 20)
        _C.save_weights(trainer,str(after_diag))
        hashes=[sha(p) for p in (before,after_train,after_diag)]
        if len(set(hashes)) != 1: raise RuntimeError("LR-zero weights changed")
        if evidence.get("contract") != CONTRACT: raise RuntimeError("contract mismatch")
        ts=evidence.get("tensors",{}); arrays={k:decode(ts[k]) for k in FIELDS}
        raw_path=args.output/"DUAL_FORWARD_RAW.npz"
        np.savez_compressed(raw_path,**arrays)
        scan_ref=cpu_head_logprobs(arrays["scan_logits"],arrays["actions"],arrays["action_mask"],arrays["act_sizes"])
        direct_ref=cpu_head_logprobs(arrays["direct_logits"],arrays["actions"],arrays["action_mask"],arrays["act_sizes"])
        scan_native_f32=arrays["scan_head_logprobs"].astype(np.float32)
        direct_native_f32=arrays["direct_head_logprobs"].astype(np.float32)
        scan_native=scan_native_f32.astype(np.float64); direct_native=direct_native_f32.astype(np.float64)
        old_f32=arrays["old_logprobs"].astype(np.float32); old=old_f32.astype(np.float64)
        scan_total=scan_native.sum(2); direct_total=direct_native.sum(2)
        scan_total_f32=arrays["scan_total_logprobs"].astype(np.float32); direct_total_f32=arrays["direct_total_logprobs"].astype(np.float32)
        scan_ratio=np.exp(scan_total-old); direct_ratio=np.exp(direct_total-old)
        scan_ratio_f32=arrays["scan_ratio"].astype(np.float32)
        direct_ratio_f32=arrays["direct_ratio"].astype(np.float32)
        if not all(np.isfinite(x).all() for x in arrays.values()): raise RuntimeError("nonfinite raw evidence")
        if not all(np.isfinite(x).all() for x in (scan_ref,direct_ref,scan_native,direct_native,scan_ratio,direct_ratio,scan_ratio_f32,direct_ratio_f32)):
            raise RuntimeError("nonfinite dual-forward evidence")
        if not np.array_equal(arrays["actions"],np.rint(arrays["actions"])): raise RuntimeError("actions are not integral")
        if np.count_nonzero(arrays["initial_state"]): raise RuntimeError("initial state is not exact zero")
        cpu_err=max(float(np.max(np.abs(scan_native-scan_ref))),float(np.max(np.abs(direct_native-direct_ref))))
        # Native fast intrinsics may differ slightly; this gate catches layout or mask mistakes.
        B,T,_=arrays["scan_logits"].shape
        by_t=[]
        for t in range(T):
            by_t.append({"t":t,"scan_ratio_float64_sum_abs":quantiles(scan_ratio[:,t]-1),
                         "direct_ratio_float64_sum_abs":quantiles(direct_ratio[:,t]-1),
                         "scan_ratio_native_float32_sum_abs":quantiles(scan_ratio_f32[:,t]-1),
                         "direct_ratio_native_float32_sum_abs":quantiles(direct_ratio_f32[:,t]-1),
                         "logit_abs_delta":quantiles(arrays["scan_logits"][:,t]-arrays["direct_logits"][:,t])})
        np.savez_compressed(args.output/"DUAL_FORWARD_ARRAYS.npz",**arrays,
                            scan_cpu_logprobs=scan_ref,direct_cpu_logprobs=direct_ref,
                            scan_ratio_float64_sum=scan_ratio,direct_ratio_float64_sum=direct_ratio,
                            scan_ratio_native_float32_sum=scan_ratio_f32,direct_ratio_native_float32_sum=direct_ratio_f32)
        oracle_ok=cpu_err <= 2e-5
        result={"status":"PASS" if oracle_ok else "FAIL","error":None if oracle_ok else f"native/float64 logprob mismatch: {cpu_err}","contract":CONTRACT,"module_path":str(Path(_C.__file__).resolve()),
                "module_sha256":sha(Path(_C.__file__).resolve()),"construction_sha256":sha(args.construction),
                "effective_config_sha256":hashlib.sha256(json.dumps(cfg,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
                "runner_sha256":sha(Path(__file__).resolve()),"source_bundle_sha256":args.source_bundle_sha256,
                "cuda_runtime_preflight":runtime_evidence,
                "frozen_manifest_sha256":sha(args.frozen_manifest),"frozen_bank_sha256":loaded,
                "raw_evidence_sha256":sha(raw_path),"weight_sha256":hashes[0],"weights_unchanged":True,
                "shape":{"B":B,"T":T,"hidden":evidence["hidden_size"],"layers":evidence["num_layers"],"heads":evidence["num_heads"],
                         "direct_chunk_sequences":evidence["direct_chunk_sequences"]},
                "native_vs_float64_head_logprob_max_abs":cpu_err,
                "scan_ratio_float64_sum_abs":quantiles(scan_ratio-1),"direct_ratio_float64_sum_abs":quantiles(direct_ratio-1),
                "scan_ratio_native_float32_sum_abs":quantiles(scan_ratio_f32-1),"direct_ratio_native_float32_sum_abs":quantiles(direct_ratio_f32-1),
                "scan_vs_direct_logits_abs":quantiles(arrays["scan_logits"]-arrays["direct_logits"]),
                "terminal_count":int(np.count_nonzero(arrays["terminals"])),"by_timestep":by_t}
        out=args.output/"DUAL_FORWARD.json"; out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
        result["arrays_sha256"]=sha(args.output/"DUAL_FORWARD_ARRAYS.npz")
        print(json.dumps(result,sort_keys=True))
        persist_result(out,result,result["error"])
    finally:
        if cfg.get("cudagraphs",cfg.get("train",{}).get("cudagraphs",-1)) != -1: _C.close(trainer)
if __name__ == "__main__": main()
