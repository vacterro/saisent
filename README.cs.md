# SAISENT 4.0

Ovládací panel, který vkládá předem připravený text do relací agentů, které právě běží na tomto počítači.

Vložíte text do fronty správné relace — SAISENT aktivuje okno agenta, přepne na kartu této relace, vloží text jednou operací a stiskne Enter.

## Rychlý start

```
START_SAISENT.bat
```

Vyžaduje Python 3.11+ ve Windows.

## Jak používat

1. **Agenti.** Horní řada — zaškrtávací políčka: Claude Code, Freebuff, Antigravity, CodeNomad.
   Zaškrtnete agenta a jeho relace se objeví v levém panelu.
2. **Živé relace.** Vlevo to, co skutečně běží: název relace, číslo karty, senzor aktivity a projekt. Seznam se sám neobnovuje, dokud nezapnete „každých N s" — ve výchozím stavu pouze tlačítkem **Obnovit**.
3. **Karta.** SAISENT hádá číslo karty podle pořadí spouštění relací. Špatně? Zapište číslo ručně do `SAISENT.json`, klíč `tabs` (klíč relace ve tvaru `<agent>:<id>`, např. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = nepřepínat kartu vůbec.
4. **Text.** Píšete (nebo vkládáte) vpravo dole, stisknete **Do fronty** (nebo Ctrl+Enter). **Vše do fronty** vloží stejný text do každé živé relace — nahrazuje staré makro „CTRL+2, text, CTRL+3, text".
5. **Fronta.** Pořadí řádků = pořadí odesílání. Přetáhnete řádek myší nebo posunete tlačítky **Nahoru**/**Dolů**. Každá relace má vlastní frontu. Dvojklik na řádek (nebo tlačítko **Upravit**) vrátí prompt zpět do textového pole; **Uložit úpravu** ho přepíše na místě, **Zrušit** zahodí. Úprava již odeslaného promptu ho vrátí do fronty — text v řádku už neodpovídá tomu, co relace obdržela. **Duplikovat** umístí kopii hned pod něj.
6. **Odesílání.** **ODESLAT TUTO FRONTU** — pouze vybraná relace. **ODESLAT VŠE** — všechny fronty za sebou. **Suchý běh** nic neposílá, jen ukazuje plán v logu. Skutečné odeslání se nejprve ptá na potvrzení a jmenuje relace.

## Vrátit odeslání

Po odeslání se objeví tlačítko **Zpět** na 30 sekund. Vrátí poslední odeslaný prompt do fronty jako `pending` — pokud ho relace ještě nezpracovala (potvrzené doručení).

## Rozvrh a limity

Ve skupině „Odeslat":

- **Odeslat v (HH:MM)** — prázdné znamená „teď". S časem fronta čeká na nejbližší výskyt toho času (dnes, nebo zítra, pokud už uplynul) a ukazuje odpočet ve stavovém řádku.
- **Čekat na reset limitu** — před každým promptem SAISENT čte text samotného agenta. Řekne-li „limit reached", fronta čeká a automaticky pokračuje, jakmile se limit uvolní. Ani jeden prompt proti zavřeným dveřím.
- **Zkontrolovat limity** — přečíst znovu teď.
- Pole vpravo ukazuje živý stav: `limits: all agents free` nebo `claude-code: LIMITED until 09:22 (1h 05m remaining)`, červeně. Odpočet tiká jednou za sekundu z cache; disk se dotýká jen tehdy, když je čtení zastaralé nebo nastane uvedený čas resetu.

Čas resetu se bere ze slov samotného agenta. Pokud ho neuvede, SAISENT napíše „reset time not stated" místo vymýšlení zástupného textu jako „+5 hodin".

### Kdy se limity resetují

Pokud agent nikdy neuvede čas resetu, SAISENT se opře o pravidlo pro agenta:

| Agent | Pravidlo | Význam |
|---|---|---|
| Freebuff | `daily 10:00` | reset každý den v 10:00 |
| CodeNomad | `daily 03:00` | reset každý den v 03:00 |
| Claude Code | `rolling 5h` | 5 hodin po posledním odeslaném promptu |
| Antigravity | jen slova agenta | žádné pravidlo — co uvede, to je |

Pravidlo nikdy nepřebije čas uvedený agentem; agent je autoritou nad vlastním limitem. Jakékoli pravidlo lze přepsat v `SAISENT.json` pod `quota_plans`, např. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Proč se další neodesílají

Odesílání jde přísně postupně a zastaví se na první skutečné chybě. Příčina se dostane do stavového řádku (`stopped: window not found: ...`), do řádku promptu v seznamu i do logu. Zbytek zůstává `pending` — nic se neztratí.

Mezi prompty je pauza `gap_ms` (výchozí 1500 ms) a stav ukazuje `Waiting N.Ns before next`. Pokud prompt odešel, ale relace se nehnula, považuje se za **nepotvrzený** a zůstává ve frontě. „Odesláno" se staví jen na potvrzené doručení.

## Senzor aktivity

Sloupec „Senzor" odpovídá na otázku „dá se teď psát".

- `busy` — relace psala do svého úložiště před méně než 20 sekundami (agent je uprostřed tahu);
- `idle` — ticho déle než 20 sekund, vstupní pole je volné.

Odkud se bere:

| Agent | Zdroj | Senzor |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + přepis | čas posledního zápisu v přepisu |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, tabulka `threads` | pole `turn_state` |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime databáze a jejího `-wal` |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | čas posledního zápisu v přepisu |

Živost je samostatná kontrola, ne „soubor na disku je čerstvý":

- **Claude Code** — PID z `~/.claude/sessions/<pid>.json` žije. Soubor přežije zavření relace; PID ne.
- **Freebuff** — běží `Freebuff.exe`. Databáze drží vlákna `open` i po ukončení aplikace.
- **Antigravity** — běží `Antigravity.exe` **a** konverzace je čerstvá. Samotná čerstvost nestačí: toto úložiště uchovává všechny konverzace navždy a zavřený editor dřív plnil seznam relacemi, ke kterým se nedostala žádná klávesa.
- **CodeNomad** — řádek databáze není archivovaný (`time_archived IS NULL`). Aktivní jsou jen ty právě otevřené.

## Kam přesně jde — sloupec „Adresa"

Boční panel u každé relace říká, čím přesně bude zasažena:

| Hodnota | Metoda | Jak spolehlivě |
|---|---|---|
| `cdp:28194` | vložení přes debugger agenta | přesně: pole se čte před i po, fokus se nekrade |
| `CTRL+3` | přepnutí karty v okně agenta | dobře, pokud je číslo karty správné |
| `blind` | ani port, ani číslo karty | prompt skončí v otevřeném chatu |

Žádný titulek okna neobsahuje název relace — `claude.exe` se jmenuje „Claude", Antigravity se jmenuje „Antigravity", Freebuff se jmenuje „Freebuff Desktop". Adresovat podle okna proto nejde a `blind` znamená přesně to, co je napsáno.

### CDP — spolehlivá cesta

Pokud je agent spuštěn s `--remote-debugging-port`, SAISENT posílá přes debugger a nedotýká se ani fokusu, ani klávesnice. Co to dává:

- text se vkládá přímo do vstupního pole, ne „kam to spadne";
- pole se čte **před** vložením: je-li tam nedopsaná zpráva, odeslání odmítne, místo aby dopisovalo do cizí věty;
- pole se čte **po** vložení: nedoletělo — neposíláme.

Odmítnutí CDP se nikdy nevrací k slepým klávesám. Přesný transport právě řekl, že okamžik není vhodný; mlátit přes to klávesami je přesně ten způsob, jak zaneřádit cizí chat.

Port se bere z `DevToolsActivePort` agenta, ale samotný soubor nestačí: zůstává z předchozího spuštění. SAISENT se před každým pokusem opravdu připojí na port.

Zapnout debugger pro agenta (restart zabije to, co právě dělá — SAISENT to sám nikdy nedělá):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Selektory stránek (sejmuto z živého DOM 2026-08-05)

| Agent | Port | Vstupní pole | Seznam dialogů |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | žádný | — | — |

Antigravity ověřen: 16 tlačítek, popisky přesně odpovídají názvům projektů, které SAISENT ukazuje (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — výběr dialogu podle jména funguje přesně.

CodeNomad je Electron nad OpenCode; datová složka se stále jmenuje `Plasticity`. Seznam relací v DOM obsahuje jen relace **právě otevřeného projektu**; relace z jiného projektu není vyrenderovaná a SAISENT ji nenajde — odeslání odmítne, místo aby slepě zasáhlo otevřený chat.

Přepsat jakýkoli klíč profilu lze v `SAISENT.json`:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Relace se čtou z `~/.local/share/opencode/opencode.db`, tabulka `session`: název = `title`, projekt = `directory`, zavřené se odsijí podle `time_archived`, senzor — podle `time_updated`. Jediný agent tady, u kterého leží seznam relací v obyčejných sloupcích, bez protobufu a bez parsování.

Živost — běží `CodeNomad.exe`. Žádné číslo karty: adresuje se podle jména přes debugger.

## Proč ne podle titulku okna

Všechna okna `claude.exe` se jmenují „Claude". Název relace se do titulku nedostane, takže adresovat podle okna nejde — název, projekt a PID se berou z disku; okno je potřeba jen k fokusu.

## Potvrzení doručení

Chromium neodpovídá na `WM_GETTEXT`, takže přečíst „dopadlo to do pole" přes Win32 nejde — starý read-back u těchto agentů vracel vždy „nepotvrzeno". Místo toho SAISENT čeká, až se pohne stejný soubor, na kterém pracuje senzor. Pohnul se — doručeno. Nepohnul se v určeném čase — prompt je označen jako odeslaný, ale nepotvrzený, a je to vidět v logu. Nepovažuje se to za chybu: agent mohl prostě ještě nezačít tah.

Odesílání se zastaví na první skutečné chybě (okno se nenašlo, fokus ujel, schránka je obsazená). Další prompty zůstávají ve frontě — neztratí se a nejdou naslepo.

## Export a import

Tlačítka **Export** a **Import** ukládají/načítají fronty ve formátu JSONL. Každý řádek je soběstačný s klíčem relace. Import sloučí bez ztráty dat — duplicity (stejný klíč + text) se přeskočí.

## Soubory vedle programu

| Soubor | Co uvnitř |
|---|---|
| `SAISENT.json` | nastavení: agenti, čísla karet, timeouty, geometrie okna |
| `SAISENT_QUEUES.json` | fronty po relacích, přežijí restart |
| `SAISENT.log` | deník odesílání |

Fronta se nikdy nečistí sama. Relace zmizela ze seznamu, ale v její frontě je neodeslané — fronta zůstane: agenti se restartují a tiše snězená fronta je horší než řádek navíc v souboru.

## Nastavení bez rozhraní

Upravuje se v `SAISENT.json` (program musí být při tom zavřený):

- `gap_ms` — pauza mezi prompty v rámci jedné dávky (výchozí 1500);
- `settle_ms` — pauza po přepnutí karty a po vložení (400);
- `confirm_seconds` — jak dlouho čekat na potvrzení doručení (10);
- `busy_seconds` — hranice senzoru „busy/idle" (20);
- `freebuff_roots` — kořeny, kde hledat `.freebuff/desktop-v2.db`, např. `["V:\\___VAC\\__K\\__CODE"]`; hloubka omezena na 3;
- `submit` — čím odesílat, výchozí `ENTER`.

## Omezení

- Karty se adresují přes `Ctrl+1..Ctrl+9`. Desátá relace je nedosažitelná — `Ctrl+10` neexistuje a SAISENT odmítne, místo aby minul.
- Číslo karty je odhad podle pořadí spouštění. První běh dělejte se **Suchým během**, pak na nedůležité relaci.
- Antigravity neuchovává název konverzace textem: v seznamu bude název pracovní složky vytažený z metadat.

## Testy

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
