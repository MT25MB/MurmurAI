"""Confidence banding for local ASR segments.

faster-whisper exposes per-segment `avg_logprob` and `no_speech_prob`. Murmur
uses them to decide whether a transcription is reliable enough to act on
without asking the user to confirm.
"""

from __future__ import annotations

from typing import Any, Iterable


def confidence_from_segments(segments: Iterable[Any]) -> tuple[str, float]:
    """Return (band, score) for a set of ASR segments.

    Score is a 0..1 heuristic: log probability is mapped via a sigmoid-like
    curve and reduced by the no-speech probability.
    """
    rows = list(segments)
    if not rows:
        return "low", 0.0
    logprobs: list[float] = []
    no_speech: list[float] = []
    for segment in rows:
        value = getattr(segment, "avg_logprob", None)
        if value is None and isinstance(segment, dict):
            value = segment.get("avg_logprob")
        try:
            logprobs.append(float(value))
        except (TypeError, ValueError):
            pass
        ns = getattr(segment, "no_speech_prob", None)
        if ns is None and isinstance(segment, dict):
            ns = segment.get("no_speech_prob")
        try:
            no_speech.append(float(ns))
        except (TypeError, ValueError):
            pass
    if not logprobs:
        return "low", 0.0
    avg = sum(logprobs) / len(logprobs)
    ns_avg = sum(no_speech) / len(no_speech) if no_speech else 0.0
    score = 1.0 / (1.0 + max(0.0, -avg) * 0.8)
    score = max(0.0, min(1.0, score * (1.0 - max(0.0, min(1.0, ns_avg)))))
    if score >= 0.7:
        return "high", round(score, 3)
    if score >= 0.4:
        return "medium", round(score, 3)
    return "low", round(score, 3)
