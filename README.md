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
│   ├── danbooru.py        # Danbooru 隨機圖片搜尋（依頻道 NSFW 旗標開放分級）
│   ├── music.py           # YouTube 音樂播放、佇列與互動控制
│   ├── earthquake.py      # 中央氣象署地震資訊查詢
│   ├── ptt.py             # PTT 文章抓取（內文解析、推噓統計、分頁推文、刪文時自動改抓 pttweb.cc 備份）
│   ├── task.py            # 定時任務（每日隨機標人 + 排行榜）
│   ├── info.py            # 機器人系統資訊面板（含即時重新整理）
│   ├── help.py            # 互動式翻頁指令說明手冊
│   ├── react.py           # 代理發話、訊息清除、趣味回覆
│   ├── main.py            # 基本指令（延遲測試、追番連結）
│   └── event.py           # 訊息監聽與自動回覆
├── services/              # 🌐 服務層：封裝業務邏輯與外部 API
│   ├── ai_service.py      # AI 供應商封裝（OpenRouter / Groq 雙引擎）
│   ├── music_cache.py     # yt-dlp 下載快取、容量與自動清理
│   ├── music_service.py   # 語音連線、播放佇列與空頻道離開
│   ├── earthquake_api.py  # 中央氣象署地震 API（並行抓取 + 60 秒快取）
│   └── database.py        # SQLite 資料庫封裝 (PingDatabase)
├── utils/                 # 🔧 工具層：跨模組通用工具
│   ├── constants.py       # 顏色、Emoji、URL、System Prompt 等常數
│   ├── time_helper.py     # 時區轉換 (Asia/Taipei) 與時間格式化
│   ├── embed_builder.py   # 進度條生成與超長訊息分段發送
│   └── validators.py      # 管理員權限檢查 (is_manager)
├── views/                 # 🖱️ UI 層：Discord 互動元件
│   ├── music.py           # 音樂控制面板、播放清單確認與待播分頁
│   └── pagination.py      # 通用分頁組件 (⏪◀ 頁碼 ▶⏩)
├── logs/                  # 📝 日誌層：自動旋轉日誌系統
│   └── __init__.py        # setup_logging()：Console + 檔案雙輸出
└── data/                  # 💾 資料層：SQLite 資料庫檔案
    └── ping_count.db      # 每日隨機標記次數統計
