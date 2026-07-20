import {
  ArrowRight,
  CheckCircle,
  Eye,
  EyeSlash,
  Lightning,
  ShieldCheck,
  Sparkle,
} from "@phosphor-icons/react";
import type { ProviderConfigView, ProviderType } from "@pymentor/api-client";
import { readServerUrl } from "@pymentor/config";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { useAdminAuth } from "../auth/auth-session";
import {
  type ProviderConnectivityResult,
  configureAdminProviderClient,
  createProvider,
  fetchProviders,
  providerApiError,
  testProviderConnectivity,
} from "./admin-provider-api";
import { pickPresetForVendor } from "./admin-provider-presets";

/**
 * Application build version surfaced in the admin Settings and profile menu.
 * Bumped alongside the release notes; intentionally a literal so the admin
 * shell can render it without an extra build-time injection step.
 */
export const ADMIN_APP_VERSION = "1.1.0";

/**
 * The ordered set of "capability slots" the first-time guided setup walks the
 * System Admin through. Each slot is the FIRST provider_type that must exist
 * for the platform to be usable end-to-end:
 *   1. LLM  — the conversational backbone (Xunfei Spark / OpenAI / DeepSeek).
 *   2. The Xunfei media trio (TTS + ASR + OCR) — voice in/out and image OCR.
 *   3. MODERATION — content moderation, also Xunfei by default.
 *
 * These are advisory "guided" slots, not a hard gate. Admin can skip the
 * wizard entirely and use the full CRUD page; see "skip" link.
 */
type WizardSlotId = "llm" | "media" | "moderation";

const WIZARD_SLOTS: ReadonlyArray<{
  id: WizardSlotId;
  title: string;
  eyebrow: string;
  description: string;
  /** Provider types that satisfy this slot (ANY of them). */
  covers: ProviderType[];
}> = [
  {
    id: "llm",
    title: "LLM 对话 Provider",
    eyebrow: "STEP 1 · LLM",
    description: "对话大脑（讯飞星火 / OpenAI / DeepSeek 任选其一）。",
    covers: ["LLM"],
  },
  {
    id: "media",
    title: "讯飞 TTS/ASR/OCR",
    eyebrow: "STEP 2 · MEDIA",
    description: "语音合成、语音听写、文字识别（建议使用讯飞）。",
    covers: ["TTS", "ASR", "OCR"],
  },
  {
    id: "moderation",
    title: "讯飞内容审核",
    eyebrow: "STEP 3 · MODERATION",
    description: "内容审核（MODERATION），建议使用讯飞审核服务。",
    covers: ["MODERATION"],
  },
];

/**
 * Maps a slot to the (vendor, provider_type) pair the wizard creates by
 * default. The LLM step defaults to xfyun because the platform is built around
 * Spark; admin can switch to openai/deepseek in the LLM step's vendor select.
 */
const SLOT_DEFAULTS: Record<WizardSlotId, { vendor: string; type: ProviderType }> = {
  llm: { vendor: "xfyun", type: "LLM" },
  media: { vendor: "xfyun", type: "TTS" },
  moderation: { vendor: "xfyun", type: "MODERATION" },
};

/**
 * The LLM step exposes a fixed vendor menu (the three vendors with curated
 * presets). Other steps are Xunfei-only by design.
 */
const LLM_VENDOR_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "xfyun", label: "讯飞星火 (xfyun)" },
  { value: "openai", label: "OpenAI" },
  { value: "deepseek", label: "DeepSeek" },
];

function commandKey(prefix: string): string {
  return `${prefix}-${globalThis.crypto.randomUUID()}`;
}

/**
 * TanStack Query key for the settings page's masked provider list. Exported
 * (not module-private) so the create-then-test flow can invalidate exactly
 * this entry after a wizard create — without flushing the unrelated
 * /admin/providers page cache.
 */
export const PROVIDERS_QUERY_KEY = ["admin", "providers", "settings"] as const;

function slotLabelForType(type: ProviderType): string {
  switch (type) {
    case "LLM":
      return "LLM";
    case "TTS":
      return "TTS";
    case "ASR":
      return "ASR";
    case "OCR":
      return "OCR";
    case "MODERATION":
      return "MODERATION";
    case "IMAGE":
      return "IMAGE";
    case "EMBEDDING":
      return "EMBEDDING";
    default:
      return type;
  }
}

