"""Subgoal decomposition and progress tracking for the visual agent.

Complex goals like "Open Blender, delete the default cube, add a monkey head,
and subdivide it twice" are broken into ordered subgoals up front. The active
subgoal is injected into the VLM prompt so it focuses on the current step, and
only a short, bounded recent history is kept so local context stays sharp.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx

from local_endpoint import normalize_ollama_host

logger = logging.getLogger("murmur_ai.agent.task_plan")

OLLAMA_HOST = normalize_ollama_host(os.getenv("OLLAMA_HOST"))
PLAN_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
HISTORY_LIMIT = 6  # only the last 5-6 steps are shown to the VLM

PLAN_PROMPT = """You are a planning assistant for a desktop automation agent.
Split the user's goal into a short ordered list of concrete subgoals.

Rules:
- Each subgoal is ONE observable action or state change, phrased as a result.
- A goal with several actions must produce several subgoals. Never collapse
  "open X, do A and do B" into one step or into "open X and do everything".
- When the user says "open X" and then names more actions, the first subgoal
  must be exactly "open X".
- Describe the visible end state, e.g. "Add a UV sphere so it is visible in the
  scene", not a vague intention like "work on the project".
- Use at most 8 subgoals. Prefer fewer, but never fewer than the action count.
- If the goal is a single simple action, return exactly one subgoal.
- Do NOT explain. Return ONLY a JSON object: {"subgoals": ["...", "..."]}

Example:
Goal: "open blender, make a new general project, delete the default cube, and add a sphere"
Subgoals: ["open blender", "Create a new General project in Blender", "Delete the default cube so the scene is empty", "Add a UV sphere so it is visible in the scene"]

User goal: {goal}"""


@dataclass
class Subgoal:
    index: int
    text: str
    done: bool = False
    attempts: int = 0


@dataclass
class TaskPlan:
    goal: str
    subgoals: list[Subgoal] = field(default_factory=list)
    active_index: int = 0

    # ---- progress ----

    def current(self) -> Optional[Subgoal]:
        if self.active_index < len(self.subgoals):
            return self.subgoals[self.active_index]
        return None

    def complete_current(self) -> None:
        sg = self.current()
        if sg:
            sg.done = True
        # Advance past any already-done subgoals.
        while self.active_index < len(self.subgoals) and self.subgoals[self.active_index].done:
            self.active_index += 1

    def note_attempt(self) -> None:
        sg = self.current()
        if sg:
            sg.attempts += 1

    @property
    def all_done(self) -> bool:
        return bool(self.subgoals) and self.active_index >= len(self.subgoals)

    # ---- prompts ----

    def progress_section(self) -> str:
        """A compact plan/status block to inject into the VLM system prompt."""
        if not self.subgoals:
            return ""
        lines = ["TASK PLAN (do only the current subgoal, then stop for the next step):"]
        for i, sg in enumerate(self.subgoals):
            marker = "✓" if sg.done else ("→" if i == self.active_index else "·")
            status = " [done]" if sg.done else (" [CURRENT]" if i == self.active_index else "")
            lines.append(f"  {marker} {i + 1}. {sg.text}{status}")
        cur = self.current()
        if cur:
            lines.append(f"FOCUS ON SUBGOAL {self.active_index + 1}: {cur.text}")
            if cur.attempts >= 2:
                lines.append(
                    "NOTE: you have tried this subgoal several times. "
                    "If progress is unclear, try a keyboard shortcut or menu/search action instead of repeating."
                )
        return "\n".join(lines) + "\n"


def _fallback_split(goal: str) -> list[str]:
    """Deterministic subgoal split when the LLM is unavailable."""
    # Numbered lists, then semicolons, "then"/"and", and plain commas.
    goal = goal.strip()
    parts = re.split(r"(?:\d+[.)]\s*|;\s*|\bthen\b|,?\s+\band\s+|,\s*)", goal, flags=re.IGNORECASE)
    parts = [p.strip(" ,.") for p in parts if p and p.strip(" ,.")]
    # Drop a leading filler like "please".
    cleaned = []
    for p in parts:
        p = re.sub(r"^(please|kindly|can you|could you)\s+", "", p, flags=re.IGNORECASE).strip()
        if p:
            cleaned.append(p)
    if not cleaned:
        cleaned = [goal]
    return cleaned[:8]


_ACTION_WORDS = (
    "open", "launch", "start", "create", "make", "delete", "remove", "add",
    "insert", "save", "select", "click", "type", "build", "rename", "import",
)


def _is_multistep(goal: str) -> bool:
    """True when the goal names more than one distinct action to perform."""
    lowered = (goal or "").lower()
    verbs = {word for word in _ACTION_WORDS if re.search(rf"\b{word}\b", lowered)}
    joined = bool(re.search(r"\b(and|then)\b|,", lowered))
    return len(verbs) >= 2 or (joined and len(verbs) >= 1)


def build_plan(goal: str, timeout: float = 20.0) -> TaskPlan:
    """Decompose a goal into ordered subgoals using the local LLM (with fallback)."""
    plan = TaskPlan(goal=goal)
    try:
        with httpx.Client(base_url=OLLAMA_HOST, timeout=timeout) as client:
            resp = client.post(
                "/api/chat",
                json={
                    "model": PLAN_MODEL,
                    "messages": [{"role": "user", "content": PLAN_PROMPT.format(goal=goal)}],
                    "stream": False,
                    "format": "json",
                },
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "{}")
            data = json.loads(content)
            items = data.get("subgoals") or data.get("steps") or []
            subgoals = [str(x).strip() for x in items if str(x).strip()][:8]
    except Exception:  # pragma: no cover - network/model dependent
        logger.exception("LLM planning failed; using deterministic split")
        subgoals = []

    # A local model sometimes answers "one step" for a clearly multi-action
    # goal. Trust the deterministic split in that case so the agent does not
    # declare success after only launching the app.
    if not subgoals or (len(subgoals) < 2 and _is_multistep(goal)):
        if subgoals:
            logger.warning("LLM collapsed a multi-action goal into one step; using split")
        subgoals = _fallback_split(goal)

    plan.subgoals = [Subgoal(index=i, text=t) for i, t in enumerate(subgoals)]
    logger.info("Plan created with %d subgoal(s): %s", len(plan.subgoals), [s.text for s in plan.subgoals])
    return plan


def format_history(records, limit: int = HISTORY_LIMIT) -> str:
    """Brief recent action/outcome summaries (bounded) for the VLM prompt."""
    if not records:
        return "(none)"
    lines = []
    for r in list(records)[-limit:]:
        target = ""
        if getattr(r, "element_id", None) is not None:
            target = f"el={r.element_id}"
        elif getattr(r, "coordinates", None):
            target = f"at {r.coordinates}"
        if getattr(r, "text", None):
            target = (target + " " + str(r.text)).strip()
        outcome = getattr(r, "result", "") or ""
        cue = f" [recovery: {r.recovery}]" if getattr(r, "recovery", "") else ""
        lines.append(
            f"- {r.action} {target} -> {outcome}{cue}"
        )
    return "\n".join(lines)
