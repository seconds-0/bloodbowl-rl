from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools/qualify_terminal_aware_memory.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("qualify_terminal_aware_memory", RUNNER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TerminalAwareMemoryValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q = load_runner()

    def fixture(self):
        L, B, H, T = 2, 8, 3, 4
        initial = np.empty((L, B, H), np.float32)
        for layer in range(L):
            for row in range(B):
                initial[layer, row] = 100*layer + 10*row + np.arange(H)
        terminals = np.array([
            [0,0,0,0,0,0,0,0], [0,1,0,0,0,0,0,0],
            [0,0,0,0,0,0,1,0], [0,0,0,0,0,0,0,0]], np.float32)
        sin = np.empty((T,L,B,H), np.float32)
        sout = np.empty_like(sin)
        prior = initial.copy()
        for t in range(T):
            for row in range(B):
                effective = np.zeros((L,H), np.float32) if terminals[t,row] else prior[:,row]
                sin[t,:,row] = effective
                sout[t,:,row] = effective + np.float32(0.25 + t/16 + row/128)
            prior = sout[t].copy()
        tail_term = np.array([0,1,0,0,1,0,0,0], np.float32)
        tail_input = prior.copy(); tail_input[:,tail_term.astype(bool)] = 0
        selected = np.array([0,1,4,5], np.int32)
        arrays = {
            "initial_states": initial, "observation_terminals": terminals,
            "behavior_state_in": sin, "behavior_state_out": sout,
            "persistent_state_before_tail": prior.copy(),
            "persistent_state_after_tail": prior.copy(),
            "tail_state_input": tail_input, "tail_terminals": tail_term,
            "tail_values": np.array([1,0,2,3,0,4,5,6], np.float32),
            "selected_rows": selected,
            "mb_initial_states": initial[:,selected].copy(),
            "mb_terminals": terminals[:,selected].T.copy(),
            "mb_ratio": np.ones((len(selected),T), np.float32),
        }
        meta = {"layers":L,"total_agents":B,"hidden":H,"horizon":T,
                "state_layout":{"num_banks":3,"num_buffers":2,
                    "agents_per_buffer":4,"bank_layout":[0,2,3,4]}}
        return arrays, meta

    def test_accepts_complete_fixture(self):
        arrays, meta = self.fixture()
        self.q.validate_snapshot_schema(arrays, meta)
        self.q.validate_terminal_forward(arrays)
        self.q.validate_tail_nonmutation(arrays)
        verdict = self.q.validate_gather_and_ratio(arrays, meta, atol=2e-5)
        self.assertEqual(verdict["covered_primary_rows"], [0,1,4,5])

    def test_schema_rejects_wrong_rank_dtype_bounds_binary_and_nonfinite(self):
        for mutation in ("rank","dtype","bounds","binary","nan","missing"):
            arrays, meta = self.fixture()
            if mutation == "rank": arrays["mb_ratio"] = arrays["mb_ratio"].reshape(-1)
            elif mutation == "dtype": arrays["selected_rows"] = arrays["selected_rows"].astype(np.int64)
            elif mutation == "bounds": arrays["selected_rows"][0] = 8
            elif mutation == "binary": arrays["observation_terminals"][1,1] = .5
            elif mutation == "nan": arrays["behavior_state_out"][0,0,0,0] = np.nan
            else: del arrays["tail_state_input"]
            with self.subTest(mutation=mutation), self.assertRaises(self.q.MemoryQualificationError):
                self.q.validate_snapshot_schema(arrays, meta)

    def test_terminal_validator_catches_late_reset_and_lost_carry(self):
        arrays, _ = self.fixture()
        arrays["behavior_state_in"][1,:,1] = arrays["behavior_state_out"][0,:,1]
        with self.assertRaisesRegex(self.q.MemoryQualificationError, "was not reset"):
            self.q.validate_terminal_forward(arrays)
        arrays, _ = self.fixture()
        arrays["behavior_state_in"][3,:,0] = 0
        with self.assertRaisesRegex(self.q.MemoryQualificationError, "lost carry"):
            self.q.validate_terminal_forward(arrays)

    def test_tail_rejects_mutation_wrong_mask_and_nonzero_terminal_bootstrap(self):
        for mutation in ("mutate","mask","bootstrap"):
            arrays, _ = self.fixture()
            if mutation == "mutate": arrays["persistent_state_after_tail"][0,0,0] += 1
            elif mutation == "mask": arrays["tail_state_input"][0,1,0] = 3
            else: arrays["tail_values"][1] = .1
            with self.subTest(mutation=mutation), self.assertRaises(self.q.MemoryQualificationError):
                self.q.validate_tail_nonmutation(arrays)

    def test_gather_detects_state_permutation_mask_permutation_frozen_and_ratio(self):
        for mutation in ("state","mask","frozen","ratio"):
            arrays, meta = self.fixture()
            if mutation == "state": arrays["mb_initial_states"][:,[0,1]] = arrays["mb_initial_states"][:,[1,0]]
            elif mutation == "mask": arrays["mb_terminals"][[0,1]] = arrays["mb_terminals"][[1,0]]
            elif mutation == "frozen": arrays["selected_rows"][0] = 2
            else: arrays["mb_ratio"][0,0] = 1.01
            with self.subTest(mutation=mutation), self.assertRaises(self.q.MemoryQualificationError):
                self.q.validate_gather_and_ratio(arrays, meta, atol=2e-5)

    def test_one_replacement_trial_need_not_cover_every_primary_row(self):
        arrays, meta = self.fixture()
        arrays["selected_rows"] = np.array([0,0,1,1], np.int32)
        arrays["mb_initial_states"] = arrays["initial_states"][:,arrays["selected_rows"]].copy()
        arrays["mb_terminals"] = arrays["observation_terminals"][:,arrays["selected_rows"]].T.copy()
        verdict = self.q.validate_gather_and_ratio(
            arrays, meta, atol=2e-5, require_full_coverage=False)
        self.assertEqual(verdict["covered_primary_rows"], [0,1])
        with self.assertRaises(self.q.MemoryQualificationError):
            self.q.validate_gather_and_ratio(
                arrays, meta, atol=2e-5, require_full_coverage=True)

    def test_graph_comparison_rejects_exact_and_float_drift(self):
        eager, _ = self.fixture(); graph = {k:v.copy() for k,v in eager.items()}
        self.q.compare_graph_modes(eager, graph, atol=1e-6)
        graph["selected_rows"][0] = 1
        with self.assertRaises(self.q.MemoryQualificationError):
            self.q.compare_graph_modes(eager, graph, atol=1e-6)
        graph = {k:v.copy() for k,v in eager.items()}; graph["behavior_state_out"][0,0,0,0] += 1e-3
        with self.assertRaises(self.q.MemoryQualificationError):
            self.q.compare_graph_modes(eager, graph, atol=1e-6)

    def test_live_crosswindow_rejects_forced_zero_and_unmasked_terminal(self):
        final = np.arange(24, dtype=np.float32).reshape(2,4,3) + 1
        terminals = np.array([0,1,0,1], np.float32)
        expected = final.copy(); expected[:,terminals.astype(bool)] = 0
        self.q.validate_live_crosswindow_arrays(final, terminals, expected)
        with self.assertRaises(self.q.MemoryQualificationError):
            self.q.validate_live_crosswindow_arrays(
                final, terminals, np.zeros_like(final))
        with self.assertRaises(self.q.MemoryQualificationError):
            self.q.validate_live_crosswindow_arrays(final, terminals, final.copy())

    def test_action_sensitivity_requires_real_alternative_and_nonzero_logprob(self):
        arrays = {"action_mask": np.array([[[1,1,1,1],[1,1,1,0]]], np.float32),
                  "logprobs": np.array([[-.5,0]], np.float32)}
        self.q.validate_action_sensitivity(arrays)
        arrays["action_mask"][0,0] = [1,1,1,0]
        with self.assertRaises(self.q.MemoryQualificationError):
            self.q.validate_action_sensitivity(arrays)
        arrays["action_mask"][0,0] = [1,1,1,1]; arrays["logprobs"][0,0] = 0
        with self.assertRaises(self.q.MemoryQualificationError):
            self.q.validate_action_sensitivity(arrays)

    def test_derivative_schema_requires_exact_terminal_gradient_cut(self):
        T = 4
        shapes = {"combined":(2,T,15), "inputs":(2,T,5), "outputs":(2,T,5),
                  "grad_outputs":(2,T,5), "grad_inputs":(2,T,5),
                  "initial_state":(2,5), "final_state":(2,5),
                  "grad_initial_state":(2,5), "terminals":(2,T),
                  "grad_combined":(2,T,15)}
        values = {name:np.zeros(shape,np.float32) for name,shape in shapes.items()}
        values["terminals"][0,0] = 1; values["terminals"][1,2] = 1
        def record(value):
            return {"dtype":"f32","shape":list(value.shape),
                    "data":value.astype("<f4").tobytes()}
        raw = {"contract":"terminal-mingru-derivatives-fp32-v1",
               "B":2,"T":T,"H":5,"tensors":{k:record(v) for k,v in values.items()}}
        self.q.decode_and_validate_derivatives(raw)
        values["grad_initial_state"][0,0] = .25
        raw["tensors"]["grad_initial_state"] = record(values["grad_initial_state"])
        with self.assertRaisesRegex(self.q.MemoryQualificationError, "leaked gradient"):
            self.q.decode_and_validate_derivatives(raw)

    def test_runtime_geometry_preserves_two_primary_rows_per_buffer(self):
        config = self.q._config(-1, 42)
        self.assertEqual(config["policy"], {"hidden_size":64,"num_layers":2})
        self.assertEqual(config["vec"]["total_agents"], 8)
        self.assertEqual(config["vec"]["num_buffers"], 2)
        self.assertEqual(config["vec"]["num_frozen_banks"], 2)
        self.assertEqual(config["vec"]["frozen_bank_pct"], 0.25)
        per_buffer = config["vec"]["total_agents"] // config["vec"]["num_buffers"]
        frozen_each = int(per_buffer * config["vec"]["frozen_bank_pct"])
        primary = per_buffer - config["vec"]["num_frozen_banks"] * frozen_each
        self.assertEqual((primary, frozen_each, frozen_each), (2, 1, 1))

    def test_actual_step_control_checks_all_bank_outputs(self):
        state = np.arange(24, dtype=np.float32).reshape(2,4,3)
        decoders = {
            "decoder_bank_0_buffer_0":np.ones((2,5),np.float32),
            "decoder_bank_1_buffer_0":np.ones((1,5),np.float32),
            "decoder_bank_2_buffer_0":np.ones((1,5),np.float32),
        }
        self.q.validate_step_control(
            state, state.copy(), decoders,
            {key:value.copy() for key,value in decoders.items()}, atol=1e-6)
        bad_state = state.copy(); bad_state[0,2,0] += .01
        with self.assertRaises(self.q.MemoryQualificationError):
            self.q.validate_step_control(
                state, bad_state, decoders, decoders, atol=1e-6)
        bad_decoders = {key:value.copy() for key,value in decoders.items()}
        bad_decoders["decoder_bank_2_buffer_0"][0,0] += .01
        with self.assertRaises(self.q.MemoryQualificationError):
            self.q.validate_step_control(
                state, state.copy(), decoders, bad_decoders, atol=1e-6)

    def test_execution_counters_bind_requested_mode_and_every_role(self):
        config = self.q._config(10, 42)
        roles = ("rollout","tail","train")
        before = {"cudagraphs":10,
                  "captured":{r:True for r in roles},
                  "handles_ready":{r:True for r in roles},
                  "graph_launch_counts":{r:7 for r in roles},
                  "eager_execution_counts":{r:0 for r in roles}}
        after = {k:(v.copy() if isinstance(v,dict) else v) for k,v in before.items()}
        after["graph_launch_counts"].update(rollout=23,tail=11,train=11)
        verdict = self.q.validate_execution_counts(before, after, config, trials=2)
        self.assertEqual(verdict["active_delta"], {"rollout":16,"tail":4,"train":4})
        for mutation in ("wrong_active","unexpected_eager","not_captured","missing_role"):
            bad = {k:(v.copy() if isinstance(v,dict) else v) for k,v in after.items()}
            if mutation == "wrong_active": bad["graph_launch_counts"]["tail"] -= 1
            elif mutation == "unexpected_eager": bad["eager_execution_counts"]["train"] = 1
            elif mutation == "not_captured": bad["captured"]["rollout"] = False
            else: del bad["handles_ready"]["tail"]
            with self.subTest(mutation=mutation), self.assertRaises(self.q.MemoryQualificationError):
                self.q.validate_execution_counts(before, bad, config, trials=2)

        eager_config = self.q._config(-1, 42)
        eager_before = {"cudagraphs":-1,
            "captured":{r:False for r in roles},
            "handles_ready":{r:False for r in roles},
            "graph_launch_counts":{r:0 for r in roles},
            "eager_execution_counts":{r:3 for r in roles}}
        eager_after = {k:(v.copy() if isinstance(v,dict) else v)
                       for k,v in eager_before.items()}
        eager_after["eager_execution_counts"].update(rollout=11,tail=5,train=5)
        self.q.validate_execution_counts(
            eager_before, eager_after, eager_config, trials=1)


if __name__ == "__main__":
    unittest.main()