```

---

## 🛠️ 指令全清單

### 🎵 音樂播放

| 指令 | 參數 | 說明 | 類型 | 權限 |
| :--- | :--- | :--- | :--- | :--- |
| `/play` | `url` | 加入 YouTube 影片；播放清單會先詢問加入整份、只加入目前影片或取消 | Slash | 使用者 |
| `/playnext` | `url` | 將影片插入目前歌曲之後，不中斷正在播放的歌曲 | Slash | 使用者 |
| `/queue` | - | 顯示目前伺服器的待播清單（暫時回覆） | Slash | 使用者 |
| `/leave` | - | 停止播放、清空待播清單並讓機器人離開語音頻道 | Slash | 使用者 |
| `/musiccache` | `action` | `status` 查看快取；`clear` 手動清理快取（僅機器人擁有者） | Slash | 機器人擁有者 |

播放中的 Embed 會附上暫停／繼續、停止、跳過與待播清單按鈕。停止只會清空播放與待播清單，機器人仍留在語音頻道；`/leave` 才會離開。當語音頻道沒有真人成員時，機器人會等待 `empty_channel_grace_seconds` 秒，若期間有人回來就取消離開計時。

目前播放採先下載到本機再交給 FFmpeg，因此第一首歌需要等待下載；不支援直播。YouTube 的驗證、限流或 PO Token 變更也可能使 yt-dlp 無法擷取特定網址。

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
| `/ptt` | `url` | 抓取 PTT 文章內文、推噓統計，支援推文分頁瀏覽與完整內文下載；原文被刪除 (404) 時自動改抓 pttweb.cc 備份 | Slash | 使用者 |

### 🎨 Danbooru 圖片

| 指令 | 參數 | 說明 | 類型 | 權限 |
| :--- | :--- | :--- | :--- | :--- |
| `/danbooru` | `tag` `[rating]` | 隨機搜尋 Danbooru 圖片（單一 tag，最多 5 張，每人 8 秒冷卻）；預設 General，Sensitive/Questionable/Explicit 分級僅限 NSFW 頻道或私訊 | Slash | 使用者 |

### ⏰ 社群互動

| 指令 | 參數 | 說明 | 類型 | 權限 |
| :--- | :--- | :--- | :--- | :--- |
| `/ping_count` | `[member]` | 查詢被「每日隨機標」選中的累計次數 | Hybrid | 使用者 |
| `/ping_rank` | `[top]` | 查看隨機標排行榜與所有人的標記總數（預設前 10，最多 25） | Hybrid | 使用者 |
| `/ping_stats` | `[member]` | 查看成員被標記次數、佔總數的百分比及上次被標記時間（預設查詢自己） | Hybrid | 使用者 |
| `/test_daily` | - | 手動觸發一次每日隨機標（測試用） | Hybrid | 管理員 |

標記總數是所有成員累計被標記次數的加總，不受排行榜顯示名次限制。`/ping_stats @成員`（或 `!ping_stats @成員`）的比例以「個人被標記次數 ÷ 標記總數 × 100%」計算，顯示至小數點後兩位；尚無標記時顯示 `0.00%`。上次被標記時間會依 Discord 使用者的時區顯示，並附上距今多久。

舊資料庫會在啟動時自動更新並保留累計次數。舊紀錄沒有時間資訊，會顯示「尚無時間紀錄」，直到該成員再次被標記；從未被標記的成員則顯示「尚未被標記」。每日排程與 `/test_daily` 都只在標記訊息成功送出後更新次數和時間。

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
| `OPENROUTER_MODEL` | OpenRouter 使用的語言模型名稱；`openrouter/free` 會自動路由 | `openrouter/free` |
| `GROQ_MODEL` | Groq 使用的語言模型名稱 | `moonshotai/kimi-k2-instruct-0905` |

音樂設定放在 `MUSIC` 物件內（完整範例見 `setting.json.example`）。設定在啟動時讀取，修改後請重啟機器人。

| 欄位 | 說明 | 預設值 |
| :--- | :--- | :--- |
| `cache_dir` | 音檔快取目錄；Docker 會隨 `/app/data` volume 持久化 | `data/music` |
| `max_cache_mb` | 快取容量上限；下載前預留單檔上限的空間，自動清理開啟時淘汰最久未使用的音檔，仍不足則拒絕下載 | `1024` |
| `max_file_mb` | 單一音檔大小上限 | `100` |
| `max_duration_seconds` | 單曲最長秒數 | `1800` |
| `max_queue_size` | 每個伺服器的待播歌曲數上限 | `100` |
| `max_playlist_items` | 一次接受的播放清單歌曲數上限 | `50` |
| `empty_channel_grace_seconds` | 沒有真人成員時離開前的等待秒數 | `10` |
| `auto_cleanup` | 是否啟用週期性 TTL／LRU 自動清理 | `true` |
| `cache_ttl_hours` | 自動清理時，未釘選音檔的保存時間 | `168` |
| `cleanup_interval_seconds` | 自動清理檢查間隔 | `600` |
| `download_timeout_seconds` | yt-dlp 單次下載逾時秒數 | `300` |
| `ffmpeg_executable` | FFmpeg 執行檔名稱或完整路徑 | `ffmpeg` |
| `js_runtime` | yt-dlp JavaScript runtime | `deno` |
| `cookies_file` | Netscape 格式 cookies 檔路徑，相對路徑以專案根目錄為準；`null` 不使用 cookies | `null` |
| `allow_ytdlp_plugins` | 載入已安裝的 yt-dlp 外掛，PO Token provider 需要開啟 | `false` |
| `youtube_player_client` | 指定 YouTube client，例如 `mweb`；`null` 使用 yt-dlp 預設 | `null` |
| `pot_provider_url` | bgutil HTTP provider 位址；須另外安裝外掛與啟動服務 | `null` |

快取檔案會跨重啟保留，伺服器的待播清單只存在記憶體中，重啟後會清空。`auto_cleanup=false` 時檔案會保留到擁有者執行 `/musiccache clear`，空間不足就拒絕新下載；手動清理會跳過目前播放、下載中或預載保留的檔案。請使用專用的 `cache_dir`，勿混放其他音檔。

下載前會預留 `max_file_mb` 的空間，因此剩餘容量不足此值時，即使新歌曲較小也可能被拒絕。下載中每 0.25 秒檢查音檔與總容量，超限便終止下載並清除未完成檔案；檢查間隔內可能短暫超出上限。`max_file_mb` 不可大於 `max_cache_mb`。

### YouTube 403、cookies 與 PO Token

cookies 提供登入身分，不保證解除所有 403。若錯誤要求登入，可嘗試 cookies；若已取得歌曲資訊但在下載媒體時出現 403，PO Token 是可能原因之一，仍需查看錯誤上下文。先確認部署中的 yt-dlp 與 JavaScript runtime 正常；本專案使用 lockfile，更新主機套件不會自動更新既有 Docker image。

**設定 cookies：** 依 [yt-dlp 的 YouTube 匯出說明](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies) 匯出 Netscape 格式的 YouTube cookies。官方的無痕視窗流程是登入後，在同一分頁開啟 `https://www.youtube.com/robots.txt`，匯出該工作階段的 YouTube cookies，再關閉無痕視窗；勿再開啟該工作階段。格式要求見 [官方 FAQ](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp)。

