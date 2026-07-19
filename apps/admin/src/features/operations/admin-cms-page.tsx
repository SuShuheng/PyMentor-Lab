import {
  ArrowLeft,
  BookOpen,
  ListMagnifyingGlass,
  MagnifyingGlass,
  PencilSimple,
  Rocket,
  ShieldCheck,
  WarningCircle,
} from "@phosphor-icons/react";
import { StatePanel } from "@pymentor/ui";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { useAdminAuth } from "../auth/auth-session";
import {
  cmsCommandKey,
  fetchCmsNode,
  fetchCmsQuestionTemplate,
  listCmsNodes,
  publishCmsNode,
  publishCmsQuestionTemplate,
  updateCmsNode,
  updateCmsQuestionTemplate,
  type CmsNode,
  type CmsNodeUpdate,
  type CmsQuestionTemplate,
  type CmsQuestionTemplateUpdate,
} from "./admin-cms-api";

const NODE_LIST_FIELDS = [
  "learning_objectives",
  "prerequisites",
  "misconceptions",
  "examples",
  "diagnostic_items",
  "practice_templates",
  "source_ids",
] as const satisfies ReadonlyArray<keyof CmsNodeUpdate>;

const NODE_LIST_LABELS: Record<(typeof NODE_LIST_FIELDS)[number], string> = {
  learning_objectives: "学习目标（每行一条）",
  prerequisites: "前置节点 UUID（每行一条）",
  misconceptions: "典型误解（每行一条）",
  examples: "示例（每行一条）",
  diagnostic_items: "诊断题目 UUID（每行一条）",
  practice_templates: "练习题目 UUID（每行一条）",
  source_ids: "来源 UUID（每行一条）",
};

function splitLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function joinLines(value: string[]): string {
  return value.join("\n");
}

function describeAudit(node: CmsNode): string {
  const audit = node.audit;
  if (!audit) return node.updated_at ?? "无审计记录";
  const parts: string[] = [];
  if (audit.last_event) parts.push(audit.last_event);
  if (audit.last_actor) parts.push(audit.last_actor);
  if (audit.trace_id) parts.push(audit.trace_id);
  return parts.length ? parts.join(" · ") : "无审计记录";
}

