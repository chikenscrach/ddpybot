import discord
from discord.ext import commands
from core.classes import Cog_Extension
import random
import json
import datetime

with open('setting.json', 'r', encoding = 'utf8') as jfile:
    jdata = json.load(jfile)

class React(Cog_Extension):
    @commands.command()
    async def 圖片(self, ctx):
        random_pic = random.choice(jdata['url_pic'])
        await ctx.send(random_pic)

    @commands.command()
    async def APEX(self, ctx):
        await ctx.send('幹你娘0分')

    @commands.command()
    async def say(self, ctx, *, msg):
        await ctx.message.delete()
        await ctx.send(msg)

    @commands.command()
    async def clean(self, ctx, num : int):
        await ctx.channel.purge(limit = num + 1)

    @commands.command()
    async def angry(self, ctx):
        await ctx.message.delete()
        await ctx.send('閉嘴啦低能兒')

    @commands.command()
    async def 宵夜街(self, ctx):
        random_eat1 = random.choice(jdata['night'])
        await ctx.send(random_eat1)

    @commands.command()
    async def 後門(self, ctx):
        random_eat2 = random.choice(jdata['back'])
        await ctx.send(random_eat2)

    @commands.command()
    async def 亞歷山大(self, ctx):
        await ctx.send('https://imgur.com/5MRjKt0')

def setup(bot):
    bot.add_cog(React(bot))