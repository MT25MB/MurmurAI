/** Suggests the matching installer, then sends the user to GitHub Releases to pick it. */

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

  // Always land on the latest GitHub release so the user can choose the exact
  // installer instead of getting a file the browser may mis-handle.
  const primaryHref = RELEASES_URL;
  const assetSize = (n: number) => (n / 1024 / 1024).toFixed(0) + " MB";

  return (
    <div className="flex min-w-0 flex-col items-center gap-3 sm:items-start">
      <a
        href={primaryHref}
        target="_blank"
        rel="noreferrer"
        className="btn-primary"
        aria-busy={state.kind === "loading"}
      >
        <svg viewBox="0 0 20 20" className="h-5 w-5 fill-current" aria-hidden="true">
          <path d="M10 2a1 1 0 0 1 1 1v8.59l2.3-2.3a1 1 0 1 1 1.4 1.42l-4 4a1 1 0 0 1-1.4 0l-4-4a1 1 0 0 1 1.4-1.42l2.3 2.3V3a1 1 0 0 1 1-1ZM3 15a1 1 0 0 1 1 1v1h12v-1a1 1 0 1 1 2 0v2a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1v-2a1 1 0 0 1 1-1Z" />
        </svg>
        Download from GitHub Releases
      </a>

      {state.kind === "ready" && (
        <span className="mono-label max-w-full break-words">
          Latest {state.tag} · suggested for {OS_LABEL[state.os]}: {state.asset.name} · {assetSize(state.asset.size)}
        </span>
      )}
    </div>
  );
}
