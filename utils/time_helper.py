# ──────────────────────────────────────────────
#  時間格式轉換工具
# ──────────────────────────────────────────────
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# 台灣時區（統一使用）
TIMEZONE = ZoneInfo('Asia/Taipei')
TW_OFFSET = timezone(timedelta(hours=8))


def parse_cwa_time(time_str: str) -> datetime:
    """
    解析 CWA 時間字串為帶時區的 datetime。
    同時支援 '2026-07-09 09:29:01' 與 ISO 8601 '2026-07-09T09:29:01+08:00' 兩種格式。
    """
    dt = datetime.fromisoformat(time_str)
    if dt.tzinfo is None:  # 沒帶時區的舊格式一律視為 UTC+8
        dt = dt.replace(tzinfo=TW_OFFSET)
    return dt


def to_unix(time_str: str) -> int:
    """將 CWA 時間字串轉為 Unix Timestamp"""
    return int(parse_cwa_time(time_str).timestamp())


def fmt_uptime(start_time: datetime) -> str:
    """將 uptime 格式化為 '○ 天 ○ 小時 ○ 分鐘 ○ 秒'"""
    ts = int((datetime.now(timezone.utc) - start_time).total_seconds())
    d, ts = divmod(ts, 86_400)
    h, ts = divmod(ts, 3_600)
    m, s  = divmod(ts, 60)
    parts = []
    if d: parts.append(f"{d} 天")
    if h: parts.append(f"{h} 小時")
    if m: parts.append(f"{m} 分鐘")
    parts.append(f"{s} 秒")
    return " ".join(parts)
