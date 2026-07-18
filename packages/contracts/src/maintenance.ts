/** Strict BE-010 database and privacy maintenance contracts. */

import { z } from "zod";

const Timestamp = z.string().datetime({ offset: true });
const Uuid = z.string().uuid();
const Digest = z.string().regex(/^[0-9a-f]{64}$/);

export const MaintenanceConfirmationRequest = z
  .object({ confirmation: z.string().min(1).max(128) })
  .strict();
export type MaintenanceConfirmationRequest = z.infer<typeof MaintenanceConfirmationRequest>;

export const DatabaseRestoreRequest = z
  .object({
    confirmation: z.string().min(1).max(128),
    backup_id: Uuid,
  })
  .strict();
export type DatabaseRestoreRequest = z.infer<typeof DatabaseRestoreRequest>;

const DatabaseTableUsage = z
  .object({
    name: z.string().min(1).max(128),
    size_bytes: z.number().int().nonnegative(),
    estimated_rows: z.number().int().nonnegative(),
  })
  .strict();

export const DatabaseBackupView = z
  .object({
    id: Uuid,
    status: z.string().min(1).max(16),
    content_digest: Digest,
    size_bytes: z.number().int().nonnegative(),
    created_at: Timestamp,
  })
  .strict();
export type DatabaseBackupView = z.infer<typeof DatabaseBackupView>;

export const DatabaseStatusView = z
  .object({
    connected: z.boolean(),
    engine: z.literal("PostgreSQL"),
    schema_revision: z.string().min(1).max(32),
    database_size_bytes: z.number().int().nonnegative(),
    active_connections: z.number().int().nonnegative(),
    slow_query_count: z.number().int().nonnegative(),
    table_count: z.number().int().nonnegative(),
    tables: z.array(DatabaseTableUsage),
    last_backup: DatabaseBackupView.nullable(),
  })
  .strict();
export type DatabaseStatusView = z.infer<typeof DatabaseStatusView>;

export const MaintenanceOperationView = z
  .object({
    id: Uuid,
    operation: z.string().min(1).max(32),
    status: z.string().min(1).max(16),
    backup_id: Uuid.nullable(),
    error_code: z.string().max(64).nullable(),
    requested_at: Timestamp,
    completed_at: Timestamp.nullable(),
  })
  .strict();
export type MaintenanceOperationView = z.infer<typeof MaintenanceOperationView>;

export const StudentDeleteView = z
  .object({ student_id: Uuid, deleted: z.boolean() })
  .strict();
export type StudentDeleteView = z.infer<typeof StudentDeleteView>;

export const DemoResetView = z
  .object({
    tenant_id: Uuid,
    reset: z.literal("completed"),
    users_removed: z.number().int().nonnegative(),
  })
  .strict();
export type DemoResetView = z.infer<typeof DemoResetView>;
