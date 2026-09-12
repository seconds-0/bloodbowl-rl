#!/usr/bin/env python3
"""Independent float64/autograd oracle for the direct min-GRU candidate."""
from __future__ import annotations
import argparse
import json
import torch


def fast_sigmoid(x):
    v = torch.clamp(x * 0.5, -9.0, 9.0); z = v*v
    r = ((((((-2.76076847742355e-16*z + 2.00018790482477e-13)*z
              - 8.60467152213735e-11)*z + 5.12229709037114e-08)*z
              + 1.48572235717979e-05)*z + 6.37261928875436e-04)*z
              + 4.89352455891786e-03)
    d = ((1.19825839466702e-06*z + 1.18534705686654e-04)*z
         + 2.26843463243900e-03)*z + 4.89352518554385e-03
    return torch.clamp((v*r/d + 1)*0.5, 0.0, 1.0)


def fast_sigmoid_derivative(x):
    v=x*0.5; z=v*v
    a5,a4,a3,a2,a1,a0,am=(-2.76076847742355e-16,2.00018790482477e-13,
        -8.60467152213735e-11,5.12229709037114e-08,1.48572235717979e-05,
        6.37261928875436e-04,4.89352455891786e-03)
    b3,b2,b1,b0=(1.19825839466702e-06,1.18534705686654e-04,
                  2.26843463243900e-03,4.89352518554385e-03)
    r=(((((a5*z+a4)*z+a3)*z+a2)*z+a1)*z+a0)*z+am
    dr=((((6*a5*z+5*a4)*z+4*a3)*z+3*a2)*z+2*a1)*z+a0
    d=((b3*z+b2)*z+b1)*z+b0; dd=(3*b3*z+2*b2)*z+b1
    unclamped=.5*(v*r/d+1)
    derivative=.25*((r+2*z*dr)*d-(v*r)*(2*v*dd))/(d*d)
    return torch.where((v <= -9)|(v >= 9)|(unclamped <= 0)|(unclamped >= 1),
                       torch.zeros_like(x), derivative)


def check_bf16_rounding_order():
    state=torch.tensor([[0.333]],dtype=torch.float32)
    hidden=torch.tensor([[-0.7]],dtype=torch.float32)
    gate=torch.tensor([[0.2]],dtype=torch.float32)
    projection=torch.tensor([[1.1]],dtype=torch.float32)
    inputs=torch.tensor([[-0.4]],dtype=torch.float32)
    candidate=fast_sigmoid(hidden); g=torch.sigmoid(gate); p=torch.sigmoid(projection)
    raw=torch.lerp(state,candidate,g)
    rollout_output=(p*raw+(1-p)*inputs).to(torch.bfloat16)
    next_state=raw.to(torch.bfloat16)
    candidate_output=(p*raw+(1-p)*inputs).to(torch.bfloat16)
    candidate_next=raw.to(torch.bfloat16)
    if not torch.equal(rollout_output,candidate_output) or not torch.equal(
            next_state,candidate_next):
        raise RuntimeError("candidate rounding order differs from rollout")
    return {"output_bits_match": True, "next_state_bits_match": True}


def reference(combined, inputs, initial):
    hidden, gate, projection = combined.chunk(3, dim=-1)
    state = initial
    outputs = []
    states = [state]
    for t in range(inputs.shape[1]):
        candidate = torch.where(hidden[:, t] >= 0,
                                hidden[:, t] + 0.5,
                                fast_sigmoid(hidden[:, t]))
        g = torch.sigmoid(gate[:, t])
        state = torch.lerp(state, candidate, g)
        p = torch.sigmoid(projection[:, t])
        outputs.append(p * state + (1 - p) * inputs[:, t])
        states.append(state)
    return torch.stack(outputs, 1), state, torch.stack(states, 1)


