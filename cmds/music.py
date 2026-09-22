"""Slash commands for the guild music player."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from core.classes import CogExtension
from core.config import PROJECT_ROOT, settings
from services.music_cache import MusicConfig, MusicError, has_playlist, single_video_url
from services.music_service import (
    MusicService,
)
from views.music import (
    MusicControlView,
    PlaylistConfirmationView,
    _music_error_text,
    _response_is_done,
    build_cache_embed,
    build_now_playing_embed,
    build_queue_embeds,
)
from views.pagination import PaginationView

log = logging.getLogger(__name__)


async def _owner_check(interaction: discord.Interaction) -> bool:
    """Application-command check matching ``commands.is_owner`` semantics."""

    client = getattr(interaction, "client", None)
    user = getattr(interaction, "user", None)
    checker = getattr(client, "is_owner", None)
    if checker is None:
        return False
    result = checker(user)
    if hasattr(result, "__await__"):
        result = await result
    return bool(result)


async def _send_ephemeral(interaction: discord.Interaction, content: str, **kwargs: Any) -> Any:
    """Send an ephemeral response after either a fresh or deferred interaction."""

    if not await _response_is_done(interaction):
        response = getattr(interaction, "response", None)
        if response is not None and hasattr(response, "send_message"):
            return await response.send_message(content, ephemeral=True, **kwargs)
    followup = getattr(interaction, "followup", None)
    if followup is not None and hasattr(followup, "send"):
        return await followup.send(content, ephemeral=True, **kwargs)
    return None


async def _defer_ephemeral(interaction: discord.Interaction) -> None:
    if await _response_is_done(interaction):
        return
    response = getattr(interaction, "response", None)
    if response is None or not hasattr(response, "defer"):
        return
    try:
        await response.defer(ephemeral=True, thinking=True)
    except TypeError:
        # Small test doubles often expose only ``defer()``.
        await response.defer()


def _id(value: Any) -> int | None:
    value = getattr(value, "id", value)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _voice_channel(member: Any) -> Any:
    return getattr(getattr(member, "voice", None), "channel", None)


def _voice_channel_id(member: Any) -> int | None:
    channel = _voice_channel(member)
    return _id(channel)


def _state_voice_channel_id(state: Any) -> int | None:
    voice = getattr(state, "voice", None)
    channel = getattr(voice, "channel", None)
    return _id(channel if channel is not None else voice)


def _count_text(count: int, *, next_up: bool = False) -> str:
    mode = "插播" if next_up else "播放"
    return f"✅ 已接受 **{count}** 首歌曲的{mode}要求。"


def _clip(value: Any, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


class Music(CogExtension):
    """Guild music commands and the now-playing panel lifecycle."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        config = MusicConfig.from_settings(settings, PROJECT_ROOT)
        self.service = MusicService(bot, config, self._on_service_update)
        # One active panel per guild.  A lock is essential because a download
        # notification and a runner notification can arrive back-to-back.
        self._panels: dict[int, MusicControlView] = {}
        self._pending_playlists: set[PlaylistConfirmationView] = set()
        self._panel_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def cog_load(self):
        await self.service.start()

    async def cog_unload(self):
        # Views are retired before closing the service so no component can
        # race a disconnect during shutdown.
        for guild_id, view in list(self._panels.items()):
            try:
                await view.dispose(state=self.service.get_state(guild_id))
            except Exception:
                log.exception("failed to dispose music panel for guild %s", guild_id)
        self._panels.clear()
        for view in list(self._pending_playlists):
            try:
                await view.dispose()
            except Exception:
                log.exception("failed to dispose pending playlist view")
        self._pending_playlists.clear()
        await self.service.close()

    async def _safe_state(self, guild_id: int | None) -> Any:
        if guild_id is None:
            return None
        try:
            return self.service.get_state(guild_id)
        except Exception:
            log.exception("failed to read music state for guild %s", guild_id)
            return None

    async def _on_service_update(
        self,
        guild_id: int,
        event: str,
        detail: str | None = None,
    ) -> None:
        """Render the latest service state into the guild's panel."""

        lock = self._panel_locks[guild_id]
        async with lock:
            state = await self._safe_state(guild_id)
            old_view = self._panels.get(guild_id)

            # A disconnect callback is emitted while the service still
            # exposes its final state.  Keep that final panel visible but make
            # every control inert, then discard the view mapping.
            retiring = event in {"stopped", "disconnected"}
            if state is None:
                if old_view is not None:
                    await old_view.dispose(detail=detail)
                    self._panels.pop(guild_id, None)
                return

            if old_view is not None and old_view.session_id != getattr(state, "session_id", None):
                await old_view.dispose(state=state, detail="播放工作階段已更新。")
                self._panels.pop(guild_id, None)
                old_view = None

            if old_view is None:
                channel = self.bot.get_channel(getattr(state, "channel_id", 0))
                if channel is None or not hasattr(channel, "send"):
                    log.warning("music text channel %s is unavailable", getattr(state, "channel_id", 0))
                    return
                view = MusicControlView(
                    self,
                    guild_id,
                    getattr(state, "session_id", 0),
                )
                view._set_control_state(state)
                try:
                    message = await channel.send(
                        embed=build_now_playing_embed(state, detail=detail),
                        view=view,
                    )
                except (discord.HTTPException, discord.Forbidden):
                    log.exception("failed to send music panel for guild %s", guild_id)
                    return
                view.message = message
                old_view = view
                self._panels[guild_id] = view
            else:
                old_view._set_control_state(state)
                try:
                    refreshed = await old_view.refresh(state, detail=detail)
                    if not refreshed:
                        self._panels.pop(guild_id, None)
                except Exception:
                    log.exception("failed to update music panel for guild %s", guild_id)

            if event == "error" and detail:
                await self._send_playback_error(state, detail)

            if retiring:
                # Stop and leave keep the final message as an audit trail but
                # immediately invalidate all of its controls.  The next
                # enqueue receives a fresh view, even when the voice session
                # ID happens to be reused by a test double.
                await old_view.dispose(state=state, detail=detail)
                if self._panels.get(guild_id) is old_view:
                    self._panels.pop(guild_id, None)

    async def refresh_panel(self, guild_id: int) -> None:
        """Refresh a panel after a component action without invoking service."""

        lock = self._panel_locks[guild_id]
        async with lock:
            view = self._panels.get(guild_id)
            state = await self._safe_state(guild_id)
            if view is None or state is None:
                return
            if view.session_id != getattr(state, "session_id", None):
                await view.dispose(state=state, detail="播放工作階段已更新。")
                self._panels.pop(guild_id, None)
                return
            refreshed = await view.refresh(state)
            if not refreshed:
                self._panels.pop(guild_id, None)

    async def _send_playback_error(self, state: Any, detail: str) -> None:
        channel = self.bot.get_channel(getattr(state, "channel_id", 0))
        if channel is None or not hasattr(channel, "send"):
            return
        current = getattr(state, "current", None)
        title = _clip(getattr(current, "title", None) or "歌曲", 180)
        message = f"⚠️ 無法播放〈{title}〉：{_clip(detail, 700)}；已跳過。"
        try:
            await channel.send(
                message,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except TypeError:
            # A small fake channel used by an offline test may only accept the
            # content positional argument.
            await channel.send(message)
        except (discord.HTTPException, discord.Forbidden):
            log.debug("failed to send music playback error", exc_info=True)

    async def _require_voice(self, interaction: discord.Interaction) -> tuple[bool, Any]:
        guild = getattr(interaction, "guild", None)
        if guild is None:
            await _send_ephemeral(interaction, "❌ 音樂指令只能在伺服器中使用。")
            return False, None

        member = getattr(interaction, "user", None)
        channel = _voice_channel(member)
        if channel is None:
            await _send_ephemeral(interaction, "❌ 請先加入語音頻道。")
            return False, None

        state = await self._safe_state(_id(guild))
        if state is not None:
            bot_channel_id = _state_voice_channel_id(state)
            member_channel_id = _id(channel)
            if bot_channel_id is not None and bot_channel_id != member_channel_id:
                await _send_ephemeral(interaction, "❌ 你必須和機器人位於同一個語音頻道。")
                return False, None
        return True, channel

    async def _enqueue(
        self,
        interaction: discord.Interaction,
        url: str,
        *,
        playlist: bool = False,
        next_up: bool = False,
    ) -> list[Any]:
        """Enqueue after the interaction has been deferred."""

        member = getattr(interaction, "user", None)
        text_channel = getattr(interaction, "channel", None)
        return await self.service.enqueue(
            member,
            text_channel,
            url,
            playlist=playlist,
            next_up=next_up,
        )

    async def _run_enqueue_command(
        self,
        interaction: discord.Interaction,
        url: str,
        *,
        next_up: bool,
    ) -> None:
        await _defer_ephemeral(interaction)
        allowed, _channel = await self._require_voice(interaction)
        if not allowed:
            return

        try:
            if has_playlist(url):
                linked_url = single_video_url(url)
                view = PlaylistConfirmationView(
                    self,
                    interaction.user,
                    url,
                    single_url=linked_url,
                    next_up=next_up,
                    guild_id=_id(interaction.guild),
                    voice_channel_id=_voice_channel_id(interaction.user),
                )
                action = "插播" if next_up else "加入播放清單"
                message = await interaction.followup.send(
                    f"這個網址包含播放清單，要{action}，還是只播放其中的連結影片？",
                    view=view,
                    ephemeral=True,
                )
                view.message = message
                self._pending_playlists.add(view)
                return

            tracks = await self._enqueue(interaction, url, next_up=next_up)
            await _send_ephemeral(interaction, _count_text(len(tracks or []), next_up=next_up))
        except MusicError as exc:
            await _send_ephemeral(interaction, _music_error_text(exc))
        except (discord.HTTPException, discord.Forbidden):
            log.exception("failed to send music command response")
            await _send_ephemeral(interaction, "❌ Discord 回應失敗，請稍後再試。")
        except Exception as exc:
            log.exception("music enqueue command failed")
            await _send_ephemeral(interaction, _music_error_text(exc))

    @app_commands.command(name="play", description="播放 YouTube 影片或播放清單")
    @app_commands.describe(url="YouTube 影片或播放清單網址")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, url: str):
        await self._run_enqueue_command(interaction, url, next_up=False)

    @app_commands.command(name="playnext", description="將 YouTube 歌曲插入目前歌曲後播放")
    @app_commands.describe(url="YouTube 影片或播放清單網址")
    @app_commands.guild_only()
    async def playnext(self, interaction: discord.Interaction, url: str):
        await self._run_enqueue_command(interaction, url, next_up=True)

    @app_commands.command(name="leave", description="讓機器人離開語音頻道並清除播放佇列")
    @app_commands.guild_only()
    async def leave(self, interaction: discord.Interaction):
        await _defer_ephemeral(interaction)
        allowed, _channel = await self._require_voice(interaction)
        if not allowed:
            return
        try:
            state = await self._safe_state(_id(interaction.guild))
            if state is None:
                await _send_ephemeral(interaction, "目前沒有加入語音頻道。")
                return
            await self.service.leave(_id(interaction.guild))
            await _send_ephemeral(interaction, "✅ 已離開語音頻道。")
        except MusicError as exc:
            await _send_ephemeral(interaction, _music_error_text(exc))
        except Exception as exc:
            log.exception("music leave command failed")
            await _send_ephemeral(interaction, _music_error_text(exc))

    @app_commands.command(name="queue", description="查看目前的音樂待播清單")
    @app_commands.guild_only()
    async def queue(self, interaction: discord.Interaction):
        await _defer_ephemeral(interaction)
        allowed, _channel = await self._require_voice(interaction)
        if not allowed:
            return
        state = await self._safe_state(_id(interaction.guild))
        if state is None:
            await _send_ephemeral(interaction, "目前沒有播放中的音樂。")
            return
        pages = build_queue_embeds(state)
        view = PaginationView(pages, interaction.user)
        message = await interaction.followup.send(
            embed=pages[0],
            view=view,
            ephemeral=True,
        )
        view.message = message

    @app_commands.command(name="musiccache", description="查看或清理音樂快取（僅限 Bot 擁有者）")
    @app_commands.describe(action="要查看狀態，或清理未使用的音檔")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="查看狀態", value="status"),
            app_commands.Choice(name="清理快取", value="clear"),
        ]
    )
    async def musiccache(self, interaction: discord.Interaction, action: str):
        await _defer_ephemeral(interaction)
        if not await _owner_check(interaction):
            # The decorator handles normal Discord dispatch.  Keeping this
            # guard in the callback also protects direct calls in tests and
            # alternate command routers.
            await _send_ephemeral(interaction, "❌ 只有 Bot 擁有者可以管理音樂快取。")
            return

        try:
            if action == "clear":
                result = await self.service.cache.cleanup(force=True)
                removed = result.get("removed_files", 0)
                freed = result.get("freed_bytes", 0)
                await _send_ephemeral(
                    interaction,
                    f"✅ 已清理 {removed} 個音檔，釋放 {_format_bytes(freed)}。",
                )
                return

            stats = await self.service.cache.stats()
            await _send_ephemeral(
                interaction,
                "",
                embed=build_cache_embed(stats, config=getattr(self.service, "config", None)),
            )
        except MusicError as exc:
            await _send_ephemeral(interaction, _music_error_text(exc))
        except Exception as exc:
            log.exception("music cache command failed")
            await _send_ephemeral(interaction, _music_error_text(exc))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: Any, after: Any):
        try:
            await self.service.voice_state_changed(member, before, after)
        except Exception:
            log.exception("music voice state update failed")


def _format_bytes(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(number) < 1024 or unit == "TiB":
            return f"{number:.1f} {unit}" if unit != "B" else f"{int(number)} B"
        number /= 1024
    return "0 B"


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))


__all__ = ["Music", "setup"]