/**
 * Decides whether a capability slot is already satisfied by an existing
 * provider. The wizard uses this to render the ✓ marker and to know when to
 * show the "配置完成" banner.
 */
function isSlotComplete(
  slotId: WizardSlotId,
  providers: ProviderConfigView[],
): boolean {
  const slot = WIZARD_SLOTS.find((item) => item.id === slotId);
  if (!slot) return false;
  return providers.some((provider) => slot.covers.includes(provider.provider_type));
}

export function SettingsPage() {
  const { session } = useAdminAuth();
  const serverUrl = readServerUrl();
  const accessToken = session?.accessToken;
  const queryClient = useQueryClient();

  // TanStack Query: same pattern as OverviewPage. The list is masked + cheap;
  // a 30s staleTime keeps the settings page responsive when admins flip back
  // and forth to /admin/providers without hammering the list endpoint.
  const providersQuery = useQuery({
    queryKey: PROVIDERS_QUERY_KEY,
    queryFn: () => {
      configureAdminProviderClient();
      return fetchProviders({ accessToken: accessToken ?? "" });
    },
    enabled: Boolean(accessToken),
    staleTime: 30_000,
    gcTime: 5 * 60_000,
  });

  const providers = providersQuery.data ?? [];
  const providersEmpty = providers.length === 0;
  const isLoading = providersQuery.isLoading && Boolean(accessToken);
  const loadError = providersQuery.isError
    ? providersQuery.error instanceof Error
      ? providersQuery.error.message
      : "Provider 配置加载失败，请稍后重试"
    : null;

  // After a wizard create (or any future mutation here) invalidate the cached
  // list so the summary table and the wizard's ✓ markers re-sync immediately.
  // This deliberately does NOT touch the /admin/providers page cache — that
  // page manages its own state. We scope the invalidation to OUR query key.
  function invalidateProviders(): Promise<void> {
    return queryClient.invalidateQueries({ queryKey: PROVIDERS_QUERY_KEY });
  }

  return (
    <div className="admin-page">
      <div className="admin-page__heading">
        <div>
          <p className="eyebrow">ADMIN SETTINGS</p>
          <h1>管理端设置</h1>
          <p>查看当前会话、AI 服务商配置与首次部署引导。</p>
        </div>
      </div>

      <section className="admin-panel admin-panel--compact">
        <div className="admin-panel__heading">
          <div>
            <p className="eyebrow">SESSION</p>
            <h2>当前会话</h2>
          </div>
        </div>
        {/* FE Issue 7: styled as a labeled value-pair card via
            .admin-session-card (see apps/admin/src/index.css) instead of a
            bare <dl>, for visual consistency with the other admin panels. */}
        <dl className="admin-session-card">
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

      <ProviderConfigSection
        loadError={loadError}
        isLoading={isLoading}
        providers={providers}
      />

      {providersEmpty && !isLoading && !loadError ? (
        <FirstTimeSetupWizard
          accessToken={accessToken ?? null}
          onProviderChanged={invalidateProviders}
          providers={providers}
        />
      ) : null}
    </div>
  );
}

/**
 * Section 2 — a compact read-only summary of every configured Provider, plus a
 * deep-link to the full CRUD page. This section exists so an admin landing on
 * /admin/settings can SEE the AI/LLM/讯飞 configuration state without
 * navigating away. It is NOT a CRUD surface; edits happen at
 * /admin/providers (FE-016).
 */
