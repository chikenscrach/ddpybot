# 設定指南

DDPYBOT 將敏感資訊與一般設定分開：

- `.env`：Token、API Key、OAuth2 Secret。
- `setting.json`：頻道、管理員、AI 模型與音樂設定。

請分別由範例檔建立：

```bash
cp .env.example .env
cp setting.json.example setting.json
```

## .env

| 變數 | 用途 | 必要性 |
| --- | --- | --- |
| `TOKEN` | Discord Bot Token | 必要 |
| `OPENROUTER_API_KEY` | OpenRouter API Key | 使用 OpenRouter 時必要 |
| `GROQ_API_KEY` | Groq API Key | 使用 Groq 時必要 |
| `CWA_API_KEY` | 中央氣象署 API Key | 使用地震功能時必要 |
| `DASHBOARD_ENABLED` | 啟用 Owner Dashboard | 預設 `false` |
| `DASHBOARD_HOST` | Dashboard 綁定介面 | 預設 `127.0.0.1` |
| `DASHBOARD_PORT` | Dashboard 連接埠 | 預設 `8080` |
| `DASHBOARD_PUBLIC_URL` | OAuth2 對外基準網址 | Dashboard 啟用時必要 |
| `DASHBOARD_CLIENT_ID` | Discord OAuth2 Client ID | Dashboard 啟用時必要 |
| `DASHBOARD_CLIENT_SECRET` | Discord OAuth2 Client Secret | Dashboard 啟用時必要 |

不要提交 `.env`。Client Secret 與 Bot Token 是不同憑證。

## setting.json

| 欄位 | 說明 | 範例／預設 |
| --- | --- | --- |
| `DAILY_CHANNEL_ID` | 每日隨機標記的目標頻道 | 依伺服器設定 |
| `moderator_ids` | Bot 管理員 Discord User ID 清單 | `[]` |
| `AI_PROVIDER` | `openrouter` 或 `groq` | `openrouter` |
| `OPENROUTER_MODEL` | OpenRouter 模型 | `openrouter/free` |
| `GROQ_MODEL` | Groq 模型 | `moonshotai/kimi-k2-instruct-0905` |

設定於啟動時載入；修改後通常需要重啟 Bot。

## MUSIC

| 欄位 | 說明 | 預設 |
| --- | --- | --- |
| `cache_dir` | 音檔快取目錄 | `data/music` |
| `max_cache_mb` | 快取總容量上限 | `1024` |
| `max_file_mb` | 單一音檔大小上限 | `100` |
| `max_duration_seconds` | 單曲最長秒數 | `1800` |
| `max_queue_size` | 每伺服器待播數上限 | `100` |
| `max_playlist_items` | 單次播放清單最大項目數 | `50` |
| `empty_channel_grace_seconds` | 無真人時離開前等待秒數 | `10` |
| `auto_cleanup` | 啟用 TTL/LRU 自動清理 | `true` |
| `cache_ttl_hours` | 未使用音檔保存時間 | `168` |
| `cleanup_interval_seconds` | 自動清理間隔 | `600` |
| `download_timeout_seconds` | yt-dlp 下載逾時 | `300` |
| `ffmpeg_executable` | FFmpeg 指令或完整路徑 | `ffmpeg` |
| `js_runtime` | yt-dlp JavaScript runtime | `deno` |
| `cookies_file` | Netscape cookies 檔案路徑 | `null` |
| `allow_ytdlp_plugins` | 允許載入 yt-dlp 外掛 | `false` |
| `youtube_player_client` | 指定 YouTube player client | `null` |
| `pot_provider_url` | bgutil HTTP provider URL | `null` |

`max_file_mb` 不應大於 `max_cache_mb`。快取目錄應專用於本 Bot，避免自動清理誤刪其他檔案。

進一步的下載、cookies 與 PO Token 說明請見 [音樂與 YouTube](Music-and-YouTube.md)。
