from datetime import UTC, datetime


def utcnow() -> datetime:
    """Current UTC time as a naive datetime.

    `datetime.utcnow()` is deprecated in Python 3.12, but every DateTime column
    in this schema is naive, and JWT `exp` claims are compared against naive
    UTC. Stripping tzinfo after converting to UTC returns exactly what
    `utcnow()` returned, so stored timestamps and issued tokens are unchanged.

    Making the columns timezone-aware would be a schema migration, not a
    deprecation fix — worth doing separately, if at all.
    """
    return datetime.now(UTC).replace(tzinfo=None)
