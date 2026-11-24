import hashlib
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import quote
from flask import Flask, abort, jsonify, render_template, request
from gmail_client import login, get_address, is_signed_in, token_path, NotSignedIn, get_service, get_email
from store import (load_results, load_actions, save_actions, action_key,
                   load_meta, load_config, save_config, sender_address,
                   load_corrections, save_corrections, load_rules, save_rules, effective_priority,
                   load_labels, save_labels,
                   DEFAULT_HIDE_AFTER, DEFAULT_TYPES)
from triage import run_triage, warm_up, build_prompt, pick_examples

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024   # caps dataset imports
# the page polls /status every second during a run; keep those out of the console
logging.getLogger("werkzeug").addFilter(lambda r: "/status" not in r.getMessage())
ALLOWED_HOSTS = {"127.0.0.1:5000", "localhost:5000"}
LEVELS = ("high", "medium", "low")
LABEL_RE = re.compile(r"[a-z0-9_-]{1,20}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

# state of the background run, shared with /status
run_state = {"running": False, "message": "", "error": None, "step": None}   # step: [done, total] while classifying
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
    # inbox-style time with the clock: "12m · 2:14 PM", "11:32 AM", "Yesterday 6:00 PM", "Mon 6:00 PM", "Oct 12, 6:00 PM"
    if dt is None:
        return ""
    if now - dt < timedelta(hours=1):
        return f"{max(1, (now - dt).seconds // 60)}m · {clock(dt)}"
    if dt.date() == now.date():
        return clock(dt)
    if dt.date() == (now - timedelta(days=1)).date():
        return f"Yesterday {clock(dt)}"
    if now - dt < timedelta(days=7):
        return f"{dt:%a} {clock(dt)}"
    if dt.year == now.year:
        return f"{dt:%b} {dt.day}, {clock(dt)}"
    return f"{dt:%b} {dt.day}, {dt.year}"


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

    # unhandled emails past their priority's cutoff go to "Older" (hidden, not deleted)
    hide_after = {**DEFAULT_HIDE_AFTER, **config.get("hide_after", {})}
    def is_old(r):
        days = hide_after.get(r["priority"])
        return days is not None and r["dt"] is not None and now - r["dt"] > timedelta(days=days)
    # emails from "Collect more" (Dataset tab) are for labelling only, never in the Inbox
    active = [r for r in results if action_key(r) not in actions and not r.get("collected")]
    older = [r for r in active if is_old(r)]
    hide_note = ", ".join(f"{level} after {days} day{'s' if days != 1 else ''}"
                          for level, days in hide_after.items() if days is not None)
    groups = {}   # priority -> emails
    for level in LEVELS:
        level_group = [r for r in active if r["priority"] == level and not is_old(r)]
        if level_group:
            groups[level] = level_group

    last_checked = ""
    if meta.get("last_run"):
        last_run = datetime.fromisoformat(meta["last_run"]).astimezone()
        last_checked = f"Checked {day_and_clock(last_run, now)} · {meta.get('added', 0)} new"
        if meta.get("speed"):
            last_checked += f" · {meta['speed']}"

    accounts = [{"label": label, "email": email, "signed_in": is_signed_in(label), "login": logins.get(label)}
                for label, email in config["accounts"].items()]
    # filter shows configured accounts, plus any removed ones that still have results
    filter_accounts = list(config["accounts"]) + sorted({r["account"] for r in results} - set(config["accounts"]))

    # Dataset tab: emails you haven't labelled yet (shuffled in the page) and label counts
    labels = load_labels()
    review = [{"account": r["account"], "id": r["id"], "sender": r["sender"], "from": r["from"],
               "subject": r["subject"], "time": r["time"], "model": r["model_priority"], "reason": r["reason"],
               "gmail_url": r["gmail_url"]}
              for r in results if action_key(r) not in labels]
    dataset = {group: {level: 0 for level in LEVELS} for group in ("train", "test", "synthetic")}
    types = config.get("types", DEFAULT_TYPES)
    type_counts = {t: 0 for t in types}
    agree = real = 0
    for l in labels.values():
        if l.get("type"):
            type_counts[l["type"]] = type_counts.get(l["type"], 0) + 1
        dataset["synthetic" if l["source"] == "synthetic" else l["split"]][l["label"]] += 1
        if l["source"] != "synthetic":
            real += 1
            agree += l["label"] == l["model"]

    # every label, newest first, for the "All labelled emails" list (made-up ones have no Gmail link)
    labelled = sorted(({"key": k, "sender": sender_name(l.get("from", "")), "subject": l.get("subject", ""),
                        "label": l["label"], "type": l.get("type", ""), "model": l.get("model", ""),
                        "group": "made-up" if l["source"] == "synthetic" else l["split"], "source": l["source"],
                        "at": l.get("at", ""),
                        "gmail_url": gmail_link(config["accounts"].get(l["account"]), l["id"]) if l.get("id") else ""}
                       for k, l in labels.items()), key=lambda l: l["at"], reverse=True)

    recent_corrections = sorted(({"key": k, **c} for k, c in corrections.items()),
                                key=lambda c: c["at"], reverse=True)[:20]

    return render_template("index.html", groups=groups, older=older, hide_after=hide_after, hide_note=hide_note, handled=handled, state=run_state,
                           last_checked=last_checked, config=config, accounts=accounts,
                           filter_accounts=filter_accounts, rules=rules["rules"], notes=rules["notes"],
                           corrections=recent_corrections, correction_count=len(corrections),
                           review=review, dataset=dataset, agree=agree, real_labels=real,
                           types=types, type_counts=type_counts, labelled=labelled)


def run_in_background(query=None, limit=None):
    try:
        run_triage(allow_login=False, open_page=False, query=query, limit=limit,
                   on_progress=lambda m, step: run_state.update(message=m, step=step))
    except (Exception, SystemExit) as e:   # shown on the page instead of killing the thread
        run_state["error"] = str(e)
    finally:
        run_state["running"] = False
        run_lock.release()


@app.post("/run")
def run_now():
    # optional body {"query", "limit"}: collect emails for the Dataset tab without touching Settings
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    query = limit = None
    if "query" in data:
        query = str(data["query"]).strip()
        try:
            limit = int(data.get("limit"))
        except (TypeError, ValueError):
            return bad_request("Number of emails must be a number.")
        if not query or len(query) > 200:
            return bad_request("Search can't be empty (max 200 characters).")
        if not 1 <= limit <= 500:
            return bad_request("Number of emails must be between 1 and 500.")
    if not load_config(required=False)["accounts"]:
        return jsonify(error="Add an account in Settings first."), 400
    if not run_lock.acquire(blocking=False):   # a run is already going
        return jsonify(run_state), 409
    run_state.update(running=True, message="Starting...", error=None, step=None)
    threading.Thread(target=run_in_background, args=(query, limit), daemon=True).start()
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
    # body: {"account", "id", "priority": "high" | "medium" | "low", "note": "optional why",
    #        "remember": true to keep the note as an instruction for every email from this sender}
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
        labels = load_labels()
        labels[key] = label_entry(r, priority, "correction", labels.get(key, {}).get("type", ""))   # keep a type set in Review
        save_labels(labels)

        rules = load_rules()
        if data.get("remember") and note and sender:
            rules["notes"][sender] = note
            save_rules(rules)

        # offer a sender rule once the same fix has been made SUGGEST_AFTER times
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
        labels = load_labels()
        if labels.get(key, {}).get("source") == "correction":   # the label came from this correction
            labels.pop(key)
            save_labels(labels)
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


# ---- Dataset: confirmed labels for training ----

def split_for(key):
    # a fixed ~20% of real emails are test data, picked by hash so it never changes
    return "test" if int(hashlib.sha1(key.encode()).hexdigest(), 16) % 5 == 0 else "train"


def label_entry(r, label, source, type_=""):
    key = action_key(r)
    return {"label": label, "type": type_, "model": r["priority"], "source": source, "split": split_for(key),
            "account": r["account"], "id": r["id"], "from": r["from"], "subject": r["subject"],
            "date": r["date"], "at": datetime.now().isoformat(timespec="seconds")}


@app.post("/labels")
def set_label():
    # body: {"account", "id", "label": "high" | "medium" | "low" | null (undo)}
    data = request.get_json(silent=True) or {}
    label = data.get("label")
    if label not in (*LEVELS, None) or not data.get("account") or not data.get("id"):
        abort(400)
    type_ = data.get("type") or ""
    if type_ and type_ not in load_config(required=False).get("types", DEFAULT_TYPES):
        return bad_request("Unknown type.")
    key = action_key(data)
    r = next((r for r in load_results() if action_key(r) == key), None)
    if r is None:
        abort(404)
    with learn_lock:
        labels = load_labels()
        if label is None:
            labels.pop(key, None)
        else:
            labels[key] = label_entry(r, label, "review", type_)
        save_labels(labels)
    return jsonify(ok=True, split=split_for(key))


gmail_lock = threading.Lock()   # the Gmail client isn't thread-safe
services = {}                   # account -> Gmail service, reused between review fetches


@app.get("/review/email")
def review_email():
    # the email as the model sees it, plus the full prompt it would get today. Fetched live from Gmail, not stored.
    account, message_id = request.args.get("account", ""), request.args.get("id", "")
    r = next((r for r in load_results() if r["account"] == account and r["id"] == message_id), None)
    if r is None:
        abort(404)
    try:
        with gmail_lock:
            if account not in services:
                services[account] = get_service(account)
            email = get_email(services[account], message_id)
    except NotSignedIn:
        return jsonify(error=f"{account} isn't signed in. Sign in from Settings."), 409
    except Exception as e:   # deleted email, network down, revoked token
        services.pop(account, None)
        return jsonify(error=f"Couldn't load from Gmail: {e}"), 502
    sender = sender_address(email["from"])
    prompt = build_prompt(email, pick_examples(load_corrections(), sender), load_rules()["notes"].get(sender, ""))
    return jsonify(email={k: email[k] for k in ("from", "subject", "snippet", "body")}, prompt=prompt)


@app.post("/labels/import")
def import_labels():
    # body: {"emails": [{"from", "subject", "body", "label", "type" (optional)}, ...]}: made-up emails for training
    data = request.get_json(silent=True)
    emails = data if isinstance(data, list) else data.get("emails") if isinstance(data, dict) else None   # a bare list works too
    if not isinstance(emails, list) or not 1 <= len(emails) <= 2000:
        return bad_request("Expected {\"emails\": [...]} with 1-2000 emails.")
    clean = []
    for n, e in enumerate(emails, 1):
        if not isinstance(e, dict) or e.get("label") not in LEVELS:
            return bad_request(f"Email {n}: label must be high, medium or low.")
        fields = {f: str(e.get(f) or "")[:limit] for f, limit in
                  (("from", 200), ("subject", 300), ("body", 1000), ("type", 40))}
        if not fields["subject"] and not fields["body"]:
            return bad_request(f"Email {n}: needs a subject or body.")
        clean.append({**fields, "label": e["label"]})
    with learn_lock:
        labels = load_labels()
        added = 0
        for e in clean:
            key = "synthetic:" + hashlib.sha1(f"{e['from']}|{e['subject']}|{e['body']}".encode()).hexdigest()[:16]
            if key not in labels:   # importing the same file twice adds nothing
                added += 1
            labels[key] = {**e, "model": None, "source": "synthetic", "split": "train",
                           "at": datetime.now().isoformat(timespec="seconds")}
        save_labels(labels)
    return jsonify(ok=True, added=added, skipped=len(clean) - added)


@app.post("/notes/remove")
def remove_note():
    sender = str((request.get_json(silent=True) or {}).get("sender", ""))
    with learn_lock:
        rules = load_rules()
        if rules["notes"].pop(sender, None) is None:
            abort(404)
        save_rules(rules)
    return jsonify(ok=True)


# ---- Settings ----

def bad_request(message):
    return jsonify(error=message), 400


@app.post("/settings")
def save_settings():
    # body: {"query": "...", "limit": 20} and/or {"hide_after": {"high": null, "medium": 10, "low": 2}}
    data = request.get_json(silent=True) or {}
    update = {}
    if "query" in data or "limit" in data:
        query = str(data.get("query", "")).strip()
        try:
            limit = int(data.get("limit"))
        except (TypeError, ValueError):
            return bad_request("Limit must be a number.")
        if not query or len(query) > 200:
            return bad_request("Query can't be empty (max 200 characters).")
        if not 1 <= limit <= 500:
            return bad_request("Limit must be between 1 and 500.")
        update.update(query=query, limit=limit)
    if "hide_after" in data:
        raw = data["hide_after"] if isinstance(data["hide_after"], dict) else {}
        hide_after = {}
        for level in LEVELS:
            value = raw.get(level)
            if value in (None, ""):
                hide_after[level] = None   # never hide
                continue
            try:
                days = int(value)
            except (TypeError, ValueError):
                return bad_request("Days must be a number.")
            if not 1 <= days <= 365:
                return bad_request("Days must be between 1 and 365, or blank for never.")
            hide_after[level] = days
        update["hide_after"] = hide_after
    if "types" in data:
        raw = data["types"] if isinstance(data["types"], list) else []
        types = list(dict.fromkeys(str(t).strip()[:40] for t in raw if str(t).strip()))   # unique, in order
        if not 1 <= len(types) <= 24:
            return bad_request("Add between 1 and 24 types.")
        update["types"] = types
    if not update:
        return bad_request("Nothing to save.")

    with config_lock:
        config = load_config(required=False)
        config.update(update)
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
    threading.Thread(target=warm_up, daemon=True).start()
    # 127.0.0.1 only: reachable from this computer, never the network
    app.run(host="127.0.0.1", port=5000, debug=True)
