import { useEffect, useRef, useState } from "react";
import {
  fetchSettings,
  saveSettings,
  resetSettings,
  fetchDiagnostics,
  type Settings,
} from "../lib/settings";

interface SettingsDrawerProps {
  open: boolean;
  onClose: () => void;
}

/** Full-ARIA settings panel, reachable from the tray or Ctrl/Cmd+,. */
export default function SettingsDrawer({ open, onClose }: SettingsDrawerProps) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [status, setStatus] = useState("");
  const [diagnostics, setDiagnostics] = useState("");
  const dialogRef = useRef<HTMLDivElement>(null);
  const firstFieldRef = useRef<HTMLSelectElement>(null);
  const saveSeqRef = useRef(0);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    fetchSettings()
      .then((s) => {
        if (!cancelled) {
          setSettings(s);
          setStatus("Settings loaded.");
        }
      })
      .catch(() => {
        if (!cancelled) setStatus("Could not load settings from the local backend.");
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (open && settings) firstFieldRef.current?.focus();
  }, [open, settings]);

  if (!open) return null;

  const change = async (patch: Partial<Settings>) => {
    const seq = ++saveSeqRef.current;
    setSettings((prev) => (prev ? { ...prev, ...patch } : prev));
    try {
      const saved = await saveSettings(patch);
      // Sliders can fire several overlapping saves; only the newest response
      // may replace the optimistic UI state.
      if (seq === saveSeqRef.current) setSettings(saved);
      setStatus("Settings saved.");
    } catch {
      setStatus("Could not save settings.");
    }
  };

  const runDiagnostics = async () => {
    setStatus("Running diagnostics…");
    try {
      const result = await fetchDiagnostics();
      setDiagnostics(result.summary);
      setStatus("Diagnostics complete.");
    } catch {
      setStatus("Diagnostics were unavailable.");
    }
  };

  const restoreDefaults = async () => {
    try {
      setSettings(await resetSettings());
      setStatus("Defaults restored.");
    } catch {
      setStatus("Could not reset settings.");
    }
  };

  return (
    <div
      className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/60 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        aria-describedby="settings-description"
        className="max-h-[85vh] w-full max-w-md overflow-y-auto rounded-2xl border border-border bg-obsidian p-5 text-ink shadow-2xl"
      >
        <div className="flex items-center justify-between gap-3">
          <h2 id="settings-title" className="text-base font-semibold">
            Murmur AI settings
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border bg-surface px-2 py-1 text-xs font-bold hover:border-blue"
            aria-label="Close settings"
          >
            Close
          </button>
        </div>
        <p id="settings-description" className="mt-1 text-[11px] text-muted">
          Changes apply immediately and are saved to ~/.murmur-ai/config.json.
        </p>

        <p className="mt-2 text-xs text-blue" role="status" aria-live="polite">
          {status}
        </p>

        {!settings ? (
          <p className="mt-4 text-sm text-muted">Loading settings…</p>
        ) : (
          <div className="mt-4 space-y-4">
            <fieldset className="space-y-3">
              <legend className="text-xs font-semibold uppercase tracking-wide text-muted">
                Speech and voice
              </legend>

              <div>
                <label htmlFor="settings-profile" className="block text-xs font-medium">
                  Voice profile
                </label>
                <select
                  id="settings-profile"
                  value={settings.voice_profile}
                  onChange={(e) => change({ voice_profile: e.target.value as Settings["voice_profile"] })}
                  className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-ink"
                >
                  <option value="default">Default</option>
                  <option value="natural">Natural (best local voice)</option>
                  <option value="clear">Clear (screen-reader friendly)</option>
                  <option value="fast">Fast</option>
                  <option value="quiet">Quiet</option>
                </select>
              </div>

              <div>
                <label htmlFor="settings-voice" className="block text-xs font-medium">
                  Voice
                </label>
                <select
                  id="settings-voice"
                  ref={firstFieldRef}
                  value={settings.voice}
                  onChange={(e) => change({ voice: e.target.value })}
                  className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-ink"
                >
                  <option value="af_heart">af_heart</option>
                  <option value="af_bella">af_bella</option>
                  <option value="am_adam">am_adam</option>
                  <option value="system-default">System default</option>
                </select>
              </div>

              <div>
                <label htmlFor="settings-rate" className="block text-xs font-medium">
                  Speech rate: {settings.speech_rate.toFixed(2)}x
                </label>
                <input
                  id="settings-rate"
                  type="range"
                  min={0.5}
                  max={2}
                  step={0.05}
                  value={settings.speech_rate}
                  onChange={(e) => change({ speech_rate: Number(e.target.value) })}
                  className="mt-1 w-full accent-blue"
                  aria-valuetext={`${settings.speech_rate.toFixed(2)} times normal speed`}
                />
              </div>

              <div className="flex items-center gap-2">
                <input
                  id="settings-uninstall-data"
                  type="checkbox"
                  checked={settings.clear_data_on_uninstall}
                  onChange={(e) => change({ clear_data_on_uninstall: e.target.checked })}
                  className="h-4 w-4 accent-blue"
                />
                <label htmlFor="settings-uninstall-data" className="text-xs font-medium">
                  Clear my data if Murmur AI is uninstalled
                </label>
              </div>
              <p className="ml-6 text-[11px] text-muted">
                Off by default: memories, chats, keys and settings stay on this PC. Model
                downloads are never removed.
              </p>

              <div className="flex items-center gap-2">
                <input
                  id="settings-earcons"
                  type="checkbox"
                  checked={settings.earcons}
                  onChange={(e) => change({ earcons: e.target.checked })}
                  className="h-4 w-4 accent-blue"
                />
                <label htmlFor="settings-earcons" className="text-xs font-medium">
                  Play state chimes
                </label>
              </div>

              <div className="flex items-center gap-2">
                <input
                  id="settings-screen-reader"
                  type="checkbox"
                  checked={settings.screen_reader_friendly}
                  onChange={(e) => change({ screen_reader_friendly: e.target.checked })}
                  className="h-4 w-4 accent-blue"
                />
                <label htmlFor="settings-screen-reader" className="text-xs font-medium">
                  Screen-reader friendly (less chatter)
                </label>
              </div>

              <div className="flex items-center gap-2">
                <input
                  id="settings-ducking"
                  type="checkbox"
                  checked={settings.media_ducking}
                  onChange={(e) => change({ media_ducking: e.target.checked })}
                  className="h-4 w-4 accent-blue"
                />
                <label htmlFor="settings-ducking" className="text-xs font-medium">
                  Lower media volume while speaking
                </label>
              </div>

              <div>
                <label htmlFor="settings-verbosity" className="block text-xs font-medium">
                  Screen descriptions
                </label>
                <select
                  id="settings-verbosity"
                  value={settings.description_verbosity}
                  onChange={(e) =>
                    change({ description_verbosity: e.target.value as Settings["description_verbosity"] })
                  }
                  className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-ink"
                >
                  <option value="concise">Concise</option>
                  <option value="detailed">Detailed</option>
                </select>
              </div>
            </fieldset>

            <fieldset className="space-y-3">
              <legend className="text-xs font-semibold uppercase tracking-wide text-muted">
                Listening and privacy
              </legend>
              <div>
                <label htmlFor="settings-listening" className="block text-xs font-medium">
                  Listening mode
                </label>
                <select
                  id="settings-listening"
                  value={settings.listening_mode}
                  onChange={(e) =>
                    change({ listening_mode: e.target.value as Settings["listening_mode"] })
                  }
                  className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-ink"
                >
                  <option value="active">Continuous listening</option>
                  <option value="wake">Wake-word only</option>
                </select>
              </div>
              <div>
                <label htmlFor="settings-threshold" className="block text-xs font-medium">
                  Microphone threshold: {settings.mic_threshold.toFixed(2)}
                </label>
                <input
                  id="settings-threshold"
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={settings.mic_threshold}
                  onChange={(e) => change({ mic_threshold: Number(e.target.value) })}
                  className="mt-1 w-full accent-blue"
                  aria-valuetext={`${settings.mic_threshold.toFixed(2)} out of one`}
                />
              </div>

              <div className="flex items-center gap-2">
                <input
                  id="settings-echo-guard"
                  type="checkbox"
                  checked={settings.echo_guard}
                  onChange={(e) => change({ echo_guard: e.target.checked })}
                  className="h-4 w-4 accent-blue"
                />
                <label htmlFor="settings-echo-guard" className="text-xs font-medium">
                  Ignore my own voice (echo guard)
                </label>
              </div>

              <div className="flex items-center gap-2">
                <input
                  id="settings-loopback"
                  type="checkbox"
                  checked={settings.loopback_guard}
                  onChange={(e) => change({ loopback_guard: e.target.checked })}
                  className="h-4 w-4 accent-blue"
                />
                <label htmlFor="settings-loopback" className="text-xs font-medium">
                  Also ignore system audio (loopback)
                </label>
              </div>

              <div>
                <label htmlFor="settings-echo-tail" className="block text-xs font-medium">
                  Echo guard tail: {settings.echo_guard_tail_ms} ms
                </label>
                <input
                  id="settings-echo-tail"
                  type="range"
                  min={0}
                  max={1000}
                  step={50}
                  value={settings.echo_guard_tail_ms}
                  onChange={(e) => change({ echo_guard_tail_ms: Number(e.target.value) })}
                  className="mt-1 w-full accent-blue"
                  aria-valuetext={`${settings.echo_guard_tail_ms} milliseconds after speech stops`}
                />
              </div>

              <div className="flex items-center gap-2">
                <input
                  id="settings-spatial-cues"
                  type="checkbox"
                  checked={settings.spatial_audio_cues}
                  onChange={(e) => change({ spatial_audio_cues: e.target.checked })}
                  className="h-4 w-4 accent-blue"
                />
                <label htmlFor="settings-spatial-cues" className="text-xs font-medium">
                  Spatial audio cues (positioned clicks)
                </label>
              </div>
            </fieldset>

            <fieldset className="space-y-3">
              <legend className="text-xs font-semibold uppercase tracking-wide text-muted">
                Models
              </legend>
              <div>
                <label htmlFor="settings-chat-model" className="block text-xs font-medium">
                  Chat model
                </label>
                <input
                  id="settings-chat-model"
                  type="text"
                  value={settings.chat_model}
                  placeholder="Leave blank for auto"
                  onChange={(e) => change({ chat_model: e.target.value })}
                  className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-ink"
                />
              </div>
              <div>
                <label htmlFor="settings-vision-model" className="block text-xs font-medium">
                  Vision model
                </label>
                <input
                  id="settings-vision-model"
                  type="text"
                  value={settings.vision_model}
                  placeholder="Leave blank for auto"
                  onChange={(e) => change({ vision_model: e.target.value })}
                  className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-ink"
                />
              </div>
            </fieldset>

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={runDiagnostics}
                className="flex-1 rounded-md bg-blue-fill px-3 py-2 text-xs font-bold text-white hover:brightness-110"
              >
                Run diagnostics
              </button>
              <button
                type="button"
                onClick={restoreDefaults}
                className="rounded-md border border-border bg-surface px-3 py-2 text-xs font-bold text-ink hover:border-blue"
              >
                Reset defaults
              </button>
            </div>

            {diagnostics && (
              <div
                role="status"
                aria-live="polite"
                className="rounded-md border border-border bg-surface p-2 text-[11px] leading-snug text-muted"
              >
                {diagnostics}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
