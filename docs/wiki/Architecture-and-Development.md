# 架構與開發

## 分層架構

DDPYBOT 以功能職責拆分：

```text
ddpybot/
├── main.py            # Bot 啟動、Cog 載入、指令同步
├── core/              # 基底類別與設定載入
├── cmds/              # Discord 指令與事件 Cogs
├── services/          # 外部 API、AI、音樂、資料庫等服務
├── utils/             # 共用常數、驗證、時間與 Embed 工具
├── views/             # Discord 互動元件與分頁
├── dashboard/         # Owner Dashboard
├── logs/              # Logging 初始化
├── scripts/           # 維護與 Dashboard UI 測試腳本
├── tests/             # pytest
└── data/              # SQLite 與音樂快取等持久化資料
```

設計原則是讓 Discord UI、業務邏輯、外部服務與資料存取分離，避免單一 Cog 同時承擔所有責任。

## 主要技術

| 類別 | 技術 |
| --- | --- |
| Discord | `discord.py[voice]` |
| HTTP | `aiohttp` |
| AI | OpenRouter / Groq |
| HTML | BeautifulSoup + lxml |
| YouTube | `yt-dlp[default]` |
| Audio | FFmpeg |
| JS runtime | Deno |
| Database | SQLite |
| System metrics | psutil |
| Timezone | zoneinfo + tzdata |
| Package manager | uv |
| Deployment | Docker + Docker Compose |

## 開發環境

依 lockfile 安裝：

```bash
uv sync --locked --dev
```

Lint：

```bash
uv run --locked ruff check .
```

Test：

```bash
SETTING_PATH=setting.json.example uv run --locked pytest
```

測試使用版本控制中的 `setting.json.example`，不需要真實 Discord Token、API Key 或 `.env`，也不會啟動 Bot。

## GitHub Actions

`.github/workflows/ci.yml` 會在推送 `main`、建立或更新 Pull Request 時執行，也可手動觸發。

CI 使用：

- Ubuntu runner。
- `.python-version` 指定的 Python。
- 固定版本 uv。
- `uv.lock`。
- Ruff。
- pytest。

相同事件與分支的新執行會取消尚未完成的舊執行。

若要保護 `main`，可在 Ruleset 將 CI 的 `test` status check 設為 required，並要求分支在合併前保持最新。

## Dashboard UI 測試

正式前端的固定資料瀏覽器測試：

```bash
uv run --no-project --with playwright==1.63.0 python -m playwright install chromium
uv run --no-sync python scripts/serve_dashboard_ui.py
uv run --no-project --with playwright==1.63.0 python scripts/test_dashboard_ui.py
```

這類測試驗證 UI 狀態與 API 互動，不等同真實 OAuth2、語音或 YouTube 端到端測試。

## Logging

Bot 會將 Console 與檔案日誌集中處理。主要記錄檔：

```text
logs/bot.log
```

檔案達到約 5 MB 時循環備份並保留有限份數，避免日誌無限制成長。

## 修改設定與資料

- `.env`：敏感資訊，不進版控。
- `setting.json`：執行環境的一般設定，不應用範例值覆蓋既有部署設定。
- `setting.json.example`：可提交的設定結構範例。
- `data/`：執行期資料，部署時應持久化並備份重要 SQLite 檔案。
