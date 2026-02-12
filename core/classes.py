import discord
from discord.ext import commands
import json

# 自訂檢查器：確認使用者是否在 moderator_ids 清單中
def is_manager():
    def predicate(ctx):
        with open('setting.json', 'r', encoding='utf8') as jfile:
            jdata = json.load(jfile)
        
        # 取得設定檔中的 ID 清單
        manager_list = jdata.get('moderator_ids', [])
        
        # 判斷邏輯：
        # 1. 使用者 ID 在清單中
        # 2. 或者使用者擁有伺服器「管理員」權限 (這行可選，建議保留以免將來你自己被擋住)
        if ctx.author.id in manager_list or ctx.author.guild_permissions.administrator:
            return True
        
        return False
    return commands.check(predicate)

class Cog_Extension(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot