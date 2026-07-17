# syntax=docker/dockerfile:1
# Agent Worker image (Node 20 LTS + TypeScript).
FROM node:20-slim AS base

WORKDIR /app

# Enable pnpm via corepack (pinned by the root packageManager field).
RUN corepack enable

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY packages ./packages
COPY workers ./workers

RUN pnpm install --frozen-lockfile

WORKDIR /app/workers/agent-worker
EXPOSE 8081
CMD ["pnpm", "start"]
