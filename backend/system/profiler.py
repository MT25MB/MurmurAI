"""Automatic hardware profiling and latency optimization.

Detects RAM, VRAM, CPU cores, and the available compute backend (CUDA on
NVIDIA Windows/Linux, Metal on Apple Silicon, otherwise CPU), then recommends a
model tier for first-run setup. All detection is local and best effort: a
missing tool or permission never breaks startup.

Also provides two latency helpers used elsewhere in the app:
  * ``downscale_png`` - aspect-preserving, high-quality screenshot downscale so
    VLM inference stays fast while Set-of-Marks coordinates remain normalized.
  * ``prewarm_audio`` - imports Kokoro and silero-vad on a background thread so
    the first spoken greeting does not pay import/weight-load cost.

Power users can override any recommended setting in the saved profile under
``~/.murmur-ai/hardware_profile.json`` (``overrides`` map) or with the matching
environment variable. Environment variables always win over recommendations.
"""

from __future__ import annotations

import io
import json
import logging
import os
import platform
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger("murmur_ai.system.profiler")

PROFILE_PATH = Path.home() / ".murmur-ai" / "hardware_profile.json"

# Keep Ollama models resident while Murmur AI is active. Consecutive voice
# commands then avoid the multi-second cold-start model reload.
KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")

# Environment variables the profiler may set. Users can pre-set any of them to
# take full control (settings/overrides are honored over our recommendation).
ENV_CHAT_MODEL = "OLLAMA_MODEL"
ENV_VISION_MODEL = "OLLAMA_VISION_MODEL"
ENV_WHISPER_MODEL = "WHISPER_MODEL"
ENV_WHISPER_COMPUTE = "WHISPER_COMPUTE_TYPE"
ENV_WHISPER_DEVICE = "WHISPER_DEVICE"
ENV_MAX_SCREEN_DIM = "MURMUR_MAX_SCREEN_DIM"
ENV_KEEP_ALIVE = "OLLAMA_KEEP_ALIVE"
ENV_MODEL_FAMILY = "MURMUR_MODEL_FAMILY"
ENV_FAST_MODEL = "MURMUR_FAST_MODEL"

# qwen3.5 checkpoints accept text *and* images natively, so voice chat and
# screen inspection can share one resident Ollama model. The legacy qwen2.5
# family needs a separate vision checkpoint and is kept as a fallback.
UNIFIED_FAMILY = "qwen3.5"
LEGACY_FAMILY = "qwen2.5vl"
UNIFIED_FAMILIES = frozenset({UNIFIED_FAMILY})

# Supported local vision checkpoints. Qwen2.5-VL emits 0-1000 normalized
# boxes; newer families emit pixel coordinates (or 0-1 fractions).
VISION_MODELS = frozenset({
    "qwen3.5:27b",
    "qwen3.5:9b",
    "qwen3.5:4b",
    "gemma4:12b",
    "qwen2.5vl:7b",
    "qwen2.5vl:3b",
})


def model_family(model: str | None) -> str:
    """Return the checkpoint family name ('qwen3.5', 'qwen2.5vl', ...)."""
    return (model or "").strip().lower().partition(":")[0]


def is_unified_multimodal(model: str | None) -> bool:
    """True when one checkpoint handles both voice chat and screen images."""
    return model_family(model) in UNIFIED_FAMILIES


def shared_multimodal_model(chat_model: str | None, vision_model: str | None = None) -> str | None:
    """Return the single model to warm when chat and vision can share one.

    Returns None for legacy families or when the user explicitly configured a
    different, non-unified vision model (their choice always wins).
    """
    chat = (chat_model or "").strip()
    if not is_unified_multimodal(chat):
        return None
    vision = (vision_model or "").strip()
    if vision and vision != chat and not is_unified_multimodal(vision):
        return None
    return chat


def tier_for_hardware(ram_gb: float, vram_gb: float) -> str:
    """Map detected memory to workstation / high / light (legacy values kept)."""
    if (vram_gb or 0) >= 24:
        return "workstation"
    if (ram_gb or 0) >= 16 or (vram_gb or 0) >= 6:
        return "high"
    return "light"


def coordinate_mode(model: str | None) -> str:
    """Return the coordinate convention used by a vision model family."""
    name = (model or "").lower()
    if name.startswith(("qwen3.5", "gemma4")):
        return "pixels"
    return "normalized_1000"


