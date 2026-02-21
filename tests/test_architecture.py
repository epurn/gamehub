from __future__ import annotations

import ast
from pathlib import Path

CORE = {"sync", "steam", "emulators", "firmware", "controllers", "common"}
SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "gamehub_cli"


def _module_group(module_path: Path) -> str | None:
    rel = module_path.relative_to(SRC_ROOT)
    if rel.parts[0] in CORE:
        return rel.parts[0]
    return None


def _module_package_parts(module_path: Path) -> list[str]:
    rel = module_path.relative_to(SRC_ROOT)
    if rel.name == "__init__.py":
        return list(rel.parent.parts)
    return list(rel.with_suffix("").parts[:-1])


def _imported_groups(node: ast.AST, module_path: Path) -> set[str]:
    found: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            name = alias.name
            if name.startswith("gamehub_cli."):
                part = name.split(".", 2)[1]
                if part in CORE:
                    found.add(part)
        return found
    if not isinstance(node, ast.ImportFrom):
        return found
    if node.level == 0:
        if not node.module:
            return found
        if node.module.startswith("gamehub_cli."):
            part = node.module.split(".", 2)[1]
            if part in CORE:
                found.add(part)
        return found

    package_parts = _module_package_parts(module_path)
    if node.level > len(package_parts) + 1:
        return found
    base_parts = package_parts[: len(package_parts) - (node.level - 1)]
    module_parts = node.module.split(".") if node.module else []
    resolved = base_parts + module_parts
    if resolved and resolved[0] in CORE:
        found.add(resolved[0])
    return found


def _graph() -> dict[str, set[str]]:
    graph = {group: set() for group in CORE}
    for py in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        src_group = _module_group(py)
        if src_group is None:
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            for target_group in _imported_groups(node, py):
                if target_group != src_group:
                    graph[src_group].add(target_group)
    return graph


def _has_cycle(graph: dict[str, set[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for nxt in graph[node]:
            if dfs(nxt):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(dfs(node) for node in sorted(graph))


def test_core_package_dependencies_are_acyclic() -> None:
    graph = _graph()
    assert not _has_cycle(graph), f"Detected cycle in core package graph: {graph}"
