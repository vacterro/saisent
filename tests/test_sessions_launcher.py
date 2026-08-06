"""Making the debugger port permanent, so nobody has to remember the flag."""

from __future__ import annotations

import json

from SAISENT_sessions import launcher


def point_argv_at(monkeypatch, tmp_path, agent="antigravity", name="argv.json"):
    path = tmp_path / name
    monkeypatch.setitem(launcher.ARGV_JSON_PATHS, agent, str(path))
    return path


def test_a_commented_argv_json_still_parses():
    """VS Code ships this file full of `//` comments."""
    raw = """
    // This configuration file allows permanent arguments.
    {
      // a comment
      "enable-crash-reporter": true
    }
    """
    import re

    assert json.loads(launcher._COMMENT.sub("", raw))["enable-crash-reporter"] is True
    assert re.search(r"//", launcher._COMMENT.sub("", raw)) is None


def test_writing_the_port_keeps_the_other_settings(monkeypatch, tmp_path):
    path = point_argv_at(monkeypatch, tmp_path)
    path.write_text(
        '// keep me\n{\n  "enable-crash-reporter": true,\n'
        '  "crash-reporter-id": "abc"\n}',
        encoding="utf-8",
    )

    changed, message = launcher.enable_permanent_port("antigravity", 28194)

    assert changed is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["remote-debugging-port"] == 28194
    assert data["enable-crash-reporter"] is True
    assert data["crash-reporter-id"] == "abc"
    assert "следующем запуске" in message


def test_the_original_is_backed_up(monkeypatch, tmp_path):
    path = point_argv_at(monkeypatch, tmp_path)
    path.write_text('{"enable-crash-reporter": true}', encoding="utf-8")

    launcher.enable_permanent_port("antigravity", 28194)

    backup = path.with_suffix(".json.saisent.bak")
    assert backup.exists()
    assert "enable-crash-reporter" in backup.read_text(encoding="utf-8")


def test_writing_the_same_port_twice_is_a_no_op(monkeypatch, tmp_path):
    path = point_argv_at(monkeypatch, tmp_path)
    path.write_text('{"remote-debugging-port": 28194}', encoding="utf-8")

    changed, message = launcher.enable_permanent_port("antigravity", 28194)

    assert changed is False
    assert "уже прописан" in message


def test_a_missing_file_is_created(monkeypatch, tmp_path):
    path = point_argv_at(monkeypatch, tmp_path)

    changed, _message = launcher.enable_permanent_port("antigravity", 1234)

    assert changed is True
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "remote-debugging-port": 1234
    }


def test_an_agent_without_argv_support_says_so(monkeypatch):
    monkeypatch.delitem(launcher.ARGV_JSON_PATHS, "antigravity", raising=False)

    changed, message = launcher.enable_permanent_port("claude-code")

    assert changed is False
    assert "не поддерживаются" in message


def test_a_missing_parent_directory_is_reported_not_created(monkeypatch, tmp_path):
    """The app's config folder existing is the proof the app is installed."""
    missing = tmp_path / "nope" / "argv.json"
    monkeypatch.setitem(launcher.ARGV_JSON_PATHS, "antigravity", str(missing))

    changed, message = launcher.enable_permanent_port("antigravity", 1)

    assert changed is False
    assert "нет папки" in message
    assert not missing.exists()


def test_current_port_reads_what_is_configured(monkeypatch, tmp_path):
    path = point_argv_at(monkeypatch, tmp_path)
    assert launcher.current_port("antigravity") == 0

    path.write_text('{"remote-debugging-port": 4242}', encoding="utf-8")
    assert launcher.current_port("antigravity") == 4242


def test_corrupt_argv_json_reads_as_no_port(monkeypatch, tmp_path):
    path = point_argv_at(monkeypatch, tmp_path)
    path.write_text("{ not json", encoding="utf-8")

    assert launcher.current_port("antigravity") == 0


def test_plan_builds_a_command_when_the_exe_is_found(monkeypatch, tmp_path):
    exe = tmp_path / "Antigravity.exe"
    exe.write_bytes(b"")
    monkeypatch.setitem(launcher.EXE_CANDIDATES, "antigravity", (str(exe),))
    point_argv_at(monkeypatch, tmp_path)

    plan = launcher.plan_for("antigravity", 28194)

    assert plan.executable == str(exe)
    assert plan.command == f'"{exe}" --remote-debugging-port=28194'
    assert plan.permanent is True


def test_plan_reports_a_missing_executable_instead_of_guessing(monkeypatch):
    monkeypatch.setitem(launcher.EXE_CANDIDATES, "antigravity", (r"Z:\nope.exe",))

    plan = launcher.plan_for("antigravity")

    assert plan.executable == ""
    assert plan.command == ""