function AdminPageHeading({
  action,
  description,
  eyebrow = "ADMIN CMS",
  title,
}: {
  action?: React.ReactNode;
  description: string;
  eyebrow?: string;
  title: string;
}) {
  return (
    <div className="admin-page__heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}

function CmsConstraintNote() {
  return (
    <p className="admin-authority-note">
      <ShieldCheck size={15} /> V1.1 极简 CMS：直写 + 审计，无暂存 / Diff / 回滚。所有变更与发布均由后端校验并写入审计。
    </p>
  );
}

export function CmsPage() {
  const { templateId } = useParams<{ templateId: string }>();
  if (templateId) {
    return <CmsQuestionTemplateEditor templateId={templateId} />;
  }
  return <CmsNodeBrowser />;
}

function CmsNodeBrowser() {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;
  const [searchParams, setSearchParams] = useSearchParams();
  const activeNodeId = searchParams.get("node_id")?.trim() ?? "";
  const [query, setQuery] = useState("");
  const [nodes, setNodes] = useState<CmsNode[]>([]);
  const [loadState, setLoadState] = useState<"error" | "loading" | "ready">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoadState("loading");
    setError(null);
    if (!accessToken) {
      setLoadState("error");
      setError("管理员会话缺少访问令牌，请重新登录");
      return () => {
        active = false;
      };
    }
    const trimmed = query.trim();
    void listCmsNodes({
      accessToken,
      query: { q: trimmed || undefined, page: 1, page_size: 50 },
    })
      .then((result) => {
        if (!active) return;
        setNodes(result.items);
        setLoadState("ready");
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "知识节点列表加载失败");
        setLoadState("error");
      });
    return () => {
      active = false;
    };
  }, [accessToken, query]);

  function selectNode(nodeId: string) {
    const next = new URLSearchParams(searchParams);
    next.set("node_id", nodeId);
    setSearchParams(next, { replace: true });
  }

  return (
    <div className="admin-page">
      <AdminPageHeading
        description="直写并审计的知识节点编辑器：标题 / 学习目标 / 前置 / 误解 / 示例 / 诊断 / 练习 / 来源"
        eyebrow="COURSE CMS · V1.1 MINIMAL"
        title="课程内容管理"
      />
      <CmsConstraintNote />
      <div className="overview-grid">
        <section aria-label="知识节点浏览" className="admin-panel admin-panel--compact admin-table-panel">
          <div className="admin-panel__heading">
            <div>
              <p className="eyebrow">KNOWLEDGE NODES</p>
              <h2>知识节点</h2>
            </div>
            <span>{nodes.length} 项 · 服务端搜索</span>
          </div>
          <div className="admin-table-toolbar">
            <label className="admin-filter-field">
              <MagnifyingGlass size={17} />
              <span className="sr-only">搜索节点</span>
              <input
                aria-label="搜索节点"
                onChange={(event) => setQuery(event.target.value)}
                placeholder="按标题或 UUID 搜索"
                type="search"
                value={query}
              />
            </label>
          </div>
          {loadState === "loading" ? <p role="status">正在加载知识节点…</p> : null}
          {loadState === "error" ? <p role="alert">{error}</p> : null}
          {loadState === "ready" && nodes.length === 0 ? (
            <p className="admin-empty-row">没有匹配的节点</p>
          ) : null}
          <div className="admin-table-scroll">
            <table aria-label="知识节点列表" className="admin-data-table">
              <thead>
                <tr>
                  <th>标题</th>
                  <th>版本</th>
                  <th>状态</th>
                  <th>
                    <span className="sr-only">操作</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {nodes.map((node) => (
                  <tr key={node.node_id}>
                    <th scope="row">
                      <strong>{node.title}</strong>
                      <small>{node.node_id}</small>
                    </th>
                    <td>v{node.content_version}</td>
                    <td>
                      <span
                        className={`admin-badge is-${node.published ? "active" : "paused"}`}
                      >
                        {node.published ? "PUBLISHED" : "DRAFT"}
                      </span>
                    </td>
                    <td>
                      <button
                        aria-label={`编辑${node.title}`}
                        className="admin-table-action"
                        onClick={() => selectNode(node.node_id)}
                        type="button"
                      >
                        <PencilSimple size={14} /> 编辑
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section
          aria-label="节点编辑"
          className="admin-panel admin-panel--compact"
        >
          <div className="admin-panel__heading">
            <div>
              <p className="eyebrow">NODE EDITOR</p>
              <h2>{activeNodeId ? "编辑节点" : "选择节点"}</h2>
            </div>
          </div>
          {activeNodeId ? (
            <CmsNodeEditor
              key={activeNodeId}
              nodeId={activeNodeId}
              accessToken={accessToken ?? ""}
            />
          ) : (
            <p className="admin-empty-row">
              <ListMagnifyingGlass size={18} /> 从左侧列表选择一个节点开始编辑
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

type NodeDraft = {
  title: string;
  chapter_id: string;
  lists: Record<(typeof NODE_LIST_FIELDS)[number], string>;
};

function toDraft(node: CmsNode): NodeDraft {
  return {
    title: node.title,
    chapter_id: node.chapter_id,
    lists: {
      learning_objectives: joinLines(node.learning_objectives),
      prerequisites: joinLines(node.prerequisites),
      misconceptions: joinLines(node.misconceptions),
      examples: joinLines(node.examples),
      diagnostic_items: joinLines(node.diagnostic_items),
      practice_templates: joinLines(node.practice_templates),
      source_ids: joinLines(node.source_ids),
    },
  };
}

function toUpdate(draft: NodeDraft): CmsNodeUpdate {
  return {
    title: draft.title.trim(),
    chapter_id: draft.chapter_id.trim(),
    learning_objectives: splitLines(draft.lists.learning_objectives),
    prerequisites: splitLines(draft.lists.prerequisites),
    misconceptions: splitLines(draft.lists.misconceptions),
    examples: splitLines(draft.lists.examples),
    diagnostic_items: splitLines(draft.lists.diagnostic_items),
    practice_templates: splitLines(draft.lists.practice_templates),
    source_ids: splitLines(draft.lists.source_ids),
  };
}

function CmsNodeEditor({ nodeId, accessToken }: { nodeId: string; accessToken: string }) {
  const [node, setNode] = useState<CmsNode | null>(null);
  const [draft, setDraft] = useState<NodeDraft | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmingPublish, setConfirmingPublish] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    let active = true;
    setNode(null);
    setDraft(null);
    setLoadError(null);
    setError(null);
    setStatus(null);
    setDirty(false);
    if (!accessToken) {
      setLoadError("管理员会话缺少访问令牌，请重新登录");
      return () => {
        active = false;
      };
    }
    void fetchCmsNode({ accessToken, nodeId })
      .then((result) => {
        if (!active) return;
        setNode(result);
        setDraft(toDraft(result));
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setLoadError(caught instanceof Error ? caught.message : "节点详情加载失败");
      });
    return () => {
      active = false;
    };
  }, [accessToken, nodeId]);

  function updateField(field: keyof NodeDraft["lists"], value: string) {
    setDraft((current) =>
      current ? { ...current, lists: { ...current.lists, [field]: value } } : current,
    );
    setDirty(true);
  }

  function updateTitle(value: string) {
    setDraft((current) => (current ? { ...current, title: value } : current));
    setDirty(true);
  }

  async function save() {
    if (!draft || !node) return;
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      const updated = await updateCmsNode({
        accessToken,
        body: toUpdate(draft),
        idempotencyKey: cmsCommandKey("cms-node"),
        nodeId,
      });
      setNode(updated);
      setDraft(toDraft(updated));
      setDirty(false);
      setStatus(`已保存 · v${updated.content_version} · 直写审计已记录`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "节点保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function publish() {
    if (!node) return;
    setConfirmingPublish(false);
    setError(null);
    try {
      const result = await publishCmsNode({
        accessToken,
        idempotencyKey: cmsCommandKey("cms-node-publish"),
        nodeId,
      });
      setNode((current) =>
        current
          ? {
              ...current,
              published: result.published,
              content_version: result.content_version,
            }
          : current,
      );
      setStatus(`已发布 · v${result.content_version} · 审计已写入`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "节点发布失败");
    }
  }

  if (loadError) {
    return <p role="alert">{loadError}</p>;
  }
  if (!node || !draft) {
    return <p role="status">正在加载节点详情…</p>;
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <dl className="cms-meta">
        <div>
          <dt>版本</dt>
          <dd>{node.content_version}</dd>
        </div>
        <div>
          <dt>状态</dt>
          <dd>{node.published ? "已发布" : "草稿"}</dd>
        </div>
        <div>
          <dt>审计</dt>
          <dd>{describeAudit(node)}</dd>
        </div>
      </dl>
      <label className="cms-field">
        <span>节点标题</span>
        <input
          aria-label="节点标题"
          onChange={(event) => updateTitle(event.target.value)}
          value={draft.title}
        />
      </label>
      <label className="cms-field">
        <span>章节 UUID</span>
        <input
          aria-label="章节 UUID"
          disabled
          readOnly
          value={draft.chapter_id}
        />
      </label>
      {NODE_LIST_FIELDS.map((field) => (
        <label className="cms-field" key={field}>
          <span>{NODE_LIST_LABELS[field]}</span>
          <textarea
            aria-label={NODE_LIST_LABELS[field]}
            onChange={(event) => updateField(field, event.target.value)}
            rows={Math.min(8, Math.max(2, draft.lists[field].split(/\r?\n/).length + 1))}
            value={draft.lists[field]}
          />
        </label>
      ))}
      {status ? (
        <p aria-label="节点保存状态" className="admin-inline-status" role="status">
          {status}
        </p>
      ) : null}
      {error ? (
        <p aria-label="节点保存错误" className="admin-health-alert" role="alert">
          <WarningCircle size={18} /> {error}
        </p>
      ) : null}
      <div className="cms-actions">
        <button disabled={saving} type="submit">
          <BookOpen size={15} /> 保存节点
        </button>
        <button
          // Publish is gated on a clean, saved draft. While `dirty` is true the
          // latest edits have not been validated by the backend, so we block the
          // publish button until the operator saves (or reloads) the node.
          disabled={dirty || saving}
          onClick={() => setConfirmingPublish(true)}
          type="button"
        >
          <Rocket size={15} /> 发布节点
        </button>
      </div>
      <p className="admin-authority-note">
        <ShieldCheck size={15} /> 发布门禁由后端强制；草稿未保存前无法发布。
      </p>
      {confirmingPublish ? (
        <div className="admin-dialog-backdrop">
          <section
            aria-labelledby="cms-publish-title"
            aria-modal="true"
            className="admin-confirm-dialog"
            role="dialog"
          >
            <p className="eyebrow">PUBLISH NODE</p>
            <h2 id="cms-publish-title">确认发布节点</h2>
            <p>
              将把 v{node.content_version} 推送为线上版本并写入审计。该操作不可回滚（V1.1 无 Diff / 回滚）。
            </p>
            <div>
              <button onClick={() => setConfirmingPublish(false)} type="button">
                取消
              </button>
              <button
                className="is-primary"
                onClick={() => void publish()}
                type="button"
              >
                确认发布
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </form>
  );
}

type TemplateDraft = {
  kind: string;
  prompt_template: string;
  parameter_schema: string;
  answer_schema: string;
  test_case_ids: string;
  source_ids: string;
};

function templateToDraft(template: CmsQuestionTemplate): TemplateDraft {
  return {
    kind: template.kind,
    prompt_template: template.prompt_template,
    parameter_schema: JSON.stringify(template.parameter_schema, null, 2),
    answer_schema: JSON.stringify(template.answer_schema, null, 2),
    test_case_ids: joinLines(template.test_case_ids),
    source_ids: joinLines(template.source_ids),
  };
}

function describeTemplateAudit(template: CmsQuestionTemplate): string {
  const audit = template.audit;
  if (!audit) return template.updated_at ?? "无审计记录";
  const parts: string[] = [];
  if (audit.last_event) parts.push(audit.last_event);
  if (audit.last_actor) parts.push(audit.last_actor);
  if (audit.trace_id) parts.push(audit.trace_id);
  return parts.length ? parts.join(" · ") : "无审计记录";
}

function CmsQuestionTemplateEditor({
  templateId,
}: {
  templateId: string;
}) {
  const { session } = useAdminAuth();
  const accessToken = session?.accessToken;
  const [template, setTemplate] = useState<CmsQuestionTemplate | null>(null);
  const [draft, setDraft] = useState<TemplateDraft | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmingPublish, setConfirmingPublish] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    let active = true;
    setTemplate(null);
    setDraft(null);
    setLoadError(null);
    setError(null);
    setStatus(null);
    setDirty(false);
    if (!accessToken) {
      setLoadError("管理员会话缺少访问令牌，请重新登录");
      return () => {
        active = false;
      };
    }
    void fetchCmsQuestionTemplate({ accessToken, templateId })
      .then((result) => {
        if (!active) return;
        setTemplate(result);
        setDraft(templateToDraft(result));
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setLoadError(caught instanceof Error ? caught.message : "题目模板加载失败");
      });
    return () => {
      active = false;
    };
  }, [accessToken, templateId]);

  function updateField(field: keyof TemplateDraft, value: string) {
    setDraft((current) => (current ? { ...current, [field]: value } : current));
    setDirty(true);
  }

  if (!accessToken) {
    return (
      <div className="admin-page">
        <AdminPageHeading
          action={
            <Link className="admin-filter-button" to="/admin/cms">
              <ArrowLeft size={15} /> 返回节点列表
            </Link>
          }
          description={`题目模板 ${templateId}`}
          title="题目模板编辑"
        />
        <StatePanel
          description="管理员会话缺少访问令牌"
          state="error"
          title="无法加载题目模板"
        />
      </div>
    );
  }
  // After the guard above TypeScript narrows `accessToken` to `string`, so the
  // save / publish closures below can pass it straight to the typed wrapper.
  const token = accessToken;

  async function save() {
    if (!draft || !template) return;
    setSaving(true);
    setError(null);
    setStatus(null);
    let parsedParameter: Record<string, unknown>;
    let parsedAnswer: Record<string, unknown>;
    try {
      parsedParameter = draft.parameter_schema.trim()
        ? (JSON.parse(draft.parameter_schema) as Record<string, unknown>)
        : {};
      parsedAnswer = JSON.parse(draft.answer_schema) as Record<string, unknown>;
    } catch (caught) {
      setError(
        `JSON 解析失败：${caught instanceof Error ? caught.message : "请检查 parameter_schema / answer_schema"}`,
      );
      setSaving(false);
      return;
    }
    const body: CmsQuestionTemplateUpdate = {
      kind: draft.kind.trim(),
      prompt_template: draft.prompt_template,
      parameter_schema: parsedParameter,
      answer_schema: parsedAnswer,
      test_case_ids: splitLines(draft.test_case_ids),
      source_ids: splitLines(draft.source_ids),
    };
    try {
      const updated = await updateCmsQuestionTemplate({
        accessToken: token,
        body,
        idempotencyKey: cmsCommandKey("cms-question"),
        templateId,
      });
      setTemplate(updated);
      setDraft(templateToDraft(updated));
      setDirty(false);
      setStatus(`已保存 · v${updated.content_version} · 直写审计已记录`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "题目模板保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function publish() {
    if (!template) return;
    setConfirmingPublish(false);
    setError(null);
    try {
      const result = await publishCmsQuestionTemplate({
        accessToken: token,
        idempotencyKey: cmsCommandKey("cms-question-publish"),
        templateId,
      });
      setTemplate((current) =>
        current
          ? {
              ...current,
              published: result.published,
              content_version: result.content_version,
            }
          : current,
      );
      setStatus(`已发布 · v${result.content_version} · 审计已写入`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "题目模板发布失败");
    }
  }

  if (loadError) {
    return (
      <div className="admin-page">
        <AdminPageHeading
          action={
            <Link className="admin-filter-button" to="/admin/cms">
              <ArrowLeft size={15} /> 返回节点列表
            </Link>
          }
          description={`题目模板 ${templateId}`}
          title="题目模板编辑"
        />
        <p role="alert">{loadError}</p>
      </div>
    );
  }
  if (!template || !draft) {
    return (
      <div className="admin-page">
        <AdminPageHeading
          action={
            <Link className="admin-filter-button" to="/admin/cms">
              <ArrowLeft size={15} /> 返回节点列表
            </Link>
          }
          description={`题目模板 ${templateId}`}
          title="题目模板编辑"
        />
        <p role="status">正在加载题目模板…</p>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminPageHeading
        action={
          <Link className="admin-filter-button" to="/admin/cms">
            <ArrowLeft size={15} /> 返回节点列表
          </Link>
        }
        description={`${template.question_id} · 节点 ${template.node_id}`}
        eyebrow="COURSE CMS · QUESTION TEMPLATE"
        title="题目模板编辑"
      />
      <CmsConstraintNote />
      <section aria-label="题目模板编辑" className="admin-panel admin-panel--compact">
        <div className="admin-panel__heading">
          <div>
            <p className="eyebrow">QUESTION TEMPLATE</p>
            <h2>{template.kind}</h2>
          </div>
          <span>{describeTemplateAudit(template)}</span>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <label className="cms-field">
            <span>题目类型</span>
            <input
              aria-label="题目类型"
              onChange={(event) => updateField("kind", event.target.value)}
              value={draft.kind}
            />
          </label>
          <label className="cms-field">
            <span>题目 prompt 模板</span>
            <textarea
              aria-label="题目 prompt 模板"
              onChange={(event) => updateField("prompt_template", event.target.value)}
              rows={4}
              value={draft.prompt_template}
            />
          </label>
          <label className="cms-field">
            <span>parameter_schema (JSON)</span>
            <textarea
              aria-label="parameter_schema (JSON)"
              className="cms-json"
              onChange={(event) => updateField("parameter_schema", event.target.value)}
              rows={4}
              spellCheck={false}
              value={draft.parameter_schema}
            />
          </label>
          <label className="cms-field">
            <span>answer_schema (JSON)</span>
            <textarea
              aria-label="answer_schema (JSON)"
              className="cms-json"
              onChange={(event) => updateField("answer_schema", event.target.value)}
              rows={4}
              spellCheck={false}
              value={draft.answer_schema}
            />
          </label>
          <label className="cms-field">
            <span>测试用例 UUID（每行一条）</span>
            <textarea
              aria-label="测试用例 UUID"
              onChange={(event) => updateField("test_case_ids", event.target.value)}
              rows={3}
              value={draft.test_case_ids}
            />
          </label>
          <label className="cms-field">
            <span>来源 UUID（每行一条）</span>
            <textarea
              aria-label="来源 UUID"
              onChange={(event) => updateField("source_ids", event.target.value)}
              rows={3}
              value={draft.source_ids}
            />
          </label>
          {status ? (
            <p aria-label="题目模板保存状态" className="admin-inline-status" role="status">
              {status}
            </p>
          ) : null}
          {error ? (
            <p aria-label="题目模板保存错误" className="admin-health-alert" role="alert">
              <WarningCircle size={18} /> {error}
            </p>
          ) : null}
          <div className="cms-actions">
            <button disabled={saving} type="submit">
              <BookOpen size={15} /> 保存题目模板
            </button>
            <button
              disabled={dirty || saving}
              onClick={() => setConfirmingPublish(true)}
              type="button"
            >
              <Rocket size={15} /> 发布题目模板
            </button>
          </div>
        </form>
        {confirmingPublish ? (
          <div className="admin-dialog-backdrop">
            <section
              aria-labelledby="cms-publish-template-title"
              aria-modal="true"
              className="admin-confirm-dialog"
              role="dialog"
            >
              <p className="eyebrow">PUBLISH TEMPLATE</p>
              <h2 id="cms-publish-template-title">确认发布题目模板</h2>
              <p>
                将把 v{template.content_version} 推送为线上版本并写入审计。该操作不可回滚（V1.1 无 Diff / 回滚）。
              </p>
              <div>
                <button onClick={() => setConfirmingPublish(false)} type="button">
                  取消
                </button>
                <button
                  className="is-primary"
                  onClick={() => void publish()}
                  type="button"
                >
                  确认发布
                </button>
              </div>
            </section>
          </div>
        ) : null}
      </section>
    </div>
  );
}
