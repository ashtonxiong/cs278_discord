import asyncio
from enum import Enum, auto
from config import config
from datetime import datetime, timedelta
import discord
from discord.ext import commands
from flash_server import get_token, save_token
import json
import logging
import openai
from openai import OpenAI
import os
import pytz
import requests
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth
import time

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
    MOD_START = auto()
    AWAITING_MORE = auto()

class ModBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='.', intents=intents)
        self.openai_client = openai.OpenAI(api_key=openai_api_key)
        self.user_state = {}
        self.spotify_bot = SpotifyBot(spotify_client_id, spotify_client_secret, spotify_redirect_uri)

    async def setup_hook(self):
        self.tree.copy_global_to(guild=discord.Object(id=discord_guild))  
        await self.tree.sync(guild=discord.Object(id=discord_guild))  

    async def on_ready(self):
        print(f'{self.user.name} has connected to Discord! It is these guilds:')
        for guild in self.guilds:
            print(f' - {guild.name}')
        print('Press Ctrl-C to quit.')

        trivia_channel = discord.utils.get(self.get_all_channels(), name='trivia')
        if trivia_channel:
            print(f"Found trivia channel: {trivia_channel.id}")
            self.scheduler = TriviaBot(trivia_channel, self.openai_client)
            asyncio.create_task(self.scheduler.start())
        else:
            print("Trivia channel not found. Make sure the bot is in the correct server and the channel exists.")

        await self.spotify_bot.setup_spotify_commands(self)

    async def on_message(self, message):
        if message.author == self.user:
            return

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
                    self.user_state[message.author]['state'] = State.MOD_START
            return

        response = self.openai_client.moderations.create(input=message.content)
        output = response.results[0]

        if output.flagged:
            await message.delete()
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

class TriviaBot:
    def __init__(self, channel, openai_client, timezone='US/Pacific'):
        self.channel = channel
        self.timezone = timezone
        self.openai_client = openai_client

    async def generate_trivia_prompt(self):
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a music trivia bot, skilled in generating interesting musical trivia questions with diverse musical interests. Format the trivia question followed by four possible answers and indicate the correct answer at the end as 'Correct: A'."},
                    {"role": "user", "content": "Generate a trivia question with four possible answers, indicating which one is correct."}
                ])
            if response.choices and response.choices[0].message:
                trivia_data = response.choices[0].message.content.strip()
                if 'Correct:' not in trivia_data:
                    print("Unexpected format received:", trivia_data)
                    return None, None, None

                question_part, answer_part = trivia_data.split('Correct:')
                question = question_part.strip()
                correct_answer = answer_part.strip()
                options = question.split('\n')[-4:]
                correct_answer_letter = correct_answer[0]
                return question, options, correct_answer_letter
            else:
                raise ValueError("No valid response received from OpenAI.")
        except Exception as e:
            print(f"Failed to generate trivia prompt.")
            return None, None, None

    async def unpin_messages(self):
        pins = await self.channel.pins()
        if pins:
            for pin in pins:
                await pin.unpin()
            print("All previous pins unpinned.")
        else:
            return None

    async def start(self):
        while True:
            now = datetime.now(pytz.timezone(self.timezone))
            next_run = now.replace(hour=12, minute=0, second=0, microsecond=0)
            if now >= next_run:
                next_run += timedelta(days=1)
            wait_seconds = (next_run - now).total_seconds()
            print(f"Waiting {wait_seconds} seconds until the next message at 12:00 PM {self.timezone}.")
            await asyncio.sleep(wait_seconds)

            question, options, correct_answer_letter = await self.generate_trivia_prompt()
            if question and options and correct_answer_letter and self.channel:
                await self.unpin_messages()

                message = f"@everyone It's trivia time! 🎉\n`{question}`\n"
                message += "\nReact with 🎹 for A\nReact with 🎧 for B\nReact with 🎸 for C\nReact with 🎵 for D."
                sent_message = await self.channel.send(message)
                emojis = {'A': '🎹', 'B': '🎧', 'C': '🎸', 'D': '🎵'}
                for option in options:
                    emoji = emojis[option.strip()[0]]
                    await sent_message.add_reaction(emoji)

                await sent_message.pin()
                thread = await sent_message.create_thread(name="Trivia Question Discussion")
                await thread.send("Discuss today's trivia question here!")

            elif question and options and correct_answer_letter and not self.channel:
                print("Channel not found or missing. Check the configuration.\n")
            elif self.channel and not question and not options and not correct_answer_letter:
                print("Could not generate trivia question.\n.")
            else:
                print("Other error in start().\n")

