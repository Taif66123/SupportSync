# SupportSync — Development Rules

Customer support platform: customers create tickets, chat with support agents in real time, and get live notifications. Backend API (FastAPI + SQLModel + Postgres + Redis) complete through **Milestone 3** (auth, users, tickets, WebSocket chat, SSE notifications, Redis fan-out, rate limiting). M4+ adds the frontend.

## Commands

```bash
docker compose up -d                # start Postgres + Redis
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows/Git Bash
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env                # then edit secrets
alembic upgrade head                # apply migrations
uvicorn app.main:app --reload       # run the API (docs at /docs)
python -m app.seeds.demo            # demo data
pytest                              # tests (sqlite by default; see below)
TEST_DATABASE_URL="postgresql+psycopg://..." pytest   # full suite on Postgres
alembic check                       # verify models ↔ database have zero drift
```

## Architecture — non-negotiable

- **Modular monolith**: business code lives in `app/modules/<feature>/`. See `docs/adr/0002`.
- **Layering inside every module**: Router → Service → Repository.
  - Routers: HTTP concerns only (status codes, request/response models). No DB access, no business rules.
  - Services: business rules, permissions, transactions. Commit happens once per request via the session dependency.
  - Repositories: the only code that touches the database. Explicit, boring, per-module — no generic BaseRepository.
- **Cross-module boundary**: models and schemas are shared contracts (importable); services may be called from other modules; repositories are private to their owning module.
- **Declarative policy tables, not if-branches.** Authorization/lifecycle rules live in one place per domain and are consumed by endpoints and table-driven tests: `tickets/policy.py` (transitions, ADR 0001), `chat/policy.py` (per-ticket chat, deliberately independent of the tickets policy), `notifications/policy.py` (recipients). Do not add role/status `if` branches in services or routers; extend the table instead.
- **Domain rules that shape code:**
  - Tickets are immutable after creation; `closed` is terminal (ADR 0001).
  - Users are deactivated, never deleted; nothing is hard-deleted (ADR 0004) — FKs therefore declare no `ON DELETE` actions.
  - Refresh tokens are stored hash-only (SHA-256), rotated on every use (ADR 0003).
  - Chat wire protocol is typed in `chat/schemas.py` (pydantic frame models) — never hand-build frame dicts in the router.
- **Notifications are commit-gated.** `notifications/service.notify()` queues on the session and publishes only in SQLAlchemy's `after_commit` (rolled-back work never notifies). Emission failures must never fail the business action.
- **Redis is a bridge, not a replacement.** The local hub remains each worker's fan-out; Redis pub/sub carries events across workers (`notifications/bus.py`, envelope carries recipients + worker `origin`). **Everything Redis is fail-open**: rate limiting (`core/ratelimit.py`) and cross-worker fan-out degrade to local-only behavior, fronted by a shared circuit breaker in `core/redis.py` (one failure → instant fail-open for a cooldown, then one probe). Rate limits: login 5/min/IP · register 3/min/IP · refresh 30/min/IP · chat send 30/min/user · ticket create 10/min/user → 429 with `code: "rate_limited"`. Known constraint: chat WS rooms are single-worker; only notifications fan out across workers.
- Domain vocabulary is defined in `CONTEXT.md` — use those terms in code names.

## Conventions

- Config comes from env via `app/core/config.py` (pydantic-settings). Never read `os.environ` elsewhere.
- All timestamps: timezone-aware UTC. All datetimes in/out of the API: UTC ISO-8601.
- Errors: raise the typed exceptions from `app/core/errors.py`; the handlers produce `{"error": {"code", "message"}}`. Never hand-build error JSONResponses in routers.
- Migrations: Alembic is the source of truth. Schema changes = edit models + `alembic revision --autogenerate -m "..."`, run the migration-safety checklist in the `database-schema-designer` skill, review the script, then `upgrade head`. `alembic check` must report zero drift afterwards.
- **Database documentation of record: `docs/database-design.md`** (Mermaid ERD, per-table specs, index justifications, ADR cross-refs). Descriptive, never prescriptive — models + migrations win. Update it in the same change as any schema change, and refresh its verification stamp.
- Tests: pytest, table-driven where a matrix of rules exists (`tests/test_policy.py`). `TEST_DATABASE_URL` overrides the test DB; default is sqlite, CI and integration runs use Postgres from docker-compose. Tests are hermetic w.r.t. Redis: conftest points `REDIS_URL` at an unreachable port and disables the bus, so fail-open paths are exercised for real.

## Skills

Configured in `.agents/skills/` and mirrored in `.claude/skills/` — **keep both copies identical** when a skill changes (the mirror exists so both harness generations find them).

| Skill | Use it for |
|---|---|
| `grilling` | Interrogate requirements before designing — every milestone starts here |
| `grill-with-docs` | Same interview, also writing `CONTEXT.md` glossary + ADRs as it goes |
| `domain-modeling` | Changing the domain model: terminology, `CONTEXT.md`, recording ADRs |
| `codebase-design` | Interface/module design decisions — deep modules, small interfaces |
| `database-schema-designer` | Any schema change or new table; also regenerates/verifies `docs/database-design.md`; carries the Alembic migration-safety checklist |
| `code-review` | Two-axis review (standards + spec) of a diff against a fixed point |
| `thermo-nuclear-code-quality-review` | Strict structural/maintainability pass after implementing |
| `setup-matt-pocock-skills` | One-time harness setup (already done — do not re-run) |

**Working loop per milestone:** `grilling` (or `grill-with-docs` for first-touch domains) → `codebase-design` for interfaces → implement → `code-review` + `thermo-nuclear-code-quality-review` → schema touched? `database-schema-designer` verifies `docs/database-design.md` + `alembic check` → docs (`HANDOFF.md`, `docs/milestones.md`) → commit.
