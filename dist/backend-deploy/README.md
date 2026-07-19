# PyMentor Lab v1.1 — Backend Deployment Package

A **self-contained** deployment bundle: the full source tree plus production
Docker Compose config and operational scripts. Unzip on a machine that has
Docker installed, edit one file (`.env`), run one script, and the stack is up.
**No `git clone` is required.**

## What is in here

```
backend-deploy/
├── README.md              this file
├── deploy.sh / .ps1       first-time + repeat deploy entrypoint
├── upgrade.sh / .ps1      rebuild + restart on a new source drop
├── rollback.sh / .ps1     stop stack + restore DB from a backup
├── backup.sh / .ps1       gzipped pg_dump into ./backups/
├── restore.sh / .ps1      restore DB from a specific backup file
├── healthcheck.sh / .ps1  poll API /health + print `docker compose ps`
├── docker-compose.yml     production variant (build context = ./code)
├── .env.example           deployment env template (with inline generation hints)
├── code/                  FULL source tree (filled by build-dist.mjs)
└── backups/               created on demand by backup.sh
```

`.sh` scripts are for Linux/macOS (and Git Bash on Windows). `.ps1` scripts are
functionally equivalent and intended for native Windows PowerShell. Each pair
is interchangeable.

## Prerequisites

The only hard requirement is **Docker** with the **Compose V2** plugin
(`docker compose version` must work).

- Docker Engine 24+ or Docker Desktop 4.34+ (Windows/macOS).
- Compose V2 plugin enabled (Docker Desktop: Settings → "Use Docker Compose V2").
- ~4 GB free RAM for the stack, ~5 GB disk for images.
- Ports `5432, 6379, 9000, 9001, 8000, 8081, 4173, 4174` free on `127.0.0.1`.
- For backups: `gunzip` on PATH if you use restore.sh on Linux/macOS. Windows
  users should use restore.ps1, which runs gzip inside the container.

You do **not** need Node, Python, pnpm, uv, or git installed on the host —
everything builds inside Docker.

## First-time deploy

### Linux / macOS / Git Bash

```bash
./deploy.sh
```

The first run detects that `.env` is missing, copies `.env.example` to `.env`,
prints the list of secrets to fill in, and exits 0 (it will **not** start with
default secrets). Edit `.env`, then run `./deploy.sh` again.

### Windows PowerShell

```powershell
.\deploy.ps1
```

If execution is blocked, run once:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Same `.env` workflow as above.

## Secrets you MUST set

Open `.env` and configure the three `[REQUIRED]` values before the second run:

| Variable | Purpose | How to generate |
|---|---|---|
| `PYMENTOR_PROVIDER_MASTER_KEY` | AES-256 key encrypting stored provider API keys. Keep stable forever. | `python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"` |
| `PYMENTOR_INITIAL_ADMIN_EMAIL` | First admin login email (must be a deliverable email address). | Pick one, e.g. `admin@yourdomain.edu` |
| `PYMENTOR_INITIAL_ADMIN_PASSWORD` | First admin login password. | Pick a strong one |

Also **rotate** these defaults away from the `dev-only-insecure-*` placeholder
values that ship in `.env.example`:

- `POSTGRES_PASSWORD`
- `MINIO_ROOT_PASSWORD`
- `PYMENTOR_JWT_SECRET`
- `PYMENTOR_WORKER_INTERNAL_SECRET`
- `PYMENTOR_SANDBOX_SECRET`

Generation command for any 32+ byte URL-safe secret:
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Accessing the running stack

After a successful deploy the stack prints a banner with URLs. Quick reference:

| URL | What |
|---|---|
| http://localhost:8000/docs | FastAPI Swagger UI (API exploration, admin login endpoint) |
| http://localhost:4173 | Student-facing web app |
| http://localhost:4174 | Operator/admin web app |
| http://localhost:9001 | MinIO console (object storage browser) |
| `localhost:5432` | Postgres (user/db `pymentor`, password = `POSTGRES_PASSWORD`) |
| `localhost:6379` | Redis |
| `localhost:9000` | MinIO S3 API |

All ports are bound to `127.0.0.1` — the stack is **not** exposed on other
network interfaces. To serve external users, put a reverse proxy (nginx,
Caddy, Traefik) in front and adjust `PYMENTOR_CORS_ALLOWED_ORIGINS`.

## Day-2 operations

### Healthcheck

