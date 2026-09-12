import hashlib, json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory_learning_evaluation as subject

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

class MemoryLearningEvaluationTests(unittest.TestCase):
    def plan(self, root):
        models=[]
        for arm in ('old','new'):
            for seed in (42,43):
                checkpoint=root/f'{arm}-{seed}.bin'; checkpoint.write_bytes(f'{arm}-{seed}'.encode())
                models.append({'arm':arm,'training_seed':seed,'runtime':str(root/arm),
                  'python':str(root/'venv/bin/python'),'cudart':str(root/'venv/lib/libcudart.so.12'),
                  'source_snapshot_root':str(root/arm),'source_closure_sha256':'c'*64,
                  'module_sha256':subject.MODULES[arm],'contract':subject.CONTRACTS[arm],
                  'checkpoint':str(checkpoint),'checkpoint_sha256':digest(checkpoint)})
        return {'schema_version':1,'mode':'memory-learning-heldout-v1',
          'evaluation_seeds':list(subject.EVAL_SEEDS),'games_per_seed_style_side':8,
          'games_per_model':128,'training_seeds':[42,43], 'qualification_only':True,
          'promotion_eligible':False,'models':models}

    def write_exam(self, directory, model, delta=0):
        directory.mkdir(parents=True)
        cells=[{'style':s,'learner_side':side,'seed':seed}
          for s in ('contact','cage') for side in ('home','away') for seed in subject.EVAL_SEEDS]
        configs=[{**c,'args':{'fixed':1, **c}} for c in cells]
        runtime='r'+model['arm']
        manifest={'checkpoint_sha256':model['checkpoint_sha256'],'runtime_identity_sha256':runtime,
          'checkpoint_qualification_only':True,
          'runtime_identity':{'compiled_module_sha256':model['module_sha256'],
                              'rollout_transition_contract':model['contract']},
          'cells':cells,'games_per_cell':8,'effective_configs':configs}
        (directory/'MANIFEST.json').write_text(json.dumps(manifest))
        rows=[]
        for c in cells:
          for episode in range(1,9):
            td=delta if episode==1 else 0
            rows.append({**c,'base_seed':c['seed'],'episode':episode,'match_points':1 if td>0 else .5,
              'td_diff':td,'checkpoint_sha256':model['checkpoint_sha256'],'runtime_identity_sha256':runtime})
        (directory/'GAMES.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        complete={'manifest_sha256':digest(directory/'MANIFEST.json'),'games_sha256':digest(directory/'GAMES.jsonl'),
                  'expected_games':128}
        (directory/'COMPLETE.json').write_text(json.dumps(complete))

    def test_plan_and_command_pin_matrix_and_contract(self):
      with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); plan=self.plan(root); subject.validate_plan(plan,require_checkpoints=True)
        model=plan['models'][0]; cmd=subject.command(model,plan,root/'out')
        self.assertEqual(cmd.count('--seed'),4); self.assertIn('--allow-qualification',cmd)
        self.assertIn('tail-bootstrap-v1',cmd); self.assertEqual(cmd[0],model['python'])
        self.assertEqual(Path(cmd[1]).name, 'frozen_scripted_eval.py')
        self.assertNotEqual(Path(cmd[1]).parent.parent, Path(model['runtime']))
        self.assertEqual(cmd[cmd.index('--runtime-root')+1], model['runtime'])
        self.assertIn('--runtime-bridge-reason', cmd)
        new_model=plan['models'][2]; new_cmd=subject.command(new_model,plan,root/'newout')
        self.assertEqual(cmd[1], new_cmd[1])
        self.assertNotIn('--runtime-bridge-reason', new_cmd)

    def test_compare_allows_only_declared_runtime_difference(self):
      with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); plan=self.plan(root); out=root/'out'
        for model in plan['models']: self.write_exam(out/f"{model['arm']}-s{model['training_seed']}",model,1 if model['arm']=='new' else 0)
        result=subject.compare(plan,out)
        self.assertEqual(result['paired_games_total'],256)
        self.assertGreater(result['macro_training_seed_match_score_delta'],0)
        manifest=out/'new-s42/MANIFEST.json'; data=json.loads(manifest.read_text()); data['effective_configs'][0]['args']['fixed']=2; manifest.write_text(json.dumps(data))
        complete=out/'new-s42/COMPLETE.json'; c=json.loads(complete.read_text()); c['manifest_sha256']=digest(manifest); complete.write_text(json.dumps(c))
        with self.assertRaisesRegex(subject.EvaluationFailure,'configs differ'): subject.compare(plan,out)

if __name__=='__main__': unittest.main()
