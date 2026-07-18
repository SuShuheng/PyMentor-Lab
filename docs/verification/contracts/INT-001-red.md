# INT-001 transport contract gate — Red evidence

Date: 2026-07-19
Platform: Windows, Python 3.13, Node.js 22, pnpm 11.13.1

## Passing component baselines

- Zod schema export and conformance completed with 80 models and all existing
  fixtures parsed.
- Pydantic parity completed with 162 passing cases.

These results show that the committed Pydantic and Zod model implementations
agree for their existing shared fixture set.

## Blocking integration findings

1. The root pnpm workspace omits `apps/web`, `apps/admin`, `packages/ui`,
   `packages/charts`, and `packages/config`. Root recursive typecheck/test
   commands therefore do not exercise the integrated frontend.
2. Neither renderer declares `@pymentor/api-client`, so generated-client
   consumption cannot be proven.
3. Regenerating the OpenAPI document from the integrated FastAPI application
   changes `openapi.json` by 4,333 insertions and 1,195 deletions and changes
   generated `types.gen.ts` by 1,044 insertions and 106 deletions. The
   committed generated client is stale.

The non-mutating integration gate reproduces all three findings with three
focused failing tests. Generated diagnostic files were restored after the
freshness comparison; no backend-owned generated output is retained in the
integration worktree.

## Ownership and unblock conditions

- Backend owner: add the five frontend projects to the root workspace,
  regenerate and commit the OpenAPI client, and make the canonical freshness
  command fail without leaving stale output.
- Frontend owner: declare and use `@pymentor/api-client` in both renderers for
  server calls instead of leaving the generated transport boundary unused.
- Integration resumes INT-001 after both owner commits are merged. The focused
  gate must pass before shared invalid/version/order fixtures are expanded.
