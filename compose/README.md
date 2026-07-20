# PyMentor Lab — compose/

This directory holds the **source** for the Windows build pipeline and the
self-contained backend deployment kit. None of the generated artifacts live
here — they are emitted under `dist/` (which is fully gitignored).

## Layout

```
compose/
├── README.md                  This file.
├── build-dist.mjs             ZIP assembler (Node, no external deps). Copies
│                              compose/backend-deploy/ + the source tree into
│                              dist/backend-deploy/, then writes the kit zip.
├── bootstrapper.iss           Inno Setup installer source. Embeds the student
│                              EXE + backend kit zip into PyMentorLab-Bootstrapper.exe.
└── backend-deploy/            Self-contained backend deployment kit (tracked source):
    ├── .env.example           Environment template (REQUIRED keys documented inside).
    ├── docker-compose.yml     Stack definition (build context = ./code).
    ├── README.md              Kit deployment guide.
    ├── deploy.ps1 / .sh       First-time deploy + port-occupancy check + healthcheck.
    ├── upgrade.ps1 / .sh      Rolling upgrade (volumes preserved).
    ├── rollback.ps1 / .sh     Stop + rollback instructions.
    ├── backup.ps1 / .sh       pg_dump -> backups/.
    ├── restore.ps1 / .sh      Restore a backup dump.
    └── healthcheck.ps1 / .sh  Report service status.
```

## How a release is built

`compose_mee.bat <version>` (at the repo root) runs the full pipeline:

1. Generate brand icon (`infra/icons/generate-icons.py`).
2. Build the Electron student EXE (`pnpm make:win` in `apps/desktop`).
3. Run `node compose/build-dist.mjs <version>` — copies `compose/backend-deploy/*`
   + the source tree into `dist/backend-deploy/`, then writes
   `dist/backend-deploy/pymentor-backend-<ver>.zip` and mirrors it to
   `dist/installer-source/installer-assets/backend-deploy.zip`.
4. Stage the icon + student EXE alongside the zip under
   `dist/installer-source/installer-assets/`.
5. Compile `compose/bootstrapper.iss` with Inno Setup — emits
   `dist/installer/PyMentorLab-Bootstrapper.exe` (embeds the student EXE + kit).
6. Copy all three artifacts to `dist/<VERSION>/`.

All output paths live under `dist/`, which is gitignored. Only the source
files under `compose/` (and the backend kit's `.env.example`, `docker-compose.yml`,
scripts, README) are tracked.

## Bootstrapper UX (v2)

The Inno Setup installer (`bootstrapper.iss`) does:

1. **`main` component** — silently installs the Electron student app via Squirrel.
2. **`backend` component** (optional):
   - Shows a wizard page collecting admin email/password + Provider master key
     (auto-generates the master key if left blank).
   - Unpacks the backend kit to `Documents\PyMentorLab-Backend`.
   - Probes Docker **inline** from PascalScript (no external `.ps1` — this fixes
     the `-196608` exit code from v1, where the probe ran before `[Files]`
     extracted its helper script).
   - Writes `.env` with the captured credentials.
   - Sets `PYMENTOR_DESKTOP_WEB_URL=http://127.0.0.1:4173` as a **machine**
     environment variable (`HKLM\...\Environment`) so the desktop shell finds
     the student web frontend. Restart the desktop app for it to take effect.
   - Offers to launch `deploy.ps1`, which handles port-occupancy detection
     and asks before killing any conflicting process.

## Conventions

- All host-facing URLs use `127.0.0.1` (never `localhost`) per the deployment
  convention. The desktop env var, CORS allowlist, object store endpoint, and
  display messages all follow this rule.
- Port conflicts are handled by `deploy.ps1` (`-ForcePort` skips the prompt).
- Versions are parameterized: `compose_mee.bat V1.1.5` -> `dist/V1.1.5/`.
  The bare version (`1.1.5`) is used in the zip filename.
