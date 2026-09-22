import asyncio
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from services import music_service as music
from services.music_cache import MusicConfig, MusicError, Track


class FakeVoice:
    def __init__(self, channel):
        self.channel = channel
        self.connected = True
        self.paused = False
        self.source = None
        self.after = None
        self.played = []

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return self.source is not None and not self.paused

    def is_paused(self):
        return self.source is not None and self.paused

    def play(self, source, *, after):
        assert self.source is None
        self.source, self.after = source, after
        self.played.append(source)

    def finish(self, error=None):
        source, after = self.source, self.after
        self.source = self.after = None
        self.paused = False
        if source:
            after(error)
            source.cleanup()

    def stop(self):
        self.finish()

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    async def disconnect(self, *, force=False):
        self.stop()
        self.connected = False


class FakeAudio(discord.AudioSource):
    def __init__(self):
        self.cleaned = False

    def read(self):
        return b''

    def is_opus(self):
        return True

    def cleanup(self):
        self.cleaned = True


async def spin_until(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0.002)
    raise AssertionError('state did not settle')


def track(number):
    return Track(str(number), f'Song {number}', f'https://www.youtube.com/watch?v={number}', 10)


def make_service(tmp_path, monkeypatch):
    config = MusicConfig.from_settings({}, tmp_path)
    service = music.MusicService(SimpleNamespace(user=SimpleNamespace(id=999)), config, AsyncMock())
    service.cache = SimpleNamespace(
        resolve=AsyncMock(), acquire=AsyncMock(return_value=Path('audio.webm')),
        release=AsyncMock(), close=AsyncMock(), cleanup=AsyncMock(),
    )
    monkeypatch.setattr(music.shutil, 'which', lambda _: 'ffmpeg')
    monkeypatch.setattr(music.discord.FFmpegOpusAudio, 'from_probe', AsyncMock(side_effect=lambda *a, **k: FakeAudio()))
    channel = SimpleNamespace(id=10, members=[SimpleNamespace(bot=False)])
    channel.permissions_for = lambda _: SimpleNamespace(connect=True, speak=True)
    voice = FakeVoice(channel)
    channel.connect = AsyncMock(return_value=voice)
    guild = SimpleNamespace(id=1, me=SimpleNamespace(), voice_client=None)
    member = SimpleNamespace(id=100, guild=guild, voice=SimpleNamespace(channel=channel))
    return service, member, voice


def test_play_pause_skip_and_release(tmp_path, monkeypatch):
    async def scenario():
        service, member, voice = make_service(tmp_path, monkeypatch)
        first, second = track(1), track(2)
        service.cache.resolve.return_value = [first, second]
        await service.enqueue(member, SimpleNamespace(id=20), 'url')
        await spin_until(lambda: voice.is_playing())
        assert service.get_state(1).current is first
        assert await service.toggle_pause(1) is True
        assert voice.is_paused()
        assert await service.toggle_pause(1) is False
        await service.skip(1)
        await spin_until(lambda: voice.is_playing())
        assert service.get_state(1).current is second
        assert voice.played[0].source.cleaned
        voice.finish()
        await spin_until(lambda: service.get_state(1).status == 'idle')
        assert service.cache.release.await_count == service.cache.acquire.await_count
        await service.close()
    asyncio.run(scenario())


def test_playnext_preserves_order_and_keeps_current(tmp_path, monkeypatch):
    async def scenario():
        service, member, voice = make_service(tmp_path, monkeypatch)
        first, queued, a, b = [track(n) for n in range(4)]
        service.cache.resolve.return_value = [first, queued]
        await service.enqueue(member, SimpleNamespace(id=20), 'url')
        await spin_until(lambda: voice.is_playing())
        service.cache.resolve.return_value = [a, b]
        await service.enqueue(member, SimpleNamespace(id=20), 'url', next_up=True)
        assert service.get_state(1).current is first
        assert list(service.get_state(1).queue) == [a, b, queued]
        await service.close()
        assert all(source.source.cleaned for source in voice.played)
    asyncio.run(scenario())


