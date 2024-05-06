import discord
from discord.ext import commands
 

bot = commands.Bot(command_prefix=",", intents=discord.Intents.all())

@bot.event
async def on_start_up():
    print("Bot Initialized and Ready!")

# Token for running
token = "MTIzNTgwNjQwNDY4Njc3ODM2OA.GhvxAX.xFDx2l_MTii62KLA9Xy2hDbVewwnYl8r4pfJEo"
secret = token.encode('utf-8')
token = secret.decode('utf-8')
bot.run(token)