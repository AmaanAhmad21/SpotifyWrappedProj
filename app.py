from flask import Flask, request, url_for, session, redirect, render_template, jsonify
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os
import time
from openai import OpenAI
from flask_caching import Cache
from concurrent.futures import ThreadPoolExecutor

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
# Remove session permanence configurations to force re-login
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "/tmp/flask_session"  # For Render deployment.
app.config["SESSION_COOKIE_SECURE"] = True  # For HTTPS.
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Better caching configuration for production.
if os.environ.get('RENDER'):
    # Use filesystem cache for Render deployment
    cache = Cache(app, config={
        'CACHE_TYPE': 'FileSystemCache',
        'CACHE_DIR': '/tmp/flask-cache',
        'CACHE_DEFAULT_TIMEOUT': 300
    })
else:
    # Use simple cache for local development.
    cache = Cache(app, config={
        'CACHE_TYPE': 'SimpleCache',
        'CACHE_DEFAULT_TIMEOUT': 300
    })

# Create a thread pool for running multiple things at once.
executor = ThreadPoolExecutor(max_workers=10)

# Function to create cache key with fixed prefix for content caching
def create_content_cache_key(base_key):
    return f"content_{base_key}"

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
    # Clear session to force re-login.
    session.clear()
    sp_oauth = createSpotifyOAuth()
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

# Redirect route: Handles Spotify OAuth callback and stores access token in session.
@app.route("/redirect_page")
def redirect_page():
    code = request.args.get("code")
    sp_oauth = createSpotifyOAuth()
    token_info = sp_oauth.get_access_token(code)
    
    # Store token info in session.
    session[TOKEN_INFO] = token_info
    return redirect(url_for("stats", _external=True))

# Function to retrieve Spotify access token from session.
def getToken():
    token_info = session.get(TOKEN_INFO, None)
    if not token_info:
        return None
    return token_info

# Get user profile data.
def getUserDetails(access_token):
    sp = spotipy.Spotify(auth=access_token)
    try:
        user_profile = sp.current_user()
        data = {
            "display_name": user_profile["display_name"],
            "profile_image": user_profile["images"][0]["url"] if user_profile["images"] else None,
            "email": user_profile.get("email"),
            "spotify_url": user_profile["external_urls"]["spotify"]
        }
        return data
    except:
        return None

# Cache track info with content-based key.
@cache.memoize(timeout=300)
def getTrackFeatures(track_id, access_token):
    cache_key = create_content_cache_key(f'track_{track_id}')
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data

    sp = spotipy.Spotify(auth=access_token)
    meta = sp.track(track_id)
    data = {
        "name": meta["name"],
        "album": meta["album"]["name"],
        "artist_names": ", ".join([artist["name"] for artist in meta["album"]["artists"]]),
        "album_cover": meta["album"]["images"][0]["url"],
        "spotify_url": meta["external_urls"]["spotify"]
    }
    cache.set(cache_key, data)
    return data

# Cache artist info with content-based key.
@cache.memoize(timeout=300)
def getArtistFeatures(artist_id, access_token):
    cache_key = create_content_cache_key(f'artist_{artist_id}')
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data

    sp = spotipy.Spotify(auth=access_token)
    meta = sp.artist(artist_id)
    data = {
        "name": meta["name"],
        "url": meta["images"][0]["url"],
        "spotify_url": meta["external_urls"]["spotify"]
    }
    cache.set(cache_key, data)
    return data

# Cache top items by time_range and result_limit.
@cache.memoize(timeout=300)
def getTopItems(access_token, time_range, result_limit):
    cache_key = create_content_cache_key(f'top_items_{time_range}_{result_limit}')
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data

    sp = spotipy.Spotify(auth=access_token)
    
    # Functions to get tracks and artists.
    def get_tracks():
        return sp.current_user_top_tracks(
            limit=result_limit, 
            offset=0, 
            time_range=time_range
        )
    
    def get_artists():
        return sp.current_user_top_artists(
            limit=result_limit, 
            offset=0, 
            time_range=time_range
        )
    
    # Run both API calls at the same time instead of waiting for one to finish.
    with ThreadPoolExecutor(max_workers=2) as executor:
        tracks_future = executor.submit(get_tracks)
        artists_future = executor.submit(get_artists)
        
        userTopSongs = tracks_future.result()
        userTopArtists = artists_future.result()
    
    data = (userTopSongs, userTopArtists)
    cache.set(cache_key, data)
    return data

