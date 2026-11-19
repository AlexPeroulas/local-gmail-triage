import requests
import json
from gmail_client import get_service, get_recent_emails, NotSignedIn
from store import (load_results, save_results, load_config, save_meta,
                   load_corrections, load_rules, sender_address)
from datetime import datetime
from render import write_html
from login import sign_in
import store
import sys
import webbrowser


prompt_instructions = """Rate the priority of this email for a college CS student.

high: interview or recruiter emails, deadlines within 3 days, professors or TAs, security alerts
medium: deadlines within 1 week, class announcements, club or team logistics
low: spam, promotions, newsletters, automated notifications

Reply with JSON only, in exactly this format:
{"priority": "high|medium|low", "reason": "one short sentence"}"""


def pick_examples(corrections, sender, n=8):
    # your past corrections, most relevant first: same sender, then same domain, then newest
    domain = sender.split("@")[-1]
    def score(c):
        return (2 if c["sender"] == sender else 1 if c["sender"].split("@")[-1] == domain else 0, c["at"])
    return sorted(corrections.values(), key=score, reverse=True)[:n]


def examples_text(examples):
    if not examples:
        return ""
    lines = []
    for c in examples:
        line = f'- From: {c["from"]} | Subject: {c["subject"]} -> {c["new"]} (not {c["old"]})'
        if c.get("note"):
            line += f'. Why: {c["note"]}'
        lines.append(line)
    return ("\n\nThe user corrected these earlier ratings. Rate similar emails the same way:\n"
            + "\n".join(lines))


MODEL = "gemma4:e4b"
KEEP_ALIVE = "5m"   # how long Ollama keeps the model in memory after the last request


def warm_up():
    # an empty request loads the model so the first email isn't slowed by the load
    try:
        requests.post("http://localhost:11434/api/generate",
                      json={"model": MODEL, "keep_alive": KEEP_ALIVE}, timeout=120)
    except requests.RequestException:
        pass   # Ollama not running: Run now reports that itself


def classify(email, examples=()):
    email_text = f"From: {email['from']}\nSubject: {email['subject']}\nPreview: {email['snippet']}\nBody: {email['body']}"
    prompt = prompt_instructions + examples_text(examples) + "\nEmail: " + email_text

    payload = {
        "model": MODEL,
        "keep_alive": KEEP_ALIVE,
        "think": False,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0}
    }

    response = requests.post("http://localhost:11434/api/chat", json=payload)
    reply = response.json()
    answer = json.loads(reply["message"]["content"])
    ns = 1e9   # Ollama reports durations in nanoseconds
    stats = {"seconds": reply.get("total_duration", 0) / ns,
             "load": reply.get("load_duration", 0) / ns,
             "tokens": reply.get("eval_count", 0),
             "tok_s": reply.get("eval_count", 0) / max(reply.get("eval_duration", 0) / ns, 1e-9)}
    return answer["priority"], answer["reason"], stats


def log_speed(line):
    # timings only (account label, no email content), so the file is safe to open
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {line}"
    print(line)
    store.DATA.mkdir(exist_ok=True)
    with open(store.DATA / "speed.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


class TriageError(Exception):
    pass


def get_services(accounts, allow_login):
    # sign in to every account first, before the slow classification
    services, missing = {}, []
    for account, address in accounts.items():
        try:
            services[account] = get_service(account)
        except NotSignedIn:
            if not allow_login:   # nobody is around to finish a browser sign-in
                missing.append(account)
                continue
            svc = sign_in(account, address)
            if svc is None:
                missing.append(account)
            else:
                services[account] = svc
    if missing:
        raise TriageError(f"Not signed in: {', '.join(missing)}. Run: python login.py")
    return services


def run_triage(allow_login=True, open_page=True, on_progress=None):
    def progress(message):
        if on_progress:
            on_progress(message)

    config = load_config()
    query, limit = config["query"], config["limit"]
    progress("Checking sign-ins...")
    services = get_services(config["accounts"], allow_login)

    results = load_results()
    if open_page:   # open the page once sign-ins are done
        out = write_html(results, done=False)
        webbrowser.open(out.as_uri())

    seen = {(r["account"], r["id"]) for r in results}
    corrections = load_corrections()
    rules = load_rules()["rules"]
    added = 0
    timings = []   # Ollama stats per model call
    run_id = datetime.now().isoformat(timespec="seconds")   # tags every email added by this run

    for account, svc in services.items():
        progress(f"Fetching up to {limit} emails from {account}...")
        emails = get_recent_emails(svc, query, limit)
        new = [e for e in emails if (account, e["id"]) not in seen]
        skipped = len(emails) - len(new)

        for i, e in enumerate(new, 1):
            progress(f"{account}: classifying {i} of {len(new)}"
                     + (f" ({skipped} already done)" if skipped else ""))
            sender = sender_address(e["from"])
            if sender in rules:   # your rule decides; no need to ask the model
                priority, reason = rules[sender], f"Sender rule: always {rules[sender]}"
            else:
                priority, reason, s = classify(e, pick_examples(corrections, sender))
                timings.append(s)
                log_speed(f"{account} {i}/{len(new)}: {s['seconds']:.1f}s "
                          f"(load {s['load']:.1f}s), {s['tokens']} tokens, {s['tok_s']:.1f} tok/s")
            results.append({
                "id": e["id"], "account": account, "from": e["from"],
                "subject": e["subject"], "date": e["date"],
                "priority": priority.lower(), "reason": reason, "run": run_id,
            })
            added += 1
            save_results(results)
            write_html(results, done=False)

    write_html(results, done=True)
    speed = ""
    if timings:
        total = sum(t["seconds"] for t in timings)
        speed = (f"{total / len(timings):.1f}s per email, "
                 f"{sum(t['tok_s'] for t in timings) / len(timings):.0f} tok/s")
        log_speed(f"Run {run_id} done: {len(timings)} emails, {total:.0f}s total, {speed}")
    save_meta({"last_run": datetime.now().isoformat(timespec="seconds"), "run": run_id,
               "added": added, "speed": speed})
    progress(f"Finished: {added} new emails")

if __name__ == "__main__":
    scheduled = "--scheduled" in sys.argv
    try:
        run_triage(allow_login=not scheduled, open_page=not scheduled)
    except TriageError as e:
        sys.exit(str(e))