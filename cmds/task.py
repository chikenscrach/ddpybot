import datetime
import logging
import random

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.classes import CogExtension
from core.config import settings
from services.database import PingDatabase
from utils.constants import COLOR_GOLD, COLOR_INFO
from utils.time_helper import TIMEZONE

log = logging.getLogger(__name__)

# 防禦式讀取：缺欄位只停用每日標功能，不讓整個 cog 掛掉
DAILY_CHANNEL_ID = settings.get('DAILY_CHANNEL_ID')


class Task(CogExtension):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.db = PingDatabase()
        if DAILY_CHANNEL_ID:
            self.daily_ping.start()
        else:
            log.warning('⚠️ 未設定 DAILY_CHANNEL_ID，每日隨機標排程停用（查詢指令仍可使用）')

    def cog_unload(self):
        try:
            self.daily_ping.cancel()
        finally:
            self.db.close()  # 即使 cancel 出錯也確保連線關閉

    # ==========================================
    #  每日 00:00 定時任務
    # ==========================================

    @tasks.loop(time=datetime.time(hour=0, minute=0, second=0, tzinfo=TIMEZONE))
    async def daily_ping(self):
        channel = self.bot.get_channel(DAILY_CHANNEL_ID)
        if channel is None:
            # 快取未暖時 get_channel 會回 None，改直接向 API 查詢
            try:
                channel = await self.bot.fetch_channel(DAILY_CHANNEL_ID)
            except discord.HTTPException:
                log.warning('⚠️ 找不到頻道 %s', DAILY_CHANNEL_ID)
                return

        guild = channel.guild

        # 取得所有非 Bot 的成員
        members = [m for m in guild.members if not m.bot]
        if not members:
            return

        chosen = random.choice(members)
        self.db.add_ping(chosen.id)

        # Bot 預設 allowed_mentions=none，這裡是真的要標人，需明確允許
        await channel.send(
            f'每日隨機標 {chosen.mention}',
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    @daily_ping.before_loop
    async def before_daily_ping(self):
        """等待 Bot 完全啟動後才開始排程"""
        await self.bot.wait_until_ready()

    # ==========================================
    #  查詢指令（前綴 + 斜線）
    # ==========================================

    @commands.hybrid_command(name='ping_count', description='查看某位成員被標的次數')
    @app_commands.describe(member='要查詢的成員（不填則查詢自己）')
    async def ping_count(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        count = self.db.get_count(member.id)

        embed = discord.Embed(
            description=f'📊 {member.mention} 被標了 **{count}** 次',
            color=COLOR_INFO,
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='ping_rank', description='查看被標次數排行榜')
    @app_commands.describe(top='顯示前幾名（預設 10）')
    async def ping_rank(self, ctx, top: int = 10):
        top = max(1, min(top, 25))  # 限制 1~25

        rows = self.db.get_leaderboard(top)
        if not rows:
            await ctx.send('📊 目前還沒有任何人被標過！')
            return

        medals = ['🥇', '🥈', '🥉']
        description = ''

        for i, (user_id, count) in enumerate(rows):
            medal = medals[i] if i < 3 else f'`#{i + 1}`'
            member = ctx.guild.get_member(user_id)
            name = member.display_name if member else f'未知用戶 ({user_id})'
            description += f'{medal} **{name}** — {count} 次\n'

        embed = discord.Embed(
            title='🏆 每日隨機標排行榜',
            description=description,
            color=COLOR_GOLD,
            timestamp=datetime.datetime.now(tz=TIMEZONE),
        )
        await ctx.send(embed=embed)

    # ==========================================
    #  手動觸發測試
    # ==========================================

    @commands.hybrid_command(name='test_daily', description='手動觸發每日標（測試用）')
    @commands.has_permissions(administrator=True)
    async def test_daily(self, ctx):
        """手動執行一次每日標記，方便測試"""
        if not DAILY_CHANNEL_ID:
            return await ctx.send('⚠️ 未設定 DAILY_CHANNEL_ID，無法觸發每日標。', ephemeral=True)
        await self.daily_ping()
        await ctx.send('✅ 已手動觸發每日標', ephemeral=True)


async def setup(bot):
    await bot.add_cog(Task(bot))
