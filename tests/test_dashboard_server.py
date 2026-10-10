import asyncio
import csv
import io
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from dashboard.server import DashboardServer
from services.config_service import ConfigRevisionConflict
from services.database import PingDatabase


class FakeAuth:
    def __init__(self):
        self.started = False
        self.closed = False
        self.verify_owner = AsyncMock()

    def register(self, app):
        pass

    async def start(self):
        self.started = True

    async def close(self):
        self.closed = True

    def require_owner(self, request, write=False):
        if request.headers.get("X-Test-Owner") != "true":
            raise web.HTTPUnauthorized(text="owner required")
        if write and request.headers.get("X-Test-Write") != "true":
            raise web.HTTPForbidden(text="write access required")
        return {"user": {"id": "123", "name": "owner"}}


class FakeSettings:
    def snapshot(self):
        return {"values": {}, "revision": "a" * 64}

    async def save(self, payload):
        return {"saved": payload}


class ConflictingSettings(FakeSettings):
    async def save(self, payload):
        raise ConfigRevisionConflict("設定已更新，請重新載入。")


class FakeMusicService:
    def __init__(self):
        self.config = SimpleNamespace(max_cache_mb=128)
        self.players = {}
        self.snapshot_data = {
            "guild_id": "111",
            "generation": "generation-token",
            "session_id": 23,
            "status": "playing",
            "loop_mode": "off",
            "voice_channel_id": "456",
            "voice_channel_name": "music room",
            "current": {
                "title": "Current track",
                "url": "https://example.test/current",
                "duration": 120,
                "thumbnail": None,
                "requester_id": "789",
            },
            "queue": [
                {
                    "title": "Queued track",
                    "url": "https://example.test/queued",
                    "duration": 90,
                    "thumbnail": None,
                    "requester_id": None,
                }
            ],
            "elapsed_seconds": 12,
        }
        self.snapshot_calls = []
        self.dashboard_control = AsyncMock(return_value={"status": "paused"})
        self.cache = SimpleNamespace(
            stats=AsyncMock(return_value={"files": 2, "bytes": 4096}),
            cleanup=AsyncMock(return_value={"removed_files": 2, "freed_bytes": 4096}),
        )

    def snapshot(self, guild_id):
        self.snapshot_calls.append(guild_id)
        return deepcopy(self.snapshot_data)


def make_server(tmp_path, *, db=None, auth=None, settings=None):
    db = db or PingDatabase(tmp_path / "ping_count.db")
    auth = auth or FakeAuth()
    settings = settings or FakeSettings()
    guild = SimpleNamespace(
        id=111,
        name="Test guild",
        icon=None,
        member_count=17,
    )
    music_service = FakeMusicService()
    music_cog = SimpleNamespace(service=music_service)
    task_cog = SimpleNamespace(db=db)
    cogs = {"Music": music_cog, "Task": task_cog}
    bot = SimpleNamespace(
        latency=0.025,
        guilds=[guild],
        cogs=cogs,
        user=SimpleNamespace(display_name="Test bot", id=222),
        is_ready=lambda: True,
        get_cog=cogs.get,
        get_guild=lambda guild_id: guild if guild_id == guild.id else None,
        get_user=lambda user_id: SimpleNamespace(display_name=f"member-{user_id}"),
    )
    server = DashboardServer(
        bot,
        SimpleNamespace(host="127.0.0.1", port=0, public_url="http://localhost"),
        auth=auth,
        config_service=settings,
    )
    return server, auth, db, music_service


def run_http(server, test_body):
    async def run():
        await server.auth.start()
        client = TestClient(TestServer(server.app))
        try:
            await client.start_server()
            await test_body(client)
        finally:
            await client.close()
            await server.close()

    asyncio.run(run())


def owner_headers(*, write=False):
    headers = {"X-Test-Owner": "true"}
    if write:
        headers["X-Test-Write"] = "true"
    return headers


