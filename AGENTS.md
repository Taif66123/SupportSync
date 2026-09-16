# SupportSync — Development Rules

A small customer support backend: customers create tickets and chat with support agents in real time. Currently backend-only, Milestone 1.

## Commands

```bash
docker compose up -d                # start Postgres
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows/Git Bash
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env                # then edit secrets
alembic upgrade head                # apply migrations
uvicorn app.main:app --reload       # run the API (docs at /docs)
python -m app.seeds.demo            # demo data
pytest                              # tests (sqlite by default; see below)
```

## Architecture — non-negotiable

- **Modular monolith**: business code lives in `app/modules/<feature>/`. See `docs/adr/0002`.
- **Layering inside every module**: Router → Service → Repository.
  - Routers: HTTP concerns only (status codes, request/response models). No DB access, no business rules.
  - Services: business rules, permissions, transactions. Commit happens once per request via the session dependency.
  - Repositories: the only code that touches the database. Explicit, boring, per-module — no generic BaseRepository.
- **Cross-module boundary**: models and schemas are shared contracts (importable); services may be called from other modules; repositories are private to their owning module.
- **Ticket rules live in `app/modules/tickets/policy.py`** — the declarative transition/permission table. Do not add role/status `if` branches in services or routers; extend the table instead.
- Tickets are immutable after creation; `closed` is terminal; users are deactivated, never deleted (`docs/adr/0001`, `docs/adr/0004`).
- Domain vocabulary is defined in `CONTEXT.md` — use those terms in code names.

## Conventions

- Config comes from env via `app/core/config.py` (pydantic-settings). Never read `os.environ` elsewhere.
- All timestamps: timezone-aware UTC. All datetimes in/out of the API: UTC ISO-8601.
- Errors: raise the typed exceptions from `app/core/errors.py`; the handlers produce `{"error": {"code", "message"}}`. Never hand-build error JSONResponses in routers.
- Migrations: Alembic is the source of truth. Schema changes = edit models + `alembic revision --autogenerate -m "..."`, review the script, then `upgrade head`.
- Tests: pytest, table-driven where a matrix of rules exists (`tests/test_policy.py`). `TEST_DATABASE_URL` overrides the test DB; default is sqlite, CI and integration runs use Postgres from docker-compose.

## Skills

- `grill-with-docs` / `grilling`: interrogate requirements before designing (writes `CONTEXT.md` + `docs/adr/`).
- `codebase-design`: deep modules, small interfaces — used for interface design decisions.
- `thermo-nuclear-code-quality-review`: strict structural review pass after implementing.
