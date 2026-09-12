import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
import numpy as np

HERE=Path(__file__).resolve().parent
PATCH=HERE/'puffer_dual_forward_qualification.patch'
RUNNER=HERE/'verify_native_dual_forward.py'

def load():
 s=importlib.util.spec_from_file_location('dual',RUNNER); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

class DualForwardTests(unittest.TestCase):
 def test_patch_applies_to_frozen_module_source(self):
  base=Path('/tmp/dual-forward-base/bindings.cu')
  if not base.exists(): self.skipTest('exact frozen source unavailable')
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'bindings.cu'; p.write_bytes(base.read_bytes())
   r=subprocess.run(['patch','--batch','--forward',str(p),str(PATCH)],capture_output=True,text=True)
   self.assertEqual(r.returncode,0,r.stdout+r.stderr)
   text=p.read_text()
   self.assertIn('qualification_dual_forward',text)
   self.assertIn('pufferl.hypers.lr != 0.0f',text)
   self.assertIn('cudaMemcpyAsync(static_cast<precision_t*>(direct_state.data) + layer * C * H',text)
   self.assertIn('pufferl.train_buf.mb_state.data + layer * B * H + b_start * H',text)
   self.assertIn('pufferl.train_buf.mb_actions.data',text)
   self.assertIn('pufferl.train_buf.mb_action_mask.data',text)
   self.assertIn('numel(pufferl.act_sizes_puf.shape)',text)
   self.assertIn('pufferl.train_buf.mb_actions.shape[2] != heads',text)
   self.assertNotIn('muon_step(', ''.join(line[1:] for line in PATCH.read_text().splitlines() if line.startswith('+') and not line.startswith('+++')))
 def test_float64_oracle_mask_and_heads(self):
  m=load(); logits=np.array([[[2.,9.,1.,4.,3.,-7.]]],np.float32)
  # two heads sizes 3,2; final decoder column is value
  actions=np.array([[[0.,1.]]],np.float32); mask=np.array([[[1,0,1,1,1]]],np.float32)
  got=m.cpu_head_logprobs(logits,actions,mask,np.array([3,2],np.int32))
  e0=2-np.log(np.exp(2)+np.exp(1)); e1=3-np.log(np.exp(4)+np.exp(3))
  np.testing.assert_allclose(got,[[[e0,e1]]],rtol=0,atol=1e-14)
 def test_rejected_oracle_persists_fail_artifact_before_raising(self):
  m=load()
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/"result.json"; result={"status":"FAIL","error":"oracle rejected"}
   with self.assertRaisesRegex(RuntimeError,"oracle rejected"):
    m.persist_result(path,result,result["error"])
   self.assertEqual(__import__("json").loads(path.read_text()),result)

 def test_runner_requires_unchanged_weights_and_saves_arrays(self):
  text=RUNNER.read_text()
  self.assertIn('len(set(hashes)) != 1',text)
  self.assertIn('DUAL_FORWARD_ARRAYS.npz',text)
  self.assertIn('scan_cpu_logprobs',text)
  self.assertIn('direct_cpu_logprobs',text)
  self.assertIn('by_timestep',text)

if __name__=='__main__': unittest.main()
