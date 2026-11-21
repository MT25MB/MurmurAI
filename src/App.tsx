import { useEffect, useState } from "react";
import HudPill from "./components/HudPill";
import OnboardingModal from "./components/OnboardingModal";
import { fetchSetupStatus } from "./lib/setup";

export default function App() {
  // null = still checking; true = setup complete (show HUD); false = onboarding.
  const [ready, setReady] = useState<boolean | null>(null);

  useEffect(() => {
    fetchSetupStatus()
      .then((s) => setReady(s.complete))
      .catch(() => setReady(false)); // if backend is down, show onboarding retry
  }, []);

  if (ready === null) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-obsidian text-sm text-muted" role="status" aria-live="polite">
        Checking setup…
      </div>
    );
  }

  if (!ready) {
    return <OnboardingModal onComplete={() => setReady(true)} />;
  }

  return (
    <main className="flex h-full w-full items-center justify-center p-3">
      <HudPill />
    </main>
  );
}
