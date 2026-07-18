import {
  readServerUrl,
  saveServerUrl,
  testServerConnection,
  type ServerConnectionResult,
} from "@pymentor/config";
import {
  ArrowRight,
  CheckCircle,
  PlugsConnected,
  ShieldCheck,
  Student,
} from "@phosphor-icons/react";
import { StatePanel } from "@pymentor/ui";
import { motion, useReducedMotion } from "framer-motion";
import { useEffect, useState } from "react";
import { useForm, type UseFormRegisterReturn } from "react-hook-form";
import { Link, Navigate } from "react-router-dom";
import { z } from "zod";

import { useAuth } from "./auth-session";

const loginSchema = z.object({
  identifier: z.string().trim().min(1, "请输入学号或邮箱"),
  password: z.string().min(8, "密码至少需要 8 位"),
  serverUrl: z.string().trim().min(1, "请输入服务器地址"),
});

const registerSchema = loginSchema.omit({ identifier: true }).extend({
  displayName: z.string().trim().min(2, "姓名至少需要 2 个字符"),
  email: z.string().email("请输入有效邮箱"),
  studentId: z.string().trim().min(4, "请输入有效学号"),
});

type LoginValues = z.infer<typeof loginSchema>;
type RegisterValues = z.infer<typeof registerSchema>;

function ServerField({
  error,
  serverField,
  value,
}: {
  error?: string;
  serverField: UseFormRegisterReturn<"serverUrl">;
  value: string;
}) {
  const [connection, setConnection] = useState<ServerConnectionResult | null>(
    null,
  );
  const [testing, setTesting] = useState(false);

  return (
    <div className="auth-server-field">
      <label htmlFor="serverUrl">服务器地址</label>
      <div className="auth-server-field__control">
        <input
          aria-describedby={
            error
              ? "serverUrl-error"
              : connection
                ? "serverUrl-result"
                : undefined
          }
          aria-invalid={Boolean(error)}
          id="serverUrl"
          {...serverField}
        />
        <button
          disabled={testing}
          onClick={async () => {
            setTesting(true);
            const result = await testServerConnection(value);
            setConnection(result);
            if (result.ok) saveServerUrl(value);
            setTesting(false);
          }}
          type="button"
        >
          <PlugsConnected size={16} /> {testing ? "连接中" : "测试连接"}
        </button>
      </div>
      {error ? (
        <p className="field-error" id="serverUrl-error">
          {error}
        </p>
      ) : connection ? (
        <p
          className={connection.ok ? "field-success" : "field-error"}
          id="serverUrl-result"
          role="status"
        >
          {connection.message}
        </p>
      ) : (
        <p className="field-help">支持本机、局域网或云端 http(s) 地址</p>
      )}
    </div>
  );
}

function AuthFrame({
  children,
  eyebrow,
  title,
}: {
  children: React.ReactNode;
  eyebrow: string;
  title: string;
}) {
  const reducedMotion = useReducedMotion();

  return (
    <main className="auth-page">
      <section className="auth-brand-panel" aria-labelledby="auth-brand-title">
        <div className="auth-brand">
          <span>
            <Student size={28} weight="bold" />
          </span>
          <strong>灵蟒智学</strong>
        </div>
        <div>
          <p className="eyebrow">PYMENTOR LAB</p>
          <h1 id="auth-brand-title">
            让每一次练习，都有证据、有路径、有反馈。
          </h1>
          <p>围绕真实代码轨迹构建你的 Python 学习画像。</p>
        </div>
        <ul className="auth-proof-list">
          <li>
            <CheckCircle size={18} weight="fill" /> 个性化任务路径
          </li>
          <li>
            <CheckCircle size={18} weight="fill" /> 可追溯学习证据
          </li>
          <li>
            <CheckCircle size={18} weight="fill" /> 安全沙箱与即时反馈
          </li>
        </ul>
      </section>
      <motion.div
        animate={{ opacity: 1, y: 0 }}
        className="auth-card"
        initial={reducedMotion ? false : { opacity: 0.01, y: 10 }}
        transition={{
          duration: reducedMotion ? 0 : 0.24,
          ease: [0.2, 0.8, 0.2, 1],
        }}
      >
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        {children}
      </motion.div>
    </main>
  );
}

