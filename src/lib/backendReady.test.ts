import { describe, expect, it, vi } from "vitest";
import { waitForBackend } from "./backendReady";

describe("waitForBackend", () => {
  it("resolves true when the probe succeeds after transient failures", async () => {
    let calls = 0;
    const probe = vi.fn(async () => {
      calls += 1;
      if (calls < 3) throw new Error("Failed to fetch");
      return { complete: true };
    });

    const result = await waitForBackend(probe, {
      attempts: 5,
      baseDelayMs: 1,
      maxDelayMs: 2,
    });

    expect(result.ready).toBe(true);
    expect(probe).toHaveBeenCalledTimes(3);
  });

  it("gives up after the bounded number of attempts", async () => {
    const probe = vi.fn(async () => {
      throw new Error("Failed to fetch");
    });

    const result = await waitForBackend(probe, {
      attempts: 3,
      baseDelayMs: 1,
      maxDelayMs: 2,
    });

    expect(result.ready).toBe(false);
    expect(probe).toHaveBeenCalledTimes(3);
  });

  it("reports progress attempt numbers", async () => {
    const progress: number[] = [];
    let calls = 0;
    await waitForBackend(
      async () => {
        calls += 1;
        if (calls < 2) throw new Error("nope");
        return {};
      },
      { attempts: 3, baseDelayMs: 1, maxDelayMs: 2, onAttempt: (n) => progress.push(n) },
    );
    expect(progress).toEqual([1, 2]);
  });
});
