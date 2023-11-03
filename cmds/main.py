import discord
from discord.ext import commands
from core.classes import Cog_Extension

class Main(Cog_Extension):

    @commands.command()
    async def ping(self, ctx):
        await ctx.send(f'{round(self.bot.latency * 1000)} (ms)')
    
    @commands.command()
    async def whoru(self, ctx):
        await ctx.send('ㄐㄐ人')

    @commands.command()
    async def titan(self, ctx):
        await ctx.send('<@&834761922782953502> 起床開打')

    @commands.command()
    async def DD(self, ctx):
      embed=discord.Embed(title="holo schedule", url="https://schedule.hololive.tv/lives/all", description="DD追直播必備", color=0x07e3f2)
      await ctx.send(embed=embed)



def setup(bot):
    bot.add_cog(Main(bot))