def test_stop_during_download_cancels_without_playing(tmp_path, monkeypatch):
    async def scenario():
        service, member, voice = make_service(tmp_path, monkeypatch)
        downloading = asyncio.Event()
        cancelled = asyncio.Event()

        async def acquire(_):
            downloading.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        service.cache.acquire.side_effect = acquire
        service.cache.resolve.return_value = [track(1), track(2)]
        await service.enqueue(member, SimpleNamespace(id=20), 'url')
        await downloading.wait()
        await service.stop(1)
        assert cancelled.is_set()
        assert not voice.played
        assert not service.get_state(1).queue
        assert service.get_state(1).status == 'stopped'
        assert voice.connected
        await service.close()
    asyncio.run(scenario())


def test_pending_metadata_cannot_rejoin_after_leave(tmp_path, monkeypatch):
    async def scenario():
        service, member, voice = make_service(tmp_path, monkeypatch)
        entered, ready = asyncio.Event(), asyncio.Event()

        async def resolve(*args, **kwargs):
            entered.set()
            await ready.wait()
            return [track(1)]

        service.cache.resolve.side_effect = resolve
        pending = asyncio.create_task(service.enqueue(member, SimpleNamespace(id=20), 'url'))
        await entered.wait()
        await service.leave(1)
        ready.set()
        with pytest.raises(MusicError, match='重新點歌'):
            await pending
        assert not voice.played
        member.voice.channel.connect.assert_not_awaited()
        await service.close()
    asyncio.run(scenario())


def test_member_must_still_be_in_original_channel(tmp_path, monkeypatch):
    async def scenario():
        service, member, _ = make_service(tmp_path, monkeypatch)

        async def resolve(*args, **kwargs):
            member.voice = None
            return [track(1)]

        service.cache.resolve.side_effect = resolve
        with pytest.raises(MusicError, match='語音頻道'):
            await service.enqueue(member, SimpleNamespace(id=20), 'url')
        assert service.get_state(1) is None
        await service.close()
    asyncio.run(scenario())


def test_empty_countdown_cancelled_on_return_and_bot_members_ignored(tmp_path, monkeypatch):
    async def scenario():
        service, member, voice = make_service(tmp_path, monkeypatch)
        service.config.empty_channel_grace_seconds = 0.04
        state = music.GuildPlayer(1, voice, 20, 1)
        service.players[1] = state
        voice.channel.members = [SimpleNamespace(bot=True)]
        await service.voice_state_changed(member, None, None)
        timer = state.empty_timer
        voice.channel.members.append(SimpleNamespace(bot=False))
        await service.voice_state_changed(member, None, None)
        await asyncio.sleep(0.06)
        assert timer.cancelled()
        assert voice.connected
        voice.channel.members = [SimpleNamespace(bot=True)]
        await service.voice_state_changed(member, None, None)
        await spin_until(lambda: service.get_state(1) is None)
        assert not voice.connected
        await service.close()
    asyncio.run(scenario())


def test_track_failure_advances_queue(tmp_path, monkeypatch):
    async def scenario():
        service, member, voice = make_service(tmp_path, monkeypatch)
        first, second = track(1), track(2)
        service.cache.acquire.side_effect = [MusicError('bad file'), Path('second.webm')]
        service.cache.resolve.return_value = [first, second]
        await service.enqueue(member, SimpleNamespace(id=20), 'url')
        await spin_until(lambda: voice.is_playing())
        assert service.get_state(1).current is second
        assert any(call.args[1] == 'error' for call in service.on_update.await_args_list)
        await service.close()
    asyncio.run(scenario())


def test_guilds_are_independent_and_queue_limit_is_atomic(tmp_path, monkeypatch):
    async def scenario():
        service, member, voice = make_service(tmp_path, monkeypatch)
        service.config.max_queue_size = 2
        state = music.GuildPlayer(1, voice, 20, 1, queue=deque([track(1)]))
        service.players[1] = state
        service.cache.resolve.return_value = [track(2), track(3)]
        with pytest.raises(MusicError, match='最多'):
            await service.enqueue(member, SimpleNamespace(id=20), 'url')
        assert len(state.queue) == 1
        other = music.GuildPlayer(2, FakeVoice(voice.channel), 30, 2, queue=deque([track(9)]))
        service.players[2] = other
        await service.stop(1)
        assert len(other.queue) == 1
        assert other.voice.connected
        await service.close()
    asyncio.run(scenario())


def test_ffmpeg_missing_gives_actionable_error(tmp_path, monkeypatch):
    async def scenario():
        service, member, _ = make_service(tmp_path, monkeypatch)
        monkeypatch.setattr(music.shutil, 'which', lambda _: None)
        with pytest.raises(MusicError, match='FFmpeg'):
            await service.enqueue(member, SimpleNamespace(id=20), 'url')
        service.cache.resolve.assert_not_awaited()
        await service.close()
    asyncio.run(scenario())


