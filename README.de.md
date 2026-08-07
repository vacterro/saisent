# SAISENT 4.0

Ein Bedienfeld, das vorbereiteten Text in die Agenten-Sitzungen einfügt, die gerade auf diesem Rechner laufen.

Text in die Warteschlange der richtigen Sitzung stellen — SAISENT aktiviert das Agenten-Fenster,
wechselt zum Tab dieser Sitzung, fügt den Text in einem Vorgang ein und drückt Enter.

## Schnellstart

```
START_SAISENT.bat
```

Erfordert Python 3.11+ unter Windows.

## So benutzt man es

1. **Agenten.** Obere Reihe — Kontrollkästchen: Claude Code, Freebuff, Antigravity, CodeNomad.
   Ein Agent angehakt, erscheinen seine Sitzungen im linken Bereich.
2. **Live-Sitzungen.** Links steht, was wirklich läuft: Sitzungsname, Tab-Nummer, Aktivitätssensor und Projekt.
   Die Liste aktualisiert sich nicht von selbst, außer „alle N s" ist aktiviert — standardmäßig nur über die
   Schaltfläche **Aktualisieren**.
3. **Tab.** SAISENT rät die Tab-Nummer aus der Startreihenfolge der Sitzungen. Falsch geraten? Nummer manuell
   in `SAISENT.json` unter `tabs` eintragen (Sitzungsschlüssel in der Form `<agent>:<id>`, z. B.
   `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = Tab gar nicht wechseln.
4. **Text.** Unten rechts schreiben (oder einfügen), **Warteschlange** (oder Ctrl+Enter) drücken.
   **Alle in Warteschlange** legt denselben Text in jede Live-Sitzung — ersetzt das alte Makro
   „CTRL+2, Text, CTRL+3, Text".
5. **Warteschlange.** Zeilenreihenfolge = Sendereihenfolge. Zeile mit der Maus ziehen oder mit **Hoch**/**Runter**
   verschieben. Jede Sitzung hat ihre eigene Warteschlange. Doppelklick auf eine Zeile (oder **Bearbeiten**)
   holt den Prompt zurück ins Textfeld; **Bearbeitung speichern** überschreibt ihn an Ort und Stelle,
   **Abbrechen** verwirft. Das Bearbeiten eines bereits gesendeten Prompts stellt ihn wieder in die
   Warteschlange — der Text in der Zeile stimmt nicht mehr mit dem überein, was die Sitzung empfing.
   **Duplizieren** legt eine Kopie direkt darunter.
6. **Senden.** **DIESE WARTESCHLANGE SENDEN** — nur die ausgewählte Sitzung. **ALLE SENDEN** — alle
   Warteschlangen der Reihe nach. **Probelauf** sendet nichts, sondern zeigt den Plan im Protokoll.
   Echte Sendungen fragen zuerst nach Bestätigung und nennen die Sitzungen.

## Senden rückgängig machen

Nach dem Senden erscheint **Rückgängig** für 30 Sekunden. Es holt den letzten gesendeten Prompt als
`pending` zurück in die Warteschlange — außer die Sitzung hat ihn bereits verarbeitet (bestätigte Zustellung).

## Zeitplan & Limits

In der Gruppe „Senden":

- **Senden um (HH:MM)** — leer bedeutet „jetzt". Mit einer Uhrzeit wartet die Warteschlange auf das nächste
  Eintreten dieser Zeit (heute, oder morgen wenn vorbei) und zeigt einen Countdown in der Statusleiste.
- **Auf Limit-Reset warten** — vor jedem Prompt liest SAISENT den eigenen Text des Agenten. Sagt er
  „limit reached", wartet die Warteschlange und setzt automatisch fort, sobald das Limit frei ist.
  Kein Prompt trifft eine verschlossene Tür.
- **Limits prüfen** — jetzt neu scannen.
- Das Statusfeld rechts zeigt den Live-Zustand: `limits: all agents free` oder
  `claude-code: LIMITED until 09:22 (1h 05m remaining)`, rot. Der Countdown tickt einmal pro Sekunde aus dem
  Cache; die Platte wird nur berührt, wenn die Messung veraltet ist oder die genannte Reset-Zeit erreicht ist.

Die Reset-Zeit stammt aus den eigenen Worten des Agenten. Nennt er keine, schreibt SAISENT
„reset time not stated" statt einen Platzhalter wie „+5 Stunden" zu erfinden.

### Wann sich Limits zurücksetzen

Nennt der Agent nie eine Reset-Zeit, greift SAISENT auf eine Regel pro Agent zurück:

| Agent | Regel | Bedeutung |
|---|---|---|
| Freebuff | `daily 10:00` | setzt sich jeden Tag um 10:00 zurück |
| CodeNomad | `daily 03:00` | setzt sich jeden Tag um 03:00 zurück |
| Claude Code | `rolling 5h` | 5 Stunden nach dem letzten gesendeten Prompt |
| Antigravity | nur die Worte des Agenten | keine Regel — was er angibt, oder nichts |

Eine Regel überschreibt nie eine vom Agenten genannte Zeit; der Agent ist die Autorität über sein eigenes
Kontingent. Jede Regel kann in `SAISENT.json` unter `quota_plans` überschrieben werden, z. B.
`{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Warum die nächsten nicht gesendet werden

Das Senden ist streng sequenziell und stoppt beim ersten echten Fehler. Der Grund erscheint in der Statusleiste
(`stopped: window not found: ...`), in der Prompt-Zeile der Liste und im Protokoll. Der Rest bleibt `pending` —
nichts ist verloren.

Zwischen Prompts liegt eine `gap_ms`-Pause (Standard 1500 ms), der Status zeigt `Waiting N.Ns before next`.
Wurde ein Prompt gesendet, hat sich die Sitzung aber nicht bewegt, gilt er als **unbestätigt** und bleibt in der
Warteschlange. „Gesendet" wird nur auf bestätigte Zustellungen angewendet.

## Aktivitätssensor

Die Spalte „Sensor" beantwortet „kann ich gerade tippen".

- `busy` — die Sitzung hat vor weniger als 20 Sekunden in ihren Store geschrieben (der Agent ist mitten im Zug);
- `idle` — Stille länger als 20 Sekunden, das Eingabefeld ist frei.

Woher es kommt:

| Agent | Quelle | Sensor |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + Transkript | letzte Schreibzeit im Transkript |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, Tabelle `threads` | Feld `turn_state` |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime der DB und ihrer `-wal` |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | letzte Schreibzeit im Transkript |

Lebendigkeit ist eine eigene Prüfung, nicht „die Datei auf der Platte ist frisch":

- **Claude Code** — die PID aus `~/.claude/sessions/<pid>.json` lebt. Die Datei überlebt das Schließen der
  Sitzung; die PID nicht.
- **Freebuff** — `Freebuff.exe` läuft. Die DB hält Threads auch nach dem Beenden der App `open`.
- **Antigravity** — `Antigravity.exe` läuft **und** das Gespräch ist frisch. Frische allein reicht nicht:
  dieser Store hält alle Gespräche für immer, und ein geschlossener Editor füllte früher die Liste mit
  Sitzungen, die keine Taste erreichen konnte.
- **CodeNomad** — die DB-Zeile ist nicht archiviert (`time_archived IS NULL`). Aktiv sind nur die gerade
  offenen Sitzungen.

## Zustelladresse — Spalte „Adresse"

Die Seitenleiste zeigt exakt, wie jede Sitzung angesprochen wird:

| Wert | Methode | Zuverlässigkeit |
|---|---|---|
| `cdp:28194` | Einfügen über den Debugger des Agenten | Exakt: Feld vor und nach gelesen, Fokus wird nicht gestohlen |
| `CTRL+3` | Tab-Wechsel im Agenten-Fenster | Gut, wenn die Tab-Nummer stimmt |
| `blind` | Kein Port, keine Tab-Nummer | Der Prompt landet im jeweils offenen Chat |

Kein Fenstertitel enthält einen Sitzungsnamen — `claude.exe` heißt „Claude", Antigravity heißt „Antigravity",
Freebuff heißt „Freebuff Desktop". Adressierung über das Fenster ist daher unmöglich, und `blind` bedeutet
genau das, was es sagt.

### CDP — der zuverlässige Weg

Wurde ein Agent mit `--remote-debugging-port` gestartet, sendet SAISENT über den Debugger und berührt weder
Fokus noch Tastatur. Das bedeutet:

- der Text wird direkt in das Eingabefeld eingefügt, nicht „irgendwohin";
- das Feld wird **vor** dem Einfügen gelesen: liegt eine halb geschriebene Nachricht darin, verweigert das
  Senden, statt an den Satz eines anderen anzuhängen;
- das Feld wird **nach** dem Einfügen gelesen: ist es nicht gelandet, senden wir nicht.

Eine CDP-Ablehnung fällt nie auf blinde Tastenanschläge zurück. Der präzise Transport hat gerade gesagt, dass
der Moment falsch ist; darüber Tasten zu hämmern ist genau die Art, wie man den Chat eines anderen ruiniert.

Der Port wird aus `DevToolsActivePort` des Agenten gelesen, aber eine Datei allein reicht nicht — sie überlebt
einen früheren Start. SAISENT verbindet sich vor jeder Sondierung tatsächlich mit dem Port.

Debugger für einen Agenten aktivieren (ein Neustart tötet, was er gerade tut — SAISENT tut das selbst nie):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Seiten-Selektoren (Live-DOM, 2026-08-05)

| Agent | Port | Eingabefeld | Dialogliste |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | keine | — | — |

Antigravity verifiziert: 16 Schaltflächen, Beschriftungen stimmen exakt mit den Projektnamen überein, die
SAISENT zeigt (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — die Auswahl des Dialogs nach Name funktioniert präzise.

CodeNomad ist Electron auf OpenCode; der Datenordner heißt immer noch `Plasticity`. Die Sitzungsliste im DOM
enthält nur Sitzungen des **aktuell offenen Projekts**; eine Sitzung aus einem anderen Projekt wird nicht
gerendert, und SAISENT findet sie nicht — das Senden verweigert, statt blind den offenen Chat zu treffen.

Einen Profilschlüssel in `SAISENT.json` überschreiben:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Sitzungen werden aus `~/.local/share/opencode/opencode.db`, Tabelle `session` gelesen: Name = `title`,
Projekt = `directory`, archivierte über `time_archived` herausgefiltert, Sensor über `time_updated`. Der einzige
Agent hier, dessen Sitzungsliste einfache Spalten sind — kein Protobuf, kein Parsing.

Lebendigkeit — `CodeNomad.exe` läuft. Keine Tab-Nummer: über den Debugger nach Name angesprochen.

## Warum nicht nach Fenstertitel

Jedes `claude.exe`-Fenster heißt „Claude". Der Sitzungsname erscheint nie im Titel, daher ist die Adressierung
über das Fenster unmöglich — Name, Projekt und PID kommen von der Platte; das Fenster wird nur für den Fokus
gebraucht.

## Zustellbestätigung

Chromium beantwortet `WM_GETTEXT` nicht, daher ist das Lesen von „ist es gelandet" über Win32 unmöglich — der
alte Read-back für diese Agenten gab immer „unbestätigt" zurück. Stattdessen wartet SAISENT, bis sich dieselbe
Datei bewegt, die auch der Aktivitätssensor beobachtet. Bewegt? Zugestellt. Hat sie sich innerhalb der
vorgegebenen Zeit nicht bewegt? Der Prompt wird als gesendet, aber unbestätigt markiert, und das ist im
Protokoll sichtbar. Das gilt nicht als Fehler: Der Agent hat seinen Zug vielleicht nur noch nicht begonnen.

Das Senden stoppt beim ersten echten Fehler (Fenster nicht gefunden, Fokus verloren, Zwischenablage belegt).
Nachfolgende Prompts bleiben in der Warteschlange — sie gehen nicht verloren und werden nicht blind gesendet.

## Export & Import

Die Schaltflächen **Export** und **Import** speichern/laden Warteschlangen im JSONL-Format. Jede Zeile ist
selbstständig mit ihrem Sitzungsschlüssel. Der Import führt ohne Datenverlust zusammen — Duplikate (gleicher
Schlüssel + Text) werden übersprungen.

## Dateien neben dem Programm

| Datei | Inhalt |
|---|---|
| `SAISENT.json` | Einstellungen: Agenten, Tab-Nummern, Zeitlimits, Fenstergeometrie |
| `SAISENT_QUEUES.json` | Warteschlangen pro Sitzung, überleben Neustart |
| `SAISENT.log` | Verlauf der Sendungen |

Die Warteschlange wird nie automatisch bereinigt. Verschwindet eine Sitzung aus der Liste, hat aber
ungesendete Elemente, bleibt die Warteschlange: Agenten werden neu gestartet, und eine still verworfenen
Warteschlange ist schlimmer als eine überzählige Zeile in einer Datei.

## Versteckte Einstellungen

`SAISENT.json` bei geschlossenem Programm bearbeiten:

- `gap_ms` — Pause zwischen Prompts innerhalb eines Stapels (Standard 1500);
- `settle_ms` — Pause nach Tab-Wechsel und nach dem Einfügen (400);
- `confirm_seconds` — wie lange auf die Zustellbestätigung warten (10);
- `busy_seconds` — Schwelle des Sensors „busy/idle" (20);
- `freebuff_roots` — Wurzeln, in denen nach `.freebuff/desktop-v2.db` gesucht wird, z. B.
  `["V:\\___VAC\\__K\\__CODE"]`; Suchtiefe auf 3 begrenzt;
- `submit` — Taste zum Senden, Standard `ENTER`.

## Einschränkungen

- Tabs werden über `Ctrl+1..Ctrl+9` angesprochen. Eine zehnte Sitzung ist unerreichbar — `Ctrl+10` existiert
  nicht, und SAISENT verweigert, statt zu raten.
- Die Tab-Nummer ist eine Schätzung nach Startreihenfolge. Den ersten Lauf mit **Probelauf** machen, dann auf
  einer unwichtigen Sitzung.
- Antigravity speichert Gesprächsnamen nicht als Text: Die Liste zeigt den aus Metadaten extrahierten Namen
  des Arbeitsordners.

## Tests

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
