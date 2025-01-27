from flask import Flask, request, url_for, session, redirect, render_template
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os
import time
import pandas as pd
from datetime import datetime, timedelta
from dateutil import parser
import pytz

# Load environment variables from .env file.
load_dotenv()

# Constants.
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
TOKEN_INFO = "token_info"

app = Flask(__name__)
app.secret_key = os.getenv("SPOTIFY_CLIENT_SECRET")  
app.config["SESSION_PERMANENT"] = False

def createSpotifyOAuth():
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=url_for("redirect_page", _external=True),
        scope="user-top-read user-read-recently-played"
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
    track_spotify_url = meta["external_urls"]["spotify"]
    return {
        "name": name,
        "album": album,
        "artist_names": artist_names,
        "album_cover": album_cover,
        "spotify_url": track_spotify_url
    }

def getArtistFeatures(artist_ids):
    user_token = getToken()
    sp = spotipy.Spotify(auth=user_token["access_token"])
    time.sleep(0.5)
    meta = sp.artist(artist_ids)
    name = meta["name"]
    artist_img = meta["images"][0]["url"]
    artist_spotify_url = meta["external_urls"]["spotify"]
    return {
        "name": name,
        "url": artist_img,
        "spotify_url": artist_spotify_url
    }

def convertToDatetime(iso_string):
    return parser.isoparse(iso_string).astimezone(pytz.utc)

# Function to convert Spotify time range to approximate date range.
def timeRangeDates(time_range):
    # Return start and end dates based on the time range.
    if time_range == "short_term":
        end_date = datetime.now(pytz.utc)
        start_date = end_date - timedelta(weeks=4)  # Last 4 weeks.
    elif time_range == "medium_term":
        end_date = datetime.now(pytz.utc)
        start_date = end_date - timedelta(weeks=26)  # Last 6 months.
    elif time_range == "long_term":
        end_date = datetime.now(pytz.utc)
        start_date = end_date - timedelta(weeks=52)  # Last Year.
    return start_date, end_date

def getRecentTracks(time_range):
    user_token = getToken()  
    sp = spotipy.Spotify(auth=user_token["access_token"])
    
    # Get the time range dates.
    time_range_start, time_range_end = timeRangeDates(time_range)
    
    # Get recently played tracks.
    history = sp.current_user_recently_played(limit=50)
    while history.get('next'):
        history = sp.next(history) # Paginate if needed.  
    
    # Filter the tracks based on time range.
    recent_tracks = []
    for play in history["items"]:
        played_at = convertToDatetime(play["played_at"])  
        
        # Check if played_at is within the time range.
        if time_range_start <= played_at <= time_range_end:
            recent_tracks.append(play["track"]["name"])  
    
    return recent_tracks

@app.before_request
def reset_session_defaults():
    
    session.clear

    if "time_range" not in session:
        session["time_range"] = "short_term"  # Default value for time range.
    if "result_limit" not in session:
        session["result_limit"] = 5  # Default value for result limit.

@app.route("/stats", methods=["GET", "POST"])
def stats():
    user_token = getToken()
    if not user_token:
        return redirect(url_for("login"))

    sp = spotipy.Spotify(auth=user_token["access_token"])

    time_range = session.get("time_range", "short_term")
    result_limit = session.get("result_limit", 5)

    # Override session values if form data is provided.
    if request.method == "POST":
        # Update the time range if provided in the form.
        if "time_range" in request.form:
            session["time_range"] = request.form["time_range"]
            time_range = session["time_range"]
        # Update the result limit if provided in the form.
        if "result_limit" in request.form:
            session["result_limit"] = int(request.form["result_limit"])
            result_limit = session["result_limit"]
    
    userTopSongs = sp.current_user_top_tracks(limit=result_limit, offset=0, time_range=time_range)
    userTopArtists = sp.current_user_top_artists(limit=result_limit, offset=0, time_range=time_range)

    # Update session with the current selections.
    session["time_range"] = time_range
    session["result_limit"] = result_limit

    # Get top tracks.
    userTopSongs = sp.current_user_top_tracks(
        limit=result_limit, 
        offset=0, 
        time_range=time_range
    )
    userTopArtists = sp.current_user_top_artists(
        limit=result_limit, 
        offset=0, 
        time_range=time_range
    )

    track_ids = [track["id"] for track in userTopSongs["items"]]
    artist_ids = [artist["id"] for artist in userTopArtists["items"]]
    tracks = [getTrackFeatures(track_id) for track_id in track_ids]
    artists = [getArtistFeatures(artist_id) for artist_id in artist_ids]
    recent_tracks = getRecentTracks(time_range)
    print(recent_tracks)


    return render_template(
        "stats.html",
        tracks=tracks,
        artists = artists, 
        song_limit=result_limit,
        time_range=time_range,
    )