from discord.ext import commands

from core.config import settings


# 自訂檢查器：確認使用者是否在 moderator_ids 清單中
def is_manager():
    def predicate(ctx):
        # 取得設定檔中的 ID 清單（settings 由 core.config 啟動時載入一次）
        manager_list = settings.get('moderator_ids', [])

        # 判斷邏輯：
        # 1. 使用者 ID 在清單中
        # 2. 或者使用者擁有伺服器「管理員」權限（私訊中沒有 guild，需先排除）
        if ctx.author.id in manager_list:
            return True
        return ctx.guild is not None and ctx.author.guild_permissions.administrator
    return commands.check(predicate)


class Cog_Extension(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
