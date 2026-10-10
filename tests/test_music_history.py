import sqlite3
from dataclasses import dataclass

import pytest

from services.music_history import MusicHistoryDatabase


@dataclass
class Track:
    title: str
    url: str
    duration: float | None
    thumbnail: str | None
    requester_id: int


def track(number, requester_id=10):
    return Track(
        f"Song {number}", f"https://example.com/{number}", 120.5, None, requester_id,
    )


def test_history_persists_and_returns_complete_entries(tmp_path, monkeypatch):
    import services.music_history as music_history

    monkeypatch.setattr(music_history.time, "time", lambda: 1_800_000_000.9)
    db_path = tmp_path / "music-history.db"
    history = MusicHistoryDatabase(db_path)
    entry_id = history.record(123456789012345678, track(1, 987654321098765432))
    history.close()

    history = MusicHistoryDatabase(db_path)
    result = history.query("123456789012345678")
    assert result == {
        "items": [{
            "id": entry_id,
            "guild_id": "123456789012345678",
            "requester_id": "987654321098765432",
            "title": "Song 1",
            "url": "https://example.com/1",
            "duration": 120.5,
            "thumbnail": None,
            "played_at": 1_800_000_000,
        }],
        "total": 1,
        "limit": 10,
        "offset": 0,
    }
    assert history.get("123456789012345678", entry_id) == result["items"][0]
    history.close()


def test_query_isolates_guilds_users_and_pages_with_stable_order(tmp_path, monkeypatch):
    import services.music_history as music_history

    monkeypatch.setattr(music_history.time, "time", lambda: 1_800_000_000)
    history = MusicHistoryDatabase(tmp_path / "history.db")
    first_id = history.record(1, track(1, 10))
    second_id = history.record(1, track(2, 20))
    third_id = history.record(1, track(3, 10))
    history.record(2, track(4, 10))

    page = history.query(1, limit=2, offset=0)
    assert [item["id"] for item in page["items"]] == [third_id, second_id]
    assert page["total"] == 3
    assert page["limit"] == 2
    assert page["offset"] == 0
    assert [item["id"] for item in history.query(1, limit=2, offset=2)["items"]] == [first_id]
    assert [item["id"] for item in history.query(1, requester_id=10)["items"]] == [
        third_id, first_id,
    ]
    assert history.query(2, requester_id=20)["total"] == 0
    assert history.get(2, first_id) is None
    assert history.get(1, third_id, requester_id=20) is None
    assert history.requesters(1) == ["10", "20"]
    assert history.requesters(2) == ["10"]
    assert history.requesters(3) == []
    history.close()


@pytest.mark.parametrize("limit", [0, -1, 101, 1.5, True])
def test_query_rejects_invalid_limit(tmp_path, limit):
    history = MusicHistoryDatabase(tmp_path / "history.db")
    with pytest.raises(ValueError):
        history.query(1, limit=limit)
    history.close()


@pytest.mark.parametrize("offset", [-1, 1.5, True, 2**63])
def test_query_rejects_invalid_offset(tmp_path, offset):
    history = MusicHistoryDatabase(tmp_path / "history.db")
    with pytest.raises(ValueError):
        history.query(1, offset=offset)
    history.close()


def test_close_is_idempotent(tmp_path):
    history = MusicHistoryDatabase(tmp_path / "history.db")
    history.close()
    history.close()


def test_failed_record_rolls_back_and_later_writes_succeed(tmp_path):
    history = MusicHistoryDatabase(tmp_path / 'history.db')
    history.record(1, track(1))
    invalid = track(2)
    invalid.title = None
    with pytest.raises(sqlite3.IntegrityError):
        history.record(1, invalid)
    assert not history.conn.in_transaction
    history.record(1, track(3))
    assert [item['title'] for item in history.query(1)['items']] == ['Song 3', 'Song 1']
    history.close()
