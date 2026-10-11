import time

import pytest
from PySide6.QtWidgets import QApplication, QMenu


@pytest.fixture(scope="module")
def window():
    application = QApplication.instance() or QApplication([])
    from app.ui import theme
    application.setStyleSheet(theme.STYLESHEET)
    from app.ui.main_window import MainWindow
    mainWindow = MainWindow()
    yield mainWindow
    mainWindow.player.shutdown()


def pump(seconds=0.3):
    deadline = time.time() + seconds
    while time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


def waitFor(condition, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_addStreamEntriesCreatesStreamSongs(window, monkeypatch):
    from app import downloader
    monkeypatch.setattr(downloader, "streamSongInfo", lambda entry: {
        "url": entry["url"], "title": entry["title"], "artist": "Artista", "album": "", "duration": 100, "cover": None})
    playlistId = window.database.createPlaylist("Test streaming")
    window.addStreamEntries([{"url": "https://www.youtube.com/watch?v=aaaaaaaaaaa", "title": "Uno"},
                             {"url": "https://www.youtube.com/watch?v=bbbbbbbbbbb", "title": "Due"}], playlistId)
    assert waitFor(lambda: len(window.database.playlistSongs(playlistId)) == 2)
    paths = [song["path"] for song in window.database.playlistSongs(playlistId)]
    assert paths == ["stream:https://www.youtube.com/watch?v=aaaaaaaaaaa", "stream:https://www.youtube.com/watch?v=bbbbbbbbbbb"]


def captureMenu(monkeypatch):
    captured = {}

    class RecordingMenu(QMenu):
        def exec(self, *args):
            captured["actions"] = [action.text() for action in self.actions()]
            return None

    from app.ui import main_window
    monkeypatch.setattr(main_window, "QMenu", RecordingMenu)
    return captured


def test_streamSongMenuHasDownloadAndNoCut(window, monkeypatch):
    song = window.database.findSongByUrl("https://www.youtube.com/watch?v=aaaaaaaaaaa")
    captured = captureMenu(monkeypatch)
    window.showSongMenu([song], None, {})
    assert "Scarica sul PC" in captured["actions"]
    assert "Taglia audio..." not in captured["actions"]
    assert "Mostra nella cartella" not in captured["actions"]


def test_cutOnStreamSongShowsMessage(window):
    song = window.database.findSongByUrl("https://www.youtube.com/watch?v=aaaaaaaaaaa")
    window.openCutDialog(song)
    assert "streaming" in window.toast.text()


def test_downloadReplacesStreamSong(window, tmp_path):
    song = window.database.findSongByUrl("https://www.youtube.com/watch?v=bbbbbbbbbbb")
    filePath = tmp_path / "Artista - Due.mp3"
    filePath.write_bytes(b"x")
    window._onSongDownloaded({"path": str(filePath), "title": "Due", "artist": "Artista", "album": "", "duration": 100,
                              "cover": None, "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb", "replaceSongId": song["id"]}, None)
    updated = window.database.getSong(song["id"])
    assert updated["path"] == str(filePath)
    assert len([row for row in window.database.allSongs() if row["url"] == song["url"]]) == 1


def test_hiddenSongSavedWhenAddedToPlaylist(window):
    hiddenId = window.database.addStreamSong("https://youtu.be/ccccccccccc", "Amico", "", "", 1, None, hidden=True)
    playlistId = window.database.createPlaylist("Mia")
    window.addToPlaylist(playlistId, [hiddenId])
    assert window.database.getSong(hiddenId)["hidden"] == 0