def test_every_api_route_rejects_unauthenticated_requests(tmp_path):
    server, auth, db, _ = make_server(tmp_path)
    requests = [
        ("GET", "/api/session", None),
        ("GET", "/api/overview", None),
        ("GET", "/api/settings", None),
        ("PUT", "/api/settings", {"values": {}, "revision": "a" * 64}),
        ("GET", "/api/ping", None),
        ("GET", "/api/ping/export", None),
        ("GET", "/api/music/111", None),
        (
            "POST",
            "/api/music/111/control",
            {"action": "pause", "session_id": 23, "generation": "generation-token"},
        ),
        ("POST", "/api/cache/clear", {"confirm": True}),
    ]

    async def check(client):
        for method, path, payload in requests:
            response = await client.request(
                method,
                path,
                json=payload,
            )
            assert response.status == 401, (method, path, await response.text())

    try:
        run_http(server, check)
        assert auth.started and auth.closed
    finally:
        db.close()


def test_mutations_require_write_authorization(tmp_path):
    server, _, db, _ = make_server(tmp_path)
    writes = [
        ("PUT", "/api/settings", {"values": {}, "revision": "a" * 64}),
        (
            "POST",
            "/api/music/111/control",
            {"action": "pause", "session_id": 23, "generation": "generation-token"},
        ),
        ("POST", "/api/cache/clear", {"confirm": True}),
    ]

    async def check(client):
        for method, path, payload in writes:
            response = await client.request(
                method,
                path,
                json=payload,
                headers=owner_headers(),
            )
            assert response.status == 403
        read_response = await client.get("/api/settings", headers=owner_headers())
        assert read_response.status == 200

    try:
        run_http(server, check)
    finally:
        db.close()


def test_api_rechecks_current_owner_before_reads_and_mutations(tmp_path):
    server, auth, db, music = make_server(tmp_path)

    async def check(client):
        response = await client.get("/api/settings", headers=owner_headers())
        assert response.status == 200
        auth.verify_owner.assert_awaited_once_with(
            {"user": {"id": "123", "name": "owner"}}, refresh=False,
        )

        auth.verify_owner.reset_mock()
        auth.verify_owner.side_effect = web.HTTPForbidden(text="ownership changed")
        response = await client.post(
            "/api/music/111/control",
            json={"action": "pause", "session_id": 23, "generation": "generation-token"},
            headers=owner_headers(write=True),
        )
        assert response.status == 403
        auth.verify_owner.assert_awaited_once_with(
            {"user": {"id": "123", "name": "owner"}}, refresh=True,
        )
        music.dashboard_control.assert_not_awaited()
        response = await client.get("/api/session", headers=owner_headers())
        assert response.status == 403

    try:
        run_http(server, check)
    finally:
        db.close()


def test_overview_reports_string_ids_and_guild_validation_errors(tmp_path):
    server, _, db, _ = make_server(tmp_path)

    async def check(client):
        headers = owner_headers()
        response = await client.get("/api/overview", headers=headers)
        assert response.status == 200
        overview = await response.json()
        assert overview["guilds"][0]["id"] == "111"
        assert overview["bot"]["id"] == "222"

        malformed = await client.get("/api/music/not-an-id", headers=headers)
        assert malformed.status == 400
        missing = await client.get("/api/music/999", headers=headers)
        assert missing.status == 404
        bad_filter = await client.get("/api/ping?guild_id=12x", headers=headers)
        assert bad_filter.status == 400

    try:
        run_http(server, check)
    finally:
        db.close()


