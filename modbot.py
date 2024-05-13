from enum import Enum, auto
import discord
import json
import logging
import openai
import os

# Set up logging to the console
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

# Retrieve token
token_path = 'tokens.json'
if not os.path.isfile(token_path):
    raise Exception(f"{token_path} not found!")
with open(token_path) as f:
    tokens = json.load(f)
    discord_token = tokens['discord']
    openai_api_key = tokens['openai']

class State(Enum):
    MOD_START = auto()
    AWAITING_LEARN_MORE = auto()

class ModBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='.', intents=intents)
        self.openai_client = openai.OpenAI(
            api_key=openai_api_key)
        self.state = State.MOD_START

    async def on_ready(self):
        print(f'{self.user.name} has connected to Discord! It is these guilds:')
        for guild in self.guilds:
            print(f' - {guild.name}')
        print('Press Ctrl-C to quit.')

    async def on_message(self, message):
        # Ignore messages sent by bot to itself
        if message.author == self.user:
            return

        response = self.openai_client.moderations.create(input=message.content)
        print("response:", response)
        output = response.results[0]

        # Respond based on moderation resul
        if output.flagged:
            print(f"Flagged content: {message.content}")
            print(f"Output: {output}")
            # Check which categories are flagged
            flagged_categories = [
                category for category, flagged in output.categories.dict().items() if flagged]

            # warning_message = "⚠️ Please adhere to community guidelines due to: " + ", ".join(flagged_categories)
            warning_message = f"Your message \n`{message.content}`\nhas been flagged as potentially harmful.\n"
            warning_message += "Please remember to adhere to the community guidelines.\n\n"
            warning_message += "If you would like to know why your message got flagged, please respond with `learn more`.\n"
            self.State = State.AWAITING_LEARN_MORE
            if message.author.dm_channel is None:
                await message.author.create_dm()
            await message.author.dm_channel.send(warning_message)

            # if self.State == State.AWAITING_LEARN_MORE:
            #     if message.content == "learn more":
            #         info_message = f"Your message was flagged due to violating policies on " + ", ".join(flagged_categories)
        # else:
        #     thank_you_message = "Thank you for keeping the community safe!"
        #     if message.author.dm_channel is None:
        #         await message.author.create_dm()
        #     await message.author.dm_channel.send(thank_you_message) 

        return None

client = ModBot()
client.run(discord_token)