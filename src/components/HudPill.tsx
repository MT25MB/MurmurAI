import { useCallback, useEffect, useRef, useState } from "react";
import { useMurmurSocket } from "../lib/websocket";
import { useSleepWakeHotkey } from "../lib/useSleepWakeHotkey";
import { useAutoUpdater } from "../lib/updater";
import { fetchSettings, saveSettings } from "../lib/settings";
import { setAutostartEnabled } from "../lib/autostart";
import { closeHud, minimizeHud, setHudSize } from "../lib/windowControls";
import TranscriptStream, { useTranscriptTurns } from "./TranscriptStream";
import { Waveform } from "./Waveform";
import logoUrl from "../assets/logo-blue.png";

type Phase = "IDLE" | "LISTENING" | "THINKING" | "SPEAKING" | "CONFIRMATION_REQUIRED" | "SLEEPING";

interface HudPillProps {
  onOpenSettings?: () => void;
}

/** State -> (label, token color). Blue = active sense, red = action/alert. */
const stateStyle: Record<Phase, { label: string; color: string; fill: string }> = {
  IDLE: { label: "Listening", color: "var(--color-blue)", fill: "bg-blue-fill" },
  LISTENING: { label: "Listening…", color: "var(--color-blue)", fill: "bg-blue-fill" },
  THINKING: { label: "Thinking", color: "var(--color-muted)", fill: "bg-surface-2" },
  SPEAKING: { label: "Speaking", color: "var(--color-red)", fill: "bg-red-fill" },
  CONFIRMATION_REQUIRED: { label: "Confirm action", color: "var(--color-red)", fill: "bg-red-fill" },
  SLEEPING: { label: "Sleeping", color: "var(--color-muted)", fill: "bg-surface-2" },
};

