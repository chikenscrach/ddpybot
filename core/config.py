import json

# 集中載入設定檔：整個專案只在這裡讀取一次 setting.json，
# 其他模組請使用 `from core.config import settings`
with open('setting.json', 'r', encoding='utf8') as jfile:
    settings: dict = json.load(jfile)
