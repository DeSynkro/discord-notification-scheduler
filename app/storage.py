import json
import threading
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()


def _path(kind: str) -> Path:
    return DATA_DIR / f"{kind}.json"


def read_json(kind: str) -> list[dict]:
    path = _path(kind)
    if not path.exists():
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def write_json(kind: str, data: list[dict]) -> None:
    path = _path(kind)
    tmp = path.with_suffix(".tmp")
    with _lock:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)
