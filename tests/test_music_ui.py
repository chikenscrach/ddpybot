import asyncio
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from services.music_cache import MusicError
from services.music_service import LoopMode
from views.music import (
    LOOP_MODE_LABELS,
    MusicControlView,
    PlaylistConfirmationView,
    build_now_playing_embed,
    build_queue_embeds,
)


class FakeResponse:
    def __init__(self):
        self.done = False
        self.send_message = AsyncMock(side_effect=self._sent)
        self.defer = AsyncMock(side_effect=self._deferred)

    def is_done(self):
        return self.done

    async def _sent(self, *args, **kwargs):
        self.done = True

    async def _deferred(self, *args, **kwargs):
        self.done = True


def _member(user_id=1, channel_id=10, guild_id=99):
    channel = SimpleNamespace(id=channel_id)
    return SimpleNamespace(
        id=user_id,
        guild=SimpleNamespace(id=guild_id),
        voice=SimpleNamespace(channel=channel),
    )


def _interaction(user, *, guild_id=99, message_id=None):
    response = FakeResponse()
    interaction = SimpleNamespace(
        user=user,
        guild=SimpleNamespace(id=guild_id),
        response=response,
        followup=SimpleNamespace(send=AsyncMock()),
        message=SimpleNamespace(id=message_id) if message_id is not None else None,
    )
    return interaction


def _state(*, session_id=1, channel_id=10, status="playing", loop_mode=LoopMode.OFF):
    track = SimpleNamespace(
        title="A very long song title " + "x" * 300,
        url="https://www.youtube.com/watch?v=abc",
        duration=3723,
        thumbnail="https://img.example/cover.jpg",
        requester_id=42,
    )
    return SimpleNamespace(
        guild_id=99,
        session_id=session_id,
        status=status,
        loop_mode=loop_mode,
        current=track,
        queue=deque(SimpleNamespace(title=f"queue-{i}") for i in range(45)),
        voice=SimpleNamespace(channel=SimpleNamespace(id=channel_id)),
    )


def test_now_playing_embed_contains_track_details_and_bounded_fields():
    embed = build_now_playing_embed(_state(), detail="e" * 5000)

    assert embed.title.startswith("🎶 ")
    assert len(embed.title) <= 256
    assert len(embed.description) <= 4096
    assert embed.url == "https://www.youtube.com/watch?v=abc"
    assert any(field.name == "時長" and field.value == "1:02:03" for field in embed.fields)
    assert any(field.name == "點歌者" and field.value == "<@42>" for field in embed.fields)


def test_queue_pages_expose_all_tracks():
    pages = build_queue_embeds(_state(), page_size=20)

    assert len(pages) == 3
    text = "\n".join(page.description for page in pages)
    assert "queue-0" in text
    assert "queue-44" in text


@pytest.mark.parametrize('mode', list(LoopMode))
def test_panels_and_queue_pages_display_loop_mode(mode):
    state = _state(loop_mode=mode)
    embed = build_now_playing_embed(state)
    assert any(
        field.name == '循環模式' and field.value == LOOP_MODE_LABELS[mode]
        for field in embed.fields
    )
    assert all(LOOP_MODE_LABELS[mode] in page.footer.text for page in build_queue_embeds(state))


@pytest.mark.parametrize('mode', [LoopMode.QUEUE, LoopMode.TRACK])
def test_loop_buttons_set_mode_and_highlight_active_mode(mode):
    state = _state(loop_mode=mode)
    service = SimpleNamespace(
        get_state=lambda _guild_id: state,
        set_loop_mode=AsyncMock(return_value=mode),
    )
    cog = SimpleNamespace(service=service, refresh_panel=AsyncMock())
    view = MusicControlView(cog, guild_id=99, session_id=1)
    view._set_control_state(state)
    buttons = {child.custom_id: child for child in view.children}
    for candidate in [LoopMode.QUEUE, LoopMode.TRACK]:
        button = buttons[f'ddpybot_music_loop_{candidate.value}']
        expected = discord.ButtonStyle.success if candidate == mode else discord.ButtonStyle.secondary
        assert button.style == expected
        assert not button.disabled

    interaction = _interaction(_member())
    _click(view, f'ddpybot_music_loop_{mode.value}', interaction)
    service.set_loop_mode.assert_awaited_once_with(99, mode.value, toggle=True)
    cog.refresh_panel.assert_awaited_once_with(99)
    interaction.response.defer.assert_awaited_once()

    state.status = 'stopped'
    state.loop_mode = LoopMode.OFF
    view._set_control_state(state)
    assert all(
        buttons[f'ddpybot_music_loop_{candidate.value}'].disabled
        for candidate in [LoopMode.QUEUE, LoopMode.TRACK]
    )


