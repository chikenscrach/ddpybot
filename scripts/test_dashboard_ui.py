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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Browser, Page, Response, Route, expect, sync_playwright

DEFAULT_URL = "http://127.0.0.1:8088"
DEFAULT_SCREENSHOTS = Path("/tmp/ddpybot-dashboard-ui")
OWNER_NAME = "Dashboard Fixture Owner"
OWNER_ID = "18446744073709551614"
GUILD_ID = "18446744073709551613"
LARGE_DAILY_ID = "18446744073709551615"
LARGE_MODERATOR_IDS = ["18446744073709551614", "9223372036854775807"]
XSS_PAYLOAD = '<img src=x onerror="window.__dashboardSmokeXss = true">'
CSRF_TOKEN = "dashboard-ui-fixture-csrf"
OTHER_GUILD_ID = "18446744073709551612"
HISTORY_REQUESTER_ID = "123456789012345678"
HISTORY_OTHER_REQUESTER_ID = "123456789012345681"
MUSIC_HISTORY = [
    {
        "id": 9000 + index,
        "guild_id": GUILD_ID,
        "requester_id": HISTORY_REQUESTER_ID if index < 11 else HISTORY_OTHER_REQUESTER_ID,
        "requester_name": "Music Listener" if index < 11 else XSS_PAYLOAD,
        "title": XSS_PAYLOAD if index == 0 else f"History Track {index + 1}",
        "url": "javascript:alert(1)" if index == 1 else f"https://music.example.invalid/track-{index + 1}",
        "duration": 95 + index,
        "thumbnail": None,
        "played_at": int(datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp()) - index * 300,
    }
    for index in range(12)
]
PING_EVENTS = (
    {"day": "2026-10-01", "user_id": "123456789012345678", "name": XSS_PAYLOAD,
     "guild_id": GUILD_ID, "source": "scheduled"},
    {"day": "2026-10-02", "user_id": "123456789012345678", "name": XSS_PAYLOAD,
     "guild_id": GUILD_ID, "source": "scheduled"},
    {"day": "2026-10-03", "user_id": "123456789012345680", "name": "Other Guild User",
     "guild_id": OTHER_GUILD_ID, "source": "scheduled"},
    {"day": "2026-10-02", "user_id": "123456789012345681", "name": "Manual Only User",
     "guild_id": GUILD_ID, "source": "manual"},
)

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
        "ping_queries": [],
        "music_history_queries": [],
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
        }, {
            "id": OTHER_GUILD_ID,
            "name": "History Empty Server",
            "icon": None,
            "member_count": 42,
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
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    start = date.fromisoformat(query["start"][0])
    end = date.fromisoformat(query["end"][0])
    guild_id = query.get("guild_id", [""])[0]
    source = query.get("source", [""])[0]
    events = [
        event for event in PING_EVENTS
        if start.isoformat() <= event["day"] <= end.isoformat()
        and (not guild_id or event["guild_id"] == guild_id)
        and (source in {"", "all"} or event["source"] == source)
    ]
    events.sort(key=lambda event: (event["day"], event["user_id"]), reverse=True)
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        leader = grouped.setdefault(event["user_id"], {
            "user_id": event["user_id"], "name": event["name"], "count": 0,
        })
        leader["count"] += 1
    started = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    response_events = [
        {
            "user_id": event["user_id"],
            "name": event["name"],
            "guild_id": event["guild_id"],
            "channel_id": "123456789012345679",
            "event_at": int(datetime.fromisoformat(event["day"]).replace(tzinfo=timezone.utc).timestamp()),
            "source": event["source"],
        }
        for event in events
    ]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "period_total": len(events),
        "unique_users": len(grouped),
        "lifetime_total": 57,
        "legacy_total": 11,
        "history_started_at": int(started.timestamp()),
        "history_start_date": start.isoformat(),
        "daily": [],
        "leaders": sorted(grouped.values(), key=lambda leader: (-leader["count"], leader["user_id"])),
        "lifetime_leaders": [{"user_id": "123456789012345678", "name": XSS_PAYLOAD, "count": 57}],
        "events": response_events,
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
        state["ping_queries"].append(parse_qs(urlsplit(request.url).query, keep_blank_values=True))
        _json_response(route, _ping_fixture(request.url))
    elif path.startswith("/api/music/") and path.endswith("/history") and method == "GET":
        parts = path.strip("/").split("/")
        guild_id = parts[2]
        query = parse_qs(urlsplit(request.url).query, keep_blank_values=True)
        limit = max(1, int(query.get("limit", ["10"])[0]))
        offset = max(0, int(query.get("offset", ["0"])[0]))
        requester_id = query.get("requester_id", [""])[0]
        state["music_history_queries"].append({
            "guild_id": guild_id,
            "requester_id": requester_id,
            "limit": limit,
            "offset": offset,
        })
        guild_items = [item for item in MUSIC_HISTORY if item["guild_id"] == guild_id]
        requesters = {
            item["requester_id"]: {
                "id": item["requester_id"],
                "name": item["requester_name"],
            }
            for item in guild_items
        }
        filtered = [
            item for item in guild_items
            if not requester_id or item["requester_id"] == requester_id
        ]
        filtered.sort(key=lambda item: (item["played_at"], item["id"]), reverse=True)
        _json_response(route, {
            "items": filtered[offset : offset + limit],
            "total": len(filtered),
            "limit": limit,
            "offset": offset,
            "requesters": sorted(requesters.values(), key=lambda item: item["id"]),
        })
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
        snapshot = copy.deepcopy(state["music"])
        guild_id = path.strip("/").split("/")[2]
        if guild_id == OTHER_GUILD_ID:
            snapshot.update({
                "guild_id": OTHER_GUILD_ID,
                "status": "disconnected",
                "session_id": None,
                "current": None,
                "voice_channel_id": None,
                "voice_channel_name": None,
                "queue": [],
            })
        _json_response(route, snapshot)
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


def _apply_ping_filter(page: Page, state: dict[str, Any], start: str, end: str,
                       *, expected_total: int, guild_id: str = "") -> None:
    page.locator("#ping-start").fill(start)
    page.locator("#ping-end").fill(end)
    page.locator("#ping-guild").select_option(guild_id)
    with page.expect_response(
        lambda response: response.request.method == "GET"
        and urlsplit(response.url).path == "/api/ping"
    ) as ping_response:
        page.get_by_role("button", name="套用篩選").click()
    response = ping_response.value
    assert response.status == 200

    expected = {
        "start": [start],
        "end": [end],
        "source": ["scheduled"],
        "guild_id": [guild_id],
    }
    expect(page.locator("#export-ping")).to_have_attribute(
        "href", f"/api/ping/export?{urlsplit(response.url).query}"
    )
    metric = page.locator("#ping-metrics .metric").filter(has_text="區間標記")
    expect(metric.locator(".metric-value")).to_have_text(f"{expected_total}次")
    expect(metric.locator(".metric-detail")).to_have_text(f"{start} — {end}")
    actual = parse_qs(urlsplit(response.url).query, keep_blank_values=True)
    assert actual == expected
    assert state["ping_queries"][-1] == expected
    export_query = parse_qs(
        urlsplit(page.locator("#export-ping").get_attribute("href") or "").query,
        keep_blank_values=True,
    )
    assert export_query == expected


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
            assert page.locator("#ping-source, #ping-chart, #daily-table").count() == 0
            assert page.locator("#view-ping .chart-panel, #view-ping svg").count() == 0
            assert page.get_by_text("每日標記紀錄", exact=True).count() == 0
            assert state["ping_queries"]
            initial_query = state["ping_queries"][-1]
            assert initial_query.get("source") == ["scheduled"]
            assert initial_query.get("guild_id") == [""]
            assert initial_query.get("start", [""])[0]
            assert initial_query.get("end", [""])[0]
            assert parse_qs(
                urlsplit(page.locator("#export-ping").get_attribute("href") or "").query,
                keep_blank_values=True,
            ) == initial_query

            _apply_ping_filter(page, state, "2026-10-01", "2026-10-03", expected_total=3)
            period_metric = page.locator("#ping-metrics .metric").filter(has_text="區間標記")
            assert "3次" in period_metric.inner_text().replace("\n", "")
            assert "2026-10-01 — 2026-10-03" in period_metric.inner_text()
            assert XSS_PAYLOAD in page.locator("#period-leaders").inner_text()
            assert "2次" in page.locator("#period-leaders").inner_text()
            assert "Other Guild User" in page.locator("#period-leaders").inner_text()
            assert "Manual Only User" not in page.locator("#period-leaders").inner_text()
            assert XSS_PAYLOAD in page.locator("#ping-events").inner_text()
            assert "Other Guild User" in page.locator("#ping-events").inner_text()
            assert "Manual Only User" not in page.locator("#ping-events").inner_text()
            assert page.locator("#ping-events img[onerror]").count() == 0
            assert page.locator("#period-leaders img[onerror]").count() == 0
            assert page.evaluate("window.__dashboardSmokeXss") is False
            _screenshot(page, screenshots, f"{viewport_name}-ping-with-records")

            _apply_ping_filter(
                page, state, "2026-10-01", "2026-10-03", expected_total=2, guild_id=GUILD_ID
            )
            period_metric = page.locator("#ping-metrics .metric").filter(has_text="區間標記")
            assert "2次" in period_metric.inner_text().replace("\n", "")
            assert XSS_PAYLOAD in page.locator("#period-leaders").inner_text()
            assert "Other Guild User" not in page.locator("#period-leaders").inner_text()
            assert XSS_PAYLOAD in page.locator("#ping-events").inner_text()
            assert "Other Guild User" not in page.locator("#ping-events").inner_text()
            assert "Manual Only User" not in page.locator("#ping-events").inner_text()

            _apply_ping_filter(page, state, "2026-10-03", "2026-10-03", expected_total=1)
            period_metric = page.locator("#ping-metrics .metric").filter(has_text="區間標記")
            assert "1次" in period_metric.inner_text().replace("\n", "")
            assert "Other Guild User" in page.locator("#period-leaders").inner_text()
            assert "Other Guild User" in page.locator("#ping-events").inner_text()
            assert XSS_PAYLOAD not in page.locator("#period-leaders").inner_text()
            assert XSS_PAYLOAD not in page.locator("#ping-events").inner_text()
            assert page.locator("#ping-events table tbody tr").count() == 1

            _apply_ping_filter(page, state, "2026-10-04", "2026-10-05", expected_total=0)
            period_metric = page.locator("#ping-metrics .metric").filter(has_text="區間標記")
            assert "0次" in period_metric.inner_text().replace("\n", "")
            assert "尚無標記紀錄" in page.locator("#period-leaders").inner_text()
            assert "Other Guild User" not in page.locator("#period-leaders").inner_text()
            assert page.locator("#ping-events table tbody tr").count() == 0
            assert "Other Guild User" not in page.locator("#ping-events").inner_text()
        elif view == "music":
            page.wait_for_function(
                "(payload) => document.querySelector('#song-title')?.textContent === payload",
                arg=XSS_PAYLOAD,
            )
            page.wait_for_function(
                "() => document.querySelector('#music-history-list .music-history-row')?.textContent"
            )
            assert page.locator("#song-title").inner_text() == XSS_PAYLOAD
            assert page.locator("#song-requester").inner_text().endswith(XSS_PAYLOAD)
            assert page.locator("#queue-list").inner_text().startswith("待播清單目前是空的。")
            assert page.locator("#album img[onerror]").count() == 0
            assert page.locator("#music-history-total").inner_text() == "12 筆"
            assert page.locator("#music-history-list .music-history-row").count() == 10
            assert page.locator("#music-history-page").inner_text() == "第 1 / 2 頁"
            first_history_row = page.locator("#music-history-list .music-history-row").first
            assert first_history_row.locator(".music-history-title").inner_text() == XSS_PAYLOAD
            assert first_history_row.locator("a.music-history-title").get_attribute("href") == (
                "https://music.example.invalid/track-1"
            )
            assert "1:35" in first_history_row.locator(".music-history-time").inner_text()
            unsafe_url_row = page.locator("#music-history-list .music-history-row").nth(1)
            assert unsafe_url_row.locator(".music-history-title").inner_text() == "History Track 2"
            assert unsafe_url_row.locator("a.music-history-title").count() == 0
            assert page.locator("#music-history-list a[href^='javascript:']").count() == 0
            assert page.locator("#music-history-list button").count() == 0
            assert page.locator("#music-history-list img[onerror]").count() == 0
            assert page.evaluate("window.__dashboardSmokeXss") is False
            _screenshot(page, screenshots, f"{viewport_name}-music-history")

            with page.expect_response(
                lambda response: response.request.method == "GET"
                and urlsplit(response.url).path == f"/api/music/{GUILD_ID}/history"
                and parse_qs(urlsplit(response.url).query).get("offset") == ["10"]
            ) as history_page_two:
                page.locator("#music-history-next").click()
            assert history_page_two.value.status == 200
            assert page.locator("#music-history-list .music-history-row").count() == 2
            assert page.locator("#music-history-page").inner_text() == "第 2 / 2 頁"
            assert state["music_history_queries"][-1] == {
                "guild_id": GUILD_ID,
                "requester_id": "",
                "limit": 10,
                "offset": 10,
            }
            with page.expect_response(
                lambda response: response.request.method == "GET"
                and urlsplit(response.url).path == f"/api/music/{GUILD_ID}/history"
                and parse_qs(urlsplit(response.url).query).get("offset") == ["0"]
            ) as history_page_one:
                page.locator("#music-history-prev").click()
            assert history_page_one.value.status == 200
            expect(page.locator("#music-history-list .music-history-row")).to_have_count(10)
            expect(page.locator("#music-history-page")).to_have_text("第 1 / 2 頁")

            with page.expect_response(
                lambda response: response.request.method == "GET"
                and urlsplit(response.url).path == f"/api/music/{GUILD_ID}/history"
                and parse_qs(urlsplit(response.url).query).get("requester_id")
                == [HISTORY_OTHER_REQUESTER_ID]
            ) as history_requester_filter:
                page.locator("#music-history-requester").select_option(
                    HISTORY_OTHER_REQUESTER_ID
                )
            assert history_requester_filter.value.status == 200
            expect(page.locator("#music-history-total")).to_have_text("1 筆")
            expect(page.locator("#music-history-list .music-history-row")).to_have_count(1)
            assert XSS_PAYLOAD in page.locator("#music-history-list").inner_text()
            assert page.locator("#music-history-list img[onerror]").count() == 0
            assert page.evaluate("window.__dashboardSmokeXss") is False

            with page.expect_response(
                lambda response: response.request.method == "GET"
                and urlsplit(response.url).path == f"/api/music/{GUILD_ID}/history"
                and parse_qs(urlsplit(response.url).query).get("requester_id")
                == [HISTORY_REQUESTER_ID]
            ) as history_primary_requester:
                page.locator("#music-history-requester").select_option(
                    HISTORY_REQUESTER_ID
                )
            assert history_primary_requester.value.status == 200
            expect(page.locator("#music-history-total")).to_have_text("11 筆")
            expect(page.locator("#music-history-page")).to_have_text("第 1 / 2 頁")
            with page.expect_response(
                lambda response: response.request.method == "GET"
                and urlsplit(response.url).path == f"/api/music/{GUILD_ID}/history"
                and parse_qs(urlsplit(response.url).query).get("requester_id")
                == [HISTORY_REQUESTER_ID]
                and parse_qs(urlsplit(response.url).query).get("offset") == ["10"]
            ) as filtered_history_page_two:
                page.locator("#music-history-next").click()
            assert filtered_history_page_two.value.status == 200
            expect(page.locator("#music-history-list .music-history-row")).to_have_count(1)
            expect(page.locator("#music-history-page")).to_have_text("第 2 / 2 頁")

            with page.expect_response(
                lambda response: response.request.method == "GET"
                and urlsplit(response.url).path == f"/api/music/{OTHER_GUILD_ID}/history"
            ) as empty_guild_history:
                page.locator("#music-guild").select_option(OTHER_GUILD_ID)
            assert empty_guild_history.value.status == 200
            expect(page.locator("#music-history-requester")).to_have_value("")
            expect(page.locator("#music-history-page")).to_have_text("第 1 / 1 頁")
            expect(page.locator("#music-history-total")).to_have_text("0 筆")
            assert "沒有符合條件的播放紀錄" in page.locator("#music-history-list").inner_text()
            assert page.locator("#music-history-list button").count() == 0
            assert state["music_history_queries"][-1] == {
                "guild_id": OTHER_GUILD_ID,
                "requester_id": "",
                "limit": 10,
                "offset": 0,
            }
            expect(page.locator("#music-status")).to_have_text("已離線")

            with page.expect_response(
                lambda response: response.request.method == "GET"
                and urlsplit(response.url).path == f"/api/music/{GUILD_ID}"
            ) as reconnect_guild:
                page.locator("#music-guild").select_option(GUILD_ID)
            assert reconnect_guild.value.status == 200
            expect(page.locator("#pause-music")).to_be_enabled()

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
