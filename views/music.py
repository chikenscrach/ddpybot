"""Discord views and embeds used by the music cog.

The service owns playback state.  This module deliberately only deals with
presentation and interaction validation, which keeps the views usable in
offline tests and prevents a stale Discord component from changing a newer
voice session.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import discord

log = logging.getLogger(__name__)


STATUS_LABELS = {
    "idle": "待命中",
    "downloading": "下載中",
    "playing": "播放中",
    "paused": "已暫停",
    "stopped": "已停止",
    "disconnected": "已離開語音頻道",
}

STATUS_COLORS = {
    "idle": discord.Color.blurple(),
    "downloading": discord.Color.orange(),
    "playing": discord.Color.green(),
    "paused": discord.Color.gold(),
    "stopped": discord.Color.light_grey(),
    "disconnected": discord.Color.dark_grey(),
}


def _truncate(value: Any, limit: int, fallback: str = "") -> str:
    text = str(value or fallback)
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1].rstrip() + "…"


def _channel_id(channel_or_voice: Any) -> int | None:
    """Return a channel ID from a VoiceClient, channel, or channel-like mock."""

    if channel_or_voice is None:
        return None
    channel = getattr(channel_or_voice, "channel", None)
    if channel is not None:
        channel_or_voice = channel
    value = getattr(channel_or_voice, "id", None)
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    value = getattr(channel_or_voice, "channel_id", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _duration_text(duration: Any) -> str:
    if duration is None or duration == "":
        return "未知"
    try:
        seconds = max(0, int(float(duration)))
    except (TypeError, ValueError):
        return _truncate(duration, 32, "未知")

    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _track_value(track: Any, name: str, default: Any = None) -> Any:
    if track is None:
        return default
    if isinstance(track, dict):
        return track.get(name, default)
    return getattr(track, name, default)


def _status(state: Any, override: str | None = None) -> str:
    return override or str(getattr(state, "status", "idle") or "idle")


def build_now_playing_embed(
    state: Any,
    *,
    detail: str | None = None,
    status_override: str | None = None,
) -> discord.Embed:
    """Build the current playback panel embed.

    ``state`` is intentionally duck-typed.  The music service exposes a
    small dataclass, while duck typing also makes this helper straightforward
    to exercise with ``SimpleNamespace`` in tests.
    """

    status = _status(state, status_override)
    status_label = STATUS_LABELS.get(status, status)
    current = getattr(state, "current", None)
    title = _track_value(current, "title", None)
    url = _track_value(current, "url", None)
    duration = _track_value(current, "duration", None)
    thumbnail = _track_value(current, "thumbnail", None)
    requester_id = _track_value(current, "requester_id", None)

    if title:
        embed_title = f"🎶 {_truncate(title, 245)}"
    elif status == "downloading":
        embed_title = "🎶 正在準備下一首歌曲"
    elif status == "idle":
        embed_title = "🎶 音樂播放面板"
    else:
        embed_title = "🎶 目前沒有播放中的歌曲"

    embed = discord.Embed(
        title=embed_title,
        url=_truncate(url, 2048) if url else None,
        color=STATUS_COLORS.get(status, discord.Color.blurple()),
        description=_truncate(detail, 4096) if detail else None,
    )

    embed.add_field(name="狀態", value=f"**{status_label}**", inline=True)
    embed.add_field(
        name="時長",
        value=_duration_text(duration) if current else "—",
        inline=True,
    )

    if requester_id:
        requester = f"<@{requester_id}>"
    else:
        requester = "—"
    embed.add_field(name="點歌者", value=requester, inline=True)

    queue = getattr(state, "queue", None)
    try:
        queue_count = len(queue) if queue is not None else 0
    except TypeError:
        queue_count = 0
    embed.add_field(name="待播歌曲", value=f"{queue_count} 首", inline=True)

    channel_id = _channel_id(getattr(state, "voice", None))
    if channel_id is not None:
        embed.add_field(name="語音頻道", value=f"<#{channel_id}>", inline=True)

    if thumbnail:
        embed.set_thumbnail(url=_truncate(thumbnail, 2048))

    embed.set_footer(text="使用下方按鈕控制播放；只有同一語音頻道的成員可以操作")
    return embed


def build_queue_embed(state: Any, *, limit: int = 20) -> discord.Embed:
    """Build an ephemeral queue listing for the queue button and /queue."""

    current = getattr(state, "current", None)
    queue = list(getattr(state, "queue", ()) or ())
    lines: list[str] = []
    if current is not None:
        title = _truncate(_track_value(current, "title", "未知歌曲"), 180, "未知歌曲")
        lines.append(f"**正在播放**　{title}")

    if queue:
        for index, track in enumerate(queue[:limit], start=1):
            title = _truncate(_track_value(track, "title", "未知歌曲"), 180, "未知歌曲")
            lines.append(f"`{index:02d}`　{title}")
        if len(queue) > limit:
            lines.append(f"… 還有 {len(queue) - limit} 首歌曲")
    elif current is None:
        lines.append("目前沒有待播歌曲。")
    else:
        lines.append("待播清單目前是空的。")

    embed = discord.Embed(
        title="📃 待播清單",
        description="\n".join(lines),
        color=discord.Color.blurple(),
    )
    embed.set_footer(text=f"共 {len(queue)} 首待播歌曲")
    return embed


def build_queue_embeds(state: Any, *, page_size: int = 20) -> list[discord.Embed]:
    """Build every queue page so large queues remain inspectable."""

    page_size = max(1, int(page_size))
    current = getattr(state, "current", None)
    queue = list(getattr(state, "queue", ()) or ())
    page_count = max(1, math.ceil(len(queue) / page_size))
    pages: list[discord.Embed] = []

    for page_index in range(page_count):
        start = page_index * page_size
        page_tracks = queue[start : start + page_size]
        lines: list[str] = []
        if page_index == 0 and current is not None:
            title = _truncate(_track_value(current, "title", "未知歌曲"), 180, "未知歌曲")
            lines.append(f"**正在播放**　{title}")
        if page_tracks:
            for index, track in enumerate(page_tracks, start=start + 1):
                title = _truncate(_track_value(track, "title", "未知歌曲"), 180, "未知歌曲")
                lines.append(f"`{index:02d}`　{title}")
        elif not lines:
            lines.append("目前沒有待播歌曲。")

        embed = discord.Embed(
            title="📃 待播清單",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"第 {page_index + 1} / {page_count} 頁 • 共 {len(queue)} 首待播歌曲")
        pages.append(embed)
    return pages


def build_cache_embed(stats: dict[str, Any], *, config: Any = None) -> discord.Embed:
    """Build the owner-only cache status response."""

    byte_count = stats.get("bytes", 0)
    try:
        byte_count = int(byte_count)
    except (TypeError, ValueError):
        byte_count = 0
    if byte_count >= 1024**3:
        size = f"{byte_count / 1024**3:.2f} GiB"
    elif byte_count >= 1024**2:
        size = f"{byte_count / 1024**2:.2f} MiB"
    elif byte_count >= 1024:
        size = f"{byte_count / 1024:.2f} KiB"
    else:
        size = f"{byte_count} B"

    embed = discord.Embed(title="🎵 音樂快取", color=discord.Color.blurple())
    embed.add_field(name="使用空間", value=size, inline=True)
    embed.add_field(name="檔案數", value=str(stats.get("files", 0)), inline=True)
    embed.add_field(name="保留檔案", value=str(stats.get("pinned_files", 0)), inline=True)

    if config is not None:
        auto_cleanup = getattr(config, "auto_cleanup", None)
        max_cache_mb = getattr(config, "max_cache_mb", None)
        if max_cache_mb is not None:
            embed.add_field(name="空間上限", value=f"{max_cache_mb} MiB", inline=True)
        if auto_cleanup is not None:
            embed.add_field(name="自動清理", value="啟用" if auto_cleanup else "停用", inline=True)
    return embed


async def _response_is_done(interaction: discord.Interaction) -> bool:
    response = getattr(interaction, "response", None)
    if response is None:
        return True
    value = getattr(response, "is_done", False)
    try:
        return bool(value()) if callable(value) else bool(value)
    except TypeError:
        return False


async def _send_ephemeral(interaction: discord.Interaction, content: str) -> None:
    """Reply to an interaction in a way that also works with lightweight test doubles."""

    if not await _response_is_done(interaction):
        response = getattr(interaction, "response", None)
        if response is not None and hasattr(response, "send_message"):
            await response.send_message(content, ephemeral=True)
            return
    followup = getattr(interaction, "followup", None)
    if followup is not None and hasattr(followup, "send"):
        await followup.send(content, ephemeral=True)


async def _defer(interaction: discord.Interaction) -> None:
    if await _response_is_done(interaction):
        return
    response = getattr(interaction, "response", None)
    if response is None or not hasattr(response, "defer"):
        return
    try:
        await response.defer()
    except TypeError:
        await response.defer(thinking=True)


def _interaction_message_matches(interaction: discord.Interaction, message: Any) -> bool:
    """Check a component came from this view's message when IDs are available."""

    incoming = getattr(interaction, "message", None)
    if message is None or incoming is None:
        return True
    expected_id = getattr(message, "id", None)
    incoming_id = getattr(incoming, "id", None)
    return not (expected_id is not None and incoming_id is not None and expected_id != incoming_id)


