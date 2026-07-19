import { ArrowSquareOut, CheckCircle } from "@phosphor-icons/react";
import { type ReactNode, createElement, Fragment } from "react";
import { Link } from "react-router-dom";

/**
 * Stage B (FE problems 4 + 8): render published resource content by its
 * declared MIME type instead of dumping raw text or JSON.
 *
 * The five backend resource types publish content under four MIME types
 * (see backend `_ALLOWED_MIME_TYPES`):
 *   - text/markdown                 -> MICRO_LECTURE / LAYERED_EXERCISE text
 *   - application/x-ipynb+json      -> NOTEBOOK_TASK (nbformat cells)
 *   - application/json              -> STRUCTURE_CARD (known shape or raw JSON)
 *   - image/svg+xml                 -> TRACE_ANIMATION (handled by the page)
 *
 * This component deliberately avoids a new markdown dependency: a small
 * regex-based renderer covers the subset emitted by the worker (headings,
 * bold, inline code, lists, fenced code blocks). The output is plain React
 * nodes, never dangerouslySetInnerHTML.
 */

export interface ResourceContentRendererProps {
  /** Raw published content decoded as UTF-8 text. */
  content: string;
  /** MIME type from the Content-Type header (no parameters). */
  mimeType: string;
  /** Optional SHA-256 digest surfaced from the ETag header. */
  sha256?: string | null;
}

type InlineToken = { type: "text" | "bold" | "code"; value: string };

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Split a single line of inline markdown into bold (**), inline code (`),
 * and plain text spans. Returns React nodes keyed by position.
 */
function renderInlineMarkdown(line: string): ReactNode[] {
  const tokens: InlineToken[] = [];
  // Match **bold** or `code` greedily, leftmost first.
  const pattern = new RegExp(
    `(?<bold>\\*\\*(?<boldText>[^*]+)\\*\\*)|(?<code>\`(?<codeText>[^\`]+)\`)`,
    "g",
  );
  let lastIndex = 0;
  for (const match of line.matchAll(pattern)) {
    const matchStart = match.index ?? 0;
    if (matchStart > lastIndex) {
      tokens.push({ type: "text", value: line.slice(lastIndex, matchStart) });
    }
    if (match.groups?.bold !== undefined) {
      tokens.push({ type: "bold", value: match.groups.boldText ?? "" });
    } else if (match.groups?.code !== undefined) {
      tokens.push({ type: "code", value: match.groups.codeText ?? "" });
    }
    lastIndex = matchStart + match[0].length;
  }
  if (lastIndex < line.length) {
    tokens.push({ type: "text", value: line.slice(lastIndex) });
  }
  return tokens.map((token, index) => {
    const key = `${token.type}-${index}`;
    if (token.type === "bold") return <strong key={key}>{token.value}</strong>;
    if (token.type === "code") return <code key={key}>{token.value}</code>;
    return <Fragment key={key}>{token.value}</Fragment>;
  });
}

interface BlockToken {
  type: "heading" | "paragraph" | "list-item" | "code";
  level: number;
  lines: string[];
}

function tokenizeMarkdown(source: string): BlockToken[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: BlockToken[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    if (line.trim() === "") {
      i += 1;
      continue;
    }
    // Fenced code block ```lang ... ```
    const fence = line.match(/^```(?<lang>\w+)?\s*$/);
    if (fence) {
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !/^```\s*$/.test(lines[i] ?? "")) {
        code.push(lines[i] ?? "");
        i += 1;
      }
      // consume the closing fence (if present)
      if (i < lines.length) i += 1;
      blocks.push({ type: "code", level: 0, lines: code });
      continue;
    }
    const heading = line.match(/^(?<hashes>#{1,6})\s+(?<text>.+?)\s*#*\s*$/);
    if (heading) {
      const hashes = heading.groups?.hashes ?? "#";
      blocks.push({
        type: "heading",
        level: hashes.length,
        lines: [heading.groups?.text ?? ""],
      });
      i += 1;
      continue;
    }
    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i] ?? "")) {
        items.push((lines[i] ?? "").replace(/^\s*[-*+]\s+/, ""));
        i += 1;
      }
      blocks.push({ type: "list-item", level: 0, lines: items });
      continue;
    }
    // Paragraph: gather until blank/structural line.
    const para: string[] = [];
    while (
      i < lines.length &&
      (lines[i] ?? "").trim() !== "" &&
      !/^(#{1,6}\s|```|\s*[-*+]\s)/.test(lines[i] ?? "")
    ) {
      para.push(lines[i] ?? "");
      i += 1;
    }
    blocks.push({ type: "paragraph", level: 0, lines: para });
  }
  return blocks;
}

function renderMarkdownBlocks(source: string): ReactNode {
  const blocks = tokenizeMarkdown(source);
  return blocks.map((block, index) => {
    const key = `block-${index}`;
    if (block.type === "heading") {
      const level = Math.min(Math.max(block.level, 1), 6);
      const tag = `h${level}` as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
      return createElement(tag, { key }, renderInlineMarkdown(block.lines[0] ?? ""));
    }
    if (block.type === "code") {
      return (
        <pre key={key}>
          <code>{block.lines.join("\n")}</code>
        </pre>
      );
    }
    if (block.type === "list-item") {
      return (
        <ul key={key}>
          {block.lines.map((item, itemIndex) => (
            <li key={`li-${itemIndex}`}>{renderInlineMarkdown(item)}</li>
          ))}
        </ul>
      );
    }
    return (
      <p key={key}>{block.lines.map((line) => renderInlineMarkdown(line))}</p>
    );
  });
}

