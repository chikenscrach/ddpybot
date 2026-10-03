import asyncio
import json
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services import music_service as music
from services.music_cache import MusicConfig, MusicError, Track


class FakeVoice:
    def __init__(self, channel):
        self.channel = channel
        self.connected = True
        self.paused = False
        self.source = None

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return self.source is not None and not self.paused

    def is_paused(self):
        return self.source is not None and self.paused

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    async def disconnect(self, *, force=False):
        self.source = None
        self.paused = False
        self.connected = False


def make_service(tmp_path):
    config = MusicConfig.from_settings({}, tmp_path)
    service = music.MusicService(SimpleNamespace(user=SimpleNamespace(id=999)), config, AsyncMock())
    service.cache = SimpleNamespace(
        close=AsyncMock(),
        cleanup=AsyncMock(),
        acquire=AsyncMock(return_value=Path("track.webm")),
        release=AsyncMock(),
    )
    channel = SimpleNamespace(id=10, name="voice")
    return service, FakeVoice(channel)


def add_player(service, voice, *, guild_id=1, session_id=1):
    state = music.GuildPlayer(guild_id, voice, 20, session_id)
    service.players[guild_id] = state
    return state


def track(track_id, *, requester_id=200, duration=60):
    return Track(
        str(track_id),
        f"Song {track_id}",
        f"https://www.youtube.com/watch?v={track_id}",
        duration,
        requester_id=requester_id,
    )


async def spin_until(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0.002)
    raise AssertionError("playback state did not settle")


def test_snapshot_is_json_safe_uses_string_snowflakes_and_returns_copies(tmp_path):
    async def scenario():
        service, voice = make_service(tmp_path)
        guild_id = 2**64 - 1
        channel_id = guild_id - 1
        requester_id = guild_id - 2
        voice.channel = SimpleNamespace(id=channel_id, name="large-id voice")
        state = add_player(service, voice, guild_id=guild_id, session_id=42)
        state.current = track("current", requester_id=requester_id)
        state.queue.extend([track("queued", requester_id=requester_id)])
        state.status = "playing"

        snapshot = service.snapshot(guild_id)
        json.dumps(snapshot)
        assert snapshot["guild_id"] == str(guild_id)
        assert snapshot["voice_channel_id"] == str(channel_id)
        assert snapshot["session_id"] == 42
        assert snapshot["current"]["requester_id"] == str(requester_id)
        assert snapshot["queue"][0]["requester_id"] == str(requester_id)

        snapshot["current"]["title"] = "changed in response"
        snapshot["queue"].clear()
        snapshot["status"] = "stopped"
        next_snapshot = service.snapshot(guild_id)
        assert next_snapshot["current"]["title"] == "Song current"
        assert len(next_snapshot["queue"]) == 1
        assert next_snapshot["status"] == "playing"
        await service.close()

    asyncio.run(scenario())


def test_progress_uses_monotonic_time_and_freezes_while_paused(tmp_path, monkeypatch):
    async def scenario():
        service, voice = make_service(tmp_path)
        clock = SimpleNamespace(value=100.0)
        monkeypatch.setattr(
            music,
            "time",
            SimpleNamespace(monotonic=lambda: clock.value),
        )
        state = add_player(service, voice)
        state.current = track(1, duration=60)
        state.status = "playing"
        state.progress_elapsed = 3.0
        state.progress_started = 100.0
        voice.source = object()

        clock.value = 105.25
        assert service.snapshot(1)["elapsed_seconds"] == 8.25
        tokens = {"session_id": state.session_id, "generation": service.generation}

        await service.dashboard_control(1, "pause", **tokens)
        assert voice.is_paused()
        assert state.status == "paused"
        assert state.progress_elapsed == 8.25
        assert state.progress_started is None

        clock.value = 200.0
        assert service.snapshot(1)["elapsed_seconds"] == 8.25
        await service.dashboard_control(1, "pause", **tokens)
        assert voice.is_paused()
        assert service.snapshot(1)["elapsed_seconds"] == 8.25

        await service.dashboard_control(1, "resume", **tokens)
        resumed_at = state.progress_started
        assert resumed_at == 200.0
        assert state.status == "playing"
        await service.dashboard_control(1, "resume", **tokens)
        assert state.progress_started == resumed_at
        clock.value = 205.25
        assert service.snapshot(1)["elapsed_seconds"] == 13.5

        voice.source = None
        await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("stale", ["generation", "session"])
