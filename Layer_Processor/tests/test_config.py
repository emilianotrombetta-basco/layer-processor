from pathlib import Path

from lib import config


def test_save_paths_creates_missing_directories(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)

    created = config.save_paths({
        "raw": "storage/raw",
        "work": "storage/work",
        "out": "storage/out",
        "state": "storage/state",
        "admin": "storage/admin",
    })

    expected = {
        tmp_path / "storage" / name
        for name in ("raw", "work", "out", "state", "admin")
    }
    assert set(created) == expected
    assert all(path.is_dir() for path in expected)
    assert config.get_paths() == {
        "raw": tmp_path / "storage" / "raw",
        "work": tmp_path / "storage" / "work",
        "out": tmp_path / "storage" / "out",
        "state": tmp_path / "storage" / "state",
        "admin": tmp_path / "storage" / "admin",
    }


def test_save_paths_rejects_existing_file(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    invalid = tmp_path / "not-a-directory"
    invalid.write_text("file", encoding="utf-8")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)

    try:
        config.save_paths({"raw": str(invalid)})
    except ValueError as exc:
        assert "non e' una cartella" in str(exc)
    else:
        raise AssertionError("Era atteso un ValueError")

    assert not config_file.exists()
