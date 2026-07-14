# ──────────────────────────────────────────────
#  統一 Embed 樣式工具
# ──────────────────────────────────────────────


def progress_bar(ratio: float, length: int = 10) -> str:
    """產生文字進度條  █████░░░░░"""
    filled = round(ratio * length)
    return "█" * filled + "░" * (length - filled)


async def send_long_message(ctx, text: str):
    """超過 2000 字自動分段發送（Discord 單則訊息上限）"""
    while len(text) > 2000:
        split_pos = text[:2000].rfind('\n')
        if split_pos == -1:
            split_pos = 2000
        await ctx.send(text[:split_pos])
        text = text[split_pos:]
    if text:
        await ctx.send(text)
