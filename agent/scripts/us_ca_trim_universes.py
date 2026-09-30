#!/usr/bin/env python3
"""One-off: trim every remaining zoo alpha's ``universe`` metadata to US equity.

Part of the US/CA-only refactor (``docs/refactor-plan.md``, phase 4). The
remaining zoos declared multi-market universes in their ``__alpha_meta__``:

    alpha101     ['equity_us', 'equity_in', 'equity_kr']
    qlib158      ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr']
    academic     ['equity_us', 'equity_cn', 'equity_hk']  (+ one 'crypto' entry)
    fundamental  ["equity_us", "equity_cn", "equity_hk"]

The build ships US equity only, so each becomes the single-entry list. The
rewrite preserves the file's existing quote style for both the key and the list
items, so the diff is one line per alpha.

Usage::

    python agent/scripts/us_ca_trim_universes.py          # rewrite in place
    python agent/scripts/us_ca_trim_universes.py --check  # exit 1 if any stale
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ZOO_ROOT = Path(__file__).resolve().parents[1] / "src" / "factors" / "zoo"

# Zoos that survive the refactor. ``gtja191`` was deleted outright.
ZOOS = ("alpha101", "qlib158", "academic", "fundamental")

TARGET = "equity_us"

# Matches the metadata entry on a single line: 'universe': [...] / "universe": [...]
_UNIVERSE = re.compile(r"""(?P<key>['"]universe['"]\s*:\s*)\[(?P<items>[^\]]*)\]""")


def trim(text: str) -> tuple[str, int]:
    """Return ``(new_text, replacements)`` with every universe list collapsed."""

    def _sub(match: re.Match[str]) -> str:
        items = match.group("items").strip()
        quote = "'" if items.startswith("'") else '"'
        return f"{match.group('key')}[{quote}{TARGET}{quote}]"

    return _UNIVERSE.subn(_sub, text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report stale files and exit 1 instead of rewriting them",
    )
    args = parser.parse_args(argv)

    stale: list[Path] = []
    changed = 0
    scanned = 0

    for zoo in ZOOS:
        zoo_dir = ZOO_ROOT / zoo
        if not zoo_dir.is_dir():  # pragma: no cover - defensive
            print(f"warning: {zoo_dir} not found", file=sys.stderr)
            continue
        for path in sorted(zoo_dir.glob("*.py")):
            if path.name == "__init__.py":
                continue
            scanned += 1
            original = path.read_text(encoding="utf-8")
            if f"[{TARGET}]" in original or f"['{TARGET}']" in original:
                # Already trimmed — but only trust it if no other market remains.
                if not _UNIVERSE.search(original):
                    continue
            updated, count = trim(original)
            if count == 0 or updated == original:
                continue
            stale.append(path)
            if not args.check:
                path.write_text(updated, encoding="utf-8")
                changed += 1

    if args.check:
        for path in stale:
            print(f"stale: {path.relative_to(ZOO_ROOT)}")
        print(f"{len(stale)} stale of {scanned} scanned")
        return 1 if stale else 0

    print(f"{changed} file(s) rewritten of {scanned} scanned")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
