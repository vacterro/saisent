# SAISENT 4.0

En kontrollpanel som klistrar in förberedd text i agentsessionerna som just nu körs på den här maskinen.

Lägg texten i kö för rätt session — SAISENT aktiverar agentfönstret, växlar till den sessionens flik, klistrar in texten i en enda åtgärd och trycker på Enter.

## Snabbstart

```
START_SAISENT.bat
```

Kräver Python 3.11+ på Windows.

## Så här använder du

1. **Agenter.** Översta raden — kryssrutor: Claude Code, Freebuff, Antigravity, CodeNomad.
   Markera en agent så dyker dess sessioner upp i den vänstra panelen.
2. **Live-sessioner.** Till vänster står det som faktiskt körs: sessionens namn, fliknummer, aktivitetssensor och projekt. Listan uppdateras inte av sig själv om du inte aktiverar "var N s" — som standard bara via **Uppdatera**-knappen.
3. **Flik.** SAISENT gissar fliknumret från sessionernas startordning. Fel? Skriv numret manuellt i `SAISENT.json`, nyckeln `tabs` (sessionsnyckel i formen `<agent>:<id>`, t.ex. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = växla inte flik alls.
4. **Text.** Skriv (eller klistra in) längst ner till höger, tryck på **Kö** (eller Ctrl+Enter). **Allt till kön** lägger samma text i varje live-session — ersätter den gamla makrofunktionen "CTRL+2, text, CTRL+3, text".
5. **Kön.** Radordningen = skickordningen. Dra en rad med musen eller flytta den med **Upp**/**Ner**. Varje session har sin egen kö. Dubbelklicka på en rad (eller **Redigera**-knappen) för att hämta tillbaka prompten i textfältet; **Spara ändring** skriver om den på plats, **Avbryt** kastar. Att redigera en redan skickad prompt returnerar den till kön — texten i raden stämmer inte längre överens med vad sessionen fick. **Duplicera** lägger en kopia direkt under.
6. **Skicka.** **SKICKA DEN HÄR KÖN** — bara den valda sessionen. **SKICKA ALLT** — alla köer i ordning. **Torrkörning** skickar ingenting, visar bara planen i loggen. Riktiga utskick frågar först om bekräftelse och namnger sessionerna.

## Ångra utskick

Efter utskicket visas en **Ångra**-knapp i 30 sekunder. Den hämtar tillbaka den senast skickade prompten till kön som `pending` — om inte sessionen redan har bearbetat den (bekräftad leverans).

## Schemaläggning och gränser

I gruppen "Skicka":

- **Skicka kl (HH:MM)** — tomt betyder "nu". Med en tid väntar kön på nästa förekomst av den tiden (idag, eller imorgon om den passerat) och visar en nedräkning i statusraden.
- **Vänta på gränsåterställning** — före varje prompt läser SAISENT agentens egen text. Säger den "limit reached" väntar kön och återupptas automatiskt när gränsen släpper. Ingen prompt mot en låst dörr.
- **Kontrollera gränser** — skanna om nu.
- Statusfältet till höger visar live-tillstånd: `limits: all agents free` eller `claude-code: LIMITED until 09:22 (1h 05m remaining)`, i rött. Nedräkningen tickar en gång per sekund från cachen; disken rörs bara när avläsningen är inaktuell eller när den angivna återställningstiden infaller.

Återställningstiden tas från agentens egna ord. Anger den ingen, skriver SAISENT "reset time not stated" istället för att hitta på en platshållare som "+5 timmar".

### När gränserna återställs

Om agenten aldrig anger en återställningstid faller SAISENT tillbaka på en regel per agent:

| Agent | Regel | Betydelse |
|---|---|---|
| Freebuff | `daily 10:00` | återställs varje dag kl 10:00 |
| CodeNomad | `daily 03:00` | återställs varje dag kl 03:00 |
| Claude Code | `rolling 5h` | 5 timmar efter den senast skickade prompten |
| Antigravity | bara agentens ord | ingen regel — vad den anger, eller inget |

En regel åsidosätter aldrig en tid som agenten angett; agenten är auktoriteten över sin egen kvot. Vilken regel som helst kan skrivas över i `SAISENT.json` under `quota_plans`, t.ex. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Varför de nästa inte skickas

Utskick är strikt sekventiellt och stannar vid det första verkliga felet. Orsaken syns i statusraden (`stopped: window not found: ...`), på promptraden i listan och i loggen. Resten förblir `pending` — ingenting går förlorat.

Mellan prompter finns en `gap_ms`-paus (standard 1500 ms) och statusen visar `Waiting N.Ns before next`. Om en prompt skickades men sessionen inte rörde sig markeras den som **obekräftad** och stannar i kön. "Skickad" tillämpas bara på bekräftade leveranser.

## Aktivitetsensor

Kolumnen "Sensor" svarar på "kan jag skriva just nu".

- `busy` — sessionen skrev till sitt lager för mindre än 20 sekunder sedan (agenten är mitt i ett drag);
- `idle` — tystnad längre än 20 sekunder, inmatningsfältet är ledigt.

Varifrån den kommer:

| Agent | Källa | Sensor |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + transkript | senaste skrivtiden i transkriptet |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, tabellen `threads` | fältet `turn_state` |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime för databasen och dess `-wal` |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | senaste skrivtiden i transkriptet |

Livlighet är en separat kontroll, inte "filen på disken är färsk":

- **Claude Code** — PID:n från `~/.claude/sessions/<pid>.json` lever. Filen överlever stängningen av sessionen; PID:n gör inte det.
- **Freebuff** — `Freebuff.exe` körs. Databasen håller trådar `open` även efter att appen avslutats.
- **Antigravity** — `Antigravity.exe` körs **och** konversationen är färsk. Färskhet ensam räcker inte: detta lager håller alla konversationer för alltid, och en stängd redigerare fyllde förr listan med sessioner som ingen tangent kunde nå.
- **CodeNomad** — databasraden är inte arkiverad (`time_archived IS NULL`). Aktiva är bara de som är öppna just nu.

## Leveransadress — kolumnen "Adress"

Sidofältet visar exakt hur varje session kommer att träffas:

| Värde | Metod | Tillförlitlighet |
|---|---|---|
| `cdp:28194` | Klistra in via agentens debugger | Exakt: fältet läses före och efter, fokus stjäls inte |
| `CTRL+3` | Flikbyte i agentfönstret | Bra, om fliknumret är korrekt |
| `blind` | Ingen port, inget fliknummer | Prompten hamnar i den chat som är öppen |

Ingen fönsterrubrik innehåller ett sessionsnamn — `claude.exe` kallas "Claude", Antigravity kallas "Antigravity", Freebuff kallas "Freebuff Desktop". Att adressera via fönster är därför omöjligt, och `blind` betyder exakt vad det säger.

### CDP — den pålitliga vägen

Om en agent startades med `--remote-debugging-port` skickar SAISENT via debuggen och rör varken fokus eller tangentbord. Det betyder:

- texten klistras direkt in i inmatningsfältet, inte "var som helst";
- fältet läses **före** inklistring: om ett halvskrivet meddelande ligger där vägrar utskicket istället för att lägga sig till någon annans mening;
- fältet läses **efter** inklistring: om det inte landade skickar vi inte.

En CDP-vägran faller aldrig tillbaka på blinda tangenttryck. Det precisa transportsättet har just sagt att ögonblicket är fel; att hamra tangenter ovanpå det är precis så man förstör någon annans chatt.

Porten läses från agentens `DevToolsActivePort`, men en fil ensam räcker inte — den överlever en tidigare start. SAISENT ansluter faktiskt till porten före varje sondering.

Aktivera debuggen för en agent (en omstart dödar det den gör — SAISENT gör aldrig detta själv):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Sidväljare (live-DOM, 2026-08-05)

| Agent | Port | Inmatningsfält | Dialoglista |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | ingen | — | — |

Antigravity verifierad: 16 knappar, etiketterna matchar exakt de projektnamn som SAISENT visar (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — dialogvalet efter namn fungerar precist.

CodeNomad är Electron ovanpå OpenCode; datamappen kallas fortfarande `Plasticity`. Sessionslistan i DOM innehåller bara sessioner från det **för närvarande öppna projektet**; en session från ett annat projekt renderas inte, och SAISENT hittar den inte — utskicket vägrar istället för att blint träffa den öppna chatten.

Skriv över valfri profilnyckel i `SAISENT.json`:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Sessioner läses från `~/.local/share/opencode/opencode.db`, tabellen `session`: namn = `title`, projekt = `directory`, arkiverade filtreras bort via `time_archived`, sensorn via `time_updated`. Den enda agenten här vars sessionslista är vanliga kolumner — ingen protobuf, ingen parsning.

Livlighet — `CodeNomad.exe` körs. Inget fliknummer: adresseras efter namn genom debuggen.

## Varför inte efter fönsterrubrik

Varje `claude.exe`-fönster kallas "Claude". Sessionsnamnet syns aldrig i rubriken, så att adressera via fönstret är omöjligt — namnet, projektet och PID:n kommer från disken; fönstret behövs bara för fokus.

## Leveransbekräftelse

Chromium svarar inte på `WM_GETTEXT`, så att läsa "landade det" via Win32 är omöjligt — den gamla read-backen för dessa agenter returnerade alltid "obekräftad". Istället väntar SAISENT på att samma fil som aktivitetssensorn bevakar rör sig. Rörde den sig? Levererad. Rörde den sig inte inom den tilldelade tiden? Prompten markeras som skickad men obekräftad, och det syns i loggen. Det räknas inte som fel: agenten kanske helt enkelt inte har börjat sitt drag än.

Utskicket stannar vid det första verkliga felet (fönster hittades inte, fokus förlorat, urklipp upptaget). Efterföljande prompter stannar i kön — de går inte förlorade och skickas inte blint.

## Export & Import

Knapparna **Exportera** och **Importera** sparar/laddar köer i JSONL-format. Varje rad är självständig med sin sessionsnyckel. Import slår samman utan dataförlust — dubbletter (samma nyckel + text) hoppas över.

## Filer bredvid programmet

| Fil | Innehåll |
|---|---|
| `SAISENT.json` | inställningar: agenter, fliknummer, tidsgränser, fönstergeometri |
| `SAISENT_QUEUES.json` | köer per session, överlever omstart |
| `SAISENT.log` | utskickslogg |

Kön rensas aldrig automatiskt. Om en session försvinner från listan men har osända objekt stannar kön: agenter startas om, och en tyst kastad kö är värre än en extra rad i en fil.

## Dolda inställningar

Redigera `SAISENT.json` medan programmet är stängt:

- `gap_ms` — paus mellan prompter inom en batch (standard 1500);
- `settle_ms` — paus efter flikbyte och efter inklistring (400);
- `confirm_seconds` — hur länge vänta på leveransbekräftelse (10);
- `busy_seconds` — tröskeln för sensorn "busy/idle" (20);
- `freebuff_roots` — rötter där `.freebuff/desktop-v2.db` söks, t.ex. `["V:\\___VAC\\__K\\__CODE"]`; sökdjup begränsat till 3;
- `submit` — tangent för att skicka, standard `ENTER`.

## Begränsningar

- Flikar adresseras via `Ctrl+1..Ctrl+9`. En tionde session är oåtkomlig — `Ctrl+10` finns inte, och SAISENT vägrar istället för att gissa.
- Fliknumret är en gissning baserad på startordning. Gör din första körning med **Torrkörning**, sedan på en oviktig session.
- Antigravity lagrar inte konversationsnamn som text: listan visar arbetsmappens namn, extraherat från metadata.

## Tester

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
