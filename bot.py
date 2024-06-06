import asyncio
from enum import Enum, auto
from config import config
from datetime import datetime, timedelta
import discord
from discord import app_commands
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
from sqlalchemy import create_engine, Column, String, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from database_setup import Base, SpotifyToken, add_playlist_to_db, fetch_all_playlists_from_db, save_music_profile, get_music_profile, add_recommendation, get_recommendations, initialize_database

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
        intents.members = True
        intents.presences = True
        super().__init__(command_prefix='.', intents=intents)
        self.openai_client = openai.OpenAI(api_key=openai_api_key)
        self.user_state = {}  # Store states for bot DM interactions
        self.user_profiles = {}  # Store music profiles
        self.spotify_bot = SpotifyBot(spotify_client_id, spotify_client_secret, spotify_redirect_uri, self.tree, discord_guild, self.user_profiles, self.openai_client)

    async def setup_hook(self):
        await self.spotify_bot.setup_spotify_commands()
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

        daily_tunein_channel = discord.utils.get(self.get_all_channels(), name='daily-tunein')
        if daily_tunein_channel:
            print(f"Found daily tune-in channel: {daily_tunein_channel.id}")
            self.daily_tunein_scheduler = DailyTuneInBot(daily_tunein_channel)
            asyncio.create_task(self.daily_tunein_scheduler.start())
        else:
            print("Daily tune-in channel not found. Make sure the bot is in the correct server and the channel exists.")

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
                    await message.author.send("Who are your favorite artists right now?")
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
                    profile.setdefault('top_songs', [])
                    profile.setdefault('top_artists', [])
                    # Fetch top songs and artists
                    token_info = get_token(message.author.id)
                    if token_info:
                        access_token = await self.spotify_bot.get_fresh_token(token_info, message.author.id)
                        if access_token:
                            top_songs = await self.spotify_bot.get_top_songs(access_token)
                            top_artists = await self.spotify_bot.get_top_artists(access_token)
                            self.user_profiles[message.author.id]['top_songs'] = top_songs  # Store as list
                            self.user_profiles[message.author.id]['top_artists'] = top_artists  # Store as list
                    save_music_profile(message.author.id, profile)
                    
                    profile = self.user_profiles[message.author.id]
                    reply = "Your music profile has been updated.\n"
                    reply += f"**Name:** {profile['name']}\n**Favorite genres:** {profile['genres']}\n**Favorite artists right now:** {profile['artists']}\n**Most played song right now:** {profile['song']}\n**Upcoming music events you're attending:** {profile['events']}\n\n"
                    reply += f"**Top 5 Songs:**\n{'\n'.join(profile['top_songs'])}\n\n"
                    reply += f"**Top 5 Artists:**\n{'\n'.join(profile['top_artists'])}\n"

                    await message.author.send(reply)
                    self.user_state[message.author.id] = {'state': None}

        response = self.openai_client.moderations.create(input=message.content)
        output = response.results[0]

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

    # async def start(self):
    #     while True:
    #         now = datetime.now(pytz.timezone(self.timezone))
    #         print(now)
    #         next_run = now.replace(hour=12, minute=0, second=0, microsecond=0)
    #         print(next_run)
    #         if now >= next_run:
    #             next_run += timedelta(days=1)
    #             print("new next run", next_run)
    #         wait_seconds = (next_run - now).total_seconds()
    #         print(f"Waiting {wait_seconds} seconds until the next message at 12:00 PM {self.timezone}.")
    #         await asyncio.sleep(wait_seconds)

    #         question, options, correct_answer_letter = await self.generate_trivia_prompt()
    #         if question and options and correct_answer_letter and self.channel:
    #             await self.unpin_messages()

    #             message = f"@everyone It's trivia time! 🎉\n`{question}`\n"
    #             message += "\nReact with 🎹 for A\nReact with 🎧 for B\nReact with 🎸 for C\nReact with 🎵 for D."
    #             sent_message = await self.channel.send(message)
    #             emojis = {'A': '🎹', 'B': '🎧', 'C': '🎸', 'D': '🎵'}
    #             for option in options:
    #                 emoji = emojis[option.strip()[0]]
    #                 await sent_message.add_reaction(emoji)

    #             await sent_message.pin()
    #             thread = await sent_message.create_thread(name="Trivia Question Discussion")
    #             await thread.send("Discuss today's trivia question here!")

    #         elif question and options and correct_answer_letter and not self.channel:
    #             print("Channel not found or missing. Check the configuration.\n")
    #         elif self.channel and not question and not options and not correct_answer_letter:
    #             print("Could not generate trivia question.\n.")
    #         else:
    #             print("Other error in start().\n")
    async def start(self):
        while True:
            now = datetime.now(pytz.timezone(self.timezone))
            print(now)
            next_run = now.replace(hour=12, minute=0, second=0, microsecond=0)
            print(next_run)
            
            if now >= next_run:
                next_run += timedelta(days=1)
                print("new next run", next_run)
            
            wait_seconds = (next_run - now).total_seconds()
            print(f"Waiting {wait_seconds} seconds until the next message at 12:00 PM {self.timezone}.")
            await asyncio.sleep(wait_seconds)
            
            # Recalculate `now` and `next_run` after waking up to ensure exact timing
            now = datetime.now(pytz.timezone(self.timezone))
            next_run = now.replace(hour=12, minute=0, second=0, microsecond=0)
        
            if now >= next_run:
                # Proceed with sending the message only if it's exactly 12:00 PM
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



