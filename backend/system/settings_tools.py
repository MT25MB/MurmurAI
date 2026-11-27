"""Voice-controlled settings and plain-English self diagnostics.

All preferences live in ~/.murmur-ai/config.json so the HUD, the voice loop and
the CLI see the same values. Commands are handled locally and deterministically
before the agent brain, so they work even when Ollama is offline.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from local_endpoint import ollama_host

logger = logging.getLogger("murmur_ai.system.settings_tools")

CONFIG_PATH = Path.home() / ".murmur-ai" / "config.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "speech_rate": 1.0,
    "voice": "af_heart",
    "earcons": True,
    "description_verbosity": "concise",  # concise | detailed
    "listening_mode": "active",          # active | wake
    "mic_threshold": 0.5,                # 0..1, higher = ignore quieter noise
    "screen_reader_friendly": False,     # reduce chatter alongside a screen reader
    "preview_plans": False,              # speak plans before multi-step/file actions
    "media_ducking": False,              # lower media volume while speaking
    "echo_guard": True,                  # ignore our own TTS during listening
    "echo_guard_tail_ms": 250,           # extra quiet after TTS stops
    "loopback_guard": False,             # optional system-audio check
    "spatial_audio_cues": True,          # panned/pitched action sonification
    "voice_profile": "default",          # default | clear | fast | quiet
    "chat_model": "",
    "vision_model": "",
    # Optional OpenAI-compatible provider name (local by default, cloud opt-in).
    "provider": "",
    # LAN-only phone companion is strictly opt-in and off by default.
    "remote_companion_enabled": False,
    "clear_data_on_uninstall": False,  # keep memories/chats/keys unless opted in
}

_CACHE: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_settings() -> dict[str, Any]:
    """Load settings, filling in defaults for missing/invalid values."""
    global _CACHE
    if _CACHE is not None:
        return dict(_CACHE)
    data: dict[str, Any] = {}
    try:
        if CONFIG_PATH.exists():
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
    except (OSError, json.JSONDecodeError):
        logger.debug("Could not read settings; using defaults", exc_info=True)

    settings = dict(DEFAULT_SETTINGS)
    for key, default in DEFAULT_SETTINGS.items():
        value = data.get(key, default)
        if isinstance(default, bool):
            settings[key] = bool(value)
        elif isinstance(default, float):
            try:
                settings[key] = float(value)
            except (TypeError, ValueError):
                settings[key] = default
        else:
            settings[key] = str(value) if value is not None else default
    settings["speech_rate"] = min(2.0, max(0.5, float(settings["speech_rate"])))
    settings["mic_threshold"] = min(1.0, max(0.0, float(settings["mic_threshold"])))
    if settings["description_verbosity"] not in ("concise", "detailed"):
        settings["description_verbosity"] = "concise"
    if settings["listening_mode"] not in ("active", "wake"):
        settings["listening_mode"] = "active"
    # Older configs used qwen2.5-vl, which Ollama does not publish.
    from agent.model_names import normalize_model

    settings["vision_model"] = normalize_model(str(settings.get("vision_model") or ""))
    _CACHE = settings
    return dict(settings)


def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    global _CACHE
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError:
        logger.debug("Could not persist settings", exc_info=True)
    _CACHE = dict(settings)
    return dict(settings)


def validate_model_choice(model: str) -> str:
    """Only known models that fit this machine may be selected."""
    from agent.model_names import normalize_model
    from system.profiler import MODEL_CATALOG, model_fits_hardware, model_requirement

    value = normalize_model(str(model or "").strip())
    if not value:
        return ""
    if value not in MODEL_CATALOG:
        raise ValueError(f"Unknown model '{value}'. Choose one from the available list.")
    if not model_fits_hardware(value):
        raise ValueError(f"This device cannot run {value}. Need {model_requirement(value).lower()}.")
    return value


def update_settings(changes: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    changes = dict(changes or {})
    if "voice_profile" in changes:
        from audio.voice_profiles import profile_settings

        profile = profile_settings(str(changes["voice_profile"]))
        if profile is not None:
            changes = {**profile, **{
                k: v for k, v in changes.items() if k != "voice_profile"
            }}
    for key, value in changes.items():
        if key not in settings or value is None:
            continue
        if key in ("chat_model", "vision_model"):
            value = validate_model_choice(str(value))
        settings[key] = value
    settings = _coerce(settings)
    saved = save_settings(settings)
    apply_settings(saved)
    return saved


def _coerce(settings: dict[str, Any]) -> dict[str, Any]:
    for key, default, low, high in (
        ("speech_rate", 1.0, 0.5, 2.0),
        ("mic_threshold", 0.5, 0.0, 1.0),
    ):
        try:
            value = float(settings.get(key, default))
        except (TypeError, ValueError):
            value = default
        settings[key] = min(high, max(low, value))
    for key in (
        "earcons", "screen_reader_friendly", "media_ducking", "echo_guard",
        "loopback_guard", "spatial_audio_cues", "remote_companion_enabled",
        "clear_data_on_uninstall",
    ):
        settings[key] = bool(settings.get(key, DEFAULT_SETTINGS[key]))
    try:
        settings["echo_guard_tail_ms"] = max(0, min(2000, int(settings.get("echo_guard_tail_ms", 250))))
    except (TypeError, ValueError):
        settings["echo_guard_tail_ms"] = 250
    if settings.get("description_verbosity") not in ("concise", "detailed"):
        settings["description_verbosity"] = "concise"
    if settings.get("listening_mode") not in ("active", "wake"):
        settings["listening_mode"] = "active"
    if settings.get("voice_profile") not in ("default", "clear", "fast", "quiet", "natural"):
        settings["voice_profile"] = "default"
    return settings


def reset_settings() -> dict[str, Any]:
    return save_settings(dict(DEFAULT_SETTINGS))


# ---------------------------------------------------------------------------
# Applying settings to live runtime objects
# ---------------------------------------------------------------------------

def apply_settings(settings: Optional[dict[str, Any]] = None) -> None:
    """Push persisted values into the live speaker, listener and brain."""
    settings = settings or load_settings()
    try:
        from audio.speaker_provider import get_speaker

        speaker = get_speaker()
        if speaker is not None:
            if hasattr(speaker, "set_speech_rate"):
                speaker.set_speech_rate(settings["speech_rate"])
            if hasattr(speaker, "set_voice"):
                speaker.set_voice(settings["voice"])
            if hasattr(speaker, "set_earcons"):
                speaker.set_earcons(settings["earcons"])
            if hasattr(speaker, "set_screen_reader_friendly"):
                speaker.set_screen_reader_friendly(settings["screen_reader_friendly"])
            if hasattr(speaker, "set_media_ducking"):
                speaker.set_media_ducking(settings["media_ducking"])
    except Exception:
        logger.debug("Speaker settings apply failed", exc_info=True)

    try:
        from audio import earcons

        earcons.set_enabled(settings["spatial_audio_cues"])
    except Exception:
        logger.debug("Spatial cue settings apply failed", exc_info=True)

    try:
        import main

        state = main.app_state
        if state.listener is not None and hasattr(state.listener, "set_mic_threshold"):
            state.listener.set_mic_threshold(settings["mic_threshold"])
        tail = settings["echo_guard_tail_ms"] / 1000.0
        echo_kwargs = {
            "enabled": settings["echo_guard"],
            "tail_s": tail,
            "loopback": settings["loopback_guard"],
        }
        if state.listener is not None and hasattr(state.listener, "set_echo_guard"):
            state.listener.set_echo_guard(**echo_kwargs)
        if getattr(state, "wake_detector", None) is not None and hasattr(
            state.wake_detector, "echo_guard"
        ):
            state.wake_detector.echo_guard = settings["echo_guard"]
            state.wake_detector.echo_tail_s = tail
            state.wake_detector.loopback_guard = settings["loopback_guard"]
        if settings.get("chat_model"):
            state.brain.model = settings["chat_model"]
        if settings.get("vision_model"):
            state.brain.vision_model = settings["vision_model"]
        if hasattr(state.brain, "set_provider"):
            state.brain.set_provider(str(settings.get("provider") or ""))
    except Exception:
        logger.debug("Runtime settings apply failed", exc_info=True)


# ---------------------------------------------------------------------------
# Voice commands
# ---------------------------------------------------------------------------

def _voice_reply(text: str) -> str:
    """Speak a confirmation through the shared speaker when available."""
    try:
        from audio.speaker_provider import get_speaker

        speaker = get_speaker()
        if speaker is not None:
            # speak() is asynchronous internally; callers use the returned text
            # for the HUD, so this is just best-effort audible feedback.
            speaker.speak(text)
    except Exception:
        logger.debug("Voice confirmation failed", exc_info=True)
    return text


def handle_voice_command(text: str) -> Optional[str]:
    """Return a spoken reply for a settings command, or None if not a match."""
    original = (text or "").strip()
    value = original.lower()
    if not value:
        return None
    settings = load_settings()

    pronounce = re.search(
        r"pronounce\s+['\"\u2018\u2019]?([\w.+-]+)['\"\u2018\u2019]?\s+as\s+"
        r"['\"\u2018\u2019]?([\w .+\u2018\u2019'-]+?)['\"\u2018\u2019]?\s*$",
        original,
        re.IGNORECASE,
    )
    if pronounce:
        from audio.pronunciation import add_pronunciation

        return _voice_reply(
            add_pronunciation(pronounce.group(1), pronounce.group(2).strip())
        )

    profile_match = re.search(
        r"(?:switch to|use|set|apply) (?:my )?(?:the )?(default|clear|fast|quiet|natural)"
        r"(?: voice)? profile",
        value,
    )
    if profile_match:
        from audio.voice_profiles import apply_voice_profile

        return _voice_reply(apply_voice_profile(profile_match.group(1)))

    if re.search(r"\b(?:high quality|best|natural) voice\b", value):
        from audio.voice_profiles import apply_voice_profile

        return _voice_reply(apply_voice_profile("natural"))

    if re.search(r"\b(be quiet|stop talking|hush|silence yourself|shut up)\b", value):
        try:
            from audio.speaker_provider import get_speaker

            speaker = get_speaker()
            if speaker is not None and hasattr(speaker, "be_quiet"):
                speaker.be_quiet()
            elif speaker is not None:
                speaker.interrupt()
        except Exception:
            pass
        # Deliberately not spoken: the user asked for silence.
        return "Okay, I'll be quiet. Say 'hello' when you need me again."

    # Uninstall data policy: explicit opt-in only; keeping data is the default.
    if re.search(r"\b(clear|delete|erase|remove)\b.*\buninstall(?:ed|ling)?\b", value):
        update_settings({"clear_data_on_uninstall": True})
        return _voice_reply("Your data will be cleared if you uninstall Murmur AI.")
    if re.search(r"\b(keep|save|retain)\b.*\buninstall(?:ed|ling)?\b", value):
        update_settings({"clear_data_on_uninstall": False})
        return _voice_reply("Your data will be kept if you uninstall Murmur AI.")
    if re.search(r"\b(what|whether)\b.*\bdata\b.*\buninstall|\bdata\b.*\buninstall(?:ed|ling)?\b", value):
        kept = not load_settings()["clear_data_on_uninstall"]
        return _voice_reply(
            "Your data will be kept when you uninstall."
            if kept else "Your data will be cleared when you uninstall."
        )

    if re.search(r"screen reader friendly\s+(on|true|enable)|\benable\b.*screen reader friendly", value):
        update_settings({"screen_reader_friendly": True})
        return _voice_reply("Screen reader friendly mode is on.")
    if re.search(r"screen reader friendly\s+(off|false|disable)|\bdisable\b.*screen reader friendly", value):
        update_settings({"screen_reader_friendly": False})
        return _voice_reply("Screen reader friendly mode is off.")

    if re.search(r"\bpreview plans\s+(on|true|enable)\b|\benable\b.*\bplan preview", value):
        update_settings({"preview_plans": True})
        return _voice_reply("Plan previews are on. I'll read multi-step plans before acting.")
    if re.search(r"\bpreview plans\s+(off|false|disable)\b|\bdisable\b.*\bplan preview", value):
        update_settings({"preview_plans": False})
        return _voice_reply("Plan previews are off.")

    if re.search(r"\b(duck|lower)\b.*\bmedia\b.*\bon\b|\bmedia ducking on\b", value):
        update_settings({"media_ducking": True})
        return _voice_reply("Media ducking is on.")
    if re.search(r"\b(duck|lower)\b.*\bmedia\b.*\boff\b|\bmedia ducking off\b", value):
        update_settings({"media_ducking": False})
        return _voice_reply("Media ducking is off.")

    if re.search(r"\b(speak|talk|say things)\s+(a bit |a little )?faster\b|\bspeed up\b|increase .*speech rate", value):
        rate = round(min(2.0, settings["speech_rate"] + 0.15), 2)
        update_settings({"speech_rate": rate})
        return _voice_reply(f"Speaking a little faster now. Rate {rate}.")

    if re.search(r"\bslow down\b|\bspeak slower\b|decrease .*speech rate", value):
        rate = round(max(0.5, settings["speech_rate"] - 0.15), 2)
        update_settings({"speech_rate": rate})
        return _voice_reply(f"Slowing down to rate {rate}.")

    voice_match = re.search(r"(?:use|switch to|change to|set) (?:the )?voice (?:to )?([a-z0-9_-]+)", value)
    if voice_match or re.search(r"change (your|the) voice|switch voice", value):
        voice = voice_match.group(1) if voice_match else "af_heart"
        update_settings({"voice": voice})
        return _voice_reply(f"Voice changed to {voice}.")

    if re.search(r"spatial (audio|cues?)\b.*\bon\b|\benable\b.*spatial (audio|cues?)", value):
        update_settings({"spatial_audio_cues": True})
        return _voice_reply("Spatial audio cues are on.")
    if re.search(r"spatial (audio|cues?)\b.*\boff\b|\bdisable\b.*spatial (audio|cues?)", value):
        update_settings({"spatial_audio_cues": False})
        return _voice_reply("Spatial audio cues are off.")

    if re.search(r"\b(chimes?|sounds?|earcons?)\b.*\bon\b|\benable\b.*\b(chimes?|sounds?|earcons?)\b", value):
        update_settings({"earcons": True})
        return _voice_reply("Chimes are on.")
    if re.search(r"\b(chimes?|sounds?|earcons?)\b.*\boff\b|\bdisable\b.*\b(chimes?|sounds?|earcons?)\b", value):
        update_settings({"earcons": False})
        return _voice_reply("Chimes are off.")

    if re.search(r"detailed screen description|be more detailed|verbose description|full description", value):
        update_settings({"description_verbosity": "detailed"})
        return _voice_reply("Screen descriptions will be detailed.")
    if re.search(r"concise description|brief description|less detail", value):
        update_settings({"description_verbosity": "concise"})
        return _voice_reply("Screen descriptions will be concise.")

    if re.search(r"wake[- ]word mode|only listen for (hey )?murmur|go to standby mode", value):
        update_settings({"listening_mode": "wake"})
        # The runtime transition is performed by main._try_settings_phrase,
        # which owns the listener and wake task.
        return _voice_reply("Wake word mode. I will only listen for hey Murmur.")

    if re.search(r"continuous listening|always listen|active listening mode", value):
        update_settings({"listening_mode": "active"})
        return _voice_reply("Continuous listening is on.")

    if re.search(r"increase (mic|microphone) threshold|noisy room|less sensitive microphone", value):
        threshold = round(min(1.0, settings["mic_threshold"] + 0.1), 2)
        update_settings({"mic_threshold": threshold})
        return _voice_reply(f"Microphone threshold raised to {threshold}.")
    if re.search(r"decrease (mic|microphone) threshold|more sensitive microphone", value):
        threshold = round(max(0.0, settings["mic_threshold"] - 0.1), 2)
        update_settings({"mic_threshold": threshold})
        return _voice_reply(f"Microphone threshold lowered to {threshold}.")

    if re.search(r"show (model )?upgrades|optional models|better models", value):
        return _voice_reply(list_model_upgrades())

    use_match = re.search(
        r"(?:use|switch to|set) (?:the )?([\w.:-]+) (?:as|for) (?:my )?(chat|vision|screen)(?: model)?\b",
        value,
    )
    if use_match:
        role = "vision" if use_match.group(2) in ("vision", "screen") else "chat"
        return _voice_reply(select_model(use_match.group(1), role))

    vision_match = re.search(r"(?:switch|change|set) (?:the )?vision model to ([\w.:-]+)", value)
    if vision_match:
        return _voice_reply(select_model(vision_match.group(1), "vision"))

    chat_match = re.search(r"(?:switch|change|set) (?:the )?(?:chat|language) model to ([\w.:-]+)", value)
    if chat_match:
        return _voice_reply(select_model(chat_match.group(1), "chat"))

    if re.search(r"show (current|available) models|what models|which models", value):
        models = _available_models()
        if not models:
            return _voice_reply("I could not reach Ollama to list models.")
        return _voice_reply("Available models: " + ", ".join(models[:10]) + ".")

    # ---- LAN-only phone companion (opt-in, PIN spoken on start) ----
    if re.search(
        r"\b(?:start|enable|turn on|open)\b.*\bphone remote\b"
        r"|\bstart companion\b|\bphone remote on\b",
        value,
    ):
        from remote.companion_server import start_companion

        result = start_companion()
        return _voice_reply(result["summary"])

    if re.search(
        r"\b(?:stop|disable|turn off|close)\b.*\bphone remote\b"
        r"|\bstop companion\b|\bphone remote off\b",
        value,
    ):
        from remote.companion_server import stop_companion

        return _voice_reply(stop_companion()["summary"])

    if re.search(r"\b(?:what|show)\b.*\bphone remote\b|\bcompanion status\b", value):
        from remote.companion_server import companion_status

        return _voice_reply(companion_status()["summary"])

    if re.search(r"export (a |the )?diagnostics|create (a |the )?diagnostics bundle|save (a |the )?bug report", value):
        from system.diagnostics_bundle import export_diagnostics

        try:
            return export_diagnostics(speak=True)
        except Exception:
            return _voice_reply("I couldn't create the diagnostics bundle.")

    if re.search(r"run diagnostics|why aren't you working|why are you not working|check your status", value):
        return _voice_reply(run_diagnostics()["summary"])

    if re.search(r"fix (missing )?permissions|open accessibility settings", value):
        result = fix_permissions()
        return _voice_reply(result)

    if re.search(r"restart ollama|start ollama", value):
        result = restart_ollama()
        return _voice_reply(result)

    # ---- OS keychain credentials (values are never spoken back) ----
    from security.secret_vault import (
        delete_secret_reference,
        list_configured_secrets,
        set_secret_reference,
    )

    confirm_delete = re.search(
        r"\b(?:yes[, ]+)?confirm\s+delete\s+(?:my\s+)?secret\s+([\w.:-]+)\b",
        original,
        re.IGNORECASE,
    )
    if confirm_delete:
        return _voice_reply(delete_secret_reference(confirm_delete.group(1), True))

    delete_match = re.search(
        r"\b(?:delete|remove|forget)\s+(?:my\s+)?secret\s+([\w.:-]+)\b",
        original,
        re.IGNORECASE,
    )
    if delete_match:
        return _voice_reply(delete_secret_reference(delete_match.group(1), False))

    set_match = re.search(
        r"\b(?:set|store|save|remember)\s+(?:my\s+)?secret\s+([\w.:-]+)\s+"
        r"(?:to|as|is)\s+(.+?)\s*$",
        original,
        re.IGNORECASE,
    )
    if set_match:
        raw_value = set_match.group(2).strip().strip("'\"\u2018\u2019\u201c\u201d")
        if raw_value.endswith("."):
            raw_value = raw_value[:-1].rstrip()
        return _voice_reply(set_secret_reference(set_match.group(1), raw_value))

    if re.search(
        r"\b(?:list|show)\s+(?:my\s+)?(?:configured\s+)?secrets\b"
        r"|\bwhat secrets (?:are|do i have)\b"
        r"|\bwhich secrets are (?:configured|set)\b",
        value,
    ):
        return _voice_reply(list_configured_secrets())

    if re.search(r"show (current )?settings|read me (my )?settings", value):
        return _voice_reply(settings_summary())

    return None


def settings_summary() -> str:
    s = load_settings()
    return (
        f"Speech rate {s['speech_rate']}, voice {s['voice']}, "
        f"chimes {'on' if s['earcons'] else 'off'}, "
        f"descriptions {s['description_verbosity']}, "
        f"listening {s['listening_mode']}, "
        f"microphone threshold {s['mic_threshold']}."
    )


# ---------------------------------------------------------------------------
# Opt-in model upgrades (hardware gated)
# ---------------------------------------------------------------------------

def list_model_upgrades() -> str:
    """Speak only upgrades this machine can run, with their requirements."""
    from system.profiler import upgrade_options

    options = [option for option in upgrade_options() if option["available"]]
    if not options:
        return "No optional model upgrades are supported by this device."
    names = ", ".join(f"{option['name']} ({option['label']})" for option in options)
    return f"Optional models for this device: {names}. You can install and select them in Settings."


def select_model(name: str, role: str = "auto") -> str:
    """Persist a model choice after checking it fits this hardware."""
    from system.profiler import MODEL_CATALOG, model_fits_hardware, model_requirement

    model = str(name or "").strip()
    entry = MODEL_CATALOG.get(model)
    if entry is None:
        return f"{model or 'That model'} is not a known local model."
    if not model_fits_hardware(model):
        return f"I can't use {model} here. It needs {model_requirement(model).lower()}."
    chosen_role = str(role or "auto").casefold()
    if chosen_role not in ("chat", "vision", "auto", "both"):
        chosen_role = "auto"
    if chosen_role == "auto":
        chosen_role = "vision" if entry["role"] in ("vision", "unified") else "chat"
    if entry["role"] == "unified" and chosen_role == "chat":
        # A unified checkpoint handles text and images; use it for both.
        chosen_role = "both"
    if chosen_role == "both":
        if entry["role"] != "unified":
            return f"{model} cannot be used for both chat and screen on this device."
        update_settings({"chat_model": model, "vision_model": model})
        return f"{model} is now used for both chat and screen."
    if chosen_role not in ("chat", "vision"):
        return f"{model} cannot be used for {chosen_role} on this device."
    update_settings({"chat_model" if chosen_role == "chat" else "vision_model": model})
    return f"{model} is now the {chosen_role} model."


# ---------------------------------------------------------------------------
# Self diagnostics
# ---------------------------------------------------------------------------

def _mic_signal() -> dict[str, Any]:
    """Measure a short microphone block. Hardware optional and non-fatal."""
    try:
        import numpy as np
        import sounddevice as sd

        duration = 0.2
        data = sd.rec(
            int(16000 * duration), samplerate=16000, channels=1, dtype="int16"
        )
        sd.wait()
        rms = float(np.sqrt(np.mean(np.asarray(data, dtype=np.float64) ** 2)))
        return {"available": True, "signal": rms, "ok": rms > 20.0}
    except Exception as exc:
        return {"available": False, "signal": 0.0, "ok": False, "detail": str(exc)}


def _available_models() -> list[str]:
    try:
        import httpx

        resp = httpx.get(f"{ollama_host()}/api/tags", timeout=2.0)
        if resp.status_code != 200:
            return []
        return [
            str(m.get("name", ""))
            for m in resp.json().get("models", [])
            if isinstance(m, dict) and m.get("name")
        ]
    except Exception:
        return []


def run_diagnostics() -> dict[str, Any]:
    """Check microphone, Ollama, models, permissions and display session."""
    import setup as setup_module

    checks: dict[str, Any] = {}
    issues: list[str] = []

    mic = _mic_signal()
    checks["microphone"] = mic
    if not mic.get("available"):
        issues.append("No microphone input device is available.")
    elif not mic.get("ok"):
        issues.append("The microphone is connected but too quiet; try increasing the mic threshold.")

    try:
        ollama = setup_module.ollama_status()
        checks["ollama"] = ollama
        if not ollama.get("running"):
            issues.append("Ollama is not running, so speech and vision models cannot answer.")
    except Exception:
        checks["ollama"] = {"running": False, "installed": False}
        issues.append("I could not check Ollama.")

    models = _available_models()
    checks["models"] = models
    if not models:
        issues.append("No local Ollama models were found.")
    else:
        checks["loaded_models"] = models[:5]

    try:
        permissions = setup_module.permission_status()
        checks["permissions"] = permissions
        for item in permissions.get("items", []):
            if item.get("granted") is False:
                issues.append(f"{item.get('label', 'A permission')} is not granted. {item.get('hint', '')}")
    except Exception:
        checks["permissions"] = {"items": []}

    session_type = os.getenv("XDG_SESSION_TYPE", "").lower()
    if not session_type:
        session_type = "wayland" if os.getenv("WAYLAND_DISPLAY") else ("x11" if os.getenv("DISPLAY") else "unknown")
    checks["display_session"] = session_type
    if session_type == "unknown":
        issues.append("No Wayland or X11 display was detected, so screen control may not work.")

    parts = [
        "Diagnostics.",
        f"Microphone: {'ok' if mic.get('ok') else ('quiet' if mic.get('available') else 'unavailable')}.",
        f"Ollama: {'running' if checks['ollama'].get('running') else 'not running'}.",
        f"Local models: {len(models)}.",
        f"Display: {session_type}.",
    ]
    if issues:
        parts.append("Issues: " + " ".join(issues))
        parts.append(
            "Say 'fix permissions' to open the permission settings, or 'restart Ollama' to start the daemon."
        )
    else:
        parts.append("Everything looks healthy.")

    summary = " ".join(parts)
    return {"checks": checks, "issues": issues, "summary": summary}


def fix_permissions() -> str:
    """Best-effort open of the OS permission settings / prompt."""
    import setup as setup_module

    try:
        setup_module.request_accessibility_prompt()
        return "I opened the permission settings. Enable accessibility and screen recording for Murmur AI, then ask me to reload."
    except Exception:
        return "I could not open the permission settings automatically. Check your system privacy settings for Murmur AI."


def restart_ollama() -> str:
    """Start the local Ollama daemon when installed but not running."""
    import setup as setup_module

    path = setup_module._ollama_binary_path()
    if not path:
        return "Ollama is not installed. Run 'winget install Ollama.Ollama' or see ollama.com/download."
    try:
        subprocess.Popen([path, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Starting Ollama now. Give it a few seconds, then ask me to check again."
    except Exception:
        return "I could not start Ollama automatically. Launch it from your applications menu."


SETTINGS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_diagnostics",
            "description": (
                "Check the microphone, Ollama, local models, OS permissions and "
                "display session, then speak a plain-English status report. Use "
                "when the user asks why Murmur AI is not working or to run diagnostics."
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
            "name": "get_settings",
            "description": "Read the current Murmur AI preferences.",
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
            "name": "set_setting",
            "description": "Change one or more Murmur AI preference values.",
            "parameters": {
                "type": "object",
                "properties": {
                    "changes": {
                        "type": "object",
                        "description": "Map of setting names to new values.",
                    }
                },
                "required": ["changes"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_model_upgrades",
            "description": (
                "List optional better local models this device can actually run, "
                "with their hardware requirements. Current models remain the default."
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
            "name": "select_model",
            "description": (
                "Select a local model for chat or screen vision. Refuses models "
                "the detected RAM/VRAM cannot support. Use only after the user "
                "has chosen an available upgrade in Settings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Model tag, e.g. qwen3.5:9b."},
                    "role": {
                        "type": "string",
                        "description": "chat | vision | both | auto (inferred from the model).",
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
]
