import discord
from discord.ext import commands
from spotipy.oauth2 import SpotifyOAuth
import spotipy
import os
from dotenv import load_dotenv
import json

# Load environment variables from the .env file
load_dotenv()

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

# Spotify API setup
SPOTIPY_CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
SPOTIPY_CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')
SPOTIPY_REDIRECT_URI = os.getenv('SPOTIPY_REDIRECT_URI')

scope = "user-read-playback-state user-read-currently-playing user-read-private user-library-read user-read-recently-played"
sp_oauth = SpotifyOAuth(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET, redirect_uri=SPOTIPY_REDIRECT_URI, scope=scope)

# Load tokens from file
def load_tokens():
    if os.path.exists('tokens.json'):
        with open('tokens.json', 'r') as f:
            return json.load(f)
    return {}

user_tokens = load_tokens()
print(f"Loaded user tokens at startup: {user_tokens}")  # Debugging: Print loaded tokens at startup

def get_spotify_client(user_id):
    global user_tokens  # Ensure we are accessing the global user_tokens
    print(f"Calling get_spotify_client for user {user_id}")  # Debugging: Verify function call
    user_tokens = load_tokens()  # Reload tokens to ensure we have the latest version
    print(f"Current user tokens: {user_tokens}")  # Debugging: Print current tokens
    print(f"Attempting to retrieve token for user {user_id}")  # Debugging: Attempt to retrieve token
    if user_id in user_tokens:
        token_info = user_tokens[user_id]
        print(f"Token info for user {user_id}: {token_info}")  # Debugging: Print token info
        if sp_oauth.is_token_expired(token_info):
            print(f"Token expired for user {user_id}, refreshing...")  # Debugging: Token expired
            token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
            user_tokens[user_id] = token_info
            with open('tokens.json', 'w') as f:
                json.dump(user_tokens, f)
            print(f"Refreshed token info for user {user_id}: {token_info}")  # Debugging: Print refreshed token info
        return spotipy.Spotify(auth=token_info['access_token'])
    print(f"No token found for user {user_id}")  # Debugging: No token found
    return None

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    # Register commands for all guilds the bot is a member of
    for guild in bot.guilds:
        print(f"Registering commands for guild: {guild.name} ({guild.id})")
        bot.tree.clear_commands(guild=guild)  # Clear existing commands to prevent duplicates
        await bot.tree.sync(guild=guild)
    print("Commands synchronized for all guilds")

@bot.tree.command(name='profile', description='View your Spotify profile')
async def profile(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    print(f"Executing /profile command for user {user_id}")  # Debugging: Print command execution
    sp = get_spotify_client(user_id)
    if sp is None:
        await interaction.response.send_message('You need to authenticate with Spotify first. Use the /createprofile command.')
        return
    profile_data = sp.current_user()
    await interaction.response.send_message(f"Profile for {profile_data['display_name']}: {profile_data['external_urls']['spotify']}")

@bot.tree.command(name='playing', description='Show what you are listening to')
async def playing(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    print(f"Executing /playing command for user {user_id}")  # Debugging: Print command execution
    await interaction.response.defer()  # Acknowledge interaction to avoid timeout
    print(f"Calling get_spotify_client from /playing for user {user_id}")  # Debugging: Verify function call
    sp = get_spotify_client(user_id)
    if sp is None:
        await interaction.followup.send('You need to authenticate with Spotify first. Use the /createprofile command.')
        return

    # Check available devices
    devices = sp.devices()
    print(f"Available devices: {devices}")  # Debugging: Print available devices

    if not devices['devices']:
        await interaction.followup.send('No active devices found. Please make sure Spotify is playing on a device.')
        return

    # Check playback state
    current_playback = sp.current_playback()
    print(f"Current playback response: {current_playback}")  # Debugging: Print current playback response
    if current_playback and current_playback['is_playing']:
        await interaction.followup.send(f"Now playing: {current_playback['item']['name']} by {current_playback['item']['artists'][0]['name']}")
    else:
        await interaction.followup.send('No music is currently playing.')

@bot.tree.command(name='listening', description='Find whose listening to what on the server')
async def listening(interaction: discord.Interaction):
    await interaction.response.send_message('This functionality is under development.')

@bot.tree.command(name='createprofile', description='Create a Spotify profile')
async def create_profile(interaction: discord.Interaction):
    auth_url = sp_oauth.get_authorize_url(state=str(interaction.user.id))
    print(f"Auth URL for {interaction.user.id}: {auth_url}")  # Print the authorization URL for debugging
    await interaction.response.send_message(f"Please authenticate with Spotify using this URL: {auth_url}")

@bot.tree.command(name='lyrics', description='Shows lyrics for the current song playing')
async def lyrics(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    print(f"Executing /lyrics command for user {user_id}")  # Debugging: Print command execution
    await interaction.response.defer()  # Acknowledge interaction to avoid timeout
    print(f"Calling get_spotify_client from /lyrics for user {user_id}")  # Debugging: Verify function call
    sp = get_spotify_client(user_id)
    if sp is None:
        await interaction.followup.send('You need to authenticate with Spotify first. Use the /createprofile command.')
        return
    current_playback = sp.current_playback()
    print(f"Current playback response: {current_playback}")  # Debugging: Print current playback response
    if current_playback and current_playback['is_playing']:
        track = current_playback['item']['name']
        artist = current_playback['item']['artists'][0]['name']
        lyrics = f"Lyrics for {track} by {artist} are not available."
        await interaction.followup.send(lyrics)
    else:
        await interaction.followup.send('No music is currently playing.')

# Run the bot with the token
bot.run(os.getenv('DISCORD_TOKEN'))
