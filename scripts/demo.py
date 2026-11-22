#!/usr/bin/env python3
"""Guided eyes-free practice sandbox.

Usage: python scripts/demo.py --demo
Prints (and, when available, speaks) four safe practice tasks. No files,
settings, apps or models are touched.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from system.demo import DEMO_STEPS  # noqa: E402


def _speaker():
    try:
        from audio.speaker import LocalSpeaker

        return LocalSpeaker()
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Murmur AI eyes-free practice demo")
    parser.add_argument("--demo", action="store_true", help="Run the guided walkthrough")
    args = parser.parse_args()
    if not args.demo:
        parser.error("pass --demo to start the guided walkthrough")

    speaker = _speaker()
    print("Murmur AI practice mode. Nothing here changes your computer.\n")
    for index, step in enumerate(DEMO_STEPS, 1):
        print(f"Task {index}/4: {step['title']}")
        print(step["prompt"])
        print()
        if speaker is not None:
            speaker.speak(f"Task {index} of four. {step['prompt']}")
        if sys.stdin.isatty() and index < len(DEMO_STEPS):
            try:
                input("Press Enter to continue...")
            except (EOFError, KeyboardInterrupt):
                break
    print("Practice complete. Try these commands for real when you are ready.")


if __name__ == "__main__":
    main()
