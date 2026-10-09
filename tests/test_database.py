import sqlite3
from datetime import date

from services import database as database_module
from services.database import PingDatabase, StartupNotificationDatabase


def test_empty_database(tmp_path):
    db = PingDatabase(tmp_path / "ping_count.db")

    assert db.get_count(123) == 0
    assert db.get_total_count() == 0
    assert db.get_last_ping(123) is None
    assert db.get_leaderboard() == []

    db.close()


def test_add_ping_updates_count_and_last_ping(tmp_path, monkeypatch):
    db = PingDatabase(tmp_path / "ping_count.db")
    monkeypatch.setattr(database_module.time, "time", lambda: 1_700_000_000)

    assert db.add_ping(123) == 1
    assert db.get_count(123) == 1
    assert db.get_total_count() == 1
    assert db.get_last_ping(123) == 1_700_000_000

    monkeypatch.setattr(database_module.time, "time", lambda: 1_700_000_123)
    assert db.add_ping(123) == 2
    assert db.get_count(123) == 2
    assert db.get_total_count() == 2
    assert db.get_last_ping(123) == 1_700_000_123

    db.close()


def test_total_count_includes_users_outside_leaderboard_limit(tmp_path):
    db = PingDatabase(tmp_path / "ping_count.db")

    for _ in range(3):
        db.add_ping(1)
    for _ in range(2):
        db.add_ping(2)
    db.add_ping(3)

    assert db.get_leaderboard(limit=2) == [(1, 3), (2, 2)]
    assert db.get_total_count() == 6

    db.close()


def test_reopen_persists_count_and_last_ping(tmp_path, monkeypatch):
    db_path = tmp_path / "ping_count.db"
    monkeypatch.setattr(database_module.time, "time", lambda: 1_700_000_000)
    db = PingDatabase(db_path)
    db.add_ping(123)
    db.close()

    reopened = PingDatabase(db_path)
    assert reopened.get_count(123) == 1
    assert reopened.get_total_count() == 1
    assert reopened.get_last_ping(123) == 1_700_000_000
    reopened.close()


def test_old_schema_is_migrated_idempotently(tmp_path, monkeypatch):
    db_path = tmp_path / "ping_count.db"
    old_conn = sqlite3.connect(db_path)
    old_conn.execute(
        "CREATE TABLE ping_counts (user_id INTEGER PRIMARY KEY, count INTEGER DEFAULT 0)"
    )
    old_conn.executemany(
        "INSERT INTO ping_counts (user_id, count) VALUES (?, ?)",
        [(123, 4), (456, 2)],
    )
    old_conn.commit()
    old_conn.close()

    monkeypatch.setattr(database_module.time, "time", lambda: 1_700_000_000)
    db = PingDatabase(db_path)
    assert db.get_count(123) == 4
    assert db.get_count(456) == 2
    assert db.get_total_count() == 6
    assert db.get_last_ping(123) is None
    assert db.get_last_ping(456) is None
    dashboard = db.query_dashboard(
        date(2023, 11, 15),
        date(2023, 11, 15),
    )
    assert dashboard["legacy_total"] == 6
    assert dashboard["lifetime_total"] == 6
    assert dashboard["history_started_at"] == 1_700_000_000
    assert dashboard["events"] == []
    db.close()

    # Reopening must not attempt to add the column a second time.
    reopened = PingDatabase(db_path)
    assert reopened.get_count(123) == 4
    assert reopened.get_count(456) == 2
    assert reopened.get_last_ping(123) is None
    assert reopened.get_last_ping(456) is None

    monkeypatch.setattr(database_module.time, "time", lambda: 1_700_000_321)
    assert reopened.add_ping(123) == 5
    assert reopened.get_last_ping(123) == 1_700_000_321
    assert reopened.get_last_ping(456) is None
    migrated_dashboard = reopened.query_dashboard(
        date(2023, 11, 15),
        date(2023, 11, 15),
    )
    assert migrated_dashboard["legacy_total"] == 6
    assert migrated_dashboard["period_total"] == 1
    reopened.close()


def test_daily_dashboard_uses_taipei_midnight_boundaries_and_counts_manual(tmp_path, monkeypatch):
    monkeypatch.setattr(database_module.time, "time", lambda: 1_704_124_800)

    db = PingDatabase(tmp_path / "ping_count.db")
    # 2024-01-01 23:59:59 Taipei, then midnight and one manual event.
    db.add_ping(1, guild_id=10, channel_id=20, message_id=100, event_at=1_704_124_799)
    db.add_ping(
        1,
        guild_id=10,
        channel_id=20,
        message_id=101,
        source="manual",
        event_at=1_704_124_800,
    )
    db.add_ping(
        2,
        guild_id=11,
        channel_id=21,
        message_id=102,
        event_at=1_704_124_800,
    )

    result = db.query_dashboard(
        date(2024, 1, 1),
        date(2024, 1, 2),
        guild_id=10,
    )

    assert result["timezone"] == "Asia/Taipei"
    assert result["period_total"] == 2
    assert result["unique_users"] == 1
    assert result["daily"] == [
        {"date": "2024-01-01", "count": 1, "scheduled": 1, "manual": 0},
        {"date": "2024-01-02", "count": 1, "scheduled": 0, "manual": 1},
    ]
    assert result["leaders"] == [
        {"user_id": "1", "count": 2, "last_ping_at": 1_704_124_800},
    ]
    assert result["events"][0]["user_id"] == "1"
    assert result["events"][0]["message_id"] == "101"
    assert result["legacy_total"] == 0
    # The previous local day has no events, but the response exposes the boundary.
    assert result["history_start_date"] == "2024-01-02"
    db.close()