def normalize_vlm_coords(raw, width: int, height: int, model: str | None = None) -> tuple[int, int]:
    """Convert a model's coordinate pair to normalized 0-1000 values."""
    try:
        x, y = float(raw[0]), float(raw[1])
    except (TypeError, ValueError, IndexError):
        return 500, 500
    if coordinate_mode(model) == "pixels":
        # Values <= 1 are treated as fractions of the image.
        x = x * 1000 if 0 <= x <= 1 else x / max(1, width) * 1000
        y = y * 1000 if 0 <= y <= 1 else y / max(1, height) * 1000
    return int(max(0, min(1000, x))), int(max(0, min(1000, y)))

# Context window tiers, chosen from RAM/VRAM on startup. A window that overflows
# grows one tier and retries once; an explicit user value disables auto-sizing.
CONTEXT_TIERS = (4_096, 8_192, 16_384, 32_768)
CONTEXT_REPLY_RESERVE = 512


def initial_context_window(ram_gb: float, vram_gb: float, override: int | None = None) -> int:
    """Pick a starting num_ctx from detected hardware, or honour the override."""
    if override and override > 0:
        return int(override)
    if (ram_gb or 0) >= 16 or (vram_gb or 0) >= 6:
        return 16_384
    if (ram_gb or 0) >= 12 or (vram_gb or 0) >= 3:
        return 8_192
    return 4_096


def needed_context(error: str | None, reserve: int = CONTEXT_REPLY_RESERVE) -> int | None:
    """Parse the token count from an Ollama 'exceeds available context' error."""
    if not error:
        return None
    match = re.search(r"\((\d+)\s*tokens?\)\s*exceeds", error, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1)) + max(0, reserve)


def next_context_window(current: int, needed: int | None, cap: int = 32_768) -> int | None:
    """Return the smallest tier above current that fits, within cap."""
    want = needed or (current * 2)
    for size in CONTEXT_TIERS:
        if size > current and size >= want and size <= cap:
            return size
    return None


@dataclass
class HardwareProfile:
    total_ram_gb: float = 0.0
    vram_gb: float = 0.0
    cpu_cores: int = 1
    compute_backend: str = "CPU"  # CUDA | Metal | CPU
    tier: str = "light"  # workstation | high | light
    os: str = "Unknown"
    overrides: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HardwareProfile":
        valid = {f.name for f in fields(cls)}
        clean = {k: v for k, v in (data or {}).items() if k in valid}
        clean.setdefault("overrides", {})
        return cls(**clean)


# ---------------------------------------------------------------------------
# Detection (stdlib only, all best effort)
# ---------------------------------------------------------------------------

def _total_ram_gb() -> float:
    """Total physical RAM in GiB, or 0.0 when undetectable."""
    try:
        if hasattr(os, "sysconf"):  # Linux / macOS
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            if pages and page_size:
                return round(pages * page_size / (1024 ** 3), 2)
    except (ValueError, OSError, AttributeError):
        pass

    if platform.system() == "Windows":
        try:  # pragma: no cover - platform specific
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return round(stat.ullTotalPhys / (1024 ** 3), 2)
        except Exception:
            pass
    return 0.0


