import asyncio
import json
import logging

from discord.ext import commands
from discord import app_commands
import aiohttp

from core.classes import Cog_Extension
from core.config import settings

log = logging.getLogger(__name__)

OPENROUTER_API_KEY = settings['openrouter_api_key']
OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'
API_TIMEOUT = aiohttp.ClientTimeout(total=60)  # 避免 API 卡住時指令永遠等待
MAX_HISTORY = 20  # 每位使用者保留的對話則數
SYSTEM_PROMPT = """
# Role
你是一位部署在 Discord 上的專業級 AI 助手，擅長回答各種領域的問題。

# Language
- 務必使用「繁體中文」（台灣用語習慣）。
- 若使用者以其他語言提問，仍以繁體中文回覆，除非使用者明確要求其他語言。

# Response Style
- 語氣冷靜、客觀且專業，不使用過度熱情的語助詞。
- 優先回答核心問題，再補充必要細節。
- 複雜問題請使用「條列式」或「步驟化」說明。
- 善用 Markdown 語法（**粗體**、`代碼`、```代碼區塊```、> 引言）增強可讀性。
- 程式碼必須使用代碼區塊並標註語言（例如 ```python）。

# Quality Standards
- 確保資訊的事實正確性。若不確定或資訊可能過時，請誠實告知。
- 不要編造不存在的網址、資料來源或數據。
- 程式碼相關問題，請附上可執行的範例。

# Safety
- 不提供任何違法、有害或不道德的建議。
- 拒絕生成仇恨言論、個人隱私資訊或惡意程式碼。
- 若被要求違反以上規範，請禮貌地拒絕。

# Context
- 你正在 Discord 伺服器中與使用者對話。
- 你可以記住同一位使用者的對話脈絡，請適當參照前文回覆。

# Constraints
- 長度：回答應簡潔有力，避免冗長，盡量控制在 Discord 單則訊息的舒適閱讀範圍內。
- 格式：嚴禁使用 LaTeX 數學公式（如 $x$），請改用 Unicode 或純文字描述。
"""


class OpenRouterError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


