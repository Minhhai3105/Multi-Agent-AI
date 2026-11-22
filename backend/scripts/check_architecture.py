"""Architecture conformance check (Architecture Design 6.2.8, rules R1-R6).

Lecture 19 (Architecture Forensics & Reconstruction) shows that the implemented
architecture drifts from the documented one unless it is checked. This script
reconstructs the module dependency graph from the source code (Python AST) and
verifies the documented rules:

  R2  API routers contain no SQL/ORM: app.api.routes must not import sqlalchemy,
      app.models, app.repositories or app.integrations.
  R3  Only the Repository/ORM layer builds queries: outside app.repositories and
      app.models, the only sqlalchemy import allowed is `sqlalchemy.orm.Session`.
  R4  Only app.integrations.llm_client talks to the LLM provider (httpx), and
      AgentService never imports the LLM client.
  R5  No cyclic dependencies between modules; only coordinator.py changes a run's
      status (update_run(..., status=...) or claim_run(...)).
  R6  os.environ / os.getenv are read only in app.core.config.
  L   Layer direction: lower layers never import higher ones
      (repositories/integrations/models -/-> services/api; services -/-> api).

Usage:  python scripts/check_architecture.py      (exit code 1 on violations)
"""
from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def scan_source(source: str, filename: str = "<module>") -> dict:
    """Facts the rules need from one module: imports, env reads and run-status changes.

    A run's status changes through update_run(..., status=...) or claim_run(...), whose
    new status is a positional argument, so every claim_run call counts (R5).
    """
    tree = ast.parse(source, filename=filename)
    imports: list[tuple[str, list[str], int]] = []
    env_reads: list[int] = []
    run_status_updates: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, [], node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append((node.module, [a.name for a in node.names], node.lineno))
        elif isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
            if isinstance(node.value, ast.Name) and node.value.id == "os":
                env_reads.append(node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr == "claim_run" or (attr == "update_run" and any(k.arg == "status" for k in node.keywords)):
                run_status_updates.append(node.lineno)
    return {"imports": imports, "env_reads": env_reads, "run_status_updates": run_status_updates}


def collect() -> dict[str, dict]:
    modules = {}
    for path in APP.rglob("*.py"):
        facts = scan_source(path.read_text(encoding="utf-8"), str(path))
        modules[module_name(path)] = {"path": path.relative_to(ROOT), **facts}
    return modules


def check(modules: dict[str, dict]) -> list[str]:
    violations: list[str] = []

    def v(rule: str, mod: str, line: int, msg: str) -> None:
        violations.append(f"[{rule}] {modules[mod]['path']}:{line} {msg}")

    for mod, info in modules.items():
        for target, names, line in info["imports"]:
            # R2 - thin routers
            if mod.startswith("app.api.routes"):
                if target.startswith(("sqlalchemy", "app.models", "app.repositories", "app.integrations")):
                    v("R2", mod, line, f"router imports {target}")
            # R3 - SQL only in repositories/models
            if target.startswith("sqlalchemy") and not mod.startswith(("app.repositories", "app.models")):
                if not (target == "sqlalchemy.orm" and set(names) <= {"Session"}):
                    v("R3", mod, line, f"imports {target} {names} outside the Repository/ORM layer")
            # R4 - only the LLM client calls the provider
            if target.startswith(("httpx", "google", "openai")) and mod != "app.integrations.llm_client":
                v("R4", mod, line, f"imports {target}; only app.integrations.llm_client may call the provider")
            if mod == "app.services.agent_service" and target.startswith("app.integrations.llm_client"):
                v("R4", mod, line, "AgentService must not call the LLM")
            # Layer direction
            if mod.startswith(("app.repositories", "app.integrations", "app.models", "app.core")):
                if target.startswith(("app.services", "app.api")):
                    v("L", mod, line, f"lower layer imports higher layer {target}")
            if mod.startswith("app.services") and target.startswith("app.api"):
                v("L", mod, line, f"service imports API layer {target}")
        # R6 - secrets/config only in app.core.config
        if mod != "app.core.config":
            for line in info["env_reads"]:
                v("R6", mod, line, "reads os.environ/os.getenv outside app.core.config")
        # R5 - only the Coordinator changes run status
        if mod != "app.services.coordinator":
            for line in info["run_status_updates"]:
                v("R5", mod, line, "changes workflow_run status outside WorkflowCoordinator")

    # R5 - no cycles in the module graph
    graph: dict[str, set[str]] = defaultdict(set)
    for mod, info in modules.items():
        for target, names, _ in info["imports"]:
            if not target.startswith("app"):
                continue
            candidates = [target] + [f"{target}.{n}" for n in names]
            for c in candidates:
                if c in modules and c != mod:
                    graph[mod].add(c)
    cycle = _find_cycle(graph)
    if cycle:
        violations.append("[R5] cyclic dependency: " + " -> ".join(cycle))
    return violations


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(int)
    stack: list[str] = []

    def dfs(node: str) -> list[str] | None:
        color[node] = GREY
        stack.append(node)
        for nxt in sorted(graph.get(node, ())):
            if nxt.endswith("__init__") or nxt in ("app",):
                continue
            if color[nxt] == GREY:
                return stack[stack.index(nxt):] + [nxt]
            if color[nxt] == WHITE:
                found = dfs(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in sorted(graph):
        if color[node] == WHITE:
            found = dfs(node)
            if found:
                return found
    return None


def layer_summary(modules: dict[str, dict]) -> dict[str, int]:
    layers = {"api": 0, "services": 0, "integrations": 0, "repositories": 0, "models": 0, "core": 0}
    for mod in modules:
        for layer in layers:
            if mod.startswith(f"app.{layer}"):
                layers[layer] += 1
    return layers


def main() -> int:
    modules = collect()
    violations = check(modules)
    print(f"Checked {len(modules)} modules: {layer_summary(modules)}")
    if violations:
        print(f"{len(violations)} violation(s):")
        for item in violations:
            print("  " + item)
        return 1
    print("OK - rules R2, R3, R4, R5, R6 and layer direction hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
