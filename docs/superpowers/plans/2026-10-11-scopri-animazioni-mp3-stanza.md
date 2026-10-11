# Scopri, animazioni, colori, mp3 in stanza — Implementation Plan (v1.8.0)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (native, as for 1.7). Steps use checkbox (`- [ ]`) syntax.

**Goal:** pagina Scopri con consigli, effetti/animazioni disattivabili, colori personalizzabili, mp3 personali condivisi in stanza.
**Spec:** `docs/superpowers/specs/2026-10-11-scopri-animazioni-mp3-stanza-design.md`
**Tech:** PySide6 (QPropertyAnimation/QVariantAnimation, QGraphicsOpacityEffect, QColorDialog), numpy FFT, urllib (Deezer API, Litterbox), yt-dlp.

## Global Constraints
- Nessuna funzione esistente tolta/cambiata; con tutti gli effetti disattivati l'app è visivamente come la 1.7.1
- Impostazioni nuove (default): `fxTransitions`, `fxCoverColors`, `fxVisualizer`, `fxMicro`, `fxSongFade` = True; `themeColors` = {} (vuoto = colori originali)
- Rete solo in background (runInBackground), mai nel thread UI; errori → messaggio breve
- Versione 1.8.0

## Review Focus
- Scopri senza internet / Deezer giù / libreria vuota → pagina utilizzabile, nessun crash (Task 1-2)
- Visualizer e animazioni con video di sfondo o mentre giochi → nessun lag: timer fermi se app inattiva o widget nascosto (Task 3-5)
- Colori scelti illeggibili (testo = sfondo) → testo secondario/hover derivati restano visibili; Ripristina sempre disponibile (Task 7)
- mp3 grande / upload lento / Litterbox giù → l'amico vede "Caricamento…", poi ripiego su YouTube; nessun file temporaneo resta oltre 1 h (Task 8)
- Due istanze durante "Riavvia ora" (istanza unica) → la nuova parte dopo la chiusura della vecchia (Task 7)

### Task 1: `app/discover.py` (logica pura + client)
Produces: `DeezerClient(fetchJson)` con `searchArtist(name)`, `relatedArtists(id)`, `topTracks(id, limit)`, `artistAlbums(id)`, `chart(limit)`, `playlistTracks(id)`; `youtubeMix(videoId, limit)`; `buildDiscover(library, client, mixProvider, nowMs) -> {"sections": [...], "artists": {...}}`; `DiscoverCache(path, ttlSeconds=21600)`; track dict `{title, artist, album, duration, image, url|None, query}`.
- [ ] Test con JSON finti: sezioni presenti, brani già in libreria esclusi, novità entro 90 giorni, errori di rete → sezioni mancanti ma risultato valido; cache scaduta/valida
- [ ] Commit

### Task 2: UI Scopri + pagina artista
Files: `app/ui/discover_page.py`; modify `main_window.py` (nav "Scopri", `playDiscovered(tracks, index)`, `saveDiscovered(track)`), `views.py` (riuso Card).
- [ ] Scheletri animati in caricamento, righe card, card artista rotonde, immagini remote caricate in background (cache in covers), menu ⋯ (coda, playlist, scarica)
- [ ] Test offscreen con servizio finto + screenshot
- [ ] Commit

### Task 3: Transizioni (`app/ui/effects.py`)
Produces: `fadeSwitch(stacked, newWidget)`, `popIn(widget)`, `HoverLift` (event filter per card), `bounce(button)`; tutti no-op se `fxTransitions` False.
### Task 4: Colori dalla copertina
Produces: `dominantColor(coverPath) -> QColor`; PlayerBar/NowPlaying animano il colore (600 ms) se `fxCoverColors`.
### Task 5: Visualizer
AudioEngine: `spectrum()` → 16 bande 0..1 calcolate nel callback (rfft del blocco, smoothing); `VisualizerWidget` (barra in basso + grande in In riproduzione) a 30 fps solo se visibile, app attiva e in riproduzione; `fxVisualizer`.
### Task 6: Micro-effetti + dissolvenza
`HeartBurst` overlay al like; pulsazione copertina sui bassi (`fxMicro`); AudioEngine gain ramp: fade-in 1 s dall'inizio, fade-out ultimi 2 s (`fxSongFade`).
- [ ] Test: bande FFT su sinusoide (picco nella banda giusta), gain ramp, dominantColor su immagine rossa, effetti off → nessun timer attivo
- [ ] Commit (Task 3-6)

### Task 7: Colori personalizzabili
theme legge `themeColors` all'avvio e deriva hover/elevated/subtext; Impostazioni → Aspetto (picker + preset + Ripristina + "Riavvia ora"); riavvio: `--restarted` salta il controllo istanza unica e attende la chiusura della vecchia.
- [ ] Test: colori derivati leggibili, preset, riavvio (processo figlio parte con `--restarted`)
- [ ] Commit

### Task 8: mp3 personali in stanza (`app/room_files.py`)
Produces: `encryptFile(path) -> (blobPath, keyB64, sha)`, `decryptFile(blobPath, keyB64, outPath)`, `uploadTemp(path, uploader=litterbox)`, `RoomFileCache(dir)` con `fetch(info)`, `touch`, `cleanup(maxIdleSeconds=3600, keep=currentPath)`; TogetherController pubblica `files/<sha>` retained; track con `fileSha`; Player resolver instrada `roomfile:<sha>`.
- [ ] Test: cifra/decifra, cleanup 1 h, integrazione mosquitto + server Litterbox finto: B suona l'mp3 di A
- [ ] Commit

### Task 9: Rilascio
- [ ] Suite completa, screenshot UI con effetti on/off, revisione indipendente, VERSION 1.8.0, LEGGIMI, zip
