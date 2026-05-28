"""
Validate PhilRice JSONL format. Run from project root: python -m src.scripts.validate_philrice_jsonl [path]
Default path: data/philrice_processed/philrice_corpus.jsonl
"""
import json
import sys
from pathlib import Path
from src.openstat.config import data_path

DEFAULT_PATH = Path(data_path("philrice_processed", "philrice_corpus.jsonl"))
SAMPLE_PATH = Path(data_path("philrice_processed", "philrice_sample_cleaned.jsonl"))

REQUIRED_KEYS = ["text", "input"]
OPTIONAL_KEYS = ["content", "source", "doc_id", "filename", "page"]


def validate(path: Path) -> tuple[bool, list[str]]:
    errors = []
    if not path.exists():
        return False, [f"File not found: {path}"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        return False, [f"Cannot read file: {e}"]

    if not lines:
        return False, ["File is empty."]

    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"Line {i}: Invalid JSON – {e}")
            continue
        if not isinstance(obj, dict):
            errors.append(f"Line {i}: Expected JSON object, got {type(obj)}")
            continue
        for k in REQUIRED_KEYS:
            if k not in obj:
                errors.append(f"Line {i}: Missing required key '{k}'")
                break
            if not isinstance(obj[k], str):
                errors.append(f"Line {i}: Key '{k}' must be string")
            if not obj[k].strip():
                errors.append(f"Line {i}: Key '{k}' is empty")
        if "text" in obj and "input" in obj and obj["text"] != obj["input"]:
            errors.append(f"Line {i}: 'text' and 'input' must be identical")
        if "content" in obj and obj.get("text") != obj.get("content"):
            errors.append(f"Line {i}: 'content' should equal 'text'")

    return len(errors) == 0, errors


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    if not path.exists() and SAMPLE_PATH.exists():
        path = SAMPLE_PATH
        print(f"Corpus not found; validating sample: {path}")
    ok, errors = validate(path)
    if ok:
        print("OK – Format valid. Required keys present, text == input.")
    else:
        print("VALIDATION FAILED:")
        for e in errors[:30]:
            print(f"  - {e}")
        if len(errors) > 30:
            print(f"  ... and {len(errors) - 30} more.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
