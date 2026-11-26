"""Local Model Context Protocol (MCP) client for Murmur AI.

Reads ~/.murmur-ai/mcp_servers.json (standard stdio server format: command,
args, env), connects to each enabled local server over stdin/stdout using MCP's
JSON-RPC 2.0 protocol, discovers its tools, and registers them with the agent
brain at runtime.

Safety: any plugin tool that looks like it writes files, makes external
requests, or runs system actions is gated behind the same spoken
CONFIRMATION_REQUIRED flow used for installer and shell tools. Server owners
can exempt specific tools with an ``allowlist`` in the config.

Only the Python standard library is required. All external servers are local
subprocesses started by the user's own configuration.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("murmur_ai.tools.mcp_manager")

CONFIG_PATH = Path.home() / ".murmur-ai" / "mcp_servers.json"
EXAMPLE_PATH = Path.home() / ".murmur-ai" / "mcp_servers.example.json"
REPO_EXAMPLE = Path(__file__).resolve().parents[1] / "mcp_servers.example.json"

PROTOCOL_VERSION = "2024-11-05"
REQUEST_TIMEOUT = 15.0
IDLE_TIMEOUT = 600.0
DEFAULT_AUDIT_PATH = Path.home() / ".murmur-ai" / "logs" / "tool_audit.jsonl"


def audit_tool_call(
    path: Path,
    server: str,
    tool: str,
    decision: str,
    arguments: dict[str, Any] | None = None,
) -> None:
    """Append a decision line. Arguments are accepted but never serialized."""
    row = {"ts": time.time(), "server": str(server), "tool": str(tool), "decision": str(decision)}
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    except OSError:  # pragma: no cover - audit must never break a tool call
        logger.debug("Could not write tool audit", exc_info=True)

# Word tokens that make a tool risky enough to require spoken confirmation.
# Names are tokenized on underscores/camel boundaries, so "write_note" counts.
_RISK_WORDS = {
    "write", "delete", "remove", "erase", "overwrite", "move", "copy",
    "mkdir", "patch", "edit", "create", "save", "modify",
    "fetch", "http", "https", "request", "download", "upload", "post",
    "curl", "web", "url", "network", "send", "email",
    "exec", "shell", "run", "bash", "cmd", "powershell", "process",
    "install", "kill", "system", "sudo", "terminal", "command",
}

MANAGEMENT_TOOL_NAMES = ("list_mcp_tools", "reload_mcp_plugins")

MANAGEMENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_mcp_tools",
            "description": (
                "List the active MCP/plugin servers and the tools they expose. "
                "Use when the user asks what plugins or MCP tools are active."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reload_mcp_plugins",
            "description": (
                "Reload ~/.murmur-ai/mcp_servers.json and reconnect to all MCP "
                "servers. Use when the user says reload my plugins."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]


class McpError(RuntimeError):
    """Raised when a configured MCP server cannot be reached or responds badly."""


@dataclass
class ServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    allowlist: set[str] = field(default_factory=set)
    tool_modes: dict[str, str] = field(default_factory=dict)
    enabled: bool = True

    @classmethod
    def from_dict(cls, name: str, raw: dict[str, Any]) -> "ServerConfig":
        command = str(raw.get("command", "")).strip()
        if not command:
            raise McpError(f"MCP server '{name}' has no command")
        args = raw.get("args") or []
        env = raw.get("env") or {}
        if not isinstance(args, list) or not isinstance(env, dict):
            raise McpError(f"MCP server '{name}' has invalid args/env")
        allowlist = raw.get("allowlist") or []
        if not isinstance(allowlist, list):
            raise McpError(f"MCP server '{name}' has an invalid allowlist")
        raw_modes = raw.get("tool_modes") or {}
        if not isinstance(raw_modes, dict):
            raise McpError(f"MCP server '{name}' has invalid tool_modes")
        modes = {
            str(k): str(v) for k, v in raw_modes.items()
            if str(v) in {"always", "ask", "off"}
        }
        return cls(
            name=name,
            command=command,
            args=[str(a) for a in args],
            env={str(k): str(v) for k, v in env.items()},
            allowlist={str(a) for a in allowlist},
            tool_modes=modes,
            enabled=bool(raw.get("enabled", True)),
        )


@dataclass
class McpTool:
    name: str          # namespaced name given to the brain
    original_name: str  # name expected by the MCP server
    server: str
    description: str
    schema: dict[str, Any]
    risk: str = "low"
    mode: str = "security"  # security | always | ask | off


def tool_risk(name: str, description: str = "") -> str:
    """Flag tools that could modify state, call the network, or affect the OS."""
    camel_split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", f"{name} {description}")
    tokens = re.split(r"[^a-z0-9]+", camel_split.lower())
    return "high" if any(token in _RISK_WORDS for token in tokens) else "low"


def _namespace(server: str, tool: str) -> str:
    safe_server = re.sub(r"\W+", "_", server).strip("_") or "server"
    safe_tool = re.sub(r"\W+", "_", tool).strip("_") or "tool"
    return f"mcp__{safe_server}__{safe_tool}"


# ---------------------------------------------------------------------------
# Minimal MCP stdio JSON-RPC client
# ---------------------------------------------------------------------------

class StdioMcpClient:
    """Line-delimited JSON-RPC 2.0 client over a local subprocess's stdio."""

    def __init__(self, config: ServerConfig, timeout: float = REQUEST_TIMEOUT):
        self.config = config
        self.timeout = timeout
        self._proc: Optional[subprocess.Popen] = None
        self._messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self._next_id = 0
        self._reader: Optional[threading.Thread] = None

    def start(self) -> None:
        env = os.environ.copy()
        # ${secret:NAME} / keyring:NAME values are resolved from the OS
        # keychain here, at launch time only. They never live in the config
        # file, diagnostics bundle or audit log.
        from security.secret_vault import resolve_secret_env

        env.update(resolve_secret_env(self.config.env))
        self._proc = subprocess.Popen(
            [self.config.command, *self.config.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "murmur-ai", "version": "1.2.49"},
            },
        )
        self.notify("notifications/initialized", {})

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            for line in self._proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._messages.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except Exception:  # pragma: no cover - pipe closed on shutdown
            pass

    def _send(self, payload: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise McpError("MCP server is not running")
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self._send({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        })
        while True:
            try:
                message = self._messages.get(timeout=self.timeout)
            except queue.Empty as exc:
                raise McpError(f"MCP server timed out on {method}") from exc
            if message.get("id") != request_id:
                continue  # notification or a different response
            if "error" in message:
                raise McpError(str(message["error"]))
            return message.get("result") or {}

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=3)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class McpManager:
    """Owns MCP server connections and their dynamic tool registration."""

    def __init__(
        self,
        config_path: Path | None = None,
        client_factory=None,
        bus=None,
        audit_path: Path | None = None,
        idle_timeout: float = IDLE_TIMEOUT,
    ):
        self.config_path = config_path or CONFIG_PATH
        self.client_factory = client_factory or StdioMcpClient
        self._clients: dict[str, StdioMcpClient] = {}
        self._tools: dict[str, McpTool] = {}
        self._configs: dict[str, ServerConfig] = {}
        self._dynamic_names: set[str] = set()
        self._last_used: dict[str, float] = {}
        self.audit_path = Path(audit_path) if audit_path else DEFAULT_AUDIT_PATH
        self.idle_timeout = float(idle_timeout)
        self.errors: list[str] = []
        self.bus = bus  # set lazily to tools.event_bus.tool_bus

    @property
    def _confirm_bus(self):
        if self.bus is None:
            from tools.event_bus import tool_bus

            self.bus = tool_bus
        return self.bus

    # ---- config ----

    def load_config(self) -> dict[str, ServerConfig]:
        """Read and validate the user-editable MCP server configuration."""
        if not self.config_path.exists():
            return {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise McpError(f"Invalid MCP config {self.config_path}: {exc}") from exc
        servers = data.get("servers", data) if isinstance(data, dict) else {}
        if not isinstance(servers, dict):
            raise McpError("MCP config 'servers' must be an object")
        result: dict[str, ServerConfig] = {}
        for name, raw in servers.items():
            if not isinstance(raw, dict):
                continue
            result[str(name)] = ServerConfig.from_dict(str(name), raw)
        return result

    def ensure_example_config(self) -> Path:
        """Create ~/.murmur-ai/mcp_servers.example.json from the bundled sample."""
        EXAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not EXAMPLE_PATH.exists() and REPO_EXAMPLE.exists():
            EXAMPLE_PATH.write_text(REPO_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        return EXAMPLE_PATH

    # ---- lifecycle ----

    def shutdown(self) -> None:
        for client in self._clients.values():
            try:
                client.close()
            except Exception:
                logger.debug("MCP client close failed", exc_info=True)
        self._clients.clear()
        self._last_used.clear()
        self._tools.clear()

    def _audit(self, tool: str, decision: str, arguments: dict[str, Any] | None = None) -> None:
        entry = self._tools.get(tool)
        audit_tool_call(
            self.audit_path,
            entry.server if entry else "unknown",
            tool,
            decision,
            arguments,
        )

    def _close_idle(self) -> None:
        """Stop servers that have not been used within the idle timeout."""
        now = time.monotonic()
        for name, client in list(self._clients.items()):
            if now - self._last_used.get(name, now) <= self.idle_timeout:
                continue
            logger.info("Stopping idle MCP server '%s'", name)
            try:
                client.close()
            except Exception:  # pragma: no cover - defensive
                logger.debug("Idle MCP close failed", exc_info=True)
            self._clients.pop(name, None)
            self._last_used.pop(name, None)

    def reload(self) -> dict[str, Any]:
        """Reconnect to every configured server and rediscover their tools."""
        self.shutdown()
        self.errors = []
        self.ensure_example_config()
        try:
            self._configs = self.load_config()
        except McpError as exc:
            self.errors.append(str(exc))
            self._configs = {}

        for name, config in self._configs.items():
            if not config.enabled:
                continue
            client = self.client_factory(config)
            try:
                client.start()
                tools = client.request("tools/list", {})
                for raw in tools.get("tools", []):
                    original = str(raw.get("name", ""))
                    if not original:
                        continue
                    namespaced = _namespace(name, original)
                    schema = _to_function_schema(raw, namespaced)
                    risk = "low" if original in config.allowlist else tool_risk(
                        original, str(raw.get("description", ""))
                    )
                    self._tools[namespaced] = McpTool(
                        name=namespaced,
                        original_name=original,
                        server=name,
                        description=str(raw.get("description", "")),
                        schema=schema,
                        risk=risk,
                        mode=config.tool_modes.get(original, "security"),
                    )
                self._clients[name] = client
                self._last_used[name] = time.monotonic()
                logger.info("MCP server '%s': %d tools", name, len(tools.get("tools", [])))
            except Exception as exc:
                self.errors.append(f"{name}: {exc}")
                logger.warning("MCP server '%s' failed: %s", name, exc)
                try:
                    client.close()
                except Exception:
                    pass

        self.refresh_brain_tools()
        status = self.status()
        status["summary"] = self.spoken_status()
        return status

    # ---- brain integration ----

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [tool.schema for tool in self._tools.values()]

    def refresh_brain_tools(self) -> None:
        """Replace previously registered dynamic schemas in agent.brain.ALL_TOOLS."""
        import agent.brain as brain_module

        managed = self._dynamic_names | set(MANAGEMENT_TOOL_NAMES)
        kept = [
            tool for tool in brain_module.ALL_TOOLS
            if tool["function"]["name"] not in managed
        ]
        dynamic = self.tool_schemas() + MANAGEMENT_TOOLS
        brain_module.ALL_TOOLS[:] = kept + dynamic
        self._dynamic_names = {t["function"]["name"] for t in self.tool_schemas()}

    # ---- execution ----

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        self._close_idle()
        tool = self._tools.get(name)
        if tool is None:
            self._audit(name, "unknown", arguments)
            return f"Unknown MCP tool: {name}"
        if tool.mode == "off":
            self._audit(name, "off", arguments)
            return f"{name} is switched off in plugin settings."
        needs_confirmation = tool.mode == "ask" or (tool.mode != "always" and tool.risk == "high")
        if needs_confirmation:
            description = (
                f"Plugin tool {name} from {tool.server} can change files, contact "
                "the network, or affect the system. Let it run?"
            )
            approved = self._confirm_bus.request_confirmation(
                description,
                f"mcp:{name} {json.dumps(arguments or {})}",
                timeout=60,
            )
            if not approved:
                self._audit(name, "denied", arguments)
                return f"Cancelled. I did not run {name}."
        client = self._clients.get(tool.server)
        if client is None:
            self._audit(name, "unavailable", arguments)
            return f"MCP server {tool.server} is not connected."
        try:
            result = client.request("tools/call", {
                "name": tool.original_name,
                "arguments": arguments or {},
            })
        except McpError as exc:
            self._audit(name, "error", arguments)
            return f"MCP tool {name} failed: {exc}"
        self._last_used[tool.server] = time.monotonic()
        texts = [
            str(part.get("text", ""))
            for part in result.get("content", [])
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        text = "\n".join(t for t in texts if t)
        if result.get("isError"):
            self._audit(name, "error", arguments)
            return f"MCP tool {name} reported an error: {text or 'unknown error'}"
        self._audit(name, "approved", arguments)
        return text or f"{name} finished."

    # ---- status / voice ----

    def status(self) -> dict[str, Any]:
        return {
            "servers": [
                {"name": name, "connected": name in self._clients}
                for name in self._configs
            ],
            "tools": [
                {"name": t.name, "server": t.server, "risk": t.risk}
                for t in self._tools.values()
            ],
            "errors": list(self.errors),
        }

    def spoken_status(self) -> str:
        if not self._tools and not self._configs:
            return "No MCP plugins are configured. Add servers to ~/.murmur-ai/mcp_servers.json."
        servers = len(self._configs)
        connected = len(self._clients)
        tools = len(self._tools)
        names = ", ".join(sorted(self._tools)) or "none"
        summary = (
            f"{connected} of {servers} MCP servers connected, with {tools} tools: {names}."
        )
        if self.errors:
            summary += f" {len(self.errors)} server(s) could not be reached."
        return summary


def _to_function_schema(raw: dict[str, Any], namespaced: str) -> dict[str, Any]:
    """Convert an MCP tool definition to the brain's OpenAI-style schema."""
    from agent.prompt_guard import strip_override_lines  # lazy: avoids agent<->tools cycle

    input_schema = raw.get("inputSchema") or {}
    if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
        input_schema = {"type": "object"}
    properties = input_schema.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    required = input_schema.get("required")
    if not isinstance(required, list):
        required = []
    return {
        "type": "function",
        "function": {
            "name": namespaced,
            "description": strip_override_lines(str(raw.get("description") or namespaced)),
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": [str(r) for r in required],
                "additionalProperties": False,
            },
        },
    }


# Module-level singleton, like tool_bus and the speaker provider.
manager = McpManager()


def reload_plugins() -> dict[str, Any]:
    """Reload plugins for the shared manager (used by voice tools / lifespan)."""
    return manager.reload()


def list_plugins() -> str:
    """Spoken summary of active MCP plugins."""
    return manager.spoken_status()


def call_mcp_tool(name: str, arguments: dict[str, Any]) -> str:
    return manager.call_tool(name, arguments)
