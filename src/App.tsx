import { useEffect, useState, type ReactNode } from "react";
import HudPill from "./components/HudPill";
import OnboardingModal from "./components/OnboardingModal";
import SettingsDrawer from "./components/SettingsDrawer";
import { fetchSetupStatus, type SetupStatus } from "./lib/setup";
import { waitForBackend } from "./lib/backendReady";
import { fetchAutostartEnabled } from "./lib/autostart";
import { fetchSettings, saveSettings } from "./lib/settings";
import { useFocusRecovery } from "./lib/focusRecovery";

export default function App() {
  // null = still checking; true = setup complete (show HUD); false = onboarding.
  const [ready, setReady] = useState<boolean | null>(null);
  const [connectAttempt, setConnectAttempt] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [alreadyRunning, setAlreadyRunning] = useState(false);
  const { containerRef, announcement } = useFocusRecovery();

  useEffect(() => {
    let disposed = false;
    (async () => {
      const state: { status: SetupStatus | null } = { status: null };
      const result = await waitForBackend(
        async () => {
          state.status = await fetchSetupStatus();
          return state.status;
        },
        {
          attempts: 40,
          baseDelayMs: 500,
          maxDelayMs: 2000,
          onAttempt: (n) => {
            if (!disposed) setConnectAttempt(n);
          },
        },
      );
      if (disposed) return;
      setReady(result.ready ? (state.status?.complete ?? false) : false);
    })();
    return () => {
      disposed = true;
    };
  }, []);

  // If a required model or weight disappears after startup, go back to setup
  // instead of leaving a HUD that accepts commands it cannot carry out.
  useEffect(() => {
    if (!ready) return;
    const id = window.setInterval(() => {
      void fetchSetupStatus()
        .then((status) => { if (!status.complete) setReady(false); })
        .catch(() => undefined);
    }, 15_000);
    return () => window.clearInterval(id);
  }, [ready]);

  // The HUD is a tiny pill when setup is complete, but onboarding/error screens
  // need room for their controls (including the Retry button). Resize the native
  // window so those controls are never clipped or unreachable.
  useEffect(() => {
    let disposed = false;
    (async () => {
      try {
        const [{ getCurrentWindow }, { LogicalSize }] = await Promise.all([
          import("@tauri-apps/api/window"),
          import("@tauri-apps/api/dpi"),
        ]);
        if (disposed) return;
        const window = getCurrentWindow();
        if (ready === null) {
          // "Connecting…" shows a two-line progress message plus a hint; the
          // short pill would clip it. Give it room until status is known.
          await window.setResizable(false);
          await window.setSize(new LogicalSize(560, 220));
        } else if (ready === false) {
          await window.setResizable(true);
          await window.setSize(new LogicalSize(560, 680));
        } else {
          await window.setResizable(false);
          await window.setSize(new LogicalSize(560, 120));
        }
        await window.center();
      } catch {
        // Browser dev mode: no native window to resize.
      }
    })();
    return () => {
      disposed = true;
    };
  }, [ready]);

  // Reconcile the saved voice/settings preference with the OS registration once
  // the backend is ready. The OS remains the source of truth.
  useEffect(() => {
    if (!ready) return;
    void (async () => {
      try {
        const [settings, actual] = await Promise.all([
          fetchSettings(), fetchAutostartEnabled(),
        ]);
        // The OS registration is the source of truth: if it was changed from
        // System Settings, adopt that value instead of undoing the user's choice.
        if (settings.autostart_enabled !== actual) {
          await saveSettings({ autostart_enabled: actual });
        }
      } catch {
        // Browser dev or backend briefly unavailable; retry on next launch.
      }
    })();
  }, [ready]);

  // A second launch never starts a competing sidecar; Rust focuses this window
  // and emits this event. The HUD speaks the cue; here we also show it visibly
  // so onboarding/connecting screens are not silent.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let disposed = false;
    (async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        unlisten = await listen("murmur://already-running", () => {
          if (!disposed) {
            setAlreadyRunning(true);
            window.setTimeout(() => { if (!disposed) setAlreadyRunning(false); }, 4000);
          }
        });
      } catch {
        // Browser dev: no Tauri events.
      }
    })();
    return () => { disposed = true; unlisten?.(); };
  }, []);

  // Ctrl+, / Cmd+, opens settings from anywhere in the HUD.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === ",") {
        event.preventDefault();
        setSettingsOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Tray menu "Settings" emits this Tauri event.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let disposed = false;
    (async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        unlisten = await listen("backend:open-settings", () => {
          if (!disposed) setSettingsOpen(true);
        });
      } catch {
        // Browser dev: the keyboard shortcut still works.
      }
    })();
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  let content: ReactNode;
  if (ready === null) {
    content = (
      <div className="flex h-full w-full flex-col items-center justify-center gap-2 bg-obsidian px-4 text-center text-sm text-muted" role="status" aria-live="polite">
        <p>Connecting to the local backend…</p>
        {connectAttempt > 2 && (
          <p className="text-xs text-muted/70">
            First launch can take ~30s (attempt {connectAttempt}).
          </p>
        )}
      </div>
    );
  } else if (!ready) {
    content = <OnboardingModal onComplete={() => setReady(true)} />;
  } else {
    content = (
      <main className="flex h-full w-full items-center justify-center p-3">
        <HudPill onOpenSettings={() => setSettingsOpen(true)} />
      </main>
    );
  }

  return (
    <div ref={containerRef} tabIndex={-1} className="h-full w-full">
      {alreadyRunning && (
        <p role="status" aria-live="polite" className="sr-only">Murmur AI is already running.</p>
      )}
      {content}
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
    </div>
  );
}
