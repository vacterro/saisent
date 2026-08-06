"""Enumerate the agent sessions that are alive on this machine right now.

Every supported agent already records what it is doing on disk. Claude Code
desktop writes one small JSON per running session; Freebuff keeps a per-project
SQLite database with a `threads` table; Antigravity keeps one database per
conversation. None of them puts the session name in the window title -- every
`claude.exe` window is called "Claude" -- so the window is useless as an
identity and the files are the only source that carries a name.

A provider's job is therefore narrow: read those files, drop what is dead, and
return `Session` records. It never touches a window, never sends anything, and
takes its roots and its clock as arguments so a test can point it at fixtures.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

# A session that wrote something this recently is mid-turn. Anything quieter is
# waiting for input -- which is the only moment it is safe to type into it.
DEFAULT_BUSY_SECONDS = 20.0

# Antigravity keeps every conversation it ever had. Only recent ones are
# plausibly open in the running editor.
DEFAULT_ANTIGRAVITY_MAX_AGE_HOURS = 12.0

STATE_BUSY = "busy"
STATE_IDLE = "idle"


@dataclass
class Session:
    """One running agent session, as the sidebar shows it."""

    key: str
    agent: str
    name: str
    project: str
    session_id: str
    started: float
    last_active: float
    state: str = STATE_IDLE
    pid: int | None = None
    detail: str = ""
    # Which tab the session occupies in its agent's window. Discovery can only
    # guess (position in start order); the user corrects it and the GUI stores
    # the correction, because guessing wrong types into somebody else's chat.
    tab_hint: int | None = None
    last_reply: str = ""

    @property
    def project_name(self) -> str:
        stem = Path(self.project).name if self.project else ""
        return stem or self.project

    def age_seconds(self, now: float | None = None) -> float:
        return max(0.0, (time.time() if now is None else now) - self.last_active)


def pid_alive(pid: int) -> bool:
    """True when a process with this PID is currently running.

    PROCESS_QUERY_LIMITED_INFORMATION is the least privilege that answers the
    question, and it works across integrity levels -- which matters here,
    because the agent may run elevated while SAISENT does not.
    """
    if not pid or pid < 0:
        return False
    if os.name != "nt":  # pragma: no cover - the app is Windows-only
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        # STILL_ACTIVE (259) means running. Without this check a process that
        # exited but is still held open by a handle would read as alive.
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return code.value == 259
        return True
    finally:
        kernel32.CloseHandle(handle)


def process_running(exe_name: str) -> bool:
    """True when a process with this image name is running right now.

    File timestamps say a session *existed*, never that it is open. Antigravity
    keeps every conversation it ever had, so without this check a closed editor
    still filled the sidebar with sessions nothing could be delivered to.
    """
    if not exe_name or os.name != "nt":  # pragma: no cover - Windows-only path
        return False
    kernel32 = ctypes.windll.kernel32
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_uint32),
            ("cntUsage", ctypes.c_uint32),
            ("th32ProcessID", ctypes.c_uint32),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", ctypes.c_uint32),
            ("cntThreads", ctypes.c_uint32),
            ("th32ParentProcessID", ctypes.c_uint32),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_uint32),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID:
        return False
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        wanted = exe_name.lower()
        if not kernel32.Process32FirstW(ctypes.c_void_p(snapshot), ctypes.byref(entry)):
            return False
        while True:
            if entry.szExeFile.lower() == wanted:
                return True
            if not kernel32.Process32NextW(
                ctypes.c_void_p(snapshot), ctypes.byref(entry)
            ):
                return False
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(snapshot))


def _state_for(last_active: float, now: float, busy_seconds: float) -> str:
    return STATE_BUSY if (now - last_active) < busy_seconds else STATE_IDLE


def project_slug(path: str) -> str:
    """Claude Code's on-disk name for a project directory.

    `V:\\___VAC\\__K\\__CODE\\_PY\\_SAISENT` becomes
    `V-----VAC---K---CODE--PY--SAISENT`: every character outside `[A-Za-z0-9]`
    becomes one dash, runs included.
    """
    return re.sub(r"[^A-Za-z0-9]", "-", path or "")


class ClaudeCodeProvider:
    """Claude Code desktop, read from `~/.claude/sessions/<pid>.json`.

    Each file is written when a session starts and carries `sessionId`, `cwd`
    and the derived `name` the app shows in its tab. The file is NOT removed
    when the session ends, so liveness is the PID check, never the file's
    existence.
    """

    agent = "claude-code"

    def __init__(
        self,
        sessions_dir: str | os.PathLike | None = None,
        projects_dir: str | os.PathLike | None = None,
        alive: Callable[[int], bool] = pid_alive,
        busy_seconds: float = DEFAULT_BUSY_SECONDS,
    ) -> None:
        home = Path.home()
        self.sessions_dir = Path(sessions_dir or home / ".claude" / "sessions")
        self.projects_dir = Path(projects_dir or home / ".claude" / "projects")
        self.alive = alive
        self.busy_seconds = float(busy_seconds)

    def transcript_mtime(self, cwd: str, session_id: str) -> float:
        """When this session last wrote a turn, or 0.0 when unknown."""
        if not session_id:
            return 0.0
        direct = self.projects_dir / project_slug(cwd) / f"{session_id}.jsonl"
        try:
            return direct.stat().st_mtime
        except OSError:
            pass
        # The slug rule can change under us; a targeted glob still finds the
        # transcript, and only runs when the direct path missed.
        try:
            for found in self.projects_dir.glob(f"*/{session_id}.jsonl"):
                try:
                    return found.stat().st_mtime
                except OSError:
                    continue
        except OSError:
            pass
        return 0.0

    def discover(self, now: float | None = None) -> list[Session]:
        now = time.time() if now is None else now
        sessions: list[Session] = []
        try:
            files = sorted(self.sessions_dir.glob("*.json"))
        except OSError:
            return sessions
        for path in files:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(raw, dict):
                continue
            pid = raw.get("pid")
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                continue
            if not self.alive(pid):
                continue
            session_id = str(raw.get("sessionId") or "")
            cwd = str(raw.get("cwd") or "")
            started = float(raw.get("startedAt") or 0) / 1000.0
            last_active = self.transcript_mtime(cwd, session_id) or started
            name = str(raw.get("name") or "").strip()
            if not name:
                name = session_id[:8] or f"pid {pid}"
            sessions.append(
                Session(
                    key=f"{self.agent}:{session_id or pid}",
                    agent=self.agent,
                    name=name,
                    project=cwd,
                    session_id=session_id,
                    started=started,
                    last_active=last_active,
                    state=_state_for(last_active, now, self.busy_seconds),
                    pid=pid,
                    detail=str(raw.get("entrypoint") or ""),
                )
            )
        sessions.sort(key=lambda s: (s.started, s.key))
        # No tab hint, deliberately. Measured on 2026-08-06: Ctrl+<digit> does
        # nothing in Claude Code -- a send aimed at tab 5 landed in whatever
        # session was focused -- and Ctrl+N opens a NEW blank one. Its sidebar
        # is a project tree, not a tab strip, so there is no keystroke that
        # selects a session by position. A number here was pure fiction, and
        # the sidebar showing `CTRL+3` promised addressing nobody had.
        for session in sessions:
            session.tab_hint = None
            session.last_reply = self.extract_last_reply(session)
        return sessions

    def extract_last_reply(self, session: Session) -> str:
        text = self.tail_transcript(session, limit=16000)
        if not text:
            return ""
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "assistant" and "message" in data:
                    content = data["message"].get("content", [])
                    if content and isinstance(content, list) and "text" in content[0]:
                        return content[0]["text"]
            except Exception:
                pass
        return ""

    def tail_transcript(self, session: Session, limit: int = 4000) -> str:
        if not session.session_id:
            return ""
        direct = self.projects_dir / project_slug(session.project) / f"{session.session_id}.jsonl"
        paths = [direct]
        try:
            # The slug rule can change under us; a targeted glob still finds the
            # transcript, and only runs when the direct path missed.
            if not direct.exists():
                paths.extend(self.projects_dir.glob(f"*/{session.session_id}.jsonl"))
        except OSError:
            pass
        for p in paths:
            try:
                with open(p, "rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    f.seek(max(0, size - limit * 2))
                    text = f.read().decode("utf-8", "ignore")
                    return text[-limit:] if len(text) > limit else text
            except OSError:
                continue
        return ""

    def recent_transcripts(self, max_age_hours: float = 6.0, limit_per_file: int = 4000) -> str:
        cutoff = time.time() - max_age_hours * 3600.0
        results = []
        try:
            for p in self.projects_dir.glob("*/*.jsonl"):
                try:
                    if p.stat().st_mtime < cutoff:
                        continue
                    with open(p, "rb") as f:
                        f.seek(0, 2)
                        size = f.tell()
                        f.seek(max(0, size - limit_per_file * 2))
                        text = f.read().decode("utf-8", "ignore")
                        results.append((p.stat().st_mtime, text[-limit_per_file:] if len(text) > limit_per_file else text))
                except OSError:
                    continue
        except OSError:
            pass
        results.sort(key=lambda x: x[0])
        return "\n".join(r[1] for r in results[-20:])



class FreebuffProvider:
    """Freebuff desktop, read from each project's `.freebuff/desktop-v2.db`.

    The `threads` table is the session list: `title` is the name shown in the
    tab, `status` is open/closed, and `turn_state` is the agent's own idle/busy
    flag -- a real sensor rather than an inference from file timestamps.
    """

    agent = "freebuff"
    exe_name = "Freebuff.exe"
    db_relative = Path(".freebuff") / "desktop-v2.db"

    def __init__(
        self,
        roots: Sequence[str | os.PathLike] = (),
        busy_seconds: float = DEFAULT_BUSY_SECONDS,
        max_depth: int = 3,
        running: Callable[[str], bool] | None = None,
    ) -> None:
        self.roots = [Path(root) for root in roots]
        self.busy_seconds = float(busy_seconds)
        self.max_depth = int(max_depth)
        # `None` keeps the old behaviour for callers that only have fixtures;
        # the app passes the real check so a closed desktop lists nothing.
        self.running = running

    def databases(self) -> list[Path]:
        """Every `.freebuff/desktop-v2.db` under the configured roots.

        Bounded by `max_depth` on purpose: these roots are source trees, and an
        unbounded walk over one of those is how a "refresh" button becomes a
        two-second freeze.
        """
        found: list[Path] = []
        for root in self.roots:
            direct = root / self.db_relative
            if direct.exists():
                found.append(direct)
            if self.max_depth <= 0:
                continue
            for depth in range(1, self.max_depth + 1):
                pattern = "/".join(["*"] * depth) + "/" + self.db_relative.as_posix()
                try:
                    found.extend(path for path in root.glob(pattern) if path.is_file())
                except OSError:
                    continue
        unique: dict[str, Path] = {}
        for path in found:
            unique.setdefault(str(path).lower(), path)
        return list(unique.values())

    def _read(self, db_path: Path, now: float) -> list[Session]:
        sessions: list[Session] = []
        try:
            # Read-only and immutable-free: the app holds the write lock and a
            # WAL, so a normal connection would either block or see a stale
            # snapshot. `mode=ro` keeps us out of its way.
            connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        except sqlite3.Error:
            return sessions
        try:
            rows = connection.execute(
                "SELECT id, title, status, turn_state, project_path, updated_at,"
                " created_at FROM threads"
            ).fetchall()
        except sqlite3.Error:
            return sessions
        finally:
            connection.close()
        for thread_id, title, status, turn_state, project_path, updated, created in rows:
            if (status or "").lower() != "open":
                continue
            last_active = float(updated or 0) / 1000.0
            state = STATE_BUSY if (turn_state or "") == "running" else STATE_IDLE
            sessions.append(
                Session(
                    key=f"{self.agent}:{thread_id}",
                    agent=self.agent,
                    name=(title or "").strip() or str(thread_id)[:8],
                    project=project_path or str(db_path.parent.parent),
                    session_id=str(thread_id),
                    started=float(created or 0) / 1000.0,
                    last_active=last_active,
                    state=state,
                    detail=turn_state or "",
                )
            )
        return sessions

    def discover(self, now: float | None = None) -> list[Session]:
        now = time.time() if now is None else now
        sessions: list[Session] = []
        if self.running is not None and not self.running(self.exe_name):
            # Threads stay `open` in the database after the desktop quits.
            return sessions
        for db_path in self.databases():
            sessions.extend(self._read(db_path, now))
        sessions.sort(key=lambda s: (s.started, s.key))
        for index, session in enumerate(sessions, start=1):
            session.tab_hint = index
            session.last_reply = self.extract_last_reply(session)
        return sessions

    def extract_last_reply(self, session: Session) -> str:
        db_path = Path(session.project) / self.db_relative
        try:
            connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
            rows = connection.execute(
                "SELECT role, content FROM messages WHERE thread_id = ? ORDER BY id DESC LIMIT 50",
                (session.session_id,)
            ).fetchall()
            connection.close()
            for role, content in rows:
                if role == "assistant":
                    return content or ""
        except Exception:
            pass
        return ""

    def tail_transcript(self, session: Session, limit: int = 4000) -> str:
        db_path = Path(session.project) / self.db_relative
        try:
            connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
            rows = connection.execute(
                "SELECT role, content FROM messages WHERE thread_id = ? ORDER BY id DESC LIMIT 50",
                (session.session_id,)
            ).fetchall()
            connection.close()
            text = "\n".join(r[1] or "" for r in reversed(rows))
            return text[-limit:] if len(text) > limit else text
        except Exception:
            return ""

    def recent_transcripts(self, max_age_hours: float = 6.0, limit_per_db: int = 4000) -> str:
        cutoff = time.time() - max_age_hours * 3600.0
        results = []
        for db_path in self.databases():
            try:
                if db_path.stat().st_mtime < cutoff:
                    continue
                connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
                rows = connection.execute(
                    "SELECT role, content FROM messages ORDER BY id DESC LIMIT 200"
                ).fetchall()
                connection.close()
                text = "\n".join(r[1] or "" for r in reversed(rows))
                if text:
                    results.append((db_path.stat().st_mtime, text[-limit_per_db:] if len(text) > limit_per_db else text))
            except Exception:
                continue
        results.sort(key=lambda x: x[0])
        return "\n".join(r[1] for r in results[-20:])



class AntigravityProvider:
    """Antigravity, read from `~/.gemini/antigravity/conversations/*.db`.

    One database per conversation, all protobuf blobs inside, so there is no
    title column to read. The workspace URI is recoverable from the metadata
    blob as plain text, and that is what the editor shows anyway.

    Liveness is two conditions, not one. Recency alone was wrong: this store
    keeps every conversation forever, so a closed editor still produced a
    sidebar full of sessions that no keystroke could ever reach. The editor's
    process has to be running as well.
    """

    agent = "antigravity"
    exe_name = "Antigravity.exe"
    _workspace_re = re.compile(rb"file:///([A-Za-z]%?3?[Aa]?[:/][^\x00-\x1f\"]{2,200})")

    def __init__(
        self,
        conversations_dir: str | os.PathLike | None = None,
        busy_seconds: float = DEFAULT_BUSY_SECONDS,
        max_age_hours: float = DEFAULT_ANTIGRAVITY_MAX_AGE_HOURS,
        running: Callable[[str], bool] = process_running,
    ) -> None:
        home = Path.home()
        self.conversations_dir = Path(
            conversations_dir or home / ".gemini" / "antigravity" / "conversations"
        )
        self.busy_seconds = float(busy_seconds)
        self.max_age_hours = float(max_age_hours)
        self.running = running
        # Reading a metadata blob costs a SQLite open; the workspace never
        # changes for a conversation, so one read per file is enough.
        self._workspace_cache: dict[str, str] = {}

    def _last_active(self, db_path: Path) -> float:
        newest = 0.0
        for suffix in ("", "-wal", "-shm"):
            sidecar = db_path.with_name(db_path.name + suffix)
            try:
                newest = max(newest, sidecar.stat().st_mtime)
            except OSError:
                continue
        return newest

    def workspace(self, db_path: Path) -> str:
        cached = self._workspace_cache.get(str(db_path))
        if cached is not None:
            return cached
        workspace = ""
        try:
            connection = sqlite3.connect(
                f"file:{db_path.as_posix()}?mode=ro", uri=True
            )
        except sqlite3.Error:
            self._workspace_cache[str(db_path)] = ""
            return ""
        try:
            row = connection.execute(
                "SELECT data FROM trajectory_metadata_blob LIMIT 1"
            ).fetchone()
            blob = row[0] if row and isinstance(row[0], (bytes, bytearray)) else b""
            match = self._workspace_re.search(bytes(blob))
            if match:
                raw = match.group(1).decode("utf-8", "ignore")
                workspace = raw.replace("%3A", ":").replace("%3a", ":").rstrip("/")
        except sqlite3.Error:
            workspace = ""
        finally:
            connection.close()
        self._workspace_cache[str(db_path)] = workspace
        return workspace

    def discover(self, now: float | None = None) -> list[Session]:
        now = time.time() if now is None else now
        cutoff = now - self.max_age_hours * 3600.0
        sessions: list[Session] = []
        try:
            files = sorted(self.conversations_dir.glob("*.db"))
        except OSError:
            return sessions
        if not self.running(self.exe_name):
            # The editor is closed. Every conversation on disk is history.
            return sessions
        for db_path in files:
            last_active = self._last_active(db_path)
            if last_active < cutoff:
                continue
            workspace = self.workspace(db_path)
            conversation_id = db_path.stem
            name = Path(workspace).name if workspace else conversation_id[:8]
            sessions.append(
                Session(
                    key=f"{self.agent}:{conversation_id}",
                    agent=self.agent,
                    name=name or conversation_id[:8],
                    project=workspace,
                    session_id=conversation_id,
                    started=last_active,
                    last_active=last_active,
                    state=_state_for(last_active, now, self.busy_seconds),
                    detail="",
                )
            )
        sessions.sort(key=lambda s: (-s.last_active, s.key))
        sessions = self._collapse_by_workspace(sessions)
        for session in sessions:
            session.tab_hint = None
            session.last_reply = self.extract_last_reply(session)
        return sessions

    @staticmethod
    def _collapse_by_workspace(sessions: list[Session]) -> list[Session]:
        """One row per workspace: the most recently active conversation.

        The page can only switch between PROJECTS -- its list is a row of
        project buttons, and every conversation inside one workspace resolves
        to the same button. Listing them separately produced three identical
        `_SAIPEN` rows in the sidebar that all delivered to the same place,
        so the extra rows were not choices, they were decoys.

        Input must already be sorted newest-first; the first hit per workspace
        wins.
        """
        collapsed: list[Session] = []
        seen: set[str] = set()
        for session in sessions:
            slot = (session.project or session.name).lower()
            if slot in seen:
                continue
            seen.add(slot)
            collapsed.append(session)
        return collapsed

    def extract_last_reply(self, session: Session) -> str:
        p = Path.home() / ".gemini" / "antigravity" / "brain" / session.session_id / ".system_generated" / "logs" / "transcript.jsonl"
        try:
            with open(p, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 16000))
                text = f.read().decode("utf-8", "ignore")
                for line in reversed(text.splitlines()):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("type") == "PLANNER_RESPONSE":
                            return data.get("content", "")
                    except Exception:
                        pass
        except OSError:
            pass
        return ""

    def tail_transcript(self, session: Session, limit: int = 4000) -> str:
        # Antigravity limits check requires recent_transcripts over all brains.
        # This function provides a stub, recent_transcripts handles it globally.
        return ""

    def recent_transcripts(self, max_age_hours: float = 6.0, limit_per_file: int = 4000) -> str:
        cutoff = time.time() - max_age_hours * 3600.0
        results = []
        try:
            logs_dir = Path.home() / ".gemini" / "antigravity" / "brain"
            for p in logs_dir.glob("*/.system_generated/logs/transcript.jsonl"):
                try:
                    if p.stat().st_mtime < cutoff:
                        continue
                    with open(p, "rb") as f:
                        f.seek(0, 2)
                        size = f.tell()
                        f.seek(max(0, size - limit_per_file * 2))
                        text = f.read().decode("utf-8", "ignore")
                        results.append((p.stat().st_mtime, text[-limit_per_file:] if len(text) > limit_per_file else text))
                except OSError:
                    continue
        except OSError:
            pass
        results.sort(key=lambda x: x[0])
        return "\n".join(r[1] for r in results[-20:])


class CodeNomadProvider:
    """CodeNomad, read from OpenCode's store at
    `~/.local/share/opencode/opencode.db`.

    CodeNomad is an Electron shell over OpenCode, so the sessions live in
    OpenCode's own database: `session.title` is the name shown in the list,
    `session.directory` the project, `time_archived` marks the closed ones.
    Nothing needs parsing -- it is the one agent here that stores its session
    list as ordinary columns.
    """

    agent = "codenomad"
    exe_name = "CodeNomad.exe"

    def __init__(
        self,
        db_path: str | os.PathLike | None = None,
        busy_seconds: float = DEFAULT_BUSY_SECONDS,
        max_age_hours: float = 24.0,
        running: Callable[[str], bool] = process_running,
    ) -> None:
        self.db_path = Path(
            db_path or Path.home() / ".local" / "share" / "opencode" / "opencode.db"
        )
        self.busy_seconds = float(busy_seconds)
        self.max_age_hours = float(max_age_hours)
        self.running = running

    def discover(self, now: float | None = None) -> list[Session]:
        now = time.time() if now is None else now
        sessions: list[Session] = []
        if not self.db_path.exists() or not self.running(self.exe_name):
            return sessions
        cutoff_ms = (now - self.max_age_hours * 3600.0) * 1000.0
        try:
            connection = sqlite3.connect(
                f"file:{self.db_path.as_posix()}?mode=ro", uri=True
            )
        except sqlite3.Error:
            return sessions
        try:
            rows = connection.execute(
                "SELECT id, title, directory, agent, time_created, time_updated,"
                " time_archived FROM session WHERE time_archived IS NULL"
                " AND time_updated >= ? ORDER BY time_updated DESC",
                (cutoff_ms,),
            ).fetchall()
        except sqlite3.Error:
            return sessions
        finally:
            connection.close()
        # Only the open project's sessions are rendered in CodeNomad's list,
        # so only those can be switched to. Rows for other projects were
        # unreachable by construction: the click found nothing and the send
        # was refused. Keep the project the app is actually showing -- the one
        # owning the most recently touched session.
        open_project = ""
        if rows:
            open_project = (rows[0][2] or "").strip().lower()

        for sid, title, directory, agent_name, created, updated, _archived in rows:
            if open_project and (directory or "").strip().lower() != open_project:
                continue
            last_active = float(updated or 0) / 1000.0
            sessions.append(
                Session(
                    key=f"{self.agent}:{sid}",
                    agent=self.agent,
                    name=(title or "").strip() or str(sid)[:12],
                    project=(directory or "").replace("/", os.sep),
                    session_id=str(sid),
                    started=float(created or 0) / 1000.0,
                    last_active=last_active,
                    state=_state_for(last_active, now, self.busy_seconds),
                    detail=agent_name or "",
                )
            )
        # Addressed by name over the debugger, so a tab index would be a lie.
        for session in sessions:
            session.tab_hint = None
        return sessions

    def tail_transcript(self, session: Session, limit: int = 4000) -> str:
        return self.recent_transcripts(limit_per_session=limit)

    def recent_transcripts(
        self, max_age_hours: float = 6.0, limit_per_session: int = 4000
    ) -> str:
        """Recent assistant text, for the quota scanner."""
        if not self.db_path.exists():
            return ""
        cutoff_ms = (time.time() - max_age_hours * 3600.0) * 1000.0
        try:
            connection = sqlite3.connect(
                f"file:{self.db_path.as_posix()}?mode=ro", uri=True
            )
        except sqlite3.Error:
            return ""
        try:
            rows = connection.execute(
                "SELECT data FROM part WHERE time_created >= ?"
                " ORDER BY time_created DESC LIMIT 400",
                (cutoff_ms,),
            ).fetchall()
        except sqlite3.Error:
            return ""
        finally:
            connection.close()
        chunks = [str(r[0] or "")[:limit_per_session] for r in rows]
        return "\n".join(reversed(chunks))


@dataclass
class SessionRegistry:
    """Every enabled provider, queried as one list.

    Holds the last successful result per provider: a provider that throws or
    momentarily reads an empty directory must not blank the sidebar the user is
    looking at, and a scan is not a reason to lose a selection.
    """

    providers: list[object] = field(default_factory=list)
    enabled: set[str] = field(default_factory=set)
    _cache: dict[str, list[Session]] = field(default_factory=dict, repr=False)
    last_error: str = ""

    def provider_names(self) -> list[str]:
        return [getattr(p, "agent", "?") for p in self.providers]

    def enable(self, agent: str, on: bool = True) -> None:
        if on:
            self.enabled.add(agent)
        else:
            self.enabled.discard(agent)
            self._cache.pop(agent, None)

    def is_enabled(self, agent: str) -> bool:
        return agent in self.enabled

    def discover(self, now: float | None = None) -> list[Session]:
        now = time.time() if now is None else now
        found: list[Session] = []
        errors: list[str] = []
        for provider in self.providers:
            agent = getattr(provider, "agent", "?")
            if agent not in self.enabled:
                continue
            try:
                result = list(provider.discover(now))
            except Exception as exc:  # a broken provider is not a broken app
                errors.append(f"{agent}: {exc}")
                result = self._cache.get(agent, [])
            else:
                self._cache[agent] = result
            found.extend(result)
        self.last_error = "; ".join(errors)
        return found

    def tail_transcript(self, session: Session, limit: int = 4000) -> str:
        for provider in self.providers:
            if getattr(provider, "agent", "?") == session.agent:
                if hasattr(provider, "tail_transcript"):
                    return provider.tail_transcript(session, limit)
        return ""

    def recent_transcripts(self, agent: str, max_age_hours: float = 6.0, limit: int = 4000) -> str:
        for provider in self.providers:
            if getattr(provider, "agent", "?") == agent:
                if hasattr(provider, "recent_transcripts"):
                    return provider.recent_transcripts(max_age_hours, limit)
        return ""


def default_registry(
    roots: Iterable[str | os.PathLike] = (),
    busy_seconds: float = DEFAULT_BUSY_SECONDS,
) -> SessionRegistry:
    """The providers SAISENT ships with, Claude Code enabled by default."""
    registry = SessionRegistry(
        providers=[
            ClaudeCodeProvider(busy_seconds=busy_seconds),
            FreebuffProvider(
                roots=list(roots),
                busy_seconds=busy_seconds,
                running=process_running,
            ),
            AntigravityProvider(busy_seconds=busy_seconds),
            CodeNomadProvider(busy_seconds=busy_seconds),
        ],
        enabled={"claude-code"},
    )
    return registry
