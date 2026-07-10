import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

from core.classes import Cog_Extension
from core.config import settings

log = logging.getLogger(__name__)


class Earthquake(Cog_Extension):
    """中央氣象署地震資訊查詢"""

    DATASETS = {
        "E-A0015-001": "顯著有感地震",
        "E-A0016-001": "小區域有感地震",
    }
    BASE_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"
    CACHE_TTL = 60  # 秒；地震報告更新頻率低，快取可省下重複的 API 請求

    INTENSITY_ORDER = {
        "1級": 1, "2級": 2, "3級": 3, "4級": 4,
        "5弱級": 5, "5弱": 5, "5強級": 6, "5強": 6,
        "6弱級": 7, "6弱": 7, "6強級": 8, "6強": 8,
        "7級": 9,
    }

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.api_key: str = settings.get("CWA_API_KEY", "")
        self.session: aiohttp.ClientSession | None = None
        self._cache: list[dict] = []
        self._cache_time: float = 0.0

    # ✅ 整個 Cog 共用一個 ClientSession（重用連線池，比每次請求都新建快）
    async def cog_load(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    # ────────── 工具方法 ──────────

    @staticmethod
    def _mag_color(mag: float) -> int:
        if mag >= 6.0:
            return 0xE74C3C
        if mag >= 5.0:
            return 0xE67E22
        if mag >= 4.0:
            return 0xF1C40F
        if mag >= 3.0:
            return 0x2ECC71
        return 0x3498DB

    @staticmethod
    def _mag_emoji(mag: float) -> str:
        if mag >= 6.0:
            return "🔴"
        if mag >= 5.0:
            return "🟠"
        if mag >= 4.0:
            return "🟡"
        if mag >= 3.0:
            return "🟢"
        return "🔵"

    @staticmethod
    def _parse_time(time_str: str) -> datetime:
        """
        解析 CWA 時間字串為帶時區的 datetime
        同時支援 '2026-07-09 09:29:01' 與 ISO 8601 '2026-07-09T09:29:01+08:00' 兩種格式
        """
        dt = datetime.fromisoformat(time_str)
        if dt.tzinfo is None:  # 沒帶時區的舊格式一律視為 UTC+8
            dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
        return dt

    @classmethod
    def _to_unix(cls, time_str: str) -> int:
        """將 CWA 時間字串轉為 Unix Timestamp"""
        return int(cls._parse_time(time_str).timestamp())

    def _get_max_intensity(self, quake: dict) -> str:
        areas = quake.get("Intensity", {}).get("ShakingArea", [])
        if not areas:
            return "—"
        max_val = 0
        max_label = "—"
        for area in areas:
            raw = area.get("AreaIntensity", "")
            val = self.INTENSITY_ORDER.get(raw, 0)
            if val > max_val:
                max_val = val
                max_label = raw
        return max_label

    def _group_shaking_areas(self, quake: dict) -> list[tuple[str, list[str]]]:
        """將各地震度依等級分組，去重後由大到小排列"""
        areas = quake.get("Intensity", {}).get("ShakingArea", [])
        if not areas:
            return []

        groups: dict[str, set[str]] = {}
        for area in areas:
            intensity = area.get("AreaIntensity", "")
            county = area.get("CountyName", "")
            if not intensity or not county:
                continue
            if intensity not in groups:
                groups[intensity] = set()
            # 處理「、」或「,」分隔的多縣市
            for c in county.replace("、", ",").split(","):
                c = c.strip()
                if c:
                    groups[intensity].add(c)

        sorted_groups = sorted(
            groups.items(),
            key=lambda x: self.INTENSITY_ORDER.get(x[0], 0),
            reverse=True,
        )
        return [(intensity, sorted(counties)) for intensity, counties in sorted_groups]

    # ────────── API 取得資料 ──────────

    async def _fetch_dataset(self, dataset_id: str, label: str) -> list[dict]:
        url = f"{self.BASE_URL}/{dataset_id}?Authorization={self.api_key}"
        try:
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    log.warning("CWA 資料集 %s 回應狀態碼 %d", dataset_id, resp.status)
                    return []
                data = await resp.json()
                if data.get("success") != "true":
                    log.warning("CWA 資料集 %s 回傳失敗: %s", dataset_id, data.get("message", data))
                    return []
                quakes = data.get("records", {}).get("Earthquake", [])
                for q in quakes:
                    q["_source"] = label
                return quakes
        except (aiohttp.ClientError, asyncio.TimeoutError):
            log.exception("取得 CWA 資料集 %s 失敗", dataset_id)
            return []

    async def get_all_earthquakes(self) -> list[dict]:
        # ✅ 快取尚未過期就直接回傳，避免每次指令都打兩次 API
        now = time.monotonic()
        if self._cache and now - self._cache_time < self.CACHE_TTL:
            return self._cache

        # ✅ 兩個資料集並行抓取，省下一半等待時間
        dataset_results = await asyncio.gather(
            *(self._fetch_dataset(did, label) for did, label in self.DATASETS.items())
        )
        results = [q for quakes in dataset_results for q in quakes]
        # 兩個資料集的時間格式可能不同，改以解析後的 datetime 排序才準確
        results.sort(
            key=lambda q: self._parse_time(q["EarthquakeInfo"]["OriginTime"]),
            reverse=True,
        )

        if results:
            self._cache = results
            self._cache_time = now
        return results

    # ────────── 列表 Embed ──────────

    def _build_list_embed(self, quakes: list[dict]) -> discord.Embed:
        top = quakes[:10]
        max_mag = max(
            float(q["EarthquakeInfo"]["EarthquakeMagnitude"]["MagnitudeValue"])
            for q in top
        )

        embed = discord.Embed(
            title="📋 最近地震報告",
            color=self._mag_color(max_mag),
        )
        embed.set_author(
            name="中央氣象署",
            icon_url="https://files.catbox.moe/t8elt5.png",
        )

        lines: list[str] = []
        for i, q in enumerate(top, start=1):
            info = q["EarthquakeInfo"]
            mag = float(info["EarthquakeMagnitude"]["MagnitudeValue"])
            loc = info["Epicenter"]["Location"]
            unix_ts = self._to_unix(info["OriginTime"])
            max_int = self._get_max_intensity(q)
            emoji = self._mag_emoji(mag)

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
        unix_ts = self._to_unix(time_str)
        dep = info["FocalDepth"]
        report_content = quake.get("ReportContent", "")
        report_image = quake.get("ReportImageURI", "")
        max_int = self._get_max_intensity(quake)
        emoji = self._mag_emoji(mag)

        # ── 標題 & 描述 ──
        embed = discord.Embed(
            title=f"{emoji} 地震報告 #{number:02d} ｜ {quake['_source']}",
            description=report_content or None,
            color=self._mag_color(mag),
            timestamp=self._parse_time(time_str),
        )
        embed.set_author(
            name="中央氣象署",
            icon_url="https://files.catbox.moe/t8elt5.png",
        )

        # ── 📋 基本資訊 ──
        embed.add_field(
            name="📋 基本資訊",
            value=(
                f"> 🕐 時間： <t:{unix_ts}:F>（<t:{unix_ts}:R>）\n"
                f"> 📍 震央： {loc}\n"
                f"> 📏 深度： {dep} km"
            ),
            inline=False,
        )

        # ── 🚨 規模與震度 ──
        embed.add_field(
            name="🚨 規模與震度",
            value=(
                f"> 💥 芮氏規模： **{mag}**\n"
                f"> 📈 最大震度： **{max_int}**"
            ),
            inline=False,
        )

        # ── 🌊 各地震度影響 ──
        grouped = self._group_shaking_areas(quake)
        if grouped:
            lines: list[str] = []
            for intensity, counties in grouped:
                lines.append(f"> **{intensity}** ➔ {', '.join(counties)}")
            text = "\n".join(lines)
            if len(text) > 1024:
                text = text[:1020] + " …"
            embed.add_field(name="🌊 各地震度影響", value=text, inline=False)

        # ── 報告圖 ──
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
        quakes = await self.get_all_earthquakes()

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
                    color=0xE74C3C,
                )
            )
            return

        # 詳細模式
        await interaction.followup.send(
            embed=self._build_detail_embed(quakes[number - 1], number)
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Earthquake(bot))