interface NotebookCell {
  cell_type?: string;
  source?: string | string[];
}

interface NotebookDoc {
  nbformat?: number;
  cells?: NotebookCell[];
}

function readCellSource(source: NotebookCell["source"]): string {
  if (!source) return "";
  return Array.isArray(source) ? source.join("") : source;
}

function renderNotebook(content: string): ReactNode {
  let parsed: NotebookDoc;
  try {
    parsed = JSON.parse(content) as NotebookDoc;
  } catch {
    return (
      <pre>
        <code>{content}</code>
      </pre>
    );
  }
  const cells = parsed.cells ?? [];
  return cells.map((cell, index) => {
    const key = `cell-${index}`;
    const text = readCellSource(cell.source);
    if (cell.cell_type === "markdown") {
      return <div key={key}>{renderMarkdownBlocks(text)}</div>;
    }
    if (cell.cell_type === "code") {
      return (
        <div className="notebook-cell" key={key}>
          <div className="notebook-cell__bar">
            <span className="eyebrow">CODE CELL</span>
            <Link className="notebook-cell__open" to="/lab">
              在代码实验中打开 <ArrowSquareOut size={14} weight="bold" />
            </Link>
          </div>
          <pre>
            <code>{text.replace(/\n$/, "")}</code>
          </pre>
        </div>
      );
    }
    // Raw output / unknown cells: keep but de-emphasized.
    if (text.trim() === "") return null;
    return (
      <pre key={key} className="notebook-cell__raw">
        <code>{text}</code>
      </pre>
    );
  });
}

interface StructureCardPoints {
  label?: unknown;
  detail?: unknown;
}

interface StructureCardDoc {
  title?: unknown;
  summary?: unknown;
  points?: unknown;
}

function isStringRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function renderStructureCard(content: string): ReactNode {
  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
  } catch {
    return (
      <pre>
        <code>{content}</code>
      </pre>
    );
  }
  if (!isStringRecord(parsed)) {
    return (
      <pre>
        <code>{content}</code>
      </pre>
    );
  }
  const card = parsed as StructureCardDoc;
  const points = Array.isArray(card.points) ? (card.points as unknown[]) : [];
  const knownPoints = points.filter(isStringRecord) as StructureCardPoints[];
  const hasKnownShape =
    typeof card.title === "string" ||
    typeof card.summary === "string" ||
    knownPoints.length > 0;
  if (!hasKnownShape) {
    return (
      <pre>
        <code>{JSON.stringify(parsed, null, 2)}</code>
      </pre>
    );
  }
  return (
    <section className="structure-card">
      {typeof card.title === "string" && card.title ? <h2>{card.title}</h2> : null}
      {typeof card.summary === "string" && card.summary ? (
        <p className="structure-card__summary">{card.summary}</p>
      ) : null}
      {knownPoints.length > 0 ? (
        <dl className="structure-card__points">
          {knownPoints.map((point, index) => {
            const label = typeof point.label === "string" ? point.label : "";
            const detail = typeof point.detail === "string" ? point.detail : "";
            if (!label && !detail) return null;
            return (
              <div key={`point-${index}`}>
                {label ? <dt>{label}</dt> : null}
                {detail ? <dd>{detail}</dd> : null}
              </div>
            );
          })}
        </dl>
      ) : null}
    </section>
  );
}

export function ResourceContentRenderer({
  content,
  mimeType,
  sha256,
}: ResourceContentRendererProps): ReactNode {
  let body: ReactNode;
  let containerClass = "resource-content";
  if (mimeType === "text/markdown") {
    containerClass = "resource-content resource-content--markdown";
    body = renderMarkdownBlocks(content);
  } else if (mimeType === "application/x-ipynb+json") {
    containerClass = "resource-content resource-content--notebook";
    body = renderNotebook(content);
  } else if (mimeType === "application/json") {
    containerClass = "resource-content resource-content--structure-card";
    body = renderStructureCard(content);
  } else {
    containerClass = "resource-content resource-content--raw";
    body = (
      <>
        <p className="eyebrow">{mimeType}</p>
        <pre>
          <code>{content}</code>
        </pre>
      </>
    );
  }

  return (
    <div className={containerClass}>
      {body}
      {sha256 ? (
        <details className="resource-integrity" aria-label="完整性校验">
          <summary>
            <span className="resource-integrity__label">
              <CheckCircle size={14} aria-hidden="true" /> 完整性校验
            </span>
          </summary>
          <p>
            服务端发布前重新校验了 SHA-256 摘要。如需核验对象内容，可对照下列哈希值。
          </p>
          <code className="resource-integrity__digest">{sha256}</code>
        </details>
      ) : null}
    </div>
  );
}

// Re-exported for tests that want to assert the regex tokenizer in isolation.
export const __testing = { tokenizeMarkdown, renderInlineMarkdown, escapeRegExp };
