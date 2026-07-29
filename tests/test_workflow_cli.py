from __future__ import annotations

import json
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

    def test_micro_skips_task_packet(self) -> None:
        result = self.workflow("start", "--title", "typo", "--tier", "micro")
        self.assertIn("packet=skipped", result.stdout)
        self.assertFalse((self.repo / "workflow" / "tasks").exists())

    def test_agent_cap_and_cognitive_routing_are_auditable(self) -> None:
        self.workflow(
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
        task_path = self.repo / "workflow" / "tasks" / "task-route" / "task.json"
        task = json.loads(task_path.read_text(encoding="utf-8"))
        self.assertEqual(task["budget"]["max_subagents"], 0)
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

    def test_agent_limit_defaults_to_tier_and_cannot_exceed_it(self) -> None:
        config_path = self.repo / "workflow" / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["codex_workflow"].pop("max_subagents")
        config_path.write_text(json.dumps(config), encoding="utf-8")
        self.workflow(
            "start",
            "--title",
            "default agent limit",
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
        self.assertEqual(default_task["budget"]["max_subagents"], 2)

        config["codex_workflow"]["max_subagents"] = 99
        config_path.write_text(json.dumps(config), encoding="utf-8")
        self.workflow(
            "start",
            "--title",
            "tier capped agents",
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
        self.assertEqual(capped_task["budget"]["max_subagents"], 1)

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
        self.workflow("transition", "task-2", "--to", "EXECUTE")
        (self.repo / "outside.txt").write_text("outside\n", encoding="utf-8")
        result = self.workflow("verify", "task-2", expected=1)
        self.assertIn("result=FAIL", result.stdout)
        task = json.loads(
            (self.repo / "workflow" / "tasks" / "task-2" / "task.json").read_text(encoding="utf-8")
        )
        self.assertEqual(task["state"], "FIX")


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


if __name__ == "__main__":
    unittest.main()