將檔案存為 `secrets/youtube.cookies.txt`，並在現有 `setting.json` 的 `MUSIC` 物件加入：

```json
"cookies_file": "secrets/youtube.cookies.txt"
```

Docker 部署改用容器內路徑 `"cookies_file": "/run/secrets/youtube_cookies"`，搭配本專案的可選 Compose 設定：

```bash
docker compose -f docker-compose.yml -f docker-compose.cookies.yml up -d --build
```

請先建立實際 cookies 檔，並確認非 root 的 bot 使用者有讀取權限。此檔以唯讀方式掛載，程式會為每次資訊查詢／下載建立獨立的可寫暫存副本，結束或取消後刪除；原始匯出檔不會被 yt-dlp 改寫。替換 cookies 後下一次請求便會讀取新內容，修改設定路徑則需重啟。

`secrets/`、`cookies.txt`、`*.cookies.txt` 已排除於 Git／Docker build。cookies 是登入憑證，請勿貼到 Discord、提交至 Git 或放進 image；機器人的點播會共用此帳號能存取的內容。官方也提醒用帳號下載可能受到帳號限制，請只在需要時啟用。

**是否需要 PO Token server：** 不一定。[官方 PO Token 指引](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide) 建議需要 token 時使用 provider 外掛搭配 `mweb`，避免手動維護逐影片的 token。[bgutil provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider#setup) 同時提供常駐 HTTP server 與按需執行的 script；常駐 bot 可考慮 HTTP 模式，低流量也可使用 script。

這次改動提供設定介面，沒有自動安裝 provider 或啟動額外服務。若確認採用 bgutil HTTP 模式，先依其文件部署服務，並在 bot 的 Python 環境安裝 provider（uv 專案可用 `uv add bgutil-ytdlp-pot-provider`，Docker 需重建 image），再設定：

```json
"allow_ytdlp_plugins": true,
"youtube_player_client": "mweb",
"pot_provider_url": "http://bgutil-provider:4416"
```

上例假設 provider 與 bot 位於同一個 Docker 網路，服務名稱為 `bgutil-provider`；本機執行可用 `http://127.0.0.1:4416`。不要在 bot 容器中用 `127.0.0.1` 指向另一個容器。只需內部網路連線，無須公開 provider port。script 模式可使用 provider 文件中的預設安裝路徑，並讓 `pot_provider_url` 保持 `null`。

預設保留 `--ignore-config` 與停用外掛；只有 `allow_ytdlp_plugins=true` 才會移除 `--no-plugin-dirs`。只安裝 provider、只啟動 server，或只修改系統的 yt-dlp 設定檔，都不足以讓目前 bot 使用 PO Token。這些設定可與 cookies 分別或一起使用，仍不能保證解決 IP 限流或所有 YouTube 驗證問題。

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

映像檔以 Debian Bookworm 為基礎，內含 FFmpeg（同時提供 `ffmpeg` 與 `ffprobe`）以及固定版本的官方 Deno binary。音樂檔會寫入 `./data/music`，請把這個目錄視為持久化資料並預留足夠空間。

### 💻 方式二：傳統本機部署

1.  **環境準備**：建議使用 Python 3.12 以上版本，並安裝 [uv](https://docs.astral.sh/uv/) 套件管理工具。
    - `ffmpeg` 與 `ffprobe` 必須在 `PATH` 中（或在 `MUSIC.ffmpeg_executable` 指定完整路徑）。
    - 建議安裝 [Deno](https://docs.deno.com/runtime/) 並讓 `deno` 在 `PATH` 中，供 yt-dlp 的 YouTube JavaScript challenge 解譯使用。
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

### 🔐 Discord 權限與 Intent

機器人在文字頻道需要 `View Channel`、`Send Messages` 與 `Embed Links`；在語音頻道需要 `View Channel`、`Connect` 與 `Speak`。請在 Bot 設定與程式的 intents 中保留 `voice_states`（這是 discord.py 的預設 intent），否則無法偵測空頻道並在無人時離開。

---

## 📈 技術棧

| 類別 | 技術 | 用途 |
| :--- | :--- | :--- |
| **框架** | `discord.py` | 非同步 Discord API 封裝 |
| **HTTP 請求** | `aiohttp` | 高性能非同步 API 通訊 |
| **AI 供應商** | OpenRouter / Groq | 雙引擎 AI 對話服務 |
| **AI SDK** | `groq` | Groq 官方 Python SDK |
| **網頁解析** | `beautifulsoup4` + `lxml` | PTT 文章 HTML 解析 |
| **音樂擷取** | `yt-dlp[default]` | YouTube 音訊下載與 metadata 擷取 |
| **音訊播放** | FFmpeg + `discord.py[voice]` | 語音頻道播放與 Opus 處理 |
| **JavaScript runtime** | Deno | yt-dlp YouTube challenge 解譯 |
| **環境變數** | `python-dotenv` | `.env` 檔讀取 |
| **系統監控** | `psutil` | 顯示 CPU / 記憶體等資源佔用 |
| **資料庫** | `sqlite3` | 輕量級本地資料持久化 |
| **時區處理** | `zoneinfo` + `tzdata` | Asia/Taipei 時區支援 |
| **套件管理** | `uv` | 快速 Python 依賴管理 |
| **部署** | Docker + Docker Compose | 容器化部署方案 |

---

## 🧪 開發工具

```bash
uv sync --locked --dev       # 依 uv.lock 安裝依賴與開發工具；鎖定檔過期時會失敗
uv run --locked ruff check . # Lint（規則見 pyproject.toml [tool.ruff]）
SETTING_PATH=setting.json.example uv run --locked pytest # 使用範例設定執行單元測試
```

### GitHub Actions CI

[CI 工作流程](.github/workflows/ci.yml) 會在推送 `main`、建立或更新 Pull Request 時執行，也可從 GitHub Actions 頁面手動觸發。執行環境為 Ubuntu，Python 版本依 `.python-version`（目前為 3.12），透過固定版本的 uv 安裝 `uv.lock` 中的依賴，再依序執行 Ruff 與 pytest。相同事件與分支的新執行會取消尚未完成的舊執行。

CI 透過 `SETTING_PATH` 讀取已納入版本控制的 `setting.json.example`，不需要設定 Discord Token、API Key、`.env` 或建立 `setting.json`，也不會啟動機器人。這些單元測試不代表已驗證實際 Discord 連線或 YouTube 下載。

將此工作流程推送至 GitHub 並成功執行一次後，可在 `main` 的 Ruleset 啟用 **Require status checks to pass**，加入檢查名稱 **`test`**（工作流程名稱為 `CI`），並啟用 **Require branches to be up to date before merging**。Ruff 或 pytest 任一失敗，`test` 就不會通過。必要檢查須另外在 GitHub 設定；新增此檔案不會自動修改 Ruleset。

---

> [!TIP]
> **維護日誌**：機器人運行過程中，所有 `ERROR` 與 `INFO` 等級的事件會同步記錄在 `logs/bot.log` 中。檔案達到 5MB 時會自動循環備份（保留 3 份），確保存放空間不爆炸。
