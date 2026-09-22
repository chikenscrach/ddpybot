"""YouTube metadata resolution and on-disk audio cache.

The module deliberately keeps the yt-dlp process boundary here.  Callers only
deal in :class:`Track` objects and paths; they never receive an expiring
YouTube media URL.  Files are leased with ``acquire``/``release`` so a cache
cleanup cannot remove audio while another guild is using it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


class MusicError(Exception):
    """An expected music/cache error safe to show to a Discord user."""


_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_PLAYLIST_ID = _VIDEO_ID
_AUDIO_SUFFIXES = frozenset({
    ".aac",
    ".flac",
    ".m4a",
    ".mka",
    ".mp3",
    ".mp4",
    ".oga",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
})
_PART_SUFFIXES = frozenset({".part", ".ytdl", ".tmp"})
_YOUTUBE_HOSTS = frozenset({
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
})


def _validate_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _VIDEO_ID.fullmatch(value):
        raise MusicError(f"{label} 不是有效的 YouTube ID。")
    return value


def _query_value(query: Mapping[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    if len(values) != 1 or not values[0]:
        raise MusicError("YouTube 網址的參數格式不正確。")
    return values[0]


def normalize_youtube_url(url: str) -> str:
    """Validate a YouTube URL and return one stable canonical form.

    Only regular watch, Shorts, short-link, and playlist URLs are accepted.
    Tracking parameters, timestamps, and fragments are intentionally omitted
    from the returned URL.
    """

    if not isinstance(url, str) or not url.strip():
        raise MusicError("請提供 YouTube 網址。")
    raw = url.strip()
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise MusicError("YouTube 網址格式不正確。") from exc
    if parsed.scheme.lower() not in {"http", "https"} or parsed.username or parsed.password:
        raise MusicError("只接受有效的 YouTube http(s) 網址。")
    try:
        port = parsed.port
        hostname = parsed.hostname
    except ValueError as exc:
        raise MusicError("YouTube 網址格式不正確。") from exc
    if port is not None:
        raise MusicError("YouTube 網址不可包含自訂連接埠。")
    host = (hostname or "").lower().rstrip(".")
    if host not in _YOUTUBE_HOSTS:
        raise MusicError("只接受 YouTube 網址。")
    if "#" in parsed.netloc:
        raise MusicError("YouTube 網址格式不正確。")

    query = parse_qs(parsed.query, keep_blank_values=True)
    for key in query:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            raise MusicError("YouTube 網址的參數格式不正確。")

    path = unquote(parsed.path or "")
    if "//" in path:
        raise MusicError("YouTube 網址路徑不正確。")
    parts = [part for part in path.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise MusicError("YouTube 網址路徑不正確。")

    video_id: str | None = None
    playlist_id = _query_value(query, "list")
    if playlist_id is not None:
        _validate_id(playlist_id, "播放清單")

    if host in {"youtu.be", "www.youtu.be"}:
        if len(parts) != 1:
            raise MusicError("youtu.be 網址缺少影片 ID。")
        video_id = _validate_id(parts[0], "影片")
    else:
        path_lower = "/" + "/".join(parts).lower()
        if path_lower == "/watch":
            video_value = _query_value(query, "v")
            if video_value is not None:
                video_id = _validate_id(video_value, "影片")
            elif playlist_id is None:
                raise MusicError("YouTube watch 網址缺少影片或播放清單 ID。")
        elif len(parts) == 2 and parts[0].lower() == "shorts":
            video_id = _validate_id(parts[1], "影片")
        elif path_lower == "/playlist":
            if playlist_id is None:
                raise MusicError("YouTube playlist 網址缺少播放清單 ID。")
        else:
            raise MusicError("只接受 YouTube watch、shorts、短網址或 playlist 網址。")

    if video_id is not None:
        result = f"https://www.youtube.com/watch?v={video_id}"
        if playlist_id is not None:
            result += f"&list={playlist_id}"
        return result
    # At this point a playlist ID is guaranteed by the checks above.
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def has_playlist(url: str) -> bool:
    """Return whether a valid YouTube URL contains a playlist selection."""

    canonical = normalize_youtube_url(url)
    return _query_value(parse_qs(urlsplit(canonical).query), "list") is not None


def single_video_url(url: str) -> str | None:
    """Return the canonical single-video URL, or ``None`` for playlist URLs."""

    canonical = normalize_youtube_url(url)
    parsed = urlsplit(canonical)
    video_id = _query_value(parse_qs(parsed.query), "v")
    return f"https://www.youtube.com/watch?v={video_id}" if video_id else None


def _setting_number(section: Mapping[str, object], key: str, default: int | float, *, integer=False,
                   minimum: float = 0, allow_zero: bool = False) -> int | float:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        kind = "整數" if integer else "數字"
        raise MusicError(f"MUSIC.{key} 必須是{kind}。")
    if not math.isfinite(float(value)):
        raise MusicError(f"MUSIC.{key} 必須是有限數字。")
    if integer and int(value) != value:
        raise MusicError(f"MUSIC.{key} 必須是整數。")
    numeric = int(value) if integer else float(value)
    if numeric < minimum or (minimum == 0 and numeric == 0 and not allow_zero):
        comparator = ">=" if allow_zero else ">"
        raise MusicError(f"MUSIC.{key} 必須 {comparator} {minimum}。")
    return numeric


@dataclass(slots=True)
class MusicConfig:
    """Validated music settings used by both the cache and playback service."""

    cache_dir: Path = Path("data/music")
    max_cache_mb: int = 1024
    max_file_mb: int = 100
    max_duration_seconds: int = 1800
    max_queue_size: int = 100
    max_playlist_items: int = 50
    empty_channel_grace_seconds: int = 10
    auto_cleanup: bool = True
    cache_ttl_hours: float = 168
    cleanup_interval_seconds: int = 600
    download_timeout_seconds: int = 300
    ffmpeg_executable: str = "ffmpeg"
    js_runtime: str = "deno"

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)
        values = {
            "max_cache_mb": self.max_cache_mb,
            "max_file_mb": self.max_file_mb,
            "max_duration_seconds": self.max_duration_seconds,
            "max_queue_size": self.max_queue_size,
            "max_playlist_items": self.max_playlist_items,
            "empty_channel_grace_seconds": self.empty_channel_grace_seconds,
            "cleanup_interval_seconds": self.cleanup_interval_seconds,
            "download_timeout_seconds": self.download_timeout_seconds,
        }
        for key, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise MusicError(f"MUSIC.{key} 必須是整數。")
            minimum = 0 if key == "empty_channel_grace_seconds" else 1
            if value < minimum:
                comparator = ">=" if minimum == 0 else ">"
                raise MusicError(f"MUSIC.{key} 必須 {comparator} {minimum}。")
        if self.max_file_mb > self.max_cache_mb:
            raise MusicError("MUSIC.max_file_mb 不可大於 MUSIC.max_cache_mb。")
        if isinstance(self.auto_cleanup, bool) is False:
            raise MusicError("MUSIC.auto_cleanup 必須是布林值。")
        if isinstance(self.cache_ttl_hours, bool) or not isinstance(self.cache_ttl_hours, (int, float)):
            raise MusicError("MUSIC.cache_ttl_hours 必須是數字。")
        if not math.isfinite(float(self.cache_ttl_hours)) or self.cache_ttl_hours < 0:
            raise MusicError("MUSIC.cache_ttl_hours 必須大於或等於 0。")
        if not isinstance(self.ffmpeg_executable, str) or not self.ffmpeg_executable.strip():
            raise MusicError("MUSIC.ffmpeg_executable 不可為空。")
        if not isinstance(self.js_runtime, str) or not self.js_runtime.strip():
            raise MusicError("MUSIC.js_runtime 不可為空。")
        if not isinstance(self.cache_dir, Path):
            raise MusicError("MUSIC.cache_dir 必須是路徑。")

    @classmethod
    def from_settings(cls, settings: dict, root: Path) -> MusicConfig:
        if not isinstance(settings, Mapping):
            raise MusicError("設定必須是物件。")
        section = settings.get("MUSIC", {})
        if section is None:
            section = {}
        if not isinstance(section, Mapping):
            raise MusicError("MUSIC 設定必須是物件。")
        root = Path(root)
        raw_cache = section.get("cache_dir")
        if raw_cache is None or raw_cache == "":
            cache_dir = root / "data" / "music"
        elif isinstance(raw_cache, str):
            cache_path = Path(raw_cache).expanduser()
            cache_dir = cache_path if cache_path.is_absolute() else root / cache_path
        else:
            raise MusicError("MUSIC.cache_dir 必須是路徑字串。")

        max_cache_mb = _setting_number(section, "max_cache_mb", 1024, integer=True, minimum=1)
        max_file_mb = _setting_number(section, "max_file_mb", 100, integer=True, minimum=1)
        if max_file_mb > max_cache_mb:
            raise MusicError("MUSIC.max_file_mb 不可大於 MUSIC.max_cache_mb。")
        return cls(
            cache_dir=cache_dir,
            max_cache_mb=max_cache_mb,
            max_file_mb=max_file_mb,
            max_duration_seconds=_setting_number(
                section, "max_duration_seconds", 1800, integer=True, minimum=1,
            ),
            max_queue_size=_setting_number(
                section, "max_queue_size", 100, integer=True, minimum=1,
            ),
            max_playlist_items=_setting_number(
                section, "max_playlist_items", 50, integer=True, minimum=1,
            ),
            empty_channel_grace_seconds=_setting_number(
                section, "empty_channel_grace_seconds", 10, integer=True, minimum=0,
                allow_zero=True,
            ),
            auto_cleanup=section.get("auto_cleanup", True),
            cache_ttl_hours=_setting_number(
                section, "cache_ttl_hours", 168, minimum=0, allow_zero=True,
            ),
            cleanup_interval_seconds=_setting_number(
                section, "cleanup_interval_seconds", 600, integer=True, minimum=1,
            ),
            download_timeout_seconds=_setting_number(
                section, "download_timeout_seconds", 300, integer=True, minimum=1,
            ),
            ffmpeg_executable=section.get("ffmpeg_executable", "ffmpeg"),
            js_runtime=section.get("js_runtime", "deno"),
        )


@dataclass(slots=True)
class Track:
    id: str
    title: str
    url: str
    duration: float | None
    thumbnail: str | None = None
    requester_id: int = 0


@dataclass(slots=True)
class _CacheEntry:
    track: Track
    path: Path
    references: int = 0
    last_access: float = field(default_factory=time.time)
    size: int = 0


class MusicCache:
    """A bounded, reference-counted audio cache backed by yt-dlp."""

    def __init__(self, config: MusicConfig):
        self.config = config
        self.cache_dir = Path(config.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # State operations are deliberately short.  A separate lock serializes
        # yt-dlp downloads without making release/stats wait behind a network
        # operation that may run for several minutes.
        self._state_lock = asyncio.Lock()
        self._download_lock = asyncio.Lock()
        self._entries: dict[str, _CacheEntry] = {}
        self._known_metadata: dict[str, tuple[dict, bool]] = {}
        self._inflight_ids: set[str] = set()
        self._closed = False

        # A download can only produce these names; never use a path reported by
        # metadata or by an untrusted child process.
        self._cache_root = self.cache_dir.resolve()
        self._max_cache_bytes = config.max_cache_mb * 1024 * 1024
        self._max_file_bytes = config.max_file_mb * 1024 * 1024

    def _ensure_open(self) -> None:
        if self._closed:
            raise MusicError("音樂快取已關閉。")

    @staticmethod
    def _safe_track_id(track_id: object) -> str:
        return _validate_id(track_id, "影片")

    def _path_for_id(self, track_id: str, suffix: str) -> Path:
        self._safe_track_id(track_id)
        if suffix not in _AUDIO_SUFFIXES:
            raise MusicError("快取音檔格式不受支援。")
        path = self.cache_dir / f"{track_id}{suffix}"
        # Resolve the parent and name to make the invariant explicit even if a
        # caller configured a symlinked cache directory after construction.
        if path.parent.resolve() != self._cache_root:
            raise MusicError("音樂快取路徑不安全。")
        return path

    def _is_owned_file(self, path: Path) -> bool:
        try:
            if path.parent.resolve() != self._cache_root or path.is_symlink() or not path.is_file():
                return False
        except OSError:
            return False
        return True

    def _file_kind(self, path: Path) -> tuple[str, bool] | None:
        if not self._is_owned_file(path):
            return None
        name = path.name
        match = re.fullmatch(
            r"([A-Za-z0-9_-]{1,128})(\.[A-Za-z0-9]+)"
            r"(?:\.(part|ytdl|tmp)(?:-frag[0-9]+(?:\.part)?)?)?",
            name,
            flags=re.IGNORECASE,
        )
        if match is None or match.group(2).lower() not in _AUDIO_SUFFIXES:
            return None
        return match.group(1), match.group(3) is not None

    def _iter_owned_files(self):
        try:
            children = self.cache_dir.iterdir()
        except OSError:
            return
        for path in children:
            kind = self._file_kind(path)
            if kind is not None:
                yield path, kind[0], kind[1]

    def _directory_usage(self) -> int:
        total = 0
        for path, _, _ in self._iter_owned_files() or ():
            with contextlib.suppress(OSError):
                total += path.stat().st_size
        return total

    def _track_usage(self, track_id: str) -> int:
        total = 0
        for path, candidate_id, _ in self._iter_owned_files() or ():
            if candidate_id != track_id:
                continue
            with contextlib.suppress(OSError):
                total += path.stat().st_size
        return total

    def _find_cached_file(self, track_id: str) -> Path | None:
        candidates: list[tuple[float, Path]] = []
        for path, candidate_id, partial in self._iter_owned_files() or ():
            if candidate_id != track_id or partial:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            candidates.append((stat.st_mtime, path))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _remove_path(self, path: Path) -> int:
        if not self._is_owned_file(path):
            return 0
        try:
            size = path.stat().st_size
            path.unlink()
            return size
        except FileNotFoundError:
            return 0
        except OSError:
            return 0

    @staticmethod
    def _touch_path(path: Path) -> None:
        try:
            now = time.time()
            os.utime(path, (now, now))
        except (OSError, NotImplementedError):
            pass

    def _remove_download_artifacts(self, track_id: str, *, keep: Path | None = None) -> None:
        for path, candidate_id, _ in list(self._iter_owned_files() or ()):
            if candidate_id == track_id and (keep is None or path != keep):
                self._remove_path(path)

    @staticmethod
    def _redact_error(stderr: bytes | str) -> str:
        if isinstance(stderr, bytes):
            text = stderr.decode("utf-8", errors="replace")
        else:
            text = stderr
        text = re.sub(r"https?://\S+", "[url]", text)
        text = " ".join(text.split())
        if len(text) > 400:
            text = text[:400].rstrip() + "…"
        return text

    def _yt_base_args(self) -> list[str]:
        args = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-config",
            "--no-plugin-dirs",
            "--no-warnings",
            "--no-progress",
        ]
        if self.config.js_runtime:
            args.extend(["--js-runtimes", self.config.js_runtime])
        return args

    async def _spawn(self, args: list[str]):
        kwargs = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        else:
            kwargs["start_new_session"] = True
        return await asyncio.create_subprocess_exec(*args, **kwargs)

    @staticmethod
    async def _kill_windows_tree(pid: int) -> bool:
        try:
            import psutil
        except ImportError:
            return False

        def kill_tree() -> bool:
            try:
                root = psutil.Process(pid)
                children = root.children(recursive=True)
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                return True
            except psutil.AccessDenied:
                return False
            for child in reversed(children):
                with contextlib.suppress(psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):
                    child.kill()
            with contextlib.suppress(psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):
                root.kill()
            _, alive = psutil.wait_procs([*children, root], timeout=2)
            for child in alive:
                with contextlib.suppress(psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):
                    child.kill()
            return not alive

        try:
            return await asyncio.to_thread(kill_tree)
        except (OSError, RuntimeError):
            return False

    async def _terminate_process(self, process, communication: asyncio.Task | None = None) -> None:
        pid = getattr(process, "pid", None)
        if os.name == "nt" and pid:
            tree_killed = await self._kill_windows_tree(pid)
            if not tree_killed:
                # yt-dlp may start Deno/ffmpeg helpers.  Killing only the
                # Python parent leaves those children downloading in the
                # background, so terminate the process tree explicitly.
                try:
                    killer = await asyncio.create_subprocess_exec(
                        "taskkill", "/PID", str(pid), "/T", "/F",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    await asyncio.wait_for(killer.communicate(), 5)
                except (FileNotFoundError, OSError, asyncio.TimeoutError):
                    pass
        elif pid:
            if os.name != "nt":
                with contextlib.suppress(ProcessLookupError, OSError):
                    os.killpg(pid, signal.SIGTERM)
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError, OSError):
                process.kill()
        if communication is not None:
            # Let communicate drain the pipes after the child is dead.  A
            # cancelled communicate task can leave a full stdout pipe and make
            # process.wait hang indefinitely.
            try:
                await asyncio.wait_for(asyncio.shield(communication), 5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                communication.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await communication
            except Exception:
                communication.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await communication
        else:
            with contextlib.suppress(asyncio.TimeoutError, Exception):
                await asyncio.wait_for(process.wait(), 5)

    async def _run_metadata(self, args: list[str]) -> dict:
        try:
            process = await self._spawn(args)
        except FileNotFoundError as exc:
            raise MusicError("找不到 Python 或 yt-dlp，請先安裝 yt-dlp。") from exc
        communication = asyncio.create_task(process.communicate())
        try:
            output, error = await asyncio.wait_for(
                asyncio.shield(communication), self.config.download_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            await self._terminate_process(process, communication)
            raise MusicError("YouTube 資訊讀取逾時，請稍後再試。") from exc
        except asyncio.CancelledError:
            await self._terminate_process(process, communication)
            raise
        if process.returncode:
            detail = self._redact_error(error)
            suffix = f": {detail}" if detail else "。"
            raise MusicError(f"YouTube 資訊讀取失敗{suffix}")
        text = output.decode("utf-8", errors="replace").strip()
        if not text:
            raise MusicError("yt-dlp 沒有回傳影片資訊。")
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = None
            for line in reversed(text.splitlines()):
                with contextlib.suppress(json.JSONDecodeError):
                    value = json.loads(line)
                    break
            if value is None:
                raise MusicError("yt-dlp 回傳的影片資訊格式不正確。") from None
        if not isinstance(value, dict):
            raise MusicError("yt-dlp 回傳的影片資訊格式不正確。")
        return value

    @staticmethod
    def _duration(value: object) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            duration = float(value)
        except (TypeError, ValueError):
            return None
        return duration if math.isfinite(duration) and duration >= 0 else None

    def _reject_unplayable(self, metadata: Mapping[str, object]) -> None:
        def truthy(value: object) -> bool:
            return value is True or (
                isinstance(value, str) and value.strip().lower() in {"true", "yes", "1"}
            )

        live_status = str(metadata.get("live_status") or "").lower()
        if truthy(metadata.get("is_live")) or truthy(metadata.get("is_upcoming")) or live_status in {
            "is_live", "is_upcoming", "live", "upcoming",
        }:
            raise MusicError("目前不支援直播或尚未開始的 YouTube 影片。")
        duration = self._duration(metadata.get("duration"))
        if duration is not None and duration > self.config.max_duration_seconds:
            raise MusicError(
                f"歌曲長度超過限制（最多 {self.config.max_duration_seconds} 秒）。",
            )

    def _track_from_metadata(self, metadata: Mapping[str, object], fallback_url: str,
                             requester_id: int) -> Track:
        video_id = metadata.get("id")
        if not isinstance(video_id, str) or not _VIDEO_ID.fullmatch(video_id):
            candidate = single_video_url(str(metadata.get("webpage_url") or fallback_url))
            if candidate:
                video_id = _query_value(parse_qs(urlsplit(candidate).query), "v")
        video_id = _validate_id(video_id, "影片")
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        duration = self._duration(metadata.get("duration"))
        title = metadata.get("title")
        if not isinstance(title, str) or not title.strip():
            title = video_id
        thumbnail = metadata.get("thumbnail")
        if not isinstance(thumbnail, str) or not thumbnail.strip():
            thumbnail = None
        return Track(video_id, title.strip(), video_url, duration, thumbnail, requester_id)

    def _remember_metadata(self, track_id: str, metadata: Mapping[str, object], full: bool) -> None:
        # yt-dlp's full object can contain a large formats list.  Keep only the
        # fields needed to validate a track, and bound this process-local cache
        # because queues may contain many rejected or short-lived requests.
        fields = {
            key: metadata[key]
            for key in (
                "id", "title", "duration", "thumbnail", "webpage_url",
                "live_status", "is_live", "is_upcoming",
            )
            if key in metadata
        }
        self._known_metadata[track_id] = (fields, full)
        while len(self._known_metadata) > 1000:
            self._known_metadata.pop(next(iter(self._known_metadata)))

    async def resolve(self, url: str, *, playlist: bool = False, requester_id: int = 0) -> list[Track]:
        self._ensure_open()
        canonical = normalize_youtube_url(url)
        if not isinstance(requester_id, int) or isinstance(requester_id, bool) or requester_id < 0:
            raise MusicError("點歌者 ID 不正確。")

        is_list = playlist and has_playlist(canonical)
        if is_list:
            args = self._yt_base_args()
            args.extend([
                "--dump-single-json",
                "--skip-download",
                "--flat-playlist",
                "--playlist-end",
                str(self.config.max_playlist_items),
                canonical,
            ])
            metadata = await self._run_metadata(args)
            entries = metadata.get("entries")
            if not isinstance(entries, list):
                raise MusicError("這個播放清單沒有可播放的歌曲。")
            tracks: list[Track] = []
            for entry in entries[: self.config.max_playlist_items]:
                if not isinstance(entry, Mapping):
                    continue
                self._reject_unplayable(entry)
                try:
                    track = self._track_from_metadata(entry, canonical, requester_id)
                except MusicError:
                    # An unavailable playlist entry cannot be downloaded later;
                    # report it as a malformed playlist instead of guessing a URL.
                    continue
                tracks.append(track)
                self._remember_metadata(track.id, entry, False)
            if not tracks:
                raise MusicError("這個播放清單沒有可播放的歌曲。")
            return tracks

        target = single_video_url(canonical)
        if target is None:
            raise MusicError("這個網址只包含播放清單，請確認是否要加入整個播放清單。")
        args = self._yt_base_args()
        args.extend(["--dump-single-json", "--skip-download", "--no-playlist", target])
        metadata = await self._run_metadata(args)
        self._reject_unplayable(metadata)
        track = self._track_from_metadata(metadata, target, requester_id)
        self._remember_metadata(track.id, metadata, True)
        return [track]

    async def _full_metadata_for(self, track: Track) -> dict:
        known = self._known_metadata.get(track.id)
        if known and known[1]:
            return known[0]
        target = single_video_url(track.url)
        if target is None:
            raise MusicError("歌曲網址不是單一 YouTube 影片。")
        args = self._yt_base_args()
        args.extend(["--dump-single-json", "--skip-download", "--no-playlist", target])
        metadata = await self._run_metadata(args)
        self._remember_metadata(track.id, metadata, True)
        return metadata

    def _validate_full_track(self, track: Track, metadata: Mapping[str, object]) -> Track:
        self._reject_unplayable(metadata)
        duration = self._duration(metadata.get("duration"))
        if duration is None:
            raise MusicError("無法確認歌曲長度，已略過這首歌曲。")
        refreshed = self._track_from_metadata(metadata, track.url, track.requester_id)
        if refreshed.id != track.id:
            raise MusicError("YouTube 回傳的影片 ID 與點歌網址不一致。")
        return refreshed

    def _evict_for_capacity_locked(self, required_bytes: int = 0) -> None:
        usage = self._directory_usage()
        if usage + required_bytes <= self._max_cache_bytes:
            return
        if self.config.auto_cleanup:
            candidates: list[tuple[float, Path, str]] = []
            for path, track_id, partial in self._iter_owned_files() or ():
                if track_id in self._inflight_ids or partial:
                    continue
                entry = self._entries.get(track_id)
                if entry and entry.references:
                    continue
                try:
                    stamp = entry.last_access if entry else path.stat().st_mtime
                except OSError:
                    stamp = 0
                candidates.append((stamp, path, track_id))
            candidates.sort(key=lambda item: item[0])
            for _, path, track_id in candidates:
                if usage + required_bytes <= self._max_cache_bytes:
                    break
                removed = self._remove_path(path)
                if removed:
                    usage -= removed
                    entry = self._entries.get(track_id)
                    if entry and entry.path == path:
                        self._entries.pop(track_id, None)
        if usage + required_bytes > self._max_cache_bytes:
            raise MusicError("音樂快取空間不足，請先清理快取。")

    async def _run_download(self, args: list[str], track_id: str) -> None:
        try:
            process = await self._spawn(args)
        except FileNotFoundError as exc:
            raise MusicError("找不到 Python 或 yt-dlp，請先安裝 yt-dlp。") from exc
        communication = asyncio.create_task(process.communicate())
        deadline = time.monotonic() + self.config.download_timeout_seconds
        try:
            while not communication.done():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    await self._terminate_process(process, communication)
                    self._remove_download_artifacts(track_id)
                    raise MusicError("歌曲下載逾時，請稍後再試。")
                done, _ = await asyncio.wait(
                    {communication}, timeout=min(remaining, 0.25),
                )
                if not done:
                    if self._track_usage(track_id) > self._max_file_bytes:
                        await self._terminate_process(process, communication)
                        self._remove_download_artifacts(track_id)
                        raise MusicError(
                            f"音檔大小超過限制（最多 {self.config.max_file_mb} MB）。",
                        )
                    if self._directory_usage() > self._max_cache_bytes:
                        await self._terminate_process(process, communication)
                        self._remove_download_artifacts(track_id)
                        raise MusicError("音樂快取空間不足，已取消下載。")
            output, error = await communication
        except asyncio.CancelledError:
            await self._terminate_process(process, communication)
            self._remove_download_artifacts(track_id)
            raise
        if process.returncode:
            self._remove_download_artifacts(track_id)
            detail = self._redact_error(error)
            suffix = f": {detail}" if detail else "。"
            raise MusicError(f"歌曲下載失敗{suffix}")
        if self._directory_usage() > self._max_cache_bytes:
            self._remove_download_artifacts(track_id)
            raise MusicError("音樂快取空間不足，已取消下載。")

    async def acquire(self, track: Track) -> Path:
        self._ensure_open()
        if not isinstance(track, Track):
            raise MusicError("歌曲資料格式不正確。")
        track_id = self._safe_track_id(track.id)
        canonical = single_video_url(track.url)
        if canonical is None:
            raise MusicError("歌曲網址不是單一 YouTube 影片。")
        if track.duration is not None:
            duration = self._duration(track.duration)
            if duration is None:
                raise MusicError("歌曲長度資料不正確。")
            if duration > self.config.max_duration_seconds:
                raise MusicError(
                    f"歌曲長度超過限制（最多 {self.config.max_duration_seconds} 秒）。",
                )

        async with self._download_lock:
            self._ensure_open()
            async with self._state_lock:
                self._inflight_ids.add(track_id)
            try:
                metadata = await self._full_metadata_for(track)
                verified = self._validate_full_track(track, metadata)
                if verified.id != track_id:
                    raise MusicError("歌曲 ID 與網址不一致。")

                async with self._state_lock:
                    cached = self._find_cached_file(track_id)
                    if cached is not None:
                        try:
                            size = cached.stat().st_size
                        except OSError:
                            size = 0
                        if 0 < size <= self._max_file_bytes:
                            entry = self._entries.get(track_id)
                            if entry is None or entry.path != cached:
                                entry = _CacheEntry(verified, cached, size=size)
                                self._entries[track_id] = entry
                            entry.track = verified
                            entry.references += 1
                            entry.last_access = time.time()
                            self._touch_path(cached)
                            return cached
                        self._remove_path(cached)

                    # Reserve one complete file slot while yt-dlp is running.
                    # This accounts for partial/inflight bytes even when the
                    # child writes its final file in one operation.  The
                    # monitor below still enforces the actual per-file limit.
                    self._evict_for_capacity_locked(required_bytes=self._max_file_bytes)
                output_template = str(self.cache_dir / f"{track_id}.%(ext)s")
                args = self._yt_base_args()
                args.extend([
                    "--no-playlist",
                    "--format",
                    "bestaudio[acodec=opus]/bestaudio/best",
                    "--output",
                    output_template,
                    "--max-filesize",
                    f"{self.config.max_file_mb}M",
                    "--no-mtime",
                    canonical,
                ])
                await self._run_download(args, track_id)
                path = self._find_cached_file(track_id)
                if path is None:
                    self._remove_download_artifacts(track_id)
                    raise MusicError("yt-dlp 沒有產生可播放的音檔。")
                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                if size <= 0:
                    self._remove_download_artifacts(track_id)
                    raise MusicError("下載的音檔是空的。")
                if size > self._max_file_bytes:
                    self._remove_download_artifacts(track_id)
                    raise MusicError(
                        f"音檔大小超過限制（最多 {self.config.max_file_mb} MB）。",
                    )
                if self._directory_usage() > self._max_cache_bytes:
                    async with self._state_lock:
                        try:
                            # The downloaded file is still marked inflight, so
                            # this can evict only older unpinned files.
                            self._evict_for_capacity_locked()
                        except MusicError:
                            self._remove_download_artifacts(track_id)
                            raise
                    if self._directory_usage() > self._max_cache_bytes:
                        self._remove_download_artifacts(track_id)
                        raise MusicError("音樂快取空間不足，已取消下載。")
                self._remove_download_artifacts(track_id, keep=path)
                async with self._state_lock:
                    entry = _CacheEntry(verified, path, references=1, size=size)
                    self._entries[track_id] = entry
                return path
            finally:
                async with self._state_lock:
                    self._inflight_ids.discard(track_id)

    async def release(self, track: Track) -> None:
        self._ensure_open()
        track_id = self._safe_track_id(track.id if isinstance(track, Track) else None)
        async with self._state_lock:
            entry = self._entries.get(track_id)
            if entry is None or entry.references <= 0:
                raise MusicError("歌曲快取引用未取得或已釋放。")
            entry.references -= 1
            entry.last_access = time.time()
            self._touch_path(entry.path)

    async def cleanup(self, *, force: bool = False) -> dict[str, int]:
        self._ensure_open()
        async with self._state_lock:
            removed_files = 0
            freed_bytes = 0
            now = time.time()
            ttl_seconds = float(self.config.cache_ttl_hours) * 3600
            candidates: list[tuple[float, Path, str, bool]] = []
            for path, track_id, partial in list(self._iter_owned_files() or ()):
                if track_id in self._inflight_ids:
                    continue
                entry = self._entries.get(track_id)
                if entry and entry.references:
                    continue
                try:
                    stamp = entry.last_access if entry else path.stat().st_mtime
                except OSError:
                    stamp = now
                expired = partial or ttl_seconds == 0 or (now - stamp >= ttl_seconds)
                if force or expired:
                    candidates.append((stamp, path, track_id, partial))
            if force:
                # Manual force cleanup means all unpinned recognized files;
                # sorting keeps the result deterministic for callers/tests.
                candidates.sort(key=lambda item: item[1].name)
            for _, path, track_id, _ in candidates:
                removed = self._remove_path(path)
                if removed:
                    removed_files += 1
                    freed_bytes += removed
                entry = self._entries.get(track_id)
                if entry and entry.path == path:
                    self._entries.pop(track_id, None)
            return {"removed_files": removed_files, "freed_bytes": freed_bytes}

    async def stats(self) -> dict[str, int]:
        self._ensure_open()
        async with self._state_lock:
            total = 0
            files = 0
            for path, _, _ in self._iter_owned_files() or ():
                try:
                    total += path.stat().st_size
                    files += 1
                except OSError:
                    pass
            pinned = sum(1 for entry in self._entries.values() if entry.references > 0)
            return {"bytes": total, "files": files, "pinned_files": pinned}

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
