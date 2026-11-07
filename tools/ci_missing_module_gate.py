#!/usr/bin/env python3
"""CI gate: every in-tree ``src.*`` / ``backtest.*`` import must resolve to a file.

Why this exists
---------------
The US/CA branch adopts upstream changes file by file. When a file is updated to
a newer upstream version that *starts importing a sibling module* which was never
adopted, nothing in the tree fails loudly: the importing module simply raises
``ModuleNotFoundError`` the first time something imports it. For an agent tool
module that means the tool is dropped from the registry with one warning line,
and the only visible trace is a summary such as::

    Registered 100 local tools; 1 tool source(s) failed during registry construction

That is how ``agent/src/factors/data_availability.py`` went missing: the sync
adopted the upstream ``bench_runner.py`` (which imports it) but not the new
module itself, so ``alpha_compare`` silently disappeared from the registry while
``agent/tests/test_alpha_compare_tool.py`` stayed red at collection time.

Scope and semantics
-------------------
* Static only. Files are parsed, never imported, so a stray import does not run
  module-level side effects and no optional SDK has to be installed.
* Only imports whose first component is ``src`` or ``backtest`` are checked --
  those are the two packages that live under ``agent/`` (the ``PYTHONPATH=agent``
  root the test suite uses). Third-party and stdlib imports are ignored.
* A relative import is resolved against the importing file's package.
* A module resolves if either ``<pkg>/<parts>.py`` or ``<pkg>/<parts>/`` exists.
  Directories count even without ``__init__.py`` (namespace packages).
* An import guarded by ``try: ... except ImportError`` is still reported: on this
  branch a missing local module inside a try block is how a feature disappears
  quietly, which is the failure this gate is aiming at. Genuine optional-local
  cases belong in ``ALLOW`` with a reason.
* ``agent/tests`` is deliberately NOT scanned. The branch keeps tests that assert
  removed markets are gone (``test_sdk_connectors.py`` imports the pruned
  binance/okx/dhan/shoonya/etoro SDKs inside try blocks to prove they are
  absent), so an unresolvable import there can be intentional. Measured on
  2026-11-07: 803 shipped files clean, 14 findings in the test tree, all of that
  shape. Shipped code is where a missing module costs a tool.

Usage
-----
    python tools/ci_missing_module_gate.py           # report + exit non-zero
    python tools/ci_missing_module_gate.py --list    # same, always exit 0
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# ``agent`` is the import root for both ``src`` and ``backtest``.
IMPORT_ROOT = REPO_ROOT / "agent"
LOCAL_PACKAGES = ("src", "backtest")
SCAN_ROOTS = (
    REPO_ROOT / "agent" / "src",
    REPO_ROOT / "agent" / "backtest",
    REPO_ROOT / "agent" / "api_server.py",
    REPO_ROOT / "agent" / "cli.py",
)

# (importing file, imported module, reason) triples that are knowingly
# unresolved. Every entry needs a reason so the list stays auditable.
ALLOW: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class Finding:
    path: str
    lineno: int
    module: str
    symbol: str

    def render(self) -> str:
        where = f"{self.path}:{self.lineno}"
        target = f"{self.module}.{self.symbol}" if self.symbol else self.module
        return f"{where}: unresolved local import {target!r}"


def _rel(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    return files


def _resolve(parts: list[str]) -> bool:
    if not parts:
        return False
    base = IMPORT_ROOT.joinpath(*parts)
    return base.with_suffix(".py").is_file() or base.is_dir()


def _is_local(parts: list[str]) -> bool:
    return bool(parts) and parts[0] in LOCAL_PACKAGES


def _module_parts_for_file(path: Path) -> list[str]:
    """Dotted module path of ``path`` relative to ``agent/`` (``__init__`` dropped)."""
    rel = path.resolve().relative_to(IMPORT_ROOT.resolve())
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return parts


def _check_file(path: Path) -> list[Finding]:
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:  # a syntax error is its own (louder) failure
        return [Finding(_rel(path), exc.lineno or 0, "<syntax error>", "")]

    own_module = _module_parts_for_file(path)
    package = own_module if path.name == "__init__.py" else own_module[:-1]
    findings: list[Finding] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if _is_local(parts) and not _resolve(parts):
                    findings.append(Finding(_rel(path), node.lineno, alias.name, ""))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # Relative import: climb out of the current package, then append.
                keep = len(package) - (node.level - 1)
                base = package[:keep] if keep > 0 else []
                parts = base + ([node.module] if node.module else [])
            else:
                parts = node.module.split(".") if node.module else []
            if not _is_local(parts) or _resolve(parts):
                continue
            # ``from src.pkg import symbol`` may name a submodule rather than an
            # attribute: accept it when ``src/pkg/symbol.py`` exists.
            for alias in node.names:
                if alias.name == "*":
                    continue
                if _resolve(parts + [alias.name]):
                    continue
                findings.append(Finding(_rel(path), node.lineno, ".".join(parts), alias.name))
    return findings


def scan() -> list[Finding]:
    allowed = {(path, module) for path, module, _reason in ALLOW}
    findings: list[Finding] = []
    for path in _iter_python_files():
        for finding in _check_file(path):
            if (finding.path, finding.module) in allowed:
                continue
            findings.append(finding)
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local-import integrity gate.")
    parser.add_argument("--list", action="store_true", help="report findings but exit 0")
    args = parser.parse_args(argv)

    findings = scan()
    if findings:
        print(f"unresolved local imports: {len(findings)}")
        for finding in findings:
            print(f"  {finding.render()}")
        print()
        print("A local module referenced from shipped code is missing from this branch.")
        print("Either adopt it from upstream (a re-adopted file belongs in PRESERVED")
        print("in agent/scripts/us_ca_prune.py) or remove the import, then re-run.")
        return 0 if args.list else 1
    print(
        f"ok: {len(_iter_python_files())} shipped files scanned; every "
        f"{'/'.join(LOCAL_PACKAGES)} import resolves to a file"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
