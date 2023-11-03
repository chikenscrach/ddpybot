import discord
from discord.ext import commands
from core.classes import Cog_Extension
from bs4 import BeautifulSoup
import json, asyncio, datetime
import random, requests, re

class Task(Cog_Extension):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.counter = 0

        self.teratimer = 0

        #async def interval():
            #await self.bot.wait_until_ready()
            
            #while not self.bot.is_closed():
                #self.channel = self.bot.get_channel(838424188490350632)
                #await self.channel.send('<@669195617666596896> 請改名')
                #self.channel = self.bot.get_channel(838424188490350632)
                #await self.channel.send('<@669546089287909407> 請改名')
                #await asyncio.sleep(30)

        #self.bg_task = self.bot.loop.create_task(interval())

        async def time_task():
            await self.bot.wait_until_ready()
            
            while not self.bot.is_closed():
                now_time = datetime.datetime.now().strftime('%H%M')
                with open('setting.json', 'r', encoding = 'utf8') as jfile:
                    jdata = json.load(jfile)
                if now_time == jdata['time'] and self.counter == 0:
                    self.channel = self.bot.get_channel(669209872163930129)
                    randomping = '每日隨機標 ' + random.choice(jdata['member'])
                    await self.channel.send(randomping)
                    self.counter = 1
                    """
                    r1 = requests.get("https://gelbooru.com/index.php?page=post&s=list&tags=mikeneko_%28utaite%29+")
                    soup = BeautifulSoup(r1.text, "html.parser")
                    sel = soup.select("div.pagination a")
                    regex = re.compile('pid=\d*')
                    pid = regex.findall(str(sel[-1]))
                    pid2 = re.search(r"\d+\.?\d*", str(pid)).group(0)
                    cho = random.randint(0, int(pid2))
                    r2 = requests.get(f"https://gelbooru.com/index.php?page=post&s=list&tags=mikeneko_%28utaite%29&pid={cho}")
                    s2 = BeautifulSoup(r2.text, "html.parser")
                    s3 = s2.select("div.thumbnail-container img")
                    await self.channel.send(str(s3[0]["src"]).replace("thumbnails", "images").replace("thumbnail_", ""))
                    """
                    await asyncio.sleep(1)
                else:
                    await asyncio.sleep(1)
                    pass

        self.bg_task = self.bot.loop.create_task(time_task())

        async def setcounter():
            await self.bot.wait_until_ready()
            while not self.bot.is_closed():
                now_time = datetime.datetime.now().strftime('%H%M')
                with open('setting.json', 'r', encoding = 'utf8') as jfile:
                    jdata = json.load(jfile)
                if int(now_time) == int(jdata['time']) + 1 and self.counter == 1:
                    self.counter = 0
                    await asyncio.sleep(1)
                else:
                    await asyncio.sleep(1)
                    pass

        self.bg_task = self.bot.loop.create_task(setcounter())

        async def timer_task():
            await self.bot.wait_until_ready()
            
            while not self.bot.is_closed():
                now_time = datetime.datetime.now().strftime('%H%M')
                if now_time == "1200" and self.teratimer == 0:
                    webhook_url = 'webhook_url'
                    slack_data = {'content':"<@800620782585643038> TERABOX領個 <a:FinanaWaveAni:993901012685422674>","username":"提醒ㄐㄐ人","avatar_url":"https://pbs.twimg.com/profile_images/1417779662348984324/eG2a5mY4_400x400.jpg"}
                    response = requests.post(webhook_url, data=json.dumps(slack_data),headers={'Content-Type': 'application/json'})
                    self.teratimer = 1
                    await asyncio.sleep(1)
                else:
                    await asyncio.sleep(1)
                    pass

        self.bg_task = self.bot.loop.create_task(timer_task())

        async def set_timer():
            await self.bot.wait_until_ready()
            while not self.bot.is_closed():
                now_time = datetime.datetime.now().strftime('%H%M')
                if int(now_time) == 1201 and self.teratimer == 1:
                    self.teratimer = 0
                    await asyncio.sleep(1)
                else:
                    await asyncio.sleep(1)
                    pass

        self.bg_task = self.bot.loop.create_task(set_timer())

    @commands.command()
    async def set_channel(self, ctx, ch: int):
        self.channel = self.bot.get_channel(ch)
        await ctx.send(f'Set Channel: {self.channel.mention}')

    @commands.command()
    async def set_time(self, ctx, time):
        with open('setting.json', 'r', encoding = 'utf8') as jfile:
            jdata = json.load(jfile)
        jdata['time'] = time
        with open('setting.json', 'w', encoding = 'utf8') as jfile:
            json.dump(jdata, jfile, indent = 4)

def setup(bot):
    bot.add_cog(Task(bot))
