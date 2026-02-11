import discord
from discord.ext import commands
from discord import app_commands
from core.classes import Cog_Extension
import aiohttp
import json

with open('setting.json', 'r', encoding='utf8') as jfile:
    jdata = json.load(jfile)

OPENROUTER_API_KEY = jdata['openrouter_api_key']
OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'
SYSTEM_PROMPT = '你是一個專業的Discord機器人，請用繁體中文回答。回答精準、專業，必要時詳細補充說明。'

# 模型清單保持不變
MODELS = {
    'gemma':  {
        'id': 'google/gemma-3-27b-it:free',
        'name': 'Gemma 3 27B',
        'emoji': '🔵',
        'description': 'Google Gemma 3（支援圖片辨識）',
    },
    'glm': {
        'id': 'z-ai/glm-4.5-air:free',
        'name': 'GLM 4.5 Air',
        'emoji': '🟢',
        'description': '智譜 GLM 4.5',
    },
    'venice': {
        'id': 'cognitivecomputations/dolphin-mistral-24b-venice-edition:free',
        'name': 'Dolphin Mistral 24B',
        'emoji': '🟣',
        'description': 'Dolphin Mistral 24B Venice Edition',
    },
    # ✅ 未來要加新模型，直接在這裡新增即可
    # 'llama': {
    #     'id': 'meta-llama/llama-4-scout:free',
    #     'name': 'Llama 4 Scout',
    #     'emoji': '🟣',
    #     'description': 'Meta Llama 4',
    # },
}
DEFAULT_MODEL = 'glm'
MODEL_CHOICES = [app_commands.Choice(name=f'{info["emoji"]} {info["name"]}', value=key) for key, info in MODELS.items()]


# ✅ 1. 定義一個 API 錯誤類別
class OpenRouterError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


