import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AppShell } from "./app-shell";

const navigation = [
  { href: "/today", label: "今日学习" },
  { href: "/lab", label: "代码实验" },
  { href: "/map", label: "学习地图" },
];

describe("AppShell", () => {
  it("exposes landmarks and the active route to assistive technology", () => {
    render(
      <AppShell
        activeHref="/today"
        brand="灵蟒智学"
        header={<span>Python 程序设计</span>}
        navigation={navigation}
      >
        <h1>今日学习工作台</h1>
      </AppShell>,
    );

    expect(screen.getByRole("navigation", { name: "主导航" })).toBeVisible();
    expect(screen.getByRole("link", { name: "今日学习" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");
    expect(screen.getByRole("banner")).toHaveTextContent("Python 程序设计");
  });

  it("places a skip link first in the keyboard order", async () => {
    const user = userEvent.setup();
    render(
      <AppShell activeHref="/today" brand="灵蟒智学" navigation={navigation}>
        <h1>今日学习工作台</h1>
      </AppShell>,
    );

    await user.tab();

    expect(screen.getByRole("link", { name: "跳到主要内容" })).toHaveFocus();
    expect(screen.getByRole("link", { name: "跳到主要内容" })).toHaveAttribute(
      "href",
      "#main-content",
    );
  });
});
