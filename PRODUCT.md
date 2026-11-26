# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

The website is the public surface for a cross-platform desktop application (Windows, macOS, Linux). The app itself is native/Tauri, not a wrapper around this site.

## Users

- People who want to control their computer by voice without sending audio, screenshots, or files to a cloud service. (Inferred from the product purpose recorded in `AGENTS.md`; not separately interviewed.)
- Screen-reader and keyboard users, who are treated as first-class users of both the HUD and the website. (Inferred from the explicit accessibility requirements in `AGENTS.md`.)
- Developers and reviewers evaluating an open-source, local-only agent: they read `AGENTS.md`, the release assets, and the hardware/model tables before installing. (Inferred from the site's existing Docs and Hardware sections.)

## Product Purpose

Murmur AI is a free, open-source desktop agent that listens through the microphone, speaks through local text-to-speech, and performs computer-control tasks on the user's behalf. Success is a hands-free task completed on the user's own machine with no data leaving it.

## Positioning

Voice computer control that is 100% local and costs $0: every model runs on the user's hardware, there is no account, no API key, and no third-party network call. The only listeners are `127.0.0.1:8765` (backend) and local Ollama; the only outbound calls are to `127.0.0.1` services.

## Operating Context

- A borderless, transparent, always-on-top floating HUD pill plus a system tray icon; voice, `M` mute, `Q` stop, Enter/Escape approval, and a global hotkey toggle standby.
- First-run setup checks Ollama and downloads required models with per-model progress; onboarding is shown until setup is complete.
- Settings (Ctrl/Cmd+, or tray) persist to `~/.murmur-ai/config.json` and are editable by voice.
- Hardware tiers: Light (8–12 GB RAM, no GPU) and High (16 GB+ RAM or 6 GB+ VRAM); chat/vision models and Whisper compute type are chosen on startup, with environment and settings overrides.
- Optional local-only features: LAN-only phone companion (opt-in), MCP plugins, browser automation over local Playwright, dictation mode, spoken plan previews, and declarative skill packs.

## Capabilities and Constraints

- Local inference only: Ollama (chat/vision), faster-whisper (STT), Kokoro or Piper (TTS), PyAutoGUI (computer control). No cloud API key or paid endpoint may be added.
- Heavy dependencies are lazy-imported so `/health` and the WebSocket control plane always boot; a missing dependency produces a clear error.
- Typed, versioned WebSocket protocol; unknown message types are rejected.
- App launching is generic: Start Menu, App Paths, PATH, and Store/UWP AppUserModelIDs — never a hardcoded app list. Multi-step GUI goals use the planner/verifier flow.
- Backend binds to `127.0.0.1` only. Optional companion server is LAN-only and opt-in.
- Current qwen2.5 chat/vision models are defaults; qwen3.5 upgrades are opt-in and hardware-gated in Settings.
- Website release data comes from the GitHub Releases API; the primary download button opens `.../releases/latest` so the visitor picks the installer for their platform.

## Brand Commitments

- Name: **Murmur AI**. Brand mark: the infinity logo in `logo.png` (navy `#1D3251`, OKLCH hue 258). Transparent tints live in `src/assets/logo-blue.png` and `website/public/logo-{blue,navy}.png`.
- Locked palette, identical in app and website: obsidian `#080A0F`, surface `#10141B`, border `#2D333E`, ink `#F1F3F9`, muted `#A0A5AE`, blue accent `#5598F9` / fill `#156CDD` (white text 4.98:1), red accent `#F05653` / fill `#D01C29` (white text 5.41:1). Blue derives from the logo hue; red is reserved for execution/alert states.
- Voice: dark, high-contrast, minimal, factual. No marketing fluff; claims must be true of the shipped code.
- Accessibility is a first-class commitment, not a checklist: ARIA roles, polite/assertive live regions, keyboard shortcuts, visible focus rings, and screen-reader-friendly transcript output.

## Evidence on Hand

- `AGENTS.md` — the repository's source of truth for architecture, safety rules, and verification gates.
- `README.md`, `BENCHMARKS.md`, `.github/ISSUE_TEMPLATE/`, `packaging/`, `scripts/verify-all.ps1` / `.sh`.
- Local test suites: 747 backend pytest tests, 99 frontend Vitest tests, 14 accessibility tests.
- Signed GitHub Releases with `latest.json`, `SHA256SUMS.txt`, and per-platform installers.
- No testimonials, customer logos, case studies, press coverage, or usage statistics exist. Do not fabricate them.

## Product Principles

1. **Local by construction.** No telemetry, no cloud keys, no third-party network calls; privacy is an architectural property, not a setting.
2. **Ask before acting.** Destructive commands and file changes go through an explicit, single-use confirmation with the exact action and blast radius.
3. **Never fake success.** The agent only claims an action ran when a tool actually ran; the site only shows claims that are true in the code.
4. **Accessibility is the baseline.** If a screen reader or keyboard user cannot complete the task, it is not done.
5. **Verify before shipping.** The full verification gate must be green before a release.

## Accessibility & Inclusion

- Website and HUD use semantic HTML, ARIA roles, visible focus rings, polite/assertive live regions, and reduced-motion support.
- Keyboard paths are documented and functional; focus is never trapped.
- Descriptive, non-colour-only status; real alternative text; content usable at 320px minimum width.

_Provenance: all confirmed facts above come from the repository's `AGENTS.md`, `README.md`, `config.ts`, and the shipped test/release state. Items marked inferred are hypotheses drawn from that evidence, not separate user answers; they were labeled because the user said "Go!" and authorized proceeding from the brief._
