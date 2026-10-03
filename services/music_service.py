"""Per-guild voice playback; downloaded audio is leased until FFmpeg has closed it."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import secrets
import shutil
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import discord

from services.music_cache import MusicCache, MusicConfig, MusicError, Track

log = logging.getLogger(__name__)
UpdateCallback = Callable[[int, str, str | None], Awaitable[None]]


class LoopMode(str, Enum):
    OFF = 'off'
    QUEUE = 'queue'
    TRACK = 'track'


class _AudioSource(discord.AudioSource):
    """Signal *after* audio cleanup, unlike VoiceClient's after callback."""

    def __init__(self, source: discord.AudioSource):
        self.source = source
        self.closed = asyncio.Event()
        self.loop = asyncio.get_running_loop()
        self._lock = threading.Lock()
        self._cleaned = False

    def read(self) -> bytes:
        return self.source.read()

    def is_opus(self) -> bool:
        return self.source.is_opus()

    @property
    def _current_error(self):
        return getattr(self.source, '_current_error', None)

    def cleanup(self):
        with self._lock:
            if self._cleaned:
                return
            self._cleaned = True
            try:
                self.source.cleanup()
            finally:
                if not self.loop.is_closed():
                    self.loop.call_soon_threadsafe(self.closed.set)


class _PreparedTrack:
    def __init__(self, cache: MusicCache, track: Track):
        self.cache = cache
        self.track = track
        self.acquired = False
        self.task = asyncio.create_task(self._acquire())
        # Prefetch failures are reported when this item reaches the front.
        self.task.add_done_callback(self._consume_exception)

    @staticmethod
    def _consume_exception(task):
        if not task.cancelled():
            task.exception()

    async def _acquire(self) -> Path:
        path = await self.cache.acquire(self.track)
        self.acquired = True
        return path

    async def close(self):
        cleanup = asyncio.create_task(self._close())
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup
            raise

    async def _close(self):
        if not self.task.done():
            self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        if self.acquired:
            self.acquired = False
            await self.cache.release(self.track)


@dataclass
class GuildPlayer:
    guild_id: int
    voice: discord.VoiceClient
    channel_id: int
    session_id: int
    current: Track | None = None
    queue: deque[Track] = field(default_factory=deque)
    loop_mode: LoopMode = LoopMode.OFF
    status: str = 'idle'
    runner: asyncio.Task | None = None
    prefetch: _PreparedTrack | None = None
    empty_timer: asyncio.Task | None = None
    disconnecting: bool = False
    progress_started: float | None = None
    progress_elapsed: float = 0.0


