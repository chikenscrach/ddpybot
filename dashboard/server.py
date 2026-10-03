from __future__ import annotations

import asyncio
import csv
import io
import logging
import math
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import psutil
from aiohttp import web

from core.config import PROJECT_ROOT, SETTING_PATH, settings
from dashboard.auth import OAuthManager
from services.config_service import ConfigService, ConfigServiceError
from services.music_cache import MusicError
from utils.time_helper import TIMEZONE

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / 'static'


class DashboardServer:
    def __init__(self, bot, config, *, auth=None, config_service=None):
        self.bot = bot
        self.config = config
        self.auth = auth or OAuthManager(bot, config)
        self.settings = config_service or ConfigService(SETTING_PATH, settings, PROJECT_ROOT)
        self.process = psutil.Process()
        self.process.cpu_percent()
        self.started = time.monotonic()
        self.runner = None
        self._cache_snapshot = None
        self._cache_time = 0
        self._control_lock = asyncio.Lock()
        self.app = web.Application(middlewares=[self.errors, self.authorize], client_max_size=64 * 1024)
        self.auth.register(self.app)
        self.app.add_routes([
            web.get('/', self.index),
            web.get('/assets/{name}', self.asset),
            web.get('/api/session', self.session),
            web.get('/api/overview', self.overview),
            web.get('/api/settings', self.get_settings),
            web.put('/api/settings', self.save_settings),
            web.get('/api/ping', self.ping),
            web.get('/api/ping/export', self.export_ping),
            web.get('/api/music/{guild_id}', self.music),
            web.post('/api/music/{guild_id}/control', self.control),
            web.post('/api/cache/clear', self.clear_cache),
        ])

    @web.middleware
    async def errors(self, request, handler):
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            if exc.status < 400:
                response = exc
            else:
                response = web.json_response({'error': exc.text or exc.reason}, status=exc.status)
        except ConfigServiceError as exc:
            response = web.json_response({'error': str(exc)}, status=exc.status)
        except (ValueError, MusicError) as exc:
            response = web.json_response({'error': str(exc)}, status=400)
        except Exception:
            log.exception('Dashboard request failed: %s %s', request.method, request.path)
            response = web.json_response({'error': '操作失敗，請查看 Bot 日誌。'}, status=500)
        response.headers.update({
            'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer',
            'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' https: data:; connect-src 'self'; base-uri 'none'; "
                "frame-ancestors 'none'; form-action 'self'",
        })
        return response

    @web.middleware
    async def authorize(self, request, handler):
        if request.path.startswith('/api/'):
            write = request.method not in ('GET', 'HEAD')
            session = self.auth.require_owner(request, write=write)
            await self.auth.verify_owner(session, refresh=write)
        return await handler(request)

    async def start(self):
        await self.auth.start()
        self.runner = web.AppRunner(self.app, access_log=None)
        try:
            await self.runner.setup()
            await web.TCPSite(self.runner, self.config.host, self.config.port).start()
        except BaseException:
            await self.close()
            raise
        log.info('Owner dashboard listening on %s:%s', self.config.host, self.config.port)

    async def close(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
        await self.auth.close()

    async def index(self, request):
        return web.FileResponse(STATIC_DIR / 'index.html')

    async def asset(self, request):
        name = request.match_info['name']
        if name not in ('app.js', 'style.css'):
            raise web.HTTPNotFound()
        return web.FileResponse(STATIC_DIR / name)

    async def session(self, request):
        return web.json_response(self.auth.require_owner(request))

    def _cog(self, name):
        cog = self.bot.get_cog(name)
        if cog is None:
            raise web.HTTPServiceUnavailable(reason=f'{name} 模組尚未載入。')
        return cog

    def _guild(self, raw):
        if not raw or not raw.isascii() or not raw.isdecimal() or len(raw) > 20:
            raise web.HTTPBadRequest(reason='無效的伺服器 ID。')
        guild = self.bot.get_guild(int(raw))
        if guild is None:
            raise web.HTTPNotFound(reason='Bot 不在這個伺服器。')
        return guild

    def _user(self, raw):
        user = self.bot.get_user(int(raw)) if raw else None
        return getattr(user, 'display_name', None) or f'使用者 {raw}'

    async def overview(self, request):
        latency = self.bot.latency
        music = self.bot.get_cog('Music')
        task = self.bot.get_cog('Task')
        if music and (time.monotonic() - self._cache_time > 15 or self._cache_snapshot is None):
            self._cache_snapshot = await music.service.cache.stats()
            self._cache_snapshot['max_bytes'] = music.service.config.max_cache_mb * 1024 * 1024
            self._cache_time = time.monotonic()
        guilds = [{
            'id': str(g.id), 'name': g.name,
            'icon': str(g.icon.url) if g.icon else None,
            'member_count': g.member_count or 0,
        } for g in self.bot.guilds]
        return web.json_response({
            'ready': self.bot.is_ready(), 'latency_ms': round(latency * 1000) if math.isfinite(latency) else None,
            'uptime_seconds': int(time.monotonic() - self.started),
            'cpu_percent': self.process.cpu_percent(), 'memory_bytes': self.process.memory_info().rss,
            'guilds': guilds, 'cogs': sorted(self.bot.cogs),
            'ping_total': task.db.get_total_count() if task else None,
            'cache': self._cache_snapshot if music else None,
            'bot': {'name': self.bot.user.display_name, 'id': str(self.bot.user.id)} if self.bot.user else None,
            'active_players': len(music.service.players) if music else 0,
        })

    async def get_settings(self, request):
        return web.json_response(await asyncio.to_thread(self.settings.snapshot))

    async def save_settings(self, request):
        return web.json_response(await self.settings.save(await self._body(request)))

    async def _body(self, request):
        if request.content_type != 'application/json':
            raise web.HTTPUnsupportedMediaType(reason='請使用 JSON 傳送設定或操作。')
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise web.HTTPBadRequest(reason='無效的 JSON。') from None
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(reason='資料必須是 JSON 物件。')
        return payload

    def _range(self, request):
        today = datetime.now(TIMEZONE).date()
        try:
            start = date.fromisoformat(request.query.get('start', str(today - timedelta(days=29))))
            end = date.fromisoformat(request.query.get('end', str(today)))
        except ValueError:
            raise web.HTTPBadRequest(reason='日期格式必須是 YYYY-MM-DD。') from None
        if start > end or (end - start).days >= 366:
            raise web.HTTPBadRequest(reason='日期區間必須介於 1 至 366 天。')
        source = request.query.get('source', 'all')
        if source not in ('all', 'scheduled', 'manual'):
            raise web.HTTPBadRequest(reason='無效的紀錄來源。')
        guild_id = request.query.get('guild_id')
        if guild_id:
            guild_id = self._guild(guild_id).id
        return start, end, {'guild_id': guild_id, 'source': source}

    async def ping(self, request):
        start, end, filters = self._range(request)
        data = self._cog('Task').db.query_dashboard(start, end, **filters)
        for key in ('leaders', 'lifetime_leaders', 'events'):
            for item in data[key]:
                item['name'] = self._user(item['user_id'])
        return web.json_response(data)

    async def export_ping(self, request):
        start, end, filters = self._range(request)
        data = self._cog('Task').db.export_events(start, end, **filters)
        if data['truncated']:
            raise web.HTTPBadRequest(reason='超過 10,000 筆，請縮小匯出日期區間。')
        output = io.StringIO()
        fields = ['user_id', 'guild_id', 'channel_id', 'message_id', 'event_at', 'source']
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(data['events'])
        return web.Response(
            text='\ufeff' + output.getvalue(), content_type='text/csv',
            headers={'Content-Disposition': f'attachment; filename="ping-{start}-{end}.csv"'},
        )

    async def music(self, request):
        guild = self._guild(request.match_info['guild_id'])
        data = self._cog('Music').service.snapshot(guild.id)
        for song in ([data['current']] if data['current'] else []) + data['queue']:
            song['requester_name'] = self._user(song['requester_id']) if song['requester_id'] else '未知'
        return web.json_response(data)

    async def control(self, request):
        guild = self._guild(request.match_info['guild_id'])
        data = await self._body(request)
        if set(data) - {'action', 'session_id', 'generation', 'mode'}:
            raise web.HTTPBadRequest(reason='不支援的操作欄位。')
        if type(data.get('session_id')) is not int or not isinstance(data.get('generation'), str):
            raise web.HTTPBadRequest(reason='請先重新取得播放狀態。')
        if data.get('action') not in ('pause', 'resume', 'skip', 'stop', 'leave', 'loop'):
            raise web.HTTPBadRequest(reason='不支援的音樂操作。')
        # Limit dashboard mutations without affecting Discord's existing controls.
        if self._control_lock.locked():
            raise web.HTTPConflict(reason='上一個操作仍在處理，請稍後再試。')
        async with self._control_lock:
            result = await self._cog('Music').service.dashboard_control(guild.id, **data)
        return web.json_response(result)

    async def clear_cache(self, request):
        data = await self._body(request)
        if data != {'confirm': True}:
            raise web.HTTPBadRequest(reason='請確認清理未使用的音樂快取。')
        result = await self._cog('Music').service.cache.cleanup(force=True)
        self._cache_snapshot = None
        return web.json_response(result)
