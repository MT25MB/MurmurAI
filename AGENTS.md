# Murmur AI — Architecture & Agent Rules

Murmur AI is a free, open-source, **100% local** voice-controlled desktop agent for
Windows, macOS, and Linux. It starts with the user's computer, listens through the
microphone, talks back through local text-to-speech, and performs computer-control
tasks on the user's behalf. **No data leaves the machine. No paid APIs. Ever.**

This file is the source of truth for every coding agent and human contributor.

---

## 1. Stack (locked)

### Frontend / Shell
- **Tauri v2** (Rust shell), **React 19**, **TypeScript 5** (strict), **Vite 7**.
- **Tailwind CSS v4** via `@tailwindcss/vite`.
- Visual direction: **dark, high-contrast, minimal**. The shell is a **borderless,
  transparent, always-on-top floating HUD pill**, plus a **system tray icon**.
- **Brand mark:** the infinity logo in `logo.png` (navy `#1D3251`, OKLCH hue 258).
  Transparent tints live in `src/assets/logo-blue.png` (app) and
  `website/public/logo-{blue,navy}.png`; favicon + Tauri icons derive from it.
- **Locked palette** (identical tokens in app + website, measured contrast):
  obsidian `#080A0F`, surface `#10141B`, border `#2D333E`, ink `#F1F3F9`,
  muted `#A0A5AE`, blue accent `#5598F9` / fill `#156CDD` (white text 4.98:1),
  red accent `#F05653` / fill `#D01C29` (white text 5.41:1). Blue is derived
  from the logo hue; red is reserved for execution/alert states.
- Auto-start on boot via **`tauri-plugin-autostart`** (opt-in, user controlled).

### Backend Sidecar
- **Python 3.11+**, **FastAPI**, **uvicorn**, real-time over WebSocket at
  **`ws://127.0.0.1:8765/ws`**. Health check at `GET /health`.
- Bind to **`127.0.0.1` only** — never `0.0.0.0`.
- Organized as `audio/`, `agent/`, `tools/`, with `main.py` as the entry point.

### Local-only inference (zero paid APIs)
- **LLM:** Ollama (default local endpoint `http://127.0.0.1:11434`).
- **STT:** faster-whisper (local).
- **TTS:** Kokoro or Piper (local).
- **Computer control:** PyAutoGUI.
- Every one of these is an **optional runtime dependency** with a lazy import so the
  backend's `/health` and WebSocket control plane boot even when heavy models or
  system packages are not installed. Never add a cloud API key or paid endpoint.

---

## 2. Repository layout

```
Murmur AI/
├─ AGENTS.md                 # this file
├─ README.md
├─ .gitignore
├─ package.json              # frontend scripts + Tauri CLI
├─ tsconfig.json
├─ vite.config.ts
├─ index.html
├─ src/                      # React HUD
│  ├─ main.tsx
│  ├─ App.tsx
│  ├─ index.css
│  ├─ components/{HudPill.tsx,Waveform.tsx,OnboardingModal.tsx}
│  └─ lib/{websocket.ts,setup.ts}
├─ src-tauri/                # Rust shell
│  ├─ Cargo.toml
│  ├─ build.rs
│  ├─ tauri.conf.json
│  ├─ capabilities/default.json
│  ├─ icons/{icon.png,icon.ico}
│  └─ src/{main.rs,lib.rs}   # tray menu + Python sidecar spawn/kill
└─ backend/                  # Python sidecar
   ├─ pyproject.toml
   ├─ requirements.txt
   ├─ .env.example
   ├─ main.py                # FastAPI /health + /ws state machine
   ├─ test_voice_loop.py     # standalone mic->STT->echo-TTS CLI test
   ├─ audio/{__init__.py,listener.py,speaker.py}
   ├─ agent/{__init__.py,brain.py,state.py,vision_agent.py,som_overlay.py,app_knowledge.py,shortcuts.json}
   ├─ tools/{__init__.py,os_tools.py,safety.py,installer_tool.py,event_bus.py}
   ├─ setup.py               # first-run checks + model/weight download endpoints
   ├─ murmur-backend.spec   # PyInstaller onefile sidecar spec
   └─ logs/                  # visual-agent step replay (screenshots + JSON)

First-run setup (`setup.py`): checks Ollama at localhost:11434, required models
(qwen2.5:7b, qwen2.5-vl:7b), auto-downloads whisper/kokoro weights into
~/.murmur-ai/models/, and exposes /setup/* endpoints + a /setup/pull-model WS
that streams Ollama pull progress. The React OnboardingModal shows this instead
of the HUD until setup is complete.

Distribution: `murmur-backend.spec` builds a onefile sidecar named with Tauri's
target triple into src-tauri/binaries/ (registered as `externalBin`). The Rust
shell launches it in release builds and falls back to `python main.py` in dev.
`.github/workflows/release.yml` builds the sidecar + Tauri app on Windows/macOS/
Linux and publishes draft GitHub Releases.

`tools/installer_tool.py` installs apps via native silent package managers
(winget/choco/brew/flatpak/snap/apt/dnf/pacman). It emits `CONFIRMATION_REQUIRED`
and `progress` WebSocket events through `tools/event_bus.py`, blocks until the
user approves, and hands off to `vision_agent.py` when no CLI package is found.
```

---

## 3. Non-negotiable rules

### Safety first
1. **Any destructive shell command or file deletion requires explicit confirmation**
   (spoken "yes/confirm" or a UI approval) through `tools/safety.py::SafetyGate`
   **before** execution. No exceptions, no silent auto-approval.
2. The agent must describe the exact action, target, and blast radius in the
   confirmation request.
3. Denied or timed-out confirmations are treated as **no**.
4. Keep a human-readable audit log of every tool invocation and its decision.

### Local-first / privacy
5. No telemetry, analytics, crash reporting, or network calls to third parties.
6. The only network listeners are `127.0.0.1:8765` (backend) and local Ollama. The
   only outbound calls are to `127.0.0.1` services.
7. Audio, transcripts, and conversations stay in memory or on disk locally, and the
   user can clear them at any time.

### Engineering
8. TypeScript is `strict`; Python targets 3.11+ with type hints where practical.
9. Heavy/optional dependencies (`faster-whisper`, `kokoro`, `piper`, `pyautogui`,
   `sounddevice`, `ollama`) are **lazy-imported** behind small interfaces so the
   control plane always starts. A missing optional dependency produces a clear,
   actionable error — never a silent failure.
10. WebSocket messages use a typed, versioned JSON protocol defined in
    `backend/agent/state.py`. Unknown message types are rejected, not guessed.
11. Keep the HUD responsive: no blocking work on the UI thread; stream state over the
    WebSocket and reconcile in React.
12. Respect the user: no always-listening indicator deceptions, no hiding
    destructive actions, and a visible, obvious mic/mute state in the HUD.

---

## 4. Commands

```bash
# Frontend
npm install
npm run dev            # Vite dev server on http://127.0.0.1:1420
npm run build          # tsc + vite build -> dist/
npm run tauri dev      # Tauri shell + frontend (requires Rust)

# Backend
python -m venv backend/.venv
backend/.venv/Scripts/Activate.ps1   # Windows (or source on macOS/Linux)
pip install -e backend
python backend/main.py               # FastAPI + WS on 127.0.0.1:8765
curl http://127.0.0.1:8765/health
```

---

## 5. Definition of done for any change
- Frontend: `npm run build` passes with no TypeScript errors.
- Backend: `python backend/main.py` starts and `/health` returns `status: ok`.
- Any new destructive capability goes through `SafetyGate` and has a test.
- No new third-party network dependency or paid API.