class MusicControlView(discord.ui.View):
    """Persistent controls for one music voice session.

    The view has no timeout while the session is active.  The cog explicitly
    deactivates it when a session is replaced, stopped, or disconnected.
    """

    def __init__(
        self,
        cog: Any,
        guild_id: int,
        session_id: int,
        *,
        timeout: float | None = None,
    ):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.guild_id = int(guild_id)
        self.session_id = session_id
        self.message: Any = None
        self.disposed = False

    def _service(self) -> Any:
        return getattr(self.cog, "service", getattr(self.cog, "music_service", None))

    def _state(self) -> Any:
        service = self._service()
        return service.get_state(self.guild_id) if service is not None else None

    async def _reject(self, interaction: discord.Interaction, content: str) -> bool:
        await _send_ephemeral(interaction, content)
        return False

    async def _validate(self, interaction: discord.Interaction) -> bool:
        if self.disposed:
            return await self._reject(interaction, "❌ 這個播放面板已失效，請使用最新面板。")

        guild = getattr(interaction, "guild", None)
        if guild is None or getattr(guild, "id", None) != self.guild_id:
            return await self._reject(interaction, "❌ 這個播放面板只屬於原本的伺服器。")

        if not _interaction_message_matches(interaction, self.message):
            return await self._reject(interaction, "❌ 這個播放面板已失效，請使用最新面板。")

        state = self._state()
        if state is None or getattr(state, "session_id", None) != self.session_id:
            return await self._reject(interaction, "❌ 這個播放面板已失效，請使用最新面板。")

        user_voice = getattr(getattr(interaction, "user", None), "voice", None)
        user_channel = getattr(user_voice, "channel", None)
        bot_channel_id = _channel_id(getattr(state, "voice", None))
        user_channel_id = _channel_id(user_channel)
        if user_channel_id is None or (
            bot_channel_id is not None and user_channel_id != bot_channel_id
        ):
            return await self._reject(interaction, "❌ 你必須和機器人位於同一個語音頻道。")

        return True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self._validate(interaction)

    def _set_control_state(self, state: Any = None) -> None:
        state = state or self._state()
        status = str(getattr(state, "status", "idle") if state is not None else "stopped")
        active = not self.disposed and status in {"downloading", "playing", "paused"}
        paused = status == "paused"
        for child in self.children:
            custom_id = getattr(child, "custom_id", "") or ""
            if custom_id.endswith("pause"):
                child.label = "繼續播放" if paused else "暫停"
                child.emoji = "▶️" if paused else "⏸️"
                child.disabled = self.disposed or status not in {"playing", "paused"}
            elif custom_id.endswith("stop"):
                child.disabled = not active
            elif custom_id.endswith("skip"):
                child.disabled = not active
            elif custom_id.endswith("queue"):
                child.disabled = self.disposed or state is None

    async def refresh(self, state: Any = None, *, detail: str | None = None) -> bool:
        """Refresh this message from the current service state."""

        state = state or self._state()
        if state is None or self.message is None:
            return False
        self._set_control_state(state)
        try:
            await self.message.edit(embed=build_now_playing_embed(state, detail=detail), view=self)
        except discord.NotFound:
            self.message = None
            log.debug("music panel message disappeared", exc_info=True)
            return False
        except discord.HTTPException:
            log.debug("music panel message disappeared", exc_info=True)
            return False
        return True

    async def dispose(self, *, state: Any = None, detail: str | None = None) -> None:
        """Disable the view and detach it from future interactions."""

        self.disposed = True
        self._set_control_state(state)
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                if state is not None:
                    await self.message.edit(
                        embed=build_now_playing_embed(state, detail=detail),
                        view=self,
                    )
                else:
                    await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                log.debug("music panel message disappeared during dispose", exc_info=True)
        super().stop()

    async def on_timeout(self) -> None:
        # This is mostly a safety net for tests or a caller that chooses a
        # finite timeout.  Active production panels use timeout=None.
        await self.dispose()

    async def _finish_action(self, interaction: discord.Interaction) -> None:
        refresh = getattr(self.cog, "refresh_panel", None)
        if refresh is not None:
            try:
                await refresh(self.guild_id)
            except Exception:
                log.exception("failed to refresh music panel after button action")

    @discord.ui.button(
        label="暫停",
        emoji="⏸️",
        style=discord.ButtonStyle.primary,
        custom_id="ddpybot_music_pause",
    )
    async def pause_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not await self._validate(interaction):
            return
        await _defer(interaction)
        try:
            await self._service().toggle_pause(self.guild_id)
            await self._finish_action(interaction)
        except Exception as exc:
            log.exception("music pause button failed")
            await _send_ephemeral(interaction, _music_error_text(exc))

    @discord.ui.button(
        label="停止",
        emoji="⏹️",
        style=discord.ButtonStyle.danger,
        custom_id="ddpybot_music_stop",
    )
    async def stop_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not await self._validate(interaction):
            return
        await _defer(interaction)
        try:
            await self._service().stop(self.guild_id)
            await self._finish_action(interaction)
        except Exception as exc:
            log.exception("music stop button failed")
            await _send_ephemeral(interaction, _music_error_text(exc))

    @discord.ui.button(
        label="跳過",
        emoji="⏭️",
        style=discord.ButtonStyle.secondary,
        custom_id="ddpybot_music_skip",
    )
    async def skip_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not await self._validate(interaction):
            return
        await _defer(interaction)
        try:
            await self._service().skip(self.guild_id)
            await self._finish_action(interaction)
        except Exception as exc:
            log.exception("music skip button failed")
            await _send_ephemeral(interaction, _music_error_text(exc))

    @discord.ui.button(
        label="待播清單",
        emoji="📃",
        style=discord.ButtonStyle.secondary,
        custom_id="ddpybot_music_queue",
    )
    async def queue_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not await self._validate(interaction):
            return
        state = self._state()
        pages = build_queue_embeds(state)
        try:
            from views.pagination import PaginationView

            queue_view = PaginationView(pages, interaction.user)
        except Exception:
            queue_view = None
        if not await _response_is_done(interaction):
            await interaction.response.send_message(
                embed=pages[0],
                view=queue_view,
                ephemeral=True,
            )
        elif getattr(interaction, "followup", None) is not None:
            message = await interaction.followup.send(
                embed=pages[0],
                view=queue_view,
                ephemeral=True,
            )
            if queue_view is not None:
                queue_view.message = message
        if queue_view is not None and getattr(queue_view, "message", None) is None:
            original_response = getattr(interaction, "original_response", None)
            if original_response is not None:
                try:
                    queue_view.message = await original_response()
                except (discord.HTTPException, discord.NotFound):
                    pass


