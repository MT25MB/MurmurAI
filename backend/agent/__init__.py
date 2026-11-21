"""Agent layer: conversation state and the local Ollama ReAct brain."""

from .brain import Brain
from .state import SessionState
from .vision_agent import ScreenController, VisionAgent, StepRecord
from .som_overlay import annotate_screenshot, SomResult, MarkedElement
from .app_knowledge import detect_app_context, AppContext, build_prompt_section

__all__ = [
    "Brain",
    "SessionState",
    "ScreenController",
    "VisionAgent",
    "StepRecord",
    "annotate_screenshot",
    "SomResult",
    "MarkedElement",
    "detect_app_context",
    "AppContext",
    "build_prompt_section",
]
