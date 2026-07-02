#!/usr/bin/env python3
"""High-signal secret scanner for CI.

This is not a replacement for a managed DLP product. It is a repo-local hard
gate for the secrets that would be catastrophic in this project: API keys,
cloud tokens, private keys, Slack tokens and AWS access keys. The rules avoid
generic "password=" matching so placeholders in docs and env templates do not
turn the scan into noise.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 2_000_000
ALLOWLIST_MARKERS = ("allowlist secret", "pragma: allowlist secret")
SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
SKIP_SUFFIXES = {
    ".db",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pyd",
    ".pyc",
    ".so",
    ".sqlite",
    ".sqlite3",
    ".tar",
    ".tgz",
    ".webp",
    ".zip",
}

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\b(?:A3T[A-Z0-9]|AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{36,255}\b")),
    ("openai_api_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9][A-Za-z0-9_-]{30,}\b")),
    ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{20,}\b")),
)


@dataclass(frozen=True, slots=True)
class Finding:
    path: Path
    line_no: int
    kind: str
    excerpt: str


def scan_paths(paths: list[Path]) -> list[Finding]:
    """Return high-confidence secret findings in the provided files."""
    findings: list[Finding] = []
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            if any(marker in lowered for marker in ALLOWLIST_MARKERS):
                continue
            for kind, pattern in PATTERNS:
                if pattern.search(line):
                    findings.append(Finding(path=path, line_no=line_no, kind=kind, excerpt=line.strip()[:180]))
    return findings


def repo_files(root: Path) -> list[Path]:
    """List tracked and unignored untracked files, matching what CI can leak."""
    git = shutil.which("git")
    if git is None:
        return [path for path in root.rglob("*") if _should_scan(path)]
    result = subprocess.run(  # noqa: S603 - executable path is resolved by shutil.which; arguments are fixed.
        [git, "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if result.returncode == 0:
        return [
            root / line
            for line in result.stdout.splitlines()
            if line.strip() and _should_scan(root / line)
        ]
    return [path for path in root.rglob("*") if _should_scan(path)]


def _should_scan(path: Path) -> bool:
    if not path.is_file():
        return False
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    return path.suffix.lower() not in SKIP_SUFFIXES


def _read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > MAX_FILE_BYTES or b"\0" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan repo files for high-risk committed secrets.")
    parser.add_argument("root", nargs="?", default=".", help="Repository root (default: cwd).")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    findings = scan_paths(repo_files(root))
    if not findings:
        print("No high-risk secrets found.")
        return 0
    for finding in findings:
        rel = finding.path.relative_to(root) if finding.path.is_relative_to(root) else finding.path
        print(f"{rel}:{finding.line_no}: {finding.kind}: {finding.excerpt}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
