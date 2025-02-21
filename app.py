from flask import Flask, request, url_for, session, redirect, render_template, jsonify
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os
import time
from openai import OpenAI
from flask_caching import Cache

# Load environment variables from .env file.
load_dotenv()

# Constants.
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
TOKEN_INFO = "token_info"
OpenAI.api_key = os.getenv("OPENAI_API_KEY")

# Initialize Flask app.
app = Flask(__name__)
app.secret_key = os.getenv("SPOTIFY_CLIENT_SECRET")  
app.config["SESSION_PERMANENT"] = False

# Initialize Flask caching.
cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache'})

# Function to create a Spotify OAuth object.
def createSpotifyOAuth():
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=url_for("redirect_page", _external=True),
        scope="user-top-read user-read-private user-read-email"
    )

# Home route: Resets session and renders the index page.
@app.route("/")
def home():
    # Reset session to defaults.
    session.clear()
    session["time_range"] = "short_term"
    session["result_limit"] = 5
    return render_template("index.html")

# Login route: Redirects to Spotify OAuth authorization page.
@app.route("/login")
def login():
    sp_oauth = createSpotifyOAuth()
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

# Redirect route: Handles Spotify OAuth callback and stores access token in session.
@app.route("/redirect_page")
def redirect_page():
    code = request.args.get("code")
    sp_oauth = createSpotifyOAuth()
    token_info = sp_oauth.get_access_token(code)
    session[TOKEN_INFO] = token_info
    return redirect(url_for("stats", _external=True))

# Function to retrieve Spotify access token from session.
def getToken():
    token_info = session.get(TOKEN_INFO, None)
    return token_info

# Function to retrieve user details from Spotify.
def getUserDetails():
    user_token = getToken()
    if not user_token:
        return None
    
    sp = spotipy.Spotify(auth=user_token["access_token"])
    try:
        user_profile = sp.current_user()
        return {
            "display_name": user_profile["display_name"],
            "profile_image": user_profile["images"][0]["url"] if user_profile["images"] else None,
            "email": user_profile.get("email"),
            "spotify_url": user_profile["external_urls"]["spotify"]
        }
    except:
        return None

# Function to retrieve track features (name, album, artist, etc.) from Spotify.
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

# Function to retrieve artist features (name, image, etc.) from Spotify.
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

# Stats route: Displays user's top tracks and artists.
@app.route("/stats", methods=["GET", "POST"])
def stats():
    user_token = getToken()
    if not user_token:
        return redirect(url_for("login"))

    sp = spotipy.Spotify(auth=user_token["access_token"])

    user_profile = getUserDetails()
    if not user_profile:
        return redirect(url_for("login"))

    # Get current values, with defaults if not set.
    time_range = session.get("time_range", "short_term")
    result_limit = session.get("result_limit", 5)

    # Handle form submissions
    if request.method == "POST":
        # Update time range if provided.
        if "time_range" in request.form:
            time_range = request.form["time_range"]
            session["time_range"] = time_range
        
        # Update result limit if provided.
        if "result_limit" in request.form:
            result_limit = int(request.form["result_limit"])
            session["result_limit"] = result_limit

    # Get top tracks and artists.
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

    # Check if suggestions exist for the current combination.
    current_combination = f"{time_range}_{result_limit}"
    suggestions = cache.get(current_combination)  # Retrieve suggestions from cache

    return render_template(
        "stats.html",
        tracks=tracks,
        artists=artists, 
        song_limit=result_limit,
        time_range=time_range,
        user=user_profile,
        suggestions=suggestions  # Pass suggestions to the template
    )

# Function to generate similar song and artist recommendations using OpenAI.
def get_similar_recommendations(top_songs, top_artists, result_limit):
    if not top_songs or not top_artists:
        print("No top songs or artists provided")
        return [], []

    # Create sets of existing names for easier comparison.
    existing_songs = {song.lower() for song in top_songs}
    existing_artists = {artist.lower() for artist in top_artists}

    # Generate more recommendations than needed (e.g., double the limit).
    num_recommendations = result_limit * 2

    prompt = f"""
    Based on these songs and artists:
    Songs: {', '.join(top_songs)}
    Artists: {', '.join(top_artists)}

    Please suggest:
    1. Exactly {num_recommendations} similar songs in the format "Song Name - Artist Name"
    2. Exactly {num_recommendations} similar artists

    Important rules:
    - DO NOT suggest any songs or artists already mentioned above (VERY IMPORTANT)
    - Only suggest fairly well-known songs and artists (they don't need to be super famous, but should be established)
    - Each suggestion must be unique (VERY IMPORTANT)
    - Suggestions should match the general style/genre of the input songs

    Format your response exactly like this:
    Songs:
    1. Song Name - Artist Name
    2. Song Name - Artist Name
    (etc.)

    Artists:
    1. Artist Name
    2. Artist Name
    (etc.)
    """

    client = OpenAI()
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "system", 
                "content": "You are a music recommendation assistant that suggests relatively well-known songs and artists similar to the user's taste. Never suggest songs or artists that are already in the user's list."
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )

    # Parse response.
    content = response.choices[0].message.content
    songs = []
    artists = []
    current_section = None
    
    for line in content.split("\n"):
        line = line.strip()
        if "Songs:" in line:
            current_section = "songs"
            continue
        elif "Artists:" in line:
            current_section = "artists"
            continue
            
        line = line.lstrip("123456789. ")  # Remove numbering
        
        if line:
            if current_section == "songs":
                # Split the line into song and artist (handle variations in format).
                if "-" in line:
                    song_parts = line.split("-", 1)
                elif "by" in line:
                    song_parts = line.split("by", 1)
                else:
                    continue  # Skip if the format is invalid

                if len(song_parts) == 2:
                    song_name = song_parts[0].strip().lower()
                    artist_name = song_parts[1].strip().lower()
                    
                    # Check if the song or artist is already in the user's list.
                    if not any(song_name in existing.lower() for existing in top_songs) and \
                       not any(artist_name in existing.lower() for existing in top_artists):
                        songs.append(line)
                        
            elif current_section == "artists":
                # Check if artist is in existing list.
                if not any(line.lower() in existing.lower() for existing in top_artists):
                    artists.append(line)

    # Return up to `result_limit` songs and artists.
    return songs[:result_limit], artists[:result_limit]

