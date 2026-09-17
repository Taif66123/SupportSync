---
name: database-schema-designer
description: Design new database tables or document the existing schema as docs/database-design.md (Mermaid ERD, per-table specs, ADR cross-references). Use whenever models or migrations change, a feature needs new tables, or the database documentation is stale. Fuses schema-design workflow (OneWave), Mermaid ERD + normalization discipline (LobeHub), and the Alembic migration-safety checklist (migrate-db).
---

# Database Schema Designer (SupportSync)

Two modes. Pick explicitly before doing anything else.

- **`document-existing`** — the schema already lives in `backend/app/modules/*/models.py` + Alembic migrations. The deliverable is `docs/database-design.md`: derive, verify, document. **Never** emit `CREATE TABLE` statements for existing tables — the models are the source of truth (AGENTS.md), and this skill describes; it does not prescribe.
- **`design-new`** — a feature needs new tables (or changes to existing ones). Design at the models level, keep `docs/database-design.md` in the same change, and run the Alembic safety checklist before generating the migration.

## Mode: document-existing

1. **Read the live surface**: every `app/modules/*/models.py` (column types, constraints, indexes, `__table_args__`), every `backend/migrations/versions/*.py` (what the database actually has), and `docs/adr/` (the decisions behind shapes).
2. **Verify first**: run `alembic check` (must report no new upgrade operations — zero drift) and `pytest` (schema-touching tests green). If either fails, stop: documenting a drifted schema is worse than not documenting.
3. **Produce `docs/database-design.md`** with the labeled sections in order: Mermaid ERD → per-table specs → design decisions → documented imperfections → change protocol.
4. **Self-verify against the quality checklist** below, then cross-check every column/constraint/index in the doc against the models one final time — the doc's accuracy IS the deliverable.

### ERD rules (Mermaid `erDiagram`)

- Entity blocks list only columns that carry design meaning: PK, FKs, unique, enums, and `CK`-prefixed check constraints. Omit boilerplate (`created_at`/`updated_at` appear only in the per-table spec).
- One relationship line per FK with the label naming it (`customer places`, `owns`, `marks`). No shortcuts through "logic" — only real FKs.
- Cardinality: `||--o{` for required-one to many, `|o--o{` when the FK is nullable.

### Per-table spec rules

- A table for each of: columns (name, type, constraints), indexes (name, columns, kind, and **why** — the concrete query or hot path that justifies it; an index without a "why" is a finding, not a given), and notes for anything non-obvious (hash-only storage, monotonic markers, observer exclusions).
- Cross-reference the ADR or milestone behind every non-obvious decision (`(ADR 0003)`, `(M2 receipts)`).

### Quality checklist (both modes)

- [ ] Every table, column, index, and constraint in the doc matches a model/migration — nothing invented, nothing missing
- [ ] `alembic check` clean at time of writing; doc records the verification
- [ ] Every index has a stated justification; every FK appears in the ERD
- [ ] Every non-obvious decision points to an ADR/milestone; imperfections are listed as future work, not hidden
- [ ] Doc states it is descriptive-only; models + Alembic remain the source of truth

## Mode: design-new

1. **Gather before designing** (never invent): engine + volume + the *concrete queries* the table must serve (an index list falls out of this, not out of habit); which existing tables relate; which ADRs constrain the shape (no hard deletes — ADR 0004; users deactivated, never deleted).
2. **Normalize to 3NF** (BCNF where it's free). Denormalize only with a written reason (read-path at real volume, monotonic markers, etc.) — the reason goes in the doc's decisions section.
3. **Design at the models level**: edit `models.py` — explicit `sa_column` for anything with a constraint or index (mirroring the existing style), `native_enum=False` varchar enums to match the codebase, tz-aware UTC datetimes via `app/utils/time.utcnow`.
4. **Update `docs/database-design.md` in the same change** — a schema change without its doc update is an incomplete change.
5. **Generate the migration with autogenerate, then run the Alembic safety checklist** (below) on the result *before* upgrading anything.
6. **Verify**: `alembic check` (zero drift), full `pytest` on sqlite + `TEST_DATABASE_URL` Postgres.

## Alembic migration-safety checklist (from migrate-db — run on every generated migration)

Before `alembic upgrade head` on any shared/live database, check the generated script for:

- [ ] **Destructive ops**: `drop_table`, `drop_column`, column type changes that can lose data — must be justified in the migration docstring or reconsidered
- [ ] **Nullable on new columns**: new columns on existing tables are nullable or carry a server default (a non-nullable bare add breaks existing rows)
- [ ] **Default values**: adding a default on a large table is planned, not accidental
- [ ] **Lock-heavy operations**: index creation on a table expected to be large uses `op.create_index` consciously (Postgres `CONCURRENTLY` is a manual follow-up if ever needed — note it, don't improvise it)
- [ ] **Missing FK indexes**: every FK column has an index (the ORM does not add one automatically)
- [ ] **Downgrade works**: the `downgrade()` is real (indexes dropped before tables), even if never expected to run
