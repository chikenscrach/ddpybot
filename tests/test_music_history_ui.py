import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from cmds.music import Music
from services.music_cache import MusicError
from views.music_history import MusicHistoryView, _history_embed


class FakeResponse:
    def __init__(self):
        self.done = False
        self.send_message = AsyncMock(side_effect=self._finish)
        self.defer = AsyncMock(side_effect=self._finish)
        self.edit_message = AsyncMock(side_effect=self._finish)

    def is_done(self):
        return self.done

    async def _finish(self, *args, **kwargs):
        self.done = True


def _member(user_id=1, guild_id=99, channel_id=10):
    return SimpleNamespace(
        id=user_id,
        guild=SimpleNamespace(id=guild_id),
        voice=SimpleNamespace(channel=SimpleNamespace(id=channel_id)),
    )


def _interaction(user=None, *, guild_id=99, message_id=500):
    response = FakeResponse()
    message = SimpleNamespace(id=message_id) if message_id is not None else None
    return SimpleNamespace(
        user=user or _member(),
        guild=SimpleNamespace(id=guild_id) if guild_id is not None else None,
        channel=SimpleNamespace(id=20),
        response=response,
        followup=SimpleNamespace(send=AsyncMock(return_value=message)),
        message=message,
    )


def _entry(entry_id, *, requester_id=1, guild_id=99, title=None):
    return {
        "id": entry_id,
        "guild_id": str(guild_id),
        "requester_id": str(requester_id),
        "title": title or f"歌曲 {entry_id}",
        "url": f"https://www.youtube.com/watch?v=video{entry_id}",
        "duration": 185,
        "thumbnail": None,
        "played_at": 1_791_599_400,
    }


def _history_result(items, total=None):
    return {
        "items": items,
        "total": len(items) if total is None else total,
        "limit": 10,
        "offset": 0,
    }


def _view(cog, items, *, total=None, owner_id=1, requester_id=1):
    view = MusicHistoryView(
        cog,
        guild_id=99,
        requester_id=requester_id,
        owner_id=owner_id,
        items=items,
        total=len(items) if total is None else total,
    )
    view.message = SimpleNamespace(id=500, edit=AsyncMock())
    return view


def test_history_command_defaults_to_caller_and_renders_play_records():
    records = [_entry(i) for i in range(1, 3)]
    cog = Music.__new__(Music)
    cog.history = SimpleNamespace(query=Mock(return_value=_history_result(records)))
    user = _member()
    user.voice = None
    interaction = _interaction(user)

    asyncio.run(Music.history_command.callback(cog, interaction))

    cog.history.query.assert_called_once_with(99, requester_id=1, limit=10, offset=0)
    kwargs = interaction.followup.send.call_args.kwargs
    assert kwargs["ephemeral"] is True
    assert isinstance(kwargs["view"], MusicHistoryView)
    text = "\n".join(field.value + field.name for field in kwargs["embed"].fields)
    assert "歌曲 1" in text
    assert "3:05" in text
    assert "<t:1791599400:R>" in text


def test_history_command_can_query_another_member():
    other = _member(user_id=2)
    cog = Music.__new__(Music)
    cog.history = SimpleNamespace(query=Mock(return_value=_history_result([_entry(1, requester_id=2)])))
    interaction = _interaction()

    asyncio.run(Music.history_command.callback(cog, interaction, other))

    cog.history.query.assert_called_once_with(99, requester_id=2, limit=10, offset=0)
    assert "<@2>" in interaction.followup.send.call_args.kwargs["embed"].description


def test_history_view_paginates_ten_records_per_page():
    records = [_entry(i) for i in range(1, 11)]
    next_records = [_entry(i) for i in range(11, 16)]
    query = Mock(side_effect=[_history_result(next_records, total=15)])
    view = _view(SimpleNamespace(history=SimpleNamespace(query=query)), records, total=15)
    interaction = _interaction()

    next_button = next(item for item in view.children if item.custom_id == "ddpybot_music_history_next")
    asyncio.run(next_button.callback(interaction))

    query.assert_called_once_with(99, requester_id=1, limit=10, offset=10)
    assert view.current_page == 1
    assert "歌曲 11" in interaction.response.edit_message.call_args.kwargs["embed"].fields[0].name
    assert view.select.options[0].value == "11"
    assert "<t:" not in view.select.options[0].description


