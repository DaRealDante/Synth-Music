import functools
import http.server
import os
import subprocess
import tempfile
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtMultimedia import QMediaPlayer

from app.config import ffmpegExe


@pytest.fixture(scope="module")
def application():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture(scope="module")
def httpAudio():
    folder = tempfile.mkdtemp()
    subprocess.run([ffmpegExe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                    os.path.join(folder, "tone.mp3")], check=True)
    handler = functools.partial(QuietHandler, directory=folder)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/tone.mp3"
    server.shutdown()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass


def waitFor(application, condition, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        application.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_engineDecodesHttpSource(application, httpAudio):
    from app.audio_engine import AudioEngine
    engine = AudioEngine()
    statuses = []
    engine.mediaStatusChanged.connect(statuses.append)
    engine.durationHintMs = 6000
    engine.setSource(QUrl(httpAudio))
    assert engine.duration() == 6000
    assert waitFor(application, lambda: QMediaPlayer.BufferedMedia in statuses)
    assert abs(engine.duration() - 6000) < 150
    engine.shutdown()


def makePlayerWithStreamSong(resolver, songs):
    from app.player import Player
    player = Player()
    player.streamResolver = resolver
    player.restoreSession(songs, 0, 0)
    return player


def test_playerLoadsStreamSongWithStartPosition(application, httpAudio):
    calls = []

    def resolver(target, useCache=True):
        calls.append((target, useCache))
        return {"url": httpAudio, "headers": {"User-Agent": "test"}, "duration": 6}

    song = {"id": 1, "path": "stream:https://www.youtube.com/watch?v=abcdefghijk", "title": "Tono", "duration": 6}
    loadingStates, loaded = [], []
    from app.player import Player
    player = Player()
    player.streamResolver = resolver
    player.loadingChanged.connect(loadingStates.append)
    player.songLoaded.connect(loaded.append)
    player.restoreSession([song], 0, 2500)
    assert player.loading
    assert waitFor(application, lambda: loaded)
    assert loadingStates == [True, False]
    assert calls == [("https://www.youtube.com/watch?v=abcdefghijk", True)]
    assert player.mediaPlayer.source().toString() == httpAudio
    assert player.mediaPlayer.sourceHeaders == {"User-Agent": "test"}
    assert waitFor(application, lambda: player.position() == 2500)
    player.shutdown()


def test_resolverFailureReportsErrorAndSkips(application, httpAudio):
    def resolver(target, useCache=True):
        if "bad" in target:
            raise RuntimeError("video non disponibile")
        return {"url": httpAudio, "headers": {}, "duration": 6}

    songs = [{"id": 1, "path": "stream:https://youtu.be/bad", "title": "Rotta", "duration": 6},
             {"id": 2, "path": "stream:https://youtu.be/ok", "title": "Buona", "duration": 6}]
    from app.player import Player
    player = Player()
    player.streamResolver = resolver
    errors = []
    player.playbackError.connect(errors.append)
    player.playSongs(songs, 0)
    assert waitFor(application, lambda: player.currentIndex == 1 and not player.loading)
    assert errors and "Streaming non disponibile" in errors[0]
    player.shutdown()


def test_togglePlayWhileLoadingDoesNotRestartResolve(application, httpAudio):
    calls = []

    def resolver(target, useCache=True):
        calls.append(target)
        time.sleep(0.3)
        return {"url": httpAudio, "headers": {}, "duration": 6}

    from app.player import Player
    player = Player()
    player.streamResolver = resolver
    player.restoreSession([{"id": 5, "path": "stream:https://youtu.be/x", "title": "X", "duration": 6}], 0, 0)
    player.togglePlay()
    assert player.loadAutoplay is True
    player.togglePlay()
    assert player.loadAutoplay is False
    assert waitFor(application, lambda: not player.loading)
    assert len(calls) == 1
    player.shutdown()


def test_playAfterFailedStartupResolveRetries(application, httpAudio):
    attempts = []

    def resolver(target, useCache=True):
        attempts.append(target)
        if len(attempts) == 1:
            raise RuntimeError("offline")
        return {"url": httpAudio, "headers": {}, "duration": 6}

    from app.player import Player
    player = Player()
    player.streamResolver = resolver
    player.restoreSession([{"id": 9, "path": "stream:https://youtu.be/z", "title": "Z", "duration": 6}], 0, 0)
    assert waitFor(application, lambda: not player.loading and attempts)
    player.togglePlay()
    assert waitFor(application, lambda: len(attempts) == 2 and not player.loading)
    assert player.mediaPlayer.source().toString() == httpAudio
    player.shutdown()
