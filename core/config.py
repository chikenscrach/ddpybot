import json
import os

from dotenv import load_dotenv

# .env 需在讀取 os.environ 之前載入
load_dotenv()

# 集中載入設定檔：整個專案只在這裡讀取一次 setting.json，
# 其他模組請使用 `from core.config import settings`
try:
    with open('setting.json', 'r', encoding='utf8') as jfile:
        settings: dict = json.load(jfile)
except FileNotFoundError:
    raise SystemExit(
        '找不到 setting.json，請複製 setting.json.example 為 setting.json 並填入設定後再啟動。'
    )


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
