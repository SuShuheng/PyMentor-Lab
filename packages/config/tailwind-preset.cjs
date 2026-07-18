const palette = {
  ink: "#0A0A0A",
  "ink-soft": "#1E1E1E",
  surface: "#FFFFFF",
  canvas: "#F6F7F8",
  muted: "#6B7280",
  border: "#E5E7EB",
  success: "#16A34A",
  warning: "#D97706",
  danger: "#DC2626",
  info: "#2563EB",
};

module.exports = {
  theme: {
    extend: {
      colors: palette,
      borderRadius: {
        control: "8px",
        card: "12px",
      },
      boxShadow: {
        card: "0 12px 32px rgba(10, 10, 10, 0.06)",
        floating: "0 20px 48px rgba(10, 10, 10, 0.1)",
      },
      fontFamily: {
        sans: ["Inter", "Noto Sans SC", "Microsoft YaHei", "sans-serif"],
        mono: ["JetBrains Mono", "Cascadia Code", "monospace"],
      },
    },
  },
};
