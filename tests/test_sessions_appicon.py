"""Icon generation: cheap, cached, and never fatal."""

from __future__ import annotations

import struct

import pytest

from SAISENT_sessions import appicon

PIL = pytest.importorskip("PIL")


def make_png(path, size=(64, 64), colour=(255, 255, 255, 255)):
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, colour).save(path, format="PNG")
    return path


def ico_sizes(path):
    """Read the ICONDIR: count and the (w, h) of every entry."""
    data = path.read_bytes()
    count = struct.unpack_from("<H", data, 4)[0]
    out = []
    for index in range(count):
        offset = 6 + index * 16
        width = data[offset] or 256
        height = data[offset + 1] or 256
        out.append((width, height))
    return out


def test_ico_is_built_with_every_size_windows_asks_for(tmp_path):
    png = make_png(tmp_path / "src.png", (256, 256))
    ico = tmp_path / "out.ico"

    result = appicon.ensure_ico(png, ico)

    assert result == str(ico)
    assert ico.exists()
    assert (16, 16) in ico_sizes(ico), "the tray asks for 16x16"
    assert (32, 32) in ico_sizes(ico)


def test_a_fresh_ico_is_not_rebuilt(tmp_path):
    png = make_png(tmp_path / "src.png")
    ico = tmp_path / "out.ico"
    appicon.ensure_ico(png, ico)
    first = ico.stat().st_mtime_ns

    appicon.ensure_ico(png, ico)

    assert ico.stat().st_mtime_ns == first, "rebuilding on every start is waste"


def test_a_newer_source_rebuilds(tmp_path):
    import os
    import time

    png = make_png(tmp_path / "src.png")
    ico = tmp_path / "out.ico"
    appicon.ensure_ico(png, ico)
    old = ico.stat().st_mtime_ns

    time.sleep(0.01)
    make_png(png, (128, 128), (0, 0, 0, 255))
    os.utime(png, None)
    appicon.ensure_ico(png, ico)

    assert ico.stat().st_mtime_ns != old


def test_a_missing_source_is_not_fatal(tmp_path):
    """A missing icon is cosmetic; it must never stop the app starting."""
    assert appicon.ensure_ico(tmp_path / "nope.png", tmp_path / "out.ico") == ""


def test_a_missing_source_keeps_an_ico_that_already_exists(tmp_path):
    ico = tmp_path / "out.ico"
    make_png(tmp_path / "src.png")
    appicon.ensure_ico(tmp_path / "src.png", ico)

    assert appicon.ensure_ico(tmp_path / "gone.png", ico) == str(ico)


def test_unreadable_source_is_not_fatal(tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")

    assert appicon.ensure_ico(broken, tmp_path / "out.ico") == ""


def test_load_hicon_of_a_missing_file_is_none(tmp_path):
    assert appicon.load_hicon(tmp_path / "nope.ico") is None
    assert appicon.load_hicon("") is None


def test_apply_window_icon_reports_failure_instead_of_raising(tmp_path):
    class Window:
        def iconbitmap(self, *args, **kwargs):
            raise RuntimeError("no display")

    assert appicon.apply_window_icon(Window(), tmp_path / "nope.ico") is False


# ------------------------------------------------------------------ tray
class FakeNid:
    def __init__(self):
        self.uFlags = 0x00000001 | 0x00000004
        self.hIcon = 0


class FakeTray:
    def __init__(self, *args, **kwargs):
        self.args = args

    def _nid(self):
        return FakeNid()


def test_the_tray_subclass_adds_the_icon_flag_the_core_omits(tmp_path, monkeypatch):
    """The core sets MESSAGE|TIP only, so the tray entry drew nothing."""
    monkeypatch.setattr(appicon, "load_hicon", lambda *_a, **_k: 4242)
    tray_class = appicon.make_tray_class(FakeTray)

    tray = tray_class(ico_path="whatever.ico")
    nid = tray._nid()

    assert nid.uFlags & tray_class.NIF_ICON
    assert nid.hIcon == 4242


def test_without_an_icon_the_tray_behaves_exactly_as_before(monkeypatch):
    monkeypatch.setattr(appicon, "load_hicon", lambda *_a, **_k: None)
    tray_class = appicon.make_tray_class(FakeTray)

    nid = tray_class(ico_path="")._nid()

    assert not (nid.uFlags & tray_class.NIF_ICON)
    assert nid.hIcon == 0
