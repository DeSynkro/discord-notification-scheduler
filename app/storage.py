import json
import threading
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()


def _path(kind: str) -> Path:
    return DATA_DIR / f"{kind}.json"


def _backup_corrupt(path: Path, kind: str) -> None:
    try:
        backup = path.with_name(f"{kind}.corrupt.json")
        backup.write_bytes(path.read_bytes())
    except OSError:
        pass


def read_json(kind: str) -> list[dict]:
    path = _path(kind)
    if not path.exists():
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (ValueError, OSError):
        _backup_corrupt(path, kind)
        return []

    if not isinstance(data, list):
        _backup_corrupt(path, kind)
        return []

    valid = [item for item in data if isinstance(item, dict)]
    if len(valid) != len(data):
        _backup_corrupt(path, kind)
    return valid


def write_json(kind: str, data: list[dict]) -> None:
    path = _path(kind)
    tmp = path.with_suffix(".tmp")
    with _lock:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)
