import asyncio
import logging
import random
from urllib.parse import urlsplit

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from core.classes import CogExtension
from utils.constants import COLOR_INFO

log = logging.getLogger(__name__)

DANBOORU_POSTS_API = "https://danbooru.donmai.us/posts.json"

# Discord 能直接顯示的常見圖片格式；略過 webm/mp4 等影片 post。
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}

# 一次拿 20 張隨機候選圖，再從中隨機選 5 張。
# 這樣即使某些 post 是影片，也較容易湊足 5 張圖片。
CANDIDATE_COUNT = 20
SEND_COUNT = 5

# Danbooru 四級分級（2022 年改制）：g=General、s=Sensitive、q=Questionable、e=Explicit。
# 注意 rating:s 是「Sensitive（擦邊）」不是舊制的 Safe；嚴格 SFW 要用 rating:g。
RATING_LABELS = {
    "g": "General",
    "s": "Sensitive",
    "q": "Questionable",
    "e": "Explicit",
}

RATING_CHOICES = [
    app_commands.Choice(name="General（一般向，預設）", value="g"),
    app_commands.Choice(name="Sensitive（輕度擦邊，需 NSFW 頻道）", value="s"),
    app_commands.Choice(name="Questionable（限制級，需 NSFW 頻道）", value="q"),
    app_commands.Choice(name="Explicit（R-18 露骨，需 NSFW 頻道）", value="e"),
]

HEADERS = {
    # Danbooru 要求可識別的 UA，不要用 aiohttp 預設值
    "User-Agent": "DDPYBOT/1.0 (+https://github.com/chikenscrach/ddpybot)",
    "Accept": "application/json",
}


def format_source_urls(source: str | None, max_chars: int = 500) -> str:
    """從 Danbooru 的 source 欄位提取 http(s) URL，供 Discord embed 顯示。"""
    if not source:
        return "Danbooru 未提供來源網址。"

    urls = []
    for value in source.split():
        try:
            parsed = urlsplit(value)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                urls.append(value)
        except ValueError:
            continue

    if not urls:
        return "Danbooru 未提供可用的來源網址。"

    # <https://...> 在 Discord 中可點擊且不會生成額外預覽。
    lines = []
    current_length = 0

    for url in urls:
        line = f"<{url}>"
        extra_length = len(line) + (1 if lines else 0)

        if current_length + extra_length > max_chars:
            break

        lines.append(line)
        current_length += extra_length

    return "\n".join(lines) if lines else "來源網址過長，請由 Danbooru post 頁查看。"


def channel_allows_nsfw(interaction: discord.Interaction) -> bool:
    """私訊視為允許（同 discord.py 內建 NSFW 檢查的慣例）；伺服器頻道看年齡限制旗標。"""
    if interaction.guild is None:
        return True
    # Thread 的 is_nsfw() 會回傳父頻道的旗標；PartialMessageable 等型別沒有此方法，一律視為不允許
    is_nsfw = getattr(interaction.channel, "is_nsfw", None)
    return callable(is_nsfw) and is_nsfw()