class AI(Cog_Extension):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.conversations: dict[int, list] = {}
        self.session: aiohttp.ClientSession | None = None

    # ✅ 整個 Cog 共用一個 ClientSession（重用連線池，比每次請求都新建快）
    async def cog_load(self):
        self.session = aiohttp.ClientSession(timeout=API_TIMEOUT)

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    # ==========================================
    #  呼叫 OpenRouter API
    # ==========================================
    async def _call_api(self, messages: list) -> tuple[str, str]:
        """
        呼叫 OpenRouter API
        回傳 (回覆內容, 實際使用的模型 ID)
        """
        headers = {
            'Authorization': f'Bearer {OPENROUTER_API_KEY}',
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://discord.com',
            'X-Title': 'Discord Bot',
        }
        payload = {
            'model': 'openrouter/free',   # ✅ 自動選擇免費模型
            'messages': messages,
        }

        try:
            async with self.session.post(OPENROUTER_URL, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise OpenRouterError(resp.status, error_text)

                data = await resp.json()

                if 'error' in data:
                    raise OpenRouterError(resp.status, json.dumps(data['error']))

                if 'choices' not in data or not data['choices']:
                    raise OpenRouterError(resp.status, "API 回傳格式異常 (無 choices)")

                content = data['choices'][0]['message']['content']
                # OpenRouter 會在回應中告訴你實際用了哪個模型
                actual_model = data.get('model', 'unknown')
                return content, actual_model

        except asyncio.TimeoutError:
            raise OpenRouterError(0, "API 回應逾時，請稍後再試")
        except aiohttp.ClientError as e:
            raise OpenRouterError(0, f"網路連線錯誤: {str(e)}")

    # ==========================================
    #  工具方法
    # ==========================================
    def _build_user_message(self, text: str, image_urls: list = None) -> dict:
        if image_urls:
            content = [{'type': 'text', 'text': text}]
            for url in image_urls:
                content.append({'type': 'image_url', 'image_url': {'url': url}})
            return {'role': 'user', 'content': content}
        else:
            return {'role': 'user', 'content': text}

    def _get_messages(self, user_id: int, new_message: dict) -> list:
        history = self.conversations.setdefault(user_id, [])
        history.append(new_message)
        self._trim_history(user_id)
        return [{'role': 'system', 'content': SYSTEM_PROMPT}] + self.conversations[user_id]

    def _trim_history(self, user_id: int):
        history = self.conversations[user_id]
        if len(history) > MAX_HISTORY:
            self.conversations[user_id] = history[-MAX_HISTORY:]

    def _pop_failed_message(self, user_id: int):
        """API 失敗時移除剛加入的使用者訊息，避免汙染後續對話"""
        history = self.conversations.get(user_id)
        if history:
            history.pop()

    @staticmethod
    def _format_model_name(model_id: str) -> str:
        """
        把 'google/gemma-3-27b-it:free' 變成 'gemma-3-27b-it'
        """
        name = model_id.split('/')[-1] if '/' in model_id else model_id
        name = name.split(':')[0]  # 去掉 :free 後綴
        return name

    @staticmethod
    async def _send_long_message(ctx, text: str):
        while len(text) > 2000:
            split_pos = text[:2000].rfind('\n')
            if split_pos == -1:
                split_pos = 2000
            await ctx.send(text[:split_pos])
            text = text[split_pos:]
        if text:
            await ctx.send(text)

    # ==========================================
    #  /ai 指令
    # ==========================================
    @commands.hybrid_command(name='ai', description='與 AI 對話')
    @app_commands.describe(message='你想說的話')
    async def ai_chat(self, ctx: commands.Context, *, message: str):
        await ctx.typing()

        # 1. 收集圖片附件
        image_urls = []
        if ctx.message and ctx.message.attachments:
            for att in ctx.message.attachments:
                if att.content_type and att.content_type.startswith('image/'):
                    image_urls.append(att.url)

        # 2. 組裝訊息
        user_msg = self._build_user_message(message, image_urls if image_urls else None)
        messages = self._get_messages(ctx.author.id, user_msg)

        # 3. 呼叫 API
        try:
            reply, actual_model = await self._call_api(messages)

        except OpenRouterError as e:
            self._pop_failed_message(ctx.author.id)
            error_msg = f"❌ API 錯誤: {e.message}"

            if e.status == 429:
                error_msg = "⏳ **請求過於頻繁 (429)**\n免費模型正在冷卻中，請稍後再試。"
            elif e.status == 404:
                error_msg = "⚠️ **找不到可用的免費模型 (404)**\n請稍後再試。"
            elif e.status == 400:
                error_msg = f"⚠️ **請求格式錯誤 (400)**\n可能圖片格式不支援或內容被過濾。\n詳細：{e.message[:100]}"

            if ctx.interaction:
                await ctx.send(error_msg, ephemeral=True)
            else:
                await ctx.send(error_msg, delete_after=10)
            return

        except Exception:
            self._pop_failed_message(ctx.author.id)
            log.exception('AI 指令發生系統錯誤')
            msg = "❌ 機器人發生內部錯誤，請通知管理員。"
            if ctx.interaction:
                await ctx.send(msg, ephemeral=True)
            else:
                await ctx.send(msg, delete_after=10)
            return

        # 4. 儲存對話紀錄
        self.conversations[ctx.author.id].append({'role': 'assistant', 'content': reply})
        self._trim_history(ctx.author.id)

        # 5. 回覆（標頭顯示 OpenRouter 自動選的模型）
        model_name = self._format_model_name(actual_model)
        header = f'🤖 **{model_name}**\n'
        await self._send_long_message(ctx, header + reply)

    # ==========================================
    #  /ai_clear 指令
    # ==========================================
    @commands.hybrid_command(name='ai_clear', description='清除對話紀錄')
    async def ai_clear(self, ctx: commands.Context):
        if ctx.author.id in self.conversations:
            del self.conversations[ctx.author.id]
        await ctx.send('🗑️ 已清除你的對話紀錄！', ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))
