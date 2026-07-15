from discord import app_commands
from discord.ext import commands

from core.classes import CogExtension
from utils.validators import is_manager


class React(CogExtension):
    # 提及安全：Bot 已在 main.py 設定 allowed_mentions=none，
    # 所以 say 不會被拿來 @everyone / @here
    @commands.hybrid_command(name='say', description='讓機器人替你說話')
    @app_commands.describe(msg='要說的內容')
    @commands.cooldown(1, 10, commands.BucketType.user)  # 每人 10 秒一次，防洗頻
    async def say(self, ctx, *, msg: str):
        # 斜線指令沒有「原始訊息」可刪，所以要判斷
        if ctx.interaction is None:
            # 是前綴指令 → 刪除使用者的訊息
            await ctx.message.delete()
        await ctx.send(msg)

    @commands.hybrid_command(name='clean', description='清除指定數量的訊息')
    @app_commands.describe(num='要清除的訊息數量（1~100）')
    @commands.cooldown(1, 30, commands.BucketType.channel)  # 每頻道 30 秒一次，防誤觸連清
    @is_manager()
    async def clean(self, ctx, num: int):
        num = max(1, min(num, 100))  # 限制範圍，避免一次清除過多訊息
        await ctx.channel.purge(limit=num)
        # 斜線指令需要回應，否則會顯示「互動失敗」
        if ctx.interaction:
            await ctx.send(f'✅ 已清除 {num} 則訊息', ephemeral=True)

    @commands.hybrid_command(name='亞歷山大', description='亞歷山大')
    async def 亞歷山大(self, ctx):
        await ctx.send('https://imgur.com/5MRjKt0')


async def setup(bot):
    await bot.add_cog(React(bot))
