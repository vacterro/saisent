"""Config schema validation on load (T-060).

`Config.load()` used to silently skip a wrong-typed value and keep the
default, so a typo in SAISENT.json (a string where a number belongs, a
negative delay, a schedule that is not HH:MM) crashed mid-send at an
`int()` cast or misbehaved without a word. Now load() raises `ConfigError`
naming the offending key; the app catches it at startup and falls back to
defaults.
"""

from __future__ import annotations

import json

import pytest

from SAISENT import Config, ConfigError


def write_config(tmp_path, **overrides):
    path = tmp_path / "SAISENT.json"
    data = dict(Config.defaults)
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_good_config_loads_unchanged(tmp_path):
    path = write_config(tmp_path, gap_ms=2000, submit="CTRL+ENTER")
    config = Config(path)
    config.load()
    assert config["gap_ms"] == 2000
    assert config["submit"] == "CTRL+ENTER"
    assert config["tray_enabled"] is True  # default still present


def test_a_missing_file_keeps_defaults(tmp_path):
    config = Config(tmp_path / "nope.json")
    config.load()  # must not raise
    assert config["gap_ms"] == 1500


def test_a_string_where_a_number_belongs_names_the_key(tmp_path):
    path = write_config(tmp_path, key_delay_ms="oops")
    with pytest.raises(ConfigError) as exc:
        Config(path).load()
    assert "key_delay_ms" in str(exc.value)


def test_a_negative_delay_names_the_key(tmp_path):
    path = write_config(tmp_path, activation_timeout_ms=-5)
    with pytest.raises(ConfigError) as exc:
        Config(path).load()
    assert "activation_timeout_ms" in str(exc.value)


def test_a_zero_gap_is_rejected(tmp_path):
    path = write_config(tmp_path, gap_ms=0)
    with pytest.raises(ConfigError) as exc:
        Config(path).load()
    assert "gap_ms" in str(exc.value)


def test_a_bool_does_not_masquerade_as_a_number(tmp_path):
    # bool is an int subclass in Python; JSON true must not become a delay.
    path = write_config(tmp_path, gap_ms=True)
    with pytest.raises(ConfigError) as exc:
        Config(path).load()
    assert "gap_ms" in str(exc.value)


def test_a_non_bool_where_a_flag_belongs_names_the_key(tmp_path):
    path = write_config(tmp_path, dry="yes")
    with pytest.raises(ConfigError) as exc:
        Config(path).load()
    assert "dry" in str(exc.value)


def test_a_bad_schedule_time_names_the_key(tmp_path):
    path = write_config(tmp_path, schedule_time="3 o'clock")
    with pytest.raises(ConfigError) as exc:
        Config(path).load()
    assert "schedule_time" in str(exc.value)


def test_a_good_schedule_time_passes(tmp_path):
    path = write_config(tmp_path, schedule_time="23:30")
    config = Config(path)
    config.load()
    assert config["schedule_time"] == "23:30"


def test_a_non_object_root_is_named(tmp_path):
    path = tmp_path / "SAISENT.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ConfigError):
        Config(path).load()


# ------------------------------------------------- version migration (T-082)
def write_v1_config(tmp_path, **extra):
    path = tmp_path / "SAISENT.json"
    data = {"version": 1, "agents": ["claude-code"], "gap_ms": 1500}
    data.update(extra)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_v1_file_is_migrated_to_the_current_version(tmp_path):
    path = write_v1_config(tmp_path, gap_ms=2000)
    config = Config(path)
    config.load()

    assert config["version"] == Config.defaults["version"]
    assert config["gap_ms"] == 2000  # explicit value survives
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["version"] == Config.defaults["version"]


def test_a_missing_version_is_treated_as_v1(tmp_path):
    path = tmp_path / "SAISENT.json"
    path.write_text(json.dumps({"gap_ms": 2500}), encoding="utf-8")
    config = Config(path)
    config.load()

    assert config["version"] == Config.defaults["version"]
    assert config["gap_ms"] == 2500


def test_migration_fills_new_defaults(tmp_path):
    """A v1 file that never knew a newer key gets its default."""
    path = write_v1_config(tmp_path)
    config = Config(path)
    config.load()

    assert config["theme"] == Config.defaults["theme"]
    assert config["templates"] == Config.defaults["templates"]
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert "theme" in on_disk


def test_a_newer_version_is_never_downgraded(tmp_path):
    path = tmp_path / "SAISENT.json"
    data = dict(Config.defaults)
    data["version"] = 99
    data["gap_ms"] = 3000
    path.write_text(json.dumps(data), encoding="utf-8")

    config = Config(path)
    config.load()  # must not raise
    assert config["gap_ms"] == 3000
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["version"] == 99  # the newer app's file is untouched


def test_migration_preserves_unknown_keys(tmp_path):
    """Keys a newer schema adds must not be dropped during migration."""
    path = write_v1_config(tmp_path, future_key="keep me")
    Config(path).load()

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["future_key"] == "keep me"