def test_ping_filters_and_csv_use_temporary_database(tmp_path):
    db = PingDatabase(tmp_path / "ping_count.db")
    db.add_ping(1, guild_id=111, channel_id=5, message_id=100, event_at=1_704_124_799)
    db.add_ping(
        1,
        guild_id=111,
        channel_id=5,
        message_id=101,
        source="manual",
        event_at=1_704_124_800,
    )
    db.add_ping(
        2,
        guild_id=999,
        channel_id=6,
        message_id=102,
        event_at=1_704_124_800,
    )
    server, _, _, _ = make_server(tmp_path, db=db)

    async def check(client):
        headers = owner_headers()
        response = await client.get(
            "/api/ping?start=2024-01-01&end=2024-01-02&guild_id=111&source=manual",
            headers=headers,
        )
        assert response.status == 200
        data = await response.json()
        assert data["period_total"] == 1
        assert data["unique_users"] == 1
        assert data["daily"] == [
            {"date": "2024-01-01", "count": 0, "scheduled": 0, "manual": 0},
            {"date": "2024-01-02", "count": 1, "scheduled": 0, "manual": 1},
        ]
        assert data["leaders"][0]["user_id"] == "1"
        assert data["leaders"][0]["name"] == "member-1"

        invalid_date = await client.get(
            "/api/ping?start=01-01-2024&end=2024-01-02",
            headers=headers,
        )
        assert invalid_date.status == 400
        invalid_source = await client.get(
            "/api/ping?source=imported",
            headers=headers,
        )
        assert invalid_source.status == 400
        too_long = await client.get(
            "/api/ping?start=2023-01-01&end=2024-01-02",
            headers=headers,
        )
        assert too_long.status == 400

        csv_response = await client.get(
            "/api/ping/export?start=2024-01-01&end=2024-01-02&guild_id=111&source=manual",
            headers=headers,
        )
        assert csv_response.status == 200
        assert csv_response.content_type == "text/csv"
        assert (
            'attachment; filename="ping-2024-01-01-2024-01-02.csv"'
            in csv_response.headers["Content-Disposition"]
        )
        csv_text = await csv_response.text()
        assert csv_text.startswith("\ufeffuser_id,guild_id,channel_id,message_id,event_at,source")
        assert "1,111,5,101,1704124800,manual" in csv_text
        assert "102" not in csv_text

    try:
        run_http(server, check)
    finally:
        db.close()


@pytest.mark.parametrize("guild_filter", ["", "&guild_id=", "&guild_id=111"])
@pytest.mark.parametrize("source_filter", ["", "&source=scheduled"])
def test_ping_scheduled_rankings_and_export_with_guild_filters(
    tmp_path, guild_filter, source_filter
):
    db = PingDatabase(tmp_path / "ping_count.db")
    db.add_ping(1, guild_id=111, message_id=100, event_at=1_704_124_799)
    db.add_ping(2, guild_id=999, message_id=101, event_at=1_704_124_800)
    db.add_ping(3, guild_id=111, message_id=102, source="manual", event_at=1_704_124_800)
    db.add_ping(4, guild_id=111, message_id=103, event_at=1_704_211_200)
    server, _, _, _ = make_server(tmp_path, db=db)

    async def check(client):
        query = f"start=2024-01-01&end=2024-01-02{guild_filter}{source_filter}"
        response = await client.get(f"/api/ping?{query}", headers=owner_headers())
        assert response.status == 200
        data = await response.json()
        expected_users = {"1"} if guild_filter == "&guild_id=111" else {"1", "2"}
        assert data["period_total"] == len(expected_users)
        assert data["unique_users"] == len(expected_users)
        assert {row["user_id"] for row in data["leaders"]} == expected_users
        assert all(row["count"] == 1 for row in data["leaders"])
        assert {row["name"] for row in data["leaders"]} == {
            f"member-{user_id}" for user_id in expected_users
        }
        assert {row["user_id"] for row in data["events"]} == expected_users
        assert all(row["source"] == "scheduled" for row in data["events"])

        exported = await client.get(f"/api/ping/export?{query}", headers=owner_headers())
        assert exported.status == 200
        rows = list(csv.DictReader(io.StringIO((await exported.text()).lstrip("\ufeff"))))
        assert {row["user_id"] for row in rows} == expected_users
        assert all(row["source"] == "scheduled" for row in rows)

        empty = await client.get(
            f"/api/ping?start=2024-01-04&end=2024-01-04{guild_filter}{source_filter}",
            headers=owner_headers(),
        )
        assert empty.status == 200
        empty_data = await empty.json()
        assert empty_data["period_total"] == 0
        assert empty_data["leaders"] == []
        assert empty_data["events"] == []

    try:
        run_http(server, check)
    finally:
        db.close()


