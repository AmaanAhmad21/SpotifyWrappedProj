from flask import Flask, request, url_for, session, redirect, render_template
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os
import time
import pandas as pd
import datetime
import gspread

# Load environment variables from .env file.
load_dotenv()

# Constants
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
TOKEN_INFO = "token_info"

# Set the secret key for session encryption.
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
    artists = []
    for artist in meta["album"]["artists"]: # Handles multiple artists.
        artists.append(artist["name"])
    artist_names = ", ".join(artists)
    album_cover = meta["album"]["images"][0]["url"]
    spotify_url = meta["external_urls"]["spotify"]
    track_info = [name, album, artist_names, album_cover, spotify_url]
    return track_info

# Function to get the track IDs from the top tracks.
def get_track_ids(top_tracks):
    return [track['id'] for track in top_tracks['items']]

# Function to insert the track data to Google Sheets.
def insert_to_gsheet(time_range, track_ids):
    # Convert to DataFrame and update Google Sheets for each time range.
    tracks = []
    for track_id in track_ids:
        track = getTrackFeatures(track_id)  
        tracks.append(track)

    df = pd.DataFrame(tracks, columns=["name", "album", "artist_names", "album_cover", "spotify_url"])

    # Insert to Google Sheets
    gc = gspread.service_account(filename="wrappedproj-2e230b153ff5.json")
    sh = gc.open("WrappedProj")
    worksheet = sh.worksheet(f"{time_range}")

    # Clear worksheets current data.
    worksheet.clear()

    # Update the sheet with new data.
    worksheet.update([df.columns.values.tolist()] + df.values.tolist())
    print(f"Updated Google Sheets with {len(df)} tracks.")

@app.route("/stats", methods=["GET", "POST"])
def stats():
    if request.method == "GET":
        # Display the form initially
        return render_template("stats.html")

    if request.method == "POST":
        user_token = getToken()
        if not user_token:
            return redirect(url_for("login"))

        # Get the user's selections
        time_range = ["short_term", "medium_term", "long_term"]
        song_limit = int(request.form.get("song_limit", 5))

        # Fetch user’s top tracks for the specified time range and limit
        sp = spotipy.Spotify(auth=user_token["access_token"])

        # Iterate over all time ranges and fetch top tracks
        for range in time_range:
            userTopSongs = sp.current_user_top_tracks(
                limit=song_limit,
                offset=0,
                time_range=range
            )

            # Extract track IDs and update the Google Sheets
            track_ids = get_track_ids(userTopSongs)
            insert_to_gsheet(range, track_ids)

    return render_template(
        "display.html", 
        time_range=range, 
        song_limit=song_limit
        )

    
@app.route("/display")
def display():
    # Get the time range and song limit from the query parameters
    time_range = request.args.get("time_range", "unknown").replace("_", " ").title()
    song_limit = request.args.get("song_limit", "unknown")

    return render_template(
        "display.html",
        message=f"Updated Google Sheets for {time_range} with Top {song_limit} songs."
    )
