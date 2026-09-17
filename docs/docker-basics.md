# Docker & local stack — operator's cheatsheet

Day-to-day commands for running the SupportSync stack on this machine (Windows, Git Bash). Machine-specific facts live here; generic docs live in the README.

## This machine's specifics

- **Our Postgres runs on port 5433**, not 5432 — a native Windows PostgreSQL 18 service (`postgresql-x64-18`) owns 5432. Don't stop that service.
- Port mapping: root `.env` → `POSTGRES_PORT=5433` · backend `.env` → `DATABASE_URL=postgresql+psycopg://supportsync:supportsync@localhost:5433/supportsync`
- Docker Desktop does not auto-start; launch it from the Start menu, wait for the whale icon, then check with `docker ps`.
- WSL2 + Virtual Machine Platform are installed and working (fixed 2026-09-17; a reboot was required after enabling the feature).

## Daily sequence

```bash
# 1. Docker alive?
docker ps

# 2. Database up + healthy (from repo root)
cd /c/Github/SupportSync
docker compose up -d
docker compose ps                # wait for "healthy"

# 3. Backend (new terminal or same one)
cd backend
. .venv/Scripts/activate         # every new terminal
alembic upgrade head             # after clone, and after any model change
python -m app.seeds.demo         # once; idempotent ("Seed skipped" = fine)

# 4. Run the API
uvicorn app.main:app --reload    # → http://127.0.0.1:8000/docs  (Ctrl+C to stop)

# 5. Tests
pytest                                                    # sqlite, fast, no Docker
TEST_DATABASE_URL="postgresql+psycopg://supportsync:supportsync@localhost:5433/supportsync_test" pytest
```

## Inspecting the database

```bash
docker exec -it supportsync-db-1 psql -U supportsync -d supportsync
```
Inside: `\dt` tables · `\d tickets` describe · `SELECT ...` queries · `\q` quit.

Demo logins (after seeding): `admin@example.com` / `admin123!` · `maya.chen@example.com` / `agent123!` (agent) · `lena@example.com` / `customer123!` (customer).

## Lifecycle / data safety

```bash
docker compose stop      # pause — data kept
docker compose start     # resume
docker compose down      # remove container — data SURVIVES in the supportsync_pgdata volume
docker compose down -v   # ⚠ ALSO deletes the volume — full data wipe; then re-run alembic + seeds
```

## Troubleshooting

| Symptom | Meaning | Fix |
|---|---|---|
| `daemon is not running` | Docker Desktop not started | Launch it, wait, retry `docker ps` |
| Virtualization error on Desktop start | WSL2 not ready | `wsl --status`; enable Virtual Machine Platform; reboot |
| `password authentication failed` | You hit **5432** (native PG18), not ours | Use 5433; check `backend/.env` |
| `relation "users" does not exist` | Empty database | `alembic upgrade head` |
| `port is already allocated` | 5433 taken | Change `POSTGRES_PORT` (root `.env`) + `DATABASE_URL` (backend `.env`) |
| `Seed skipped` | Not an error — idempotent seeds | Nothing |

## Reading the output — what healthy looks like

Run the sequence top to bottom; each step has one green-light signal:

| Command | Success looks like | Red flags |
|---|---|---|
| `docker ps` | Empty table header (no containers yet) | `error during connect` → Desktop not started |
| `docker compose up -d` | `✔ Container supportsync-db-1  Started` | ✖ / red text (port taken, pull failed) |
| `docker compose ps` | `Up 2 minutes (healthy)` + `0.0.0.0:5433->5432/tcp` | `(health: starting)` → wait; `Restarting`/`Exited` → logs |
| `docker compose logs db` | ends with `database system is ready to accept connections` | `FATAL`/`PANIC`, same lines repeating forever |
| `alembic upgrade head` | `Running upgrade -> 0001, ...` first time; **silence** afterwards | `sqlalchemy.exc.OperationalError` traceback → DB unreachable |
| `python -m app.seeds.demo` | `Seeded: 1 admin ...` or `Seed skipped: admin already exists` (both fine) | Python traceback |
| `uvicorn ... --reload` | `Application startup complete.` then `/docs` in browser | startup traceback (config/DB bug), `Address already in use` |
| `pytest` | `68 passed, 2 warnings` — warnings are fine | `FAILED tests/...` lines |

**HTTP status codes in the uvicorn log** (and /docs): 200/201 good · 401 auth (re-login) · 403 wrong role (expected) · 404 invisible-by-design or missing · 409 business rule correctly rejecting you · 422 malformed body (read `message`) · 500 real bug (copy traceback).

## Migrations (Alembic) — version control for the schema

Models (`app/modules/**/models.py`) are the source of truth for what the schema *should be*; migration scripts (`migrations/versions/`) are the source of truth for *how we get there*. The DB tracks its position in a small `alembic_version` table — running `upgrade head` twice is safe (second run is a no-op).

```bash
# When you change a model (M2 will, for the Message table):
alembic revision --autogenerate -m "describe the change"   # 1. generate draft by diffing models vs live DB
#                                                          # 2. OPEN and REVIEW the generated file (autogenerate misses
#                                                          #    renames — it sees drop+add; never apply unread)
alembic upgrade head                                       # 3. apply
alembic current                                            # which revision is this DB at?
alembic history                                            # all revisions
alembic downgrade -1                                       # undo last (dev only, careful with data)
```

Tests bypass this (`metadata.create_all` on throwaway DBs) — everything real (dev DB, CI, production) goes through Alembic.

## Useful extras

```bash
docker compose logs -f db          # follow database logs (Ctrl+C to exit)
docker exec supportsync-db-1 env | grep POSTGRES   # what creds the container was initialized with
docker volume ls                   # list volumes (supportsync_pgdata holds all project data)
```