function ProviderConfigSection({
  providers,
  isLoading,
  loadError,
}: {
  providers: ProviderConfigView[];
  isLoading: boolean;
  loadError: string | null;
}) {
  return (
    <section
      aria-labelledby="settings-providers-title"
      className="admin-panel admin-panel--compact"
    >
      <div className="admin-panel__heading">
        <div>
          <p className="eyebrow">AI PROVIDERS</p>
          <h2 id="settings-providers-title">AI 服务商配置</h2>
          <p>
            讯飞 API 与 LLM 服务商（OpenAI / DeepSeek 等）的当前配置摘要。完整增删改查请前往
            Provider 管理页。
          </p>
        </div>
        <Link className="admin-filter-button" to="/admin/providers">
          前往 Provider 管理页 <ArrowRight size={16} />
        </Link>
      </div>
      {isLoading ? <p role="status">正在加载 Provider 配置…</p> : null}
      {loadError ? <p role="alert">{loadError}</p> : null}
      {!isLoading && !loadError ? (
        <table aria-label="已配置 Provider 摘要" className="admin-data-table">
          <thead>
            <tr>
              <th>Provider</th>
              <th>能力</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {providers.length === 0 ? (
              <tr>
                <td colSpan={3}>
                  <em>尚未配置任何 Provider，参见下方"首次配置引导"。</em>
                </td>
              </tr>
            ) : (
              providers.map((provider) => (
                <tr key={provider.id}>
                  <th scope="row">
                    <strong>{provider.vendor}</strong>
                    <small>
                      {provider.model} · v{provider.version}
                    </small>
                  </th>
                  <td>{provider.provider_type}</td>
                  <td>
                    <span className={`admin-badge is-${provider.enabled ? "active" : "paused"}`}>
                      {provider.enabled ? "ACTIVE" : "DISABLED"}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      ) : null}
      <p className="admin-authority-note">
        <ShieldCheck size={15} /> 密钥由后端 AES-GCM 加密保存，本页只显示 mask。完整启停、删除、
        候选密钥测试请前往 <Link to="/admin/providers">Provider 管理页</Link>。
      </p>
    </section>
  );
}

/**
 * Section 3 — first-time guided setup. Rendered ONLY when no Provider is
 * configured yet (the list is empty). Each slot has its own card; completing
 * slot N visually unlocks slot N+1 (no enforcement). Admin can always skip to
 * the full CRUD page via the "跳过引导" link.
 *
 * TEST-BEFORE-CREATE LIMITATION (documented inline): the BE-019 test endpoint
 * is `POST /{id}/test` — it requires an EXISTING provider id, because the
 * candidate-key probe needs a saved row to test against. We cannot probe a
 * pure-candidate key before the provider exists. The wizard therefore uses a
 * "create-then-test" flow: on "创建并启用" it creates the provider with
 * `enabled=true`, then immediately calls `POST /{id}/test`. If the test fails
 * the wizard tells the admin (they can fix the key in the CRUD page or delete
 * the row). This is honest about the API surface rather than pretending to
 * validate a key that the backend has nowhere to store yet.
 */
function FirstTimeSetupWizard({
  providers,
  accessToken,
  onProviderChanged,
}: {
  providers: ProviderConfigView[];
  accessToken: string | null;
  onProviderChanged: () => Promise<void> | void;
}) {
  return (
    <section
      aria-labelledby="settings-wizard-title"
      className="admin-panel admin-panel--compact admin-setup-wizard"
    >
      <div className="admin-panel__heading">
        <div>
          <p className="eyebrow">FIRST-RUN GUIDED SETUP</p>
          <h2 id="settings-wizard-title">首次配置引导</h2>
          <p>
            新部署后，按下方三步完成讯飞 API 与 LLM 服务商的最小可用配置。每步完成会显示 ✓，
            全部完成后即可投入使用。
          </p>
        </div>
        <Link className="admin-setup-skip" to="/admin/providers">
          跳过引导，前往 Provider 管理页 <ArrowRight size={16} />
        </Link>
      </div>
      <p className="admin-provider-field-hint">
        预设值可编辑（仅起始值，并非官方验证；端点/模型可能随供应商更新而变化）。
      </p>
      <ol className="admin-setup-wizard__steps">
        {WIZARD_SLOTS.map((slot) => (
          <WizardStepCard
            accessToken={accessToken}
            covers={slot.covers}
            description={slot.description}
            eyebrow={slot.eyebrow}
            id={slot.id}
            isComplete={isSlotComplete(slot.id, providers)}
            key={slot.id}
            onProviderChanged={onProviderChanged}
            providers={providers}
            title={slot.title}
          />
        ))}
      </ol>
      <WizardCompletionBanner providers={providers} />
    </section>
  );
}

/**
 * A single capability-slot card. Carries its own minimal form state (vendor is
 * fixed except in the LLM step; preset-driven model/endpoint; an API key
 * field; a create-and-test action). Local state keeps each step independent.
 */
function WizardStepCard({
  id,
  title,
  eyebrow,
  description,
  covers,
  providers,
  isComplete,
  accessToken,
  onProviderChanged,
}: {
  id: WizardSlotId;
  title: string;
  eyebrow: string;
  description: string;
  covers: ProviderType[];
  providers: ProviderConfigView[];
  isComplete: boolean;
  accessToken: string | null;
  onProviderChanged: () => Promise<void> | void;
}) {
  // The LLM step lets the admin pick a vendor; the others are Xunfei-locked.
  // The LLM step always targets the "LLM" capability regardless of vendor
  // (every preset vendor in the menu ships an LLM preset).
  const allowVendorSwitch = id === "llm";
  const initialVendor = SLOT_DEFAULTS[id].vendor;
  const providerType = SLOT_DEFAULTS[id].type;

  const [vendor, setVendor] = useState(initialVendor);

  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [revealKey, setRevealKey] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function applyPreset(): void {
    const preset = pickPresetForVendor(vendor, providerType);
    if (!preset) {
      setStatus(`未找到 ${vendor} · ${providerType} 的预设，请手动填写。`);
      return;
    }
    setModel(preset.model);
    setEndpoint(preset.endpoint);
    setStatus(`已应用预设：${preset.label}（模型/端点可编辑）`);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!accessToken) {
      setStatus("管理员会话缺少访问令牌，请重新登录");
      return;
    }
    if (apiKey.length < 8) {
      setStatus("API Key 至少 8 个字符");
      return;
    }
    if (model.trim().length === 0) {
      setStatus("请先点击「应用预设」或手动填写模型");
      return;
    }
    setBusy(true);
    setStatus(`正在创建并启用 ${vendor} · ${providerType}…`);
    configureAdminProviderClient();
    try {
      // Create-then-test flow (documented above). Idempotency-Key keeps a
      // double-click safe.
      const created = await createProvider(
        {
          provider_type: providerType,
          vendor: vendor.trim(),
          model: model.trim(),
          api_key: apiKey,
          endpoint: endpoint.trim() || null,
          params: {},
          enabled: true,
        },
        {
          accessToken,
          idempotencyKey: commandKey("provider-create"),
        },
      );
      // Probe the freshly-created provider. A failure here is informational —
      // the row already exists, so we tell the admin how to recover.
      const probe = await runConnectivityProbe(accessToken, created.id);
      setStatus(formatWizardResult(vendor, created, probe));
      setApiKey("");
      setRevealKey(false);
      // Re-sync the summary table + wizard ✓ markers. We do NOT await this —
      // the user already has their status line and the refetch lands in the
      // background.
      void onProviderChanged();
    } catch (error) {
      setStatus(providerApiError(error, "Provider 创建失败，请稍后重试"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li
      aria-label={title}
      className={`admin-setup-wizard__step${isComplete ? " is-complete" : ""}`}
      data-testid={`wizard-step-${covers[0]}`}
    >
      <header className="admin-setup-wizard__step-header">
        <p className="eyebrow">{eyebrow}</p>
        <h3>
          {isComplete ? <CheckCircle size={18} weight="fill" /> : null}
          {title}
          {isComplete ? <span className="admin-setup-wizard__done">✓ 已配置</span> : null}
        </h3>
        <p>{description}</p>
        {isComplete ? (
          <p className="admin-setup-wizard__covered">
            已存在 {covers.map((type) => slotLabelForType(type)).join(" / ")} 类型 Provider。
          </p>
        ) : null}
      </header>
      {isComplete ? null : (
        <form className="admin-provider-form admin-setup-wizard__form" onSubmit={handleSubmit}>
          {allowVendorSwitch ? (
            <>
              <label htmlFor={`wizard-${id}-vendor`}>服务商</label>
              <select
                id={`wizard-${id}-vendor`}
                onChange={(event) => {
                  setVendor(event.target.value);
                  // Reset preset-derived fields so a stale model doesn't leak
                  // across vendors; the admin clicks 应用预设 again to refill.
                  setModel("");
                  setEndpoint("");
                }}
                value={vendor}
              >
                {LLM_VENDOR_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </>
          ) : (
            <p className="admin-provider-field-hint">
              服务商：<strong>{vendor}</strong>（本步骤默认使用讯飞）
            </p>
          )}

          <div className="admin-provider-preset-row">
            <button
              aria-label="应用预设"
              className="admin-provider-preset-apply"
              disabled={busy}
              onClick={applyPreset}
              type="button"
            >
              <Lightning size={14} /> 应用预设
            </button>
            <small className="admin-provider-field-hint">
              将填入 {vendor} · {providerType} 的推荐模型与端点（仍可编辑）。
            </small>
          </div>

          <label htmlFor={`wizard-${id}-type`}>能力</label>
          <select
            disabled={!allowVendorSwitch}
            id={`wizard-${id}-type`}
            // The type is fixed per slot (LLM/TTS/MODERATION). `disabled`
            // communicates this visually; the value is still submitted because
            // we render it as the selected <option>.
            value={providerType}
          >
            {covers.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
            {!covers.includes(providerType) ? (
              <option value={providerType}>{providerType}</option>
            ) : null}
          </select>

          <label htmlFor={`wizard-${id}-model`}>模型</label>
          <input
            id={`wizard-${id}-model`}
            onChange={(event) => setModel(event.target.value)}
            pattern="[A-Za-z0-9._:/-]+"
            placeholder="点击「应用预设」或手动填写"
            required
            value={model}
          />

          <label htmlFor={`wizard-${id}-endpoint`}>Endpoint</label>
          <input
            id={`wizard-${id}-endpoint`}
            onChange={(event) => setEndpoint(event.target.value)}
            placeholder="https://provider.example.test/v1"
            value={endpoint}
          />

          <div className="admin-provider-field-row">
            <label htmlFor={`wizard-${id}-api-key`}>API Key</label>
            <button
              aria-label={revealKey ? "隐藏 API Key" : "显示 API Key"}
              className="admin-provider-reveal"
              onClick={() => setRevealKey((current) => !current)}
              type="button"
            >
              {revealKey ? <EyeSlash size={14} /> : <Eye size={14} />}
              {revealKey ? "隐藏" : "显示"}
            </button>
          </div>
          <input
            autoComplete="off"
            id={`wizard-${id}-api-key`}
            minLength={8}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder="至少 8 个字符，提交后由后端加密保存"
            required
            type={revealKey ? "text" : "password"}
            value={apiKey}
          />
          <small className="admin-provider-field-hint">
            创建并启用后将立即测试连通性；如失败可在 Provider 管理页修复或删除。
          </small>

          <div className="admin-setup-wizard__actions">
            <button className="is-primary" disabled={busy} type="submit">
              <Sparkle size={14} /> {busy ? "处理中…" : "创建并启用"}
            </button>
          </div>
          {status ? (
            <p aria-label={`${title} 状态`} className="admin-inline-status" role="status">
              {status}
            </p>
          ) : null}
        </form>
      )}
    </li>
  );
}

/**
 * Thin wrapper around `testProviderConnectivity` that swallows transport
 * errors into a standardized "probe failed" result. The wizard does NOT throw
 * on probe failure — the provider was already created; the admin needs the
 * status text to decide whether to fix or delete the row.
 */
async function runConnectivityProbe(
  accessToken: string,
  providerId: string,
): Promise<ProviderConnectivityResult | null> {
  try {
    return await testProviderConnectivity({ accessToken, providerId });
  } catch {
    return null;
  }
}

function formatWizardResult(
  vendor: string,
  created: ProviderConfigView,
  probe: ProviderConnectivityResult | null,
): string {
  const base = `${vendor} 已创建并启用（${created.provider_type}）· 版本 v${created.version}`;
  if (!probe) return `${base} · 连通性测试请求失败，请稍后在 Provider 管理页重试`;
  if (probe.ok) {
    return `${base} · 连接成功 · ${probe.latency_ms}ms${
      probe.model_id ? ` · ${probe.model_id}` : ""
    }`;
  }
  const reason = [probe.detail, probe.error_code ? `error_code=${probe.error_code}` : ""]
    .filter((segment) => segment && segment.length > 0)
    .join(" · ");
  return `${base} · 连接失败${reason ? `（${reason}）` : ""} · 可在 Provider 管理页修复`;
}

/**
 * Renders the "配置完成" banner once every guided slot is satisfied. Hidden
 * until all three slots are green.
 */
function WizardCompletionBanner({ providers }: { providers: ProviderConfigView[] }) {
  const allComplete = useMemo(
    () => WIZARD_SLOTS.every((slot) => isSlotComplete(slot.id, providers)),
    [providers],
  );
  if (!allComplete) return null;
  return (
    <div className="admin-setup-wizard__complete" role="status">
      <CheckCircle size={20} weight="fill" />
      <div>
        <strong>🎉 配置完成</strong>
        <p>
          LLM、讯飞媒体与内容审核均已就绪。前往{" "}
          <Link to="/admin/providers">Provider 管理页</Link>{" "}
          进行后续维护（启停、密钥轮换、候选测试、删除）。
        </p>
      </div>
    </div>
  );
}
