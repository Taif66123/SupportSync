"""Milestone 2 — per-ticket WebSocket chat.

Decided boundaries: participants = ticket Customer + assigned Support Agent; Admins
read-only; messages before assignment are buffered, not delivered. Authorization lives
in chat/policy.py — same declarative pattern as tickets/policy.py, deliberately a
separate table (never extend or import the tickets policy from here).
"""
