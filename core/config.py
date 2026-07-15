import json
import os
from pathlib import Path

from dotenv import load_dotenv

# 專案根目錄：所有路徑以此為基準，不受啟動時工作目錄影響
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# .env 需在讀取 os.environ 之前載入
load_dotenv(PROJECT_ROOT / '.env')

# 設定檔路徑可用環境變數覆寫（例如測試或多實例部署）
SETTING_PATH = Path(os.environ.get('SETTING_PATH', PROJECT_ROOT / 'setting.json'))

# 集中載入設定檔：整個專案只在這裡讀取一次 setting.json，
# 其他模組請使用 `from core.config import settings`
try:
    with open(SETTING_PATH, encoding='utf8') as jfile:
        settings: dict = json.load(jfile)
except FileNotFoundError:
    raise SystemExit(
        f'找不到 {SETTING_PATH}，請複製 setting.json.example 為 setting.json 並填入設定後再啟動。'
    ) from None


def _secret(env_key: str, legacy_key: str | None = None, default: str = '') -> str:
    """敏感資訊以環境變數 (.env) 優先，setting.json 中的舊欄位作為向下相容備援"""
    value = os.environ.get(env_key, '').strip()
    if value:
        return value
    if legacy_key and settings.get(legacy_key):
        return str(settings[legacy_key])
    return default


TOKEN = _secret('TOKEN', 'token')
OPENROUTER_API_KEY = _secret('OPENROUTER_API_KEY', 'openrouter_api_key')
GROQ_API_KEY = _secret('GROQ_API_KEY')
CWA_API_KEY = _secret('CWA_API_KEY', 'CWA_API_KEY')
