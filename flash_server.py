from flask import Flask, request, redirect, session as flask_session, jsonify, url_for
from database_setup import sql_session, SpotifyToken
import json
import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import urllib.parse

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Load Spotify API credentials
SPOTIPY_CLIENT_ID = 'your_client_id'
SPOTIPY_CLIENT_SECRET = 'your_client_secret'
SPOTIPY_REDIRECT_URI = 'http://localhost:8888/callback'

# Initialize SpotifyOAuth object
sp_oauth = SpotifyOAuth(client_id=SPOTIPY_CLIENT_ID,
                        client_secret=SPOTIPY_CLIENT_SECRET,
                        redirect_uri=SPOTIPY_REDIRECT_URI,
                        scope="user-read-playback-state")

@app.route('/')
def index():
    if 'token_info' in flask_session:
        token_info = flask_session['token_info']
        if token_info:
            sp = spotipy.Spotify(auth=token_info['access_token'])
            current_user = sp.current_user()
            return f'Logged in as {current_user["display_name"]}'
        else:
            return redirect(url_for('login'))
    return redirect(url_for('login'))

@app.route('/login')
def login():
    # Simulate capturing a user ID
    user_id = request.args.get('user_id', 'default_user_id')
    state = urllib.parse.quote_plus(json.dumps({'user_id': user_id}))
    auth_url = sp_oauth.get_authorize_url(state=state)
    return redirect(auth_url)

@app.route('/callback')
def callback():
    state = json.loads(urllib.parse.unquote_plus(request.args.get('state', '{}')))
    user_id = state.get('user_id')
    # user_id = flask_session.get('user_id')
    code = request.args.get('code')
    token_info = sp_oauth.get_access_token(code)
    if user_id and token_info:
        save_token(user_id, token_info)
    return redirect(url_for('index'))

def save_token(user_id, token_info):
    existing_token = sql_session.query(SpotifyToken).filter_by(user_id=user_id).first()
    if existing_token:
        existing_token.access_token = token_info['access_token']
        existing_token.refresh_token = token_info.get('refresh_token', existing_token.refresh_token)
        existing_token.token_type = token_info['token_type']
        existing_token.expires_in = token_info['expires_in']
        existing_token.scope = token_info['scope']
    else:
        new_token = SpotifyToken(
            user_id=user_id,
            access_token=token_info['access_token'],
            refresh_token=token_info.get('refresh_token'),
            token_type=token_info['token_type'],
            expires_in=token_info['expires_in'],
            scope=token_info['scope']
        )
        sql_session.add(new_token)
    sql_session.commit()

if __name__ == '__main__':
    app.run(port=8888, debug=True)
