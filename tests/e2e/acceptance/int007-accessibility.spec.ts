import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const webBase = process.env.PYMENTOR_WEB_URL ?? "http://127.0.0.1:4173";
const adminBase = process.env.PYMENTOR_ADMIN_URL ?? "http://127.0.0.1:4174";

async function expectNoSeriousViolations(page: Page, context: string) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const blocking = result.violations.filter((item) =>
    ["critical", "serious"].includes(item.impact ?? ""),
  );
  expect(blocking, `${context}: ${JSON.stringify(blocking, null, 2)}`).toEqual([]);
}

test("student critical path is keyboard-operable and WCAG AA clean", async ({ page }) => {
  await page.goto(`${webBase}/login`);
  await expect(page.getByRole("heading", { name: "欢迎回来" })).toBeVisible();
  await expectNoSeriousViolations(page, "student login");

  await page.keyboard.press("Tab");
  await expect(page.getByRole("textbox", { name: "学号或邮箱" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("密码")).toBeFocused();

  await page.getByRole("button", { name: "一键体验演示" }).click();
  await expect(page.getByRole("heading", { name: "今日学习工作台" })).toBeVisible();
  await expect(page.getByRole("progressbar", { name: "今日任务完成度" })).toHaveAttribute(
    "aria-valuenow",
    /\d+/,
  );
  await expectNoSeriousViolations(page, "student today");

  await page.getByRole("link", { name: "学习资源" }).click();
  await expect(page.getByRole("heading", { name: "服务端学习资源" })).toBeVisible();
  await expect(page.getByRole("status", { name: "资源生成进度" })).toContainText(
    /已可用|正在生成/,
  );
  await expectNoSeriousViolations(page, "student resources");

  await page.getByRole("link", { name: "向智能辅导提问" }).click();
  await expect(page.getByRole("heading", { name: "智能辅导" })).toBeVisible();
  await expectNoSeriousViolations(page, "student tutor");
  await page.getByRole("button", { name: "发送问题" }).click();
  await expect(page.getByRole("alert", { name: "辅导流中断" })).toBeVisible();
  await expect(page.getByRole("status", { name: "辅导流状态" })).toContainText(
    "流已中断",
  );
});

test("admin login surface is WCAG AA clean", async ({ page }) => {
  await page.goto(`${adminBase}/login`);
  await expect(page.getByRole("heading", { name: /管理/ })).toBeVisible();
  await expectNoSeriousViolations(page, "admin login");
});
