from flask import Flask, request, redirect, session as flask_session, jsonify, url_for
from database_setup import sql_session, SpotifyToken
import json
import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth

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

# Initialize SpotifyOAuth object
sp_oauth = SpotifyOAuth(client_id=SPOTIPY_CLIENT_ID,
                        client_secret=SPOTIPY_CLIENT_SECRET,
                        redirect_uri=SPOTIPY_REDIRECT_URI,
                        scope="user-read-playback-state user-read-email")

@app.route('/')
def index():
    if 'token_info' in flask_session:
        token_info = flask_session['token_info']
        sp = spotipy.Spotify(auth=token_info['access_token'])
        current_user = sp.current_user()
        return f'Logged in as {current_user["display_name"]}'
    else:
        return redirect(url_for('login'))

@app.route('/login')
def login():
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    token_info = sp_oauth.get_access_token(code)
    flask_session['token_info'] = token_info 
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    flask_session.pop('token_info', None)
    return redirect(url_for('index'))

def save_token(user_id, token_info):
    existing_token = sql_session.query(SpotifyToken).filter_by(user_id=user_id).first()
    if existing_token:
        existing_token.access_token = token_info['access_token']
        existing_token.refresh_token = token_info['refresh_token']
        existing_token.token_type = token_info['token_type']
        existing_token.expires_in = token_info['expires_in']
        existing_token.scope = token_info['scope']
    else:
        new_token = SpotifyToken(
            user_id=user_id,
            access_token=token_info['access_token'],
            refresh_token=token_info['refresh_token'],
            token_type=token_info['token_type'],
            expires_in=token_info['expires_in'],
            scope=token_info['scope']
        )
        sql_session.add(new_token)
    sql_session.commit()

def get_token(user_id):
    token = sql_session.query(SpotifyToken).filter_by(user_id=user_id).first()
    if token:
        return {
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
            "token_type": token.token_type,
            "expires_in": token.expires_in,
            "scope": token.scope
        }
    return None

@app.route('/refresh_token/<user_id>')
def refresh_token(user_id):
    token_info = get_token(user_id)  # Retrieve token from your storage
    if token_info and sp_oauth.is_token_expired(token_info):
        token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
        save_token(user_id, token_info)  # Save the refreshed token
    return jsonify(token_info)

if __name__ == '__main__':
    app.run(port=8888, debug=True)