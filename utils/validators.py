# ──────────────────────────────────────────────
#  輸入驗證 / 權限檢查
# ──────────────────────────────────────────────
from discord.ext import commands

from core.config import settings


def is_manager():
    """
    自訂檢查器：確認使用者是否在 moderator_ids 清單中，
    或擁有伺服器管理員權限。

    settings 由 core.config 啟動時載入一次，不會每次檢查都重讀檔案；
    私訊中沒有 guild，需先排除以免 AttributeError。
    """
    def predicate(ctx):
        manager_list = settings.get('moderator_ids', [])
        if ctx.author.id in manager_list:
            return True
        return ctx.guild is not None and ctx.author.guild_permissions.administrator
    return commands.check(predicate)
