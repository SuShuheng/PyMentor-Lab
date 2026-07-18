import { createHash } from "node:crypto";

import { describe, expect, it } from "vitest";

import { NoSourcesError, buildSourceBoundContext } from "./source-bound.js";

function digest(content: string): string {
  return createHash("sha256").update(content, "utf8").digest("hex");
}

describe("source-bound RAG context", () => {
  it("keeps only approved, digest-valid HTTPS sources in deterministic rank order", () => {
    const lower = "range excludes the stop value";
    const higher = "for statements repeat a suite over an iterable";

    const context = buildSourceBoundContext(
      {
        question: "How does a Python for loop work?",
        courseId: "course-python",
        nodeId: "node-for-loop",
        allowedSourceIds: ["source-language", "source-range"],
        maxCharacters: 200,
      },
      [
        {
          sourceId: "source-range",
          courseId: "course-python",
          nodeId: "node-for-loop",
          title: "Built-in range",
          url: "https://docs.python.org/3/library/stdtypes.html#range",
          excerpt: lower,
          excerptDigest: digest(lower),
          score: 0.7,
        },
        {
          sourceId: "source-language",
          courseId: "course-python",
          nodeId: "node-for-loop",
          title: "The for statement",
          url: "https://docs.python.org/3/reference/compound_stmts.html#the-for-statement",
          excerpt: higher,
          excerptDigest: digest(higher),
          score: 0.9,
        },
        {
          sourceId: "source-unapproved",
          courseId: "course-python",
          nodeId: "node-for-loop",
          title: "Unapproved",
          url: "https://example.com/python",
          excerpt: "unapproved text",
          excerptDigest: digest("unapproved text"),
          score: 1,
        },
        {
          sourceId: "source-range",
          courseId: "course-python",
          nodeId: "node-for-loop",
          title: "Tampered",
          url: "https://docs.python.org/3/library/stdtypes.html#range",
          excerpt: "tampered text",
          excerptDigest: "0".repeat(64),
          score: 0.95,
        },
      ],
    );

    expect(context.citations.map((citation) => citation.sourceId)).toEqual([
      "source-language",
      "source-range",
    ]);
    expect(context.prompt).toContain("[source:source-language]");
    expect(context.prompt).toContain("[source:source-range]");
    expect(context.prompt).not.toContain("Unapproved");
    expect(context.prompt).not.toContain("Tampered");
    expect(context.contextDigest).toMatch(/^[a-f0-9]{64}$/);
  });

  it.each([
    {
      title: "there are no hits",
      hits: [],
      allowedSourceIds: ["source-language"],
    },
    {
      title: "the node declares no sources",
      hits: [
        {
          sourceId: "source-language",
          courseId: "course-python",
          nodeId: "node-for-loop",
          title: "The for statement",
          url: "https://docs.python.org/3/reference/compound_stmts.html",
          excerpt: "for statement",
          excerptDigest: digest("for statement"),
          score: 1,
        },
      ],
      allowedSourceIds: [],
    },
  ])("refuses before model invocation when $title", ({ hits, allowedSourceIds }) => {
    expect(() =>
      buildSourceBoundContext(
        {
          question: "How does a loop work?",
          courseId: "course-python",
          nodeId: "node-for-loop",
          allowedSourceIds,
        },
        hits,
      ),
    ).toThrowError(NoSourcesError);

    try {
      buildSourceBoundContext(
        {
          question: "How does a loop work?",
          courseId: "course-python",
          nodeId: "node-for-loop",
          allowedSourceIds,
        },
        hits,
      );
    } catch (error) {
      expect(error).toMatchObject({ code: "NO_SOURCES", retryable: false });
    }
  });

  it("enforces the context budget without truncating a citation silently", () => {
    const excerpt = "A".repeat(80);
    const context = buildSourceBoundContext(
      {
        question: "Explain",
        courseId: "course-python",
        nodeId: "node-for-loop",
        allowedSourceIds: ["source-a", "source-b"],
        maxCharacters: 100,
      },
      [
        {
          sourceId: "source-a",
          courseId: "course-python",
          nodeId: "node-for-loop",
          title: "A",
          url: "https://docs.python.org/a",
          excerpt,
          excerptDigest: digest(excerpt),
          score: 1,
        },
        {
          sourceId: "source-b",
          courseId: "course-python",
          nodeId: "node-for-loop",
          title: "B",
          url: "https://docs.python.org/b",
          excerpt,
          excerptDigest: digest(excerpt),
          score: 0.9,
        },
      ],
    );

    expect(context.citations).toHaveLength(1);
    expect(context.prompt).toContain("[source:source-a]");
    expect(context.prompt).not.toContain("[source:source-b]");
  });
});
