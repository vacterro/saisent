# SAISENT 4.0

Un panou de control care inserează text pregătit în prealabil în sesiunile agenților care rulează chiar acum pe această mașină.

Pui textul în coada sesiunii potrivite — SAISENT activează fereastra agentului, comută pe fila acelei sesiuni, inserează textul într-o singură operație și apasă Enter.

## Pornire rapidă

```
START_SAISENT.bat
```

Necesită Python 3.11+ pe Windows.

## Cum se folosește

1. **Agenți.** Rândul de sus — casete de bifat: Claude Code, Freebuff, Antigravity, CodeNomad.
   Bifezi un agent, iar sesiunile lui apar în panoul din stânga.
2. **Sesiuni live.** În stânga ce rulează efectiv: numele sesiunii, numărul filei, senzorul de activitate și proiectul. Lista nu se actualizează singură, decât dacă activezi „la fiecare N s" — implicit doar prin butonul **Actualizează**.
3. **Filă.** SAISENT ghicește numărul filei din ordinea pornirii sesiunilor. Greșit? Scrie numărul manual în `SAISENT.json`, cheia `tabs` (cheie de sesiune de forma `<agent>:<id>`, ex. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = nu schimba fila deloc.
4. **Text.** Scrii (sau inserezi) în dreapta jos, apeși **În coadă** (sau Ctrl+Enter). **Tot în coadă** pune același text în fiecare sesiune live — înlocuiește vechiul macro „CTRL+2, text, CTRL+3, text".
5. **Coada.** Ordinea rândurilor = ordinea trimiterii. Trage un rând cu mouse-ul sau mută-l cu **Sus**/**Jos**. Fiecare sesiune are propria coadă. Dublu-clic pe un rând (sau butonul **Editare**) scoate promptul înapoi în câmpul de text; **Salvare editare** îl rescrie pe loc, **Anulează** renunță. Editarea unui prompt deja trimis îl întoarce în coadă — textul din rând nu mai corespunde cu ce a primit sesiunea. **Duplicare** pune o copie imediat dedesubt.
6. **Trimitere.** **TRIMITE ACEASTĂ COADĂ** — doar sesiunea selectată. **TRIMITE TOATE** — toate cozile la rând. **Rulare de probă** nu trimite nimic, doar arată planul în jurnal. Trimiterile reale cer întâi confirmare și numesc sesiunile.

## Anulează trimiterea

După trimitere apare un buton **Anulează** timp de 30 de secunde. Întoarce ultimul prompt trimis în coadă ca `pending` — cu excepția cazului în care sesiunea l-a procesat deja (livrare confirmată).

## Programare și limite

În grupul „Trimitere":

- **Trimite la (HH:MM)** — gol înseamnă „acum". Cu o oră, coada așteaptă următoarea apariție a acelei ore (azi, sau mâine dacă a trecut) și arată o numărătoare inversă în bara de stare.
- **Așteaptă resetarea limitei** — înainte de fiecare prompt, SAISENT citește textul agentului însuși. Dacă spune „limit reached", coada așteaptă și reia automat când limita se eliberează. Niciun prompt într-o ușă încuiată.
- **Verifică limitele** — recitește chiar acum.
- Câmpul din dreapta arată starea live: `limits: all agents free` sau `claude-code: LIMITED until 09:22 (1h 05m remaining)`, cu roșu. Numărătoarea inverse bate o dată pe secundă din cache; discul e atins doar când citirea e învechită sau când a sosit ora de resetare indicată.

Ora de resetare se ia din cuvintele agentului însuși. Dacă nu o spune, SAISENT scrie „reset time not stated" în loc să inventeze un substituent ca „+5 ore".

### Când se resetează limitele

Dacă agentul nu indică niciodată o oră de resetare, SAISENT apelează la o regulă per agent:

| Agent | Regulă | Înseamnă |
|---|---|---|
| Freebuff | `daily 10:00` | resetare în fiecare zi la 10:00 |
| CodeNomad | `daily 03:00` | resetare în fiecare zi la 03:00 |
| Claude Code | `rolling 5h` | la 5 ore după ultimul prompt trimis |
| Antigravity | doar cuvintele agentului | nicio regulă — ce indică el, sau nimic |

O regulă nu suprascrie niciodată o oră indicată de agent; agentul este autoritatea asupra propriei cote. Orice regulă poate fi suprascrisă în `SAISENT.json` sub `quota_plans`, ex. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## De ce următoarele nu pleacă

Trimiterea este strict secvențială și se oprește la prima eroare reală. Cauza ajunge și în bara de stare (`stopped: window not found: ...`), și în rândul promptului din listă, și în jurnal. Restul rămâne `pending` — nu se pierde nimic.

Între prompturi se ține o pauză `gap_ms` (implicit 1500 ms), iar starea arată `Waiting N.Ns before next`. Dacă promptul a plecat, dar sesiunea nu s-a mișcat, el e considerat **neconfirmat** și rămâne în coadă. „Trimis" se pune doar pe livrări confirmate.

## Senzorul de activitate

Coloana „Senzor" răspunde la întrebarea „se poate scrie acum".

- `busy` — sesiunea a scris în magazinul său acum mai puțin de 20 de secunde (agentul e la mijlocul unei runde);
- `idle` — tăcere de peste 20 de secunde, câmpul de introducere e liber.

De unde se ia:

| Agent | Sursă | Senzor |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + transcriere | timpul ultimei scrieri în transcriere |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, tabela `threads` | câmpul `turn_state` |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime al bazei și al `-wal`-ului ei |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | timpul ultimei scrieri în transcriere |

Vivacitatea este o verificare separată, nu „fișierul de pe disc e proaspăt":

- **Claude Code** — PID-ul din `~/.claude/sessions/<pid>.json` e viu. Fișierul supraviețuiește închiderii sesiunii; PID-ul nu.
- **Freebuff** — rulează `Freebuff.exe`. Baza ține firele `open` chiar și după ieșirea din aplicație.
- **Antigravity** — rulează `Antigravity.exe` **și** conversația e proaspătă. Doar prospețimea nu ajunge: acest magazin păstrează toate conversațiile pentru totdeauna, iar un editor închis umplea lista cu sesiuni pe care nicio tastă nu le putea atinge.
- **CodeNomad** — rândul din bază nu e arhivat (`time_archived IS NULL`). Active sunt doar cele deschise acum.

## Adresa de livrare — coloana „Adresă"

Bara laterală arată exact cum va fi lovită fiecare sesiune:

| Valoare | Metodă | Cât de sigur |
|---|---|---|
| `cdp:28194` | inserare prin debugger-ul agentului | exact: câmpul e citit înainte și după, focusul nu e furat |
| `CTRL+3` | comutare de filă în fereastra agentului | bine, dacă numărul filei e corect |
| `blind` | nici port, nici număr de filă | promptul va ajunge în chat-ul deschis |

Niciun titlu de fereastră nu conține numele sesiunii — `claude.exe` se numește „Claude", Antigravity se numește „Antigravity", Freebuff se numește „Freebuff Desktop". Adresarea după fereastră e deci imposibilă, iar `blind` înseamnă exact ce scrie.

### CDP — calea de încredere

Dacă agentul e pornit cu `--remote-debugging-port`, SAISENT trimite prin debugger și nu atinge nici focusul, nici tastatura. Ce dă asta:

- textul e inserat direct în câmpul de introducere, nu „unde apucă";
- câmpul e citit **înainte** de inserare: dacă acolo e un mesaj neterminat, trimiterea refuză în loc să completeze propoziția altcuiva;
- câmpul e citit **după** inserare: n-a ajuns — nu trimitem.

Refuzul CDP nu retrogradează niciodată la taste oarbe. Transportul exact tocmai a spus că momentul nu e potrivit; să batești peste el taste e exact felul de a mânji chat-ul altcuiva.

Portul se ia din `DevToolsActivePort` al agentului, dar un singur fișier nu ajunge: rămâne de la o pornire anterioară. SAISENT se conectează cu adevărat la port înainte de fiecare probă.

Pornește debugger-ul pentru un agent (o repornire omoară ce face acum — SAISENT nu face niciodată asta singur):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Selectori de pagini (scoși din DOM live 2026-08-05)

| Agent | Port | Câmp de introducere | Listă de dialoguri |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | niciunul | — | — |

Antigravity verificat: 16 butoane, etichetele coincid exact cu numele proiectelor pe care le arată SAISENT (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — selectarea dialogului după nume funcționează precis.

CodeNomad e Electron peste OpenCode; folderul de date se cheamă încă `Plasticity`. Lista de sesiuni din DOM conține doar sesiunile **proiectului deschis acum**; o sesiune din alt proiect nu e randată, iar SAISENT n-o va găsi — trimiterea refuză, nu lovește la nimereală în chat-ul deschis.

Poți suprascrie orice cheie de profil în `SAISENT.json`:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Sesiunile se citesc din `~/.local/share/opencode/opencode.db`, tabela `session`: nume = `title`, proiect = `directory`, închisele se cerne după `time_archived`, senzorul — după `time_updated`. Singurul agent aici la care lista de sesiuni stă în coloane simple, fără protobuf și fără parsing.

Vivacitate — rulează `CodeNomad.exe`. Nu există număr de filă: se adresează după nume prin debugger.

## De ce nu după titlul ferestrei

Toate ferestrele `claude.exe` se numesc „Claude". Numele sesiunii nu ajunge în titlu, deci adresarea după fereastră e imposibilă — numele, proiectul și PID-ul se iau de pe disc; fereastra e necesară doar pentru focus.

## Confirmarea livrării

Chromium nu răspunde la `WM_GETTEXT`, deci citirea „a ajuns în câmp" prin Win32 e imposibilă — vechiul read-back la acești agenți returna mereu „neconfirmat". În schimb, SAISENT așteaptă să se miște același fișier pe care lucrează senzorul. S-a mișcat — livrat. Nu s-a mișcat în timpul alocat — promptul e marcat ca trimis, dar neconfirmat, și asta se vede în jurnal. Nu e considerat eroare: agentul s-ar putea să nu fi început încă runda.

Trimiterea se oprește la prima eroare reală (fereastra nu s-a găsit, focusul a fugit, clipboard-ul e ocupat). Prompturile următoare rămân în coadă — nu se pierd și nu pleacă orbește.

## Export și import

Butoanele **Export** și **Import** salvează/încarcă cozile în format JSONL. Fiecare rând e autosuficient cu cheia sesiunii. Importul unește fără pierdere de date — duplicatele (aceeași cheie + text) sunt sărite.

## Fișiere lângă program

| Fișier | Ce conține |
|---|---|
| `SAISENT.json` | setări: agenți, numere de file, timeout-uri, geometria ferestrei |
| `SAISENT_QUEUES.json` | cozi pe sesiuni, supraviețuiesc repornirii |
| `SAISENT.log` | jurnalul trimiterilor |

Coada nu se curăță niciodată singură. Sesiunea a dispărut din listă, dar în coada ei e netrimis — coada rămâne: agenții se repornesc, iar o coadă înghițită pe tăcute e mai rea decât un rând în plus în fișier.

## Setări fără interfață

Se editează în `SAISENT.json` (programul trebuie închis):

- `gap_ms` — pauză între prompturi într-o singură tură (implicit 1500);
- `settle_ms` — pauză după comutarea filei și după inserare (400);
- `confirm_seconds` — cât se așteaptă confirmarea livrării (10);
- `busy_seconds` — granița senzorului „busy/idle" (20);
- `freebuff_roots` — rădăcini unde se caută `.freebuff/desktop-v2.db`, ex. `["V:\\___VAC\\__K\\__CODE"]`; adâncime limitată la 3;
- `submit` — cu ce se trimite, implicit `ENTER`.

## Limitări

- Filele se adresează prin `Ctrl+1..Ctrl+9`. A zecea sesiune e inaccesibilă — `Ctrl+10` nu există, iar SAISENT va refuza, nu va rata.
- Numărul filei e o presupunere după ordinea pornirii. Prima rulare fă-o cu **Rulare de probă**, apoi pe o sesiune neimportantă.
- Antigravity nu păstrează numele conversației ca text: în listă va fi numele folderului de lucru scos din metadate.

## Teste

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
