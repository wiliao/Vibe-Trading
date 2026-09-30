"""Scope gate: forbid removed-market strings from returning to shipped code.

Part of the US/CA-only refactor (docs/refactor-plan.md, Phase 10). The deny-list
and its companion allowlist live in ``tools/us-ca-scope-deny.json`` (single
source of truth, shared with the Phase 10 grep gate in
``tools/ci_grep_gates.sh`` through ``tools/ci_us_ca_scope_gate.py``). Scope is
``agent/src``, ``agent/backtest``, ``frontend/src`` — intentionally **not**
``CHANGELOG.md``, ``agent/tests``, or the plan itself.

A hit is a violation unless an ``allow`` entry covers that exact token for that
file: entries match a repo-relative path or an ``fnmatch`` glob and suppress
only their own ``tokens``. Two invariants keep the allowlist honest:

* every entry must carry a non-empty ``reason`` (an unexplained allow is a
  failure), and
* every entry must still suppress at least one real hit (a stale entry is a
  failure), so the list cannot rot as the code changes.
"""

from __future__ import annotations

import json
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DENY_FILE = REPO_ROOT / "tools" / "us-ca-scope-deny.json"
SCAN_ROOTS = ("agent/src", "agent/backtest", "frontend/src")
# Mirrors ci_us_ca_scope_gate.py's --include surface; skips binaries and lockfiles.
TEXT_SUFFIXES = (
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md",
    ".html", ".css", ".yaml", ".yml",
)


def _read_policy() -> dict[str, Any]:
    data = json.loads(DENY_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "tools/us-ca-scope-deny.json must be a JSON object"
    return data


def _load_policy() -> tuple[list[str], list[dict[str, Any]]]:
    """Return the validated ``(deny, allow)`` policy.

    Raises ``AssertionError`` for a malformed policy, including any allow entry
    that does not explain itself.
    """
    data = _read_policy()
    deny = data.get("deny")
    assert isinstance(deny, list) and deny, "tools/us-ca-scope-deny.json 'deny' must be a non-empty list"
    assert all(isinstance(token, str) and token for token in deny), "'deny' entries must be non-empty strings"

    allow = data.get("allow", [])
    assert isinstance(allow, list), "'allow' must be a list of {path, tokens, reason} objects"
    deny_lower = {token.lower() for token in deny}
    for index, entry in enumerate(allow):
        where = f"allow[{index}]"
        assert isinstance(entry, dict), f"{where} must be an object with path/tokens/reason"
        path = entry.get("path")
        tokens = entry.get("tokens")
        reason = entry.get("reason")
        assert isinstance(path, str) and path.strip(), f"{where}.path must be a non-empty string"
        where = f"allow[{index}] ({path})"
        assert isinstance(tokens, list) and tokens, f"{where}.tokens must be a non-empty list"
        assert all(isinstance(t, str) and t.strip() for t in tokens), f"{where}.tokens entries must be non-empty strings"
        unknown = sorted(t for t in tokens if t.lower() not in deny_lower)
        assert not unknown, f"{where}.tokens lists tokens that are not in 'deny': {unknown}"
        assert isinstance(reason, str) and reason.strip(), (
            f"{where} must carry a non-empty 'reason'; an unexplained allow is itself a failure"
        )
    return deny, allow


def _allowed_tokens_for(path: str, allow: list[dict[str, Any]]) -> set[str]:
    """Return the lower-cased deny tokens suppressed for ``path``."""
    allowed: set[str] = set()
    for entry in allow:
        if fnmatch(path, entry["path"]):
            allowed.update(token.lower() for token in entry["tokens"])
    return allowed


def _scan_raw() -> dict[str, list[str]]:
    """Return every file's raw deny-token hits, before allowlist filtering."""
    deny = _load_policy()[0]
    lowered = [token.lower() for token in deny]
    hits: dict[str, list[str]] = {}
    for root_name in SCAN_ROOTS:
        root = REPO_ROOT / root_name
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            low = text.lower()
            found = [token for token, token_low in zip(deny, lowered) if token_low in low]
            if found:
                hits[str(path.relative_to(REPO_ROOT))] = found
    return hits


def _scan() -> dict[str, list[str]]:
    """Return violations: raw hits minus tokens covered by an allow entry."""
    _, allow = _load_policy()
    violations: dict[str, list[str]] = {}
    for path, hits in _scan_raw().items():
        allowed = _allowed_tokens_for(path, allow)
        remaining = [token for token in hits if token.lower() not in allowed]
        if remaining:
            violations[path] = remaining
    return violations


def _allow_usage() -> list[int]:
    """Return, per allow entry, how many real hits it actually suppresses."""
    _, allow = _load_policy()
    usage = [0] * len(allow)
    for path, hits in _scan_raw().items():
        hit_tokens = {token.lower() for token in hits}
        for index, entry in enumerate(allow):
            if fnmatch(path, entry["path"]):
                usage[index] += len(hit_tokens.intersection(token.lower() for token in entry["tokens"]))
    return usage


def test_allow_entries_all_carry_a_reason() -> None:
    """An unexplained allow entry is a failure (also enforced by _load_policy)."""
    _, allow = _load_policy()
    missing = [entry.get("path") for entry in allow if not str(entry.get("reason") or "").strip()]
    assert not missing, f"allow entries without a reason: {missing}"


def test_allow_entries_are_not_stale() -> None:
    """Every allow entry must still suppress a real hit, or the list has rotted."""
    _, allow = _load_policy()
    stale = [
        f"{entry['path']} {entry['tokens']}"
        for entry, used in zip(allow, _allow_usage())
        if used == 0
    ]
    assert not stale, (
        "stale allow entries (they no longer suppress any real hit; delete or retarget them):\n"
        + "\n".join(f"  {entry}" for entry in stale)
    )


def test_us_ca_scope_gate() -> None:
    violations = _scan()
    assert not violations, (
        f"removed-market strings found in shipped code ({len(violations)} files):\n"
        + "\n".join(f"  {path}: {', '.join(hits)}" for path, hits in sorted(violations.items()))
    )
