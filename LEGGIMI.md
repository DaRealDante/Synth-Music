# Synth Music v1.7.0

## Installare / aggiornare (tu)
Doppio click su **`INSTALLA_E_AGGIORNA.bat`**. Fa tutto da solo:
1. installa Python se manca (poi riapri il file)
2. installa/aggiorna le librerie
3. crea l'app e l'installer `installer\SynthMusic_Setup_vX.exe`
4. installa/aggiorna Synth Music sul tuo PC (icona sul Desktop)

La prima volta Synth Music si copia da solo in `%LOCALAPPDATA%\SynthMusic\Sorgente` (poi la cartella scaricata si può cancellare) e crea sul Desktop **"Synth Music - Aggiorna"**.
L'app installata sta in `%LOCALAPPDATA%\Programs\Synth Music`, con icona sul Desktop e nel menu Start.
Nuova versione → **trascina il nuovo `SynthMusic.zip` sopra "Synth Music - Aggiorna"**: estrae, ricompila e aggiorna da solo.

## Aggiornamenti automatici con GitHub (consigliato)
Una volta sola:
1. Crea un account su **github.com** e un repository **pubblico** vuoto (es. `SynthMusic`)
2. Apri **`PUBBLICA_AGGIORNAMENTO.bat`** e incolla l'indirizzo del repository (la prima volta si apre il browser per il login)

Ogni nuova versione: estrai lo zip, apri `INSTALLA_E_AGGIORNA.bat` (per provarla tu) e poi `PUBBLICA_AGGIORNAMENTO.bat`.
GitHub crea l'installer da solo (10-15 min) e **tutte le app** (tua e degli amici) mostrano "È disponibile Synth Music X → Aggiorna ora".
Controllo manuale: bottone **⋯** in basso a destra → *Controlla aggiornamenti* (o Impostazioni).

## Reinstallare da zero
1. Apri **`DISINSTALLA_TUTTO.bat`** (toglie app, codice e icone; ti chiede se cancellare anche playlist e canzoni)
2. Estrai `SynthMusic.zip` e apri **`INSTALLA_E_AGGIORNA.bat`**