def test_stale_dashboard_tokens_cannot_change_current_player(tmp_path, stale):
    async def scenario():
        service, voice = make_service(tmp_path)
        state = add_player(service, voice, guild_id=1, session_id=72)
        current = track("new-session")
        queued = track("queued")
        state.current = current
        state.queue.append(queued)
        state.status = "playing"
        voice.source = object()

        generation = service.generation + "-old" if stale == "generation" else service.generation
        session_id = 71 if stale == "session" else state.session_id
        with pytest.raises(MusicError, match="播放工作階段已更新"):
            await service.dashboard_control(
                1,
                "stop",
                session_id=session_id,
                generation=generation,
            )

        assert service.players[1] is state
        assert state.current is current
        assert list(state.queue) == [queued]
        assert state.status == "playing"
        assert voice.is_playing()
        voice.source = None
        await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["stop", "loop", "skip"])
def test_dashboard_controls_match_existing_music_operations(tmp_path, action):
    async def exercise(use_dashboard):
        service, voice = make_service(tmp_path / ("dashboard" if use_dashboard else "discord"))
        state = add_player(service, voice)
        first, following = track("first"), track("following")
        state.current = first
        state.queue = deque([following])
        state.status = "playing"

        if action == "stop":
            state.loop_mode = music.LoopMode.QUEUE
            if use_dashboard:
                await service.dashboard_control(
                    1,
                    "stop",
                    session_id=state.session_id,
                    generation=service.generation,
                )
            else:
                await service.stop(1)
            outcome = (state.status, state.current, tuple(state.queue), state.loop_mode)
            assert outcome == ("stopped", None, (), music.LoopMode.OFF)
        elif action == "loop":
            state.queue.clear()
            if use_dashboard:
                await service.dashboard_control(
                    1,
                    "loop",
                    session_id=state.session_id,
                    generation=service.generation,
                    mode="queue",
                )
            else:
                await service.set_loop_mode(1, music.LoopMode.QUEUE)
            outcome = (state.current, tuple(state.queue), state.loop_mode)
            assert outcome == (first, (), music.LoopMode.QUEUE)
        else:
            played = []

            async def play_next(current_state):
                played.append(current_state.current)

            service._play = play_next
            state.runner = asyncio.create_task(asyncio.Event().wait())
            if use_dashboard:
                await service.dashboard_control(
                    1,
                    "skip",
                    session_id=state.session_id,
                    generation=service.generation,
                )
            else:
                await service.skip(1)
            await spin_until(lambda: state.runner is None)
            outcome = (
                tuple(item.title for item in played),
                state.status,
                state.current,
                tuple(state.queue),
            )
            assert outcome == (("Song following",), "idle", None, ())

        await service.close()
        return outcome

    async def scenario():
        dashboard_result = await exercise(True)
        legacy_result = await exercise(False)
        assert dashboard_result == legacy_result

    asyncio.run(scenario())


def test_dashboard_control_rejects_unknown_action_without_mutating_player(tmp_path):
    async def scenario():
        service, voice = make_service(tmp_path)
        state = add_player(service, voice)
        current = track("current")
        queued = track("queued")
        state.current = current
        state.queue.append(queued)
        state.status = "playing"
        voice.source = object()

        with pytest.raises(MusicError, match="不支援的音樂操作"):
            await service.dashboard_control(
                1,
                "erase",
                session_id=state.session_id,
                generation=service.generation,
            )

        assert state.current is current
        assert list(state.queue) == [queued]
        assert state.status == "playing"
        assert voice.is_playing()
        voice.source = None
        await service.close()

    asyncio.run(scenario())
