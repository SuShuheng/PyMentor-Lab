import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { StudentRoutes } from "./student-routes";
import { studentSession } from "./features/auth/auth-session";

describe("student application shell", () => {
  it("routes to Today and marks its navigation item as current", () => {
    render(
      <MemoryRouter initialEntries={["/today"]}>
        <StudentRoutes initialSession={studentSession} />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", { name: "今日学习工作台" }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "今日学习" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("renders the shared offline state from a route query", () => {
    render(
      <MemoryRouter initialEntries={["/today?view=offline"]}>
        <StudentRoutes initialSession={studentSession} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("当前处于离线状态");
    expect(screen.getByRole("button", { name: "重新连接" })).toBeVisible();
  });
});