def _nvidia_vram_gb() -> float:
    """Largest NVIDIA GPU VRAM in GiB via nvidia-smi, or 0.0."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return 0.0
    try:  # pragma: no cover - environment dependent
        out = subprocess.run(
            [exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        ).stdout
        values = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                values.append(float(line.split()[0]))
            except (ValueError, IndexError):
                continue
        return round(max(values) / 1024, 2) if values else 0.0
    except Exception:
        return 0.0


def detect_hardware() -> HardwareProfile:
    """Profile this machine. Never raises; falls back to the light tier."""
    ram = _total_ram_gb()
    vram = _nvidia_vram_gb()
    cores = os.cpu_count() or 1
    system = platform.system()
    machine = platform.machine().lower()

    if vram > 0:
        backend = "CUDA"
    elif system == "Darwin" and ("arm" in machine or machine in ("aarch64", "arm64")):
        backend = "Metal"
    else:
        backend = "CPU"

    tier = tier_for_hardware(ram, vram)
    profile = HardwareProfile(
        total_ram_gb=ram,
        vram_gb=vram,
        cpu_cores=cores,
        compute_backend=backend,
        tier=tier,
        os=system,
    )
    logger.info(
        "Hardware profile: %.1f GiB RAM, %.1f GiB VRAM, %d cores, %s -> %s tier",
        ram, vram, cores, backend, tier,
    )
    return profile


# ---------------------------------------------------------------------------
# Tier recommendations
# ---------------------------------------------------------------------------

_LEGACY_TIERS: dict[str, dict[str, Any]] = {
    "high": {
        "chat_model": "qwen2.5:7b",
        "vision_model": "qwen2.5vl:7b",
        "alternate_vision_model": "minicpm-v",
        "whisper_model": "small.en",
        "alternate_whisper_model": "base.en",
        "whisper_compute_type": "float16",
        "max_screen_dim": 1600,
    },
    "light": {
        "chat_model": "qwen2.5:3b",
        "vision_model": "qwen2.5vl:3b",
        "alternate_vision_model": "minicpm-v",
        "whisper_model": "tiny.en",
        "alternate_whisper_model": "base.en",
        "whisper_compute_type": "int8",
        "max_screen_dim": 1024,
    },
}

# Unified qwen3.5 tiers: one checkpoint serves chat and vision, plus a tiny
# text-only head for interrupt/intent routing. Workstation only needs the 27b
# unified checkpoint; the fast head is optional there.
_UNIFIED_TIERS: dict[str, dict[str, Any]] = {
    "light": {
        "chat_model": "qwen3.5:4b",
        "vision_model": "qwen3.5:4b",
        "fast_model": "qwen3.5:0.8b",
        "alternate_vision_model": "qwen2.5vl:3b",
        "whisper_model": "tiny.en",
        "alternate_whisper_model": "base.en",
        "whisper_compute_type": "int8",
        "max_screen_dim": 1024,
    },
    "high": {
        "chat_model": "qwen3.5:9b",
        "vision_model": "qwen3.5:9b",
        "fast_model": "qwen3.5:2b",
        "alternate_vision_model": "qwen2.5vl:7b",
        "whisper_model": "small.en",
        "alternate_whisper_model": "base.en",
        "whisper_compute_type": "float16",
        "max_screen_dim": 1600,
    },
    "workstation": {
        "chat_model": "qwen3.5:27b",
        "vision_model": "qwen3.5:27b",
        "fast_model": "qwen3.5:2b",
        "alternate_vision_model": "qwen3.5:9b",
        "whisper_model": "small.en",
        "alternate_whisper_model": "base.en",
        "whisper_compute_type": "float16",
        "max_screen_dim": 1920,
    },
}


def _tier_config(tier: str, family: str = UNIFIED_FAMILY) -> dict[str, Any]:
    """Return base model settings for a tier and checkpoint family."""
    unified = model_family(family) == UNIFIED_FAMILY
    if unified:
        base = dict(_UNIFIED_TIERS.get(tier, _UNIFIED_TIERS["high"]))
    else:
        # Legacy qwen2.5vl fallback: separate text and vision checkpoints.
        base = dict(_LEGACY_TIERS.get(tier, _LEGACY_TIERS["high"]))
        base["fast_model"] = ""
    cfg: dict[str, Any] = {"tier": tier, **base}
    cfg["model_family"] = UNIFIED_FAMILY if unified else LEGACY_FAMILY
    cfg["unified_multimodal"] = unified
    cfg["shared_model"] = shared_multimodal_model(
        cfg["chat_model"], cfg["vision_model"]
    ) if unified else None
    # Only one warm call when chat and vision share a checkpoint.
    cfg["warm_models"] = (
        [cfg["chat_model"]] if cfg["shared_model"] else [cfg["chat_model"], cfg["vision_model"]]
    )
    cfg["required_models"] = (
        [cfg["chat_model"], cfg["fast_model"]] if cfg.get("fast_model")
        else [cfg["chat_model"], cfg["vision_model"]]
    )
    return cfg


def recommend_config(profile: HardwareProfile | None = None) -> dict[str, Any]:
    """Map a hardware profile to concrete model + latency settings."""
    profile = profile or detect_hardware()
    family = os.getenv(ENV_MODEL_FAMILY) or profile.overrides.get(ENV_MODEL_FAMILY) or UNIFIED_FAMILY
    cfg = _tier_config(profile.tier, family)

    # CTranslate2 (faster-whisper) only accelerates on CUDA. Apple Metal and
    # CPU fall back to quantized int8 so the first run never fails to load.
    if profile.compute_backend == "CUDA":
        cfg["whisper_compute_type"] = "float16" if profile.tier == "high" else "int8_float16"
        cfg["whisper_device"] = "cuda"
    elif profile.compute_backend == "Metal" and profile.tier == "high":
        cfg["whisper_compute_type"] = "int8_float16"
        cfg["whisper_device"] = "cpu"
    else:
        cfg["whisper_compute_type"] = "int8"
        cfg["whisper_device"] = "cpu"

    cfg.update(
        compute_backend=profile.compute_backend,
        keep_alive=KEEP_ALIVE,
        total_ram_gb=profile.total_ram_gb,
        vram_gb=profile.vram_gb,
        cpu_cores=profile.cpu_cores,
    )
    return cfg


# ---------------------------------------------------------------------------
# Persistence + application
# ---------------------------------------------------------------------------

def load_profile() -> HardwareProfile | None:
    """Load a previously saved profile, or None on first run."""
    try:
        if PROFILE_PATH.exists():
            return HardwareProfile.from_dict(json.loads(PROFILE_PATH.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError):
        logger.debug("Could not load hardware profile", exc_info=True)
    return None


def save_profile(profile: HardwareProfile) -> None:
    """Persist a profile so settings can read/override it."""
    try:
        PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROFILE_PATH.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
    except OSError:  # pragma: no cover - disk permissions
        logger.debug("Could not save hardware profile", exc_info=True)


def configure_from_hardware(
    profile: HardwareProfile | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Detect hardware (or use a supplied profile) and apply recommended env.

    Resolution order for each setting: environment variable > profile override >
    recommendation. Persisting the profile lets the settings UI show what was
    chosen and let power users override individual values.
    """
    profile = profile or load_profile() or detect_hardware()
    cfg = recommend_config(profile)

    env_to_cfg = {
        ENV_CHAT_MODEL: "chat_model",
        ENV_VISION_MODEL: "vision_model",
        ENV_WHISPER_MODEL: "whisper_model",
        ENV_WHISPER_COMPUTE: "whisper_compute_type",
        ENV_WHISPER_DEVICE: "whisper_device",
        ENV_MAX_SCREEN_DIM: "max_screen_dim",
        ENV_KEEP_ALIVE: "keep_alive",
    }
    if cfg.get("fast_model"):
        env_to_cfg[ENV_FAST_MODEL] = "fast_model"

    for env_key, cfg_key in env_to_cfg.items():
        recommended = str(cfg[cfg_key])
        override = profile.overrides.get(env_key)
        # 1) explicit environment variable set by the user wins,
        # 2) a saved settings override wins over our recommendation,
        # 3) otherwise apply the recommended value.
        if env_key in os.environ:
            chosen = os.environ[env_key]
        elif override:
            chosen = override
            os.environ[env_key] = override
        else:
            chosen = recommended
            os.environ[env_key] = recommended
        if cfg_key == "max_screen_dim":
            try:
                chosen = int(chosen)
            except ValueError:
                chosen = cfg[cfg_key]
        cfg[cfg_key] = chosen

    if persist:
        save_profile(profile)
    return cfg


