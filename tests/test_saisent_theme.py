"""Theme toggle: config stores theme, core has all three palettes."""

from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import SAISENT_core as core


def test_all_three_themes_are_defined():
    assert "vintage" in core.THEMES
    assert "dark" in core.THEMES
    assert "light" in core.THEMES


def test_vintage_is_the_default():
    assert core.THEMES["vintage"] is core.C


def test_all_themes_have_same_keys():
    vintage_keys = set(core.C)
    for name, theme in core.THEMES.items():
        assert set(theme) == vintage_keys, f"{name} has different keys from vintage"


def test_each_theme_has_all_required_tokens():
    required = {
        "background", "surface", "surfaceRaised", "textPrimary",
        "textSecondary", "textMuted", "danger", "success", "warning",
        "borderHighlight", "borderMuted", "selection", "compareBack",
    }
    for name, theme in core.THEMES.items():
        missing = required - set(theme)
        assert not missing, f"{name} missing: {missing}"
