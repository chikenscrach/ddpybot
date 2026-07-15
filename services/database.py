# ──────────────────────────────────────────────
#  SQLite 資料庫操作統一管理
# ──────────────────────────────────────────────
import sqlite3
from pathlib import Path

from core.config import PROJECT_ROOT


class PingDatabase:
    """封裝 ping_count 的所有 SQLite 操作"""

    def __init__(self, db_path: str | Path | None = None):
        # 預設路徑以專案根目錄為基準，不受啟動時工作目錄影響
        db_path = Path(db_path) if db_path else PROJECT_ROOT / 'data' / 'ping_count.db'
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        # WAL 模式：讀寫不互鎖、意外中斷後可自動復原；WAL 下 NORMAL 已足夠安全
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=NORMAL')
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS ping_counts (
                user_id  INTEGER PRIMARY KEY,
                count    INTEGER DEFAULT 0
            )
        ''')
        self.conn.commit()

    def close(self):
        """關閉資料庫連線"""
        self.conn.close()

    def add_ping(self, user_id: int) -> int:
        """新增一次標記，回傳累計次數"""
        # SQLite 3.35+ 的 RETURNING：upsert 與取值一條 query 完成
        cur = self.conn.execute('''
            INSERT INTO ping_counts (user_id, count) VALUES (?, 1)
            ON CONFLICT(user_id) DO UPDATE SET count = count + 1
            RETURNING count
        ''', (user_id,))
        count = cur.fetchone()[0]
        self.conn.commit()
        return count

    def get_count(self, user_id: int) -> int:
        """查詢某人被標記次數"""
        cur = self.conn.execute(
            'SELECT count FROM ping_counts WHERE user_id = ?', (user_id,)
        )
        row = cur.fetchone()
        return row[0] if row else 0

    def get_leaderboard(self, limit: int = 10) -> list:
        """取得排行榜（次數由高到低）"""
        cur = self.conn.execute(
            'SELECT user_id, count FROM ping_counts ORDER BY count DESC LIMIT ?',
            (limit,)
        )
        return cur.fetchall()
