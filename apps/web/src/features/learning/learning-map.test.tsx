import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { StudentRoutes } from "../../student-routes";
import {
  classifyMapEmptyState,
  LearningMapEmptyState,
  LearningMapReasonPanel,
  synthesizePathReasoning,
  type LearningMapEmptyKind,
  type PathSummary,
} from "./learning-map";
import { studentSession } from "../auth/auth-session";

const demoSession = {
  ...studentSession,
  displayName: "演示访客",
  role: "demo" as const,
  userId: "demo-001",
};

function renderRoute(route: string, initialSession = studentSession) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <StudentRoutes initialSession={initialSession} />
    </MemoryRouter>,
  );
}

describe("synthesizePathReasoning", () => {
  it("explains a repaired path using validation metadata, not hardcoded evidence", () => {
    const summary: PathSummary = {
      totalSteps: 5,
      kindCounts: { LEARN: 3, PRACTICE: 1, REVIEW: 1, ASSESSMENT: 0 },
      validationCounts: { VALIDATED: 4, REPAIRED: 1, FALLBACK: 0 },
    };

    const reasoning = synthesizePathReasoning(summary, 7);

    expect(reasoning.narrative).toContain("修复");
    expect(reasoning.narrative).toContain("复测");
    // Honesty: must flag itself as synthesized and call out the BE follow-up.
    expect(reasoning.narrative).toMatch(/合成|后端/);
    // Must not leak the V1.0 hardcoded evidence text.
    expect(reasoning.narrative).not.toContain("EVD-1882");
    expect(reasoning.narrative).not.toContain("path-candidate-08");

    const versionRow = reasoning.evidenceRows.find((row) => row.label === "路径版本");
    expect(versionRow?.value).toBe("v7");
    const structureRow = reasoning.evidenceRows.find((row) => row.label === "节点构成");
    expect(structureRow?.value).toContain("学习 3");
    expect(structureRow?.value).toContain("复测 1");
    const validationRow = reasoning.evidenceRows.find((row) => row.label === "验证结果");
    expect(validationRow?.value).toContain("修复");
  });

  it("reports a fully validated learn-only path without claiming repairs", () => {
    const summary: PathSummary = {
      totalSteps: 3,
      kindCounts: { LEARN: 3, PRACTICE: 0, REVIEW: 0, ASSESSMENT: 0 },
      validationCounts: { VALIDATED: 3, REPAIRED: 0, FALLBACK: 0 },
    };

    const reasoning = synthesizePathReasoning(summary, 2);

    expect(reasoning.narrative).not.toContain("修复");
    expect(reasoning.narrative).toContain("学习");
    const validationRow = reasoning.evidenceRows.find((row) => row.label === "验证结果");
    expect(validationRow?.value).toContain("已验证");
  });
});

describe("LearningMapReasonPanel", () => {
  it("renders the synthesized narrative and evidence rows", () => {
    render(
      <MemoryRouter>
        <LearningMapReasonPanel
          reasoning={{
            narrative: "由路径元数据合成的说明。",
            evidenceRows: [
              { label: "路径版本", value: "v7" },
              { label: "节点总数", value: "5" },
            ],
          }}
        />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", { name: "为什么这样安排？" }),
    ).toBeVisible();
    expect(screen.getByText("由路径元数据合成的说明。")).toBeVisible();
    expect(screen.getByText("v7")).toBeVisible();
    expect(screen.getByText("5")).toBeVisible();
  });

  it("never renders the V1.0 hardcoded evidence identifiers", () => {
    const { container } = render(
      <MemoryRouter>
        <LearningMapReasonPanel
          reasoning={{
            narrative: "合成的说明。",
            evidenceRows: [{ label: "路径版本", value: "v7" }],
          }}
        />
      </MemoryRouter>,
    );

    expect(container.textContent).not.toContain("EVD-1882");
    expect(container.textContent).not.toContain("EVD-1901");
    expect(container.textContent).not.toContain("path-candidate-08");
  });
});

