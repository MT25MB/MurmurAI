import { useCallback, useEffect, useRef, useState } from "react";
import { useMurmurSocket } from "../lib/websocket";
import { useSleepWakeHotkey } from "../lib/useSleepWakeHotkey";
import { useAutoUpdater } from "../lib/updater";
import { closeHud, minimizeHud, setHudSize } from "../lib/windowControls";
import TranscriptStream from "./TranscriptStream";
import { Waveform } from "./Waveform";
import logoUrl from "../assets/logo-blue.png";

type Phase = "IDLE" | "LISTENING" | "THINKING" | "SPEAKING" | "CONFIRMATION_REQUIRED" | "SLEEPING";

/** State -> (label, token color). Blue = active sense, red = action/alert. */
const stateStyle: Record<Phase, { label: string; color: string; fill: string }> = {
  IDLE: { label: "Listening", color: "var(--color-blue)", fill: "bg-blue-fill" },
  LISTENING: { label: "Listening…", color: "var(--color-blue)", fill: "bg-blue-fill" },
  THINKING: { label: "Thinking", color: "var(--color-muted)", fill: "bg-surface-2" },
  SPEAKING: { label: "Speaking", color: "var(--color-red)", fill: "bg-red-fill" },
  CONFIRMATION_REQUIRED: { label: "Confirm action", color: "var(--color-red)", fill: "bg-red-fill" },
  SLEEPING: { label: "Sleeping", color: "var(--color-muted)", fill: "bg-surface-2" },
};

