import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from cmds import task as task_module
from services.database import PingDatabase


@pytest.fixture
def task_cog(tmp_path, monkeypatch):
    db = PingDatabase(tmp_path / 'ping_count.db')
    monkeypatch.setattr(task_module, 'PingDatabase', lambda: db)
    monkeypatch.setattr(task_module, 'DAILY_CHANNEL_ID', None)
    cog = task_module.Task(SimpleNamespace())
    yield cog
    cog.cog_unload()


def make_context(user_id=1):
    return SimpleNamespace(
        author=SimpleNamespace(id=user_id, mention=f'<@{user_id}>'),
        guild=SimpleNamespace(get_member=lambda _: None),
        send=AsyncMock(),
    )


def embed_fields(ctx):
    return {field.name: field.value for field in ctx.send.call_args.kwargs['embed'].fields}


def test_ping_rank_total_includes_members_outside_top(task_cog):
    for user_id in (1, 1, 1, 2, 2, 3):
        task_cog.db.add_ping(user_id)
    ctx = make_context()

    asyncio.run(task_module.Task.ping_rank.callback(task_cog, ctx, top=1))

    embed = ctx.send.call_args.kwargs['embed']
    assert '未知用戶 (1)' in embed.description
    assert '未知用戶 (2)' not in embed.description
    assert embed_fields(ctx)['標記總數'] == '**6** 次'


def test_ping_rank_empty_database_shows_zero_total(task_cog):
    ctx = make_context()

    asyncio.run(task_module.Task.ping_rank.callback(task_cog, ctx))

    embed = ctx.send.call_args.kwargs['embed']
    assert '目前還沒有任何人被標過' in embed.description
    assert embed_fields(ctx)['標記總數'] == '**0** 次'


@pytest.mark.parametrize('other_pings', [0, 2])
def test_ping_stats_unpinged_author_shows_zero_and_no_time(task_cog, other_pings):
    for _ in range(other_pings):
        task_cog.db.add_ping(2)
    ctx = make_context()

    asyncio.run(task_module.Task.ping_stats.callback(task_cog, ctx))

    assert ctx.send.call_args.kwargs['embed'].description == ctx.author.mention
    fields = embed_fields(ctx)
    assert fields['被標記次數'] == '**0** 次'
    assert fields['標記總數'] == f'**{other_pings}** 次'
    assert fields['被標記比例'] == '**0.00%**'
    assert fields['上次被標記時間'] == '尚未被標記'


def test_ping_stats_selected_member_shows_share_and_last_ping(task_cog):
    for user_id in (1, 1, 2):
        task_cog.db.add_ping(user_id)
    member = SimpleNamespace(id=2, mention='<@2>')
    last_ping = task_cog.db.get_last_ping(member.id)
    ctx = make_context()

    asyncio.run(task_module.Task.ping_stats.callback(task_cog, ctx, member=member))

    assert ctx.send.call_args.kwargs['embed'].description == member.mention
    fields = embed_fields(ctx)
    assert fields['被標記次數'] == '**1** 次'
    assert fields['標記總數'] == '**3** 次'
    assert fields['被標記比例'] == '**33.33%**'
    assert f'<t:{last_ping}:F>' in fields['上次被標記時間']
    assert f'<t:{last_ping}:R>' in fields['上次被標記時間']


def test_ping_stats_old_count_has_unknown_time(task_cog):
    task_cog.db.conn.execute('INSERT INTO ping_counts (user_id, count) VALUES (1, 5)')
    task_cog.db.conn.commit()
    ctx = make_context()

    asyncio.run(task_module.Task.ping_stats.callback(task_cog, ctx))

    fields = embed_fields(ctx)
    assert fields['被標記次數'] == '**5** 次'
    assert fields['被標記比例'] == '**100.00%**'
    assert '尚無時間紀錄' in fields['上次被標記時間']
    assert '尚未被標記' not in fields['上次被標記時間']


@pytest.mark.parametrize('send_fails', [False, True])
def test_daily_ping_records_only_after_successful_send(task_cog, monkeypatch, send_fails):
    member = SimpleNamespace(id=1, mention='<@1>', bot=False)

    async def send_message(*args, **kwargs):
        assert task_cog.db.get_count(member.id) == 0
        assert task_cog.db.get_last_ping(member.id) is None
        if send_fails:
            raise discord.Forbidden(
                SimpleNamespace(status=403, reason='Forbidden'), 'Missing Permissions'
            )

    channel = SimpleNamespace(
        guild=SimpleNamespace(members=[member]),
        send=AsyncMock(side_effect=send_message),
    )
    task_cog.bot.get_channel = Mock(return_value=channel)
    monkeypatch.setattr(task_module, 'DAILY_CHANNEL_ID', 123)

    if send_fails:
        with pytest.raises(discord.Forbidden):
            asyncio.run(task_cog.daily_ping())
        assert task_cog.db.get_count(member.id) == 0
        assert task_cog.db.get_last_ping(member.id) is None
    else:
        asyncio.run(task_cog.daily_ping())
        assert task_cog.db.get_count(member.id) == 1
        assert task_cog.db.get_last_ping(member.id) is not None

    channel.send.assert_awaited_once()
    assert channel.send.call_args.args[0] == '每日隨機標 <@1>'
    assert channel.send.call_args.kwargs['allowed_mentions'].users is True
