"""Scope gate: forbid removed-market strings from returning to shipped code.

Part of the US/CA-only refactor (docs/refactor-plan.md, Phase 10). Written in
Phase 0 as a *failing* ``xfail``: the denied strings are still present across
the tree, so the assertion currently fails, and ``xfail(strict=True)`` keeps the
suite green while signalling the work is outstanding. Once the refactor deletes
every occurrence, the test starts passing and ``strict=True`` turns it red
(XPASS-strict) — at that point remove the ``xfail`` marker so the gate enforces
for real.

The deny-list lives in ``tools/us-ca-scope-deny.json`` (single source of truth,
shared with the Phase 10 grep gate in ``tools/ci_grep_gates.sh``). Scope is
``agent/src``, ``agent/backtest``, ``frontend/src`` — intentionally **not**
``CHANGELOG.md``, ``agent/tests``, or the plan itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DENY_FILE = REPO_ROOT / "tools" / "us-ca-scope-deny.json"
SCAN_ROOTS = ("agent/src", "agent/backtest", "frontend/src")
# Mirrors ci_grep_gates.sh's --include surface; skips binaries and lockfiles.
TEXT_SUFFIXES = (
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md",
    ".html", ".css", ".yaml", ".yml",
)


def _load_deny_list() -> list[str]:
    data = json.loads(DENY_FILE.read_text(encoding="utf-8"))
    deny = data.get("deny")
    assert isinstance(deny, list) and deny, "tools/us-ca-scope-deny.json 'deny' must be a non-empty list"
    return deny


def _scan() -> dict[str, list[str]]:
    deny = _load_deny_list()
    lowered = [d.lower() for d in deny]
    violations: dict[str, list[str]] = {}
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
            hits = [d for d, dl in zip(deny, lowered) if dl in low]
            if hits:
                violations[str(path.relative_to(REPO_ROOT))] = hits
    return violations


@pytest.mark.xfail(
    reason=(
        "scope gate: removed-market strings still present — expected until the "
        "US/CA refactor completes (Phase 10); remove the xfail marker once it passes"
    ),
    strict=True,
)
def test_us_ca_scope_gate() -> None:
    violations = _scan()
    assert not violations, (
        f"removed-market strings found in shipped code ({len(violations)} files):\n"
        + "\n".join(f"  {path}: {', '.join(hits)}" for path, hits in sorted(violations.items()))
    )
