from __future__ import annotations

import ast
import tomllib
from pathlib import Path

CORE = {"sync", "steam", "emulators", "firmware", "controllers", "common", "shortcuts"}
CLI_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "gamehub_cli"
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
REPO_ROOT = Path(__file__).resolve().parents[1]
TOP_PACKAGES = {"gamehub_cli", "gamehub_server", "gamehub_common"}

ALLOWED_DEPENDENCIES: dict[str, set[str]] = {
    "common": set(),
    "controllers": {"common", "emulators", "firmware"},
    "emulators": {"common"},
    "firmware": {"common", "emulators"},
    "shortcuts": {"common", "controllers", "emulators", "firmware", "sync"},
    "steam": {"common"},
    "sync": {"common", "controllers", "emulators", "firmware", "steam"},
}

TOP_LEVEL_DISALLOWED: dict[str, set[str]] = {
    "gamehub_cli": {"gamehub_server"},
    "gamehub_server": {"gamehub_cli"},
    "gamehub_common": {"gamehub_cli", "gamehub_server"},
}


def _module_group(module_path: Path) -> str | None:
    rel = module_path.relative_to(CLI_SRC_ROOT)
    if rel.parts[0] in CORE:
        return rel.parts[0]
    return None


def _module_package_parts(module_path: Path) -> list[str]:
    rel = module_path.relative_to(CLI_SRC_ROOT)
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


def _cli_graph() -> dict[str, set[str]]:
    graph = {group: set() for group in CORE}
    for py in CLI_SRC_ROOT.rglob("*.py"):
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


def _source_top_package(module_path: Path) -> str | None:
    rel = module_path.relative_to(SRC_ROOT)
    if not rel.parts:
        return None
    package = rel.parts[0]
    if package in TOP_PACKAGES:
        return package
    return None


def _top_level_imports(node: ast.AST) -> set[str]:
    found: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            package = alias.name.split(".", 1)[0]
            if package in TOP_PACKAGES:
                found.add(package)
        return found
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        package = node.module.split(".", 1)[0]
        if package in TOP_PACKAGES:
            found.add(package)
    return found


def _top_level_graph() -> dict[str, set[str]]:
    graph = {package: set() for package in TOP_PACKAGES}
    for py in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        source_package = _source_top_package(py)
        if source_package is None:
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            for target in _top_level_imports(node):
                if target != source_package:
                    graph[source_package].add(target)
    return graph


def _repo_local_dynamic_imports() -> list[tuple[Path, str]]:
    violations: list[tuple[Path, str]] = []
    for py in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name: str | None = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name not in {"import_module", "__import__"}:
                continue
            target = node.args[0]
            if not isinstance(target, ast.Constant) or not isinstance(target.value, str):
                continue
            if target.value.startswith(("gamehub_cli.", "gamehub_server.")):
                violations.append((py, target.value))
    return violations


def test_core_package_dependencies_are_acyclic() -> None:
    graph = _cli_graph()
    assert not _has_cycle(graph), f"Detected cycle in core package graph: {graph}"


def test_core_package_dependencies_follow_allowed_directions() -> None:
    graph = _cli_graph()
    violations: dict[str, set[str]] = {}
    for source, targets in graph.items():
        allowed_targets = ALLOWED_DEPENDENCIES[source]
        disallowed = {target for target in targets if target not in allowed_targets}
        if disallowed:
            violations[source] = disallowed

    assert not violations, f"Disallowed core package dependencies detected: {violations}"


def test_top_level_package_dependencies_follow_allowed_directions() -> None:
    graph = _top_level_graph()
    violations: dict[str, set[str]] = {}
    for source, targets in graph.items():
        disallowed_targets = TOP_LEVEL_DISALLOWED.get(source, set())
        disallowed = {target for target in targets if target in disallowed_targets}
        if disallowed:
            violations[source] = disallowed

    assert not violations, f"Disallowed top-level package dependencies detected: {violations}"


def test_runtime_code_does_not_bypass_architecture_with_repo_local_dynamic_imports() -> None:
    violations = _repo_local_dynamic_imports()
    assert not violations, f"Repo-local dynamic imports detected: {violations}"


def test_gamehub_install_has_no_azahar_mouse_bridge_optional_dependency() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    optional_dependencies = pyproject["project"]["optional-dependencies"]

    assert all(not dependency.startswith("evdev>=") for dependency in dependencies)
    assert "linux-input" not in optional_dependencies
