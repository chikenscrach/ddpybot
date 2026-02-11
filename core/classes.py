import discord
from discord.ext import commands

class Cog_Extension(commands.Cog):
    # 在這裡加上 : commands.Bot 可以讓編輯器知道 bot 是一個機器人物件
    def __init__(self, bot: commands.Bot):
        self.bot = bot