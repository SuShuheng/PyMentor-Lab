import { Check, Pencil, Play, Sparkle, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import { useAdminAuth } from "../auth/auth-session";
import {
  AGENT_PROMPT_NODES,
  agentPromptIdempotencyKey,
  type AgentPromptNode,
  type AgentPromptVersion,
  dryRunAgentPrompt,
  fetchAgentPromptHistory,
  fetchCurrentAgentPrompt,
  publishAgentPromptVersion,
  saveAgentPromptDraft,
} from "./admin-agent-prompt-api";

type LoadState = "error" | "loading" | "ready";

type DraftState = {
  /** Most recent saved draft (or published baseline if no draft exists yet). */
  version: number | null;
  /** Text currently in the textarea; may differ from `savedText`. */
  promptText: string;
  /** Last persisted prompt text; drives the dirty flag and save button. */
  savedText: string;
};

/**
 * Admin-only Agent prompt tuning page (FE-017).
 *
 * Consumes BE-020 (`/api/v1/admin/agent-prompts`) through the typed wrapper
 * in `admin-agent-prompt-api.ts`. Lets a System Admin:
 *  - pick one of the six agent nodes (orchestrator/profile/path/resource/coach/assessment)
 *  - read the currently published prompt + versioned audit trail
 *  - edit a draft and save it as a new idempotent version
 *  - promote a saved draft to the live prompt through a confirmation gate
 *  - invoke the dry-run stub, which honestly surfaces BE-020's
 *    `implemented=false` note instead of fabricating an evaluation result.
 *
 * The page never renders raw student PII alongside prompts; publish and
 * save operations are server-side audited and idempotent.
 */
export function AgentTuningPage() {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;

  const [node, setNode] = useState<AgentPromptNode>("coach");
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [current, setCurrent] = useState<AgentPromptVersion | null>(null);
  const [history, setHistory] = useState<AgentPromptVersion[]>([]);
  const [draft, setDraft] = useState<DraftState>({
    version: null,
    promptText: "",
    savedText: "",
  });
  const draftIsDirty = draft.promptText !== draft.savedText;
  const [status, setStatus] = useState<string | null>(null);
  const [statusTone, setStatusTone] = useState<"error" | "info">("info");
  const [busy, setBusy] = useState<"dry-run" | "publish" | "save" | null>(null);
  const [pendingPublish, setPendingPublish] = useState<DraftState | null>(null);

  // Load current + history whenever the selected node or token changes.
  useEffect(() => {
    let active = true;
    setLoadState("loading");
    setLoadError(null);
    setStatus(null);
    if (!accessToken) {
      setLoadState("error");
      setLoadError("管理员会话缺少访问令牌，请重新登录");
      return () => {
        active = false;
      };
    }
    void Promise.all([
      fetchCurrentAgentPrompt({ accessToken, node }),
      fetchAgentPromptHistory({ accessToken, node }),
    ])
      .then(([currentPrompt, historyResult]) => {
        if (!active) return;
        setCurrent(currentPrompt);
        setHistory(historyResult.items);
        // Seed the draft from the published prompt so the admin edits a known
        // baseline. A fresh install has no published prompt (BE-020 returns
        // 200 + null); in that case seed an empty draft the admin can write
        // the first version into. `fetchCurrentAgentPrompt` only throws on a
        // real HTTP error, so reaching this branch means the load succeeded.
        setDraft({
          version: currentPrompt?.version ?? null,
          promptText: currentPrompt?.prompt_text ?? "",
          savedText: currentPrompt?.prompt_text ?? "",
        });
        setLoadState("ready");
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setLoadError(caught instanceof Error ? caught.message : "Agent 提示词加载失败");
        setLoadState("error");
      });
    return () => {
      active = false;
    };
  }, [accessToken, node]);

  function report(message: string, tone: "error" | "info" = "info") {
    setStatus(message);
    setStatusTone(tone);
  }

  async function saveDraft() {
    if (!accessToken) return;
    setBusy("save");
    setStatus(null);
    try {
      const saved = await saveAgentPromptDraft({
        accessToken,
        node,
        promptText: draft.promptText,
        idempotencyKey: agentPromptIdempotencyKey(node, "draft"),
      });
      setDraft({
        version: saved.version,
        promptText: saved.prompt_text,
        savedText: saved.prompt_text,
      });
      report(`已保存草稿 v${saved.version} · 等待发布`);
    } catch (caught) {
      report(caught instanceof Error ? caught.message : "Agent 提示词保存失败", "error");
    } finally {
      setBusy(null);
    }
  }

  function requestPublish() {
    if (!draft.version) return;
    setPendingPublish(draft);
  }

  async function confirmPublish() {
    if (!accessToken || !pendingPublish?.version) return;
    setBusy("publish");
    setStatus(null);
    const version = pendingPublish.version;
    try {
      const result = await publishAgentPromptVersion({
        accessToken,
        node,
        version,
        idempotencyKey: agentPromptIdempotencyKey(node, "publish", version),
      });
      const published: AgentPromptVersion = {
        node,
        version: result.version,
        prompt_text: pendingPublish.promptText,
        published_at: result.published_at,
        updated_by: result.updated_by,
        is_current: true,
        is_published: true,
      };
      setCurrent(published);
      setDraft({
        version: published.version,
        promptText: published.prompt_text,
        savedText: published.prompt_text,
      });
      setHistory((items) => [
        published,
        ...items.map((item) => ({ ...item, is_current: false })),
      ]);
      report(`已发布 v${result.version} · 即刻生效`);
      setPendingPublish(null);
    } catch (caught) {
      report(caught instanceof Error ? caught.message : "Agent 提示词发布失败", "error");
    } finally {
      setBusy(null);
    }
  }

  async function dryRun() {
    if (!accessToken) return;
    setBusy("dry-run");
    setStatus(null);
    try {
      const result = await dryRunAgentPrompt({
        accessToken,
        node,
        promptText: draft.promptText,
        idempotencyKey: agentPromptIdempotencyKey(node, "dry-run"),
      });
      // BE-020 is stubbed: surface the note verbatim and never fabricate a result.
      if (!result.implemented) {
        report(`试运行未实现 · ${result.note}`, "info");
        return;
      }
      // Defensive: if the backend starts returning implemented=true before this
      // branch is wired up, fail loudly instead of pretending nothing changed.
      report("后端返回未知试运行结果，请联系平台维护者", "error");
    } catch (caught) {
      report(caught instanceof Error ? caught.message : "Agent 提示词试运行失败", "error");
    } finally {
      setBusy(null);
    }
  }

  const saveDisabled = !accessToken || busy !== null || !draftIsDirty;
  const publishDisabled = !accessToken || busy !== null || draft.version === null;
  const dryRunDisabled = !accessToken || busy !== null;

  const nodeOptions = useMemo(() => AGENT_PROMPT_NODES, []);

  return (
    <div className="admin-page">
      <div className="admin-page__heading">
        <div>
          <p className="eyebrow">AGENT TUNING · BE-020</p>
          <h1>Agent 提示词调优</h1>
          <p>
            为六类 Agent 节点编辑草稿、保存为新版本并发布；试运行尚未在后端实现，会如实提示。
          </p>
        </div>
        <label className="admin-filter-field">
          <Sparkle size={17} />
          <span className="sr-only">Agent 节点</span>
          <select
            aria-label="Agent 节点"
            onChange={(event) => setNode(event.target.value as AgentPromptNode)}
            value={node}
          >
            {nodeOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
      </div>

      {status ? (
        <p
          aria-label="调优状态"
          className={`admin-inline-status${statusTone === "error" ? " is-error" : ""}`}
          role="status"
        >
          {statusTone === "error" ? <WarningCircle size={16} /> : <Check size={16} />}
          {status}
        </p>
      ) : null}

      {loadState === "loading" ? (
        <p role="status">
          正在加载 {node} 提示词…
        </p>
      ) : null}
      {loadState === "error" ? <p role="alert">{loadError}</p> : null}

      {loadState === "ready" ? (
        <div className="agent-tuning-grid">
          <section
            aria-label="当前发布版本"
            className="admin-panel admin-panel--compact agent-tuning-published"
          >
            <div className="admin-panel__heading">
              <div>
                <p className="eyebrow">CURRENT PUBLISHED</p>
                <h2>当前发布版本</h2>
              </div>
              {current ? <span>v{current.version}</span> : null}
            </div>
            {current ? (
              <>
                <dl>
                  <div>
                    <dt>节点</dt>
                    <dd>{current.node}</dd>
                  </div>
                  <div>
                    <dt>版本</dt>
                    <dd>v{current.version}</dd>
                  </div>
                  <div>
                    <dt>发布时间</dt>
                    <dd>
                      {current.published_at
                        ? new Date(current.published_at).toLocaleString("zh-CN")
                        : "-"}
                    </dd>
                  </div>
                  <div>
                    <dt>更新人</dt>
                    <dd>{current.updated_by}</dd>
                  </div>
                </dl>
                <pre className="agent-tuning-published-text">{current.prompt_text}</pre>
              </>
            ) : (
              <p className="admin-empty-row">尚未发布任何版本。请在下方编辑并保存草稿，然后发布。</p>
            )}
            <p className="admin-authority-note">
              <Sparkle size={15} /> 仅 System Admin 可调优；发布由后端审计并立刻生效。
            </p>
          </section>

          <section
            aria-label="提示词编辑器"
            className="admin-panel admin-panel--compact agent-tuning-editor"
          >
            <div className="admin-panel__heading">
              <div>
                <p className="eyebrow">DRAFT EDITOR</p>
                <h2>草稿编辑器</h2>
              </div>
              {draft.version !== null ? <span>基于 v{draft.version}</span> : null}
            </div>
            <textarea
              aria-label="提示词草稿"
              className="agent-tuning-textarea"
              disabled={busy !== null}
              onChange={(event) =>
                setDraft((current) => ({ ...current, promptText: event.target.value }))
              }
              placeholder="编辑草稿后保存为新版本。Monaco/CodeMirror 未集成，使用纯文本编辑器。"
              value={draft.promptText}
            />
            <div className="agent-tuning-actions">
              <button
                aria-label="保存为新版本"
                className="admin-filter-button"
                disabled={saveDisabled}
                onClick={() => void saveDraft()}
                type="button"
              >
                <Pencil size={15} /> 保存为新版本
              </button>
              {draft.version !== null ? (
                <button
                  aria-label={`发布版本 v${draft.version}`}
                  className="admin-filter-button"
                  disabled={publishDisabled}
                  onClick={requestPublish}
                  type="button"
                >
                  <Check size={15} /> 发布版本 v{draft.version}
                </button>
              ) : null}
              <button
                aria-label="试运行"
                className="admin-table-action"
                disabled={dryRunDisabled}
                onClick={() => void dryRun()}
                type="button"
              >
                <Play size={14} /> 试运行
              </button>
              {busy ? <span aria-live="polite">处理中…</span> : null}
            </div>
            <p className="admin-authority-note">
              <WarningCircle size={15} /> 草稿只写入版本表，不会影响线上 Agent 行为。
            </p>
          </section>

          <section
            aria-label="版本历史"
            className="admin-panel admin-panel--compact agent-tuning-history"
          >
            <div className="admin-panel__heading">
              <div>
                <p className="eyebrow">VERSION HISTORY</p>
                <h2>版本历史</h2>
              </div>
              <span>{history.length} 版</span>
            </div>
            {history.length === 0 ? (
              <p className="admin-empty-row">该节点暂无历史版本</p>
            ) : (
              <ol className="agent-tuning-history-list">
                {history.map((item) => (
                  <li key={`${item.node}-v${item.version}`}>
                    <strong>
                      v{item.version}
                      {item.is_current ? " · 当前线上" : ""}
                    </strong>
                    <small>
                      {item.published_at
                        ? new Date(item.published_at).toLocaleString("zh-CN")
                        : "草稿"}
                      {" · "}
                      {item.updated_by}
                      {" · "}
                      {item.is_published ? "已发布" : "草稿"}
                    </small>
                    <code>{item.prompt_text.slice(0, 80)}</code>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      ) : null}

      {pendingPublish ? (
        <div className="admin-dialog-backdrop">
          <section
            aria-labelledby="agent-publish-title"
            aria-modal="true"
            className="admin-confirm-dialog"
            role="dialog"
          >
            <p className="eyebrow">PUBLISH AGENT PROMPT</p>
            <h2 id="agent-publish-title">
              确认发布 {node} v{pendingPublish.version}
            </h2>
            <p>
              发布后该版本将立即对线上 Agent 生效，所有调用都会切换到新提示词。操作由后端审计且幂等。
            </p>
            <pre className="agent-publish-preview">{pendingPublish.promptText}</pre>
            <div>
              <button
                aria-label="取消发布"
                disabled={busy === "publish"}
                onClick={() => setPendingPublish(null)}
                type="button"
              >
                取消
              </button>
              <button
                aria-label="确认发布"
                className="is-primary"
                disabled={busy === "publish"}
                onClick={() => void confirmPublish()}
                type="button"
              >
                {busy === "publish" ? "发布中…" : "确认发布"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
