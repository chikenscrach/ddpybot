import logging

from discord.ext import commands

from core.classes import CogExtension

log = logging.getLogger(__name__)

# 完全比對的自動回覆表：新增規則只需加一行資料
AUTO_REPLIES = {
    'ㄐㄐ人臭DD': '你婆真好用',
    '0.0': '0.0三小?你是低能兒嗎肏',
    '夸黑': '主Q副哭 有社恐點社恐',
    '志道樓': '黃民化運動',
}


class Event(CogExtension):
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            msg = f'⏳ 指令冷卻中，請 {error.retry_after:.0f} 秒後再試。'
            if ctx.interaction:
                await ctx.send(msg, ephemeral=True)
            else:
                await ctx.send(msg, delete_after=5)

        elif isinstance(error, commands.CheckFailure):
            await ctx.send('🚫 **你沒有權限使用此指令！**', delete_after=5)

        elif isinstance(error, commands.CommandNotFound):
            pass

        else:
            log.error('指令 %s 發生錯誤', ctx.command, exc_info=error)

    # ✅ 必須加上 @commands.Cog.listener()，Cog 裡的方法才會註冊為事件監聽器
    @commands.Cog.listener()
    async def on_message(self, msg):
        if msg.author.bot:  # 排除自己與其他機器人，避免互相觸發
            return
        if msg.content.endswith('的啦'):
            await msg.channel.send('原住民?')
        elif msg.content in AUTO_REPLIES:
            await msg.channel.send(AUTO_REPLIES[msg.content])


async def setup(bot):
    await bot.add_cog(Event(bot))
