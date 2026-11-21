/** First-run setup client for the Murmur AI local sidecar. */

export const API_BASE = "http://127.0.0.1:8765";
export const PULL_WS_URL = "ws://127.0.0.1:8765/setup/pull-model";

export interface OllamaStatus {
  installed: boolean;
  running: boolean;
  install_path: string | null;
  version?: string;
  error?: string;
}

export interface SetupStatus {
  ollama: OllamaStatus;
  models: Record<string, boolean>;
  model_labels: Record<string, string>;
  weights: Record<string, boolean>;
  weights_ready: boolean;
  model_cache_dir: string;
  required_models: string[];
  complete: boolean;
  onboarding_dismissed: boolean;
}

export interface PermissionItem {
  key: string;
  label: string;
  granted: boolean | null;
  hint: string;
}

export interface PermissionStatus {
  platform: string;
  session_type?: string;
  items: PermissionItem[];
}

export async function fetchSetupStatus(): Promise<SetupStatus> {
  const res = await fetch(`${API_BASE}/setup/status`);
  if (!res.ok) throw new Error(`Setup status failed: ${res.status}`);
  return res.json();
}

export async function fetchPermissions(): Promise<PermissionStatus> {
  const res = await fetch(`${API_BASE}/setup/permissions`);
  if (!res.ok) throw new Error(`Permissions check failed: ${res.status}`);
  return res.json();
}

export async function promptPermissions(): Promise<PermissionStatus> {
  const res = await fetch(`${API_BASE}/setup/permissions/prompt`, { method: "POST" });
  if (!res.ok) throw new Error(`Permission prompt failed: ${res.status}`);
  return res.json();
}

export async function installOllama(): Promise<{ command: string; url: string; platform: string }> {
  const res = await fetch(`${API_BASE}/setup/install-ollama`, { method: "POST" });
  if (!res.ok) throw new Error(`Install request failed: ${res.status}`);
  return res.json();
}

export async function completeSetup(): Promise<SetupStatus> {
  const res = await fetch(`${API_BASE}/setup/complete`, { method: "POST" });
  if (!res.ok) throw new Error(`Complete request failed: ${res.status}`);
  return res.json();
}

/** Pull a model over the dedicated WebSocket, streaming progress updates. */
export function pullModel(
  model: string,
  onProgress: (text: string, percent: number | null) => void,
  onDone: (ok: boolean, text: string) => void,
): () => void {
  const ws = new WebSocket(PULL_WS_URL);
  ws.onopen = () => ws.send(JSON.stringify({ model }));
  ws.onmessage = (event: MessageEvent<string>) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "pull_progress") {
        onProgress(msg.text ?? msg.detail ?? "", msg.percent ?? null);
      } else if (msg.type === "pull_complete") {
        onDone(true, msg.text ?? "Model ready.");
        ws.close();
      } else if (msg.type === "error") {
        onDone(false, msg.detail ?? "Pull failed.");
        ws.close();
      }
    } catch {
      onDone(false, "Malformed progress message.");
    }
  };
  ws.onerror = () => onDone(false, "Could not connect to the model pull service.");
  return () => ws.close();
}