@pytest.mark.parametrize('mode', [LoopMode.QUEUE, LoopMode.TRACK])
@pytest.mark.parametrize('reason', ['wrong_channel', 'stale_session', 'disposed'])
def test_loop_buttons_reject_unauthorized_or_stale_interactions(mode, reason):
    state = _state(session_id=2 if reason == 'stale_session' else 1)
    service = SimpleNamespace(get_state=lambda _guild_id: state, set_loop_mode=AsyncMock())
    cog = SimpleNamespace(service=service)
    view = MusicControlView(cog, guild_id=99, session_id=1)
    view.disposed = reason == 'disposed'
    interaction = _interaction(_member(channel_id=11 if reason == 'wrong_channel' else 10))
    _click(view, f'ddpybot_music_loop_{mode.value}', interaction)
    service.set_loop_mode.assert_not_awaited()
    assert interaction.response.send_message.call_args.kwargs['ephemeral'] is True


def test_loop_button_reports_service_error_ephemerally():
    state = _state()
    service = SimpleNamespace(
        get_state=lambda _guild_id: state,
        set_loop_mode=AsyncMock(side_effect=MusicError('目前沒有可循環播放的歌曲，請先點歌。')),
    )
    view = MusicControlView(SimpleNamespace(service=service), guild_id=99, session_id=1)
    interaction = _interaction(_member())
    _click(view, 'ddpybot_music_loop_queue', interaction)
    assert '請先點歌' in interaction.followup.send.call_args.args[0]
    assert interaction.followup.send.call_args.kwargs['ephemeral'] is True


@pytest.mark.parametrize('mode', list(LoopMode))
def test_loop_command_sets_mode_and_confirms_selection(mode):
    from cmds.music import Music

    state = _state()
    cog = Music.__new__(Music)
    cog.service = SimpleNamespace(
        get_state=lambda _guild_id: state,
        set_loop_mode=AsyncMock(return_value=mode),
    )
    interaction = _interaction(_member())
    asyncio.run(Music.loop.callback(cog, interaction, mode.value))
    cog.service.set_loop_mode.assert_awaited_once_with(99, mode.value)
    assert LOOP_MODE_LABELS[mode] in interaction.followup.send.call_args.args[0]
    assert interaction.followup.send.call_args.kwargs['ephemeral'] is True
    assert {choice.value for choice in Music.loop.parameters[0].choices} == {'off', 'queue', 'track'}


@pytest.mark.parametrize('reason', ['wrong_channel', 'no_voice', 'no_guild'])
def test_loop_command_requires_same_voice_channel(reason):
    from cmds.music import Music

    cog = Music.__new__(Music)
    cog.service = SimpleNamespace(get_state=lambda _guild_id: _state(), set_loop_mode=AsyncMock())
    user = _member(channel_id=11 if reason == 'wrong_channel' else 10)
    interaction = _interaction(user)
    if reason == 'no_voice':
        user.voice = None
    elif reason == 'no_guild':
        interaction.guild = None
    asyncio.run(Music.loop.callback(cog, interaction, 'queue'))
    cog.service.set_loop_mode.assert_not_awaited()
    assert interaction.followup.send.call_args.kwargs['ephemeral'] is True


def test_loop_command_reports_missing_songs_ephemerally():
    from cmds.music import Music

    cog = Music.__new__(Music)
    cog.service = SimpleNamespace(
        get_state=lambda _guild_id: _state(),
        set_loop_mode=AsyncMock(side_effect=MusicError('目前沒有可循環播放的歌曲，請先點歌。')),
    )
    interaction = _interaction(_member())
    asyncio.run(Music.loop.callback(cog, interaction, 'track'))
    assert '請先點歌' in interaction.followup.send.call_args.args[0]
    assert interaction.followup.send.call_args.kwargs['ephemeral'] is True


def test_music_control_rejects_stale_session_and_wrong_channel():
    state = _state(session_id=2)
    service = SimpleNamespace(get_state=lambda guild_id: state)
    cog = SimpleNamespace(service=service)
    view = MusicControlView(cog, guild_id=99, session_id=1)

    stale = _interaction(_member(channel_id=10))
    assert asyncio.run(view.interaction_check(stale)) is False
    assert "失效" in stale.response.send_message.call_args.args[0]

    state.session_id = 1
    wrong_channel = _interaction(_member(channel_id=11))
    assert asyncio.run(view.interaction_check(wrong_channel)) is False
    assert "同一個語音頻道" in wrong_channel.response.send_message.call_args.args[0]


def test_playlist_confirmation_requires_original_requester_and_voice_channel():
    requester = _member(user_id=7, channel_id=10)
    cog = SimpleNamespace(service=SimpleNamespace(get_state=lambda _guild_id: None))
    view = PlaylistConfirmationView(
        cog,
        requester,
        "https://www.youtube.com/playlist?list=abc",
        single_url="https://www.youtube.com/watch?v=xyz",
        guild_id=99,
        voice_channel_id=10,
    )

    other = _interaction(_member(user_id=8, channel_id=10))
    assert asyncio.run(view.interaction_check(other)) is False
    assert "原本輸入指令" in other.response.send_message.call_args.args[0]

    moved = _interaction(_member(user_id=7, channel_id=11))
    assert asyncio.run(view._check_current_voice(moved)) is False
    assert "原本的語音頻道" in moved.response.send_message.call_args.args[0]


