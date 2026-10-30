"""Capri voice-assistant bridge.

Capri talks to Synth through the existing single-instance pipe (\\\\.\\pipe\\SynthMusic-<user>).
Messages that start with "capri:" are handled here instead of being treated as share links,
they never bring the window to the front (so a game in focus is not interrupted), and the
answer is written back on the same connection as one line of JSON: {"ok": bool, "message": str}.

Commands:
    capri:ping
    capri:play [query]          query empty = resume (or shuffle the library if nothing is loaded)
    capri:pause | capri:resume | capri:toggle | capri:next | capri:previous
    capri:volume <0-100 | +N | -N>
    capri:shuffle <on|off>
    capri:playlist <name>
    capri:favorites
    capri:playlists
    capri:now
"""

import json
import re

PREFIX = "capri:"


def isCapriMessage(message):
    return isinstance(message, str) and message.strip().lower().startswith(PREFIX)


def _normalize(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _songLabel(song):
    if not song:
        return ""
    title = song.get("title") or "Unknown"
    artist = song.get("artist") or ""
    return f"{title} by {artist}" if artist else title


class CapriBridge:
    """`window` must expose: database (Database), player (Player) and optionally playSongs()."""

    def __init__(self, window):
        self.window = window

    @property
    def database(self):
        return self.window.database

    @property
    def player(self):
        return self.window.player

    # ---- entry point -------------------------------------------------------------------------
    def handle(self, message):
        try:
            ok, text = self._dispatch(message.strip()[len(PREFIX):].strip())
        except Exception as error:  # never let a voice command crash the player
            ok, text = False, f"Synth error: {error}"
        return json.dumps({"ok": ok, "message": text})

    def _dispatch(self, body):
        command, _, argument = body.partition(" ")
        command = command.lower()
        argument = argument.strip()
        handlers = {
            "ping": lambda: (True, "pong"),
            "play": lambda: self.play(argument),
            "pause": self.pause,
            "resume": self.resume,
            "toggle": self.toggle,
            "next": self.next,
            "previous": self.previous,
            "volume": lambda: self.volume(argument),
            "shuffle": lambda: self.shuffle(argument),
            "playlist": lambda: self.playlist(argument),
            "favorites": self.favorites,
            "playlists": self.listPlaylists,
            "now": self.nowPlaying,
        }
        handler = handlers.get(command)
        if handler is None:
            return False, f"Unknown command '{command}'"
        return handler()

    # ---- playback ----------------------------------------------------------------------------
    def _playSongs(self, songs, shuffled=None):
        songs = [song for song in songs if song]
        if not songs:
            return False
        if hasattr(self.window, "playSongs"):
            self.window.playSongs(songs, 0, shuffled=shuffled)
        else:
            self.player.playSongs(songs, 0, shuffled=shuffled)
        return True

    def play(self, query):
        if not query:
            return self.resume()
        playlist = self._findPlaylist(query)
        if playlist is not None and _normalize(playlist.get("name")) == _normalize(query):
            return self.playlist(query)
        songs = self.findSongs(query)
        if songs:
            self._playSongs(songs, shuffled=False)
            extra = f" and {len(songs) - 1} more from your library" if len(songs) > 1 else ""
            return True, f"Playing {_songLabel(songs[0])}{extra}"
        if playlist is not None:
            return self.playlist(playlist.get("name"))
        # Not in the library: add a hidden streaming entry; Synth resolves it on YouTube when it loads.
        songId = self.database.addStreamSong(f"ytsearch1:{query} audio", query, "", hidden=True)
        song = self.database.getSong(songId)
        self._playSongs([song], shuffled=False)
        return True, f"Not in your library, streaming '{query}' from YouTube"

    def findSongs(self, query):
        """Library songs matching the query: direct LIKE first, then every word across title/artist/album."""
        query = query.strip()
        direct = list(self.database.searchSongs(query))
        if direct:
            return direct
        for separator in (" by ", " - ", " di "):
            if separator in query.lower():
                index = query.lower().index(separator)
                title, artist = query[:index].strip(), query[index + len(separator):].strip()
                found = self.database.findSong(title, artist)
                if found:
                    return [found]
        words = [word for word in _normalize(query).split() if len(word) > 1]
        if not words:
            return []
        matches = []
        for song in self.database.allSongs():
            if song.get("hidden"):
                continue
            haystack = _normalize(f"{song.get('title')} {song.get('artist')} {song.get('album')}")
            if all(word in haystack for word in words):
                matches.append(song)
        return matches

    def pause(self):
        self.player.pause()
        return True, "Paused"

    def resume(self):
        if self.player.currentSong() is None:
            songs = [song for song in self.database.allSongs() if not song.get("hidden")]
            if not songs:
                return False, "Your library is empty"
            self._playSongs(songs, shuffled=True)
            return True, "Shuffling your library"
        self.player.play()
        return True, f"Resuming {_songLabel(self.player.currentSong())}"

    def toggle(self):
        if self.player.isPlaying():
            return self.pause()
        return self.resume()

    def next(self):
        self.player.next()
        return True, "Skipped"

    def previous(self):
        self.player.previous()
        return True, "Going back"

    def volume(self, argument):
        match = re.fullmatch(r"([+-]?)\s*(\d{1,3})", argument or "")
        if not match:
            return False, "Volume needs a number from 0 to 100, or +N / -N"
        sign, amount = match.group(1), int(match.group(2))
        current = getattr(self.player, "volume", 70)
        level = current + amount if sign == "+" else current - amount if sign == "-" else amount
        level = max(0, min(100, level))
        self.player.setVolume(level)
        return True, f"Volume {level}"

    def shuffle(self, argument):
        enabled = (argument or "on").lower() in ("on", "true", "1", "yes")
        self.player.setShuffle(enabled)
        return True, "Shuffle on" if enabled else "Shuffle off"

    # ---- playlists ---------------------------------------------------------------------------
    def _findPlaylist(self, name):
        wanted = _normalize(name)
        if not wanted:
            return None
        playlists = list(self.database.playlists())
        for playlist in playlists:
            if _normalize(playlist.get("name")) == wanted:
                return playlist
        for playlist in playlists:
            normalized = _normalize(playlist.get("name"))
            if normalized and (wanted in normalized or normalized in wanted):
                return playlist
        return None

    def playlist(self, name):
        playlist = self._findPlaylist(name)
        if playlist is None:
            names = ", ".join(item.get("name") for item in self.database.playlists()) or "none"
            return False, f"No playlist called '{name}'. Your playlists: {names}"
        songs = list(self.database.playlistSongs(playlist["id"]))
        if not songs:
            return False, f"Playlist '{playlist.get('name')}' is empty"
        self._playSongs(songs)
        return True, f"Playing playlist {playlist.get('name')}"

    def favorites(self):
        songs = list(self.database.favoriteSongs())
        if not songs:
            return False, "You have no favorite songs yet"
        self._playSongs(songs, shuffled=True)
        return True, "Shuffling your favorites"

    def listPlaylists(self):
        playlists = list(self.database.playlists())
        if not playlists:
            return True, "You have no playlists"
        return True, "Playlists: " + ", ".join(f"{item.get('name')} ({item.get('songCount', 0)} songs)" for item in playlists)

    def nowPlaying(self):
        song = self.player.currentSong()
        if song is None:
            return True, "Nothing is loaded"
        state = "Playing" if self.player.isPlaying() else "Paused on"
        return True, f"{state} {_songLabel(song)}"
