# SupportSync — Handoff / Continuation Notes

Written 2026-09-16. Self-contained: everything a fresh session (human or LLM) needs to continue.

## 1. What this project is

**SupportSync** — a small customer-support application backend: a Customer creates a support Ticket and communicates with a Support Agent in real time. Backend only for now (no frontend yet). Stack: **FastAPI + PostgreSQL + SQLModel (SQLAlchemy 2) + Alembic + PyJWT + bcrypt + pytest + Docker (compose for infra) + Redis (M3: fan-out bridge + rate limiting)**. Environment: Windows, Git Bash, Python 3.14.7, Docker 29.7.2. Working dir: `C:\Github\SupportSync` (**git repo on `master`; committed through M3 — SHA map in §5**).

Planned milestones (full roadmap in `docs/milestones.md`):
- **M1 (✅ DONE — 68/68 tests green):** auth + users + tickets CRUD/lifecycle. Quality review pass complete.
- **M2 (✅ DONE — 94/94 tests green):** per-ticket WebSocket chat: instant delivery, REST history + REST post, typing indicators, read receipts, buffered pre-assignment messages, admin read-only, closed = read-only. M2 is feature-complete per `docs/milestones.md`.
- **M3 complete (✅ DONE — 118/118 tests green on sqlite + Postgres):** Phase A = SSE live notifications (commit-gated emissions, in-process hub); Phase B = Redis pub/sub bridge + fixed-window rate limiting, both fail-open behind a shared circuit breaker (`app/core/redis.py`: one failure → fail-open fast path for a 30 s cooldown, then a single probe dial; `stop_listener` is best-effort). The cross-worker bus is gated by `NOTIFICATIONS_BUS_ENABLED` (off in tests, on by default in prod — tests stay hermetic via `REDIS_URL=redis://127.0.0.1:9/0` conftest default).

## 2. Process that produced this design (user-requested workflow)

