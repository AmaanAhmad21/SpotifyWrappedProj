from flask import Flask, request, url_for, session, redirect, render_template
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os
import time
import pandas as pd
import datetime

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

@app.route("/stats", methods=["GET", "POST"])
def stats():
    user_token = getToken()
    if not user_token:
        print("No token, redirecting to login...")  # Debugging statement
        return redirect(url_for("login"))

    time_range = request.form.get("time_range", "short_term")  # Default to short_term
    sp = spotipy.Spotify(auth=user_token['access_token'])
    time.sleep(0.5)

    # Fetch top tracks based on the selected time range
    userTopSongs = sp.current_user_top_tracks(limit=5, offset=0, time_range=time_range)
    track_ids = [track['id'] for track in userTopSongs['items']]

    def convertToDf(track_ids):
        tracks = []
        for track_id in track_ids:
            time.sleep(0.5)  # To avoid hitting API rate limits
            track = getTrackFeatures(track_id)
            tracks.append(track)

        # Create DataFrame
        columns = ["name", "album", "artist", "album_cover"]
        df = pd.DataFrame(tracks, columns=columns)

        # Save to CSV with a timestamped filename
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"data_{time_range}_{timestamp}.csv"
        df.to_csv(filename, index=False)
        print(f"Data saved to {filename}")  # Debugging statement
        return df

    # Convert track IDs to DataFrame and save to CSV
    df = convertToDf(track_ids)

    # Debugging: Print the DataFrame
    print(df)
    
    return render_template("stats.html", tracks=df.to_dict(orient="records"), time_range=time_range)
