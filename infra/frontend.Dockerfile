FROM node:22-slim AS builder

WORKDIR /app
ENV COREPACK_HOME=/opt/corepack
RUN mkdir -p "$COREPACK_HOME" \
    && corepack enable \
    && corepack prepare pnpm@11.13.1 --activate \
    && chmod -R a+rX "$COREPACK_HOME"

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml tsconfig.base.json ./
COPY apps ./apps
COPY packages ./packages
RUN pnpm install --frozen-lockfile

ARG APP
RUN test "$APP" = "web" -o "$APP" = "admin" \
    && pnpm --filter "@pymentor/$APP" build \
    && mkdir -p /out \
    && cp -R "apps/$APP/dist/." /out/

FROM node:22-slim AS runtime
WORKDIR /app
COPY infra/frontend-server.mjs ./frontend-server.mjs
COPY --from=builder /out ./public
EXPOSE 8080
USER node
CMD ["node", "frontend-server.mjs"]
