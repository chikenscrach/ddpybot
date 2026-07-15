import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.classes import CogExtension
from services.ai_service import (
    AIError,
    build_user_message,
    create_provider,
    format_model_name,
)
from utils.constants import SYSTEM_PROMPT
from utils.embed_builder import send_long_message

log = logging.getLogger(__name__)

MAX_HISTORY = 20  # 每位使用者保留的對話則數
MAX_USERS = 200   # 最多同時保留幾位使用者的對話，超過踢掉最久沒互動的（防記憶體無限成長）


class AI(CogExtension):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.conversations: dict[int, list] = {}
        self.provider = create_provider()

    async def cog_load(self):
        await self.provider.start()

    async def cog_unload(self):
        await self.provider.close()

    # ==========================================
    #  對話管理
    # ==========================================
    def _get_messages(self, user_id: int, new_message: dict) -> list:
        # LRU：先移除再重插，讓活躍使用者排到 dict 尾端（dict 保插入順序）
        history = self.conversations.pop(user_id, [])
        history.append(new_message)
        self.conversations[user_id] = history
        self._trim_history(user_id)

        # 超過人數上限時，淘汰最久沒互動的使用者（dict 開頭）
        while len(self.conversations) > MAX_USERS:
            oldest = next(iter(self.conversations))
            del self.conversations[oldest]

        return [{'role': 'system', 'content': SYSTEM_PROMPT}] + self.conversations[user_id]

    def _trim_history(self, user_id: int):
        history = self.conversations[user_id]
        if len(history) > MAX_HISTORY:
            self.conversations[user_id] = history[-MAX_HISTORY:]

    def _pop_failed_message(self, user_id: int):
        """API 失敗時移除剛加入的使用者訊息，避免汙染後續對話"""
        history = self.conversations.get(user_id)
        if history and history[-1]['role'] == 'user':
            history.pop()

    # ==========================================
    #  取得被回覆（引用）的訊息
    # ==========================================
    async def _get_referenced_context(
        self, ctx: commands.Context
    ) -> tuple[str | None, str | None, list[str]]:
        """
        如果使用者是「回覆」某則訊息後再打指令，就把被引用的訊息抓出來。

        回傳: (作者顯示名, 訊息文字, 圖片URL列表)
              若沒有引用 → (None, None, [])
        """
        # Slash command 沒有 message.reference，只有 prefix command 才有
        if not ctx.message or not ctx.message.reference:
            return None, None, []

        try:
            ref_msg: discord.Message | None = ctx.message.reference.resolved
            # resolved 可能是 DeletedReferencedMessage 或 None
            if not isinstance(ref_msg, discord.Message):
                ref_msg = await ctx.channel.fetch_message(
                    ctx.message.reference.message_id
                )

            author_name = ref_msg.author.display_name
            content = ref_msg.content or ''

            # 引用訊息裡的圖片也一併收集
            image_urls = [
                att.url
                for att in ref_msg.attachments
                if att.content_type and att.content_type.startswith('image/')
            ]

            # 如果引用訊息有 embed（例如別的 bot 回覆），也把文字抓出來
            for embed in ref_msg.embeds:
                if embed.description:
                    content += f'\n{embed.description}'

            return author_name, content.strip(), image_urls

        except Exception as e:
            log.warning('無法取得引用訊息: %s', e)
            return None, None, []

    # ==========================================
    #  錯誤訊息對照
    # ==========================================
    def _error_message(self, e: AIError) -> str:
        if e.status == 429:
            return '⏳ **請求過於頻繁 (429)**\n模型正在冷卻中，請稍後再試。'
        if e.status == 404:
            return (
                '⚠️ **找不到可用模型 (404)**\n'
                f'請稍後再試，或請管理員檢查 {self.provider.name} 的模型設定。'
            )
        if e.status == 400:
            return (
                '⚠️ **請求格式錯誤 (400)**\n'
                '可能是圖片格式不支援或內容被過濾。\n'
                f'詳細：{e.message[:200]}'
            )
        if e.status == 413:
            return '⚠️ **內容過長 (413)**\n請縮短訊息或用 `/ai_clear` 清除對話紀錄。'
        if e.status == 401:
            return f'🔑 **API Key 無效 (401)**\n{e.message[:200]}'
        return f'❌ API 錯誤：{e.message[:300]}'

    # ==========================================
    #  /ai 指令
    # ==========================================
    @commands.hybrid_command(
        name='ai',
        description='與 AI 對話（回覆某則訊息可自動附加上下文）',
    )
    @app_commands.describe(message='你想說的話')
    async def ai_chat(self, ctx: commands.Context, *, message: str):
        await ctx.typing()

        # ── 1. 取得被引用的訊息 ──
        ref_author, ref_content, ref_images = await self._get_referenced_context(ctx)

        # ── 2. 收集圖片（引用的 + 自己附加的）──
        image_urls = list(ref_images)
        if ctx.message and ctx.message.attachments:
            for att in ctx.message.attachments:
                if att.content_type and att.content_type.startswith('image/'):
                    image_urls.append(att.url)

        # ── 3. 組裝文字 ──
        if ref_content is not None:
            full_text = (
                f'[以下是 {ref_author} 說的話]:\n'
                f'{ref_content}\n\n'
                f'[以下是我的訊息]:\n'
                f'{message}'
            )
        else:
            full_text = message

        # ── 4. 組裝 API 訊息並呼叫 ──
        user_msg = build_user_message(full_text, image_urls if image_urls else None)
        messages = self._get_messages(ctx.author.id, user_msg)

        try:
            reply, actual_model = await self.provider.call(messages)

        except AIError as e:
            self._pop_failed_message(ctx.author.id)
            error_msg = self._error_message(e)
            if ctx.interaction:
                await ctx.send(error_msg, ephemeral=True)
            else:
                await ctx.send(error_msg, delete_after=15)
            return

        except Exception:
            self._pop_failed_message(ctx.author.id)
            log.exception('AI 指令發生系統錯誤')
            msg = '❌ 機器人發生內部錯誤，請通知管理員。'
            if ctx.interaction:
                await ctx.send(msg, ephemeral=True)
            else:
                await ctx.send(msg, delete_after=10)
            return

        # ── 5. 儲存 assistant 回覆到對話紀錄 ──
        self.conversations[ctx.author.id].append({'role': 'assistant', 'content': reply})
        self._trim_history(ctx.author.id)

        # ── 6. 送出回覆（標頭顯示實際使用的模型）──
        model_name = format_model_name(actual_model)
        if ref_content is not None:
            header = f'🤖 **{model_name}**  *(針對 {ref_author} 的訊息)*\n'
        else:
            header = f'🤖 **{model_name}**\n'

        await send_long_message(ctx, header + reply)

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
