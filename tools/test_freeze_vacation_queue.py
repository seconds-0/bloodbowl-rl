#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import experiment_queue
import freeze_vacation_queue as freezer


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


class FreezeVacationQueueTests(unittest.TestCase):
    def test_validate_spec_enforces_reviewed_four_anchor_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            main_warm = root / "main.bin"
            second_warm = root / "second.bin"
            for path, marker in ((main_warm, b"m"), (second_warm, b"s")):
                with path.open("wb") as handle:
                    handle.write(marker)
                    handle.truncate(16_066_560)
            pool = root / "pool"
            pool.mkdir()
            write_json(pool / "league_seeds.json", {})
            anchor_config = root / "anchors.json"
            write_json(anchor_config, {"config": True})
            screen = root / "main-screen/SCREEN_COMPLETE.json"
            screen.parent.mkdir()
            write_json(screen, {"screen_manifest_sha256": "a" * 64})
            scripted = root / "main-scripted/TRANSFER_COMPLETE.json"
            scripted.parent.mkdir()
            write_json(scripted, {"complete": True})
            scripted_manifest = scripted.parent / "TRANSFER_MANIFEST.json"
            write_json(scripted_manifest, {
                "source_screen": str(screen.parent),
                "source_screen_sha256": "a" * 64,
            })
            learned = root / "main-learned/LEARNED_TRANSFER_COMPLETE.json"
            learned.parent.mkdir()
            write_json(learned, {"complete": True})
            learned_manifest = learned.parent / "LEARNED_TRANSFER_MANIFEST.json"
            anchor_sha = freezer.sha256(anchor_config)
            write_json(learned_manifest, {
                "games_per_cell": 4096,
                "anchor_config_sha256": anchor_sha,
            })
            spec_path = root / "VACATION_SPEC.json"
            write_json(spec_path, {
                "schema_version": 1,
                "queue_id": "vacation-test",
                "root": str(root),
                "candidate_arm": "gain_only",
                "main_warm": str(main_warm),
                "second_warm": str(second_warm),
                "pool": str(pool),
                "anchor_config": str(anchor_config),
                "main_screen_complete": str(screen),
                "main_scripted_complete": str(scripted),
                "main_learned_complete": str(learned),
                "second_steps": 1_000_000_000,
                "final_steps": 6_000_000_000,
                "min_free_bytes": 1,
                "min_free_inodes": 1,
                "max_gpu_temperature_c": 89,
            })
            anchors = [
                {"name": f"anchor-{index}", "sha256": f"{index:064x}"}
                for index in range(4)
            ]
            anchor_record = {
                "games_per_cell": 4096,
                "anchors": anchors,
                "sha256": anchor_sha,
            }
            learned_report = {
                "candidate_arm": "gain_only",
                "source_screen_complete_sha256": freezer.sha256(screen),
                "eligible_for_longer_confirmation": True,
                "learned_transfer_manifest": {"path": str(learned_manifest)},
            }
            with (
                mock.patch.dict(
                    freezer.REVIEWED_SECOND_ANCESTRY,
                    {"sha256": freezer.sha256(second_warm)},
                ),
                mock.patch.object(
                    freezer, "validate_main_screen",
                    return_value={"screen": {"manifest_sha256": "a" * 64}},
                ),
                mock.patch.object(
                    freezer.analyze_reward_candidate_transfer,
                    "validate_completion_evidence",
                    return_value={"transfer_manifest": str(scripted_manifest)},
                ),
                mock.patch.object(
                    freezer.run_reward_learned_transfer,
                    "validate_completion", return_value=learned_report,
                ),
                mock.patch.object(
                    freezer.run_reward_learned_transfer,
                    "validate_anchor_config", return_value=anchor_record,
                ),
            ):
                validated = freezer.validate_spec(spec_path)
                self.assertEqual(len(validated["anchor_config_record"]["anchors"]), 4)
                anchor_record["anchors"] = anchors[:2]
                with self.assertRaisesRegex(freezer.FreezeError, "exactly four"):
                    freezer.validate_spec(spec_path)

    def test_main_screen_must_be_one_billion_steps_and_match_warm_and_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            screen_dir = root / "screen"
            screen_dir.mkdir()
            complete = screen_dir / "SCREEN_COMPLETE.json"
            write_json(complete, {"screen_manifest_sha256": "a" * 64})
            warm = root / "warm.bin"
            warm.write_bytes(b"warm")
            pool = root / "pool"
            pool.mkdir()
            pool_manifest = pool / "league_seeds.json"
            write_json(pool_manifest, {"seeds": []})
            source_hash = root / "vendor/PufferLib/ocean/bloodbowl/.content_hash"
            source_hash.parent.mkdir(parents=True)
            source_hash.write_text("source-hash\n", encoding="utf-8")
            config = root / "vendor/PufferLib/config/bloodbowl.ini"
            config.parent.mkdir(parents=True)
            config.write_text("config\n", encoding="utf-8")
            module = root / "vendor/PufferLib/pufferlib/_C.so"
            module.parent.mkdir(parents=True)
            module.write_bytes(b"module")
            critical = root / "vendor/PufferLib/pufferlib/pufferl.py"
            critical.write_text("critical\n", encoding="utf-8")
            patch = root / "training/test.patch"
            patch.parent.mkdir()
            patch.write_text("patch\n", encoding="utf-8")
            write_json(screen_dir / "SCREEN_MANIFEST.json", {
                "contract": {
                    "warm": {"sha256": freezer.sha256(warm)},
                    "pool": {
                        "manifest_sha256": freezer.sha256(pool_manifest),
                        "banks": [],
                    },
                    "implementation": {
                        "source_sha256": "source-hash",
                        "config_sha256": freezer.sha256(config),
                        "compiled_module": str(module),
                        "compiled_module_sha256": freezer.sha256(module),
                        "critical_vendor_files": {
                            "pufferlib/pufferl.py": freezer.sha256(critical),
                        },
                        "patches": {str(patch): freezer.sha256(patch)},
                    },
                }
            })
            report = {
                "screen": {
                    "profile": "paired-confirmation",
                    "candidate_arm": "gain_only",
                    "requested_steps": 500_000_000,
                    "completion": {
                        "present": True,
                        "sha256": freezer.sha256(complete),
                    },
                }
            }
            with mock.patch.object(
                freezer.analyze_reward_screen, "analyze_screen", return_value=report
            ):
                with self.assertRaisesRegex(freezer.FreezeError, "exact paired"):
                    freezer.validate_main_screen(
                        complete, "gain_only", warm, pool, root
                    )
                report["screen"]["requested_steps"] = 1_000_000_000
                accepted = freezer.validate_main_screen(
                    complete, "gain_only", warm, pool, root
                )
            self.assertEqual(accepted, report)

    def fixture(self, root: Path) -> dict:
        files = [
            "vendor/PufferLib/.venv/bin/python",
            "vendor/PufferLib/.venv/bin/puffer",
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
            "puffer/config/bloodbowl.ini",
            "puffer/config/rewards/r0_full.json",
            "puffer/config/rewards/p1_possession_only.json",
            "puffer/config/rewards/p2_gain_only.json",
            "puffer/config/rewards/r2_no_possession.json",
            "vendor/PufferLib/config/bloodbowl.ini",
            "vendor/PufferLib/config/default.ini",
            "vendor/PufferLib/pufferlib/pufferl.py",
            "vendor/PufferLib/pufferlib/models.py",
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
        pinned_names = {Path(pin["path"]).name for pin in plan["pinned_files"]}
        for name in ("bash", "puffer", "default.ini", "models.py"):
            self.assertIn(name, pinned_names)
        self.assertIn(
            str((root / "puffer/config/bloodbowl.ini").resolve()),
            {pin["path"] for pin in plan["pinned_files"]},
        )


if __name__ == "__main__":
    unittest.main()
