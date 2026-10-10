"""Persistent per-guild music playback history."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from core.config import PROJECT_ROOT


class MusicHistoryDatabase:
    def __init__(self, db_path: str | Path | None = None):
        db_path = Path(db_path) if db_path else PROJECT_ROOT / "data" / "music_history.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS music_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                requester_id TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                duration REAL,
                thumbnail TEXT,
                played_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_music_history_guild_played
                ON music_history (guild_id, played_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_music_history_guild_requester_played
                ON music_history (guild_id, requester_id, played_at DESC, id DESC);
            """
        )
        self._closed = False

    @staticmethod
    def _entry(row: sqlite3.Row) -> dict:
        return {
            "id": int(row["id"]),
            "guild_id": str(row["guild_id"]),
            "requester_id": str(row["requester_id"]),
            "title": row["title"],
            "url": row["url"],
            "duration": row["duration"],
            "thumbnail": row["thumbnail"],
            "played_at": int(row["played_at"]),
        }

    def record(self, guild_id, track) -> int:
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO music_history (
                    guild_id, requester_id, title, url, duration, thumbnail, played_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(guild_id),
                    str(track.requester_id),
                    track.title,
                    track.url,
                    track.duration,
                    track.thumbnail,
                    int(time.time()),
                ),
            )
        return int(cursor.lastrowid)

    def query(
        self, guild_id, requester_id=None, limit: int = 10, offset: int = 0,
    ) -> dict:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit 必須介於 1 到 100。")
        if (
            isinstance(offset, bool) or not isinstance(offset, int)
            or not 0 <= offset <= 2**63 - 1
        ):
            raise ValueError("offset 必須介於 0 到 SQLite 整數上限。")

        where = "guild_id = ?"
        params = [str(guild_id)]
        if requester_id is not None:
            where += " AND requester_id = ?"
            params.append(str(requester_id))
        total = int(
            self.conn.execute(
                f"SELECT COUNT(*) FROM music_history WHERE {where}", params,
            ).fetchone()[0]
        )
        rows = self.conn.execute(
            f"""
            SELECT * FROM music_history
            WHERE {where}
            ORDER BY played_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        return {
            "items": [self._entry(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def get(self, guild_id, entry_id: int, requester_id=None) -> dict | None:
        where = "guild_id = ? AND id = ?"
        params = [str(guild_id), entry_id]
        if requester_id is not None:
            where += " AND requester_id = ?"
            params.append(str(requester_id))
        row = self.conn.execute(
            f"SELECT * FROM music_history WHERE {where}", params,
        ).fetchone()
        return self._entry(row) if row else None

    def requesters(self, guild_id) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT DISTINCT requester_id FROM music_history
            WHERE guild_id = ? ORDER BY requester_id
            """,
            (str(guild_id),),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def close(self):
        if not self._closed:
            self.conn.close()
            self._closed = True
