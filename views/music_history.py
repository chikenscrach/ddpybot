"""Private history browser and quick-play selector for guild music records."""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

import discord

from services.music_cache import MusicError
from utils.time_helper import TIMEZONE
from views.music import (
    _duration_text,
    _interaction_message_matches,
    _music_error_text,
    _response_is_done,
    _send_ephemeral,
)

log = logging.getLogger(__name__)
PAGE_SIZE = 10


def _id(value: Any) -> int | None:
    value = getattr(value, "id", value)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _clip(value: Any, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _played_at(item: dict[str, Any]) -> int | None:
    try:
        value = int(item["played_at"])
    except (KeyError, TypeError, ValueError):
        return None
    return value if value > 0 else None


def _history_embed(
    items: list[dict[str, Any]],
    *,
    requester_id: int | None,
    page: int,
    total: int,
) -> discord.Embed:
    embed = discord.Embed(
        title="🎵 音樂播放紀錄",
        description=(f"查詢點歌者：<@{requester_id}>" if requester_id is not None else "全部點歌者"),
        color=discord.Color.blurple(),
    )
    for index, item in enumerate(items, start=page * PAGE_SIZE + 1):
        title = str(item.get("title") or "未知歌曲")
        duration = _duration_text(item.get("duration"))
        played_at = _played_at(item)
        played_text = f"<t:{played_at}:R>" if played_at is not None else "時間未知"
        song_requester = _id(item.get("requester_id"))
        requester_text = f"<@{song_requester}>" if song_requester is not None else "未知"
        embed.add_field(
            name=_clip(f"{index}. {title}", 256),
            value=f"時長：{duration} · 播放時間：{played_text}\n點歌者：{requester_text}",
            inline=False,
        )
    pages = max(1, math.ceil(total / PAGE_SIZE))
    embed.set_footer(text=f"第 {page + 1} / {pages} 頁 · 共 {total} 筆")
    return embed


class _HistorySelect(discord.ui.Select):
    def __init__(self, view: MusicHistoryView):
        self.history_view = view
        super().__init__(
            placeholder="選擇歌曲以重新播放",
            min_values=1,
            max_values=1,
            options=[],
            custom_id="ddpybot_music_history_select",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.history_view.select_track(interaction, self.values[0])


class MusicHistoryView(discord.ui.View):
    """Caller-only, guild-scoped history pages with a validated quick-play menu."""

    def __init__(
        self,
        cog: Any,
        *,
        guild_id: int,
        requester_id: int | None,
        owner_id: int | None,
        items: list[dict[str, Any]],
        total: int,
        timeout: float = 180,
    ):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.guild_id = int(guild_id)
        self.requester_id = requester_id
        self.owner_id = owner_id
        self.items = list(items)
        self.total = max(0, int(total))
        self.current_page = 0
        self.message: Any = None
        self.busy = False
        self.disposed = False
        self.select = _HistorySelect(self)
        self.add_item(self.select)
        self._update_controls()

    @property
    def page_count(self) -> int:
        return max(1, math.ceil(self.total / PAGE_SIZE))

    @property
    def embed(self) -> discord.Embed:
        return _history_embed(
            self.items,
            requester_id=self.requester_id,
            page=self.current_page,
            total=self.total,
        )

    def _options(self) -> list[discord.SelectOption]:
        options = []
        for item in self.items:
            entry_id = _id(item.get("id"))
            if entry_id is None:
                continue
            title = _clip(item.get("title") or "未知歌曲", 100)
            duration = _duration_text(item.get("duration"))
            played_at = _played_at(item)
            played_text = (
                datetime.fromtimestamp(played_at, tz=TIMEZONE).strftime("%Y/%m/%d %H:%M")
                if played_at is not None
                else "時間未知"
            )
            options.append(
                discord.SelectOption(
                    label=title,
                    value=str(entry_id),
                    description=_clip(f"{duration} · {played_text}", 100),
                )
            )
        return options

    def _update_controls(self) -> None:
        options = self._options()
        self.select.options = options or [discord.SelectOption(label="沒有可選歌曲", value="none")]
        self.select.disabled = not options or self.busy or self.disposed
        self.btn_previous.disabled = self.current_page <= 0 or self.busy or self.disposed
        self.btn_next.disabled = (
            self.current_page >= self.page_count - 1 or self.busy or self.disposed
        )
        self.btn_page.label = f"{self.current_page + 1} / {self.page_count}"

    async def _check_interaction(self, interaction: discord.Interaction) -> bool:
        user_id = _id(getattr(interaction, "user", None))
        guild_id = _id(getattr(interaction, "guild", None))
        if self.disposed:
            message = "❌ 這份播放紀錄已失效，請重新查詢。"
        elif user_id != self.owner_id:
            message = "❌ 只有查詢紀錄的人可以操作。"
        elif guild_id != self.guild_id:
            message = "❌ 這份播放紀錄只屬於原本的伺服器。"
        elif not _interaction_message_matches(interaction, self.message):
            message = "❌ 這份播放紀錄已失效，請重新查詢。"
        elif self.busy:
            message = "⌛ 正在處理上一個選擇，請稍候。"
        else:
            return True
        await _send_ephemeral(interaction, message)
        return False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self._check_interaction(interaction)

    async def _load_page(self, page: int) -> None:
        result = self.cog.history.query(
            self.guild_id,
            requester_id=self.requester_id,
            limit=PAGE_SIZE,
            offset=page * PAGE_SIZE,
        )
        self.items = list(result["items"])
        self.total = max(0, int(result["total"]))
        self.current_page = min(page, self.page_count - 1)
        self._update_controls()

    async def _change_page(self, interaction: discord.Interaction, page: int) -> None:
        if not await self._check_interaction(interaction):
            return
        if page < 0 or page >= self.page_count:
            await _send_ephemeral(interaction, "❌ 這一頁已不存在，請重新查詢。")
            return
        try:
            await self._load_page(page)
            await interaction.response.edit_message(embed=self.embed, view=self)
        except Exception:
            log.exception("failed to load music history page")
            await _send_ephemeral(interaction, "❌ 無法讀取這一頁播放紀錄，請稍後再試。")

    @discord.ui.button(
        label="◀",
        style=discord.ButtonStyle.secondary,
        custom_id="ddpybot_music_history_previous",
        row=1,
    )
    async def btn_previous(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self._change_page(interaction, self.current_page - 1)

    @discord.ui.button(
        label="1 / 1",
        style=discord.ButtonStyle.secondary,
        custom_id="ddpybot_music_history_page",
        disabled=True,
        row=1,
    )
    async def btn_page(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        if await self._check_interaction(interaction):
            await interaction.response.defer()

    @discord.ui.button(
        label="▶",
        style=discord.ButtonStyle.secondary,
        custom_id="ddpybot_music_history_next",
        row=1,
    )
    async def btn_next(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self._change_page(interaction, self.current_page + 1)

    async def select_track(self, interaction: discord.Interaction, value: str) -> None:
        if not await self._check_interaction(interaction):
            return
        try:
            entry_id = int(value)
        except (TypeError, ValueError):
            await _send_ephemeral(interaction, "❌ 這首歌曲已失效，請重新查詢。")
            return
        if entry_id not in {_id(item.get("id")) for item in self.items}:
            await _send_ephemeral(interaction, "❌ 這首歌曲不在目前頁面，請重新查詢。")
            return

        self.busy = True
        try:
            await self._defer_ephemeral(interaction)
            entry = self.cog.history.get(
                self.guild_id,
                entry_id,
                requester_id=self.requester_id,
            )
            if (
                entry is None
                or _id(entry.get("id")) != entry_id
                or str(entry.get("guild_id")) != str(self.guild_id)
                or (
                    self.requester_id is not None
                    and str(entry.get("requester_id")) != str(self.requester_id)
                )
                or not entry.get("url")
            ):
                await _send_ephemeral(interaction, "❌ 這首歌曲已失效或無法存取，請重新查詢。")
                return

            allowed, _channel = await self.cog._require_voice(interaction)
            if not allowed:
                return
            tracks = await self.cog._enqueue(interaction, entry["url"])
            count = len(tracks or [])
            await _send_ephemeral(interaction, f"✅ 已接受 **{count}** 首歌曲的播放要求。")
        except MusicError as exc:
            await _send_ephemeral(interaction, _music_error_text(exc))
        except Exception as exc:
            log.exception("music history quick-play failed")
            await _send_ephemeral(interaction, _music_error_text(exc))
        finally:
            if not self.disposed:
                self.busy = False
                self._update_controls()
                await self._edit_view()

    async def _defer_ephemeral(self, interaction: discord.Interaction) -> None:
        if await _response_is_done(interaction):
            return
        response = getattr(interaction, "response", None)
        if response is None or not hasattr(response, "defer"):
            return
        try:
            await response.defer(ephemeral=True, thinking=True)
        except TypeError:
            await response.defer()

    async def _edit_view(self) -> None:
        if self.message is None or not hasattr(self.message, "edit"):
            return
        try:
            await self.message.edit(view=self)
        except (discord.NotFound, discord.HTTPException):
            log.debug("music history view message is no longer available", exc_info=True)

    async def on_timeout(self) -> None:
        self.disposed = True
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass
        super().stop()
