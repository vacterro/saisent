# SAISENT 4.0

A control panel that pastes pre-written text into the agent sessions
currently running on this machine.

Queue text for the right session — SAISENT activates the agent window,
switches to that session's tab, pastes the text in one operation, and
presses Enter.

## Quick Start

```
START_SAISENT.bat
```

Requires Python 3.11+ on Windows.

## How to Use

1. **Agents.** Top row — checkboxes: Claude Code, Freebuff, Antigravity,
   CodeNomad. Check an agent and its sessions appear in the left panel.
2. **Live sessions.** Left panel shows what is actually running: session
   name, tab number, activity sensor, and project. The list does not
   auto-refresh unless you enable "every N s" — by default, refresh is
   manual via the **Refresh** button.
3. **Tab.** SAISENT guesses the tab number from session launch order.
   Wrong? Set the correct number and press **Remember**; it saves for
   that session. `0` = don't switch tabs at all.
4. **Text.** Type (or paste) in the bottom-right box, press **Queue**
   (or Ctrl+Enter). **Queue All** puts the same text into every live
   session — replacing the old macro of "CTRL+2, text, CTRL+3, text".
5. **Queue.** Row order = send order. Drag rows with the mouse or use
   **Up**/**Down** buttons. Every session has its own queue.
   Double-click a row (or press **Edit**) to pull a prompt back into the
   text box; **Save Edit** rewrites it in place, **Cancel** discards.
   Editing an already-sent prompt returns it to the queue — the text in
   the row no longer matches what the session received. **Duplicate**
   places a copy right below.
6. **Send.** **Send This Queue** — selected session only. **Send All
   Queues** — all queues in order. **Dry Run** sends nothing, just
   shows the plan in the log. Real sends ask for confirmation first and
   name the sessions.

## Undo Send

After sending, an **Undo** button appears for 30 seconds. It pops the
last sent prompt back into the queue as pending — unless the session
has already processed it (confirmed delivery).

## Scheduling & Limits

In the "Send" group:

- **Send at (HH:MM)** — empty means "now". With a time, the queue waits
  for the next occurrence of that time (today, or tomorrow if past) and
  shows a countdown in the status bar.
- **Wait for rate limit reset** — before each prompt, SAISENT reads the
  agent's own text. If it says "limit reached", the queue waits and
  resumes automatically when the limit clears. Not a single prompt hits
  a locked door.
- **Check Limits** — re-scan right now.
- Status field on the right shows live state: `limits: all agents free`
  or `claude-code: LIMITED until 09:22 (1h 05m remaining)`, in red. The
  countdown ticks once per second from the cache; disk is only touched
  when the reading is stale or the named reset time arrives.

Reset time is taken from the agent's own words. If the agent does not
state one, SAISENT writes "reset time not stated" rather than inventing
a placeholder like "+5 hours".

## Why The Next Ones Don't Send

Sending is strictly sequential and stops on the first real error. The
reason appears in the status bar (`stopped: window not found: ...`), on
the prompt row in the list, and in the log. The rest stay `pending` —
they are not lost.

Between prompts there is a `gap_ms` pause (default 1500 ms), and the
status shows `Waiting N.Ns before next`. If a prompt was sent but the
session has not moved, it is marked **unconfirmed** and stays in the
queue. "Sent" is only applied to confirmed deliveries.

## Activity Sensor

The "Sensor" column answers "can I type right now".

- `busy` — the session wrote to its store less than 20 seconds ago
  (the agent is mid-turn);
- `idle` — silence longer than 20 seconds, the input field is free.

Where it comes from:

| Agent | Source | Sensor |
|---|---|---|
| Claude Code | `~/.claude/sessions/<pid>.json` + transcript | last write time in transcript |
| Freebuff | `<project>/.freebuff/desktop-v2.db`, `threads` table | `turn_state` field |
| Antigravity | `~/.gemini/antigravity/conversations/*.db` | mtime of DB and its `-wal` |
| CodeNomad | `~/.local/share/opencode/opencode.db` SQLite | last write time in transcript |

Liveness is a separate check, not "the file on disk is fresh":

- **Claude Code** — PID from `~/.claude/sessions/<pid>.json` is alive.
  The file survives session close; the PID does not.
- **Freebuff** — `Freebuff.exe` is running. The DB keeps threads `open`
  even after the app exits.
- **Antigravity** — `Antigravity.exe` is running **and** the
  conversation is fresh. Freshness alone isn't enough: this store holds
  all conversations forever, and a closed editor used to fill the list
  with sessions no keystroke could reach.
- **CodeNomad** — DB row is unarchived (`time_archived IS NULL`).
  Active sessions are only the ones currently open.

## Delivery Address — "Address" Column

The sidebar shows exactly how each session will be hit:

| Value | Method | Reliability |
|---|---|---|
| `cdp:28194` | Paste via agent's debugger | Exact: field read before and after, focus not stolen |
| `CTRL+3` | Tab switch in agent window | Good, if tab number is correct |
| `blind` | No port, no tab number | The prompt lands in whichever chat is open |

No window title contains a session name — `claude.exe` is called
"Claude", Antigravity is "Antigravity", Freebuff is "Freebuff Desktop".
Addressing by window is therefore impossible, and `blind` means exactly
what it says.

### CDP — the reliable path

If an agent was launched with `--remote-debugging-port`, SAISENT sends
through the debugger and touches neither focus nor keyboard. This means:

- text is pasted directly into the input field, not "wherever";
- the field is read **before** paste: if a half-written message is
  sitting there, the send refuses rather than appending to someone
  else's sentence;
- the field is read **after** paste: if it did not land, we do not send.

A CDP refusal never falls back to blind keystrokes. The precise
transport just said the moment is wrong; hammering keystrokes over that
is exactly how you trash someone else's chat.

The port is read from the agent's `DevToolsActivePort`, but a file
alone is not enough — it survives a previous launch. SAISENT actually
connects to the port before every probe.

Enable the debugger for an agent (a restart kills what it's doing —
SAISENT never does this itself):

```bash
"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" --remote-debugging-port=22998
```

### Page Selectors (live DOM, 2026-08-05)

| Agent | Port | Input Field | Dialog List |
|---|---|---|---|
| Antigravity | `%APPDATA%\Antigravity\DevToolsActivePort` | `[aria-label="Message input"]` | `button[class*="headerbtn"]` |
| CodeNomad | `%APPDATA%\Plasticity\DevToolsActivePort` | `textarea.prompt-input` | `span.session-item-title` |
| Claude Code | `%APPDATA%\Claude\DevToolsActivePort` | — | — |
| Freebuff | none | — | — |

Antigravity verified: 16 buttons, labels exactly match the project names
SAISENT shows (`_SAIPEN`, `_FastPrompter`, `SAISENT`, …) — dialog
selection by name works precisely.

CodeNomad is Electron on top of OpenCode; the data folder is still
called `Plasticity`. The session list in the DOM only contains sessions
of the **currently open project**; a session from another project is
not rendered, and SAISENT will not find it — the send refuses rather
than blindly hitting the open chat.

Override any profile key in `SAISENT.json`:

```json
{ "cdp_profiles": { "codenomad": { "dialog_selector": ".session-list-item" } } }
```

## CodeNomad

Sessions are read from `~/.local/share/opencode/opencode.db`, `session`
table: name = `title`, project = `directory`, archived filtered by
`time_archived`, sensor by `time_updated`. The only agent here whose
session list is plain columns, no protobuf and no parsing.

Liveness — `CodeNomad.exe` is running. No tab number: addressed by name
through the debugger.

## Why Not By Window Title

Every `claude.exe` window is called "Claude". The session name never
appears in the title, so addressing by window is impossible — the name,
project, and PID come from disk; the window is only needed for focus.

## Delivery Confirmation

Chromium does not answer `WM_GETTEXT`, so reading "did it land" through
Win32 is impossible — the old read-back for these agents always
returned "unconfirmed". Instead, SAISENT waits for the same file that
the activity sensor watches to move. Moved? Delivered. Has not moved
within the allotted time? The prompt is marked as sent but unconfirmed,
and this is visible in the log. This is not considered an error: the
agent may simply not have started its turn yet.

Sending stops on the first real error (window not found, focus lost,
clipboard busy). Subsequent prompts stay in the queue — they are not
lost and are not sent blind.

## Export & Import

**Export** and **Import** buttons save/load queues in JSONL format.
Each line is self-contained with its session key. Import merges without
data loss — duplicate items (same key + text) are skipped.

## Files Next to the Program

| File | Contents |
|---|---|
| `SAISENT.json` | settings: agents, tab numbers, timeouts, window geometry |
| `SAISENT_QUEUES.json` | per-session queues, survive restart |
| `SAISENT.log` | send history log |

The queue is never cleaned automatically. If a session disappears from
the list but has unsent items, the queue stays: agents get restarted,
and a silently dropped queue is worse than an extra line in a file.

## Hidden Settings

Edit `SAISENT.json` while the program is closed:

- `gap_ms` — pause between prompts within one batch (default 1500);
- `settle_ms` — pause after tab switch and after paste (400);
- `confirm_seconds` — how long to wait for delivery confirmation (10);
- `busy_seconds` — sensor "busy/idle" threshold (20);
- `freebuff_roots` — roots where to search for `.freebuff/desktop-v2.db`,
  e.g. `["V:\\___VAC\\__K\\__CODE"]`; search depth limited to 3;
- `submit` — key to press for send, default `ENTER`.

## Limitations

- Tabs are addressed via `Ctrl+1..Ctrl+9`. A tenth session is
  unreachable — `Ctrl+10` does not exist, and SAISENT refuses rather
  than guessing.
- The tab number is a guess based on launch order. Do your first run
  with **Dry Run**, then on an unimportant session.
- Antigravity does not store conversation names as text: the list shows
  the workspace folder name extracted from metadata.

## Tests

```
python -m pytest -q
```
