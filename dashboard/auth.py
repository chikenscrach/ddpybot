"""Owner-only Discord OAuth authentication for the web dashboard."""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import aiohttp
from aiohttp import web

DISCORD_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_ME_URL = "https://discord.com/api/users/@me"
STATE_COOKIE = "ddpybot_dashboard_oauth_state"
SESSION_COOKIE = "ddpybot_dashboard_session"
STATE_TTL_SECONDS = 600
SESSION_TTL_SECONDS = 8 * 60 * 60
OWNER_CACHE_TTL_SECONDS = 30
MAX_PENDING_STATES = 128
MAX_SESSIONS = 512


@dataclass(frozen=True, slots=True)
class DashboardConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8080
    public_url: str = ""
    client_id: str = ""
    client_secret: str = ""

    @property
    def callback_url(self) -> str:
        if not self.public_url:
            return ""
        return f"{self.public_url.rstrip('/')}/auth/callback"

    @property
    def secure_cookies(self) -> bool:
        return urlsplit(self.public_url).scheme.lower() == "https"

    @classmethod
    def from_env(cls) -> DashboardConfig:
        import os

        enabled_value = os.environ.get("DASHBOARD_ENABLED", "false").strip().lower()
        bool_values = {"true": True, "1": True, "yes": True, "false": False,
                       "0": False, "no": False}
        if enabled_value not in bool_values:
            raise ValueError("DASHBOARD_ENABLED 必須是 true 或 false。")
        enabled = bool_values[enabled_value]

        host = os.environ.get("DASHBOARD_HOST", "127.0.0.1").strip()
        if not host or any(char.isspace() for char in host):
            raise ValueError("DASHBOARD_HOST 不可為空或包含空白。")

        raw_port = os.environ.get("DASHBOARD_PORT", "8080").strip()
        try:
            port = int(raw_port)
        except (TypeError, ValueError):
            raise ValueError("DASHBOARD_PORT 必須是 1 到 65535 的整數。") from None
        if not 1 <= port <= 65535:
            raise ValueError("DASHBOARD_PORT 必須是 1 到 65535 的整數。")

        public_url = os.environ.get("DASHBOARD_PUBLIC_URL", "").strip().rstrip("/")
        if public_url:
            _validate_public_url(public_url)
        elif enabled:
            raise ValueError("啟用 Dashboard 時必須設定 DASHBOARD_PUBLIC_URL。")

        client_id = os.environ.get("DASHBOARD_CLIENT_ID", "").strip()
        client_secret = os.environ.get("DASHBOARD_CLIENT_SECRET", "").strip()
        if enabled:
            if not (client_id.isascii() and client_id.isdecimal()):
                raise ValueError("啟用 Dashboard 時 DASHBOARD_CLIENT_ID 必須是 Discord 應用程式 ID。")
            if not client_secret:
                raise ValueError("啟用 Dashboard 時必須設定 DASHBOARD_CLIENT_SECRET。")

        return cls(
            enabled=enabled,
            host=host,
            port=port,
            public_url=public_url,
            client_id=client_id,
            client_secret=client_secret,
        )


