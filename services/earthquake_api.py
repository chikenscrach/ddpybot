# ──────────────────────────────────────────────
#  中央氣象署地震 API 封裝
#  （共用連線池 + 60 秒快取 + 兩個資料集並行抓取）
# ──────────────────────────────────────────────
import asyncio
import logging
import time

import aiohttp

from utils.constants import EARTHQUAKE_DATASETS, EARTHQUAKE_BASE_URL, INTENSITY_ORDER
from utils.time_helper import parse_cwa_time

log = logging.getLogger(__name__)


class EarthquakeAPI:
    """CWA 地震資料存取；整個 Cog 生命週期共用一個 ClientSession"""

    CACHE_TTL = 60  # 秒；地震報告更新頻率低，快取可省下重複的 API 請求

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session: aiohttp.ClientSession | None = None
        self._cache: list[dict] = []
        self._cache_time: float = 0.0

    async def start(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )

    async def close(self):
        if self.session:
            await self.session.close()

    async def _fetch_dataset(self, dataset_id: str, label: str) -> list[dict]:
        url = f"{EARTHQUAKE_BASE_URL}/{dataset_id}?Authorization={self.api_key}"
        try:
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    log.warning("CWA 資料集 %s 回應狀態碼 %d", dataset_id, resp.status)
                    return []
                data = await resp.json()
                if data.get("success") != "true":
                    log.warning("CWA 資料集 %s 回傳失敗: %s", dataset_id, data.get("message", data))
                    return []
                quakes = data.get("records", {}).get("Earthquake", [])
                for q in quakes:
                    q["_source"] = label
                return quakes
        except (aiohttp.ClientError, asyncio.TimeoutError):
            log.exception("取得 CWA 資料集 %s 失敗", dataset_id)
            return []

    async def get_all(self) -> list[dict]:
        """取得所有地震資料（顯著有感 + 小區域有感），依時間由新到舊排列"""
        # 快取尚未過期就直接回傳，避免每次指令都打兩次 API
        now = time.monotonic()
        if self._cache and now - self._cache_time < self.CACHE_TTL:
            return self._cache

        # 兩個資料集並行抓取，省下一半等待時間
        dataset_results = await asyncio.gather(
            *(self._fetch_dataset(did, label) for did, label in EARTHQUAKE_DATASETS.items())
        )
        results = [q for quakes in dataset_results for q in quakes]
        # 兩個資料集的時間格式可能不同，改以解析後的 datetime 排序才準確
        results.sort(
            key=lambda q: parse_cwa_time(q["EarthquakeInfo"]["OriginTime"]),
            reverse=True,
        )

        if results:
            self._cache = results
            self._cache_time = now
        return results


def get_max_intensity(quake: dict) -> str:
    """取得該筆地震的最大震度"""
    areas = quake.get("Intensity", {}).get("ShakingArea", [])
    if not areas:
        return "—"
    max_val = 0
    max_label = "—"
    for area in areas:
        raw = area.get("AreaIntensity", "")
        val = INTENSITY_ORDER.get(raw, 0)
        if val > max_val:
            max_val = val
            max_label = raw
    return max_label


def group_shaking_areas(quake: dict) -> list[tuple[str, list[str]]]:
    """將各地震度依等級分組，去重後由大到小排列"""
    areas = quake.get("Intensity", {}).get("ShakingArea", [])
    if not areas:
        return []

    groups: dict[str, set[str]] = {}
    for area in areas:
        intensity = area.get("AreaIntensity", "")
        county = area.get("CountyName", "")
        if not intensity or not county:
            continue
        if intensity not in groups:
            groups[intensity] = set()
        # 處理「、」或「,」分隔的多縣市
        for c in county.replace("、", ",").split(","):
            c = c.strip()
            if c:
                groups[intensity].add(c)

    sorted_groups = sorted(
        groups.items(),
        key=lambda x: INTENSITY_ORDER.get(x[0], 0),
        reverse=True,
    )
    return [(intensity, sorted(counties)) for intensity, counties in sorted_groups]
