import pytest


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HT2WV_HOME", str(tmp_path / "home"))
    from ht2wv import config

    return config.init_home()
