import sqlite3

from services import database as database_module
from services.database import PingDatabase


def test_empty_database(tmp_path):
    db = PingDatabase(tmp_path / 'ping_count.db')

    assert db.get_count(123) == 0
    assert db.get_total_count() == 0
    assert db.get_last_ping(123) is None
    assert db.get_leaderboard() == []

    db.close()


def test_add_ping_updates_count_and_last_ping(tmp_path, monkeypatch):
    db = PingDatabase(tmp_path / 'ping_count.db')
    monkeypatch.setattr(database_module.time, 'time', lambda: 1_700_000_000)

    assert db.add_ping(123) == 1
    assert db.get_count(123) == 1
    assert db.get_total_count() == 1
    assert db.get_last_ping(123) == 1_700_000_000

    monkeypatch.setattr(database_module.time, 'time', lambda: 1_700_000_123)
    assert db.add_ping(123) == 2
    assert db.get_count(123) == 2
    assert db.get_total_count() == 2
    assert db.get_last_ping(123) == 1_700_000_123

    db.close()


def test_total_count_includes_users_outside_leaderboard_limit(tmp_path):
    db = PingDatabase(tmp_path / 'ping_count.db')

    for _ in range(3):
        db.add_ping(1)
    for _ in range(2):
        db.add_ping(2)
    db.add_ping(3)

    assert db.get_leaderboard(limit=2) == [(1, 3), (2, 2)]
    assert db.get_total_count() == 6

    db.close()


def test_reopen_persists_count_and_last_ping(tmp_path, monkeypatch):
    db_path = tmp_path / 'ping_count.db'
    monkeypatch.setattr(database_module.time, 'time', lambda: 1_700_000_000)
    db = PingDatabase(db_path)
    db.add_ping(123)
    db.close()

    reopened = PingDatabase(db_path)
    assert reopened.get_count(123) == 1
    assert reopened.get_total_count() == 1
    assert reopened.get_last_ping(123) == 1_700_000_000
    reopened.close()


def test_old_schema_is_migrated_idempotently(tmp_path, monkeypatch):
    db_path = tmp_path / 'ping_count.db'
    old_conn = sqlite3.connect(db_path)
    old_conn.execute(
        'CREATE TABLE ping_counts (user_id INTEGER PRIMARY KEY, count INTEGER DEFAULT 0)'
    )
    old_conn.executemany(
        'INSERT INTO ping_counts (user_id, count) VALUES (?, ?)',
        [(123, 4), (456, 2)],
    )
    old_conn.commit()
    old_conn.close()

    db = PingDatabase(db_path)
    assert db.get_count(123) == 4
    assert db.get_count(456) == 2
    assert db.get_total_count() == 6
    assert db.get_last_ping(123) is None
    assert db.get_last_ping(456) is None
    db.close()

    # Reopening must not attempt to add the column a second time.
    reopened = PingDatabase(db_path)
    assert reopened.get_count(123) == 4
    assert reopened.get_count(456) == 2
    assert reopened.get_last_ping(123) is None
    assert reopened.get_last_ping(456) is None

    monkeypatch.setattr(database_module.time, 'time', lambda: 1_700_000_321)
    assert reopened.add_ping(123) == 5
    assert reopened.get_last_ping(123) == 1_700_000_321
    assert reopened.get_last_ping(456) is None
    reopened.close()
