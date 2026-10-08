from datetime import datetime, timezone

import pytest

from app.routers.public import equity_session_start


@pytest.mark.parametrize(
    ("now", "expected_start"),
    [
        (
            datetime(2026, 10, 8, 23, 59, tzinfo=timezone.utc),
            datetime(2026, 10, 8, 0, 0, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 10, 9, 0, 1, tzinfo=timezone.utc),
            datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc),
        ),
    ],
)
def test_equity_session_starts_at_seven_wib(now, expected_start):
    assert equity_session_start(now) == expected_start
