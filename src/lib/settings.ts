/** Settings + diagnostics client for the local sidecar. */

import { API_BASE } from "./setup";

export interface Settings {
  speech_rate: number;
  voice: string;
  earcons: boolean;
  description_verbosity: "concise" | "detailed";
  listening_mode: "active" | "wake";
  mic_threshold: number;
  screen_reader_friendly: boolean;
  media_ducking: boolean;
  echo_guard: boolean;
  echo_guard_tail_ms: number;
  loopback_guard: boolean;
  spatial_audio_cues: boolean;
  voice_profile: "default" | "natural" | "clear" | "fast" | "quiet";
  chat_model: string;
  vision_model: string;
  provider: string;
  autostart_enabled: boolean;
  clear_data_on_uninstall: boolean;
}

export interface ModelOption {
  name: string;
  label: string;
  role: "chat" | "vision" | "fast" | "unified";
  tier: "current" | "upgrade";
  available: boolean;
  requirement: string;
  reason: string;
}

export interface ModelOptions {
  hardware: {
    total_ram_gb: number;
    vram_gb: number;
    compute_backend: string;
    tier: string;
  };
  options: ModelOption[];
  current: string[];
}

export async function fetchModelOptions(): Promise<ModelOptions> {
  const res = await fetch(`${API_BASE}/model-options`);
  if (!res.ok) throw new Error(`Model options request failed: ${res.status}`);
  return res.json();
}

export async function installModel(model: string): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`${API_BASE}/models/install`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  });
  return res.json();
}

export async function useModel(model: string, role: "chat" | "vision" | "both" | "auto"): Promise<{ ok: boolean; summary: string }> {
  const res = await fetch(`${API_BASE}/models/use`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, role }),
  });
  return res.json();
}

export interface Provider {
  name: string;
  base_url: string;
  model: string;
  cloud: boolean;
  api_key_ref: string;
  key_configured: boolean;
}

export async function fetchProviders(): Promise<Provider[]> {
  const res = await fetch(`${API_BASE}/providers`);
  if (!res.ok) throw new Error(`Provider list failed: ${res.status}`);
  const data = await res.json();
  return Array.isArray(data?.providers) ? (data.providers as Provider[]) : [];
}

export async function registerProvider(input: {
  name: string;
  base_url: string;
  model: string;
  cloud: boolean;
  api_key?: string;
}): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`${API_BASE}/providers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const data = await res.json();
  return res.ok ? { ok: true } : { ok: false, error: String(data.error || "Could not save provider") };
}

export async function removeProvider(name: string): Promise<void> {
  await fetch(`${API_BASE}/providers/remove`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export interface Diagnostics {
  checks: Record<string, unknown>;
  issues: string[];
  summary: string;
}

export async function fetchSettings(): Promise<Settings> {
  const res = await fetch(`${API_BASE}/settings`);
  if (!res.ok) throw new Error(`Settings request failed: ${res.status}`);
  return res.json();
}

export async function saveSettings(changes: Partial<Settings>): Promise<Settings> {
  const res = await fetch(`${API_BASE}/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(String(detail.error || `Settings save failed: ${res.status}`));
  }
  return res.json();
}

export async function resetSettings(): Promise<Settings> {
  const res = await fetch(`${API_BASE}/settings/reset`, { method: "POST" });
  if (!res.ok) throw new Error(`Settings reset failed: ${res.status}`);
  return res.json();
}

export async function fetchDiagnostics(): Promise<Diagnostics> {
  const res = await fetch(`${API_BASE}/diagnostics`);
  if (!res.ok) throw new Error(`Diagnostics request failed: ${res.status}`);
  return res.json();
}
