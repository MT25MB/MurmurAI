"""Pre-release smoke checks: local sidecar, /health, /ws, tools and artifacts.

Runs entirely on localhost with no microphone and no external network. Invoked
by scripts/smoke-test.sh / .ps1.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PORT = int(os.getenv("SMOKE_PORT", "8766"))
BASE = f"http://127.0.0.1:{PORT}"
WS_URL = f"ws://127.0.0.1:{PORT}/ws"


def fail(message: str) -> None:
    print(f"SMOKE FAIL: {message}", flush=True)
    raise SystemExit(1)


def check_artifacts() -> None:
    index = ROOT / "dist" / "index.html"
    if not index.is_file():
        fail(f"frontend build missing: {index}")
    assets = list((ROOT / "dist" / "assets").glob("*.js"))
    if not assets:
        fail("frontend build has no JS assets")
    sidecars = list((ROOT / "src-tauri" / "binaries").glob("murmur-backend-*"))
    if not sidecars:
        fail("no src-tauri/binaries/murmur-backend-* sidecar artifacts")
    print(f"SMOKE OK: frontend + sidecar artifacts ({len(assets)} JS, {len(sidecars)} binaries)")


def check_tools() -> None:
    sys.path.insert(0, str(BACKEND))
    from agent.brain import ALL_TOOLS  # noqa: WPS433 - deliberately late import

    names: list[str] = []
    for tool in ALL_TOOLS:
        fn = tool.get("function", {})
        name = fn.get("name", "")
        params = fn.get("parameters", {})
        if not name or params.get("type") != "object" or not isinstance(params.get("properties"), dict):
            fail(f"invalid tool schema: {name or tool}")
        names.append(name)
    if len(names) != len(set(names)):
        fail("duplicate tool names in brain.ALL_TOOLS")
    required = {
        "run_terminal_command", "describe_screen", "read_clipboard",
        "export_diagnostics", "list_mcp_tools",
    }
    missing = required - set(names)
    if missing:
        fail(f"missing core tools: {sorted(missing)}")
    print(f"SMOKE OK: {len(names)} registered tools with valid schemas")


def wait_for_health(proc: subprocess.Popen, timeout_s: float = 60.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            fail(f"sidecar exited early with code {proc.returncode}")
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=2) as response:
                return json.loads(response.read().decode())
        except Exception:
            time.sleep(0.4)
    fail(f"/health did not respond within {timeout_s:.0f}s")
    return {}


def check_websocket() -> None:
    from websockets.sync.client import connect

    with connect(WS_URL, open_timeout=8, close_timeout=3) as ws:
        greeting = json.loads(ws.recv(timeout=8))
        if greeting.get("type") != "state" or greeting.get("status") != "IDLE":
            fail(f"unexpected WS greeting: {greeting}")
        ws.send(json.dumps({"type": "ping"}))
        pong = json.loads(ws.recv(timeout=8))
        if pong.get("type") != "pong":
            fail(f"unexpected WS pong: {pong}")
    print("SMOKE OK: WebSocket handshake + ping/pong")


def main() -> None:
    check_artifacts()
    check_tools()

    env = os.environ.copy()
    env.update(
        BACKEND_HOST="127.0.0.1",
        BACKEND_PORT=str(PORT),
        OLLAMA_HOST="http://127.0.0.1:1",  # forced offline, never external
        MURMUR_AI_AUTO_DOWNLOAD_WEIGHTS="0",
        MURMUR_AI_EARCONS="0",
    )
    proc = subprocess.Popen(
        [sys.executable, "main.py"], cwd=str(BACKEND), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        health = wait_for_health(proc)
        if health.get("status") != "ok":
            fail(f"unhealthy /health payload: {health}")
        print(f"SMOKE OK: /health {health}")

        # Hardware probing (nvidia-smi) can take a few seconds; give it room.
        status = json.loads(
            urllib.request.urlopen(f"{BASE}/setup/status", timeout=25).read().decode()
        )
        if "recommended_models" not in status or "hardware" not in status:
            fail("/setup/status missing recommended_models or hardware")
        print("SMOKE OK: /setup/status")

        check_websocket()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("SMOKE ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
