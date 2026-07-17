# syntax=docker/dockerfile:1
# Agent Worker image (Node 22 LTS; required by the pinned pnpm 11 runtime).
FROM node:22-slim AS base

WORKDIR /app

# Enable pnpm via corepack (pinned by the root packageManager field).
ENV COREPACK_HOME=/opt/corepack
RUN mkdir -p "$COREPACK_HOME" \
    && corepack enable \
    && corepack prepare pnpm@11.13.1 --activate \
    && chmod -R a+rX "$COREPACK_HOME"

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml tsconfig.base.json ./
COPY packages ./packages
COPY workers ./workers

RUN pnpm install --frozen-lockfile
RUN pnpm --filter @pymentor/agent-worker typecheck

WORKDIR /app/workers/agent-worker
ENV NODE_ENV=production
EXPOSE 8081
USER node
CMD ["pnpm", "start"]
