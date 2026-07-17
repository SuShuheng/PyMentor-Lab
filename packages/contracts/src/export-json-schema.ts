/**
 * Exports canonical JSON Schemas for every published contract model.
 *
 * The generated file (`schemas.json`) is the neutral contract that the
 * Pydantic mirror in `backend/app/contracts/` is checked against. Run via
 * `pnpm contracts:check`. The output is deterministic (sorted keys) so a
 * stale schema shows up as a git diff.
 */

import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { zodToJsonSchema } from "zod-to-json-schema";

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
const OUT = resolve(__dirname, "..", "schemas.json");

const schemas = {
  ErrorEnvelope: zodToJsonSchema(ErrorEnvelope, "ErrorEnvelope"),
  HealthResponse: zodToJsonSchema(HealthResponse, "HealthResponse"),
  SystemPingResponse: zodToJsonSchema(SystemPingResponse, "SystemPingResponse"),
  ChatCompletionChunk: zodToJsonSchema(ChatCompletionChunk, "ChatCompletionChunk"),
  StreamEvent: zodToJsonSchema(StreamEvent, "StreamEvent"),
  SandboxResult: zodToJsonSchema(SandboxResult, "SandboxResult"),
  WorkerJobEnvelope: zodToJsonSchema(WorkerJobEnvelope, "WorkerJobEnvelope"),
  RegisterRequest: zodToJsonSchema(RegisterRequest, "RegisterRequest"),
  RegisterResponse: zodToJsonSchema(RegisterResponse, "RegisterResponse"),
  LoginRequest: zodToJsonSchema(LoginRequest, "LoginRequest"),
  AuthTokens: zodToJsonSchema(AuthTokens, "AuthTokens"),
  TokenRefreshRequest: zodToJsonSchema(TokenRefreshRequest, "TokenRefreshRequest"),
  UserProfile: zodToJsonSchema(UserProfile, "UserProfile"),
  PendingRegistration: zodToJsonSchema(PendingRegistration, "PendingRegistration"),
  RegistrationDecisionRequest: zodToJsonSchema(
    RegistrationDecisionRequest,
    "RegistrationDecisionRequest",
  ),
} as const;

writeFileSync(OUT, JSON.stringify(schemas, null, 2) + "\n", "utf8");
console.log(`wrote ${OUT}`);
