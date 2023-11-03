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
    async def on_member_join(self, member):
        channel = self.bot.get_channel(835805162530537505)
        await channel.send(f'{member} join!')

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        channel = self.bot.get_channel(835805189999034388)
        await channel.send(f'{member} leave!')

    @commands.Cog.listener()
    async def on_message(self, msg):
        if msg.content.endswith('的啦'):
            await msg.channel.send('原住民?')
        if msg.content.endswith('nanora'):
            random_pic = random.choice(jdata['luna'])
            await msg.channel.send(random_pic)
        if msg.content == '誰討厭我':
            await msg.channel.send('<@321546647920312323> 討厭大家')
        if msg.content == 'ㄐㄐ人臭DD':
            await msg.channel.send('你婆真好用')
        # if msg.content == '0.0':
            # await msg.channel.send('0.0三小?你是低能兒嗎肏')
        if msg.content == '夸黑':
            await msg.channel.send('主Q副哭 有社恐點社恐')
        if msg.content == '口交惡徒':
            await msg.channel.send('我叫你吹')
            await msg.channel.send('https://tsj.tw/img/artworks/03.jpg')
        if msg.content == '志道樓':
            await msg.channel.send('黃民化運動')

def setup(bot):
    bot.add_cog(Event(bot))