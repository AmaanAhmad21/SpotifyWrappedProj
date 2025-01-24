from flask import Flask, request, url_for, session, redirect, render_template
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os
import time
import pandas as pd

# Load environment variables from .env file.
load_dotenv()

# Constants.
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
TOKEN_INFO = "token_info"

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

@app.route("/stats", methods=["GET", "POST"])
def stats():
    user_token = getToken()
    if not user_token:
        return redirect(url_for("login"))

    sp = spotipy.Spotify(auth=user_token["access_token"])

    # Default values.
    default_time_range = "short_term"
    default_song_limit = 5

    # Get time range and song limit from user input or use defaults.
    time_range = request.form.get("time_range", session.get("time_range", default_time_range))
    song_limit = int(request.form.get("song_limit", session.get("song_limit", default_song_limit)))

    # Update session with the current selections.
    session["time_range"] = time_range
    session["song_limit"] = song_limit

    # Get top tracks.
    userTopSongs = sp.current_user_top_tracks(
        limit=song_limit, 
        offset=0, 
        time_range=time_range
    )
    track_ids = [track["id"] for track in userTopSongs["items"]]
    tracks = [getTrackFeatures(track_id) for track_id in track_ids]

    return render_template(
        "stats.html",
        tracks=tracks,
        song_limit=song_limit,
        time_range=time_range
    )