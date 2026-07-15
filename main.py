import logging
import signal
from pathlib import Path

import discord
from discord.ext import commands

from core.config import TOKEN
from logs import setup_logging

# ── 初始化日誌（console + logs/bot.log 自動旋轉）──
setup_logging()
log = logging.getLogger(__name__)

CMDS_DIR = Path(__file__).resolve().parent / 'cmds'

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class DDBot(commands.Bot):
    async def setup_hook(self):
        # 逐個載入，單一 cog 失敗不影響其他模組
        for file in sorted(CMDS_DIR.glob('*.py')):
            if file.name.startswith('_'):
                continue
            try:
                await self.load_extension(f'cmds.{file.stem}')
                log.info('✅ 已載入: %s', file.stem)
            except Exception:
                log.exception('❌ 載入失敗: %s', file.stem)

        # ✅ 只在啟動時同步一次斜線指令，
        # 避免 on_ready 重連時重複同步觸發速率限制
        synced = await self.tree.sync()
        log.info('🔄 已同步 %d 個斜線指令', len(synced))


bot = DDBot(
    command_prefix=['!', '！'],
    intents=intents,
    help_command=None,  # ← 改由自訂的 Help cog 處理
    # 預設不觸發任何提及，防止 !say 之類的指令被拿來 @everyone
    allowed_mentions=discord.AllowedMentions.none(),
)


@bot.event
async def on_ready():
    log.info('>> Bot is online <<')
    game = discord.Game('你婆真好用')
    await bot.change_presence(status=discord.Status.idle, activity=game)


@bot.command()
@commands.is_owner()  # 只有 Bot 擁有者能用
async def load(ctx, extension):
    await bot.load_extension(f'cmds.{extension}')
    await ctx.send(f'✅ Loaded `{extension}` done.')

@bot.command()
@commands.is_owner()
async def unload(ctx, extension):
    await bot.unload_extension(f'cmds.{extension}')
    await ctx.send(f'✅ Unloaded `{extension}` done.')

@bot.command()
@commands.is_owner()
async def reload(ctx, extension):
    await bot.reload_extension(f'cmds.{extension}')
    await ctx.send(f'✅ Reloaded `{extension}` done.')

@bot.command()
@commands.is_owner()
async def sync(ctx):
    """reload 之後若斜線指令有變動，用這個手動同步"""
    synced = await bot.tree.sync()
    await ctx.send(f'🔄 已同步 {len(synced)} 個斜線指令')


def _handle_sigterm(signum, frame):
    # docker stop / systemd 會送 SIGTERM；轉成 KeyboardInterrupt 讓 discord.py
    # 走既有的優雅關閉流程（close() 會逐一卸載 cogs，觸發 cog_unload 清理資源）
    raise KeyboardInterrupt


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit('未設定 TOKEN，請複製 .env.example 為 .env 並填入 Discord Bot Token。')
    signal.signal(signal.SIGTERM, _handle_sigterm)
    # 日誌已由 setup_logging() 統一設定，關閉 discord.py 內建 handler 避免重複輸出
    bot.run(TOKEN, log_handler=None)
