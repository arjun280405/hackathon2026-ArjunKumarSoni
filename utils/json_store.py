import json
from pathlib import Path


def load_json(path, default):
    file_path = Path(path)
    if not file_path.exists():
        return default

    with open(file_path, encoding="utf-8") as file:
        return json.load(file)


def save_json(path, data):
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)
