# Ascolto condiviso, playlist condivise e streaming — Design

## Obiettivo
Due persone su PC diversi (anche lontani) ascoltano la stessa canzone nello stesso momento, entrando con un **codice o link e via** (niente router, VPN o account). Playlist condivise sempre sincronizzate. Possibilità di ascoltare in streaming senza scaricare.

## Decisioni prese (da Giuseppe)
- Connessione: "inserisci codice o link e via" → relay pubblico gratuito (MQTT), niente configurazione
- Playlist condivisa: sincronizzata sempre, in entrambe le direzioni
- Download di default come oggi; opzione "solo streaming" generale e per canzone
- Canzoni condivise: streaming di default, a meno che la canzone sia già salvata nel PC
- Ascolto condiviso: tutti e due controllano tutto
- Rilascio in 3 step: 1.7 streaming → 1.8 ascolto insieme → 1.9 playlist condivisa

## Step 1 — Streaming (v1.7)
- `downloader.resolveStream(url)` → URL audio diretto via yt-dlp (`bestaudio`), cache in memoria ~5 h (gli URL YouTube scadono)
- `AudioEngine` già decodifica con `ffmpeg -i <sorgente>`: per URL http aggiungo `-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5`
- Canzoni in streaming = righe del DB con `path` vuoto e `streamOnly = 1` (nuova colonna), `url` = link YouTube. Il Player, prima di caricare una canzone senza file, risolve lo stream in un thread (niente blocco UI) e mostra "Caricamento…"
- Ricerca: bottone **▶ Ascolta** (streaming immediato, aggiunge alla coda senza scaricare) accanto a "Scarica"
- Impostazione **"Solo streaming (non scaricare)"**; menu canzone: **"Scarica sul PC"** / **"Solo streaming"**
- Testi funzionano uguale; per le canzoni in streaming il video non viene scaricato da solo (si può sempre scegliere/scaricare a mano)
- Errori: stream scaduto → risolve di nuovo una volta; offline → toast "Serve internet per lo streaming", passa alla successiva

## Step 2 — Ascolta insieme (v1.8)
**Trasporto (`app/session_link.py`)**
- `paho-mqtt` su TLS. Broker in ordine: `broker.hivemq.com:8883`, `broker.emqx.io:8883`, `test.mosquitto.org:8886`; se uno cade passa al successivo
- Codice stanza: `SYNTH-XXXX-XXXX` (8 caratteri casuali, alfabeto senza 0/O/1/I). Link: `synthmusic://join/SYNTH-...` (registrato dall'installer) — incollare il link o il codice funziona uguale
- Topic = `synthmusic/v1/<sha256(codice)[:24]>/…` → il codice non compare in chiaro
- Messaggi JSON criptati+firmati con chiave derivata dal codice (PBKDF2 → keystream SHA-256 + HMAC, solo libreria standard). Messaggi non firmati vengono scartati
- Presenza: messaggio "online" + Last Will "offline" → si vede chi c'è

**Sincronizzazione**
- Stato condiviso: `{song: {title, artist, youtubeUrl, duration}, positionMs, playing, effects: {rate, keepPitch, reverbWet, reverbSize}, at: tempoServer, queue:[…], version, by}`
- Orologio: ping/pong tra i due → offset medio; ogni comando porta il tempo di riferimento → chi lo riceve calcola la posizione corretta (precisione ~0.5 s)
- Chiunque fa play/pausa/seek/salta/aggiunge alla coda/cambia effetti → manda il nuovo stato con `version+1`; vince la versione più alta (pari → vince l'id più piccolo)
- Ogni 5 s chi suona manda la posizione; se l'altro è sfasato > 700 ms → piccolo seek
- Canzone ricevuta: cerca nella libreria (url YouTube uguale, poi titolo+artista) → se c'è usa il file, altrimenti streaming
- mp3 locali senza link YouTube → si manda titolo+artista, l'altro cerca su YouTube (come l'import Spotify) e va in streaming
- **Effetti condivisi** (velocità, mantieni pitch, reverb): fanno parte dello stato della stanza. Quando parte una canzone si usano gli effetti salvati di chi l'ha messa; se uno li cambia durante la sessione cambiano per tutti e due. Così la velocità è identica e il timing resta allineato
- Le modifiche agli effetti fatte durante la sessione **non** sovrascrivono gli effetti salvati per canzone (l'amico non ti cambia le impostazioni); uscito dalla stanza tornano i tuoi
- La posizione si sincronizza sul tempo originale della canzone

**Più persone e profili**
- Una stanza accetta **più persone** (nessun limite pratico; testato fino a 6). Tutti controllano tutto
- Profilo: **nome + foto** (opzionali). La prima volta l'app propone un nome casuale (es. "Volpe Viola 42") modificabile; foto scelta da file, ritagliata quadrata e compressa a 96×96 JPEG (≤ 12 KB)
- Il profilo viaggia nel messaggio di presenza (retained per persona) → chi entra vede subito tutti con nome e foto; uscendo (o chiudendo l'app) la presenza viene cancellata (Last Will)
- Ogni persona ha un `clientId` casuale fisso salvato in impostazioni

**UI**
- Bottone **"Ascolta insieme"** nella barra in basso (icona persone) → popup: "Crea stanza" (mostra codice + Copia) / "Entra" (campo codice o link) / persone connesse / "Esci"
- Barra in alto "Stai ascoltando con …" con le foto/iniziali delle persone; toast "Marco è entrato", "Marco ha messo X"
- Impostazioni → **Profilo**: nome, foto, "Nome casuale"

## Step 3 — Playlist condivise (v1.9)
- Menu playlist → **"Condividi"**: crea codice playlist `SYNTHP-XXXX-XXXX`; **"Aggiungi playlist condivisa"** nella sidebar
- Ogni playlist condivisa: colonne `shareCode`, `shareVersion` in `playlists`; i brani identificati da `trackKey` (url YouTube, altrimenti titolo|artista normalizzati)
- Sul broker: messaggio **retained** con lo snapshot completo (nome, copertina piccola ≤ 64 KB, lista brani con metadati, `version`, `updatedAt`) → chi apre l'app dopo vede le modifiche anche se l'altro era offline
- Modifiche (aggiungi/togli/riordina/rinomina): si aggiorna lo snapshot e si ripubblica; conflitti → unione per brano (aggiunte di entrambi tenute, rimozioni con "tombstone" e timestamp, ordine dall'ultima modifica)
- Brani ricevuti non presenti in libreria → aggiunti come "solo streaming" (scaricabili con un click)
- Limite: i broker pubblici possono cancellare i messaggi retained dopo molto tempo → ogni app ripubblica lo snapshot all'avvio, quindi basta che uno dei due apra l'app

## Regola d'oro
Nessuna funzione esistente viene tolta o cambiata nel comportamento: tutto il nuovo è in aggiunta e, fuori da una stanza, l'app funziona esattamente come prima.

## Rischi / limiti
- Broker pubblici: niente garanzie di uptime; con 3 broker di riserva il rischio è basso. Se tutti giù: toast "Ascolto condiviso non disponibile ora", il resto dell'app funziona
- YouTube cambia spesso → lo streaming dipende da yt-dlp (già si aggiorna da solo ogni giorno)
- Non sincronizziamo i file audio, solo metadati e link

## Test
- Unit: codifica/decodifica e firma messaggi, risoluzione conflitti di versione, calcolo posizione con offset orologio, merge playlist
- Integrazione: due istanze dell'app nello stesso PC (cartelle dati diverse) collegate allo stesso broker; streaming di un video YouTube reale
