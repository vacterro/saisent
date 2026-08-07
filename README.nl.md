# SAISENT 4.0

Een bedieningspaneel dat vooraf voorbereide tekst invoegt in de agentsessies die op dit moment op deze machine draaien.

Zet de tekst in de wachtrij van de juiste sessie — SAISENT activeert het venster van de agent, schakelt naar het tabblad van die sessie, plakt de tekst in één handeling en drukt op Enter.

## Snel starten

```
START_SAISENT.bat
```

Vereist Python 3.11+ op Windows.

## Hoe te gebruiken

1. **Agents.** Bovenste rij — selectievakjes: Claude Code, Freebuff, Antigravity, CodeNomad.
   Vink een agent aan en de sessies verschijnen in het linkerpaneel.
2. **Live-sessies.** Links staat wat echt draait: sessienaam, tabnummer, activiteitssensor en project. De lijst vernieuwt zich niet zelf, tenzij je 'elke N s' inschakelt — standaard alleen via de knop **Vernieuwen**.
3. **Tab.** SAISENT raadt het tabnummer uit de startvolgorde van de sessies. Fout? Typ het nummer handmatig in `SAISENT.json`, sleutel `tabs` (sessiesleutel in de vorm `<agent>:<id>`, bijv. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = helemaal niet van tab wisselen.
4. **Tekst.** Schrijf (of plak) rechtsonder, druk op **In wachtrij** (of Ctrl+Enter). **Alles in wachtrij** plaatst dezelfde tekst in elke live-sessie — vervangt de oude macro 'CTRL+2, tekst, CTRL+3, tekst'.
5. **Wachtrij.** Regelvolgorde = verzendvolgorde. Sleep een regel met de muis of verplaats hem met **Omhoog**/**Omlaag**. Elke sessie heeft zijn eigen wachtrij. Dubbelklik op een regel (of knop **Bewerken**) haalt de prompt terug naar het tekstveld; **Bewerking opslaan** schrijft hem ter plekke, **Annuleren** gooit weg. Het bewerken van een reeds verzonden prompt zet hem terug in de wachtrij — de tekst in de regel komt niet meer overeen met wat de sessie ontving. **Dupliceren** plaatst een kopie er direct onder.
6. **Verzenden.** **DEZE WACHTRIJ VERZENDEN** — alleen de geselecteerde sessie. **ALLES VERZENDEN** — alle wachtrijen op rij. **Droge run** verzendt niets, toont alleen het plan in het logboek. Echte verzendingen vragen eerst bevestiging en noemen de sessies.

## Verzenden ongedaan maken

Na het verzenden verschijnt een knop **Ongedaan maken** gedurende 30 seconden. Hij haalt de laatste verzonden prompt terug in de wachtrij als `pending` — tenzij de sessie hem al heeft verwerkt (bevestigde levering).

## Planning en limieten

In de groep 'Verzenden':

- **Verzenden om (HH:MM)** — leeg betekent 'nu'. Met een tijd wacht de wachtrij op het volgende optreden van die tijd (vandaag, of morgen als voorbij) en toont een aftelling in de statusbalk.
- **Wachten op limietreset** — voor elke prompt leest SAISENT de eigen tekst van de agent. Zegt hij 'limit reached', dan wacht de wachtrij en hervat automatisch zodra het limiet vrij is. Geen enkele prompt tegen een gesloten deur.
- **Limieten controleren** — nu opnieuw scannen.
- Het statusveld rechts toont de live-status: `limits: all agents free` of `claude-code: LIMITED until 09:22 (1h 05m remaining)`, in het rood. De aftelling tikt één keer per seconde uit de cache; de schijf wordt alleen aangeraakt wanneer de meting verouderd is of de genoemde resettijd aanbreekt.

De resettijd komt uit de eigen woorden van de agent. Noemt hij er geen, dan schrijft SAISENT 'reset time not stated' in plaats van een plaatshouder zoals '+5 uur' te verzinnen.

### Wanneer limieten worden gereset

Noemt de agent nooit een resettijd, dan valt SAISENT terug op een regel per agent:

| Agent | Regel | Betekenis |
|---|---|---|
| Freebuff | `daily 10:00` | reset elke dag om 10:00 |
| CodeNomad | `daily 03:00` | reset elke dag om 03:00 |
| Claude Code | `rolling 5h` | 5 uur na de laatste verzonden prompt |
| Antigravity | alleen de woorden van de agent | geen regel — wat hij aangeeft, of niets |

Een regel overschrijft nooit een door de agent genoemde tijd; de agent is de autoriteit over zijn eigen quotum. Elke regel kan worden overschreven in `SAISENT.json` onder `quota_plans`, bijv. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Waarom de volgende niet gaan

Het verzenden is strikt sequentieel en stopt bij de eerste echte fout. De reden verschijnt in de statusbalk (`stopped: window not found: ...`), op de promptregel in de lijst en in het logboek. De rest blijft `pending` — niets is verloren.

Tussen prompts zit een `gap_ms`-pauze (standaard 1500 ms) en de status toont `Waiting N.Ns before next`. Werd een prompt verzonden maar bewoog de sessie niet, dan geldt hij als **ongekwalificeerd** en blijft in de wachtrij. 'Verzonden' wordt alleen toegepast op bevestigde leveringen.

## Activiteitssensor

De kolom 'Sensor' beantwoordt 'kan ik nu typen'.

- `busy` — de sessie heeft minder dan 20 seconden geleden naar zijn opslag geschreven (de agent zit midden in een zet);
- `idle` — stilte langer dan 20 seconden, het invoerveld is vrij.

Waar het vandaan komt:

| Agent | Bron | Sensor |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + transcript | laatste schrijftijd in transcript |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, tabel `threads` | veld `turn_state` |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime van de DB en de `-wal` |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | laatste schrijftijd in transcript |

Levensvatbaarheid is een aparte controle, niet 'het bestand op schijf is vers':

- **Claude Code** — de PID uit `~/.claude/sessions/<pid>.json` leeft. Het bestand overleeft het sluiten van de sessie; de PID niet.
- **Freebuff** — `Freebuff.exe` draait. De DB houdt threads `open`, zelfs na het afsluiten van de app.
- **Antigravity** — `Antigravity.exe` draait **en** het gesprek is vers. Versheid alleen is niet genoeg: deze opslag bewaart alle gesprekken voor altijd, en een gesloten editor vulde de lijst vroeger met sessies die geen enkele toets kon bereiken.
- **CodeNomad** — de DB-regel is niet gearchiveerd (`time_archived IS NULL`). Actief zijn alleen de op dit moment geopende sessies.

## Leveradres — kolom 'Adres'

De zijbalk toont precies hoe elke sessie zal worden aangepakt:

| Waarde | Methode | Betrouwbaarheid |
|---|---|---|
| `cdp:28194` | Plakken via de debugger van de agent | Exact: veld voor en na gelezen, focus wordt niet gestolen |
| `CTRL+3` | Tabwissel in het venster van de agent | Goed, als het tabnummer klopt |
| `blind` | Geen poort, geen tabnummer | De prompt belandt in de chat die openstaat |

Geen enkele venstertitel bevat een sessienaam — `claude.exe` heet 'Claude', Antigravity heet 'Antigravity', Freebuff heet 'Freebuff Desktop'. Adresseren via het venster is daarom onmogelijk, en `blind` betekent precies wat het zegt.

### CDP — de betrouwbare weg

Als een agent is gestart met `--remote-debugging-port`, verzendt SAISENT via de debugger en raakt noch focus noch toetsenbord aan. Dit betekent:

- de tekst wordt rechtstreeks in het invoerveld geplakt, niet 'waar het uitkomt';
- het veld wordt **vóór** het plakken gelezen: ligt er een halfgeschreven bericht, dan weigert de verzending in plaats van aan te vullen bij de zin van een ander;
- het veld wordt **na** het plakken gelezen: is het niet geland, dan verzenden we niet.

Een CDP-weigering valt nooit terug op blinde toetsaanslagen. Het precieze transport heeft zojuist gezegd dat het moment verkeerd is; daaroverheen toetsen hameren is precies de manier om de chat van een ander te verpesten.

De poort wordt gelezen uit `DevToolsActivePort` van de agent, maar een bestand alleen is niet genoeg — het overleeft een eerdere start. SAISENT verbindt zich vóór elke peiling daadwerkelijk met de poort.

Debugger voor een agent inschakelen (een herstart doodt wat hij doet — SAISENT doet dit zelf nooit):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Pagina-selectors (live DOM, 2026-08-05)

| Agent | Poort | Invoerveld | Dialooglijst |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | geen | — | — |

Antigravity geverifieerd: 16 knoppen, labels komen exact overeen met de projectnamen die SAISENT toont (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — de selectie van het dialoogvenster op naam werkt precies.

CodeNomad is Electron op OpenCode; de datamap heet nog steeds `Plasticity`. De sessielijst in het DOM bevat alleen sessies van het **momenteel geopende project**; een sessie uit een ander project wordt niet gerenderd en SAISENT vindt hem niet — de verzending weigert in plaats van blind de open chat te raken.

Een profielsleutel overschrijven in `SAISENT.json`:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Sessies worden gelezen uit `~/.local/share/opencode/opencode.db`, tabel `session`: naam = `title`, project = `directory`, gearchiveerde gefilterd op `time_archived`, sensor op `time_updated`. De enige agent hier wiens sessielijst gewone kolommen zijn — geen protobuf, geen parsing.

Levensvatbaarheid — `CodeNomad.exe` draait. Geen tabnummer: op naam geadresseerd via de debugger.

## Waarom niet via venstertitel

Elk `claude.exe`-venster heet 'Claude'. De sessienaam verschijnt nooit in de titel, dus adresseren via het venster is onmogelijk — naam, project en PID komen van de schijf; het venster is alleen nodig voor de focus.

## Leveringsbevestiging

Chromium beantwoordt `WM_GETTEXT` niet, dus 'is het geland' via Win32 lezen is onmogelijk — de oude read-back voor deze agents gaf altijd 'niet bevestigd' terug. In plaats daarvan wacht SAISENT tot hetzelfde bestand beweegt dat de activiteitssensor bewaakt. Bewogen? Geleverd. Niet bewogen binnen de toegewezen tijd? De prompt wordt gemarkeerd als verzonden maar onbevestigd, en dit is zichtbaar in het logboek. Dit geldt niet als fout: de agent is misschien gewoon nog niet aan zijn zet begonnen.

Het verzenden stopt bij de eerste echte fout (venster niet gevonden, focus verloren, klembord bezet). Volgende prompts blijven in de wachtrij — ze gaan niet verloren en worden niet blind verzonden.

## Exporteren & importeren

De knoppen **Exporteren** en **Importeren** bewaren/laden wachtrijen in JSONL-formaat. Elke regel is zelfstandig met zijn sessiesleutel. Importeren voegt samen zonder gegevensverlies — duplicaten (zelfde sleutel + tekst) worden overgeslagen.

## Bestanden naast het programma

| Bestand | Inhoud |
|---|---|
| `SAISENT.json` | instellingen: agents, tabnummers, time-outs, venstergeometrie |
| `SAISENT_QUEUES.json` | wachtrijen per sessie, overleven herstart |
| `SAISENT.log` | verzendgeschiedenis |

De wachtrij wordt nooit automatisch opgeruimd. Als een sessie uit de lijst verdwijnt maar onverzonden items heeft, blijft de wachtrij: agents worden herstart en een stil weggegooide wachtrij is erger dan een extra regel in een bestand.

## Verborgen instellingen

Bewerk `SAISENT.json` terwijl het programma gesloten is:

- `gap_ms` — pauze tussen prompts in één batch (standaard 1500);
- `settle_ms` — pauze na tabwissel en na het plakken (400);
- `confirm_seconds` — hoe lang wachten op leveringsbevestiging (10);
- `busy_seconds` — drempel van de sensor 'busy/idle' (20);
- `freebuff_roots` — wortels waar gezocht wordt naar `.freebuff/desktop-v2.db`, bijv. `["V:\\___VAC\\__K\\__CODE"]`; zoekdiepte beperkt tot 3;
- `submit` — toets om te verzenden, standaard `ENTER`.

## Beperkingen

- Tabs worden geadresseerd via `Ctrl+1..Ctrl+9`. Een tiende sessie is onbereikbaar — `Ctrl+10` bestaat niet, en SAISENT weigert in plaats van te raden.
- Het tabnummer is een schatting op basis van startvolgorde. Doe je eerste run met **Droge run**, daarna op een onbelangrijke sessie.
- Antigravity slaat gespreksnamen niet als tekst op: de lijst toont de naam van de werkmap, geëxtraheerd uit metadata.

## Tests

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
