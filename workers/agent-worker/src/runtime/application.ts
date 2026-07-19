import { serve } from "@hono/node-server";
import type { ConnectionOptions } from "bullmq";
import { Hono } from "hono";
import Redis from "ioredis";

import type { AgentProviderPort } from "../agents/types.js";
import { ToolRegistry } from "../agents/tool-registry.js";
import { buildHealthApp } from "../health.js";
import {
  createAgentQueue,
  createRedisCompletionStore,
  createAgentWorker,
  createRedisRunStore,
  createRedisStreamPort,
  type AgentQueueRuntime,
  type AgentWorkerRuntime,
} from "../queue/runtime.js";
import { createCheckpointSaver, type CheckpointSaverRuntime } from "../workflow/checkpoints.js";
import { buildAgentGraph } from "../workflow/graph.js";
import { createResourceGenerationHandler } from "../resources/http.js";
import type { WorkerRuntimeConfig } from "./config.js";

export interface WorkerHttpRuntime {
  close(): Promise<void>;
}

export interface WorkerRedisRuntime {
  readonly client: Redis;
  readonly connection: ConnectionOptions;
  close(): Promise<void>;
}

export interface WorkerIntakeRuntime extends AgentWorkerRuntime {
  pause(): Promise<void>;
}

export interface WorkerApplicationAdapters {
  readonly provider: AgentProviderPort;
  startHttp(
    fetch: (request: Request) => Response | Promise<Response>,
    port: number,
  ): WorkerHttpRuntime;
  connectRedis(config: WorkerRuntimeConfig): Promise<WorkerRedisRuntime>;
  createCheckpoint(config: WorkerRuntimeConfig): Promise<CheckpointSaverRuntime>;
  createQueue(redis: WorkerRedisRuntime, config: WorkerRuntimeConfig): Promise<AgentQueueRuntime>;
  createWorker(
    redis: WorkerRedisRuntime,
    checkpoint: CheckpointSaverRuntime,
    config: WorkerRuntimeConfig,
  ): Promise<WorkerIntakeRuntime>;
}

export interface WorkerApplication {
  readonly health: Hono;
  start(): Promise<void>;
  close(): Promise<void>;
}

export interface WorkerSignalTarget {
  once(event: string, listener: () => void): unknown;
  off(event: string, listener: () => void): unknown;
}

function connectionOptions(redisUrl: string): ConnectionOptions {
  const parsed = new URL(redisUrl);
  const database = parsed.pathname.length > 1 ? Number(parsed.pathname.slice(1)) : 0;
  return {
    host: parsed.hostname,
    port: Number(parsed.port || 6379),
    ...(parsed.username.length === 0 ? {} : { username: decodeURIComponent(parsed.username) }),
    ...(parsed.password.length === 0 ? {} : { password: decodeURIComponent(parsed.password) }),
    db: Number.isInteger(database) ? database : 0,
    maxRetriesPerRequest: null,
    ...(parsed.protocol === "rediss:" ? { tls: {} } : {}),
  };
}

const fallbackProvider: AgentProviderPort = {
  async complete() {
    throw new Error("No external Agent provider is configured; use the bounded node fallback.");
  },
};

export function defaultWorkerApplicationAdapters(
  provider: AgentProviderPort = fallbackProvider,
  tools: ToolRegistry = new ToolRegistry({}),
): WorkerApplicationAdapters {
  return {
    provider,
    startHttp(fetch, port) {
      const server = serve({ fetch, port });
      return {
        close: () =>
          new Promise<void>((resolve, reject) => {
            server.close((error) => {
              if (error === undefined) resolve();
              else reject(error);
            });
          }),
      };
    },
    async connectRedis(config) {
      const client = new Redis(config.redisUrl, { maxRetriesPerRequest: null });
      try {
        await client.ping();
      } catch (error) {
        client.disconnect(false);
        throw error;
      }
      return {
        client,
        connection: connectionOptions(config.redisUrl),
        close: async () => {
          await client.quit();
        },
      };
    },
    createCheckpoint: (config) => createCheckpointSaver(config.redisUrl),
    async createQueue(redis) {
      const queue = createAgentQueue(redis.connection);
      await queue.queue.waitUntilReady();
      return queue;
    },
    async createWorker(redis, checkpoint, config) {
      const runtime = createAgentWorker({
        connection: redis.connection,
        concurrency: config.concurrency,
        dependencies: {
          store: createRedisRunStore(redis.client),
          stream: createRedisStreamPort(redis.client),
          completion: createRedisCompletionStore(redis.client),
          graphFactory: (audit) =>
            buildAgentGraph({
              provider,
              audit,
              tools,
              checkpointer: checkpoint.saver,
            }),
        },
      });
      await runtime.worker.waitUntilReady();
      return { ...runtime, pause: () => runtime.worker.pause(true) };
    },
  };
}

export function buildWorkerApplication(
  config: WorkerRuntimeConfig,
  adapters: WorkerApplicationAdapters = defaultWorkerApplicationAdapters(),
): WorkerApplication {
  let ready = false;
  let started = false;
  let closePromise: Promise<void> | undefined;
  let http: WorkerHttpRuntime | undefined;
  let redis: WorkerRedisRuntime | undefined;
  let checkpoint: CheckpointSaverRuntime | undefined;
  let queue: AgentQueueRuntime | undefined;
  let worker: WorkerIntakeRuntime | undefined;
  const health = buildHealthApp(
    undefined,
    { isReady: () => ready },
    createResourceGenerationHandler(config.internalSecret),
  );

  const closeResources = async (): Promise<void> => {
    ready = false;
    const errors: unknown[] = [];
    const close = async (operation: (() => Promise<void>) | undefined): Promise<void> => {
      if (operation === undefined) return;
      try {
        await operation();
      } catch (error) {
        errors.push(error);
      }
    };
    if (worker !== undefined) {
      await close(() => worker!.pause());
      await close(() => worker!.close(config.shutdownGraceMs));
    }
    await close(queue === undefined ? undefined : () => queue!.close(config.shutdownGraceMs));
    await close(checkpoint === undefined ? undefined : () => checkpoint!.close());
    await close(redis === undefined ? undefined : () => redis!.close());
    await close(http === undefined ? undefined : () => http!.close());
    if (errors.length > 0) {
      throw new AggregateError(errors, "One or more Worker resources failed to close.");
    }
  };

  const application: WorkerApplication = {
    health,
    async start() {
      if (started) return;
      started = true;
      http = adapters.startHttp((request) => health.fetch(request), config.port);
      try {
        redis = await adapters.connectRedis(config);
        checkpoint = await adapters.createCheckpoint(config);
        queue = await adapters.createQueue(redis, config);
        worker = await adapters.createWorker(redis, checkpoint, config);
        ready = true;
      } catch (error) {
        closePromise = closeResources();
        await closePromise;
        throw error;
      }
    },
    close() {
      closePromise ??= closeResources();
      return closePromise;
    },
  };
  return application;
}

export async function startWorkerApplication(
  config: WorkerRuntimeConfig,
  adapters: WorkerApplicationAdapters = defaultWorkerApplicationAdapters(),
): Promise<WorkerApplication> {
  const application = buildWorkerApplication(config, adapters);
  await application.start();
  return application;
}

export function installWorkerSignalHandlers(
  application: WorkerApplication,
  target: WorkerSignalTarget = process,
): () => void {
  const shutdown = (): void => {
    void application.close();
  };
  target.once("SIGINT", shutdown);
  target.once("SIGTERM", shutdown);
  return () => {
    target.off("SIGINT", shutdown);
    target.off("SIGTERM", shutdown);
  };
}
