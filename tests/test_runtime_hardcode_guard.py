from __future__ import annotations

import ast
import re
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "src" / "gamehub_cli"
APPID_LIKE_LITERAL_RE = re.compile(r"(?<!\d)-?\d{9,10}(?!\d)")
ALLOWLIST_NUMERIC_APP_ID_CONSTANTS = {"241100"}
# Existing protocol/keycode tokens in controller profile strings. These are not Steam appids.
ALLOWLIST_NON_APPID_NUMERIC_LITERALS = {"016777234", "016777235", "016777236", "016777237"}
BANNED_FIXTURE_LITERALS = (
    "Super Mario Galaxy",
    "Tomodachi Life",
    "Luigi's Mansion",
    "Ape Escape",
    "Gran Turismo 4",
    "Crash Team Racing",
    "3366254221",
    "4290272364",
    "3242237453",
    "-928713075",
    "-602952253",
)


def _runtime_python_files() -> list[Path]:
    return sorted(path for path in RUNTIME_ROOT.rglob("*.py") if path.is_file())


def _iter_assigned_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for element in target.elts:
            names.extend(_iter_assigned_names(element))
        return names
    return []


def _iter_string_assignments(tree: ast.AST) -> list[tuple[int, str, str]]:
    assignments: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        value_node: ast.expr | None = None
        target_nodes: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            value_node = node.value
            target_nodes = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            value_node = node.value
            target_nodes = [node.target]
        if value_node is None:
            continue
        if not isinstance(value_node, ast.Constant) or not isinstance(value_node.value, str):
            continue
        value = value_node.value.strip()
        for target in target_nodes:
            for name in _iter_assigned_names(target):
                assignments.append((node.lineno, name, value))
    return assignments


def test_runtime_modules_do_not_contain_fixture_titles_or_appids() -> None:
    violations: list[str] = []
    for path in _runtime_python_files():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(RUNTIME_ROOT.parent).as_posix()
        for token in BANNED_FIXTURE_LITERALS:
            if token in text:
                violations.append(f"{rel}: contains banned fixture literal {token!r}")
    assert not violations, "\n".join(violations)


def test_runtime_numeric_app_id_constants_are_allowlisted() -> None:
    violations: list[str] = []
    for path in _runtime_python_files():
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        rel = path.relative_to(RUNTIME_ROOT.parent).as_posix()
        for line_no, name, value in _iter_string_assignments(tree):
            upper_name = name.upper()
            if "APP_ID" not in upper_name and "APPID" not in upper_name:
                continue
            if not value.isdigit():
                continue
            if value in ALLOWLIST_NUMERIC_APP_ID_CONSTANTS:
                continue
            violations.append(f"{rel}:{line_no}: {name}={value!r} is not allowlisted")
    assert not violations, "\n".join(violations)


def test_runtime_appid_like_numeric_literals_are_allowlisted() -> None:
    violations: list[str] = []
    for path in _runtime_python_files():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(RUNTIME_ROOT.parent).as_posix()
        for match in APPID_LIKE_LITERAL_RE.finditer(text):
            token = match.group(0)
            if token in ALLOWLIST_NON_APPID_NUMERIC_LITERALS:
                continue
            violations.append(f"{rel}:{token} is a new appid-like literal and must be reviewed/allowlisted")
    assert not violations, "\n".join(violations)
