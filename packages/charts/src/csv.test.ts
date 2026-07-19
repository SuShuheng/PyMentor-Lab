import { afterEach, describe, expect, it, vi } from "vitest";

import { downloadCsv, toCsv } from "./csv";

describe("toCsv", () => {
  it("joins header and rows with CRLF and a trailing newline", () => {
    const csv = toCsv(
      ["时间桶", "请求量"],
      [
        ["2026-07-19T00:00:00Z", 120],
        ["2026-07-19T01:00:00Z", 0],
      ],
    );
    expect(csv).toBe("时间桶,请求量\r\n2026-07-19T00:00:00Z,120\r\n2026-07-19T01:00:00Z,0\r\n");
  });

  it("quotes cells that contain commas, quotes or newlines", () => {
    const csv = toCsv(["note"], [['a,b "c"', 1]]);
    expect(csv).toContain('"a,b ""c"""');
  });
});

describe("downloadCsv", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates an anchor with the csv blob and a download attribute, then clicks it", () => {
    const clicks: string[] = [];
    const downloads: string[] = [];
    const originalCreate = document.createElement.bind(document);
    const createElementSpy = vi
      .spyOn(document, "createElement")
      .mockImplementation((tagName: string) => {
        const node = originalCreate(tagName) as HTMLAnchorElement;
        if (tagName === "a") {
          Object.defineProperty(node, "download", {
            get() {
              return downloads[downloads.length - 1];
            },
            set(value: string) {
              downloads.push(value);
            },
            configurable: true,
          });
          node.click = () => {
            clicks.push(node.download ?? "");
          };
        }
        return node;
      });

    downloadCsv("metrics.csv", ["时间桶", "请求量"], [["2026-07-19T00:00:00Z", 120]]);

    expect(clicks).toEqual(["metrics.csv"]);
    expect(downloads).toEqual(["metrics.csv"]);

    createElementSpy.mockRestore();
  });
});
