# SAISENT 4.0

Juhtpult, mis kleebib ettevalmistatud teksti sellesse AI-agendi sessiooni,
mis parasjagu sellel masinal töötab.

Pane tekst õige sessiooni järjekorda — SAISENT aktiveerib agendi akna,
lülitab selle sessiooni tabile, kleebib teksti ühe operatsiooniga ja vajutab
Enterit.

## Kiirkäivitus

```
START_SAISENT.bat
```

Vajalik Python 3.11+ Windowsil.

## Kasutamine

1. **Agendid.** Ülemine rida — linnukesed: Claude Code, Freebuff, Antigravity,
   CodeNomad. Linnukesega agent näitab oma sessioone vasakul paneelil.
2. **Elus sessioonid.** Vasakul on see, mis päriselt töötab: sessiooni nimi,
   tabi number, andur ja projekt. Nimekiri ei uuene ise, kui pole sisse
   lülitatud "iga N s" — vaikimisi ainult nupust **Uuenda**.
3. **Tab.** SAISENT arvab tabi numbri sessioonide käivitusjärjekorrast.
   Vale? Kirjuta number käsitsi `SAISENT.json` võtme `tabs` alla (võti
   on kujul `<agent>:<id>`, nt `{ "tabs": { "claude-code:abc123": 3 } }`).
   `0` = ära vaheta tabi üldse.
4. **Tekst.** Kirjuta (või kleebi) paremal all, vajuta **Järjekorda**
   (Ctrl+Enter). **Kõigile** paneb sama teksti igasse elusasse sessiooni.
5. **Järjekord.** Rea järjekord = saatmise järjekord. Lohistad hiirega või
   nuppudega **Üles**/**Alla**. Igal sessioonil oma järjekord.
   Topeltklõps real (või **Muuda**) toob teksti tagasi väljale.
   Juba saadetud teksti muutmine paneb selle tagasi järjekorda.
   **Koopia** teeb duplikaadi otse alla.
6. **Saatmine.** **Saada see järjekord** — ainult valitud sessioon.
   **Saada kõik** — kõik järjekorrad. **Proovisaade** ei saada midagi,
   näitab plaani logis. Päris saadetised küsivad kinnitust.

## Tühista saatmine

Pärast saatmist ilmub **Tühista** nupp 30 sekundiks. See tõmbab viimati
saadetud teksti tagasi järjekorda — kui sessioon pole seda juba
töödelnud.

## Ajakava ja limiidid

- **Saada kell (HH:MM)** — tühi = "kohe". Ajaga ootab järjekord selle
  kellaaja järgmise esinemiseni ja näitab tagasiloendust.
- **Oota limiidi lähtestust** — enne igat teksti loeb SAISENT agendi
  enda teksti. "limit reached" → ootab ja jätkab ise, kui limiit kaob.
- **Kontrolli limiite** — loe kohe uuesti.
- Paremal olekuribal: `limiidid: kõik vabad` või punaselt
  `claude-code: LIMIIT kuni 09:22 (1t 05min jäänud)`.

## Miks järgmised ei lähe

Saatmine on rangelt järjestikune ja peatub esimesel päris veal. Põhjus
ilmub olekuribale, reale ja logisse. Ülejäänud jäävad `ootel` — need
pole kadunud.

## Andur

" Andur" veerg vastab "kas praegu võib kirjutada".

- `kinni` — sessioon kirjutas oma salve < 20s tagasi;
- `ootab` — vaikus > 20s, sisestusväli vaba.

## Kohaletoimetamise aadress

| Väärtus | Meetod | Usaldusväärsus |
|---|---|---|
| `cdp:28194` | Kleebi läbi agendi siluri | Täpne |
| `CTRL+3` | Tabi vahetus | OK, kui number õige |
| `pimesi` | Pole porti ega tabi | Läheb avatud chatti |

## Eksport ja import

**Ekspordi** ja **Impordi** nupud salvestavad/laadivad järjekorrad
JSONL-formaadis. Import liidab ilma andmekadudeta — duplikaadid jäetakse
vahele.

## Failid

| Fail | Sisu |
|---|---|
| `SAISENT.json` | seaded |
| `SAISENT_QUEUES.json` | järjekorrad sessioonide kaupa |
| `SAISENT.log` | saatmislogi |

## Testid

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:a73584ea9e942d83d3a1d5a38f8437aa55a5abf8837b778d616815f160dc0a56 -->
