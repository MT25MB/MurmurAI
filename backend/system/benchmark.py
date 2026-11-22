"""Reproducible, local-only latency benchmark for Murmur AI.

Every probe is best-effort: missing optional models/tools are reported as
skipped rather than failing the run. No microphone, display, or external
network is required (Ollama probes use the configured localhost endpoint only).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import platform
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("murmur_ai.system.benchmark")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
BENCHMARK_CHAT_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
BENCHMARK_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5-vl:7b")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base.en")


@dataclass
class BenchmarkResult:
    name: str
    cold_ms: Optional[float] = None
    warm_ms: Optional[float] = None
    status: str = "skipped"
    notes: str = ""

    def to_row(self) -> str:
        cold = "n/a" if self.cold_ms is None else f"{self.cold_ms:.0f}"
        warm = "n/a" if self.warm_ms is None else f"{self.warm_ms:.0f}"
        return f"| {self.name} | {cold} | {warm} | {self.status} | {self.notes} |"


@dataclass
class BenchmarkReport:
    created_at: str
    system: str
    hardware: dict[str, Any] = field(default_factory=dict)
    results: list[BenchmarkResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "system": self.system,
            "hardware": self.hardware,
            "results": [r.__dict__ for r in self.results],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def to_markdown(self) -> str:
        lines = [
            "# Murmur AI Benchmarks",
            "",
            f"Generated: {self.created_at}  ",
            f"System: {self.system}",
            "",
            "Local, offline-friendly measurements. Lower is better. Cold includes model "
            "construction; warm reuses the loaded model. `skipped` means the optional "
            "dependency/model was not available on this machine.",
            "",
            "## Hardware",
            "",
            "| Metric | Value |",
            "| --- | --- |",
        ]
        for key, value in self.hardware.items():
            lines.append(f"| {key.replace('_', ' ').title()} | {value} |")
        lines += [
            "",
            "## Latency",
            "",
            "| Benchmark | Cold (ms) | Warm (ms) | Status | Notes |",
            "| --- | --- | --- | --- | --- |",
        ]
        lines.extend(result.to_row() for result in self.results)
        lines += [
            "",
            "## Comparing platforms",
            "",
            "Run `python scripts/benchmark.py` on a CPU-only machine, Apple Silicon "
            "Mac, and an NVIDIA GPU box, then compare the table above. Keep the same "
            "model versions and `MURMUR_*` environment variables for a fair comparison.",
            "",
        ]
        return "\n".join(lines)


def _timed(action: Callable[[], Any]) -> float:
    start = time.perf_counter()
    action()
    return (time.perf_counter() - start) * 1000.0


def _skipped(name: str, reason: str) -> BenchmarkResult:
    return BenchmarkResult(name=name, status="skipped", notes=reason)


# ---------------------------------------------------------------------------
# Individual probes
# ---------------------------------------------------------------------------

def measure_whisper() -> BenchmarkResult:
    name = "faster-whisper transcription"
    try:
        import numpy as np
        from faster_whisper import WhisperModel  # type: ignore
    except Exception:
        return _skipped(name, "faster-whisper not installed")
    audio = np.zeros(16000, dtype=np.float32)

    def build():
        try:
            return WhisperModel(
                WHISPER_MODEL, compute_type="int8", device="cpu", local_files_only=True
            )
        except TypeError:
            return None

    model = build()
    if model is None:
        return _skipped(name, f"{WHISPER_MODEL} not cached offline")
    try:
        cold = _timed(lambda: model.transcribe(audio, language="en", beam_size=1))
        warm = _timed(lambda: model.transcribe(audio, language="en", beam_size=1))
        return BenchmarkResult(name, cold, warm, "ok", "1s synthetic silence")
    except Exception as exc:
        return _skipped(name, f"transcription failed: {exc}")


def _ollama_chat(payload: dict[str, Any]) -> None:
    import httpx

    with httpx.Client(timeout=12.0) as client:
        response = client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
        response.raise_for_status()


def measure_ollama_routing() -> BenchmarkResult:
    name = "Ollama tool-call routing"
    payload = {
        "model": BENCHMARK_CHAT_MODEL,
        "messages": [{"role": "user", "content": "Open notepad for me."}],
        "stream": False,
        "tools": [{
            "type": "function",
            "function": {
                "name": "open_application",
                "description": "Open an app.",
                "parameters": {
                    "type": "object",
                    "properties": {"app_name": {"type": "string"}},
                    "required": ["app_name"],
                },
            },
        }],
    }
    try:
        cold = _timed(lambda: _ollama_chat(payload))
        warm = _timed(lambda: _ollama_chat(payload))
        return BenchmarkResult(name, cold, warm, "ok", BENCHMARK_CHAT_MODEL)
    except Exception:
        return _skipped(name, "Ollama unreachable on localhost")


def _synthetic_screenshot() -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1280, 720), (15, 18, 24))
    draw = ImageDraw.Draw(image)
    for x in (40, 320, 600, 880):
        draw.rectangle([x, 100, x + 220, 180], fill=(220, 220, 230))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def measure_som() -> BenchmarkResult:
    name = "Set-of-Marks detection"
    try:
        from agent.som_overlay import annotate_screenshot
    except Exception:
        return _skipped(name, "SoM module unavailable")
    try:
        png = _synthetic_screenshot()
        cold = _timed(lambda: annotate_screenshot(png))
        warm = _timed(lambda: annotate_screenshot(png))
        return BenchmarkResult(name, cold, warm, "ok", "synthetic 1280x720 UI")
    except Exception as exc:
        return _skipped(name, f"detection failed: {exc}")


def measure_vlm_grounding() -> BenchmarkResult:
    name = "qwen2.5-vl screen grounding"
    payload = {
        "model": BENCHMARK_VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Which numbered box is a button? Reply JSON."},
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(_synthetic_screenshot()).decode()
                }},
            ],
        }],
        "stream": False,
        "format": "json",
    }
    try:
        cold = _timed(lambda: _ollama_chat(payload))
        warm = _timed(lambda: _ollama_chat(payload))
        return BenchmarkResult(name, cold, warm, "ok", BENCHMARK_VISION_MODEL)
    except Exception:
        return _skipped(name, "vision model unreachable on localhost")


def measure_kokoro_ttfa() -> BenchmarkResult:
    name = "Kokoro-82M time-to-first-audio"
    try:
        from kokoro import KModel, KPipeline  # type: ignore
    except Exception:
        return _skipped(name, "kokoro not installed")

    def synth(pipeline):
        for _, _, _audio in pipeline("Hello.", voice="af_heart", speed=1.0):
            break

    try:
        cold = _timed(lambda: synth(KPipeline(lang_code="a", model=KModel())))
        pipeline = KPipeline(lang_code="a", model=KModel())
        warm = _timed(lambda: synth(pipeline))
        return BenchmarkResult(name, cold, warm, "ok", "short phrase, first chunk")
    except Exception as exc:
        return _skipped(name, f"audio init failed: {exc}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all(probes: Optional[list[Callable[[], BenchmarkResult]]] = None) -> BenchmarkReport:
    """Run all probes and return a report. ``probes`` is injectable for tests."""
    from system.profiler import detect_hardware

    profile = detect_hardware().to_dict()
    hardware = {
        "compute_backend": profile.get("compute_backend"),
        "tier": profile.get("tier"),
        "total_ram_gb": profile.get("total_ram_gb"),
        "vram_gb": profile.get("vram_gb"),
        "cpu_cores": profile.get("cpu_cores"),
        "os": profile.get("os"),
    }
    probes = probes or [
        measure_whisper,
        measure_ollama_routing,
        measure_som,
        measure_vlm_grounding,
        measure_kokoro_ttfa,
    ]
    results = []
    for probe in probes:
        try:
            results.append(probe())
        except Exception as exc:  # never let one probe abort the run
            results.append(_skipped(probe.__name__, f"probe error: {exc}"))
    return BenchmarkReport(
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        system=platform.platform(),
        hardware=hardware,
        results=results,
    )
