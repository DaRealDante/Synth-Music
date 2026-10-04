import json
import os
import shutil
import sys

APP_NAME = "Synth Music"
VERSION = "1.5.0"
UPDATE_REPO = "DaRealDante/Synth-Music"  # "utente/repository" su GitHub: lo compila da solo PUBBLICA_AGGIORNAMENTO.bat

AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".webm"}
IMAGE_FILTER = "Immagini (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"


def resourceDir():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dataRoot():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        newPath, oldPath = os.path.join(base, "SynthMusic"), os.path.join(base, "KenMusic")
    else:
        base = os.path.expanduser("~")
        newPath, oldPath = os.path.join(base, ".synthmusic"), os.path.join(base, ".kenmusic")
    # Ken Music -> Synth Music: keep using the old folder so playlists, songs and paths keep working
    if not os.path.isdir(newPath) and os.path.isfile(os.path.join(oldPath, "library.db")):
        return oldPath
    return newPath


DATA_DIR = _dataRoot()
COVERS_DIR = os.path.join(DATA_DIR, "covers")
TEMP_DIR = os.path.join(DATA_DIR, "temp")
DB_PATH = os.path.join(DATA_DIR, "library.db")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
DEFAULT_MUSIC_DIR = os.path.join(DATA_DIR, "music")

for folderPath in (DATA_DIR, COVERS_DIR, TEMP_DIR, DEFAULT_MUSIC_DIR):
    os.makedirs(folderPath, exist_ok=True)


DEFAULT_SETTINGS = {
    "volume": 70,
    "muted": False,
    "repeatMode": 0,
    "shuffle": False,
    "playbackRate": 1.0,
    "musicDir": DEFAULT_MUSIC_DIR,
    "audioQuality": "192",
    "copyImported": False,
    "lastSongId": None,
    "lastPosition": 0,
    "lastQueue": [],
    "searchResults": 25,
    "windowGeometry": None,
    "rightPanelVisible": False,
    "eqEnabled": False,
    "eqGains": None,
    "eqPreamp": 0.0,
    "eqBalance": 0,
    "eqPreset": "Piatto",
    "eqCustomPresets": {},
    "autoVideo": True,
    "autoLyrics": True,
    "videoQuality": "720",
    "nowPlayingMode": "lyrics",
    "ambientVideo": True,
    "ambientMode": None,
    "pauseVideoInBackground": True,
    "autoCheckUpdates": True,
    "skippedVersion": "",
}


class Settings:
    def __init__(self):
        self.values = dict(DEFAULT_SETTINGS)
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as settingsFile:
                self.values.update(json.load(settingsFile))
        except (OSError, ValueError):
            pass
        os.makedirs(self.musicDir(), exist_ok=True)

    def get(self, key, default=None):
        return self.values.get(key, DEFAULT_SETTINGS.get(key, default))

    def set(self, key, value):
        self.values[key] = value

    def musicDir(self):
        folderPath = self.values.get("musicDir") or DEFAULT_MUSIC_DIR
        try:
            os.makedirs(folderPath, exist_ok=True)
        except OSError:
            folderPath = DEFAULT_MUSIC_DIR
        return folderPath

    def save(self):
        tempPath = SETTINGS_PATH + ".tmp"
        with open(tempPath, "w", encoding="utf-8") as settingsFile:
            json.dump(self.values, settingsFile, indent=2)
        os.replace(tempPath, SETTINGS_PATH)


settings = Settings()


def ffmpegExe():
    bundled = os.path.join(resourceDir(), "bin", "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if os.path.isfile(bundled):
        return bundled
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def denoExe():
    bundled = os.path.join(resourceDir(), "bin", "deno.exe" if sys.platform == "win32" else "deno")
    if os.path.isfile(bundled):
        return bundled
    try:
        import deno
        return deno.find_deno_bin()
    except Exception:
        return shutil.which("deno")
