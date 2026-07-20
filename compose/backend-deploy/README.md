# PyMentor Lab - Backend deployment kit (self-contained)

This folder is a complete, standalone copy of the PyMentor Lab backend stack.
The Bootstrapper unpacks it to `Documents\PyMentorLab-Backend` on first install.
You can also deploy it manually on Linux/macOS/WSL.

## Layout

| Path | Purpose |
| --- | --- |
| `code/`                | Full source tree (backend, workers, packages, knowledge, infra, sandbox). |
| `docker-compose.yml`   | The stack definition (build context = `./code`). |
| `.env.example`         | Template environment. Copy to `.env` and edit. |
| `deploy.ps1` / `deploy.sh`        | First-time deploy + healthcheck. |
| `upgrade.ps1` / `upgrade.sh`      | Rolling upgrade (volumes preserved). |
| `rollback.ps1` / `rollback.sh`    | Stop + rollback instructions. |
| `backup.ps1` / `backup.sh`        | `pg_dump` to `backups/`. |
| `restore.ps1` / `restore.sh`      | Restore a backup dump. |
| `healthcheck.ps1` / `healthcheck.sh` | Report service status. |

## First-time deploy (Windows)

1. Make sure **Docker Desktop** is running.
2. Copy `.env.example` to `.env` and edit. Set at minimum:
   - `PYMENTOR_PROVIDER_MASTER_KEY`
     (`python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`)
   - `PYMENTOR_INITIAL_ADMIN_EMAIL` (must be a real email like `admin@pymentor.dev`)
   - `PYMENTOR_INITIAL_ADMIN_PASSWORD` (min 8 chars)
3. Run `.\deploy.ps1`.
4. After the stack is healthy, the Bootstrapper has already set
   `PYMENTOR_DESKTOP_WEB_URL=http://127.0.0.1:4173` as a machine environment
   variable. **Restart the PyMentor Lab desktop app** so it picks up the URL.

## First-time deploy (Linux/macOS/WSL)

```bash
cp .env.example .env
# edit .env
./deploy.sh
```

## URLs (after deploy)

| Service | URL |
| --- | --- |
| API (docs) | http://127.0.0.1:8000/docs |
| Student web | http://127.0.0.1:4173 |
| Admin web | http://127.0.0.1:4174 |
| MinIO console | http://127.0.0.1:9001 |

## Common operations

```powershell
.\healthcheck.ps1               # status of every service
.\upgrade.ps1                   # rebuild + recreate (data preserved)
.\backup.ps1                    # dump Postgres to backups/
.\restore.ps1 -File backups\pymentor-...sql.gz
.\deploy.ps1 -FreshDatabase     # WARNING: deletes volumes + reseeds
.\deploy.ps1 -ForcePort         # auto-kill any process on a required port
```

## Notes

- The stack binds only to `127.0.0.1`. To expose it on a LAN, edit the `ports:`
  block in `docker-compose.yml` and update `PYMENTOR_CORS_ALLOWED_ORIGINS`.
- The desktop app reads `PYMENTOR_DESKTOP_WEB_URL` from the **machine**
  environment, not from this `.env`. The Bootstrapper sets it on Windows; on
  other OSes set it in your shell profile.
- If you move the backend to another host, update the machine env var to
  `https://your-host/app` and restart the desktop app.
