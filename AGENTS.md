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
- Audio coexistence: `audio/echo_guard.py` suppresses the listener and wake
  word while `audio/speaker.py` is playing TTS plus a 250ms tail (configurable
  `echo_guard`, `echo_guard_tail_ms`, optional `loopback_guard` /
  `MURMUR_LOOPBACK_DEVICE`). `audio/media_duck.py` lowers system media while
  speaking when `media_ducking` is on. `screen_reader_friendly` suppresses
  redundant chimes. "Be quiet" / "Stop talking" (voice, Q key, or Ctrl/Cmd+Shift+Q)
  call `speaker.interrupt()` immediately.
- Voice-controlled settings + diagnostics live in `system/settings_tools.py`.
  Preferences persist in `~/.murmur-ai/config.json` (speech rate, voice,
  chimes, description verbosity, listening mode, mic threshold, chat/vision
  models, `clear_data_on_uninstall`) and are applied to the live speaker/listener/brain at startup and on
  change. Voice commands are matched locally before the brain: "speak faster",
  "change your voice", "turn chimes off", "switch to detailed screen
  descriptions", "switch to wake-word mode", "increase mic threshold", "switch
  vision model to X", "show current models". `run_diagnostics` checks the
  microphone, Ollama, local models, OS permissions and Wayland/X11 session and
  speaks a plain-English report with "fix permissions"/"restart Ollama" offers.
  The React `SettingsDrawer` (Ctrl/Cmd+, or tray menu) edits the same file over
  `GET/POST /settings`, `/settings/reset` and `/diagnostics`, with full ARIA.
- Hands-free updates via **`tauri-plugin-updater`**: Rust commands
  `check_for_updates()` / `install_update()` read
  `https://github.com/MT25MB/MurmurAI/releases/latest/download/latest.json`.
  The HUD relays a discovered release to the Python sidecar over WebSocket;
  the backend speaks the version + release summary and asks "Would you like me
  to download and restart to install it?" Yes/no (spoken or clicked) resolves
  through `main.py` and calls the install command. Offline/unverified checks
  are reported as info, never as an update prompt.
- Release signing: set repository secrets `TAURI_SIGNING_PRIVATE_KEY` and
  `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`; the matching public key is in
  `src-tauri/tauri.conf.json` under `plugins.updater.pubkey`. `tauri-action`
  signs artifacts and publishes `latest.json` on every `v*` tag.

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

### Hardware profiling & latency (first class)
- `system/profiler.py` detects RAM, VRAM (nvidia-smi), CPU cores, and compute
  backend (CUDA / Apple Metal / CPU) and picks a model tier on startup:
  - **High (16GB+ RAM or 6GB+ VRAM):** `qwen2.5:7b` + `qwen2.5-vl:7b`,
    `small.en` whisper (`float16`/`int8_float16`).
  - **Light (8–12GB RAM, no GPU):** `qwen2.5:3b` + `qwen2.5-vl:3b` (or
    `minicpm-v`), `tiny.en` whisper (`int8`).
- Chosen profile is saved to `~/.murmur-ai/hardware_profile.json`; settings/env
  overrides always win (`OLLAMA_MODEL`, `OLLAMA_VISION_MODEL`, `WHISPER_MODEL`,
  `WHISPER_COMPUTE_TYPE`, `WHISPER_DEVICE`, `MURMUR_MAX_SCREEN_DIM`,
  `OLLAMA_KEEP_ALIVE`).
- Ollama chat + vision calls send `keep_alive: "30m"` and are warmed at startup
  via `/api/generate` so consecutive commands avoid cold model reloads.
- 4K/high-DPI screenshots are downscaled with LANCZOS before base64 encoding
  (aspect preserved, SoM stays in normalized 0-1000 coords) using the tier's
  `MURMUR_MAX_SCREEN_DIM` cap.
- Kokoro and silero-vad are imported in a background thread at startup so the
  first spoken greeting does not stutter.

### Accessibility (first-class)
- `describe_screen(focus)` in `agent/vision_agent.py` captures the screen and
  queries the VLM with a blind-optimized prompt, then speaks the result through
  `audio/speaker.py` (shared via `audio/speaker_provider.py`).
- `CONFIRMATION_REQUIRED` events are spoken aloud with the exact action and
  verbal choices ("yes, confirm" / "no, cancel"); verbal responses are parsed in
  `main.py::_try_verbal_confirmation` alongside UI/Enter/Escape approval.