def _click(view, custom_id, interaction):
    button = next(child for child in view.children if child.custom_id == custom_id)
    return asyncio.run(button.callback(interaction))


def test_playlist_confirmation_adds_playlist_once_and_rejects_repeat():
    requester = _member(user_id=7, channel_id=10)
    service = SimpleNamespace(
        get_state=lambda _guild_id: None,
        enqueue=AsyncMock(return_value=[SimpleNamespace(title="one")]),
    )
    cog = SimpleNamespace(service=service, refresh_panel=AsyncMock())
    view = PlaylistConfirmationView(
        cog,
        requester,
        "https://www.youtube.com/playlist?list=abc",
        single_url="https://www.youtube.com/watch?v=xyz",
        guild_id=99,
        voice_channel_id=10,
    )
    view.message = SimpleNamespace(edit=AsyncMock(), id=123)

    interaction = _interaction(requester, message_id=123)
    _click(view, "ddpybot_music_playlist", interaction)
    service.enqueue.assert_awaited_once_with(
        requester,
        None,
        "https://www.youtube.com/playlist?list=abc",
        playlist=True,
        next_up=False,
    )

    # A second click on the now-retired view must not enqueue a duplicate.
    repeat = _interaction(requester, message_id=123)
    _click(view, "ddpybot_music_playlist", repeat)
    assert service.enqueue.await_count == 1


def test_playlist_confirmation_single_video_and_cancel_do_not_enqueue_playlist():
    requester = _member(user_id=7, channel_id=10)
    service = SimpleNamespace(
        get_state=lambda _guild_id: None,
        enqueue=AsyncMock(return_value=[SimpleNamespace(title="one")]),
    )
    cog = SimpleNamespace(service=service, refresh_panel=AsyncMock())

    single = PlaylistConfirmationView(
        cog,
        requester,
        "https://www.youtube.com/watch?v=xyz&list=abc",
        single_url="https://www.youtube.com/watch?v=xyz",
        guild_id=99,
        voice_channel_id=10,
    )
    single.message = SimpleNamespace(edit=AsyncMock(), id=1)
    _click(single, "ddpybot_music_single", _interaction(requester, message_id=1))
    service.enqueue.assert_awaited_once_with(
        requester,
        None,
        "https://www.youtube.com/watch?v=xyz",
        playlist=False,
        next_up=False,
    )

    cancel = PlaylistConfirmationView(
        cog,
        requester,
        "https://www.youtube.com/playlist?list=abc",
        single_url=None,
        guild_id=99,
        voice_channel_id=10,
    )
    cancel.message = SimpleNamespace(edit=AsyncMock(), id=2)
    _click(cancel, "ddpybot_music_cancel", _interaction(requester, message_id=2))
    assert service.enqueue.await_count == 1
    assert cancel.disposed is True


def test_musiccache_non_owner_never_cleans_global_cache():
    cache = SimpleNamespace(cleanup=AsyncMock())
    bot = SimpleNamespace(is_owner=AsyncMock(return_value=False))
    cog = SimpleNamespace(bot=bot, service=SimpleNamespace(cache=cache))
    interaction = _interaction(_member(user_id=7), guild_id=99)
    interaction.client = bot

    from cmds.music import Music

    asyncio.run(Music.musiccache.callback(cog, interaction, "clear"))
    cache.cleanup.assert_not_awaited()
    assert "Bot 擁有者" in interaction.followup.send.call_args.args[0]


def test_stopped_and_disconnected_panels_are_retired_and_stale():
    from collections import defaultdict

    from cmds.music import Music

    state = _state(session_id=3, status="playing")
    service = SimpleNamespace(get_state=lambda _guild_id: state)
    channel = SimpleNamespace(send=AsyncMock())
    bot = SimpleNamespace(get_channel=lambda _channel_id: channel)
    cog = Music.__new__(Music)
    cog.bot = bot
    cog.service = service
    cog._panels = {}
    cog._panel_locks = defaultdict(__import__("asyncio").Lock)

    view = MusicControlView(cog, 99, 3)
    view.message = SimpleNamespace(id=7, edit=AsyncMock())
    cog._panels[99] = view
    state.status = "stopped"
    asyncio.run(cog._on_service_update(99, "stopped"))
    assert view.disposed is True
    assert 99 not in cog._panels
    stale = _interaction(_member(channel_id=10), message_id=7)
    assert asyncio.run(view.interaction_check(stale)) is False

    # A disconnect notification with no remaining state also retires a fresh view.
    state.status = "playing"
    service.get_state = lambda _guild_id: state
    disconnected = MusicControlView(cog, 99, 4)
    disconnected.message = SimpleNamespace(id=8, edit=AsyncMock())
    cog._panels[99] = disconnected
    service.get_state = lambda _guild_id: None
    asyncio.run(cog._on_service_update(99, "disconnected"))
    assert disconnected.disposed is True
