#!/usr/bin/env python3
"""Deterministic workflow state and verification for Codex-managed workspaces."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ENGINE_VERSION = "1.0.0"
ACTIVE_STATES = {"PLAN", "EXECUTE", "VERIFY", "REVIEW", "FIX", "INTEGRATE", "BLOCKED"}
ALLOWED = {
    "PLAN": {"EXECUTE", "BLOCKED"},
    "EXECUTE": {"VERIFY", "BLOCKED"},
    "VERIFY": {"REVIEW", "FIX", "BLOCKED"},
    "REVIEW": {"FIX", "INTEGRATE", "BLOCKED"},
    "FIX": {"VERIFY", "BLOCKED"},
    "INTEGRATE": {"VERIFY", "CLOSED", "BLOCKED"},
    "BLOCKED": {"PLAN", "EXECUTE", "FIX"},
    "CLOSED": set(),
}


class WorkflowError(RuntimeError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def run(
    args: list[str],
    cwd: Path,
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        timeout=timeout,
        shell=False,
    )
    if check and result.returncode:
        raise WorkflowError(f"Command failed ({result.returncode}): {' '.join(args)}\n{result.stdout}")
    return result


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    if check and result.returncode:
        diagnostics = "\n".join(
            value.rstrip("\r\n") for value in (result.stdout, result.stderr) if value
        )
        raise WorkflowError(f"Command failed ({result.returncode}): git {' '.join(args)}\n{diagnostics}")
    return result.stdout.rstrip("\r\n")


def repo_root(start: Path | None = None) -> Path:
    cwd = (start or Path.cwd()).resolve()
    result = run(["git", "rev-parse", "--show-toplevel"], cwd, check=False)
    if result.returncode:
        raise WorkflowError(f"Not inside a Git repository: {cwd}")
    return Path(result.stdout.strip()).resolve()


def load_config(repo: Path) -> tuple[Path, dict[str, Any]]:
    path = repo / "workflow" / "config.json"
    if not path.exists():
        raise WorkflowError(f"Missing workflow configuration: {path}")
    try:
        return path, json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"Invalid UTF-8 JSON in {path}: {exc}") from exc


def read_project_text(path: Path, limit: int = 1_000_000) -> str:
    """Read non-secret project metadata without following arbitrarily large files."""
    try:
        if not path.is_file() or path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def project_documents(repo: Path) -> list[str]:
    candidates = (
        "AGENTS.md",
        "README.md",
        "README-CODEX.md",
        "ARCHITECTURE.md",
        "DESIGN.md",
        "CONTRIBUTING.md",
        "pyproject.toml",
        "package.json",
        "pom.xml",
    )
    labels = {
        "AGENTS.md": "Agent rules",
        "README.md": "Project guide",
        "README-CODEX.md": "Codex guide",
        "ARCHITECTURE.md": "Architecture",
        "DESIGN.md": "Design",
        "CONTRIBUTING.md": "Contributing",
        "pyproject.toml": "Python project",
        "package.json": "Node project",
        "pom.xml": "Maven project",
    }
    return [f"{labels[name]}: {name}" for name in candidates if (repo / name).is_file()]


def python_markers(repo: Path) -> str:
    paths = [
        repo / "pyproject.toml",
        repo / "setup.cfg",
        repo / "tox.ini",
        repo / "requirements.txt",
        repo / "requirements-dev.txt",
    ]
    tests = repo / "tests"
    if tests.is_dir():
        paths.extend(sorted(tests.rglob("test*.py"))[:40])
    return "\n".join(read_project_text(path) for path in paths).lower()


def detect_python(repo: Path) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    has_python = any(
        (
            (repo / "pyproject.toml").is_file(),
            (repo / "setup.py").is_file(),
            (repo / "setup.cfg").is_file(),
            (repo / "requirements.txt").is_file(),
            (repo / "tests").is_dir() and any((repo / "tests").glob("test*.py")),
        )
    )
    if not has_python:
        return None
    venv = next(
        (
            name
            for name in (".venv", "venv", "env")
            if (repo / name / ("Scripts/python.exe" if os.name == "nt" else "bin/python")).is_file()
        ),
        None,
    )
    markers = python_markers(repo)
    uses_pytest = "pytest" in markers
    component: dict[str, Any] = {"dir": "", "type": "python-venv"}
    component["probe_imports"] = ["pytest"] if uses_pytest else []
    if (repo / "tests").is_dir():
        args = ["-m", "pytest"] if uses_pytest else ["-m", "unittest", "discover", "-s", "tests", "-v"]
        check_name = "pytest" if uses_pytest else "unittest"
    else:
        source = "src" if (repo / "src").is_dir() else "."
        args = ["-m", "compileall", "-q", source]
        check_name = "compileall"
    checks = [
        {
            "name": check_name,
            "dir": "",
            "cmd": "python",
            "args": args,
            "timeout_seconds": 900,
        }
    ]
    if venv:
        component["venv"] = venv
    return component, checks


def detect_node(repo: Path) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    package_path = repo / "package.json"
    if not package_path.is_file():
        return None
    try:
        package = json.loads(read_project_text(package_path))
    except json.JSONDecodeError:
        package = {}
    scripts = package.get("scripts") if isinstance(package, dict) else {}
    scripts = scripts if isinstance(scripts, dict) else {}
    if (repo / "pnpm-lock.yaml").is_file():
        manager = "pnpm"
    elif (repo / "yarn.lock").is_file():
        manager = "yarn"
    else:
        manager = "npm"
    checks: list[dict[str, Any]] = []
    for name in ("lint", "test", "build"):
        value = scripts.get(name)
        if not isinstance(value, str) or not value.strip():
            continue
        if name == "test" and "no test specified" in value.lower():
            continue
        checks.append(
            {
                "name": name,
                "dir": "",
                "cmd": manager,
                "args": [name] if manager != "npm" else ["run", name],
                "timeout_seconds": 900,
            }
        )
    if not checks:
        checks.append(
            {
                "name": "package-metadata",
                "dir": "",
                "cmd": "node",
                "args": ["-e", "JSON.parse(require('fs').readFileSync('package.json','utf8'))"],
                "timeout_seconds": 60,
            }
        )
    component = {
        "dir": "",
        "type": "node",
        "package_manager": manager,
        "probe_modules": [],
    }
    return component, checks


def detect_maven(repo: Path) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    if not (repo / "pom.xml").is_file():
        return None
    if os.name == "nt" and (repo / "mvnw.cmd").is_file():
        cmd, args = "cmd", ["/c", "mvnw.cmd", "-q", "test"]
    elif (repo / "mvnw").is_file():
        cmd, args = str(repo / "mvnw"), ["-q", "test"]
    else:
        cmd, args = "mvn", ["-q", "test"]
    return (
        {"dir": "", "type": "maven"},
        [{"name": "maven-test", "dir": "", "cmd": cmd, "args": args, "timeout_seconds": 1200}],
    )


def detect_gradle(repo: Path) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    if not any((repo / name).is_file() for name in ("build.gradle", "build.gradle.kts")):
        return None
    if os.name == "nt" and (repo / "gradlew.bat").is_file():
        cmd, args = "cmd", ["/c", "gradlew.bat", "test"]
    elif (repo / "gradlew").is_file():
        cmd, args = str(repo / "gradlew"), ["test"]
    else:
        cmd, args = "gradle", ["test"]
    return (
        {"dir": "", "type": "gradle"},
        [{"name": "gradle-test", "dir": "", "cmd": cmd, "args": args, "timeout_seconds": 1200}],
    )


def generated_config(repo: Path, project_name: str | None = None) -> tuple[dict[str, Any], list[str]]:
    components: dict[str, Any] = {}
    checks: dict[str, list[dict[str, Any]]] = {}
    detected: list[str] = []
    for name, detector in (
        ("python", detect_python),
        ("node", detect_node),
        ("maven", detect_maven),
        ("gradle", detect_gradle),
    ):
        result = detector(repo)
        if result is None:
            continue
        component, group_checks = result
        components[name] = component
        checks[name] = group_checks
        detected.append(name)
    if not detected:
        components["repository"] = {"dir": "", "type": "generic"}
        checks["repository"] = [
            {
                "name": "git-diff-check",
                "dir": "",
                "cmd": "git",
                "args": ["diff", "--check"],
                "timeout_seconds": 60,
            }
        ]
        detected.append("repository")
    python_config: dict[str, Any] = {}
    python_component = components.get("python", {})
    if python_component.get("venv"):
        python_config["venv"] = python_component.pop("venv")
    contract_markers = [
        path
        for path in ("api/", "apis/", "schema/", "schemas/", "openapi/", "src/models.py")
        if (repo / path.rstrip("/")).exists()
    ]
    config: dict[str, Any] = {
        "$comment": (
            "Generated by codex-workflow init from repository metadata. "
            "Review project-specific checks before the first production change."
        ),
        "project_name": project_name or repo.name,
        "memory": {"pointers": project_documents(repo)},
        "codex_workflow": {
            "version": 1,
            "default_tier": "small",
            "default_class": "app-change",
            "max_fix_loops": 2,
            "max_subagents": 1,
            "check_timeout_seconds": 900,
        },
        "components": components,
        "checks": checks,
        "workflow_classes": {"app-change": detected},
        "auto_check": None,
        "contract_touchpoints": {
            "$comment": "Conservative path markers only; add structural checks when contracts are known.",
            "surface_markers": contract_markers,
            "structural_checks": [],
        },
        "env_consistency": {
            "$comment": "Never store secret values here. Add only required variable-name markers.",
            "rules": [],
        },
    }
    if python_config:
        config["python"] = python_config
    return config, detected


def cmd_init(args: argparse.Namespace) -> int:
    repo = repo_root()
    path = repo / "workflow" / "config.json"
    if path.exists():
        raise WorkflowError(f"Workflow configuration already exists; refusing to overwrite: {path}")
    config, detected = generated_config(repo, args.project_name)
    if args.dry_run:
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return 0
    atomic_json(path, config)
    print(f"created={path}")
    print(f"detected={','.join(detected)}")
    print("doctor:")
    return cmd_doctor(argparse.Namespace())


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_hash(repo: Path, relative: str) -> str:
    path = repo / relative
    if not path.exists():
        return "<missing>"
    if path.is_dir():
        return "<directory>"
    try:
        return sha256_bytes(path.read_bytes())
    except OSError:
        return "<unreadable>"


def status_entries(repo: Path) -> list[dict[str, str]]:
    raw = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if not raw:
        return []
    tokens = raw.split("\0")
    entries: list[dict[str, str]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token:
            continue
        status = token[:2]
        path = token[3:]
        if ("R" in status or "C" in status) and index < len(tokens):
            path = tokens[index]
            index += 1
        path = path.replace("\\", "/")
        entries.append({"status": status, "path": path, "hash": file_hash(repo, path)})
    return sorted(entries, key=lambda item: item["path"])


def dirty_fingerprint(entries: list[dict[str, str]]) -> str:
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return sha256_bytes(payload)


def workspace_info(repo: Path, ignore_prefixes: list[str] | None = None) -> dict[str, Any]:
    git_dir_text = git(repo, "rev-parse", "--git-dir")
    common_text = git(repo, "rev-parse", "--git-common-dir")
    git_dir = (repo / git_dir_text).resolve() if not Path(git_dir_text).is_absolute() else Path(git_dir_text).resolve()
    common_dir = (repo / common_text).resolve() if not Path(common_text).is_absolute() else Path(common_text).resolve()
    branch = git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False) or None
    prefixes = [value.strip("/").replace("\\", "/") + "/" for value in (ignore_prefixes or [])]
    entries = [
        item
        for item in status_entries(repo)
        if not any(item["path"].startswith(prefix) for prefix in prefixes)
    ]
    return {
        "kind": "linked-worktree" if git_dir != common_dir else "main-checkout",
        "branch": branch,
        "detached": branch is None,
        "head_sha": git(repo, "rev-parse", "--verify", "HEAD", check=False) or "<unborn>",
        "dirty_fingerprint": dirty_fingerprint(entries),
        "dirty_entries": entries,
    }


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def task_dir(repo: Path, task_id: str) -> Path:
    return repo / "workflow" / "tasks" / task_id


def task_path(repo: Path, task_id: str) -> Path:
    return task_dir(repo, task_id) / "task.json"


def load_task(repo: Path, task_id: str) -> dict[str, Any]:
    path = task_path(repo, task_id)
    if not path.exists():
        raise WorkflowError(f"Task not found: {task_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_task(repo: Path, task: dict[str, Any], event: str, details: Any = None) -> None:
    task["updated_at"] = now()
    task.setdefault("history", []).append({"at": task["updated_at"], "event": event, "details": details})
    atomic_json(task_path(repo, task["task_id"]), task)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "task")[:36]


def path_owned(path: str, owned_paths: list[str]) -> bool:
    normalized = path.strip("/").replace("\\", "/")
    for owner in owned_paths:
        candidate = owner.strip("/").replace("\\", "/")
        if normalized == candidate or normalized.startswith(candidate + "/"):
            return True
    return False


def changed_files(repo: Path, task: dict[str, Any]) -> tuple[list[str], list[str]]:
    base_sha = task["workspace"]["base_sha"]
    commands = []
    if base_sha != "<unborn>":
        commands.append(["diff", "--name-only", f"{base_sha}...HEAD"])
    commands.extend(
        [
            ["diff", "--cached", "--name-only"],
            ["diff", "--name-only"],
            ["ls-files", "--others", "--exclude-standard"],
        ]
    )
    candidates: set[str] = set()
    for args in commands:
        output = git(repo, *args, check=False)
        candidates.update(line.replace("\\", "/") for line in output.splitlines() if line.strip())

    engine_prefix = f"workflow/tasks/{task['task_id']}/"
    candidates = {path for path in candidates if not path.startswith(engine_prefix)}
    baseline = {item["path"]: item["hash"] for item in task["workspace"].get("dirty_entries", [])}
    attributable: list[str] = []
    unchanged_baseline: list[str] = []
    for path in sorted(candidates):
        if path in baseline and file_hash(repo, path) == baseline[path]:
            unchanged_baseline.append(path)
        else:
            attributable.append(path)
    return attributable, unchanged_baseline


def resolve_python(repo: Path, config: dict[str, Any]) -> str:
    venv = config.get("python", {}).get("venv")
    if venv:
        root = repo / str(venv)
        candidate = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if candidate.exists():
            return str(candidate)
    configured = os.environ.get("WORKFLOW_PYTHON")
    if configured and Path(configured).exists():
        return configured
    return sys.executable


def executable(cmd: str, repo: Path, config: dict[str, Any]) -> str:
    if cmd.lower() == "python":
        return resolve_python(repo, config)
    found = shutil.which(cmd)
    if found:
        return found
    if os.name == "nt":
        found = shutil.which(cmd + ".cmd") or shutil.which(cmd + ".exe")
    if not found:
        raise WorkflowError(f"Executable not found: {cmd}")
    return found


def redact_proxy(value: str | None) -> str | None:
    if not value:
        return value
    return re.sub(r"(://)[^/@]+@", r"\1<credentials>@", value)


def system_proxy() -> dict[str, Any]:
    result: dict[str, Any] = {
        "environment": {
            key: redact_proxy(os.environ.get(key))
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
            if os.environ.get(key)
        }
    }
    if os.name != "nt":
        return result
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            enabled = bool(winreg.QueryValueEx(key, "ProxyEnable")[0])
            server = str(winreg.QueryValueEx(key, "ProxyServer")[0]) if enabled else ""
        result["windows"] = {"enabled": enabled, "server": redact_proxy(server)}
        endpoint = server.split(";")[0].split("=")[-1] if server else ""
        if ":" in endpoint:
            host, port_text = endpoint.rsplit(":", 1)
            try:
                with socket.create_connection((host, int(port_text)), timeout=0.5):
                    listening = True
            except (OSError, ValueError):
                listening = False
            result["windows"]["listening"] = listening
    except (OSError, ImportError):
        result["windows"] = {"enabled": None, "server": None}
    return result


def cmd_doctor(args: argparse.Namespace) -> int:
    repo = repo_root()
    findings: dict[str, Any] = {
        "engine_version": ENGINE_VERSION,
        "repo_root": str(repo),
        "platform": platform.platform(),
        "python": {
            "engine": sys.executable,
            "utf8_mode": sys.flags.utf8_mode,
            "default_encoding": sys.getdefaultencoding(),
        },
        "proxy": system_proxy(),
    }
    try:
        config_path, config = load_config(repo)
        findings["config"] = {"path": str(config_path), "valid": True}
        findings["python"]["project"] = resolve_python(repo, config)
        findings["workspace"] = workspace_info(repo)
        findings["tools"] = {
            "git": shutil.which("git"),
            "node": shutil.which("node"),
            "npm": shutil.which("npm") or shutil.which("npm.cmd"),
        }
    except WorkflowError as exc:
        findings["config"] = {"valid": False, "error": str(exc)}
    print(json.dumps(findings, ensure_ascii=False, indent=2))
    return 0 if findings.get("config", {}).get("valid") else 2


def cmd_start(args: argparse.Namespace) -> int:
    if args.tier == "micro":
        print("tier=micro\npacket=skipped\nsubagents=0")
        return 0
    repo = repo_root()
    _, config = load_config(repo)
    classes = config.get("workflow_classes", {})
    settings = config.get("codex_workflow", {})
    workflow_class = args.workflow_class or settings.get("default_class")
    if workflow_class not in classes:
        raise WorkflowError(
            f"Unknown workflow class '{workflow_class}'. Available: {', '.join(sorted(classes))}"
        )
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    task_id = args.task_id or f"{timestamp}-{slugify(args.title)}"
    path = task_path(repo, task_id)
    if path.exists():
        raise WorkflowError(f"Task already exists: {task_id}")
    workspace = workspace_info(repo)
    max_loops = args.max_fix_loops if args.max_fix_loops is not None else int(settings.get("max_fix_loops", 2))
    max_agents = {"small": 1, "medium": 2, "contract": 2}[args.tier]
    task = {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "task_id": task_id,
        "title": args.title,
        "tier": args.tier,
        "workflow_class": workflow_class,
        "state": "PLAN",
        "created_at": now(),
        "updated_at": now(),
        "workspace": {**workspace, "base_sha": workspace["head_sha"]},
        "scope": {"owned_paths": sorted(set(args.owned_path or []))},
        "budget": {
            "max_subagents": max_agents,
            "max_fix_loops": max_loops,
            "fix_loops": 0,
            "verification_attempts": 0,
        },
        "verification": {"latest": None},
        "history": [{"at": now(), "event": "TASK_STARTED", "details": None}],
    }
    atomic_json(path, task)
    brief = task_dir(repo, task_id) / "brief.md"
    brief.write_text(
        f"# Task Brief\n\n"
        f"- task_id: `{task_id}`\n"
        f"- title: {args.title}\n"
        f"- tier: `{args.tier}`\n"
        f"- workflow_class: `{workflow_class}`\n"
        f"- base_sha: `{workspace['head_sha']}`\n"
        f"- workspace: `{workspace['kind']}`\n"
        f"- owned_paths: {', '.join(args.owned_path or []) or '(not yet constrained)'}\n\n"
        "## Acceptance criteria\n\n- [ ] Define before implementation.\n\n"
        "## Plan\n\n- [ ] Define bounded implementation slices.\n",
        encoding="utf-8",
    )
    print(f"task_id={task_id}\nstate=PLAN\npath={task_dir(repo, task_id)}")
    return 0


def transition(task: dict[str, Any], target: str) -> None:
    current = task["state"]
    if target not in ALLOWED.get(current, set()):
        raise WorkflowError(f"Invalid transition: {current} -> {target}")
    task["state"] = target


def cmd_transition(args: argparse.Namespace) -> int:
    repo = repo_root()
    task = load_task(repo, args.task_id)
    transition(task, args.to)
    save_task(repo, task, "TRANSITION", {"to": args.to, "note": args.note})
    print(f"task_id={args.task_id}\nstate={task['state']}")
    return 0


def run_check(
    repo: Path,
    config: dict[str, Any],
    check: dict[str, Any],
    default_timeout: int,
) -> dict[str, Any]:
    run_dir = repo / str(check.get("dir") or "")
    if not run_dir.exists():
        return {
            "name": check.get("name", "unnamed"),
            "status": "FAIL",
            "returncode": 2,
            "duration_seconds": 0,
            "output": f"Working directory does not exist: {run_dir}",
        }
    command = executable(str(check["cmd"]), repo, config)
    engine_dir = Path(__file__).resolve().parent
    arguments = [str(value).replace("{engine}", str(engine_dir)) for value in check.get("args", [])]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    started = time.monotonic()
    try:
        result = run(
            [command, *arguments],
            run_dir,
            check=False,
            env=env,
            timeout=int(check.get("timeout_seconds", default_timeout)),
        )
        output = result.stdout[-6000:]
        return {
            "name": check.get("name", command),
            "command": [command, *arguments],
            "dir": str(run_dir),
            "status": "PASS" if result.returncode == 0 else "FAIL",
            "returncode": result.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": output,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": check.get("name", command),
            "command": [command, *arguments],
            "dir": str(run_dir),
            "status": "FAIL",
            "returncode": 124,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": f"Timed out: {exc}",
        }


def contract_results(repo: Path, config: dict[str, Any], changed: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    contract = config.get("contract_touchpoints") or {}
    markers = [str(value).replace("\\", "/") for value in contract.get("surface_markers", [])]
    touched = [path for path in changed if any(marker in path for marker in markers)]
    if touched:
        for rule in contract.get("structural_checks", []):
            path = repo / str(rule["file"])
            try:
                content = path.read_text(encoding="utf-8-sig")
                missing = [marker for marker in rule.get("must_contain", []) if marker not in content]
            except (OSError, UnicodeError):
                missing = list(rule.get("must_contain", [])) or ["<readable file>"]
            results.append(
                {
                    "name": f"contract:{rule['file']}",
                    "status": "PASS" if not missing else "FAIL",
                    "returncode": 0 if not missing else 1,
                    "duration_seconds": 0,
                    "output": "OK" if not missing else f"{rule.get('error', 'contract marker missing')}; missing={missing}",
                }
            )
    for rule in (config.get("env_consistency") or {}).get("rules", []):
        path = repo / str(rule["file"])
        try:
            content = path.read_text(encoding="utf-8-sig")
            marker = str(rule["must_contain"])
            missing = marker not in content
        except (OSError, UnicodeError):
            missing = True
        results.append(
            {
                "name": f"env:{rule['file']}",
                "status": "FAIL" if missing else "PASS",
                "returncode": 1 if missing else 0,
                "duration_seconds": 0,
                "output": rule.get("error", "environment marker missing") if missing else "OK",
            }
        )
    return results


def write_evidence(repo: Path, task: dict[str, Any], evidence: dict[str, Any]) -> Path:
    evidence_dir = task_dir(repo, task["task_id"]) / "verification"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_id = evidence["verification_id"]
    json_path = evidence_dir / f"{evidence_id}.json"
    md_path = evidence_dir / f"{evidence_id}.md"
    atomic_json(json_path, evidence)
    lines = [
        "# Verification Evidence",
        "",
        f"- result: **{evidence['result']}**",
        f"- head_sha: `{evidence['head_sha']}`",
        f"- dirty_fingerprint: `{evidence['dirty_fingerprint']}`",
        f"- config_sha256: `{evidence['config_sha256']}`",
        f"- changed_files: {len(evidence['changed_files'])}",
        f"- scope_violations: {len(evidence['scope_violations'])}",
        "",
        "## Checks",
        "",
    ]
    for item in evidence["checks"]:
        lines.append(
            f"- {item['status']}: `{item['name']}` ({item['returncode']}, {item['duration_seconds']}s)"
        )
    if evidence["scope_violations"]:
        lines.extend(["", "## Scope violations", ""])
        lines.extend(f"- `{path}`" for path in evidence["scope_violations"])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def cmd_verify(args: argparse.Namespace) -> int:
    repo = repo_root()
    config_path, config = load_config(repo)
    task = load_task(repo, args.task_id)
    if task["state"] not in {"EXECUTE", "FIX", "INTEGRATE", "VERIFY", "REVIEW"}:
        raise WorkflowError(f"Cannot verify task in state {task['state']}")
    task["state"] = "VERIFY"
    task["budget"]["verification_attempts"] += 1
    changed, unchanged_baseline = changed_files(repo, task)
    owned = task.get("scope", {}).get("owned_paths", [])
    scope_violations = [path for path in changed if owned and not path_owned(path, owned)]
    workflow_class = task["workflow_class"]
    groups = config.get("workflow_classes", {}).get(workflow_class)
    if groups is None:
        raise WorkflowError(f"Workflow class no longer exists: {workflow_class}")
    settings = config.get("codex_workflow", {})
    timeout = int(settings.get("check_timeout_seconds", 900))
    checks: list[dict[str, Any]] = []
    for group in groups:
        for check in config.get("checks", {}).get(group, []):
            checks.append(run_check(repo, config, check, timeout))
    checks.extend(contract_results(repo, config, changed))
    engine_prefix = f"workflow/tasks/{task['task_id']}"
    workspace = workspace_info(repo, [engine_prefix])
    passed = not scope_violations and all(item["status"] == "PASS" for item in checks)
    verification_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    evidence = {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "verification_id": verification_id,
        "task_id": task["task_id"],
        "run_at": now(),
        "result": "PASS" if passed else "FAIL",
        "head_sha": workspace["head_sha"],
        "dirty_fingerprint": workspace["dirty_fingerprint"],
        "config_sha256": sha256_bytes(config_path.read_bytes()),
        "changed_files": changed,
        "unchanged_preexisting_dirty": unchanged_baseline,
        "scope_violations": scope_violations,
        "checks": checks,
    }
    evidence_path = write_evidence(repo, task, evidence)
    task["verification"]["latest"] = {
        "result": evidence["result"],
        "verification_id": verification_id,
        "head_sha": evidence["head_sha"],
        "dirty_fingerprint": evidence["dirty_fingerprint"],
        "config_sha256": evidence["config_sha256"],
        "evidence": str(evidence_path.relative_to(repo)).replace("\\", "/"),
    }
    task["state"] = "REVIEW" if passed else "FIX"
    save_task(repo, task, "VERIFIED", {"result": evidence["result"], "evidence": str(evidence_path)})
    print(f"task_id={task['task_id']}\nresult={evidence['result']}\nstate={task['state']}\nevidence={evidence_path}")
    return 0 if passed else 1


def evidence_fresh(repo: Path, task: dict[str, Any], config_path: Path) -> tuple[bool, str]:
    latest = task.get("verification", {}).get("latest")
    if not latest or latest.get("result") != "PASS":
        return False, "No passing verification evidence"
    engine_prefix = f"workflow/tasks/{task['task_id']}"
    workspace = workspace_info(repo, [engine_prefix])
    if latest.get("head_sha") != workspace["head_sha"]:
        return False, "HEAD changed after verification"
    if latest.get("dirty_fingerprint") != workspace["dirty_fingerprint"]:
        return False, "Working tree changed after verification"
    if latest.get("config_sha256") != sha256_bytes(config_path.read_bytes()):
        return False, "Workflow config changed after verification"
    return True, "fresh"


def cmd_review(args: argparse.Namespace) -> int:
    repo = repo_root()
    config_path, _ = load_config(repo)
    task = load_task(repo, args.task_id)
    if task["state"] not in {"REVIEW", "VERIFY"}:
        raise WorkflowError(f"Cannot review task in state {task['state']}")
    if args.verdict == "pass":
        fresh, reason = evidence_fresh(repo, task, config_path)
        if not fresh:
            raise WorkflowError(f"Cannot pass review: {reason}")
        task["state"] = "INTEGRATE"
    elif args.verdict == "fix":
        loops = int(task["budget"].get("fix_loops", 0)) + 1
        maximum = int(task["budget"].get("max_fix_loops", 2))
        if loops > maximum:
            task["state"] = "BLOCKED"
            save_task(repo, task, "FIX_LOOP_EXHAUSTED", {"finding": args.finding})
            raise WorkflowError(f"Fix-loop limit reached ({maximum}); task moved to BLOCKED")
        task["budget"]["fix_loops"] = loops
        task["state"] = "FIX"
    else:
        task["state"] = "BLOCKED"
    save_task(repo, task, "REVIEW", {"verdict": args.verdict, "finding": args.finding})
    print(f"task_id={task['task_id']}\nverdict={args.verdict}\nstate={task['state']}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    repo = repo_root()
    task = load_task(repo, args.task_id)
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    repo = repo_root()
    config_path, _ = load_config(repo)
    task = load_task(repo, args.task_id)
    if task["state"] != "INTEGRATE":
        raise WorkflowError(f"Close requires INTEGRATE state, found {task['state']}")
    fresh, reason = evidence_fresh(repo, task, config_path)
    if not fresh:
        raise WorkflowError(f"Cannot close: {reason}")
    changed, _ = changed_files(repo, task)
    task["state"] = "CLOSED"
    latest = task["verification"]["latest"]
    summary = task_dir(repo, task["task_id"]) / "summary.md"
    summary.write_text(
        f"# Task Summary\n\n"
        f"- task_id: `{task['task_id']}`\n"
        f"- title: {task['title']}\n"
        f"- result: CLOSED\n"
        f"- verification: `{latest['evidence']}`\n"
        f"- fix_loops: {task['budget']['fix_loops']}\n\n"
        "## Changed files\n\n"
        + ("\n".join(f"- `{path}`" for path in changed) if changed else "- None")
        + "\n\n## Lessons\n\n- Record only reusable, deduplicated lessons when applicable.\n",
        encoding="utf-8",
    )
    save_task(repo, task, "CLOSED", {"summary": str(summary)})
    print(f"task_id={task['task_id']}\nstate=CLOSED\nsummary={summary}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="codex-workflow")
    root.add_argument("--version", action="version", version=ENGINE_VERSION)
    commands = root.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument("--project-name")
    init.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the detected configuration without writing workflow/config.json.",
    )
    init.set_defaults(func=cmd_init)

    doctor = commands.add_parser("doctor")
    doctor.set_defaults(func=cmd_doctor)

    start = commands.add_parser("start")
    start.add_argument("--title", required=True)
    start.add_argument("--tier", choices=["micro", "small", "medium", "contract"], required=True)
    start.add_argument("--workflow-class")
    start.add_argument("--owned-path", action="append", default=[])
    start.add_argument("--task-id")
    start.add_argument("--max-fix-loops", type=int)
    start.set_defaults(func=cmd_start)

    state = commands.add_parser("transition")
    state.add_argument("task_id")
    state.add_argument("--to", choices=sorted(ACTIVE_STATES), required=True)
    state.add_argument("--note")
    state.set_defaults(func=cmd_transition)

    verify = commands.add_parser("verify")
    verify.add_argument("task_id")
    verify.set_defaults(func=cmd_verify)

    review = commands.add_parser("review")
    review.add_argument("task_id")
    review.add_argument("--verdict", choices=["pass", "fix", "blocked"], required=True)
    review.add_argument("--finding")
    review.set_defaults(func=cmd_review)

    status = commands.add_parser("status")
    status.add_argument("task_id")
    status.set_defaults(func=cmd_status)

    close = commands.add_parser("close")
    close.add_argument("task_id")
    close.set_defaults(func=cmd_close)
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        return int(args.func(args))
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("ERROR: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
