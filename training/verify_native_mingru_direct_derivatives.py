#!/usr/bin/env python3
"""Compare candidate CUDA direct min-GRU forward/backward with float64 autograd."""
import argparse, json, math, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import qualify_recurrent_cuda as q
FIELDS=("combined","layer_inputs","initial_state","outputs","final_states","grad_top_output","grad_next_state","grad_combined","grad_layer_inputs","grad_initial_state")
CASES=tuple((t,l) for t in (1,2,7,64) for l in (1,3)); ATOL=3e-5; MAX_BYTES=16<<20

def require_finite_arrays(arrays,label):
    for name,value in arrays.items():
        if not np.isfinite(np.asarray(value)).all(): raise RuntimeError(f"{label}.{name} contains non-finite values")

def persist_raw_case(output,t,layers,arrays):
    path=Path(output)/f"DERIVATIVE_T{t}_L{layers}.raw.npz"; q.write_npz_atomic(path,arrays)
    return {"path":str(path.resolve()),"sha256":q.sha256(path)}

def _file_identity(path):
    path=Path(path).resolve(); return {"path":str(path),"sha256":q.sha256(path)}

def check_case(C,t,layers,output,torch,fast_sigmoid,progress):
    raw=C.qualification_direct_mingru_derivatives(t,layers,MAX_BYTES)
    if not isinstance(raw,dict) or not isinstance(raw.get("tensors"),dict): raise RuntimeError("native derivative fixture returned no tensor mapping")
    arrays={name:q._decode_tensor(raw["tensors"][name]) for name in FIELDS}
    artifact=persist_raw_case(output,t,layers,arrays); progress.append({"T":t,"layers":layers,"raw_artifact":artifact})
    if raw.get("contract")!="direct-mingru-derivatives-fp32-v1": raise RuntimeError("native derivative contract mismatch")
    require_finite_arrays(arrays,"native")
    combined=torch.tensor(arrays["combined"],dtype=torch.float64,requires_grad=True)
    initial=torch.tensor(arrays["initial_state"],dtype=torch.float64,requires_grad=True)
    base=torch.tensor(arrays["layer_inputs"][0],dtype=torch.float64,requires_grad=True)
    current=base; layer_inputs=[]; outputs=[]; finals=[]
    for layer in range(layers):
        current.retain_grad(); layer_inputs.append(current)
        hidden,gate,projection=combined[layer].chunk(3,-1); state=initial[layer]; sequence=[]
        for step in range(t):
            candidate=torch.where(hidden[:,step]>=0,hidden[:,step]+.5,fast_sigmoid(hidden[:,step]))
            state=torch.lerp(state,candidate,torch.sigmoid(gate[:,step])); p=torch.sigmoid(projection[:,step])
            sequence.append(p*state+(1-p)*current[:,step])
        current=torch.stack(sequence,1); outputs.append(current); finals.append(state)
    go=torch.tensor(arrays["grad_top_output"],dtype=torch.float64); gn=torch.tensor(arrays["grad_next_state"],dtype=torch.float64)
    ((current*go).sum()+sum((state*gn[i]).sum() for i,state in enumerate(finals))).backward()
    refs={"outputs":np.stack([x.detach().numpy() for x in outputs]),"final_states":np.stack([x.detach().numpy() for x in finals]),"grad_combined":combined.grad.detach().numpy(),"grad_layer_inputs":np.stack([x.grad.detach().numpy() for x in layer_inputs]),"grad_initial_state":initial.grad.detach().numpy()}
    require_finite_arrays(refs,"reference"); errors={}
    for name,expected in refs.items():
        actual=arrays[name].astype(np.float64)
        if actual.shape!=expected.shape: raise RuntimeError(f"{name} shape mismatch: {actual.shape} != {expected.shape}")
        delta=np.abs(actual-expected); require_finite_arrays({name:delta},"error"); errors[name]=float(np.max(delta))
        if not math.isfinite(errors[name]): raise RuntimeError(f"{name} maximum error is non-finite")
    if max(errors.values())>ATOL: raise RuntimeError(f"native derivative mismatch T={t} L={layers}: {errors}")
    progress[-1]["max_abs"]=errors; return progress[-1]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--puffer-root",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    result_path=args.output/"MINGRU_DIRECT_DERIVATIVES.json"; here=Path(__file__).resolve().parent
    result={"status":"FAIL","error":None,"config":{"cases":[list(x) for x in CASES],"atol":ATOL,"max_bytes":MAX_BYTES},"cases":[],"identity":{"runner":_file_identity(Path(__file__)),"candidate_patch":_file_identity(here/"puffer_mingru_direct_recurrence_candidate.patch"),"fixture_patch":_file_identity(here/"puffer_mingru_direct_derivative_fixture.patch"),"reference_oracle":_file_identity(here/"verify_mingru_direct_derivatives.py"),"models_source":_file_identity(args.puffer_root/"src"/"models.cu")}}
    try:
        C,module,runtime=q._load_backend(args.puffer_root); identity=q._module_identity(C,module,args.puffer_root); q.validate_module_identity(identity)
        result["identity"]["module"]=identity; result["identity"]["cuda_runtime_preflight"]=runtime
        if not hasattr(C,"qualification_direct_mingru_derivatives"): raise RuntimeError("native direct derivative fixture is absent")
        import torch
        from verify_mingru_direct_derivatives import fast_sigmoid
        for t,layers in CASES:
            check_case(C,t,layers,args.output,torch,fast_sigmoid,result["cases"]); q.write_json_atomic(result_path,result)
        result["status"]="PASS"
    except BaseException as exc:
        result["status"]="FAIL"; result["error"]=f"{type(exc).__name__}: {exc}"; q.write_json_atomic(result_path,result); raise
    finally: q.write_json_atomic(result_path,result)
    print(json.dumps(result,indent=2,sort_keys=True,allow_nan=False))
if __name__=="__main__": main()
