#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

import experiment_queue
import freeze_vacation_queue as freezer


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


class FreezeVacationQueueTests(unittest.TestCase):
    def fixture(self, root: Path) -> dict:
        files = [
            "vendor/PufferLib/.venv/bin/python",
            "tools/experiment_queue.py",
            "tools/run_frozen_reward_screen.py",
            "tools/run_reward_screen.sh",
            "tools/run_reward_ablation.sh",
            "tools/run_reward_candidate_transfer.py",
            "tools/analyze_reward_candidate_transfer.py",
            "tools/analyze_reward_screen.py",
            "tools/run_reward_learned_transfer.py",
            "tools/vacation_reward_gate.py",
            "tools/validate_vacation_artifact.py",
            "tools/reward_manifest.py",
            "tools/install_puffer_env.sh",
            "tools/cpu_cap.sh",
            "tools/game_stats.py",
            "tools/contact_bot_stats.py",
            "tools/eval_vs_contact_bot.sh",
            "training/convert_checkpoint.py",
            "puffer/config/rewards/r0_full.json",
            "puffer/config/rewards/p1_possession_only.json",
            "puffer/config/rewards/p2_gain_only.json",
            "puffer/config/rewards/r2_no_possession.json",
            "vendor/PufferLib/config/bloodbowl.ini",
            "vendor/PufferLib/pufferlib/pufferl.py",
            "vendor/PufferLib/pufferlib/selfplay.py",
            "vendor/PufferLib/pufferlib/torch_pufferl.py",
            "vendor/PufferLib/src/pufferlib.cu",
            "vendor/PufferLib/src/bindings.cu",
            "vendor/PufferLib/src/vecenv.h",
            "vendor/PufferLib/pufferlib/_C.so",
            "vendor/PufferLib/ocean/bloodbowl/.content_hash",
        ]
        for index, relative in enumerate(files):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"fixture-{index}\n", encoding="utf-8")
        (root / "training/puffer-test.patch").write_text(
            "patch\n", encoding="utf-8"
        )
        pool = root / "pool"
        pool.mkdir()
        (pool / "league_seeds.json").write_text("{}\n", encoding="utf-8")
        main_warm = root / "main-warm.bin"
        second_warm = root / "second-warm.bin"
        main_warm.write_bytes(b"main")
        second_warm.write_bytes(b"second")
        anchors = []
        for name in ("league9", "turnover3"):
            path = root / f"{name}.bin"
            path.write_bytes(name.encode())
            anchors.append({
                "name": name,
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": freezer.sha256(path),
            })
        anchor_config = root / "anchors.json"
        write_json(anchor_config, {"anchors": anchors})

        screen_dir = root / "evidence/main-screen"
        checkpoint = root / "checkpoint.bin"
        checkpoint.write_bytes(b"checkpoint")
        result = screen_dir / "main-both-s42.result.json"
        write_json(result, {"checkpoint": str(checkpoint)})
        main_screen_complete = screen_dir / "SCREEN_COMPLETE.json"
        write_json(main_screen_complete, {
            "results": [{"path": result.name}],
        })
        write_json(screen_dir / "SCREEN_MANIFEST.json", {
            "contract": {
                "implementation": {
                    "compiled_module": str(
                        root / "vendor/PufferLib/pufferlib/_C.so"
                    )
                }
            }
        })
        main_scripted = root / "evidence/main-scripted/TRANSFER_COMPLETE.json"
        main_learned = (
            root / "evidence/main-learned/LEARNED_TRANSFER_COMPLETE.json"
        )
        write_json(main_scripted, {"complete": True})
        write_json(main_learned, {"complete": True})
        spec_path = root / "VACATION_SPEC.json"
        write_json(spec_path, {"fixture": True})
        return {
            "schema_version": 1,
            "queue_id": "vacation-test",
            "root": str(root),
            "root_path": root,
            "queue_dir": root / "runs/vacation-test",
            "candidate_arm": "gain_only",
            "main_warm": main_warm,
            "second_warm": second_warm,
            "pool": pool,
            "anchor_config": anchor_config,
            "anchor_config_record": {"anchors": anchors},
            "main_screen_complete": main_screen_complete,
            "main_scripted_complete": main_scripted,
            "main_learned_complete": main_learned,
            "second_steps": 1_000_000_000,
            "final_steps": 6_000_000_000,
            "min_free_bytes": 1,
            "min_free_inodes": 1,
            "max_gpu_temperature_c": 89,
            "spec_path": spec_path,
        }

    def test_freeze_emits_a_valid_six_job_typed_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            spec = self.fixture(root)
            plan_path = freezer.freeze(spec)
            plan, validated_root, digest = experiment_queue.validate_plan(plan_path)
            final_config = json.loads(
                (root / "runs/vacation-test/configs/FINAL_MAIN_SCREEN_CONFIG.json")
                .read_text(encoding="utf-8")
            )

        self.assertEqual(validated_root, root)
        self.assertEqual(len(digest), 64)
        self.assertEqual([job["id"] for job in plan["jobs"]], [
            "second-confirmation",
            "second-scripted-transfer",
            "second-learned-transfer",
            "two-lineage-gate",
            "final-main",
            "final-second",
        ])
        self.assertFalse(plan["jobs"][0]["resume_safe"])
        self.assertTrue(plan["jobs"][1]["resume_safe"])
        self.assertFalse(plan["jobs"][4]["resume_safe"])
        self.assertEqual(final_config["profile"], "paired-final")
        self.assertEqual(final_config["steps"], 6_000_000_000)
        self.assertTrue(final_config["require_gate"])


if __name__ == "__main__":
    unittest.main()
