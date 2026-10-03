import asyncio
import json

import pytest

from services.config_service import (
    ConfigRevisionConflict,
    ConfigService,
    ConfigServiceError,
    ConfigStorageError,
)

BASE_SETTINGS = {
    "DAILY_CHANNEL_ID": 12345,
    "moderator_ids": [123456789012345678],
    "AI_PROVIDER": "openrouter",
    "OPENROUTER_MODEL": "openrouter/free",
    "GROQ_MODEL": "moonshotai/kimi-k2-instruct-0905",
    "MUSIC": {
        "max_queue_size": 80,
        "auto_cleanup": True,
        "allow_ytdlp_plugins": False,
    },
    "legacy_unknown": {"kept": True},
    "token": "dummy-legacy-secret",
    "openrouter_api_key": "dummy-legacy-api-key",
}


def write_settings(path, settings=None):
    path.write_text(json.dumps(settings or BASE_SETTINGS, ensure_ascii=False, indent=2), encoding="utf-8")


def make_service(tmp_path, settings=None):
    path = tmp_path / "setting.json"
    write_settings(path)
    return ConfigService(path, settings or BASE_SETTINGS, tmp_path), path


def test_snapshot_returns_string_ids_and_hides_legacy_and_unknown_fields(tmp_path):
    service, _ = make_service(tmp_path)

    snapshot = service.snapshot()

    assert snapshot["values"]["DAILY_CHANNEL_ID"] == "12345"
    assert snapshot["values"]["moderator_ids"] == ["123456789012345678"]
    assert snapshot["values"]["MUSIC"]["max_queue_size"] == 80
    assert snapshot["active_values"] == snapshot["saved_values"]
    assert snapshot["pending_restart"] == []
    assert len(snapshot["revision"]) == 64
    assert "legacy_unknown" not in snapshot["values"]
    assert "token" not in snapshot["values"]
    assert "openrouter_api_key" not in snapshot["values"]
    assert set(snapshot["values"]["MUSIC"]) == {
        "cache_dir", "max_cache_mb", "max_file_mb", "max_duration_seconds", "max_queue_size",
        "max_playlist_items", "empty_channel_grace_seconds", "auto_cleanup", "cache_ttl_hours",
        "cleanup_interval_seconds", "download_timeout_seconds", "ffmpeg_executable",
        "js_runtime", "cookies_file", "allow_ytdlp_plugins", "youtube_player_client",
        "pot_provider_url",
    }


def test_save_is_atomic_and_pending_until_restart(tmp_path):
    active = json.loads(json.dumps(BASE_SETTINGS))
    service, path = make_service(tmp_path, active)
    before = service.snapshot()
    submitted = {
        "DAILY_CHANNEL_ID": "123456789012345678",
        "moderator_ids": ["987654321098765432"],
        "AI_PROVIDER": "groq",
        "OPENROUTER_MODEL": "openrouter/free",
        "GROQ_MODEL": "moonshotai/kimi-k2-instruct-0905",
        "MUSIC": {
            **before["values"]["MUSIC"],
            "max_queue_size": 120,
        },
    }

    result = asyncio.run(service.save({"values": submitted, "revision": before["revision"]}))
    saved_document = json.loads(path.read_text(encoding="utf-8"))

    assert saved_document["DAILY_CHANNEL_ID"] == 123456789012345678
    assert saved_document["moderator_ids"] == [987654321098765432]
    assert saved_document["MUSIC"]["max_queue_size"] == 120
    assert saved_document["legacy_unknown"] == {"kept": True}
    assert saved_document["token"] == "dummy-legacy-secret"
    assert saved_document["openrouter_api_key"] == "dummy-legacy-api-key"
    assert result["values"]["DAILY_CHANNEL_ID"] == "123456789012345678"
    assert result["active_values"] == before["active_values"]
    assert "DAILY_CHANNEL_ID" in result["pending_restart"]
    assert "AI_PROVIDER" in result["pending_restart"]
    assert "MUSIC.max_queue_size" in result["pending_restart"]
    assert result["revision"] != before["revision"]
    assert service.snapshot()["active_values"] == before["active_values"]


def test_save_rejects_stale_revision_without_changing_file(tmp_path):
    service, path = make_service(tmp_path)
    first = service.snapshot()
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    before = path.read_bytes()

    with pytest.raises(ConfigRevisionConflict):
        asyncio.run(service.save({"values": first["values"], "revision": first["revision"]}))

    assert path.read_bytes() == before


@pytest.mark.parametrize("mutation", [
    lambda values: values.update(unknown_field="bad"),
    lambda values: values.update(DAILY_CHANNEL_ID=True),
    lambda values: values.update(moderator_ids=["123", "123"]),
    lambda values: values.update(AI_PROVIDER="unsupported"),
    lambda values: values["MUSIC"].update(auto_cleanup="true"),
    lambda values: values["MUSIC"].update(max_queue_size=True),
    lambda values: values["MUSIC"].update(unknown_field=1),
])
def test_invalid_payload_is_rejected_without_writing(tmp_path, mutation):
    service, path = make_service(tmp_path)
    before = service.snapshot()
    submitted = json.loads(json.dumps(before["values"]))
    mutation(submitted)
    original = path.read_bytes()

    with pytest.raises(ConfigServiceError):
        asyncio.run(service.save({"values": submitted, "revision": before["revision"]}))

    assert path.read_bytes() == original


def test_save_requires_web_ids_to_be_decimal_strings(tmp_path):
    service, path = make_service(tmp_path)
    before = service.snapshot()
    submitted = json.loads(json.dumps(before["values"]))
    submitted["moderator_ids"] = [123456789012345678]
    original = path.read_bytes()

    with pytest.raises(ConfigServiceError, match="十進位 Discord ID 字串"):
        asyncio.run(service.save({"values": submitted, "revision": before["revision"]}))

    assert path.read_bytes() == original


def test_replace_failure_preserves_original_and_does_not_fallback(tmp_path, monkeypatch):
    service, path = make_service(tmp_path)
    before = service.snapshot()
    original = path.read_bytes()
    submitted = json.loads(json.dumps(before["values"]))
    submitted["DAILY_CHANNEL_ID"] = "456"

    def fail_replace(*args):
        raise OSError("device busy")

    monkeypatch.setattr("services.config_service.os.replace", fail_replace)

    with pytest.raises(ConfigStorageError, match="原子方式"):
        asyncio.run(service.save({"values": submitted, "revision": before["revision"]}))

    assert path.read_bytes() == original
    assert list(tmp_path.glob(".setting.json.*.tmp")) == []
