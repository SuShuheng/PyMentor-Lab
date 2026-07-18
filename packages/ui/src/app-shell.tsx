import {
  BracketsCurly,
  Gear,
  TerminalWindow,
  WifiHigh,
} from "@phosphor-icons/react";
import type { ReactNode } from "react";

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
  subtitle?: string;
  variant?: "student" | "admin";
}

export function AppShell({
  activeHref,
  brand,
  children,
  header,
  navigation,
  subtitle = "PyMentor Lab",
  variant = "student",
}: AppShellProps) {
  return (
    <div className={`py-shell py-shell--${variant}`}>
      <a className="py-skip-link" href="#main-content">
        跳到主要内容
      </a>
      <aside className="py-sidebar">
        <a
          className="py-brand"
          href={variant === "student" ? "/today" : "/admin"}
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
              <strong>
                {variant === "student" ? "AI 助教 · 在线" : "系统状态正常"}
              </strong>
              <small>
                {variant === "student" ? "随时为你答疑解惑" : "全部服务可用"}
              </small>
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
        <header className="py-header">
          {header ?? <strong>{brand}</strong>}
        </header>
        <main className="py-main" id="main-content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
