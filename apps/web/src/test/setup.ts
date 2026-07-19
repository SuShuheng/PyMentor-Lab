import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom does not implement URL.createObjectURL/revokeObjectURL. Several
// features (e.g. FE-019 TTS playback) mint temporary blob URLs for
// authenticated media; stub them so components can exercise that path under
// jsdom without throwing. Returns a stable fake URL; revoke is a no-op.
if (typeof URL.createObjectURL !== "function") {
  URL.createObjectURL = vi.fn((blob: Blob) => `blob:fake://${blob.size}`);
}
if (typeof URL.revokeObjectURL !== "function") {
  URL.revokeObjectURL = vi.fn();
}

afterEach(() => cleanup());
