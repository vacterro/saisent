# SAISENT 4.0

Upravljačka ploča koja ubacuje unaprijed pripremljeni tekst u sesije agenata koji trenutačno rade na ovom računalu.

Stavite tekst u red za ispravnu sesiju — SAISENT aktivira prozor agenta, prebaci se na karticu te sesije, ubaci tekst u jednoj operaciji i pritisne Enter.

## Brzi početak

```
START_SAISENT.bat
```

Zahtijeva Python 3.11+ na Windowsu.

## Kako se koristi

1. **Agenti.** Gornji red — potvrdni okviri: Claude Code, Freebuff, Antigravity, CodeNomad.
   Označite agenta i njegove sesije pojavljuju se u lijevom panelu.
2. **Žive sesije.** Lijevo je ono što stvarno radi: naziv sesije, broj kartice, senzor aktivnosti i projekt. Popis se ne osvježava sam, osim ako ne uključite "svakih N s" — prema zadanim postavkama samo gumbom **Osvježi**.
3. **Kartica.** SAISENT pogađa broj kartice prema redoslijedu pokretanja sesija. Krivo? Upišite broj ručno u `SAISENT.json`, ključ `tabs` (ključ sesije u obliku `<agent>:<id>`, npr. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = uopće ne mijenjaj karticu.
4. **Tekst.** Pišete (ili lijepite) dolje desno, pritisnete **U red** (ili Ctrl+Enter). **Sve u red** stavlja isti tekst u svaku živu sesiju — zamjena za stari makro "CTRL+2, tekst, CTRL+3, tekst".
5. **Red.** Redoslijed redaka = redoslijed slanja. Povucite redak mišem ili ga pomičite gumbima **Gore**/**Dolje**. Svaka sesija ima svoj red. Dvostruki klik na redak (ili gumb **Uredi**) vraća upit natrag u polje teksta; **Spremi izmjenu** ga prepisuje na mjestu, **Odustani** baca. Uređivanje već poslanog upita vraća ga u red — tekst u retku više ne odgovara onome što je sesija primila. **Dupliciraj** stavlja kopiju odmah ispod.
6. **Slanje.** **POŠALJI OVAJ RED** — samo odabrana sesija. **POŠALJI SVE** — svi redovi redom. **Suhi pokus** ništa ne šalje, samo prikazuje plan u zapisniku. Pravo slanje prvo traži potvrdu i imenuje sesije.

## Poništi slanje

Nakon slanja gumb **Poništi** visi 30 sekundi. Vraća posljednji poslani upit u red kao `pending` — osim ako ga sesija već nije obradila (potvrđena dostava).

## Raspored i ograničenja

U grupi "Slanje":

- **Pošalji u (HH:MM)** — prazno znači "sada". S vremenom red čeka sljedeći nastup tog vremena (danas, ili sutra ako je prošlo) i prikazuje odbrojavanje u traci statusa.
- **Čekaj reset ograničenja** — prije svakog upita SAISENT čita tekst samog agenta. Ako kaže "limit reached", red čeka i sam se nastavlja čim se ograničenje oslobodi; nijedan upit u zatvorena vrata.
- **Provjeri ograničenja** — pročitaj ponovno sada.
- Polje desno prikazuje živo stanje: `limits: all agents free` ili `claude-code: LIMITED until 09:22 (1h 05m remaining)`, crveno. Odbrojavanje otkucava jednom u sekundi iz predmemorije; disk se dira samo kad je čitanje zastarjelo ili kad nastupi navedeno vrijeme resetiranja.

Vrijeme resetiranja uzima se iz riječi samog agenta. Ako ga ne navede, SAISENT piše "reset time not stated" umjesto da izmišlja rezervirano mjesto poput "+5 sati".

### Kada se ograničenja resetiraju

Ako agent nikad ne navede vrijeme resetiranja, SAISENT se oslanja na pravilo po agentu:

| Agent | Pravilo | Značenje |
|---|---|---|
| Freebuff | `daily 10:00` | reset svaki dan u 10:00 |
| CodeNomad | `daily 03:00` | reset svaki dan u 03:00 |
| Claude Code | `rolling 5h` | 5 sati nakon zadnjeg poslanog upita |
| Antigravity | samo riječi agenta | nema pravila — što navede, to jest |

Pravilo nikad ne nadjačava vrijeme koje je naveo agent; agent je autoritet nad vlastitim ograničenjem. Bilo koje pravilo može se nadjačati u `SAISENT.json` pod `quota_plans`, npr. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Zašto se sljedeći ne šalju

Slanje ide strogo po redu i zaustavlja se na prvoj pravoj pogrešci. Razlog dospijeva i u traku statusa (`stopped: window not found: ...`), i u redak upita u popisu, i u zapisnik. Ostali ostaju `pending` — nisu izgubljeni.

Između upita drži se pauza `gap_ms` (zadano 1500 ms), a status pokazuje `Waiting N.Ns before next`. Ako je upit otišao, ali se sesija nije pomaknula, smatra se **nepotvrđenim** i ostaje u redu. "Poslano" se stavlja samo na potvrđene dostave.

## Senzor aktivnosti

Stupac "Senzor" odgovara na pitanje "može li se sada pisati".

- `busy` — sesija je pisala u svoju pohranu prije manje od 20 sekundi (agent je usred poteza);
- `idle` — tišina duža od 20 sekundi, polje za unos je slobodno.

Odakle se uzima:

| Agent | Izvor | Senzor |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + transkript sesije | vrijeme zadnjeg zapisa u transkriptu |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, tablica `threads` | vlastito polje `turn_state` |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime baze i njezinog `-wal` |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | vrijeme zadnjeg zapisa u transkriptu |

Živost je zasebna provjera, a ne "datoteka na disku je svježa":

- **Claude Code** — živi PID iz `~/.claude/sessions/<pid>.json`. Datoteka ostaje nakon zatvaranja sesije; PID ne.
- **Freebuff** — pokrenut je `Freebuff.exe`. U bazi nit ostaje `open` i nakon izlaska iz aplikacije.
- **Antigravity** — pokrenut je `Antigravity.exe` **i** razgovor je svjež. Sama svježina nije dovoljna: ova pohrana čuva sve razgovore zauvijek, a zatvoreni uređivač prije je punio popis sesijama do kojih nijedna tipka nije mogla doprijeti.
- **CodeNomad** — redak u bazi nije arhiviran (`time_archived IS NULL`). Aktivne su samo trenutno otvorene.

## Kamo točno ide — stupac "Adresa"

U bočnoj traci svake sesije piše čime će točno biti pogođena:

| Vrijednost | Metoda | Koliko pouzdano |
|---|---|---|
| `cdp:28194` | umetanje putem debuggera agenta | točno: polje se čita prije i poslije, fokus se ne krade |
| `CTRL+3` | prebacivanje kartice u prozoru agenta | normalno, ako je broj kartice točan |
| `blind` | ni port, ni broj kartice | upit će otići u otvoreni chat |

Nijedan naslov prozora ne sadrži naziv sesije — `claude.exe` se zove "Claude", Antigravity se zove "Antigravity", Freebuff se zove "Freebuff Desktop". Zato adresiranje po prozoru nije moguće, a `blind` znači točno ono što piše.

### CDP — pouzdani put

Ako je agent pokrenut s `--remote-debugging-port`, SAISENT šalje kroz debugger i ne dira ni fokus ni tipkovnicu. Što to daje:

- tekst se umeće izravno u polje za unos, a ne "kamo god";
- polje se čita **prije** umetanja: ako je tamo nedovršena poruka, slanje odbija umjesto da dopisuje tuđoj rečenici;
- polje se čita **poslije** umetanja: nije dospjelo — ne šaljemo.

Odbijanje CDP-a nikad se ne vraća na slijepe tipke. Točan transport upravo je rekao da trenutak nije prikladan; udaranje tipkama preko toga upravo je način da se uprlja tuđi chat.

Port se uzima iz `DevToolsActivePort` agenta, ali sam dokument nije dovoljan: ostaje od prethodnog pokretanja. SAISENT se prije svake probe stvarno povezuje s portom.

Uključite debugger za agenta (ponovno pokretanje ubit će ono što radi — SAISENT to nikad ne čini sam):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Selektor stranica (snimljeno sa živog DOM-a 2026-08-05)

| Agent | Port | Polje za unos | Popis dijaloga |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | nema | — | — |

Antigravity provjeren: 16 gumba, oznake točno odgovaraju nazivima projekata koje SAISENT prikazuje (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — odabir dijaloga po imenu radi točno.

CodeNomad je Electron na OpenCodeu; mapa s podacima još se zove `Plasticity`. Popis sesija u DOM-u sadrži samo sesije **trenutačno otvorenog projekta**; sesija iz drugog projekta nije renderirana i SAISENT je neće pronaći — slanje odbija umjesto da na slijepo pogodi otvoreni chat.

Bilo koji ključ profila može se nadjačati u `SAISENT.json`:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Sesije se čitaju iz `~/.local/share/opencode/opencode.db`, tablica `session`: naziv = `title`, projekt = `directory`, zatvorene se izdvajaju po `time_archived`, senzor — po `time_updated`. Jedini agent ovdje čiji je popis sesija u običnim stupcima, bez protobufa i bez parsiranja.

Živost — pokrenut je `CodeNomad.exe`. Broja kartice nema: adresira se po imenu kroz debugger.

## Zašto ne po naslovu prozora

Svi prozori `claude.exe` zovu se "Claude". Naziv sesije ne dospijeva u naslov, pa adresiranje po prozoru nije moguće — naziv, projekt i PID uzimaju se s diska; prozor je potreban samo za fokus.

## Potvrda dostave

Chromium ne odgovara na `WM_GETTEXT`, pa čitanje "je li dospjelo u polje" kroz Win32 nije moguće — stari read-back kod ovih agenata uvijek je vraćao "nepotvrđeno". Umjesto toga SAISENT čeka da se pomakne ista datoteka po kojoj radi senzor. Pomaknula se — dostavljeno. Nije se pomaknula u zadanom vremenu — upit se označava kao poslan, ali nepotvrđen, i to se vidi u zapisniku. To se ne smatra pogreškom: agent je možda jednostavno još počeo potez.

Slanje se zaustavlja na prvoj pravoj pogrešci (prozor nije pronađen, fokus je pobjegao, međuspremnik je zauzet). Sljedeći upiti ostaju u redu — ne gube se i ne idu naslijepo.

## Izvoz i uvoz

Gumbi **Izvoz** i **Uvoz** spremaju/učitavaju redove u JSONL formatu. Svaki redak je samodostatan s ključem sesije. Uvoz spaja bez gubitka podataka — duplikati (isti ključ + tekst) preskaču se.

## Datoteke pored programa

| Datoteka | Što je unutra |
|---|---|
| `SAISENT.json` | postavke: agenti, brojevi kartica, timeouti, geometrija prozora |
| `SAISENT_QUEUES.json` | redovi po sesijama, preživljavaju ponovno pokretanje |
| `SAISENT.log` | zapisnik slanja |

Red se nikad ne čisti sam. Sesija je nestala s popisa, a u njezinu redu ima neposlanog — red će ostati: agenti se ponovno pokreću, a tiho pojeden red gori je od suvišnog retka u datoteci.

## Postavke bez sučelja

Uređuju se u `SAISENT.json` (program mora biti zatvoren):

- `gap_ms` — pauza između upita unutar jedne serije (zadano 1500);
- `settle_ms` — pauza nakon prebacivanja kartice i nakon umetanja (400);
- `confirm_seconds` — koliko se čeka potvrda dostave (10);
- `busy_seconds` — granica senzora "busy/idle" (20);
- `freebuff_roots` — korijeni gdje se traži `.freebuff/desktop-v2.db`, npr. `["V:\\___VAC\\__K\\__CODE"]`; dubina ograničena na 3;
- `submit` — čime se šalje, zadano `ENTER`.

## Ograničenja

- Kartice se adresiraju putem `Ctrl+1..Ctrl+9`. Deseta sesija je nedostupna — `Ctrl+10` ne postoji i SAISENT će odbiti, a ne promašiti.
- Broj kartice je pogađanje prema redoslijedu pokretanja. Prvi probni rad radite sa **Suhim pokusom**, zatim na nevažnoj sesiji.
- Antigravity ne pohranjuje naziv razgovora kao tekst: u popisu će biti naziv radne mape izvučen iz metapodataka.

## Testovi

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
