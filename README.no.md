# SAISENT 4.0

Et kontrollpanel som limer inn forhåndsforberedt tekst i agentsesjonene som akkurat nå kjører på denne maskinen.

Legg teksten i kø for riktig sesjon — SAISENT aktiverer agentvinduet, bytter til den sesjonens fane, limer inn teksten i én operasjon og trykker Enter.

## Hurtigstart

```
START_SAISENT.bat
```

Krever Python 3.11+ på Windows.

## Slik bruker du det

1. **Agenter.** Øverste rad — avkrysningsbokser: Claude Code, Freebuff, Antigravity, CodeNomad.
   Kryss av en agent, så vises sesjonene i panelet til venstre.
2. **Live-sesjoner.** Til venstre står det som faktisk kjører: sesjonsnavn, fane-nummer, aktivitetssensor og prosjekt. Listen oppdateres ikke av seg selv, med mindre du aktiverer «hver N s» — som standard bare via **Oppdater**-knappen.
3. **Fane.** SAISENT gjetter fane-nummeret ut fra sesjonenes startrekkefølge. Feil? Skriv nummeret manuelt i `SAISENT.json`, nøkkelen `tabs` (sesjonsnøkkel i formen `<agent>:<id>`, f.eks. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = ikke bytt fane i det hele tatt.
4. **Tekst.** Skriv (eller lim inn) nederst til høyre, trykk på **I kø** (eller Ctrl+Enter). **Alt i kø** legger samme tekst inn i hver live-sesjon — erstatter den gamle makroen «CTRL+2, tekst, CTRL+3, tekst».
5. **Køen.** Radrekkefølgen = sendingsrekkefølgen. Dra en rad med musen eller flytt den med **Opp**/**Ned**. Hver sesjon har sin egen kø. Dobbeltklikk på en rad (eller **Rediger**-knappen) henter prompten tilbake i tekstfeltet; **Lagre endring** skriver den om på stedet, **Avbryt** forkaster. Å redigere en allerede sendt prompt sender den tilbake i køen — teksten i raden stemmer ikke lenger med det sesjonen fikk. **Dupliser** legger en kopi rett under.
6. **Sending.** **SEND DENNE KØEN** — bare den valgte sesjonen. **SEND ALLE** — alle køer i rekkefølge. **Tørrkjøring** sender ingenting, viser bare planen i loggen. Ekte sendinger spør først om bekreftelse og navngir sesjonene.

## Angre sending

Etter sendingen vises en **Angre**-knapp i 30 sekunder. Den henter den sist sendte prompten tilbake i køen som `pending` — med mindre sesjonen allerede har behandlet den (bekreftet levering).

## Planlegging og grenser

I gruppen «Send»:

- **Send kl (HH:MM)** — tomt betyr «nå». Med et klokkeslett venter køen på neste forekomst av det tidspunktet (i dag, eller i morgen hvis det er passert) og viser en nedtelling i statuslinjen.
- **Vent på grensetilbakestilling** — før hver prompt leser SAISENT agentens egen tekst. Sier den «limit reached», venter køen og gjenopptas automatisk når grensen slipper. Ikke én prompt mot en låst dør.
- **Sjekk grenser** — skann på nytt nå.
- Statusfeltet til høyre viser live-tilstanden: `limits: all agents free` eller `claude-code: LIMITED until 09:22 (1h 05m remaining)`, i rødt. Nedtellingen tikker én gang i sekundet fra cachen; disken berøres bare når avlesningen er foreldet eller den oppgitte tilbakestillingstiden inntreffer.

Tilbakestillingstiden tas fra agentens egne ord. Oppgir den ingen, skriver SAISENT «reset time not stated» i stedet for å finne på en plassholder som «+5 timer».

### Når grenser tilbakestilles

Hvis agenten aldri oppgir en tilbakestillingstid, faller SAISENT tilbake på en regel per agent:

| Agent | Regel | Betydning |
|---|---|---|
| Freebuff | `daily 10:00` | tilbakestilles hver dag kl. 10:00 |
| CodeNomad | `daily 03:00` | tilbakestilles hver dag kl. 03:00 |
| Claude Code | `rolling 5h` | 5 timer etter den sist sendte prompten |
| Antigravity | bare agentens ord | ingen regel — hva den oppgir, eller ingenting |

En regel overstyrer aldri en tid agenten har oppgitt; agenten er autoriteten over sin egen kvote. Enhver regel kan overskrives i `SAISENT.json` under `quota_plans`, f.eks. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Hvorfor de neste ikke sendes

Sending er strengt sekvensiell og stopper ved den første ekte feilen. Årsaken vises i statuslinjen (`stopped: window not found: ...`), på prompt-raden i listen og i loggen. Resten forblir `pending` — ingenting er tapt.

Mellom prompter er det en `gap_ms`-pause (standard 1500 ms), og statusen viser `Waiting N.Ns before next`. Hvis en prompt ble sendt, men sesjonen ikke beveget seg, markeres den som **ubekreftet** og blir i køen. «Sendt» brukes bare på bekreftede leveranser.

## Aktivitetssensor

Kolonnen «Sensor» svarer på «kan jeg skrive akkurat nå».

- `busy` — sesjonen skrev til lagringsstedet sitt for mindre enn 20 sekunder siden (agenten er midt i et trekk);
- `idle` — stillhet i mer enn 20 sekunder, inntastingsfeltet er ledig.

Hvor det kommer fra:

| Agent | Kilde | Sensor |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + transkript | siste skrivetid i transkriptet |
| Freebuff | `<prosjekt>/.freebuff/desktop-v2.db`, tabellen `threads` | feltet `turn_state` |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime for databasen og dens `-wal` |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | siste skrivetid i transkriptet |

Live-tilstand er en separat kontroll, ikke «filen på disken er fersk»:

- **Claude Code** — PID-en fra `~/.claude/sessions/<pid>.json` lever. Filen overlever at sesjonen lukkes; PID-en gjør ikke det.
- **Freebuff** — `Freebuff.exe` kjører. Databasen holder tråder `open` selv etter at appen er avsluttet.
- **Antigravity** — `Antigravity.exe` kjører **og** samtalen er fersk. Ferskhet alene er ikke nok: dette lageret holder alle samtaler for alltid, og en lukket editor pleide å fylle listen med sesjoner ingen tast kunne nå.
- **CodeNomad** — databaseraden er ikke arkivert (`time_archived IS NULL`). Aktive er bare de som er åpne akkurat nå.

## Leveringsadresse — kolonnen «Adresse»

Sidepanelet viser nøyaktig hvordan hver sesjon vil bli truffet:

| Verdi | Metode | Pålitelighet |
|---|---|---|
| `cdp:28194` | Lim inn via agentens debugger | Nøyaktig: felt lest før og etter, fokus stjeles ikke |
| `CTRL+3` | Fanebytte i agentvinduet | Bra, hvis fane-nummeret er riktig |
| `blind` | Ingen port, intet fane-nummer | Prompten havner i den chatten som er åpen |

Ingen vindutittel inneholder et sesjonsnavn — `claude.exe` heter «Claude», Antigravity heter «Antigravity», Freebuff heter «Freebuff Desktop». Å adressere via vinduet er derfor umulig, og `blind` betyr nøyaktig det det sier.

### CDP — den pålitelige veien

Hvis en agent ble startet med `--remote-debugging-port`, sender SAISENT via debuggeren og rører verken fokus eller tastatur. Det betyr:

- teksten limes rett inn i inntastingsfeltet, ikke «hvor som helst»;
- feltet leses **før** innlimingen: hvis det ligger en halvskrevet melding der, nekter sendingen i stedet for å legge seg til en annens setning;
- feltet leses **etter** innlimingen: hvis den ikke landet, sender vi ikke.

Et CDP-avslag faller aldri tilbake på blinde tastetrykk. Det presise transportmiddelet har nettopp sagt at øyeblikket er feil; å hamre taster oppå det er nøyaktig slik man ødelegger en annens chat.

Porten leses fra agentens `DevToolsActivePort`, men en fil alene er ikke nok — den overlever en tidligere start. SAISENT kobler seg faktisk til porten før hver sondering.

Aktiver debuggeren for en agent (en omstart dreper det den gjør — SAISENT gjør aldri dette selv):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Sidevelgere (live-DOM, 2026-08-05)

| Agent | Port | Inntastingsfelt | Dialogliste |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | ingen | — | — |

Antigravity verifisert: 16 knapper, etikettene samsvarer nøyaktig med prosjektnavnene SAISENT viser (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — dialogvalget etter navn fungerer presist.

CodeNomad er Electron oppå OpenCode; datamappen heter fortsatt `Plasticity`. Sesjonslisten i DOM inneholder bare sesjoner fra det **for øyeblikket åpne prosjektet**; en sesjon fra et annet prosjekt renderes ikke, og SAISENT finner den ikke — sendingen nekter i stedet for å treffe den åpne chatten blindt.

Overskriv en hvilken som helst profilsnøkkel i `SAISENT.json`:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Sesjoner leses fra `~/.local/share/opencode/opencode.db`, tabellen `session`: navn = `title`, prosjekt = `directory`, arkiverte filtreres via `time_archived`, sensoren via `time_updated`. Den eneste agenten her hvis sesjonsliste er vanlige kolonner — ingen protobuf, ingen parsing.

Live-tilstand — `CodeNomad.exe` kjører. Intet fane-nummer: adresseres etter navn gjennom debuggeren.

## Hvorfor ikke etter vindutittel

Hvert `claude.exe`-vindu heter «Claude». Sesjonsnavnet vises aldri i tittelen, så å adressere via vinduet er umulig — navnet, prosjektet og PID-en kommer fra disken; vinduet trengs bare for fokus.

## Leveringsbekreftelse

Chromium svarer ikke på `WM_GETTEXT`, så å lese «landet det» via Win32 er umulig — den gamle read-backen for disse agentene returnerte alltid «ubekreftet». I stedet venter SAISENT på at den samme filen som aktivitetssensoren følger med på, beveger seg. Beveget den seg? Levert. Beveget den seg ikke innen tildelt tid? Prompten markeres som sendt, men ubekreftet, og det er synlig i loggen. Det regnes ikke som en feil: agenten har kanskje bare ikke startet trekket sitt ennå.

Sendingen stopper ved den første ekte feilen (vindu ikke funnet, fokus mistet, utklippstavle opptatt). Etterfølgende prompter blir i køen — de går ikke tapt og sendes ikke blindt.

## Eksport & Import

Knappene **Eksporter** og **Importer** lagrer/laster køer i JSONL-format. Hver linje er selvstendig med sin sesjonsnøkkel. Import slår sammen uten datatap — duplikater (samme nøkkel + tekst) hoppes over.

## Filer ved siden av programmet

| Fil | Innhold |
|---|---|
| `SAISENT.json` | innstillinger: agenter, fane-nummer, tidsgrenser, vindugeometri |
| `SAISENT_QUEUES.json` | køer per sesjon, overlever omstart |
| `SAISENT.log` | logg over sendinger |

Køen ryddes aldri automatisk. Hvis en sesjon forsvinner fra listen, men har usendte elementer, blir køen: agenter startes på nytt, og en lydløst kastet kø er verre enn en ekstra linje i en fil.

## Skjulte innstillinger

Rediger `SAISENT.json` mens programmet er lukket:

- `gap_ms` — pause mellom prompter i én batch (standard 1500);
- `settle_ms` — pause etter fanebytte og etter innliming (400);
- `confirm_seconds` — hvor lenge vente på leveringsbekreftelse (10);
- `busy_seconds` — terskelen for sensoren «busy/idle» (20);
- `freebuff_roots` — røtter der `.freebuff/desktop-v2.db` søkes, f.eks. `["V:\\___VAC\\__K\\__CODE"]`; søkedybde begrenset til 3;
- `submit` — tast for å sende, standard `ENTER`.

## Begrensninger

- Faner adresseres via `Ctrl+1..Ctrl+9`. En tiende sesjon er uoppnåelig — `Ctrl+10` finnes ikke, og SAISENT nekter i stedet for å gjette.
- Fane-nummeret er en gjetning basert på startrekkefølge. Gjør den første kjøringen med **Tørrkjøring**, deretter på en uviktig sesjon.
- Antigravity lagrer ikke samtalens navn som tekst: listen viser navnet på arbeidsmappen, hentet fra metadata.

## Tester

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