class Danbooru(CogExtension):
    """Danbooru 隨機圖片搜尋"""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        # 整個 Cog 生命週期共用一個連線池（同 ptt.py / earthquake_api.py 的慣例）
        self.session = aiohttp.ClientSession(
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        )

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    @app_commands.command(
        name="danbooru",
        description="隨機搜尋 Danbooru 圖片（最多 5 張；NSFW 分級僅限年齡限制頻道）",
    )
    @app_commands.describe(
        tag="單一 Danbooru tag，例如：hakurei_reimu",
        rating="圖片分級，預設 General；其餘分級僅能在 NSFW 頻道或私訊使用",
    )
    @app_commands.choices(rating=RATING_CHOICES)
    @app_commands.checks.cooldown(
        1,
        8.0,
        key=lambda interaction: interaction.user.id,
    )
    async def danbooru(
        self,
        interaction: discord.Interaction,
        tag: str,
        rating: str | None = None,
    ):
        tag = tag.strip()

        # 此版本刻意只允許一個 tag，避免有人自行塞入額外搜尋條件。
        if not tag or len(tag) > 100 or any(char.isspace() for char in tag):
            await interaction.response.send_message(
                "請輸入一個 Danbooru tag，例如：`hakurei_reimu`。",
                ephemeral=True,
            )
            return

        # 一般頻道固定 General；NSFW 頻道與私訊可由參數放寬到 s/q/e。
        chosen_rating = rating or "g"
        if chosen_rating != "g" and not channel_allows_nsfw(interaction):
            await interaction.response.send_message(
                f"`{RATING_LABELS[chosen_rating]}` 分級僅能在 NSFW（年齡限制）頻道或私訊中使用，"
                "一般頻道僅提供 General。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        search_tags = f"{tag} rating:{chosen_rating} random:{CANDIDATE_COUNT}"
        params = {
            "tags": search_tags,
            "limit": CANDIDATE_COUNT,
        }

        try:
            async with self.session.get(DANBOORU_POSTS_API, params=params) as response:
                if response.status == 429:
                    log.warning("Danbooru API 速率限制 (429)，tag=%s", tag)
                    await interaction.followup.send(
                        "Danbooru API 目前限制請求頻率，請稍後再試。"
                    )
                    return

                if response.status != 200:
                    log.warning("Danbooru API 回應狀態碼 %d，tag=%s", response.status, tag)
                    await interaction.followup.send(
                        f"Danbooru API 回傳錯誤：HTTP {response.status}"
                    )
                    return

                posts = await response.json()

        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            log.exception("Danbooru API 請求失敗，tag=%s", tag)
            await interaction.followup.send(
                "目前無法連線至 Danbooru，請稍後再試。"
            )
            return

        if not isinstance(posts, list):
            log.warning("Danbooru API 回傳非預期格式: %r", type(posts))
            await interaction.followup.send("Danbooru 回傳了非預期的資料格式。")
            return

        # 過濾掉影片、受限（缺少 id）或沒有可顯示圖片網址的 post。
        candidates = [
            post
            for post in posts
            if post.get("id")
            and str(post.get("file_ext", "")).lower() in IMAGE_EXTENSIONS
            and (
                post.get("large_file_url")
                or post.get("file_url")
                or post.get("preview_file_url")
            )
        ]

        if not candidates:
            await interaction.followup.send(
                f"找不到 tag `{tag}` 的可顯示 {RATING_LABELS[chosen_rating]} 分級圖片。"
            )
            return

        selected_posts = random.sample(
            candidates,
            k=min(SEND_COUNT, len(candidates)),
        )

        embeds = []

        for index, post in enumerate(selected_posts, start=1):
            post_id = post["id"]
            post_url = f"https://danbooru.donmai.us/posts/{post_id}"

            # large_file_url 通常較適合 Discord 預覽；
            # 若沒有才退回原圖或縮圖。
            image_url = (
                post.get("large_file_url")
                or post.get("file_url")
                or post.get("preview_file_url")
            )

            embed = discord.Embed(
                title=f"Danbooru post #{post_id}",
                url=post_url,  # 點標題即可開啟 Danbooru post
                description=(
                    f"搜尋 tag：`{discord.utils.escape_markdown(tag)}`\n"
                    f"Rating：`{RATING_LABELS[chosen_rating]}`"
                ),
                color=COLOR_INFO,
            )

            embed.set_image(url=image_url)

            embed.add_field(
                name="Danbooru post",
                value=f"<{post_url}>",
                inline=False,
            )

            embed.add_field(
                name="Source（原始作品來源）",
                value=format_source_urls(post.get("source")),
                inline=False,
            )

            width = post.get("image_width", "?")
            height = post.get("image_height", "?")
            score = post.get("score", 0)

            embed.set_footer(
                text=f"{width}×{height} · score: {score} · {index}/{len(selected_posts)}"
            )

            embeds.append(embed)

        await interaction.followup.send(embeds=embeds)

    @danbooru.error
    async def danbooru_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"請在 {error.retry_after:.1f} 秒後再搜尋。"

            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return

        raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(Danbooru(bot))
