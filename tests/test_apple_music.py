import json

import pytest

from app import apple_music


def _serverData(items, header="Hit di oggi"):
    data = [{"intent": {"$kind": "PlaylistDetailPageIntent"},
             "data": {"sections": [
                 {"itemKind": "containerDetailHeaderLockup", "items": [{"title": header, "artwork": {}}]},
                 {"itemKind": "trackLockup", "items": items},
             ]}}]
    return f'<script type="application/json" id="serialized-server-data">{json.dumps(data)}</script>'


def _song(adamId, title, artist, durationMs=200000, album="Disco"):
    return {"title": title, "artistName": artist, "duration": durationMs, "albumName": album,
            "artwork": {"dictionary": {"url": "https://is1-ssl.mzstatic.com/image/{w}x{h}{c}.{f}"}},
            "contentDescriptor": {"kind": "song", "identifiers": {"storeAdamID": adamId}}}


def _page(body):
    return ('<html><head><meta property="og:title" content="Hit di oggi - Playlist - Apple Music">'
            '<meta property="og:description" content="Le canzoni del momento.">'
            '<meta property="og:image" content="https://example.com/cover.jpg"></head><body>' + body + "</body></html>")


def test_recognisesAppleMusicLinks():
    assert apple_music.isAppleMusicUrl("https://music.apple.com/it/playlist/hit/pl.abc")
    assert apple_music.isAppleMusicUrl("music.apple.com/us/album/x/123?i=456")
    assert not apple_music.isAppleMusicUrl("https://open.spotify.com/playlist/abc")
    assert apple_music.parseUrl("https://music.apple.com/it/playlist/hit/pl.abc") == ("playlist", None)
    assert apple_music.parseUrl("https://music.apple.com/it/album/disco/123") == ("album", None)
    assert apple_music.parseUrl("https://music.apple.com/it/album/disco/123?i=456") == ("song", "456")
    assert apple_music.parseUrl("https://music.apple.com/it/song/titolo/789") == ("song", "789")
    with pytest.raises(RuntimeError):
        apple_music.parseUrl("https://music.apple.com/it/artist/qualcuno/1")


def test_playlistFromServerData():
    page = _page(_serverData([_song("1", "Prima", "Artista A & Artista B"), _song("2", "Seconda", "Artista C", 180),
                              _song("1", "Prima", "Artista A & Artista B")]))
    info = apple_music.parsePage(page, "https://music.apple.com/it/playlist/hit/pl.abc")
    assert info["kind"] == "playlist" and info["source"] == "Apple Music"
    assert info["name"] == "Hit di oggi" and info["description"] == "Le canzoni del momento."
    assert [track["title"] for track in info["tracks"]] == ["Prima", "Seconda"]
    first, second = info["tracks"]
    assert first["mainArtist"] == "Artista A" and first["artist"] == "Artista A & Artista B"
    assert first["durationMs"] == 200000 and second["durationMs"] == 180000
    assert first["image"] == "https://is1-ssl.mzstatic.com/image/600x600bb.jpg"
    assert first["spotifyId"] == "apple:1" and second["playlistIndex"] == 1


def test_singleSongPicksTheLinkedTrack():
    page = _page(_serverData([_song("1", "Prima", "A"), _song("2", "Seconda", "B")]))
    info = apple_music.parsePage(page, "https://music.apple.com/it/album/disco/99?i=2")
    assert info["kind"] == "track" and [track["title"] for track in info["tracks"]] == ["Seconda"]


def test_fallsBackToLinkedDataThenMetaTags():
    linked = {"@type": "MusicAlbum", "name": "Disco", "byArtist": {"name": "Band"},
              "tracks": [{"@type": "MusicRecording", "name": "Uno", "duration": "PT3M20S",
                          "url": "https://music.apple.com/it/album/disco/9?i=11"}]}
    page = _page(f'<script type="application/ld+json">{json.dumps(linked)}</script>')
    info = apple_music.parsePage(page, "https://music.apple.com/it/album/disco/9")
    assert info["tracks"][0]["title"] == "Uno" and info["tracks"][0]["artist"] == "Band"
    assert info["tracks"][0]["durationMs"] == 200000 and info["description"] == "Album di Band"

    page = _page('<meta property="music:song" content="https://music.apple.com/it/song/bella-canzone/123">'
                 '<meta property="music:song:duration" content="PT2M5S">')
    info = apple_music.parsePage(page, "https://music.apple.com/it/playlist/hit/pl.abc")
    assert info["tracks"][0]["title"] == "bella canzone" and info["tracks"][0]["durationMs"] == 125000


def test_cleanTitle():
    assert apple_music._cleanTitle("‎Folklore di Taylor Swift su Apple Music") == "Folklore di Taylor Swift"
    assert apple_music._cleanTitle("Today&#39;s Hits - Playlist - Apple Music") == "Today's Hits"


def test_youtubeMusicLinksBecomeYoutubePlaylists():
    from app import downloader
    assert downloader.isYoutubeMusicUrl("https://music.youtube.com/playlist?list=PLabc")
    assert downloader.normalizeYoutubeMusicUrl("https://music.youtube.com/playlist?list=PLabc&si=x") == "https://www.youtube.com/playlist?list=PLabc"
    assert downloader.normalizeYoutubeMusicUrl("https://music.youtube.com/browse/VLPLxyz") == "https://www.youtube.com/playlist?list=PLxyz"
    assert downloader.normalizeYoutubeMusicUrl("https://music.youtube.com/browse/MPREb_123") == "https://music.youtube.com/browse/MPREb_123"
    assert downloader.normalizeYoutubeMusicUrl("https://www.youtube.com/playlist?list=PL1") == "https://www.youtube.com/playlist?list=PL1"
    with pytest.raises(RuntimeError):
        downloader.normalizeYoutubeMusicUrl("https://music.youtube.com/playlist?list=LM")
