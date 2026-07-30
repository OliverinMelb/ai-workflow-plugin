from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CLI = Path(__file__).parents[1] / "skills" / "codex-workflow" / "scripts" / "workflow_cli.py"


class WorkflowCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.run_cmd("git", "init", "-q")
        self.run_cmd("git", "config", "user.email", "workflow-test@example.invalid")
        self.run_cmd("git", "config", "user.name", "Workflow Test")
        (self.repo / "app.txt").write_text("base\n", encoding="utf-8")
        workflow = self.repo / "workflow"
        workflow.mkdir()
        config = {
            "project_name": "fixture",
            "codex_workflow": {
                "version": 1,
                "default_class": "app-change",
                "max_fix_loops": 2,
                "max_subagents": 0,
                "check_timeout_seconds": 30,
            },
            "checks": {
                "app": [
                    {
                        "name": "smoke",
                        "dir": "",
                        "cmd": "python",
                        "args": ["-c", "print('ok')"],
                    }
                ]
            },
            "workflow_classes": {"app-change": ["app"]},
        }
        (workflow / "config.json").write_text(json.dumps(config), encoding="utf-8")
        (self.repo / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
        self.workflow("setup")
        self.run_cmd("git", "add", ".")
        self.run_cmd("git", "commit", "-qm", "fixture")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cmd(self, *args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(args),
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, expected, result.stdout)
        return result

    def workflow(self, *args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        return self.run_cmd(sys.executable, "-X", "utf8", str(CLI), *args, expected=expected)

    def ready_plan(self, task_id: str) -> None:
        self.workflow(
            "plan",
            task_id,
            "--acceptance",
            "Requested behavior is verified.",
            "--status",
            "ready",
            "--confirm-grilling",
        )

    def test_micro_skips_task_packet_without_imposing_an_agent_cap(self) -> None:
        result = self.workflow("start", "--title", "typo", "--tier", "micro")
        self.assertIn("packet=skipped", result.stdout)
        self.assertIn("subagent_limit=runtime", result.stdout)
        self.assertNotIn("subagents=0", result.stdout)
        self.assertFalse((self.repo / "workflow" / "tasks").exists())

    def test_runtime_managed_delegation_and_cognitive_routing_are_auditable(self) -> None:
        started = self.workflow(
            "start",
            "--title",
            "routed change",
            "--tier",
            "medium",
            "--owned-path",
            "app.txt",
            "--task-id",
            "task-route",
            "--skill",
            "diagnosing-bugs",
            "--source-ref",
            "issue:42",
            "--routing-note",
            "Reproduction established before implementation.",
        )
        self.assertIn("subagent_limit=runtime", started.stdout)
        self.assertIn(
            "parallel_write_isolation=dedicated-worktree",
            started.stdout,
        )
        task_path = self.repo / "workflow" / "tasks" / "task-route" / "task.json"
        task = json.loads(task_path.read_text(encoding="utf-8"))
        self.assertNotIn("max_subagents", task["budget"])
        self.assertEqual(
            task["delegation"],
            {
                "subagent_limit": "runtime",
                "parallel_write_isolation": "dedicated-worktree",
                "writers": [],
            },
        )
        self.assertEqual(task["cognitive_routing"]["skills"], ["diagnosing-bugs"])
        self.assertEqual(task["cognitive_routing"]["source_refs"], ["issue:42"])

        self.workflow(
            "route",
            "task-route",
            "--skill",
            "research",
            "--source-ref",
            "research/api-contract.md",
        )
        task = json.loads(task_path.read_text(encoding="utf-8"))
        self.assertEqual(
            task["cognitive_routing"]["skills"],
            ["diagnosing-bugs", "research"],
        )
        self.assertEqual(
            task["cognitive_routing"]["source_refs"],
            ["issue:42", "research/api-contract.md"],
        )
        self.assertEqual(task["history"][-1]["event"], "COGNITIVE_ROUTE")
        brief = task_path.with_name("brief.md").read_text(encoding="utf-8")
        self.assertIn("## Cognitive routing", brief)
        self.assertIn("diagnosing-bugs", brief)

    def test_assign_writer_records_and_validates_dedicated_worktree(self) -> None:
        invalid_scope = self.workflow(
            "start",
            "--title",
            "invalid writer scope",
            "--tier",
            "medium",
            "--owned-path",
            "src/../app.txt",
            "--task-id",
            "task-invalid-writer-scope",
            expected=2,
        )
        self.assertIn("must not contain '..'", invalid_scope.stdout)

        self.workflow(
            "start",
            "--title",
            "parallel writers",
            "--tier",
            "medium",
            "--owned-path",
            "app.txt",
            "--task-id",
            "task-writers",
        )
        writer_one = self.repo.parent / f"{self.repo.name}-writer-one"
        writer_two = self.repo.parent / f"{self.repo.name}-writer-two"
        self.run_cmd("git", "worktree", "add", "--detach", str(writer_one), "HEAD")
        self.run_cmd("git", "worktree", "add", "--detach", str(writer_two), "HEAD")
        try:
            assigned = self.workflow(
                "assign-writer",
                "task-writers",
                "--writer-id",
                "writer-one",
                "--worktree-path",
                str(writer_one),
                "--owned-path",
                "app.txt",
                "--integration-order",
                "1",
            )
            self.assertIn("writer_id=writer-one", assigned.stdout)
            task = json.loads(
                (
                    self.repo
                    / "workflow"
                    / "tasks"
                    / "task-writers"
                    / "task.json"
                ).read_text(encoding="utf-8")
            )
            writer = task["delegation"]["writers"][0]
            self.assertEqual(writer["worktree_path"], str(writer_one.resolve()))
            self.assertEqual(writer["workspace_kind"], "linked-worktree")
            self.assertTrue(writer["detached"])
            self.assertEqual(writer["base_sha"], task["workspace"]["base_sha"])
            self.assertEqual(writer["owned_paths"], ["app.txt"])
            self.assertEqual(writer["integration_order"], 1)

            overlap_path = "APP.TXT" if os.name == "nt" else "app.txt"
            overlap = self.workflow(
                "assign-writer",
                "task-writers",
                "--writer-id",
                "writer-two",
                "--worktree-path",
                str(writer_two),
                "--owned-path",
                overlap_path,
                "--integration-order",
                "2",
                expected=2,
            )
            self.assertIn("overlap", overlap.stdout.lower())

            nested = self.repo / ".nested-writer"
            self.run_cmd("git", "worktree", "add", "--detach", str(nested), "HEAD")
            try:
                nested_result = self.workflow(
                    "assign-writer",
                    "task-writers",
                    "--writer-id",
                    "nested-writer",
                    "--worktree-path",
                    str(nested),
                    "--owned-path",
                    "app.txt",
                    "--integration-order",
                    "3",
                    expected=2,
                )
                self.assertIn("sibling", nested_result.stdout.lower())
            finally:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(nested)],
                    cwd=self.repo,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(writer_two)],
                cwd=self.repo,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(writer_one)],
                cwd=self.repo,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

    def test_legacy_agent_limit_config_is_ignored_for_all_tiers(self) -> None:
        config_path = self.repo / "workflow" / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["codex_workflow"]["max_subagents"] = 0
        config_path.write_text(json.dumps(config), encoding="utf-8")
        self.workflow(
            "start",
            "--title",
            "legacy zero agent limit",
            "--tier",
            "medium",
            "--task-id",
            "task-default-agents",
        )
        default_task = json.loads(
            (
                self.repo
                / "workflow"
                / "tasks"
                / "task-default-agents"
                / "task.json"
            ).read_text(encoding="utf-8")
        )
        self.assertNotIn("max_subagents", default_task["budget"])
        self.assertEqual(default_task["delegation"]["subagent_limit"], "runtime")

        config["codex_workflow"]["max_subagents"] = 99
        config_path.write_text(json.dumps(config), encoding="utf-8")
        self.workflow(
            "start",
            "--title",
            "legacy high agent limit",
            "--tier",
            "small",
            "--task-id",
            "task-tier-agents",
        )
        capped_task = json.loads(
            (
                self.repo
                / "workflow"
                / "tasks"
                / "task-tier-agents"
                / "task.json"
            ).read_text(encoding="utf-8")
        )
        self.assertNotIn("max_subagents", capped_task["budget"])
        self.assertEqual(capped_task["delegation"]["subagent_limit"], "runtime")

    def test_route_rejects_empty_or_post_plan_updates(self) -> None:
        self.workflow(
            "start",
            "--title",
            "route guards",
            "--tier",
            "small",
            "--task-id",
            "task-route-guards",
        )
        empty = self.workflow("route", "task-route-guards", expected=2)
        self.assertIn("Provide at least one", empty.stdout)
        self.ready_plan("task-route-guards")
        self.workflow("transition", "task-route-guards", "--to", "EXECUTE")
        late = self.workflow(
            "route",
            "task-route-guards",
            "--skill",
            "research",
            expected=2,
        )
        self.assertIn("only allowed in PLAN or BLOCKED", late.stdout)

    def test_verify_review_and_close_with_preexisting_dirty_file(self) -> None:
        (self.repo / "user-note.txt").write_text("do not own\n", encoding="utf-8")
        result = self.workflow(
            "start",
            "--title",
            "bounded change",
            "--tier",
            "small",
            "--owned-path",
            "app.txt",
            "--task-id",
            "task-1",
        )
        self.assertIn("state=PLAN", result.stdout)
        self.ready_plan("task-1")
        self.workflow("transition", "task-1", "--to", "EXECUTE")
        (self.repo / "app.txt").write_text("changed\n", encoding="utf-8")
        verified = self.workflow("verify", "task-1")
        self.assertIn("result=PASS", verified.stdout)
        self.workflow("review", "task-1", "--verdict", "pass")
        closed = self.workflow("close", "task-1")
        self.assertIn("state=CLOSED", closed.stdout)
        task = json.loads(
            (self.repo / "workflow" / "tasks" / "task-1" / "task.json").read_text(encoding="utf-8")
        )
        self.assertEqual(task["state"], "CLOSED")
        evidence_path = (self.repo / task["verification"]["latest"]["evidence"]).with_suffix(".json")
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(evidence["changed_files"], ["app.txt"])
        self.assertIn("user-note.txt", evidence["unchanged_preexisting_dirty"])

    def test_out_of_scope_change_enters_fix(self) -> None:
        self.workflow(
            "start",
            "--title",
            "scope",
            "--tier",
            "small",
            "--owned-path",
            "app.txt",
            "--task-id",
            "task-2",
        )
        self.ready_plan("task-2")
        self.workflow("transition", "task-2", "--to", "EXECUTE")
        (self.repo / "outside.txt").write_text("outside\n", encoding="utf-8")
        result = self.workflow("verify", "task-2", expected=1)
        self.assertIn("result=FAIL", result.stdout)
        task = json.loads(
            (self.repo / "workflow" / "tasks" / "task-2" / "task.json").read_text(encoding="utf-8")
        )
        self.assertEqual(task["state"], "FIX")

    def test_plan_gate_requires_resolution_acceptance_and_medium_spec(self) -> None:
        self.workflow(
            "start",
            "--title",
            "planned change",
            "--tier",
            "medium",
            "--task-id",
            "task-plan-gate",
        )
        blocked = self.workflow(
            "transition",
            "task-plan-gate",
            "--to",
            "EXECUTE",
            expected=2,
        )
        self.assertIn("planning status is not ready", blocked.stdout)
        self.assertIn("grilling checkpoint is not confirmed", blocked.stdout)
        self.assertIn("acceptance criteria are empty", blocked.stdout)
        self.assertIn("require a local spec", blocked.stdout)

        self.workflow(
            "plan",
            "task-plan-gate",
            "--open-decision",
            "Which compatibility policy applies?",
            "--acceptance",
            "Compatibility behavior is covered.",
        )
        still_blocked = self.workflow(
            "plan",
            "task-plan-gate",
            "--status",
            "ready",
        )
        self.assertIn("unresolved=1", still_blocked.stdout)
        unconfirmed = self.workflow(
            "plan",
            "task-plan-gate",
            "--confirm-grilling",
            expected=2,
        )
        self.assertIn("unresolved decisions remain", unconfirmed.stdout)
        blocked = self.workflow(
            "transition",
            "task-plan-gate",
            "--to",
            "EXECUTE",
            expected=2,
        )
        self.assertIn("unresolved decisions remain", blocked.stdout)

        spec = self.repo / "workflow" / "tasks" / "task-plan-gate" / "spec.md"
        spec.write_text("# Spec\n", encoding="utf-8")
        self.workflow(
            "plan",
            "task-plan-gate",
            "--resolve-decision",
            "Which compatibility policy applies?",
            "--decision",
            "Preserve the existing policy.",
            "--spec-ref",
            "workflow/tasks/task-plan-gate/spec.md",
            "--confirm-grilling",
        )
        self.workflow("transition", "task-plan-gate", "--to", "EXECUTE")

    def test_plan_gate_requires_grilling_confirmation_before_execution(self) -> None:
        self.workflow(
            "start",
            "--title",
            "confirmed plan",
            "--tier",
            "small",
            "--task-id",
            "task-grilling-gate",
        )
        self.workflow(
            "plan",
            "task-grilling-gate",
            "--acceptance",
            "The agreed behavior is verified.",
            "--status",
            "ready",
        )

        blocked = self.workflow(
            "transition",
            "task-grilling-gate",
            "--to",
            "EXECUTE",
            expected=2,
        )
        self.assertIn("grilling checkpoint is not confirmed", blocked.stdout)

        confirmed = self.workflow(
            "plan",
            "task-grilling-gate",
            "--confirm-grilling",
        )
        self.assertIn("grilling=confirmed", confirmed.stdout)

        changed = self.workflow(
            "plan",
            "task-grilling-gate",
            "--acceptance",
            "A newly agreed constraint is also verified.",
        )
        self.assertIn("grilling=pending", changed.stdout)
        stale = self.workflow(
            "transition",
            "task-grilling-gate",
            "--to",
            "EXECUTE",
            expected=2,
        )
        self.assertIn("grilling checkpoint is not confirmed", stale.stdout)

        self.workflow("plan", "task-grilling-gate", "--confirm-grilling")
        self.workflow("transition", "task-grilling-gate", "--to", "EXECUTE")

    def test_multi_session_plan_records_tracer_tickets_and_edges(self) -> None:
        self.workflow(
            "start",
            "--title",
            "multi session",
            "--tier",
            "contract",
            "--task-id",
            "task-tickets",
        )
        spec = self.repo / "workflow" / "tasks" / "task-tickets" / "spec.md"
        spec.write_text("# Contract spec\n", encoding="utf-8")
        self.workflow(
            "ticket",
            "task-tickets",
            "--ticket-id",
            "T1",
            "--title",
            "Vertical tracer",
            "--acceptance",
            "One end-to-end path passes.",
        )
        self.workflow(
            "ticket",
            "task-tickets",
            "--ticket-id",
            "T2",
            "--title",
            "Complete remaining behavior",
            "--blocked-by",
            "T1",
            "--acceptance",
            "Remaining cases pass.",
        )
        self.workflow(
            "plan",
            "task-tickets",
            "--multi-session",
            "--spec-ref",
            "workflow/tasks/task-tickets/spec.md",
            "--acceptance",
            "Contract is verified end to end.",
            "--status",
            "ready",
            "--confirm-grilling",
        )
        self.workflow("transition", "task-tickets", "--to", "EXECUTE")
        task_path = self.repo / "workflow" / "tasks" / "task-tickets" / "task.json"
        task = json.loads(task_path.read_text(encoding="utf-8"))
        self.assertEqual(task["planning"]["tickets"][1]["blocked_by"], ["T1"])
        planning = task_path.with_name("planning.md").read_text(encoding="utf-8")
        self.assertIn("### T1: Vertical tracer", planning)
        self.assertIn("- blocked_by: T1", planning)

    def test_legacy_task_without_planning_keeps_transition_compatibility(self) -> None:
        self.workflow(
            "start",
            "--title",
            "legacy",
            "--tier",
            "small",
            "--task-id",
            "task-legacy",
        )
        task_path = self.repo / "workflow" / "tasks" / "task-legacy" / "task.json"
        task = json.loads(task_path.read_text(encoding="utf-8"))
        task["schema_version"] = 1
        task.pop("planning")
        task_path.write_text(json.dumps(task), encoding="utf-8")
        self.workflow("transition", "task-legacy", "--to", "EXECUTE")

    def test_schema_v2_cannot_bypass_gate_by_deleting_planning(self) -> None:
        self.workflow(
            "start",
            "--title",
            "tampered packet",
            "--tier",
            "small",
            "--task-id",
            "task-tampered",
        )
        task_path = self.repo / "workflow" / "tasks" / "task-tampered" / "task.json"
        task = json.loads(task_path.read_text(encoding="utf-8"))
        task.pop("planning")
        task_path.write_text(json.dumps(task), encoding="utf-8")
        result = self.workflow(
            "transition",
            "task-tampered",
            "--to",
            "EXECUTE",
            expected=2,
        )
        self.assertIn("schema v2 task is missing planning state", result.stdout)

    def test_existing_schema_v2_plan_without_grilling_status_requires_confirmation(self) -> None:
        self.workflow(
            "start",
            "--title",
            "pre-grilling task",
            "--tier",
            "small",
            "--task-id",
            "task-pre-grilling",
        )
        self.ready_plan("task-pre-grilling")
        task_path = (
            self.repo
            / "workflow"
            / "tasks"
            / "task-pre-grilling"
            / "task.json"
        )
        task = json.loads(task_path.read_text(encoding="utf-8"))
        task["planning"].pop("grilling_status")
        task_path.write_text(json.dumps(task), encoding="utf-8")

        blocked = self.workflow(
            "transition",
            "task-pre-grilling",
            "--to",
            "EXECUTE",
            expected=2,
        )
        self.assertIn("grilling checkpoint is not confirmed", blocked.stdout)

        self.workflow("plan", "task-pre-grilling", "--confirm-grilling")
        self.workflow("transition", "task-pre-grilling", "--to", "EXECUTE")

    def test_blocked_state_cannot_bypass_planning_gate(self) -> None:
        self.workflow(
            "start",
            "--title",
            "blocked bypass",
            "--tier",
            "small",
            "--task-id",
            "task-blocked-gate",
        )
        self.workflow("transition", "task-blocked-gate", "--to", "BLOCKED")
        result = self.workflow(
            "transition",
            "task-blocked-gate",
            "--to",
            "EXECUTE",
            expected=2,
        )
        self.assertIn("PLAN -> EXECUTE blocked", result.stdout)

    def test_ticket_dependency_cycle_is_rejected(self) -> None:
        self.workflow(
            "start",
            "--title",
            "cyclic tickets",
            "--tier",
            "small",
            "--task-id",
            "task-cycle",
        )
        self.workflow(
            "ticket",
            "task-cycle",
            "--ticket-id",
            "T1",
            "--title",
            "First",
            "--blocked-by",
            "T2",
            "--acceptance",
            "First passes.",
        )
        self.workflow(
            "ticket",
            "task-cycle",
            "--ticket-id",
            "T2",
            "--title",
            "Second",
            "--blocked-by",
            "T1",
            "--acceptance",
            "Second passes.",
        )
        self.workflow(
            "plan",
            "task-cycle",
            "--acceptance",
            "Workflow completes.",
            "--status",
            "ready",
        )
        result = self.workflow(
            "transition",
            "task-cycle",
            "--to",
            "EXECUTE",
            expected=2,
        )
        self.assertIn("dependency graph contains a cycle", result.stdout)

    def test_resolving_decision_requires_recorded_resolution(self) -> None:
        self.workflow(
            "start",
            "--title",
            "decision audit",
            "--tier",
            "small",
            "--task-id",
            "task-decision",
        )
        self.workflow(
            "plan",
            "task-decision",
            "--open-decision",
            "Which mode?",
        )
        result = self.workflow(
            "plan",
            "task-decision",
            "--resolve-decision",
            "Which mode?",
            "--decision",
            " ",
            expected=2,
        )
        self.assertIn("requires a corresponding --decision", result.stdout)

    def test_spec_change_invalidates_verification_evidence(self) -> None:
        self.workflow(
            "start",
            "--title",
            "spec freshness",
            "--tier",
            "medium",
            "--owned-path",
            "app.txt",
            "--task-id",
            "task-spec-freshness",
        )
        spec = self.repo / "workflow" / "tasks" / "task-spec-freshness" / "spec.md"
        spec.write_text("# Spec v1\n", encoding="utf-8")
        self.workflow(
            "plan",
            "task-spec-freshness",
            "--spec-ref",
            "workflow/tasks/task-spec-freshness/spec.md",
            "--acceptance",
            "Behavior passes.",
            "--status",
            "ready",
            "--confirm-grilling",
        )
        self.workflow("transition", "task-spec-freshness", "--to", "EXECUTE")
        (self.repo / "app.txt").write_text("changed\n", encoding="utf-8")
        self.workflow("verify", "task-spec-freshness")
        spec.write_text("# Spec v2\n", encoding="utf-8")
        result = self.workflow(
            "review",
            "task-spec-freshness",
            "--verdict",
            "pass",
            expected=2,
        )
        self.assertIn("local spec changed after verification", result.stdout)


class WorkflowInitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.run_cmd("git", "init", "-q")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cmd(self, *args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(args),
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, expected, result.stdout)
        return result

    def workflow(self, *args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        return self.run_cmd(sys.executable, "-X", "utf8", str(CLI), *args, expected=expected)

    def dry_run_fixture(self, name: str, files: dict[str, str]) -> dict:
        fixture = self.repo / name
        fixture.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=fixture, check=True)
        for relative, content in files.items():
            path = fixture / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(CLI), "init", "--dry-run"],
            cwd=fixture,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        return json.loads(result.stdout)

    def test_init_detects_python_and_runs_doctor(self) -> None:
        (self.repo / "pyproject.toml").write_text(
            "[project]\nname='fixture'\n"
            "[project.optional-dependencies]\ndev=['pytest>=8']\n",
            encoding="utf-8",
        )
        tests = self.repo / "tests"
        tests.mkdir()
        (tests / "test_smoke.py").write_text(
            "def test_smoke():\n    assert True\n",
            encoding="utf-8",
        )
        result = self.workflow("init", "--project-name", "fixture")
        self.assertIn("detected=python", result.stdout)
        self.assertIn('"valid": true', result.stdout)
        config = json.loads(
            (self.repo / "workflow" / "config.json").read_text(encoding="utf-8")
        )
        self.assertEqual(config["project_name"], "fixture")
        self.assertEqual(config["workflow_classes"]["app-change"], ["python"])
        self.assertEqual(config["checks"]["python"][0]["args"], ["-m", "pytest"])
        self.assertNotIn("global_memory_dir", config["codex_workflow"])
        self.assertNotIn("max_subagents", config["codex_workflow"])

    def test_init_refuses_to_overwrite_existing_config(self) -> None:
        workflow = self.repo / "workflow"
        workflow.mkdir()
        config_path = workflow / "config.json"
        original = '{"project_name":"keep-me"}\n'
        config_path.write_text(original, encoding="utf-8")
        result = self.workflow("init", expected=2)
        self.assertIn("refusing to overwrite", result.stdout)
        self.assertEqual(config_path.read_text(encoding="utf-8"), original)

    def test_init_dry_run_detects_node_without_writing(self) -> None:
        (self.repo / "package.json").write_text(
            json.dumps(
                {
                    "name": "web-fixture",
                    "scripts": {
                        "lint": "eslint .",
                        "test": "vitest run",
                        "build": "vite build",
                    },
                }
            ),
            encoding="utf-8",
        )
        result = self.workflow("init", "--dry-run")
        config = json.loads(result.stdout)
        self.assertEqual(config["workflow_classes"]["app-change"], ["node"])
        self.assertEqual(
            [item["name"] for item in config["checks"]["node"]],
            ["lint", "test", "build"],
        )
        self.assertFalse((self.repo / "workflow").exists())

    def test_init_detects_maven_gradle_and_generic_repositories(self) -> None:
        maven = self.dry_run_fixture(
            "maven",
            {"pom.xml": "<project/>", "mvnw.cmd": "@echo off\n"},
        )
        self.assertEqual(maven["workflow_classes"]["app-change"], ["maven"])
        self.assertEqual(maven["checks"]["maven"][0]["cmd"], "cmd")

        gradle = self.dry_run_fixture(
            "gradle",
            {"build.gradle.kts": "plugins {}", "gradlew.bat": "@echo off\n"},
        )
        self.assertEqual(gradle["workflow_classes"]["app-change"], ["gradle"])
        self.assertEqual(gradle["checks"]["gradle"][0]["cmd"], "cmd")

        generic = self.dry_run_fixture("generic", {})
        self.assertEqual(generic["workflow_classes"]["app-change"], ["repository"])
        self.assertEqual(generic["checks"]["repository"][0]["args"], ["diff", "--check"])

    def test_setup_adds_local_project_conventions(self) -> None:
        self.workflow("init", "--project-name", "fixture")
        (self.repo / "AGENTS.md").write_text("# Project rules\n", encoding="utf-8")
        result = self.workflow(
            "setup",
            "--tracker",
            "local",
            "--publication-policy",
            "explicit",
            "--domain-layout",
            "single",
            "--with-triage",
        )
        self.assertIn("tracker=local", result.stdout)
        self.workflow(
            "setup",
            "--tracker",
            "local",
            "--publication-policy",
            "explicit",
            "--domain-layout",
            "single",
            "--with-triage",
        )
        config = json.loads(
            (self.repo / "workflow" / "config.json").read_text(encoding="utf-8")
        )
        conventions = config["project_conventions"]
        self.assertEqual(conventions["tracker"]["kind"], "local")
        self.assertEqual(
            conventions["tracker"]["publication_policy"],
            "explicit",
        )
        self.assertTrue(conventions["triage"]["enabled"])
        self.assertIn(
            "Issue tracker: docs/agents/issue-tracker.md",
            config["memory"]["pointers"],
        )
        tracker = (self.repo / "docs" / "agents" / "issue-tracker.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(".scratch/<feature>/issues/", tracker)
        self.assertIn("explicit user authorization", tracker)
        agents = (self.repo / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(agents.count("## Agent skills"), 1)
        self.assertIn("codex-workflow:project-conventions:start", agents)

    def test_setup_dry_run_writes_nothing(self) -> None:
        self.workflow("init")
        result = self.workflow(
            "setup",
            "--agent-file",
            "CLAUDE.md",
            "--dry-run",
        )
        preview = json.loads(result.stdout)
        self.assertEqual(preview["project_conventions"]["tracker"]["kind"], "local")
        self.assertIn("CLAUDE.md", preview["files"])
        self.assertFalse((self.repo / "CLAUDE.md").exists())
        config = json.loads(
            (self.repo / "workflow" / "config.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("project_conventions", config)

    def test_setup_forbidden_policy_rejects_remote_tracker(self) -> None:
        self.workflow("init")
        (self.repo / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
        result = self.workflow(
            "setup",
            "--tracker",
            "github",
            "--publication-policy",
            "forbidden",
            expected=2,
        )
        self.assertIn("requires the local tracker", result.stdout)
        self.assertFalse((self.repo / "docs" / "agents").exists())

    def test_setup_refuses_unmanaged_agent_skills_section(self) -> None:
        self.workflow("init")
        (self.repo / "AGENTS.md").write_text(
            "## Agent skills\n\nUser-owned rules.\n",
            encoding="utf-8",
        )
        result = self.workflow("setup", expected=2)
        self.assertIn("merge it manually", result.stdout)
        self.assertFalse((self.repo / "docs" / "agents").exists())

    def test_non_micro_start_requires_project_conventions(self) -> None:
        self.workflow("init")
        result = self.workflow(
            "start",
            "--title",
            "missing setup",
            "--tier",
            "small",
            expected=2,
        )
        self.assertIn("run workflow setup", result.stdout)

    def test_start_rejects_tampered_forbidden_remote_conventions(self) -> None:
        self.workflow("init")
        (self.repo / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
        self.workflow("setup", "--publication-policy", "forbidden")
        config_path = self.repo / "workflow" / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["project_conventions"]["tracker"]["kind"] = "github"
        config["project_conventions"]["tracker"]["remote"] = "https://example.invalid/repo"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        result = self.workflow(
            "start",
            "--title",
            "tampered policy",
            "--tier",
            "small",
            expected=2,
        )
        self.assertIn("forbidden publication requires the local tracker", result.stdout)

    def test_start_rejects_tampered_convention_document(self) -> None:
        self.workflow("init")
        (self.repo / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
        self.workflow("setup")
        (self.repo / "docs" / "agents" / "issue-tracker.md").write_text(
            "# Replaced\n",
            encoding="utf-8",
        )
        result = self.workflow(
            "start",
            "--title",
            "tampered docs",
            "--tier",
            "small",
            expected=2,
        )
        self.assertIn("Project convention changed", result.stdout)

    def test_start_rejects_tampered_managed_agent_block(self) -> None:
        self.workflow("init")
        agent = self.repo / "AGENTS.md"
        agent.write_text("# Rules\n", encoding="utf-8")
        self.workflow("setup")
        content = agent.read_text(encoding="utf-8")
        agent.write_text(
            content.replace(
                "Publication policy is `explicit`",
                "Publication policy is `forbidden`",
            ),
            encoding="utf-8",
        )
        result = self.workflow(
            "start",
            "--title",
            "tampered block",
            "--tier",
            "small",
            expected=2,
        )
        self.assertIn("Managed project-conventions block changed", result.stdout)

    def test_setup_rejects_reversed_managed_markers(self) -> None:
        self.workflow("init")
        (self.repo / "AGENTS.md").write_text(
            "<!-- codex-workflow:project-conventions:end -->\n"
            "content\n"
            "<!-- codex-workflow:project-conventions:start -->\n",
            encoding="utf-8",
        )
        result = self.workflow("setup", expected=2)
        self.assertIn("Reversed managed", result.stdout)

    def test_other_tracker_and_triage_overrides_are_recorded(self) -> None:
        self.workflow("init")
        (self.repo / "CLAUDE.md").write_text("# Rules\n", encoding="utf-8")
        self.workflow(
            "setup",
            "--tracker",
            "other",
            "--tracker-url",
            "https://tracker.example.invalid/project",
            "--tracker-instructions",
            "Use the internal tracker client for fetch, comment, and close.",
            "--with-triage",
            "--triage-label",
            "needs-triage=bug:triage",
        )
        tracker = (self.repo / "docs" / "agents" / "issue-tracker.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Wayfinding operations", tracker)
        self.assertIn("fetch, comment, and close", tracker)
        labels = (self.repo / "docs" / "agents" / "triage-labels.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("needs-triage: `bug:triage`", labels)
        started = self.workflow(
            "start",
            "--title",
            "custom tracker task",
            "--tier",
            "small",
        )
        self.assertIn("state=PLAN", started.stdout)

    def test_rh_task_requires_private_project_profile(self) -> None:
        self.workflow("init")
        (self.repo / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
        self.workflow("setup")
        result = self.workflow(
            "start",
            "--title",
            "rh task",
            "--tier",
            "small",
            "--skill",
            "rh-company-workflow",
            expected=2,
        )
        self.assertIn("RH tasks require private project conventions", result.stdout)

    def test_setup_rejects_agent_symlink_outside_repository(self) -> None:
        self.workflow("init")
        outside = self.repo.parent / f"{self.repo.name}-outside-agent.md"
        outside.write_text("keep\n", encoding="utf-8")
        link = self.repo / "AGENTS.md"
        try:
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"Symlink creation is unavailable: {exc}")
            result = self.workflow("setup", expected=2)
            self.assertIn("escapes the repository", result.stdout)
            self.assertEqual(outside.read_text(encoding="utf-8"), "keep\n")
        finally:
            if outside.exists():
                outside.unlink()

    def test_private_profile_allows_rh_task_with_local_forbidden_policy(self) -> None:
        self.workflow("init")
        (self.repo / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
        self.workflow(
            "setup",
            "--profile",
            "private",
            "--tracker",
            "local",
            "--publication-policy",
            "forbidden",
        )
        result = self.workflow(
            "start",
            "--title",
            "private rh task",
            "--tier",
            "small",
            "--skill",
            "rh-company-workflow",
        )
        self.assertIn("state=PLAN", result.stdout)

    def test_setup_rejects_credentials_in_tracker_url_without_echoing_them(self) -> None:
        self.workflow("init")
        (self.repo / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
        result = self.workflow(
            "setup",
            "--tracker",
            "github",
            "--tracker-url",
            "https://user:super-secret@github.com/example/repo.git",
            expected=2,
        )
        self.assertIn("contains credentials", result.stdout)
        self.assertNotIn("super-secret", result.stdout)
        self.assertFalse((self.repo / "docs" / "agents").exists())
        query_result = self.workflow(
            "setup",
            "--tracker",
            "other",
            "--tracker-url",
            "https://tracker.example.invalid/project?private_token=super-secret",
            "--tracker-instructions",
            "Use the tracker client.",
            expected=2,
        )
        self.assertIn("query data", query_result.stdout)
        self.assertNotIn("super-secret", query_result.stdout)

    def test_github_tracker_document_contains_deterministic_operations(self) -> None:
        self.workflow("init")
        (self.repo / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
        self.workflow(
            "setup",
            "--tracker",
            "github",
            "--tracker-url",
            "https://github.com/example/repo.git",
        )
        tracker = (self.repo / "docs" / "agents" / "issue-tracker.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("gh issue view", tracker)
        self.assertIn("pull_request", tracker)
        self.assertIn("wayfinder frontier", tracker)


if __name__ == "__main__":
    unittest.main()
