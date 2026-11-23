/** Downloads the correct installer by querying the GitHub Releases API. */

import { useEffect, useState } from "react";
import { RELEASES_API, RELEASES_URL } from "../config";
import { resolveBestAsset, type Asset, type Os, type Release } from "../releases";

type State =
  | { kind: "loading" }
  | { kind: "ready"; os: Os; asset: Asset; tag: string }
  | { kind: "fallback"; os: Os };

function detectOs(): Os {
  const ua = navigator.userAgent.toLowerCase();
  if (ua.includes("win")) return "windows";
  if (ua.includes("mac") || ua.includes("iphone") || ua.includes("ipad")) return "macos";
  return "linux";
}

const OS_LABEL: Record<Os, string> = {
  windows: "Windows",
  macos: "macOS",
  linux: "Linux",
};

export default function DownloadButton() {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [os] = useState<Os>(() => detectOs());

  useEffect(() => {
    let alive = true;
    fetch(RELEASES_API, { headers: { Accept: "application/vnd.github+json" } })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((releases: Release[]) => {
        if (!alive) return;
        const best = resolveBestAsset(releases, os);
        if (best) {
          setState({ kind: "ready", os, asset: best.asset, tag: best.tag });
        } else {
          setState({ kind: "fallback", os });
        }
      })
      .catch(() => alive && setState({ kind: "fallback", os }));
    return () => {
      alive = false;
    };
  }, [os]);

  const primaryHref = state.kind === "ready" ? state.asset.browser_download_url : RELEASES_URL;
  const primaryLabel =
    state.kind === "ready"
      ? `Download for ${OS_LABEL[state.os]}`
      : state.kind === "loading"
        ? "Detecting your platform…"
        : `Get Murmur AI for ${OS_LABEL[os]}`;

  const assetSize = (n: number) => (n / 1024 / 1024).toFixed(0) + " MB";

  return (
    <div className="flex flex-col items-center gap-3 sm:items-start">
      <a
        href={primaryHref}
        download={state.kind === "ready" ? state.asset.name : undefined}
        target={state.kind === "ready" ? undefined : "_blank"}
        rel={state.kind === "ready" ? undefined : "noreferrer"}
        aria-busy={state.kind === "loading"}
        className={`group inline-flex items-center gap-3 rounded-xl px-6 py-3.5 text-sm font-semibold text-white shadow-lg shadow-blue-fill/20 transition-all hover:-translate-y-0.5 hover:shadow-blue-fill/40 ${
          state.kind === "loading" ? "bg-blue-fill/70" : "bg-blue-fill"
        }`}
      >
        <svg viewBox="0 0 20 20" className="h-5 w-5 fill-current" aria-hidden="true">
          <path d="M10 2a1 1 0 0 1 1 1v8.59l2.3-2.3a1 1 0 1 1 1.4 1.42l-4 4a1 1 0 0 1-1.4 0l-4-4a1 1 0 0 1 1.4-1.42l2.3 2.3V3a1 1 0 0 1 1-1ZM3 15a1 1 0 0 1 1 1v1h12v-1a1 1 0 1 1 2 0v2a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1v-2a1 1 0 0 1 1-1Z" />
        </svg>
        {primaryLabel}
      </a>

      <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 sm:justify-start">
        {state.kind === "ready" && (
          <span className="mono-label">
            {state.tag} · {state.asset.name} · {assetSize(state.asset.size)}
          </span>
        )}
        <a href={RELEASES_URL} target="_blank" rel="noreferrer" className="mono-label !text-blue hover:underline">
          All platforms ↓
        </a>
      </div>
    </div>
  );
}
