# 部署指南

DDPYBOT 支援 Docker Compose 與傳統本機執行。

## Docker（推薦）

需求：

- Docker
- Docker Compose

建立設定：

```bash
cp .env.example .env
cp setting.json.example setting.json
```

填入至少 `TOKEN` 後啟動：

```bash
docker compose up -d --build
```

預設 Compose 會使用本地 `Dockerfile` 建置 image，並將資料與日誌持久化到專案目錄。

映像以 Debian Bookworm 為基礎，包含 FFmpeg、ffprobe 與固定版本 Deno。音樂檔預設保存於 `./data/music`，部署前應預留足夠空間。

### 可選 overlay

Dashboard：

```bash
docker compose -f docker-compose.yml -f docker-compose.dashboard.yml up -d --build
```

YouTube cookies：

```bash
docker compose -f docker-compose.yml -f docker-compose.cookies.yml up -d --build
```

兩者可依需要同時加入。

## 本機執行

建議環境：

- Python 3.12（專案宣告最低 Python 3.10）
- uv
- FFmpeg / ffprobe
- Deno（供 yt-dlp YouTube JavaScript challenge 使用）

安裝：

```bash
uv sync
```

設定：

```bash
cp .env.example .env
cp setting.json.example setting.json
```

啟動：

```bash
uv run python main.py
```

若不使用 uv，也可自行建立 virtualenv 並安裝相依套件；正式開發與 CI 仍以 `uv.lock` 為主要依賴鎖定來源。

## Discord 權限

文字頻道至少需要：

- View Channel
- Send Messages
- Embed Links

語音頻道至少需要：

- View Channel
- Connect
- Speak

程式 intents 應保留 `voice_states`，否則無法正確偵測空語音頻道並自動離開。

## 部署後檢查

1. Bot 是否成功登入 Discord。
2. Slash commands 是否已同步。
3. `/ping` 與 `/botinfo` 是否正常。
4. 使用音樂功能時 FFmpeg、Deno 與 yt-dlp 是否可用。
5. `data/` 與 `logs/` 是否具備正確寫入權限。
6. 若啟用 Dashboard，OAuth2 Redirect URL 與 `DASHBOARD_PUBLIC_URL` 是否完全一致。
