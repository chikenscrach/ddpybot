import discord
from discord.ext import commands
from discord import app_commands
from core.classes import Cog_Extension
import random
import json
import datetime

with open('setting.json', 'r', encoding='utf8') as jfile:
    jdata = json.load(jfile)


class React(Cog_Extension):
    # ✅ 用 @app_commands.describe 為斜線指令的參數加上說明
    @commands.hybrid_command(name='say', description='讓機器人替你說話')
    @app_commands.describe(msg='要說的內容')
    async def say(self, ctx, *, msg: str):
        # 斜線指令沒有「原始訊息」可刪，所以要判斷
        if ctx.interaction is None:
            # 是前綴指令 → 刪除使用者的訊息
            await ctx.message.delete()
            await ctx.send(msg)
        else:
            # 是斜線指令 → 用 ephemeral 回覆「已發送」，再另外發送訊息
            await ctx.send(msg)

    @commands.hybrid_command(name='clean', description='清除指定數量的訊息')
    @app_commands.describe(num='要清除的訊息數量')
    async def clean(self, ctx, num: int):
        await ctx.channel.purge(limit=num)
        # 斜線指令需要回應，否則會顯示「互動失敗」
        if ctx.interaction:
            await ctx.send(f'✅ 已清除 {num} 則訊息', ephemeral=True)

    @commands.hybrid_command(name='亞歷山大', description='亞歷山大')
    async def 亞歷山大(self, ctx):
        await ctx.send('https://imgur.com/5MRjKt0')


async def setup(bot):
    await bot.add_cog(React(bot))