from enum import Enum, auto
import discord
import json
import logging
import openai
from openai import OpenAI
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
    AWAITING_MORE = auto()

class ModBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='.', intents=intents)
        self.openai_client = openai.OpenAI(api_key=openai_api_key)
        # self.state = State.MOD_START
        self.user_state = {}

    async def on_ready(self):
        print(f'{self.user.name} has connected to Discord! It is these guilds:')
        for guild in self.guilds:
            print(f' - {guild.name}')
        print('Press Ctrl-C to quit.')

    async def on_message(self, message):
        # Ignore messages sent by bot to itself
        if message.author == self.user:
            return

        # Check if the message is a DM
        if message.guild is None: 
            if message.author in self.user_state and self.user_state[message.author]['state'] == State.AWAITING_MORE:
                if message.content.lower() == "learn more":
                    content, categories = self.user_state[message.author]['data']
                    categories = [category.replace('_', ' ').replace('/', ' ') for category in categories]
                    info_message = f"Your message\n`{content}`\nwas flagged due to: " + ', '.join(categories) + ".\n"
                    await message.author.send(info_message)
                if message.content.lower() == "report":
                    info_message = "Thank you for submitting a report.\n"
                    info_message += "Your message will be reviewed by our content moderation team.\n"
                    info_message += "You will be informed if your message is restored.\n\n"
                    await message.author.send(info_message)
                if message.content.lower() == "done":
                    info_message = "Thank you. Your interaction has ended.\n"
                    await message.author.send(info_message)
                    self.user_state[message.author]['state'] = State.MOD_START  # Reset state
            return  # Stop processing if it's a DM and no relevant state action


        response = self.openai_client.moderations.create(input=message.content)
        output = response.results[0]

        # Respond based on moderation resul
        if output.flagged:
            await message.delete()
            # Check which categories are flagged
            flagged_categories = [
                category for category, flagged in output.categories.dict().items() if flagged]
            self.user_state[message.author] = {'state': State.AWAITING_MORE, 'data': (message.content, flagged_categories)}
            print("user_state:", self.user_state)

            warning_message = f"Your message \n`{message.content}`\nwas flagged as potentially harmful and has been deleted.\n\n"
            warning_message += "Please remember to adhere to the community guidelines.\n\n\n"
            warning_message += "If you would like to know why your message was deleted, please respond with `learn more`.\n"
            warning_message += "If you believe your message was not harmful and should not have been deleted, please respond with `report`.\n"
            warning_message += "If you are done, please respond with `done`.\n"

            if message.author.dm_channel is None:
                await message.author.create_dm()
            await message.author.dm_channel.send(warning_message)
            self.State = State.AWAITING_MORE

        return None

client = ModBot()
client.run(discord_token)