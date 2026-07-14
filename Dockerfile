# ========== 階段 1：用 uv 安裝依賴 ==========
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev


# ========== 階段 2：正式執行環境 ==========
FROM python:3.12-slim

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
