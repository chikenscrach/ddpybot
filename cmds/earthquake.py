import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.classes import CogExtension
from core.config import CWA_API_KEY
from services.earthquake_api import EarthquakeAPI, get_max_intensity, group_shaking_areas
from utils.constants import COLOR_ERROR, CWA_ICON_URL, mag_color, mag_emoji
from utils.time_helper import parse_cwa_time, to_unix

log = logging.getLogger(__name__)


class Earthquake(CogExtension):
    """中央氣象署地震資訊查詢"""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.api = EarthquakeAPI(CWA_API_KEY)

    async def cog_load(self):
        await self.api.start()

    async def cog_unload(self):
        await self.api.close()

    # ────────── 列表 Embed ──────────

    def _build_list_embed(self, quakes: list[dict]) -> discord.Embed:
        top = quakes[:10]
        max_mag = max(
            float(q["EarthquakeInfo"]["EarthquakeMagnitude"]["MagnitudeValue"])
            for q in top
        )

        embed = discord.Embed(
            title="📋 最近地震報告",
            color=mag_color(max_mag),
        )
        embed.set_author(name="中央氣象署", icon_url=CWA_ICON_URL)

        lines: list[str] = []
        for i, q in enumerate(top, start=1):
            info = q["EarthquakeInfo"]
            mag = float(info["EarthquakeMagnitude"]["MagnitudeValue"])
            loc = info["Epicenter"]["Location"]
            unix_ts = to_unix(info["OriginTime"])
            max_int = get_max_intensity(q)
            emoji = mag_emoji(mag)

            lines.append(
                f"**`#{i:02d}`** {emoji} **M {mag}**　｜　最大震度 **{max_int}**\n"
                f"　　　{loc}\n"
                f"　　　🕐 <t:{unix_ts}:f>（<t:{unix_ts}:R>）"
            )

        embed.description = "\n\n".join(lines)
        embed.set_footer(
            text="輸入 /earthquake number:<編號> 查看完整報告　｜　僅顯示最近 10 筆"
        )
        return embed

    # ────────── 詳細 Embed ──────────

    def _build_detail_embed(self, quake: dict, number: int) -> discord.Embed:
        info = quake["EarthquakeInfo"]
        mag = float(info["EarthquakeMagnitude"]["MagnitudeValue"])
        loc = info["Epicenter"]["Location"]
        time_str = info["OriginTime"]
        unix_ts = to_unix(time_str)
        dep = info["FocalDepth"]
        report_content = quake.get("ReportContent", "")
        report_image = quake.get("ReportImageURI", "")
        max_int = get_max_intensity(quake)
        emoji = mag_emoji(mag)

        embed = discord.Embed(
            title=f"{emoji} 地震報告 #{number:02d} ｜ {quake['_source']}",
            description=report_content or None,
            color=mag_color(mag),
            timestamp=parse_cwa_time(time_str),
        )
        embed.set_author(name="中央氣象署", icon_url=CWA_ICON_URL)

        embed.add_field(
            name="📋 基本資訊",
            value=(
                f"> 🕐 時間： <t:{unix_ts}:F>（<t:{unix_ts}:R>）\n"
                f"> 📍 震央： {loc}\n"
                f"> 📏 深度： {dep} km"
            ),
            inline=False,
        )

        embed.add_field(
            name="🚨 規模與震度",
            value=(
                f"> 💥 芮氏規模： **{mag}**\n"
                f"> 📈 最大震度： **{max_int}**"
            ),
            inline=False,
        )

        grouped = group_shaking_areas(quake)
        if grouped:
            lines: list[str] = []
            for intensity, counties in grouped:
                lines.append(f"> **{intensity}** ➔ {', '.join(counties)}")
            text = "\n".join(lines)
            if len(text) > 1024:
                text = text[:1020] + " …"
            embed.add_field(name="🌊 各地震度影響", value=text, inline=False)

        if report_image:
            embed.set_image(url=report_image)

        embed.set_footer(text="資料來源：中央氣象署")
        return embed

    # ────────── 斜線指令 ──────────

    @app_commands.command(name="earthquake", description="查詢最近的地震資訊")
    @app_commands.describe(number="地震編號（1 = 最新，由近到遠排列）")
    async def earthquake_cmd(
        self, interaction: discord.Interaction, number: int | None = None
    ):
        await interaction.response.defer()
        quakes = await self.api.get_all()

        if not quakes:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ 無法取得地震資料",
                    description="請確認 `CWA_API_KEY` 是否正確設定，或稍後再試。",
                    color=0x95A5A6,
                )
            )
            return

        # 列表模式
        if number is None:
            await interaction.followup.send(embed=self._build_list_embed(quakes))
            return

        # 範圍檢查
        if number < 1 or number > len(quakes):
            await interaction.followup.send(
                embed=discord.Embed(
                    description=f"❌ 請輸入 **1** ~ **{len(quakes)}** 之間的編號",
                    color=COLOR_ERROR,
                )
            )
            return

        # 詳細模式
        await interaction.followup.send(
            embed=self._build_detail_embed(quakes[number - 1], number)
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Earthquake(bot))
