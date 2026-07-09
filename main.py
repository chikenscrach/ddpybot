import logging
import os

import discord
from discord.ext import commands

from core.config import settings

log = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class DDBot(commands.Bot):
    async def setup_hook(self):
        for filename in os.listdir('./cmds'):
            if filename.endswith('.py') and not filename.startswith('_'):
                await self.load_extension(f'cmds.{filename[:-3]}')
                log.info('✅ 已載入: %s', filename[:-3])

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


if __name__ == "__main__":
    bot.run(settings['token'])
