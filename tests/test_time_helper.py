from datetime import datetime, timedelta, timezone

from utils.time_helper import fmt_uptime, parse_cwa_time, to_unix


def test_parse_cwa_legacy_format():
    """舊格式（無時區）視為 UTC+8"""
    dt = parse_cwa_time('2026-07-09 09:29:01')
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timedelta(hours=8)


def test_parse_cwa_iso_format():
    """ISO 8601 格式帶時區直接使用"""
    dt = parse_cwa_time('2026-07-09T09:29:01+08:00')
    assert dt.utcoffset() == timedelta(hours=8)


def test_both_formats_same_timestamp():
    """兩種格式代表同一時刻，Unix timestamp 應相等"""
    assert to_unix('2026-07-09 09:29:01') == to_unix('2026-07-09T09:29:01+08:00')


def test_fmt_uptime():
    start = datetime.now(timezone.utc) - timedelta(days=1, hours=2, minutes=3, seconds=30)
    result = fmt_uptime(start)
    assert '1 天' in result
    assert '2 小時' in result
    assert '3 分鐘' in result


def test_fmt_uptime_seconds_only():
    start = datetime.now(timezone.utc) - timedelta(seconds=5)
    result = fmt_uptime(start)
    assert '天' not in result
    assert '小時' not in result
    assert '秒' in result
