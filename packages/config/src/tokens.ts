export const designTokens = {
  color: {
    ink: "#0A0A0A",
    inkSoft: "#1E1E1E",
    surface: "#FFFFFF",
    canvas: "#F6F7F8",
    muted: "#6B7280",
    border: "#E5E7EB",
    success: "#16A34A",
    warning: "#D97706",
    danger: "#DC2626",
    info: "#2563EB",
  },
  space: [4, 8, 12, 16, 24, 32],
  radius: {
    control: 8,
    card: 12,
  },
  shadow: {
    card: "0 12px 32px rgba(10, 10, 10, 0.06)",
    floating: "0 20px 48px rgba(10, 10, 10, 0.1)",
  },
} as const;

export const motionTokens = {
  standard: {
    duration: 0.2,
    ease: [0.2, 0.8, 0.2, 1],
  },
  reduced: {
    duration: 0,
  },
} as const;
