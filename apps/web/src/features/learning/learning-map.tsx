import { type AuthRole } from "../auth/auth-session";
import { StatePanel } from "@pymentor/ui";
import { Link } from "react-router-dom";

/**
 * FE-015 — Learning-map reason panel + empty states.
 *
 * The current path projection (`PathSnapshot` / `PathStepView` in
 * `packages/api-client/src/generated/types.gen.ts`) does NOT carry a per-step
 * "reason" field. The backend writes only deterministic projection metadata:
 * `kind` (REVIEW | LEARN | PRACTICE | ASSESSMENT), `scenario_key`,
 * `validation_status` (VALIDATED | REPAIRED | FALLBACK), and
 * `estimated_minutes`. There is no narrative/rationale column on
 * `LearningPathStep` (see `backend/app/contracts/learning.py`).
 *
 * To stay honest we SYNTHESIZE the "为什么这样安排？" narrative from that
 * projection metadata instead of pretending hardcoded UX copy is server data.
 * The synthesized narrative explicitly labels itself as such.
 *
 * BE-side follow-up (BE-021 sibling): when the path projection gains a real
 * reason field, `synthesizePathReasoning` should consume it verbatim and the
 * "合成" note should be dropped. Until then, do not invent fake evidence IDs.
 */

export type LearningMapEmptyKind =
  | "no-profile"
  | "pending-path"
  | "demo-guest"
  | "pending-approval"
  | "no-tasks-today";

export type PathReasoning = {
  /** Human-readable narrative. Always discloses that it is synthesized. */
  narrative: string;
  /** Structured key/value rows shown in the reason panel's `<dl>`. */
  evidenceRows: ReadonlyArray<{ label: string; value: string }>;
};

export type PathSummary = {
  totalSteps: number;
  kindCounts: {
    LEARN: number;
    PRACTICE: number;
    REVIEW: number;
    ASSESSMENT: number;
  };
  validationCounts: {
    VALIDATED: number;
    REPAIRED: number;
    FALLBACK: number;
  };
};

export function emptyPathSummary(): PathSummary {
  return {
    totalSteps: 0,
    kindCounts: { LEARN: 0, PRACTICE: 0, REVIEW: 0, ASSESSMENT: 0 },
    validationCounts: { VALIDATED: 0, REPAIRED: 0, FALLBACK: 0 },
  };
}

/**
 * Build a synthesized "为什么这样安排？" explanation from projection metadata.
 *
 * Honesty contract:
 * - The narrative MUST disclose that it is synthesized (contains "合成" or
 *   "后端") so we never pass UX copy off as server-provided reasons.
 * - The narrative MUST NOT contain hardcoded evidence identifiers from the
 *   V1.0 demo fixtures (e.g. `EVD-1882`, `path-candidate-08`).
 *
 * BE follow-up: replace this synthesis with a real reason field once the
 * projection (BE-021) carries one.
 */
export function synthesizePathReasoning(
  summary: PathSummary,
  pathVersion: number,
): PathReasoning {
  const { totalSteps, kindCounts, validationCounts } = summary;

  const repaired = validationCounts.REPAIRED > 0;
  const fallback = validationCounts.FALLBACK > 0;
  const allValidated =
    validationCounts.VALIDATED === totalSteps && totalSteps > 0;

  const validationPhrase = repaired
    ? `其中 ${validationCounts.REPAIRED} 个节点由路径验证器自动修复前置`
    : fallback
      ? `其中 ${validationCounts.FALLBACK} 个节点使用兜底顺序，请关注后续版本`
      : allValidated
        ? "所有节点均已通过路径验证器的前置关系校验"
        : "当前节点顺序由路径验证器给出";

  const compositionHint =
    `路径以学习节点为主（学习 ${kindCounts.LEARN}）` +
    (kindCounts.REVIEW > 0
      ? `，并安排 ${kindCounts.REVIEW} 个到期复测节点用于巩固已学内容`
      : "");

  const narrative = `当前路径共 ${totalSteps} 个节点，${compositionHint}；${validationPhrase}。本说明由路径元数据合成（后端尚未提供逐条原因），完整原因请以未来路径投影字段为准。`;

  const evidenceRows: ReadonlyArray<{ label: string; value: string }> = [
    { label: "路径版本", value: `v${pathVersion}` },
    {
      label: "节点构成",
      value: `学习 ${kindCounts.LEARN} · 练习 ${kindCounts.PRACTICE} · 复测 ${kindCounts.REVIEW} · 测评 ${kindCounts.ASSESSMENT}`,
    },
    {
      label: "验证结果",
      value: repaired
        ? `已验证 ${validationCounts.VALIDATED} · 修复 ${validationCounts.REPAIRED}${fallback ? ` · 兜底 ${validationCounts.FALLBACK}` : ""}`
        : allValidated
          ? `全部已验证 (${validationCounts.VALIDATED})`
          : `已验证 ${validationCounts.VALIDATED}${fallback ? ` · 兜底 ${validationCounts.FALLBACK}` : ""}`,
    },
  ];

  return { narrative, evidenceRows };
}

