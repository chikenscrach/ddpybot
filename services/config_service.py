"""Validated, revision-aware edits to the persisted bot configuration."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import MISSING, fields
from pathlib import Path
from typing import Any

from services.music_cache import MusicConfig, MusicError


class ConfigServiceError(ValueError):
    """A safe-to-display settings error raised by the dashboard config API."""

    status = 400


class ConfigRevisionConflict(ConfigServiceError):
    """The settings file changed since the dashboard last read it."""

    status = 409


class ConfigStorageError(ConfigServiceError):
    """The settings file could not be read or atomically replaced."""

    status = 500


TOP_LEVEL_KEYS = frozenset({
    "DAILY_CHANNEL_ID",
    "moderator_ids",
    "AI_PROVIDER",
    "OPENROUTER_MODEL",
    "GROQ_MODEL",
    "MUSIC",
})
MUSIC_KEYS = frozenset(field.name for field in fields(MusicConfig))
_REVISION_RE = re.compile(r"^[0-9a-f]{64}$")
_MODEL_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,200}$")
_MAX_DISCORD_ID = 2**64 - 1


def _music_defaults() -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    for field in fields(MusicConfig):
        if field.default is not MISSING:
            defaults[field.name] = field.default
        elif field.default_factory is not MISSING:
            defaults[field.name] = field.default_factory()
    # Keep this setting portable and consistent with setting.json.example.
    defaults["cache_dir"] = "data/music"
    return defaults


DEFAULT_VALUES: dict[str, Any] = {
    "DAILY_CHANNEL_ID": None,
    "moderator_ids": [],
    "AI_PROVIDER": "openrouter",
    "OPENROUTER_MODEL": "openrouter/free",
    "GROQ_MODEL": "moonshotai/kimi-k2-instruct-0905",
    "MUSIC": _music_defaults(),
}


class ConfigService:
    """Read safe dashboard settings and atomically save changes for next restart."""

    def __init__(self, path: str | Path, settings: Mapping[str, Any], root: str | Path):
        self.path = Path(path)
        self.root = Path(root)
        self._active_settings = copy.deepcopy(dict(settings))
        self._lock = asyncio.Lock()

    def snapshot(self) -> dict[str, Any]:
        document, raw = self._read_document()
        revision = hashlib.sha256(raw).hexdigest()
        saved_values = _public_values(document, self.root, allow_legacy_id_types=True)
        active_values = _public_values(self._active_settings, self.root, allow_legacy_id_types=True)
        return {
            "values": copy.deepcopy(saved_values),
            "saved_values": copy.deepcopy(saved_values),
            "active_values": active_values,
            "pending_restart": _changed_fields(active_values, saved_values),
            "revision": revision,
        }

    async def save(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        async with self._lock:
            return await asyncio.to_thread(self._save_sync, payload)

    def _read_document(self) -> tuple[dict[str, Any], bytes]:
        try:
            raw = self.path.read_bytes()
        except OSError as exc:
            raise ConfigStorageError("無法讀取設定檔，請確認路徑與檔案權限。") from exc
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ConfigStorageError("設定檔不是有效的 UTF-8 JSON。") from None
        if not isinstance(document, dict):
            raise ConfigStorageError("設定檔最上層必須是 JSON 物件。")
        return document, raw

    def _save_sync(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ConfigServiceError("請提供設定物件。")
        if set(payload) != {"values", "revision"}:
            raise ConfigServiceError("設定請求只能包含 values 與 revision。")
        revision = payload.get("revision")
        if not isinstance(revision, str) or not _REVISION_RE.fullmatch(revision):
            raise ConfigServiceError("設定 revision 格式無效，請重新載入設定。")

        document, raw = self._read_document()
        current_revision = hashlib.sha256(raw).hexdigest()
        if not hmac_compare_digest(revision, current_revision):
            raise ConfigRevisionConflict("設定檔已被其他操作更新，請重新載入後再儲存。")

        submitted = payload.get("values")
        if not isinstance(submitted, Mapping):
            raise ConfigServiceError("values 必須是設定物件。")
        unknown_top = set(submitted) - TOP_LEVEL_KEYS
        if unknown_top:
            raise ConfigServiceError(f"不支援的設定欄位：{', '.join(sorted(unknown_top))}")

        candidate = _public_values(document, self.root, allow_legacy_id_types=True)
        candidate = _merge_submitted(candidate, submitted)
        normalized = _public_values(candidate, self.root, allow_legacy_id_types=False)
        _validate_settings(normalized, self.root)

        updated = copy.deepcopy(document)
        for key in TOP_LEVEL_KEYS - {"MUSIC", "DAILY_CHANNEL_ID", "moderator_ids"}:
            if key in submitted:
                updated[key] = normalized[key]
        if "DAILY_CHANNEL_ID" in submitted:
            value = normalized["DAILY_CHANNEL_ID"]
            updated["DAILY_CHANNEL_ID"] = int(value) if value is not None else None
        if "moderator_ids" in submitted:
            updated["moderator_ids"] = [int(value) for value in normalized["moderator_ids"]]
        if "MUSIC" in submitted:
            raw_music = updated.get("MUSIC")
            music_document = copy.deepcopy(raw_music) if isinstance(raw_music, dict) else {}
            # Include every supported field, while retaining unknown legacy data
            # already present in the file. Unknown submitted fields were rejected.
            music_document.update(normalized["MUSIC"])
            updated["MUSIC"] = music_document

        try:
            new_raw = (json.dumps(updated, ensure_ascii=False, indent=4, allow_nan=False) + "\n").encode("utf-8")
        except (TypeError, ValueError):
            raise ConfigServiceError("設定值無法轉成 JSON。") from None

        self._atomic_replace(new_raw, current_revision)
        new_revision = hashlib.sha256(new_raw).hexdigest()
        saved_values = _public_values(updated, self.root, allow_legacy_id_types=True)
        active_values = _public_values(self._active_settings, self.root, allow_legacy_id_types=True)
        return {
            "values": copy.deepcopy(saved_values),
            "saved_values": copy.deepcopy(saved_values),
            "active_values": active_values,
            "pending_restart": _changed_fields(active_values, saved_values),
            "revision": new_revision,
        }

    def _atomic_replace(self, contents: bytes, expected_revision: str) -> None:
        parent = self.path.parent
        temporary_path: str | None = None
        try:
            fd, temporary_path = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=parent
            )
            try:
                try:
                    mode = stat.S_IMODE(self.path.stat().st_mode)
                    os.fchmod(fd, mode)
                except OSError:
                    # New files retain mkstemp's restrictive 0600 permissions.
                    pass
                with os.fdopen(fd, "wb") as stream:
                    stream.write(contents)
                    stream.flush()
                    os.fsync(stream.fileno())

                # Recheck immediately before replacement so an external edit
                # during validation is not silently overwritten.
                try:
                    current = self.path.read_bytes()
                except OSError as exc:
                    raise ConfigStorageError("無法在儲存前重新讀取設定檔。") from exc
                if hashlib.sha256(current).hexdigest() != expected_revision:
                    raise ConfigRevisionConflict("設定檔已被其他操作更新，請重新載入後再儲存。")
                os.replace(temporary_path, self.path)
                temporary_path = None
                try:
                    directory_fd = os.open(parent, os.O_RDONLY)
                except OSError:
                    directory_fd = None
                if directory_fd is not None:
                    try:
                        os.fsync(directory_fd)
                    except OSError:
                        pass
                    finally:
                        os.close(directory_fd)
            except ConfigServiceError:
                raise
            except OSError as exc:
                raise ConfigStorageError(
                    "無法以原子方式更新設定檔；請確認目錄權限，且設定檔可由同目錄暫存檔取代。"
                ) from exc
        except ConfigServiceError:
            raise
        except OSError as exc:
            raise ConfigStorageError("無法建立設定檔暫存檔，請確認目錄與檔案權限。") from exc
        finally:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass


def _merge_submitted(current: dict[str, Any], submitted: Mapping[str, Any]) -> dict[str, Any]:
    candidate = copy.deepcopy(current)
    for key, value in submitted.items():
        if key == "MUSIC":
            if not isinstance(value, Mapping):
                raise ConfigServiceError("MUSIC 必須是設定物件。")
            unknown_music = set(value) - MUSIC_KEYS
            if unknown_music:
                raise ConfigServiceError(f"不支援的 MUSIC 欄位：{', '.join(sorted(unknown_music))}")
            candidate["MUSIC"].update(copy.deepcopy(dict(value)))
        else:
            candidate[key] = copy.deepcopy(value)
    return candidate


def _public_values(
    source: Mapping[str, Any], root: Path, *, allow_legacy_id_types: bool
) -> dict[str, Any]:
    values = copy.deepcopy(DEFAULT_VALUES)
    for key in TOP_LEVEL_KEYS - {"MUSIC"}:
        if key in source:
            values[key] = copy.deepcopy(source[key])
    raw_music = source.get("MUSIC", {})
    if raw_music is None:
        raw_music = {}
    if not isinstance(raw_music, Mapping):
        raise ConfigServiceError("MUSIC 設定必須是物件。")
    values["MUSIC"].update({key: copy.deepcopy(value) for key, value in raw_music.items()
                            if key in MUSIC_KEYS})

    daily_id = values["DAILY_CHANNEL_ID"]
    if daily_id is not None:
        values["DAILY_CHANNEL_ID"] = _discord_id(daily_id, "DAILY_CHANNEL_ID",
                                                  allow_int=allow_legacy_id_types)
    moderators = values["moderator_ids"]
    if not isinstance(moderators, list):
        raise ConfigServiceError("moderator_ids 必須是 Discord ID 陣列。")
    values["moderator_ids"] = [
        _discord_id(value, "moderator_ids", allow_int=allow_legacy_id_types)
        for value in moderators
    ]
    if len(set(values["moderator_ids"])) != len(values["moderator_ids"]):
        raise ConfigServiceError("moderator_ids 不可包含重複 ID。")

    provider = values["AI_PROVIDER"]
    if not isinstance(provider, str):
        raise ConfigServiceError("AI_PROVIDER 必須是 openrouter 或 groq。")
    provider = provider.strip().lower()
    if provider not in {"openrouter", "groq"}:
        raise ConfigServiceError("AI_PROVIDER 必須是 openrouter 或 groq。")
    values["AI_PROVIDER"] = provider
    for key in ("OPENROUTER_MODEL", "GROQ_MODEL"):
        model = values[key]
        if not isinstance(model, str) or not _MODEL_RE.fullmatch(model.strip()):
            raise ConfigServiceError(f"{key} 必須是 1 到 200 字元的模型名稱。")
        values[key] = model.strip()

    _validate_settings(values, root)
    return values


def _discord_id(value: Any, field: str, *, allow_int: bool) -> str:
    if isinstance(value, bool):
        raise ConfigServiceError(f"{field} 必須是十進位 Discord ID 字串。")
    if isinstance(value, int) and allow_int:
        value = str(value)
    if not isinstance(value, str) or not (value.isascii() and value.isdecimal()):
        raise ConfigServiceError(f"{field} 必須是十進位 Discord ID 字串。")
    number = int(value)
    if number <= 0 or number > _MAX_DISCORD_ID:
        raise ConfigServiceError(f"{field} 必須是有效的 Discord ID。")
    return str(number)


def _validate_settings(values: Mapping[str, Any], root: Path) -> None:
    try:
        MusicConfig.from_settings(dict(values), root)
    except (MusicError, TypeError, ValueError) as exc:
        message = str(exc)
        # Validation messages contain setting names and constraints, never values.
        raise ConfigServiceError(message or "MUSIC 設定無效。") from None


def _changed_fields(active: Mapping[str, Any], saved: Mapping[str, Any]) -> list[str]:
    pending = []
    for key in TOP_LEVEL_KEYS:
        if key == "MUSIC":
            for music_key in MUSIC_KEYS:
                if active["MUSIC"][music_key] != saved["MUSIC"][music_key]:
                    pending.append(f"MUSIC.{music_key}")
        elif active[key] != saved[key]:
            pending.append(key)
    return sorted(pending)


def hmac_compare_digest(left: str, right: str) -> bool:
    # Import locally to keep the public module surface small.
    import hmac

    return hmac.compare_digest(left, right)
