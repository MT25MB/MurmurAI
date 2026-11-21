"""Local system profiling, latency optimization, settings and diagnostics."""

from .profiler import (
    HardwareProfile,
    configure_from_hardware,
    detect_hardware,
    downscale_png,
    prewarm_audio,
    recommend_config,
)
from .diagnostics_bundle import (
    DIAGNOSTICS_TOOLS,
    build_manifest,
    export_diagnostics,
    sanitize_config,
    sanitize_value,
)
from .settings_tools import (
    SETTINGS_TOOLS,
    apply_settings,
    handle_voice_command,
    load_settings,
    run_diagnostics,
    settings_summary,
    update_settings,
)

__all__ = [
    "HardwareProfile",
    "detect_hardware",
    "recommend_config",
    "configure_from_hardware",
    "downscale_png",
    "prewarm_audio",
    "DIAGNOSTICS_TOOLS",
    "build_manifest",
    "export_diagnostics",
    "sanitize_config",
    "sanitize_value",
    "SETTINGS_TOOLS",
    "apply_settings",
    "handle_voice_command",
    "load_settings",
    "run_diagnostics",
    "settings_summary",
    "update_settings",
]
