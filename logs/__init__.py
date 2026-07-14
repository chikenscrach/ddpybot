# ──────────────────────────────────────────────
#  日誌系統初始化
# ──────────────────────────────────────────────
import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(
    log_dir: str = 'logs',
    log_file: str = 'bot.log',
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,   # 5 MB
    backup_count: int = 3,
):
    """
    設定日誌系統：同時輸出到 console 與檔案。

    Parameters
    ----------
    log_dir : str
        日誌資料夾路徑。
    log_file : str
        日誌檔名。
    level : int
        日誌等級。
    max_bytes : int
        單一日誌檔最大大小（bytes），超過則自動旋轉。
    backup_count : int
        保留的舊日誌檔數量。
    """
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_file)

    fmt = logging.Formatter(
        fmt='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # ── 檔案 Handler（自動旋轉）──
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8',
    )
    file_handler.setFormatter(fmt)

    # ── Console Handler ──
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)

    # ── Root Logger ──
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # 降低 discord.py 本身的日誌等級，避免過多雜訊
    logging.getLogger('discord').setLevel(logging.WARNING)
    logging.getLogger('discord.http').setLevel(logging.WARNING)
