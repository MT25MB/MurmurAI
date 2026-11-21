# Contributing to Murmur AI

Thanks for contributing. Murmur AI is a **100% local**, open-source voice agent —
every contribution must keep it that way. Read [AGENTS.md](AGENTS.md) before
making changes; it is the source of truth for architecture and non-negotiable rules.

## Ground rules

- **Local-first.** No cloud API calls, no telemetry, no analytics, no paid services.
  The only network listeners are `127.0.0.1:8765` and local Ollama (`127.0.0.1:11434`).
- **Safety gates are mandatory.** Any destructive shell command or file deletion
  must require explicit confirmation via `tools/safety.py::SafetyGate`.
- **Optional deps stay lazy.** Heavy packages (`faster-whisper`, `kokoro`,
  `pyautogui`, etc.) are imported behind interfaces so the control plane always boots.

## Development setup

```bash
# Frontend + Tauri shell
npm install
npm run dev            # HUD at http://127.0.0.1:1420
npm run tauri dev      # full desktop shell (requires Rust + Tauri prerequisites)
                       # the pretauri hook creates sidecar placeholders automatically

# Backend sidecar
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows  |  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
python main.py                     # http://127.0.0.1:8765/health
```

To run the full app, install [Ollama](https://ollama.com) and pull the models:

```bash
ollama pull qwen2.5:7b
ollama pull qwen2.5-vl:7b
```

## Website

The marketing/docs site lives in [`website/`](website/) (Vite + React + Tailwind v4).
It deploys to GitHub Pages via `.github/workflows/deploy-website.yml`. Change the
repo slug in `website/src/config.ts` and the `base` path in `website/vite.config.ts`
together.

```bash
cd website && npm install && npm run dev
```

## Definition of done

- `npm run build` passes (TypeScript + Vite) for both the app and the website.
- Backend modules compile; `python backend/main.py` serves `/health` with `status: ok`.
- No new third-party network dependency or paid API.
- New destructive capabilities have a test and pass through `SafetyGate`.
- UI changes preserve the locked **obsidian / blue / red** palette defined in
  `src/index.css` and `website/src/index.css` (measured contrast, semantic tokens).

## Verification and git hooks

Run the whole suite locally before pushing:

```bash
bash scripts/verify-all.sh                    # macOS / Linux
powershell -File scripts/verify-all.ps1       # Windows
```

Enable the guardrails that verify automatically on commits to `main` and on
pushes to `main` or `v*` tags:

```bash
git config core.hooksPath .githooks
```

The hooks also refuse to stage secrets, `backend/logs/`, or model binaries.

## Pull requests

1. Fork and create a focused branch (`feat/…`, `fix/…`, `docs/…`).
2. Keep diffs small and explain the "why" in the PR description.
3. Note any new optional dependency and how it degrades when unavailable.
4. Link the issue you're addressing, if any.

By contributing you agree that your work is licensed under the [MIT License](LICENSE).
