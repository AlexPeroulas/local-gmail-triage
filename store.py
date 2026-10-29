import os
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "results.json"


def load_results():
    if RESULTS.exists():
        return json.loads(RESULTS.read_text(encoding="utf-8"))
    return []


def save_results(results):
    tmp = RESULTS.with_suffix(".tmp")
    tmp.write_text(json.dumps(results), encoding="utf-8")
    os.replace(tmp, RESULTS)