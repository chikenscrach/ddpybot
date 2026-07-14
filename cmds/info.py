import discord
from discord.ext import commands
from discord import app_commands

from core.classes import Cog_Extension

import platform
import sys
import os
import psutil
from datetime import datetime, timezone

from utils.embed_builder import progress_bar
from utils.time_helper import fmt_uptime


class Info(Cog_Extension):

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.start_time = datetime.now(timezone.utc)
        self.process = psutil.Process(os.getpid())
        self.process.cpu_percent()  # 第一次呼叫只是初始化，之後才有值

    # ==================== 建立 Embed ====================

    def _build_embed(self, user: discord.User | discord.Member) -> discord.Embed:
        bot = self.bot
        now = datetime.now(timezone.utc)

        # ── 系統數據 ──
        mem_info   = self.process.memory_info()
        cpu_pct    = self.process.cpu_percent()
        sys_mem    = psutil.virtual_memory()

        # ── Discord 數據 ──
        guild_count   = len(bot.guilds)
        member_count  = sum(g.member_count or 0 for g in bot.guilds)
        channel_count = sum(len(g.channels) for g in bot.guilds)
        latency_ms    = round(bot.latency * 1000)

        # 延遲指示燈
        if latency_ms < 100:
            lat_emoji = "🟢"
        elif latency_ms < 200:
            lat_emoji = "🟡"
        else:
            lat_emoji = "🔴"

        # ── 組裝 Embed ──
        embed = discord.Embed(
            title=f"📋 {bot.user.display_name} ─ 資訊面板",
            color=discord.Color.blurple(),
            timestamp=now,
        )
        embed.set_thumbnail(url=bot.user.display_avatar.url)

        # — 第一排 —
        embed.add_field(
            name="🤖 基本資訊",
            value=(
                f"> **名稱：** {bot.user}\n"
                f"> **ID：** `{bot.user.id}`\n"
                f"> **建立於：** <t:{int(bot.user.created_at.timestamp())}:D>"
            ),
            inline=True,
        )
        embed.add_field(
            name="📊 統計數據",
            value=(
                f"> **伺服器：** {guild_count}\n"
                f"> **使用者：** {member_count:,}\n"
                f"> **頻道數：** {channel_count:,}"
            ),
            inline=True,
        )
        embed.add_field(name="​", value="​", inline=True)   # 佔位

        # — 第二排 —
        embed.add_field(
            name="⏱️ 運行狀態",
            value=(
                f"> **延遲：** {lat_emoji} {latency_ms} ms\n"
                f"> **上線時間：** {fmt_uptime(self.start_time)}\n"
                f"> **已載入模組：** {len(bot.cogs)} 個"
            ),
            inline=True,
        )

        mem_bar = progress_bar(sys_mem.percent / 100)
        embed.add_field(
            name="🖥️ 系統資源",
            value=(
                f"> **程序記憶體：** {mem_info.rss / 1024**2:.1f} MB\n"
                f"> **系統記憶體：** {mem_bar} {sys_mem.percent}%\n"
                f"> **程序 CPU：** {cpu_pct:.1f}%"
            ),
            inline=True,
        )
        embed.add_field(name="​", value="​", inline=True)   # 佔位

        # — 第三排（滿版） —
        embed.add_field(
            name="📦 版本資訊",
            value=(
                f"> **Python：** `{sys.version.split()[0]}`　"
                f"**discord.py：** `{discord.__version__}`　"
                f"**OS：** `{platform.system()} {platform.release()}`"
            ),
            inline=False,
        )

        embed.set_footer(
            text=f"由 {user.display_name} 查詢",
            icon_url=user.display_avatar.url,
        )
        return embed

    # ==================== Slash 指令 ====================

    @app_commands.command(name="botinfo", description="顯示機器人的詳細資訊與運行狀態")
    async def botinfo(self, interaction: discord.Interaction):
        embed = self._build_embed(interaction.user)
        view  = _RefreshView(self, interaction.user)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()


# ==================== 重新整理按鈕 ====================

class _RefreshView(discord.ui.View):
    """附帶 🔄 按鈕，讓使用者即時更新數據"""

    def __init__(self, cog: Info, author: discord.User):
        super().__init__(timeout=180)
        self.cog    = cog
        self.author = author
        self.message: discord.Message | None = None

    @discord.ui.button(label="重新整理", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message(
                "❌ 只有指令使用者才能重新整理。", ephemeral=True
            )
        embed = self.cog._build_embed(interaction.user)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