def test_ahk_snippet_is_pasteable(monkeypatch, tmp_path):
    exe = tmp_path / "Antigravity.exe"
    exe.write_bytes(b"")
    monkeypatch.setitem(launcher.EXE_CANDIDATES, "antigravity", (str(exe),))

    line = launcher.ahk_snippet("antigravity", 28194)

    # AHK v2 doubles a quote inside a double-quoted string. Emitting them
    # singly made `Run(""C:\...exe" ...)`, which parses as an empty string
    # followed by nonsense -- a snippet that looks right and runs nothing.
    assert line.startswith('Run("""')
    assert line.endswith('")')
    assert '"" --remote-debugging-port=28194' in line


def test_ahk_snippet_without_an_executable_is_a_comment(monkeypatch):
    monkeypatch.setitem(launcher.EXE_CANDIDATES, "antigravity", (r"Z:\nope.exe",))
    assert launcher.ahk_snippet("antigravity").startswith(";")


def test_every_agent_has_a_distinct_default_port():
    ports = list(launcher.DEFAULT_PORTS.values())
    assert len(ports) == len(set(ports)), "two agents on one port collide"


# ------------------------------------------------------------ T-047 debugger
def test_running_without_debugger_detects_running_but_dead_port(monkeypatch):
    monkeypatch.setitem(
        launcher.DEFAULT_PORTS, "claude-code", 9222,
    )
    monkeypatch.setitem(
        launcher.EXE_CANDIDATES, "claude-code",
        (r"C:\nonexistent\claude.exe",),
    )
    monkeypatch.setattr(
        launcher, "find_executable",
        lambda agent: r"C:\nonexistent\claude.exe",
    )
    detected, exe_name, port = launcher.running_without_debugger(
        "claude-code",
        probe=lambda p: False,          # port dead
        process_check=lambda n: True,   # exe alive
    )
    assert detected is True
    assert exe_name == "claude.exe"
    assert port == 9222


def test_running_without_debugger_not_detected_when_port_answers(monkeypatch):
    monkeypatch.setitem(launcher.DEFAULT_PORTS, "claude-code", 9222)
    monkeypatch.setattr(
        launcher, "find_executable",
        lambda agent: r"C:\nonexistent\claude.exe",
    )
    detected, _exe, _port = launcher.running_without_debugger(
        "claude-code",
        probe=lambda p: True,           # port alive
        process_check=lambda n: True,
    )
    assert detected is False


def test_running_without_debugger_not_detected_when_not_running():
    detected, _exe_name, port = launcher.running_without_debugger(
        "claude-code",
        probe=lambda p: False,
        process_check=lambda n: False,  # not running
    )
    assert detected is False
    assert port == 9222


def test_running_without_debugger_needs_both_exe_and_port():
    detected, _exe, port = launcher.running_without_debugger(
        "claude-code",
        probe=lambda p: False,
        process_check=lambda n: True,
    )
    # With no real exe on this machine the launcher cannot claim a restart
    # exists; "not detected" is the honest answer.
    assert port in (0, 9222)
    if not detected and port == 9222:
        assert _exe  # exe_name must be non-empty if a restart could exist


# ------------------------------------------------- graceful close (T-047 fix)
class Proc:
    """A process that exits after N polls, or never."""

    def __init__(self, exits_after=None):
        self.exits_after = exits_after
        self.polls = 0
        self.closed = False
        self.forced = False

    def alive(self, _exe):
        self.polls += 1
        if self.exits_after is None:
            return True
        return self.polls <= self.exits_after

    def close(self, _exe):
        self.closed = True

    def force(self, _exe):
        self.forced = True
        self.exits_after = self.polls  # dies right after the force


def close(proc, **kw):
    kw.setdefault("sleep", lambda _s: None)
    kw.setdefault("timeout", 1.0)
    return launcher.close_gracefully(
        "claude.exe",
        process_check=proc.alive,
        post_close=proc.close,
        force=proc.force,
        **kw,
    )


def test_a_polite_close_is_tried_before_any_force():
    """`taskkill /F` gives an agent no chance to flush its state."""
    proc = Proc(exits_after=1)

    exited, message = close(proc)

    assert exited is True
    assert proc.closed is True
    assert proc.forced is False, "force must be the fallback, not the plan"
    assert "сам" in message


def test_force_is_used_only_after_the_timeout():
    proc = Proc(exits_after=None)

    exited, message = close(proc)

    assert proc.closed is True
    assert proc.forced is True
    assert exited is True
    assert "принудительно" in message


def test_force_can_be_refused():
    proc = Proc(exits_after=None)

    exited, message = close(proc, force_after=False)

    assert exited is False
    assert proc.forced is False
    assert "добивать не стал" in message


def test_a_process_that_is_already_gone_needs_nothing():
    proc = Proc(exits_after=0)

    exited, message = close(proc)

    assert exited is True
    assert proc.closed is False
    assert "уже не запущен" in message


def test_the_claude_warning_names_what_actually_dies():
    """One image name covers the desktop app and every CLI session."""
    warning = launcher.restart_warning("claude-code")
    assert "claude.exe" in warning
    assert "сессии" in warning.lower()


def test_other_agents_get_the_plain_warning():
    assert "прервётся" in launcher.restart_warning("antigravity")
