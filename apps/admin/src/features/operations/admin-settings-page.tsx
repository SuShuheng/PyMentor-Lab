import { readServerUrl } from "@pymentor/config";

import { useAdminAuth } from "../auth/auth-session";

/**
 * Application build version surfaced in the admin Settings and profile menu.
 * Bumped alongside the release notes; intentionally a literal so the admin
 * shell can render it without an extra build-time injection step.
 */
export const ADMIN_APP_VERSION = "1.1.0";

export function SettingsPage() {
  const { session } = useAdminAuth();
  const serverUrl = readServerUrl();

  return (
    <div className="admin-page">
      <div className="admin-page__heading">
        <div>
          <p className="eyebrow">ADMIN SETTINGS</p>
          <h1>管理端设置</h1>
          <p>查看当前管理端会话、服务地址与版本信息。</p>
        </div>
      </div>
      <section className="admin-panel admin-panel--compact">
        <div className="admin-panel__heading">
          <div>
            <p className="eyebrow">SESSION</p>
            <h2>当前会话</h2>
          </div>
        </div>
        <dl>
          <div>
            <dt>显示名</dt>
            <dd>{session?.displayName ?? "-"}</dd>
          </div>
          <div>
            <dt>角色</dt>
            <dd>{session?.role ?? "-"}</dd>
          </div>
          <div>
            <dt>用户 ID</dt>
            <dd>{session?.userId ?? "-"}</dd>
          </div>
          <div>
            <dt>服务地址</dt>
            <dd>
              <code>{serverUrl}</code>
            </dd>
          </div>
          <div>
            <dt>版本</dt>
            <dd>v{ADMIN_APP_VERSION}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
