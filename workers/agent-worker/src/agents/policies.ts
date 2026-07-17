export const FORBIDDEN_AGENT_PERMISSIONS = Object.freeze([
  "formal_state.write",
  "filesystem.access",
  "shell.execute",
  "provider.secret.read",
] as const);

export const AGENT_TOOL_ALLOWLISTS = Object.freeze({
  orchestrator: Object.freeze([]),
  profile: Object.freeze([]),
  path: Object.freeze(["knowledge.search"]),
  resource: Object.freeze(["knowledge.search", "resource.generate"]),
  coach: Object.freeze(["knowledge.search"]),
  assessment: Object.freeze([]),
} as const);

export const DEFAULT_AGENT_TIMEOUT_MS = 30_000;
