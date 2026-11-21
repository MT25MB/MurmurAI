"""Local Ollama ReAct brain for Murmur AI.

Receives transcribed user speech, decides whether to call a local OS tool or
reply directly, executes the tool, observes the output, and generates a concise,
conversational spoken response.

Design rules:
- Every reply is short and natural for voice: no markdown, no code blocks, no
  bullet lists unless the user explicitly asks for them.
- All calls go to localhost Ollama only. No paid APIs, no cloud.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from tools.os_tools import OS_TOOLS, dispatch_tool
from tools.installer_tool import INSTALL_TOOLS
from tools.safety import SafetyGate

logger = logging.getLogger("murmur_ai.agent.brain")

# All tools exposed to the local Ollama model (OS control + app installer).
ALL_TOOLS = OS_TOOLS + INSTALL_TOOLS

SYSTEM_PROMPT = """You are Murmur AI, a local voice-controlled desktop assistant.

You run entirely on the user's computer. No cloud. No paid APIs. Every action
happens locally.

You speak through text-to-speech, so keep every response SHORT, conversational,
and natural for voice. Do NOT use markdown, code blocks, bold/italics, or bullet
lists unless the user explicitly asks for them. Say things out loud instead of
writing them down.

Available local tools:
- open_application(app_name): launch an app by name.
- mouse_and_keyboard(action, x, y, text): click, type, scroll, hotkeys.
- capture_screen(): take a screenshot (base64).
- run_terminal_command(command): run a shell command. Destructive ones need confirmation.
- manage_files(operation, path, content): read/write/delete/search local files.
- install_application(app_name): install an app via native silent package managers
  (winget/choco/brew/flatpak/snap/apt). The user is asked to approve before any
  install runs. If the app is not found, it installs via the browser visually.

ReAct loop: think about what the user wants, pick ONE tool at a time (or none),
execute it, observe the result, then reply. If a tool says confirmation is
required, tell the user what needs approval and wait for them to say yes. Never
run destructive commands silently.

If you are unsure what to do, ask the user for clarification in one short
sentence."""


class Brain:
    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
        vision_model: str | None = None,
        timeout: float = 120.0,
    ):
        self.host = (host or os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip(
            "/"
        )
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.vision_model = vision_model or os.getenv(
            "OLLAMA_VISION_MODEL", "llava"
        )
        self.timeout = float(os.getenv("OLLAMA_REQUEST_TIMEOUT", str(timeout)))
        self.safety = SafetyGate()
        self._client = httpx.Client(base_url=self.host, timeout=self.timeout)
        self._tools_ready = bool(ALL_TOOLS)

    # ---- Ollama chat ----

    def _chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        tools: list[dict] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        resp = self._client.post("/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()

    # ---- ReAct turn ----

    def think_and_act(
        self,
        user_text: str,
        conversation_history: list[dict[str, str]] | None = None,
        screen_base64: str | None = None,
    ) -> str:
        """One full ReAct turn. Returns the final spoken response text."""
        history = conversation_history or []
        messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history)
        if screen_base64:
            messages.append(
                {
                    "role": "user",
                    "content": f"(Image on screen, base64 PNG: {screen_base64[:40]}...)",
                }
            )
        messages.append({"role": "user", "content": user_text})

        # First model pass: decide tool or reply.
        response = self._chat(messages, tools=ALL_TOOLS if self._tools_ready else None)
        message = response.get("message", {})
        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            # Direct conversational reply.
            content = message.get("content") or "I'm not sure how to help with that."
            return self._clean_for_voice(content)

        # Execute tools one at a time, feeding results back.
        for call in tool_calls[:5]:  # bound to avoid runaway loops
            name = call.get("function", {}).get("name", "")
            args_raw = call.get("function", {}).get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = {}

            result = dispatch_tool(name, args, self.safety)

            # If the tool demands confirmation, surface it instead of running blindly.
            if result.startswith("Confirmation required"):
                return self._clean_for_voice(result)

            messages.append({"role": "assistant", "content": ""})
            messages.append(
                {"role": "tool", "name": name, "content": str(result)}
            )

        # Second model pass: turn tool results into a spoken reply.
        final = self._chat(messages)
        content = final.get("message", {}).get("content") or "Done."
        return self._clean_for_voice(content)

    # ---- Voice-friendly output ----

    @staticmethod
    def _clean_for_voice(text: str) -> str:
        """Strip markdown/code artifacts so TTS reads naturally."""
        import re

        # Remove code fences.
        text = re.sub(r"```[\s\S]*?```", " ", text)
        # Remove inline code backticks but keep the text inside.
        text = re.sub(r"`([^`]+)`", r"\1", text)
        # Collapse markdown emphasis markers.
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"\*(.*?)\*", r"\1", text)
        # Replace bullets with short phrases.
        text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
        # Collapse whitespace.
        text = re.sub(r"\s+", " ", text).strip()
        return text or "I didn't catch that."
