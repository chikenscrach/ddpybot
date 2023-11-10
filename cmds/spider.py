import discord
from discord.ext import commands
from core.classes import Cog_Extension
import time, requests, json
from urllib.request import urlopen
from bs4 import BeautifulSoup

with open('setting.json', 'r', encoding = 'utf8') as jfile:
    jdata = json.load(jfile)

class Game(Cog_Extension):
    @commands.command()
    async def 八卦版(self, ctx):
        r = requests.Session()
        payload ={
            "from":"/bbs/Gossiping/index.html",
            "yes":"yes"
        }
        r1 = r.post("https://www.ptt.cc/ask/over18?from=%2Fbbs%2FGossiping%2Findex.html",payload)
        r2 = r.get("https://www.ptt.cc/bbs/Gossiping/index.html")
        soup = BeautifulSoup(r2.text, "html.parser")
        sel = soup.select("div.title a")
        for s in sel:
            await ctx.send(s.text)
        await ctx.send('先這樣啦')

    @commands.command()
    async def ayame(self, ctx):
        
        url = 'https://script.googleusercontent.com/macros/echo?user_content_key=61qJeCgvkRi7hX6QyucfotrC7AXmhF0BgepQ8mbL5yPTdvSxolySS-EsQi1UBe8BNedOIrmIJLM7Fbzy1BxtvIoRZVyzdhg4m5_BxDlH2jW0nuo2oDemN9CCS2h10ox_1xSncGQajx_ryfhECjZEnNqVaIg6uWIusfaT6109P6AiX8-Jc70itxwf3vkR0F4vwX0NWBNrxNkTEKkvViUG5ASCAyw-o_Tv2w637yi-8rE7WE8Pq9zTnw&lib=Mv0Flh1wcXT8fGz2m4i_W0fGCLS4z58-Q'

        data = json.loads(urlopen(url).read().decode('utf-8'))
        if data['live'] == 'none':
            c = data['pubt'][:10] + ' ' + data['pubt'][11:19]
            a = time.mktime(time.strptime(c,'%Y-%m-%d %H:%M:%S'))
            b = time.time() - 28800

            hcont = 60 * 60
            dcont = 24 * hcont
            days = int((b - a) // dcont)
            hours = int(((b - a) - days * dcont) // hcont)
            mins = int(((b - a) - days * dcont - hours * hcont) // 60)
            secs = int((b - a) - days * dcont - hours * hcont - mins * 60)

            await ctx.send('鬼鬼上次開台已經過了：')
            blackghost = str(days) + ' 天 '+ str(hours)+ ' 時 '+ str(mins)+ ' 分 '+ str(secs)+ ' 秒'
            await ctx.send(blackghost)
          
        elif data['live'] == 'upcoming':
            await ctx.send('鬼鬼要開台啦！等好久了！')

        elif data['live'] == 'live':
            await ctx.send('鬼鬼正在開台，趕快跟上！')
          
        elif data['live'] == 'twet':
            httpstart = data['pubt'].find('https')
            twetstring = data['pubt'][httpstart : httpstart + 58]
            await ctx.send(twetstring)

        else:
          await ctx.send('不要再黑我們鬼鬼了')

    @commands.command()
    async def gura(self, ctx):

        payload = {'channel_id': 'UCoSrY_IQQVpmIRZ9Xf-y93g', 'max_upcoming_hours': '24', 'type': 'stream', 'limit': '1'}
        url = 'https://holodex.net/api/v2/videos'
        headers = {'X-APIKEY': jdata['holodexAPIkey']}

        r = requests.get(url, headers=headers, params=payload)
        s = json.loads(r.text)[0]
        t = time.time()

        stream = "[" + s['title'] + "](https://youtu.be/" + s['id'] + ")"
        
        if s['status'] == 'past':
            a = s["available_at"]
            atime = time.strptime(a, "%Y-%m-%dT%H:%M:%S.%fZ")
            b = t - time.mktime(atime)
            td = b // 86400
            b -= td * 86400
            th = b // 3600
            b -= th * 3600
            tm = b // 60
            b -= tm * 60
            await ctx.send("鯊鯊上次開台已經過了：")
            last = str(int(td)) + " 天 " + str(int(th)) + " 時 " + str(int(tm)) + " 分 " + str(int(b)) + " 秒" # 這邊要注意時區...
            await ctx.send(last)
            await ctx.send(stream)
            
        elif s['status'] == 'upcoming':
            await ctx.send("鯊鯊就快開台了，還不快去待機！")
            await ctx.send(stream)
            
        elif s['status'] == 'live':
            await ctx.send("鯊鯊正在開台，還不快去看！")
            await ctx.send(stream)
            
        else:
            await ctx.send("不要再黑我們可愛的鯊鯊了！")

def setup(bot):
    bot.add_cog(Game(bot)) 
