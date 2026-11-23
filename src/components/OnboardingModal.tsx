/**
 * First-run setup card. Shown inside the Tauri window instead of the HUD pill
 * whenever Ollama, the required local models, or local weights are missing.
 * All steps are local; no cloud API keys are ever requested.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import logoUrl from "../assets/logo-blue.png";
import { waitForBackend } from "../lib/backendReady";
import {
  completeSetup,
  fetchPermissions,
  fetchSetupStatus,
  installOllama,
  promptPermissions,
  pullModel,
  type PermissionStatus,
  type SetupStatus,
} from "../lib/setup";

type Check = { ok: boolean; label: string; detail: string };

export default function OnboardingModal({ onComplete }: { onComplete: () => void }) {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [permissions, setPermissions] = useState<PermissionStatus | null>(null);
  const [loadError, setLoadError] = useState("");
  const [retrying, setRetrying] = useState(false);
  const [installInfo, setInstallInfo] = useState<{ command: string; url: string } | null>(null);
  const [pulls, setPulls] = useState<Record<string, {
    text: string;
    percent: number | null;
    updatedAt: number;
    active: boolean;
  }>>({});
  const [tick, setTick] = useState(0);
  const [micLevel, setMicLevel] = useState(0);
  const [micState, setMicState] = useState<"idle" | "listening" | "error" | "done">("idle");
  const [busy, setBusy] = useState(false);
  const closePullRefs = useRef<Record<string, () => void>>({});
  const micCleanupRef = useRef<(() => void) | null>(null);

  const refresh = useCallback(async (): Promise<boolean> => {
    try {
      const [s, p] = await Promise.all([fetchSetupStatus(), fetchPermissions()]);
      setStatus(s);
      setPermissions(p);
      setLoadError("");
      return true;
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Backend unavailable.");
      return false;
    }
  }, []);

  // Re-render periodically so a stalled pull can be detected without frames.
  useEffect(() => {
    if (!Object.values(pulls).some((p) => p.active)) return;
    const id = setInterval(() => setTick((n) => n + 1), 2000);
    return () => clearInterval(id);
  }, [pulls]);

  // Retry must survive the sidecar's cold start, so poll briefly with feedback
  // instead of firing one fetch that fails instantly and looks unclickable.
  const retry = useCallback(async () => {
    setRetrying(true);
    await waitForBackend(
      async () => {
        if (!(await refresh())) throw new Error("Backend not ready");
      },
      { attempts: 12, baseDelayMs: 300, maxDelayMs: 1500 },
    );
    setRetrying(false);
  }, [refresh]);

  useEffect(() => {
    refresh();
    return () => {
      Object.values(closePullRefs.current).forEach((close) => close());
      closePullRefs.current = {};
      micCleanupRef.current?.();
    };
  }, [refresh]);

  const handleInstallOllama = async () => {
    setBusy(true);
    try {
      const info = await installOllama();
      setInstallInfo(info);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Install request failed.");
    } finally {
      setBusy(false);
    }
    // Re-check after a short delay in case the user installs quickly.
    setTimeout(refresh, 4000);
  };

  const handlePull = (model: string) => {
    // A stalled socket is restarted by closing it first; other models keep going.
    if (closePullRefs.current[model]) {
      closePullRefs.current[model]();
      delete closePullRefs.current[model];
    }
    setPulls((prev) => ({
      ...prev,
      [model]: { text: "Starting download…", percent: 0, updatedAt: Date.now(), active: true },
    }));
    closePullRefs.current[model] = pullModel(
      model,
      (text, percent) =>
        setPulls((prev) => ({
          ...prev,
          [model]: { text, percent, updatedAt: Date.now(), active: true },
        })),
      (ok, text) => {
        setPulls((prev) => ({
          ...prev,
          [model]: { text, percent: ok ? 100 : null, updatedAt: Date.now(), active: false },
        }));
        delete closePullRefs.current[model];
        if (ok) setTimeout(refresh, 500);
      },
    );
  };

  const pullAllMissing = () => {
    if (!status) return;
    status.required_models.filter((m) => !status.models[m]).forEach(handlePull);
  };

  const testMic = async () => {
    micCleanupRef.current?.();
    setMicState("listening");
    setMicLevel(0);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new AudioContext();
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      let raf = 0;
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (const v of data) sum += ((v - 128) / 128) ** 2;
        const rms = Math.sqrt(sum / data.length);
        setMicLevel(Math.min(1, rms * 4));
        raf = requestAnimationFrame(tick);
      };
      tick();
      const stop = () => {
        cancelAnimationFrame(raf);
        stream.getTracks().forEach((t) => t.stop());
        ctx.close();
        setMicState("done");
      };
      micCleanupRef.current = stop;
      // Auto-stop after 5 seconds.
      setTimeout(() => micCleanupRef.current?.(), 5000);
    } catch {
      setMicState("error");
    }
  };

  const handlePermissions = async () => {
    setBusy(true);
    try {
      setPermissions(await promptPermissions());
    } catch {
      // ignore; user can re-check manually
    } finally {
      setBusy(false);
    }
  };

  const handleFinish = async () => {
    setBusy(true);
    try {
      await completeSetup();
      onComplete();
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Could not save setup state.");
      setBusy(false);
    }
  };

  if (loadError && !status) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-obsidian p-4 text-muted" role="main" aria-label="Murmur AI setup error">
        <div className="w-full max-w-md rounded-2xl border border-red/35 bg-red-deep/30 p-6 text-center" role="alert" aria-live="assertive" aria-labelledby="backend-error-title">
          <p id="backend-error-title" className="text-sm font-semibold text-red">Can't reach the local backend</p>
          <p className="mt-1 text-xs text-red/80">{loadError}</p>
          <button
            type="button"
            onClick={retry}
            disabled={retrying}
            aria-label="Try connecting to the local backend again"
            className="mt-4 cursor-pointer rounded-lg bg-surface-2 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-fill active:bg-blue-deep disabled:cursor-wait disabled:opacity-70"
          >
            {retrying ? "Retrying…" : "Retry"}
          </button>
          <p className="mt-2 text-[11px] text-muted/70">
            The local engine starts on first launch and can take up to 30 seconds.
          </p>
        </div>
      </div>
    );
  }

  if (!status) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-obsidian text-muted" role="status" aria-live="polite">
        <p className="text-sm">Checking what's installed…</p>
      </div>
    );
  }

  const checks: Check[] = [
    {
      ok: status.ollama.running,
      label: "Ollama running",
      detail: status.ollama.running
        ? "Up and running."
        : status.ollama.installed
          ? "Installed, but not running. Start Ollama, then check again."
          : "Not installed yet.",
    },
    ...status.required_models.map((m) => ({
      ok: status.models[m],
      label: m,
      detail: status.models[m] ? "Installed." : status.model_labels[m] || "Not downloaded yet.",
    })),
    {
      ok: status.weights_ready,
      label: "Local voice weights",
      detail: status.weights_ready
        ? "Whisper and Kokoro are saved locally."
        : "We'll fetch these on first launch.",
    },
  ];

  const allReady = checks.every((c) => c.ok);
  const permsReady = !permissions || permissions.items.every((p) => p.granted !== false);
  const missing = checks.filter((c) => !c.ok).map((c) => c.label);

  return (
    <div className="h-full w-full overflow-y-auto bg-obsidian p-5 text-ink" role="main" aria-label="Murmur AI first-run setup" aria-busy={busy}>
      <div
        className="mx-auto w-full max-w-lg rounded-2xl border border-border bg-surface/95 p-6 shadow-2xl ring-1 ring-white/5"
        role="dialog"
        aria-modal="false"
        aria-labelledby="setup-title"
        aria-describedby="setup-intro"
      >
        <div className="flex items-center gap-3">
          <img src={logoUrl} alt="" aria-hidden="true" className="h-11 w-11 object-contain" />
          <div>
            <h1 id="setup-title" className="text-lg font-semibold tracking-tight text-white">Welcome to Murmur AI</h1>
            <p id="setup-intro" className="text-xs text-muted">A one-time setup on this machine. Your stuff stays here.</p>
          </div>
        </div>

        {/* Screen-reader summary of overall readiness. */}
        <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
          {allReady ? "You're all set." : `Still needed: ${missing.join(", ")}.`}
        </p>

        {/* Environment checks */}
        <section className="mt-6">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted">
            Environment
          </h2>
          <ul className="mt-2 space-y-1.5" role="list">
            {checks.map((c) => (
              <li
                key={c.label}
                className="flex items-center gap-3 rounded-lg border border-border bg-surface/60 px-3 py-2"
              >
                <span
                  className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
                    c.ok ? "bg-blue/20 text-blue" : "bg-red/20 text-red"
                  }`}
                  aria-hidden="true"
                >
                  {c.ok ? "✓" : "!"}
                </span>
                <span className="sr-only">{c.ok ? "Ready:" : "Missing:"}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-white">{c.label}</p>
                  <p className="truncate text-[11px] text-muted">{c.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>

        {/* Ollama install */}
        {!status.ollama.installed && (
          <button
            type="button"
            onClick={handleInstallOllama}
            disabled={busy}
            aria-busy={busy}
            aria-label="Install Ollama locally"
            className="mt-4 w-full rounded-lg bg-blue-fill px-4 py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
          >
            Install Ollama
          </button>
        )}
        {installInfo && (
          <p className="mt-2 break-all rounded bg-obsidian p-2 text-[11px] text-muted">
            Or run: <code className="text-blue">{installInfo.command}</code>
          </p>
        )}

        {/* Model pulls */}
        <section className="mt-6">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted">
              Local models
            </h2>
            {status.required_models.some((m) => !status.models[m]) && (
              <button
                type="button"
                onClick={pullAllMissing}
                className="app-region-no-drag rounded-md border border-blue/40 bg-blue-deep/25 px-2 py-1 text-[10px] font-semibold text-blue hover:bg-blue-deep/40"
                aria-label="Download all missing local models at once"
              >
                Download all missing
              </button>
            )}
          </div>
          <div className="mt-2 space-y-2">
            {status.required_models.map((m) => (
              <div key={m} className="rounded-lg border border-border bg-surface/60 p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-xs font-medium text-white">{m}</p>
                    <p className="text-[11px] text-muted">{status.model_labels[m]}</p>
                  </div>
                  {status.models[m] ? (
                    <span className="rounded-md bg-blue/15 px-2 py-1 text-[10px] font-semibold text-blue">
                      Ready
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handlePull(m)}
                      aria-label={`Download the ${m} model. ${status.model_labels[m]}.`}
                      className="shrink-0 rounded-md bg-blue-fill px-3 py-1.5 text-[11px] font-semibold text-white hover:brightness-110"
                    >
                      Pull
                    </button>
                  )}
                </div>
                {pulls[m] && (() => {
                  const pull = pulls[m];
                  const stalled = pull.active && tick > 0 && Date.now() - pull.updatedAt > 15000;
                  const known = pull.percent !== null && pull.percent > 0;
                  return (
                    <div className="mt-2" aria-live="polite">
                      <p className="truncate text-[11px] text-blue" title={pull.text} aria-hidden="true">
                        {stalled ? "No progress from the local engine" : pull.text}
                      </p>
                      <div
                        role="progressbar"
                        aria-label={`Download progress for ${m}`}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={known ? pull.percent! : undefined}
                        aria-valuetext={known ? `${pull.percent}%` : "Downloading, estimating remaining time"}
                      >
                        <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-surface-2">
                          <div
                            className={`h-full rounded-full transition-all duration-200 ${
                              known ? "bg-blue-fill" : "progress-indeterminate"
                            }`}
                            style={known ? { width: `${pull.percent}%` } : undefined}
                          />
                        </div>
                      </div>
                      {stalled && (
                        <button
                          type="button"
                          onClick={() => handlePull(m)}
                          className="mt-2 rounded-md border border-red/40 px-2 py-1 text-[10px] font-semibold text-red hover:bg-red-fill/20"
                        >
                          Restart this download
                        </button>
                      )}
                      <span className="sr-only">{stalled ? "Download stalled" : pull.text}</span>
                    </div>
                  );
                })()}
              </div>
            ))}
          </div>
        </section>

        {/* Microphone test */}
        <section className="mt-6">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted">
            Microphone
          </h2>
          <div className="mt-2 flex items-center gap-3 rounded-lg border border-border bg-surface/60 p-3">
            <button
              type="button"
              onClick={testMic}
              aria-label="Test your microphone. Talk after starting; it stops after five seconds."
              className="shrink-0 rounded-md bg-surface-2 px-3 py-1.5 text-[11px] font-semibold text-white hover:bg-surface-2"
            >
              Test mic
            </button>
            <div
              className="h-2 flex-1 overflow-hidden rounded-full bg-surface-2"
              role="meter"
              aria-label="Microphone input level"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(micLevel * 100)}
            >
              <div
                className="h-full rounded-full bg-blue-fill transition-all duration-75"
                style={{ width: `${micLevel * 100}%` }}
              />
            </div>
            <span className="w-16 text-right text-[10px] text-muted" aria-live="polite">
              {micState === "error" ? "Blocked" : micState === "done" ? "Done" : micState === "listening" ? "Go ahead, talk" : "Ready"}
            </span>
          </div>
        </section>

        {/* OS permissions */}
        {permissions && (
          <section className="mt-6">
            <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted">
              Permissions
            </h2>
            <div className="mt-2 space-y-1.5">
              {permissions.items.map((item) => (
                <div
                  key={item.key}
                  className="rounded-lg border border-border bg-surface/60 px-3 py-2"
                >
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-medium text-white">{item.label}</p>
                    <span
                      className={`text-[10px] font-semibold ${
                        item.granted === true
                          ? "text-blue"
                          : item.granted === false
                            ? "text-red"
                            : "text-muted"
                      }`}
                    >
                      {item.granted === true ? "Granted" : item.granted === false ? "Needed" : "Check manually"}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[11px] leading-snug text-muted">{item.hint}</p>
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={handlePermissions}
              disabled={busy}
              aria-busy={busy}
              aria-label="Check your system permissions, or ask for them"
              className="mt-2 w-full rounded-lg border border-border bg-surface-2 px-4 py-2 text-xs font-semibold text-ink hover:bg-surface-2 disabled:opacity-50"
            >
              Check permissions
            </button>
          </section>
        )}

        {loadError && (
          <p className="mt-3 rounded-md border border-red/30 bg-red-deep/20 p-2 text-[11px] text-red" role="alert" aria-live="assertive">
            {loadError}
          </p>
        )}

        <button
          type="button"
          onClick={handleFinish}
          disabled={busy || !allReady || !permsReady}
          aria-busy={busy}
          aria-label={allReady ? "Finish setup and start Murmur AI" : `Still needed: ${missing.join(", ")}.`}
          className="mt-6 w-full rounded-lg bg-blue-fill px-4 py-3 text-sm font-bold text-white hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {allReady ? "Start Murmur AI" : "Finish the steps above"}
        </button>
      </div>
    </div>
  );
}
