# SAISENT 4.0

Olyan vezérlőpult, amely előre elkészített szöveget illeszt be azokba az ügynök-munkamenetekbe, amelyek éppen ezen a gépen futnak.

Tedd a szöveget a megfelelő munkamenet sorába — a SAISENT aktiválja az ügynök ablakát, átvált annak a munkamenetnek a fülére, egy művelettel beilleszti a szöveget, és megnyomja az Entert.

## Gyors indítás

```
START_SAISENT.bat
```

Windows rendszeren Python 3.11+ szükséges.

## Hogyan használd

1. **Ügynökök.** Felső sor — jelölőnégyzetek: Claude Code, Freebuff, Antigravity, CodeNomad.
   Pipálj be egy ügynököt, és a munkamenetei megjelennek a bal oldali panelen.
2. **Élő munkamenetek.** Bal oldalon az, ami tényleg fut: munkamenet neve, fül száma, aktivitásérzékelő és projekt. A lista nem frissül magától, hacsak nem kapcsolod be a „minden N másodperc"-et — alapértelmezésben csak a **Frissítés** gombbal.
3. **Fül.** A SAISENT a munkamenetek indítási sorrendjéből találja ki a fül számát. Rossz? Írd be a számot kézzel a `SAISENT.json` `tabs` kulcsába (munkamenet-kulcs `<agent>:<id>` formában, pl. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = egyáltalán ne válts füle.
4. **Szöveg.** Írj (vagy illessz be) jobb alul, nyomd meg a **Sorba** (vagy Ctrl+Enter) gombot. **Mindent sorba** ugyanazt a szöveget teszi minden élő munkamenetbe — a régi „CTRL+2, szöveg, CTRL+3, szöveg" makró helyett.
5. **Sor.** A sorok rendje = a küldés rendje. Húzd el egy sort az egérrel, vagy mozgasd a **Fel**/**Le** gombokkal. Minden munkamenetnek saját sora van. Kattints duplán egy sorra (vagy a **Szerkesztés** gombra), és a prompt visszakerül a szövegmezőbe; a **Szerkesztés mentése** helyben átírja, a **Mégse** eldobja. Egy már elküldött prompt szerkesztése visszateszi a sorba — a sorban lévő szöveg már nem egyezik azzal, amit a munkamenet kapott. A **Duplikálás** közvetlenül alá tesz egy másolatot.
6. **Küldés.** **E SOR KÜLDÉSE** — csak a kiválasztott munkamenet. **MIND KÜLDÉSE** — az összes sor egymás után. **Száraz futtatás** semmit nem küld, csak a tervet mutatja a naplóban. A valódi küldés először megerősítést kér, és megnevezi a munkameneteket.

## Küldés visszavonása

A küldés után **Visszavonás** gomb jelenik meg 30 másodpercre. Visszateszi a legutóbb elküldött promptot a sorba `pending` állapotban — hacsak a munkamenet már fel nem dolgozta (megerősített kézbesítés).

## Ütemezés és korlátok

A „Küldés" csoportban:

- **Küldés ekkor (HH:MM)** — üres jelentése „most". Időponttal a sor vár annak az időnek a következő előfordulására (ma, vagy holnap, ha már elmúlt), és visszaszámlálást mutat az állapotsorban.
- **Korlát-visszaállításra várás** — minden prompt előtt a SAISENT az ügynök saját szövegét olvassa. Ha azt mondja, „limit reached", a sor vár, és automatikusan folytatja, amikor a korlát felszabadul. Egyetlen prompt sem csapódik zárt ajtónak.
- **Korlátok ellenőrzése** — olvasd újra most.
- A jobb oldali állapotmező az élő állapotot mutatja: `limits: all agents free` vagy `claude-code: LIMITED until 09:22 (1h 05m remaining)`, pirossal. A visszaszámlálás másodpercenként egyszer ketyeg a gyorsítótárból; a lemezhez csak akkor nyúlnak, ha az olvasás elavult, vagy beáll a megnevezett visszaállítási idő.

A visszaállítási idő az ügynök saját szavaiból származik. Ha nem mondja meg, a SAISENT „reset time not stated" szöveget ír, ahelyett hogy kitalálna egy „+5 óra" jellegű helyettesítőt.

### Mikor állnak vissza a korlátok

Ha az ügynök soha nem ad meg visszaállítási időt, a SAISENT ügynökenkénti szabályra támaszkodik:

| Ügynök | Szabály | Jelentés |
|---|---|---|
| Freebuff | `daily 10:00` | minden nap 10:00-kor áll vissza |
| CodeNomad | `daily 03:00` | minden nap 03:00-kor áll vissza |
| Claude Code | `rolling 5h` | az utolsó elküldött prompt után 5 órával |
| Antigravity | csak az ügynök szavai | nincs szabály — amit megad, az van |

A szabály soha nem írja felül az ügynök által megadott időt; az ügynök a saját keretének tekintélye. Bármelyik szabály felülírható a `SAISENT.json` `quota_plans` kulcsában, pl. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Miért nem mennek a következők

A küldés szigorúan sorrendben halad, és az első valódi hibánál megáll. Az ok bekerül az állapotsorba (`stopped: window not found: ...`), a lista prompt-sorába és a naplóba. A többi `pending` marad — semmi nem vész el.

A promptok között `gap_ms` szünet van (alapértelmezés 1500 ms), és az állapot `Waiting N.Ns before next` szöveget mutat. Ha egy prompt elment, de a munkamenet nem mozdult, **megerősítetlenként** jelölődik, és a sorban marad. „Elküldve" csak a megerősített kézbesítésekre kerül.

## Aktivitásérzékelő

Az „Érzékelő" oszlop arra a kérdésre válaszol, hogy „írhatok most".

- `busy` — a munkamenet kevesebb mint 20 másodperce írt a tárolójába (az ügynök kör közepén van);
- `idle` — több mint 20 másodperces csend, a beviteli mező szabad.

Honnan származik:

| Ügynök | Forrás | Érzékelő |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + átirat | utolsó írási idő az átiratban |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, `threads` tábla | `turn_state` mező |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | az adatbázis és `-wal`-ja mtime-ja |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | utolsó írási idő az átiratban |

Az élőség külön ellenőrzés, nem „a lemezen lévő fájl friss":

- **Claude Code** — a `~/.claude/sessions/<pid>.json` PID-je él. A fájl túléli a munkamenet bezárását; a PID nem.
- **Freebuff** — fut a `Freebuff.exe`. Az adatbázis az alkalmazásból való kilépés után is `open`-ként tartja a szálakat.
- **Antigravity** — fut a `Antigravity.exe` **és** a beszélgetés friss. A frissesség önmagában nem elég: ez a tároló örökre megőriz minden beszélgetést, és egy bezárt szerkesztő régen olyan munkamenetekkel töltötte meg a listát, amelyekhez egyetlen billentyű sem fért hozzá.
- **CodeNomad** — az adatbázis-sor nincs archiválva (`time_archived IS NULL`). Csak a jelenleg nyitottak aktívak.

## Kézbesítési cím — „Cím" oszlop

Az oldalsáv pontosan megmutatja, hogyan lesz megcélozva minden munkamenet:

| Érték | Módszer | Megbízhatóság |
|---|---|---|
| `cdp:28194` | beillesztés az ügynök hibakeresőjén keresztül | pontos: a mező előtte és utána olvasva, a fókusz nem lopható el |
| `CTRL+3` | fülváltás az ügynök ablakában | jó, ha a fül száma helyes |
| `blind` | se port, se fül szám | a prompt abba a chatbe esik, amelyik nyitva van |

Egyetlen ablak címe sem tartalmaz munkamenet-nevet — a `claude.exe` neve „Claude", az Antigravity neve „Antigravity", a Freebuff neve „Freebuff Desktop". Ezért az ablak szerinti címzés lehetetlen, és a `blind` pontosan azt jelenti, amit mond.

### CDP — a megbízható út

Ha egy ügynököt `--remote-debugging-port`-tal indítottak, a SAISENT a hibakeresőn keresztül küld, és sem a fókuszt, sem a billentyűzetet nem érinti. Ez azt jelenti:

- a szöveg közvetlenül a beviteli mezőbe kerül, nem „akárhová";
- a mező **beillesztés előtt** olvasva: ha félkész üzenet van benne, a küldés visszautasítja, ahelyett hogy más mondatához toldana;
- a mező **beillesztés után** olvasva: ha nem ért oda, nem küldünk.

A CDP visszautasítása soha nem esik vissza vak billentyűleütésekre. A pontos átviteli csatorna épp most mondta, hogy a pillanat nem megfelelő; fölé billentyűzni pontosan az a mód, ahogyan más chatjét tönkreteszed.

A portot az ügynök `DevToolsActivePort` fájljából olvassák, de önmagában a fájl nem elég: egy korábbi indításból marad ott. A SAISENT minden próba előtt ténylegesen csatlakozik a porthoz.

Kapcsold be a hibakeresőt egy ügynökhöz (az újraindítás megöli, amit éppen csinál — a SAISENT ezt soha nem teszi meg magától):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Oldalválasztók (élő DOM, 2026-08-05)

| Ügynök | Port | Beviteli mező | Párbeszédlista |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | nincs | — | — |

Antigravity ellenőrizve: 16 gomb, a címkék pontosan egyeznek a SAISENT által mutatott projektnevekkel (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — a párbeszéd kiválasztása név alapján pontosan működik.

A CodeNomad az OpenCode-ra épülő Electron; az adatmappa még mindig `Plasticity` néven fut. A DOM munkamenetlistája csak a **jelenleg nyitott projekt** munkameneteit tartalmazza; egy másik projektből származó munkamenet nincs renderelve, és a SAISENT nem találja meg — a küldés visszautasítja, ahelyett hogy vakon beleütne a nyitott chatbe.

Bármely profilkulcs felülírható a `SAISENT.json`-ben:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

A munkamenetek a `~/.local/share/opencode/opencode.db` `session` táblájából olvasódnak: név = `title`, projekt = `directory`, a bezártak `time_archived` szerint kiszűrve, az érzékelő `time_updated` szerint. Az egyetlen ügynök itt, akinél a munkamenetlista egyszerű oszlopokban van — protobuf és feldolgozás nélkül.

Élőség — fut a `CodeNomad.exe`. Nincs fül szám: név szerint címezhető a hibakeresőn keresztül.

## Miért nem az ablak címe szerint

Minden `claude.exe` ablak neve „Claude". A munkamenet neve soha nem kerül a címbe, ezért az ablak szerinti címzés lehetetlen — a név, a projekt és a PID a lemezről jön; az ablak csak a fókuszhoz kell.

## Kézbesítés megerősítése

A Chromium nem válaszol a `WM_GETTEXT`-re, ezért „odaért-e" olvasása Win32-n keresztül lehetetlen — a régi read-back ezeknél az ügynököknél mindig „megerősítetlen" volt. Ehelyett a SAISENT megvárja, hogy az a fájl mozogjon, amelyet az aktivitásérzékelő figyel. Mozgott? Kézbesítve. Nem mozgott a megadott időn belül? A prompt elküldöttként, de megerősítetlenként jelölődik, és ez látszik a naplóban. Ez nem számít hibának: az ügynök lehet, hogy még nem kezdte meg a körét.

A küldés az első valódi hibánál megáll (ablak nem található, fókusz elúszott, vágólap foglalt). A következő promptok a sorban maradnak — nem vésznek el, és nem mennek vakon.

## Export és import

Az **Export** és **Import** gombok JSONL formátumban mentik/töltik be a sorokat. Minden sor önálló a munkamenet-kulcsával. Az import adatvesztés nélkül egyesít — a duplikátumok (azonos kulcs + szöveg) kimaradnak.

## Fájlok a program mellett

| Fájl | Tartalom |
|---|---|
| `SAISENT.json` | beállítások: ügynökök, fül számok, időtúllépések, ablakgeometria |
| `SAISENT_QUEUES.json` | munkamenetenkénti sorok, túlélik az újraindítást |
| `SAISENT.log` | küldési előzmény napló |

A sort soha nem takarítják automatikusan. Ha egy munkamenet eltűnik a listáról, de a sorában van elküldetlen, a sor megmarad: az ügynököket újraindítják, és egy csendben megevett sor rosszabb, mint egy plusz sor egy fájlban.

## Rejtett beállítások

A `SAISENT.json`-t zárt program mellett szerkeszd:

- `gap_ms` — szünet a promptok között egy adagban (alapértelmezés 1500);
- `settle_ms` — szünet fülváltás és beillesztés után (400);
- `confirm_seconds` — mennyit vár a kézbesítés megerősítésére (10);
- `busy_seconds` — az érzékelő „busy/idle" határa (20);
- `freebuff_roots` — gyökerek, ahol a `.freebuff/desktop-v2.db`-t keresik, pl. `["V:\\___VAC\\__K\\__CODE"]`; mélység 3-ra korlátozva;
- `submit` — mivel küld, alapértelmezés `ENTER`.

## Korlátok

- A fülek `Ctrl+1..Ctrl+9`-cel címezhetők. A tizedik munkamenet elérhetetlen — a `Ctrl+10` nem létezik, és a SAISENT visszautasítja, nem melléfog.
- A fül száma az indítási sorrend alapján tipp. Az első futtatást **Száraz futtatás**-ként, majd egy nem fontos munkameneten végezd.
- Az Antigravity nem tárolja a beszélgetés nevét szövegként: a listában a metaadatokból kihúzott munkamappa neve lesz.

## Tesztek

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
