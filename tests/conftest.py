import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("YNG_DATA", str(tmp_path / "data"))
    from app import db, net, ranking

    db.set_db_path(tmp_path / "test.sqlite3")
    db.init()
    ranking.INDEX.__init__()
    ranking._CACHE.clear()

    # No network in tests: any HTTP attempt fails loudly.
    def _no_net(*a, **k):
        raise AssertionError("network access in tests")
    monkeypatch.setattr(net, "client", _no_net)
    yield
    db.set_db_path(None)