class PlaylistConfirmationView(discord.ui.View):
    """Requester-only confirmation before resolving a playlist URL."""

    def __init__(
        self,
        cog: Any,
        requester: Any,
        url: str,
        *,
        single_url: str | None = None,
        next_up: bool = False,
        guild_id: int | None = None,
        voice_channel_id: int | None = None,
        timeout: float | None = 120,
    ):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.requester_id = int(getattr(requester, "id", 0))
        self.guild_id = guild_id if guild_id is not None else _obj_id(getattr(requester, "guild", None))
        user_voice = getattr(getattr(requester, "voice", None), "channel", None)
        self.voice_channel_id = (
            voice_channel_id if voice_channel_id is not None else _channel_id(user_voice)
        )
        self.url = url
        self.single_url = single_url
        self.next_up = next_up
        self.message: Any = None
        self.disposed = False
        self.busy = False

        if single_url is None:
            for child in self.children:
                if (getattr(child, "custom_id", "") or "").endswith("single"):
                    child.disabled = True

    async def _reject(self, interaction: discord.Interaction, content: str) -> bool:
        await _send_ephemeral(interaction, content)
        return False

    async def _check_requester(self, interaction: discord.Interaction) -> bool:
        if self.disposed or self.busy:
            return await self._reject(interaction, "❌ 這個選擇已經失效，請重新輸入指令。")
        if int(getattr(getattr(interaction, "user", None), "id", 0)) != self.requester_id:
            return await self._reject(interaction, "❌ 只有原本輸入指令的人可以選擇。")
        if self.guild_id is not None and _obj_id(getattr(interaction, "guild", None)) != self.guild_id:
            return await self._reject(interaction, "❌ 這個選擇只屬於原本的伺服器。")
        if not _interaction_message_matches(interaction, self.message):
            return await self._reject(interaction, "❌ 這個選擇已經失效，請重新輸入指令。")
        return True

    async def _check_current_voice(self, interaction: discord.Interaction) -> bool:
        if not await self._check_requester(interaction):
            return False
        current_channel = _channel_id(
            getattr(getattr(getattr(interaction, "user", None), "voice", None), "channel", None)
        )
        if current_channel is None or (
            self.voice_channel_id is not None and current_channel != self.voice_channel_id
        ):
            return await self._reject(interaction, "❌ 你已不在原本的語音頻道，請重新輸入指令。")

        state = None
        service = getattr(self.cog, "service", getattr(self.cog, "music_service", None))
        if service is not None and self.guild_id is not None:
            state = service.get_state(self.guild_id)
        bot_channel_id = _channel_id(getattr(state, "voice", None)) if state else None
        if bot_channel_id is not None and bot_channel_id != current_channel:
            return await self._reject(interaction, "❌ 你必須和機器人位於同一個語音頻道。")
        return True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self._check_requester(interaction)

    async def _edit_confirmation(self, content: str) -> None:
        if self.message is not None and hasattr(self.message, "edit"):
            try:
                await self.message.edit(content=content, view=self)
                return
            except (discord.NotFound, discord.HTTPException):
                pass

    async def dispose(self, *, content: str | None = None) -> None:
        """Disable a pending confirmation when its cog is unloaded."""

        self.disposed = True
        self.busy = False
        for child in self.children:
            child.disabled = True
        if content:
            await self._edit_confirmation(content)
        super().stop()

    async def _enqueue(self, interaction: discord.Interaction, url: str, *, playlist: bool) -> None:
        self.busy = True
        for child in self.children:
            child.disabled = True
        await _defer(interaction)
        try:
            channel = getattr(interaction, "channel", None)
            tracks = await self.cog.service.enqueue(
                interaction.user,
                channel,
                url,
                playlist=playlist,
                next_up=self.next_up,
            )
            count = len(tracks or [])
            mode = "插播" if self.next_up else "播放"
            await self._edit_confirmation(f"✅ 已接受 {count} 首歌曲的{mode}要求。")
            self.disposed = True
            pending = getattr(self.cog, "_pending_playlists", None)
            if pending is not None:
                pending.discard(self)
            super().stop()
            refresh = getattr(self.cog, "refresh_panel", None)
            if refresh is not None:
                await refresh(self.guild_id)
        except Exception as exc:
            self.busy = False
            for child in self.children:
                child.disabled = False
            if self.single_url is None:
                for child in self.children:
                    if (getattr(child, "custom_id", "") or "").endswith("single"):
                        child.disabled = True
            log.exception("playlist confirmation enqueue failed")
            await _send_ephemeral(interaction, _music_error_text(exc))

    async def _cancel(self, interaction: discord.Interaction) -> None:
        self.disposed = True
        for child in self.children:
            child.disabled = True
        await _defer(interaction)
        await self._edit_confirmation("已取消加入播放清單。")
        pending = getattr(self.cog, "_pending_playlists", None)
        if pending is not None:
            pending.discard(self)
        super().stop()

    @discord.ui.button(
        label="加入播放清單",
        emoji="📃",
        style=discord.ButtonStyle.primary,
        custom_id="ddpybot_music_playlist",
    )
    async def add_playlist_button(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ):
        if await self._check_current_voice(interaction):
            await self._enqueue(interaction, self.url, playlist=True)

    @discord.ui.button(
        label="只播放這部影片",
        emoji="▶️",
        style=discord.ButtonStyle.secondary,
        custom_id="ddpybot_music_single",
    )
    async def single_track_button(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ):
        if await self._check_current_voice(interaction):
            await self._enqueue(interaction, self.single_url or self.url, playlist=False)

    @discord.ui.button(
        label="取消",
        emoji="✖️",
        style=discord.ButtonStyle.danger,
        custom_id="ddpybot_music_cancel",
    )
    async def cancel_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if await self._check_requester(interaction):
            await self._cancel(interaction)

    async def on_timeout(self) -> None:
        if self.disposed:
            return
        self.disposed = True
        for child in self.children:
            child.disabled = True
        await self._edit_confirmation("⌛ 選擇逾時，請重新輸入指令。")
        pending = getattr(self.cog, "_pending_playlists", None)
        if pending is not None:
            pending.discard(self)
        super().stop()


def _obj_id(obj: Any) -> int | None:
    value = getattr(obj, "id", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _music_error_text(exc: Exception) -> str:
    """Keep service failures user-readable without exposing implementation details."""

    try:
        from services.music_cache import MusicError
    except ImportError:
        MusicError = ()
    if not isinstance(exc, MusicError):
        return "❌ 音樂服務目前無法處理這個要求，請稍後再試。"
    text = str(exc).strip()
    if not text:
        text = "音樂服務目前無法處理這個要求，請稍後再試。"
    return f"❌ {_truncate(text, 900)}"


__all__ = [
    "MusicControlView",
    "PlaylistConfirmationView",
    "build_cache_embed",
    "build_now_playing_embed",
    "build_queue_embed",
    "build_queue_embeds",
]
