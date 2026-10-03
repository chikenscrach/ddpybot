# Owner Dashboard

Owner Dashboard 與 Bot 共用同一個 Python 程序，透過 `aiohttp` 提供 Web UI，不需要額外 Node.js runtime。

## 功能

Dashboard 目前提供：

- **總覽**：Gateway 延遲、CPU、記憶體、運行時間、伺服器、已載入模組與音樂快取。
- **Ping 分析**：依台北時間篩選日期、伺服器與來源，顯示圖表、區間排行、歷來排行、最近事件與 CSV 匯出。
- **音樂控制**：查看目前歌曲與佇列，執行暫停、繼續、跳過、停止、離開及循環切換。
- **設定**：修改每日頻道、管理員、AI provider / model 與 MUSIC 設定。

## 權限與安全

- 透過 Discord OAuth2 登入。
- 只允許此 Bot 應用程式的 owner；團隊應用只接受 team owner。
- `moderator_ids`、Discord 伺服器管理員及其他團隊成員不會因其身分取得 Dashboard 權限。
- 所有資料 API 都要求登入。
- 寫入操作另驗證 Origin 與 CSRF token。
- Token / API Key 不會透過設定 API 回傳到前端。
- 修改設定前會檢查版本，避免以過期頁面覆蓋其他修改。
- 設定以原子方式寫入。

Dashboard 登入有效時間為 8 小時；登出或 Bot 重啟後需重新登入。需要高權限操作時會重新確認 owner 身分。

## 本機啟用

先在 Discord Developer Portal 的 OAuth2 Redirects 登記精確 callback，例如：

```text
http://127.0.0.1:8080/auth/callback
```

`.env`：

```dotenv
DASHBOARD_ENABLED=true
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8080
DASHBOARD_PUBLIC_URL=http://127.0.0.1:8080
DASHBOARD_CLIENT_ID=你的應用程式ID
DASHBOARD_CLIENT_SECRET=你的OAuth2ClientSecret
```

外部公開時 `DASHBOARD_PUBLIC_URL` 必須使用 HTTPS；HTTP 只允許 localhost / loopback。Public URL 應指向網域根目錄，不要包含子路徑。

啟動：

```bash
uv run python main.py
```

## Docker 啟用

Dashboard 的設定寫入需要可寫設定檔。可先準備：

```bash
mkdir -p data/config
cp -n setting.json data/config/setting.json
docker compose build
docker compose run --rm --no-deps --user root --entrypoint sh discord-bot -c   'chown botuser:botuser /app/data/config /app/data/config/setting.json && chmod 700 /app/data/config && chmod 600 /app/data/config/setting.json'
```

啟動：

```bash
docker compose -f docker-compose.yml -f docker-compose.dashboard.yml up -d --build
```

啟用 overlay 後，實際設定來源為：

```text
data/config/setting.json
```

容器內則由 `SETTING_PATH=/app/data/config/setting.json` 指向該檔案。

公開網域建議由宿主機 HTTPS reverse proxy 轉送至 `127.0.0.1:8080`。若反向代理也在 Docker 中，應透過共同網路使用 `discord-bot:8080`，不要使用另一個容器自己的 `127.0.0.1`。

設定頁寫入後，重啟 Bot 才套用需要重新載入的設定：

```bash
docker compose -f docker-compose.yml -f docker-compose.dashboard.yml restart discord-bot
```

若修改 OAuth2 等環境變數，應重新建立容器。

## 測試

後端測試涵蓋 owner 驗證、CSRF、設定版本衝突、原子寫入、SQLite migration、台北日期邊界、HTTP API 與音樂工作階段控制。

瀏覽器測試使用 `scripts/test_dashboard_ui.py` 與固定 API 資料驗證桌面／手機版 UI；這不代表已驗證真實 Discord OAuth2、Discord 語音或 YouTube 下載。

```bash
uv run --no-project --with playwright==1.63.0 python -m playwright install chromium
uv run --no-sync python scripts/serve_dashboard_ui.py
uv run --no-project --with playwright==1.63.0 python scripts/test_dashboard_ui.py
```
