# 音樂與 YouTube

## 播放模型

目前音樂功能會先由 yt-dlp 將音訊下載到本機，再交給 FFmpeg 播放，因此首次播放需要等待下載完成；不支援直播。

主要行為：

- 每個 Discord 伺服器有獨立佇列與循環狀態。
- `queue` 循環會把播完的歌曲放回佇列尾端。
- `track` 循環只重播目前歌曲。
- 跳過會直接前往下一首，不會因單曲循環而重播被跳過的歌曲。
- 停止會清空播放與佇列並關閉循環，但 Bot 仍留在語音頻道。
- `/leave` 會離開語音頻道並重設播放狀態。
- 語音頻道沒有真人成員時，會等待 `empty_channel_grace_seconds` 後離開；期間有人返回則取消離開計時。

## 快取

音檔會保存在 `MUSIC.cache_dir`。Docker 預設透過 `/app/data` 持久化。

- `auto_cleanup=true`：依 TTL / LRU 清理未使用檔案。
- `auto_cleanup=false`：檔案保留到手動清理；空間不足時拒絕新下載。
- 手動清理會避開目前播放、下載中或預載保留的檔案。
- 下載前會依 `max_file_mb` 預留空間，因此剩餘容量不足時可能在真正下載前就被拒絕。

## YouTube 403

403 不一定只有一種原因。常見方向：

1. yt-dlp 或 YouTube extractor 行為變更。
2. JavaScript challenge runtime 不可用。
3. 登入驗證，需要 cookies。
4. PO Token 要求。
5. IP / 帳號限流。

本專案使用 lockfile；更新宿主機套件不會自動改變既有 Docker image 內的版本，必要時需重新 build。

## cookies

cookies 用來提供登入身分，但不能保證解決所有 403。

依 yt-dlp 官方文件匯出 Netscape 格式的 YouTube cookies，建議使用獨立工作階段。範例路徑：

```text
secrets/youtube.cookies.txt
```

一般執行：

```json
{
  "MUSIC": {
    "cookies_file": "secrets/youtube.cookies.txt"
  }
}
```

Docker 建議使用容器內秘密檔路徑：

```json
{
  "MUSIC": {
    "cookies_file": "/run/secrets/youtube_cookies"
  }
}
```

並啟動 cookies overlay：

```bash
docker compose -f docker-compose.yml -f docker-compose.cookies.yml up -d --build
```

`secrets/`、`cookies.txt` 與 `*.cookies.txt` 應保持在 Git / Docker build 排除清單中。cookies 等同登入憑證，不要貼到 Discord、提交至 Git 或打包進 image。

## PO Token / bgutil provider

只有在實際錯誤情境需要時才啟用。若使用 bgutil HTTP provider，先依 provider 文件部署服務並安裝 yt-dlp provider 外掛，再設定：

```json
{
  "MUSIC": {
    "allow_ytdlp_plugins": true,
    "youtube_player_client": "mweb",
    "pot_provider_url": "http://bgutil-provider:4416"
  }
}
```

若 provider 與 Bot 是不同容器，Bot 容器內不能用 `127.0.0.1` 指向 provider；應使用共同 Docker 網路中的服務名稱。

本專案預設停用外掛。只安裝 provider、只啟動 server 或只修改系統 yt-dlp 設定檔，都不代表 Bot 已啟用 PO Token。

## 相關文件

- yt-dlp YouTube extractor / cookies 文件
- yt-dlp FAQ
- yt-dlp PO Token Guide
- bgutil-ytdlp-pot-provider

實際排錯時應優先依錯誤訊息判斷原因，不要把 cookies 或 PO Token 當成所有下載問題的固定解法。
