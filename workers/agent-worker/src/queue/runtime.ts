import {
  Queue,
  UnrecoverableError,
  Worker,
  type ConnectionOptions,
  type JobsOptions,
} from "bullmq";
import type Redis from "ioredis";

import {
  AgentProposalEnvelope,
  WorkerJobEnvelope,
  type AgentProposalEnvelope as AgentProposalEnvelopeValue,
  type WorkerJobEnvelope as WorkerJobEnvelopeValue,
} from "@pymentor/contracts";

import {
  AGENT_EVENT_STREAM,
  AGENT_EVENT_STREAM_MAXLEN,
  serializeAgentEvent,
  type RedisStreamPort,
} from "./events.js";
import { jobIdForEvent } from "./identities.js";
import {
  AgentJobProcessingError,
  processAgentJob,
  type AgentProcessorDependencies,
  type AgentCompletionStore,
  type RedisRunStore,
} from "./processor.js";

// BullMQ forbids ':' in the queue name because it is its key delimiter.
// Prefix + name preserves the frozen Redis namespace pymentor:agent-jobs:v1:*.
export const AGENT_QUEUE_PREFIX = "pymentor:agent-jobs";
export const AGENT_QUEUE_NAME = "v1";
export const AGENT_QUEUE_DEFAULT_JOB_OPTIONS: JobsOptions = Object.freeze({
  attempts: 3,
  backoff: { type: "exponential", delay: 1_000 },
  removeOnComplete: { count: 1_000 },
  removeOnFail: { count: 5_000 },
});

export interface AgentQueueRuntime {
  readonly queue: Queue<WorkerJobEnvelopeValue, AgentProposalEnvelopeValue, string>;
  enqueue(job: unknown): Promise<string>;
  close(timeoutMs?: number): Promise<void>;
}

export interface AgentWorkerRuntime {
  readonly worker: Worker<WorkerJobEnvelopeValue, AgentProposalEnvelopeValue, string>;
  close(timeoutMs?: number): Promise<void>;
}

export interface CreateAgentWorkerOptions {
  readonly connection: ConnectionOptions;
  readonly dependencies: AgentProcessorDependencies;
  readonly concurrency?: number;
}

async function closeWithin(close: () => Promise<void>, timeoutMs: number): Promise<void> {
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      close(),
      new Promise<never>((_resolve, reject) => {
        timeout = setTimeout(
          () => reject(new Error("Queue shutdown exceeded its grace period.")),
          timeoutMs,
        );
      }),
    ]);
  } finally {
    if (timeout !== undefined) {
      clearTimeout(timeout);
    }
  }
}

export function createAgentQueue(connection: ConnectionOptions): AgentQueueRuntime {
  const queue = new Queue<WorkerJobEnvelopeValue, AgentProposalEnvelopeValue, string>(
    AGENT_QUEUE_NAME,
    {
      connection,
      prefix: AGENT_QUEUE_PREFIX,
      defaultJobOptions: AGENT_QUEUE_DEFAULT_JOB_OPTIONS,
    },
  );
  return {
    queue,
    async enqueue(rawJob) {
      const job = WorkerJobEnvelope.parse(rawJob);
      const queued = await queue.add(job.kind, job, {
        jobId: jobIdForEvent(job),
      });
      if (queued.id === undefined) {
        throw new Error("BullMQ did not return a job identity.");
      }
      return queued.id;
    },
    close: (timeoutMs = 10_000) => closeWithin(() => queue.close(), timeoutMs),
  };
}

export function createAgentWorker(options: CreateAgentWorkerOptions): AgentWorkerRuntime {
  const worker = new Worker<WorkerJobEnvelopeValue, AgentProposalEnvelopeValue, string>(
    AGENT_QUEUE_NAME,
    async (job) => {
      try {
        const result = await processAgentJob(
          job.data,
          { attempt: job.attemptsMade },
          options.dependencies,
        );
        return AgentProposalEnvelope.parse(result);
      } catch (error) {
        if (error instanceof AgentJobProcessingError && !error.retryable) {
          throw new UnrecoverableError(`${error.code}: ${error.message}`);
        }
        throw error;
      }
    },
    {
      connection: options.connection,
      prefix: AGENT_QUEUE_PREFIX,
      concurrency: options.concurrency ?? 4,
    },
  );
  return {
    worker,
    close: (timeoutMs = 10_000) => closeWithin(() => worker.close(), timeoutMs),
  };
}

export function createRedisRunStore(redis: Redis): RedisRunStore {
  return {
    get: (key) => redis.get(key),
    async set(key, value, options = {}) {
      const commandOptions: Array<string | number> = [];
      if (options.ttlMs !== undefined) {
        commandOptions.push("PX", options.ttlMs);
      }
      if (options.nx === true) {
        commandOptions.push("NX");
      }
      const result = await redis.call("SET", key, value, ...commandOptions);
      return result === "OK";
    },
    async nextSequence(key) {
      return redis.incr(key);
    },
  };
}

export function createRedisCompletionStore(redis: Redis): AgentCompletionStore {
  return {
    async commit(completionKey, completionValue, events) {
      const script = `
        local stream_type = redis.call('TYPE', KEYS[1]).ok
        if stream_type ~= 'none' and stream_type ~= 'stream' then
          return redis.error_reply('agent event key is not a stream')
        end
        for index = 3, #ARGV do
          redis.call('XADD', KEYS[1], 'MAXLEN', '~', ARGV[1], '*', 'payload', ARGV[index])
        end
        redis.call('SET', KEYS[2], ARGV[2])
        return #ARGV - 2
      `;
      const serializedEvents = events.map(serializeAgentEvent);
      const result = await redis.eval(
        script,
        2,
        AGENT_EVENT_STREAM,
        completionKey,
        AGENT_EVENT_STREAM_MAXLEN,
        completionValue,
        ...serializedEvents,
      );
      if (Number(result) !== serializedEvents.length) {
        throw new Error("Redis completion script did not publish every terminal event.");
      }
    },
  };
}

export function createRedisStreamPort(redis: Redis): RedisStreamPort {
  return {
    async xadd(stream, ...args) {
      const result = await redis.call("XADD", stream, ...args);
      return result === null ? null : String(result);
    },
  };
}
