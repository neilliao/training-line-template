import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from env_snapshot import should_refresh

NOW = datetime(2026, 7, 10, 5, 0, 0, tzinfo=timezone.utc)


def test_refresh_when_missing():
    assert should_refresh(None, NOW) is True
    assert should_refresh({}, NOW) is True
    assert should_refresh({"today": {}}, NOW) is True


def test_refresh_when_timestamp_invalid():
    assert should_refresh({"updated_at": "not-a-time"}, NOW) is True
    assert should_refresh({"updated_at": 12345}, NOW) is True


def test_no_refresh_within_window():
    fresh = (NOW - timedelta(minutes=30)).isoformat()
    assert should_refresh({"updated_at": fresh}, NOW) is False


def test_refresh_after_window():
    stale = (NOW - timedelta(minutes=61)).isoformat()
    assert should_refresh({"updated_at": stale}, NOW) is True


def test_naive_timestamp_treated_as_utc():
    fresh_naive = (NOW - timedelta(minutes=10)).replace(tzinfo=None).isoformat()
    assert should_refresh({"updated_at": fresh_naive}, NOW) is False
