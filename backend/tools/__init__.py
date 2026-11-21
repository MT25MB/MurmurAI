"""Local OS automation tools, installer, and the destructive-action safety gate."""

from .os_tools import OS_TOOLS, dispatch_tool
from .safety import SafetyGate, is_destructive
from .installer_tool import INSTALL_TOOLS, install_application, detect_install_plan
from .event_bus import tool_bus, ToolEventBus

__all__ = [
    "OS_TOOLS",
    "dispatch_tool",
    "SafetyGate",
    "is_destructive",
    "INSTALL_TOOLS",
    "install_application",
    "detect_install_plan",
    "tool_bus",
    "ToolEventBus",
]
