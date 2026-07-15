from discord.ext import commands


class CogExtension(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot


# 向下相容別名：舊程式碼（或外部複製來的 cog）可能仍 import Cog_Extension
Cog_Extension = CogExtension