# class DailyTuneInBot:
#     def __init__(self, channel, timezone='US/Pacific'):
#         self.channel = channel
#         self.timezone = timezone

#     async def start(self):
#         while True:
#             now = datetime.now(pytz.timezone(self.timezone))
#             next_run = now.replace(hour=17, minute=0, second=0, microsecond=0)
#             if now >= next_run:
#                 next_run += timedelta(days=1)
#             wait_seconds = (next_run - now).total_seconds()
#             print(f"Waiting {wait_seconds} seconds until the next message at 5:00 PM {self.timezone}.")
#             await asyncio.sleep(wait_seconds)

#             if self.channel:
#                 await self.channel.send("@everyone It's daily tune-in time! 🎶\n")
#                 await self.channel.send("Use `/authenticate` to re-authenticate with Spotify.")
#                 await self.channel.send("Then use `/currently_playing` to share your currently playing song!")
#             else:
#                 print("Daily tune-in channel not found. Check the configuration.\n")
class DailyTuneInBot:
    def __init__(self, channel, timezone='US/Pacific'):
        self.channel = channel
        self.timezone = timezone

    async def start(self):
        while True:
            now = datetime.now(pytz.timezone(self.timezone))
            next_run = now.replace(hour=17, minute=0, second=0, microsecond=0)
            if now >= next_run:
                next_run += timedelta(days=1)
            wait_seconds = (next_run - now).total_seconds()
            print(f"Waiting {wait_seconds} seconds until the next message at 5:00 PM {self.timezone}.")
            await asyncio.sleep(wait_seconds)

            # Recalculate `now` and `next_run` after waking up to ensure exact timing
            now = datetime.now(pytz.timezone(self.timezone))
            next_run = now.replace(hour=17, minute=0, second=0, microsecond=0)

            if now >= next_run:
                # Proceed with sending the message only if it's exactly 5:00 PM
                if self.channel:
                    await self.channel.send("@everyone It's daily tune-in time! 🎶\n")
                    await self.channel.send("Use `/authenticate` to re-authenticate with Spotify.")
                    await self.channel.send("Then use `/currently_playing` to share your currently playing song!")
                else:
                    print("Daily tune-in channel not found. Check the configuration.\n")



