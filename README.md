# DDPYBOT Discord 機器人

這是一個使用 Python (`discord.py`) 編寫的 Discord 機器人專案。包含了許多趣味功能、實用工具以及一個每日隨機標系統。

## ✨ 功能特色

### 🎮 每日隨機標
這是一個獨特的社群互動遊戲：
- **每日標記**：每天 00:00 (台北時間) 自動從伺服器成員中隨機挑選一位進行標記 (Ping)。
- **排行榜**：紀錄被標記的次數並提供排行榜查詢。
- **指令**：
  - `/ping_count [成員]`: 查詢自己或他人的被標記次數。
  - `/ping_rank [數量]`: 查看被標記次數排行榜 (前 10 名)。
  - `/test_daily`: (管理員專用) 手動觸發每日標記測試。

## 🚀 專案結構

```
ddpybot/
├── main.py                # 機器人啟動入口 (載入 cogs, sync tree)
├── setting.json           # 設定檔 (Token, Key, Moderator IDs)
├── core/
│   └── classes.py         # 共用類別 (Cog_Extension, is_manager)
├── cmds/                  # 所有指令模組 (Cogs)
│   ├── main.py            # 基本指令 (ping, whoru)
│   ├── events.py          # 事件監聽 (on_message, on_error)
│   ├── react.py           # 互動指令 (clean, say, 圖片)
│   ├── task.py            # 排程任務 (每日標記, 資料庫操作)
│   ├── ai.py              # AI 對話 (OpenRouter API)
│   └── help.py            # 自訂說明選單 (按鈕翻頁)
└── data/                  # 資料庫存放區
    └── ping_count.db      # SQLite 資料庫檔案 (自動生成)
```

## ⚙️ 安裝與設定

### 1. 安裝環境
確保你已經安裝了 [Python 3.10](https://www.python.org/downloads/) 或以上版本。

### 2. 安裝依賴套件
在終端機 (Terminal) 執行以下指令安裝所需套件：
```bash
pip install -r requirements.txt
```

### 3. 設定檔 (⚠️ 重要)
專案中包含一個 `setting.json` 檔案。
**安全警告**：請勿將含有真實 Token 的 `setting.json` 上傳到公開的 GitHub 儲存庫，這會導致你的機器人帳號被盜用。

`setting.json` 格式如下：
```json
{
	"token": "",
	"openrouter_api_key": "",
	"DAILY_CHANNEL_ID": 12345,
	"moderator_ids": [
        123456789012345678, 
        987654321098765432
    ]
}
```

## ▶️ 啟動機器人

執行 `main.py` 來啟動機器人：
```bash
python main.py
```