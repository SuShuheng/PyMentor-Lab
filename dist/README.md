# PyMentor Lab v1.1 — Distribution

This folder produces **two shippable artifacts** for end users:

1. **`backend-deploy/pymentor-backend-v1.1.zip`** — a self-contained backend
   deployment package. Unzip on any machine with Docker installed, edit one
   `.env` file, and `docker compose up --build` brings up the entire stack.
   No `git clone`, no Node/Python/pnpm toolchain on the host.
2. **`installer/pymentor-setup-v1.1.exe`** (built later by the installer lane)
   — a Windows installer (Inno Setup) that embeds the backend-deploy zip and
   walks the user through extraction + first deploy.

This folder holds the **source** for both artifacts. Generated outputs are
gitignored (see the root `.gitignore`).

## Layout

```
dist/
├── README.md                          this file
├── build-dist.mjs                     Node ESM assembler (no external deps)
├── backend-deploy/                    SOURCE for the deploy zip
│   ├── README.md                      user-facing deploy docs
│   ├── docker-compose.yml             production variant (build context = ./code)
│   ├── .env.example                   deploy env template
│   ├── deploy.sh / .ps1               deploy entrypoint (bash + powershell)
│   ├── upgrade.sh / .ps1              rebuild + restart
│   ├── rollback.sh / .ps1             stop + DB restore (no image tags; see README)
│   ├── backup.sh / .ps1               gzipped pg_dump into ./backups/
│   ├── restore.sh / .ps1              restore DB from a backup file
│   ├── healthcheck.sh / .ps1          poll /health + `docker compose ps`
│   ├── code/                          GENERATED — full source copy (gitignored)
│   └── pymentor-backend-v1.1.zip      GENERATED — the shippable zip (gitignored)
└── installer-source/                  SOURCE for the Windows installer
    ├── README.md                      (added by the installer lane)
    ├── pymentor-setup.iss             Inno Setup script (added by the installer lane)
    ├── installer-assets/              GENERATED — backend-deploy.zip copy (gitignored)
    └── tools/                         GENERATED — Inno Setup compiler if vendored
```

Files marked **GENERATED** are produced by `build-dist.mjs` and are gitignored.
Files marked **SOURCE** are committed; edit them directly.

## Building the backend-deploy zip

Prerequisites: Node.js 18+ (only Node, no npm install needed — the script uses
only the standard library).

From the repository root:

```bash
node dist/build-dist.mjs
```

What it does:
1. Creates `dist/backend-deploy/code/`, `dist/installer-source/installer-assets/`,
   and `dist/installer/` if they do not exist.
2. Copies the source tree (`backend/`, `workers/`, `packages/`, `knowledge/`,
   `infra/`, `sandbox/`, plus root config files) into `code/`, skipping
   `node_modules`, `.venv`, `.git`, caches, `dist`, `build`, etc.
3. Writes a ZIP of the entire `backend-deploy/` folder to
   `backend-deploy/pymentor-backend-v1.1.zip` using a **self-contained** ZIP
   writer (Node `zlib` only — no `7z`, `zip`, or PowerShell required). The
   archive is compatible with Windows Explorer, 7-Zip, `unzip`, and Java
   `ZipInputStream`.
4. Copies the zip to `installer-source/installer-assets/backend-deploy.zip`
   so the Inno Setup stage can embed it.
5. Prints a summary: file count, source size, zip entry count, zip size.

The expected compressed size is **1–3 MiB** (source code only; no
`node_modules` or Python venvs).

## Building the Windows installer

The Inno Setup `.iss` script and its build invocation are owned by the
**installer lane** and added to `dist/installer-source/`. The output EXE lands
in `dist/installer/`. See `dist/installer-source/README.md` (added by the
installer lane) for build steps once that script exists.

## End-to-end release flow

1. **Backend lane** (this folder): `node dist/build-dist.mjs` produces
   `dist/backend-deploy/pymentor-backend-v1.1.zip` and seeds
   `dist/installer-source/installer-assets/backend-deploy.zip`.
2. **Installer lane**: writes `dist/installer-source/pymentor-setup.iss`,
   invokes the Inno Setup compiler against it, and emits
   `dist/installer/pymentor-setup-v1.1.exe`.
3. **Integration lane**: ships both the zip (for Linux/macOS/PowerShell users)
   and the EXE (for Windows users who want a guided install).

## Releasing a new version

1. Bump `VERSION` in `dist/build-dist.mjs` (and the matching references in
   `dist/backend-deploy/README.md`, `.env.example`, `deploy.sh`, `deploy.ps1`
   if the user-facing version label matters).
2. Re-run `node dist/build-dist.mjs`.
3. Smoke-test the zip on a clean machine with only Docker installed.
4. Re-run the installer-lane build to produce a matching EXE.