class AI(Cog_Extension):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.conversations: dict[int, list] = {}
        self.user_models: dict[int, str] = {}

    # ==========================================
    #  呼叫 OpenRouter API (修改過)
    # ==========================================
    async def _call_api(self, messages: list, model_key: str) -> str:
        model_id = MODELS[model_key]['id']
        headers = {
            'Authorization': f'Bearer {OPENROUTER_API_KEY}',
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://discord.com', # OpenRouter 建議加上
            'X-Title': 'Discord Bot',
        }
        payload = {'model': model_id, 'messages': messages}

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(OPENROUTER_URL, headers=headers, json=payload) as resp:
                    # ✅ 2. 如果狀態碼不是 200，直接拋出例外
                    if resp.status != 200:
                        error_text = await resp.text()
                        # 將錯誤拋給外層處理
                        raise OpenRouterError(resp.status, error_text)

                    data = await resp.json()
                    
                    if 'error' in data:
                         raise OpenRouterError(resp.status, json.dumps(data['error']))

                    if 'choices' not in data or not data['choices']:
                        raise OpenRouterError(resp.status, "API 回傳格式異常 (無 choices)")

                    return data['choices'][0]['message']['content']
                    
            except aiohttp.ClientError as e:
                # 網路連線問題
                raise OpenRouterError(0, f"網路連線錯誤: {str(e)}")

    # ==========================================
    #  工具方法 (保持不變)
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
        if user_id not in self.conversations: self.conversations[user_id] = []
        self.conversations[user_id].append(new_message)
        if len(self.conversations[user_id]) > 20: self.conversations[user_id] = self.conversations[user_id][-20:]
        messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
        messages.extend(self.conversations[user_id])
        return messages

    def _get_user_model(self, user_id: int) -> str:
        return self.user_models.get(user_id, DEFAULT_MODEL)

    @staticmethod
    async def _send_long_message(ctx, text: str):
        while len(text) > 2000:
            split_pos = text[:2000].rfind('\n')
            if split_pos == -1: split_pos = 2000
            await ctx.send(text[:split_pos])
            text = text[split_pos:]
        if text: await ctx.send(text)

    # ==========================================
    #  /ai 指令 (修改過)
    # ==========================================
    @commands.hybrid_command(name='ai', description='與 AI 對話')
    @app_commands.describe(message='你想說的話', model='選擇 AI 模型')
    @app_commands.choices(model=MODEL_CHOICES)
    async def ai_chat(self, ctx: commands.Context, *, message: str, model: str = None):
        model_key = model if model and model in MODELS else self._get_user_model(ctx.author.id)
        if model_key not in MODELS: model_key = DEFAULT_MODEL
        model_info = MODELS[model_key]

        # 這裡不使用 async with ctx.typing() 包住整個區塊
        # 因為如果在 typing 中出錯，有時錯誤訊息顯示會怪怪的
        await ctx.typing()

        try:
            # 1. 準備資料
            image_urls = []
            if ctx.message and ctx.message.attachments:
                for att in ctx.message.attachments:
                    if att.content_type and att.content_type.startswith('image/'):
                        image_urls.append(att.url)

            user_msg = self._build_user_message(message, image_urls if image_urls else None)
            messages = self._get_messages(ctx.author.id, user_msg)

            # 2. 呼叫 API (這裡可能會報錯)
            reply = await self._call_api(messages, model_key)

            # 3. 成功：儲存對話並回覆 (公開)
            self.conversations[ctx.author.id].append({'role': 'assistant', 'content': reply})
            
            header = f'{model_info["emoji"]} **{model_info["name"]}**\n'
            await self._send_long_message(ctx, header + reply)

        except OpenRouterError as e:
            # ✅ 3. 捕捉錯誤：只顯示給使用者看 (Ephemeral)
            error_msg = f"❌ API 錯誤: {e.message}"
            
            if e.status == 429:
                error_msg = "⏳ **請求過於頻繁 (429)**\n目前免費模型正在冷卻中，請稍後再試，或切換其他模型。"
            elif e.status == 404:
                error_msg = f"⚠️ **找不到模型 (404)**\n模型 `{model_info['id']}` 可能已失效或維修中。"
            elif e.status == 400:
                error_msg = f"⚠️ **請求格式錯誤 (400)**\n可能圖片格式不支援或內容被過濾。\n詳細：{e.message[:100]}"

            # 如果是斜線指令，ephemeral=True 會讓訊息只有該用戶看得到
            if ctx.interaction:
                await ctx.send(error_msg, ephemeral=True)
            else:
                # 如果是前綴指令 (!ai)，無法使用 ephemeral，改用 10 秒後自動刪除
                await ctx.send(error_msg, delete_after=10)

        except Exception as e:
            # 其他未知的 Python 錯誤
            print(f"系統錯誤: {e}")
            msg = "❌ 機器人發生內部錯誤，請通知管理員。"
            if ctx.interaction:
                await ctx.send(msg, ephemeral=True)
            else:
                await ctx.send(msg, delete_after=10)

    # ... 其他指令 (ai_setmodel, ai_models, ai_clear) 保持原樣 ...
    @commands.hybrid_command(name='ai_setmodel', description='設定你的預設 AI 模型')
    @app_commands.describe(model='選擇預設模型')
    @app_commands.choices(model=MODEL_CHOICES)
    async def ai_setmodel(self, ctx: commands.Context, model: str):
        if model not in MODELS:
            await ctx.send(f'❌ 未知的模型 `{model}`', ephemeral=True)
            return
        self.user_models[ctx.author.id] = model
        info = MODELS[model]
        await ctx.send(f'✅ 已將預設模型設定為 {info["emoji"]} **{info["name"]}**', ephemeral=True)

    @commands.hybrid_command(name='ai_models', description='查看所有可用的 AI 模型')
    async def ai_models(self, ctx: commands.Context):
        current = self._get_user_model(ctx.author.id)
        embed = discord.Embed(title='🤖 可用的 AI 模型', color=0x5865F2)
        for key, info in MODELS.items():
            marker = ' ← 目前預設' if key == current else ''
            embed.add_field(name=f'{info["emoji"]} {info["name"]}{marker}', value=f'> {info["description"]}', inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='ai_clear', description='清除對話紀錄')
    async def ai_clear(self, ctx: commands.Context):
        if ctx.author.id in self.conversations: del self.conversations[ctx.author.id]
        await ctx.send('🗑️ 已清除你的對話紀錄！', ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))