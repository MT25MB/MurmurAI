#!/usr/bin/env python3
"""Honour the uninstall data choice stored in ~/.murmur-ai/config.json.

Dry-run by default. Pass --apply to actually remove data, which only happens
when the user explicitly chose "clear data on uninstall" in settings.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from system.uninstall import run_cleanup  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Murmur AI uninstall data choice")
    parser.add_argument("--apply", action="store_true", help="actually remove chosen data")
    parser.add_argument("--home", type=Path, default=None, help="override home for testing")
    parser.add_argument("--json", action="store_true", help="print machine-readable result")
    args = parser.parse_args()

    result = run_cleanup(home=args.home, apply=args.apply)
    if args.json:
        print(json.dumps(result, indent=2))
    elif not result["choice"]:
        print("Data kept: clear_data_on_uninstall is off (the default).")
    elif not args.apply:
        print("Data would be cleared. Re-run with --apply to remove it:")
        for path in result["candidates"]:
            print(f"  {path}")
    else:
        print(f"Removed {len(result['removed'])} data paths; model weights were kept.")
        for error in result["errors"]:
            print(f"ERROR {error}", file=sys.stderr)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
