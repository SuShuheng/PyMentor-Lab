import { describe, expect, it } from "vitest";

import { designTokens, motionTokens } from "./tokens";

describe("PyMentor design tokens", () => {
  it("keeps the frozen monochrome palette and spacing rhythm", () => {
    expect(designTokens.color).toMatchObject({
      ink: "#0A0A0A",
      surface: "#FFFFFF",
      muted: "#6B7280",
      border: "#E5E7EB",
    });
    expect(designTokens.space).toEqual([4, 8, 12, 16, 24, 32]);
    expect(designTokens.radius).toEqual({ control: 8, card: 12 });
  });

  it("defines a reduced-motion-safe transition", () => {
    expect(motionTokens.reduced).toEqual({ duration: 0 });
    expect(motionTokens.standard.duration).toBeLessThanOrEqual(0.24);
  });
});
