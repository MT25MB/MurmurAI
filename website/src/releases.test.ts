import { describe, expect, it } from "vitest";
import { compareVersions, pickLatestRelease, resolveBestAsset } from "./releases";
import type { Release } from "./releases";

const asset = (name: string): any => ({
  name,
  browser_download_url: `https://example.test/download/${name}`,
  size: 1000,
});

const release = (tag: string, assets: string[], extra = {}): Release => ({
  tag_name: tag,
  assets: assets.map(asset),
  ...extra,
});

describe("compareVersions", () => {
  it("orders patch releases correctly", () => {
    expect(compareVersions("v1.2.9", "v1.2.10")).toBeLessThan(0);
    expect(compareVersions("v1.3.0", "v1.2.9")).toBeGreaterThan(0);
    expect(compareVersions("v1.2.14-beta.1", "v1.2.14")).toBeLessThan(0);
    expect(compareVersions("v1.2.14+build.5", "v1.2.14")).toBeLessThan(0);
  });
});

describe("pickLatestRelease", () => {
  it("chooses the highest version even when an older release was published later", () => {
    const releases = [
      release("v1.1.1", ["old.dmg"], { published_at: "2026-11-21T18:00:00Z" }),
      release("v1.2.5", ["new.dmg"], { published_at: "2026-11-23T02:00:00Z" }),
      release("v1.0.1", ["older.exe"], { published_at: "2026-11-23T03:00:00Z" }),
    ];
    expect(pickLatestRelease(releases)?.tag_name).toBe("v1.2.5");
  });

  it("ignores drafts, prereleases and releases without assets", () => {
    const releases = [
      release("v9.0.0", [], { draft: true }),
      release("v8.0.0", ["x.dmg"], { prerelease: true }),
      release("v1.2.5", ["ok.dmg"]),
    ];
    expect(pickLatestRelease(releases)?.tag_name).toBe("v1.2.5");
  });
});

describe("resolveBestAsset", () => {
  it("picks the newest release's installer for the platform", () => {
    const releases = [
      release("v1.0.0", ["Murmur.AI_1.0.0_x64_en-US.msi"]),
      release("v1.2.5", ["Murmur.AI_1.2.5_x64_en-US.msi", "Murmur.AI_1.2.5_amd64.AppImage"]),
    ];
    expect(resolveBestAsset(releases, "windows")?.asset.name).toContain("1.2.5");
    expect(resolveBestAsset(releases, "linux")?.asset.name).toContain("AppImage");
  });
});
