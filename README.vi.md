# SAISENT 4.0

Một bảng điều khiển dán văn bản đã chuẩn bị sẵn vào các phiên của agent hiện đang chạy trên máy này.

Đặt văn bản vào hàng đợi của đúng phiên — SAISENT kích hoạt cửa sổ agent, chuyển đến tab của phiên đó, dán văn bản trong một thao tác và nhấn Enter.

## Bắt đầu nhanh

```
START_SAISENT.bat
```

Cần Python 3.11+ trên Windows.

## Cách sử dụng

1. **Agent.** Hàng trên cùng — hộp kiểm: Claude Code, Freebuff, Antigravity, CodeNomad.
   Tích vào một agent, các phiên của nó xuất hiện ở bảng bên trái.
2. **Phiên trực tiếp.** Bên trái là những gì thực sự chạy: tên phiên, số tab, cảm biến hoạt động và dự án. Danh sách không tự cập nhật trừ khi bạn bật "mỗi N giây" — mặc định chỉ cập nhật bằng nút **Làm mới**.
3. **Tab.** SAISENT đoán số tab theo thứ tự khởi động của các phiên. Sai? Gõ số thủ công vào `SAISENT.json`, khóa `tabs` (khóa phiên dạng `<agent>:<id>`, ví dụ `{ "tabs": { "claude-code:abc123": 3 } }`). `0` = không chuyển tab nào.
4. **Văn bản.** Viết (hoặc dán) ở dưới bên phải, nhấn **Vào hàng đợi** (hoặc Ctrl+Enter). **Tất cả vào hàng đợi** đặt cùng văn bản vào mọi phiên trực tiếp — thay thế macro cũ "CTRL+2, văn bản, CTRL+3, văn bản".
5. **Hàng đợi.** Thứ tự dòng = thứ tự gửi. Kéo dòng bằng chuột hoặc di chuyển bằng **Lên**/**Xuống**. Mỗi phiên có hàng đợi riêng. Nhấp đúp vào dòng (hoặc nút **Sửa**) để kéo prompt trở lại ô văn bản; **Lưu bản sửa** ghi đè tại chỗ, **Hủy** bỏ. Sửa prompt đã gửi sẽ đưa nó trở lại hàng đợi — văn bản trong dòng không còn khớp với những gì phiên nhận được. **Nhân bản** đặt một bản sao ngay bên dưới.
6. **Gửi.** **GỬI HÀNG ĐỢI NÀY** — chỉ phiên được chọn. **GỬI TẤT CẢ** — tất cả hàng đợi lần lượt. **Chạy thử** không gửi gì, chỉ hiển thị kế hoạch trong nhật ký. Gửi thật sẽ hỏi xác nhận trước và nêu tên các phiên.

## Hoàn tác gửi

Sau khi gửi, nút **Hoàn tác** xuất hiện trong 30 giây. Nó đưa prompt gửi cuối trở lại hàng đợi dạng `pending` — trừ khi phiên đã xử lý nó (giao hàng đã xác nhận).

## Lịch trình và giới hạn

Trong nhóm "Gửi":

- **Gửi lúc (HH:MM)** — trống nghĩa là "ngay bây giờ". Có giờ, hàng đợi chờ lần xuất hiện tiếp theo của giờ đó (hôm nay, hoặc ngày mai nếu đã qua) và hiển thị đếm ngược trên thanh trạng thái.
- **Chờ đặt lại giới hạn** — trước mỗi prompt, SAISENT đọc chính văn bản của agent. Nếu nó nói "limit reached", hàng đợi chờ và tự động tiếp tục khi giới hạn được nới. Không một prompt nào đập vào cánh cửa bị khóa.
- **Kiểm tra giới hạn** — quét lại ngay.
- Trường trạng thái bên phải hiển thị trạng thái trực tiếp: `limits: all agents free` hoặc `claude-code: LIMITED until 09:22 (1h 05m remaining)`, màu đỏ. Đếm ngược chạy mỗi giây từ bộ nhớ đệm; đĩa chỉ được chạm khi bản đọc cũ hoặc khi đến thời gian đặt lại đã nêu.

Thời gian đặt lại lấy từ chính lời nói của agent. Nếu agent không nêu, SAISENT viết "reset time not stated" thay vì bịa ra chỗ giữ chỗ như "+5 giờ".

### Khi nào giới hạn được đặt lại

Nếu agent không bao giờ nêu thời gian đặt lại, SAISENT dùng quy tắc cho từng agent:

| Agent | Quy tắc | Ý nghĩa |
|---|---|---|
| Freebuff | `daily 10:00` | đặt lại mỗi ngày lúc 10:00 |
| CodeNomad | `daily 03:00` | đặt lại mỗi ngày lúc 03:00 |
| Claude Code | `rolling 5h` | 5 giờ sau prompt gửi cuối cùng |
| Antigravity | chỉ lời agent | không quy tắc — nó nêu gì, thì là cái đó |

Quy tắc không bao giờ ghi đè thời gian agent đã nêu; agent là cơ quan có thẩm quyền về hạn mức của chính nó. Bất kỳ quy tắc nào cũng có thể ghi đè trong `SAISENT.json` dưới `quota_plans`, ví dụ `{ "quota_plans": { "claude-code": "rolling 3h" } }`.

## Vì sao các cái tiếp theo không gửi đi

Gửi là tuần tự nghiêm ngặt và dừng ở lỗi thật đầu tiên. Lý do hiện trên thanh trạng thái (`stopped: window not found: ...`), trên dòng prompt trong danh sách và trong nhật ký. Phần còn lại ở trạng thái `pending` — không mất gì.

Giữa các prompt có khoảng dừng `gap_ms` (mặc định 1500 ms) và trạng thái hiển thị `Waiting N.Ns before next`. Nếu prompt đã gửi nhưng phiên không nhúc nhích, nó bị đánh dấu **chưa xác nhận** và nằm lại trong hàng đợi. "Đã gửi" chỉ áp dụng cho giao hàng đã xác nhận.

## Cảm biến hoạt động

Cột "Cảm biến" trả lời "tôi có thể gõ ngay bây giờ không".

- `busy` — phiên đã ghi vào kho của nó dưới 20 giây trước (agent đang giữa lượt);
- `idle` — im lặng hơn 20 giây, trường nhập trống.

Lấy từ đâu:

| Agent | Nguồn | Cảm biến |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + bản ghi | thời gian ghi cuối trong bản ghi |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, bảng `threads` | trường `turn_state` |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime của DB và `-wal` của nó |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | thời gian ghi cuối trong bản ghi |

Sự sống là một kiểm tra riêng, không phải "tệp trên đĩa còn mới":

- **Claude Code** — PID từ `~/.claude/sessions/<pid>.json` còn sống. Tệp sống sót sau khi đóng phiên; PID thì không.
- **Freebuff** — `Freebuff.exe` đang chạy. DB giữ các thread `open` ngay cả sau khi thoát ứng dụng.
- **Antigravity** — `Antigravity.exe` đang chạy **và** cuộc trò chuyện còn mới. Chỉ mới không đủ: kho này giữ mọi cuộc trò chuyện vĩnh viễn, và một trình soạn thảo bị đóng từng làm đầy danh sách bằng các phiên mà không phím nào với tới.
- **CodeNomad** — dòng DB không bị lưu trữ (`time_archived IS NULL`). Chỉ những cái đang mở hiện tại là hoạt động.

## Địa chỉ giao hàng — cột "Địa chỉ"

Thanh bên cho biết chính xác mỗi phiên sẽ bị xử lý ra sao:

| Giá trị | Phương thức | Độ tin cậy |
|---|---|---|
| `cdp:28194` | Dán qua trình gỡ lỗi của agent | Chính xác: đọc trường trước và sau, không đánh cắp tiêu điểm |
| `CTRL+3` | Chuyển tab trong cửa sổ agent | Tốt, nếu số tab đúng |
| `blind` | Không cổng, không số tab | Prompt rơi vào cuộc trò chuyện đang mở |

Không tiêu đề cửa sổ nào chứa tên phiên — `claude.exe` tên là "Claude", Antigravity tên là "Antigravity", Freebuff tên là "Freebuff Desktop". Vì vậy định địa chỉ theo cửa sổ là bất khả, và `blind` có nghĩa đúng như lời nó nói.

### CDP — con đường đáng tin cậy

Nếu agent được khởi động với `--remote-debugging-port`, SAISENT gửi qua trình gỡ lỗi và không chạm tiêu điểm lẫn bàn phím. Điều đó có nghĩa:

- văn bản được dán trực tiếp vào trường nhập, không phải "bất kỳ đâu";
- trường được đọc **trước** khi dán: nếu có tin nhắn viết dở, lệnh gửi từ chối thay vì nối vào câu của người khác;
- trường được đọc **sau** khi dán: nếu nó không rơi vào, chúng tôi không gửi.

Sự từ chối của CDP không bao giờ quay lại gõ phím mù. Phương tiện chính xác vừa nói thời điểm không đúng; đập phím lên trên nó chính là cách làm hỏng cuộc trò chuyện của người khác.

Cổng được đọc từ `DevToolsActivePort` của agent, nhưng một mình tệp không đủ — nó sống sót qua lần khởi động trước. SAISENT thực sự kết nối cổng trước mỗi lần dò.

Bật trình gỡ lỗi cho agent (khởi động lại sẽ giết việc nó đang làm — SAISENT không bao giờ tự làm điều này):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Bộ chọn trang (DOM thật, 2026-08-05)

| Agent | Cổng | Trường nhập | Danh sách hộp thoại |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | không có | — | — |

Antigravity đã kiểm chứng: 16 nút, nhãn khớp chính xác với tên dự án SAISENT hiển thị (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — chọn hộp thoại theo tên hoạt động chính xác.

CodeNomad là Electron trên OpenCode; thư mục dữ liệu vẫn gọi là `Plasticity`. Danh sách phiên trong DOM chỉ chứa phiên của **dự án đang mở**; phiên từ dự án khác không được render và SAISENT sẽ không tìm thấy — lệnh gửi từ chối thay vì đập mù vào cuộc trò chuyện đang mở.

Ghi đè bất kỳ khóa hồ sơ nào trong `SAISENT.json`:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Phiên được đọc từ `~/.local/share/opencode/opencode.db`, bảng `session`: tên = `title`, dự án = `directory`, phiên lưu trữ lọc theo `time_archived`, cảm biến theo `time_updated`. Agent duy nhất ở đây có danh sách phiên là các cột đơn giản — không protobuf, không phân tích.

Sự sống — `CodeNomad.exe` đang chạy. Không có số tab: định địa chỉ theo tên qua trình gỡ lỗi.

## Vì sao không theo tiêu đề cửa sổ

Mọi cửa sổ `claude.exe` đều tên "Claude". Tên phiên không bao giờ xuất hiện trong tiêu đề, nên định địa chỉ theo cửa sổ là bất khả — tên, dự án và PID đến từ đĩa; cửa sổ chỉ cần cho tiêu điểm.

## Xác nhận giao hàng

Chromium không trả lời `WM_GETTEXT`, nên đọc "nó đã vào chưa" qua Win32 là bất khả — bản đọc lại cũ cho các agent này luôn trả "chưa xác nhận". Thay vào đó, SAISENT chờ tệp mà cảm biến hoạt động theo dõi nhúc nhích. Nhúc nhích? Đã giao. Không nhúc nhích trong thời gian cho phép? Prompt bị đánh dấu đã gửi nhưng chưa xác nhận, và điều này thấy được trong nhật ký. Điều này không được coi là lỗi: agent có thể chưa bắt đầu lượt.

Gửi dừng ở lỗi thật đầu tiên (không tìm thấy cửa sổ, mất tiêu điểm, khay nhớ tạm bận). Các prompt sau vẫn nằm trong hàng đợi — không mất và không bị gửi mù.

## Xuất & Nhập

Các nút **Xuất** và **Nhập** lưu/tải hàng đợi ở định dạng JSONL. Mỗi dòng tự chứa với khóa phiên của nó. Nhập hợp nhất không mất dữ liệu — các mục trùng (cùng khóa + văn bản) được bỏ qua.

## Các tệp bên cạnh chương trình

| Tệp | Nội dung |
|---|---|
| `SAISENT.json` | cài đặt: agent, số tab, thời gian chờ, kích thước cửa sổ |
| `SAISENT_QUEUES.json` | hàng đợi theo phiên, sống sót sau khởi động lại |
| `SAISENT.log` | nhật ký lịch sử gửi |

Hàng đợi không bao giờ tự dọn. Nếu phiên biến mất khỏi danh sách nhưng còn mục chưa gửi, hàng đợi vẫn ở lại: agent được khởi động lại, và một hàng đợi bị bỏ lặng lẽ còn tệ hơn một dòng thừa trong tệp.

## Cài đặt ẩn

Sửa `SAISENT.json` khi chương trình đã đóng:

- `gap_ms` — dừng giữa các prompt trong một lô (mặc định 1500);
- `settle_ms` — dừng sau khi chuyển tab và sau khi dán (400);
- `confirm_seconds` — chờ xác nhận giao hàng bao lâu (10);
- `busy_seconds` — ngưỡng cảm biến "busy/idle" (20);
- `freebuff_roots` — gốc để tìm `.freebuff/desktop-v2.db`, ví dụ `["V:\\___VAC\\__K\\__CODE"]`; độ sâu tìm giới hạn ở 3;
- `submit` — phím để gửi, mặc định `ENTER`.

## Giới hạn

- Tab được định địa chỉ qua `Ctrl+1..Ctrl+9`. Phiên thứ mười không thể với tới — `Ctrl+10` không tồn tại, và SAISENT từ chối thay vì đoán.
- Số tab là dự đoán dựa trên thứ tự khởi động. Hãy chạy lần đầu với **Chạy thử**, sau đó trên một phiên không quan trọng.
- Antigravity không lưu tên cuộc trò chuyện dưới dạng văn bản: danh sách hiển thị tên thư mục làm việc trích từ siêu dữ liệu.

## Kiểm thử

```
python -m pytest -q
```

<!-- source-digest: README.md sha256:8396e932d633848051a0136a6389cad9784a44e2a74b88b1cdb693c9505b6d2b -->
