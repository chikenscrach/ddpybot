import discord
from discord.ext import commands, tasks
from discord import app_commands
from core.classes import Cog_Extension
import sqlite3
import random
import datetime
import os
import json

with open('setting.json', 'r', encoding = 'utf8') as jfile:
    jdata = json.load(jfile)

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo('Asia/Taipei')

# ✅ 改成你要發送每日標的頻道 ID
DAILY_CHANNEL_ID = jdata['DAILY_CHANNEL_ID']


class Task(Cog_Extension):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self._init_db()
        self.daily_ping.start()

    def cog_unload(self):
        self.daily_ping.cancel()
        self.conn.close()

    # ==========================================
    #  資料庫
    # ==========================================

    def _init_db(self):
        """初始化 SQLite 資料庫"""
        os.makedirs('data', exist_ok=True)
        self.conn = sqlite3.connect('data/ping_count.db')
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS ping_counts (
                user_id  INTEGER PRIMARY KEY,
                count    INTEGER DEFAULT 0
            )
        ''')
        self.conn.commit()

    def _add_ping(self, user_id: int) -> int:
        """新增一次標記，回傳累計次數"""
        self.conn.execute('''
            INSERT INTO ping_counts (user_id, count) VALUES (?, 1)
            ON CONFLICT(user_id) DO UPDATE SET count = count + 1
        ''', (user_id,))
        self.conn.commit()
        cur = self.conn.execute(
            'SELECT count FROM ping_counts WHERE user_id = ?', (user_id,)
        )
        return cur.fetchone()[0]

    def _get_count(self, user_id: int) -> int:
        """查詢某人被標記次數"""
        cur = self.conn.execute(
            'SELECT count FROM ping_counts WHERE user_id = ?', (user_id,)
        )
        row = cur.fetchone()
        return row[0] if row else 0

    def _get_leaderboard(self, limit: int = 10) -> list:
        """取得排行榜（次數由高到低）"""
        cur = self.conn.execute(
            'SELECT user_id, count FROM ping_counts ORDER BY count DESC LIMIT ?',
            (limit,)
        )
        return cur.fetchall()

    # ==========================================
    #  每日 00:00 定時任務
    # ==========================================

    @tasks.loop(time=datetime.time(hour=0, minute=0, second=0, tzinfo=TIMEZONE))
    async def daily_ping(self):
        channel = self.bot.get_channel(DAILY_CHANNEL_ID)
        if channel is None:
            print(f'⚠️ 找不到頻道 {DAILY_CHANNEL_ID}')
            return

        guild = channel.guild

        # 取得所有非 Bot 的成員
        members = [m for m in guild.members if not m.bot]
        if not members:
            return

        chosen = random.choice(members)
        self._add_ping(chosen.id)
        
        await channel.send(f'每日隨機標 {chosen.mention}')

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
        count = self._get_count(member.id)

        embed = discord.Embed(
            description=f'📊 {member.mention} 被標了 **{count}** 次',
            color=0x3498DB
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='ping_rank', description='查看被標次數排行榜')
    @app_commands.describe(top='顯示前幾名（預設 10）')
    async def ping_rank(self, ctx, top: int = 10):
        top = max(1, min(top, 25))  # 限制 1~25

        rows = self._get_leaderboard(top)
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
            color=0xFFD700,
            timestamp=datetime.datetime.now(tz=TIMEZONE)
        )
        await ctx.send(embed=embed)

    # ==========================================
    #  手動觸發測試（可選，上線後可刪除）
    # ==========================================

    @commands.hybrid_command(name='test_daily', description='手動觸發每日標（測試用）')
    @commands.has_permissions(administrator=True)
    async def test_daily(self, ctx):
        """手動執行一次每日標記，方便測試"""
        await self.daily_ping()
        await ctx.send('✅ 已手動觸發每日標', ephemeral=True)


async def setup(bot):
    await bot.add_cog(Task(bot))