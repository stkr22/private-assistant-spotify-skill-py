import spotipy
from spotipy.oauth2 import SpotifyOAuth

sp = spotipy.Spotify(
    auth_manager=SpotifyOAuth(
        client_id="SPOTIFY_CLIENT_ID",
        client_secret="SPOTIFY_CLIENT_SECRET",
        redirect_uri="http://localhost:8888/callback",
        scope="user-read-playback-state user-modify-playback-state playlist-read-private",
    )
)
playlists = sp.user_playlists("spotify")
