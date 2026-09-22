import asyncio
import json
from pathlib import Path

import pytest

from services.music_cache import (
    MusicCache,
    MusicConfig,
    MusicError,
    Track,
    has_playlist,
    normalize_youtube_url,
    single_video_url,
)


class _FakeProcess:
    def __init__(self, *, output=b"", error=b"", write_path=None, size=32, delay=0):
        self.output = output
        self.error = error
        self.write_path = write_path
        self.size = size
        self.delay = delay
        self.returncode = None
        self.pid = None
        self.killed = False

    async def communicate(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.write_path is not None:
            self.write_path.write_bytes(b"x" * self.size)
        self.returncode = 0
        return self.output, self.error

    async def wait(self):
        if self.returncode is None:
            self.returncode = -9 if self.killed else 0
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def _config(tmp_path, **overrides):
    values = {
        "cache_dir": tmp_path,
        "max_cache_mb": 1,
        "max_file_mb": 1,
        "download_timeout_seconds": 5,
        "cleanup_interval_seconds": 60,
    }
    values.update(overrides)
    return MusicConfig(**values)


def test_youtube_urls_are_canonical_and_strict():
    assert normalize_youtube_url(
        "https://youtu.be/abc123?t=30&list=playlist_1#now",
    ) == "https://www.youtube.com/watch?v=abc123&list=playlist_1"
    assert normalize_youtube_url("http://m.youtube.com/shorts/abc123") == (
        "https://www.youtube.com/watch?v=abc123"
    )
    assert normalize_youtube_url("https://www.youtube.com/playlist?list=playlist_1") == (
        "https://www.youtube.com/playlist?list=playlist_1"
    )
    assert has_playlist("https://www.youtube.com/watch?v=abc123&list=playlist_1")
    assert single_video_url("https://www.youtube.com/watch?v=abc123&list=playlist_1") == (
        "https://www.youtube.com/watch?v=abc123"
    )

    with pytest.raises(MusicError):
        normalize_youtube_url("https://example.test/watch?v=abc123")
    with pytest.raises(MusicError):
        normalize_youtube_url("https://www.youtube.com:443/watch?v=abc123")
    with pytest.raises(MusicError):
        normalize_youtube_url("https://www.youtube.com/watch?v=../etc")


def test_music_config_defaults_and_validation(tmp_path):
    config = MusicConfig.from_settings({}, tmp_path)
    assert config.cache_dir == tmp_path / "data" / "music"
    assert config.max_cache_mb == 1024
    assert config.max_file_mb == 100
    assert config.auto_cleanup is True

    with pytest.raises(MusicError, match="max_file_mb"):
        MusicConfig.from_settings(
            {"MUSIC": {"max_cache_mb": 2, "max_file_mb": 3}}, tmp_path,
        )
    with pytest.raises(MusicError, match="max_queue_size"):
        MusicConfig.from_settings({"MUSIC": {"max_queue_size": 0}}, tmp_path)
    with pytest.raises(MusicError, match="auto_cleanup"):
        MusicConfig.from_settings({"MUSIC": {"auto_cleanup": "yes"}}, tmp_path)


def _install_fake_runner(cache, metadata, *, size=32, delay=0):
    calls = []

    async def spawn(args):
        calls.append(args)
        if "--dump-single-json" in args:
            return _FakeProcess(output=json.dumps(metadata).encode())
        output_template = Path(args[args.index("--output") + 1])
        return _FakeProcess(
            write_path=Path(str(output_template).replace("%(ext)s", "webm")),
            size=size,
            delay=delay,
        )

    cache._spawn = spawn
    return calls


def test_acquire_shares_download_and_pins_until_balanced_release(tmp_path):
    asyncio.run(_test_acquire_shares_download_and_pins_until_balanced_release(tmp_path))


async def _test_acquire_shares_download_and_pins_until_balanced_release(tmp_path):
    cache = MusicCache(_config(tmp_path))
    metadata = {
        "id": "abc123",
        "title": "Test song",
        "duration": 10,
        "webpage_url": "https://www.youtube.com/watch?v=abc123",
    }
    calls = _install_fake_runner(cache, metadata)
    track = Track(
        "abc123", "Test song", "https://www.youtube.com/watch?v=abc123", 10,
    )

    first, second = await asyncio.gather(cache.acquire(track), cache.acquire(track))
    assert first == second == tmp_path / "abc123.webm"
    assert sum("--output" in call for call in calls) == 1
    assert (await cache.stats())["pinned_files"] == 1

    await cache.release(track)
    assert (await cache.stats())["pinned_files"] == 1
    await cache.release(track)
    assert (await cache.stats())["pinned_files"] == 0
    with pytest.raises(MusicError):
        await cache.release(track)

    assert await cache.cleanup(force=True) == {"removed_files": 1, "freed_bytes": 32}
    await cache.close()


def test_auto_cleanup_evicts_unpinned_but_never_pinned_files(tmp_path):
    asyncio.run(_test_auto_cleanup_evicts_unpinned_but_never_pinned_files(tmp_path))


async def _test_auto_cleanup_evicts_unpinned_but_never_pinned_files(tmp_path):
    cache = MusicCache(_config(tmp_path))
    metadata = {
        "id": "abc123",
        "title": "Test song",
        "duration": 10,
        "webpage_url": "https://www.youtube.com/watch?v=abc123",
    }
    _install_fake_runner(cache, metadata, size=700_000)
    first = Track("abc123", "First", "https://www.youtube.com/watch?v=abc123", 10)
    await cache.acquire(first)
    await cache.release(first)

    second_metadata = {**metadata, "id": "def456", "title": "Second"}
    metadata.update(second_metadata)
    second = Track("def456", "Second", "https://www.youtube.com/watch?v=def456", 10)
    await cache.acquire(second)
    assert not (tmp_path / "abc123.webm").exists()
    assert (tmp_path / "def456.webm").exists()
    await cache.release(second)

    third_metadata = {**metadata, "id": "ghi789", "title": "Third"}
    metadata.update(third_metadata)
    third = Track("ghi789", "Third", "https://www.youtube.com/watch?v=ghi789", 10)
    await cache.acquire(third)
    await cache.release(third)
    assert (tmp_path / "def456.webm").exists() is False
    await cache.close()


def test_pinned_cache_rejects_capacity_and_cancellation_cleans_partial(tmp_path):
    asyncio.run(_test_pinned_cache_rejects_capacity_and_cancellation_cleans_partial(tmp_path))


async def _test_pinned_cache_rejects_capacity_and_cancellation_cleans_partial(tmp_path):
    cache = MusicCache(_config(tmp_path, auto_cleanup=False))
    metadata = {
        "id": "abc123",
        "title": "Test song",
        "duration": 10,
        "webpage_url": "https://www.youtube.com/watch?v=abc123",
    }
    _install_fake_runner(cache, metadata, size=700_000)
    first = Track("abc123", "First", "https://www.youtube.com/watch?v=abc123", 10)
    await cache.acquire(first)
    second = Track("def456", "Second", "https://www.youtube.com/watch?v=def456", 10)
    metadata.update({"id": "def456", "title": "Second"})
    with pytest.raises(MusicError, match="空間不足"):
        await cache.acquire(second)
    assert (tmp_path / "abc123.webm").exists()
    await cache.release(first)
    await cache.cleanup(force=True)

    metadata.update({"id": "ghi789", "title": "Slow"})
    slow = Track("ghi789", "Slow", "https://www.youtube.com/watch?v=ghi789", 10)
    processes = []

    async def slow_spawn(args):
        if "--dump-single-json" in args:
            return _FakeProcess(output=json.dumps(metadata).encode())
        output_template = Path(args[args.index("--output") + 1])
        process = _FakeProcess(
            write_path=Path(str(output_template).replace("%(ext)s", "webm")),
            delay=30,
        )
        processes.append(process)
        return process

    cache._spawn = slow_spawn
    pending = asyncio.create_task(cache.acquire(slow))
    await asyncio.sleep(0.1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert processes and processes[-1].killed
    assert not (tmp_path / "ghi789.webm").exists()
    await cache.close()


def test_fragment_files_count_toward_limits_and_manual_cleanup(tmp_path):
    async def scenario():
        cache = MusicCache(_config(tmp_path))
        names = [
            'abc123.webm.part',
            'abc123.webm.part-Frag1',
            'abc123.webm.part-Frag2.part',
            'abc123.webm.ytdl',
        ]
        for name in names:
            (tmp_path / name).write_bytes(b'a' * 100)
        unrelated = tmp_path / 'keep.txt'
        unrelated.write_text('leave this file alone')
        stats = await cache.stats()
        assert stats['bytes'] == 400
        assert stats['files'] == 4
        assert cache._track_usage('abc123') == 400
        cache._inflight_ids.add('abc123')
        assert (await cache.cleanup(force=True))['removed_files'] == 0
        cache._inflight_ids.clear()
        assert await cache.cleanup(force=True) == {'removed_files': 4, 'freed_bytes': 400}
        assert unrelated.exists()
        for name in names:
            (tmp_path / name).write_bytes(b'b')
        cache._remove_download_artifacts('abc123')
        assert (await cache.stats())['files'] == 0
        assert unrelated.exists()
        await cache.close()
    asyncio.run(scenario())
