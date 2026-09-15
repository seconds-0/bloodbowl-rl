import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from tools import campaign_supervisor as sup


def plan(root, *, stages=None, pattern=None):
    return {
        "schema_version": 1,
        "campaign_id": "test-campaign",
        "root": str(root),
        "trainer_pgrep": pattern or sup.DEFAULT_TRAINER_PGREP,
        "stages": stages
        or [
            {
                "name": "one",
                "success": "one.done",
                "launch": "true",
                "max_attempts": 2,
            },
            {
                "name": "two",
                "success": "two.done",
                "launch": "true",
                "max_attempts": 2,
            },
        ],
    }


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.launched = []
        # Never spawn a real process in a test.
        self._real_launch = sup.launch_stage
        self._real_alive = sup.trainer_is_alive
        sup.launch_stage = lambda root, stage, log_dir, attempt: (
            self.launched.append((stage["name"], attempt)) or 4242
        )
        sup.trainer_is_alive = lambda pattern: False

    def tearDown(self):
        sup.launch_stage = self._real_launch
        sup.trainer_is_alive = self._real_alive
        self._tmp.cleanup()

    def state_for(self, p):
        return sup._blank_state(p)

    def test_launches_the_first_incomplete_stage(self):
        p = plan(self.root)
        st = self.state_for(p)
        verdict = sup.tick(p, st)
        self.assertTrue(verdict.startswith("LAUNCHED stage=one"), verdict)
        self.assertEqual(self.launched, [("one", 1)])
        self.assertEqual(st["stages"]["one"]["attempts"], 1)

    def test_advances_to_the_next_stage_once_the_artifact_appears(self):
        p = plan(self.root)
        st = self.state_for(p)
        (self.root / "one.done").write_text("x", encoding="utf-8")
        verdict = sup.tick(p, st)
        self.assertTrue(verdict.startswith("LAUNCHED stage=two"), verdict)
        self.assertEqual(self.launched, [("two", 1)])

    def test_never_launches_while_a_trainer_is_alive(self):
        sup.trainer_is_alive = lambda pattern: True
        p = plan(self.root)
        st = self.state_for(p)
        verdict = sup.tick(p, st)
        self.assertTrue(verdict.startswith("BUSY"), verdict)
        self.assertEqual(self.launched, [])

    def test_a_failed_probe_is_treated_as_busy_not_as_idle(self):
        # If pgrep cannot run we must NOT conclude the GPU is free.
        def explode(_cmd, **_kw):
            raise OSError("no pgrep")

        real_run = sup.subprocess.run
        sup.subprocess.run = explode
        try:
            # self._real_alive, not sup.trainer_is_alive: setUp stubs the module
            # attribute, so the stub would answer instead of the code under test.
            self.assertTrue(self._real_alive("[p]uffer train"))
        finally:
            sup.subprocess.run = real_run

    def test_attempt_cap_halts_instead_of_relaunching_forever(self):
        p = plan(self.root)
        st = self.state_for(p)
        sup.tick(p, st)
        sup.tick(p, st)
        self.assertEqual(len(self.launched), 2)
        verdict = sup.tick(p, st)
        self.assertTrue(verdict.startswith("HALT"), verdict)
        self.assertTrue(st["halted"])
        self.assertIn("attempt cap", st["halt_reason"])
        self.assertEqual(len(self.launched), 2, "must not launch a third time")

    def test_a_halt_is_sticky(self):
        p = plan(self.root)
        st = self.state_for(p)
        st["halted"] = True
        st["halt_reason"] = "operator"
        verdict = sup.tick(p, st)
        self.assertTrue(verdict.startswith("HALTED"), verdict)
        self.assertEqual(self.launched, [])

    def test_all_artifacts_present_reports_complete(self):
        p = plan(self.root)
        st = self.state_for(p)
        (self.root / "one.done").write_text("x", encoding="utf-8")
        (self.root / "two.done").write_text("x", encoding="utf-8")
        verdict = sup.tick(p, st)
        self.assertTrue(verdict.startswith("COMPLETE"), verdict)
        self.assertTrue(st["complete"])
        self.assertEqual(self.launched, [])

    def test_stale_progress_is_reported_and_nothing_is_killed(self):
        # Trainer alive, progress file ancient: the supervisor must surface it
        # and take no action. Terminating on a heuristic eventually kills a
        # healthy run, and the screen's own integrity guard owns that call.
        sup.trainer_is_alive = lambda pattern: True
        stages = [
            {
                "name": "one",
                "success": "one.done",
                "launch": "true",
                "progress": "progress.json",
                "max_stale_seconds": 60,
            }
        ]
        p = plan(self.root, stages=stages)
        st = self.state_for(p)
        prog = self.root / "progress.json"
        prog.write_text("{}", encoding="utf-8")
        import os

        old = 1_600_000_000
        os.utime(prog, (old, old))
        verdict = sup.tick(p, st)
        self.assertTrue(verdict.startswith("STALE"), verdict)
        self.assertEqual(self.launched, [])
        self.assertFalse(st["halted"], "a stall must not halt the campaign")

    def test_unbracketed_trainer_pattern_is_refused(self):
        # An unbracketed pgrep pattern matches the command line that carries it,
        # which has already reported dead processes as alive twice.
        with self.assertRaisesRegex(sup.PlanError, "bracketed"):
            sup.validate_plan(plan(self.root, pattern="puffer train"))

    def test_relative_root_is_refused(self):
        p = plan(self.root)
        p["root"] = "relative/path"
        with self.assertRaisesRegex(sup.PlanError, "absolute"):
            sup.validate_plan(p)

    def test_duplicate_stage_names_are_refused(self):
        stages = [
            {"name": "dup", "success": "a", "launch": "true"},
            {"name": "dup", "success": "b", "launch": "true"},
        ]
        with self.assertRaisesRegex(sup.PlanError, "duplicate stage name"):
            sup.validate_plan(plan(self.root, stages=stages))

    def test_state_from_another_campaign_is_refused(self):
        p = plan(self.root)
        plan_path = self.root / "plan.json"
        state_path = self.root / "state.json"
        plan_path.write_text(json.dumps(p), encoding="utf-8")
        other = sup._blank_state(p)
        other["campaign_id"] = "somebody-elses-campaign"
        state_path.write_text(json.dumps(other), encoding="utf-8")
        rc = sup.main(["--plan", str(plan_path), "--state", str(state_path)])
        self.assertEqual(rc, 2)

    def test_dry_run_neither_launches_nor_writes_state(self):
        p = plan(self.root)
        plan_path = self.root / "plan.json"
        state_path = self.root / "state.json"
        plan_path.write_text(json.dumps(p), encoding="utf-8")
        rc = sup.main(
            ["--plan", str(plan_path), "--state", str(state_path), "--dry-run"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(self.launched, [])
        self.assertFalse(state_path.exists(), "dry run must not write state")


class TerminalTickTests(unittest.TestCase):
    """A terminal campaign must stop churning its state file and lock.

    The rig's stale timers kept rewriting CAMPAIGN_STATE.json and its lock
    every five minutes for campaigns that had halted or completed weeks before.
    """

    OLD = 1_600_000_000

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.campaign_dir = self.root / "runs" / "campaigns" / "camp-x"
        self.campaign_dir.mkdir(parents=True)
        self.plan_path = self.campaign_dir / "CAMPAIGN_PLAN.json"
        self.state_path = self.campaign_dir / "CAMPAIGN_STATE.json"
        self.lock_path = self.campaign_dir / "CAMPAIGN_STATE.json.lock"
        self.plan = plan(self.root)
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        self.launched = []
        self.probed = []
        self._real_launch = sup.launch_stage
        self._real_alive = sup.trainer_is_alive
        sup.launch_stage = lambda root, stage, log_dir, attempt: (
            self.launched.append((stage["name"], attempt)) or 4242
        )
        sup.trainer_is_alive = lambda pattern: self.probed.append(pattern) or False

    def tearDown(self):
        sup.launch_stage = self._real_launch
        sup.trainer_is_alive = self._real_alive
        self._tmp.cleanup()

    def write_state(self, state):
        self.state_path.write_text(json.dumps(state), encoding="utf-8")
        self.lock_path.write_bytes(b"")
        os.utime(self.state_path, (self.OLD, self.OLD))
        os.utime(self.lock_path, (self.OLD, self.OLD))

    def run_main(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = sup.main(
                ["--plan", str(self.plan_path), "--state", str(self.state_path), *extra]
            )
        return rc, out.getvalue()

    def assert_untouched(self, before_bytes):
        self.assertEqual(self.state_path.stat().st_mtime, self.OLD, "state rewritten")
        self.assertEqual(self.state_path.read_bytes(), before_bytes)
        self.assertEqual(self.lock_path.stat().st_mtime, self.OLD, "lock touched")
        self.assertFalse(
            self.state_path.with_suffix(".json.tmp").exists(), "temp state left behind"
        )

    def test_halted_campaign_writes_nothing_and_exits_zero(self):
        st = sup._blank_state(self.plan)
        st["halted"] = True
        st["halt_reason"] = "operator"
        self.write_state(st)
        before = self.state_path.read_bytes()
        for _ in range(3):
            rc, out = self.run_main()
            self.assertEqual(rc, 0)
            self.assertTrue(out.startswith("HALTED operator"), out)
            self.assert_untouched(before)
        self.assertEqual(self.launched, [])
        self.assertIn(
            "systemctl --user disable --now campaign-supervisor@camp-x.timer", out
        )

    def test_complete_campaign_writes_nothing_and_exits_zero(self):
        (self.root / "one.done").write_text("x", encoding="utf-8")
        (self.root / "two.done").write_text("x", encoding="utf-8")
        st = sup._blank_state(self.plan)
        st["complete"] = True
        self.write_state(st)
        before = self.state_path.read_bytes()
        for _ in range(3):
            rc, out = self.run_main()
            self.assertEqual(rc, 0)
            self.assertTrue(out.startswith("COMPLETE"), out)
            self.assert_untouched(before)
        self.assertEqual(self.launched, [])
        self.assertEqual(self.probed, [], "a complete campaign must not probe pgrep")
        self.assertIn(
            "systemctl --user disable --now campaign-supervisor@camp-x.timer", out
        )

    def test_timer_unit_override_is_printed_verbatim(self):
        st = sup._blank_state(self.plan)
        st["halted"] = True
        st["halt_reason"] = "operator"
        self.write_state(st)
        rc, out = self.run_main("--timer-unit", "other-supervisor@foo.timer")
        self.assertEqual(rc, 0)
        self.assertIn("systemctl --user disable --now other-supervisor@foo.timer", out)
        self.assertNotIn("camp-x", out)

    def test_non_terminal_tick_still_advances_and_writes(self):
        self.write_state(sup._blank_state(self.plan))
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("LAUNCHED stage=one attempt=1/2"), out)
        self.assertNotIn("systemctl", out)
        self.assertEqual(self.launched, [("one", 1)])
        self.assertNotEqual(self.state_path.stat().st_mtime, self.OLD)
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["stages"]["one"]["attempts"], 1)
        self.assertEqual(saved["stages"]["one"]["last_pid"], 4242)

        (self.root / "one.done").write_text("x", encoding="utf-8")
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("LAUNCHED stage=two attempt=1/2"), out)
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["stages"]["two"]["attempts"], 1)

    def test_busy_tick_still_refreshes_state(self):
        sup.trainer_is_alive = lambda pattern: True
        self.write_state(sup._blank_state(self.plan))
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("BUSY"), out)
        self.assertNotEqual(self.state_path.stat().st_mtime, self.OLD)

    def test_first_completion_is_recorded_once_then_goes_quiet(self):
        (self.root / "one.done").write_text("x", encoding="utf-8")
        (self.root / "two.done").write_text("x", encoding="utf-8")
        self.write_state(sup._blank_state(self.plan))
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("COMPLETE"), out)
        self.assertIn("systemctl --user disable --now", out)
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertTrue(saved["complete"], "the transition must be persisted")
        self.assertIn("campaign complete", saved["history"][-1]["event"])

        os.utime(self.state_path, (self.OLD, self.OLD))
        os.utime(self.lock_path, (self.OLD, self.OLD))
        before = self.state_path.read_bytes()
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        self.assert_untouched(before)

    def test_attempt_cap_halt_is_recorded_once_then_goes_quiet(self):
        st = sup._blank_state(self.plan)
        st["stages"]["one"] = {"attempts": 2, "launched_utc": None, "last_pid": 1}
        self.write_state(st)
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("HALT stage one"), out)
        self.assertIn("systemctl --user disable --now", out)
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertTrue(saved["halted"], "the halt must be persisted")

        os.utime(self.state_path, (self.OLD, self.OLD))
        os.utime(self.lock_path, (self.OLD, self.OLD))
        before = self.state_path.read_bytes()
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("HALTED"), out)
        self.assert_untouched(before)
        self.assertEqual(self.launched, [])

    def test_extending_a_completed_plan_resumes_the_campaign(self):
        # `complete` is a record, not a latch: operators append stages to a
        # finished plan, and the next tick must launch the new stage.
        (self.root / "one.done").write_text("x", encoding="utf-8")
        (self.root / "two.done").write_text("x", encoding="utf-8")
        st = sup._blank_state(self.plan)
        st["complete"] = True
        self.write_state(st)
        self.plan["stages"].append(
            {"name": "three", "success": "three.done", "launch": "true"}
        )
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("LAUNCHED stage=three"), out)
        self.assertEqual(self.launched, [("three", 1)])
        self.assertNotEqual(self.state_path.stat().st_mtime, self.OLD)


if __name__ == "__main__":
    unittest.main()
