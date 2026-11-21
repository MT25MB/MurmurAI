"""Standalone CLI voice loop test for Murmur AI.

Listens to your microphone, transcribes with faster-whisper, prints the
transcription, and speaks back an echo response using local TTS.

Usage:
    python backend/test_voice_loop.py

Press Ctrl+C to stop. Requires: sounddevice, webrtcvad2, faster-whisper,
kokoro (or pyttsx3/piper fallback).
"""

from __future__ import annotations

import logging
import signal
import sys
import time

from audio.listener import VoiceListener
from audio.speaker import LocalSpeaker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("murmur_ai.test")


def main() -> None:
    log.info("Murmur AI voice loop test — speaking into your mic…")
    log.info("Say something. I'll echo it back. Ctrl+C to quit.\n")

    speaker = LocalSpeaker(engine="auto")
    latest = {"text": ""}

    def on_utterance(text: str) -> None:
        latest["text"] = text.strip()
        print(f"\n>>> You said: {latest['text']}", flush=True)
        echo = f"You said: {latest['text']}"
        print(f"<<< Murmur AI: {echo}", flush=True)
        try:
            speaker.speak(echo)
        except Exception as exc:
            log.error("TTS failed: %s", exc)

    listener = VoiceListener(
        model_name="base.en",
        compute_type="int8",
        silence_ms=800,
        on_utterance=on_utterance,
    )

    stop = False

    def handle_sigint(signum, frame):
        nonlocal stop
        stop = True
        print("\n\nStopping…", flush=True)

    signal.signal(signal.SIGINT, handle_sigint)

    listener.start()
    try:
        while not stop:
            time.sleep(0.1)
    finally:
        listener.stop()
        speaker.interrupt()
        log.info("Bye.")


if __name__ == "__main__":
    main()
