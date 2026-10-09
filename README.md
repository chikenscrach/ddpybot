# DDPYBOT

![Bot Status](https://img.shields.io/badge/Status-Online-success)
![Python Version](https://img.shields.io/badge/Python-3.12-blue)
![discord.py](https://img.shields.io/badge/discord.py-2.7.1-blueviolet)
![Package Manager](https://img.shields.io/badge/uv-package%20manager-orange)

DDPYBOT 是以 `discord.py` 開發的多功能 Discord Bot，整合 AI 對話、YouTube 音樂播放、地震資訊、PTT 文章、Danbooru 圖片、社群互動與 Bot owner 專用 Dashboard。

專案採分層與模組化設計，將 Discord 指令、外部服務、共用工具、互動元件與資料存取拆分，方便維護與擴充。

## 主要功能

- **AI 對話**：OpenRouter / Groq，多輪上下文、引用訊息與圖片輸入。
- **音樂播放**：YouTube 點歌、播放清單、佇列、單曲／清單循環、本機快取與 FFmpeg 播放。
- **資訊查詢**：中央氣象署地震資訊、PTT 文章與 Danbooru 圖片。
- **社群功能**：每日隨機標記、排行榜、統計與管理指令。
- **啟動通知**：各伺服器可指定通知頻道，機器人每次啟動時通知一次，也可停用。
- **互動介面**：Discord Buttons、Views、分頁與系統資訊面板。
- **Owner Dashboard**：Discord OAuth2 登入、狀態總覽、Ping 分析、音樂控制與設定管理。
- **部署與維運**：Docker Compose、旋轉日誌、pytest、Ruff 與 GitHub Actions CI。

## 快速開始

### Docker（推薦）

```bash
cp .env.example .env
cp setting.json.example setting.json
docker compose up -d --build
```

### 本機執行

建議使用 Python 3.12、[uv](https://docs.astral.sh/uv/)、FFmpeg；音樂功能另建議安裝 Deno。

```bash
cp .env.example .env
cp setting.json.example setting.json
uv sync
uv run python main.py
```

至少需要在 `.env` 設定 `TOKEN`。AI、地震與 Dashboard 等功能會依啟用項目需要額外 API Key 或 OAuth2 設定。

### 啟動通知

具有「管理伺服器」權限的成員可使用：

- `/startupnotify action:set channel:#通知頻道`：設定或更換通知頻道，下次啟動時發送通知。
- `/startupnotify action:disable`：停用此伺服器的啟動通知。

預設停用，每個伺服器各自保存一個文字頻道；Bot 需要在該頻道擁有「查看頻道」與「傳送訊息」權限。設定存於 `data/startup_notifications.db`，現有 Docker Compose 的 `data/` 掛載會保留設定。Discord 重新連線或重載模組不會重複通知；頻道被刪除或無法發送時會記錄日誌，不影響其他伺服器。

## 文件

完整文件集中於 [GitHub Wiki](https://github.com/chikenscrach/ddpybot/wiki)。

| 文件 | 內容 |
| --- | --- |
| [文件首頁](https://github.com/chikenscrach/ddpybot/wiki) | 文件導覽與功能概覽 |
| [指令參考](https://github.com/chikenscrach/ddpybot/wiki/Commands) | Slash / Hybrid / Prefix 指令 |
| [設定指南](https://github.com/chikenscrach/ddpybot/wiki/Configuration) | `.env`、`setting.json`、音樂參數 |
| [音樂與 YouTube](https://github.com/chikenscrach/ddpybot/wiki/Music-and-YouTube) | 播放行為、快取、cookies、PO Token |
| [Owner Dashboard](https://github.com/chikenscrach/ddpybot/wiki/Dashboard) | OAuth2、頁面功能、Docker 啟用與安全模型 |
| [部署指南](https://github.com/chikenscrach/ddpybot/wiki/Deployment) | Docker、本機部署、Discord 權限 |
| [架構與開發](https://github.com/chikenscrach/ddpybot/wiki/Architecture-and-Development) | 專案結構、技術棧、測試、CI、日誌 |

## 開發

```bash
uv sync --locked --dev
uv run --locked ruff check .
SETTING_PATH=setting.json.example uv run --locked pytest
```

CI 會在推送 `main` 與 Pull Request 時執行 Ruff 與 pytest。更多資訊請見 [架構與開發](https://github.com/chikenscrach/ddpybot/wiki/Architecture-and-Development)。