# Route to get recommendations: Generates and returns similar songs and artists.
@app.route("/get_recommendations", methods=["POST"])
def get_recommendations():
    try:
        token_info = getToken()
        if not token_info:
            return jsonify({"error": "No Spotify token found"}), 401
        
        sp = spotipy.Spotify(auth=token_info["access_token"])
        
        time_range = session.get("time_range", "short_term")
        result_limit = session.get("result_limit", 5)
        
        # Check if suggestions already exist for this combination.
        current_combination = f"{time_range}_{result_limit}"
        suggestions = cache.get(current_combination)
        
        if suggestions:
            # Return existing suggestions.
            return jsonify(suggestions)
        
        # Generate new suggestions.
        top_tracks = sp.current_user_top_tracks(limit=result_limit, time_range=time_range)
        top_artists = sp.current_user_top_artists(limit=result_limit, time_range=time_range)
        
        top_track_names = [
            f"{track['name']} - {track['artists'][0]['name']}" 
            for track in top_tracks["items"]
        ]
        top_artist_names = [artist["name"] for artist in top_artists["items"]]
        
        recommended_songs, recommended_artists = get_similar_recommendations(
            top_track_names, 
            top_artist_names, 
            result_limit
        )
        
        # Look up songs with popularity filter.
        suggested_songs = []
        for rec in recommended_songs:
            try:
                if "-" not in rec and "by" not in rec:
                    continue  # Skip if the format is invalid
                
                # Split the recommendation into song and artist.
                if "-" in rec:
                    song_parts = rec.split("-", 1)
                elif "by" in rec:
                    song_parts = rec.split("by", 1)
                
                if len(song_parts) != 2:
                    continue  # Skip if the format is invalid

                song_name = song_parts[0].strip()
                artist_name = song_parts[1].strip()
                
                # Search for the song using both track and artist name.
                query = f"track:{song_name} artist:{artist_name}"
                results = sp.search(q=query, type="track", limit=5)  # Increase limit to 5 for better results
                
                if results["tracks"]["items"]:
                    # Find the best match based on popularity.
                    best_match = max(results["tracks"]["items"], key=lambda x: x["popularity"])
                    suggested_songs.append({
                        "name": best_match["name"],
                        "artist": best_match["artists"][0]["name"],
                        "album_cover": best_match["album"]["images"][0]["url"] if best_match["album"]["images"] else None,
                        "spotify_url": best_match["external_urls"]["spotify"],
                        "preview_url": best_match.get("preview_url"),
                        "album": best_match["album"]["name"],
                        "popularity": best_match["popularity"]  
                    })

                    # Stop if we have enough songs.
                    if len(suggested_songs) >= result_limit:
                        break
            except Exception as e:
                print(f"Error processing song {rec}: {str(e)}")
                continue

        # Look up artists with popularity filter.
        suggested_artists = []
        for artist_name in recommended_artists:
            try:
                results = sp.search(q=artist_name, type="artist", limit=1)
                if results["artists"]["items"]:
                    artist = results["artists"]["items"][0]
                    suggested_artists.append({
                        "name": artist["name"],
                        "image_url": artist["images"][0]["url"] if artist["images"] else None,
                        "spotify_url": artist["external_urls"]["spotify"],
                        "popularity": artist["popularity"]  
                    })

                    # Stop if we have enough artists.
                    if len(suggested_artists) >= result_limit:
                        break
            except Exception as e:
                print(f"Error processing artist {artist_name}: {str(e)}")
                continue

        # Store suggestions in cache.
        suggestions = {
            "songs": suggested_songs,
            "artists": suggested_artists
        }
        cache.set(current_combination, suggestions)  # Store suggestions in cache

        # Return suggestions as JSON.
        return jsonify(suggestions)
        
    except Exception as e:
        print(f"Error in get_recommendations: {str(e)}")
        return jsonify({"error": str(e)}), 500