/**
 * Decide which empty-state branch applies to the current viewer.
 *
 * Returns `null` when there is nothing wrong (a real path is available) so
 * the caller can render the full map.
 *
 * The decision tree, in priority order:
 *  1. Demo role → demo-guest (always uses preset fixtures).
 *  2. Pending status → pending-approval (cannot learn until approved).
 *  3. No profile (404) → no-profile (must complete onboarding first).
 *  4. Profile exists but no path (404) → pending-path (compilation pending).
 *  5. Path exists → null (caller renders the full map; no-tasks-today is
 *     decided elsewhere when the today plan is genuinely empty).
 */
export function classifyMapEmptyState(input: {
  role: AuthRole;
  status?: string;
  pathStatus?: number;
  profileStatus?: number;
}): LearningMapEmptyKind | null {
  const { role, status, pathStatus, profileStatus } = input;

  if (role === "demo") return "demo-guest";
  if (status === "pending") return "pending-approval";

  if (pathStatus === 404) {
    return profileStatus === 200 ? "pending-path" : "no-profile";
  }

  return null;
}

const emptyCopy: Record<
  LearningMapEmptyKind,
  { title: string; description: string }
> = {
  "no-profile": {
    title: "还没有学习画像",
    description:
      "请先完成入门问卷，以便规则组件根据你的起点生成正式画像与首条路径。",
  },
  "pending-path": {
    title: "画像已生成，等待路径编译",
    description:
      "入门证据已被记录，路径编译器会在处理完成后发布首版路径；通常需要几分钟，请稍后刷新。",
  },
  "demo-guest": {
    title: "演示账号使用预置路径",
    description:
      "演示环境展示固定的学习路径与样本数据，如需生成属于你的个性化路径，请注册正式账号。",
  },
  "pending-approval": {
    title: "账号待审批",
    description:
      "账号正在等待管理员审批；审批通过后即可完成入门问卷并开始学习。",
  },
  "no-tasks-today": {
    title: "今天还没有学习任务",
    description:
      "当前路径暂未发布今日任务；可在学习地图查看完整路径，或等待任务编译器推送下一项。",
  },
};

/**
 * Render the "为什么这样安排？" side panel from synthesized metadata.
 *
 * Uses `<aside role="complementary">` so screen readers announce it as
 * supporting content. The narrative and rows come from
 * `synthesizePathReasoning`; never hardcoded.
 */
export function LearningMapReasonPanel({ reasoning }: { reasoning: PathReasoning }) {
  return (
    <aside aria-labelledby="map-reason-title" className="map-reason-panel">
      <p className="eyebrow">WHY THIS PATH</p>
      <h2 id="map-reason-title">为什么这样安排？</h2>
      <p>{reasoning.narrative}</p>
      <dl>
        {reasoning.evidenceRows.map((row) => (
          <div key={row.label}>
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>
      <Link className="profile-secondary-button" to="/growth/profile">
        查看相关画像证据
      </Link>
    </aside>
  );
}

/**
 * Reusable empty-state panel for the learning surface. Designed to be reused
 * by the Today and Notebook pages in later FE work; for now it backs the map.
 *
 * For actionable branches (no-profile, demo-guest) we render a navigation link
 * below the StatePanel instead of a button that needs an `onAction`, so the
 * call-to-action stays a real, deep-linkable anchor.
 */
export function LearningMapEmptyState({
  kind,
}: {
  kind: LearningMapEmptyKind;
}) {
  const copy = emptyCopy[kind];

  const cta =
    kind === "no-profile"
      ? { label: "前往入门问卷", to: "/onboarding" }
      : kind === "demo-guest"
        ? { label: "注册正式账号", to: "/register" }
        : null;

  return (
    <section className="learning-map-empty">
      <StatePanel description={copy.description} state="empty" title={copy.title} />
      {cta ? (
        <Link className="py-button learning-map-empty__cta" to={cta.to}>
          {cta.label}
        </Link>
      ) : null}
    </section>
  );
}
