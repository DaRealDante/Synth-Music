"""Reads public Apple Music playlist / album / song links (no account needed) into the same track list
format used by the Spotify import, so the tracks are matched on YouTube exactly the same way."""
import html
import json
import re
import urllib.parse
import urllib.request

_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/126.0 Safari/537.36")


def isAppleMusicUrl(text):
    text = (text or "").strip().lower()
    return bool(re.match(r"^(https?://)?(music|itunes|geo\.music)\.apple\.com/", text))


def parseUrl(url):
    """("playlist" | "album" | "song", songId or None) from an Apple Music link."""
    parsed = urllib.parse.urlparse(url.strip() if "://" in url else "https://" + url.strip())
    parts = [part for part in parsed.path.split("/") if part]
    query = urllib.parse.parse_qs(parsed.query)
    songId = (query.get("i") or [None])[0]
    for kind in ("playlist", "album", "song"):
        if kind in parts:
            if kind == "album" and songId:
                return "song", songId
            if kind == "song":
                return "song", parts[-1] if parts[-1].isdigit() else songId
            return kind, None
    raise RuntimeError("Link non supportato: usa il link di una playlist, di un album o di un brano Apple Music")


def _fetchPage(url):
    if "://" not in url:
        url = "https://" + url
    request = urllib.request.Request(url.strip(), headers={"User-Agent": _USER_AGENT, "Accept-Language": "it-IT,it;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


# ---------- parsing ----------
def _scripts(page, attribute, value):
    pattern = rf"<script[^>]*{attribute}=[\"']{re.escape(value)}[\"'][^>]*>(.*?)</script>"
    return re.findall(pattern, page, re.IGNORECASE | re.DOTALL)


def _meta(page, name):
    """All values of <meta property|name="name" content="...">, in page order."""
    values = []
    for tag in re.findall(r"<meta\b[^>]*>", page, re.IGNORECASE):
        key = re.search(r"(?:property|name)=[\"']([^\"']+)[\"']", tag, re.IGNORECASE)
        content = re.search(r"content=[\"']([^\"']*)[\"']", tag, re.IGNORECASE)
        if key and content and key.group(1).lower() == name.lower():
            values.append(html.unescape(content.group(1)))
    return values


def _isoSeconds(duration):
    match = re.fullmatch(r"P(?:T)?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", str(duration or "").strip(), re.IGNORECASE)
    if not match:
        return 0
    hours, minutes, seconds = match.groups()
    return int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0)


def _artworkUrl(artwork, size=600):
    if not isinstance(artwork, dict):
        return None
    template = artwork.get("url") or (artwork.get("dictionary") or {}).get("url")
    if not template:
        return None
    return (template.replace("{w}", str(size)).replace("{h}", str(size)).replace("{c}", "bb")
            .replace("{f}", "jpg").replace("{q}", ""))


def _songId(item):
    descriptor = item.get("contentDescriptor") or {}
    identifiers = descriptor.get("identifiers") or {}
    return str(identifiers.get("storeAdamID") or descriptor.get("id") or item.get("id") or "") or None


def _isSong(item):
    if not isinstance(item.get("title"), str) or not isinstance(item.get("artistName"), str):
        return False
    descriptor = item.get("contentDescriptor") or {}
    kind = str(descriptor.get("kind") or item.get("kind") or item.get("type") or "").lower()
    if kind:
        return kind in ("song", "songs", "musicvideo", "music-videos", "musicvideos")
    return isinstance(item.get("duration"), (int, float))


def _walk(node, found):
    if isinstance(node, dict):
        if _isSong(node):
            found.append(node)
            return
        for value in node.values():
            _walk(value, found)
    elif isinstance(node, list):
        for value in node:
            _walk(value, found)


def _tracksFromServerData(page):
    found = []
    for raw in _scripts(page, "id", "serialized-server-data"):
        try:
            _walk(json.loads(html.unescape(raw)), found)
        except ValueError:
            continue
    tracks, seen = [], set()
    for item in found:
        key = _songId(item) or (item["title"].lower(), item["artistName"].lower())
        if key in seen:
            continue
        seen.add(key)
        duration = item.get("duration") or item.get("durationInMillis") or 0
        tracks.append({"id": _songId(item), "title": item["title"].strip(), "artist": item["artistName"].strip(),
                       "album": str(item.get("albumName") or item.get("tertiaryTitle") or ""),
                       "durationMs": int(duration if duration > 10000 else duration * 1000),
                       "image": _artworkUrl(item.get("artwork"))})
    return tracks


def _tracksFromLinkedData(page):
    tracks = []
    for raw in _scripts(page, "type", "application/ld+json"):
        try:
            data = json.loads(html.unescape(raw))
        except ValueError:
            continue
        for block in data if isinstance(data, list) else [data]:
            if not isinstance(block, dict):
                continue
            items = block.get("track") or (block.get("tracks") if isinstance(block.get("tracks"), list) else None) or []
            if isinstance(items, dict):
                items = items.get("itemListElement") or [items]
            albumArtist = block.get("byArtist")
            for item in items:
                item = item.get("item", item) if isinstance(item, dict) else None
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                artist = item.get("byArtist") or albumArtist
                if isinstance(artist, list):
                    artist = ", ".join(entry.get("name", "") for entry in artist if isinstance(entry, dict))
                elif isinstance(artist, dict):
                    artist = artist.get("name", "")
                songId = re.search(r"[?&]i=(\d+)|/song/[^/]+/(\d+)", str(item.get("url") or ""))
                tracks.append({"id": next((group for group in songId.groups() if group), None) if songId else None,
                               "title": html.unescape(str(item["name"])).strip(), "artist": str(artist or "").strip(),
                               "album": "", "durationMs": int(_isoSeconds(item.get("duration")) * 1000), "image": None})
    return tracks


def _tracksFromMeta(page):
    """Last resort: the standard music:song tags (title from the song link, no artist)."""
    tracks = []
    durations = _meta(page, "music:song:duration")
    for index, songUrl in enumerate(_meta(page, "music:song")):
        match = re.search(r"/song/([^/?#]+)/(\d+)", songUrl) or re.search(r"/album/([^/?#]+)/\d+\?i=(\d+)", songUrl)
        if not match:
            continue
        title = urllib.parse.unquote(match.group(1)).replace("-", " ").strip()
        seconds = _isoSeconds(durations[index]) if index < len(durations) else 0
        tracks.append({"id": match.group(2), "title": title, "artist": "", "album": "", "durationMs": int(seconds * 1000), "image": None})
    return tracks


def _cleanTitle(title):
    # "Today's Hits - Playlist - Apple Music" / "‎Album di X su Apple Music" -> name only
    title = html.unescape(title or "").replace("‎", "").strip()
    title = re.sub(r"\s+(su|on|sur|en|auf)\s+Apple\s*Music$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*[-–|]\s*Apple\s*Music$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*[-–]\s*(Playlist|Album|Single|EP|Song|Brano)$", "", title, flags=re.IGNORECASE)
    return title.strip()


def parsePage(page, url):
    kind, songId = parseUrl(url)
    tracks = _tracksFromServerData(page)
    if not tracks or not any(track["artist"] for track in tracks):
        tracks = _tracksFromLinkedData(page) or tracks or _tracksFromMeta(page)
    if kind == "song":
        chosen = [track for track in tracks if songId and track["id"] == str(songId)]
        tracks = chosen or tracks[:1]
    name = _cleanTitle((_meta(page, "og:title") or [""])[0]) or ("Brano Apple Music" if kind == "song" else "Playlist Apple Music")
    description = html.unescape((_meta(page, "og:description") or [""])[0]).strip()
    if kind == "album" and tracks and tracks[0]["artist"]:
        description = f"Album di {tracks[0]['artist']}"
    image = (_meta(page, "og:image") or [None])[0]
    infoTracks = []
    for index, track in enumerate(tracks):
        artists = [part.strip() for part in re.split(r",| & ", track["artist"]) if part.strip()]
        infoTracks.append({
            "spotifyId": f"apple:{track['id'] or index}",
            "title": track["title"],
            "artist": track["artist"],
            "mainArtist": artists[0] if artists else "",
            "album": track["album"] or (name if kind == "album" else ""),
            "durationMs": track["durationMs"],
            "image": track["image"] or (image if kind != "playlist" else None),
            "playlistIndex": index,
            "source": "Apple Music",
        })
    return {"kind": "track" if kind == "song" else kind, "source": "Apple Music", "name": name if kind != "song" else (tracks[0]["title"] if tracks else name),
            "description": description if kind != "playlist" else (description or "Importata da Apple Music"),
            "image": image, "tracks": [track for track in infoTracks if track["title"]]}


def fetchAppleMusic(url):
    info = parsePage(_fetchPage(url), url)
    if not info["tracks"]:
        raise RuntimeError("non trovo brani: la playlist è vuota, privata o la pagina è cambiata")
    info["coverPath"] = None
    if info.get("image") and info["kind"] != "track":
        try:
            from . import metadata
            from .downloader import fetchBytes
            info["coverPath"] = metadata.saveCoverBytes(fetchBytes(info["image"]))
        except Exception:
            pass
    return info
