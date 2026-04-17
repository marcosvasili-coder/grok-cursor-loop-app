#!/usr/bin/env python3
"""Quick import and path check — no network, no Grok login.

Run from repo root:
  python3 scripts/smoke_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    errors: list[str] = []

    for mod in ("playwright", "watchdog", "pystray", "PIL"):
        try:
            __import__(mod)
        except ImportError as e:
            errors.append(f"import {mod}: {e}")

    try:
        import tkinter  # noqa: F401
    except ImportError as e:
        print(
            f"WARNING: tkinter unavailable ({e}) — install a Python with Tcl/Tk to run the GUI.",
            file=sys.stderr,
        )

    for d in ("plans/handoffs", "plans/grok-pm-specs", "plans/debug/screenshots"):
        p = root / d
        try:
            p.mkdir(parents=True, exist_ok=True)
            print(f"OK {p.relative_to(root)}")
        except OSError as e:
            errors.append(f"mkdir {p}: {e}")

    if errors:
        print("smoke_check FAILED:", file=sys.stderr)
        for line in errors:
            print(f"  {line}", file=sys.stderr)
        return 1

    print("smoke_check: all OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
