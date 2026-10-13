from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    user_home = tmp_path / "user_home"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("USERPROFILE", str(user_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: user_home))
    monkeypatch.setenv("HT2WV_HOME", str(tmp_path / "home"))
    from ht2wv import config

    return config.init_home()
