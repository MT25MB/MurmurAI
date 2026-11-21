<div align="center">

<img src="website/public/logo-blue.png" alt="Murmur AI" width="120" />

# Murmur AI

**Eyes-free, hands-free computing. A 100% local, zero-cost AI desktop agent that sees your screen, describes what's happening, and operates any software through natural conversation.**

[![License: MIT](https://img.shields.io/badge/License-MIT-156CDD?style=for-the-badge)](LICENSE)
[![Platforms](https://img.shields.io/badge/Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=for-the-badge)](#installation)
[![Accessibility](https://img.shields.io/badge/Built%20for%20Blind%20%26%20Low--Vision%20Users-894CFF?style=for-the-badge)](#built-for-eyes-free-independence)
[![100% Local](https://img.shields.io/badge/100%25%20Local%20%26%20Offline-D01C29?style=for-the-badge)](#architecture)

**[Download the latest release](https://github.com/MT25MB/MurmurAI/releases/latest)** ·
**[Website & docs](https://MT25MB.github.io/MurmurAI/)** ·
**[Contributing](#contributing)**

</div>

---

Murmur AI is a free, open-source desktop companion designed to give blind, visually impaired, and hands-free users full autonomy over their computers. Launching automatically at boot, it combines local speech recognition, natural neural voices, and a real-time Vision-Language Model (VLM) to bridge the gap where traditional screen readers stop — letting you navigate visually dense software, install applications, manage files, and ask *"What is on my screen right now?"* entirely by voice.

No cloud subscriptions. No API keys. No telemetry. Everything runs on your machine.

---

## Built for Eyes-Free Independence

Traditional screen readers (like NVDA, VoiceOver, and Orca) depend on software developers properly labeling every UI element in an OS accessibility tree. When an application lacks accessibility tags, or relies on dense visual viewports, timelines, and custom canvases, blind users are often locked out.

Murmur AI solves this using **Multimodal Visual Grounding**:

* **Navigate Unlabeled & Complex Interfaces:** Uses live screen capture and Set-of-Marks visual detection to see buttons, menus, timelines, and icons in applications like **Blender**, **DaVinci Resolve**, and web apps, clicking and typing on your behalf.
* **On-Demand Visual Context:** Ask *"What's on my screen?"*, *"Did that download finish?"*, or *"Read the error dialog"* to get concise, spoken descriptions of visual UI states, pop-ups, and layouts.
* **Zero-Touch Startup & Conversational Control:** Starts at boot and listens continuously via local Voice Activity Detection (`webrtcvad`, with optional Silero), no hunting for push-to-talk keys. You can interrupt the AI mid-sentence anytime just by speaking.
* **Spoken Safety Confirmations:** Before running destructive commands, deleting files, or installing software, Murmur AI reads the exact action aloud and waits for your verbal *"Yes"* before proceeding.

---

## Core Capabilities

* **Natural Two-Way Voice Loop:** Pairs local VAD and `faster-whisper` (STT) with `Kokoro-82M` (TTS) for low-latency, human-sounding speech synthesis with instant barge-in interruption.
* **Set-of-Marks (SoM) Visual Agent:** Captures screen frames (`mss`), identifies interactive controls via OpenCV and OS accessibility APIs, draws numbered boxes on the image, then executes precise mouse/keyboard actions (`pyautogui`) driven by a local vision model (`qwen2.5-vl:7b`).
* **Smart Shortcut Execution:** Detects the active foreground application and applies its native keyboard shortcuts automatically for faster, more reliable navigation.
* **Voice-Driven App Installation:** Say *"Install VLC"* or *"Install Blender"* and Murmur AI handles installation silently through native package managers (`winget`, `brew`, `flatpak`, `snap`, `apt`, `dnf`, `pacman`), falling back to visual browser navigation if needed.

---

## Architecture

Murmur AI runs a lightweight **Tauri v2** (Rust + React/TypeScript) desktop shell paired with a bundled local Python sidecar over WebSockets (`ws://127.0.0.1:8765`).

```text
 [ Microphone ] ──► webrtcvad + Faster-Whisper (local STT)
                          │
                          ▼
              Ollama ReAct Brain (qwen2.5:7b)
              ┌───────────┴────────────┐
              ▼                        ▼
   Native OS & CLI Tools      Set-of-Marks Vision Loop
   (winget/brew/files)        (mss + OpenCV + qwen2.5-vl:7b)
              │                        │
              └───────────┬────────────┘
                          ▼
             Kokoro-82M TTS ──► [ Speakers ]
```

- **Frontend:** Tauri v2 shell, React + TypeScript + Tailwind, transparent HUD pill + tray icon
- **Backend:** Python 3.11 FastAPI sidecar with a typed WebSocket state machine (`IDLE → LISTENING → THINKING → SPEAKING`)
- **Inference:** Ollama — `qwen2.5:7b` for voice/tool chat, `qwen2.5-vl:7b` for screen vision
- **Voice:** faster-whisper (`base.en`, `int8`) and Kokoro-82M (with Piper / pyttsx3 fallbacks)
- **Local cache:** models and weights live in `~/.murmur-ai/models/`
- **Privacy:** the only network listeners are `127.0.0.1:8765` and local Ollama at `127.0.0.1:11434`; there is no third-party egress

Full architecture rules live in [AGENTS.md](AGENTS.md).

---

## Installation

Download the installer for your platform from the **[latest release](https://github.com/MT25MB/MurmurAI/releases/latest)**:

| Platform | Installers |
| --- | --- |
| Windows | `.msi`, `.exe` |
| macOS | `.dmg` (Apple Silicon) |
| Linux | `.AppImage`, `.deb` |

Every installer is built from source by GitHub Actions in `.github/workflows/release.yml`.

---

## Quick start

1. **Install [Ollama](https://ollama.com).** The first-run setup card detects it and offers a one-click install if missing.
2. **Pull the two local models.** The setup card does this with live progress, or run it manually:

   ```bash
   ollama pull qwen2.5:7b
   ollama pull qwen2.5-vl:7b
   ```

3. **Grant OS permissions.** macOS: Accessibility + Screen Recording. Linux: X11 (XTest) or a Wayland portal. Windows: none required.
4. **Start talking.** Try *"Install Blender"*, *"What's on my screen?"*, or *"Open DaVinci and import the clips"*.

First launch also caches Whisper and Kokoro weights into `~/.murmur-ai/models/`.

---

## Hardware requirements

| Requirement | Minimum | Recommended |
| --- | --- | --- |
| OS | Windows 10, macOS 12, Linux (X11/Wayland) | Latest |
| CPU | 4 cores with AVX2 | 8 cores |
| RAM | 8 GB | 16 GB+ |
| Storage | ~8 GB free for models and weights | 20 GB SSD |
| GPU | Not required — CPU inference works | NVIDIA or Apple Silicon for lower latency |
| Microphone | Any input device | Noise-cancelling |

---

## Privacy by design

* No cloud inference, no paid APIs, no analytics, no crash reporting.
* Audio, transcripts, and screenshots stay in memory or on your local disk.
* Destructive actions always require explicit confirmation — spoken or via the HUD.
* You can clear local state at any time.

---

## Development

```bash
# App
npm install && npm run tauri dev

# Backend
cd backend && python -m venv .venv && pip install -r requirements.txt && python main.py
# verify: curl http://127.0.0.1:8765/health

# Website
cd website && npm install && npm run dev
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for ground rules and the definition of done.

---

## Contributing

Contributions are welcome, especially improvements to accessibility, visual grounding, and support for more applications. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. By contributing you agree that your work is licensed under the MIT License.

## License

[MIT](LICENSE) © Murmur AI contributors.

<div align="center"><sub>Built for people who want an assistant, not a data pipeline.</sub></div>