def _validate_public_url(value: str) -> None:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        # Accessing port also validates malformed or out-of-range port text.
        _ = parsed.port
    except (TypeError, ValueError):
        raise ValueError("DASHBOARD_PUBLIC_URL 必須是有效的 HTTPS 或 loopback HTTP 網址。") from None
    if (parsed.scheme not in {"https", "http"} or not hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise ValueError("DASHBOARD_PUBLIC_URL 必須是有效的 HTTPS 或 loopback HTTP 網址。")
    if parsed.scheme == "http":
        try:
            is_loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = hostname.lower() == "localhost"
        if not is_loopback:
            raise ValueError("HTTP 僅允許 loopback 的 DASHBOARD_PUBLIC_URL。")


class OAuthManager:
    """Owns OAuth state, browser sessions, and owner authorization checks."""

    def __init__(self, bot: Any, config: DashboardConfig):
        self.bot = bot
        self.config = config
        self._http: aiohttp.ClientSession | None = None
        self._states: dict[str, tuple[str, float]] = {}
        self._sessions: dict[str, dict[str, Any]] = {}
        self._owner_id: str | None = None
        self._owner_checked_at = 0.0
        self._owner_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._http is None:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))

    async def close(self) -> None:
        if self._http is not None:
            await self._http.close()
            self._http = None

    def register(self, app: web.Application) -> None:
        app.router.add_get("/auth/login", self.login)
        app.router.add_get("/auth/callback", self.callback)
        app.router.add_post("/auth/logout", self.logout)

    def require_owner(self, request: web.Request, write: bool = False) -> dict[str, Any]:
        token = request.cookies.get(SESSION_COOKIE, "")
        session = self._sessions.get(token)
        if not token or session is None or session["expires_at"] <= time.time():
            if token:
                self._sessions.pop(token, None)
            raise web.HTTPUnauthorized(text="請先登入 Bot owner 帳號。")

        if write:
            origin = request.headers.get("Origin", "")
            csrf = request.headers.get("X-CSRF-Token", "")
            if not _same_origin(origin, self.config.public_url):
                raise web.HTTPForbidden(text="請求來源驗證失敗。")
            if not csrf or not hmac.compare_digest(csrf, session["csrf_token"]):
                raise web.HTTPForbidden(text="CSRF 驗證失敗。")

        return {"user": dict(session["user"]), "csrf_token": session["csrf_token"]}

    async def verify_owner(self, session: dict[str, Any], *, refresh: bool = False) -> None:
        """Confirm a logged-in session still belongs to the current application owner."""
        user = session.get("user")
        user_id = user.get("id") if isinstance(user, dict) else None
        owner_id = await self._application_owner_id(refresh=refresh)
        if owner_id is None or str(user_id) != owner_id:
            raise web.HTTPForbidden(text="此 Discord 帳號不是 Bot owner。")

    async def login(self, request: web.Request) -> web.StreamResponse:
        self._ensure_available()
        now = time.time()
        self._prune_states(now)
        if len(self._states) >= MAX_PENDING_STATES:
            self._states.pop(next(iter(self._states)))
        state = secrets.token_urlsafe(32)
        browser_binding = secrets.token_urlsafe(32)
        self._states[state] = (browser_binding, now + STATE_TTL_SECONDS)
        params = urlencode({
            "client_id": self.config.client_id,
            "response_type": "code",
            "redirect_uri": self.config.callback_url,
            "scope": "identify",
            "state": state,
        })
        response = web.HTTPFound(f"{DISCORD_AUTHORIZE_URL}?{params}")
        response.set_cookie(
            STATE_COOKIE,
            browser_binding,
            max_age=STATE_TTL_SECONDS,
            httponly=True,
            secure=self.config.secure_cookies,
            samesite="Lax",
            path="/auth/callback",
        )
        raise response

    async def callback(self, request: web.Request) -> web.StreamResponse:
        self._ensure_available()
        state = request.query.get("state", "")
        code = request.query.get("code", "")
        binding = request.cookies.get(STATE_COOKIE, "")
        pending = self._states.pop(state, None) if state else None
        if (not pending or not binding or not hmac.compare_digest(binding, pending[0])
                or pending[1] <= time.time() or not code or len(code) > 4096
                or request.query.get("error")):
            raise web.HTTPBadRequest(text="Discord 登入驗證失敗，請重新登入。")

        try:
            profile = await self._exchange_code(code)
            if not await self._is_owner(profile["id"]):
                raise web.HTTPForbidden(text="此 Discord 帳號不是 Bot owner。")
        except (web.HTTPForbidden, web.HTTPServiceUnavailable):
            raise
        except Exception:
            raise web.HTTPBadGateway(text="Discord 登入暫時無法完成，請稍後重試。") from None

        now = time.time()
        self._prune_sessions(now)
        while len(self._sessions) >= MAX_SESSIONS:
            self._sessions.pop(next(iter(self._sessions)))
        token = secrets.token_urlsafe(32)
        session = {
            "user": _public_user(profile),
            "csrf_token": secrets.token_urlsafe(32),
            "expires_at": now + SESSION_TTL_SECONDS,
        }
        self._sessions[token] = session
        response = web.HTTPFound("/")
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            secure=self.config.secure_cookies,
            samesite="Lax",
            path="/",
        )
        response.del_cookie(STATE_COOKIE, path="/auth/callback", secure=self.config.secure_cookies,
                           httponly=True, samesite="Lax")
        raise response

    async def logout(self, request: web.Request) -> web.StreamResponse:
        self.require_owner(request, write=True)
        token = request.cookies.get(SESSION_COOKIE, "")
        self._sessions.pop(token, None)
        response = web.json_response({"ok": True})
        response.del_cookie(SESSION_COOKIE, path="/", secure=self.config.secure_cookies,
                           httponly=True, samesite="Lax")
        return response

    async def _exchange_code(self, code: str) -> dict[str, Any]:
        if self._http is None:
            raise RuntimeError("OAuth client is not started")
        token_data = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.callback_url,
        }
        async with self._http.post(DISCORD_TOKEN_URL, data=token_data) as response:
            if response.status != 200:
                raise ValueError("OAuth token exchange failed")
            token_payload = await response.json(content_type=None)
        access_token = token_payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("OAuth response omitted access token")
        async with self._http.get(
            DISCORD_ME_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        ) as response:
            if response.status != 200:
                raise ValueError("Discord profile lookup failed")
            profile = await response.json(content_type=None)
        user_id = profile.get("id")
        if not isinstance(user_id, str) or not (user_id.isascii() and user_id.isdecimal()):
            raise ValueError("Discord profile has invalid id")
        return profile

    async def _is_owner(self, user_id: str) -> bool:
        # Owner status is always resolved from Discord's application metadata;
        # neither an environment variable nor the client-supplied profile is trusted.
        owner_id = await self._application_owner_id(refresh=True)
        return owner_id is not None and owner_id == user_id

    async def _application_owner_id(self, *, refresh: bool) -> str | None:
        async with self._owner_lock:
            now = time.monotonic()
            if (not refresh and self._owner_checked_at
                    and now - self._owner_checked_at < OWNER_CACHE_TTL_SECONDS):
                return self._owner_id

            try:
                info = await self.bot.application_info()
            except Exception:
                # Invalidate freshness so a failed refresh can never authorize a
                # write from the previous cache. Keep the last identity so a
                # later successful lookup can still revoke its sessions.
                self._owner_checked_at = 0.0
                raise web.HTTPServiceUnavailable(
                    text="目前無法確認 Bot owner 身分，請稍後重試。"
                ) from None

            team = getattr(info, "team", None)
            if team is not None:
                owner_id = getattr(team, "owner_id", None)
                if owner_id is None:
                    owner_id = getattr(getattr(team, "owner", None), "id", None)
            else:
                owner_id = getattr(getattr(info, "owner", None), "id", None)
            current_owner_id = str(owner_id) if owner_id is not None else None
            previous_owner_id = self._owner_id
            if previous_owner_id is not None and current_owner_id != previous_owner_id:
                self._revoke_owner_sessions(previous_owner_id)
            self._owner_id = current_owner_id
            self._owner_checked_at = time.monotonic()
            return current_owner_id

    def _revoke_owner_sessions(self, owner_id: str) -> None:
        for token, session in list(self._sessions.items()):
            user = session.get("user", {})
            if str(user.get("id", "")) == owner_id:
                self._sessions.pop(token, None)

    def _ensure_available(self) -> None:
        if not self.config.enabled or self._http is None:
            raise web.HTTPServiceUnavailable(text="Dashboard 登入服務尚未啟用。")

    def _prune_states(self, now: float) -> None:
        for key, (_, expiry) in list(self._states.items()):
            if expiry <= now:
                self._states.pop(key, None)

    def _prune_sessions(self, now: float) -> None:
        for key, session in list(self._sessions.items()):
            if session["expires_at"] <= now:
                self._sessions.pop(key, None)


def _public_user(profile: dict[str, Any]) -> dict[str, str | None]:
    user_id = str(profile["id"])
    name = profile.get("global_name") or profile.get("username") or user_id
    avatar_hash = profile.get("avatar")
    avatar = None
    if isinstance(avatar_hash, str) and avatar_hash:
        extension = "gif" if avatar_hash.startswith("a_") else "png"
        avatar = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{extension}?size=128"
    return {"name": str(name), "id": user_id, "avatar": avatar}


def _same_origin(origin: str, public_url: str) -> bool:
    if not origin or origin == "null" or not public_url:
        return False
    try:
        return _origin_tuple(origin) == _origin_tuple(public_url)
    except (TypeError, ValueError):
        return False


def _origin_tuple(value: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("invalid origin")
    if (parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or parsed.username or parsed.password):
        raise ValueError("invalid origin")
    port = parsed.port
    if port == (443 if parsed.scheme == "https" else 80):
        port = None
    return parsed.scheme.lower(), parsed.hostname.lower(), port
