/**
 * Bounded readiness polling for the local sidecar.
 *
 * The bundled onefile backend can take ~30s to extract and start on a cold
 * launch, so a single fetch on mount is not enough. Poll with a short,
 * bounded backoff and report each attempt so the UI can show progress.
 */

export interface BackendReadyOptions {
  attempts?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
  onAttempt?: (attempt: number) => void;
}

export interface BackendReadyResult {
  ready: boolean;
  attempts: number;
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export async function waitForBackend<T>(
  probe: () => Promise<T>,
  options: BackendReadyOptions = {},
): Promise<BackendReadyResult> {
  const attempts = Math.max(1, options.attempts ?? 30);
  const baseDelayMs = Math.max(1, options.baseDelayMs ?? 250);
  const maxDelayMs = Math.max(baseDelayMs, options.maxDelayMs ?? 2000);

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    options.onAttempt?.(attempt);
    try {
      await probe();
      return { ready: true, attempts };
    } catch {
      if (attempt === attempts) break;
      const delay = Math.min(maxDelayMs, baseDelayMs * 2 ** (attempt - 1));
      await sleep(delay);
    }
  }
  return { ready: false, attempts };
}