class SpotifyBot:
    def __init__(self, client_id, client_secret, redirect_uri):
        self.sp_oauth = SpotifyOAuth(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri, scope="user-read-playback-state user-read-email")
    
    async def setup_spotify_commands(self, bot):
        @bot.tree.command(name='authenticate_spotify', description='Authenticate with Spotify')
        async def authenticate_spotify(interaction: discord.Interaction):
            user_id = str(interaction.user.id)
            auth_url = f"http://localhost:8888/login?user_id={user_id}"
            # auth_url = f"https://885e-128-12-122-208.ngrok-free.app/login?user_id={user_id}"
            await interaction.response.send_message(f"Please authenticate using this URL: {auth_url}", ephemeral=True)

        @bot.tree.command(name='callback', description='Handle Spotify callback with code')
        async def callback(interaction: discord.Interaction, code: str, state: str):
            user_id = state
            token_info = self.sp_oauth.get_access_token(code)
            if 'refresh_token' in token_info:
                token_info['expires_at'] = int(time.time()) + token_info['expires_in']
                save_token(user_id, token_info)  # Save the token to the database
                await interaction.response.send_message("Authentication successful! You can now use Spotify commands.", ephemeral=True)
            else:
                await interaction.response.send_message("Failed to receive all necessary token information from Spotify.", ephemeral=True)

        @bot.tree.command(name='playing', description='Get the currently playing song on Spotify')
        async def playing(interaction: discord.Interaction):
            user_id = str(interaction.user.id)
            token_info = get_token(user_id)  # Retrieve the token from the database
            access_token = await self.get_fresh_token(token_info, user_id)
            if not access_token:
                await interaction.response.send_message("Please authenticate with Spotify first using /authenticate_spotify.", ephemeral=True)
                return
            
            sp = spotipy.Spotify(auth=access_token)
            current_track = sp.current_user_playing_track()
            if current_track and current_track['item']:
                track_name = current_track['item']['name']
                artist_name = current_track['item']['artists'][0]['name']
                album_cover_url = current_track['item']['album']['images'][0]['url']  # Get the album cover image URL
                
                embed = discord.Embed(
                    title=f"Now playing: {track_name}",
                    description=f"Artist: {artist_name}",
                    color=discord.Color.blue()
                )
                embed.set_image(url=album_cover_url)
                
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message('No track currently playing.')

        @bot.tree.command(name='spotifyprofile', description='Get your Spotify profile')
        async def spotifyprofile(interaction: discord.Interaction):
            user_id = str(interaction.user.id)
            token_info = get_token(user_id)  # Retrieve the token from the database
            access_token = await self.get_fresh_token(token_info, user_id)
            if not access_token:
                await interaction.response.send_message("Please authenticate with Spotify first using /authenticate_spotify.", ephemeral=True)
                return
            
            headers = {
                'Authorization': f'Bearer {access_token}'
            }
            response = requests.get('https://api.spotify.com/v1/me', headers=headers)
            if response.status_code == 200:
                profile_data = response.json()
                display_name = profile_data.get('display_name', 'N/A')
                email = profile_data.get('email', 'N/A')
                profile_url = profile_data.get('external_urls', {}).get('spotify', 'N/A')
                profile_image_url = profile_data.get('images', [{}])[0].get('url', '')

                embed = discord.Embed(
                    title=f"Spotify Profile: {display_name}",
                    description=f"[Profile URL]({profile_url})\nEmail: {email}",
                    color=discord.Color.green()
                )
                if profile_image_url:
                    embed.set_thumbnail(url=profile_image_url)
                
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message('Failed to retrieve Spotify profile.')
            
        @bot.tree.command(name='listening', description='Find who\'s listening to what on the server')
        async def listening(interaction: discord.Interaction):
            await interaction.response.send_message('This functionality is under development.')

        logger.debug('Synchronizing commands with Discord')
        await bot.tree.sync(guild=discord.Object(id=discord_guild))

    async def get_fresh_token(self, token_info, user_id):
        if token_info and (token_info['expires_at'] - int(time.time()) < 60):
            # Token needs refreshing
            refresh_url = f"http://localhost:8888/refresh_token?refresh_token={token_info['refresh_token']}"
            # refresh_url = f"https://885e-128-12-122-208.ngrok-free.app/refresh_token?refresh_token={token_info['refresh_token']}"
            response = requests.get(refresh_url)
            if response.status_code == 200:
                refreshed_token_info = response.json()
                refreshed_token_info['expires_at'] = int(time.time()) + self.sp_oauth.expires_in
                save_token(user_id, refreshed_token_info)  # Save the refreshed token to the database
                return refreshed_token_info['access_token']
            else:
                return None
        return token_info.get('access_token') if token_info else None

client = ModBot()
client.run(discord_token)