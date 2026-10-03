import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from aiohttp import web

from dashboard.auth import (
    SESSION_COOKIE,
    STATE_COOKIE,
    DashboardConfig,
    OAuthManager,
)


def test_dashboard_config_defaults_to_disabled(monkeypatch):
    for name in (
        "DASHBOARD_ENABLED", "DASHBOARD_HOST", "DASHBOARD_PORT", "DASHBOARD_PUBLIC_URL",
        "DASHBOARD_CLIENT_ID", "DASHBOARD_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    config = DashboardConfig.from_env()

    assert config.enabled is False
    assert config.host == "127.0.0.1"
    assert config.port == 8080
    assert config.callback_url == ""


@pytest.mark.parametrize("public_url", [
    "http://dashboard.example.com",
    "ftp://localhost",
    "https://user:password@example.com",
    "https://example.com/path",
    "https://example.com/?next=/",
])
def test_dashboard_config_rejects_unsafe_public_urls(monkeypatch, public_url):
    monkeypatch.setenv("DASHBOARD_PUBLIC_URL", public_url)

    with pytest.raises(ValueError):
        DashboardConfig.from_env()


def test_dashboard_config_enabled_requires_oauth_and_uses_fixed_callback(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_PUBLIC_URL", "https://dashboard.example.com/")
    monkeypatch.setenv("DASHBOARD_CLIENT_ID", "123456789012345678")
    monkeypatch.setenv("DASHBOARD_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("DASHBOARD_PORT", "9000")

    config = DashboardConfig.from_env()

    assert config.port == 9000
    assert config.callback_url == "https://dashboard.example.com/auth/callback"
    assert config.secure_cookies is True


@pytest.mark.parametrize("value", ["", "0", "65536", "8080.5", "false"])
def test_dashboard_config_rejects_invalid_ports(monkeypatch, value):
    monkeypatch.setenv("DASHBOARD_PORT", value)

    with pytest.raises(ValueError):
        DashboardConfig.from_env()


def test_dashboard_config_allows_only_loopback_http(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PUBLIC_URL", "http://127.0.0.1:8080")
    config = DashboardConfig.from_env()
    assert config.secure_cookies is False

    monkeypatch.setenv("DASHBOARD_PUBLIC_URL", "http://localhost:8080")
    assert DashboardConfig.from_env().public_url == "http://localhost:8080"


def test_login_registers_bound_state_cookie_and_identify_scope():
    async def scenario():
        config = DashboardConfig(
            enabled=True,
            public_url="https://dashboard.example.com",
            client_id="123456789012345678",
            client_secret="client-secret",
        )
        manager = OAuthManager(SimpleNamespace(), config)
        await manager.start()
        request = SimpleNamespace()
        try:
            with pytest.raises(web.HTTPFound) as caught:
                await manager.login(request)
            response = caught.value
            location = urlsplit(response.location)
            params = parse_qs(location.query)
            assert params["scope"] == ["identify"]
            assert params["redirect_uri"] == ["https://dashboard.example.com/auth/callback"]
            state = params["state"][0]
            binding, expiry = manager._states[state]
            assert binding
            assert expiry > time.time()
            cookie = response.cookies[STATE_COOKIE]
            assert cookie["httponly"] is True
            assert cookie["secure"] is True
            assert cookie["samesite"] == "Lax"
        finally:
            await manager.close()

    asyncio.run(scenario())


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self, content_type=None):
        return self.payload


class FakeOAuthHTTP:
    def __init__(self, profile):
        self.profile = profile
        self.post_calls = []
        self.get_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return FakeResponse(200, {"access_token": "short-lived-test-access-token"})

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return FakeResponse(200, self.profile)


def test_oauth_callback_creates_session_only_for_actual_individual_owner():
    async def scenario():
        bot = SimpleNamespace(application_info=AsyncMock(return_value=SimpleNamespace(
            owner=SimpleNamespace(id=123), team=None,
        )))
        config = DashboardConfig(
            enabled=True,
            public_url="https://dashboard.example.com",
            client_id="123456789012345678",
            client_secret="client-secret",
        )
        manager = OAuthManager(bot, config)
        manager._http = FakeOAuthHTTP({
            "id": "123", "username": "owner", "global_name": "Bot Owner", "avatar": "hash",
        })
        state, binding = "single-use-state", "browser-binding"
        manager._states[state] = (binding, time.time() + 60)
        request = SimpleNamespace(
            query={"state": state, "code": "authorization-code"},
            cookies={STATE_COOKIE: binding},
        )

        with pytest.raises(web.HTTPFound) as caught:
            await manager.callback(request)

        response = caught.value
        cookie = response.cookies[SESSION_COOKIE]
        token = cookie.value
        assert token in manager._sessions
        assert manager._sessions[token]["user"] == {
            "name": "Bot Owner",
            "id": "123",
            "avatar": "https://cdn.discordapp.com/avatars/123/hash.png?size=128",
        }
        assert cookie["httponly"] is True
        assert cookie["secure"] is True
        assert cookie["samesite"] == "Lax"
        assert response.location == "/"
        assert state not in manager._states
        assert manager._http.post_calls[0][1]["data"]["client_secret"] == "client-secret"
        assert manager._http.get_calls[0][1]["headers"]["Authorization"].startswith("Bearer ")
        bot.application_info.assert_awaited_once()

    asyncio.run(scenario())


def test_oauth_callback_rejects_team_members_who_are_not_team_owner():
    async def scenario():
        bot = SimpleNamespace(application_info=AsyncMock(return_value=SimpleNamespace(
            owner=SimpleNamespace(id=444),
            team=SimpleNamespace(owner_id=555),
        )))
        manager = OAuthManager(bot, DashboardConfig(
            enabled=True,
            public_url="https://dashboard.example.com",
            client_id="123456789012345678",
            client_secret="client-secret",
        ))
        manager._http = FakeOAuthHTTP({"id": "444", "username": "team-member"})
        state, binding = "team-state", "team-browser"
        manager._states[state] = (binding, time.time() + 60)
        request = SimpleNamespace(
            query={"state": state, "code": "authorization-code"},
            cookies={STATE_COOKIE: binding},
        )

        with pytest.raises(web.HTTPForbidden):
            await manager.callback(request)

        assert manager._sessions == {}

    asyncio.run(scenario())


def test_require_owner_enforces_login_origin_and_csrf():
    manager = OAuthManager(SimpleNamespace(), DashboardConfig(
        enabled=True,
        public_url="https://dashboard.example.com",
    ))
    manager._sessions["random-session"] = {
        "user": {"name": "Owner", "id": "123", "avatar": None},
        "csrf_token": "csrf-value",
        "expires_at": time.time() + 60,
    }

    def request(origin="https://dashboard.example.com", csrf="csrf-value"):
        return SimpleNamespace(
            cookies={SESSION_COOKIE: "random-session"},
            headers={"Origin": origin, "X-CSRF-Token": csrf},
        )

    assert manager.require_owner(request()) == {
        "user": {"name": "Owner", "id": "123", "avatar": None},
        "csrf_token": "csrf-value",
    }
    with pytest.raises(web.HTTPForbidden):
        manager.require_owner(request(origin="https://evil.example"), write=True)
    with pytest.raises(web.HTTPForbidden):
        manager.require_owner(request(csrf="wrong"), write=True)
    with pytest.raises(web.HTTPUnauthorized):
        manager.require_owner(SimpleNamespace(cookies={}, headers={}))


def test_logout_returns_json_and_clears_session_cookie():
    async def scenario():
        manager = OAuthManager(SimpleNamespace(), DashboardConfig(
            enabled=True,
            public_url="https://dashboard.example.com",
        ))
        manager._sessions["random-session"] = {
            "user": {"name": "Owner", "id": "123", "avatar": None},
            "csrf_token": "csrf-value",
            "expires_at": time.time() + 60,
        }
        request = SimpleNamespace(
            cookies={SESSION_COOKIE: "random-session"},
            headers={
                "Origin": "https://dashboard.example.com",
                "X-CSRF-Token": "csrf-value",
            },
        )

        response = await manager.logout(request)

        assert response.status == 200
        assert response.content_type == "application/json"
        assert json.loads(response.text) == {"ok": True}
        assert SESSION_COOKIE in response.cookies
        assert response.cookies[SESSION_COOKIE]["max-age"] == "0"
        assert "random-session" not in manager._sessions

    asyncio.run(scenario())


def test_oauth_callback_rejects_replayed_or_cookie_unbound_state():
    async def scenario():
        manager = OAuthManager(SimpleNamespace(), DashboardConfig(
            enabled=True,
            public_url="https://dashboard.example.com",
            client_id="123456789012345678",
            client_secret="client-secret",
        ))
        await manager.start()
        manager._states["valid-state"] = ("expected-cookie", time.time() + 60)
        request = SimpleNamespace(
            query={"state": "valid-state", "code": "authorization-code"},
            cookies={STATE_COOKIE: "wrong-cookie"},
        )
        try:
            with pytest.raises(web.HTTPBadRequest):
                await manager.callback(request)
            assert "valid-state" not in manager._states
        finally:
            await manager.close()

    asyncio.run(scenario())


def _application_info(owner_id):
    return SimpleNamespace(owner=SimpleNamespace(id=owner_id), team=None)


def _owner_session(user_id="123"):
    return {"user": {"id": user_id, "name": "Owner", "avatar": None}}


def test_owner_change_during_write_revokes_all_old_owner_sessions():
    async def scenario():
        bot = SimpleNamespace(application_info=AsyncMock(side_effect=[
            _application_info(123), _application_info(456),
        ]))
        manager = OAuthManager(bot, DashboardConfig(enabled=True))
        manager._sessions.update({
            "old-session-1": {"user": {"id": "123"}},
            "old-session-2": {"user": {"id": "123"}},
            "new-owner-session": {"user": {"id": "456"}},
        })
        session = _owner_session()

        await manager.verify_owner(session)
        with pytest.raises(web.HTTPForbidden):
            await manager.verify_owner(session, refresh=True)

        assert set(manager._sessions) == {"new-owner-session"}
        assert bot.application_info.await_count == 2

    asyncio.run(scenario())


def test_expired_owner_cache_rejects_old_owner_read_and_revokes_session():
    async def scenario():
        bot = SimpleNamespace(application_info=AsyncMock(side_effect=[
            _application_info(123), _application_info(456),
        ]))
        manager = OAuthManager(bot, DashboardConfig(enabled=True))
        manager._sessions["old-session"] = {"user": {"id": "123"}}
        session = _owner_session()

        await manager.verify_owner(session)
        manager._owner_checked_at = time.monotonic() - 31
        with pytest.raises(web.HTTPForbidden):
            await manager.verify_owner(session)

        assert manager._sessions == {}
        assert bot.application_info.await_count == 2

    asyncio.run(scenario())


def test_owner_api_failure_blocks_mutation_even_with_cached_owner():
    async def scenario():
        bot = SimpleNamespace(application_info=AsyncMock(return_value=_application_info(123)))
        manager = OAuthManager(bot, DashboardConfig(enabled=True))
        session = _owner_session()
        mutation = AsyncMock()
        await manager.verify_owner(session)
        bot.application_info.side_effect = RuntimeError("Discord API unavailable")

        async def guarded_mutation():
            await manager.verify_owner(session, refresh=True)
            await mutation()

        with pytest.raises(web.HTTPServiceUnavailable):
            await guarded_mutation()

        mutation.assert_not_awaited()
        assert manager._owner_checked_at == 0

    asyncio.run(scenario())


def test_owner_reads_within_cache_window_do_not_refetch():
    async def scenario():
        bot = SimpleNamespace(application_info=AsyncMock(return_value=_application_info(123)))
        manager = OAuthManager(bot, DashboardConfig(enabled=True))
        session = _owner_session()

        for _ in range(5):
            await manager.verify_owner(session)
            manager._owner_checked_at = time.monotonic() - 3

        bot.application_info.assert_awaited_once()

    asyncio.run(scenario())
