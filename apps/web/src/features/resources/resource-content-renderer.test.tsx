import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ResourceContentRenderer } from "./resource-content-renderer";

function mount(content: string, mimeType: string, sha256 = "abc123def456") {
  return render(
    <MemoryRouter>
      <ResourceContentRenderer content={content} mimeType={mimeType} sha256={sha256} />
    </MemoryRouter>,
  );
}

describe("ResourceContentRenderer by content type", () => {
  it("renders text/markdown headings as <h1>/<h2> instead of raw markdown syntax", () => {
    const md = "# Python micro-lecture\n\n解释 input 总是返回字符串。\n\n**Bold point.**";
    mount(md, "text/markdown");

    expect(screen.getByRole("heading", { level: 1, name: "Python micro-lecture" })).toBeVisible();
    expect(screen.getByText("Bold point.")).toBeInTheDocument();
    // The raw leading hash must not appear as the visible body text.
    expect(screen.queryByText(/^#\s/)).not.toBeInTheDocument();
  });

  it("renders markdown lists and code blocks without dumping the raw source", () => {
    const md = "- first point\n- second point\n\n`x = 1` inline code";
    mount(md, "text/markdown");

    expect(screen.getByText("first point")).toBeInTheDocument();
    expect(screen.getByText("second point")).toBeInTheDocument();
    expect(screen.getByText("x = 1")).toBeInTheDocument();
  });

  it("renders notebook cells from application/x-ipynb+json and offers a lab link for code cells", () => {
    const nb = JSON.stringify({
      nbformat: 4,
      cells: [
        {
          cell_type: "markdown",
          source: ["# Notebook task\n", "Sum even numbers in a list."],
        },
        {
          cell_type: "code",
          source: ["total = 0\n", "for n in nums:\n", "    if n % 2 == 0:\n", "        total += n\n"],
        },
      ],
    });
    mount(nb, "application/x-ipynb+json");

    // Markdown cell rendered as heading, not raw JSON.
    expect(
      screen.getByRole("heading", { level: 1, name: "Notebook task" }),
    ).toBeVisible();
    // Code cell rendered inside a <pre> block.
    expect(screen.getByText(/total = 0/)).toBeInTheDocument();
    // Code cell exposes a link into the lab.
    expect(screen.getByRole("link", { name: /在代码实验中打开/ })).toHaveAttribute("href", "/lab");
    // The raw nbformat wrapper text must not be the visible body.
    expect(screen.queryByText(/^{"nbformat":\s*\d+/)).not.toBeInTheDocument();
  });

  it("renders a known structure card (application/json) as a card layout, not raw JSON", () => {
    const card = JSON.stringify({
      title: "range 边界结构卡",
      summary: "起点 → 终点（不含）→ 步长",
      points: [
        { label: "起点 start", detail: "默认是 0" },
        { label: "终点 stop", detail: "只负责划边界" },
      ],
    });
    mount(card, "application/json");

    expect(
      screen.getByRole("heading", { name: "range 边界结构卡" }),
    ).toBeVisible();
    expect(screen.getByText("起点 start")).toBeInTheDocument();
    expect(screen.getByText("默认是 0")).toBeInTheDocument();
    // Raw JSON braces must not leak into the card body.
    expect(screen.queryByText(/^\{"title":/)).not.toBeInTheDocument();
  });

  it("falls back to a labeled <pre> for unknown content types", () => {
    const body = "just plain text blob";
    mount(body, "text/csv");

    expect(screen.getByText(/text\/csv/)).toBeInTheDocument();
    expect(screen.getByText(body)).toBeInTheDocument();
  });

  it("keeps the SHA-256 hash out of the main body and inside a 完整性校验 disclosure", () => {
    const sha = "a".repeat(64);
    mount("# heading\n", "text/markdown", sha);

    // The hash must live inside a closed disclosure labeled 完整性校验 —
    // never as the primary rendered body (which is the heading text).
    const disclosure = screen.getByRole("group", { name: /完整性校验/ });
    expect(disclosure).toBeInTheDocument();
    expect(disclosure).toHaveTextContent(sha);
    // Default-closed: the disclosure is collapsed so the hash is not the
    // first thing the student reads.
    const details = disclosure as HTMLDetailsElement;
    expect(details.open).toBe(false);
    // The hash must not be rendered as a heading or paragraph body element.
    expect(screen.queryByRole("heading", { name: sha })).not.toBeInTheDocument();
  });
});