class SpotifyBot:
    def __init__(self, client_id, client_secret, redirect_uri, tree, guild_id, user_profiles, openai_client):
        self.sp_oauth = SpotifyOAuth(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri, 
                                     scope="user-read-private user-read-email user-read-playback-state user-top-read playlist-read-private playlist-read-collaborative playlist-modify-public playlist-modify-private")
        self.tree = tree
        self.guild = discord.Object(id=guild_id)
        self.user_profiles = user_profiles
        self.openai_client = openai_client

    
    async def setup_spotify_commands(self):
        @self.tree.command(name='authenticate', description='Authenticate with Spotify', guild=self.guild)
        async def authenticate_spotify(interaction: discord.Interaction):
            user_id = str(interaction.user.id)
            # auth_url = f"http://localhost:8888/login?user_id={user_id}"
            auth_url = f"https://5c04-128-12-123-206.ngrok-free.app/login?user_id={user_id}"
            await interaction.response.send_message(f"Please authenticate using this URL: {auth_url}", ephemeral=True)

        @self.tree.command(name='spotify_profile', description='Share your Spotify profile', guild=self.guild)
        async def spotify_profile(interaction: discord.Interaction):
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

        @self.tree.command(name='music_profile', description='Share your music profile with others', guild=self.guild)
        async def music_profile(interaction: discord.Interaction):
            user_id = interaction.user.id
            profile = get_music_profile(user_id)
            if profile:
                reply = f"**Music Profile for {interaction.user.display_name}:**\n"
                reply += f"**Preferred Name:** {profile.name}\n"
                reply += f"**Favorite Genres:** {profile.genres}\n"
                reply += f"**Favorite Artists:** {profile.artists}\n"
                reply += f"**Most played song right now:** {profile.song}\n"
                reply += f"**Upcoming music events they're attending:** {profile.events}\n"
                reply += "**Top 5 Songs:**\n" + "\n".join(profile.top_songs) + "\n"
                reply += "**Top 5 Artists:**\n" + "\n".join(profile.top_artists)
                await interaction.response.send_message(reply)
            else:
                await interaction.response.send_message('You do not have a music profile yet. Create one by DM\'ing the bot `music`.', ephemeral=True)

        @self.tree.command(name='currently_playing', description='Share your currently playing song on Spotify', guild=self.guild)
        async def playing(interaction: discord.Interaction):
            user_id = str(interaction.user.id)
            track_info = await self.fetch_currently_playing(user_id)
            
            if track_info:
                embed = discord.Embed(
                    title=f"Now playing: {track_info['track_name']}",
                    description=f"Artist: {track_info['artist_name']}",
                    color=discord.Color.blue()
                )
                if track_info['album_cover_url']:
                    embed.set_thumbnail(url=track_info['album_cover_url'])
                
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message('No track currently playing.')

        @self.tree.command(name='listening', description="Find who's listening to what on the server", guild=self.guild)
        async def listening(interaction: discord.Interaction):
            members = interaction.guild.members
            listening_info = []
            for member in members:
                user_id = str(member.id)
                track_info = await self.fetch_currently_playing(user_id)
                if track_info:
                    listening_info.append({
                        "member_name": member.display_name,
                        "track_name": track_info['track_name'],
                        "artist_name": track_info['artist_name'],
                        "album_cover_url": track_info['album_cover_url'],
                        "track_url": track_info['track_url']
                    })

            if listening_info:
                embed = discord.Embed(title="Currently Listening To", color=discord.Color.blue())
                for info in listening_info:
                    embed.add_field(
                        name=f"{info['member_name']} is listening to:",
                        value=f"[{info['track_name']} by {info['artist_name']}]({info['track_url']})",
                        inline=False
                    )
                    if info['album_cover_url']:
                        embed.set_thumbnail(url=info['album_cover_url'])

                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("No one is currently listening to anything on Spotify or they haven't authenticated.", ephemeral=True)

        @self.tree.command(name='recommend', description='Recommend a song, album, or artist to the channel', guild=self.guild)
        @app_commands.describe(search_type="Type of search: song, album, artist", query="Title of song, album, or artist name")
        async def search(interaction: discord.Interaction, query: str, search_type: str):
            user_id = str(interaction.user.id)
            token_info = get_token(user_id)  # Retrieve the token from the database
            access_token = await self.get_fresh_token(token_info, user_id)
            if not access_token:
                await interaction.response.send_message("Please authenticate with Spotify first using /authenticate_spotify.", ephemeral=True)
                return
            
            sp = spotipy.Spotify(auth=access_token)
            results = sp.search(q=query, type=search_type, limit=1)
            embed = discord.Embed(title=f"Search results for '{query}'", color=discord.Color.blue())
            
            if results:
                if search_type == 'track' and results['tracks']['items']:
                    track = results['tracks']['items'][0]
                    track_name = track['name']
                    artist_name = track['artists'][0]['name']
                    album_name = track['album']['name']
                    album_image = track['album']['images'][0]['url'] if track['album']['images'] else None
                    embed.add_field(name="Top track result", value=f"**Track:** {track_name}\n**Artist:** {artist_name}\n**Album:** {album_name}", inline=False)
                    if album_image:
                        embed.set_thumbnail(url=album_image)

                elif search_type == 'album' and results['albums']['items']:
                    album = results['albums']['items'][0]
                    album_name = album['name']
                    artist_name = album['artists'][0]['name']
                    album_image = album['images'][0]['url'] if album['images'] else None
                    embed.add_field(name="Top album result", value=f"**Album:** {album_name}\n**Artist:** {artist_name}", inline=False)
                    if album_image:
                        embed.set_thumbnail(url=album_image)

                elif search_type == 'artist' and results['artists']['items']:
                    artist = results['artists']['items'][0]
                    artist_name = artist['name']
                    artist_image = artist['images'][0]['url'] if artist['images'] else None
                    embed.add_field(name="Top artist result", value=f"**Artist:** {artist_name}", inline=False)
                    if artist_image:
                        embed.set_thumbnail(url=artist_image)

                else:
                    embed.add_field(name="No results found", value=f"No results found for {search_type}.", inline=False)
            else:
                embed.add_field(name="No results found", value="No results found.", inline=False)

            await interaction.response.send_message(embed=embed)

        # @self.tree.command(name='discover', description='Discover new music with AI recommendations', guild=self.guild)
        # @app_commands.describe(search_type="Type of search: Song, Album, Artist, Random")
        # async def discover_music(interaction: discord.Interaction, search_type: str):
        #     user_id = interaction.user.id
        #     profile_info = get_music_profile(user_id)
        #     print("Profile Info", profile_info.top_songs)
        #     recommendation_info = []

        #     # Defer the interaction response to get more time
        #     await interaction.response.defer()

        #     if search_type.lower() == "random":
        #         try:
        #             response = self.openai_client.chat.completions.create(
        #                 model="gpt-4",
        #                 messages=[
        #                     {"role": "system", "content": "You are a music recommendation algorithm. Your task is to recommend a random song from any genre. Do not limit your recommendation to a single genre."},
        #                     {"role": "user", "content": "Recommend a song from any genre, culture, country, decade, time period, etc. Do not limit yourself to a single genre of songs. Please include musical diversity, but do not repeat recommended songs."},
        #                     {"role": "user", "content": "Please recommend a random song. It can be from any genre and any decade. I don't want the possibility of a repeated song. I want all different recommendations. Do not include Bohemian Rapsody."}
        #                 ])
        #             print("Test response:", response.choices[0].message.content)
        #             if response.choices:
        #                 await interaction.followup.send(f"AI Recommendations:\n{response.choices[0].message.content}")
        #             else:
        #                 print("No valid response received from OpenAI.")
        #                 await interaction.followup.send("Failed to generate recommendations. Please try again later.")
        #         except Exception as e:
        #             print(f"Failed to generate trivia prompt: {e}")
        #             await interaction.followup.send(f"Error occurred: {e}")
        #         return

        #     elif search_type.lower() == "song":
        #         recommendation_info = profile_info.top_songs
        #         try:
        #             response = self.openai_client.chat.completions.create(
        #                 model="gpt-4",
        #                 messages=[
        #                     {"role": "system", "content": f'Recommend a song that is similar with the given songs in this information: {recommendation_info}'},
        #                     {"role": "user", "content": "Recommend a single song based on the information given."}
        #                 ])
        #             print("Test response:", response.choices[0].message.content)
        #             if response.choices:
        #                 await interaction.followup.send(f"AI Recommendations:\n{response.choices[0].message.content}")
        #             else:
        #                 print("No valid response received from OpenAI.")
        #                 await interaction.followup.send("Failed to generate recommendations. Please try again later.")
        #         except Exception as e:
        #             print(f"Failed to generate trivia prompt: {e}")
        #             await interaction.followup.send(f"Error occurred: {e}")
        #         return
        #     elif search_type.lower() == "artist":
        #         recommendation_info = profile_info.top_artists
        #         try:
        #             response = self.openai_client.chat.completions.create(
        #                 model="gpt-4",
        #                 messages=[
        #                     {"role": "system", "content": f'Recommend an artist that produces similar music to any one of these songs: {recommendation_info}'},
        #                     {"role": "user", "content": "Recommend an artist based on the information given."}
        #                 ])
        #             print("Test response:", response.choices[0].message.content)
        #             if response.choices:
        #                 await interaction.followup.send(f"AI Recommendations:\n{response.choices[0].message.content}")
        #             else:
        #                 print("No valid response received from OpenAI.")
        #                 await interaction.followup.send("Failed to generate recommendations. Please try again later.")
        #         except Exception as e:
        #             print(f"Failed to generate trivia prompt: {e}")
        #             await interaction.followup.send(f"Error occurred: {e}")
        #         return
        #     elif search_type.lower() == "album":
        #         recommendation_info = profile_info.top_songs  # Placeholder, should be updated with albums
        #         try:
        #             response = self.openai_client.chat.completions.create(
        #                 model="gpt-4",
        #                 messages=[
        #                     {"role": "system", "content": f'Analyze the albums that these songs come from in the information, recommend an album siimlar to the the albums these songs come from: {recommendation_info}'},
        #                     {"role": "user", "content": "Recommend an album based on the information given."}
        #                 ])
        #             print("Test response:", response.choices[0].message.content)
        #             if response.choices:
        #                 await interaction.followup.send(f"AI Recommendations:\n{response.choices[0].message.content}")
        #             else:
        #                 print("No valid response received from OpenAI.")
        #                 await interaction.followup.send("Failed to generate recommendations. Please try again later.")
        #         except Exception as e:
        #             print(f"Failed to generate trivia prompt: {e}")
        #             await interaction.followup.send(f"Error occurred: {e}")
        #         return

        @self.tree.command(name='discover', description='Discover new music with AI recommendations', guild=self.guild)
        @app_commands.describe(search_type="Type of search: Song, Album, Artist, Random")
        async def discover_music(interaction: discord.Interaction, search_type: str):
            user_id = str(interaction.user.id)
            profile_info = get_music_profile(user_id)
            
            if not profile_info:
                await interaction.response.send_message("You do not have a music profile yet. Create one by DM'ing the bot `music`.", ephemeral=True)
                return

            # Defer the interaction response to get more time
            await interaction.response.defer()

            previous_recommendations = get_recommendations(user_id, search_type.lower())
            print('previous recommendations:', previous_recommendations)
            recommendation_info = profile_info.top_songs if search_type.lower() == "song" else profile_info.top_artists

            if search_type.lower() == "random":
                try:
                    response = self.openai_client.chat.completions.create(
                        model="gpt-4",
                        messages=[
                            {"role": "system", "content": "You are a music recommendation algorithm. Your task is to recommend a random song from any genre. Do not limit your recommendation to a single genre."},
                            {"role": "user", "content": "Recommend a song from any genre, culture, country, decade, time period, etc. Do not limit yourself to a single genre of songs. Please include musical diversity, but do not repeat recommended songs."},
                            {"role": "user", "content": f"Do not recommend any songs already recommended, including: {previous_recommendations}. Please recommend a random song. It can be from any genre and any decade. I want all different recommendation. Again, do not repeat recommended songs."}
                        ])
                    if response.choices:
                        new_recommendation = response.choices[0].message.content.strip()
                        print('recommendation added to table:', new_recommendation)
                        await interaction.followup.send(f"AI Recommendations:\n{new_recommendation}")
                        add_recommendation(user_id, 'random', new_recommendation)
                    else:
                        await interaction.followup.send("Failed to generate recommendations. Please try again later.", ephemeral=True)
                except Exception as e:
                    await interaction.followup.send(f"Error occurred: {e}", ephemeral=True)
                return

            if search_type.lower() == "song":
                recommendation_info = profile_info.top_songs
            elif search_type.lower() == "artist":
                recommendation_info = profile_info.top_artists
            elif search_type.lower() == "album":
                recommendation_info = profile_info.top_songs  # Placeholder, should be updated with albums

            try:
                response = self.openai_client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": f'Recommend a {search_type.lower()} that is similar to the given {search_type.lower()}s in this information: {recommendation_info}'},
                        {"role": "user", "content": f"Recommend a {search_type.lower()} based on the information given. Do not repeat these recommendations: {previous_recommendations}"}
                    ])
                if response.choices:
                    new_recommendation = response.choices[0].message.content.strip()
                    await interaction.followup.send(f"AI Recommendations:\n{new_recommendation}")
                    add_recommendation(user_id, search_type.lower(), new_recommendation)
                    print('recommendation added to table:', new_recommendation)
                else:
                    await interaction.followup.send("Failed to generate recommendations. Please try again later.")
            except Exception as e:
                await interaction.followup.send(f"Error occurred: {e}")



        @self.tree.command(name='share_playlist', description="Share one of your Spotify playlists", guild=self.guild)
        @app_commands.describe(playlist_name="The name of the playlist you want to share")
        async def share_playlist(interaction: discord.Interaction, playlist_name: str):
            user_id = str(interaction.user.id)
            token_info = get_token(user_id)  # Retrieve the token from the database
            access_token = await self.get_fresh_token(token_info, user_id)
            if not access_token:
                await interaction.response.send_message("Please authenticate with Spotify first using /authenticate_spotify.", ephemeral=True)
                return

            sp = spotipy.Spotify(auth=access_token)
            try:
                playlist = await self.find_playlist_by_name(sp, playlist_name)
                if playlist:
                    playlist_name = playlist['name']
                    playlist_description = playlist['description']
                    playlist_owner = playlist['owner']['display_name']
                    playlist_image = playlist['images'][0]['url'] if playlist['images'] else None
                    playlist_url = playlist['external_urls']['spotify']

                    embed = discord.Embed(
                        title=f"Playlist: {playlist_name}",
                        description=f"Description: {playlist_description}\nOwner: {playlist_owner}",
                        url=playlist_url,
                        color=discord.Color.blue()
                    )
                    if playlist_image:
                        embed.set_thumbnail(url=playlist_image)

                    await interaction.response.send_message(embed=embed)
                else:
                    await interaction.response.send_message(f"No playlist named '{playlist_name}' found for user {user_id}.", ephemeral=True)
            except spotipy.exceptions.SpotifyException as e:
                await interaction.response.send_message(f"Failed to retrieve playlist details: {e}", ephemeral=True)

        @self.tree.command(name='playlist_create', description="Create a collaborative playlist for the server", guild=self.guild)
        @app_commands.describe(name="The name of the playlist", description="The description of the playlist")
        async def playlist_create(interaction: discord.Interaction, name: str, description: str):
            user_id = str(interaction.user.id)
            token_info = get_token(user_id)  # Retrieve the token from the database
            access_token = await self.get_fresh_token(token_info, user_id)
            if not access_token:
                await interaction.response.send_message("Please authenticate with Spotify first using /authenticate_spotify.", ephemeral=True)
                return

            sp = spotipy.Spotify(auth=access_token)
            user_profile = sp.current_user()
            try:
                playlist = sp.user_playlist_create(
                    user=user_profile['id'],
                    name=name,
                    public=False,  # To create a collaborative playlist, public must be False
                    description=description
                )
                playlist_id = playlist['id']
                # Set the playlist to be collaborative
                sp.playlist_change_details(playlist_id=playlist_id, collaborative=True)
                
                # Add playlist to the database
                playlist_url = playlist['external_urls']['spotify']
                add_playlist_to_db(playlist_id, name, description, playlist_url, user_id)
                await interaction.response.send_message(f"Collaborative playlist created: [Playlist Link]({playlist_url})")
            except spotipy.exceptions.SpotifyException as e:
                await interaction.response.send_message(f"Failed to create playlist: {e}", ephemeral=True)

        @self.tree.command(name='playlist_add', description="Add a song to a collaborative playlist", guild=self.guild)
        @app_commands.describe(playlist_name="The name of the playlist", track_id="The ID of the track to add")
        async def playlist_add(interaction: discord.Interaction, playlist_name: str, track_id: str):
            user_id = str(interaction.user.id)
            token_info = get_token(user_id)  # Retrieve the token from the database
            access_token = await self.get_fresh_token(token_info, user_id)
            if not access_token:
                await interaction.response.send_message("Please authenticate with Spotify first using /authenticate_spotify.", ephemeral=True)
                return

            sp = spotipy.Spotify(auth=access_token)
            
            # Search for the playlist by name
            playlists = fetch_all_playlists_from_db()
            playlist_id = None
            for playlist in playlists:
                if playlist.name.lower() == playlist_name.lower():
                    playlist_id = playlist.playlist_id  # Ensure this is treated as a string
                    break

            if not playlist_id:
                await interaction.response.send_message(f"Playlist '{playlist_name}' not found.", ephemeral=True)
                return

            # Retrieve the track details using the track ID
            try:
                track = sp.track(track_id)
                track_name = track['name']
                track_artists = ', '.join([artist['name'] for artist in track['artists']])
                album_name = track['album']['name']
                album_cover_url = track['album']['images'][0]['url'] if track['album']['images'] else None
                track_url = track['external_urls']['spotify']
            except spotipy.exceptions.SpotifyException as e:
                await interaction.response.send_message(f"Failed to retrieve track details: {e}", ephemeral=True)
                return

            # Add the track to the playlist
            try:
                sp.playlist_add_items(playlist_id=playlist_id, items=[track_id])
                
                # Create embed
                embed = discord.Embed(
                    title=f"'{track_name}' by {track_artists}",
                    description=f"Album: {album_name}",
                    url=track_url,
                    color=discord.Color.green()
                )
                if album_cover_url:
                    embed.set_thumbnail(url=album_cover_url)

                await interaction.response.send_message(f"'{track_name}' by {track_artists} added to playlist '{playlist_name}'.", embed=embed)
            except spotipy.exceptions.SpotifyException as e:
                await interaction.response.send_message(f"Failed to add track: {e}", ephemeral=True)

        @self.tree.command(name='playlists', description="Show a list of collaborative playlists", guild=self.guild)
        async def playlists(interaction: discord.Interaction):
            user_id = str(interaction.user.id)
            token_info = get_token(user_id)  # Retrieve the token from the database
            access_token = await self.get_fresh_token(token_info, user_id)
            if not access_token:
                await interaction.response.send_message("Please authenticate with Spotify first using /authenticate_spotify.", ephemeral=True)
                return

            playlists = fetch_all_playlists_from_db()
            embed = discord.Embed(title="Collaborative Playlists", color=discord.Color.purple())

            for playlist in playlists:
                embed.add_field(name=playlist.name, value=f"[Link]({playlist.playlist_url})", inline=False)

            await interaction.response.send_message(embed=embed)

    async def fetch_currently_playing(self, user_id: str):
        token_info = get_token(user_id)  # Retrieve the token from the database
        if token_info:
            access_token = await self.get_fresh_token(token_info, user_id)
            if access_token:
                sp = spotipy.Spotify(auth=access_token)
                try:
                    current_track = sp.current_user_playing_track()
                    if current_track and current_track['item']:
                        track = current_track['item']
                        track_name = track['name']
                        artist_name = track['artists'][0]['name']
                        album_cover_url = track['album']['images'][0]['url'] if track['album']['images'] else None
                        track_url = track['external_urls']['spotify']
                        return {
                            "track_name": track_name,
                            "artist_name": artist_name,
                            "album_cover_url": album_cover_url,
                            "track_url": track_url
                        }
                except spotipy.exceptions.SpotifyException as e:
                    logging.error(f"Spotify API error for user {user_id}: {e}")
        return None

    async def find_playlist_by_name(self, sp, playlist_name: str):
            playlists = sp.current_user_playlists(limit=50)
            for playlist in playlists['items']:
                if playlist['name'].lower() == playlist_name.lower():
                    return playlist
            return None

    async def get_top_songs(self, access_token):
        sp = spotipy.Spotify(auth=access_token)
        top_tracks = sp.current_user_top_tracks(limit=5)
        return [f"{track['name']} by {track['artists'][0]['name']}" for track in top_tracks['items']]

    async def get_top_artists(self, access_token):
        sp = spotipy.Spotify(auth=access_token)
        top_artists = sp.current_user_top_artists(limit=5)
        return [artist['name'] for artist in top_artists['items']]

    # async def get_fresh_token(self, token_info, user_id):
    #         if token_info and (token_info.expires_at - int(time.time()) < 60):
    #             # Token needs refreshing
    #             refresh_url = f"https://5c04-128-12-123-206.ngrok-free.app/refresh_token?refresh_token={token_info.refresh_token}"
    #             response = requests.get(refresh_url)
    #             if response.status_code == 200:
    #                 refreshed_token_info = response.json()
    #                 if 'expires_in' in refreshed_token_info:
    #                     refreshed_token_info['expires_at'] = int(time.time()) + refreshed_token_info['expires_in']
    #                     save_token(user_id, refreshed_token_info)  # Save the refreshed token to the database
    #                     return refreshed_token_info['access_token']
    #                 else:
    #                     logging.error(f"Response did not contain 'expires_in': {refreshed_token_info}")
    #                     return None
    #             else:
    #                 logging.error(f"Failed to refresh token: {response.status_code} {response.text}")
    #                 return None
    #         return token_info.access_token if token_info else None

    async def get_fresh_token(self, token_info, user_id):
        if token_info and (token_info.expires_at - int(time.time()) < 60):
            # Token needs refreshing
            refresh_url = f"https://5c04-128-12-123-206.ngrok-free.app/refresh_token?refresh_token={token_info.refresh_token}"
            response = requests.get(refresh_url)
            if response.status_code == 200:
                refreshed_token_info = response.json()
                if 'expires_in' in refreshed_token_info:
                    refreshed_token_info['expires_at'] = int(time.time()) + refreshed_token_info['expires_in']
                else:
                    logging.error(f"Response did not contain 'expires_in': {refreshed_token_info}")
                    # Set a default expires_at if 'expires_in' is missing (assuming 1 hour lifespan)
                    refreshed_token_info['expires_at'] = int(time.time()) + 3600
                
                # Ensure token_type is included
                if 'token_type' not in refreshed_token_info:
                    refreshed_token_info['token_type'] = 'Bearer'

                save_token(user_id, refreshed_token_info)  # Save the refreshed token to the database
                return refreshed_token_info['access_token']
            else:
                logging.error(f"Failed to refresh token: {response.status_code} {response.text}")
                return None
        return token_info.access_token if token_info else None



client = ModBot()
client.run(discord_token)