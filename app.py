from flask import Flask, request, url_for, session, redirect, render_template
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os
import time
import pandas as pd

# Load environment variables from .env file.
load_dotenv()

# Constants
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
TOKEN_INFO = "token_info"

# Set up Flask app
app = Flask(__name__)
app.secret_key = os.getenv("SPOTIFY_CLIENT_SECRET")  

def createSpotifyOAuth():
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=url_for("redirect_page", _external=True),
        scope="user-top-read"
    )

@app.route("/")
def home():
    return render_template("index.html")

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
    sp = spotipy.Spotify(auth=user_token["access_token"])
    time.sleep(0.5)
    meta = sp.track(track_ids)
    name = meta["name"]
    album = meta["album"]["name"]
    artists = [artist["name"] for artist in meta["album"]["artists"]]
    artist_names = ", ".join(artists)
    album_cover = meta["album"]["images"][0]["url"]
    spotify_url = meta["external_urls"]["spotify"]
    return {
        "name": name,
        "album": album,
        "artist_names": artist_names,
        "album_cover": album_cover,
        "spotify_url": spotify_url,
    }

def save_to_csv(time_range, tracks):
    df = pd.DataFrame(tracks)
    filename = f"{time_range}_top_tracks.csv"
    df.to_csv(filename, index=False)
    print(f"Saved {len(tracks)} tracks to {filename}")

@app.route("/stats", methods=["GET", "POST"])
def stats():
    if request.method == "GET":
        return render_template("stats.html")

    if request.method == "POST":
        user_token = getToken()
        if not user_token:
            return redirect(url_for("login"))

        time_ranges = ["short_term", "medium_term", "long_term"]
        song_limit = int(request.form.get("song_limit", 5))
        all_tracks = {}

        sp = spotipy.Spotify(auth=user_token["access_token"])

        # Fetch top tracks for all time ranges
        for time_range in time_ranges:
            userTopSongs = sp.current_user_top_tracks(
                limit=song_limit,
                offset=0,
                time_range=time_range
            )
            track_ids = [track["id"] for track in userTopSongs["items"]]
            tracks = [getTrackFeatures(track_id) for track_id in track_ids]
            all_tracks[time_range] = tracks
            save_to_csv(time_range, tracks)

        return render_template(
            "display.html",
            tracks=all_tracks,
            song_limit=song_limit
        )

@app.route("/display")
def display():
    return render_template("display.html")