# Stats route.
@app.route("/stats", methods=["GET", "POST"])
def stats():
    user_token = getToken()
    if not user_token:
        # No token found, redirect to login.
        return redirect(url_for("login"))

    access_token = user_token["access_token"]
    
    # Get user profile.
    user_profile = getUserDetails(access_token)
    if not user_profile:
        return redirect(url_for("login"))

    # Get current values.
    time_range = session.get("time_range", "short_term")
    result_limit = session.get("result_limit", 5)

    # Handle form submissions.
    if request.method == "POST":
        if "time_range" in request.form:
            time_range = request.form["time_range"]
            session["time_range"] = time_range
        if "result_limit" in request.form:
            result_limit = int(request.form["result_limit"])
            session["result_limit"] = result_limit

    # Get top tracks and artists.
    userTopSongs, userTopArtists = getTopItems(access_token, time_range, result_limit)

    # Process track and artist details in parallel.
    track_ids = [track["id"] for track in userTopSongs["items"]]
    artist_ids = [artist["id"] for artist in userTopArtists["items"]]

    # Process all tracks at once.
    def process_tracks():
        return [getTrackFeatures(track_id, access_token) for track_id in track_ids]

    # Process all artists at once.
    def process_artists():
        return [getArtistFeatures(artist_id, access_token) for artist_id in artist_ids]

    # Run both processes at the same time.
    with ThreadPoolExecutor(max_workers=2) as executor:
        tracks_future = executor.submit(process_tracks)
        artists_future = executor.submit(process_artists)
        
        tracks = tracks_future.result()
        artists = artists_future.result()

    # Check if suggestions already exist in content cache.
    cache_key = create_content_cache_key(f"suggestions_{time_range}_{result_limit}")
    suggestions = cache.get(cache_key)

    return render_template(
        "stats.html",
        tracks=tracks,
        artists=artists,
        song_limit=result_limit,
        time_range=time_range,
        user=user_profile,
        suggestions=suggestions
    )

