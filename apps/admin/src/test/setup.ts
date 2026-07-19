import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

/**
 * ECharts measures text via an offscreen canvas even when the SVG renderer is
 * selected. jsdom does not implement `HTMLCanvasElement.prototype.getContext`,
 * which logs a noisy "Not implemented" error per render. We stub a minimal 2D
 * context so chart mount stays quiet and fast under jsdom; assertions use the
 * option builders and the companion data table, not pixels.
 */
if (typeof HTMLCanvasElement !== "undefined") {
  HTMLCanvasElement.prototype.getContext = vi.fn(() => {
    const ctx = {
      measureText: (text: string) => ({ width: text.length * 6 }),
    };
    return ctx as unknown as CanvasRenderingContext2D;
  }) as unknown as typeof HTMLCanvasElement.prototype.getContext;
}

/**
 * jsdom does not implement `URL.createObjectURL`, which `downloadCsv` uses to
 * produce the CSV blob URL. We stub it (and `revokeObjectURL`) so CSV export
 * tests can assert on the anchor without hitting "not implemented" errors.
 */
if (typeof URL.createObjectURL !== "function") {
  URL.createObjectURL = vi.fn(() => "blob:stub");
  URL.revokeObjectURL = vi.fn();
}

afterEach(() => cleanup());