describe("LearningMapEmptyState", () => {
  const cases: ReadonlyArray<{
    kind: LearningMapEmptyKind;
    heading: string;
    snippet: string;
  }> = [
    {
      kind: "no-profile",
      heading: "还没有学习画像",
      snippet: "入门问卷",
    },
    {
      kind: "pending-path",
      heading: "画像已生成，等待路径编译",
      snippet: "路径编译",
    },
    {
      kind: "demo-guest",
      heading: "演示账号使用预置路径",
      snippet: "注册",
    },
    {
      kind: "pending-approval",
      heading: "账号待审批",
      snippet: "审批",
    },
    {
      kind: "no-tasks-today",
      heading: "今天还没有学习任务",
      snippet: "学习地图",
    },
  ];

  for (const { kind, heading, snippet } of cases) {
    it(`renders actionable copy for the ${kind} state`, () => {
      render(
        <MemoryRouter>
          <LearningMapEmptyState kind={kind} />
        </MemoryRouter>,
      );

      expect(
        screen.getByRole("heading", { name: heading }),
      ).toBeVisible();
      // Status panels use an aria-label equal to the title.
      const panel = screen.getByRole("status", { name: heading });
      expect(panel).toHaveTextContent(snippet);
    });
  }

  it("offers an onboarding CTA for the no-profile state", () => {
    render(
      <MemoryRouter>
        <LearningMapEmptyState kind="no-profile" />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("link", { name: "前往入门问卷" }),
    ).toHaveAttribute("href", "/onboarding");
  });

  it("offers a register CTA for the demo-guest state", () => {
    render(
      <MemoryRouter>
        <LearningMapEmptyState kind="demo-guest" />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("link", { name: "注册正式账号" }),
    ).toHaveAttribute("href", "/register");
  });
});

describe("classifyMapEmptyState", () => {
  it("routes demo users to the demo-guest state regardless of path data", () => {
    expect(classifyMapEmptyState({ role: "demo" })).toBe("demo-guest");
  });

  it("routes pending users to the pending-approval state", () => {
    expect(classifyMapEmptyState({ role: "student", status: "pending" })).toBe(
      "pending-approval",
    );
  });

  it("routes a missing profile to no-profile", () => {
    expect(
      classifyMapEmptyState({
        role: "student",
        pathStatus: 404,
        profileStatus: 404,
      }),
    ).toBe("no-profile");
  });

  it("routes a missing path with an existing profile to pending-path", () => {
    expect(
      classifyMapEmptyState({
        role: "student",
        pathStatus: 404,
        profileStatus: 200,
      }),
    ).toBe("pending-path");
  });

  it("returns null when the path is available", () => {
    expect(
      classifyMapEmptyState({ role: "student", pathStatus: 200 }),
    ).toBeNull();
  });
});

describe("LearningMapPage reason panel (fixture mode)", () => {
  it("renders synthesized metadata instead of the hardcoded V1.0 evidence", () => {
    renderRoute("/map");

    // The reason panel heading is still present.
    const reasonHeading = screen.getByRole("heading", {
      name: "为什么这样安排？",
    });
    expect(reasonHeading).toBeVisible();
    // Scope to the reason panel <aside> (the AppShell sidebar is also a
    // complementary region, so walk up from the heading instead).
    const panel = reasonHeading.closest("aside");
    expect(panel).not.toBeNull();
    // The hardcoded evidence identifiers must be gone.
    expect(panel!.textContent).not.toContain("EVD-1882");
    expect(panel!.textContent).not.toContain("EVD-1901");
    expect(panel!.textContent).not.toContain("path-candidate-08");
    // The synthesized version row should reference the fixture path version.
    expect(panel!.textContent).toContain("v7");
  });

  it("shows the demo-guest empty state for demo sessions", () => {
    renderRoute("/map", demoSession);

    expect(
      screen.getByRole("status", { name: "演示账号使用预置路径" }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: "注册正式账号" }),
    ).toBeVisible();
  });
});
