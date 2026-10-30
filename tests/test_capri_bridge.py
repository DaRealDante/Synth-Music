import json

from app.capri_bridge import CapriBridge, isCapriMessage
from app.database import Database


class FakePlayer:
    def __init__(self):
        self.queue, self.index, self.playing, self.volume, self.shuffle = [], -1, False, 70, False

    def playSongs(self, songs, startIndex=0, shuffled=None):
        self.queue, self.index, self.playing = list(songs), startIndex, True
        if shuffled is not None:
            self.shuffle = shuffled

    def currentSong(self):
        return self.queue[self.index] if 0 <= self.index < len(self.queue) else None

    def isPlaying(self):
        return self.playing

    def play(self):
        self.playing = True

    def pause(self):
        self.playing = False

    def next(self):
        self.index += 1

    def previous(self):
        self.index -= 1

    def setVolume(self, level):
        self.volume = level

    def setShuffle(self, enabled):
        self.shuffle = enabled


class FakeWindow:
    def __init__(self, database):
        self.database, self.player = database, FakePlayer()


def _bridge(tmp_path):
    database = Database(str(tmp_path / "library.db"))
    database.addSong("C:/a.mp3", "Bohemian Rhapsody", "Queen", "A Night at the Opera")
    database.addSong("C:/b.mp3", "Resonance", "HOME", "Odyssey")
    favorite = database.addSong("C:/c.mp3", "I Really Want to Stay at Your House", "Rosa Walton")
    database.toggleFavorite(favorite)
    playlistId = database.createPlaylist("Night City")
    database.addToPlaylist(playlistId, [favorite])
    return CapriBridge(FakeWindow(database))


def _call(bridge, message):
    return json.loads(bridge.handle(message))


def test_detects_messages():
    assert isCapriMessage("capri:play x") and isCapriMessage("CAPRI:now")
    assert not isCapriMessage("show") and not isCapriMessage("ABC123")


def test_play_library_song_and_words_match(tmp_path):
    bridge = _bridge(tmp_path)
    reply = _call(bridge, "capri:play bohemian rhapsody")
    assert reply["ok"] and "Bohemian Rhapsody by Queen" in reply["message"]
    reply = _call(bridge, "capri:play queen rhapsody")
    assert reply["ok"] and "Bohemian" in reply["message"]
    reply = _call(bridge, "capri:play resonance by home")
    assert reply["ok"] and "Resonance" in reply["message"]


def test_play_unknown_song_streams(tmp_path):
    bridge = _bridge(tmp_path)
    reply = _call(bridge, "capri:play some song nobody has")
    assert reply["ok"] and "YouTube" in reply["message"]
    song = bridge.player.currentSong()
    assert song["path"].startswith("stream:ytsearch1:some song nobody has")
    assert song["hidden"] == 1


def test_playlists_and_favorites(tmp_path):
    bridge = _bridge(tmp_path)
    assert "Night City" in _call(bridge, "capri:playlists")["message"]
    reply = _call(bridge, "capri:playlist night city")
    assert reply["ok"] and bridge.player.currentSong()["title"].startswith("I Really")
    assert _call(bridge, "capri:play night city")["message"] == "Playing playlist Night City"
    assert not _call(bridge, "capri:playlist nope")["ok"]
    assert _call(bridge, "capri:favorites")["ok"]


def test_controls_and_volume(tmp_path):
    bridge = _bridge(tmp_path)
    assert _call(bridge, "capri:now")["message"] == "Nothing is loaded"
    assert "Shuffling" in _call(bridge, "capri:resume")["message"]
    assert _call(bridge, "capri:pause")["message"] == "Paused"
    assert not bridge.player.playing
    _call(bridge, "capri:toggle")
    assert bridge.player.playing
    assert _call(bridge, "capri:volume 30")["message"] == "Volume 30"
    assert _call(bridge, "capri:volume +15")["message"] == "Volume 45"
    bridge.player.volume = 45
    assert _call(bridge, "capri:volume -100")["message"] == "Volume 0"
    assert not _call(bridge, "capri:volume loud")["ok"]
    assert not _call(bridge, "capri:dance")["ok"]
    assert _call(bridge, "capri:shuffle off")["message"] == "Shuffle off"
