from app.storage import read_json


def test_corrupt_json_is_backed_up(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.DATA_DIR", tmp_path)
    (tmp_path / "alarms.json").write_text("{not json")
    assert read_json("alarms") == []
    assert (tmp_path / "alarms.corrupt.json").read_text() == "{not json"


def test_missing_file_returns_empty_without_backup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.DATA_DIR", tmp_path)
    assert read_json("alarms") == []
    assert not (tmp_path / "alarms.corrupt.json").exists()
