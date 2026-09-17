"""Milestone 3 — live notifications over SSE.

One long-lived `GET /notifications/stream` per client session. Events are
**ephemeral push** (user decision): nothing is persisted, nothing is replayed —
clients that were offline simply see current state on their next fetch.

Recipients (milestone boundary): all active Agents on `ticket.created`; the
conversation participants minus the actor on `ticket.updated` and
`message.created`. Admins observe but are never notified.

Emissions are queued on the request session and only published to the hub after
that session's commit succeeds — a subscriber's client never hears about data it
cannot yet fetch. A rollback discards the queue. Phase B (Redis pub/sub) replaces
the cross-process gap the in-process hub leaves; the emitter contract stays.
"""