# ---------------------------------------------------------------------------
# Latency helpers
# ---------------------------------------------------------------------------

def downscale_png(png_bytes: bytes, max_dim: int) -> tuple[bytes, int, int]:
    """Downscale a PNG to fit within ``max_dim`` preserving aspect ratio.

    Uses LANCZOS resampling for readable UI text and returns ``(png, w, h)``.
    Callers keep working in normalized 0-1000 coordinates, so Set-of-Marks
    element mapping is unchanged by the resize.
    """
    from PIL import Image  # type: ignore

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    width, height = img.size
    if max_dim <= 0 or max(width, height) <= max_dim:
        return png_bytes, width, height

    scale = max_dim / max(width, height)
    new_w = max(1, int(width * scale))
    new_h = max(1, int(height * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), new_w, new_h


def prewarm_audio(speaker: Any | None = None) -> dict[str, bool]:
    """Import Kokoro and silero-vad up front, off the UI thread.

    Non-fatal: a missing optional dependency simply reports ``False``. The
    already-constructed speaker is nudged to resolve its Kokoro engine so the
    first spoken greeting does not stutter.
    """
    result = {"kokoro": False, "silero_vad": False}
    try:  # pragma: no cover - environment dependent
        if speaker is not None and hasattr(speaker, "_try_kokoro"):
            result["kokoro"] = bool(speaker._try_kokoro())
        if not result["kokoro"]:
            importlib = __import__("importlib")
            importlib.import_module("kokoro")
            result["kokoro"] = True
    except Exception:
        logger.debug("Kokoro prewarm skipped", exc_info=True)

    try:  # pragma: no cover - environment dependent
        __import__("importlib").import_module("silero_vad")
        result["silero_vad"] = True
    except Exception:
        logger.debug("silero-vad prewarm skipped", exc_info=True)

    return result
