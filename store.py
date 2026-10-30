import os
import json
from email.utils import parseaddr
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
RESULTS = DATA / "results.json"
ACTIONS = DATA / "actions.json"   # done / ignored, written only by the UI
META = DATA / "meta.json"         # last run time and count
CORRECTIONS = DATA / "corrections.json"   # your priority fixes, written only by the UI
RULES = DATA / "rules.json"               # sender -> priority, written only by the UI
CONFIG = BASE / "config.json"
DEFAULT_CONFIG = {"accounts": {}, "query": "in:inbox newer_than:1d", "limit": 20}


def read_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def write_json(path, data, indent=None):
    # write to a temp file, then swap, so a crash never leaves half a file
    DATA.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=indent), encoding="utf-8")
    os.replace(tmp, path)


def load_results():
    return read_json(RESULTS, [])


def save_results(results):
    write_json(RESULTS, results)


def action_key(r):
    return f"{r['account']}:{r['id']}"


def load_actions():
    # {"<account>:<id>": {"status": "done" | "ignored", "at": "<iso time>"}}
    return read_json(ACTIONS, {})


def save_actions(actions):
    write_json(ACTIONS, actions)


def sender_address(from_header):
    # "Jane Doe <Jane@X.com>" -> "jane@x.com"
    return parseaddr(from_header)[1].lower()


def load_corrections():
    # {"<account>:<id>": {"from", "sender", "subject", "old", "new", "note", "at"}}
    return read_json(CORRECTIONS, {})


def save_corrections(corrections):
    write_json(CORRECTIONS, corrections)


def load_rules():
    # {"rules": {"<sender address>": "high" | "medium" | "low"}, "declined": [<addresses not to suggest again>]}
    return read_json(RULES, {"rules": {}, "declined": []})


def save_rules(rules):
    write_json(RULES, rules, indent=2)


def effective_priority(r, corrections, rules):
    # your correction beats a sender rule, which beats the model; returns (priority, source)
    correction = corrections.get(action_key(r))
    if correction:
        return correction["new"], "corrected"
    rule = rules["rules"].get(sender_address(r["from"]))
    if rule:
        return rule, "rule"
    return r["priority"], "model"


def load_meta():
    return read_json(META, {})


def save_meta(meta):
    write_json(META, meta)


def load_config(required=True):
    # required=False: the UI starts with an empty config so accounts can be added in Settings
    if not CONFIG.exists():
        if required:
            raise SystemExit("config.json not found. Copy config.example.json to config.json and add your accounts.")
        return dict(DEFAULT_CONFIG, accounts={})
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def save_config(config):
    write_json(CONFIG, config, indent=2)   # indented: people edit this file by hand
