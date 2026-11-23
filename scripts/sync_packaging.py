#!/usr/bin/env python3
"""Sync package manifests with release version + checksums.

Usage: python scripts/sync_packaging.py --version 1.2.10 --assets-dir release-assets
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from system.packaging_sync import (  # noqa: E402
    collect_artifacts,
    sync_manifests,
    write_sha256sums,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Murmur AI package manifests")
    parser.add_argument("--version", required=True, help="Release version (with or without 'v')")
    parser.add_argument("--assets-dir", required=True, help="Directory with downloaded release assets")
    parser.add_argument("--packaging-dir", default=str(ROOT / "packaging"))
    parser.add_argument("--output-sums", default=None)
    parser.add_argument("--date", default=None, help="Release date (YYYY-MM-DD)")
    args = parser.parse_args()

    version = args.version.lstrip("v")
    assets = Path(args.assets_dir).expanduser()
    artifacts = collect_artifacts(assets, version)
    if not artifacts:
        print(f"WARNING: no installer artifacts found in {assets}", flush=True)

    sums = Path(args.output_sums).expanduser() if args.output_sums else assets / "SHA256SUMS.txt"
    write_sha256sums(artifacts, sums)
    changed = sync_manifests(Path(args.packaging_dir).expanduser(), version, artifacts, args.date)

    print(f"Wrote {sums} ({len(artifacts)} artifacts)")
    for path in changed:
        print(f"Updated {path}")


if __name__ == "__main__":
    main()
