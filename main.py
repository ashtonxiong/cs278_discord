import discord
from discord.ext import commands
 

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

@bot.event
async def on_ready():
    print("Bot Initialized and Ready!")

@bot.command()
async def slash(xmd):
    await xmd.send("test")

@bot.command()
async def hello(ctx):
    await ctx.send("Hello There!")

# Token for running
# In the parenthesisof bot.run add the token"
# When pushing make sure to remove the token or discord will automatically refresh the token.
bot.run("MTIzNTgwNjQwNDY4Njc3ODM2OA.GWuHRi.Q5hTQDLGuMEMsnw_hJmt65fartNNk9Ebp2EJ8s")