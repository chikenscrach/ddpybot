#!/usr/bin/env python3
"""Repeatable Playwright smoke test for the dashboard's shipped static UI.

The dashboard server must already be running. This script only intercepts its
API and logout calls; the real HTML, CSS, and JavaScript are loaded from --url.
It never intercepts /auth/login or adds an authentication bypass to the app.

Run with:
    uv run --with playwright python scripts/test_dashboard_ui.py
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Browser, Page, Response, Route, sync_playwright

DEFAULT_URL = "http://127.0.0.1:8088"
DEFAULT_SCREENSHOTS = Path("/tmp/ddpybot-dashboard-ui")
OWNER_NAME = "Dashboard Fixture Owner"
OWNER_ID = "18446744073709551614"
GUILD_ID = "18446744073709551613"
LARGE_DAILY_ID = "18446744073709551615"
LARGE_MODERATOR_IDS = ["18446744073709551614", "9223372036854775807"]
XSS_PAYLOAD = '<img src=x onerror="window.__dashboardSmokeXss = true">'
CSRF_TOKEN = "dashboard-ui-fixture-csrf"

MUSIC_VALUES: dict[str, Any] = {
    "cache_dir": "data/music",
    "max_cache_mb": 1024,
    "max_file_mb": 100,
    "max_duration_seconds": 1800,
    "max_queue_size": 100,
    "max_playlist_items": 50,
    "empty_channel_grace_seconds": 10,
    "auto_cleanup": True,
    "cache_ttl_hours": 168,
    "cleanup_interval_seconds": 600,
    "download_timeout_seconds": 300,
    "ffmpeg_executable": "ffmpeg",
    "js_runtime": "deno",
    "cookies_file": None,
    "allow_ytdlp_plugins": False,
    "youtube_player_client": None,
    "pot_provider_url": None,
}

SETTINGS_VALUES: dict[str, Any] = {
    "DAILY_CHANNEL_ID": "123456789012345678",
    "moderator_ids": ["123456789012345678"],
    "AI_PROVIDER": "openrouter",
    "OPENROUTER_MODEL": "openrouter/free",
    "GROQ_MODEL": "moonshotai/kimi-k2-instruct-0905",
    "MUSIC": copy.deepcopy(MUSIC_VALUES),
}


def _json_response(route: Route, payload: Any, *, status: int = 200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload, ensure_ascii=False),
    )


def _new_state() -> dict[str, Any]:
    values = copy.deepcopy(SETTINGS_VALUES)
    return {
        "authenticated": False,
        "settings": {
            "values": values,
            "saved_values": copy.deepcopy(values),
            "active_values": copy.deepcopy(values),
            "pending_restart": [],
            "revision": "a" * 64,
        },
        "settings_puts": [],
        "control_actions": [],
        "mutation_csrf": [],
        "logout_count": 0,
        "music": _new_music_state(),
    }


def _new_music_state() -> dict[str, Any]:
    return {
        "guild_id": GUILD_ID,
        "status": "playing",
        "session_id": 37,
        "generation": "fixture-generation-1",
        "current": {
            "id": "fixture-song",
            "title": XSS_PAYLOAD,
            "url": "https://music.example.invalid/fixture-song",
            "duration": 240,
            "thumbnail": None,
            "requester_id": "123456789012345678",
            "requester_name": XSS_PAYLOAD,
        },
        "elapsed_seconds": 74,
        "voice_channel_id": "123456789012345679",
        "voice_channel_name": "Smoke Test Voice",
        "loop_mode": "off",
        "queue": [],
    }


def _overview_fixture() -> dict[str, Any]:
    return {
        "ready": True,
        "latency_ms": 42,
        "uptime_seconds": 7320,
        "cpu_percent": 3.5,
        "memory_bytes": 256 * 1024 * 1024,
        "guilds": [{
            "id": GUILD_ID,
            "name": XSS_PAYLOAD,
            "icon": None,
            "member_count": 128,
        }],
        "cogs": ["Music", "Task"],
        "ping_total": 57,
        "cache": {
            "bytes": 32 * 1024 * 1024,
            "max_bytes": 1024 * 1024 * 1024,
            "files": 5,
            "pinned_files": 1,
        },
        "bot": {"name": "Dashboard Smoke Bot", "id": OWNER_ID},
        "active_players": 1,
    }


def _ping_fixture(url: str) -> dict[str, Any]:
    query = parse_qs(urlsplit(url).query)
    start = date.fromisoformat(query["start"][0])
    end = date.fromisoformat(query["end"][0])
    history_start = max(start, end - timedelta(days=5))
    day_count = (end - start).days
    daily = []
    for offset in range(day_count + 1):
        current = start + timedelta(days=offset)
        known = current >= history_start
        daily.append({
            "date": current.isoformat(),
            "scheduled": 1 if known and offset % 2 == 0 else 0,
            "manual": 1 if known and offset % 3 == 0 else 0,
            "count": (1 if known and offset % 2 == 0 else 0)
            + (1 if known and offset % 3 == 0 else 0),
        })
    started = datetime.combine(history_start, datetime.min.time(), tzinfo=timezone.utc)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "period_total": 4,
        "unique_users": 2,
        "lifetime_total": 57,
        "legacy_total": 11,
        "history_started_at": int(started.timestamp()),
        "history_start_date": history_start.isoformat(),
        "daily": daily,
        "leaders": [{"user_id": "123456789012345678", "name": XSS_PAYLOAD, "count": 3}],
        "lifetime_leaders": [{"user_id": "123456789012345678", "name": XSS_PAYLOAD, "count": 57}],
        "events": [{
            "user_id": "123456789012345678",
            "name": XSS_PAYLOAD,
            "guild_id": GUILD_ID,
            "channel_id": "123456789012345679",
            "event_at": int(time.time()),
            "source": "scheduled",
        }],
    }


def _merge_settings(current: dict[str, Any], submitted: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(current)
    for key, value in submitted.items():
        if key == "MUSIC" and isinstance(value, dict):
            result["MUSIC"].update(copy.deepcopy(value))
        else:
            result[key] = copy.deepcopy(value)
    return result


def _api_route(route: Route, state: dict[str, Any]) -> None:
    request = route.request
    path = urlsplit(request.url).path
    method = request.method.upper()

    if path == "/api/session":
        if not state["authenticated"]:
            _json_response(route, {"error": "請先登入。"}, status=401)
            return
        _json_response(route, {
            "user": {"name": OWNER_NAME, "id": OWNER_ID, "avatar": None},
            "csrf_token": CSRF_TOKEN,
        })
        return

    if not state["authenticated"]:
        _json_response(route, {"error": "請先登入。"}, status=401)
        return

    if method != "GET":
        csrf = request.headers.get("x-csrf-token", "")
        state["mutation_csrf"].append((path, csrf))

    if path == "/api/overview" and method == "GET":
        _json_response(route, _overview_fixture())
    elif path == "/api/ping" and method == "GET":
        _json_response(route, _ping_fixture(request.url))
    elif path == "/api/settings" and method == "GET":
        _json_response(route, state["settings"])
    elif path == "/api/settings" and method == "PUT":
        try:
            submitted = json.loads(request.post_data or "{}")
        except json.JSONDecodeError:
            _json_response(route, {"error": "invalid fixture request"}, status=400)
            return
        state["settings_puts"].append({
            "body": submitted,
            "csrf": request.headers.get("x-csrf-token", ""),
        })
        if len(state["settings_puts"]) == 1:
            _json_response(route, {"error": "fixture revision conflict"}, status=409)
            return
        values = _merge_settings(state["settings"]["values"], submitted.get("values", {}))
        state["settings"] = {
            "values": values,
            "saved_values": copy.deepcopy(values),
            "active_values": copy.deepcopy(SETTINGS_VALUES),
            "pending_restart": ["DAILY_CHANNEL_ID", "moderator_ids", "MUSIC.max_queue_size"],
            "revision": "b" * 64,
        }
        _json_response(route, state["settings"])
    elif path.startswith("/api/music/") and path.endswith("/control") and method == "POST":
        try:
            control = json.loads(request.post_data or "{}")
        except json.JSONDecodeError:
            _json_response(route, {"error": "invalid fixture request"}, status=400)
            return
        action = control.get("action")
        state["control_actions"].append(control)
        music = state["music"]
        if action == "pause":
            music["status"] = "paused"
        elif action == "resume":
            music["status"] = "playing"
        elif action == "loop":
            music["loop_mode"] = control.get("mode", "off")
        elif action == "stop":
            music["status"] = "stopped"
            music["session_id"] = None
            music["current"] = None
            music["loop_mode"] = "off"
            music["queue"] = []
        _json_response(route, {"ok": True})
    elif path.startswith("/api/music/") and method == "GET":
        _json_response(route, copy.deepcopy(state["music"]))
    else:
        _json_response(route, {"error": f"no fixture for {method} {path}"}, status=404)


def _logout_route(route: Route, state: dict[str, Any]) -> None:
    state["mutation_csrf"].append(("/auth/logout", route.request.headers.get("x-csrf-token", "")))
    state["logout_count"] += 1
    state["authenticated"] = False
    _json_response(route, {"ok": True})


def _install_routes(page: Page, state: dict[str, Any]) -> None:
    page.route("**/api/**", lambda route: _api_route(route, state))
    page.route("**/auth/logout", lambda route: _logout_route(route, state))


def _expect_no_horizontal_overflow(page: Page, viewport_name: str, view_name: str) -> None:
    dimensions = page.evaluate("""() => ({
        viewport: window.innerWidth,
        document: document.documentElement.scrollWidth,
        body: document.body.scrollWidth
    })""")
    assert dimensions["document"] <= dimensions["viewport"] + 1, (
        f"horizontal overflow at {viewport_name}/{view_name}: {dimensions}"
    )


def _screenshot(page: Page, directory: Path, name: str) -> None:
    page.wait_for_load_state('networkidle')
    page.screenshot(path=str(directory / f"{name}.png"), full_page=True, animations="disabled")


def _expect_control_and_refresh(page: Page, trigger) -> None:
    control_response: Response | None = None
    refresh_response: Response | None = None
    with page.expect_response(
        lambda response: response.request.method == "GET" and "/api/music/" in response.url
    ) as refresh:
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith("/control")
        ) as control:
            trigger()
        control_response = control.value
    refresh_response = refresh.value
    assert control_response.status == 200
    assert refresh_response.status == 200


def _exercise_dashboard(page: Page, state: dict[str, Any], screenshots: Path, viewport_name: str) -> None:
    titles = {
        "overview": "總覽",
        "ping": "Ping 分析",
        "music": "音樂播放",
        "settings": "設定",
    }
    # The caller has already authenticated the fixture session and reloaded.
    page.locator("#console").wait_for(state="visible")
    assert page.locator("#owner-name").inner_text() == OWNER_NAME
    assert page.locator("#page-title").inner_text() == titles["overview"]
    page.wait_for_function(
        "(payload) => document.querySelector('#guild-list')?.textContent.includes(payload)",
        arg=XSS_PAYLOAD,
    )
    _expect_no_horizontal_overflow(page, viewport_name, "overview")
    assert XSS_PAYLOAD in page.locator("#guild-list").inner_text()
    assert page.locator("#guild-list img[onerror]").count() == 0
    assert page.evaluate("window.__dashboardSmokeXss") is False
    _screenshot(page, screenshots, f"{viewport_name}-overview")

    for view in ("ping", "music", "settings"):
        page.locator(f'[data-view="{view}"]').click()
        page.locator(f"#view-{view}").wait_for(state="visible")
        page.wait_for_load_state("networkidle")
        assert page.locator("#page-title").inner_text() == titles[view]
        _expect_no_horizontal_overflow(page, viewport_name, view)
        _screenshot(page, screenshots, f"{viewport_name}-{view}")

        if view == "ping":
            page.wait_for_function(
                "() => document.querySelector('#history-note')?.textContent.includes('更早日期沒有')"
            )
            page.locator("#ping-chart svg").wait_for(state="visible")
            assert "更早日期沒有可分析的明細" in page.locator("#history-note").inner_text()
            assert page.locator("#ping-chart title").filter(has_text="尚未開始記錄").count() > 0
            assert XSS_PAYLOAD in page.locator("#ping-events").inner_text()
            assert page.locator("#ping-events img[onerror]").count() == 0
        elif view == "music":
            page.wait_for_function(
                "(payload) => document.querySelector('#song-title')?.textContent === payload",
                arg=XSS_PAYLOAD,
            )
            assert page.locator("#song-title").inner_text() == XSS_PAYLOAD
            assert page.locator("#song-requester").inner_text().endswith(XSS_PAYLOAD)
            assert page.locator("#queue-list").inner_text().startswith("待播清單目前是空的。")
            assert page.locator("#album img[onerror]").count() == 0
            assert page.evaluate("window.__dashboardSmokeXss") is False

            _expect_control_and_refresh(
                page, lambda: page.locator("#pause-music").click()
            )
            page.get_by_role("button", name="繼續播放").wait_for(state="visible")
            _expect_control_and_refresh(
                page, lambda: page.get_by_role("button", name="繼續播放").click()
            )
            page.get_by_role("button", name="暫停").wait_for(state="visible")
            _expect_control_and_refresh(
                page, lambda: page.locator("#loop-mode").select_option("queue")
            )
            assert page.locator("#loop-mode").input_value() == "queue"

            actions_before_cancel = len(state["control_actions"])
            page.locator('[data-action="stop"]').click()
            page.locator("#confirm-dialog").wait_for(state="visible")
            assert "停止並清空待播清單？" in page.locator("#confirm-title").inner_text()
            page.locator("#confirm-cancel").click()
            assert len(state["control_actions"]) == actions_before_cancel

            _expect_control_and_refresh(
                page,
                lambda: (
                    page.locator('[data-action="stop"]').click(),
                    page.locator("#confirm-dialog").wait_for(state="visible"),
                    page.locator("#confirm-ok").click(),
                ),
            )
            assert state["control_actions"][-1]["action"] == "stop"
            page.wait_for_function(
                "() => document.querySelector('#song-title')?.textContent === '等待下一首好歌'"
            )
            assert page.locator("#queue-list").inner_text().startswith("待播清單目前是空的。")
        elif view == "settings":
            daily = page.locator("#setting-DAILY_CHANNEL_ID")
            moderators = page.locator("#setting-moderator_ids")
            queue_size = page.locator("#setting-MUSIC-max_queue_size")
            page.wait_for_function(
                "(value) => document.querySelector('#setting-DAILY_CHANNEL_ID')?.value === value",
                arg=SETTINGS_VALUES["DAILY_CHANNEL_ID"],
            )
            assert daily.input_value() == SETTINGS_VALUES["DAILY_CHANNEL_ID"]
            assert moderators.input_value() == SETTINGS_VALUES["moderator_ids"][0]
            daily.fill(LARGE_DAILY_ID)
            moderators.fill("\n".join(LARGE_MODERATOR_IDS))
            queue_size.fill("120")

            with page.expect_response(
                lambda response: response.request.method == "PUT"
                and response.url.endswith("/api/settings")
            ) as conflict:
                page.get_by_role("button", name="儲存設定").click()
            assert conflict.value.status == 409
            assert "請先保留你的修改" in page.locator("#notice").inner_text()
            assert daily.input_value() == LARGE_DAILY_ID
            assert moderators.input_value() == "\n".join(LARGE_MODERATOR_IDS)

            with page.expect_response(
                lambda response: response.request.method == "PUT"
                and response.url.endswith("/api/settings")
            ) as saved:
                page.get_by_role("button", name="儲存設定").click()
            assert saved.value.status == 200
            assert page.locator("#pending-settings").is_visible()
            assert "等待重啟 Bot 生效" in page.locator("#pending-settings").inner_text()
            assert daily.input_value() == LARGE_DAILY_ID
            assert moderators.input_value() == "\n".join(LARGE_MODERATOR_IDS)
            assert len(state["settings_puts"]) == 2
            saved_body = state["settings_puts"][1]["body"]
            assert saved_body["values"]["DAILY_CHANNEL_ID"] == LARGE_DAILY_ID
            assert isinstance(saved_body["values"]["DAILY_CHANNEL_ID"], str)
            assert saved_body["values"]["moderator_ids"] == LARGE_MODERATOR_IDS
            assert all(item["csrf"] == CSRF_TOKEN for item in state["settings_puts"])
            assert page.evaluate("window.__dashboardSmokeXss") is False

    assert state["control_actions"][:3] == [
        {"action": "pause", "session_id": 37, "generation": "fixture-generation-1"},
        {"action": "resume", "session_id": 37, "generation": "fixture-generation-1"},
        {"action": "loop", "session_id": 37, "generation": "fixture-generation-1", "mode": "queue"},
    ]
    assert all(token == CSRF_TOKEN for _, token in state["mutation_csrf"])


def _run_viewport(browser: Browser, base_url: str, screenshots: Path, viewport_name: str,
                  width: int, height: int, *, test_logout: bool) -> list[str]:
    state = _new_state()
    page = browser.new_page(viewport={"width": width, "height": height})
    page.add_init_script("window.__dashboardSmokeXss = false;")
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    _install_routes(page, state)
    responses: dict[str, int] = {}

    def capture_response(response: Response) -> None:
        path = urlsplit(response.url).path
        if path in {"/", "/assets/app.js", "/assets/style.css"}:
            responses[path] = response.status

    page.on("response", capture_response)
    page.goto(base_url, wait_until="networkidle")
    page.locator("#login").wait_for(state="visible")
    assert page.locator("#console").is_hidden()
    assert page.locator(".login-button").get_attribute("href") == "/auth/login"
    _expect_no_horizontal_overflow(page, viewport_name, "login")
    _screenshot(page, screenshots, f"{viewport_name}-login")
    assert responses.get("/") == 200
    assert responses.get("/assets/app.js") == 200
    assert responses.get("/assets/style.css") == 200
    assert state["authenticated"] is False

    # The fixture authenticates only the mocked session API. The real login URL
    # remains untouched, and the shipped app must render the actual static UI.
    state["authenticated"] = True
    page.reload(wait_until="networkidle")
    _exercise_dashboard(page, state, screenshots, viewport_name)

    if test_logout:
        page.locator("#logout").click()
        page.locator("#login").wait_for(state="visible")
        assert page.locator("#console").is_hidden()
        assert state["authenticated"] is False
        assert state["logout_count"] == 1
        assert state["mutation_csrf"][-1] == ("/auth/logout", CSRF_TOKEN)
        _expect_no_horizontal_overflow(page, viewport_name, "logout-login")
        _screenshot(page, screenshots, f"{viewport_name}-logged-out")

    assert page_errors == [], f"page errors at {viewport_name}: {page_errors}"
    page.close()
    return page_errors


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help=f"dashboard URL (default: {DEFAULT_URL})")
    parser.add_argument(
        "--screenshots",
        type=Path,
        default=DEFAULT_SCREENSHOTS,
        help=f"directory for screenshots (default: {DEFAULT_SCREENSHOTS})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    screenshots = args.screenshots.expanduser().resolve()
    screenshots.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            _run_viewport(browser, args.url, screenshots, "desktop", 1440, 1000, test_logout=True)
            _run_viewport(browser, args.url, screenshots, "mobile", 390, 844, test_logout=False)
        finally:
            browser.close()

    print(f"Dashboard UI smoke passed. Screenshots: {screenshots}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
