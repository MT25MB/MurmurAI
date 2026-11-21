/**
 * Ensure Tauri externalBin placeholder files exist for local development.
 *
 * Real sidecars are produced by PyInstaller in CI (see release.yml) and written
 * to src-tauri/binaries/. Because those binaries are gitignored, fresh clones
 * need placeholders before `cargo tauri dev` can validate tauri.conf.json.
 * This script is intentionally dependency-free and cross-platform.
 */
import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// In CI the real PyInstaller sidecar already exists — never create placeholders
// there, otherwise `npm run tauri build` (via the pretauri hook) can shadow it.
if (process.env.CI === "true" || process.env.GITHUB_ACTIONS === "true") {
  console.log("CI detected — skipping sidecar placeholders (PyInstaller provides them).");
  process.exit(0);
}

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const binaries = join(root, "src-tauri", "binaries");
mkdirSync(binaries, { recursive: true });

const triples = [
  "x86_64-pc-windows-msvc.exe",
  "x86_64-apple-darwin",
  "aarch64-apple-darwin",
  "x86_64-unknown-linux-gnu",
  "aarch64-unknown-linux-gnu",
];

for (const triple of triples) {
  const path = join(binaries, `murmur-backend-${triple}`);
  if (!existsSync(path)) {
    writeFileSync(path, "PLACEHOLDER — replaced by PyInstaller in CI\n");
    console.log(`created ${path}`);
  }
}
console.log("Sidecar placeholders ready.");