export default function HudPill() {
  const { lastMessage, send } = useMurmurSocket();

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
  const approveRef = useRef<HTMLButtonElement>(null);
  const typeInputRef = useRef<HTMLInputElement>(null);

  // One place decides the native size: expanded panel, typing row, or pill.
  useEffect(() => {
    if (expanded) void setHudSize(520, 620, true);
    else if (typing) void setHudSize(400, 260, false);
    else void setHudSize(400, 84, false);
  }, [expanded, typing]);

  useEffect(() => {
    if (typing) typeInputRef.current?.focus();
  }, [typing]);

  useEffect(() => {
    if (!lastMessage) return;
    if (lastMessage.type === "state") {
      const next = (lastMessage.status as Phase) || "IDLE";
      setStatus(next);
      if (next === "SLEEPING") setMode("sleep");
      else if (next === "IDLE" || next === "LISTENING") setMode("active");
      if (typeof lastMessage.amplitude === "number") amplitudeRef.current = lastMessage.amplitude;
    }
    if (lastMessage.type === "text_output") {
      setTranscript(lastMessage.text);
      setProgress(null);
    }
    if (lastMessage.type === "confirmation_required") {
      setConfirmation({
        request_id: lastMessage.request_id,
        description: lastMessage.description,
        command: lastMessage.command,
      });
      setStatus("CONFIRMATION_REQUIRED");
    }
    if (lastMessage.type === "progress") {
      setProgress({ text: lastMessage.text, percent: lastMessage.percent });
      setStatus("THINKING");
      setAutomating(true);
    }
    if (lastMessage.type === "guidance_required") {
      setGuidance({ request_id: lastMessage.request_id, text: lastMessage.text });
    }
    if (lastMessage.type === "automation_stopped") {
      setStopped(lastMessage.text);
      setAutomating(false);
      setGuidance(null);
      setConfirmation(null);
      setTimeout(() => setStopped(""), 6000);
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
      if (confirmation) {
        if (e.key === "Enter") {
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

  const submitTyped = useCallback(() => {
    const text = typeInput.trim();
    if (!text) return;
    send({ type: "text_input", text });
    setTypeInput("");
    setTranscript(text);
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

  const meta = stateStyle[status] || stateStyle.IDLE;
  const displayLabel = muted ? "Muted" : meta.label;
  const statusMessage = `${displayLabel}. ${muted ? "Microphone muted." : ""} ${transcript || ""}`.trim();

  return (
    <section
      className={
        expanded
          ? "app-region-drag fixed inset-0 z-[9999] flex select-none flex-col gap-2 overflow-hidden rounded-[1.75rem] border border-border bg-obsidian/95 p-4 shadow-2xl shadow-black/70 ring-1 ring-white/5 backdrop-blur-xl"
          : "app-region-drag fixed bottom-[8vh] left-1/2 z-[9999] w-[360px] -translate-x-1/2 select-none rounded-[1.75rem] border border-border bg-obsidian/92 px-4 py-3 shadow-2xl shadow-black/70 ring-1 ring-white/5 backdrop-blur-xl"
      }
      role="region"
      aria-label="Murmur AI status and controls"
    >
      {/* Non-visual status + captions for screen readers (polite). */}
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {statusMessage}
      </div>
      <div className="flex items-center gap-2.5">
        <img
          src={logoUrl}
          alt=""
          aria-hidden="true"
          className="h-7 w-7 shrink-0 object-contain"
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <h2 className="truncate text-xs font-semibold tracking-tight text-ink">
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
          className="app-region-no-drag flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-surface text-ink transition-colors hover:border-blue"
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
          className="app-region-no-drag flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-surface text-ink transition-colors hover:border-blue"
          onClick={() => changeMode(mode === "active" ? "sleep" : "active")}
          aria-pressed={mode === "sleep"}
          aria-label={mode === "sleep" ? "Wake Murmur (Ctrl+Shift+Space)" : "Put Murmur to sleep (Ctrl+Shift+Space)"}
          title={mode === "sleep" ? "Wake up" : "Go to sleep"}
        >
          {mode === "sleep" ? (
            <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 fill-current" aria-hidden="true">
              <path d="M10 2a1 1 0 0 1 1 1v1.1a6 6 0 1 1-4.1 4.1H6A1 1 0 0 1 5 7.2V6a4 4 0 0 1 8 0v1.1a1 1 0 0 1-.5.86 4 4 0 0 0-2.5 3.7V13a1 1 0 0 1-2 0V9.6a1 1 0 0 1 .5-.86A4 4 0 0 0 10 5V3a1 1 0 0 1 0-1Z" />
            </svg>
          ) : (
            <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 fill-current" aria-hidden="true">
              <path d="M7 3a1 1 0 0 1 1 1v9.6a3 3 0 1 0 4 0V4a1 1 0 1 1 2 0v9.6a5 5 0 1 1-8 0V4a1 1 0 0 1 1-1Z" />
            </svg>
          )}
        </button>
        <button
          type="button"
          className="app-region-no-drag flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-surface text-ink transition-colors hover:border-blue"
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
            className="app-region-no-drag flex h-6 w-6 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface hover:text-ink"
            onClick={() => void minimizeHud()}
            aria-label="Minimize HUD"
            title="Minimize (restore from the tray)"
          >
            <svg viewBox="0 0 20 20" className="h-3 w-3 fill-current" aria-hidden="true">
              <rect x="4" y="9" width="12" height="2" />
            </svg>
          </button>
          <button
            type="button"
            className="app-region-no-drag flex h-6 w-6 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface hover:text-ink"
            onClick={() => setExpanded((v) => !v)}
            aria-label={expanded ? "Collapse HUD" : "Expand HUD"}
            title={expanded ? "Collapse HUD" : "Expand HUD"}
          >
            <svg viewBox="0 0 20 20" className="h-3 w-3 fill-current" aria-hidden="true">
              {expanded ? (
                <rect x="5" y="8" width="10" height="4" />
              ) : (
                <path d="M4 4h12v2H6v8H4V4Zm0 10h2v2h8v-2h2v4H4v-4Z" />
              )}
            </svg>
          </button>
          <button
            type="button"
            className="app-region-no-drag flex h-6 w-6 items-center justify-center rounded-md text-muted transition-colors hover:bg-red-fill/30 hover:text-red"
            onClick={() => void closeHud()}
            aria-label="Close Murmur AI"
            title="Quit Murmur AI"
          >
            <svg viewBox="0 0 20 20" className="h-3 w-3 fill-current" aria-hidden="true">
              <path d="M5.3 4.2 10 8.9l4.7-4.7 1.1 1.1-4.7 4.7 4.7 4.7-1.1 1.1-4.7-4.7-4.7 4.7-1.1-1.1 4.7-4.7-4.7-4.7 1.1-1.1Z" />
            </svg>
          </button>
        </div>
      </div>

      <div className="my-2.5 flex w-full items-end justify-center" aria-hidden="true">
        <Waveform
          amplitude={amplitudeRef.current}
          active={!muted && (status === "LISTENING" || status === "SPEAKING")}
        />
      </div>

      <TranscriptStream lastMessage={lastMessage} visible={expanded || typing} />

      {(typing || expanded) && (
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
            className="min-w-0 flex-1 rounded-md border border-border bg-obsidian px-2 py-1.5 text-[11px] text-ink placeholder:text-muted"
          />
          <button
            type="button"
            onClick={submitTyped}
            disabled={!typeInput.trim()}
            aria-label="Send typed command"
            className="shrink-0 rounded-md bg-blue-fill px-2 py-1.5 text-[10px] font-bold text-white disabled:opacity-40"
          >
            Send
          </button>
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
              className="min-w-0 flex-1 rounded-md border border-border bg-obsidian px-2 py-1.5 text-[11px] text-ink placeholder:text-muted"
            />
            <button
              type="button"
              onClick={submitGuidance}
              disabled={!guidanceInput.trim()}
              className="shrink-0 rounded-md bg-blue-fill px-2 py-1.5 text-[10px] font-bold text-white disabled:opacity-40"
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
              aria-label="Download and install the update"
            >
              Install update
            </button>
            <button
              type="button"
              onClick={() => answerUpdate(false)}
              className="flex-1 rounded-md border border-border bg-surface px-2 py-1.5 text-[10px] font-bold text-ink hover:border-blue"
              aria-label="Skip this update"
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
              aria-label="Approve and run the action. Shortcut: Enter"
            >
              Yes, do it
            </button>
            <button
              type="button"
              onClick={() => answer(false)}
              className="flex-1 rounded-md border border-border bg-surface px-2 py-1.5 text-[10px] font-bold text-ink hover:border-red"
              aria-label="Cancel the action. Shortcut: Escape"
            >
              Cancel
            </button>
          </div>
          <p className="sr-only">
            You can answer out loud: say yes to approve, or no to cancel.
          </p>
        </div>
      )}
    </section>
  );
}
