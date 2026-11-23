/** Pure helpers for choosing the newest stable installer from GitHub Releases. */

export type Asset = { name: string; browser_download_url: string; size: number };
export type Release = {
  tag_name: string;
  draft?: boolean;
  prerelease?: boolean;
  published_at?: string;
  assets: Asset[];
};

export type Os = "windows" | "macos" | "linux";

/** Compare dotted version numbers, ignoring a leading `v` and build suffixes. */
export function compareVersions(a: string, b: string): number {
  const parts = (value: string) =>
    value.replace(/^v/i, "").split(/[.+-]/).map((p) => parseInt(p, 10) || 0);
  const left = parts(a);
  const right = parts(b);
  for (let i = 0; i < Math.max(left.length, right.length); i += 1) {
    const diff = (left[i] ?? 0) - (right[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

/** Highest stable version, not whichever release was published most recently. */
export function pickLatestRelease(releases: Release[]): Release | null {
  const stable = releases.filter(
    (r) => !r.draft && !r.prerelease && (r.assets?.length ?? 0) > 0,
  );
  if (!stable.length) return null;
  return stable.reduce((best, current) =>
    compareVersions(current.tag_name, best.tag_name) > 0 ? current : best,
  );
}

const PATTERNS: Record<Os, RegExp[]> = {
  windows: [/\.msi$/i, /\.exe$/i, /windows/i],
  macos: [/\.dmg$/i, /\.app\.tar\.gz$/i, /macos/i, /darwin/i, /aarch64.*apple/i],
  linux: [/\.appimage$/i, /\.deb$/i, /linux/i, /\.tar\.gz$/i],
};

export function pickAsset(assets: Asset[], os: Os): Asset | undefined {
  for (const re of PATTERNS[os]) {
    const found = assets.find((a) => re.test(a.name));
    if (found) return found;
  }
  return undefined;
}

export function resolveBestAsset(
  releases: Release[],
  os: Os,
): { tag: string; asset: Asset } | null {
  const release = pickLatestRelease(releases);
  if (!release) return null;
  const asset = pickAsset(release.assets ?? [], os);
  return asset ? { tag: release.tag_name, asset } : null;
}
