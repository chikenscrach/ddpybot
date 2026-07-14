import discord
from discord.ext import commands

from core.classes import Cog_Extension


class Main(Cog_Extension):

    # hybrid_command = 前綴 + 斜線 都能用
    @commands.hybrid_command(name='ping', description='查看機器人延遲')
    async def ping(self, ctx):
        await ctx.send(f'{round(self.bot.latency * 1000)} (ms)')

    @commands.hybrid_command(name='whoru', description='我是誰')
    async def whoru(self, ctx):
        await ctx.send('ㄐㄐ人')

    @commands.hybrid_command(name='dd', description='DD追直播必備連結')
    async def dd(self, ctx):
        embed = discord.Embed(
            title="holo schedule",
            url="https://schedule.hololive.tv/lives/all",
            description="DD追直播必備",
            color=0x07e3f2
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Main(bot))
