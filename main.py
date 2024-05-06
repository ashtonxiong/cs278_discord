import discord
from discord.ext import commands
 

bot = commands.Bot(command_prefix=",", intents=discord.Intents.all())

@bot.event
async def on_start_up():
    print("Bot Initialized and Ready!")

# Token for running
# In the parenthesisof bot.run add the token"
bot.run()