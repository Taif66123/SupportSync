# SupportSync — Milestones

Source: the SupportSync feature list (4 milestones). Status tracked here; decisions live in `docs/adr/`, vocabulary in `CONTEXT.md`.

## Milestone 1 — Login & Support Tickets ✅ (current scope)

**Business**: customer can register and log in; agent can log in; customer creates tickets and sees their own; agent sees the Queue and assigned tickets; agent updates status `open → in_progress → resolved`; customer sees current status.

**Technical**: REST API, JWT auth (15-min access token) with rotating stored refresh tokens (ADR 0003), role-based authorization (Customer / Support Agent / Admin), PostgreSQL, SQLModel, Alembic migrations, pytest.

**Refined during grilling**:
- Three roles; open self-registration for Customers only; Admin creates Agents/Admins.
- Explicit action endpoints (`claim`, `assign`, `resolve`, `reopen`, `close`) — no generic status PATCH. Rules in one declarative table (`tickets/policy.py`).
- Tickets immutable after creation; Priority set by customer, mutable by Agent/Admin; `closed` terminal; Agent/Admin may also close (ADR 0001).
- Admin user management: create, list, role change (last-Admin guard), deactivate/reactivate — never delete (ADR 0004).
- Redis rate limiting deliberately deferred (moved to M3/M4 where Redis is actually introduced).

## Milestone 2 — Real-Time Chat

**Business**: customer and assigned agent chat inside a ticket; messages appear instantly; typing indicator; read receipts; history preserved on reopen.

**Technical**: FastAPI WebSockets, WebSocket authentication, PostgreSQL message storage (new `Message` table shaped by chat needs), typed clients.

**Boundaries already decided**: chat is strictly per-Ticket; participants = ticket Customer + assigned Support Agent; Admins read-only observers; messages sent before assignment are buffered, not delivered, until an Agent claims. Authorization follows the same policy-module pattern as tickets (`chat/policy.py`), it does not extend the tickets policy.

## Milestone 3 — Live Notifications

**Business**: agent notified on new ticket; customer notified on status update and on new message; no refresh needed.

**Technical**: SSE (Server-Sent Events) over long-lived HTTP, server → client push, FastAPI SSE client. **Redis enters the stack here** (pub/sub for fan-out across workers) plus the deferred rate limiting.

## Milestone 4 — Background Processing & Finalization

**Business**: confirmation email after ticket creation (async, user doesn't wait); proper error messages; API docs; main flows tested; packaged with Docker.

**Technical**: async/await, FastAPI BackgroundTasks (or a task queue if retries matter), exception handling, pytest coverage of main flows, OpenAPI/Swagger, Docker + docker-compose packaging of backend (and frontend later), CI pipeline (Jenkinsfile).

## Deferred / explicit non-goals

- Cursor-style cursor pagination, departments partitioning the Queue, auto-assignment — revisit only if the domain demands them.
- Hard deletes — never (ADR 0004).
