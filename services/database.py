# ──────────────────────────────────────────────
#  SQLite 資料庫操作統一管理
# ──────────────────────────────────────────────
import sqlite3
import time
from datetime import date, datetime, timezone
from datetime import time as datetime_time
from pathlib import Path
from zoneinfo import ZoneInfo

from core.config import PROJECT_ROOT

TIMEZONE = ZoneInfo("Asia/Taipei")
EXPORT_EVENTS_LIMIT = 10_000
SUPPORTED_SOURCES = frozenset({"all", "scheduled", "manual"})


class PingDatabase:
    """封裝 ping 累計資料及可追溯事件的 SQLite 操作。"""

    def __init__(self, db_path: str | Path | None = None):
        # 預設路徑以專案根目錄為基準，不受啟動時工作目錄影響
        db_path = Path(db_path) if db_path else PROJECT_ROOT / "data" / "ping_count.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        # WAL 模式：讀寫不互鎖、意外中斷後可自動復原；WAL 下 NORMAL 已足夠安全
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._migrate()

    def _migrate(self):
        """建立事件紀錄，並標記開始保留可追溯明細的時間。"""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS ping_counts (
                    user_id      INTEGER PRIMARY KEY,
                    count        INTEGER DEFAULT 0,
                    last_ping_at INTEGER
                )
            """)
            columns = {row[1] for row in self.conn.execute("PRAGMA table_info(ping_counts)")}
            # 舊版本的資料庫只有 user_id/count；補欄位時保留既有次數。
            if "last_ping_at" not in columns:
                self.conn.execute("ALTER TABLE ping_counts ADD COLUMN last_ping_at INTEGER")

            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS ping_events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    TEXT NOT NULL,
                    guild_id   TEXT,
                    channel_id TEXT,
                    message_id TEXT UNIQUE,
                    event_at   INTEGER NOT NULL,
                    source     TEXT NOT NULL CHECK (source IN ('scheduled', 'manual'))
                )
            """)
            self.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ping_events_event_at
                ON ping_events(event_at)
            """)
            self.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ping_events_guild_event_at
                ON ping_events(guild_id, event_at)
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS ping_metadata (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            # 對既有累計資料只記錄 migration 時的總數，不替舊資料虛構事件日期。
            # 同時存在事件表但缺 metadata 的資料庫，先扣除已可追溯的事件數。
            metadata = {row[0] for row in self.conn.execute("SELECT key FROM ping_metadata")}
            if "history_started_at" not in metadata:
                now = int(time.time())
                event_total = int(
                    self.conn.execute("SELECT COUNT(*) FROM ping_events").fetchone()[0]
                )
                aggregate_total = int(
                    self.conn.execute("SELECT COALESCE(SUM(count), 0) FROM ping_counts").fetchone()[
                        0
                    ]
                )
                legacy_total = max(0, aggregate_total - event_total)
                self.conn.executemany(
                    "INSERT OR IGNORE INTO ping_metadata (key, value) VALUES (?, ?)",
                    [("history_started_at", str(now)), ("legacy_total", str(legacy_total))],
                )
            elif "legacy_total" not in metadata:
                aggregate_total = int(
                    self.conn.execute("SELECT COALESCE(SUM(count), 0) FROM ping_counts").fetchone()[
                        0
                    ]
                )
                event_total = int(
                    self.conn.execute("SELECT COUNT(*) FROM ping_events").fetchone()[0]
                )
                self.conn.execute(
                    "INSERT INTO ping_metadata (key, value) VALUES (?, ?)",
                    ("legacy_total", str(max(0, aggregate_total - event_total))),
                )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def close(self):
        """關閉資料庫連線"""
        self.conn.close()

    @staticmethod
    def _validate_range(start: date, end: date, source: str):
        if isinstance(start, datetime) or not isinstance(start, date):
            raise TypeError("start 必須是 datetime.date")
        if isinstance(end, datetime) or not isinstance(end, date):
            raise TypeError("end 必須是 datetime.date")
        if end < start:
            raise ValueError("end 不可早於 start")
        if (end - start).days + 1 > 366:
            raise ValueError("日期範圍不可超過 366 天")
        if source not in SUPPORTED_SOURCES:
            raise ValueError("source 必須是 'all'、'scheduled' 或 'manual'")

    @staticmethod
    def _utc_bounds(start: date, end: date) -> tuple[int, int]:
        """將台北時區的含端點日期轉成 UTC Unix 秒數的左閉右開範圍。"""
        start_local = datetime.combine(start, datetime_time.min, tzinfo=TIMEZONE)
        after_end_local = datetime.combine(
            date.fromordinal(end.toordinal() + 1), datetime_time.min, tzinfo=TIMEZONE
        )
        return int(start_local.timestamp()), int(after_end_local.timestamp())

    @staticmethod
    def _event_dict(row) -> dict:
        event_id, user_id, guild_id, channel_id, message_id, event_at, source = row
        return {
            "id": int(event_id),
            "user_id": str(user_id),
            "guild_id": str(guild_id) if guild_id is not None else None,
            "channel_id": str(channel_id) if channel_id is not None else None,
            "message_id": str(message_id) if message_id is not None else None,
            "event_at": int(event_at),
            "source": source,
        }

    @staticmethod
    def _where(start_at: int, after_end_at: int, guild_id: int | None, source: str):
        clauses = ["event_at >= ?", "event_at < ?"]
        params = [start_at, after_end_at]
        if guild_id is not None:
            clauses.append("guild_id = ?")
            params.append(str(guild_id))
        if source != "all":
            clauses.append("source = ?")
            params.append(source)
        return " AND ".join(clauses), params

    def add_ping(
        self,
        user_id: int,
        *,
        guild_id: int | None = None,
        channel_id: int | None = None,
        message_id: int | None = None,
        source: str = "scheduled",
        event_at: int | float | None = None,
    ) -> int:
        """新增 ping 事件與累計，並回傳累計次數。

        明細和聚合資料放在同一個 transaction。若 Discord message_id 已存在，
        視為重送並回傳目前累計，不重複新增事件或計數。event_at 使用 UTC Unix 秒。
        """
        if source not in ("scheduled", "manual"):
            raise ValueError("source 必須是 'scheduled' 或 'manual'")
        timestamp = int(time.time() if event_at is None else event_at)
        user_key = str(user_id)
        event_values = (
            user_key,
            str(guild_id) if guild_id is not None else None,
            str(channel_id) if channel_id is not None else None,
            str(message_id) if message_id is not None else None,
            timestamp,
            source,
        )

        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO ping_events (
                    user_id, guild_id, channel_id, message_id, event_at, source
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO NOTHING
            """,
                event_values,
            )
            if cur.rowcount == 0:
                row = self.conn.execute(
                    "SELECT count FROM ping_counts WHERE user_id = ?", (int(user_id),)
                ).fetchone()
                return int(row[0]) if row else 0

            cur = self.conn.execute(
                """
                INSERT INTO ping_counts (user_id, count, last_ping_at) VALUES (?, 1, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    count = ping_counts.count + 1,
                    last_ping_at = excluded.last_ping_at
                RETURNING count
            """,
                (int(user_id), timestamp),
            )
            count = int(cur.fetchone()[0])
        return count

    def query_dashboard(
        self,
        start: date,
        end: date,
        *,
        guild_id: int | None = None,
        source: str = "all",
    ) -> dict:
        """取得台北日界線的 ping 分析資料。

        `history_started_at` 是開始記錄新事件的 UTC Unix 秒；較早日期的 0
        只表示沒有可追溯明細，不代表當時沒有 ping。
        """
        self._validate_range(start, end, source)
        start_at, after_end_at = self._utc_bounds(start, end)
        where, params = self._where(start_at, after_end_at, guild_id, source)

        period_rows = self.conn.execute(
            f"""SELECT user_id, event_at, source FROM ping_events WHERE {where}""",
            params,
        ).fetchall()
        per_day = {}
        per_user = {}
        for user_id, event_at, event_source in period_rows:
            local_date = (
                datetime.fromtimestamp(event_at, tz=timezone.utc)
                .astimezone(TIMEZONE)
                .date()
                .isoformat()
            )
            daily_counts = per_day.setdefault(local_date, {"count": 0, "scheduled": 0, "manual": 0})
            daily_counts["count"] += 1
            daily_counts[event_source] += 1
            user_key = str(user_id)
            user_stats = per_user.setdefault(user_key, [0, None])
            user_stats[0] += 1
            user_stats[1] = event_at if user_stats[1] is None else max(user_stats[1], event_at)

        daily = []
        for day_offset in range((end - start).days + 1):
            day = date.fromordinal(start.toordinal() + day_offset).isoformat()
            counts = per_day.get(day, {"count": 0, "scheduled": 0, "manual": 0})
            daily.append({"date": day, **counts})

        leaders = [
            {"user_id": user_id, "count": count, "last_ping_at": last_ping_at}
            for user_id, (count, last_ping_at) in per_user.items()
        ]
        leaders.sort(key=lambda row: (-row["count"], -row["last_ping_at"], row["user_id"]))

        event_rows = self.conn.execute(
            f"""
            SELECT id, user_id, guild_id, channel_id, message_id, event_at, source
            FROM ping_events WHERE {where}
            ORDER BY event_at DESC, id DESC LIMIT 100
        """,
            params,
        ).fetchall()
        events = [self._event_dict(row) for row in event_rows]

        lifetime_total = int(
            self.conn.execute("SELECT COALESCE(SUM(count), 0) FROM ping_counts").fetchone()[0]
        )
        lifetime_leaders = [
            {
                "user_id": str(user_id),
                "count": int(count),
                "last_ping_at": int(last_ping_at) if last_ping_at is not None else None,
            }
            for user_id, count, last_ping_at in self.conn.execute("""
                SELECT user_id, count, last_ping_at FROM ping_counts
                ORDER BY count DESC, user_id ASC LIMIT 25
            """).fetchall()
        ]
        metadata = dict(
            self.conn.execute(
                "SELECT key, value FROM ping_metadata WHERE key IN ('history_started_at', 'legacy_total')"
            ).fetchall()
        )
        history_started_at = int(metadata["history_started_at"])
        history_start_date = (
            datetime.fromtimestamp(history_started_at, tz=timezone.utc)
            .astimezone(TIMEZONE)
            .date()
            .isoformat()
        )

        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": "Asia/Taipei",
            "history_started_at": history_started_at,
            "history_start_date": history_start_date,
            "legacy_total": int(metadata["legacy_total"]),
            "lifetime_total": lifetime_total,
            "period_total": len(period_rows),
            "unique_users": len(per_user),
            "daily": daily,
            "leaders": leaders,
            "events": events,
            "lifetime_leaders": lifetime_leaders,
        }

    def export_events(
        self,
        start: date,
        end: date,
        guild_id: int | None = None,
        source: str = "all",
    ) -> dict:
        """匯出日期範圍內的事件，最多 10,000 筆並明確回報是否截斷。"""
        self._validate_range(start, end, source)
        start_at, after_end_at = self._utc_bounds(start, end)
        where, params = self._where(start_at, after_end_at, guild_id, source)
        rows = self.conn.execute(
            f"""
            SELECT id, user_id, guild_id, channel_id, message_id, event_at, source
            FROM ping_events WHERE {where}
            ORDER BY event_at ASC, id ASC LIMIT ?
        """,
            [*params, EXPORT_EVENTS_LIMIT + 1],
        ).fetchall()
        truncated = len(rows) > EXPORT_EVENTS_LIMIT
        events = [self._event_dict(row) for row in rows[:EXPORT_EVENTS_LIMIT]]
        return {"events": events, "truncated": truncated}

    def get_count(self, user_id: int) -> int:
        """查詢某人被標記次數"""
        cur = self.conn.execute("SELECT count FROM ping_counts WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return row[0] if row else 0

    def get_total_count(self) -> int:
        """查詢所有人的標記總次數"""
        cur = self.conn.execute("SELECT COALESCE(SUM(count), 0) FROM ping_counts")
        return int(cur.fetchone()[0])

    def get_last_ping(self, user_id: int) -> int | None:
        """查詢某人最後一次被標記的 Unix 時間；沒有紀錄時回傳 None"""
        cur = self.conn.execute(
            "SELECT last_ping_at FROM ping_counts WHERE user_id = ?", (user_id,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    def get_leaderboard(self, limit: int = 10) -> list:
        """取得排行榜（次數由高到低）"""
        cur = self.conn.execute(
            "SELECT user_id, count FROM ping_counts ORDER BY count DESC LIMIT ?", (limit,)
        )
        return cur.fetchall()
