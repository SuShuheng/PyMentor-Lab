import { EventEmitter } from "node:events";

import type { ConnectionOptions } from "bullmq";
import type Redis from "ioredis";
import { describe, expect, it, vi } from "vitest";

import type { AgentProviderPort } from "../agents/types.js";
import type { AgentQueueRuntime, AgentWorkerRuntime } from "../queue/runtime.js";
import type { CheckpointSaverRuntime } from "../workflow/checkpoints.js";
import {
  buildWorkerApplication,
  installWorkerSignalHandlers,
  type WorkerApplicationAdapters,
  type WorkerHttpRuntime,
  type WorkerRedisRuntime,
} from "./application.js";
import { loadWorkerRuntimeConfig } from "./config.js";

const config = loadWorkerRuntimeConfig({
  NODE_ENV: "production",
  PYMENTOR_REDIS_URL: "redis://redis:6379/0",
  PYMENTOR_WORKER_PORT: "8081",
  PYMENTOR_WORKER_CONCURRENCY: "2",
  PYMENTOR_WORKER_SHUTDOWN_GRACE_MS: "5000",
});

function harness() {
  const calls: string[] = [];
  const redis: WorkerRedisRuntime = {
    client: {} as Redis,
    connection: {} as ConnectionOptions,
    close: vi.fn(async () => {
      calls.push("redis.close");
    }),
  };
  const checkpoint: CheckpointSaverRuntime = {
    saver: {} as CheckpointSaverRuntime["saver"],
    close: vi.fn(async () => {
      calls.push("checkpoint.close");
    }),
  };
  const queue: AgentQueueRuntime = {
    queue: {} as AgentQueueRuntime["queue"],
    enqueue: vi.fn(),
    close: vi.fn(async () => {
      calls.push("queue.close");
    }),
  };
  const worker: AgentWorkerRuntime = {
    worker: {} as AgentWorkerRuntime["worker"],
    close: vi.fn(async () => {
      calls.push("worker.close");
    }),
  };
  const http: WorkerHttpRuntime = {
    close: vi.fn(async () => {
      calls.push("http.close");
    }),
  };
  const provider: AgentProviderPort = { complete: vi.fn() };
  const adapters: WorkerApplicationAdapters = {
    startHttp: vi.fn(() => {
      calls.push("http.start");
      return http;
    }),
    connectRedis: vi.fn(async () => {
      calls.push("redis.ready");
      return redis;
    }),
    createCheckpoint: vi.fn(async () => {
      calls.push("checkpoint.ready");
      return checkpoint;
    }),
    createQueue: vi.fn(async () => {
      calls.push("queue.ready");
      return queue;
    }),
    createWorker: vi.fn(async () => {
      calls.push("worker.ready");
      return {
        ...worker,
        pause: vi.fn(async () => {
          calls.push("worker.pause");
        }),
      };
    }),
    provider,
  };
  return { adapters, calls, worker };
}

describe("Worker application lifecycle", () => {
  it("stays live while readiness is false, then becomes ready after dependencies", async () => {
    const fixture = harness();
    const application = buildWorkerApplication(config, fixture.adapters);

    expect((await application.health.request("/health")).status).toBe(200);
    expect((await application.health.request("/ready")).status).toBe(503);
    await application.start();

    expect((await application.health.request("/ready")).status).toBe(200);
    expect(fixture.calls).toEqual([
      "http.start",
      "redis.ready",
      "checkpoint.ready",
      "queue.ready",
      "worker.ready",
    ]);
  });

  it("pauses intake before reverse-order shutdown and is idempotent", async () => {
    const fixture = harness();
    const application = buildWorkerApplication(config, fixture.adapters);
    await application.start();
    fixture.calls.length = 0;

    await application.close();
    await application.close();

    expect(fixture.calls).toEqual([
      "worker.pause",
      "worker.close",
      "queue.close",
      "checkpoint.close",
      "redis.close",
      "http.close",
    ]);
    expect((await application.health.request("/ready")).status).toBe(503);
    expect(fixture.worker.close).toHaveBeenCalledWith(config.shutdownGraceMs);
  });

  it("uses the same close path for SIGTERM", async () => {
    const fixture = harness();
    const application = buildWorkerApplication(config, fixture.adapters);
    await application.start();
    const signals = new EventEmitter();
    const close = vi.spyOn(application, "close");
    const remove = installWorkerSignalHandlers(application, signals);

    signals.emit("SIGTERM");
    await vi.waitFor(() => expect(close).toHaveBeenCalledOnce());
    remove();
  });
});

describe("Worker runtime config", () => {
  it("fails fast without a production Redis URL", () => {
    expect(() => loadWorkerRuntimeConfig({ NODE_ENV: "production" })).toThrow(/PYMENTOR_REDIS_URL/);
  });

  it.each(["http://redis:6379", "redis://", "not-a-url"])(
    "rejects invalid Redis URL %s",
    (redisUrl) => {
      expect(() =>
        loadWorkerRuntimeConfig({ NODE_ENV: "production", PYMENTOR_REDIS_URL: redisUrl }),
      ).toThrow(/Redis URL/);
    },
  );
});