1. **Grilling** (Matt Pocock's `grill-with-docs` skill — 3 rounds of Q&A) → produced `CONTEXT.md` (domain glossary) and `docs/adr/0001–0004` (decision records).
2. **Refinement check** with Matt Pocock's `codebase-design` skill + **Cursor's `thermo-nuclear-code-quality-review`** skill → 6 findings folded into the design (see §4).
3. **Design-it-twice** (from `codebase-design`) on the policy interface → chose "ergonomic minimal" shape: `ensure() / scoped() / get_visible()` over a declarative rules table; explicitly rejected a rule-engine/registry design as a hypothetical seam.

All skills are installed in `.agents/skills/` (also mirrored in `.claude/skills/`): `grilling`, `grill-with-docs`, `domain-modeling`, `codebase-design`, `code-review`, `thermo-nuclear-code-quality-review`, `database-schema-designer`, `setup-matt-pocock-skills`. Read `SKILL.md` inside each before claiming to "use" them.

## 3. Locked design decisions (do not re-litigate; ADRs are authoritative)

**Roles & auth**
- Three roles: `customer`, `agent` (Support Agent), `admin`. Open self-registration → Customer only. Admin creates Agents/Admins.
- JWT access token (~15 min, stateless, claims: sub/role/type) + **rotating refresh tokens** stored as SHA-256 hashes in `refresh_tokens` table (7-day expiry, rotate on use, reuse-after-rotation rejected as 401) — ADR 0003.
- `POST /auth/logout` revokes presented refresh token. Password change / admin deactivation → revoke all of that user's tokens.
- Deactivated users: cannot log in, token auth fails (401). Deleted users: **never** (deactivate-only, ADR 0004).

**Tickets (ADR 0001)**
- Statuses: `open → in_progress → resolved → closed`.
- `claim`: Agent only, open+unassigned → in_progress, self-assigns. `assign`: Admin only, same source, assignee from payload (must be an active Agent). `resolve`: Agent, from in_progress. `reopen`: Agent, from resolved → in_progress. `close`: Customer (own tickets only, from any non-closed status) or Agent/Admin; sets `closed_at`.
- **`closed` is terminal for everyone** — follow-up = new ticket. Title/description **immutable** after creation. Priority: set by customer at creation (low/medium/high), mutable by Agent/Admin only, not on closed tickets.
- Explicit action endpoints only (no generic status PATCH): `POST /tickets/{id}/claim|assign|resolve|reopen|close`, `PATCH /tickets/{id}/priority`.
- **Visibility** (returns 404 for invisible — don't leak existence): Customer = own tickets; Agent = Queue (open+unassigned) + assigned-to-me; Admin = all.
- Claim/assign use an **atomic conditional UPDATE** (`WHERE status IN (...) AND agent_id IS NULL`, check rowcount) so racing agents can't both claim.

**Admin user management:** create staff (agent/admin only — customer role rejected 422), list/filter users (`role`, `is_active`, `q` on email/name), change role, deactivate/reactivate. Guards: cannot change own role; cannot deactivate self. The self-guards ARE the last-admin protection (actor is always an active admin and never the target — a separate "last admin" count check was deliberately deleted as dead code).

**Chat (M2, decided during M2 grilling):** scope = core chat (messages, instant delivery, history) + typing indicators; read receipts still deferred. Sending on a **closed** ticket → 403/`error.forbidden`, but history stays readable — closed is terminal (ADR 0001) yet not erased. Pre-assignment sends are allowed (buffered). WS auth = `?token=<access token>` query param (browsers can't set headers on the handshake), resolved **before** `accept()` with close code 1008 so an invisible ticket is indistinguishable from a nonexistent one. WS protocol (typed pydantic frames in `chat/schemas.py` — the protocol's single source of truth): client → `message.send{body}` / `typing.start` / `read.up-to{message_id}`; server → `connect.ack{can_send}` / `message.new{message}` / `typing.start{user_id}` (to the room except the typist; ephemeral, never persisted) / `read.receipt{user_id,message_id}` (to the whole room incl. the reader) / `error{code,message}`. Typing authorization = exactly the send rules (on a closed ticket nobody may type either). Read receipts: per-participant marker in `ticket_read_states` (one row per ticket×user, monotonic — never moves backwards; a repeat/backwards read is a silent no-op with no broadcast); receipts use the send rules (participants only, admins never generate them); a receipt for a message of another ticket → `not_found`; REST `GET /tickets/{id}/messages/read-states` serves the markers (read-authorized). Migration 0003 = `ticket_read_states`. A REST `POST /tickets/{id}/messages` mirrors socket sends (retries, clients without a live socket); `GET /tickets/{id}/messages` = paginated history, oldest first. `chat/policy.py` is a separate declarative table (never imports tickets policy — milestone boundary). WS connections own their transaction: **commit per message frame** (`session.commit()` in the WS handler is intentional and is the codebase's only direct commit).

**Notifications (M3 Phase A, decided during M3 grilling):** scope phased — Phase A = SSE core (built), Phase B = Redis pub/sub fan-out + the deferred rate limiting. Notifications are **ephemeral push** (user decision): no notifications table, no replay — offline clients catch up by fetching current state; the `TicketEvent` idea stays dead (YAGNI). Recipients come from `notifications/policy.py` (declarative table, same discipline as the other policies): `ticket.created` → all **active** Agents; `ticket.updated` / `message.created` → the conversation participants (Customer + assigned Agent); Admins observe, never get notified; the **actor is always subtracted**. Emissions are **commit-gated**: `notify()` resolves recipients once at queue time (with the real ticket), stashes `(recipients, notification)` on `session.info`, and SQLAlchemy `after_commit` publishes to the hub — a subscriber never hears about data it can't fetch; `after_rollback` discards. Emissions are fire-and-forget: notification failures must never fail the business action. `GET /api/v1/notifications/stream` = SSE, auth = Bearer header **or** `?token=` (EventSource can't set headers), 15 s keep-alive comment frames, media type `text/event-stream`, frame = `event: <type>` + `data: {type, at, payload}`.

**Deliberately dropped/deferred:** Redis rate limiting + pub/sub fan-out (M3 Phase B), `TicketEvent` table (YAGNI; twice-dead), CI/Jenkinsfile + backend Dockerfile (M4), frontend, cursor pagination (offset is fine).

**Architecture (ADR 0002):** modular monolith. Modules in `backend/app/modules/<name>/` each layered Router → Service → Repository. Routers = HTTP only; services = business rules + permissions; repositories = only DB code; no generic BaseRepository. Cross-module: models + schemas importable, services callable, **repositories private**. All ticket permission/visibility logic lives in ONE declarative table `tickets/policy.py` — never add role/status if-branches elsewhere; extend the table.

## 4. Repo layout (what exists)

```
C:\Github\SupportSync\
├── AGENTS.md / CLAUDE.md        # dev rules & commands (identical copies)
├── CONTEXT.md                   # domain glossary (authoritative vocabulary)
├── README.md                    # quickstart, layout
├── HANDOFF.md                   # this file
├── docker-compose.yml           # postgres:17-alpine + redis:7-alpine (M3 Phase B)
├── .env.example, .gitignore, .dockerignore
├── docs/
│   ├── milestones.md            # M1–M4 roadmap
│   ├── database-design.md       # DB doc of record (Mermaid ERD, table specs, ADR refs)
│   └── adr/0001–0004            # immutable tickets+terminal closed; modular monolith
│                                # rotating refresh tokens; deactivate-only
├── .agents/skills/ + .claude/skills/   # installed agent skills (see §2)
└── backend/
    ├── .env.example  requirements.txt  requirements-dev.txt  pytest.ini  alembic.ini
    ├── .venv/                   # created; deps installed (Windows venv)
    ├── migrations/env.py        # wired to SQLModel metadata + DATABASE_URL
    ├── migrations/versions/0001_initial_schema.py   # users, refresh_tokens, tickets (hand-written)
    ├── migrations/versions/87e92c87d5e5_messages_table.py   # 0002, autogenerated (+ declares tickets customer/agent index)
    ├── migrations/versions/f679192f699c_ticket_read_states.py   # 0003, per-participant chat read markers
    ├── app/
    │   ├── main.py              # app factory, CORS, error handlers, /api/v1 prefix, /health
    │   ├── core/config.py       # pydantic-settings (JWT_SECRET required), database.py (get_session: commit-on-success), security.py (bcrypt, JWT, refresh gen/hash), errors.py (AppError hierarchy → {"error":{code,message}})
    │   ├── utils/time.py        # utcnow + as_utc (sqlite-naive vs pg-aware normalization)
    │   ├── utils/pagination.py  # Page[T], limit_offset (limit≤100)
    │   ├── modules/auth/        # models(RefreshToken), schemas, repository, service(register/login/refresh-rotate/logout), dependencies(get_current_user, require_role), router
    │   ├── modules/users/       # models(User+Role), schemas, repository, service, router (/users, /users/me, role+status PATCH)
    │   ├── modules/tickets/     # models(Ticket+enums), schemas, policy (THE rules table: ensure/scoped/get_visible), repository (incl. atomic transition()), service (act/change_priority), router
    │   ├── modules/notifications/   # schemas (typed SSE events), policy (recipients table),
    │   │                            # hub (in-process fan-out), bus (Redis bridge + self-healing listener),
    │   │                            # service (commit-gated emitter), router (SSE stream)
    │   ├── modules/chat/         # models(Message, TicketReadState), schemas, policy (own rules table), repository,
    │   │                         # service, connections (in-process per-ticket room registry),
    │   │                         # router (REST history+post, WS /tickets/{id}/ws)
    │   └── seeds/demo.py        # idempotent demo data (python -m app.seeds.demo)
    └── tests/
        ├── conftest.py          # sqlite default (TEST_DATABASE_URL override), transaction-per-test rollback, client+token fixtures
        ├── test_policy.py       # 38-case hand-written grid vs RULES + invariants (closed terminal, owner_roles subset)
        ├── test_auth.py         # register/login/me, dup email 409, rotation+reuse-rejection, logout, deactivation, 401s
        ├── test_users.py        # RBAC 403s, staff create (customer-role 422), list/filter, self-guards, last-admin invariant
        ├── test_tickets.py      # create/visibility 404s, queue+claim, claim race (repo-level), assign, lifecycle, close semantics, priority, pagination/filters, mine
        ├── test_notifications.py # stream auth (header/query-token), SSE frame shape (bounded async unit),
        │                         # commit-gating + rollback discard, recipients per notification type,
        │                         # actor subtraction, multi-stream fan-out, deactivated agents, admins never
        ├── test_chat.py         # REST history/post authorization, closed read-only, WS auth, participants,
        │                         # admin read-only, closed read-only (connection stays open), buffering, malformed frames
        └── test_phase_b.py      # Redis bridge contract (fakeredis): envelopes, origin dedupe, fail-open,
                                  # circuit breaker trip/probe, rate-limit 429 integration
```

## 5. Current state & test status

**118/118 tests pass** on sqlite AND on real Postgres (`TEST_DATABASE_URL=postgresql+psycopg://supportsync:supportsync@localhost:5433/supportsync_test` — dedicated test DB, created via `CREATE DATABASE supportsync_test;`). All migrations applied to the live dev Postgres; `alembic check` reports zero drift. Committed: M1 `549b48b`, M2 `9ec8612` + docs `0698d3a`, M3 Phase A `b714bde` + docs `25a23c7`, M3 Phase B `fd606da` + docs `59b390f`.

**M3 Phase A testing notes:** the SSE stream endpoint cannot be tested over the TestClient HTTP transport — starlette 1.6 runs an app call to completion, so an infinite stream blocks forever. Tests invoke the endpoint coroutine directly (auth + response shape) and exercise `_stream()` as a bounded async unit (connected frame, event frame, keep-alive, unsubscribe). Emission gating is tested via the session-event seam: `session.commit()` in tests plays the role of `get_session`'s commit-on-success in production.

**M2 quality pass ran** (`code-review` two-axis + `thermo-nuclear-code-quality-review`) and all findings were fixed: dead code deleted (unused frame-model placeholders, an unused `asyncio.Lock`, an uncalled repository count helper), the wire protocol is now typed pydantic models in `chat/schemas.py` (used at every send/broadcast site — no more hand-built frame dicts), and the middle-man `service.get_ticket_for_chat` wrapper was removed (router calls `policy.get_chat` directly). Commit-per-frame in the WS handler was reviewed and accepted as a justified deviation from "commit once per request" (a WS connection is not a request).

**Two environment/library findings from M2 (both load-bearing):**

1. **pysqlite cannot do real SAVEPOINTs out of the box** (SQLAlchemy-documented limitation). The `conftest.py` "rollback-per-test" harness silently had no isolation against mid-test commits: `session.commit()` inside the WS chat handler persisted rows for the rest of the run and poisoned later tests (`email is already registered` at fixture setup). Fix (already in conftest): the official serializable/savepoint recipe on the test engine — `isolation_level=None` on connect + an explicit `BEGIN` on the engine `begin` event. With it, a nested session commit stays inside the outer transaction and is discarded by the rollback (verified empirically). Postgres is unaffected — this is sqlite-only, but the recipe is harmless there and the TEST_DATABASE_URL engine shares the harness.
2. **starlette 1.6 TestClient drops the WebSocket upgrade for absolute URLs** (`http://testserver/...` → HTTP response → `RuntimeError: Expected WebSocket upgrade`); relative URLs (`/api/v1/...`) work. Test helper `ws_url()` builds relative URLs. Not an app bug — production ASGI servers are unaffected.

Also fixed in passing: migration 0001 had hand-written indexes (`tickets.customer_id`, `tickets.agent_id`) the models never declared — now declared on the model so autogenerate is clean, and 0002 no longer drops them.

**Live Postgres smoke test passed end-to-end** (2026-09-17): `docker compose up -d` → `alembic upgrade head` → `python -m app.seeds.demo` → uvicorn boots → `/health` 200, `/docs` 200, login as seeded agent 200, agent ticket list shows Queue + assigned tickets.

Environment-specific notes for THIS machine (HP EliteBook, Windows):
- **Docker works now.** Earlier "Virtualization support not detected" was resolved by installing WSL 2.7.14 + Virtual Machine Platform (elevated) and rebooting. Hypervisor present, daemon live.
- **Port 5433, not 5432**: a native Windows PostgreSQL 18 service (`postgresql-x64-18`, auto-start) occupies 5432 on this machine — do NOT stop it; other projects may use it. Root `.env` (gitignored) sets `POSTGRES_PORT=5433`; `backend/.env` DATABASE_URL points at `localhost:5433`. The backend `.env.example` template stays at 5432 (generic default).
- `backend/.env` exists with a real JWT_SECRET and port 5433.

**Integration bug found & fixed by the live smoke test (commit 584baec):** `EmailStr` (email-validator) rejects reserved/special-use domains like `.local` at the API boundary — seeded accounts using `@supportsflow.local` could register in seeds but never log in. All seed/demo/admin emails now use `@example.com` (IANA documentation domain, accepted by the validator). Seeds data also had an agent-index bug (index 2 with only 2 agents) — fixed. Lesson: seeds bypass API validation; anything seeded must be valid *through* the API too.

Two code changes made in the quality-review session:

1. **`users/service.set_active()`** now revokes all refresh tokens internally when deactivating a user. Previously this was in the router (wrong layer — business invariant). Router is now a one-liner.
2. **Deleted redundant pre-check** in `tickets/service.act()` — the in-memory `requires_unassigned` check was a weaker, racy duplicate of the DB-level atomic `transition()` guard.

**CORS dotenv fix (commit 0bfe32c):** `CORS_ORIGINS` in `.env` as a comma-separated string crashed Settings at import — pydantic-settings JSON-parses complex fields (`list[str]`) from dotenv *before* validators run. `cors_origins` is now a plain `str` with a `cors_origin_list` property; `main.py` uses the property. Note for M2+: any new env-driven list/complex setting must follow the same pattern (raw string + parsed property). The earlier "68/68 twice" claim ran pytest from a cwd where `.env` was absent, which masked this — always run pytest from `backend/`.

Already fixed in prior dev (don't regress): naive-vs-aware datetimes on sqlite (always compare via `as_utc` from `app/utils/time.py`), test JWT secret must be ≥32 bytes, `email-validator` in requirements.txt.

## 6. How to continue (exact steps)

```powershell
# Run tests (PowerShell — use direct python.exe, not venv activate):
powershell -ExecutionPolicy Bypass -Command "& 'C:/Github/SupportSync/backend/.venv/Scripts/python.exe' -m pytest"

# Postgres verification (requires Docker running):
docker compose up -d                     # from C:/Github/SupportSync
# create backend/.env from .env.example; set JWT_SECRET via:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
cd backend
alembic upgrade head                     # applies 0001 to Postgres
python -m app.seeds.demo                 # demo data
uvicorn app.main:app --reload            # docs at http://127.0.0.1:8000/docs
$env:TEST_DATABASE_URL="postgresql+psycopg://supportsync:supportsync@localhost:5433/supportsync_test"
& '.venv/Scripts/python.exe' -m pytest

# Git (everything through M3 is committed — SHA map in §5):
git status && git add <files> && git commit -m "feat: <what> (<N> tests green)"
```

Quality review already done this session. Next quality pass: run `code-review` + `thermo-nuclear-code-quality-review` skills after any significant new diff.

**Next entry points:** (a) the live two-terminal smoke test (uvicorn: one terminal streaming `/notifications/stream`, another creating a ticket — also the first live check of the Redis bridge with `docker compose up -d`). (b) **M4 — Frontend** per `docs/milestones.md` (the harness is current: AGENTS.md/CLAUDE.md through M3, `docs/database-design.md` is the DB doc of record).

## 7. Quality review summary (this session)

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | Token revocation in router — business invariant in wrong layer | Medium | ✅ Fixed |
| 2 | Redundant in-memory unassigned pre-check (racy, weaker than DB guard) | Low | ✅ Fixed |
| 3 | `conftest.py` model side-effect imports fragile (note for M2) | Low | Deferred |
| 4 | Hand-written migration will drift — use `alembic revision --autogenerate` going forward | Info | Documented |

Spec coverage: **100%** — all M1 requirements from ADRs and milestone image implemented and tested.

## 8. Vocabulary (use these exact terms — CONTEXT.md)

User (any account) · Customer · Support Agent ("Agent" in code/enum) · Admin · Ticket · Priority (low/medium/high) · Queue (open, unassigned tickets) · Ticket Lifecycle (open/in_progress/resolved/closed).
