#!/usr/bin/env python3
"""Run Murmur AI's local latency benchmark and write BENCHMARKS.md.

Usage: python scripts/benchmark.py [--output PATH] [--json]
Optional deps/models that are not installed are reported as skipped.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from system.benchmark import run_all  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark local Murmur AI latency")
    parser.add_argument(
        "--output", default=str(ROOT / "BENCHMARKS.md"),
        help="Where to write the report (default: repo BENCHMARKS.md)",
    )
    parser.add_argument("--json", action="store_true", help="Write JSON instead of Markdown")
    args = parser.parse_args()

    report = run_all()
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.to_json() if args.json else report.to_markdown(), encoding="utf-8")
    print(f"Wrote {output}")
    if not args.json:
        print()
        print(report.to_markdown())


if __name__ == "__main__":
    main()
