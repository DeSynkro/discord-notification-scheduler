import os

os.environ["DISABLE_SCHEDULER"] = "1"

import pytest


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def client(tmp_data):
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c
