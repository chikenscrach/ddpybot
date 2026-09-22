# Deno 的官方 binary image 只提供執行檔，方便沿用 Python 的 Bookworm runtime。
# 版本固定，避免 yt-dlp 的 JavaScript runtime 隨 latest tag 漂移。
FROM ghcr.io/denoland/deno:bin-2.9.7 AS deno

# ========== 階段 1：用 uv 安裝依賴 ==========
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev


# ========== 階段 2：正式執行環境 ==========
FROM python:3.12-slim-bookworm

# discord.py 透過 FFmpeg 播放語音；Debian 的 ffmpeg 套件同時提供
# ffmpeg 與 ffprobe。yt-dlp 的 JavaScript challenge 解譯使用 Deno。
RUN apt-get update && \
    apt-get install --no-install-recommends --yes ffmpeg ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY --from=deno /deno /usr/local/bin/deno

# 建立非 root 使用者
RUN groupadd -r botuser && useradd -r -g botuser -m botuser

WORKDIR /app

# 複製已建好的虛擬環境
COPY --from=builder /app/.venv /app/.venv

# 複製原始碼（.dockerignore 會排除敏感檔案）
COPY . .

# 建立 data/ 和 logs/ 資料夾，並設定權限
# （這兩個資料夾被 .dockerignore 排除了，所以要手動建立）
RUN mkdir -p /app/data /app/logs && \
    chown -R botuser:botuser /app

# 宣告 volume 掛載點
VOLUME ["/app/data", "/app/logs"]

# 切換到非 root 使用者
USER botuser

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "main.py"]
