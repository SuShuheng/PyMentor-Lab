import { BracketsCurly, Gear, TerminalWindow, WifiHigh } from "@phosphor-icons/react";
import type { MouseEvent, ReactNode } from "react";

export interface NavigationItem {
  href: string;
  label: string;
  icon?: ReactNode;
}

export interface AppShellProps {
  activeHref: string;
  brand: string;
  children: ReactNode;
  header?: ReactNode;
  navigation: readonly NavigationItem[];
  onNavigate?: (href: string) => void;
  status?: {
    detail: string;
    label: string;
  };
  subtitle?: string;
  variant?: "student" | "admin";
}

export function AppShell({
  activeHref,
  brand,
  children,
  header,
  navigation,
  onNavigate,
  status,
  subtitle = "PyMentor Lab",
  variant = "student",
}: AppShellProps) {
  function handleNavigation(event: MouseEvent<HTMLAnchorElement>, href: string) {
    if (
      !onNavigate ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    event.preventDefault();
    onNavigate(href);
  }

  const homeHref = variant === "student" ? "/today" : "/admin";
  const shellStatus =
    status ??
    (variant === "student"
      ? { label: "AI 助教 · 在线", detail: "随时为你答疑解惑" }
      : { label: "系统状态未知", detail: "打开运行监控查看实时状态" });

  return (
    <div className={`py-shell py-shell--${variant}`}>
      <a className="py-skip-link" href="#main-content">
        跳到主要内容
      </a>
      <aside className="py-sidebar">
        <a
          className="py-brand"
          href={homeHref}
          onClick={(event) => handleNavigation(event, homeHref)}
        >
          <span className="py-brand__mark" aria-hidden="true">
            <BracketsCurly size={30} weight="bold" />
          </span>
          <span>
            <strong>{brand}</strong>
            <small>{subtitle}</small>
          </span>
        </a>

        <nav aria-label="主导航" className="py-navigation">
          {navigation.map((item) => {
            const isCurrent = item.href === activeHref;
            return (
              <a
                aria-current={isCurrent ? "page" : undefined}
                className={isCurrent ? "py-nav-link is-current" : "py-nav-link"}
                href={item.href}
                key={item.href}
                onClick={(event) => handleNavigation(event, item.href)}
              >
                {item.icon ? (
                  <span aria-hidden="true" className="py-nav-link__icon">
                    {item.icon}
                  </span>
                ) : null}
                <span>{item.label}</span>
              </a>
            );
          })}
        </nav>

        <div className="py-sidebar__footer">
          <div className="py-assistant-status" role="status">
            <WifiHigh aria-hidden="true" size={18} />
            <span>
              <strong>{shellStatus.label}</strong>
              <small>{shellStatus.detail}</small>
            </span>
          </div>
          <div className="py-sidebar__tools" aria-label="快捷工具">
            <button aria-label="设置" type="button">
              <Gear size={22} />
            </button>
            <button aria-label="打开控制台" type="button">
              <TerminalWindow size={22} />
            </button>
          </div>
        </div>
      </aside>

      <div className="py-workspace">
        <header className="py-header">{header ?? <strong>{brand}</strong>}</header>
        <main className="py-main" id="main-content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
