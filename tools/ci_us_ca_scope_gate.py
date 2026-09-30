#!/usr/bin/env python3
"""CI scope gate: grep the US/CA deny-list over shipped code, minus allow entries.

Single source of truth for the policy is ``tools/us-ca-scope-deny.json``, shared
with ``agent/tests/test_us_ca_scope_gate.py`` (its Python twin). This helper
greps the deny tokens case-insensitively over ``agent/src``, ``agent/backtest``
and ``frontend/src``, then drops the hits that an ``allow`` entry covers for
that path. It also re-asserts the allowlist invariants the test enforces:
every entry carries a non-empty reason and lists only deny-list tokens.

Exit codes:
    0  no violations
    1  violations found (one ``path: tokens`` line per offending file)
    2  the policy file is malformed (bad JSON or a missing reason)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DENY_FILE = REPO_ROOT / "tools" / "us-ca-scope-deny.json"
SCAN_ROOTS = ("agent/src", "agent/backtest", "frontend/src")
# Mirrors the test's TEXT_SUFFIXES.
TEXT_SUFFIXES = (
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md",
    ".html", ".css", ".yaml", ".yml",
)
EXCLUDE_DIRS = ("node_modules", "__pycache__", ".venv", "dist", "build", ".pytest_cache", ".ruff_cache")


class PolicyError(Exception):
    """The deny/allow policy is malformed."""


def load_policy() -> tuple[list[str], list[dict[str, Any]]]:
    """Return the validated ``(deny, allow)`` policy."""
    try:
        data = json.loads(DENY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot read {DENY_FILE}: {exc}") from exc
    deny = data.get("deny")
    if not isinstance(deny, list) or not deny:
        raise PolicyError("'deny' must be a non-empty list")
    if not all(isinstance(token, str) and token for token in deny):
        raise PolicyError("'deny' entries must be non-empty strings")

    allow = data.get("allow", [])
    if not isinstance(allow, list):
        raise PolicyError("'allow' must be a list of {path, tokens, reason} objects")
    deny_lower = {token.lower() for token in deny}
    for index, entry in enumerate(allow):
        if not isinstance(entry, dict):
            raise PolicyError(f"allow[{index}] must be an object with path/tokens/reason")
        path, tokens, reason = entry.get("path"), entry.get("tokens"), entry.get("reason")
        if not isinstance(path, str) or not path.strip():
            raise PolicyError(f"allow[{index}].path must be a non-empty string")
        if not isinstance(tokens, list) or not tokens:
            raise PolicyError(f"allow[{index}] ({path}).tokens must be a non-empty list")
        if not all(isinstance(token, str) and token.strip() for token in tokens):
            raise PolicyError(f"allow[{index}] ({path}).tokens entries must be non-empty strings")
        unknown = sorted(token for token in tokens if token.lower() not in deny_lower)
        if unknown:
            raise PolicyError(f"allow[{index}] ({path}).tokens lists tokens not in 'deny': {unknown}")
        if not isinstance(reason, str) or not reason.strip():
            raise PolicyError(f"allow[{index}] ({path}) must carry a non-empty 'reason'")
    return deny, allow


def allowed_tokens_for(path: str, allow: list[dict[str, Any]]) -> set[str]:
    """Return the lower-cased deny tokens an allow entry suppresses for ``path``."""
    allowed: set[str] = set()
    for entry in allow:
        if fnmatch(path, entry["path"]):
            allowed.update(token.lower() for token in entry["tokens"])
    return allowed


def grep_hits(deny: list[str]) -> list[tuple[str, int, str]]:
    """Grep every deny token over the scan roots; return ``(path, lineno, text)``."""
    pattern = "|".join(re.escape(token) for token in deny)
    command = ["grep", "-rniE", "-I"]
    command += [f"--include=*{suffix}" for suffix in TEXT_SUFFIXES]
    command += [f"--exclude-dir={name}" for name in EXCLUDE_DIRS]
    command += ["-e", pattern, *SCAN_ROOTS]
    try:
        proc = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True)
    except OSError as exc:  # pragma: no cover - grep missing
        raise PolicyError(f"cannot run grep: {exc}") from exc
    if proc.returncode not in (0, 1):  # grep: 1 == "no matches"
        raise PolicyError(f"grep failed ({proc.returncode}): {proc.stderr.strip()}")

    hits: list[tuple[str, int, str]] = []
    for line in proc.stdout.splitlines():
        path, _, rest = line.partition(":")
        lineno, _, text = rest.partition(":")
        hits.append((path, int(lineno) if lineno.isdigit() else 0, text))
    return hits


def main() -> int:
    try:
        deny, allow = load_policy()
        hits = grep_hits(deny)
    except PolicyError as exc:
        print(f"US/CA scope policy error: {exc}", file=sys.stderr)
        return 2

    violations: dict[str, set[str]] = {}
    for path, _lineno, text in hits:
        allowed = allowed_tokens_for(path, allow)
        low = text.lower()
        offending = {
            token for token in deny
            if token.lower() in low and token.lower() not in allowed
        }
        if offending:
            violations.setdefault(path, set()).update(offending)

    if not violations:
        return 0

    for path in sorted(violations):
        print(f"{path}: {', '.join(sorted(violations[path]))}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
