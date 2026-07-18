const preset = require("../../packages/config/tailwind-preset.cjs");

module.exports = {
  presets: [preset],
  content: ["./index.html", "./src/**/*.{ts,tsx}", "../../packages/ui/src/**/*.{ts,tsx}"],
};
