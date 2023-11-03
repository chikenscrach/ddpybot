import discord
from os import system
import random
# import keep_alive
from discord.ext import commands
import json
import os

with open('setting.json', 'r', encoding = 'utf8') as jfile:
    jdata = json.load(jfile)

bot = commands.Bot(command_prefix = ['!', '！'])

@bot.event
async def on_ready():
    print(">> Bot is online <<")
    game = discord.Game('你婆真好用')
    await bot.change_presence(status=discord.Status.idle,activity=game)

@bot.command()
async def load(ctx, extension):
    bot.load_extension(f'cmds.{extension}')
    await ctx.send(f'Loaded {extension} done.')

@bot.command()
async def unload(ctx, extension):
    bot.unload_extension(f'cmds.{extension}')
    await ctx.send(f'Unloaded {extension} done.')

@bot.command()
async def reload(ctx, extension):
    bot.reload_extension(f'cmds.{extension}')
    await ctx.send(f'Reloaded {extension} done.')

for filename in os.listdir('./cmds'):
    if filename.endswith('.py'):
        bot.load_extension(f'cmds.{filename[:-3]}')

if __name__ == "__main__":
    try:
#         keep_alive.keep_alive()
        bot.run(jdata['token'])
    except discord.errors.HTTPException:
        print("\n\n\nBLOCKED BY RATE LIMITS\nRESTARTING NOW\n\n\n")
        system("python restarter.py")
        system('kill 1')
