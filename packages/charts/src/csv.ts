/**
 * Minimal RFC-4180-ish CSV serialiser shared by chart exports.
 *
 * Kept dependency-free and deterministic so FE-025 (admin metrics) and any
 * sibling task (FE-026 resource stats) can produce identical CSV payloads
 * without pulling in a CSV library. Values containing commas, quotes or
 * newlines are quoted and inner quotes are doubled.
 */

export type CsvRow = readonly (string | number)[];

function escapeCell(value: string | number): string {
  const text = typeof value === "number" ? String(value) : value;
  if (/[",\n\r]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

export function toCsv(header: readonly string[], rows: readonly CsvRow[]): string {
  const lines = [header.map(escapeCell).join(",")];
  for (const row of rows) {
    lines.push(row.map(escapeCell).join(","));
  }
  return `${lines.join("\r\n")}\r\n`;
}

/**
 * Trigger a browser download of `csv` as `filename`. Safe to call from a click
 * handler; no-ops outside a DOM environment. The UTF-8 BOM ensures Excel opens
 * Chinese headers correctly.
 */
export function downloadCsv(
  filename: string,
  header: readonly string[],
  rows: readonly CsvRow[],
): void {
  if (typeof document === "undefined") return;
  const csv = toCsv(header, rows);
  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
