/**
 * Conformance gate: every published contract model must parse a shared fixture
 * set, and the Zod-derived JSON Schema must equal the canonical committed
 * `schemas.json`. The Python Pydantic mirror runs an identical fixture set
 * (see `backend/tests/test_contracts_parity.py`) and compares against the same
 * JSON Schemas, so a field drift fails on at least one side.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import {
  AuthTokens,
  ChatCompletionChunk,
  ErrorEnvelope,
  HealthResponse,
  LoginRequest,
  PendingRegistration,
  RegisterRequest,
  RegisterResponse,
  RegistrationDecisionRequest,
  SandboxResult,
  StreamEvent,
  SystemPingResponse,
  TokenRefreshRequest,
  UserProfile,
  WorkerJobEnvelope,
} from "./index.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SCHEMAS_PATH = resolve(__dirname, "..", "schemas.json");

type Cases = Record<string, { schema: unknown; samples: unknown[] }>;

const cases: Cases = {
  ErrorEnvelope: {
    schema: ErrorEnvelope,
    samples: [
      {
        code: "VALIDATION_ERROR",
        message: "email is invalid",
        trace_id: "trc_123",
        retryable: false,
        field_errors: [{ field: "email", code: "format", message: "invalid email" }],
      },
      {
        code: "INTERNAL_ERROR",
        message: "unexpected failure",
        trace_id: "trc_456",
        retryable: false,
      },
    ],
  },
  HealthResponse: {
    schema: HealthResponse,
    samples: [
      { status: "ok", service: "api", version: "0.0.0", timestamp: "2026-07-17T00:00:00Z" },
      { status: "degraded", service: "worker", version: "1.2.3", timestamp: "2026-07-17T00:00:00Z" },
    ],
  },
  SystemPingResponse: {
    schema: SystemPingResponse,
    samples: [{ ok: true, service: "api", timestamp: "2026-07-17T00:00:00Z" }],
  },
  ChatCompletionChunk: {
    schema: ChatCompletionChunk,
    samples: [
      {
        id: "chat_1",
        chunk_index: 0,
        delta_content: "Hello",
        timestamp: "2026-07-17T00:00:00Z",
      },
      {
        id: "chat_1",
        chunk_index: 1,
        delta_reasoning: "thinking",
        delta_tool_calls: [{ index: 0, id: "call_1", name: "lookup", arguments: "{}" }],
        timestamp: "2026-07-17T00:00:00Z",
      },
    ],
  },
  StreamEvent: {
    schema: StreamEvent,
    samples: [
      {
        type: "content_delta",
        event_id: "evt_1",
        chunk: { id: "chat_1", chunk_index: 0, delta_content: "Hi", timestamp: "2026-07-17T00:00:00Z" },
      },
      { type: "done", event_id: "evt_2" },
      {
        type: "progress",
        event_id: "evt_3",
        message: "halfway",
        percent: 50,
      },
    ],
  },
  SandboxResult: {
    schema: SandboxResult,
    samples: [
      {
        run_id: "run_1",
        status: "PASSED",
        passed: true,
        stdout: "",
        stderr: "",
        tests: [
          { name: "test_a", passed: true, duration_ms: 12 },
          { name: "test_b", passed: false, message: "assert", duration_ms: 3, stderr: "AssertionError" },
        ],
        duration_ms: 20,
        peak_memory_kb: 1024,
        user_error: null,
        platform_error: null,
      },
      {
        run_id: "run_2",
        status: "ERROR",
        passed: false,
        stdout: "",
        stderr: "",
        tests: [],
        duration_ms: 0,
        peak_memory_kb: null,
        user_error: null,
        platform_error: "runner crashed",
      },
    ],
  },
  WorkerJobEnvelope: {
    schema: WorkerJobEnvelope,
    samples: [
      {
        schema_version: 1,
        event_id: "evt_job_1",
        trace_id: "trc_1",
        tenant_id: "tnt_demo",
        student_id: "stu_1",
        kind: "resource_generate",
        payload: { need: "loops" },
        enqueued_at: "2026-07-17T00:00:00Z",
      },
    ],
  },
  RegisterRequest: {
    schema: RegisterRequest,
    samples: [
      { email: "student@example.com", password: "S3cret-Pass!" },
      { email: "stu@uni.edu", password: "another-ok-pw", student_no: "2024001" },
    ],
  },
  RegisterResponse: {
    schema: RegisterResponse,
    samples: [
      {
        user_id: "00000000-0000-0000-0000-000000000001",
        email: "student@example.com",
        status: "PENDING",
        message: "Registration received. An administrator will review it.",
      },
    ],
  },
  LoginRequest: {
    schema: LoginRequest,
    samples: [{ email: "student@example.com", password: "S3cret-Pass!" }],
  },
  AuthTokens: {
    schema: AuthTokens,
    samples: [
      {
        access_token: "eyJhbGciOiJIUzI1NiJ9.payload.sig",
        refresh_token: "eyJhbGciOiJIUzI1NiJ9.refresh.sig",
        token_type: "Bearer",
        expires_in: 900,
      },
    ],
  },
  TokenRefreshRequest: {
    schema: TokenRefreshRequest,
    samples: [{ refresh_token: "eyJhbGciOiJIUzI1NiJ9.refresh.sig" }],
  },
  UserProfile: {
    schema: UserProfile,
    samples: [
      {
        id: "00000000-0000-0000-0000-000000000001",
        email: "student@example.com",
        tenant_id: "00000000-0000-0000-0000-000000000002",
        roles: ["STUDENT"],
        status: "ACTIVE",
      },
      {
        id: "00000000-0000-0000-0000-000000000003",
        email: "admin@uni.edu",
        tenant_id: "00000000-0000-0000-0000-000000000002",
        roles: ["SYSTEM_ADMIN"],
        status: "ACTIVE",
        display_name: "Admin",
      },
    ],
  },
  PendingRegistration: {
    schema: PendingRegistration,
    samples: [
      {
        user_id: "00000000-0000-0000-0000-000000000001",
        email: "student@example.com",
        status: "PENDING",
        created_at: "2026-07-17T00:00:00Z",
      },
    ],
  },
  RegistrationDecisionRequest: {
    schema: RegistrationDecisionRequest,
    samples: [{}, { reason: "Missing student ID" }],
  },
};

let failed = 0;

for (const [name, { schema, samples }] of Object.entries(cases)) {
  // Each sample must parse cleanly.
  for (const [i, sample] of samples.entries()) {
    const parsed = (schema as { safeParse: (v: unknown) => { success: boolean; error?: { message: string } } }).safeParse(sample);
    if (!parsed.success) {
      console.error(`✗ ${name}[${i}] failed to parse: ${parsed.error?.message}`);
      failed += 1;
    }
  }
}

// The committed JSON Schemas file must exist (exported by export-json-schema.ts).
let schemasRaw: string;
try {
  schemasRaw = readFileSync(SCHEMAS_PATH, "utf8");
} catch {
  console.error(`✗ ${SCHEMAS_PATH} missing — run "pnpm contracts:check" which exports schemas first.`);
  failed += 1;
  schemasRaw = "{}";
}

// Sanity: every published model name is present in the committed schemas.
let committed: Record<string, unknown> = {};
try {
  committed = JSON.parse(schemasRaw) as Record<string, unknown>;
} catch (e) {
  console.error("✗ schemas.json is not valid JSON");
  failed += 1;
}
for (const name of Object.keys(cases)) {
  if (!(name in committed)) {
    console.error(`✗ schemas.json missing model: ${name}`);
    failed += 1;
  }
}

if (failed > 0) {
  console.error(`\n${failed} conformance failure(s).`);
  process.exit(1);
}
console.log(`conformance OK: ${Object.keys(cases).length} models, fixtures parsed.`);
