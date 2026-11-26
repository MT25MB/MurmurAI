import { beforeEach, describe, expect, it, vi } from "vitest";

const winMock = vi.hoisted(() => ({
  setSize: vi.fn().mockResolvedValue(undefined),
  setResizable: vi.fn().mockResolvedValue(undefined),
  setPosition: vi.fn().mockResolvedValue(undefined),
}));

const monitorMock = vi.hoisted(() => ({
  current: {
    scaleFactor: 1.5,
    workArea: {
      position: { toLogical: () => ({ x: 0, y: 0 }) },
      size: { toLogical: () => ({ width: 1280, height: 900 }) },
    },
  } as unknown,
}));

vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => winMock,
  currentMonitor: async () => monitorMock.current,
}));
vi.mock("@tauri-apps/api/dpi", () => ({
  LogicalSize: class { constructor(public width: number, public height: number) {} },
  LogicalPosition: class { constructor(public x: number, public y: number) {} },
}));

import { setHudSize } from "./windowControls";

const lastSize = () => winMock.setSize.mock.calls.at(-1)?.[0];
const lastPos = () => winMock.setPosition.mock.calls.at(-1)?.[0];

describe("setHudSize", () => {
  beforeEach(() => {
    winMock.setSize.mockClear();
    winMock.setResizable.mockClear();
    winMock.setPosition.mockClear();
    monitorMock.current = {
      scaleFactor: 1.5,
      workArea: {
        position: { toLogical: () => ({ x: 0, y: 0 }) },
        size: { toLogical: () => ({ width: 1280, height: 900 }) },
      },
    } as unknown;
  });

  it("centers the expanded panel inside the work area", async () => {
    await setHudSize(560, 680, true);
    expect(lastSize()).toMatchObject({ width: 560, height: 680 });
    expect(lastPos()).toMatchObject({ x: 360, y: 110 });
    expect(winMock.setResizable).toHaveBeenCalledWith(true);
  });

  it("clamps size and position to a small work area", async () => {
    monitorMock.current = {
      scaleFactor: 1,
      workArea: {
        position: { toLogical: () => ({ x: 0, y: 0 }) },
        size: { toLogical: () => ({ width: 600, height: 500 }) },
      },
    } as unknown;
    await setHudSize(560, 680, true);
    expect(lastSize()).toMatchObject({ width: 560, height: 468 });
    expect(lastPos().y).toBeGreaterThanOrEqual(16);
    expect(lastPos().y + lastSize().height).toBeLessThanOrEqual(500);
  });

  it("respects a work-area offset on a secondary monitor", async () => {
    monitorMock.current = {
      scaleFactor: 1,
      workArea: {
        position: { toLogical: () => ({ x: -1920, y: 100 }) },
        size: { toLogical: () => ({ width: 1920, height: 1000 }) },
      },
    } as unknown;
    await setHudSize(440, 120, false);
    expect(lastPos().x).toBeLessThan(0);
    expect(lastPos().y).toBeGreaterThan(100);
    expect(winMock.setResizable).toHaveBeenCalledWith(true);
    expect(winMock.setResizable).toHaveBeenCalledWith(false);
  });

  it("still resizes when no monitor is reported", async () => {
    monitorMock.current = null;
    await setHudSize(560, 680, true);
    expect(lastSize()).toMatchObject({ width: 560, height: 680 });
    expect(winMock.setPosition).not.toHaveBeenCalled();
  });
});
