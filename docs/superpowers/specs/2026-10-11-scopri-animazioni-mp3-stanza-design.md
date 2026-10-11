# Scopri, animazioni e mp3 personali in stanza — Design (v1.8.0)

## Decisioni di Giuseppe
- Categorie: "un po' di tutto" → consigliati, simili, artisti per te, i tuoi artisti, novità, classifiche
- Animazioni/effetti: tutti, attivi di default, ognuno disattivabile nelle Impostazioni
- mp3 personali in stanza: sì, upload temporaneo criptato, cancellato dopo 1 ora senza ascolto
- Regola d'oro: nessuna funzione esistente tolta o cambiata

## 1. Pagina "Scopri" (nuova voce nella sidebar, sotto Cerca)
Fonti senza account: **Deezer API pubblica** (artisti simili, top brani, album, classifiche) + **YouTube** via yt-dlp (radio/mix di una canzone).
Sezioni (righe orizzontali scorrevoli di card, come Home):
- **Consigliati per te** — top brani degli artisti simili ai tuoi più ascoltati, esclusi quelli già in libreria, mescolati
- **Perché hai ascoltato "X"** (×2, ultime canzoni ascoltate) — mix YouTube della canzone (`watch?v=ID&list=RDID`)
- **Artisti che potrebbero piacerti** — artisti simili (foto rotonde); click → pagina artista
- **I tuoi artisti** — i più ascoltati (play count); click → pagina artista
- **Novità per te** — album/singoli usciti negli ultimi 90 giorni dai tuoi artisti
- **Classifica mondiale** e **Top Italia** (Deezer)

Pagina artista: foto + nome, "Popolari" (top 10 Deezer, segnati ✓ quelli che hai), "Le tue canzoni", artisti simili.
Card brano: hover → ▶ (riproduci in streaming), ＋ (salva in libreria in streaming), menu ⋯ (coda, playlist, scarica).
Brani scoperti suonati e non salvati = canzoni in streaming nascoste (compaiono in Recenti), come quelle degli amici.
Cache su disco 6 ore (`discover_cache.json`), bottone "Aggiorna"; tutto in background, la pagina mostra scheletri animati mentre carica; senza internet: messaggio, nessun crash. Libreria vuota → solo classifiche + messaggio "Ascolta qualcosa e qui arrivano i consigli".

## 2. Animazioni ed effetti (Impostazioni → "Animazioni", tutti attivi di default)
- **Transizioni**: cambio pagina con dissolvenza+scorrimento (screenshot della pagina vecchia che sfuma, leggero), popup che si aprono morbidi, card che si illuminano/alzano al passaggio del mouse, bottone play che "rimbalza"
- **Colori dalla copertina**: colore dominante della copertina → sfumatura della barra in basso e del banner In riproduzione, transizione graduale (600 ms) a ogni canzone
- **Visualizer**: barre a ritmo (16 bande, FFT calcolata nel motore audio sui campioni già in uscita) nella barra in basso e grandi nella pagina In riproduzione; si ferma quando l'app non è in primo piano
- **Micro-effetti**: cuore che "esplode" con particelle al like, copertina che pulsa leggermente sui bassi
- **Dissolvenza tra canzoni**: fade-out degli ultimi 2 s e fade-in di 1 s all'inizio (non sovrapposizione vera: richiederebbe due flussi audio)

## 3. mp3 personali in stanza
- Brano locale senza link YouTube (mp3 tuoi, tagliati, personali) messo in una stanza con altre persone → l'app lo **cripta** (chiave casuale per file) e lo carica su **Litterbox** (catbox.moe, gratis, nessun account) con scadenza **1 ora** sul server
- Nella stanza (messaggio criptato, retained `files/<sha>`) viaggiano link + chiave + sha256; se il link ha più di 50 minuti e serve ancora, si ricarica
- Chi lo riceve: canzone nascosta `stream:roomfile:<sha>`; il Player la "risolve" aspettando il link (max 90 s, "Caricamento…"), scaricando e decriptando in `temp/room_files/<sha>.<ext>`; poi la suona come un file normale (testo/video come le altre)
- Pulizia: ogni 5 minuti e all'avvio si cancellano i file non ascoltati da più di 1 ora (mai quello in riproduzione)
- Errore upload/download (internet, Litterbox giù) → messaggio breve, l'altro cerca la canzone su YouTube come prima (fallback attuale)

## 4. Colori personalizzabili
- Impostazioni → **Aspetto**: color picker (QColorDialog) per **Accento**, **Sfondo pagine**, **Pannelli**, **Barra e menu laterale**, **Testo**; anteprima del colore sul bottone
- Preset rapidi: Verde (originale), Viola, Blu, Rosso, Arancio, Rosa + **Ripristina**
- Colori derivati in automatico (hover, elementi rialzati, testo secondario) per restare leggibili
- Salvati in impostazioni; si applicano con **"Riavvia ora"** (l'app si riapre da sola sulla stessa canzone e posizione) perché icone e stili sono generati all'avvio

## Test
- Unit: parsing risposte Deezer (fixture JSON), costruzione sezioni, esclusione brani già in libreria, cache; colore dominante; bande FFT; cifratura/decifratura file; pulizia cache 1 h
- Integrazione: mosquitto locale + server HTTP finto al posto di Litterbox: A mette un mp3 locale, B lo riceve e lo suona; pagina Scopri offscreen con risposte finte; screenshot di Scopri, pagina artista, barra con visualizer
- Regressione: tutta la suite esistente + navigazione di tutte le pagine con animazioni attive e disattivate