def test_settings_revision_conflict_uses_service_http_status(tmp_path):
    server, _, db, _ = make_server(tmp_path, settings=ConflictingSettings())

    async def check(client):
        response = await client.put(
            "/api/settings",
            json={"values": {}, "revision": "a" * 64},
            headers=owner_headers(write=True),
        )
        assert response.status == 409
        assert (await response.json())["error"] == "設定已更新，請重新載入。"

    try:
        run_http(server, check)
    finally:
        db.close()


def test_music_snapshot_and_control_keep_ids_and_session_tokens(tmp_path):
    server, _, db, music = make_server(tmp_path)

    async def check(client):
        headers = owner_headers()
        response = await client.get("/api/music/111", headers=headers)
        assert response.status == 200
        snapshot = await response.json()
        assert snapshot["guild_id"] == "111"
        assert snapshot["voice_channel_id"] == "456"
        assert snapshot["current"]["requester_id"] == "789"
        assert snapshot["current"]["requester_name"] == "member-789"
        assert snapshot["queue"][0]["requester_id"] is None
        assert music.snapshot_calls == [111]

        payload = {
            "action": "pause",
            "session_id": 23,
            "generation": "generation-token",
        }
        control = await client.post(
            "/api/music/111/control",
            json=payload,
            headers=owner_headers(write=True),
        )
        assert control.status == 200
        assert await control.json() == {"status": "paused"}
        music.dashboard_control.assert_awaited_once_with(111, **payload)

    try:
        run_http(server, check)
    finally:
        db.close()


def test_invalid_json_and_body_types_return_client_errors(tmp_path):
    server, _, db, _ = make_server(tmp_path)

    async def check(client):
        headers = owner_headers(write=True)
        malformed = await client.put(
            "/api/settings",
            data="{broken",
            headers={**headers, "Content-Type": "application/json"},
        )
        assert malformed.status == 400

        wrong_type = await client.put(
            "/api/settings",
            data="{}",
            headers={**headers, "Content-Type": "text/plain"},
        )
        assert wrong_type.status == 415

        array_body = await client.put(
            "/api/settings",
            json=[],
            headers=headers,
        )
        assert array_body.status == 400

        malformed_control = await client.post(
            "/api/music/111/control",
            data="{broken",
            headers={**headers, "Content-Type": "application/json"},
        )
        assert malformed_control.status == 400

    try:
        run_http(server, check)
    finally:
        db.close()


def test_static_allowlist_and_security_headers(tmp_path):
    server, _, db, _ = make_server(tmp_path)

    async def check(client):
        page = await client.get("/")
        assert page.status == 200
        csp = page.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert page.headers["X-Frame-Options"] == "DENY"

        asset = await client.get("/assets/app.js")
        assert asset.status == 200
        assert "Content-Security-Policy" in asset.headers

        denied = await client.get("/assets/secret.txt")
        assert denied.status == 404
        assert "Content-Security-Policy" in denied.headers

    try:
        run_http(server, check)
    finally:
        db.close()


def test_cache_clear_requires_explicit_confirmation(tmp_path):
    server, _, db, music = make_server(tmp_path)
    server._cache_snapshot = {"files": 5}

    async def check(client):
        headers = owner_headers(write=True)
        unconfirmed = await client.post(
            "/api/cache/clear",
            json={"confirm": False},
            headers=headers,
        )
        assert unconfirmed.status == 400
        music.cache.cleanup.assert_not_awaited()

        confirmed = await client.post(
            "/api/cache/clear",
            json={"confirm": True},
            headers=headers,
        )
        assert confirmed.status == 200
        assert await confirmed.json() == {"removed_files": 2, "freed_bytes": 4096}
        music.cache.cleanup.assert_awaited_once_with(force=True)
        assert server._cache_snapshot is None

    try:
        run_http(server, check)
    finally:
        db.close()
