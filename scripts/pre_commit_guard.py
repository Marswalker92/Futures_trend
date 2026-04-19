#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


BLOCKED_PATH_PATTERNS = [
    re.compile(r"(^|/)\.env($|\.|/)"),
    re.compile(r"(^|/)output(/|$)"),
    re.compile(r"\.(pem|key|secret|p12|pfx)$", re.IGNORECASE),
    re.compile(r"\.(log|csv|json|db|xlsx)$", re.IGNORECASE),
]

TEXT_FILE_EXTENSIONS = {
    ".py",
    ".sh",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".json",
    ".env",
    ".example",
}

SECRET_PATTERNS = [
    (
        "BINANCE_API_KEY assignment",
        re.compile(r"BINANCE_API_KEY\s*=\s*['\"]?[A-Za-z0-9_\-]{8,}['\"]?"),
    ),
    (
        "BINANCE_API_SECRET assignment",
        re.compile(r"BINANCE_API_SECRET\s*=\s*['\"]?[A-Za-z0-9/_+=\-]{12,}['\"]?"),
    ),
    (
        "generic API key token",
        re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9/_+=\-]{12,}"),
    ),
    (
        "private key block",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ),
]


def run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=False,
        text=True,
        capture_output=True,
    )


def staged_paths() -> list[str]:
    result = run_git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        raise SystemExit(1)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def is_blocked_path(path: str) -> str | None:
    normalized = path.strip()
    if Path(normalized).name == ".env.example":
        return None
    for pattern in BLOCKED_PATH_PATTERNS:
        if pattern.search(normalized):
            return pattern.pattern
    return None


def should_scan_text(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    if suffix in TEXT_FILE_EXTENSIONS:
        return True
    return Path(path).name.startswith(".env")


def staged_file_content(path: str) -> str:
    result = run_git("show", f":{path}")
    if result.returncode != 0:
        return ""
    return result.stdout


def is_placeholder_example_env(content: str) -> bool:
    example_lines = {
        "BINANCE_API_KEY=your_api_key_here",
        "BINANCE_API_SECRET=your_api_secret_here",
    }
    normalized = {line.strip() for line in content.splitlines() if line.strip()}
    return example_lines.issubset(normalized)


def detect_secret(path: str, content: str) -> str | None:
    if Path(path).name == ".env.example" and is_placeholder_example_env(content):
        for label, pattern in SECRET_PATTERNS:
            if label == "private key block" and pattern.search(content):
                return label
        return None

    for label, pattern in SECRET_PATTERNS:
        if pattern.search(content):
            return label
    return None


def main() -> int:
    blocked: list[str] = []
    leaked: list[str] = []

    for path in staged_paths():
        blocked_reason = is_blocked_path(path)
        if blocked_reason:
            blocked.append(f"{path}  (matched blocked path rule: {blocked_reason})")
            continue

        if path == "scripts/pre_commit_guard.py":
            continue

        if not should_scan_text(path):
            continue

        content = staged_file_content(path)
        secret_reason = detect_secret(path, content)
        if secret_reason:
            leaked.append(f"{path}  (matched secret rule: {secret_reason})")

    if not blocked and not leaked:
        return 0

    print("Commit blocked: sensitive files or secret-like content detected.\n", file=sys.stderr)
    if blocked:
        print("Blocked paths:", file=sys.stderr)
        for item in blocked:
            print(f"  - {item}", file=sys.stderr)
        print("", file=sys.stderr)
    if leaked:
        print("Potential secrets in staged content:", file=sys.stderr)
        for item in leaked:
            print(f"  - {item}", file=sys.stderr)
        print("", file=sys.stderr)

    print("Fix suggestions:", file=sys.stderr)
    print("  - Move real credentials into .env and keep only .env.example in git.", file=sys.stderr)
    print("  - Remove accidental staging with: git restore --staged <file>", file=sys.stderr)
    print("  - Keep generated reports inside output/ only.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
