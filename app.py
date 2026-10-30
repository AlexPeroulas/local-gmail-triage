import re
import threading
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import quote
from flask import Flask, abort, jsonify, render_template, request
from gmail_client import login, get_address, is_signed_in, token_path, NotSignedIn
from store import (load_results, load_actions, save_actions, action_key,
                   load_meta, load_config, save_config, sender_address,
                   load_corrections, save_corrections, load_rules, save_rules, effective_priority)
from triage import run_triage

app = Flask(__name__)
ALLOWED_HOSTS = {"127.0.0.1:5000", "localhost:5000"}
LEVELS = ("high", "medium", "low")
LABEL_RE = re.compile(r"[a-z0-9_-]{1,20}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

# state of the background run, shared with /status
run_state = {"running": False, "message": "", "error": None}
run_lock = threading.Lock()
actions_lock = threading.Lock()   # one /action write at a time
config_lock = threading.Lock()    # one config.json write at a time
learn_lock = threading.Lock()     # one corrections.json / rules.json write at a time
SUGGEST_AFTER = 2                 # corrections for one sender before offering a rule
logins = {}                       # label -> {"state": "waiting" | "ok" | "error", "message": ...}


@app.before_request
def only_this_page():
    # blocks DNS rebinding (other domains pointed at 127.0.0.1)
    if request.host not in ALLOWED_HOSTS:
        abort(403)
    # blocks other websites from POSTing to this server
    origin = request.headers.get("Origin")
    if request.method == "POST" and origin not in {f"http://{h}" for h in ALLOWED_HOSTS}:
        abort(403)


def sender_name(from_header):
    # "Jane Doe <jane@x.com>" -> "Jane Doe"; falls back to the address
    name, address = parseaddr(from_header)
    return name or address or from_header


def clock(dt):
    return f"{dt.hour % 12 or 12}:{dt:%M} {dt:%p}"


def short_time(dt, now):
    # inbox-style time: "12m", "3h", "Yesterday", "Mon", "Oct 12"
    if dt is None:
        return ""
    if now - dt < timedelta(hours=1):
        return f"{max(1, (now - dt).seconds // 60)}m"
    if dt.date() == now.date():
        return f"{(now - dt).seconds // 3600}h"
    if dt.date() == (now - timedelta(days=1)).date():
        return "Yesterday"
    if now - dt < timedelta(days=7):
        return f"{dt:%a}"
    return f"{dt:%b} {dt.day}" + ("" if dt.year == now.year else f", {dt.year}")


def day_and_clock(dt, now):
    # "8:02 AM", "Yesterday 6:00 PM", "Oct 12 6:00 PM"
    if dt.date() == now.date():
        return clock(dt)
    if dt.date() == (now - timedelta(days=1)).date():
        return f"Yesterday {clock(dt)}"
    return f"{dt:%b} {dt.day} {clock(dt)}"


def gmail_link(address, message_id):
    # plain link to the email in Gmail; authuser picks the right signed-in account
    if not address:
        return ""
    return f"https://mail.google.com/mail/?authuser={quote(address)}#all/{quote(message_id)}"


def email_time(date_header):
    try:
        return parsedate_to_datetime(date_header).astimezone()
    except (TypeError, ValueError):
        return None


@app.route("/")
def index():
    now = datetime.now().astimezone()
    results = load_results()
    actions = load_actions()
    config = load_config(required=False)

    meta = load_meta()
    corrections = load_corrections()
    rules = load_rules()
    for r in results:
        r["model_priority"] = r["priority"]
        r["priority"], r["source"] = effective_priority(r, corrections, rules)
        r["new"] = bool(meta.get("run")) and r.get("run") == meta["run"]   # added by the latest finished run
        r["sender"] = sender_name(r["from"])
        r["gmail_url"] = gmail_link(config["accounts"].get(r["account"]), r["id"])
        r["dt"] = email_time(r["date"])
        r["time"] = short_time(r["dt"], now)
    oldest = datetime.min.replace(tzinfo=timezone.utc)   # emails with no date go last
    results.sort(key=lambda r: r["dt"] or oldest, reverse=True)   # newest first

    # emails marked done / ignored go to their own tabs, most recently handled first
    handled = {"done": [], "ignored": []}
    for r in results:
        action = actions.get(action_key(r))
        if action:
            at = datetime.fromisoformat(action["at"]).astimezone()
            handled[action["status"]].append({**r, "at": action["at"], "when": day_and_clock(at, now)})
    for items in handled.values():
        items.sort(key=lambda r: r["at"], reverse=True)

    active = [r for r in results if action_key(r) not in actions]
    groups = {}   # priority -> emails
    for level in LEVELS:
        level_group = [r for r in active if r["priority"] == level]
        if level_group:
            groups[level] = level_group

    last_checked = ""
    if meta.get("last_run"):
        last_run = datetime.fromisoformat(meta["last_run"]).astimezone()
        last_checked = f"Checked {day_and_clock(last_run, now)} · {meta.get('added', 0)} new"

    accounts = [{"label": label, "email": email, "signed_in": is_signed_in(label), "login": logins.get(label)}
                for label, email in config["accounts"].items()]
    # filter shows configured accounts, plus any removed ones that still have results
    filter_accounts = list(config["accounts"]) + sorted({r["account"] for r in results} - set(config["accounts"]))

    recent_corrections = sorted(({"key": k, **c} for k, c in corrections.items()),
                                key=lambda c: c["at"], reverse=True)[:20]

    return render_template("index.html", groups=groups, handled=handled, state=run_state,
                           last_checked=last_checked, config=config, accounts=accounts,
                           filter_accounts=filter_accounts, rules=rules["rules"],
                           corrections=recent_corrections, correction_count=len(corrections))


def run_in_background():
    try:
        run_triage(allow_login=False, open_page=False, on_progress=lambda m: run_state.update(message=m))
    except (Exception, SystemExit) as e:   # shown on the page instead of killing the thread
        run_state["error"] = str(e)
    finally:
        run_state["running"] = False
        run_lock.release()


@app.post("/run")
def run_now():
    if not load_config(required=False)["accounts"]:
        return jsonify(error="Add an account in Settings first."), 400
    if not run_lock.acquire(blocking=False):   # a run is already going
        return jsonify(run_state), 409
    run_state.update(running=True, message="Starting...", error=None)
    threading.Thread(target=run_in_background, daemon=True).start()
    return jsonify(run_state)


@app.post("/action")
def set_action():
    # body: {"account": ..., "id": ..., "status": "done" | "ignored" | null}
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in ("done", "ignored", None) or not data.get("account") or not data.get("id"):
        abort(400)

    key = action_key(data)
    with actions_lock:
        actions = load_actions()
        if status is None:   # undo / restore
            actions.pop(key, None)
        else:
            actions[key] = {"status": status, "at": datetime.now().isoformat(timespec="seconds")}
        save_actions(actions)
    return jsonify(ok=True)


# ---- Learning from your corrections ----

@app.post("/correct")
def correct():
    # body: {"account", "id", "priority": "high" | "medium" | "low", "note": "optional why"}
    data = request.get_json(silent=True) or {}
    priority = data.get("priority")
    note = str(data.get("note") or "").strip()[:200]
    if priority not in LEVELS or not data.get("account") or not data.get("id"):
        abort(400)
    key = action_key(data)
    r = next((r for r in load_results() if action_key(r) == key), None)
    if r is None:
        abort(404)
    sender = sender_address(r["from"])

    with learn_lock:
        corrections = load_corrections()
        if priority == r["priority"]:   # back to what the model said: forget the correction
            corrections.pop(key, None)
        else:
            corrections[key] = {"from": r["from"], "sender": sender, "subject": r["subject"],
                                "old": r["priority"], "new": priority, "note": note,
                                "at": datetime.now().isoformat(timespec="seconds")}
        save_corrections(corrections)

        # offer a sender rule once the same fix has been made SUGGEST_AFTER times
        rules = load_rules()
        same = sum(1 for c in corrections.values() if c["sender"] == sender and c["new"] == priority)
        suggest = None
        if sender and same >= SUGGEST_AFTER and sender not in rules["rules"] and sender not in rules["declined"]:
            suggest = {"sender": sender, "priority": priority, "count": same}
    return jsonify(ok=True, suggest=suggest)


@app.post("/corrections/remove")
def remove_correction():
    key = (request.get_json(silent=True) or {}).get("key")
    with learn_lock:
        corrections = load_corrections()
        if corrections.pop(key, None) is None:
            abort(404)
        save_corrections(corrections)
    return jsonify(ok=True)


@app.post("/rules")
def set_rule():
    # body: {"sender": "x@y.com", "priority": "low"} to set, {"priority": null} to remove,
    #       {"decline": true} to stop suggesting a rule for this sender
    data = request.get_json(silent=True) or {}
    sender = str(data.get("sender", "")).strip().lower()
    priority = data.get("priority")
    if not EMAIL_RE.fullmatch(sender) or priority not in (*LEVELS, None):
        abort(400)
    with learn_lock:
        rules = load_rules()
        if data.get("decline"):
            if sender not in rules["declined"]:
                rules["declined"].append(sender)
        elif priority is None:
            rules["rules"].pop(sender, None)
        else:
            rules["rules"][sender] = priority
        save_rules(rules)
    return jsonify(ok=True)


# ---- Settings ----

def bad_request(message):
    return jsonify(error=message), 400


@app.post("/settings")
def save_settings():
    # body: {"query": "...", "limit": 20}
    data = request.get_json(silent=True) or {}
    query = str(data.get("query", "")).strip()
    try:
        limit = int(data.get("limit"))
    except (TypeError, ValueError):
        return bad_request("Limit must be a number.")
    if not query or len(query) > 200:
        return bad_request("Query can't be empty (max 200 characters).")
    if not 1 <= limit <= 100:
        return bad_request("Limit must be between 1 and 100.")

    with config_lock:
        config = load_config(required=False)
        config.update(query=query, limit=limit)
        save_config(config)
    return jsonify(ok=True)


@app.post("/accounts")
def add_account():
    # body: {"label": "school", "email": "me@school.edu"}
    data = request.get_json(silent=True) or {}
    label = str(data.get("label", "")).strip().lower()
    email = str(data.get("email", "")).strip()
    if not LABEL_RE.fullmatch(label):
        return bad_request("Label: 1-20 lowercase letters, numbers, - or _.")
    if not EMAIL_RE.fullmatch(email):
        return bad_request("That doesn't look like an email address.")

    with config_lock:
        config = load_config(required=False)
        if label in config["accounts"]:
            return bad_request(f"There's already an account called {label}.")
        config["accounts"][label] = email
        save_config(config)
    return jsonify(ok=True)


@app.post("/accounts/<label>/remove")
def remove_account(label):
    with config_lock:
        config = load_config(required=False)
        if label not in config["accounts"]:
            abort(404)
        del config["accounts"][label]
        save_config(config)
    token_path(label).unlink(missing_ok=True)   # forget the sign-in too
    logins.pop(label, None)
    return jsonify(ok=True)


def login_in_background(label, email):
    try:
        svc = login(label, email)   # opens the Google sign-in tab and waits (max 5 min)
        actual = get_address(svc)
        if actual.lower() != email.lower():
            token_path(label).unlink(missing_ok=True)
            logins[label] = {"state": "error", "message": f"You signed in as {actual}, not {email}. Try again."}
        else:
            logins[label] = {"state": "ok", "message": "Signed in"}
    except NotSignedIn:
        logins[label] = {"state": "error", "message": "Sign-in timed out. Try again."}
    except Exception as e:
        logins[label] = {"state": "error", "message": str(e)}


@app.post("/accounts/<label>/login")
def start_login(label):
    email = load_config(required=False)["accounts"].get(label)
    if email is None:
        abort(404)
    if logins.get(label, {}).get("state") == "waiting":
        return jsonify(logins[label]), 409
    logins[label] = {"state": "waiting", "message": "Finish signing in in the Google tab..."}
    threading.Thread(target=login_in_background, args=(label, email), daemon=True).start()
    return jsonify(logins[label])


@app.get("/status")
def status():
    return jsonify(**run_state, logins=logins)


if __name__ == "__main__":
    # 127.0.0.1 only: reachable from this computer, never the network
    app.run(host="127.0.0.1", port=5000, debug=True)
