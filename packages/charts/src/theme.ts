/**
 * Black-and-white chart palette (design §26.6).
 *
 * The admin operations surfaces use a strict monochrome language: ink black on
 * white, with grey tints for secondary series and a single dashed accent for
 * thresholds. No colour is used for status semantics in charts — the adjacent
 * data table (rendered by `ChartFrame`) carries the accessible, screen-reader
 * friendly representation. ECharts series here are purely visual.
 *
 * Shared between FE-025 (admin advanced charts) and any sibling chart task
 * (FE-026) that needs the same monochrome language.
 */

export const monochromePalette = {
  ink: "#0A0A0A",
  inkSoft: "#1E1E1E",
  graphite: "#4B5563",
  steel: "#6B7280",
  silver: "#9CA3AF",
  ash: "#C4C9D2",
  mist: "#E5E7EB",
  surface: "#FFFFFF",
  /** Dashed accent reserved for threshold / target reference lines. */
  accentDashed: "#111111",
} as const;

/**
 * Ordered series colours for multi-series monochrome charts (bars, stacked
 * segments). Later indices are lighter so the eye reads the first series as
 * the dominant one without resorting to hue.
 */
export const monochromeSeries: readonly string[] = [
  monochromePalette.ink,
  monochromePalette.graphite,
  monochromePalette.steel,
  monochromePalette.silver,
  monochromePalette.ash,
  monochromePalette.mist,
] as const;

/** Common ECharts axis/grid styling shared by every monochrome chart. */
export const monochromeAxis = {
  axisLine: { lineStyle: { color: monochromePalette.mist } },
  axisTick: { show: false },
  axisLabel: { color: monochromePalette.steel, fontSize: 10 },
  splitLine: { lineStyle: { color: monochromePalette.mist, type: "dashed" as const } },
} as const;

/** ECharts `opts` passed to `ReactECharts` — SVG renderer works in jsdom and
 * avoids the canvas dependency, which keeps unit tests fast and headless. */
export const svgRendererOpts = { renderer: "svg" as const } as const;
