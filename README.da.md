# SAISENT 4.0

Et kontrolpanel, der indsætter på forhånd forberedt tekst i de agentsessioner, der lige nu kører på denne maskine.

Læg teksten i køen for den rigtige session — SAISENT aktiverer agentvinduet, skifter til den sessions fane, indsætter teksten i én handling og trykker på Enter.

## Hurtig start

```
START_SAISENT.bat
```

Kræver Python 3.11+ på Windows.

## Sådan bruges det

1. **Agenter.** Øverste række — afkrydsningsfelter: Claude Code, Freebuff, Antigravity, CodeNomad.
   Marker en agent, og dens sessioner vises i panelet til venstre.
2. **Live-sessioner.** Til venstre står, hvad der faktisk kører: sessionens navn, fane-nummer, aktivitetssensor og projekt. Listen opdateres ikke af sig selv, medmindre du aktiverer "hver N s" — som standard kun via **Opdater**-knappen.
3. **Fane.** SAISENT gætter fane-nummeret ud fra sessionernes startrækkefølge. Forkert? Skriv nummeret manuelt i `SAISENT.json`, nøglen `tabs` (sessionsnøgle i formen `<agent>:<id>`, f.eks. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = skift slet ikke fane.
4. **Tekst.** Skriv (eller indsæt) nederst til højre, tryk på **I kø** (eller Ctrl+Enter). **Alt i kø** lægger samme tekst i hver live-session — erstatter den gamle makro "CTRL+2, tekst, CTRL+3, tekst".
5. **Køen.** Rækkefølgen af rækker = afsendelsesrækkefølgen. Træk en række med musen eller flyt den med **Op**/**Ned**. Hver session har sin egen kø. Dobbeltklik på en række (eller **Rediger**-knappen) henter prompten tilbage i tekstfeltet; **Gem ændring** overskriver den på stedet, **Annullér** kasserer. At redigere en allerede sendt prompt sender den tilbage i køen — teksten i rækken svarer ikke længere til, hvad sessionen modtog. **Dupliker** lægger en kopi direkte nedenunder.
6. **Afsendelse.** **SEND DENNE KØ** — kun den valgte session. **SEND ALLE** — alle køer i træk. **Tørkørsel** sender intet, viser bare planen i loggen. Ægte afsendelser spørger først om bekræftelse og nævner sessionerne.

## Fortryd afsendelse

Efter afsendelsen vises en **Fortryd**-knap i 30 sekunder. Den henter den sidst sendte prompt tilbage i køen som `pending` — medmindre sessionen allerede har behandlet den (bekræftet levering).

## Planlægning og grænser

I gruppen "Send":

- **Send kl (HH:MM)** — tomt betyder "nu". Med et klokkeslæt venter køen på næste forekomst af det tidspunkt (i dag, eller i morgen hvis overskredet) og viser en nedtælling i statuslinjen.
- **Vent på grænse-nulstilling** — før hver prompt læser SAISENT agentens egen tekst. Siger den "limit reached", venter køen og genoptager automatisk, når grænsen frigives. Ingen prompt mod en låst dør.
- **Tjek grænser** — genscan nu.
- Statusfeltet til højre viser live-tilstand: `limits: all agents free` eller `claude-code: LIMITED until 09:22 (1h 05m remaining)`, i rødt. Nedtællingen tikker én gang i sekundet fra cachen; disken berøres kun, når aflæsningen er forældet, eller når den angivne nulstillingstid indtræffer.

Nulstillingstiden tages fra agentens egne ord. Angiver den ikke nogen, skriver SAISENT "reset time not stated" i stedet for at finde på en pladsholder som "+5 timer".

### Hvornår nulstilles grænserne

Hvis agenten aldrig angiver en nulstillingstid, falder SAISENT tilbage på en regel pr. agent:

| Agent | Regel | Betydning |
|---|---|---|
| Freebuff | `daily 10:00` | nulstilles hver dag kl. 10:00 |
| CodeNomad | `daily 03:00` | nulstilles hver dag kl. 03:00 |
| Claude Code | `rolling 5h` | 5 timer efter den sidst sendte prompt |
| Antigravity | kun agentens ord | ingen regel — hvad den angiver, eller intet |

En regel tilsidesætter aldrig en tid, agenten har angivet; agenten er autoriteten over sin egen kvote. Enhver regel kan overskrives i `SAISENT.json` under `quota_plans`, f.eks. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Hvorfor de næste ikke sendes

Afsendelse er strengt sekventiel og stopper ved den første egentlige fejl. Årsagen vises i statuslinjen (`stopped: window not found: ...`), på prompt-rækken i listen og i loggen. Resten forbliver `pending` — intet er tabt.

Mellem prompter er der en `gap_ms`-pause (standard 1500 ms), og statusen viser `Waiting N.Ns before next`. Hvis en prompt blev sendt, men sessionen ikke bevægede sig, markeres den som **ubekræftet** og bliver i køen. "Sendt" anvendes kun på bekræftede leverancer.

## Aktivitetssensor

Kolonnen "Sensor" besvarer "kan jeg skrive lige nu".

- `busy` — sessionen skrev til sit lager for mindre end 20 sekunder siden (agenten er midt i et træk);
- `idle` — stilhed i mere end 20 sekunder, indtastningsfeltet er frit.

Hvor det kommer fra:

| Agent | Kilde | Sensor |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + transskription | seneste skrivetid i transskriptionen |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, tabellen `threads` | feltet `turn_state` |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime for databasen og dens `-wal` |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | seneste skrivetid i transskriptionen |

Live-tilstand er en separat kontrol, ikke "filen på disken er frisk":

- **Claude Code** — PID'en fra `~/.claude/sessions/<pid>.json` lever. Filen overlever sessionens lukning; PID'en gør ikke.
- **Freebuff** — `Freebuff.exe` kører. Databasen holder tråde `open`, selv efter appen er lukket.
- **Antigravity** — `Antigravity.exe` kører **og** samtalen er frisk. Friskhed alene er ikke nok: dette lager gemmer alle samtaler for evigt, og en lukket editor plejede at fylde listen med sessioner, som ingen tast kunne nå.
- **CodeNomad** — databaserækken er ikke arkiveret (`time_archived IS NULL`). Aktive er kun dem, der er åbne lige nu.

## Leveringsadresse — kolonnen "Adresse"

Sidepanelet viser præcis, hvordan hver session vil blive ramt:

| Værdi | Metode | Pålidelighed |
|---|---|---|
| `cdp:28194` | Indsæt via agentens debugger | Præcis: felt læst før og efter, fokus stjæles ikke |
| `CTRL+3` | Faneskift i agentvinduet | Godt, hvis fane-nummeret er korrekt |
| `blind` | Ingen port, intet fane-nummer | Prompterne havner i den chat, der er åben |

Ingen vinduestitel indeholder et sessionsnavn — `claude.exe` kaldes "Claude", Antigravity kaldes "Antigravity", Freebuff kaldes "Freebuff Desktop". Adressering via vinduet er derfor umulig, og `blind` betyder præcis, hvad det siger.

### CDP — den pålidelige vej

Hvis en agent blev startet med `--remote-debugging-port`, sender SAISENT via debuggeren og rører hverken fokus eller tastatur. Det betyder:

- teksten indsættes direkte i indtastningsfeltet, ikke "hvor som helst";
- feltet læses **før** indsættelse: hvis der ligger en halvskrevet besked, nægter afsendelsen i stedet for at tilføje til en andens sætning;
- feltet læses **efter** indsættelse: hvis den ikke landede, sender vi ikke.

Et CDP-afslag falder aldrig tilbage på blinde tastetryk. Det præcise transportsystem har lige sagt, at øjeblikket er forkert; at hamre taster oveni er præcis sådan, man ødelægger en andens chat.

Porten læses fra agentens `DevToolsActivePort`, men en fil alene er ikke nok — den overlever en tidligere start. SAISENT forbinder faktisk til porten før hver sondering.

Aktivér debuggeren for en agent (en genstart dræber, hvad den laver — SAISENT gør det aldrig selv):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Sidevælgere (live DOM, 2026-08-05)

| Agent | Port | Indtastningsfelt | Dialogliste |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | ingen | — | — |

Antigravity verificeret: 16 knapper, etiketterne matcher præcis de projektnavne, SAISENT viser (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — valg af dialog efter navn fungerer præcist.

CodeNomad er Electron oven på OpenCode; datamappen kaldes stadig `Plasticity`. Sessionslisten i DOM indeholder kun sessioner fra det **aktuelt åbne projekt**; en session fra et andet projekt renderes ikke, og SAISENT finder den ikke — afsendelsen nægter i stedet for blidt at ramme den åbne chat.

Overskriv en hvilken som helst profilynøgle i `SAISENT.json`:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Sessioner læses fra `~/.local/share/opencode/opencode.db`, tabellen `session`: navn = `title`, projekt = `directory`, arkiverede filtreres via `time_archived`, sensoren via `time_updated`. Den eneste agent her, hvis sessionsliste er almindelige kolonner — ingen protobuf, ingen parsing.

Live-tilstand — `CodeNomad.exe` kører. Intet fane-nummer: adresseres efter navn gennem debuggeren.

## Hvorfor ikke efter vinduestitel

Hvert `claude.exe`-vindue kaldes "Claude". Sessionsnavnet vises aldrig i titlen, så adressering via vinduet er umulig — navnet, projektet og PID'en kommer fra disken; vinduet er kun nødvendigt for fokus.

## Leveringsbekræftelse

Chromium svarer ikke på `WM_GETTEXT`, så at læse "landede det" via Win32 er umuligt — den gamle read-back for disse agenter returnerede altid "ubekræftet". I stedet venter SAISENT på, at den samme fil, aktivitetssensoren holder øje med, bevæger sig. Bevægede den sig? Leveret. Bevægede den sig ikke inden for den tildelte tid? Prompten markeres som sendt, men ubekræftet, og det er synligt i loggen. Det tælles ikke som en fejl: agenten har måske bare ikke startet sit træk endnu.

Afsendelsen stopper ved den første egentlige fejl (vindue ikke fundet, fokus mistet, udklipsholder optaget). Efterfølgende prompter bliver i køen — de går ikke tabt og sendes ikke blindt.

## Eksport & Import

Knapperne **Eksporter** og **Importer** gemmer/loader køer i JSONL-format. Hver linje er selvstændig med sin sessionsnøgle. Import fletter uden datatab — dubletter (samme nøgle + tekst) springes over.

## Filer ved siden af programmet

| Fil | Indhold |
|---|---|
| `SAISENT.json` | indstillinger: agenter, fane-numre, tidsgrænser, vinduegeometri |
| `SAISENT_QUEUES.json` | køer pr. session, overlever genstart |
| `SAISENT.log` | log over afsendelser |

Køen ryddes aldrig automatisk. Hvis en session forsvinder fra listen, men har usendte elementer, bliver køen: agenter genstartes, og en lydløst kasseret kø er værre end en ekstra linje i en fil.

## Skjulte indstillinger

Rediger `SAISENT.json`, mens programmet er lukket:

- `gap_ms` — pause mellem prompter i én batch (standard 1500);
- `settle_ms` — pause efter faneskift og efter indsættelse (400);
- `confirm_seconds` — hvor længe vente på leveringsbekræftelse (10);
- `busy_seconds` — tærsklen for sensoren "busy/idle" (20);
- `freebuff_roots` — rødder, hvor `.freebuff/desktop-v2.db` søges, f.eks. `["V:\\___VAC\\__K\\__CODE"]`; søgedybde begrænset til 3;
- `submit` — tast til at sende, standard `ENTER`.

## Begrænsninger

- Faner adresseres via `Ctrl+1..Ctrl+9`. En tiende session er uopnåelig — `Ctrl+10` findes ikke, og SAISENT nægter i stedet for at gætte.
- Fane-nummeret er et gæt baseret på startrækkefølge. Lav din første kørsel med **Tørkørsel**, derefter på en uvigtig session.
- Antigravity gemmer ikke samtalenavne som tekst: listen viser navnet på arbejdsmappen, hentet fra metadata.

## Tests

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
