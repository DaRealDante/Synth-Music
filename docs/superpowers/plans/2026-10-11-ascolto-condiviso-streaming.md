# Ascolto condiviso, playlist condivise e streaming — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Streaming YouTube senza download, stanze "Ascolta insieme" multi-persona con profili, playlist condivise sincronizzate — tutto via codice/link.

**Architecture:** Canzoni in streaming = righe `songs` con `path = "stream:<url o ytsearch1:query>"`, risolte da yt-dlp al momento del play e decodificate da ffmpeg via HTTP. Trasporto: un solo client `paho-mqtt` (TLS) verso broker pubblici con failover; ogni stanza/playlist ha topic derivato dall'hash del codice e messaggi cifrati+firmati con chiave dal codice. Logica di sync (stato stanza, orologio, merge playlist) in moduli puri testabili senza Qt/rete.

**Tech Stack:** Python 3.12, PySide6, yt-dlp, ffmpeg, paho-mqtt 2.x, sqlite3, pytest (+ mosquitto locale per i test d'integrazione).

**Spec:** `docs/superpowers/specs/2026-10-11-ascolto-condiviso-streaming-design.md`

## Global Constraints
- Nessuna funzione esistente tolta o cambiata: fuori da una stanza e senza playlist condivise l'app si comporta come la 1.6.2
- Stile codice del progetto: camelCase descrittivo, niente commenti superflui, testi UI in italiano
- Codici: stanza `SYNTH-XXXX-XXXX`, playlist `SYNTHP-XXXX-XXXX`, alfabeto `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`; link `synthmusic://join/<codice>`
- Broker (in ordine): `broker.hivemq.com:8883`, `broker.emqx.io:8883`, `test.mosquitto.org:8886`; override con env `SYNTH_BROKERS="host:port:tls,..."` (per i test)
- Topic: `synthmusic/v1/r/<sha256(codice)[:24]>/…` (stanze), `synthmusic/v1/p/<…>/snapshot` (playlist)
- Sync: correzione se sfasato > 700 ms; foto profilo 96×96 JPEG ≤ 12 KB
- Versione finale 1.7.0 (unico rilascio, i 3 step sono task interni)

## Review Focus
- Stream scaduto/irraggiungibile o offline → toast, nessun crash, la coda va avanti (Task 2)
- Canzone in streaming usata da funzioni che vogliono un file (taglia, esporta effetti, mostra cartella, waveform, tag) → messaggio "Scarica prima la canzone", niente crash (Task 3)
- Messaggi estranei/corrotti/di un'altra stanza sul broker → scartati in silenzio (Task 4)
- Due persone premono comandi quasi insieme → convergono allo stesso stato (Task 5)
- Playlist modificata da due persone offline → unione senza perdite né duplicati (Task 7)

---

### Task 1: Database — canzoni stream, nascoste, playlist condivise
**Files:** Modify `app/database.py`; Test `tests/test_database_stream.py`
**Produces:** colonne songs `hidden INTEGER DEFAULT 0`; tabella `sharedPlaylists(playlistId INTEGER PRIMARY KEY REFERENCES playlists(id) ON DELETE CASCADE, code TEXT, snapshot TEXT)`; `isStreamPath(path) -> bool`; `Database.findSongByUrl(url) -> dict|None`; `Database.addStreamSong(url, title, artist, album, duration, cover, hidden=False) -> int`; `Database.setShared(playlistId, code, snapshot)`, `sharedPlaylist(playlistId)`, `sharedPlaylists()`, `unshare(playlistId)`; `Database.playlistListener` (callable(playlistId) chiamato da addToPlaylist/removeEntries/setPlaylistOrder/updatePlaylist/deleteSongs); query libreria (allSongs, favoriteSongs, recent*, mostPlayed, searchSongs) escludono `hidden=1`; `updateSong` accetta `hidden`.
- [ ] Test: stream song creata con path `stream:<url>`, `findSongByUrl` la trova, `allSongs` non mostra hidden, listener chiamato con il playlistId corretto per ogni operazione (anche removeEntries e deleteSongs)
- [ ] Implementa, test verdi, commit

### Task 2: Streaming nel motore e nel Player
**Files:** Modify `app/downloader.py`, `app/audio_engine.py`, `app/player.py`; Test `tests/test_streaming.py`
**Produces:** `downloader.resolveStream(target) -> {"url","headers","duration","title","webpageUrl"}` (target = url YouTube o `ytsearch1:…`; cache 4 h); `downloader.streamSongInfo(entry) -> dict` (titolo/artista/copertina come downloadAudio, senza scaricare audio); `AudioEngine.sourceHeaders` (dict), `AudioEngine.durationHintMs`; sorgenti http → ffmpeg con `-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5` e `-headers`; `Player.streamResolver` (callable target → info, sostituibile nei test), segnali `Player.loadingChanged(bool)`, `Player.seeked(int)`, `Player.songLoaded(object)`; `_loadCurrent` per stream: risolve in background (generazione per scartare risultati vecchi), poi setSource; errore → `playbackError` + avanti (stessa logica dei file mancanti); stream scaduto (errore decoder) → una nuova risoluzione senza cache.
- [ ] Test (server HTTP locale con un mp3 generato da ffmpeg): AudioEngine suona da URL http e riporta durata; Player con resolver finto carica una stream song, emette loading true→false, applica startPosition; resolver che fallisce → playbackError e passa alla successiva
- [ ] Implementa, test verdi, commit

### Task 3: UI streaming
**Files:** Modify `app/ui/views.py`, `app/ui/main_window.py`, `app/ui/dialogs.py`, `app/config.py`, `app/ui/theme.py`
**Produces:** impostazione `streamOnly` (default False) in DEFAULT_SETTINGS + checkbox "Non scaricare: aggiungi le canzoni solo in streaming"; risultati web: menu "+" con "Riproduci in streaming", "Aggiungi alla coda (streaming)", "Salva in libreria (solo streaming)", sottomenu playlist streaming; con `streamOnly` il bottone "Scarica" diventa "Aggiungi"; `MainWindow.addStreamEntries(entries, playlistId=None, play=False, queue=False)`; menu canzone: stream → "Scarica sul PC"; file con url → "Solo streaming (elimina il file)" con conferma; `_onSongDownloaded` aggiorna la stream song esistente (stessa url) invece di duplicarla; funzioni che vogliono un file (taglia, esporta, mostra nella cartella, scrivi tag, waveform, video auto) → "Scarica prima la canzone"/salto silenzioso; icona "cloud" accanto al titolo delle stream song nella tabella; indicatore "Caricamento…" nella barra mentre risolve
- [ ] Test offscreen: MainWindow si apre; addStreamEntries crea righe stream; menu canzone per stream non contiene "Taglia audio"; openCutDialog su stream mostra il messaggio
- [ ] Commit

### Task 4: Trasporto cifrato
**Files:** Create `app/session_link.py`; Modify `requirements.txt`, `synth_build.py`; Test `tests/test_session_link.py`
**Produces:** `makeCode(prefix) -> str`; `parseCode(text) -> (kind, code)|None` (accetta codice o link, minuscole, spazi; kind "room"/"playlist"); `CodeBox(code)` con `topicBase`, `seal(obj) -> bytes`, `open(data) -> obj|None` (zlib + keystream SHA-256 + HMAC 16 byte, PBKDF2 20 000 iterazioni); `Link(QObject)`: `start()`, `stop()`, `watch(code, subtopics)`, `unwatch(code)`, `publish(code, subtopic, obj, retain=False)`, `clearRetained(code, subtopic)`, `setWill(code, subtopic)`; segnali `received(str code, str subtopic, object payload)`, `connectedChanged(bool)`; failover broker e riconnessione automatica con resubscribe
- [ ] Test unit: round-trip seal/open; payload manomesso/altra chiave → None; parseCode su codici e link validi/invalidi
- [ ] Test integrazione con mosquitto locale (`SYNTH_BROKERS=127.0.0.1:18830:0`): due Link, publish/received, retained ricevuto da chi entra dopo, will cancellata alla disconnessione brusca
- [ ] Commit

### Task 5: Logica stanza (pura)
**Files:** Create `app/together_sync.py`; Test `tests/test_together_sync.py`
**Produces:** `ClockSync` (`onPong(peerId, t0, t1, t2)`, `offset(peerId) -> ms`, best di 5 campioni per RTT); `RoomState` dict `{queue:[track], index, positionMs, playing, at, effects, version, by}`; `trackFromSong(song) -> track` (`key` = url YouTube oppure `t:<titolo|artista normalizzati>`); `isNewer(candidate, current) -> bool` (versione più alta; pari → `by` minore); `expectedPosition(state, nowMs, offsetMs) -> ms` (pos + elapsed·rate se playing, clamp ≥0)
- [ ] Test: ordinamento versioni/pareggi, expectedPosition con rate 0.85 e offset, ClockSync sceglie il campione con RTT minore
- [ ] Commit

### Task 6: Controller "Ascolta insieme" + UI + profili
**Files:** Create `app/together.py`, `app/ui/together_popup.py`; Modify `app/ui/main_window.py`, `app/ui/player_bar.py`, `app/ui/dialogs.py`, `app/config.py`, `app/player.py`
**Produces:** impostazioni `profileName`, `profilePhoto` (base64), `clientId`; `randomName()`; `TogetherController(window)`: `createRoom()`, `joinRoom(code)`, `leaveRoom()`, `peers` dict, segnali `roomChanged`, `peersChanged`; pubblica stato alle azioni locali (songChanged/playingChanged/seeked/queueChanged/effetti), applica stati remoti con flag anti-eco, canzoni remote → libreria o stream song nascosta (`ytsearch1:` se senza url), correzione drift ogni 2 s, effetti della stanza via `player.effectsProvider` senza salvarli nel DB; presenza retained + will; ping/pong ogni 20 s; toast entrate/uscite; banner "In ascolto insieme con …"; bottone persone nella barra; popup con profilo, Crea/Entra (codice o link)/Copia link/Esci; Impostazioni → Profilo
- [ ] Test integrazione (mosquitto + 3 finestre offscreen con cartelle dati diverse, resolver finto): B entra e riceve la canzone di A; pausa da C → A e B in pausa; seek da B → posizione allineata < 700 ms; effetti cambiati da A applicati a B senza modificare il DB di B; uscita di C → sparisce dai peers
- [ ] Commit

### Task 7: Playlist condivise
**Files:** Create `app/playlist_sync.py` (merge puro + `SharedPlaylists` manager); Modify `app/ui/main_window.py`; Test `tests/test_playlist_sync.py`
**Produces:** `buildSnapshot(name, coverB64, tracks, previous, nowMs) -> snapshot` (tombstone per i rimossi, `addedAt` conservati, `orderAt`/`nameAt` aggiornati solo se cambiati, chiavi duplicate → `key#2`); `mergeSnapshots(a, b) -> snapshot`; `SharedPlaylists(window)`: `share(playlistId) -> code`, `addShared(code)`, `stop(playlistId)`, sync all'avvio e su `playlistListener` (debounce 1 s), applica snapshot remoti al DB (stream song visibili per brani mancanti), ripubblica se il merge cambia qualcosa; menu playlist "Condividi playlist…/Codice di condivisione/Smetti di condividere"; sidebar "+" → "Aggiungi playlist condivisa…"; il campo codice del popup accetta anche `SYNTHP-`
- [ ] Test unit merge: aggiunte da entrambi tenute; rimozione dopo aggiunta vince; ri-aggiunta dopo rimozione vince; ordine dall'ultimo; idempotenza e commutatività sul contenuto
- [ ] Test integrazione (mosquitto, 2 DB): A condivide, B aggiunge col codice e vede i brani; B aggiunge un brano offline, poi si connette → A lo riceve
- [ ] Commit

### Task 8: Link `synthmusic://`, istanza unica, rilascio
**Files:** Modify `main.py`, `installer.iss`, `app/config.py` (VERSION 1.7.0), `LEGGIMI.md`
**Produces:** istanza unica con `QLocalServer("SynthMusic-<utente>")`: secondo avvio con link → inoltra il codice e si chiude; `MainWindow.handleLink(text)`; registro HKCU `Software\Classes\synthmusic` → app; LEGGIMI con "Come funziona il connetti"
- [ ] Test: `parseCode` dagli argv; secondo processo offscreen inoltra al primo
- [ ] Regressione completa: tutti i test + avvio offscreen della finestra + smoke di funzioni esistenti (riproduzione file, cut, effetti, ricerca locale)
- [ ] Commit, zip
