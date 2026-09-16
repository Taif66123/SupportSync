# SupportSync

A small customer support application: a customer creates a support ticket and communicates with a support agent in real time.

**Status**: backend, Milestone 1 (auth + tickets). Roadmap in [`docs/milestones.md`](docs/milestones.md), domain vocabulary in [`CONTEXT.md`](CONTEXT.md), decisions in [`docs/adr/`](docs/adr/).

## Stack

FastAPI · PostgreSQL · SQLModel (SQLAlchemy 2) · Alembic · JWT (PyJWT) + bcrypt · pytest · Docker (compose for infra)

## Quickstart

```bash
# 1. Infrastructure (Postgres)
docker compose up -d

# 2. Backend
cd backend
python -m venv .venv
. .venv/Scripts/activate          # Windows Git Bash (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env              # then set JWT_SECRET etc.

# 3. Database + demo data
alembic upgrade head
python -m app.seeds.demo

# 4. Run
uvicorn app.main:app --reload     # API docs at http://127.0.0.1:8000/docs
```

## Tests

```bash
pytest                            # runs on sqlite by default, no infra needed
TEST_DATABASE_URL="postgresql+psycopg://supportsync:supportsync@localhost:5432/supportsync_test" pytest
                                  # run against real Postgres (recommended before merging)
```

## Layout

```
backend/app/
├── main.py            # app factory, router registration, error handlers
├── core/              # config, database, security (JWT/hash), errors
├── modules/           # business modules — the architecture unit
│   ├── auth/          # register, login, refresh rotation, logout
│   ├── users/         # user management (admin), roles, deactivation
│   ├── tickets/       # CRUD + lifecycle actions; policy.py = the rules table
│   ├── chat/          # M2 placeholder
│   └── notifications/ # M3 placeholder
├── utils/             # pagination, shared helpers
└── seeds/             # demo data
migrations/            # Alembic (source of truth for schema)
tests/                 # pytest suite
```

Each module layers Router → Service → Repository. Rules and boundaries: [`AGENTS.md`](AGENTS.md).