def test_notifications_failure_does_not_stop_audio(tmp_path, monkeypatch):
    async def scenario():
        service, member, voice = make_service(tmp_path, monkeypatch)
        service.on_update.side_effect = RuntimeError('no text permission')
        service.cache.resolve.return_value = [track(1)]
        await service.enqueue(member, SimpleNamespace(id=20), 'url')
        await spin_until(lambda: voice.is_playing())
        await service.close()
        assert service.cache.release.await_count == 1
    asyncio.run(scenario())


def test_source_cleanup_is_idempotent():
    async def scenario():
        audio = FakeAudio()
        audio.cleanup = Mock()
        wrapper = music._AudioSource(audio)
        wrapper.cleanup()
        wrapper.cleanup()
        await wrapper.closed.wait()
        audio.cleanup.assert_called_once()
    asyncio.run(scenario())


def test_failed_prefetch_retries_after_current_file_released(tmp_path, monkeypatch):
    async def scenario():
        service, member, voice = make_service(tmp_path, monkeypatch)
        first, second = track(1), track(2)
        service.cache.resolve.return_value = [first, second]
        service.cache.acquire.side_effect = [Path('one.webm'), MusicError('space full'), Path('two.webm')]
        await service.enqueue(member, SimpleNamespace(id=20), 'url')
        await spin_until(lambda: service.cache.acquire.await_count == 2)
        voice.finish()
        await spin_until(lambda: voice.is_playing() and service.get_state(1).current is second)
        service.cache.release.assert_awaited_with(first)
        assert service.cache.acquire.await_count == 3
        await service.close()
    asyncio.run(scenario())


def test_stop_cancels_inflight_prefetch(tmp_path, monkeypatch):
    async def scenario():
        service, member, voice = make_service(tmp_path, monkeypatch)
        first, second = track(1), track(2)
        prefetch_started, prefetch_cancelled = asyncio.Event(), asyncio.Event()

        async def acquire(item):
            if item is first:
                return Path('one.webm')
            prefetch_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                prefetch_cancelled.set()

        service.cache.acquire.side_effect = acquire
        service.cache.resolve.return_value = [first, second]
        await service.enqueue(member, SimpleNamespace(id=20), 'url')
        await prefetch_started.wait()
        await asyncio.wait_for(service.stop(1), 1)
        assert prefetch_cancelled.is_set()
        assert not voice.is_playing()
        assert voice.played[0].source.cleaned
        service.cache.release.assert_awaited_once_with(first)
        await service.close()
    asyncio.run(scenario())


def test_bot_forced_disconnect_releases_session(tmp_path, monkeypatch):
    async def scenario():
        service, member, voice = make_service(tmp_path, monkeypatch)
        service.cache.resolve.return_value = [track(1)]
        await service.enqueue(member, SimpleNamespace(id=20), 'url')
        await spin_until(lambda: voice.is_playing())
        bot_member = SimpleNamespace(id=999, guild=member.guild)
        await service.voice_state_changed(bot_member, SimpleNamespace(channel=voice.channel), SimpleNamespace(channel=None))
        assert service.get_state(1) is None
        assert not voice.connected
        service.cache.release.assert_awaited_once()
        await service.close()
    asyncio.run(scenario())


def test_enqueue_during_idle_notification_starts_next_track(tmp_path, monkeypatch):
    async def scenario():
        service, member, voice = make_service(tmp_path, monkeypatch)
        idle_entered, finish_notification = asyncio.Event(), asyncio.Event()

        async def update(guild_id, event, detail):
            if event == 'idle':
                idle_entered.set()
                await finish_notification.wait()

        service.on_update.side_effect = update
        service.cache.resolve.return_value = [track(1)]
        await service.enqueue(member, SimpleNamespace(id=20), 'url')
        await spin_until(lambda: voice.is_playing())
        voice.finish()
        await idle_entered.wait()
        second = track(2)
        service.cache.resolve.return_value = [second]
        await service.enqueue(member, SimpleNamespace(id=20), 'url')
        finish_notification.set()
        await spin_until(lambda: voice.is_playing())
        assert service.get_state(1).current is second
        await service.close()
    asyncio.run(scenario())
