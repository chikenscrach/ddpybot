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
.
├── main.py          # 機器人主程式 (啟動入口)
├── setting.json     # 設定檔 (Token, ID 等)
├── requirements.txt # 依賴套件列表
├── core/
│   └── classes.py   # 核心類別 (Cog_Extension)
├── cmds/            # 指令模組 (Cogs)
│   ├── event.py     # 事件監聽
│   ├── main.py      # 一般指令
│   ├── react.py     # 反應與訊息操作
│   └── task.py      # 定時任務與資料庫
└── data/            # 資料儲存 (自動生成)
    └── ping_count.db # SQLite 資料庫
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
    "token": "你的_BOT_TOKEN",
    "DAILY_CHANNEL_ID": 12345
}
```

## ▶️ 啟動機器人

執行 `main.py` 來啟動機器人：
```bash
python main.py
```