export default function HudPill({ onOpenSettings = () => {} }: HudPillProps) {
  const { lastMessage, send, status: socketStatus } = useMurmurSocket();

  // One-shot OS permission check from the native shell; the backend surfaces it
  // on /health and speaks any plain-language recovery steps.
  useEffect(() => {
    let disposed = false;
    import("../lib/permissions")
      .then((m) => m.checkOsPermissions())
      .then((report) => {
        if (!disposed && report) {
          send({ type: "permission_status", permissions: report });
        }
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [send]);
  const [status, setStatus] = useState<Phase>("IDLE");
  const [transcript, setTranscript] = useState("");
  const [muted, setMuted] = useState(false);
  const [progress, setProgress] = useState<{ text: string; percent?: number } | null>(null);
  const [confirmation, setConfirmation] = useState<{
    request_id: string;
    description: string;
    command: string;
  } | null>(null);
  const [guidance, setGuidance] = useState<{ request_id: string; text: string } | null>(null);
  const [guidanceInput, setGuidanceInput] = useState("");
  const [stopped, setStopped] = useState("");
  const [automating, setAutomating] = useState(false);
  // Independent of the transient state label: an activity/status line or a
  // typed command means work is in flight until the final reply arrives.
  const [working, setWorking] = useState(false);
  const [mode, setMode] = useState<"active" | "sleep">("active");
  const [typing, setTyping] = useState(false);
  const [typeInput, setTypeInput] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [update, setUpdate] = useState<{
    request_id: string;
    version: string;
    notes: string;
    text: string;
  } | null>(null);
  const amplitudeRef = useRef(0);
  const panelRef = useRef<HTMLElement>(null);
  const approveRef = useRef<HTMLButtonElement>(null);
  const typeInputRef = useRef<HTMLInputElement>(null);
  const stoppedTimerRef = useRef<number | null>(null);

  // One place decides the native size: expanded panel, typing row, or pill.
  useEffect(() => {
    if (expanded) void setHudSize(560, 680, true);
    else if (typing) void setHudSize(560, 260, false);
    else void setHudSize(560, 120, false);
  }, [expanded, typing]);

  useEffect(() => {
    if (typing) typeInputRef.current?.focus();
  }, [typing]);

  // A minimized/restored or re-expanded window can keep its previous scroll
  // offset in WebView2. Always show the header and input, never a scrolled-away
  // transcript.
  useEffect(() => {
    if (panelRef.current) panelRef.current.scrollTop = 0;
  }, [expanded, typing]);

  useEffect(() => {
    if (!lastMessage) return;
    if (lastMessage.type === "state") {
      const next = (lastMessage.status as Phase) || "IDLE";
      setStatus(next);
      if (next === "THINKING") setWorking(true);
      if (next === "SLEEPING") {
        setMode("sleep");
        setWorking(false);
      } else if (next === "IDLE" || next === "LISTENING") {
        setMode("active");
        // A completed/cancelled tool turn emits no automation_stopped frame.
        setAutomating(false);
        // LISTENING/IDLE can be emitted by barge-in or the listener while the
        // model is still thinking. Never hide the bar on a state flip alone:
        // only a real reply, error, stop or approval ends the work.
      }
      if (typeof lastMessage.amplitude === "number") amplitudeRef.current = lastMessage.amplitude;
    }
    if (lastMessage.type === "text_output") {
      setTranscript(lastMessage.text);
      setProgress(null);
      setWorking(false);
    }
    if (lastMessage.type === "transcript" && lastMessage.role === "assistant") {
      setWorking(false);
    }
    if (lastMessage.type === "transcript" && /working on it/i.test(lastMessage.text || "")) {
      setWorking(true);
    }
    if (lastMessage.type === "confirmation_required") {
      setConfirmation({
        request_id: lastMessage.request_id,
        description: lastMessage.description,
        command: lastMessage.command,
      });
      setStatus("CONFIRMATION_REQUIRED");
      setWorking(false); // waiting for the user, not computing
    }
    if (lastMessage.type === "activity") {
      setWorking(true);
    }
    if (lastMessage.type === "progress") {
      setProgress({ text: lastMessage.text, percent: lastMessage.percent });
      setStatus("THINKING");
      setAutomating(true);
      setWorking(true);
    }
    if (lastMessage.type === "guidance_required") {
      setGuidance({ request_id: lastMessage.request_id, text: lastMessage.text });
    }
    if (lastMessage.type === "automation_stopped") {
      setStopped(lastMessage.text);
      setAutomating(false);
      setWorking(false);
      setGuidance(null);
      setConfirmation(null);
      if (stoppedTimerRef.current !== null) window.clearTimeout(stoppedTimerRef.current);
      stoppedTimerRef.current = window.setTimeout(() => setStopped(""), 6000);
    }
    if (lastMessage.type === "update_available") {
      setUpdate({
        request_id: lastMessage.request_id,
        version: lastMessage.version,
        notes: lastMessage.notes,
        text: lastMessage.text,
      });
    }
    if (lastMessage.type === "update_install") {
      setUpdate(null);
      setTranscript(lastMessage.text);
    }
    if (lastMessage.type === "error") setWorking(false);
  }, [lastMessage]);

  // Startup / voice-driven update check, Tauri events and confirmed installs.
  useAutoUpdater(send, lastMessage);

  // Move focus to the Approve button when a confirmation appears, so
  // keyboard-only users can act immediately with Enter.
  useEffect(() => {
    if (confirmation) approveRef.current?.focus();
  }, [confirmation]);

  const answer = useCallback(
    (approved: boolean) => {
      if (!confirmation) return;
      send({ type: "confirm", request_id: confirmation.request_id, approved });
      setConfirmation(null);
      setStatus("IDLE");
    },
    [confirmation, send],
  );

  // Switch between active conversation and sleep/standby. The backend
  // announces the change aloud, so this is safe for screen-reader users.
  const changeMode = useCallback(
    (next: "active" | "sleep") => {
      setMode(next);
      send({ type: "set_listening_mode", mode: next });
      if (next === "sleep") {
        setStatus("SLEEPING");
        setTranscript("");
      } else {
        setStatus("LISTENING");
      }
    },
    [send],
  );

  const answerUpdate = useCallback(
    (approved: boolean) => {
      if (!update) return;
      send({ type: "update_confirm", request_id: update.request_id, approved });
      setUpdate(null);
    },
    [update, send],
  );

  // Mute must reach the sidecar, otherwise the mic still feeds the brain and the
  // HUD keeps announcing "Listening" after the user clicked mute.
  const toggleMute = useCallback(() => {
    const next = !muted;
    setMuted(next);
    send({ type: "set_muted", muted: next });
  }, [muted, send]);

  // Tauri global hotkey (Ctrl/Cmd+Shift+Space) toggles standby. In a browser
  // there is no Tauri event, so the in-HUD button below is the tactile fallback.
  useSleepWakeHotkey(mode, changeMode);

  // Global keyboard shortcuts: M = mute toggle, Enter = approve, Escape = cancel.
  // Typed in a text field is ignored to avoid hijacking input.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      // Never steal OS/browser shortcuts such as Cmd+Q or Ctrl+T. Escape and
      // Enter confirmation handling below still work unmodified.
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (confirmation) {
        // Let focused buttons handle their own Enter so Tab-to-Cancel then
        // Enter cannot be hijacked into approving a destructive action.
        const onButton = target?.closest("button, a, [role='button']");
        if (e.key === "Enter" && !onButton) {
          e.preventDefault();
          answer(true);
        } else if (e.key === "Escape") {
          e.preventDefault();
          answer(false);
        }
        return;
      }
      if (e.key.toLowerCase() === "t") {
        e.preventDefault();
        setTyping(true);
      } else if (e.key.toLowerCase() === "m") {
        e.preventDefault();
        toggleMute();
      } else if (e.key.toLowerCase() === "q") {
        // Quick "be quiet": stop TTS immediately without muting the mic.
        e.preventDefault();
        send({ type: "be_quiet" });
        setTranscript("I'll be quiet.");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [confirmation, answer, send, toggleMute]);

  // Tray/global hotkey asks us to silence spoken output immediately.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let disposed = false;
    (async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        unlisten = await listen("backend:be-quiet", () => {
          if (!disposed) send({ type: "be_quiet" });
        });
      } catch {
        // Browser dev: the Q shortcut still works.
      }
    })();
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [send]);

  useEffect(() => () => {
    if (stoppedTimerRef.current !== null) window.clearTimeout(stoppedTimerRef.current);
  }, []);

  // Accessible tray actions and shell notices all land on the same WS router.
  useEffect(() => {
    let unlisteners: Array<() => void> = [];
    let disposed = false;
    (async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        const handlers: Array<[string, () => void]> = [
          ["backend:toggle-listening", () => changeMode(mode === "active" ? "sleep" : "active")],
          ["backend:describe-screen", () => send({ type: "describe_screen", focus: "overview" })],
          ["backend:run-diagnostics", () => send({ type: "run_diagnostics" })],
          ["murmur://already-running", () => send({
            type: "cue", text: "Murmur AI is already running",
          })],
        ];
        for (const [event, handler] of handlers) {
          const stop = await listen(event, () => { if (!disposed) handler(); });
          if (disposed) { stop(); return; }
          unlisteners.push(stop);
        }
        const stopAutostart = await listen<boolean>("murmur://autostart-changed", (event) => {
          if (disposed) return;
          void fetchSettings()
            .then((settings) => saveSettings({
              ...settings, autostart_enabled: event.payload,
            }))
            .catch(() => undefined);
        });
        if (disposed) { stopAutostart(); return; }
        unlisteners.push(stopAutostart);
      } catch {
        // Browser dev: tray events are unavailable; the in-HUD controls still work.
      }
    })();
    return () => {
      disposed = true;
      unlisteners.forEach((stop) => stop());
    };
  }, [send, changeMode, mode]);

  // The backend mirrors launch-at-login changes made by voice into config.json
  // and asks the shell to apply the OS registration here.
  useEffect(() => {
    if (lastMessage?.type !== "autostart") return;
    void setAutostartEnabled(lastMessage.enabled).then((actual) => {
      void saveSettings({ autostart_enabled: actual });
    });
  }, [lastMessage]);

  const submitTyped = useCallback(() => {
    const text = typeInput.trim();
    if (!text) return;
    send({ type: "text_input", text });
    setTypeInput("");
    setTranscript(text);
    setStatus("THINKING");
    setWorking(true);
  }, [typeInput, send]);

  const submitGuidance = useCallback(() => {
    if (!guidance || !guidanceInput.trim()) return;
    send({ type: "guidance_response", request_id: guidance.request_id, text: guidanceInput.trim() });
    setGuidance(null);
    setGuidanceInput("");
  }, [guidance, guidanceInput, send]);

  const abortAutomation = useCallback(() => {
    send({ type: "abort_automation", text: "user pressed stop in the HUD" });
    setAutomating(false);
    setGuidance(null);
  }, [send]);

  // One history for both layouts: the compact (screen-reader only) and the
  // expanded (visible) log are separate DOM nodes, but the turns must survive
  // toggling between them.
  const turns = useTranscriptTurns(lastMessage);

  const meta = stateStyle[status] || stateStyle.IDLE;
  const baseLabel = status === "THINKING" ? "Working on it" : meta.label;
  const displayLabel = `${muted ? `${baseLabel} · Muted` : baseLabel}${
    socketStatus === "connected" ? "" : " · Reconnecting"
  }`;
  const statusMessage = `${displayLabel}. ${muted ? "Microphone muted." : ""} ${transcript || ""}`.trim();

  return (
    <section
      ref={panelRef}
      className={
        expanded
          ? "app-region-drag relative fixed inset-0 z-[9999] flex h-full max-h-full min-h-0 select-none flex-col gap-2 overflow-hidden rounded-[1.75rem] border border-border bg-obsidian/95 p-4 shadow-2xl shadow-black/70 ring-1 ring-white/5 backdrop-blur-xl"
          : "app-region-drag relative fixed bottom-[6vh] left-1/2 z-[9999] w-[540px] -translate-x-1/2 select-none rounded-[1.75rem] border border-border bg-obsidian/92 px-4 py-3 shadow-2xl shadow-black/70 ring-1 ring-white/5 backdrop-blur-xl"
      }
      role="region"
      aria-label="Murmur AI status and controls"
    >
      {/* Non-visual status + captions for screen readers (polite). */}
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {statusMessage}
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1">
        <img
          src={logoUrl}
          alt=""
          aria-hidden="true"
          className="h-7 w-7 shrink-0 object-contain"
        />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-col leading-tight">
            <h2 className="text-xs font-semibold tracking-tight text-ink">
              MURMUR<span className="text-blue">/AI</span>
            </h2>
            <span
              className="mono-label !text-[10px]"
              style={{ color: muted ? "var(--color-muted)" : meta.color }}
              aria-hidden="true"
            >
              {displayLabel}
            </span>
          </div>
          {transcript && (
            <p className="truncate text-[11px] leading-snug text-muted" title={transcript} aria-hidden="true">
              {transcript}
            </p>
          )}
        </div>
        {automating && (
          <button
            type="button"
            onClick={abortAutomation}
            className="app-region-no-drag flex h-8 shrink-0 items-center gap-1 rounded-lg border border-red/40 bg-red-fill/20 px-2 text-[11px] font-bold text-red transition-colors hover:bg-red-fill/30"
            aria-label="Stop automation now"
            title="Say 'stop automation', or move the mouse to a screen corner"
          >
            <svg viewBox="0 0 20 20" className="h-3 w-3 fill-current" aria-hidden="true">
              <rect x="4" y="4" width="12" height="12" rx="2" />
            </svg>
            Stop
          </button>
        )}
        <button
          type="button"
          className="app-region-no-drag flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface text-ink transition-colors hover:border-blue"
          onClick={() => setTyping((v) => !v)}
          aria-pressed={typing}
          aria-label="Type a command (T)"
          title="Type instead of speaking (T)"
        >
          <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 fill-current" aria-hidden="true">
            <path d="M4 3h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm1 4v2h10V7H5Zm0 4v2h6v-2H5Z" />
          </svg>
        </button>
        <button
          type="button"
          className="app-region-no-drag flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface text-ink transition-colors hover:border-blue"
          onClick={() => changeMode(mode === "active" ? "sleep" : "active")}
          aria-pressed={mode === "sleep"}
          aria-label={mode === "sleep" ? "Wake Murmur (Ctrl+Shift+Space)" : "Put Murmur to sleep (Ctrl+Shift+Space)"}
          title={mode === "sleep" ? "Wake up" : "Go to sleep"}
        >
          {mode === "sleep" ? (
            // Asleep: the action is "wake up", so show a sun.
            <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 stroke-current" fill="none" strokeWidth={1.8} strokeLinecap="round" aria-hidden="true">
              <circle cx="10" cy="10" r="3.5" />
              <path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.3 4.3l1.4 1.4M14.3 14.3l1.4 1.4M15.7 4.3l-1.4 1.4M5.7 14.3l-1.4 1.4" />
            </svg>
          ) : (
            // Awake: the action is "go to sleep", so show a crescent moon.
            <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 fill-current" aria-hidden="true">
              <path d="M17.3 13.3A7.5 7.5 0 0 1 6.7 2.7 7.5 7.5 0 1 0 17.3 13.3Z" />
            </svg>
          )}
        </button>
        <button
          type="button"
          className="app-region-no-drag flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface text-ink transition-colors hover:border-blue"
          onClick={toggleMute}
          aria-pressed={muted}
          aria-label={muted ? "Unmute microphone (M)" : "Mute microphone (M)"}
          title={muted ? "Unmute (M)" : "Mute (M)"}
        >
          <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 fill-current" aria-hidden="true">
            {muted ? (
              <path d="M3 3l14 14-1.4 1.4-2.2-2.2A7 7 0 0 1 10 17a7 7 0 0 1-7-7 6.9 6.9 0 0 1 1.2-3.9L1.6 2.4 3 1l16 16-1.4 1.4M5 5.1A5 5 0 0 0 3 9a5 5 0 0 0 6 4.9V10l-4-4.9ZM13 5V3a3 3 0 0 0-6 0v2.2l6 6V5Z" />
            ) : (
              <path d="M10 15a4 4 0 0 0 4-4V6a4 4 0 1 0-8 0v5a4 4 0 0 0 4 4ZM3 10a7 7 0 0 0 6 6.9V19h2v-2.1A7 7 0 0 0 17 10h-2a5 5 0 0 1-10 0H3Z" />
            )}
          </svg>
        </button>
        <div className="flex shrink-0 items-center gap-1 border-l border-border pl-1.5">
          <button
            type="button"
            className="app-region-no-drag flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-ink"
            onClick={onOpenSettings}
            aria-label="Open settings (Ctrl+,)"
            title="Settings (Ctrl+, or Cmd+,)"
          >
            <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 fill-current" aria-hidden="true">
              <path d="M9.1 2h1.8l.3 2.1c.5.2 1 .4 1.4.7l1.9-1 1.3 1.3-1 1.9c.3.4.5.9.7 1.4L18 9.1v1.8l-2.1.3c-.2.5-.4 1-.7 1.4l1 1.9-1.3 1.3-1.9-1c-.4.3-.9.5-1.4.7L11.9 18H10.1l-.3-2.1a6 6 0 0 1-1.4-.7l-1.9 1-1.3-1.3 1-1.9a6 6 0 0 1-.7-1.4L3.4 11.9V10.1l2.1-.3c.2-.5.4-1 .7-1.4l-1-1.9 1.3-1.3 1.9 1c.4-.3.9-.5 1.4-.7L9.1 2Zm1.8 4.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z" />
            </svg>
          </button>
          <button
            type="button"
            className="app-region-no-drag flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-ink"
            onClick={() => void minimizeHud()}
            aria-label="Minimize HUD"
            title="Minimize (restore from the tray)"
          >
            <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 fill-current" aria-hidden="true">
              <rect x="3" y="9" width="14" height="2" rx="1" />
            </svg>
          </button>
          <button
            type="button"
            className="app-region-no-drag flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-ink"
            onClick={() => setExpanded((v) => !v)}
            aria-label={expanded ? "Collapse HUD" : "Expand HUD"}
            title={expanded ? "Collapse HUD" : "Expand HUD"}
          >
            <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 fill-current" aria-hidden="true">
              {expanded ? (
                // Restore: two offset squares, drawn as solid frames so the
                // strokes stay crisp at small sizes.
                <path d="M6 3h11v11h-2V5H6V3ZM3 6h11v11H3V6Zm2 2v7h7V8H5Z" />
              ) : (
                // Maximize: one clean square frame (not a thin corner bracket).
                <path d="M4 4h12v12H4V4Zm2 2v8h8V6H6Z" />
              )}
            </svg>
          </button>
          <button
            type="button"
            className="app-region-no-drag flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-red-fill/30 hover:text-red"
            onClick={() => void closeHud()}
            aria-label="Close Murmur AI"
            title="Quit Murmur AI"
          >
            <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 fill-current" aria-hidden="true">
              <path d="M5.3 4.2 10 8.9l4.7-4.7 1.1 1.1-4.7 4.7 4.7 4.7-1.1 1.1-4.7-4.7-4.7 4.7-1.1-1.1 4.7-4.7-4.7-4.7 1.1-1.1Z" />
            </svg>
          </button>
        </div>
      </div>

      {working && (typing || expanded) && (
        <div className="app-region-no-drag shrink-0 rounded-lg border border-blue/35 bg-blue-deep/20 px-2.5 py-2">
          <p className="mb-1.5 text-[11px] font-semibold text-blue" aria-hidden="true">
            Working on it…
          </p>
          <div
            role="progressbar"
            aria-label="Working on it"
            className="h-2 w-full overflow-hidden rounded-full bg-border"
          >
            <div className="h-full progress-indeterminate" />
          </div>
        </div>
      )}

      <div className="my-2.5 flex w-full shrink-0 items-end justify-center" aria-hidden="true">
        <Waveform
          amplitude={amplitudeRef.current}
          active={!muted && (status === "LISTENING" || status === "SPEAKING")}
        />
      </div>

      {(typing || expanded) && (
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto" style={{ maxHeight: expanded ? "55vh" : undefined }}>
          {/* TranscriptStream already speaks every status/action line. A second
              activity log duplicated those lines and pushed the input out of the
              window, so the single live log is the only one rendered. */}
          <TranscriptStream lastMessage={lastMessage} turns={turns} visible />
        </div>
      )}

      {!typing && !expanded && <TranscriptStream lastMessage={lastMessage} turns={turns} />}

      {(typing || expanded) && (
        <div className="mt-auto shrink-0 space-y-2">
          <div className="app-region-no-drag flex gap-1.5">
            <label htmlFor="typed-command" className="sr-only">Command to send</label>
            <input
              id="typed-command"
              ref={typeInputRef}
              type="text"
              value={typeInput}
              onChange={(e) => setTypeInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  submitTyped();
                } else if (e.key === "Escape") {
                  e.preventDefault();
                  setTyping(false);
                }
              }}
              placeholder="Type a command, then press Enter…"
              className="min-w-0 flex-1 rounded-md border border-border bg-obsidian px-3 py-2.5 text-xs text-ink placeholder:text-muted"
            />
            <button
              type="button"
              onClick={submitTyped}
              disabled={!typeInput.trim()}
              aria-label="Send typed command"
              className="min-w-[88px] shrink-0 rounded-md bg-blue-fill px-4 py-2.5 text-xs font-bold text-white disabled:opacity-40"
            >
              Send
            </button>
          </div>
        </div>
      )}

      {progress && (
        <div className="app-region-no-drag mt-2 rounded-lg border border-blue/30 bg-blue-deep/20 p-2.5">
          <p className="truncate text-[11px] text-blue" title={progress.text} aria-hidden="true">
            {progress.text}
          </p>
          <div
            role="progressbar"
            aria-label="Download progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress.percent ?? 0}
          >
            <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-border">
              <div
                className="h-full rounded-full bg-blue-fill transition-all duration-300"
                style={{ width: `${progress.percent ?? 0}%` }}
              />
            </div>
          </div>
          <span className="sr-only">{progress.text}</span>
        </div>
      )}

      {stopped && (
        <div className="app-region-no-drag mt-2 rounded-lg border border-red/40 bg-red-deep/30 p-2.5" role="alert" aria-live="assertive">
          <p className="text-[11px] font-semibold text-red">{stopped}</p>
        </div>
      )}

      {guidance && (
        <div className="app-region-no-drag mt-2 rounded-lg border border-blue/35 bg-blue-deep/25 p-2.5" role="alert" aria-live="assertive">
          <p className="text-[10px] font-semibold uppercase text-blue">I'm stuck. Need a hand?</p>
          <p className="mt-1 text-[11px] leading-snug text-ink">{guidance.text}</p>
          <div className="mt-2 flex gap-1.5">
            <label htmlFor="guidance-input" className="sr-only">Your guidance</label>
            <input
              id="guidance-input"
              type="text"
              value={guidanceInput}
              onChange={(e) => setGuidanceInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") submitGuidance(); }}
              placeholder="Type it, or just say it out loud…"
              className="min-w-0 flex-1 rounded-md border border-border bg-obsidian px-3 py-2.5 text-xs text-ink placeholder:text-muted"
            />
            <button
              type="button"
              onClick={submitGuidance}
              disabled={!guidanceInput.trim()}
              className="min-w-[88px] shrink-0 rounded-md bg-blue-fill px-4 py-2.5 text-xs font-bold text-white disabled:opacity-40"
            >
              Send
            </button>
          </div>
        </div>
      )}

      {update && (
        <div
          className="app-region-no-drag mt-2 rounded-lg border border-blue/35 bg-blue-deep/25 p-2.5"
          role="alert"
          aria-live="assertive"
          aria-atomic="true"
        >
          <p className="mono-label !text-blue">Update available</p>
          <p className="mt-0.5 text-[11px] font-semibold text-ink">Version {update.version}</p>
          {update.notes && (
            <p className="mt-1 line-clamp-3 text-[10px] leading-snug text-muted">{update.notes}</p>
          )}
          <p className="sr-only">{update.text}</p>
          <div className="mt-2 flex gap-1.5">
            <button
              type="button"
              onClick={() => answerUpdate(true)}
              className="flex-1 rounded-md bg-blue-fill px-2 py-1.5 text-[10px] font-bold text-white hover:brightness-110"
              aria-label="Install update: download and install it now"
            >
              Install update
            </button>
            <button
              type="button"
              onClick={() => answerUpdate(false)}
              className="flex-1 rounded-md border border-border bg-surface px-2 py-1.5 text-[10px] font-bold text-ink hover:border-blue"
              aria-label="Not now, skip this update"
            >
              Not now
            </button>
          </div>
        </div>
      )}

      {confirmation && (
        <div
          className="app-region-no-drag mt-2 rounded-lg border border-red/35 bg-red-deep/25 p-2.5"
          role="alert"
          aria-live="assertive"
          aria-atomic="true"
        >
          <p className="mono-label !text-red">Should I go ahead?</p>
          <p className="mt-0.5 break-words text-[11px] leading-snug text-ink">
            {confirmation.description}
          </p>
          <code className="mt-1 block break-all rounded bg-obsidian p-2 font-mono text-[10px] text-muted">
            {confirmation.command}
          </code>
          <div className="mt-2 flex gap-1.5">
            <button
              ref={approveRef}
              type="button"
              onClick={() => answer(true)}
              className="flex-1 rounded-md bg-blue-fill px-2 py-1.5 text-[10px] font-bold text-white hover:brightness-110"
              aria-label="Yes, do it, approve and run the action. Shortcut: Enter"
            >
              Yes, do it
            </button>
            <button
              type="button"
              onClick={() => answer(false)}
              className="flex-1 rounded-md border border-border bg-surface px-2 py-1.5 text-[10px] font-bold text-ink hover:border-red"
              aria-label="Cancel, stop this action. Shortcut: Escape"
            >
              Cancel
            </button>
          </div>
          <p className="sr-only">
            You can answer out loud: say yes to approve, or no to cancel.
          </p>
        </div>
      )}

      {working && !typing && !expanded && (
        <div
          className="pointer-events-none absolute inset-x-4 bottom-1 h-1.5 overflow-hidden rounded-full bg-border"
          role="progressbar"
          aria-label="Working on it"
        >
          <div className="h-full progress-indeterminate" />
        </div>
      )}
    </section>
  );
}
