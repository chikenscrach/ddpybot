# DDPYBOT ─ 全方位 Discord 機器人解決方案

![Bot Status](https://img.shields.io/badge/Status-Online-success)
![Python Version](https://img.shields.io/badge/Python-3.12-blue)
![Discord.py](https://img.shields.io/badge/discord.py-2.7.1-blueviolet)
![Package Manager](https://img.shields.io/badge/uv-package%20manager-orange)

DDPYBOT 是一個基於 `discord.py` 開發的高層級 Discord 機器人。本專案採用現代化的 **分層架構 (Layered Architecture)** 設計，將業務邏輯、API 調用與 UI 組件完全解耦，提供極佳的擴充性與可維護性。

---

## 📂 專案架構詳解

專案依據功能職責分為以下層次，透過模組化設計確保代碼清晰：

```bash
ddpybot/
├── main.py                # 🚀 啟動入口：Bot 初始化、Cog 自動載入、斜線指令同步
├── .env                   # 🔒 安全層：存放 Token、API Key 等敏感資訊 (Git 忽略)
├── setting.json           # ⚙️ 配置層：存放頻道 ID、管理員列表、AI 供應商選擇等
├── pyproject.toml         # 📦 依賴管理：使用 uv 管理 Python 依賴
├── core/
│   ├── classes.py         # 🏛️ 核心層：定義 Cog_Extension 基底類別
│   └── config.py          # 🔑 配置載入：統一讀取 .env 與 setting.json
├── cmds/                  # 🎮 指令層：所有的功能模組 (Cogs)
│   ├── ai.py              # AI 對話（支援多模型、圖片輸入、引用上下文）
│   ├── earthquake.py      # 中央氣象署地震資訊查詢
│   ├── ptt.py             # PTT 文章抓取（內文解析、推噓統計、分頁推文）
│   ├── task.py            # 定時任務（每日隨機標人 + 排行榜）
│   ├── info.py            # 機器人系統資訊面板（含即時重新整理）
│   ├── help.py            # 互動式翻頁指令說明手冊
│   ├── react.py           # 代理發話、訊息清除、趣味回覆
│   ├── main.py            # 基本指令（延遲測試、追番連結）
│   └── event.py           # 訊息監聽與自動回覆
├── services/              # 🌐 服務層：封裝業務邏輯與外部 API
│   ├── ai_service.py      # AI 供應商封裝（OpenRouter / Groq 雙引擎）
│   ├── earthquake_api.py  # 中央氣象署地震 API（並行抓取 + 60 秒快取）
│   └── database.py        # SQLite 資料庫封裝 (PingDatabase)
├── utils/                 # 🔧 工具層：跨模組通用工具
│   ├── constants.py       # 顏色、Emoji、URL、System Prompt 等常數
│   ├── time_helper.py     # 時區轉換 (Asia/Taipei) 與時間格式化
│   ├── embed_builder.py   # 進度條生成與超長訊息分段發送
│   └── validators.py      # 管理員權限檢查 (is_manager)
├── views/                 # 🖱️ UI 層：Discord 互動元件
│   └── pagination.py      # 通用分頁組件 (⏪◀ 頁碼 ▶⏩)
├── logs/                  # 📝 日誌層：自動旋轉日誌系統
│   └── __init__.py        # setup_logging()：Console + 檔案雙輸出
└── data/                  # 💾 資料層：SQLite 資料庫檔案
    └── ping_count.db      # 每日隨機標記次數統計
```

---

## 🛠️ 指令全清單

### 🤖 AI 對話

| 指令 | 參數 | 說明 | 類型 | 權限 |
| :--- | :--- | :--- | :--- | :--- |
| `/ai` | `message` | 與 AI 對話（可回覆訊息自動附加上下文、支援圖片附件） | Hybrid | 使用者 |
| `/ai_clear` | - | 清除個人目前的對話上下文 | Hybrid | 使用者 |

### 🌍 地震資訊

| 指令 | 參數 | 說明 | 類型 | 權限 |
| :--- | :--- | :--- | :--- | :--- |
| `/earthquake` | `[number]` | 查看最新地震列表；指定編號可查看完整報告與震度圖 | Slash | 使用者 |

### 🗞️ PTT 文章

| 指令 | 參數 | 說明 | 類型 | 權限 |
| :--- | :--- | :--- | :--- | :--- |
| `/ptt` | `url` | 抓取 PTT 文章內文、推噓統計，支援推文分頁瀏覽與完整內文下載 | Slash | 使用者 |

### ⏰ 社群互動

| 指令 | 參數 | 說明 | 類型 | 權限 |
| :--- | :--- | :--- | :--- | :--- |
| `/ping_count` | `[member]` | 查詢被「每日隨機標」選中的累計次數 | Hybrid | 使用者 |
| `/ping_rank` | `[top]` | 查看隨機標排行榜（預設前 10，最多 25） | Hybrid | 使用者 |
| `/test_daily` | - | 手動觸發一次每日隨機標（測試用） | Hybrid | 管理員 |

### 🎭 管理與互動

| 指令 | 參數 | 說明 | 類型 | 權限 |
| :--- | :--- | :--- | :--- | :--- |
| `/say` | `msg` | 讓機器人代理發放訊息（前綴指令會自動刪除原訊息） | Hybrid | 使用者 |
| `/clean` | `num` | 批量清除目前頻道的訊息（1~100 則） | Hybrid | 管理員 |
| `/亞歷山大` | - | 亞歷山大 | Hybrid | 使用者 |

### 📋 資訊

| 指令 | 參數 | 說明 | 類型 | 權限 |
| :--- | :--- | :--- | :--- | :--- |
| `/botinfo` | - | 顯示機器人運行狀態、系統資源與版本資訊（可即時重新整理） | Slash | 使用者 |
| `/help` | - | 互動式翻頁指令說明手冊 | Hybrid | 使用者 |
| `/ping` | - | 測試網路延遲 (Latency) | Hybrid | 使用者 |
| `/whoru` | - | 我是誰 | Hybrid | 使用者 |
| `/dd` | - | DD 追直播必備連結 (hololive schedule) | Hybrid | 使用者 |

### 🔧 Bot 擁有者

| 指令 | 參數 | 說明 | 類型 | 權限 |
| :--- | :--- | :--- | :--- | :--- |
| `!load` | `extension` | 載入功能模組 | Prefix | 擁有者 |
| `!unload` | `extension` | 卸載功能模組 | Prefix | 擁有者 |
| `!reload` | `extension` | 重新載入功能模組 | Prefix | 擁有者 |
| `!sync` | - | 手動同步斜線指令 | Prefix | 擁有者 |

### 📡 自動回覆 (Event)

機器人會自動偵測特定訊息內容並回覆，不需要任何指令前綴：

| 觸發條件 | 回覆內容 |
| :--- | :--- |
| 訊息以「的啦」結尾 | 原住民? |
| `ㄐㄐ人臭DD` | 你婆真好用 |
| `0.0` | 0.0三小?你是低能兒嗎肏 |
| `夸黑` | 主Q副哭 有社恐點社恐 |
| `志道樓` | 黃民化運動 |

---

## ⚙️ 安全與配置指南

### 1. 敏感資訊管理 (`.env`)
本專案嚴格區分秘密資訊。請勿將 `.env` 提交至版本控制系統。建置步驟：
- 複製 `.env.example` 並重新命名為 `.env`。
- 填入以下必要的 API 密鑰：

| 環境變數 | 說明 | 必要性 |
| :--- | :--- | :--- |
| `TOKEN` | Discord Bot Token | ✅ 必要 |
| `OPENROUTER_API_KEY` | OpenRouter API Key | AI_PROVIDER=openrouter 時必要 |
| `GROQ_API_KEY` | Groq API Key | AI_PROVIDER=groq 時必要 |
| `CWA_API_KEY` | 中央氣象署 API Key | `/earthquake` 指令所需 |

### 2. 一般設定 (`setting.json`)
管理與秘密無關的專案設定。複製 `setting.json.example` 為 `setting.json` 並修改：

| 欄位 | 說明 | 預設值 |
| :--- | :--- | :--- |
| `DAILY_CHANNEL_ID` | 每日隨機標訊息發送的頻道 ID | - |
| `moderator_ids` | 擁有機器人管理級權限的使用者 ID 清單 | `[]` |
| `AI_PROVIDER` | AI 供應商選擇：`openrouter` 或 `groq` | `openrouter` |
| `GROQ_MODEL` | Groq 使用的語言模型名稱 | `moonshotai/kimi-k2-instruct-0905` |

---

## 🚀 部署教學

本專案提供 **Docker 容器化部署 (推薦)** 與 **傳統本機部署** 兩種方式。

### 🐳 方式一：使用 Docker 部署 (推薦)

1.  **環境準備**：請確認系統已安裝 [Docker](https://www.docker.com/) 與 Docker Compose。
2.  **設定密鑰與配置檔**：
    - 複製 `.env.example` 並重新命名為 `.env`，填寫對應的密鑰。
    - 複製 `setting.json.example` 為 `setting.json` 並填入設定（若無此檔案，Docker 掛載時會將其誤建為資料夾）。
3.  **啟動服務**：
    ```bash
    docker compose up -d --build
    ```
    > 💡 **進階說明**：
    > `docker-compose.yml` 預設使用本地端 `Dockerfile` 構建映像檔。運行後，機器人的資料庫檔與日誌檔會分別掛載到本機的 `./data` 與 `./logs` 目錄中，實現資料持久化。`setting.json` 也會掛載進容器，修改後重啟即可生效。

### 💻 方式二：傳統本機部署

1.  **環境準備**：建議使用 Python 3.12 以上版本，並安裝 [uv](https://docs.astral.sh/uv/) 套件管理工具。
2.  **安裝依賴**：
    ```bash
    uv sync
    ```
3.  **設定密鑰與配置檔**：確認 `.env` 與 `setting.json` 已正確設定（參考上方配置指南）。
4.  **啟動**：
    ```bash
    uv run python main.py
    ```

    > 💡 **不使用 uv？** 也可以手動建立虛擬環境：
    > ```bash
    > python -m venv .venv
    > .\.venv\Scripts\activate   # Windows
    > # source .venv/bin/activate  # Linux/macOS
    > pip install -e .
    > python main.py
    > ```

---

## 📈 技術棧

| 類別 | 技術 | 用途 |
| :--- | :--- | :--- |
| **框架** | `discord.py` | 非同步 Discord API 封裝 |
| **HTTP 請求** | `aiohttp` | 高性能非同步 API 通訊 |
| **AI 供應商** | OpenRouter / Groq | 雙引擎 AI 對話服務 |
| **AI SDK** | `groq` | Groq 官方 Python SDK |
| **網頁解析** | `beautifulsoup4` + `lxml` | PTT 文章 HTML 解析 |
| **環境變數** | `python-dotenv` | `.env` 檔讀取 |
| **系統監控** | `psutil` | 顯示 CPU / 記憶體等資源佔用 |
| **資料庫** | `sqlite3` | 輕量級本地資料持久化 |
| **時區處理** | `zoneinfo` + `tzdata` | Asia/Taipei 時區支援 |
| **套件管理** | `uv` | 快速 Python 依賴管理 |
| **部署** | Docker + Docker Compose | 容器化部署方案 |

---

> [!TIP]
> **維護日誌**：機器人運行過程中，所有 `ERROR` 與 `INFO` 等級的事件會同步記錄在 `logs/bot.log` 中。檔案達到 5MB 時會自動循環備份（保留 3 份），確保存放空間不爆炸。