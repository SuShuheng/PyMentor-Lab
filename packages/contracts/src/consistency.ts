/**
 * 一致性基础设施契约（Zod 镜像）。
 *
 * Mirror of `backend/app/contracts/consistency.py`。
 * 设计依据：§6.1 append-only 证据、§20.2 幂等、§15.3 必须约束。
 */

import { z } from "zod";

/** 学习证据记录（append-only，event_id 唯一）。 */
export const EvidenceEvent = z.object({
  id: z.string().min(1),
  tenant_id: z.string().min(1),
  student_id: z.string().min(1),
  event_id: z.string().min(1),
  event_type: z.string().min(1),
  trace_id: z.string().min(1),
  payload: z.record(z.string(), z.unknown()).default({}),
  evidence_confidence: z.number().min(0).max(1).default(1.0),
  created_at: z.string().min(1),
  course_id: z.string().nullish(),
  node_id: z.string().nullish(),
  task_id: z.string().nullish(),
});
export type EvidenceEvent = z.infer<typeof EvidenceEvent>;

/** 审计事件（append-only）。 */
export const AuditEvent = z.object({
  id: z.string().min(1),
  tenant_id: z.string().min(1),
  action: z.string().min(1),
  resource_type: z.string().min(1),
  resource_id: z.string().min(1),
  trace_id: z.string().min(1),
  detail: z.record(z.string(), z.unknown()).default({}),
  actor_user_id: z.string().nullish(),
  created_at: z.string().min(1),
});
export type AuditEvent = z.infer<typeof AuditEvent>;

/** Outbox 事件（事务性，event_id 唯一幂等消费）。 */
export const OutboxEvent = z.object({
  id: z.string().min(1),
  tenant_id: z.string().min(1),
  event_type: z.string().min(1),
  event_id: z.string().min(1),
  aggregate_type: z.string().min(1),
  aggregate_id: z.string().min(1),
  trace_id: z.string().min(1),
  payload: z.record(z.string(), z.unknown()).default({}),
  published: z.boolean().default(false),
  created_at: z.string().min(1),
});
export type OutboxEvent = z.infer<typeof OutboxEvent>;

/** 幂等性记录。 */
export const IdempotencyRecord = z.object({
  key: z.string().min(1),
  tenant_id: z.string().min(1),
  endpoint: z.string().min(1),
  response_status: z.number().int().nullish(),
  response_body: z.record(z.string(), z.unknown()).nullish(),
});
export type IdempotencyRecord = z.infer<typeof IdempotencyRecord>;
