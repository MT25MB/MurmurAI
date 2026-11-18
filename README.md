# Murmur AI

**Eyes-free, hands-free computing. A 100% local, zero-cost AI desktop agent that sees your screen, describes what's happening, and operates any software through natural conversation.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platforms](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](#installation)
[![Accessibility](https://img.shields.io/badge/Accessibility-Built%20for%20Blind%20%26%20Low--Vision%20Users-purple.svg)](#built-for-eyes-free-independence)
[![100% Local](https://img.shields.io/badge/Privacy-100%25%20Local%20%26%20Offline-success.svg)](#architecture)

Murmur AI is a free, open-source desktop companion designed to give blind, visually impaired, and hands-free users full autonomy over their computers. Launching automatically at boot, it combines local speech recognition, natural neural voices, and a real-time Vision-Language Model (VLM) to bridge the gap where traditional screen readers stop allowing you to navigate visually dense software, install applications, manage files, and ask *"What is on my screen right now?"* entirely by voice.

No cloud subscriptions. No API keys. No telemetry.

---

## Built for Eyes-Free Independence

Traditional screen readers (like NVDA, VoiceOver, and Orca) depend on software developers properly labeling every UI element in an OS accessibility tree. When an application lacks accessibility tags, or relies on dense visual viewports, timelines, and custom canvases, blind users are often locked out.

Murmur AI solves this using **Multimodal Visual Grounding**:
* **Navigate Unlabeled & Complex Interfaces:** Uses live screen capture and Set-of-Marks visual detection to see buttons, menus, timelines, and icons in applications like **Blender**, **DaVinci Resolve**, and web apps, clicking and typing on your behalf.
* **On-Demand Visual Context:** Ask *"What's on my screen?"*, *"Did that download finish?"*, or *"Read the error dialog"* to get concise, spoken descriptions of visual UI states, pop-ups, and layouts.
* **Zero-Touch Startup & Conversational Control:** Starts at boot and listens continuously via local Voice Activity Detection (`silero-vad`), no hunting for push-to-talk keys. You can interrupt the AI mid-sentence anytime just by speaking.
* **Spoken Safety Confirmations:** Before running destructive commands, deleting files, or installing software, Murmur AI reads the exact action aloud and waits for your verbal *"Yes"* before proceeding.

---

## Core Capabilities

* **Natural Two-Way Voice Loop:** Pairs `silero-vad` and `faster-whisper` (STT) with `Kokoro-82M` (TTS) for low-latency, human-sounding speech synthesis with instant barge-in interruption.
* **Set-of-Marks (SoM) Visual Agent:** Captures screen frames (`mss`), identifies interactive controls via OpenCV and OS accessibility APIs, and executes precise mouse/keyboard actions (`pyautogui`) driven by local vision models (`qwen2.5-vl:7b`).
* **Smart Shortcut Execution:** Detects the active foreground application and applies native keyboard shortcuts automatically for faster, more reliable navigation.
* **Voice-Driven App Installation:** Say *"Install VLC"* or *"Install Blender"* and Murmur AI handles installation silently through native package managers (`winget`, `brew`, `flatpak`, `apt`, `dnf`, `pacman`), falling back to visual browser navigation if needed.

---

## Architecture

Murmur AI runs a lightweight **Tauri v2** (Rust + React/TypeScript) desktop shell paired with a bundled local Python sidecar over WebSockets (`ws://127.0.0.1:8765`).

```text
[ Microphone ] ──► Silero VAD + Faster-Whisper (Local STT)
                         │
                         ▼
               Ollama Tool & ReAct Brain (qwen2.5:7b)
               ┌─────────┴─────────┐
               ▼                   ▼
     Native OS & CLI Tools   Set-of-Marks Vision Loop (qwen2.5-vl:7b)
    (winget/brew/files)     (mss + OpenCV + PyAutoGUI)
               │                   │
               └─────────┬─────────┘
                         ▼
             Kokoro-82M TTS ──► [ Speakers ]
