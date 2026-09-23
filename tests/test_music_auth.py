import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from services.music_cache import MusicCache, MusicConfig, MusicError

COOKIE_TEXT = '# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tfake-test-cookie\n'


def make_cache(tmp_path, **settings):
    config = MusicConfig.from_settings({'MUSIC': settings}, tmp_path)
    return MusicCache(config)


def test_cookie_config_is_optional_and_relative_to_project(tmp_path):
    assert MusicConfig.from_settings({}, tmp_path).cookies_file is None
    assert MusicConfig.from_settings({'MUSIC': {'cookies_file': ''}}, tmp_path).cookies_file is None
    config = MusicConfig.from_settings({'MUSIC': {'cookies_file': 'secrets/youtube.cookies.txt'}}, tmp_path)
    assert config.cookies_file == tmp_path / 'secrets' / 'youtube.cookies.txt'
    with pytest.raises(MusicError, match='cookies_file'):
        MusicConfig.from_settings({'MUSIC': {'cookies_file': True}}, tmp_path)


def test_provider_is_opt_in_and_client_args_are_passed(tmp_path):
    default = make_cache(tmp_path)
    assert '--no-plugin-dirs' in default._yt_base_args()
    enabled = make_cache(tmp_path, allow_ytdlp_plugins=True, youtube_player_client='mweb',
                         pot_provider_url='http://bgutil-provider:4416')
    args = enabled._yt_base_args()
    assert '--no-plugin-dirs' not in args
    assert 'youtube:player_client=mweb' in args
    assert 'youtubepot-bgutilhttp:base_url=http://bgutil-provider:4416' in args


@pytest.mark.parametrize('settings', [
    {'allow_ytdlp_plugins': 'true'},
    {'youtube_player_client': 0},
    {'youtube_player_client': 'mweb;po_token=secret'},
    {'allow_ytdlp_plugins': True, 'pot_provider_url': 'https://user:password@server'},
    {'allow_ytdlp_plugins': True, 'pot_provider_url': 'http://server:bad'},
    {'allow_ytdlp_plugins': True, 'pot_provider_url': 'file:///secret'},
    {'allow_ytdlp_plugins': True, 'pot_provider_url': 'http://server;bad'},
    {'pot_provider_url': 'http://server:4416'},
])
def test_invalid_provider_config_is_rejected(tmp_path, settings):
    with pytest.raises(MusicError):
        make_cache(tmp_path, **settings)


def test_metadata_and_download_use_separate_writable_copies(tmp_path):
    async def scenario():
        original = tmp_path / 'youtube.cookies.txt'
        original.write_text(COOKIE_TEXT, encoding='utf-8')
        original.chmod(0o400)
        cache = make_cache(tmp_path, cookies_file=str(original))
        copied = []
        both_started = asyncio.Event()

        async def consume(args, *extra):
            copied_path = Path(args[args.index('--cookies') + 1])
            assert copied_path != original
            assert await asyncio.to_thread(copied_path.read_text, encoding='utf-8') == COOKIE_TEXT
            assert 'fake-test-cookie' not in ' '.join(args)
            copied.append(copied_path)
            await asyncio.to_thread(copied_path.write_text, 'yt-dlp writes refreshed cookies', encoding='utf-8')
            if len(copied) == 2:
                both_started.set()
            await both_started.wait()
            return {'id': 'test'}

        cache._run_metadata_process = consume
        cache._run_download_process = consume
        try:
            await asyncio.gather(cache._run_metadata(cache._yt_base_args()),
                                 cache._run_download(cache._yt_base_args(), 'test'))
            assert copied[0] != copied[1]
            assert all(not path.exists() for path in copied)
            assert original.read_text(encoding='utf-8') == COOKIE_TEXT
        finally:
            original.chmod(0o600)
            await cache.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('contents', [None, '', '# Netscape HTTP Cookie File\n',
                                    'sensitive-cookie-invalid-format',
                                    '# Netscape HTTP Cookie File\nsecret\tmalformed-cookie\n'])
def test_bad_cookie_file_fails_before_spawn_without_secret_output(tmp_path, contents, caplog, capsys):
    async def scenario():
        original = tmp_path / 'cookies.txt'
        if contents is not None:
            original.write_text(contents, encoding='utf-8')
        cache = make_cache(tmp_path, cookies_file=str(original))
        cache._spawn = AsyncMock()
        with pytest.raises(MusicError) as caught:
            await cache._run_metadata(cache._yt_base_args())
        assert 'sensitive-cookie' not in str(caught.value)
        assert 'malformed-cookie' not in str(caught.value)
        cache._spawn.assert_not_awaited()
        await cache.close()
    asyncio.run(scenario())
    captured = capsys.readouterr()
    assert 'malformed-cookie' not in caplog.text + captured.err + captured.out


@pytest.mark.parametrize('cancel', [False, True])
def test_cookie_copies_removed_after_errors_and_cancellation(tmp_path, cancel):
    async def scenario():
        original = tmp_path / 'cookies.txt'
        original.write_text(COOKIE_TEXT, encoding='utf-8')
        cache = make_cache(tmp_path, cookies_file=str(original))
        started = asyncio.Event()
        copied = []

        async def consume(args):
            copied.append(Path(args[args.index('--cookies') + 1]))
            started.set()
            if cancel:
                await asyncio.Event().wait()
            raise MusicError('HTTP Error 403: Forbidden')

        cache._run_metadata_process = consume
        task = asyncio.create_task(cache._run_metadata(cache._yt_base_args()))
        await started.wait()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else MusicError):
            await task
        assert not copied[0].exists()
        assert original.read_text(encoding='utf-8') == COOKIE_TEXT
        await cache.close()
    asyncio.run(scenario())