def test_history_embed_bounds_full_field_name_for_long_titles():
    embed = _history_embed(
        [_entry(1, title="長" * 400)],
        requester_id=1,
        page=0,
        total=1,
    )

    assert len(embed.fields[0].name) <= 256
    assert embed.fields[0].name.endswith("…")


@pytest.mark.parametrize(
    ("user_id", "guild_id", "expected"),
    [(2, 99, "只有查詢紀錄的人"), (1, 100, "原本的伺服器")],
)
def test_history_view_rejects_other_user_or_guild(user_id, guild_id, expected):
    view = _view(SimpleNamespace(), [_entry(1)])
    interaction = _interaction(_member(user_id=user_id), guild_id=guild_id)

    allowed = asyncio.run(view.interaction_check(interaction))

    assert allowed is False
    assert expected in interaction.response.send_message.call_args.args[0]


@pytest.mark.parametrize("history_owner_id", [1, 2])
def test_history_quick_play_reloads_scoped_entry_and_enqueues_its_url(history_owner_id):
    entry = _entry(7, requester_id=history_owner_id)
    history = SimpleNamespace(get=Mock(return_value=entry))
    service = SimpleNamespace(get_state=Mock(return_value=None), enqueue=AsyncMock(return_value=[object()]))
    cog = Music.__new__(Music)
    cog.history = history
    cog.service = service
    view = _view(cog, [entry], owner_id=1, requester_id=history_owner_id)
    interaction = _interaction(_member(user_id=1))

    asyncio.run(view.select_track(interaction, "7"))

    history.get.assert_called_once_with(99, 7, requester_id=history_owner_id)
    service.enqueue.assert_awaited_once_with(
        interaction.user,
        interaction.channel,
        entry["url"],
        playlist=False,
        next_up=False,
    )
    assert interaction.followup.send.call_args.kwargs["ephemeral"] is True
    assert "已接受 **1** 首歌曲" in interaction.followup.send.call_args.args[0]
    assert view.busy is False
    assert view.message.edit.await_count == 1
    assert all(option.default is False for option in view.select.options)

    again = _interaction(_member(user_id=1))
    asyncio.run(view.select_track(again, "7"))
    assert service.enqueue.await_count == 2


def test_history_quick_play_shows_enqueue_failure():
    entry = _entry(7)
    cog = Music.__new__(Music)
    cog.history = SimpleNamespace(get=Mock(return_value=entry))
    cog.service = SimpleNamespace(
        get_state=Mock(return_value=None),
        enqueue=AsyncMock(side_effect=MusicError("請先加入語音頻道。")),
    )
    view = _view(cog, [entry])
    interaction = _interaction()

    asyncio.run(view.select_track(interaction, "7"))

    assert "請先加入語音頻道" in interaction.followup.send.call_args.args[0]
    assert interaction.followup.send.call_args.kwargs["ephemeral"] is True
    assert view.busy is False


def test_history_quick_play_rejects_missing_scoped_entry():
    entry = _entry(7)
    cog = Music.__new__(Music)
    cog.history = SimpleNamespace(get=Mock(return_value=None))
    cog.service = SimpleNamespace(get_state=Mock(return_value=None), enqueue=AsyncMock())
    view = _view(cog, [entry])
    interaction = _interaction()

    asyncio.run(view.select_track(interaction, "7"))

    cog.history.get.assert_called_once_with(99, 7, requester_id=1)
    cog.service.enqueue.assert_not_awaited()
    assert "已失效" in interaction.followup.send.call_args.args[0]


def test_history_view_disables_controls_after_timeout():
    view = _view(SimpleNamespace(), [_entry(1)])

    asyncio.run(view.on_timeout())

    assert all(item.disabled for item in view.children)
    view.message.edit.assert_awaited_once_with(view=view)
    assert view.disposed is True


def test_music_cog_injects_history_database(monkeypatch):
    history = object()
    created = {}

    class FakeService:
        def __init__(self, _bot, _config, _callback, *, history):
            created["history"] = history

    monkeypatch.setattr("cmds.music.MusicHistoryDatabase", lambda: history)
    monkeypatch.setattr("cmds.music.MusicService", FakeService)
    monkeypatch.setattr("cmds.music.MusicConfig.from_settings", lambda *_args: object())
    monkeypatch.setattr("cmds.music.settings", {})
    monkeypatch.setattr("cmds.music.PROJECT_ROOT", ".")

    cog = Music(SimpleNamespace())

    assert cog.history is history
    assert created["history"] is history
