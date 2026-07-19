import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts-for-react";
import { useCallback, useId, useMemo, useState } from "react";

/**
 * FE-018 — Knowledge graph renderer (NON-radial).
 *
 * Consumes BE-021's `GET /api/v1/knowledge/graph` payload and renders a
 * force-directed nodes+edges graph using Apache ECharts (`graph` series).
 * Radial/circular layout is explicitly OUT of scope per the v1.1 design
 * decision — only the `force` layout is supported here. Adding `circular`
 * would reintroduce the radial layout the user explicitly deferred.
 *
 * Design rules baked into this component (so callers can't accidentally
 * recolor nodes from browser-side guesses):
 * - Node color comes ONLY from `mastery_status` (server projection). The
 *   renderer never derives color from click state or hover.
 * - Every edge renders as a single prerequisite arrow; weights are ignored.
 * - Clicking a node opens a side panel showing the node's title and the
 *   *server's* mastery status. Clicks do not mutate status.
 * - A legend lists all six mastery buckets; a "reset view" button re-fits the
 *   graph (it does NOT re-fetch — there is no reload surface in the chart).
 */

/** Status enum mirroring `MasteryStatusContract` from `@pymentor/api-client`. */
export type KnowledgeMasteryStatus =
  | "UNSEEN"
  | "LEARNING"
  | "PASSED_WITH_HELP"
  | "INITIAL_MASTERY"
  | "STABLE_MASTERY"
  | "REVIEW_REQUIRED";

/** A node as consumed by the renderer (the BE-021 wire shape, student view). */
export interface KnowledgeGraphNode {
  node_id: string;
  title: string;
  chapter_id: string;
  mastery_status: KnowledgeMasteryStatus;
}

/** A directed prerequisite edge as consumed by the renderer. */
export interface KnowledgeGraphEdge {
  from_node_id: string;
  to_node_id: string;
  kind: string;
}

/** Minimal subset of ECharts instance API we depend on (resize/dispatch). */
export interface KnowledgeGraphEChartsInstance {
  resize(): void;
  dispatchAction(payload: Record<string, unknown>): void;
}

/** Public props for the knowledge graph figure. */
export interface KnowledgeGraphProps {
  nodes: ReadonlyArray<KnowledgeGraphNode>;
  edges: ReadonlyArray<KnowledgeGraphEdge>;
  /** Accessible title for the chart figure. */
  title: string;
  /** Accessible description (rendered as the figure caption). */
  description: string;
  /** Number of nodes — surfaced in the legend so screen-reader users get a
   * count without parsing the canvas. Defaults to `nodes.length`. */
  nodeCountLabel?: string;
  /** Number of edges — surfaced in the legend. Defaults to `edges.length`. */
  edgeCountLabel?: string;
  /** Height of the chart canvas in px. Default 520. */
  height?: number;
}

/** Ordered legend list. Order is fixed so the legend is stable across renders. */
export const MASTERY_LEGEND: ReadonlyArray<{
  status: KnowledgeMasteryStatus;
  label: string;
  color: string;
}> = [
  { status: "UNSEEN", label: "未开始", color: "#9ca3af" },
  { status: "LEARNING", label: "学习中", color: "#2563eb" },
  { status: "PASSED_WITH_HELP", label: "辅助通过", color: "#7c3aed" },
  { status: "INITIAL_MASTERY", label: "初步掌握", color: "#0891b2" },
  { status: "STABLE_MASTERY", label: "稳定掌握", color: "#16a34a" },
  { status: "REVIEW_REQUIRED", label: "需要复测", color: "#dc2626" },
];

const MASTERY_COLOR = new Map<KnowledgeMasteryStatus, string>(
  MASTERY_LEGEND.map((entry) => [entry.status, entry.color]),
);

const MASTERY_LABEL = new Map<KnowledgeMasteryStatus, string>(
  MASTERY_LEGEND.map((entry) => [entry.status, entry.label]),
);

