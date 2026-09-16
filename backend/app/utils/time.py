from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Normalize a stored datetime to aware UTC.

    Postgres returns tz-aware datetimes; SQLite (tests) returns naive ones.
    Comparisons must always happen between normalized values.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
