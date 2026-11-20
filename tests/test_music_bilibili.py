import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest

from services.music_cache import (
    MusicCache,
    MusicError,
    has_playlist,
    normalize_bilibili_url,
    normalize_music_url,
    single_video_url,
)
from tests.test_music_cache import _config, _install_fake_runner

BVID = "BV1xx411c7mD"
VIDEO_URL = f"https://www.bilibili.com/video/{BVID}"


@pytest.mark.parametrize(("url", "expected"), [
    (VIDEO_URL, VIDEO_URL),
    (f"http://m.bilibili.com/video/{BVID}/?spm_id_from=333&t=20#reply", VIDEO_URL),
    (f"https://bilibili.com/video/{BVID}?p=2&share_source=copy_web", f"{VIDEO_URL}?p=2"),
    ("https://www.bilibili.com/video/av1074402/", "https://www.bilibili.com/video/av1074402"),
    ("https://www.bilibili.com/video/AV1074402?p=3", "https://www.bilibili.com/video/av1074402?p=3"),
    ("https://b23.tv/AbC123?share_source=copy#reply", "https://b23.tv/AbC123"),
    ("http://www.b23.tv/AbC123/", "https://b23.tv/AbC123"),
])
def test_bilibili_urls_keep_only_video_and_part(url, expected):
    assert normalize_bilibili_url(url) == expected
    assert normalize_music_url(url) == expected
    assert single_video_url(url) == expected
    assert not has_playlist(url)


@pytest.mark.parametrize("url", [
    "https://example.com/video/BV1xx411c7mD",
    "https://www.bilibili.com.evil.test/video/BV1xx411c7mD",
    "https://www.bilibili.com@127.0.0.1/video/BV1xx411c7mD",
    "https://user@www.bilibili.com/video/BV1xx411c7mD",
    "https://www.bilibili.com:443/video/BV1xx411c7mD",
    "https://www.bilibili.com:bad/video/BV1xx411c7mD",
    "file:///video/BV1xx411c7mD",
    "https://www.bili\nbili.com/video/BV1xx411c7mD",
    "https://www.bilibili.com/video/BV123",
    "https://www.bilibili.com/video/av0",
    "https://www.bilibili.com/video/BV1xx411c7mD/extra",
    "https://www.bilibili.com/video/../video/BV1xx411c7mD",
    "https://www.bilibili.com/video/%2Fetc",
    "https://www.bilibili.com/video/BV1xx411c7mD?p=0",
    "https://www.bilibili.com/video/BV1xx411c7mD?p=-1",
    "https://www.bilibili.com/video/BV1xx411c7mD?p=1.5",
    "https://www.bilibili.com/video/BV1xx411c7mD?p=1&p=2",
    "https://www.bilibili.com/video/BV1xx411c7mD?p=",
    "https://www.bilibili.com/video/BV1xx411c7mD?p=99999999999999",
    "https://live.bilibili.com/1234",
    "https://www.bilibili.com/bangumi/play/ep1234",
    "https://space.bilibili.com/1234/favlist?fid=5678",
    "https://b23.tv/../secret",
    "https://b23.tv/abc/def",
    "https://b23.tv/",
    "",
    None,
])
def test_invalid_bilibili_input_never_reaches_a_process(tmp_path, url):
    async def scenario():
        cache = MusicCache(_config(tmp_path))
        cache._spawn = AsyncMock()
        with pytest.raises(MusicError):
            await cache.resolve(url)
        cache._spawn.assert_not_awaited()
        await cache.close()
    asyncio.run(scenario())


def test_bilibili_downloads_parts_separately_and_replays_canonical_urls(tmp_path):
    async def scenario():
        cache = MusicCache(_config(tmp_path, max_cache_mb=4))
        metadata = {"id": BVID, "title": "First part", "duration": 10, "webpage_url": VIDEO_URL}
        calls = _install_fake_runner(cache, metadata)
        first, = await cache.resolve(VIDEO_URL, requester_id=42)
        assert first.id == f"bilibili_{BVID}_p1"
        assert first.url == f"{VIDEO_URL}?p=1"
        assert first.requester_id == 42
        path1 = await cache.acquire(first)
        await cache.release(first)
        metadata.update(id=f"{BVID}_p1")
        explicit_first, = await cache.resolve(f"{VIDEO_URL}?p=1")
        assert explicit_first.id == first.id
        assert await cache.acquire(explicit_first) == path1
        await cache.release(explicit_first)

        # The extractor's webpage URL may omit the part.  Its ID is decisive.
        metadata.update(id=f"{BVID}_p2", title="Second part")
        second, = await cache.resolve(f"{VIDEO_URL}?p=2")
        assert second.id == f"bilibili_{BVID}_p2"
        assert second.url == f"{VIDEO_URL}?p=2"
        path2 = await cache.acquire(second)
        await cache.release(second)
        assert path1 != path2
        assert path1.exists() and path2.exists()

        # Re-resolving the URL persisted by history reuses that part's file.
        replay, = await cache.resolve(second.url, requester_id=99)
        assert replay.id == second.id and replay.requester_id == 99
        assert await cache.acquire(replay) == path2
        await cache.release(replay)

        metadata.update(id=BVID)
        youtube, = await cache.resolve(f"https://www.youtube.com/watch?v={BVID}")
        path3 = await cache.acquire(youtube)
        assert path3 not in {path1, path2}
        await cache.release(youtube)
        downloads = [call for call in calls if "--output" in call]
        assert len(downloads) == 3
        assert downloads[0][-1] == first.url
        assert downloads[1][-1] == second.url
        assert all("bestaudio[acodec=opus]/bestaudio/best" in call for call in downloads)
        assert (await cache.cleanup(force=True))["removed_files"] == 3
        await cache.close()
    asyncio.run(scenario())


