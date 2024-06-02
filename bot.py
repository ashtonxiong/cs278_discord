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
from database_setup import Base, SpotifyToken, Playlist, add_playlist_to_db, fetch_playlists_from_db

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
        self.spotify_bot = SpotifyBot(spotify_client_id, spotify_client_secret, spotify_redirect_uri, self.tree, discord_guild, self.user_profiles)

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
                    # Fetch top songs and artists
                    token_info = get_token(message.author.id)
                    if token_info:
                        access_token = await self.spotify_bot.get_fresh_token(token_info, message.author.id)
                        if access_token:
                            top_songs = await self.spotify_bot.get_top_songs(access_token)
                            top_artists = await self.spotify_bot.get_top_artists(access_token)
                            self.user_profiles[message.author.id]['top_songs'] = '\n'.join(top_songs)
                            self.user_profiles[message.author.id]['top_artists'] = '\n'.join(top_artists)
                    
                    profile = self.user_profiles[message.author.id]
                    reply = "Your music profile has been updated.\n"
                    reply += f"**Name:** {profile['name']}\n**Favorite genres:** {profile['genres']}\n**Favorite artists right now:** {profile['artists']}\n**Most played song right now:** {profile['song']}\n**Upcoming music events you're attending:** {profile['events']}\n\n"
                    reply += f"**Top 5 Songs:**\n{profile['top_songs']}\n\n"
                    reply += f"**Top 5 Artists:**\n{profile['top_artists']}\n"

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
    def __init__(self, client_id, client_secret, redirect_uri, tree, guild_id, user_profiles):
        self.sp_oauth = SpotifyOAuth(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri, 
                                     scope="user-read-private user-read-email user-read-playback-state user-top-read playlist-modify-public playlist-modify-private")
        self.tree = tree
        self.guild = discord.Object(id=guild_id)
        self.user_profiles = user_profiles
    
    async def setup_spotify_commands(self):
        @self.tree.command(name='authenticate_spotify2', description='Authenticate with Spotify', guild=self.guild)
        async def authenticate_spotify(interaction: discord.Interaction):
            user_id = str(interaction.user.id)
            auth_url = f"http://localhost:8888/login?user_id={user_id}"
            await interaction.response.send_message(f"Please authenticate using this URL: {auth_url}", ephemeral=True)

        @self.tree.command(name='spotifyprofile', description='Share your Spotify profile', guild=self.guild)
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

        @self.tree.command(name='music_profile', description='Share your music profile with others', guild=self.guild)
        async def music_profile(interaction: discord.Interaction):
            user_id = interaction.user.id
            profile = self.user_profiles.get(user_id)
            if profile:
                reply = f"**Music Profile for {interaction.user.display_name}:**\n"
                reply += f"**Preferred Name:** {profile['name']}\n"
                reply += f"**Favorite Genres:** {profile['genres']}\n"
                reply += f"**Favorite Artists:** {profile['artists']}\n"
                reply += f"**Most played song right now:** {profile['song']}\n"
                reply += f"**Upcoming music events they're attending:** {profile['events']}\n"
                reply += f"**Top 5 Songs:**\n{profile['top_songs']}\n"
                reply += f"**Top 5 Artists:**\n{profile['top_artists']}\n"
                await interaction.response.send_message(reply)
            else:
                await interaction.response.send_message('You do not have a music profile yet. Create one by DM\'ing the bot `music`.')

        # @self.tree.command(name='callback', description='Handle Spotify callback with code', guild=self.guild)
        # async def callback(interaction: discord.Interaction, code: str, state: str):
        #     user_id = state
        #     token_info = self.sp_oauth.get_access_token(code)
        #     if 'refresh_token' in token_info:
        #         token_info['expires_at'] = int(time.time()) + token_info['expires_in']
        #         save_token(user_id, token_info)  # Save the token to the database
        #         await interaction.response.send_message("Authentication successful! You can now use Spotify commands.", ephemeral=True)
        #     else:
        #         await interaction.response.send_message("Failed to receive all necessary token information from Spotify.", ephemeral=True)

        @self.tree.command(name='playing2', description='Share your currently playing song on Spotify', guild=self.guild)
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

        # NEEDS TO BE FIXED
        @self.tree.command(name='listening', description="Find who's listening to what on the server", guild=self.guild)
        async def listening(interaction: discord.Interaction):
            members = interaction.guild.members
            listening_info = []
            for member in members:
                user_id = str(member.id)
                token_info = get_token(user_id)
                if token_info:
                    access_token = await self.get_fresh_token(token_info, user_id)
                    if access_token:
                        sp = spotipy.Spotify(auth=access_token)
                        try:
                            current_track = sp.current_user_playing_track()
                            if current_track and current_track['item']:
                                track_name = current_track['item']['name']
                                artist_name = current_track['item']['artists'][0]['name']
                                listening_info.append(f"{member.display_name} is listening to '{track_name}' by {artist_name}")
                        except spotipy.SpotifyException as e:
                            print(f"Spotify API error for user {member.display_name}: {e}")
            if listening_info:
                reply = "Here's what everyone is listening to right now:\n" + "\n".join(listening_info)
            else:
                reply = "No one is currently listening to anything on Spotify or they haven't authenticated."
            await interaction.response.send_message(reply)

        @self.tree.command(name='recommend', description='Recommend a song, album, or artist to the channel', guild=self.guild)
        @app_commands.describe(search_type="Type of search: track, album, artist", query="Title of song, album, or artist name")
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

        @self.tree.command(name='playlistcreate', description="Create a collaborative playlist for the server", guild=self.guild)
        @app_commands.describe(name="The name of the playlist", description="The description of the playlist")
        async def playlistcreate(interaction: discord.Interaction, name: str, description: str):
            user_id = str(interaction.user.id)
            token_info = get_token(user_id)  # Retrieve the token from the database
            access_token = await self.get_fresh_token(token_info, user_id)
            if not access_token:
                await interaction.response.send_message("Please authenticate with Spotify first using /authenticate_spotify.", ephemeral=True)
                return

            sp = spotipy.Spotify(auth=access_token)
            user_profile = sp.current_user()
            try:
                playlist = sp.user_playlist_create(user=user_profile['id'], name=name, public=True, description=description)
                playlist_url = playlist['external_urls']['spotify']
                # Add playlist to the database
                add_playlist_to_db(playlist['id'], name, description, playlist_url, user_id)
                await interaction.response.send_message(f"Collaborative playlist created: [Playlist Link]({playlist_url})")
            except spotipy.exceptions.SpotifyException as e:
                await interaction.response.send_message(f"Failed to create playlist: {e}", ephemeral=True)

        @self.tree.command(name='playlistadd', description="Add a song to a collaborative playlist", guild=self.guild)
        @app_commands.describe(playlist_name="The name of the playlist", track_id="The ID of the track to add")
        async def playlistadd(interaction: discord.Interaction, playlist_name: str, track_id: str):
            user_id = str(interaction.user.id)
            token_info = get_token(user_id)  # Retrieve the token from the database
            access_token = await self.get_fresh_token(token_info, user_id)
            if not access_token:
                await interaction.response.send_message("Please authenticate with Spotify first using /authenticate_spotify.", ephemeral=True)
                return
            sp = spotipy.Spotify(auth=access_token)
            # Search for the playlist by name
            playlists = fetch_playlists_from_db(user_id)
            playlist_id = None
            for playlist in playlists:
                if playlist.name.lower() == playlist_name.lower():
                    playlist_id = playlist.id
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
                sp.user_playlist_add_tracks(user=user_id, playlist_id=playlist_id, tracks=[track_id])
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
            playlists = fetch_playlists_from_db(user_id)

            if not playlists:
                await interaction.response.send_message("You have no playlists.", ephemeral=True)
                return
            embeds = []
            embed = discord.Embed(title="Your Collaborative Playlists", color=discord.Color.purple())
            field_count = 0
            for playlist in playlists:
                embed.add_field(name=playlist.name, value=f"[Link]({playlist.url})", inline=False)
                field_count += 1
                if field_count == 25:
                    embeds.append(embed)
                    embed = discord.Embed(title="Your Collaborative Playlists (continued)", color=discord.Color.purple())
                    field_count = 0
            if field_count > 0:
                embeds.append(embed)
            for embed in embeds:
                await interaction.response.send_message(embed=embed, ephemeral=True)

        # @self.tree.command(name='top5songs', description='Share your top 5 songs on Spotify', guild=self.guild)
        # async def top5songs(interaction: discord.Interaction):
        #     user_id = str(interaction.user.id)
        #     token_info = get_token(user_id)  # Retrieve the token from the database
        #     access_token = await self.get_fresh_token(token_info, user_id)
        #     if not access_token:
        #         await interaction.response.send_message("Please authenticate with Spotify first using /authenticate_spotify.", ephemeral=True)
        #         return

        #     sp = spotipy.Spotify(auth=access_token)
        #     top_tracks = sp.current_user_top_tracks(limit=5)

        #     if top_tracks and top_tracks['items']:
        #         top_tracks_list = [f"{idx + 1}. {track['name']} by {track['artists'][0]['name']}" for idx, track in enumerate(top_tracks['items'])]
        #         reply = f"{interaction.user.display_name}'s top 5 songs on Spotify:\n" + "\n".join(top_tracks_list)
        #         await interaction.response.send_message(reply)
        #     else:
        #         await interaction.response.send_message('Could not retrieve top tracks.')

        # @self.tree.command(name='top5artists', description='Share your top 5 artists on Spotify', guild=self.guild)
        # async def top5artists(interaction: discord.Interaction):
        #     user_id = str(interaction.user.id)
        #     token_info = get_token(user_id)  # Retrieve the token from the database
        #     access_token = await self.get_fresh_token(token_info, user_id)
        #     if not access_token:
        #         await interaction.response.send_message("Please authenticate with Spotify first using /authenticate_spotify.", ephemeral=True)
        #         return

        #     sp = spotipy.Spotify(auth=access_token)
        #     top_artists = sp.current_user_top_artists(limit=5)

        #     if top_artists and top_artists['items']:
        #         top_artists_list = [f"{idx + 1}. {artist['name']}" for idx, artist in enumerate(top_artists['items'])]
        #         reply = f"{interaction.user.display_name}'s top 5 artists on Spotify:\n" + "\n".join(top_artists_list)
        #         await interaction.response.send_message(reply)
        #     else:
        #         await interaction.response.send_message('Could not retrieve top artists.')

    async def get_top_songs(self, access_token):
        sp = spotipy.Spotify(auth=access_token)
        top_tracks = sp.current_user_top_tracks(limit=5)
        return [f"{track['name']} by {track['artists'][0]['name']}" for track in top_tracks['items']]

    async def get_top_artists(self, access_token):
        sp = spotipy.Spotify(auth=access_token)
        top_artists = sp.current_user_top_artists(limit=5)
        return [artist['name'] for artist in top_artists['items']]

    async def get_fresh_token(self, token_info, user_id):
        if token_info and (token_info['expires_at'] - int(time.time()) < 60):
            # Token needs refreshing
            refresh_url = f"http://localhost:8888/refresh_token?refresh_token={token_info['refresh_token']}"
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