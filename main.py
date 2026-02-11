import discord
from discord.ext import commands
import json
import os

with open('setting.json', 'r', encoding='utf8') as jfile:
    jdata = json.load(jfile)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=['!', '！'],
    intents=intents,
    help_command=None,  # ← 加這行，改由自訂的 Help cog 處理
)


async def setup_hook():
    for filename in os.listdir('./cmds'):
        if filename.endswith('.py'):
            await bot.load_extension(f'cmds.{filename[:-3]}')
            print(f'  ✅ 已載入: {filename[:-3]}')

bot.setup_hook = setup_hook


@bot.event
async def on_ready():
    # ✅ 同步斜線指令到 Discord
    synced = await bot.tree.sync()
    print(f'🔄 已同步 {len(synced)} 個斜線指令')

    print(">> Bot is online <<")
    game = discord.Game('你婆真好用')
    await bot.change_presence(status=discord.Status.idle, activity=game)


@bot.command()
@commands.is_owner()  # 只有 Bot 擁有者能用
async def load(ctx, extension):
    await bot.load_extension(f'cmds.{extension}')
    await ctx.send(f'✅ Loaded `{extension}` done.')

@bot.command()
@commands.is_owner()
async def unload(ctx, extension):
    await bot.unload_extension(f'cmds.{extension}')
    await ctx.send(f'✅ Unloaded `{extension}` done.')

@bot.command()
@commands.is_owner()
async def reload(ctx, extension):
    await bot.reload_extension(f'cmds.{extension}')
    await ctx.send(f'✅ Reloaded `{extension}` done.')


if __name__ == "__main__":
    bot.run(jdata['token'])