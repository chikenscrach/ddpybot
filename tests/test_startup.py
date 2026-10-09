import asyncio
import logging
import re
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from cmds import startup as startup_module
from services.database import StartupNotificationDatabase


@pytest.fixture
def startup_env(tmp_path, monkeypatch):
    db_path = tmp_path / "startup_notifications.db"
    databases = []

    def database_factory():
        db = StartupNotificationDatabase(db_path)
        databases.append(db)
        return db

    monkeypatch.setattr(startup_module, "StartupNotificationDatabase", database_factory)
    bot = make_bot()
    cog = startup_module.Startup(bot)
    yield SimpleNamespace(bot=bot, cog=cog, db_path=db_path, databases=databases)
    for db in databases:
        db.close()


def make_bot(guilds=None):
    guilds = guilds or {}
    bot = SimpleNamespace(startup_notifications_sent=False)
    bot.get_guild = Mock(side_effect=lambda guild_id: guilds.get(guild_id))
    bot.fetch_channel = AsyncMock()
    return bot


def make_guild(guild_id, channel=None, *, bot_member=True):
    guild = SimpleNamespace(id=guild_id, me=object() if bot_member else None)
    if channel is not None:
        channel.guild = guild
    guild.get_channel = Mock(
        side_effect=lambda channel_id: channel if channel and channel.id == channel_id else None
    )
    return guild


def make_channel(channel_id, guild, *, view=True, send=True):
    channel = Mock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.guild = guild
    channel.mention = f"<#{channel_id}>"
    channel.send = AsyncMock()
    channel.permissions_for = Mock(
        return_value=SimpleNamespace(view_channel=view, send_messages=send)
    )
    return channel


def make_interaction(guild, *, manage_guild=True):
    return SimpleNamespace(
        guild=guild,
        permissions=SimpleNamespace(manage_guild=manage_guild),
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )


def run_startupnotify(cog, interaction, action, channel=None):
    asyncio.run(startup_module.Startup.startupnotify.callback(cog, interaction, action, channel))


def test_startupnotify_sets_replaces_disables_and_persists_per_guild(startup_env):
    cog = startup_env.cog
    other_guild = 22
    cog.db.set_channel(other_guild, 220)
    guild = make_guild(11)

    first_channel = make_channel(110, guild)
    first = make_interaction(guild)
    run_startupnotify(cog, first, "set", first_channel)
    assert cog.db.get_channels() == {11: 110, other_guild: 220}
    first.response.defer.assert_awaited_once_with(ephemeral=True)
    assert first.followup.send.call_args.kwargs["ephemeral"] is True

    replacement = make_channel(111, guild)
    second = make_interaction(guild)
    run_startupnotify(cog, second, "set", replacement)
    assert cog.db.get_channels() == {11: 111, other_guild: 220}

    disabled = make_interaction(guild)
    run_startupnotify(cog, disabled, "disable")
    assert cog.db.get_channels() == {other_guild: 220}

    cog.db.close()
    reopened = StartupNotificationDatabase(startup_env.db_path)
    try:
        assert reopened.get_channels() == {other_guild: 220}
    finally:
        reopened.close()


def test_startupnotify_is_guild_only_and_defaults_to_manage_guild():
    command = startup_module.Startup.startupnotify

    assert command.guild_only is True
    assert command.default_permissions.manage_guild is True


@pytest.mark.parametrize(
    "reason",
    [
        "dm",
        "no_manage_guild",
        "missing_channel",
        "cross_guild_channel",
        "disable_with_channel",
        "bot_not_in_guild",
        "no_view_permission",
        "no_send_permission",
    ],
)
def test_startupnotify_rejects_invalid_context_or_channel(startup_env, reason):
    guild = make_guild(11, bot_member=reason != "bot_not_in_guild")
    permissions = {
        "no_view_permission": (False, True),
        "no_send_permission": (True, False),
    }.get(reason, (True, True))
    channel = make_channel(110, guild, view=permissions[0], send=permissions[1])
    interaction = make_interaction(guild, manage_guild=reason != "no_manage_guild")
    action = "set"

    if reason == "dm":
        interaction.guild = None
    elif reason == "missing_channel":
        channel = None
    elif reason == "cross_guild_channel":
        channel.guild = SimpleNamespace(id=99)
    elif reason == "disable_with_channel":
        action = "disable"

    run_startupnotify(startup_env.cog, interaction, action, channel)

    assert interaction.response.send_message.call_args.kwargs["ephemeral"] is True
    interaction.response.defer.assert_not_awaited()
    assert startup_env.cog.db.get_channels() == {}


