export interface WorkerRuntimeConfig {
  readonly redisUrl: string;
  readonly port: number;
  readonly concurrency: number;
  readonly shutdownGraceMs: number;
}

type RuntimeEnvironment = Readonly<Record<string, string | undefined>>;

function integerSetting(
  environment: RuntimeEnvironment,
  name: string,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  const value = Number(environment[name] ?? fallback);
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}.`);
  }
  return value;
}

function redisUrl(environment: RuntimeEnvironment): string {
  const configured = environment["PYMENTOR_REDIS_URL"] ?? environment["REDIS_URL"];
  if (configured === undefined && environment["NODE_ENV"] === "production") {
    throw new Error("PYMENTOR_REDIS_URL is required in production.");
  }
  const value = configured ?? "redis://127.0.0.1:6379/0";
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("Redis URL must be an absolute redis:// or rediss:// URL.");
  }
  if (!new Set(["redis:", "rediss:"]).has(parsed.protocol) || parsed.hostname.length === 0) {
    throw new Error("Redis URL must use redis:// or rediss:// and include a hostname.");
  }
  return parsed.toString();
}

export function loadWorkerRuntimeConfig(
  environment: RuntimeEnvironment = process.env,
): WorkerRuntimeConfig {
  return Object.freeze({
    redisUrl: redisUrl(environment),
    port: integerSetting(environment, "PYMENTOR_WORKER_PORT", 8081, 1, 65_535),
    concurrency: integerSetting(environment, "PYMENTOR_WORKER_CONCURRENCY", 4, 1, 64),
    shutdownGraceMs: integerSetting(
      environment,
      "PYMENTOR_WORKER_SHUTDOWN_GRACE_MS",
      10_000,
      100,
      120_000,
    ),
  });
}
