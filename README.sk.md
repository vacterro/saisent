# SAISENT 4.0

Ovládací panel, ktorý vkladá vopred pripravený text do relácií agentov, ktoré práve bežia na tomto počítači.

Vložíte text do fronty správnej relácie — SAISENT aktivuje okno agenta, prepne na kartu tejto relácie, vloží text jednou operáciou a stlačí Enter.

## Rýchly štart

```
START_SAISENT.bat
```

Vyžaduje Python 3.11+ v systéme Windows.

## Ako používať

1. **Agenti.** Horný riadok — začiarkavacie políčka: Claude Code, Freebuff, Antigravity, CodeNomad.
   Začiarknete agenta a jeho relácie sa objavia v ľavom paneli.
2. **Živé relácie.** Vľavo to, čo skutočne beží: názov relácie, číslo karty, senzor aktivity a projekt. Zoznam sa sám neobnovuje, kým nezapnete „každých N s" — v predvolenom stave iba tlačidlom **Obnoviť**.
3. **Karta.** SAISENT háda číslo karty podľa poradia spúšťania relácií. Zle? Zapíšte číslo ručne do `SAISENT.json`, kľúč `tabs` (kľúč relácie v tvare `<agent>:<id>`, napr. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = neprepínať kartu vôbec.
4. **Text.** Píšete (alebo vkladáte) vpravo dole, stlačíte **Do fronty** (alebo Ctrl+Enter). **Všetko do fronty** vloží rovnaký text do každej živej relácie — nahrádza staré makro „CTRL+2, text, CTRL+3, text".
5. **Fronta.** Poradie riadkov = poradie odosielania. Pretiahnete riadok myšou alebo posuniete tlačidlami **Hore**/**Dole**. Každá relácia má vlastnú frontu. Dvojklik na riadok (alebo tlačidlo **Upraviť**) vráti prompt späť do textového poľa; **Uložiť úpravu** ho prepíše na mieste, **Zrušiť** zahodí. Úprava už odoslaného promptu ho vráti do fronty — text v riadku už nezodpovedá tomu, čo relácia dostala. **Duplikovať** umiestni kópiu hneď pod neho.
6. **Odosielanie.** **ODOSLAŤ TÚTO FRONTU** — iba vybraná relácia. **ODOSLAŤ VŠETKO** — všetky fronty za sebou. **Suchý beh** nič neposiela, len ukazuje plán v logu. Skutočné odoslanie sa najprv pýta na potvrdenie a menuje relácie.

## Vrátiť odoslanie

Po odoslaní sa objaví tlačidlo **Späť** na 30 sekúnd. Vráti posledný odoslaný prompt do fronty ako `pending` — ak ho relácia ešte nespracovala (potvrdené doručenie).

## Rozvrh a limity

V skupine „Odoslať":

- **Odoslať o (HH:MM)** — prázdne znamená „teraz". S časom fronta čaká na najbližší výskyt tohto času (dnes, alebo zajtra, ak už uplynul) a ukazuje odpočet v stavovom riadku.
- **Čakať na reset limitu** — pred každým promptom SAISENT číta text samotného agenta. Ak povie „limit reached", fronta čaká a automaticky pokračuje, len čo sa limit uvoľní. Ani jeden prompt proti zatvoreným dverám.
- **Skontrolovať limity** — prečítať znova teraz.
- Pole vpravo ukazuje živý stav: `limits: all agents free` alebo `claude-code: LIMITED until 09:22 (1h 05m remaining)`, červeno. Odpočet tika raz za sekundu z cache; disk sa dotýka len vtedy, keď je čítanie zastarané alebo nastane uvedený čas resetu.

Čas resetu sa berie zo slov samotného agenta. Ak ho neuvedie, SAISENT napíše „reset time not stated" namiesto vymýšľania zástupného textu ako „+5 hodín".

### Kedy sa limity resetujú

Ak agent nikdy neuvedie čas resetu, SAISENT sa oprie o pravidlo pre agenta:

| Agent | Pravidlo | Význam |
|---|---|---|
| Freebuff | `daily 10:00` | reset každý deň o 10:00 |
| CodeNomad | `daily 03:00` | reset každý deň o 03:00 |
| Claude Code | `rolling 5h` | 5 hodín po poslednom odoslanom prompte |
| Antigravity | len slová agenta | žiadne pravidlo — čo uvedie, to je |

Pravidlo nikdy neprebije čas uvedený agentom; agent je autoritou nad vlastným limitom. Akékoľvek pravidlo možno prepísať v `SAISENT.json` pod `quota_plans`, napr. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Prečo sa ďalšie neodosielajú

Odosielanie ide prísne postupne a zastaví sa na prvej skutočnej chybe. Príčina sa dostane do stavového riadku (`stopped: window not found: ...`), do riadku promptu v zozname aj do logu. Zvyšok zostáva `pending` — nič sa nestratí.

Medzi promptmi je pauza `gap_ms` (predvolená 1500 ms) a stav ukazuje `Waiting N.Ns before next`. Ak prompt odišiel, ale relácia sa nepohla, považuje sa za **nepotvrdený** a zostáva vo fronte. „Odoslané" sa stavia len na potvrdené doručenie.

## Senzor aktivity

Stĺpec „Senzor" odpovedá na otázku „dá sa teraz písať".

- `busy` — relácia písala do svojho úložiska pred menej ako 20 sekundami (agent je uprostred ťahu);
- `idle` — ticho dlhšie ako 20 sekúnd, vstupné pole je voľné.

Odkiaľ sa berie:

| Agent | Zdroj | Senzor |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + prepis | čas posledného zápisu v prepise |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, tabuľka `threads` | pole `turn_state` |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime databázy a jej `-wal` |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | čas posledného zápisu v prepise |

Živosť je samostatná kontrola, nie „súbor na disku je čerstvý":

- **Claude Code** — PID z `~/.claude/sessions/<pid>.json` žije. Súbor prežije zatvorenie relácie; PID nie.
- **Freebuff** — beží `Freebuff.exe`. Databáza drží vlákna `open` aj po ukončení aplikácie.
- **Antigravity** — beží `Antigravity.exe` **a** konverzácia je čerstvá. Samotná čerstvosť nestačí: toto úložisko uchováva všetky konverzácie navždy a zatvorený editor kedysi plnil zoznam reláciami, ku ktorým sa nedostal žiadny kláves.
- **CodeNomad** — riadok databázy nie je archivovaný (`time_archived IS NULL`). Aktívne sú len tie práve otvorené.

## Kam presne ide — stĺpec „Adresa"

Bočný panel pri každej relácii hovorí, čím presne bude zasiahnutá:

| Hodnota | Metóda | Ako spoľahlivo |
|---|---|---|
| `cdp:28194` | vloženie cez debugger agenta | presne: pole sa číta pred aj po, fokus sa nekradne |
| `CTRL+3` | prepnutie karty v okne agenta | dobre, ak je číslo karty správne |
| `blind` | ani port, ani číslo karty | prompt skončí v otvorenom chate |

Žiadny názov okna neobsahuje názov relácie — `claude.exe` sa volá „Claude", Antigravity sa volá „Antigravity", Freebuff sa volá „Freebuff Desktop". Adresovať podľa okna preto nejde a `blind` znamená presne to, čo je napísané.

### CDP — spoľahlivá cesta

Ak je agent spustený s `--remote-debugging-port`, SAISENT posiela cez debugger a nedotýka sa ani fokusu, ani klávesnice. Čo to dáva:

- text sa vkladá priamo do vstupného poľa, nie „kam to spadne";
- pole sa číta **pred** vložením: ak je tam nedopísaná správa, odoslanie odmietne, namiesto toho aby dopisovalo do cudzej vety;
- pole sa číta **po** vložení: nedolietlo — neposielame.

Odmietnutie CDP sa nikdy nevracia k slepým klávesám. Presný transport práve povedal, že okamih nie je vhodný; mlátiť cez to klávesami je presne ten spôsob, ako zaneřadiť cudzí chat.

Port sa berie z `DevToolsActivePort` agenta, ale samotný súbor nestačí: zostáva z predchádzajúceho spustenia. SAISENT sa pred každým pokusom naozaj pripojí na port.

Zapnúť debugger pre agenta (reštart zabije to, čo práve robí — SAISENT to sám nikdy nerobí):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Selektory stránok (snímané zo živého DOM 2026-08-05)

| Agent | Port | Vstupné pole | Zoznam dialógov |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | žiadny | — | — |

Antigravity overený: 16 tlačidiel, popisky presne zodpovedajú názvom projektov, ktoré SAISENT ukazuje (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — výber dialógu podľa mena funguje presne.

CodeNomad je Electron nad OpenCode; dátový priečinok sa stále volá `Plasticity`. Zoznam relácií v DOM obsahuje len relácie **práve otvoreného projektu**; relácia z iného projektu nie je vyrenderovaná a SAISENT ju nenájde — odoslanie odmietne, namiesto toho aby slepo zasiahlo otvorený chat.

Prepísať akýkoľvek kľúč profilu možno v `SAISENT.json`:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Relácie sa čítajú z `~/.local/share/opencode/opencode.db`, tabuľka `session`: názov = `title`, projekt = `directory`, zatvorené sa odsievajú podľa `time_archived`, senzor — podľa `time_updated`. Jediný agent tu, pri ktorom leží zoznam relácií v obyčajných stĺpcoch, bez protobufu a bez parsovania.

Živosť — beží `CodeNomad.exe`. Žiadne číslo karty: adresuje sa podľa mena cez debugger.

## Prečo nie podľa názvu okna

Všetky okná `claude.exe` sa volajú „Claude". Názov relácie sa do názvu nedostane, takže adresovať podľa okna nejde — názov, projekt a PID sa berú z disku; okno je potrebné len na fokus.

## Potvrdenie doručenia

Chromium neodpovedá na `WM_GETTEXT`, takže prečítať „dopadlo to do poľa" cez Win32 nejde — starý read-back u týchto agentov vracal vždy „nepotvrdené". Namiesto toho SAISENT čaká, kým sa pohne rovnaký súbor, na ktorom pracuje senzor. Pohol sa — doručené. Nepohol sa v určenom čase — prompt je označený ako odoslaný, ale nepotvrdený, a je to vidieť v logu. Nepovažuje sa to za chybu: agent mohol jednoducho ešte nezačať ťah.

Odosielanie sa zastaví na prvej skutočnej chybe (okno sa nenašlo, fokus ušiel, schránka je obsadená). Ďalšie prompty zostávajú vo fronte — nestratia sa a nejdú naslepo.

## Export a import

Tlačidlá **Export** a **Import** ukladajú/načítavajú fronty vo formáte JSONL. Každý riadok je sebestačný s kľúčom relácie. Import zlúči bez straty dát — duplicity (rovnaký kľúč + text) sa preskočia.

## Súbory vedľa programu

| Súbor | Čo je vnútri |
|---|---|
| `SAISENT.json` | nastavenia: agenti, čísla kariet, timeouty, geometria okna |
| `SAISENT_QUEUES.json` | fronty po reláciách, prežijú reštart |
| `SAISENT.log` | denník odosielania |

Fronta sa nikdy nečistí sama. Relácia zmizla zo zoznamu, ale v jej fronte je neodoslané — fronta zostane: agenti sa reštartujú a ticho zjedená fronta je horšia ako riadok navyše v súbore.

## Nastavenia bez rozhrania

Upravuje sa v `SAISENT.json` (program musí byť pritom zatvorený):

- `gap_ms` — pauza medzi promptmi v rámci jednej dávky (predvolená 1500);
- `settle_ms` — pauza po prepnutí karty a po vložení (400);
- `confirm_seconds` — ako dlho čakať na potvrdenie doručenia (10);
- `busy_seconds` — hranica senzora „busy/idle" (20);
- `freebuff_roots` — korene, kde hľadať `.freebuff/desktop-v2.db`, napr. `["V:\\___VAC\\__K\\__CODE"]`; hĺbka obmedzená na 3;
- `submit` — čím odosielať, predvolené `ENTER`.

## Obmedzenia

- Karty sa adresujú cez `Ctrl+1..Ctrl+9`. Desiata relácia je nedosiahnuteľná — `Ctrl+10` neexistuje a SAISENT odmietne, namiesto toho aby minul.
- Číslo karty je odhad podľa poradia spúšťania. Prvý beh robte so **Suchým behom**, potom na nedôležitej relácii.
- Antigravity neuchováva názov konverzácie textom: v zozname bude názov pracovného priečinka vytiahnutý z metadát.

## Testy

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