function AuthOutcome() {
  const { clearOutcome, errorMessage, refresh, status } = useAuth();

  if (status === "pending") {
    return (
      <StatePanel
        actionLabel="返回登录"
        description="注册资料已提交，管理员审核通过后即可登录"
        onAction={clearOutcome}
        state="success"
        title="账号正在审核"
      />
    );
  }
  if (status === "rejected") {
    return (
      <StatePanel
        actionLabel="更新注册资料"
        description={errorMessage ?? "账号申请未通过，请核对资料后重新提交"}
        onAction={clearOutcome}
        state="error"
        title="账号申请未通过"
      />
    );
  }
  if (status === "refresh-failed") {
    return (
      <StatePanel
        actionLabel="重试会话刷新"
        description={errorMessage ?? "请检查服务器连接后重试"}
        onAction={() => void refresh()}
        state="offline"
        title="无法恢复登录会话"
      />
    );
  }
  return null;
}

export function LoginPage() {
  const auth = useAuth();
  const form = useForm<LoginValues>({
    defaultValues: { identifier: "", password: "", serverUrl: readServerUrl() },
  });
  const serverUrl = form.watch("serverUrl");

  useEffect(() => {
    if (auth.status === "anonymous") auth.clearOutcome();
  }, []);

  if (auth.status === "authenticated") return <Navigate replace to="/today" />;
  const outcome = <AuthOutcome />;
  if (
    outcome &&
    ["pending", "rejected", "refresh-failed"].includes(auth.status)
  ) {
    return (
      <AuthFrame eyebrow="ACCOUNT STATUS" title="登录状态">
        {outcome}
      </AuthFrame>
    );
  }

  return (
    <AuthFrame eyebrow="WELCOME BACK" title="欢迎回来">
      <p className="auth-card__lead">使用学校账号继续你的学习旅程</p>
      <form
        className="auth-form"
        onSubmit={form.handleSubmit(async (values) => {
          const parsed = loginSchema.safeParse(values);
          if (!parsed.success) {
            for (const issue of parsed.error.issues) {
              const field = issue.path[0];
              if (
                field === "identifier" ||
                field === "password" ||
                field === "serverUrl"
              ) {
                form.setError(field, { message: issue.message });
              }
            }
            return;
          }
          const {
            identifier,
            password,
            serverUrl: nextServerUrl,
          } = parsed.data;
          try {
            saveServerUrl(nextServerUrl);
          } catch (error) {
            form.setError("serverUrl", {
              message: error instanceof Error ? error.message : "地址无效",
            });
            return;
          }
          await auth.login({ identifier, password });
        })}
      >
        <label htmlFor="identifier">学号或邮箱</label>
        <input
          aria-describedby={
            form.formState.errors.identifier ? "identifier-error" : undefined
          }
          aria-invalid={Boolean(form.formState.errors.identifier)}
          autoComplete="username"
          id="identifier"
          placeholder="20260001 / name@example.edu"
          {...form.register("identifier")}
        />
        {form.formState.errors.identifier ? (
          <p className="field-error" id="identifier-error">
            {form.formState.errors.identifier.message}
          </p>
        ) : null}

        <label htmlFor="password">密码</label>
        <input
          aria-describedby={
            form.formState.errors.password ? "password-error" : undefined
          }
          aria-invalid={Boolean(form.formState.errors.password)}
          autoComplete="current-password"
          id="password"
          type="password"
          {...form.register("password")}
        />
        {form.formState.errors.password ? (
          <p className="field-error" id="password-error">
            {form.formState.errors.password.message}
          </p>
        ) : null}

        <ServerField
          error={form.formState.errors.serverUrl?.message}
          serverField={form.register("serverUrl")}
          value={serverUrl}
        />
        {auth.status === "error" ? (
          <p className="auth-error" role="alert">
            {auth.errorMessage}
          </p>
        ) : null}
        <button
          className="auth-submit"
          disabled={auth.status === "checking"}
          type="submit"
        >
          {auth.status === "checking" ? "正在登录…" : "登录"}{" "}
          <ArrowRight size={18} />
        </button>
      </form>
      <div className="auth-divider">
        <span>或</span>
      </div>
      <button
        className="auth-demo"
        disabled={auth.status === "checking"}
        onClick={() => void auth.startDemo()}
        type="button"
      >
        <ShieldCheck size={19} /> 一键体验演示
      </button>
      <p className="auth-switch">
        没有账号？ <Link to="/register">提交注册申请</Link>
      </p>
    </AuthFrame>
  );
}