# Function to generate similar song and artist recommendations using OpenAI.
def get_similar_recommendations(top_songs, top_artists, result_limit):
    if not top_songs or not top_artists:
        print("No top songs or artists provided")
        return [], []

    # Create sets of existing names for easier comparison.
    existing_songs = {song.lower() for song in top_songs}
    existing_artists = {artist.lower() for artist in top_artists}

    # Request a fixed number of recommendations instead of scaling with result_limit.
    num_recommendations = 10  # Ask for 10 recommendations to ensure we get at least 5 valid ones.

    prompt = f"""
    Based on these songs and artists:
    Songs: {', '.join(top_songs)}
    Artists: {', '.join(top_artists)}

    Please suggest:
    1. Exactly {num_recommendations} similar songs in the format "Song Name - Artist Name"
    2. Exactly {num_recommendations} similar artists

    Important rules:
    - DO NOT suggest any songs or artists already mentioned above (IMPORTANT!!!)
    - MAKE SURE TO REMEMBER DO NOT GIVE REPEATED SONGS OR ARTISTS (IMPORTANT!!!)
    - Only suggest well-known songs and artists that are definitely on Spotify
    - Each suggestion must be unique (IMPORTANT)
    - Suggestions should match the general style/genre of the input songs (leniant)
    - Format songs EXACTLY as "Song Name - Artist Name" with a single hyphen
    - For artist names, use their exact Spotify artist name
    - Ensure they exist on Spotify (IMPORTANT)

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
                "content": "You are a music recommendation assistant specializing in current, popular music. Always use exact Spotify artist names and suggest only songs that definitely exist on Spotify. Format all song suggestions exactly as 'Song Name - Artist Name' with a single hyphen."
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.65,
        max_tokens=1000
    )

    # Parse response with improved error handling.
    content = response.choices[0].message.content
    songs = []
    artists = []
    current_section = None
    
    for line in content.split("\n"):
        line = line.strip()
        
        # Skip empty lines and section headers.
        if not line or line in ["Songs:", "Artists:"]:
            if "Songs:" in line:
                current_section = "songs"
            elif "Artists:" in line:
                current_section = "artists"
            continue
            
        # Remove numbering and extra spaces.
        line = ' '.join(line.split())  # Normalize spaces.
        line = line.lstrip("1234567890. ")
        
        if current_section == "songs":
            if " - " in line:  # Strict hyphen check.
                song_name, artist_name = line.split(" - ", 1)
                if song_name and artist_name:  # Verify both parts exist.
                    songs.append(f"{song_name.strip()} - {artist_name.strip()}")
                    
        elif current_section == "artists" and line:
            artist_name = line.strip()
            if artist_name and not any(artist_name.lower() == existing.lower() for existing in top_artists):
                artists.append(artist_name)

    return songs, artists

# Route to get recommendations: Generates and returns similar songs and artists.
@app.route("/get_recommendations", methods=["POST"])
def get_recommendations():
    try:
        token_info = getToken()
        if not token_info:
            return jsonify({"error": "No Spotify token found"}), 401
        
        access_token = token_info["access_token"]
        sp = spotipy.Spotify(auth=access_token)
        
        time_range = session.get("time_range", "short_term")
        result_limit = session.get("result_limit", 5)
        
        # Check if suggestions already exist for this combination in content cache
        cache_key = create_content_cache_key(f"suggestions_{time_range}_{result_limit}")
        suggestions = cache.get(cache_key)
        
        if suggestions:
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
                    continue  # Skip if the format is invalid.
                
                # Split the recommendation into song and artist.
                if "-" in rec:
                    song_parts = rec.split("-", 1)
                elif "by" in rec:
                    song_parts = rec.split("by", 1)
                
                if len(song_parts) != 2:
                    continue  # Skip if the format is invalid.

                song_name = song_parts[0].strip()
                artist_name = song_parts[1].strip()
                
                # Search for the song using both track and artist name.
                query = f"track:{song_name} artist:{artist_name}"
                results = sp.search(q=query, type="track", limit=5)  # Increase limit to 5 for better results.
                
                if results["tracks"]["items"]:
                    # Find the best match based on popularity.
                    filtered_suggestions = [track for track in results["tracks"]["items"] if track['popularity'] > 40]
                    if filtered_suggestions:  # Ensure there are filtered results.
                        track = filtered_suggestions[0]  # Take the first track.
                        suggested_songs.append({
                            "name": track["name"],
                            "artist": track["artists"][0]["name"],
                            "album_cover": track["album"]["images"][0]["url"] if track["album"]["images"] else None,
                            "spotify_url": track["external_urls"]["spotify"],
                            "preview_url": track.get("preview_url"),
                            "album": track["album"]["name"],
                            "popularity": track["popularity"]  
                        })

                        # Stop if we have enough songs (always 5).
                        if len(suggested_songs) >= 5:
                            break
            except Exception as e:
                continue

        # Look up artists with popularity filter.
        suggested_artists = []
        for artist_name in recommended_artists:
            try:
                results = sp.search(q=artist_name, type="artist", limit=3)  # Increased limit for better matching.
                if results["artists"]["items"]:
                    # Less strict popularity filter (reduced from 40 to 30).
                    filtered_suggestions = [artist for artist in results["artists"]["items"] if artist['popularity'] > 30]
                    if filtered_suggestions:
                        artist = filtered_suggestions[0]
                        suggested_artists.append({
                            "name": artist["name"],
                            "image_url": artist["images"][0]["url"] if artist["images"] else None,
                            "spotify_url": artist["external_urls"]["spotify"],
                            "popularity": artist["popularity"]
                        })
                    else:  # If no artists meet popularity threshold, take the most popular one anyway.
                        artist = max(results["artists"]["items"], key=lambda x: x['popularity'])
                        suggested_artists.append({
                            "name": artist["name"],
                            "image_url": artist["images"][0]["url"] if artist["images"] else None,
                            "spotify_url": artist["external_urls"]["spotify"],
                            "popularity": artist["popularity"]
                        })

                    # Stop if we have enough artists.
                    if len(suggested_artists) >= 5:
                        break
            except Exception as e:
                continue

        # Store suggestions in content cache.
        suggestions = {
            "songs": suggested_songs,
            "artists": suggested_artists
        }
        cache.set(cache_key, suggestions)
        
        return jsonify(suggestions)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500