"""Local OS automation tools, installer, and the destructive-action safety gate."""

from .os_tools import OS_TOOLS, dispatch_tool
from .safety import SafetyGate, is_destructive
from .installer_tool import INSTALL_TOOLS, install_application, detect_install_plan
from .event_bus import tool_bus, ToolEventBus
from .browser_tool import BROWSER_TOOLS, open_url, read_page_summary, click_web_element, fill_web_field
from .window_tools import (
    WINDOW_TOOLS, WindowInfo, list_open_windows, focus_or_manage_window,
    get_monitors, monitor_for_rect,
)
from .context_tools import (
    CONTEXT_TOOLS, FileInfo, read_clipboard, write_clipboard, inspect_recent_files,
    handle_context_phrase, record_context, resolve_reference,
)
from .mcp_manager import (
    McpManager, McpTool, ServerConfig, StdioMcpClient, manager as mcp_plugin_manager,
    list_plugins, reload_plugins, call_mcp_tool, tool_risk,
)

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
    "CONTEXT_TOOLS",
    "FileInfo",
    "read_clipboard",
    "write_clipboard",
    "inspect_recent_files",
    "handle_context_phrase",
    "record_context",
    "resolve_reference",
    "BROWSER_TOOLS",
    "open_url",
    "read_page_summary",
    "click_web_element",
    "fill_web_field",
    "WINDOW_TOOLS",
    "WindowInfo",
    "list_open_windows",
    "focus_or_manage_window",
    "get_monitors",
    "monitor_for_rect",
    "McpManager",
    "McpTool",
    "ServerConfig",
    "StdioMcpClient",
    "mcp_plugin_manager",
    "list_plugins",
    "reload_plugins",
    "call_mcp_tool",
    "tool_risk",
]
