# SAISENT 4.0

Panel sterowania, który wkleja wcześniej przygotowany tekst do sesji agentów aktualnie uruchomionych na tej maszynie.

Umieszczasz tekst w kolejce właściwej sesji — SAISENT aktywuje okno agenta, przełącza na kartę tej sesji, wkleja tekst jedną operacją i naciska Enter.

## Szybki start

```
START_SAISENT.bat
```

Wymaga Pythona 3.11+ w systemie Windows.

## Jak używać

1. **Agenci.** Górny rząd — pola wyboru: Claude Code, Freebuff, Antigravity, CodeNomad.
   Zaznaczasz agenta, a jego sesje pojawiają się w lewym panelu.
2. **Żywe sesje.** Po lewej to, co naprawdę działa: nazwa sesji, numer karty, czujnik aktywności i projekt. Lista nie odświeża się sama, dopóki nie włączysz „co N s" — domyślnie odświeżanie tylko przyciskiem **Odśwież**.
3. **Karta.** SAISENT zgaduje numer karty po kolejności uruchamiania sesji. Źle? Wpisz numer ręcznie w `SAISENT.json`, klucz `tabs` (klucz sesji w formie `<agent>:<id>`, np. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = nie przełączaj karty wcale.
4. **Tekst.** Piszesz (lub wklejasz) w prawym dolnym rogu, naciskasz **Do kolejki** (lub Ctrl+Enter). **Wszystko do kolejki** wkłada ten sam tekst do każdej żywej sesji — zastępuje starą makro „CTRL+2, tekst, CTRL+3, tekst".
5. **Kolejka.** Kolejność wierszy = kolejność wysyłki. Przeciągasz wiersz myszą lub przesuwasz przyciskami **W górę**/**W dół**. Każda sesja ma własną kolejkę. Dwuklik na wiersz (lub przycisk **Edytuj**) wyciąga prompt z powrotem do pola tekstowego; **Zapisz edycję** nadpisuje go w miejscu, **Anuluj** porzuca. Edycja już wysłanego promptu zwraca go do kolejki — tekst w wierszu nie jest już tym, co otrzymała sesja. **Duplikuj** umieszcza kopię tuż poniżej.
6. **Wysyłka.** **WYŚLIJ TĘ KOLEJKĘ** — tylko wybrana sesja. **WYŚLIJ WSZYSTKO** — wszystkie kolejki po kolei. **Próba na sucho** niczego nie wysyła, tylko pokazuje plan w dzienniku. Prawdziwa wysyłka pyta o potwierdzenie i podaje sesje.

## Cofnij wysyłkę

Po wysyłce przycisk **Cofnij** wisi przez 30 sekund. Zwraca ostatni wysłany prompt do kolejki jako `pending` — chyba że sesja już go przetworzyła (potwierdzona dostawa).

## Harmonogram i limity

W grupie „Wysyłka":

- **Wyślij o (HH:MM)** — puste znaczy „teraz". Z czasem kolejka czeka na najbliższe wystąpienie tego czasu (dziś, a jeśli minął — jutro) i pokazuje odliczanie na pasku statusu.
- **Czekaj na reset limitu** — przed każdym promptem SAISENT czyta tekst samego agenta. Jeśli powie „limit reached", kolejka czeka i rusza sama, gdy limit się zwolni; żaden prompt nie uderza w zamknięte drzwi.
- **Sprawdź limity** — przeczytaj ponownie teraz.
- Pole po prawej pokazuje stan na żywo: `limits: all agents free` lub `claude-code: LIMITED until 09:22 (1h 05m remaining)`, na czerwono. Odliczanie tyka raz na sekundę z pamięci podręcznej; dysk jest dotykany tylko wtedy, gdy odczyt jest nieaktualny lub nadszedł podany czas resetu.

Czas resetu pochodzi ze słów samego agenta. Jeśli go nie poda, SAISENT pisze „reset time not stated" zamiast wymyślać placeholder w stylu „+5 godzin".

### Kiedy resetują się limity

Jeśli agent nigdy nie podaje czasu resetu, SAISENT opiera się na regule dla agenta:

| Agent | Reguła | Znaczenie |
|---|---|---|
| Freebuff | `daily 10:00` | reset codziennie o 10:00 |
| CodeNomad | `daily 03:00` | reset codziennie o 03:00 |
| Claude Code | `rolling 5h` | 5 godzin po ostatnim wysłanym prompcie |
| Antigravity | tylko słowa agenta | brak reguły — co poda, to jest |

Reguła nigdy nie nadpisuje czasu podanego przez agenta; agent jest autorytetem w sprawie własnego limitu. Dowolną regułę można nadpisać w `SAISENT.json` pod `quota_plans`, np. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Dlaczego kolejne nie idą

Wysyłka przebiega ściśle po kolei i zatrzymuje się na pierwszym prawdziwym błędzie. Przyczyna trafia i na pasek statusu (`stopped: window not found: ...`), i do wiersza promptu na liście, i do dziennika. Reszta pozostaje `pending` — nic nie ginie.

Między promptami jest pauza `gap_ms` (domyślnie 1500 ms), a status pokazuje `Waiting N.Ns before next`. Jeśli prompt poszedł, ale sesja się nie ruszyła, uznaje się go za **niepotwierdzony** i pozostaje w kolejce. „Wysłano" stawia się tylko na potwierdzonych.

## Czujnik zajętości

Kolumna „Czujnik" odpowiada na pytanie „czy można teraz pisać".

- `busy` — sesja pisała do swojego magazynu mniej niż 20 sekund temu (agent jest w trakcie tury);
- `idle` — cisza dłuższa niż 20 sekund, pole wejściowe jest wolne.

Skąd się bierze:

| Agent | Źródło | Czujnik |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + transkrypt sesji | czas ostatniego zapisu w transkrypcie |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, tabela `threads` | pole `turn_state` |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime bazy i jej `-wal` |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | czas ostatniego zapisu w transkrypcie |

Żywość to osobna kontrola, a nie „plik na dysku jest świeży":

- **Claude Code** — żywy PID z `~/.claude/sessions/<pid>.json`. Plik zostaje po zamknięciu sesji; PID nie.
- **Freebuff** — działa `Freebuff.exe`. W bazie wątek zostaje `open` nawet po wyjściu z aplikacji.
- **Antigravity** — działa `Antigravity.exe` **i** rozmowa jest świeża. Sama świeżość nie wystarczy: ten magazyn trzyma wszystkie rozmowy na zawsze, a zamknięty edytor dawniej zapełniał listę sesjami, których nie dosięgnął żaden klawisz.
- **CodeNomad** — wiersz bazy nie jest zarchiwizowany (`time_archived IS NULL`). Aktywne są tylko aktualnie otwarte.

## Dokąd dokładnie idzie — kolumna „Adres"

Na pasku bocznym każdej sesji napisano, czym dokładnie będzie ona uderzona:

| Wartość | Metoda | Jak niezawodnie |
|---|---|---|
| `cdp:28194` | wstawienie przez debugger agenta | dokładnie: pole czytane przed i po, fokus nie jest kradziony |
| `CTRL+3` | przełączenie karty w oknie agenta | dobrze, jeśli numer karty poprawny |
| `blind` | ani portu, ani numeru karty | prompt trafi do otwartego czatu |

Żaden tytuł okna nie zawiera nazwy sesji — `claude.exe` nazywa się „Claude", Antigravity nazywa się „Antigravity", Freebuff nazywa się „Freebuff Desktop". Dlatego adresowanie po oknie jest niemożliwe, a `blind` znaczy dokładnie to, co napisano.

### CDP — niezawodna ścieżka

Jeśli agent został uruchomiony z `--remote-debugging-port`, SAISENT wysyła przez debugger i nie dotyka ani fokusu, ani klawiatury. Co to daje:

- tekst jest wstawiany bezpośrednio do pola wejściowego, a nie „gdzie popadnie";
- pole jest czytane **przed** wstawieniem: jeśli leży tam niedokończona wiadomość, wysyłka odmawia zamiast dopisywać do cudzego zdania;
- pole jest czytane **po** wstawieniu: nie doleciało — nie wysyłamy.

Odmowa CDP nigdy nie cofa się do ślepych klawiszy. Precyzyjny transport właśnie powiedział, że moment jest nieodpowiedni; młócenie po tym klawiszami to dokładnie sposób na zepsucie cudzego czatu.

Port jest brany z `DevToolsActivePort` agenta, ale samego pliku mało: zostaje po poprzednim uruchomieniu. Przed każdą próbą SAISENT naprawdę łączy się z portem.

Włączyć debugger dla agenta (restart zabije to, co teraz robi — SAISENT sam tego nigdy nie robi):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Selektory stron (zdjęte z żywego DOM 2026-08-05)

| Agent | Port | Pole wejściowe | Lista dialogów |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | brak | — | — |

Antigravity sprawdzony: 16 przycisków, etykiety dokładnie odpowiadają nazwom projektów, które pokazuje SAISENT (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — wybór dialogu po nazwie działa precyzyjnie.

CodeNomad to Electron na OpenCode; folder danych wciąż nazywa się `Plasticity`. Lista sesji w DOM zawiera tylko sesje **aktualnie otwartego projektu**; sesja z innego projektu nie jest renderowana i SAISENT jej nie znajdzie — wysyłka odmawia, a nie bije na ślepo w otwarty czat.

Nadpisać dowolny klucz profilu można w `SAISENT.json`:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Sesje czyta się z `~/.local/share/opencode/opencode.db`, tabela `session`: nazwa = `title`, projekt = `directory`, zamknięte odsiane po `time_archived`, czujnik — po `time_updated`. Jedyny agent tutaj, u którego lista sesji leży zwykłymi kolumnami, bez protobufa i bez parsowania.

Żywość — działa `CodeNomad.exe`. Numeru karty nie ma: adresowany po nazwie przez debugger.

## Dlaczego nie po tytule okna

Wszystkie okna `claude.exe` nazywają się „Claude". Nazwa sesji nie trafia do tytułu, więc adresowanie po oknie jest niemożliwe — nazwa, projekt i PID biorą się z dysku; okno potrzebne jest tylko do fokusu.

## Potwierdzenie dostawy

Chromium nie odpowiada na `WM_GETTEXT`, więc odczytanie „czy wpadło do pola" przez Win32 jest niemożliwe — stary read-back dla tych agentów zawsze zwracał „niepotwierdzone". Zamiast tego SAISENT czeka, aż przesunie się ten sam plik, na którym pracuje czujnik. Przesunął się — dostarczono. Nie przesunął się w wyznaczonym czasie — prompt jest oznaczony jako wysłany, ale niepotwierdzony, i to widać w dzienniku. Nie uchodzi to za błąd: agent mógł po prostu jeszcze nie zacząć tury.

Wysyłka zatrzymuje się na pierwszym prawdziwym błędzie (okno nie znalezione, fokus uciekł, schowek zajęty). Kolejne prompty pozostają w kolejce — nie giną i nie idą na ślepo.

## Eksport i import

Przyciski **Eksport** i **Import** zapisują/ładują kolejki w formacie JSONL. Każdy wiersz jest samowystarczalny z kluczem sesji. Import łączy bez utraty danych — duplikaty (ten sam klucz + tekst) są pomijane.

## Pliki obok programu

| Plik | Co w środku |
|---|---|
| `SAISENT.json` | ustawienia: agenci, numery kart, timeouty, geometria okna |
| `SAISENT_QUEUES.json` | kolejki po sesjach, przeżywają restart |
| `SAISENT.log` | dziennik wysyłek |

Kolejka nigdy nie jest czyszczona sama. Sesja zniknęła z listy, a w jej kolejce jest niewysłane — kolejka zostanie: agenci są restartowani, a cicho zjedzona kolejka jest gorsza niż dodatkowy wiersz w pliku.

## Ustawienia bez interfejsu

Edytowane w `SAISENT.json` (program musi być przy tym zamknięty):

- `gap_ms` — pauza między promptami w ramach jednej partii (domyślnie 1500);
- `settle_ms` — pauza po przełączeniu karty i po wstawieniu (400);
- `confirm_seconds` — ile czekać na potwierdzenie dostawy (10);
- `busy_seconds` — granica czujnika „busy/idle" (20);
- `freebuff_roots` — korzenie, gdzie szukać `.freebuff/desktop-v2.db`, np. `["V:\\___VAC\\__K\\__CODE"]`; głębokość ograniczona do 3;
- `submit` — czym wysyłać, domyślnie `ENTER`.

## Ograniczenia

- Karty są adresowane przez `Ctrl+1..Ctrl+9`. Dziesiąta sesja jest nieosiągalna — `Ctrl+10` nie istnieje, i SAISENT odmówi, a nie spudłuje.
- Numer karty to zgadywanie po kolejności uruchamiania. Pierwszy przebieg rób z **Próbą na sucho**, potem na nieważnej sesji.
- Antigravity nie przechowuje nazwy rozmowy tekstem: na liście będzie nazwa folderu roboczego wyciągnięta z metadanych.

## Testy

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
