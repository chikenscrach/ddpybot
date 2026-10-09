import logging
import sqlite3
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from core.classes import CogExtension
from services.database import StartupNotificationDatabase

log = logging.getLogger(__name__)


class Startup(CogExtension):
    """設定各伺服器的機器人啟動通知。"""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.db = StartupNotificationDatabase()

    def cog_unload(self):
        self.db.close()

    @commands.Cog.listener()
    async def on_ready(self):
        if self.bot.startup_notifications_sent:
            return
        # 記在 Bot 上且先標記，避免重連、重載 cog 或重疊事件重複通知。
        self.bot.startup_notifications_sent = True
        try:
            channels = self.db.get_channels()
        except sqlite3.Error:
            log.exception("無法讀取啟動通知設定")
            return

        timestamp = int(discord.utils.utcnow().timestamp())
        for guild_id, channel_id in channels.items():
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                log.warning("略過啟動通知：找不到伺服器 %s", guild_id)
                continue
            try:
                channel = guild.get_channel(channel_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(channel_id)
                if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild_id:
                    log.warning("略過啟動通知：頻道 %s 不屬於伺服器 %s 的文字頻道", channel_id, guild_id)
                    continue
                await channel.send(
                    f"✅ 機器人已啟動！\n上線時間：<t:{timestamp}:F>",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                log.exception("啟動通知發送失敗：伺服器 %s，頻道 %s", guild_id, channel_id)

    @app_commands.command(name="startupnotify", description="設定啟動通知頻道或停用通知（需管理伺服器權限）")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(action="set：設定頻道；disable：停用通知", channel="接收啟動通知的文字頻道（set 時必填）")
    async def startupnotify(
        self,
        interaction: discord.Interaction,
        action: Literal["set", "disable"],
        channel: discord.TextChannel | None = None,
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("❌ 請在伺服器中使用此指令。", ephemeral=True)
            return
        if not interaction.permissions.manage_guild:
            await interaction.response.send_message("❌ 需要「管理伺服器」權限才能設定啟動通知。", ephemeral=True)
            return

        if action == "set":
            if channel is None or channel.guild.id != guild.id:
                await interaction.response.send_message("❌ 請指定此伺服器中的文字頻道。", ephemeral=True)
                return
            permissions = channel.permissions_for(guild.me) if guild.me is not None else None
            if permissions is None or not (permissions.view_channel and permissions.send_messages):
                await interaction.response.send_message("❌ 我需要在通知頻道擁有「查看頻道」及「傳送訊息」權限。", ephemeral=True)
                return
            channel_id = channel.id
            message = f"✅ 已設定啟動通知頻道為 {channel.mention}，下次啟動時會發送通知。"
        else:
            if channel is not None:
                await interaction.response.send_message("❌ 停用通知時不需要指定頻道。", ephemeral=True)
                return
            channel_id = None
            message = "✅ 已停用此伺服器的啟動通知。"

        await interaction.response.defer(ephemeral=True)
        try:
            self.db.set_channel(guild.id, channel_id)
        except sqlite3.Error:
            log.exception("無法儲存伺服器 %s 的啟動通知設定", guild.id)
            await interaction.followup.send("❌ 無法儲存啟動通知設定，請稍後再試。", ephemeral=True)
            return
        await interaction.followup.send(message, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Startup(bot))
