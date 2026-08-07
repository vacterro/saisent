# SAISENT 4.0

Ohjauspaneeli, joka liittää etukäteen valmistellun tekstin tällä koneella parhaillaan käynnissä olevien agenttisessioiden keskusteluihin.

Laita teksti oikean sessioon jonoon — SAISENT aktivoi agentin ikkunan, vaihtaa kyseisen session välilehdelle, liittää tekstin yhdellä toiminnolla ja painaa Enteriä.

## Pika-aloitus

```
START_SAISENT.bat
```

Vaatii Python 3.11+ Windowsissa.

## Käyttö

1. **Agentit.** Ylin rivi — valintaruudut: Claude Code, Freebuff, Antigravity, CodeNomad.
   Rastita agentti, niin sen sessiot näkyvät vasemmassa paneelissa.
2. **Live-sessiot.** Vasemmalla se, mikä todella toimii: session nimi, välilehden numero, aktiivisuusanturi ja projekti. Luettelo ei päivity itsestään, ellet ota käyttöön "joka N s" — oletuksena päivitys vain **Päivitä**-painikkeella.
3. **Välilehti.** SAISENT arvaa välilehden numeron sessioiden käynnistysjärjestyksestä. Väärin? Kirjoita numero käsin `SAISENT.json`-tiedostoon, avaimeen `tabs` (sessioavain muodossa `<agentti>:<id>`, esim. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = älä vaihda välilehteä ollenkaan.
4. **Teksti.** Kirjoita (tai liitä) oikeaan alareunaan, paina **Jonoon** (tai Ctrl+Enter). **Kaikki jonoon** laittaa saman tekstin jokaiseen live-sessioon — korvaa vanhan makron "CTRL+2, teksti, CTRL+3, teksti".
5. **Jono.** Rivien järjestys = lähetysjärjestys. Vedä riviä hiirellä tai siirrä **Ylös**/**Alas**-painikkeilla. Jokaisella sessioilla on oma jono. Kaksoisnapsauta riviä (tai **Muokkaa**-painiketta), niin kehote palaa tekstikenttään; **Tallenna muokkaus** kirjoittaa sen paikalleen, **Peruuta** hylkää. Jo lähetetyn kehotteen muokkaaminen palauttaa sen jonoon — rivin teksti ei enää vastaa sitä, minkä sessio sai. **Monista** asettaa kopion heti alle.
6. **Lähetys.** **LÄHETÄ TÄMÄ JONO** — vain valittu sessio. **LÄHETÄ KAIKKI** — kaikki jonot peräkkäin. **Kuiva-ajo** ei lähetä mitään, vaan näyttää suunnitelman lokissa. Oikeat lähetykset kysyvät ensin vahvistuksen ja nimeävät sessiot.

## Kumoa lähetys

Lähetyksen jälkeen **Kumoa**-painike näkyy 30 sekunnin ajan. Se palauttaa viimeksi lähetetyn kehotteen jonoon `pending`-tilassa — ellei sessio ole jo käsitellyt sitä (vahvistettu toimitus).

## Ajoitus ja rajat

"Lähetä"-ryhmässä:

- **Lähetä klo (HH:MM)** — tyhjä tarkoittaa "heti". Ajan kanssa jono odottaa seuraavaa kyseisen kellonajan esiintymää (tänään, tai huomenna jos se on jo mennyt) ja näyttää lähtölaskennan tilapalkissa.
- **Odota rajan palautusta** — ennen jokaista kehotetta SAISENT lukee agentin oman tekstin. Jos se sanoo "limit reached", jono odottaa ja jatkuu automaattisesti, kun raja vapautuu. Ei yhtään kehotetta lukittuun oveen.
- **Tarkista rajat** — lue uudelleen nyt.
- Oikealla oleva tilakenttä näyttää live-tilan: `limits: all agents free` tai `claude-code: LIMITED until 09:22 (1h 05m remaining)`, punaisella. Lähtölaskenta tikittää kerran sekunnissa välimuistista; levyyn kosketaan vain, kun luku on vanhentunut tai nimetty palautusaika koittaa.

Palautusaika otetaan agentin omista sanoista. Jos se ei ilmoita aikaa, SAISENT kirjoittaa "reset time not stated" sen sijaan, että keksisi paikkamerkin kuten "+5 tuntia".

### Milloin rajat palautuvat

Jos agentti ei koskaan ilmoita palautusaikaa, SAISENT turvautuu agenttikohtaiseen sääntöön:

| Agentti | Sääntö | Merkitys |
|---|---|---|
| Freebuff | `daily 10:00` | palautuu joka päivä klo 10:00 |
| CodeNomad | `daily 03:00` | palautuu joka päivä klo 03:00 |
| Claude Code | `rolling 5h` | 5 tuntia viimeksi lähetetyn kehotteen jälkeen |
| Antigravity | vain agentin sanat | ei sääntöä — mitä se ilmoittaa, tai ei mitään |

Sääntö ei koskaan ohita agentin ilmoittamaa aikaa; agentti on oman kiintiönsä auktoriteetti. Minkä tahansa säännön voi korvata `SAISENT.json`-tiedoston `quota_plans`-avaimessa, esim. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Miksi seuraavat eivät lähde

Lähetys on tiukasti peräkkäinen ja pysähtyy ensimmäiseen todelliseen virheeseen. Syy näkyy tilapalkissa (`stopped: window not found: ...`), kehotteen rivillä luettelossa ja lokissa. Loput jäävät `pending`-tilaan — mikään ei katoa.

Kehotteiden välillä on `gap_ms`-tauko (oletus 1500 ms), ja tila näyttää `Waiting N.Ns before next`. Jos kehote lähti mutta sessio ei liikkunut, se merkitään **vahvistamattomaksi** ja jää jonoon. "Lähetetty" koskee vain vahvistettuja toimituksia.

## Aktiivisuusanturi

"Anturi"-sarake vastaa kysymykseen "voinko kirjoittaa nyt".

- `busy` — sessio kirjoitti tallennustilaansa alle 20 sekuntia sitten (agentti on vuoron keskellä);
- `idle` — hiljaisuus yli 20 sekuntia, syöttökenttä on vapaa.

Mistä se tulee:

| Agentti | Lähde | Anturi |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + transkriptio | viimeisin kirjoitusaika transkriptiossa |
| Freebuff | `<projekti>/.freebuff/desktop-v2.db`, `threads`-taulu | `turn_state`-kenttä |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | tietokannan ja sen `-wal`-tiedoston mtime |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | viimeisin kirjoitusaika transkriptiossa |

Elävyys on erillinen tarkistus, ei "levyn tiedosto on tuore":

- **Claude Code** — PID osoitteesta `~/.claude/sessions/<pid>.json` on elossa. Tiedosto säilyy session sulkemisen jälkeen; PID ei.
- **Freebuff** — `Freebuff.exe` on käynnissä. Tietokanta pitää säikeet `open`-tilassa, vaikka sovellus suljettaisiin.
- **Antigravity** — `Antigravity.exe` on käynnissä **ja** keskustelu on tuore. Tuoreus yksin ei riitä: tämä tallennustila säilyttää kaikki keskustelut ikuisesti, ja suljettu editori täytti ennen luettelon sessioilla, joihin mikään näppäin ei yltänyt.
- **CodeNomad** — tietokannan riviä ei ole arkistoitu (`time_archived IS NULL`). Aktiivisia ovat vain parhaillaan auki olevat.

## Toimitusosoite — "Osoite"-sarake

Sivupalkki näyttää tarkalleen, miten kukin sessio kohdistetaan:

| Arvo | Menetelmä | Luotettavuus |
|---|---|---|
| `cdp:28194` | Liittäminen agentin debuggerin kautta | Tarkka: kenttä luetaan ennen ja jälkeen, tarkennusta ei varasteta |
| `CTRL+3` | Välilehden vaihto agentin ikkunassa | Hyvä, jos välilehden numero on oikea |
| `blind` | Ei porttia, ei välilehden numeroa | Kehote päätyy siihen keskusteluun, joka on auki |

Missään ikkunan otsikossa ei ole session nimeä — `claude.exe` on nimeltään "Claude", Antigravity on "Antigravity", Freebuff on "Freebuff Desktop". Kohdistaminen ikkunan kautta on siksi mahdotonta, ja `blind` tarkoittaa tarkalleen sitä, mitä se sanoo.

### CDP — luotettava reitti

Jos agentti on käynnistetty `--remote-debugging-port`-lipulla, SAISENT lähettää debuggerin kautta eikä koske tarkennukseen eikä näppäimistöön. Se tarkoittaa:

- teksti liitetään suoraan syöttökenttään, ei "minne sattuu";
- kenttä luetaan **ennen** liittämistä: jos siinä on puoliksi kirjoitettu viesti, lähetys kieltäytyy sen sijaan, että jatkaisi toisen lausetta;
- kenttä luetaan **liittämisen jälkeen**: jos se ei saapunut, emme lähetä.

CDP-kielteinen vastaus ei koskaan putoa sokeisiin näppäinpainalluksiin. Tarkka siirtotapa juuri sanoi, että hetki on väärä; näppäinten hakkaaminen sen päälle on juuri se tapa, jolla toisen keskustelu tärveltyy.

Portti luetaan agentin `DevToolsActivePort`-tiedostosta, mutta tiedosto yksin ei riitä — se säilyy edellisestä käynnistyksestä. SAISENT oikeasti yhdistää porttiin ennen jokaista tiedustelua.

Ota debugger käyttöön agentille (uudelleenkäynnistys tappaa sen, mitä se tekee — SAISENT ei tee tätä koskaan itse):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Sivun valitsimet (live-DOM, 2026-08-05)

| Agentti | Portti | Syöttökenttä | Dialogiluettelo |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | ei mitään | — | — |

Antigravity varmennettu: 16 painiketta, etiketit vastaavat tarkalleen niitä projektinimiä, joita SAISENT näyttää (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — dialogin valinta nimellä toimii tarkasti.

CodeNomad on Electron OpenCoden päällä; datakansio on edelleen nimeltään `Plasticity`. DOM:n sessioluettelo sisältää vain **parhaillaan avoinna olevan projektin** sessiot; toisen projektin sessiota ei renderöidä, eikä SAISENT löydä sitä — lähetys kieltäytyy sen sijaan, että hakkaisi sokeasti avointa keskustelua.

Korvaa mikä tahansa profiiliavain `SAISENT.json`-tiedostossa:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Sessiot luetaan `~/.local/share/opencode/opencode.db`-tiedoston `session`-taulusta: nimi = `title`, projekti = `directory`, arkistoidut suodatetaan `time_archived`-kentällä, anturi `time_updated`-kentällä. Ainoa agentti tässä, jonka sessioluettelo on tavallisia sarakkeita — ei protobufia, ei jäsennystä.

Elävyys — `CodeNomad.exe` on käynnissä. Ei välilehden numeroa: kohdistetaan nimellä debuggerin kautta.

## Miksi ei ikkunan otsikon mukaan

Jokainen `claude.exe`-ikkuna on nimeltään "Claude". Session nimeä ei koskaan näy otsikossa, joten kohdistaminen ikkunan kautta on mahdotonta — nimi, projekti ja PID tulevat levyltä; ikkunaa tarvitaan vain tarkennusta varten.

## Toimituksen vahvistus

Chromium ei vastaa `WM_GETTEXT`-viestiin, joten "saapuiko se kenttään" -lukeminen Win32:n kautta on mahdotonta — vanha read-back näille agenteille palautti aina "vahvistamaton". Sen sijaan SAISENT odottaa, että sama tiedosto, jota aktiivisuusanturi tarkkailee, liikkuu. Liikkuiko? Toimitettu. Ei liikkunut annetussa ajassa? Kehote merkitään lähetetyksi mutta vahvistamattomaksi, ja se näkyy lokissa. Tätä ei lasketa virheeksi: agentti ei ehkä ole vielä aloittanut vuoroaan.

Lähetys pysähtyy ensimmäiseen todelliseen virheeseen (ikkunaa ei löydy, tarkennus karkasi, leikepöytä varattu). Seuraavat kehotteet jäävät jonoon — ne eivät katoa eikä niitä lähetetä sokeasti.

## Vienti ja tuonti

**Vie**- ja **Tuo**-painikkeet tallentavat/lataavat jonoja JSONL-muodossa. Jokainen rivi on itsenäinen sessioavaimellaan. Tuonti yhdistää ilman tiedonmenetystä — kaksoiskappaleet (sama avain + teksti) ohitetaan.

## Tiedostot ohjelman vieressä

| Tiedosto | Sisältö |
|---|---|
| `SAISENT.json` | asetukset: agentit, välilehden numerot, aikarajat, ikkunan geometria |
| `SAISENT_QUEUES.json` | jonot sessioittain, säilyvät uudelleenkäynnistyksessä |
| `SAISENT.log` | lähetyshistoria |

Jonoa ei koskaan siivota automaattisesti. Jos sessio katoaa luettelosta mutta sen jonossa on lähettämättömiä kohteita, jono jää: agentit käynnistetään uudelleen, ja hiljaa heitetty jono on pahempi kuin ylimääräinen rivi tiedostossa.

## Piilotetut asetukset

Muokkaa `SAISENT.json`-tiedostoa ohjelman ollessa suljettu:

- `gap_ms` — tauko kehotteiden välillä yhdessä erässä (oletus 1500);
- `settle_ms` — tauko välilehden vaihdon ja liittämisen jälkeen (400);
- `confirm_seconds` — kuinka kauan odottaa toimitusvahvistusta (10);
- `busy_seconds` — anturin "busy/idle"-kynnys (20);
- `freebuff_roots` — juuret, joista `.freebuff/desktop-v2.db`-tiedostoa haetaan, esim. `["V:\\___VAC\\__K\\__CODE"]`; hakusyvyys rajoitettu 3:een;
- `submit` — näppäin, jolla lähetetään, oletus `ENTER`.

## Rajoitukset

- Välilehdet kohdistetaan `Ctrl+1..Ctrl+9`-näppäimillä. Kymmenes sessio on tavoittamaton — `Ctrl+10`-näppäintä ei ole, ja SAISENT kieltäytyy sen sijaan, että arvaisi.
- Välilehden numero on arvaus käynnistysjärjestyksen perusteella. Tee ensimmäinen ajo **Kuiva-ajona**, sitten ei-tärkeällä sessioilla.
- Antigravity ei tallenna keskustelun nimiä tekstinä: luettelo näyttää työkansion nimen, joka on haettu metadatasta.

## Testit

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
