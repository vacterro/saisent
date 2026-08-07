# SAISENT 4.0

Un pannello di controllo che incolla testo preparato in anticipo nelle sessioni degli agenti attualmente in esecuzione su questa macchina.

Metti il testo nella coda della sessione giusta — SAISENT attiva la finestra dell'agente, passa alla scheda di quella sessione, incolla il testo in un'unica operazione e preme Invio.

## Avvio rapido

```
START_SAISENT.bat
```

Richiede Python 3.11+ su Windows.

## Come si usa

1. **Agenti.** Riga in alto — caselle di spunta: Claude Code, Freebuff, Antigravity, CodeNomad.
   Spunta un agente e le sue sessioni appaiono nel pannello di sinistra.
2. **Sessioni live.** A sinistra ciò che gira davvero: nome sessione, numero scheda, sensore di attività e progetto. La lista non si aggiorna da sola, a meno che non si attivi «ogni N s» — di default l'aggiornamento è solo col pulsante **Aggiorna**.
3. **Scheda.** SAISENT indovina il numero di scheda dall'ordine di avvio delle sessioni. Sbagliato? Scrivi il numero manualmente in `SAISENT.json`, chiave `tabs` (chiave di sessione nella forma `<agente>:<id>`, es. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = non cambiare affatto scheda.
4. **Testo.** Scrivi (o incolla) in basso a destra, premi **In coda** (o Ctrl+Invio). **Tutto in coda** mette lo stesso testo in ogni sessione live — sostituisce la vecchia macro «CTRL+2, testo, CTRL+3, testo».
5. **Coda.** L'ordine delle righe = l'ordine di invio. Trascina una riga col mouse o spostala con **Su**/**Giù**. Ogni sessione ha la sua coda. Doppio clic su una riga (o pulsante **Modifica**) riporta il prompt nel campo di testo; **Salva modifica** lo riscrive sul posto, **Annulla** scarta. Modificare un prompt già inviato lo rimette in coda — il testo nella riga non corrisponde più a ciò che ha ricevuto la sessione. **Duplica** mette una copia subito sotto.
6. **Invio.** **INVIA QUESTA CODA** — solo la sessione selezionata. **INVIA TUTTE** — tutte le code in ordine. **Prova a secco** non invia nulla, mostra solo il piano nel registro. Gli invii reali chiedono conferma e nominano le sessioni.

## Annulla invio

Dopo l'invio, appare un pulsante **Annulla** per 30 secondi. Riporta l'ultimo prompt inviato in coda come `pending` — a meno che la sessione non lo abbia già elaborato (consegna confermata).

## Pianificazione e limiti

Nel gruppo «Invio»:

- **Invia alle (HH:MM)** — vuoto significa «ora». Con un orario, la coda attende la prossima occorrenza di quell'ora (oggi, o domani se passata) e mostra un conto alla rovescia nella barra di stato.
- **Attendi il reset del limite** — prima di ogni prompt, SAISENT legge il testo dell'agente stesso. Se dice «limit reached», la coda attende e riprende automaticamente quando il limite si libera. Nessun prompt contro una porta chiusa.
- **Controlla limiti** — riscansiona ora.
- Il campo di stato a destra mostra lo stato live: `limits: all agents free` o `claude-code: LIMITED until 09:22 (1h 05m remaining)`, in rosso. Il conto alla rovescia batte una volta al secondo dalla cache; il disco si tocca solo quando la lettura è obsoleta o arriva l'ora di reset indicata.

L'ora di reset si prende dalle parole dell'agente stesso. Se non la indica, SAISENT scrive «reset time not stated» piuttosto che inventare un segnaposto come «+5 ore».

### Quando si resettano i limiti

Se l'agente non indica mai un'ora di reset, SAISENT ripiega su una regola per agente:

| Agente | Regola | Significato |
|---|---|---|
| Freebuff | `daily 10:00` | reset ogni giorno alle 10:00 |
| CodeNomad | `daily 03:00` | reset ogni giorno alle 03:00 |
| Claude Code | `rolling 5h` | 5 ore dopo l'ultimo prompt inviato |
| Antigravity | solo le parole dell'agente | nessuna regola — ciò che indica, o nulla |

Una regola non annulla mai un'ora indicata dall'agente; l'agente è l'autorità sul proprio quota. Qualsiasi regola si può sovrascrivere in `SAISENT.json` sotto `quota_plans`, es. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Perché i successivi non partono

L'invio è strettamente sequenziale e si ferma al primo errore vero. Il motivo appare nella barra di stato (`stopped: window not found: ...`), sulla riga del prompt nella lista e nel registro. Il resto resta `pending` — non è perso.

Tra un prompt e l'altro c'è una pausa `gap_ms` (default 1500 ms) e lo stato mostra `Waiting N.Ns before next`. Se un prompt è stato inviato ma la sessione non si è mossa, viene marcato **non confermato** e resta in coda. «Inviato» si applica solo alle consegne confermate.

## Sensore di attività

La colonna «Sensore» risponde a «posso scrivere adesso?».

- `busy` — la sessione ha scritto nel suo store meno di 20 secondi fa (l'agente è a metà turno);
- `idle` — silenzio oltre 20 secondi, il campo di input è libero.

Da dove viene:

| Agente | Fonte | Sensore |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + trascrizione | ultima scrittura nella trascrizione |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, tabella `threads` | campo `turn_state` |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime del DB e del suo `-wal` |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | ultima scrittura nella trascrizione |

La vivacità è un controllo separato, non «il file su disco è fresco»:

- **Claude Code** — il PID da `~/.claude/sessions/<pid>.json` è vivo. Il file sopravvive alla chiusura della sessione; il PID no.
- **Freebuff** — `Freebuff.exe` è in esecuzione. Il DB tiene i thread `open` anche dopo l'uscita dall'app.
- **Antigravity** — `Antigravity.exe` è in esecuzione **e** la conversazione è fresca. La freschezza da sola non basta: questo store tiene tutte le conversazioni per sempre, e un editor chiuso riempiva la lista di sessioni che nessun tasto poteva raggiungere.
- **CodeNomad** — la riga del DB non è archiviata (`time_archived IS NULL`). Attive sono solo quelle attualmente aperte.

## Indirizzo di consegna — colonna «Indirizzo»

La barra laterale mostra esattamente come verrà colpita ogni sessione:

| Valore | Metodo | Affidabilità |
|---|---|---|
| `cdp:28194` | Incolla tramite il debugger dell'agente | Esatto: campo letto prima e dopo, il focus non viene rubato |
| `CTRL+3` | Cambio scheda nella finestra dell'agente | Buono, se il numero di scheda è corretto |
| `blind` | Nessuna porta, nessun numero di scheda | Il prompt atterra nella chat aperta |

Nessun titolo di finestra contiene un nome di sessione — `claude.exe` si chiama «Claude», Antigravity si chiama «Antigravity», Freebuff si chiama «Freebuff Desktop». Indirizzarsi per finestra è quindi impossibile, e `blind` significa esattamente ciò che dice.

### CDP — il percorso affidabile

Se un agente è stato avviato con `--remote-debugging-port`, SAISENT invia tramite il debugger e non tocca né focus né tastiera. Questo significa:

- il testo viene incollato direttamente nel campo di input, non «dovunque»;
- il campo viene letto **prima** dell'incollaggio: se c'è un messaggio a metà, l'invio rifiuta piuttosto che appendere alla frase di un altro;
- il campo viene letto **dopo** l'incollaggio: se non è atterrato, non inviamo.

Un rifiuto CDP non ricade mai su tasti alla cieca. Il trasporto preciso ha appena detto che il momento è sbagliato; martellare tasti sopra è esattamente il modo per rovinare la chat di un altro.

La porta si legge da `DevToolsActivePort` dell'agente, ma un file da solo non basta — sopravvive a un avvio precedente. SAISENT si connette davvero alla porta prima di ogni sonda.

Abilitare il debugger per un agente (un riavvio uccide ciò che sta facendo — SAISENT non lo fa mai da sé):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Selettori di pagina (DOM reale, 2026-08-05)

| Agente | Porta | Campo di input | Elenco dialoghi |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | nessuna | — | — |

Antigravity verificato: 16 pulsanti, le etichette corrispondono esattamente ai nomi di progetto che mostra SAISENT (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — la selezione del dialogo per nome funziona con precisione.

CodeNomad è Electron su OpenCode; la cartella dati si chiama ancora `Plasticity`. L'elenco sessioni nel DOM contiene solo le sessioni del **progetto attualmente aperto**; una sessione di un altro progetto non viene renderizzata e SAISENT non la troverà — l'invio rifiuta piuttosto che colpire alla cieca la chat aperta.

Sovrascrivere qualsiasi chiave di profilo in `SAISENT.json`:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Le sessioni si leggono da `~/.local/share/opencode/opencode.db`, tabella `session`: nome = `title`, progetto = `directory`, le archiviate filtrate per `time_archived`, il sensore per `time_updated`. L'unico agente qui la cui lista sessioni è colonne semplici, senza protobuf né parsing.

Vivacità — `CodeNomad.exe` è in esecuzione. Nessun numero di scheda: si indirizza per nome tramite il debugger.

## Perché non per titolo di finestra

Ogni finestra `claude.exe` si chiama «Claude». Il nome di sessione non appare mai nel titolo, quindi indirizzarsi per finestra è impossibile — nome, progetto e PID vengono dal disco; la finestra serve solo per il focus.

## Conferma di consegna

Chromium non risponde a `WM_GETTEXT`, quindi leggere «è atterrato?» via Win32 è impossibile — la vecchia rilettura per questi agenti restituiva sempre «non confermato». Invece, SAISENT attende che si muova lo stesso file che osserva il sensore di attività. Mosso? Consegnato. Non mosso nel tempo assegnato? Il prompt viene marcato come inviato ma non confermato, ed è visibile nel registro. Non è considerato un errore: l'agente potrebbe semplicemente non aver ancora iniziato il turno.

L'invio si ferma al primo errore vero (finestra non trovata, focus perso, appunti occupati). I prompt successivi restano in coda — non si perdono e non partono alla cieca.

## Esporta e Importa

I pulsanti **Esporta** e **Importa** salvano/caricano le code in formato JSONL. Ogni riga è autonoma con la sua chiave di sessione. L'import unisce senza perdita di dati — i duplicati (stessa chiave + testo) vengono saltati.

## File accanto al programma

| File | Contenuto |
|---|---|
| `SAISENT.json` | impostazioni: agenti, numeri scheda, timeout, geometria finestra |
| `SAISENT_QUEUES.json` | code per sessione, sopravvivono al riavvio |
| `SAISENT.log` | registro dello storico invii |

La coda non viene mai pulita automaticamente. Se una sessione scompare dalla lista ma ha elementi non inviati, la coda resta: gli agenti vengono riavviati, e una coda scartata in silenzio è peggio di una riga in più in un file.

## Impostazioni nascoste

Modifica `SAISENT.json` a programma chiuso:

- `gap_ms` — pausa tra i prompt in un lotto (default 1500);
- `settle_ms` — pausa dopo il cambio scheda e dopo l'incollaggio (400);
- `confirm_seconds` — quanto attendere la conferma di consegna (10);
- `busy_seconds` — soglia del sensore «busy/idle» (20);
- `freebuff_roots` — radici dove cercare `.freebuff/desktop-v2.db`, es. `["V:\\___VAC\\__K\\__CODE"]`; profondità limitata a 3;
- `submit` — tasto per inviare, default `ENTER`.

## Limitazioni

- Le schede si indirizzano via `Ctrl+1..Ctrl+9`. Una decima sessione è irraggiungibile — `Ctrl+10` non esiste, e SAISENT rifiuta piuttosto che indovinare.
- Il numero di scheda è una stima basata sull'ordine di avvio. Fai la prima passata con **Prova a secco**, poi su una sessione non importante.
- Antigravity non memorizza i nomi di conversazione come testo: la lista mostra il nome della cartella di lavoro estratto dai metadati.

## Test

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