def analytic(combined, inputs, initial, grad_output, grad_final):
    output, final, states = reference(combined, inputs, initial)
    hidden, gate, projection = combined.chunk(3, dim=-1)
    grad_combined = torch.zeros_like(combined)
    grad_input = torch.zeros_like(inputs)
    carry = grad_final.clone()
    H = inputs.shape[-1]
    for t in range(inputs.shape[1] - 1, -1, -1):
        candidate = torch.where(hidden[:, t] >= 0,
                                hidden[:, t] + 0.5,
                                fast_sigmoid(hidden[:, t]))
        g, p = torch.sigmoid(gate[:, t]), torch.sigmoid(projection[:, t])
        carry = carry + grad_output[:, t] * p
        gcandidate = carry * g
        gcandidate_hidden = torch.where(
            hidden[:, t] >= 0, gcandidate,
            gcandidate * fast_sigmoid_derivative(hidden[:, t]))
        grad_combined[:, t, :H] = gcandidate_hidden
        grad_combined[:, t, H:2*H] = (
            carry * (candidate - states[:, t]) * g * (1 - g))
        grad_combined[:, t, 2*H:] = (
            grad_output[:, t] * (states[:, t+1] - inputs[:, t]) * p * (1-p))
        grad_input[:, t] = grad_output[:, t] * (1-p)
        carry = carry * (1-g)
    return output, final, grad_combined, grad_input, carry


def run(seed=20260904):
    torch.manual_seed(seed)
    results = []
    for T in (1, 2, 7, 64):
        B, H = 2, 5
        # Stay away from hidden=0, where the candidate's piecewise derivative kinks.
        raw = torch.randn(B, T, 3*H, dtype=torch.float64)
        sign = torch.where(raw[..., :H] >= 0, 1.0, -1.0)
        raw[..., :H] = raw[..., :H] + 0.25 * sign
        if T >= 2:
            raw[0, 0, 0] = -0.125
            raw[0, 1, 0] = -20.0
        combined = raw.requires_grad_()
        inputs = torch.randn(B, T, H, dtype=torch.float64, requires_grad=True)
        initial = torch.rand(B, H, dtype=torch.float64, requires_grad=True)
        go = torch.randn(B, T, H, dtype=torch.float64)
        gf = torch.randn(B, H, dtype=torch.float64)
        out, final, *_ = analytic(combined, inputs, initial, go, gf)
        loss = (out * go).sum() + (final * gf).sum()
        auto = torch.autograd.grad(loss, (combined, inputs, initial))
        _, _, gc, gx, gs = analytic(
            combined.detach(), inputs.detach(), initial.detach(), go, gf)
        errors = [float((a-b).abs().max()) for a,b in zip(auto, (gc,gx,gs))]
        if max(errors) > 2e-12:
            raise RuntimeError(f"T={T} analytic/autograd mismatch: {errors}")
        # Independent directional derivative, avoiding coordinate-wise mirror tests.
        directions = [torch.randn_like(x) for x in (combined, inputs, initial)]
        eps = 1e-6
        def objective(scale):
            o, f, _ = reference(*(x.detach()+scale*d for x,d in
                                  zip((combined, inputs, initial), directions)))
            return (o*go).sum() + (f*gf).sum()
        finite = float((objective(eps)-objective(-eps))/(2*eps))
        predicted = float(sum((g*d).sum() for g,d in zip((gc,gx,gs), directions)))
        relative = abs(finite-predicted)/max(1.0,abs(finite),abs(predicted))
        if relative > 2e-8:
            raise RuntimeError(f"T={T} directional derivative mismatch: {relative}")
        results.append({"T": T, "max_autograd_error": max(errors),
                        "directional_relative_error": relative})
    eps=1e-7; zero=torch.tensor(0.0,dtype=torch.float64)
    left=float((fast_sigmoid(zero)-fast_sigmoid(zero-eps))/eps)
    right=float(((zero+eps+0.5)-0.5)/eps)
    if abs(left-0.25)>1e-7 or abs(right-1.0)>1e-7:
        raise RuntimeError(f"hidden-zero one-sided derivatives differ: {left}, {right}")
    return {"status": "PASS", "seed": seed, "cases": results,
            "hidden_zero_excluded": True,
            "hidden_zero_one_sided": {"left": left, "right": right},
            "negative_saturation_derivative": float(fast_sigmoid_derivative(
                torch.tensor(-20.0,dtype=torch.float64))),
            "bf16_rounding_order": check_bf16_rounding_order()}


if __name__ == "__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--seed",type=int,default=20260904)
    print(json.dumps(run(ap.parse_args().seed),indent=2,sort_keys=True))
