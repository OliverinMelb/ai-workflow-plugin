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
from urllib.parse import urlsplit

ENGINE_VERSION = "1.2.0"
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
    path = safe_repo_target(repo, "workflow/config.json")
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
    path = safe_repo_target(repo, "workflow/config.json")
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


MANAGED_AGENT_START = "<!-- codex-workflow:project-conventions:start -->"
MANAGED_AGENT_END = "<!-- codex-workflow:project-conventions:end -->"


def text_sha256(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def safe_repo_target(repo: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise WorkflowError("Project convention paths must be repository-relative")
    resolved = (repo / candidate).resolve()
    try:
        resolved.relative_to(repo.resolve())
    except ValueError as exc:
        raise WorkflowError(
            f"Project convention path escapes the repository: {relative}"
        ) from exc
    return resolved


def selected_agent_file(repo: Path, requested: str | None) -> Path:
    if requested:
        if requested not in {"AGENTS.md", "CLAUDE.md"}:
            raise WorkflowError("--agent-file must be AGENTS.md or CLAUDE.md")
        return safe_repo_target(repo, requested)
    if (repo / "CLAUDE.md").is_file():
        return safe_repo_target(repo, "CLAUDE.md")
    if (repo / "AGENTS.md").is_file():
        return safe_repo_target(repo, "AGENTS.md")
    raise WorkflowError(
        "No AGENTS.md or CLAUDE.md exists; choose one with --agent-file"
    )


def tracker_remote(repo: Path, tracker: str, requested: str | None) -> str | None:
    if tracker == "local":
        return None
    if tracker == "other":
        remote = requested
    else:
        remote = requested or git(repo, "remote", "get-url", "origin", check=False)
    if not remote and tracker != "other":
        raise WorkflowError(
            f"{tracker} tracker requires --tracker-url or an origin remote"
        )
    if not remote:
        return None
    parsed = urlsplit(remote)
    http_userinfo = parsed.scheme.lower() in {"http", "https"} and parsed.username
    if parsed.password or http_userinfo or parsed.query or parsed.fragment:
        raise WorkflowError(
            "Tracker URL contains credentials or query data; use a credential-free base URL"
        )
    return remote


def convention_documents(
    tracker: str,
    remote: str | None,
    publication_policy: str,
    domain_layout: str,
    triage_labels: dict[str, str] | None,
    tracker_instructions: str | None,
) -> dict[str, str]:
    if tracker == "local":
        tracker_location = "Local Markdown under `.scratch/<feature>/issues/`."
        operations = (
            "Use `.scratch/<feature>/spec.md` for a standalone spec and one file per ticket under "
            "`.scratch/<feature>/issues/<ticket-id>.md`. Each ticket records status, acceptance "
            "criteria, `Blocked by`, and dated comment sections. List/frontier operations scan "
            "those files; claim changes status to `in-progress`; resolve records the outcome and "
            "sets status to `closed`. Codex Workflow evidence remains under "
            "`workflow/tasks/<task-id>/`."
        )
    elif tracker == "other":
        tracker_location = f"Custom tracker at `{remote or 'user-defined location'}`."
        operations = tracker_instructions or ""
    elif tracker == "github":
        tracker_location = f"GitHub issues at `{remote}`."
        operations = (
            "Use credential-free `gh` commands after publication is authorized:\n\n"
            "```text\n"
            "read:    gh issue view <number> --json number,title,body,state,labels,assignees,comments\n"
            "list:    gh issue list --state <open|closed|all> --json number,title,state,labels,assignees\n"
            "create:  gh issue create --title <title> --body-file <file> --label <label>\n"
            "update:  gh issue edit <number> --title <title> --body-file <file> [--add-label <label>]\n"
            "comment: gh issue comment <number> --body-file <file>\n"
            "close:   gh issue close <number> --comment <outcome>\n"
            "claim:   gh issue edit <number> --add-assignee @me\n"
            "```\n\n"
            "GitHub issue and PR numbers share a namespace. Before treating a number as an issue, "
            "query `gh api repos/{owner}/{repo}/issues/<number>`; a `pull_request` field means it is "
            "a PR and must be ignored while `prs_as_request_surface=false`. Prefer native "
            "sub-issue/blocking relationships when the repository exposes them; otherwise keep "
            "`Blocked by: #<number>` in every body and update both sides explicitly. Query a "
            "wayfinder frontier with `gh issue list --state open --label wayfinder:decision --json "
            "number,title,body,labels,assignees`, then select only tickets whose `Blocked by` issues "
            "are closed. Claim before work and close with an outcome comment."
        )
    else:
        tracker_location = f"GitLab issues at `{remote}`."
        operations = (
            "Use credential-free `glab` commands after publication is authorized:\n\n"
            "```text\n"
            "read:    glab issue view <iid> --comments\n"
            "list:    glab issue list --state <opened|closed|all>\n"
            "create:  glab issue create --title <title> --description <body> --label <label>\n"
            "update:  glab issue update <iid> --title <title> --description <body>\n"
            "comment: glab issue note <iid> --message <comment>\n"
            "close:   glab issue close <iid>\n"
            "claim:   glab issue update <iid> --assignee @me\n"
            "```\n\n"
            "Issue and merge-request IIDs are distinct resources; confirm with `glab issue view` "
            "and never substitute `glab mr view` results while `prs_as_request_surface=false`. "
            "Use native related/blocking issues where configured; otherwise keep `Blocked by: "
            "#<iid>` in each description. Query the wayfinder frontier with `glab issue list "
            "--state opened --label wayfinder:decision`, inspect blockers, claim before work, add "
            "the decision as a note, and close only after the map is updated."
        )
    issue_tracker = (
        "# Issue tracker\n\n"
        f"- kind: `{tracker}`\n"
        f"- location: {tracker_location}\n"
        f"- publication_policy: `{publication_policy}`\n"
        "- prs_as_request_surface: `false`\n\n"
        "## Operations\n\n"
        f"{operations}\n\n"
        "The configured adapter must support fetch/read, list/query, create, update, comment, and "
        "close operations. For local Markdown these are filesystem reads and bounded file edits; "
        "for remote trackers they are CLI/API operations.\n\n"
        "Distinguish issues from pull/merge requests; PRs/MRs are not a request surface unless "
        "`prs_as_request_surface` is deliberately changed. A spec is one canonical artifact; "
        "tickets are tracer-bullet vertical slices with explicit status and blocking edges.\n\n"
        "## Wayfinding operations\n\n"
        "Create one map issue and child decision tickets. Query the frontier as open children with "
        "no unresolved blockers. Claim one decision ticket before work, append evidence/comments, "
        "resolve at most one non-research decision per session, then update the map and newly "
        "visible frontier. Never treat the map itself as the implementation spec.\n\n"
        "A Workflow invocation authorizes local planning artifacts only. "
        + (
            "Remote issue creation or modification always requires explicit user authorization.\n"
            if publication_policy == "explicit"
            else "Remote issue creation, modification, and publication are forbidden.\n"
        )
    )
    if domain_layout == "single":
        domain_description = (
            "Use root `CONTEXT.md` as the domain glossary and `docs/adr/` for durable decisions."
        )
    else:
        domain_description = (
            "Use root `CONTEXT-MAP.md` to route to per-context `CONTEXT.md` files; keep ADRs near "
            "their owning context."
        )
    domain = (
        "# Domain documentation\n\n"
        f"- layout: `{domain_layout}`\n\n"
        f"{domain_description}\n\n"
        "If a referenced domain document does not exist, continue without inventing its contents. "
        "Read the relevant glossary and ADRs before naming interfaces, tests, specs, or tickets. "
        "Use one term per concept and challenge overloaded vocabulary before it reaches an "
        "interface. Existing ADRs outrank a new proposal until an explicit superseding decision is "
        "recorded. Update domain docs only when their paths are explicitly owned by the task.\n"
    )
    documents = {
        "docs/agents/issue-tracker.md": issue_tracker,
        "docs/agents/domain.md": domain,
    }
    if triage_labels is not None:
        documents["docs/agents/triage-labels.md"] = (
            "# Triage labels\n\n"
            + "".join(
                f"- {role}: `{triage_labels[role]}`\n"
                for role in (
                    "needs-triage",
                    "needs-info",
                    "ready-for-agent",
                    "ready-for-human",
                    "wontfix",
                )
            )
        )
    return documents


def parsed_triage_labels(values: list[str], enabled: bool) -> dict[str, str] | None:
    if not enabled:
        if values:
            raise WorkflowError("--triage-label requires --with-triage")
        return None
    roles = {
        "needs-triage",
        "needs-info",
        "ready-for-agent",
        "ready-for-human",
        "wontfix",
    }
    labels = {role: role for role in roles}
    for value in values:
        if "=" not in value:
            raise WorkflowError("--triage-label must use role=value")
        role, label = (part.strip() for part in value.split("=", 1))
        if role not in roles or not label:
            raise WorkflowError(f"Invalid triage label override: {value}")
        labels[role] = label
    return labels


def agent_conventions_block(
    tracker: str,
    domain_layout: str,
    with_triage: bool,
    publication_policy: str,
) -> str:
    tracker_summary = (
        "Local Markdown issues are stored under `.scratch/<feature>/issues/`."
        if tracker == "local"
        else f"Use the configured {tracker.title()} tracker."
    )
    lines = [
        MANAGED_AGENT_START,
        "## Agent skills",
        "",
        "### Issue tracker",
        "",
        f"{tracker_summary} Publication policy is `{publication_policy}`. "
        "See `docs/agents/issue-tracker.md`.",
    ]
    if with_triage:
        lines.extend(
            [
                "",
                "### Triage labels",
                "",
                "Use the canonical project label mapping. See `docs/agents/triage-labels.md`.",
            ]
        )
    lines.extend(
        [
            "",
            "### Domain docs",
            "",
            f"Use the `{domain_layout}` domain layout. See `docs/agents/domain.md`.",
            MANAGED_AGENT_END,
        ]
    )
    return "\n".join(lines) + "\n"


def with_managed_agent_block(path: Path, block: str) -> str:
    current = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    if MANAGED_AGENT_START in current or MANAGED_AGENT_END in current:
        if current.count(MANAGED_AGENT_START) != 1 or current.count(MANAGED_AGENT_END) != 1:
            raise WorkflowError(f"Malformed managed project-conventions block in {path}")
        start = current.index(MANAGED_AGENT_START)
        end_start = current.index(MANAGED_AGENT_END)
        if end_start <= start:
            raise WorkflowError(f"Reversed managed project-conventions markers in {path}")
        end = end_start + len(MANAGED_AGENT_END)
        return current[:start] + block.rstrip() + current[end:]
    if re.search(r"(?m)^## Agent skills\s*$", current):
        raise WorkflowError(
            f"{path.name} has an unmanaged '## Agent skills' section; merge it manually"
        )
    separator = "\n\n" if current.strip() else ""
    return current.rstrip() + separator + block


def cmd_setup(args: argparse.Namespace) -> int:
    repo = repo_root()
    config_path = safe_repo_target(repo, "workflow/config.json")
    _, config = load_config(repo)
    if args.publication_policy == "forbidden" and args.tracker != "local":
        raise WorkflowError("Forbidden publication policy requires the local tracker")
    if args.profile == "private" and (
        args.tracker != "local" or args.publication_policy != "forbidden"
    ):
        raise WorkflowError("Private profile requires local tracker with forbidden publication")
    if args.tracker == "other" and not (args.tracker_instructions or "").strip():
        raise WorkflowError("Other tracker requires --tracker-instructions")
    agent_path = selected_agent_file(repo, args.agent_file)
    remote = tracker_remote(repo, args.tracker, args.tracker_url)
    triage_labels = parsed_triage_labels(args.triage_label, args.with_triage)
    documents = convention_documents(
        args.tracker,
        remote,
        args.publication_policy,
        args.domain_layout,
        triage_labels,
        args.tracker_instructions,
    )
    block = agent_conventions_block(
        args.tracker,
        args.domain_layout,
        args.with_triage,
        args.publication_policy,
    )
    agent_content = with_managed_agent_block(agent_path, block)
    conventions = {
        "schema_version": 1,
        "profile": args.profile,
        "tracker": {
            "kind": args.tracker,
            "remote": remote,
            "doc": "docs/agents/issue-tracker.md",
            "publication_policy": args.publication_policy,
        },
        "domain": {
            "layout": args.domain_layout,
            "doc": "docs/agents/domain.md",
        },
        "triage": {
            "enabled": args.with_triage,
            "doc": "docs/agents/triage-labels.md" if args.with_triage else None,
            "labels": triage_labels,
        },
        "agent_file": agent_path.name,
        "integrity": {
            "documents": {
                relative: text_sha256(content)
                for relative, content in documents.items()
            },
            "agent_block_sha256": text_sha256(block.rstrip()),
        },
    }
    preview = {
        "project_conventions": conventions,
        "files": {
            **documents,
            agent_path.name: agent_content,
        },
    }
    if args.dry_run:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0
    for relative, content in documents.items():
        path = safe_repo_target(repo, relative)
        if path.exists() and path.read_text(encoding="utf-8-sig") != content:
            raise WorkflowError(f"Refusing to overwrite existing project convention: {path}")
    for relative, content in documents.items():
        path = safe_repo_target(repo, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    agent_path.write_text(agent_content, encoding="utf-8")
    config["project_conventions"] = conventions
    pointers = [
        *config.setdefault("memory", {}).get("pointers", []),
        f"Agent rules: {agent_path.name}",
        "Issue tracker: docs/agents/issue-tracker.md",
        "Domain docs: docs/agents/domain.md",
    ]
    if args.with_triage:
        pointers.append("Triage labels: docs/agents/triage-labels.md")
    config["memory"]["pointers"] = normalized_strings(pointers)
    atomic_json(config_path, config)
    print(f"configured={config_path}")
    print(f"tracker={args.tracker}")
    print(f"publication_policy={args.publication_policy}")
    print(f"agent_file={agent_path.name}")
    return 0


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


def normalized_strings(values: list[str] | None) -> list[str]:
    return sorted({value.strip() for value in (values or []) if value.strip()})


def planning_state() -> dict[str, Any]:
    return {
        "status": "discovering",
        "unresolved_decisions": [],
        "decisions": [],
        "acceptance_criteria": [],
        "spec_ref": None,
        "multi_session": False,
        "tickets": [],
    }


def repository_ref(repo: Path, value: str) -> tuple[str, Path]:
    candidate = Path(value)
    if candidate.is_absolute():
        raise WorkflowError("Planning artifact references must be repository-relative")
    resolved = (repo / candidate).resolve()
    try:
        relative = resolved.relative_to(repo.resolve()).as_posix()
    except ValueError as exc:
        raise WorkflowError("Planning artifact reference escapes the repository") from exc
    if not resolved.is_file():
        raise WorkflowError(f"Planning artifact does not exist: {relative}")
    return relative, resolved


def ticket_cycles(tickets: list[dict[str, Any]]) -> bool:
    graph = {ticket["id"]: ticket.get("blocked_by", []) for ticket in tickets}
    active: set[str] = set()
    complete: set[str] = set()

    def visit(ticket_id: str) -> bool:
        if ticket_id in active:
            return True
        if ticket_id in complete:
            return False
        active.add(ticket_id)
        if any(dependency in graph and visit(dependency) for dependency in graph.get(ticket_id, [])):
            return True
        active.remove(ticket_id)
        complete.add(ticket_id)
        return False

    return any(visit(ticket_id) for ticket_id in graph)


def validate_plan(repo: Path, task: dict[str, Any]) -> None:
    planning = task.get("planning")
    if planning is None:
        if int(task.get("schema_version", 1)) <= 1:
            return
        raise WorkflowError("PLAN -> EXECUTE blocked: schema v2 task is missing planning state")
    failures: list[str] = []
    if planning.get("status") != "ready":
        failures.append("planning status is not ready")
    if planning.get("unresolved_decisions"):
        failures.append("unresolved decisions remain")
    if not planning.get("acceptance_criteria"):
        failures.append("acceptance criteria are empty")
    if task.get("tier") in {"medium", "contract"} and not planning.get("spec_ref"):
        failures.append(f"{task.get('tier')} tasks require a local spec")
    spec_ref = planning.get("spec_ref")
    if spec_ref:
        repository_ref(repo, spec_ref)
    tickets = planning.get("tickets", [])
    if planning.get("multi_session"):
        if not spec_ref:
            failures.append("multi-session tasks require a local spec")
        if not tickets:
            failures.append("multi-session tasks require tracer-bullet tickets")
    ticket_ids = {ticket["id"] for ticket in tickets}
    for ticket in tickets:
        unknown = sorted(set(ticket.get("blocked_by", [])) - ticket_ids)
        if unknown:
            failures.append(f"ticket {ticket['id']} has unknown dependencies: {', '.join(unknown)}")
        if ticket["id"] in ticket.get("blocked_by", []):
            failures.append(f"ticket {ticket['id']} blocks itself")
        if not ticket.get("acceptance_criteria"):
            failures.append(f"ticket {ticket['id']} has no acceptance criteria")
    if ticket_cycles(tickets):
        failures.append("ticket dependency graph contains a cycle")
    if failures:
        raise WorkflowError("PLAN -> EXECUTE blocked: " + "; ".join(failures))


def planning_fingerprint(repo: Path, task: dict[str, Any]) -> str:
    planning = task.get("planning")
    if planning is None:
        if int(task.get("schema_version", 1)) <= 1:
            return sha256_bytes(b"legacy-schema-v1")
        raise WorkflowError("Schema v2 task is missing planning state")
    payload = {
        "planning": planning,
        "spec_sha256": None,
    }
    if planning.get("spec_ref"):
        _, spec_path = repository_ref(repo, planning["spec_ref"])
        payload["spec_sha256"] = sha256_bytes(spec_path.read_bytes())
    return sha256_bytes(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )


def write_planning_artifact(repo: Path, task: dict[str, Any]) -> None:
    planning = task["planning"]
    lines = [
        "# Planning Record",
        "",
        f"- status: `{planning['status']}`",
        f"- multi_session: `{str(planning['multi_session']).lower()}`",
        f"- spec_ref: `{planning['spec_ref'] or 'none'}`",
        "",
        "## Unresolved decisions",
        "",
        *([f"- {value}" for value in planning["unresolved_decisions"]] or ["- None"]),
        "",
        "## Decisions",
        "",
        *([f"- {value}" for value in planning["decisions"]] or ["- None"]),
        "",
        "## Acceptance criteria",
        "",
        *([f"- [ ] {value}" for value in planning["acceptance_criteria"]] or ["- [ ] Not defined"]),
        "",
        "## Tracer-bullet tickets",
        "",
    ]
    if planning["tickets"]:
        for ticket in planning["tickets"]:
            blocked_by = ", ".join(ticket["blocked_by"]) or "none"
            lines.extend(
                [
                    f"### {ticket['id']}: {ticket['title']}",
                    "",
                    f"- blocked_by: {blocked_by}",
                    *[f"- [ ] {value}" for value in ticket["acceptance_criteria"]],
                    "",
                ]
            )
    else:
        lines.append("- None")
    (task_dir(repo, task["task_id"]) / "planning.md").write_text(
        "\n".join(lines).rstrip() + "\n",
        encoding="utf-8",
    )


def validate_project_conventions(repo: Path, config: dict[str, Any]) -> None:
    conventions = config.get("project_conventions")
    if not isinstance(conventions, dict):
        raise WorkflowError(
            "Missing project_conventions; run workflow setup before starting non-micro work"
        )
    if conventions.get("schema_version") != 1:
        raise WorkflowError("Invalid project_conventions schema_version")
    profile = conventions.get("profile")
    if profile not in {"standard", "private"}:
        raise WorkflowError("Invalid project_conventions profile")
    tracker = conventions.get("tracker")
    if not isinstance(tracker, dict):
        raise WorkflowError("Invalid project_conventions tracker")
    kind = tracker.get("kind")
    policy = tracker.get("publication_policy")
    if kind not in {"local", "github", "gitlab", "other"}:
        raise WorkflowError("Invalid project_conventions tracker kind")
    if policy not in {"explicit", "forbidden"}:
        raise WorkflowError("Invalid project_conventions publication policy")
    if policy == "forbidden" and kind != "local":
        raise WorkflowError(
            "Invalid project_conventions: forbidden publication requires the local tracker"
        )
    if kind == "local" and tracker.get("remote") is not None:
        raise WorkflowError("Invalid project_conventions: local tracker cannot have a remote")
    if kind != "local" and not tracker.get("remote"):
        if kind != "other":
            raise WorkflowError("Invalid project_conventions: remote tracker URL is missing")
    if profile == "private" and (kind != "local" or policy != "forbidden"):
        raise WorkflowError(
            "Invalid project_conventions: private profile requires local forbidden policy"
        )
    references = [tracker.get("doc")]
    domain = conventions.get("domain")
    if not isinstance(domain, dict) or domain.get("layout") not in {"single", "multi"}:
        raise WorkflowError("Invalid project_conventions domain layout")
    references.append(domain.get("doc"))
    triage = conventions.get("triage")
    if not isinstance(triage, dict) or not isinstance(triage.get("enabled"), bool):
        raise WorkflowError("Invalid project_conventions triage settings")
    if triage["enabled"]:
        references.append(triage.get("doc"))
    agent_file = conventions.get("agent_file")
    if agent_file not in {"AGENTS.md", "CLAUDE.md"}:
        raise WorkflowError("Invalid project_conventions agent_file")
    references.append(agent_file)
    integrity = conventions.get("integrity")
    if not isinstance(integrity, dict) or not isinstance(integrity.get("documents"), dict):
        raise WorkflowError("Invalid project_conventions integrity metadata")
    for reference in references:
        if not isinstance(reference, str) or not reference.strip():
            raise WorkflowError("Invalid project_conventions document reference")
        repository_ref(repo, reference)
    for reference in references[:-1]:
        expected = integrity["documents"].get(reference)
        if not isinstance(expected, str):
            raise WorkflowError(f"Missing integrity hash for {reference}")
        _, path = repository_ref(repo, reference)
        if text_sha256(path.read_text(encoding="utf-8-sig")) != expected:
            raise WorkflowError(f"Project convention changed; rerun setup: {reference}")
    _, agent_path = repository_ref(repo, agent_file)
    agent_content = agent_path.read_text(encoding="utf-8-sig")
    if (
        agent_content.count(MANAGED_AGENT_START) != 1
        or agent_content.count(MANAGED_AGENT_END) != 1
    ):
        raise WorkflowError("Managed project-conventions block is missing or malformed")
    start = agent_content.index(MANAGED_AGENT_START)
    end_start = agent_content.index(MANAGED_AGENT_END)
    if end_start <= start:
        raise WorkflowError("Managed project-conventions markers are reversed")
    block = agent_content[start : end_start + len(MANAGED_AGENT_END)]
    if text_sha256(block) != integrity.get("agent_block_sha256"):
        raise WorkflowError("Managed project-conventions block changed; rerun setup")


def cognitive_routing(args: argparse.Namespace) -> dict[str, list[str]]:
    return {
        "skills": normalized_strings(getattr(args, "skill", None)),
        "source_refs": normalized_strings(getattr(args, "source_ref", None)),
        "notes": normalized_strings(getattr(args, "routing_note", None)),
    }


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
    validate_project_conventions(repo, config)
    if "rh-company-workflow" in normalized_strings(args.skill):
        conventions = config["project_conventions"]
        tracker = conventions["tracker"]
        if (
            conventions.get("profile") != "private"
            or tracker.get("kind") != "local"
            or tracker.get("publication_policy") != "forbidden"
        ):
            raise WorkflowError(
                "RH tasks require private project conventions with local forbidden publication"
            )
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
    tier_agent_limit = {"small": 1, "medium": 2, "contract": 2}[args.tier]
    configured_agent_limit = max(0, int(settings.get("max_subagents", tier_agent_limit)))
    max_agents = min(tier_agent_limit, configured_agent_limit)
    routing = cognitive_routing(args)
    task = {
        "schema_version": 2,
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
        "cognitive_routing": routing,
        "planning": planning_state(),
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
        "## Cognitive routing\n\n"
        f"- skills: {', '.join(routing['skills']) or 'direct'}\n"
        f"- source_refs: {', '.join(routing['source_refs']) or 'none'}\n"
        f"- notes: {'; '.join(routing['notes']) or 'none'}\n\n"
        "## Acceptance criteria\n\n- [ ] Define before implementation.\n\n"
        "## Plan\n\n- [ ] Define bounded implementation slices.\n",
        encoding="utf-8",
    )
    write_planning_artifact(repo, task)
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
    if args.to == "EXECUTE":
        validate_plan(repo, task)
    transition(task, args.to)
    save_task(repo, task, "TRANSITION", {"to": args.to, "note": args.note})
    print(f"task_id={args.task_id}\nstate={task['state']}")
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    repo = repo_root()
    task = load_task(repo, args.task_id)
    if task["state"] not in {"PLAN", "BLOCKED"}:
        raise WorkflowError(
            f"Cognitive routing is only allowed in PLAN or BLOCKED, found {task['state']}"
        )
    additions = cognitive_routing(args)
    if not any(additions.values()):
        raise WorkflowError("Provide at least one --skill, --source-ref, or --routing-note")
    current = task.setdefault(
        "cognitive_routing",
        {"skills": [], "source_refs": [], "notes": []},
    )
    for key, values in additions.items():
        current[key] = normalized_strings([*current.get(key, []), *values])
    save_task(repo, task, "COGNITIVE_ROUTE", additions)
    print(
        f"task_id={task['task_id']}\n"
        f"state={task['state']}\n"
        f"skills={','.join(current['skills']) or 'direct'}"
    )
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    repo = repo_root()
    task = load_task(repo, args.task_id)
    if task["state"] not in {"PLAN", "BLOCKED"}:
        raise WorkflowError(f"Planning updates are only allowed in PLAN or BLOCKED, found {task['state']}")
    planning = task.setdefault("planning", planning_state())
    before = json.loads(json.dumps(planning))
    opened = normalized_strings(args.open_decision)
    resolved = normalized_strings(args.resolve_decision)
    decisions = normalized_strings(args.decision)
    acceptance = normalized_strings(args.acceptance)
    if resolved and len(decisions) < len(resolved):
        raise WorkflowError("Each --resolve-decision requires a corresponding --decision")
    if args.status:
        planning["status"] = args.status
    planning["unresolved_decisions"] = normalized_strings(
        [*planning.get("unresolved_decisions", []), *opened]
    )
    for value in resolved:
        if value not in planning["unresolved_decisions"]:
            raise WorkflowError(f"Unresolved decision not found: {value}")
        planning["unresolved_decisions"].remove(value)
    planning["decisions"] = normalized_strings([*planning.get("decisions", []), *decisions])
    planning["acceptance_criteria"] = normalized_strings(
        [*planning.get("acceptance_criteria", []), *acceptance]
    )
    if args.spec_ref:
        planning["spec_ref"], _ = repository_ref(repo, args.spec_ref)
    if args.multi_session:
        planning["multi_session"] = True
    if planning == before:
        raise WorkflowError("Provide at least one planning update")
    save_task(
        repo,
        task,
        "PLAN_UPDATED",
        {
            "status": args.status,
            "opened": opened,
            "resolved": resolved,
            "decisions": decisions,
            "acceptance": acceptance,
            "spec_ref": planning["spec_ref"],
            "multi_session": planning["multi_session"],
        },
    )
    write_planning_artifact(repo, task)
    print(
        f"task_id={task['task_id']}\nstatus={planning['status']}\n"
        f"unresolved={len(planning['unresolved_decisions'])}\n"
        f"acceptance={len(planning['acceptance_criteria'])}"
    )
    return 0


def cmd_ticket(args: argparse.Namespace) -> int:
    repo = repo_root()
    task = load_task(repo, args.task_id)
    if task["state"] not in {"PLAN", "BLOCKED"}:
        raise WorkflowError(f"Ticket updates are only allowed in PLAN or BLOCKED, found {task['state']}")
    planning = task.setdefault("planning", planning_state())
    tickets = planning.setdefault("tickets", [])
    ticket = next((item for item in tickets if item["id"] == args.ticket_id), None)
    if ticket is None:
        ticket = {
            "id": args.ticket_id,
            "title": args.title,
            "blocked_by": [],
            "acceptance_criteria": [],
        }
        tickets.append(ticket)
    elif ticket["title"] != args.title:
        raise WorkflowError(f"Ticket {args.ticket_id} already exists with a different title")
    ticket["blocked_by"] = normalized_strings([*ticket["blocked_by"], *args.blocked_by])
    ticket["acceptance_criteria"] = normalized_strings(
        [*ticket["acceptance_criteria"], *args.acceptance]
    )
    tickets.sort(key=lambda item: item["id"])
    save_task(repo, task, "TICKET_UPSERTED", ticket)
    write_planning_artifact(repo, task)
    print(
        f"task_id={task['task_id']}\nticket={ticket['id']}\n"
        f"blocked_by={','.join(ticket['blocked_by']) or 'none'}"
    )
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
        f"- planning_sha256: `{evidence['planning_sha256']}`",
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
        "schema_version": 2,
        "engine_version": ENGINE_VERSION,
        "verification_id": verification_id,
        "task_id": task["task_id"],
        "run_at": now(),
        "result": "PASS" if passed else "FAIL",
        "head_sha": workspace["head_sha"],
        "dirty_fingerprint": workspace["dirty_fingerprint"],
        "config_sha256": sha256_bytes(config_path.read_bytes()),
        "planning_sha256": planning_fingerprint(repo, task),
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
        "planning_sha256": evidence["planning_sha256"],
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
    try:
        current_planning = planning_fingerprint(repo, task)
    except WorkflowError as exc:
        return False, str(exc)
    if latest.get("planning_sha256") != current_planning:
        return False, "Planning state or local spec changed after verification"
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

    setup = commands.add_parser("setup")
    setup.add_argument("--profile", choices=["standard", "private"], default="standard")
    setup.add_argument("--tracker", choices=["local", "github", "gitlab", "other"], default="local")
    setup.add_argument("--tracker-url")
    setup.add_argument("--tracker-instructions")
    setup.add_argument("--publication-policy", choices=["explicit", "forbidden"], default="explicit")
    setup.add_argument("--domain-layout", choices=["single", "multi"], default="single")
    setup.add_argument("--with-triage", action="store_true")
    setup.add_argument("--triage-label", action="append", default=[])
    setup.add_argument("--agent-file", choices=["AGENTS.md", "CLAUDE.md"])
    setup.add_argument("--dry-run", action="store_true")
    setup.set_defaults(func=cmd_setup)

    doctor = commands.add_parser("doctor")
    doctor.set_defaults(func=cmd_doctor)

    start = commands.add_parser("start")
    start.add_argument("--title", required=True)
    start.add_argument("--tier", choices=["micro", "small", "medium", "contract"], required=True)
    start.add_argument("--workflow-class")
    start.add_argument("--owned-path", action="append", default=[])
    start.add_argument("--task-id")
    start.add_argument("--max-fix-loops", type=int)
    start.add_argument("--skill", action="append", default=[])
    start.add_argument("--source-ref", action="append", default=[])
    start.add_argument("--routing-note", action="append", default=[])
    start.set_defaults(func=cmd_start)

    route = commands.add_parser("route")
    route.add_argument("task_id")
    route.add_argument("--skill", action="append", default=[])
    route.add_argument("--source-ref", action="append", default=[])
    route.add_argument("--routing-note", action="append", default=[])
    route.set_defaults(func=cmd_route)

    plan = commands.add_parser("plan")
    plan.add_argument("task_id")
    plan.add_argument("--status", choices=["discovering", "ready"])
    plan.add_argument("--open-decision", action="append", default=[])
    plan.add_argument("--resolve-decision", action="append", default=[])
    plan.add_argument("--decision", action="append", default=[])
    plan.add_argument("--acceptance", action="append", default=[])
    plan.add_argument("--spec-ref")
    plan.add_argument("--multi-session", action="store_true")
    plan.set_defaults(func=cmd_plan)

    ticket = commands.add_parser("ticket")
    ticket.add_argument("task_id")
    ticket.add_argument("--ticket-id", required=True)
    ticket.add_argument("--title", required=True)
    ticket.add_argument("--blocked-by", action="append", default=[])
    ticket.add_argument("--acceptance", action="append", default=[])
    ticket.set_defaults(func=cmd_ticket)

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
