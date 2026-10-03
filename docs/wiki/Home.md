# DDPYBOT 文件

本目錄整理 DDPYBOT 的操作、設定、部署與開發文件。README 只保留專案入口資訊，細節依用途分頁維護。

## 文件分類

| 分類 | 說明 |
| --- | --- |
| [指令參考](Commands.md) | 使用者、管理員與 Bot owner 可用指令 |
| [設定指南](Configuration.md) | 環境變數、一般設定與音樂參數 |
| [音樂與 YouTube](Music-and-YouTube.md) | 播放流程、快取、403、cookies 與 PO Token |
| [Owner Dashboard](Dashboard.md) | OAuth2、頁面功能、設定寫入與 Docker 啟用 |
| [部署指南](Deployment.md) | Docker、本機部署、Discord 權限與 Intent |
| [架構與開發](Architecture-and-Development.md) | 分層架構、技術棧、測試、CI 與日誌 |

## 功能概覽

DDPYBOT 目前包含：

- AI 對話：OpenRouter / Groq。
- YouTube 音樂播放與本機快取。
- 中央氣象署地震資訊。
- PTT 文章抓取與備份來源切換。
- Danbooru 圖片搜尋。
- 每日隨機標記、排行榜與統計。
- Discord 互動式 Views 與資訊面板。
- Bot owner 專用 Web Dashboard。

## 文件維護原則

- README：只放專案定位、核心功能、快速開始與文件入口。
- Wiki：放完整指令、設定、部署、疑難排解與開發細節。
- 範例值以 `.env.example`、`setting.json.example` 與實際程式碼為準。
- 敏感資訊不得提交至 Git。
