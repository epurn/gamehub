from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = REPO_ROOT / "scripts" / "audit_secret_allowlist.toml"

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
RAW_DOC_REF_RE = re.compile(r"\bdocs/[A-Za-z0-9._/\-]+\.(?:md|toml)\b")
API_KEY_ASSIGN_RE = re.compile(r'api_key\s*=\s*"([^"]+)"')
HISTORY_GREP_LINE_RE = re.compile(
    r"^(?P<commit>[0-9a-f]{40}):(?P<path>[^:]+):(?P<line>\d+):(?P<text>.*)$"
)
URL_LITERAL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%\\\-]+")

HIGH_CONF_SECRET_PATTERNS: dict[str, str] = {
    "aws_access_key": r"(AKIA|ASIA)[0-9A-Z]{16}",
    "github_classic_pat": r"ghp_[A-Za-z0-9]{36}",
    "github_fine_grained_pat": r"github_pat_[A-Za-z0-9_]{20,}",
    "google_api_key": r"AIza[0-9A-Za-z\-_]{35}",
    "slack_token": r"xox[baprs]-[0-9A-Za-z-]{10,}",
    "stripe_live_secret": r"sk_live_[0-9A-Za-z]{20,}",
    "private_key_block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}

ALLOWED_RUNTIME_URL_HOSTS = {
    "127.0.0.1",
    "www.steamgriddb.com",
    "buildbot.libretro.com",
    "dolphin-emu.org",
    "dl.dolphin-emu.org",
    "github.com",
    "flathub.org",
}

MONITORED_ABSOLUTE_PATH_PREFIXES = (
    "/etc/",
    "/run/",
    "/sysroot/",
    "/usr/",
    "/var/",
    "C:/",
    "C:\\",
    "D:/",
    "D:\\",
)

ALLOWED_ABSOLUTE_PATH_PREFIXES = (
    "/etc/os-release",
    "/run/ostree-booted",
    "/sysroot/ostree",
    "/usr/bin/",
    "/usr/local/bin/",
    "/var/lib/flatpak/exports/bin",
)

PLACEHOLDER_SECRET_TOKENS = (
    "optional",
    "placeholder",
    "example",
    "<optional",
    "<your",
    "from-config-key",
    "from-env-key",
    "sgdb-secret-key",
    "quoted-config-key",
)


@dataclass
class Finding:
    level: str
    message: str
    location: str | None = None

    def as_dict(self) -> dict[str, str]:
        payload = {"level": self.level, "message": self.message}
        if self.location:
            payload["location"] = self.location
        return payload


@dataclass
class CheckResult:
    name: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def status(self) -> str:
        levels = {item.level for item in self.findings}
        if "FAIL" in levels:
            return "FAIL"
        if "WARN" in levels:
            return "WARN"
        return "PASS"

    def add_fail(self, message: str, location: str | None = None) -> None:
        self.findings.append(Finding(level="FAIL", message=message, location=location))

    def add_warn(self, message: str, location: str | None = None) -> None:
        self.findings.append(Finding(level="WARN", message=message, location=location))

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "findings": [entry.as_dict() for entry in self.findings],
        }