- `system/diagnostics_bundle.py` builds a privacy-safe zip on the Desktop (or
  `~/.murmur-ai/diagnostics/`) with recent local logs, hardware/OS profile,
  localhost Ollama status and sanitized config. Secrets, credentials, custom
  paths, env values and user identifiers are redacted. The `export_diagnostics`
  tool speaks the exact archive path for attaching to a GitHub issue.
- `scripts/smoke-test.sh` / `.ps1` (via `scripts/smoke_check.py`) verify frontend
  and sidecar artifacts, brain tool schemas, a localhost-only sidecar startup,
  `/health`, `/setup/status` and the `/ws` handshake. `verify-all` runs it as
  its final step. No microphone or external network is needed.
- `audio/earcons.py` synthesizes stereo action cues with numpy/sounddevice:
  equal-power panning by screen X, pitch shifted by screen Y, plus distinct
  `wake_up`/`sleep`/`action_success`/`confirmation_needed`/`error_recovery`
  chimes. `ScreenController` plays a cue before click/drag; config key
  `spatial_audio_cues` (voice: "turn spatial audio cues off") mutes them.
- `packaging/` holds WinGet/Homebrew/Linux manifest templates with `{{VERSION}}`
  and `{{*_SHA256}}` placeholders. `scripts/sync_packaging.py` (called by the
  release workflow's `package-sync` job) fills them from downloaded release
  assets and attaches `SHA256SUMS.txt` to the release, then commits the updated
  manifests to main.
- `scripts/benchmark.py` runs the local-only latency harness from
  `system/benchmark.py` (Whisper, Ollama tool routing, SoM, VLM grounding,
  Kokoro TTFA) and writes `BENCHMARKS.md` for CPU/Apple Silicon/NVIDIA comparison.
  `scripts/demo.py --demo` and the "start tutorial" voice command run a four-step
  eyes-free practice sandbox that never modifies files or settings.
- `.github/ISSUE_TEMPLATE/` has YAML forms for bug reports (with "Export
  diagnostics" zip instructions), accessibility feedback and shortcut profile
  requests; `.github/PULL_REQUEST_TEMPLATE.md` tracks verification and a11y.
- `audio/pronunciation.py` normalizes spoken text before TTS using a user-editable
  `~/.murmur-ai/pronunciations.json` (GUI→gooey, sudo→soo-doo, Ctrl→Control,
  bpy→B-P-Y, VRAM→V-ram, plus accessibility/dev terms). Voice: "pronounce X as Y".
  `audio/voice_profiles.py` switches named profiles (default/clear/fast/quiet);
  "clear" is screen-reader tuned. `main.py` emits clean `transcript` WS messages
  for every reply/action summary, rendered by `TranscriptStream.tsx` in a
  dedicated polite live log for screen readers and refreshable Braille.
- `tools/file_tools.py` adds local file search (`mdfind`/Windows Search with a
  scandir fallback and ignore list), spoken document reading for txt/md/pdf/docx
  (pypdf, python-docx), and move/copy/rename batch tools. Overwrites always go
  through `tool_bus.request_confirmation`; no tool deletes files.
- `tools/context_tools.py` provides local clipboard access (pyperclip with
  native fallbacks) and recent-file inspection (Downloads/Desktop/Documents or
  an explicit path) with spoken size/type/age summaries. `SessionState.context`
  remembers the last mentioned file/app and clipboard text so "this"/"it"/
  "what's copied" resolve locally before a model call; voice phrases for
  clipboard questions and "copy that result to my clipboard" are handled
  deterministically in `main.py`.
- `tools/mcp_manager.py` is a stdlib JSON-RPC stdio MCP client. It reads
  `~/.murmur-ai/mcp_servers.json` (`command`/`args`/`env` per server), connects
  on startup, discovers tools via `tools/list`, and injects their schemas into
  `agent.brain.ALL_TOOLS` as `mcp__<server>__<tool>`. Tools that write files,
  use the network, or run system actions require `tool_bus.request_confirmation`
  unless the server's `allowlist` contains that tool. Voice phrases: "what
  plugins are active" and "reload my plugins".
- `tools/browser_tool.py` provides accessibility-first web automation via local
  Playwright (attaches to the user's Chrome over CDP at `localhost:9222`, or
  launches Chromium). Tools: `open_url` (URLs or private DuckDuckGo/Startpage
  search, no API key), `read_page_summary` (headings, main article text, form
  fields, buttons/links; nav clutter stripped for spoken narration),
  `click_web_element` and `fill_web_field` (accessible-name/label locators, no
  pixel coordinates). Requires `pip install playwright && playwright install chromium`.
  **Routing rule:** prefer browser tools for websites, articles, web search and
  online forms; reserve `vision_agent.py` for native desktop apps (Blender,
  DaVinci Resolve, OS dialogs) and canvas-heavy web apps.
- Toggleable earcons (`audio/speaker.py::chime`) give short tones for
  listening/thinking/speaking/confirmation/error (`MURMUR_AI_EARCONS=1`).
- **Offline wake word + sleep/wake states** (`audio/wake_word.py`): 100% local
  detector (`openwakeword`, or silero-vad + tiny `faster-whisper` keyword gate
  fallback). Two listening modes: **active** (default continuous VAD with
  barge-in) and **sleep/standby** (`SLEEPING` state, wake-word only, ignores room
  audio). Say "go to sleep" / "stop listening" / "pause murmur" to enter standby;
  say "hey murmur" / "wake up murmur" to wake (ascending chime + "I'm listening").
  Spoken `set_listening_mode` and `SLEEPING` WS messages keep HUD and tray in sync.
  Tauri global hotkey **Ctrl/Cmd+Shift+Space** toggles standby and announces the
  change aloud for screen-reader/keyboard users (HUD sleep button is the fallback).
- HUD + onboarding use ARIA roles, polite/assertive live regions,
  `role=progressbar`/`meter`, keyboard shortcuts (M mute, Enter approve,
  Escape cancel), and 3px high-contrast focus rings.

### Visual agent planning, loop recovery & abort
- `agent/task_plan.py` decomposes multi-step goals into ordered subgoals
  (LLM with deterministic comma/list fallback); only the active subgoal and a
  bounded `format_history()` (last 6 steps, brief outcomes) go to the VLM.
- `agent/loop_detector.py` fingerprints actions + average-hash screenshots;
  repeated actions or static screens on the same subgoal trigger recovery:
  first an alternative-path hint (shortcut/menu), then a spoken
  `guidance_required` question via the event bus (or graceful abort on timeout).
- `agent/abort.py` is a shared thread-safe `abort_controller`. PyAutoGUI's corner
  failsafe, the `stop_automation` tool, dedicated spoken phrases ("stop
  automation"/"abort task"), and the HUD Stop button all abort the loop, clear
  pending actions, and announce "Automation stopped" via `automation_stopped`.
- New WS messages: `guidance_required`/`guidance_response`, `automation_stopped`,
  `abort_automation`.

---

### Agent/tool loop discipline (Capri-inspired)
- Approvals are single-use and bound to one exact request: only one may be held, a
  "yes" cannot be replayed, and unrelated speech drops the held action
  (`tools/event_bus.py`). Spoken yes/no is ignored while `audio/echo_guard.py`
  reports echo; physical stop phrases always abort.
- Tool output is fenced as untrusted data (12K cap) and code-owned safety is the
  final system-prompt block; override-style lines in plugin descriptions are
  stripped before their schemas reach the brain (`agent/prompt_guard.py`).
- The brain never claims an action unless a tool actually ran
  (`guard_unverified_claim`), and Ollama's context window starts from RAM/VRAM
  and grows once on an overflow (override: `MURMUR_CONTEXT_WINDOW`).
- A fast local head handles stop/status mid-job without a model call
  (`agent/mid_job.py`). Screen questions stay on the brain's `describe_screen`
  tool path, which reports missing vision dependencies cleanly.
- MCP plugins support per-tool `always`/`ask`/`off` modes and a payload-free
  decision audit at `~/.murmur-ai/logs/tool_audit.jsonl`; idle servers stop after
  10 minutes. Declarative look-up recipes (`~/.murmur-ai/tool_recipes.json`) are
  HTTPS-GET-only, domain-allowlisted and start disabled until reviewed.
- Optional extra providers are strictly loopback OpenAI-compatible endpoints
  named by `MURMUR_LOCAL_ENDPOINT`; Ollama remains the default. No cloud keys.
- Uninstall data policy: keeping data is the default. `clear_data_on_uninstall`
  is opt-in via settings or voice, and `scripts/uninstall_cleanup.py` removes
  only an explicit allowlist of local data (never model weights). It is a dry
  run unless `--apply` is passed; OS installers do not invoke it automatically.

### v1.1.0 perception and speech upgrades (clean-room study applied)
- Streamed replies are split at sentence boundaries (`audio/streaming.py`) and
  delivered through a priority queue (`audio/speech_queue.py`): normal narration
  queues, urgent confirmations/errors preempt once, and barge-in drops only
  interruptible pending items. `Brain.stream_sentences` consumes Ollama tokens
  as they arrive; long replies and screen descriptions speak sentence by sentence.
- Native accessibility trees (`tools/a11y_tree.py`, UIA/AT-SPI/AX with graceful
  fallback) are the fast path for named controls; the brain can call
  `list_a11y_controls` and the VLM receives a bounded a11y table. Canvas-heavy
  apps still use Set-of-Marks + the VLM.
- Set-of-Marks uses a compact token-efficient manifest (`agent/som_manifest.py`)
  with one shared ID space, contained-duplicate merging and geometry in a side
  map, so small 7B VLMs stay fast. Post-action verification
  (`agent/screen_diff.py`) makes "no change" explicit and feeds alternative-path
  recovery when a click leaves the screen static.
- Declarative `.murmur-skill` packs (`skills/`) carry only hotkeys, terminology
  and prompt context, reject executable fields and injection text, and ship
  built-ins for Blender, DaVinci Resolve and VS Code. Tauri
  `check_os_permissions` reports mic/screen/accessibility status through `/health`
  and speaks plain-language recovery steps.

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
│  ├─ components/{HudPill.tsx,Waveform.tsx,OnboardingModal.tsx,SettingsDrawer.tsx,TranscriptStream.tsx}
│  ├─ lib/{websocket.ts,setup.ts,settings.ts,updater.ts}
│  └─ components/*.test.tsx    # Vitest + Testing Library (41 tests)
├─ src-tauri/                # Rust shell
│  ├─ Cargo.toml
│  ├─ build.rs
│  ├─ tauri.conf.json
│  ├─ capabilities/default.json
│  ├─ icons/{icon.png,icon.ico}
│  └─ src/{main.rs,lib.rs}   # tray menu + Python sidecar spawn/kill
├─ scripts/                  # verify-all, smoke-test, benchmark, demo, prepare-sidecar
├─ tests/e2e/                # headless synthetic voice-to-action E2E harness
├─ BENCHMARKS.md             # generated local latency table
├─ packaging/                # WinGet, Homebrew Cask, Linux desktop/AppStream templates
└─ backend/                  # Python sidecar
   ├─ pyproject.toml
   ├─ requirements.txt
   ├─ .env.example
   ├─ main.py                # FastAPI /health + /ws state machine
   ├─ test_voice_loop.py     # standalone mic->STT->echo-TTS CLI test
   ├─ tests/                 # 542 pytest tests: audio/VAD/STT/TTS, agent tools
   │                         #   + ReAct + installer + confirmations, vision/SoM,
   │                         #   WS state machine + setup, safety, planning/abort
   │                         #   (see test_agent_tools.py, test_vision.py,
   │                         #    test_server_setup.py, test_profiler.py,
   │                         #    test_browser_tool.py, test_updates.py,
   │                         #    test_mcp_manager.py, test_context_tools.py,
   │                         #    test_diagnostics_bundle.py, test_file_tools.py,
   │                         #    test_pronunciation.py, test_transcript.py,
   │                         #    test_benchmark.py, test_demo.py,
   │                         #    test_community_templates.py, test_earcons.py,
   │                         #    test_packaging.py + fixtures/)
   ├─ system/                 # hardware profiling + latency helpers (profiler.py)
   ├─ replay_log.py          # CLI: replay/diagnose saved visual-agent run logs
   ├─ audio/{__init__.py,listener.py,speaker.py,speaker_provider.py,wake_word.py}  # offline wake word + sleep/wake
   ├─ agent/{__init__.py,brain.py,state.py,vision_agent.py,som_overlay.py,app_knowledge.py,task_plan.py,loop_detector.py,abort.py,mid_job.py,local_providers.py,prompt_guard.py,shortcuts.json}
   ├─ tools/{__init__.py,os_tools.py,safety.py,installer_tool.py,event_bus.py,browser_tool.py,window_tools.py,context_tools.py,file_tools.py,mcp_manager.py,memory_tools.py,tool_recipes.py}
   ├─ memory.py               # private-filtered local memory vault (forget/undo)
   ├─ audio/{streaming.py,speech_queue.py}  # sentence chunking + priority speech
   ├─ agent/{som_manifest.py,screen_diff.py}  # compact SoM + post-action verify
   ├─ skills/                 # declarative app workflow packs (non-executable)
   ├─ system/uninstall.py     # uninstall data choice allowlist and cleanup runner
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