const MASTERY_CATEGORY = new Map<KnowledgeMasteryStatus, number>(
  MASTERY_LEGEND.map((entry, index) => [entry.status, index]),
);

/** Lookup mastery label for a status (exported for tests / a11y fallback). */
export function masteryLabel(status: KnowledgeMasteryStatus): string {
  return MASTERY_LABEL.get(status) ?? status;
}

/** Lookup color for a status. Exposed so the legend matches the canvas. */
export function masteryColor(status: KnowledgeMasteryStatus): string {
  return MASTERY_COLOR.get(status) ?? "#9ca3af";
}

/**
 * Build the ECharts option object for a `graph` series from the BE-021 payload.
 *
 * Pure function: same input always yields the same option. Exported so tests
 * can assert node/edge presence without rendering a canvas.
 */
export function buildKnowledgeGraphOption(
  nodes: ReadonlyArray<KnowledgeGraphNode>,
  edges: ReadonlyArray<KnowledgeGraphEdge>,
): EChartsOption {
  const data = nodes.map((node) => ({
    id: node.node_id,
    name: node.title,
    itemStyle: { color: masteryColor(node.mastery_status) },
    symbolSize: 22,
    category: MASTERY_CATEGORY.get(node.mastery_status) ?? 0,
  }));

  const links = edges.map((edge) => ({
    source: edge.from_node_id,
    target: edge.to_node_id,
  }));

  return {
    tooltip: { trigger: "item" },
    legend: [
      {
        // Match the canvas order so the legend is stable.
        data: MASTERY_LEGEND.map((entry) => entry.label),
        bottom: 0,
      },
    ],
    series: [
      {
        type: "graph",
        // NON-radial: only force layout. `circular` is intentionally absent.
        layout: "force",
        roam: true,
        draggable: true,
        data,
        links,
        categories: MASTERY_LEGEND.map((entry) => ({ name: entry.label })),
        force: {
          repulsion: 220,
          edgeLength: 90,
          gravity: 0.04,
        },
        label: { show: true, position: "right", fontSize: 11 },
        lineStyle: { color: "#9ca3af", width: 1, curveness: 0.15 },
        edgeSymbol: ["none", "arrow"],
        edgeSymbolSize: [0, 6],
        emphasis: { focus: "adjacency", scale: 1.2 },
      },
    ],
  };
}

/**
 * The knowledge graph figure: legend + ECharts canvas + accessible data
 * summary + side panel. Node color is server-driven only.
 */
