from flask import Flask, request, redirect, url_for
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError
import os
from dotenv import load_dotenv
import json

app = Flask(__name__)

# Load environment variables from the .env file
load_dotenv()

# Verify environment variables
discord_token = os.getenv('DISCORD_TOKEN')
spotipy_client_id = os.getenv('SPOTIPY_CLIENT_ID')
spotipy_client_secret = os.getenv('SPOTIPY_CLIENT_SECRET')
spotipy_redirect_uri = os.getenv('SPOTIPY_REDIRECT_URI')

# Print environment variables to verify they are loaded correctly
print(f"DISCORD_TOKEN: {discord_token}")
print(f"SPOTIPY_CLIENT_ID: {spotipy_client_id}")
print(f"SPOTIPY_CLIENT_SECRET: {spotipy_client_secret}")
print(f"SPOTIPY_REDIRECT_URI: {spotipy_redirect_uri}")

scope = "user-read-playback-state user-read-currently-playing user-read-private user-library-read user-read-recently-played"
sp_oauth = SpotifyOAuth(client_id=spotipy_client_id, client_secret=spotipy_client_secret, redirect_uri=spotipy_redirect_uri, scope=scope, show_dialog=True)

user_tokens = {}

def save_tokens():
    global user_tokens
    print(f"Saving tokens: {user_tokens}")  # Debugging: Print tokens before saving
    with open('tokens.json', 'w') as f:
        json.dump(user_tokens, f)
    print("Tokens saved successfully.")  # Debugging: Confirm tokens saved

def load_tokens():
    global user_tokens
    if os.path.exists('tokens.json'):
        with open('tokens.json', 'r') as f:
            user_tokens = json.load(f)
        print(f"Loaded tokens: {user_tokens}")  # Debugging: Print loaded tokens
    else:
        user_tokens = {}
        print("No existing tokens found, starting fresh.")  # Debugging: Confirm no tokens found

# Load existing tokens
load_tokens()

@app.route('/')
def index():
    return 'Spotify Auth Service Running'

@app.route('/callback')
def callback():
    code = request.args.get('code')
    state = request.args.get('state')  # Get the user_id from the state parameter
    print(f"Callback received with code: {code} and state: {state}")  # Debugging: Log callback parameters
    try:
        token_info = sp_oauth.get_access_token(code)
        print(f"Received token info: {token_info}")  # Debugging: Print received token info
        user_tokens[state] = token_info  # Store token_info with the user_id
        save_tokens()  # Save tokens to the file
        print(f"Stored token for user {state}: {token_info}")  # Debugging: Verify token storage
        print(f"All tokens after storing: {user_tokens}")  # Debugging: Print all stored tokens
        return redirect(url_for('success', user_id=state))
    except SpotifyOauthError as e:
        print(f"Error during authentication: {str(e)}")  # Debugging: Log the error
        return f"Error during authentication: {str(e)}. Please <a href='/clear?user_id={state}'>click here</a> to retry authentication."

@app.route('/clear')
def clear_tokens():
    user_id = request.args.get('user_id')
    if user_id in user_tokens:
        del user_tokens[user_id]
        save_tokens()  # Save tokens to the file
        print(f"Cleared tokens for user {user_id}")  # Debugging: Confirm token clearance
        return f"Tokens for user {user_id} cleared. Please <a href='/retry?user_id={user_id}'>click here</a> to retry authentication."
    print(f"No tokens found for user {user_id} to clear")  # Debugging: Confirm no tokens found
    return "No tokens found for user."

@app.route('/retry')
def retry_authentication():
    user_id = request.args.get('user_id')
    if user_id in user_tokens:
        del user_tokens[user_id]  # Ensure old tokens are cleared
    auth_url = sp_oauth.get_authorize_url(state=user_id)
    print(f"Retry Auth URL for user {user_id}: {auth_url}")  # Print the authorization URL for debugging
    return redirect(auth_url)

@app.route('/success')
def success():
    user_id = request.args.get('user_id')
    return f"Authentication successful for user {user_id}! You can now return to Discord."

if __name__ == '__main__':
    app.run(debug=True, port=8888)
