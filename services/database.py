# ──────────────────────────────────────────────
#  SQLite 資料庫操作統一管理
# ──────────────────────────────────────────────
import os
import sqlite3


class PingDatabase:
    """封裝 ping_count 的所有 SQLite 操作"""

    def __init__(self, db_path: str = 'data/ping_count.db'):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
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
        self.conn.execute('''
            INSERT INTO ping_counts (user_id, count) VALUES (?, 1)
            ON CONFLICT(user_id) DO UPDATE SET count = count + 1
        ''', (user_id,))
        self.conn.commit()
        cur = self.conn.execute(
            'SELECT count FROM ping_counts WHERE user_id = ?', (user_id,)
        )
        return cur.fetchone()[0]

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