export function RegisterPage() {
  const auth = useAuth();
  const form = useForm<RegisterValues>({
    defaultValues: {
      displayName: "",
      email: "",
      password: "",
      serverUrl: readServerUrl(),
      studentId: "",
    },
  });
  const serverUrl = form.watch("serverUrl");

  const outcome = <AuthOutcome />;
  if (outcome && ["pending", "rejected"].includes(auth.status)) {
    return (
      <AuthFrame eyebrow="ACCOUNT REVIEW" title="注册申请">
        {outcome}
      </AuthFrame>
    );
  }

  return (
    <AuthFrame eyebrow="CREATE ACCOUNT" title="申请学生账号">
      <p className="auth-card__lead">
        提交后由管理员审核，审核期间不会创建正式学习数据
      </p>
      <form
        className="auth-form auth-form--register"
        onSubmit={form.handleSubmit(async (values) => {
          const parsed = registerSchema.safeParse(values);
          if (!parsed.success) {
            for (const issue of parsed.error.issues) {
              const field = issue.path[0];
              if (
                field === "displayName" ||
                field === "email" ||
                field === "password" ||
                field === "serverUrl" ||
                field === "studentId"
              ) {
                form.setError(field, { message: issue.message });
              }
            }
            return;
          }
          const { serverUrl: nextServerUrl, ...input } = parsed.data;
          try {
            saveServerUrl(nextServerUrl);
          } catch (error) {
            form.setError("serverUrl", {
              message: error instanceof Error ? error.message : "地址无效",
            });
            return;
          }
          await auth.register(input);
        })}
      >
        {(
          [
            ["displayName", "姓名", "text", "你的真实姓名"],
            ["studentId", "学号", "text", "20260001"],
            ["email", "学校邮箱", "email", "name@example.edu"],
            ["password", "密码", "password", "至少 8 位"],
          ] as const
        ).map(([name, label, type, placeholder]) => (
          <div className="auth-field" key={name}>
            <label htmlFor={name}>{label}</label>
            <input
              aria-describedby={
                form.formState.errors[name] ? `${name}-error` : undefined
              }
              aria-invalid={Boolean(form.formState.errors[name])}
              id={name}
              placeholder={placeholder}
              type={type}
              {...form.register(name)}
            />
            {form.formState.errors[name] ? (
              <p className="field-error" id={`${name}-error`}>
                {form.formState.errors[name]?.message}
              </p>
            ) : null}
          </div>
        ))}
        <ServerField
          error={form.formState.errors.serverUrl?.message}
          serverField={form.register("serverUrl")}
          value={serverUrl}
        />
        {auth.status === "error" ? (
          <p className="auth-error" role="alert">
            {auth.errorMessage}
          </p>
        ) : null}
        <button
          className="auth-submit"
          disabled={auth.status === "checking"}
          type="submit"
        >
          {auth.status === "checking" ? "正在提交…" : "提交审核"}{" "}
          <ArrowRight size={18} />
        </button>
      </form>
      <p className="auth-switch">
        已有账号？ <Link to="/login">返回登录</Link>
      </p>
    </AuthFrame>
  );
}
