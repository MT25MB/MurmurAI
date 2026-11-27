#!/usr/bin/env python3
"""Replay and diagnose Murmur AI visual-agent run logs.

Reads step folders written by `agent/vision_agent.py` from either
`~/.murmur-ai/logs/` or `backend/logs/`, and prints a human-friendly trace of
each step: thought, chosen action, coordinates / element ID, and outcome.
It also flags likely problems so you can diagnose missed clicks or VLM JSON
parsing errors without opening every screenshot.

Usage:
    python backend/replay_log.py                 # auto-detect newest run
    python backend/replay_log.py --dir PATH      # explicit log directory
    python backend/replay_log.py --run step_03   # replay a single step
    python backend/replay_log.py --diagnose      # only show problems
    python backend/replay_log.py --list-runs     # list available log folders
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Colors only when attached to a terminal.
def _color(code: str, text: str) -> str:
    if sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text


def C_DIM(s): return _color("2", s)
def C_RED(s): return _color("31", s)
def C_GREEN(s): return _color("32", s)
def C_YELLOW(s): return _color("33", s)
def C_BLUE(s): return _color("34", s)
def C_BOLD(s): return _color("1", s)


def candidate_log_dirs() -> list[Path]:
    """Return likely log directories, newest-first by convention."""
    home_logs = Path.home() / ".murmur-ai" / "logs"
    backend_logs = Path(__file__).resolve().parent / "logs"
    dirs = [home_logs, backend_logs]
    return [d for d in dirs if d.exists()]


def resolve_log_dir(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            raise SystemExit(f"Log directory not found: {p}")
        return p
    dirs = candidate_log_dirs()
    if not dirs:
        raise SystemExit(
            "No log directories found. Looked in ~/.murmur-ai/logs/ and backend/logs/."
        )
    # Prefer the directory with the most recent step artifact.
    def newest(d: Path) -> float:
        steps = list(d.glob("step_*"))
        return max((s.stat().st_mtime for s in steps), default=0.0)
    return max(dirs, key=newest)


def find_runs(log_dir: Path) -> list[Path]:
    """Each step_* folder is a run step; also treat timestamped subdirs as runs."""
    steps = sorted(log_dir.glob("step_*"), key=lambda p: _step_number(p))
    if steps:
        return steps
    # Nested runs (e.g. logs/2026-01-01/step_01), so take the newest parent.
    parents = {p.parent for p in log_dir.glob("**/step_*/step.json")}
    if parents:
        newest = max(parents, key=lambda p: max((s.stat().st_mtime for s in p.glob("step_*")), default=0))
        return sorted(newest.glob("step_*"), key=lambda p: _step_number(p))
    return []


def _step_number(p: Path) -> int:
    try:
        return int(p.name.split("_")[-1])
    except ValueError:
        return 0


def load_step(step_dir: Path) -> dict[str, Any] | None:
    meta = step_dir / "step.json"
    if not meta.exists():
        return None
    try:
        return json.loads(meta.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"_parse_error": f"step.json is invalid JSON: {exc}", "step": _step_number(step_dir)}


def diagnose(data: dict[str, Any], step_dir: Path) -> list[str]:
    """Return a list of human-readable problems for one step."""
    problems: list[str] = []
    if "_parse_error" in data:
        return [C_RED(data["_parse_error"])]

    action = str(data.get("action", "")).upper()
    element_id = data.get("element_id")
    coords = data.get("coordinates")
    drag_to = data.get("drag_to")
    text = data.get("text")
    elements = data.get("elements") or {}
    result = str(data.get("result", "")).lower()
    recovery = str(data.get("recovery", ""))

    # Parsing errors fall back to FINISH with a "non-JSON" thought.
    thought = str(data.get("thought", ""))
    if "non-json" in thought.lower() or "vlm returned non-json" in thought.lower():
        problems.append(C_RED("VLM JSON parse failure, so action defaulted to FINISH."))
    if action == "FINISH" and not data.get("subgoal_done") and not data.get("result"):
        problems.append(C_YELLOW("FINISH without subgoal_done, so the model may have given up."))

    # Click with neither a resolved element nor coordinates.
    if action in ("CLICK", "DOUBLE_CLICK") and element_id is None and not coords:
        problems.append(C_RED(f"{action} has no target (no element_id or coordinates)."))
    # Element ID that no longer exists in the element map.
    if element_id is not None and str(element_id) not in {str(k) for k in elements}:
        problems.append(
            C_YELLOW(f"element_id {element_id} is not in the saved element map, so possible missed click.")
        )
    # Invalid coordinate ranges.
    for label, value in (("coordinates", coords), ("drag_to", drag_to)):
        if value:
            try:
                if not (0 <= float(value[0]) <= 1000 and 0 <= float(value[1]) <= 1000):
                    problems.append(C_YELLOW(f"{label} out of 0-1000 range: {value}"))
            except (ValueError, TypeError, IndexError):
                problems.append(C_RED(f"Malformed {label}: {value}"))
    # Action requiring a payload but missing it.
    if action in ("TYPE", "KEY") and not text:
        problems.append(C_YELLOW(f"{action} action has no text payload."))
    if action == "DRAG" and (not coords or not drag_to):
        problems.append(C_YELLOW("DRAG is missing coordinates or drag_to."))
    # Execution failures / loop recovery.
    if "error" in result or "failed" in result:
        problems.append(C_RED(f"Execution issue: {data.get('result')}"))
    if recovery:
        problems.append(C_YELLOW(f"Loop recovery triggered: {recovery}"))

    # Missing screenshots.
    if not (step_dir / "screen.png").exists():
        problems.append(C_DIM("No screen.png saved for this step."))
    return problems


def print_step(data: dict[str, Any], step_dir: Path, show_problems_only: bool) -> list[str]:
    problems = diagnose(data, step_dir)
    idx = data.get("step", _step_number(step_dir))
    action = str(data.get("action", "?")).upper()

    if not show_problems_only:
        header = f"{C_BOLD(f'STEP {idx}')}"
        if data.get("subgoal"):
            header += f"  |  subgoal {data.get('subgoal_index')}: {C_BLUE(data['subgoal'])}"
        print(header)
        if data.get("app_title"):
            print(f"  app      : {C_DIM(data['app_title'])}")
        print(f"  thought  : {data.get('thought', '')}")
        print(f"  action   : {C_GREEN(action)}")
        if data.get("element_id") is not None:
            print(f"  element  : [{data['element_id']}]")
        if data.get("coordinates"):
            print(f"  coords   : {data['coordinates']}")
        if data.get("drag_to"):
            print(f"  drag_to  : {data['drag_to']}")
        if data.get("text"):
            print(f"  text     : {data['text']}")
        if data.get("subgoal_done"):
            print(f"  progress : {C_GREEN('subgoal complete')}")
        print(f"  outcome  : {data.get('result', '(no outcome recorded)')}")
        shot = step_dir / "screen.png"
        if shot.exists():
            print(f"  screen   : {C_DIM(str(shot))}")
        if problems:
            print("  " + C_RED("problems:"))
            for p in problems:
                print(f"    - {p}")
        print()
    elif problems:
        print(f"{C_BOLD(f'STEP {idx}')} [{action}]")
        for p in problems:
            print(f"    - {p}")
        print()
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay Murmur AI visual-agent logs.")
    parser.add_argument("--dir", help="Explicit log directory.")
    parser.add_argument("--run", help="Replay only a single step folder (e.g. step_03).")
    parser.add_argument("--diagnose", action="store_true", help="Only print steps with problems.")
    parser.add_argument("--list-runs", action="store_true", help="List available step folders and exit.")
    args = parser.parse_args()

    log_dir = resolve_log_dir(args.dir)
    runs = find_runs(log_dir)

    if args.list_runs:
        print(f"Log directory: {log_dir}")
        if not runs:
            print("  (no step_* folders found)")
        for r in runs:
            has_meta = "ok" if (r / "step.json").exists() else C_RED("no step.json")
            print(f"  {r.name}  [{has_meta}]")
        return

    if args.run:
        runs = [r for r in runs if r.name == args.run or r.name.endswith(args.run)]
        if not runs:
            raise SystemExit(f"No step matching '{args.run}' in {log_dir}")

    if not runs:
        raise SystemExit(f"No step logs found in {log_dir}")

    print(f"{C_BOLD('Murmur AI run replay')}  |  {log_dir}  |  {len(runs)} step(s)\n")
    total_problems = 0
    flagged_steps = 0
    for step_dir in runs:
        data = load_step(step_dir)
        if data is None:
            print(f"{C_BOLD(f'STEP {_step_number(step_dir)}')}  {C_RED('missing step.json')}\n")
            total_problems += 1
            flagged_steps += 1
            continue
        problems = print_step(data, step_dir, args.diagnose)
        if problems:
            flagged_steps += 1
            total_problems += len(problems)

    if args.diagnose or total_problems:
        print(
            C_BOLD("Summary:")
            + f" {len(runs)} step(s), {flagged_steps} with problems, {total_problems} total finding(s)."
        )


if __name__ == "__main__":
    main()