class MusicService:
    def __init__(self, bot, config: MusicConfig, on_update: UpdateCallback):
        self.bot = bot
        self.config = config
        self.on_update = on_update
        self.cache = MusicCache(config)
        self.players: dict[int, GuildPlayer] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._revisions: dict[int, int] = {}
        self._sessions = itertools.count(1)
        self._cleanup_task: asyncio.Task | None = None
        self._requests: set[asyncio.Task] = set()
        self._closed = False
        self.generation = secrets.token_hex(12)

    def get_state(self, guild_id: int) -> GuildPlayer | None:
        return self.players.get(guild_id)

    @staticmethod
    def _elapsed(state: GuildPlayer) -> float:
        elapsed = state.progress_elapsed
        if state.progress_started is not None:
            elapsed += max(0, time.monotonic() - state.progress_started)
        if state.current and state.current.duration:
            elapsed = min(elapsed, state.current.duration)
        return round(max(0, elapsed), 2)

    def snapshot(self, guild_id: int) -> dict:
        """Copy browser-safe state on the bot loop; never expose runtime objects."""
        def song(track):
            if track is None:
                return None
            return {
                'title': track.title, 'url': track.url, 'duration': track.duration,
                'thumbnail': track.thumbnail,
                'requester_id': str(track.requester_id) if track.requester_id else None,
            }

        state = self.players.get(guild_id)
        channel = state.voice.channel if state else None
        return {
            'guild_id': str(guild_id), 'generation': self.generation,
            'session_id': state.session_id if state else None,
            'status': state.status if state else 'idle',
            'loop_mode': state.loop_mode.value if state else 'off',
            'voice_channel_id': str(channel.id) if channel else None,
            'voice_channel_name': getattr(channel, 'name', '') if channel else None,
            'current': song(state.current) if state else None,
            'queue': [song(track) for track in state.queue] if state else [],
            'elapsed_seconds': self._elapsed(state) if state and state.current else 0,
        }

    def _lock(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(guild_id, asyncio.Lock())

    async def start(self):
        if self.config.auto_cleanup and self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self):
        while True:
            try:
                await self.cache.cleanup()
            except Exception:
                log.exception('音樂快取自動清理失敗')
            await asyncio.sleep(self.config.cleanup_interval_seconds)

    async def _notify(self, state: GuildPlayer, event: str, detail: str | None = None):
        try:
            await self.on_update(state.guild_id, event, detail)
        except Exception:
            # Missing text permissions must never stop playback or leak a file lease.
            log.exception('無法更新伺服器 %s 的音樂面板', state.guild_id)

    @staticmethod
    def _member_channel(member):
        channel = member.voice.channel if member.voice else None
        if channel is None:
            raise MusicError('請先加入語音頻道。')
        if isinstance(channel, discord.StageChannel):
            raise MusicError('目前只支援一般語音頻道，尚不支援舞台頻道。')
        return channel

    async def enqueue(self, member, text_channel, url: str, *, playlist=False, next_up=False):
        if self._closed:
            raise MusicError('音樂服務正在關閉，請稍後再試。')
        channel = self._member_channel(member)
        guild = member.guild
        guild_id = guild.id
        revision = self._revisions.get(guild_id, 0)
        current = self.players.get(guild_id)
        if current and current.voice.channel.id != channel.id:
            raise MusicError('請先加入機器人所在的語音頻道。')
        if not shutil.which(self.config.ffmpeg_executable):
            raise MusicError('找不到 FFmpeg，請機器人管理員安裝並檢查音樂設定。')
        request = asyncio.current_task()
        self._requests.add(request)
        try:
            tracks = await self.cache.resolve(url, playlist=playlist, requester_id=member.id)
            if not tracks:
                raise MusicError('這個網址沒有可播放的歌曲。')
            async with self._lock(guild_id):
                if self._closed or revision != self._revisions.get(guild_id, 0):
                    raise MusicError('點歌期間播放已停止或機器人已離開，請重新點歌。')
                if self._member_channel(member).id != channel.id:
                    raise MusicError('點歌期間你已更換語音頻道，請重新點歌。')
                state = self.players.get(guild_id)
                if state and (not state.voice.is_connected() or state.disconnecting):
                    raise MusicError('語音連線已中斷，請稍後重新點歌。')
                if state and state.voice.channel.id != channel.id:
                    raise MusicError('請先加入機器人所在的語音頻道。')
                if len(tracks) + (len(state.queue) if state else 0) > self.config.max_queue_size:
                    raise MusicError(f'待播清單最多 {self.config.max_queue_size} 首，請減少加入數量。')
                if state is None:
                    me = guild.me
                    permissions = channel.permissions_for(me)
                    if not permissions.connect or not permissions.speak:
                        raise MusicError('機器人需要此語音頻道的「連線」與「說話」權限。')
                    voice = guild.voice_client
                    if voice and voice.is_connected() and voice.channel.id != channel.id:
                        raise MusicError('請先加入機器人所在的語音頻道。')
                    try:
                        if voice and not voice.is_connected():
                            await voice.disconnect(force=True)
                            voice = None
                        if voice is None:
                            voice = await channel.connect(self_deaf=True, timeout=20)
                    except BaseException as exc:
                        if guild.voice_client:
                            with contextlib.suppress(Exception):
                                await guild.voice_client.disconnect(force=True)
                        if isinstance(exc, asyncio.CancelledError):
                            raise
                        log.warning('語音連線失敗: %s', type(exc).__name__)
                        raise MusicError('無法加入語音頻道，請檢查語音依賴、權限或連線。') from exc
                    state = GuildPlayer(guild_id, voice, text_channel.id, next(self._sessions))
                    self.players[guild_id] = state
                state.channel_id = text_channel.id
                if next_up:
                    state.queue.extendleft(reversed(tracks))
                    await self._discard_prefetch(state)
                else:
                    state.queue.extend(tracks)
                if (
                    state.status in ('playing', 'paused')
                    and state.loop_mode != LoopMode.TRACK
                    and state.prefetch is None
                    and state.queue
                ):
                    state.prefetch = _PreparedTrack(self.cache, state.queue[0])
                self._ensure_runner(state)
                self._refresh_empty_timer(state)
                await self._notify(state, 'queue')
                return tracks
        finally:
            self._requests.discard(request)

    def _ensure_runner(self, state: GuildPlayer):
        if state.runner is None or state.runner.done():
            state.runner = asyncio.create_task(self._run(state))

    async def _discard_prefetch(self, state: GuildPlayer):
        prepared, state.prefetch = state.prefetch, None
        if prepared:
            await prepared.close()

    async def _run(self, state: GuildPlayer):
        try:
            while True:
                while state.queue and state.voice.is_connected():
                    state.current = state.queue.popleft()
                    try:
                        await self._play(state)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        log.exception('伺服器 %s 播放歌曲失敗', state.guild_id)
                        detail = str(exc) if isinstance(exc, MusicError) else '下載或播放失敗，已跳過這首歌曲。'
                        await self._notify(state, 'error', detail)
                    else:
                        # Only naturally completed tracks rejoin the queue;
                        # a skip cancels this runner and failures stay removed.
                        if state.loop_mode == LoopMode.TRACK:
                            state.queue.appendleft(state.current)
                        elif state.loop_mode == LoopMode.QUEUE:
                            state.queue.append(state.current)
                    finally:
                        state.current = None
                        state.progress_started = None
                        state.progress_elapsed = 0.0
                await self._discard_prefetch(state)
                state.status = 'idle'
                await self._notify(state, 'idle')
                # Enqueue may have added work while the idle message was sent.
                if not state.queue or not state.voice.is_connected():
                    state.runner = None
                    return
        finally:
            await self._discard_prefetch(state)

    async def _play(self, state: GuildPlayer):
        prepared, state.prefetch = state.prefetch, None
        if prepared and prepared.track is not state.current:
            await prepared.close()
            prepared = None
        if prepared and prepared.task.done() and (
            prepared.task.cancelled() or prepared.task.exception() is not None
        ):
            # A prefetch can run out of space while the previous song is pinned.
            # Retry as the foreground item after that song has released its file.
            await prepared.close()
            prepared = None
        prepared = prepared or _PreparedTrack(self.cache, state.current)
        source = None
        started = False
        try:
            state.progress_elapsed = 0.0
            state.progress_started = None
            state.status = 'downloading'
            await self._notify(state, 'downloading')
            path = await prepared.task
            audio = await discord.FFmpegOpusAudio.from_probe(
                str(path), executable=self.config.ffmpeg_executable, options='-vn',
            )
            source = _AudioSource(audio)
            loop = asyncio.get_running_loop()
            finished = loop.create_future()

            def complete(error):
                if not finished.done():
                    finished.set_result(error)

            def after(error):
                if not loop.is_closed():
                    loop.call_soon_threadsafe(complete, error)

            state.voice.play(source, after=after)
            started = True
            state.progress_started = time.monotonic()
            state.status = 'playing'
            if state.queue and state.loop_mode != LoopMode.TRACK:
                state.prefetch = _PreparedTrack(self.cache, state.queue[0])
            await self._notify(state, 'playing')
            error = await finished
            if error:
                raise MusicError('音訊播放中斷，已跳過這首歌曲。')
        finally:
            cleanup = asyncio.create_task(self._finish_audio(state, source, started, prepared))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise

    async def _finish_audio(self, state, source, started, prepared):
        try:
            if source:
                if started:
                    state.voice.stop()
                    try:
                        await asyncio.wait_for(source.closed.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        await asyncio.to_thread(source.cleanup)
                else:
                    await asyncio.to_thread(source.cleanup)
        finally:
            await prepared.close()

    def _require_state(self, guild_id: int) -> GuildPlayer:
        state = self.players.get(guild_id)
        if state is None or state.disconnecting or not state.voice.is_connected():
            raise MusicError('機器人目前沒有加入語音頻道。')
        return state

    async def toggle_pause(self, guild_id: int) -> bool:
        async with self._lock(guild_id):
            state = self._require_state(guild_id)
            await self._pause_locked(state, not state.voice.is_paused())
            return state.status == 'paused'

    async def _pause_locked(self, state: GuildPlayer, paused: bool):
        if not (state.voice.is_paused() or state.voice.is_playing()):
            raise MusicError('目前沒有正在播放的歌曲。')
        if paused and not state.voice.is_paused():
            state.progress_elapsed = self._elapsed(state)
            state.progress_started = None
            state.voice.pause()
            state.status = 'paused'
        elif not paused and state.voice.is_paused():
            state.voice.resume()
            state.progress_started = time.monotonic()
            state.status = 'playing'
        await self._notify(state, state.status)

    async def set_loop_mode(
        self, guild_id: int, mode: LoopMode | str, *, toggle: bool = False,
    ) -> LoopMode:
        try:
            mode = LoopMode(mode)
        except ValueError:
            raise MusicError('無效的循環模式，請選擇關閉、播放清單循環或單曲循環。') from None
        async with self._lock(guild_id):
            state = self._require_state(guild_id)
            if toggle and state.loop_mode == mode:
                mode = LoopMode.OFF
            return await self._set_loop_locked(state, mode)

    async def _set_loop_locked(self, state: GuildPlayer, mode: LoopMode) -> LoopMode:
        if mode != LoopMode.OFF and state.current is None and not state.queue:
            raise MusicError('目前沒有可循環播放的歌曲，請先點歌。')
        state.loop_mode = mode
        if mode == LoopMode.TRACK:
            await self._discard_prefetch(state)
        elif state.status in ('playing', 'paused') and state.prefetch is None and state.queue:
            state.prefetch = _PreparedTrack(self.cache, state.queue[0])
        await self._notify(state, 'loop')
        return mode

    async def _halt(self, state: GuildPlayer):
        runner, state.runner = state.runner, None
        if runner:
            runner.cancel()
        # Cancel the speculative download promptly as well as the current song.
        await self._discard_prefetch(state)
        if runner:
            await asyncio.gather(runner, return_exceptions=True)
        await self._discard_prefetch(state)
        state.current = None
        state.progress_started = None
        state.progress_elapsed = 0.0

    async def skip(self, guild_id: int):
        async with self._lock(guild_id):
            state = self._require_state(guild_id)
            await self._skip_locked(state)

    async def _skip_locked(self, state: GuildPlayer):
        if state.current is None:
            raise MusicError('目前沒有可跳過的歌曲。')
        await self._halt(state)
        self._ensure_runner(state)

    async def stop(self, guild_id: int):
        async with self._lock(guild_id):
            state = self._require_state(guild_id)
            await self._stop_locked(state)

    async def _stop_locked(self, state: GuildPlayer):
        guild_id = state.guild_id
        self._revisions[guild_id] = self._revisions.get(guild_id, 0) + 1
        state.loop_mode = LoopMode.OFF
        state.queue.clear()
        await self._halt(state)
        state.status = 'stopped'
        await self._notify(state, 'stopped')

    async def dashboard_control(
        self, guild_id: int, action: str, *, session_id: int, generation: str, mode=None,
    ) -> dict:
        """Called only after HTTP owner authorization; validate under the mutation lock."""
        async with self._lock(guild_id):
            state = self._require_state(guild_id)
            if self._closed or generation != self.generation or session_id != state.session_id:
                raise MusicError('播放工作階段已更新，請重新整理後再操作。')
            if action in ('pause', 'resume'):
                await self._pause_locked(state, action == 'pause')
            elif action == 'skip':
                await self._skip_locked(state)
            elif action == 'stop':
                await self._stop_locked(state)
            elif action == 'leave':
                self._revisions[guild_id] = self._revisions.get(guild_id, 0) + 1
                await self._leave_locked(state)
            elif action == 'loop':
                try:
                    loop_mode = LoopMode(mode)
                except (ValueError, TypeError):
                    raise MusicError('無效的循環模式。') from None
                await self._set_loop_locked(state, loop_mode)
            else:
                raise MusicError('不支援的音樂操作。')
            return self.snapshot(guild_id)

    async def leave(self, guild_id: int):
        async with self._lock(guild_id):
            self._revisions[guild_id] = self._revisions.get(guild_id, 0) + 1
            state = self.players.get(guild_id)
            if state:
                await self._leave_locked(state)

    async def _leave_locked(self, state: GuildPlayer):
        state.disconnecting = True
        state.loop_mode = LoopMode.OFF
        timer, state.empty_timer = state.empty_timer, None
        if timer and timer is not asyncio.current_task():
            timer.cancel()
            await asyncio.gather(timer, return_exceptions=True)
        state.queue.clear()
        await self._halt(state)
        try:
            await state.voice.disconnect(force=True)
        finally:
            state.status = 'disconnected'
            await self._notify(state, 'disconnected')
            self.players.pop(state.guild_id, None)

    @staticmethod
    def _has_listeners(state: GuildPlayer) -> bool:
        return any(not member.bot for member in state.voice.channel.members)

    def _refresh_empty_timer(self, state: GuildPlayer):
        if self._has_listeners(state):
            if state.empty_timer:
                state.empty_timer.cancel()
                state.empty_timer = None
        elif state.empty_timer is None or state.empty_timer.done():
            state.empty_timer = asyncio.create_task(self._leave_when_empty(state))

    async def _leave_when_empty(self, state: GuildPlayer):
        await asyncio.sleep(self.config.empty_channel_grace_seconds)
        async with self._lock(state.guild_id):
            if self.players.get(state.guild_id) is state and not self._has_listeners(state):
                self._revisions[state.guild_id] = self._revisions.get(state.guild_id, 0) + 1
                await self._leave_locked(state)

    async def voice_state_changed(self, member, before, after):
        state = self.players.get(member.guild.id)
        if state is None or state.disconnecting:
            return
        if self.bot.user and member.id == self.bot.user.id and after.channel is None:
            await self.leave(state.guild_id)
        else:
            self._refresh_empty_timer(state)

    async def close(self):
        self._closed = True
        requests = [task for task in self._requests if task is not asyncio.current_task()]
        for task in requests:
            task.cancel()
        await asyncio.gather(*requests, return_exceptions=True)
        if self._cleanup_task:
            self._cleanup_task.cancel()
            await asyncio.gather(self._cleanup_task, return_exceptions=True)
            self._cleanup_task = None
        for guild_id in list(self.players):
            try:
                await self.leave(guild_id)
            except Exception:
                log.exception('關閉伺服器 %s 的語音連線失敗', guild_id)
        await self.cache.close()