def test_bilibili_av_is_resolved_to_a_stable_bv_url(tmp_path):
    async def scenario():
        cache = MusicCache(_config(tmp_path))
        calls = _install_fake_runner(cache, {"id": f"{BVID}_p2", "duration": 10})
        track, = await cache.resolve("https://www.bilibili.com/video/av1074402?p=2")
        assert track.url == f"{VIDEO_URL}?p=2"
        assert track.id == f"bilibili_{BVID}_p2"
        assert "--no-playlist" in calls[0]
        await cache.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("metadata", [
    {"id": "../../outside"},
    {"id": "BV1aa411c7mD"},
    {"id": f"{BVID}_p2"},
    {"id": f"{BVID}_400950101", "_type": "playlist", "entries": []},
    {"id": BVID, "is_live": True},
    {"id": BVID, "duration": 999999},
])
def test_bilibili_invalid_or_unplayable_metadata_is_rejected(tmp_path, metadata):
    async def scenario():
        cache = MusicCache(_config(tmp_path))
        _install_fake_runner(cache, metadata)
        with pytest.raises(MusicError):
            await cache.resolve(VIDEO_URL)
        await cache.close()
    asyncio.run(scenario())


def test_bilibili_metadata_is_checked_again_after_a_restart(tmp_path):
    async def scenario():
        cache = MusicCache(_config(tmp_path))
        _install_fake_runner(cache, {"id": f"{BVID}_p2", "duration": 10})
        track, = await cache.resolve(f"{VIDEO_URL}?p=2")
        await cache.close()
        restarted = MusicCache(_config(tmp_path))
        calls = _install_fake_runner(restarted, {"id": f"{BVID}_p2", "duration": 10})
        path = await restarted.acquire(track)
        assert path.name == f"bilibili_{BVID}_p2.webm"
        assert calls[0][-1] == track.url
        await restarted.release(track)
        await restarted.close()
    asyncio.run(scenario())


def _redirects(monkeypatch, locations, *, status=302):
    requested = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        @asynccontextmanager
        async def get(self, url, *, allow_redirects):
            assert allow_redirects is False
            requested.append(url)
            location = locations[min(len(requested) - 1, len(locations) - 1)]
            if isinstance(location, BaseException):
                raise location
            yield SimpleNamespace(status=status, headers={"Location": location} if location else {})

    monkeypatch.setattr(aiohttp, "ClientSession", lambda **kwargs: Session())
    return requested


def test_b23_redirects_are_validated_before_resolving_metadata(tmp_path, monkeypatch):
    requested = _redirects(monkeypatch, ["/Second", f"{VIDEO_URL}?p=2&share_source=copy"])

    async def scenario():
        cache = MusicCache(_config(tmp_path))
        calls = _install_fake_runner(cache, {"id": f"{BVID}_p2", "duration": 10})
        track, = await cache.resolve("https://b23.tv/First")
        assert track.url == f"{VIDEO_URL}?p=2"
        assert calls[0][-1] == track.url
        assert requested == ["https://b23.tv/First", "https://b23.tv/Second"]
        await cache.close()
    asyncio.run(scenario())


@pytest.mark.parametrize(("destination", "status", "request_count"), [
    ("http://127.0.0.1/private", 302, 1),
    ("https://www.youtube.com/watch?v=abc123", 302, 1),
    ("https://www.bilibili.com:8443/video/BV1xx411c7mD", 302, 1),
    ("https://www.bilibili.com/bangumi/play/ep1234", 302, 1),
    ("/Forever", 302, 5),
    (None, 302, 1),
    (VIDEO_URL, 200, 1),
    (aiohttp.ClientError("offline"), 302, 1),
    (asyncio.TimeoutError(), 302, 1),
])
def test_b23_rejects_bad_redirects_without_fetching_them(
    tmp_path, monkeypatch, destination, status, request_count,
):
    requested = _redirects(monkeypatch, [destination], status=status)

    async def scenario():
        cache = MusicCache(_config(tmp_path))
        cache._spawn = AsyncMock()
        with pytest.raises(MusicError):
            await cache.resolve("https://b23.tv/First")
        cache._spawn.assert_not_awaited()
        assert len(requested) == request_count
        assert all(url.startswith("https://b23.tv/") for url in requested)
        await cache.close()
    asyncio.run(scenario())
