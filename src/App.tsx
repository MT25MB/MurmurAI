import { useEffect, useState, type ReactNode } from "react";
import HudPill from "./components/HudPill";
import OnboardingModal from "./components/OnboardingModal";
import SettingsDrawer from "./components/SettingsDrawer";
import { fetchSetupStatus } from "./lib/setup";

export default function App() {
  // null = still checking; true = setup complete (show HUD); false = onboarding.
  const [ready, setReady] = useState<boolean | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    fetchSetupStatus()
      .then((s) => setReady(s.complete))
      .catch(() => setReady(false)); // if backend is down, show onboarding retry
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
      <div className="flex h-full w-full items-center justify-center bg-obsidian text-sm text-muted" role="status" aria-live="polite">
        Checking setup…
      </div>
    );
  } else if (!ready) {
    content = <OnboardingModal onComplete={() => setReady(true)} />;
  } else {
    content = (
      <main className="flex h-full w-full items-center justify-center p-3">
        <HudPill />
      </main>
    );
  }

  return (
    <>
      {content}
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  );
}
