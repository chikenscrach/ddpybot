# ──────────────────────────────────────────────
#  AI 供應商封裝（OpenRouter / Groq 二選一）
#  由 setting.json 的 "AI_PROVIDER" 決定使用哪一家
# ──────────────────────────────────────────────
import asyncio
import json
import logging

import aiohttp

from core.config import settings, OPENROUTER_API_KEY, GROQ_API_KEY
from utils.constants import OPENROUTER_URL

log = logging.getLogger(__name__)

API_TIMEOUT = aiohttp.ClientTimeout(total=60)  # 避免 API 卡住時指令永遠等待
DEFAULT_GROQ_MODEL = 'moonshotai/kimi-k2-instruct-0905'


class AIError(Exception):
    """統一的 AI API 錯誤，status 對應 HTTP 狀態碼（0 = 連線層錯誤）"""

    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


class OpenRouterProvider:
    """OpenRouter：'openrouter/free' 自動路由到可用的免費模型"""

    name = 'OpenRouter'

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session: aiohttp.ClientSession | None = None

    # 整個 Cog 共用一個 ClientSession（重用連線池，比每次請求都新建快）
    async def start(self):
        self.session = aiohttp.ClientSession(timeout=API_TIMEOUT)

    async def close(self):
        if self.session:
            await self.session.close()

    async def call(self, messages: list) -> tuple[str, str]:
        """呼叫 API，回傳 (回覆內容, 實際使用的模型 ID)"""
        if not self.api_key:
            raise AIError(401, '未設定 OPENROUTER_API_KEY，請通知管理員檢查 .env')

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://discord.com',
            'X-Title': 'Discord Bot',
        }
        payload = {
            'model': 'openrouter/free',
            'messages': messages,
        }

        try:
            async with self.session.post(OPENROUTER_URL, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise AIError(resp.status, error_text)

                data = await resp.json()

                if 'error' in data:
                    raise AIError(resp.status, json.dumps(data['error']))

                if 'choices' not in data or not data['choices']:
                    raise AIError(resp.status, 'API 回傳格式異常 (無 choices)')

                content = data['choices'][0]['message']['content']
                # OpenRouter 會在回應中告訴你實際用了哪個模型
                actual_model = data.get('model', 'unknown')
                return content, actual_model

        except asyncio.TimeoutError:
            raise AIError(0, 'API 回應逾時，請稍後再試')
        except aiohttp.ClientError as e:
            raise AIError(0, f'網路連線錯誤: {e}')


class GroqProvider:
    """Groq：使用 setting.json 的 GROQ_MODEL 指定模型"""

    name = 'Groq'

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self._client = None

    async def start(self):
        if not self.api_key:
            log.warning('未設定 GROQ_API_KEY，/ai 指令將無法使用')
            return
        from groq import AsyncGroq
        self._client = AsyncGroq(api_key=self.api_key)

    async def close(self):
        if self._client:
            await self._client.close()

    async def call(self, messages: list) -> tuple[str, str]:
        """呼叫 API，回傳 (回覆內容, 實際使用的模型名稱)"""
        if self._client is None:
            raise AIError(401, '未設定 GROQ_API_KEY，請通知管理員檢查 .env')

        from groq import APIStatusError, APIConnectionError
        try:
            completion = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.6,
                max_tokens=4095,
                top_p=1,
                stream=False,  # Discord 不需要串流，一次收完再送出
            )
            reply = completion.choices[0].message.content or ''
            actual_model = completion.model or self.model
            return reply, actual_model

        except APIStatusError as e:
            log.error('Groq API status error %s: %s', e.status_code, e.message)
            raise AIError(e.status_code, str(e.message))
        except APIConnectionError as e:
            log.error('Groq connection error: %s', e)
            raise AIError(0, '無法連接到 Groq API')


def create_provider():
    """依 setting.json 的 AI_PROVIDER 建立對應的供應商（預設 openrouter）"""
    provider = str(settings.get('AI_PROVIDER', 'openrouter')).lower()
    if provider == 'groq':
        return GroqProvider(GROQ_API_KEY, settings.get('GROQ_MODEL', DEFAULT_GROQ_MODEL))
    if provider != 'openrouter':
        log.warning("未知的 AI_PROVIDER '%s'，改用 openrouter", provider)
    return OpenRouterProvider(OPENROUTER_API_KEY)


def build_user_message(text: str, image_urls: list[str] | None = None) -> dict:
    """組裝使用者訊息；有圖片時使用 multimodal content 格式（需模型支援 vision）"""
    if image_urls:
        content: list[dict] = [{'type': 'text', 'text': text}]
        for url in image_urls:
            content.append({'type': 'image_url', 'image_url': {'url': url}})
        return {'role': 'user', 'content': content}
    return {'role': 'user', 'content': text}


def format_model_name(model_id: str) -> str:
    """把 'google/gemma-3-27b-it:free' 變成 'gemma-3-27b-it'"""
    name = model_id.split('/')[-1] if '/' in model_id else model_id
    return name.split(':')[0]  # 去掉 :free 後綴