## Amici
Mandagli solo **`installer\SynthMusic_Setup_vX.exe`**.
- Doppio click = installa (niente Python, niente admin)
- Per aggiornare: aprono il Setup nuovo, oppure dall'app → Impostazioni → **Installa aggiornamento...**
- Playlist, canzoni, loop e impostazioni non si perdono con gli aggiornamenti (`%APPDATA%\SynthMusic`)
- Disinstallare: Impostazioni di Windows → App → Synth Music (chiede se cancellare anche i dati)
- Se vogliono crearsi l'app da soli: zip + `INSTALLA_E_AGGIORNA.bat` funziona anche da loro (installa pure Python)
- Windows potrebbe dire "PC protetto": *Ulteriori informazioni → Esegui comunque* (l'app non è firmata)

Il motore YouTube (yt-dlp) si aggiorna da solo una volta al giorno: non serve ricompilare quando YouTube cambia.

## Ascolta insieme (come funziona il "connetti")
1. Bottone **persone** in basso a destra → **Crea una stanza**: il link (`synthmusic://join/SYNTH-XXXX-XXXX`) viene copiato da solo
2. Mandalo agli amici (anche più persone). Loro: bottone persone → incollano link o codice → **Entra**
3. Fatto: sentite la stessa canzone nello stesso punto. Tutti possono mettere play/pausa, saltare, cercare un punto, cambiare canzone, aggiungere alla coda e cambiare velocità/reverb (valgono per tutti, non toccano i tuoi effetti salvati)

- Le app non si mandano l'audio: si scambiano solo "quale canzone, a che secondo, play/pausa" (criptato col codice). Ognuno la suona dal suo PC: se ce l'ha già usa il file, sennò la prende in **streaming** da YouTube
- Il collegamento passa da server pubblici gratuiti (HiveMQ, EMQX, Mosquitto): niente router, niente account. Se uno è giù passa da solo al successivo
- Restate allineati entro ~½ secondo; se uno resta indietro (internet lento) si riallinea da solo
- Profilo (nome + foto): bottone persone → *Modifica profilo* (o Impostazioni → Profilo). La prima volta hai un nome casuale
- Le canzoni messe dagli amici non finiscono nella tua libreria: se una ti piace, menu della canzone → *Salva nella libreria*

## Playlist condivise
- Tasto destro su una playlist → **Condividi playlist...**: il link è copiato. Chi lo apre (o lo incolla col bottone 🔗 accanto a "Playlist", o nel bottone persone) riceve la playlist
- Aggiunte, rimozioni, ordine, nome e copertina si sincronizzano per tutti, anche se uno era offline (si allinea quando riapre l'app)
- I brani che non hai diventano canzoni in streaming: menu → *Scarica sul PC* per averli offline
- *Smetti di condividere* / *Elimina* toccano solo la tua copia

## Streaming
- Di default si scarica come sempre. Nella ricerca, bottone **+** → *Riproduci in streaming*, *Aggiungi alla coda*, *Salva in libreria (solo streaming)*
- Impostazioni → **"Non scaricare: aggiungi le canzoni solo in streaming"**: il bottone Scarica diventa *Aggiungi* (vale anche per playlist YouTube e Spotify)
- Le canzoni in streaming hanno "Streaming ·" sotto il titolo. Menu → *Scarica sul PC*; al contrario, su una canzone scaricata *Solo streaming (elimina il file)*
- Taglia audio ed "Esporta con effetti" richiedono il file: scarica prima la canzone

## Novità 1.7
- **Ascolta insieme** con più persone, profili con nome e foto
- **Playlist condivise** sincronizzate
- **Streaming** senza download
- Aprire un link `synthmusic://` porta direttamente nella stanza/playlist (se l'app è già aperta usa quella)

## Novità 1.6.2
- **Tasti multimediali** (Fn+F9, play/pausa, avanti/indietro) funzionano con Synth Music anche se l'app è in background
- Synth Music compare nel riquadro media di Windows (volume / schermata di blocco) con titolo, artista e copertina

## Novità 1.6.1
- I video ora vanno in **loop** se sono più corti della canzone (prima si fermavano)

## Novità 1.6
- **Velocità, pitch e reverb per canzone** (bottone ⏩ in basso a destra): slider 0.50x–2.00x, "mantieni il pitch", reverb con grandezza stanza, preset (Slowed + Reverb, Sped up, Nightcore). Si salva per ogni canzone.
- **Salva come nuova canzone** con gli effetti applicati (il testo sincronizzato si adatta alla velocità)

## Novità 1.5.1
- I testi seguono i tagli: se tagli una canzone (tieni o elimini una parte) il testo sincronizzato viene spostato/tagliato uguale

## Novità 1.4
- **Aggiornamenti automatici** via GitHub Releases + "Controlla aggiornamenti"
- `PUBBLICA_AGGIORNAMENTO.bat`: invia la nuova versione su GitHub, che crea l'installer da solo

## Novità 1.3.3
- I file .bat ora sono minimi: tutto il lavoro lo fa `synth_build.py` (Python), così gli antivirus (es. Bitdefender) non li scambiano per virus. Niente più download con PowerShell.
- "Synth Music - Aggiorna" ora è nel **menu Start**. Aprilo: se in Download c'è un SynthMusic.zip più nuovo, lo usa da solo.

## Novità 1.3.2
- Fix lag dell'audio mentre giochi: buffer audio più grande, priorità più alta all'app, ffmpeg a bassa priorità, video di sfondo in pausa quando usi altre app (disattivabile in Impostazioni)

## Novità 1.3
- **Video di sfondo con 2 modalità** (bottone immagine in basso a destra o tasto **V**): *Solo sfondo* (il video sta dietro, la UI resta sempre visibile) e *Schermo intero* (quando non muovi il mouse va a tutto schermo col video; muovi il mouse e torna tutto com'era)
- **Bottone Testo** in basso a destra (microfono): click = apre/chiude il testo; freccetta ▾ = testo automatico on/off (per tutte o solo per questa canzone) e "Cerca il testo"
- **Cerca testo** come "cerca video": scrivi artista/titolo, scegli dal risultato con anteprima (⏱ = sincronizzato)
- Barra in basso riordinata: taglia, velocità, timer e pannello loop sono nel bottone **⋯**
- Aggiornamento molto più veloce: le librerie si reinstallano solo se cambiano, build incrementale

## Novità 1.2
- **Video di sfondo**: se la canzone ha un video parte da solo dietro l'app, con la UI semi-trasparente. Dopo 3 secondi senza muovere il mouse la UI sparisce e resta solo il video; muovi il mouse e ricompare tutto.
- Si attiva/disattiva col bottone in basso a destra (icona immagine) o col tasto **V**

## Novità 1.1
- **Equalizzatore** 10 bande + preamp, preset (Bass Boost, Rock, Voce...), slider rapidi Bassi/Medi/Alti, bilanciamento, preset personali
- **Import da Spotify**: incolla il link di una playlist/album/brano pubblico → cerca ogni brano su YouTube, lo scarica con titolo e copertina Spotify e crea la playlist nello stesso ordine (salta quelli già in libreria)
- **Testi** automatici (sincronizzati quando disponibili, da LRCLIB): click su una riga = salta lì; puoi cercarli di nuovo, incollarli o modificarli
- **Video** salvati automaticamente per le canzoni da YouTube; puoi scegliere un altro video (ricerca YouTube o file)
- **In riproduzione**: 3 stili (Testo · Video · Video + Testo) e **schermo intero** (F11 / Esc)
- Testo e video automatici si possono disattivare per una singola canzone (menu Testo / Video)
- Fix: "Brani che ti piacciono" con finestre piccole, banner, slider, layout ricerca

## Scorciatoie
| Tasto | Azione |
|---|---|
| Spazio | Play / pausa |
| Ctrl + ← / → | Precedente / successiva |
| Shift + ← / → | -5 s / +5 s |
| Ctrl + ↑ / ↓ | Volume |
| T / E / Q | Testo e video / Equalizzatore / Coda |
| V | Video di sfondo: off → sfondo → schermo intero |
| F11 | Schermo intero |
| [ / ] / L | Punto A / punto B / loop on-off |
| S / R / M | Shuffle / ripeti / muto |
| Ctrl+F / Ctrl+N / Ctrl+I | Cerca / nuova playlist / importa |
