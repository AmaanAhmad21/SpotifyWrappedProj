from flask import Flask, request, url_for, session, redirect, render_template
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os
import time
import pandas as pd

# Load environment variables from .env file
load_dotenv()

# Constants
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
TOKEN_INFO = "token_info"

# Set the secret key for session encryption
app = Flask(__name__)
app.secret_key = os.getenv("SPOTIFY_CLIENT_SECRET")  # Ensure it's set

def createSpotifyOAuth():
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=url_for("redirect_page", _external=True),
        scope="user-top-read"
    )

@app.route("/")
def home():
    return render_template('index.html')

@app.route("/login")
def login():
    sp_oauth = createSpotifyOAuth()
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)


@app.route("/redirect_page")
def redirect_page():
    code = request.args.get("code")
    sp_oauth = createSpotifyOAuth()
    token_info = sp_oauth.get_access_token(code)
    session[TOKEN_INFO] = token_info
    return redirect(url_for("stats", _external=True))

def getToken():
    token_info = session.get(TOKEN_INFO, None)
    return token_info

def getTrackFeatures(track_ids):
    user_token = getToken()
    sp = spotipy.Spotify(auth=user_token['access_token'])
    time.sleep(0.5)
    meta = sp.track(track_ids)
    name = meta["name"]
    album = meta["album"]["name"]
    artists = []
    for artist in meta["album"]["artists"]: # Handles multiple artists.
        artists.append(artist["name"])
    artist_names = ", ".join(artists)
    album_cover = meta["album"]["images"][0]["url"]
    track_info = [name, album, artist_names, album_cover]
    return track_info

@app.route("/stats")
def stats():
    user_token = getToken()
    if not user_token:
        print("No token, redirecting to login...")  # Debugging statement
        return redirect(url_for("login"))

    sp = spotipy.Spotify(auth=user_token['access_token'])
    time.sleep(0.5)
    userTopSongs_short = sp.current_user_top_tracks(
        limit=5, 
        offset=0, 
        time_range="short_term"
        )
    # userTopSongs_medium = sp.current_user_top_tracks(
    #     limit=5, 
    #     offset=0, 
    #     time_range="medium_term"
    #     )
    # userTopSongs_long = sp.current_user_top_tracks(
    #     limit=5, 
    #     offset=0, 
    #     time_range="long_term"
    #     )
    track_ids = [track['id'] for track in userTopSongs_short['items']]
    track_details = []
    for track_id in track_ids:
        track_info = getTrackFeatures(track_id)
        track_details.append(track_info)
    # Create the datatable.
    df = pd.DataFrame(track_details, columns=["name", "album", "artist_names", "album_cover"])
    print("Generated DataFrame:")
    print(df)
    return track_details        