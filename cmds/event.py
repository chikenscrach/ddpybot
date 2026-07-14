import logging

from discord.ext import commands

from core.classes import Cog_Extension

log = logging.getLogger(__name__)


class Event(Cog_Extension):
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
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
        if msg.content == 'ㄐㄐ人臭DD':
            await msg.channel.send('你婆真好用')
        if msg.content == '0.0':
            await msg.channel.send('0.0三小?你是低能兒嗎肏')
        if msg.content == '夸黑':
            await msg.channel.send('主Q副哭 有社恐點社恐')
        if msg.content == '志道樓':
            await msg.channel.send('黃民化運動')


async def setup(bot):
    await bot.add_cog(Event(bot))
