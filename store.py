import os
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
RESULTS = DATA / "results.json"


def load_results():
    if RESULTS.exists():
        return json.loads(RESULTS.read_text(encoding="utf-8"))
    return []


def save_results(results):
    DATA.mkdir(exist_ok=True)
    tmp = RESULTS.with_suffix(".tmp")
    tmp.write_text(json.dumps(results), encoding="utf-8")
    os.replace(tmp, RESULTS)

def load_config():
    config = BASE / "config.json"
    if not config.exists():
        raise SystemExit("config.json not found. Copy config.example.json to config.json and add your accounts.")
    return json.loads(config.read_text(encoding="utf-8"))
