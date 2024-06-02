import asyncio
from enum import Enum, auto
import discord
from discord.ext import commands
import json
import logging
import openai
from openai import OpenAI
import os
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth

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
    discord_guild = tokens['discord_guild']
    openai_api_key = tokens['openai']
    spotify_client_id = tokens['spotify_client_id']
    spotify_client_secret = tokens['spotify_client_secret']
    spotify_redirect_uri = tokens['spotify_redirect_uri']

class State(Enum):
    REPORT_START = auto()
    ADDING_DETAILS = auto()
    MESSAGE_DETAILS = auto()
    CREATE_EDIT_PROFILE = auto()
    AWAITING_NAME = auto()
    AWAITING_GENRES = auto()
    AWAITING_ARTISTS = auto()
    AWAITING_SONG = auto()
    AWAITING_EVENTS = auto()

class ModBot(commands.Bot):
    HELP_KEYWORD = "help"
    CANCEL_KEYWORD = "cancel"
    START_REPORT_KEYWORD = "report"
    LEARN_MORE_KEYWORD = "learn more"
    MUSIC_PROFILE_KEYWORD = "music"

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='.', intents=intents)
        self.openai_client = openai.OpenAI(api_key=openai_api_key)
        self.user_state = {}  # Store states for bot DM interactions
        self.user_profiles = {}  # Store music profiles

    async def on_ready(self):
        print(f'{self.user.name} has connected to Discord! It is these guilds:')
        for guild in self.guilds:
            print(f' - {guild.name}')
        print('Press Ctrl-C to quit.')
        
    async def on_message(self, message):
        if message.author == self.user:
            return

        if message.guild is None:
            print('message sent to bot:', message.content)
            if message.content.lower() == self.HELP_KEYWORD:
                reply = "If your message was flagged as potentially harmful and was deleted, use the options below.\n"
                reply += "Type `learn more` to learn why your message was deleted.\n"
                reply += "Type `report` to dispute if you believe your message was wrongfully deleted.\n\n"
                reply += "If you would like to create or edit your music profile, use the option below.\n"
                reply += "Type `music` to create or edit your music profile.\n"
                await message.author.send(reply)
                return
            if message.content.lower() == self.CANCEL_KEYWORD:
                self.user_state[message.author.id] = {'state': None}
                await message.author.send("Action cancelled.")
                return
            if message.content.lower() == self.START_REPORT_KEYWORD:
                reply = "Thank you for starting the reporting process.\n"
                reply += "Your message will be reviewed by our content moderation team.\n"
                reply += "Would you like to add additional details to include in the report?\n"
                reply += "Please respond with `yes` or `no`.\n"
                self.user_state[message.author.id] = {'state': State.REPORT_START}
                await message.author.send(reply)
                return
            if message.content.lower() == self.LEARN_MORE_KEYWORD:
                content, categories = self.user_state[message.author.id]['data']
                categories = [category.replace('_', ' ').replace('/', ' ') for category in categories]
                reply = f"Your message\n`{content}`\nwas flagged due to: " + ', '.join(categories) + ".\n"
                self.user_state[message.author.id]['state'] = State.MESSAGE_DETAILS
                await message.author.send(reply)
                return
            if message.content.lower() == self.MUSIC_PROFILE_KEYWORD:
                self.user_state[message.author.id] = {'state': State.CREATE_EDIT_PROFILE}
                if message.author.id in self.user_profiles:
                    profile = self.user_profiles[message.author.id]
                    reply = "Your current profile:\n"
                    reply += f"Name: {profile['name']}\nFavorite Genres: {profile['genres']}\nFavorite Artists: {profile['artists']}\nMost played song right now: {profile['song']}\nUpcoming music events you're attending: {profile['events']}\n\n"
                    reply += "Let's update your music profile.\n"
                    reply += "What is your preferred name?\n"
                else:
                    reply = "Let's create your music profile.\n"
                    reply += "What is your preferred name?\n"
                await message.author.send(reply)
                self.user_state[message.author.id]['state'] = State.AWAITING_NAME
                return
            
            user_state = self.user_state.get(message.author.id)
            if user_state:
                state = user_state['state']

                if state == State.REPORT_START:
                    if message.content.lower() == 'yes':
                        await message.author.send("Please provide the additional details for your report.")
                        self.user_state[message.author.id]['state'] = State.ADDING_DETAILS
                    elif message.content.lower() == 'no':
                        await message.author.send("Thank you for submitting a report. You will be notified if your message is restored.\n")
                        self.user_state[message.author.id] = {'state': None}
                    return
                if state == State.ADDING_DETAILS:
                    await message.author.send("Thank you for the additional details. Your report has been updated and submitted. You will be notified if your message is restored.\n")
                    self.user_state[message.author.id] = {'state': None}
                    return

                if state == State.AWAITING_NAME:
                    if message.author.id not in self.user_profiles:
                        self.user_profiles[message.author.id] = {}
                    self.user_profiles[message.author.id]['name'] = message.content
                    await message.author.send("What are your favorite genres?")
                    self.user_state[message.author.id]['state'] = State.AWAITING_GENRES
                elif state == State.AWAITING_GENRES:
                    self.user_profiles[message.author.id]['genres'] = message.content
                    await message.author.send("Who are your favorite artists?")
                    self.user_state[message.author.id]['state'] = State.AWAITING_ARTISTS
                elif state == State.AWAITING_ARTISTS:
                    self.user_profiles[message.author.id]['artists'] = message.content
                    await message.author.send("What is your most played song right now?")
                    self.user_state[message.author.id]['state'] = State.AWAITING_SONG
                elif state == State.AWAITING_SONG:
                    self.user_profiles[message.author.id]['song'] = message.content
                    await message.author.send("What upcoming music events are you attending?")
                    self.user_state[message.author.id]['state'] = State.AWAITING_EVENTS
                elif state == State.AWAITING_EVENTS:
                    self.user_profiles[message.author.id]['events'] = message.content
                    profile = self.user_profiles[message.author.id]
                    reply = "Your music profile has been updated.\n"
                    reply += f"Name: {profile['name']}\nFavorite Genres: {profile['genres']}\nFavorite Artists: {profile['artists']}\nMost played song right now: {profile['song']}\nUpcoming music events you're attending: {profile['events']}\n\n"
                    await message.author.send(reply)
                    self.user_state[message.author.id] = {'state': None}

        print('message sent to channel:', message.content) 

        response = self.openai_client.moderations.create(input=message.content)
        print('response:', response)
        output = response.results[0]
        print('output:', output)

        if output.flagged:
            await message.delete()
            flagged_categories = [category for category, flagged in output.categories.dict().items() if flagged]
            self.user_state[message.author.id] = {'state': State.MESSAGE_DETAILS, 'data': (message.content, flagged_categories)}

            warning_message = f"Your message \n`{message.content}`\nwas flagged as potentially harmful and has been deleted.\n\n"
            warning_message += "Please remember to adhere to the community guidelines.\n\n\n"
            warning_message += "If you would like to know why your message was deleted, please respond with `learn more`.\n"
            warning_message += "If you believe your message was wrongfully deleted and you would like to dispute it, please respond with `report`.\n"

            if message.author.dm_channel is None:
                await message.author.create_dm()
            await message.author.dm_channel.send(warning_message)
            self.user_state[message.author.id]['state'] = State.MESSAGE_DETAILS

        return None
    
client = ModBot()
client.run(discord_token)