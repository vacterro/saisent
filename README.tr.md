# SAISENT 4.0

Bu makinede şu anda çalışan ajan oturumlarına önceden hazırlanmış metni yapıştıran bir kontrol paneli.

Metni doğru oturumun kuyruğuna koyun — SAISENT ajan penceresini etkinleştirir, o oturumun sekmesine geçer, metni tek işlemde yapıştırır ve Enter'a basar.

## Hızlı başlangıç

```
START_SAISENT.bat
```

Windows'ta Python 3.11+ gerekir.

## Nasıl kullanılır

1. **Ajanlar.** Üst satır — onay kutuları: Claude Code, Freebuff, Antigravity, CodeNomad.
   Bir ajanı işaretleyin, oturumları sol panelde belirir.
2. **Canlı oturumlar.** Solda gerçekten çalışan şey: oturum adı, sekme numarası, etkinlik sensörü ve proje. "Her N sn"yi açmadıkça liste kendiliğinden güncellenmez — varsayılan olarak yalnızca **Yenile** düğmesiyle güncellenir.
3. **Sekme.** SAISENT sekme numarasını oturumların başlatma sırasından tahmin eder. Yanlış mı? Numarayı `SAISENT.json` içinde `tabs` anahtarına elle yazın (oturum anahtarı `<agent>:<id>` biçiminde, ör. `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = hiç sekme değiştirme.
4. **Metin.** Sağ altta yazın (veya yapıştırın), **Kuyruğa** (veya Ctrl+Enter) basın. **Hepsini kuyruğa** aynı metni her canlı oturuma koyar — eski "CTRL+2, metin, CTRL+3, metin" makrosunun yerine geçer.
5. **Kuyruk.** Satır sırası = gönderim sırası. Bir satırı fareyle sürükleyin veya **Yukarı**/**Aşağı** düğmeleriyle taşıyın. Her oturumun kendi kuyruğu vardır. Bir satıra çift tıklayın (veya **Düzenle** düğmesi) istemi metin kutusuna geri getirir; **Düzenlemeyi kaydet** yerinde yeniden yazar, **İptal** atar. Zaten gönderilmiş bir istemi düzenlemek onu kuyruğa geri koyar — satırdaki metin artık oturumun aldığıyla eşleşmez. **Çoğalt** hemen altına bir kopya koyar.
6. **Gönderim.** **BU KUYRUĞU GÖNDER** — yalnızca seçili oturum. **HEPSİNİ GÖNDER** — tüm kuyruklar sırayla. **Kuru çalıştırma** hiçbir şey göndermez, yalnızca planı günlükte gösterir. Gerçek gönderimler önce onay ister ve oturumları adlandırır.

## Gönderimi geri al

Gönderimden sonra **Geri al** düğmesi 30 saniye görünür. Son gönderilen istemi `pending` olarak kuyruğa geri getirir — oturum onu zaten işlemediyse (onaylanmış teslimat).

## Zamanlama ve limitler

"Gönder" grubunda:

- **Şu saatte gönder (HH:MM)** — boş "şimdi" demektir. Bir saatle kuyruk o saatin bir sonraki gelişini bekler (bugün, geçtiyse yarın) ve durum çubuğunda geri sayım gösterir.
- **Limit sıfırlanmasını bekle** — her istemden önce SAISENT ajanın kendi metnini okur. "limit reached" derse kuyruk bekler ve limit boşaldığında otomatik devam eder. Kilitli kapıya tek istem vurmaz.
- **Limitleri kontrol et** — şimdi yeniden tara.
- Sağdaki durum alanı canlı durumu gösterir: `limits: all agents free` veya `claude-code: LIMITED until 09:22 (1h 05m remaining)`, kırmızı. Geri sayım önbellekten saniyede bir tikler; disk yalnızca okuma bayatladığında veya belirtilen sıfırlama saati geldiğinde dokunulur.

Sıfırlama saati ajanın kendi sözlerinden alınır. Ajan belirtmezse SAISENT "+5 saat" gibi bir yer tutucu uydurmak yerine "reset time not stated" yazar.

### Limitler ne zaman sıfırlanır

Ajan hiç sıfırlama saati belirtmezse SAISENT ajan başına kurala başvurur:

| Ajan | Kural | Anlamı |
|---|---|---|
| Freebuff | `daily 10:00` | her gün 10:00'da sıfırlanır |
| CodeNomad | `daily 03:00` | her gün 03:00'te sıfırlanır |
| Claude Code | `rolling 5h` | son gönderilen istemden 5 saat sonra |
| Antigravity | yalnızca ajanın sözleri | kural yok — ne belirtirse o, ya da hiçbir şey |

Bir kural ajanın belirttiği saati asla geçersiz kılmaz; ajan kendi kotasının otoritesidir. Herhangi bir kural `SAISENT.json` içinde `quota_plans` altında geçersiz kılınabilir, ör. `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Sonrakiler neden gitmiyor

Gönderim kesinlikle sıralıdır ve ilk gerçek hatada durur. Neden durum çubuğunda (`stopped: window not found: ...`), listedeki istem satırında ve günlükte görünür. Geri kalan `pending` kalır — hiçbir şey kaybolmaz.

İstemler arasında `gap_ms` duraklaması vardır (varsayılan 1500 ms) ve durum `Waiting N.Ns before next` gösterir. Bir istem gönderildi ama oturum kıpırdamadıysa **onaylanmamış** olarak işaretlenir ve kuyrukta kalır. "Gönderildi" yalnızca onaylanmış teslimatlara uygulanır.

## Etkinlik sensörü

"Sensör" sütunu "şu an yazabilir miyim"i yanıtlar.

- `busy` — oturum 20 saniyeden az önce deposuna yazdı (ajan hamlenin ortasında);
- `idle` — 20 saniyeden uzun sessizlik, giriş alanı boş.

Nereden geliyor:

| Ajan | Kaynak | Sensör |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + transkript | transkriptteki son yazma zamanı |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, `threads` tablosu | `turn_state` alanı |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | veritabanı ve `-wal` dosyasının mtime'ı |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | transkriptteki son yazma zamanı |

Canlılık ayrı bir kontrol, "diskteki dosya taze" değil:

- **Claude Code** — `~/.claude/sessions/<pid>.json` içindeki PID canlı. Dosya oturum kapanışını atlatır; PID atlatmaz.
- **Freebuff** — `Freebuff.exe` çalışıyor. Veritabanı uygulamadan çıkıldıktan sonra bile thread'leri `open` tutar.
- **Antigravity** — `Antigravity.exe` çalışıyor **ve** konuşma taze. Tazelik tek başına yetmez: bu depo tüm konuşmaları sonsuza kadar tutar ve kapalı bir düzenleyici eskiden hiçbir tuşun ulaşamayacağı oturumlarla listeyi doldururdu.
- **CodeNomad** — veritabanı satırı arşivlenmemiş (`time_archived IS NULL`). Yalnızca şu an açık olanlar etkin.

## Teslimat adresi — "Adres" sütunu

Kenar çubuğu her oturumun tam olarak nasıl ele alınacağını gösterir:

| Değer | Yöntem | Güvenilirlik |
|---|---|---|
| `cdp:28194` | Ajanın hata ayıklayıcısı üzerinden yapıştırma | Kesin: alan önce ve sonra okunur, odak çalınmaz |
| `CTRL+3` | Ajan penceresinde sekme değiştirme | İyi, sekme numarası doğruysa |
| `blind` | Port yok, sekme numarası yok | İstem açık olan sohbete düşer |

Hiçbir pencere başlığı oturum adı içermez — `claude.exe` "Claude", Antigravity "Antigravity", Freebuff "Freebuff Desktop" diye adlandırılır. Bu yüzden pencereyle adresleme imkânsızdır ve `blind` tam olarak dediği şeyi ifade eder.

### CDP — güvenilir yol

Bir ajan `--remote-debugging-port` ile başlatıldıysa SAISENT hata ayıklayıcı üzerinden gönderir ve ne odağa ne de klavyeye dokunur. Bu şu anlama gelir:

- metin doğrudan giriş alanına yapıştırılır, "herhangi bir yere" değil;
- alan yapıştırmadan **önce** okunur: yarım yazılmış bir mesaj varsa gönderim, başkasının cümlesine eklemek yerine reddeder;
- alan yapıştırmadan **sonra** okunur: yerine oturmadıysa göndermeyiz.

Bir CDP reddi asla kör tuş vuruşlarına düşmez. Hassas aktarım az önce anın yanlış olduğunu söyledi; üstüne tuş vurmak, başkasının sohbetini mahvetmenin tam yoludur.

Port, ajanın `DevToolsActivePort` dosyasından okunur ama tek başına dosya yetmez — önceki bir başlatmadan kalır. SAISENT her yoklamadan önce porta gerçekten bağlanır.

Bir ajan için hata ayıklayıcıyı etkinleştirin (yeniden başlatma yaptığı şeyi öldürür — SAISENT bunu asla kendisi yapmaz):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Sayfa seçiciler (canlı DOM, 2026-08-05)

| Ajan | Port | Giriş alanı | İletişim listesi |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | yok | — | — |

Antigravity doğrulandı: 16 düğme, etiketler SAISENT'in gösterdiği proje adlarıyla birebir eşleşir (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — ada göre iletişim seçimi tam çalışır.

CodeNomad, OpenCode üzerinde Electron'dur; veri klasörü hâlâ `Plasticity` diye adlandırılır. DOM'daki oturum listesi yalnızca **şu an açık projenin** oturumlarını içerir; başka bir projeden oturum işlenmez ve SAISENT onu bulamaz — gönderim, açık sohbete körü körüne vurmak yerine reddeder.

`SAISENT.json` içinde herhangi bir profil anahtarını geçersiz kılın:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Oturumlar `~/.local/share/opencode/opencode.db` içindeki `session` tablosundan okunur: ad = `title`, proje = `directory`, arşivlenenler `time_archived` ile elenir, sensör `time_updated` ile. Oturum listesi düz sütunlar olan tek ajan — protobuf yok, ayrıştırma yok.

Canlılık — `CodeNomad.exe` çalışıyor. Sekme numarası yok: hata ayıklayıcı üzerinden ada göre adreslenir.

## Neden pencere başlığına göre değil

Her `claude.exe` penceresi "Claude" diye adlandırılır. Oturum adı başlıkta asla görünmez, bu yüzden pencereyle adresleme imkânsızdır — ad, proje ve PID diskten gelir; pencere yalnızca odak için gereklidir.

## Teslimat onayı

Chromium `WM_GETTEXT`'e yanıt vermez, bu yüzden Win32 üzerinden "yerine düştü mü"yü okumak imkânsızdır — bu ajanlar için eski read-back hep "onaylanmamış" döndürürdü. Bunun yerine SAISENT, etkinlik sensörünün izlediği aynı dosyanın hareket etmesini bekler. Hareket etti mi? Teslim edildi. Verilen süre içinde hareket etmedi mi? İstem gönderilmiş ama onaylanmamış olarak işaretlenir ve bu günlükte görünür. Bu hata sayılmaz: ajan hamlesine henüz başlamamış olabilir.

Gönderim ilk gerçek hatada durur (pencere bulunamadı, odak kayboldu, pano meşgul). Sonraki istemler kuyrukta kalır — kaybolmazlar ve kör gönderilmezler.

## Dışa & içe aktarma

**Dışa aktar** ve **İçe aktar** düğmeleri kuyrukları JSONL biçiminde kaydeder/yükler. Her satır oturum anahtarıyla kendi kendine yeterlidir. İçe aktarma veri kaybı olmadan birleştirir — yinelenen öğeler (aynı anahtar + metin) atlanır.

## Programın yanındaki dosyalar

| Dosya | İçerik |
|---|---|
| `SAISENT.json` | ayarlar: ajanlar, sekme numaraları, zaman aşımları, pencere geometrisi |
| `SAISENT_QUEUES.json` | oturum başına kuyruklar, yeniden başlatmayı atlatır |
| `SAISENT.log` | gönderim geçmişi günlüğü |

Kuyruk asla otomatik temizlenmez. Bir oturum listeden kaybolur ama gönderilmemiş öğeleri varsa kuyruk kalır: ajanlar yeniden başlatılır ve sessizce atılmış bir kuyruk, dosyadaki fazladan bir satırdan daha kötüdür.

## Gizli ayarlar

Program kapalıyken `SAISENT.json` dosyasını düzenleyin:

- `gap_ms` — tek yığındaki istemler arası duraklama (varsayılan 1500);
- `settle_ms` — sekme değişiminden ve yapıştırmadan sonra duraklama (400);
- `confirm_seconds` — teslimat onayını ne kadar bekleyeceği (10);
- `busy_seconds` — "busy/idle" sensörü eşiği (20);
- `freebuff_roots` — `.freebuff/desktop-v2.db` aranacak kökler, ör. `["V:\\___VAC\\__K\\__CODE"]`; arama derinliği 3 ile sınırlı;
- `submit` — gönderme tuşu, varsayılan `ENTER`.

## Sınırlamalar

- Sekmeler `Ctrl+1..Ctrl+9` ile adreslenir. Onuncu oturuma ulaşılamaz — `Ctrl+10` yoktur ve SAISENT tahmin etmek yerine reddeder.
- Sekme numarası başlatma sırasına dayalı bir tahmindir. İlk koşuyu **Kuru çalıştırma** ile, sonra önemsiz bir oturumda yapın.
- Antigravity konuşma adlarını metin olarak saklamaz: liste, meta verilerden çıkarılan çalışma klasörü adını gösterir.

## Testler

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