def test_startupnotify_reports_database_write_failure_without_success(startup_env, monkeypatch):
    guild = make_guild(11)
    channel = make_channel(110, guild)
    interaction = make_interaction(guild)
    monkeypatch.setattr(
        startup_env.cog.db,
        "set_channel",
        Mock(side_effect=sqlite3.OperationalError("database is locked")),
    )

    run_startupnotify(startup_env.cog, interaction, "set", channel)

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    response = interaction.followup.send.call_args.args[0]
    assert "無法儲存" in response
    assert "已設定" not in response
    assert interaction.followup.send.call_args.kwargs["ephemeral"] is True


def test_first_ready_sends_only_configured_channel_with_timestamp_and_no_mentions(startup_env):
    cog = startup_env.cog
    guild = make_guild(11)
    channel = make_channel(110, guild)
    guild.get_channel.side_effect = None
    guild.get_channel.return_value = channel
    guilds = {11: guild, 22: make_guild(22)}
    startup_env.bot.get_guild.side_effect = lambda guild_id: guilds.get(guild_id)
    cog.db.set_channel(11, channel.id)

    asyncio.run(cog.on_ready())
    asyncio.run(cog.on_ready())

    channel.send.assert_awaited_once()
    message = channel.send.call_args.args[0]
    assert "啟動" in message
    assert re.search(r"<t:\d+:[tTdDfFR]>", message)
    allowed_mentions = channel.send.call_args.kwargs["allowed_mentions"]
    assert not allowed_mentions.everyone
    assert not allowed_mentions.users
    assert not allowed_mentions.roles
    assert not allowed_mentions.replied_user
    startup_env.bot.get_guild.assert_called_once_with(11)


def test_ready_falls_back_to_fetch_channel_and_continues_after_http_failure(startup_env):
    guilds = {}
    channels = {}
    for guild_id, channel_id in ((11, 110), (22, 220), (33, 330)):
        guild = make_guild(guild_id)
        channel = make_channel(channel_id, guild)
        guild.get_channel.side_effect = lambda candidate_id, channel=channel: (
            channel if candidate_id == channel.id else None
        )
        if guild_id == 11:
            guild.get_channel.side_effect = None
            guild.get_channel.return_value = None
        guilds[guild_id] = guild
        channels[guild_id] = channel
        startup_env.cog.db.set_channel(guild_id, channel_id)

    channels[22].send.side_effect = discord.Forbidden(
        SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions"
    )
    startup_env.bot.get_guild.side_effect = lambda guild_id: guilds.get(guild_id)
    startup_env.bot.fetch_channel.return_value = channels[11]

    asyncio.run(startup_env.cog.on_ready())

    startup_env.bot.fetch_channel.assert_awaited_once_with(110)
    channels[11].send.assert_awaited_once()
    channels[22].send.assert_awaited_once()
    channels[33].send.assert_awaited_once()


@pytest.mark.parametrize("invalid_channel", ["wrong_guild", "not_text_channel"])
def test_ready_does_not_send_invalid_channel(startup_env, invalid_channel):
    guild = make_guild(11)
    if invalid_channel == "wrong_guild":
        channel = make_channel(110, SimpleNamespace(id=99))
    else:
        channel = SimpleNamespace(id=110, guild=guild, send=AsyncMock())
    guild.get_channel.side_effect = None
    guild.get_channel.return_value = channel
    startup_env.bot.get_guild.side_effect = lambda guild_id: guild if guild_id == 11 else None
    startup_env.cog.db.set_channel(11, 110)

    asyncio.run(startup_env.cog.on_ready())

    channel.send.assert_not_awaited()


def test_ready_db_read_failure_is_logged_and_not_retried(startup_env, monkeypatch, caplog):
    get_channels = Mock(side_effect=sqlite3.OperationalError("database is locked"))
    monkeypatch.setattr(startup_env.cog.db, "get_channels", get_channels)

    with caplog.at_level(logging.ERROR):
        asyncio.run(startup_env.cog.on_ready())
        asyncio.run(startup_env.cog.on_ready())

    assert "無法讀取啟動通知設定" in caplog.text
    get_channels.assert_called_once_with()
    assert startup_env.bot.startup_notifications_sent is True


def test_ready_runs_once_per_bot_across_reconnect_and_cog_reload(startup_env):
    guild = make_guild(11)
    channel = make_channel(110, guild)
    guild.get_channel.side_effect = None
    guild.get_channel.return_value = channel
    startup_env.bot.get_guild.side_effect = lambda guild_id: guild if guild_id == 11 else None
    startup_env.cog.db.set_channel(11, channel.id)

    asyncio.run(startup_env.cog.on_ready())
    asyncio.run(startup_env.cog.on_ready())
    startup_env.cog.cog_unload()
    reloaded_cog = startup_module.Startup(startup_env.bot)
    asyncio.run(reloaded_cog.on_ready())
    reloaded_cog.cog_unload()

    channel.send.assert_awaited_once()

    other_bot = make_bot({11: guild})
    other_cog = startup_module.Startup(other_bot)
    try:
        asyncio.run(other_cog.on_ready())
    finally:
        other_cog.cog_unload()
    assert channel.send.await_count == 2