def _run_git(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


def _iter_non_code_lines(text: str) -> Iterable[tuple[int, str]]:
    in_fence = False
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield line_no, line


def _looks_like_placeholder(value: str) -> bool:
    trimmed = value.strip()
    if not trimmed:
        return True
    lowered = trimmed.casefold()
    if trimmed in {"\\", "\\\\"}:
        return True
    return any(token in lowered for token in PLACEHOLDER_SECRET_TOKENS)


def _chunked(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _load_revoked_secret_allowlist(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    raw_entries = parsed.get("known_revoked_values", [])
    if not isinstance(raw_entries, list):
        return {}
    entries: dict[str, dict[str, str]] = {}
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        fingerprint = raw.get("fingerprint_sha256")
        if not isinstance(fingerprint, str):
            continue
        entries[fingerprint.lower()] = {
            key: str(value)
            for key, value in raw.items()
            if isinstance(value, (str, int, float, bool))
        }
    return entries


def _all_commits() -> list[str]:
    rev_list = _run_git(["rev-list", "--all"])
    if rev_list.returncode != 0:
        return []
    return [line.strip() for line in rev_list.stdout.splitlines() if line.strip()]


def _check_docs() -> CheckResult:
    result = CheckResult(name="docs")
    md_files = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").rglob("*.md"))]

    for md_path in md_files:
        text = md_path.read_text(encoding="utf-8")
        relative_md = md_path.relative_to(REPO_ROOT).as_posix()

        for match in MARKDOWN_LINK_RE.finditer(text):
            target = match.group(1).strip()
            if not target:
                continue
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if "://" in target:
                continue
            resolved = (md_path.parent / target).resolve()
            if not resolved.exists():
                result.add_fail(
                    "Broken markdown link target",
                    location=f"{relative_md} -> {target}",
                )

        for line_no, line in _iter_non_code_lines(text):
            line_without_links = MARKDOWN_LINK_RE.sub("", line)
            for match in RAW_DOC_REF_RE.finditer(line_without_links):
                raw_ref = match.group(0)
                result.add_fail(
                    "Raw docs reference should be a markdown link",
                    location=f"{relative_md}:{line_no} ({raw_ref})",
                )
    return result


def _extract_history_api_key_assignments() -> list[tuple[str, str, str, str]]:
    commits = _all_commits()
    if not commits:
        return []

    rows: list[tuple[str, str, str, str]] = []
    for chunk in _chunked(commits, 200):
        grep = _run_git(["grep", "-nE", r'api_key\s*=\s*"[^"]+"', *chunk, "--", "."])
        if grep.returncode not in (0, 1):
            continue
        for line in grep.stdout.splitlines():
            parsed = HISTORY_GREP_LINE_RE.match(line)
            if parsed is None:
                continue
            text = parsed.group("text")
            value_match = API_KEY_ASSIGN_RE.search(text)
            if value_match is None:
                continue
            rows.append(
                (
                    parsed.group("commit"),
                    parsed.group("path"),
                    parsed.group("line"),
                    value_match.group(1).strip(),
                )
            )
    return rows


def _check_secrets() -> CheckResult:
    result = CheckResult(name="secrets")
    commits = _all_commits()
    if not commits:
        result.add_fail("Failed to enumerate commit history for secret scan")
        return result

    for name, pattern in HIGH_CONF_SECRET_PATTERNS.items():
        matched_commits: set[str] = set()
        failed_scan = False
        for chunk in _chunked(commits, 200):
            grep = _run_git(["grep", "-nEI", "-e", pattern, *chunk, "--", "."])
            if grep.returncode not in (0, 1):
                failed_scan = True
                break
            if grep.returncode == 0:
                for line in grep.stdout.splitlines():
                    parsed = HISTORY_GREP_LINE_RE.match(line)
                    if parsed:
                        matched_commits.add(parsed.group("commit"))
        if failed_scan:
            result.add_fail(f"Failed to scan history for pattern '{name}'")
            continue
        if matched_commits:
            commit_list = sorted(matched_commits)
            preview = ", ".join(commit_list[:5])
            suffix = " ..." if len(commit_list) > 5 else ""
            result.add_fail(
                f"History contains potential secret pattern '{name}' in commit diff(s): {preview}{suffix}"
            )

    allowlisted = _load_revoked_secret_allowlist(ALLOWLIST_PATH)
    seen_history_signatures: set[tuple[str, str, str]] = set()
    for commit, path, line_no, value in _extract_history_api_key_assignments():
        normalized_path = path.replace("\\", "/")
        if normalized_path.startswith("tests/"):
            continue
        if _looks_like_placeholder(value):
            continue
        fingerprint = hashlib.sha256(value.encode("utf-8")).hexdigest()
        location = f"{commit}:{normalized_path}:{line_no}"
        signature = (fingerprint, normalized_path, line_no)
        if signature in seen_history_signatures:
            continue
        seen_history_signatures.add(signature)
        if fingerprint in allowlisted:
            metadata = allowlisted[fingerprint]
            label = metadata.get("label", "known revoked value")
            result.add_warn(
                f"Known revoked historical api_key literal found (sha256={fingerprint}, label={label})",
                location=location,
            )
            continue
        result.add_fail(
            f"Unknown historical api_key literal found (sha256={fingerprint}, length={len(value)})",
            location=location,
        )

    tracked = _run_git(["ls-files"])
    if tracked.returncode != 0:
        result.add_fail("Failed to enumerate tracked files for secret scan")
        return result

    high_conf_regexes = [
        re.compile(pattern)
        for pattern in HIGH_CONF_SECRET_PATTERNS.values()
    ]

    for raw_path in tracked.stdout.splitlines():
        if not raw_path.strip():
            continue
        path = REPO_ROOT / raw_path
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        relative = path.relative_to(REPO_ROOT).as_posix()
        for regex in high_conf_regexes:
            if regex.search(content):
                result.add_fail(
                    "Tracked file contains high-confidence secret signature",
                    location=relative,
                )
                break

        for match in API_KEY_ASSIGN_RE.finditer(content):
            value = match.group(1).strip()
            if relative.startswith("tests/"):
                continue
            if _looks_like_placeholder(value):
                continue
            fingerprint = hashlib.sha256(value.encode("utf-8")).hexdigest()
            result.add_fail(
                f"Tracked file contains non-placeholder api_key literal (sha256={fingerprint})",
                location=relative,
            )
    return result


def _iter_runtime_string_literals(py_path: Path) -> Iterable[tuple[int, str]]:
    text = py_path.read_text(encoding="utf-8-sig")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def _normalized_url_host(url_literal: str) -> str | None:
    cleaned = url_literal.rstrip(").,;\"'")
    normalized = cleaned.replace("\\.", ".")
    parsed = urlparse(normalized)
    return parsed.hostname.casefold() if parsed.hostname else None


def _check_config_literals() -> CheckResult:
    result = CheckResult(name="config")
    src_root = REPO_ROOT / "src"
    if src_root.exists():
        runtime_roots = [src_root]
    else:
        runtime_roots = [
            REPO_ROOT / "apps" / "cli",
            REPO_ROOT / "apps" / "server",
            REPO_ROOT / "shared",
        ]
    for root in runtime_roots:
        for py_path in sorted(root.rglob("*.py")):
            relative = py_path.relative_to(REPO_ROOT).as_posix()
            try:
                literals = list(_iter_runtime_string_literals(py_path))
            except SyntaxError as exc:
                result.add_fail(
                    "Unable to parse python file while auditing runtime literals",
                    location=f"{relative}:{exc.lineno}",
                )
                continue

            for line_no, literal in literals:
                for url in URL_LITERAL_RE.findall(literal):
                    host = _normalized_url_host(url)
                    if host is None:
                        result.add_fail(
                            "Runtime URL literal has no parseable host",
                            location=f"{relative}:{line_no}",
                        )
                        continue
                    if host not in ALLOWED_RUNTIME_URL_HOSTS:
                        result.add_fail(
                            f"Runtime URL host is not allowlisted: {host}",
                            location=f"{relative}:{line_no}",
                        )

                if literal.startswith(MONITORED_ABSOLUTE_PATH_PREFIXES):
                    if not literal.startswith(ALLOWED_ABSOLUTE_PATH_PREFIXES):
                        result.add_fail(
                            "Runtime absolute path literal is not allowlisted",
                            location=f"{relative}:{line_no} ({literal})",
                        )
    return result


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local pre-public readiness audit checks.")
    parser.add_argument(
        "--checks",
        default="docs,secrets,config",
        help="Comma-separated checks to run: docs,secrets,config",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON summary.",
    )
    parser.add_argument(
        "--fail-on-warn",
        action="store_true",
        help="Treat warnings as failures for exit code.",
    )
    args = parser.parse_args(argv)
    selected = [item.strip().casefold() for item in args.checks.split(",") if item.strip()]
    allowed = {"docs", "secrets", "config"}
    invalid = [item for item in selected if item not in allowed]
    if invalid:
        parser.error(f"Unsupported check name(s): {', '.join(sorted(set(invalid)))}")
    args.selected_checks = selected or ["docs", "secrets", "config"]
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    dispatch = {
        "docs": _check_docs,
        "secrets": _check_secrets,
        "config": _check_config_literals,
    }
    results = [dispatch[name]() for name in args.selected_checks]

    has_fail = any(item.status == "FAIL" for item in results)
    has_warn = any(item.status == "WARN" for item in results)
    if has_fail:
        overall = "FAIL"
    elif has_warn:
        overall = "WARN"
    else:
        overall = "PASS"

    payload = {
        "overall": overall,
        "checks": [result.as_dict() for result in results],
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for result in results:
            print(f"[{result.name}] {result.status}")
            for finding in result.findings:
                location = f" ({finding.location})" if finding.location else ""
                print(f"  - {finding.level}: {finding.message}{location}")
        print(f"Overall: {overall}")

    if has_fail:
        return 1
    if args.fail_on_warn and has_warn:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
