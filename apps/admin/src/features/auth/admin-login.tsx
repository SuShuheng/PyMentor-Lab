import {
  readServerUrl,
  saveServerUrl,
  testServerConnection,
} from "@pymentor/config";
import {
  ArrowRight,
  LockKey,
  PlugsConnected,
  ShieldCheck,
} from "@phosphor-icons/react";
import { useState } from "react";
import { Navigate } from "react-router-dom";

import { useAdminAuth } from "./auth-session";

export function AdminLoginPage() {
  const auth = useAdminAuth();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [serverUrl, setServerUrl] = useState(readServerUrl());
  const [serverMessage, setServerMessage] = useState<string | null>(null);
  const [serverOk, setServerOk] = useState(false);

  if (auth.status === "authenticated")
    return <Navigate replace to="/admin/overview" />;

  return (
    <main className="admin-auth-page">
      <div className="admin-auth-card">
        <span className="admin-auth-mark">
          <ShieldCheck size={28} weight="fill" />
        </span>
        <p className="eyebrow">PYMENTOR LAB · ADMIN</p>
        <h1>管理员登录</h1>
        <p className="admin-auth-lead">运营、审核与系统维护入口</p>
        <form
          className="admin-auth-form"
          onSubmit={(event) => {
            event.preventDefault();
            try {
              saveServerUrl(serverUrl);
              void auth.login({ identifier, password });
            } catch (error) {
              setServerOk(false);
              setServerMessage(
                error instanceof Error ? error.message : "服务器地址无效",
              );
            }
          }}
        >
          <label htmlFor="admin-identifier">管理员账号</label>
          <input
            autoComplete="username"
            id="admin-identifier"
            onChange={(event) => setIdentifier(event.target.value)}
            required
            value={identifier}
          />
          <label htmlFor="admin-password">密码</label>
          <div className="admin-password-field">
            <LockKey aria-hidden="true" size={17} />
            <input
              autoComplete="current-password"
              id="admin-password"
              minLength={8}
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </div>
          <label htmlFor="admin-server">服务器地址</label>
          <div className="admin-server-field">
            <input
              id="admin-server"
              onChange={(event) => setServerUrl(event.target.value)}
              value={serverUrl}
            />
            <button
              onClick={async () => {
                const result = await testServerConnection(serverUrl);
                setServerOk(result.ok);
                setServerMessage(result.message);
                if (result.ok) saveServerUrl(serverUrl);
              }}
              type="button"
            >
              <PlugsConnected size={16} /> 测试
            </button>
          </div>
          {serverMessage ? (
            <p
              className={serverOk ? "admin-field-success" : "admin-field-error"}
              role="status"
            >
              {serverMessage}
            </p>
          ) : null}
          {auth.errorMessage ? (
            <p className="admin-field-error" role="alert">
              {auth.errorMessage}
            </p>
          ) : null}
          <button
            className="admin-login-button"
            disabled={auth.status === "checking"}
            type="submit"
          >
            {auth.status === "checking" ? "正在验证…" : "登录管理端"}{" "}
            <ArrowRight size={18} />
          </button>
        </form>
        <p className="admin-security-note">
          仅授权管理员可访问 · 所有登录尝试均记入审计
        </p>
      </div>
    </main>
  );
}
