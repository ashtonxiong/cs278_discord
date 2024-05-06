import discord
from discord.ext import commands
 

bot = commands.Bot(command_prefix=",", intents=discord.Intents.all())

@bot.event
async def on_start_up():
    print("Bot Initialized and Ready!")

# Token for running
bot.run("MTIzNTgwNjQwNDY4Njc3ODM2OA.GhvxAX.xFDx2l_MTii62KLA9Xy2hDbVewwnYl8r4pfJEo")