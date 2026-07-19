# INT-002 identity and onboarding — Red evidence

Date: 2026-07-19

The initial integration gate intentionally requires real browser-to-API and
generated-client boundaries before a Playwright success path is accepted.

Expected owner failures at the integrated baseline:

1. FastAPI must authorize the declared Web/Admin origins for credentialed
   browser calls; unit-only generated-client tests do not prove this.
2. Demo Guest needs a public, bounded login endpoint scoped to the demo tenant.
3. `ProfileSnapshot` must expose its immutable profile-version ID so a dispute
   can reference the version the student actually viewed.
4. Web must consume generated demo/profile/dispute calls rather than throwing
   for demo and rendering a hard-coded profile.
5. Admin must consume generated pending/approve/reject calls rather than
   mutating a hard-coded registration list.

Ownership returns CORS, demo login, profile identity, contracts, and generated
client work to backend; live Student/Admin bindings return to frontend. The
integration lane retains only this reproducible gate and evidence until both
owner commits are merged.
