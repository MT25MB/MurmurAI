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
  voice_profile: "default" | "clear" | "fast" | "quiet";
  chat_model: string;
  vision_model: string;
  clear_data_on_uninstall: boolean;
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
  if (!res.ok) throw new Error(`Settings save failed: ${res.status}`);
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