```bash
./healthcheck.sh            # Linux/macOS
.\healthcheck.ps1           # Windows
```
Polls `http://localhost:8000/health` and prints `docker compose ps`. Exits 0
when healthy, non-zero on timeout.

### Backup

```bash
./backup.sh                 # writes backups/pymentor-YYYYMMDD-HHMMSS.sql.gz
.\backup.ps1
```
Runs `pg_dump` inside the postgres container, pipes through gzip, writes to
`./backups/`. Safe to run while the stack is up. Print the path and size when
done. Run this before every upgrade.

### Restore

```bash
./restore.sh backups/pymentor-20260719-103015.sql.gz
.\restore.ps1 -BackupFile backups\pymentor-20260719-103015.sql.gz
```
DESTRUCTIVE — confirms before overwriting. The stack must be up so the postgres
container is reachable.

### Upgrade

When you receive a new backend-deploy zip:

1. `./backup.sh` (always back up first).
2. Replace `code/` with the new source tree from the new archive.
3. `./upgrade.sh` — runs `docker compose build --pull && up -d`. Volumes are
   preserved, so Postgres/Redis/MinIO data survives.

### Rollback (read this carefully)

This package **builds images locally** — there is **no image registry**, so
there are no per-version image tags to switch back to. A true image-tag
rollback requires pushing images to a registry, which this package does not do.

What "rollback" means here is **database restore**:

```bash
./rollback.sh                                   # uses newest backup in ./backups/
./rollback.sh backups/pymentor-20260719-103015.sql.gz
.\rollback.ps1
.\rollback.ps1 -BackupFile backups\pymentor-20260719-103015.sql.gz
```

`rollback.sh` will:
1. Stop the running stack (`docker compose down` — volumes preserved).
2. Bring up only the postgres container.
3. Restore the DB from the chosen backup file.
4. Leave the rest of the stack stopped; you then run `./deploy.sh` to bring it
   back up with the restored data.

To also **roll back the CODE** to a previous version, replace `code/` with the
previous archive's source tree and run `./upgrade.sh`.

## Ports you might want to change

If you need to change a port to avoid a conflict, edit **both** places:

| Port | Service | Edit in `docker-compose.yml` | Also update in `.env` |
|---|---|---|---|
| 5432 | Postgres | `postgres.ports` | `PYMENTOR_DATABASE_URL` |
| 8000 | FastAPI | `api.ports` | (used by external clients) |
| 4173 | Web app | `web.ports` | `PYMENTOR_CORS_ALLOWED_ORIGINS` |
| 4174 | Admin app | `admin.ports` | `PYMENTOR_CORS_ALLOWED_ORIGINS` |

The other ports (6379 Redis, 9000/9001 MinIO, 8081 Worker) rarely need
changing; if you do change 9000, also update `PYMENTOR_OBJECT_STORE_ENDPOINT`.

## How this package was built

Run `node dist/build-dist.mjs` from the repository root. It copies the source
tree (`backend/`, `workers/`, `packages/`, `knowledge/`, `infra/`, `sandbox/`,
root config files) into `code/`, then zips the whole `backend-deploy/` folder
into `pymentor-backend-v1.1.zip`. The committed artifacts in this folder
(`docker-compose.yml`, `.env.example`, the scripts, this README) are source;
`code/` and `*.zip` are generated and gitignored.

## Troubleshooting

- **`docker compose` not found.** Install Docker Desktop or the Compose V2
  plugin. On Docker Desktop, enable "Use Docker Compose V2" in Settings.
- **Port already allocated.** Another process is using one of the listed
  ports. Either stop it or change the port in `docker-compose.yml` (see
  "Ports you might want to change").
- **API never becomes healthy.** Check `docker compose -p pymentor-prod logs
  api` and `docker compose -p pymentor-prod ps`. Common cause: an invalid
  `PYMENTOR_INITIAL_ADMIN_EMAIL` (must be a deliverable email address, not
  `admin@something.local`).
- **Sandbox fails to start.** The sandbox supervisor mounts
  `/var/run/docker.sock` read-only. On Docker Desktop for Windows/macOS, make
  sure the daemon is running and the socket is exposed to containers (it is by
  default).
- **Backup file is empty.** The postgres container probably was not up. Run
  `./deploy.sh` first; verify with `./healthcheck.sh`.

## License

CC BY-NC 4.0 (non-commercial, learning use only). See `code/README.md` and
`code/NOTICE` for details.
