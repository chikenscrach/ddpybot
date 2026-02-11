import discord
from discord.ext import commands
from discord.utils import get
from core.classes import Cog_Extension
import json
import random

with open('setting.json', 'r', encoding = 'utf8') as jfile:
    jdata = json.load(jfile)

class Event(Cog_Extension):
    @commands.Cog.listener()
    async def on_message(self, msg):
        if msg.author == self.bot.user:
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