import json
from datetime import datetime
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_checkpoint_json(path: Path, data: dict[str, Any], *, add_updated: bool = True) -> None:
    payload = dict(data)
    if add_updated:
        payload["updated"] = datetime.now().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