def test_dashboard_can_filter_manual_source_and_fills_empty_days(tmp_path):
    db = PingDatabase(tmp_path / "ping_count.db")
    db.add_ping(1, guild_id=10, message_id=1, event_at=1_704_124_800)
    db.add_ping(
        2,
        guild_id=10,
        message_id=2,
        source="manual",
        event_at=1_704_124_801,
    )
    result = db.query_dashboard(
        date(2024, 1, 1),
        date(2024, 1, 3),
        guild_id=10,
        source="manual",
    )
    assert result["period_total"] == 1
    assert result["daily"] == [
        {"date": "2024-01-01", "count": 0, "scheduled": 0, "manual": 0},
        {"date": "2024-01-02", "count": 1, "scheduled": 0, "manual": 1},
        {"date": "2024-01-03", "count": 0, "scheduled": 0, "manual": 0},
    ]
    assert result["leaders"][0]["user_id"] == "2"
    assert result["lifetime_total"] == 2
    assert (
        db.query_dashboard(
            date(2024, 1, 1),
            date(2024, 1, 3),
            guild_id=11,
        )["period_total"]
        == 0
    )
    db.close()


def test_duplicate_message_id_does_not_duplicate_event_or_count(tmp_path):
    db = PingDatabase(tmp_path / "ping_count.db")
    assert db.add_ping(123, guild_id=456, message_id=789, event_at=1_700_000_000) == 1
    assert (
        db.add_ping(
            123,
            guild_id=456,
            message_id=789,
            source="manual",
            event_at=1_700_000_100,
        )
        == 1
    )
    result = db.query_dashboard(date(2023, 11, 14), date(2023, 11, 15))
    assert db.get_count(123) == 1
    assert result["period_total"] == 1
    assert len(result["events"]) == 1
    assert result["events"][0]["source"] == "scheduled"
    db.close()


def test_event_and_aggregate_roll_back_together_on_failure(tmp_path):
    import pytest

    db = PingDatabase(tmp_path / "ping_count.db")
    db.conn.execute("""
        CREATE TRIGGER fail_ping_count BEFORE INSERT ON ping_counts
        BEGIN SELECT RAISE(ABORT, 'simulated aggregate failure'); END
    """)
    db.conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="simulated aggregate failure"):
        db.add_ping(123, guild_id=456, message_id=789, event_at=1_700_000_000)
    assert db.conn.execute("SELECT COUNT(*) FROM ping_events").fetchone()[0] == 0
    assert db.get_total_count() == 0
    db.close()


def test_export_events_sorts_and_reports_truncation(tmp_path, monkeypatch):
    db = PingDatabase(tmp_path / "ping_count.db")
    db.add_ping(1, message_id=1, event_at=1_700_000_002)
    db.add_ping(2, message_id=2, event_at=1_700_000_001)
    monkeypatch.setattr(database_module, "EXPORT_EVENTS_LIMIT", 1)
    result = db.export_events(date(2023, 11, 15), date(2023, 11, 15))
    assert result["truncated"] is True
    assert [event["message_id"] for event in result["events"]] == ["2"]
    db.close()


def test_startup_notification_channels_are_guild_scoped_and_persist(tmp_path):
    db_path = tmp_path / "startup_notifications.db"
    db = StartupNotificationDatabase(db_path)
    guild_id = 2**63 + 10
    channel_id = 2**63 + 100

    assert db.get_channels() == {}
    db.set_channel(guild_id, channel_id)
    db.set_channel(20, 200)
    db.set_channel(guild_id, channel_id + 1)
    assert db.get_channels() == {guild_id: channel_id + 1, 20: 200}
    db.close()

    reopened = StartupNotificationDatabase(db_path)
    assert reopened.get_channels() == {guild_id: channel_id + 1, 20: 200}
    reopened.close()


def test_startup_notification_channel_can_be_disabled_idempotently(tmp_path):
    db_path = tmp_path / "startup_notifications.db"
    db = StartupNotificationDatabase(db_path)
    db.set_channel(10, 100)
    db.set_channel(10, None)
    db.set_channel(10, None)
    assert db.get_channels() == {}
    db.close()

    reopened = StartupNotificationDatabase(db_path)
    assert reopened.get_channels() == {}
    reopened.close()