export function KnowledgeGraph({
  nodes,
  edges,
  title,
  description,
  nodeCountLabel,
  edgeCountLabel,
  height = 520,
}: KnowledgeGraphProps) {
  const figureTitleId = useId();
  const figureDescriptionId = useId();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [echartsInstance, setEchartsInstance] =
    useState<KnowledgeGraphEChartsInstance | null>(null);

  const option = useMemo(
    () => buildKnowledgeGraphOption(nodes, edges),
    [nodes, edges],
  );

  const nodeById = useMemo(() => {
    const map = new Map<string, KnowledgeGraphNode>();
    for (const node of nodes) map.set(node.node_id, node);
    return map;
  }, [nodes]);

  const selectedNode = selectedNodeId ? nodeById.get(selectedNodeId) : null;

  const handleNodeClick = useCallback(
    (params: unknown) => {
      const data =
        params && typeof params === "object" && "data" in params
          ? Reflect.get(params, "data")
          : undefined;
      const id =
        data && typeof data === "object"
          ? Reflect.get(data, "id")
          : undefined;
      if (typeof id === "string") setSelectedNodeId(id);
    },
    [],
  );

  const handleChartReady = useCallback((instance: unknown) => {
    if (instance && typeof instance === "object") {
      const maybe = instance as Partial<KnowledgeGraphEChartsInstance>;
      if (
        typeof maybe.dispatchAction === "function" &&
        typeof maybe.resize === "function"
      ) {
        setEchartsInstance(instance as KnowledgeGraphEChartsInstance);
      }
    }
  }, []);

  const handleResetView = useCallback(() => {
    // Re-fit without re-fetching — there is no reload surface in the chart.
    echartsInstance?.dispatchAction({ type: "restore" });
    setSelectedNodeId(null);
  }, [echartsInstance]);

  const nodeCount = nodeCountLabel ?? String(nodes.length);
  const edgeCount = edgeCountLabel ?? String(edges.length);

  return (
    <figure
      aria-describedby={figureDescriptionId}
      aria-labelledby={figureTitleId}
      className="py-knowledge-graph"
    >
      <div className="py-knowledge-graph__heading">
        <h2 id={figureTitleId}>{title}</h2>
        <p id={figureDescriptionId}>{description}</p>
      </div>

      <ul aria-label="掌握状态图例" className="py-knowledge-graph__legend">
        {MASTERY_LEGEND.map(({ status, label, color }) => {
          const count = nodes.filter(
            (node) => node.mastery_status === status,
          ).length;
          return (
            <li
              className="py-knowledge-graph__legend-item"
              data-status={status}
              key={status}
            >
              <span
                aria-hidden="true"
                className="py-knowledge-graph__legend-swatch"
                style={{ backgroundColor: color }}
              />
              <span>{label}</span>
              <span aria-label={`${label} 数量`}>{count}</span>
            </li>
          );
        })}
      </ul>

      <button
        className="py-knowledge-graph__reset"
        onClick={handleResetView}
        type="button"
      >
        重置视图
      </button>

      <ReactECharts
        aria-hidden="true"
        onChartReady={handleChartReady}
        // echarts-for-react binds each event name to a handler receiving the
        // raw echarts params; we narrow `data.id` ourselves above.
        onEvents={{ click: handleNodeClick }}
        opts={{ renderer: "svg" }}
        option={option}
        style={{ height: `${height}px`, width: "100%" }}
      />

      {/* Accessible summary so screen-reader users get node/edge counts and
          the selected-node details without parsing the canvas. */}
      <dl className="py-knowledge-graph__summary">
        <div>
          <dt>节点数</dt>
          <dd>{nodeCount}</dd>
        </div>
        <div>
          <dt>前置依赖</dt>
          <dd>{edgeCount}</dd>
        </div>
        {selectedNode ? (
          <div aria-live="polite">
            <dt>当前选中</dt>
            <dd>
              <strong>{selectedNode.title}</strong>
              <span>
                {MASTERY_LABEL.get(selectedNode.mastery_status) ??
                  selectedNode.mastery_status}{" "}
                · 章节 {selectedNode.chapter_id}
              </span>
            </dd>
          </div>
        ) : null}
      </dl>

      <aside
        aria-labelledby="py-knowledge-graph-panel-title"
        className="py-knowledge-graph__panel"
      >
        <p className="eyebrow">NODE DETAIL</p>
        <h3 id="py-knowledge-graph-panel-title">
          {selectedNode ? selectedNode.title : "点击节点查看详情"}
        </h3>
        {selectedNode ? (
          <dl>
            <div>
              <dt>掌握状态</dt>
              <dd data-status={selectedNode.mastery_status}>
                {MASTERY_LABEL.get(selectedNode.mastery_status) ??
                  selectedNode.mastery_status}
              </dd>
            </div>
            <div>
              <dt>所属章节</dt>
              <dd>{selectedNode.chapter_id}</dd>
            </div>
            <div>
              <dt>节点 ID</dt>
              <dd>
                <code>{selectedNode.node_id}</code>
              </dd>
            </div>
          </dl>
        ) : (
          <p>
            颜色由服务端掌握状态决定（BE-021），浏览器不会修改节点状态。
          </p>
        )}
      </aside>
    </figure>
  );
}
