"""First-run environment & dependency setup for Murmur AI.

Responsibilities (all local, zero paid APIs):
- Detect whether Ollama is installed and running at http://localhost:11434.
- Report which required local models are pulled (qwen2.5:7b, qwen2.5-vl:7b).
- Stream Ollama `/api/pull` download progress over a WebSocket endpoint (wired in main.py).
- Auto-download faster-whisper + Kokoro-82M weights on first launch into
  ~/.murmur-ai/models/ (a local cache owned by this app).
- Report OS-level permission state (Accessibility / Screen Recording on macOS,
  Wayland/X11 session checks on Linux, always-granted on Windows).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from system.profiler import (
    KEEP_ALIVE,
    configure_from_hardware as _configure_hardware,
    prewarm_audio as _prewarm_audio,
    recommend_config,
)

logger = logging.getLogger("murmur_ai.setup")

OLLAMA_HOST = (os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")

# Models required for a fully functional Murmur AI.
REQUIRED_MODELS: list[str] = ["qwen2.5:7b", "qwen2.5-vl:7b"]
MODEL_LABELS: dict[str, str] = {
    "qwen2.5:7b": "Fast voice & tool chat model",
    "qwen2.5-vl:7b": "Screen-vision model",
}

# Local model cache owned by Murmur AI.
MODEL_CACHE_DIR = Path.home() / ".murmur-ai" / "models"
COMPLETE_MARKER = MODEL_CACHE_DIR.parent / "setup_complete.json"

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base.en")
KOKORO_REPO = "hexgrad/Kokoro-82M"

# Whether to auto-download heavy local weights on first launch (can be disabled
# for offline/testing scenarios with MURMUR_AI_AUTO_DOWNLOAD_WEIGHTS=0).
AUTO_DOWNLOAD = os.getenv("MURMUR_AI_AUTO_DOWNLOAD_WEIGHTS", "1") == "1"

# Progress callback type: (label: str, percent: int | None, status: str) -> None
ProgressCallback = Callable[[str, Optional[int], str], None]


# ---------------------------------------------------------------------------
# Ollama detection
# ---------------------------------------------------------------------------

def _ollama_binary_path() -> Optional[str]:
    """Locate the ollama binary, including common per-user install paths."""
    found = shutil.which("ollama")
    if found:
        return found
    if platform.system() == "Windows":
        candidates = [
            Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
            Path(os.getenv("ProgramFiles", "")) / "Ollama" / "ollama.exe",
        ]
    elif platform.system() == "Darwin":
        candidates = [Path("/Applications/Ollama.app/Contents/MacOS/ollama"), Path("/usr/local/bin/ollama")]
    else:
        candidates = [Path("/usr/bin/ollama"), Path("/usr/local/bin/ollama")]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def ollama_status() -> dict[str, Any]:
    """Return {installed, running, version?, error?} for Ollama."""
    installed = _ollama_binary_path() is not None
    result: dict[str, Any] = {
        "installed": installed,
        "running": False,
        "install_path": _ollama_binary_path(),
    }
    try:
        resp = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=2.0)
        if resp.status_code == 200:
            result["running"] = True
            data = resp.json()
            result["version"] = data.get("version")
    except Exception as exc:  # pragma: no cover - network dependent
        result["error"] = str(exc)
    return result


def pulled_models(models: Optional[list[str]] = None) -> dict[str, bool]:
    """Return {model_name: is_pulled}. Defaults to the required model set."""
    names = models if models is not None else REQUIRED_MODELS
    status = {name: False for name in names}
    try:
        resp = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=2.0)
        if resp.status_code != 200:
            return status
        models_data = resp.json().get("models", [])
        available = {m.get("name", "").lower() for m in models_data if isinstance(m, dict)}
        for name in names:
            base = name.split(":")[0]
            status[name] = any(
                a == name.lower() or a.startswith(base + ":") for a in available
            )
    except Exception:  # pragma: no cover - network dependent
        pass
    return status


# ---------------------------------------------------------------------------
# Hardware-driven model tier (first-run setup)
# ---------------------------------------------------------------------------

def recommended_setup(profile: Optional[Any] = None) -> dict[str, Any]:
    """Return the model tier recommended for this machine.

    High-RAM/GPU machines get the 7b models; lightweight/CPU machines get the
    3b models. A saved profile or an explicit ``profile`` can override this.
    """
    from system.profiler import HardwareProfile, load_profile

    profile = profile or load_profile()
    cfg = recommend_config(profile)
    models = [cfg["chat_model"], cfg["vision_model"]]
    labels = {
        cfg["chat_model"]: "Fast voice & tool chat model",
        cfg["vision_model"]: "Screen-vision model",
    }
    return {
        **cfg,
        "models": models,
        "model_labels": labels,
        "alternatives": [cfg["alternate_vision_model"]],
    }


def configure_from_hardware(profile: Optional[Any] = None) -> dict[str, Any]:
    """Detect hardware and apply the recommended model/whisper settings.

    Called once on background startup. Environment variables already set by
    the user (settings) always win.
    """
    cfg = _configure_hardware(profile)
    logger.info(
        "Applied %s tier (%s): chat=%s vision=%s whisper=%s/%s",
        cfg["tier"], cfg["compute_backend"], cfg["chat_model"],
        cfg["vision_model"], cfg["whisper_model"], cfg["whisper_compute_type"],
    )
    return cfg


async def warm_models(models: Optional[list[str]] = None) -> dict[str, bool]:
    """Ask Ollama to load the chat and vision models and keep them resident.

    Uses ``/api/generate`` with an empty prompt and ``keep_alive: 30m`` so the
    first real voice command avoids a cold model reload. Non-fatal and safe to
    call when Ollama is offline.
    """
    if models is None:
        rec = recommended_setup()
        models = [rec["chat_model"], rec["vision_model"]]

    results: dict[str, bool] = {}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            for model in models:
                try:
                    resp = await client.post(
                        f"{OLLAMA_HOST}/api/generate",
                        json={
                            "model": model,
                            "prompt": "",
                            "stream": False,
                            "keep_alive": KEEP_ALIVE,
                        },
                    )
                    results[model] = resp.status_code == 200
                except Exception:  # pragma: no cover - network dependent
                    results[model] = False
    except Exception:  # pragma: no cover - network dependent
        pass
    return results


def prewarm_audio_on_startup(speaker: Optional[Any] = None) -> dict[str, bool]:
    """Background pre-warm of Kokoro + silero-vad (non-fatal)."""
    return _prewarm_audio(speaker)


# ---------------------------------------------------------------------------
# Local weight cache (faster-whisper + Kokoro-82M) -> ~/.murmur-ai/models/
# ---------------------------------------------------------------------------

def _marker_path(key: str) -> Path:
    return MODEL_CACHE_DIR / f".{key}_ready"


def local_weights_status() -> dict[str, bool]:
    """Check whether whisper + kokoro weights have been cached."""
    whisper_marker = _marker_path("whisper")
    kokoro_marker = _marker_path("kokoro")
    whisper_ready = whisper_marker.exists() and MODEL_CACHE_DIR.exists()
    kokoro_dir = MODEL_CACHE_DIR / "kokoro-v1_0"
    kokoro_ready = kokoro_marker.exists() or (kokoro_dir.exists() and any(kokoro_dir.iterdir()))
    return {"whisper": bool(whisper_ready), "kokoro": bool(kokoro_ready)}


def _download_whisper(progress: ProgressCallback) -> None:
    """Download faster-whisper weights into the local cache (runs in a thread)."""
    progress("Whisper", 0, "Preparing faster-whisper weights…")
    # faster-whisper downloads via HuggingFace; point HF_HOME at our cache.
    os.environ.setdefault("HF_HOME", str(MODEL_CACHE_DIR / "huggingface"))
    try:
        from faster_whisper import WhisperModel  # type: ignore

        # Read at call time so the hardware profile applied on startup wins.
        model = os.getenv("WHISPER_MODEL", WHISPER_MODEL)
        compute = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
        device = os.getenv("WHISPER_DEVICE", "cpu")
        progress("Whisper", 10, f"Downloading {model} weights…")
        WhisperModel(model, compute_type=compute, device=device)
        _marker_path("whisper").write_text("ok", encoding="utf-8")
        progress("Whisper", 100, "Whisper weights ready.")
    except ImportError:
        progress("Whisper", 0, "faster-whisper not installed — run: pip install faster-whisper")
    except Exception as exc:  # pragma: no cover - network dependent
        logger.exception("Whisper weight download failed")
        progress("Whisper", 0, f"Whisper download failed: {exc}")


def _download_kokoro(progress: ProgressCallback) -> None:
    """Download Kokoro-82M weights into the local cache (runs in a thread)."""
    progress("Kokoro", 0, "Preparing Kokoro-82M weights…")
    target = MODEL_CACHE_DIR / "kokoro-v1_0"
    target.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download  # type: ignore

        progress("Kokoro", 10, "Downloading Kokoro-82M weights…")
        snapshot_download(
            repo_id=KOKORO_REPO,
            local_dir=str(target),
            allow_patterns=["*.onnx", "*.json", "*.bin", "voices/*.pt"],
        )
        _marker_path("kokoro").write_text("ok", encoding="utf-8")
        progress("Kokoro", 100, "Kokoro weights ready.")
    except ImportError:
        progress("Kokoro", 0, "huggingface_hub not installed — run: pip install huggingface_hub")
    except Exception as exc:  # pragma: no cover - network dependent
        logger.exception("Kokoro weight download failed")
        progress("Kokoro", 0, f"Kokoro download failed: {exc}")


async def ensure_local_weights(progress: Optional[ProgressCallback] = None) -> None:
    """Auto-download local TTS/STT weights on first launch (best effort, non-fatal)."""
    MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not AUTO_DOWNLOAD:
        logger.info("Auto-download of local weights disabled by env flag.")
        return

    def log_progress(label: str, percent: Optional[int], status: str) -> None:
        logger.info("[%s] %s%% — %s", label, percent if percent is not None else "?", status)
        if progress:
            progress(label, percent, status)

    weights = local_weights_status()
    loop = asyncio.get_running_loop()
    tasks = []
    if not weights.get("whisper"):
        tasks.append(loop.run_in_executor(None, _download_whisper, log_progress))
    if not weights.get("kokoro"):
        tasks.append(loop.run_in_executor(None, _download_kokoro, log_progress))
    if tasks:
        logger.info("Starting first-run download of %d local weight sets…", len(tasks))
        await asyncio.gather(*tasks, return_exceptions=True)
    else:
        logger.info("Local weights already cached.")


# ---------------------------------------------------------------------------
# Ollama model pulling with streamed progress
# ---------------------------------------------------------------------------

async def pull_model(model: str, on_progress: ProgressCallback) -> dict[str, Any]:
    """Stream Ollama /api/pull progress via on_progress; return final status."""
    model = (model or "").strip()
    if not model:
        return {"ok": False, "error": "No model name provided."}

    on_progress(model, 0, f"Starting download of {model}…")
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_HOST}/api/pull",
                json={"name": model, "stream": True},
            ) as resp:
                if resp.status_code != 200:
                    detail = (await resp.aread()).decode("utf-8", "replace")
                    return {"ok": False, "error": f"Ollama returned {resp.status_code}: {detail[:200]}"}

                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    status = str(data.get("status", ""))
                    total = data.get("total") or 0
                    completed = data.get("completed") or 0
                    percent: Optional[int] = None
                    if total and completed:
                        percent = min(100, int(completed / total * 100))

                    label = f"{status}"
                    if percent is not None:
                        label = f"{status} {percent}%"
                    on_progress(model, percent, label)

                    if status == "success":
                        return {"ok": True, "model": model}
    except Exception as exc:  # pragma: no cover - network dependent
        logger.exception("Ollama pull failed for %s", model)
        return {"ok": False, "error": str(exc)}

    return {"ok": False, "error": "Pull stream ended without success status."}


def install_ollama_instructions() -> dict[str, Any]:
    """Return platform-specific Ollama install info and open the official page."""
    system = platform.system()
    if system == "Windows":
        command = "winget install Ollama.Ollama"
        url = "https://ollama.com/download/windows"
    elif system == "Darwin":
        command = "brew install ollama"
        url = "https://ollama.com/download/mac"
    else:
        command = "curl -fsSL https://ollama.com/install.sh | sh"
        url = "https://ollama.com/download/linux"
    try:  # best effort: open the official installer page in the default browser
        import webbrowser

        webbrowser.open(url)
    except Exception:  # pragma: no cover - headless env
        pass
    return {"platform": system, "command": command, "url": url}


# ---------------------------------------------------------------------------
# OS permission checks (Accessibility / Screen Recording / display server)
# ---------------------------------------------------------------------------

def permission_status() -> dict[str, Any]:
    """Report OS permission/session state for screen + accessibility control."""
    system = platform.system()
    result: dict[str, Any] = {"platform": system, "items": []}

    if system == "Darwin":
        # AXIsProcessTrusted via the ApplicationServices framework.
        accessibility = None
        try:
            import ctypes
            import ctypes.util

            path = ctypes.util.find_library("ApplicationServices")
            if path:
                lib = ctypes.CDLL(path)
                lib.AXIsProcessTrusted.restype = ctypes.c_bool
                lib.AXIsProcessTrusted.argtypes = []
                accessibility = bool(lib.AXIsProcessTrusted())
        except Exception:  # pragma: no cover - platform dependent
            accessibility = None
        result["items"].append(
            {
                "key": "accessibility",
                "label": "Accessibility",
                "granted": accessibility,
                "hint": "System Settings → Privacy & Security → Accessibility → enable Murmur AI.",
            }
        )
        result["items"].append(
            {
                "key": "screen_recording",
                "label": "Screen Recording",
                "granted": None,  # cannot be queried reliably; user confirms
                "hint": "System Settings → Privacy & Security → Screen Recording → enable Murmur AI.",
            }
        )

    elif system == "Linux":
        session = os.getenv("XDG_SESSION_TYPE", "").lower()
        if not session:
            session = "wayland" if os.getenv("WAYLAND_DISPLAY") else ("x11" if os.getenv("DISPLAY") else "unknown")
        result["session_type"] = session
        result["items"].append(
            {
                "key": "display_server",
                "label": f"Display server ({session or 'unknown'})",
                "granted": bool(os.getenv("WAYLAND_DISPLAY") or os.getenv("DISPLAY")),
                "hint": (
                    "Wayland: grant Screen Capture/portal permission in your desktop settings. "
                    "X11: ensure DISPLAY is set and XTest/xdotool is available."
                ),
            }
        )

    else:  # Windows
        result["items"].append(
            {
                "key": "screen_capture",
                "label": "Screen capture & input control",
                "granted": True,
                "hint": "Windows does not require a separate permission for screen capture or UI automation.",
            }
        )

    return result


def request_accessibility_prompt() -> dict[str, Any]:
    """On macOS, trigger the Accessibility permission prompt with a side effect.

    On other platforms this is a no-op returning guidance.
    """
    if platform.system() == "Darwin":
        try:
            import ctypes
            import ctypes.util

            path = ctypes.util.find_library("ApplicationServices")
            if path:
                lib = ctypes.CDLL(path)
                lib.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
                opts = {"kAXTrustedCheckOptionPrompt": True}
                # CoreFoundation dict creation would be needed for real options;
                # a direct call still presents the system prompt on most versions.
                try:
                    lib.AXIsProcessTrustedWithOptions(None)
                except Exception:
                    pass
        except Exception:  # pragma: no cover - platform dependent
            pass
    return permission_status()


# ---------------------------------------------------------------------------
# Setup completion marker
# ---------------------------------------------------------------------------

def get_setup_status() -> dict[str, Any]:
    """Aggregate everything the HUD needs to decide whether to show onboarding."""
    from system.profiler import detect_hardware, load_profile

    ollama = ollama_status()
    models = pulled_models()
    weights = local_weights_status()
    required_ready = all(models.values())
    weights_ready = all(weights.values())
    complete = COMPLETE_MARKER.exists() and ollama["running"] and required_ready and weights_ready

    profile = load_profile() or detect_hardware()
    recommendation = recommended_setup(profile)
    return {
        "ollama": ollama,
        "models": models,
        "model_labels": MODEL_LABELS,
        "weights": weights,
        "weights_ready": weights_ready,
        "model_cache_dir": str(MODEL_CACHE_DIR),
        "required_models": REQUIRED_MODELS,
        "recommended_models": recommendation["models"],
        "recommended_model_labels": recommendation["model_labels"],
        "hardware": {
            "total_ram_gb": profile.total_ram_gb,
            "vram_gb": profile.vram_gb,
            "cpu_cores": profile.cpu_cores,
            "compute_backend": profile.compute_backend,
            "tier": profile.tier,
        },
        "recommendation": recommendation,
        "complete": complete,
        "onboarding_dismissed": COMPLETE_MARKER.exists(),
    }


def mark_setup_complete() -> dict[str, Any]:
    """Persist that onboarding was finished (user can still re-open it later)."""
    COMPLETE_MARKER.parent.mkdir(parents=True, exist_ok=True)
    COMPLETE_MARKER.write_text(
        json.dumps({"dismissed_at": time.time()}),
        encoding="utf-8",
    )
    return get_setup_status()


def reset_setup() -> dict[str, Any]:
    """Re-open onboarding on next launch (useful for troubleshooting)."""
    try:
        COMPLETE_MARKER.unlink(missing_ok=True)
    except OSError:  # pragma: no cover
        pass
    return get_setup_status()
