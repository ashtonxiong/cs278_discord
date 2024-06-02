from flask import Flask, request, redirect, session as flask_session, jsonify, url_for
from database_setup import sql_session, SpotifyToken
import json
import os
import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import base64
import random
import string
import urllib.parse
import time

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Load Spotify API credentials from a secure JSON file
token_path = 'tokens.json'
if not os.path.isfile(token_path):
    raise Exception(f"{token_path} not found!")
with open(token_path) as f:
    tokens = json.load(f)
    SPOTIPY_CLIENT_ID = tokens['spotify_client_id']
    SPOTIPY_CLIENT_SECRET = tokens['spotify_client_secret']
    SPOTIPY_REDIRECT_URI = tokens['spotify_redirect_uri']

def generate_random_string(length):
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(length))


@app.route('/')
def index():
    return "Authentication successful! You can close this page and return to Discord."


@app.route('/login')
def login():
    user_id = request.args.get('user_id')  # Get user ID from query parameter
    state = generate_random_string(16)
    flask_session['user_id'] = user_id  # Store user ID in session
    flask_session['state'] = state  # Store state in session to verify later
    scope="user-read-private user-read-email user-read-playback-state user-top-read playlist-read-private playlist-read-collaborative playlist-modify-public playlist-modify-private"
    
    auth_url = 'https://accounts.spotify.com/authorize?' + urllib.parse.urlencode({
        'response_type': 'code',
        'client_id': SPOTIPY_CLIENT_ID,
        'scope': scope,
        'redirect_uri': SPOTIPY_REDIRECT_URI,
        'state': state
    })
    
    return redirect(auth_url)


@app.route('/callback')
def callback():
    code = request.args.get('code')
    state = request.args.get('state')

    stored_state = flask_session.get('state')
    if state is None or state != stored_state:
        return redirect('/?error=state_mismatch')

    auth_options = {
        'url': 'https://accounts.spotify.com/api/token',
        'data': {
            'code': code,
            'redirect_uri': SPOTIPY_REDIRECT_URI,
            'grant_type': 'authorization_code'
        },
        'headers': {
            'content-type': 'application/x-www-form-urlencoded',
            'Authorization': 'Basic ' + base64.b64encode(f"{SPOTIPY_CLIENT_ID}:{SPOTIPY_CLIENT_SECRET}".encode()).decode()
        }
    }

    response = requests.post(auth_options['url'], data=auth_options['data'], headers=auth_options['headers'])
    if response.status_code == 200:
        token_info = response.json()
        token_info['expires_at'] = int(time.time()) + token_info['expires_in']
        flask_session['token_info'] = token_info
        
        # Save token to the database
        user_id = flask_session.get('user_id')
        if user_id:
            save_token(user_id, token_info)
        
        return redirect(url_for('index'))
    else:
        return jsonify({'error': 'Failed to get token from Spotify'}), response.status_code


@app.route('/refresh_token')
def refresh_token():
    refresh_token = request.args.get('refresh_token')
    auth_options = {
        'url': 'https://accounts.spotify.com/api/token',
        'headers': {
            'content-type': 'application/x-www-form-urlencoded',
            'Authorization': 'Basic ' + base64.b64encode((SPOTIPY_CLIENT_ID + ':' + SPOTIPY_CLIENT_SECRET).encode()).decode()
        },
        'data': {
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token
        }
    }

    response = requests.post(auth_options['url'], headers=auth_options['headers'], data=auth_options['data'])
    if response.status_code == 200:
        response_data = response.json()
        access_token = response_data.get('access_token')
        refresh_token = response_data.get('refresh_token', refresh_token)  # Use old refresh token if new one is not provided
        return jsonify({'access_token': access_token, 'refresh_token': refresh_token})
    else:
        return jsonify({'error': 'Failed to refresh token'}), response.status_code


def save_token(user_id, token_info):
    existing_token = sql_session.query(SpotifyToken).filter_by(user_id=user_id).first()
    if existing_token:
        existing_token.access_token = token_info['access_token']
        existing_token.refresh_token = token_info.get('refresh_token', existing_token.refresh_token)
        existing_token.token_type = token_info['token_type']
        existing_token.expires_in = token_info['expires_in']
        existing_token.scope = token_info['scope']
        existing_token.expires_at = token_info['expires_at'] 
    else:
        new_token = SpotifyToken(
            user_id=user_id,
            access_token=token_info['access_token'],
            refresh_token=token_info['refresh_token'],
            token_type=token_info['token_type'],
            expires_in=token_info['expires_in'],
            scope=token_info['scope'],
            expires_at=token_info['expires_at'] 
        )
        sql_session.add(new_token)
    sql_session.commit()
    print(f"Token for user {user_id} saved to the database")


def get_token(user_id):
    token = sql_session.query(SpotifyToken).filter_by(user_id=user_id).first()
    if token:
        print(f"Token for user {user_id} retrieved from the database")
        return {
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
            "token_type": token.token_type,
            "expires_in": token.expires_in,
            "scope": token.scope,
            "expires_at": token.expires_at  
        }
    return None


if __name__ == '__main__':
    app.run(port=8888, debug=True)
