from datetime import date, datetime, time, timedelta, timezone


UTC = timezone.utc
WIB = timezone(timedelta(hours=7), name="Asia/Jakarta")


def as_utc(value: datetime) -> datetime:
    """Treat naive datetimes from SQLite as UTC and return an aware UTC value."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def as_wib(value: datetime) -> datetime:
    return as_utc(value).astimezone(WIB)


def wib_iso(value: datetime | None) -> str | None:
    return as_wib(value).isoformat() if value is not None else None


def wib_day_start_utc_naive(day: date) -> datetime:
    """Return WIB midnight as naive UTC for comparisons with SQLite datetimes."""
    return datetime.combine(day, time.min, tzinfo=WIB).astimezone(UTC).replace(tzinfo=None)


def wib_datetime_to_utc_naive(value: datetime) -> datetime:
    """Interpret naive filter values as WIB and convert them to SQLite UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=WIB)
    return value.astimezone(UTC).replace(tzinfo=None)
