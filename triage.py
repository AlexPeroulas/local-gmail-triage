import requests
import json
from gmail_client import get_service, get_recent_emails, NotSignedIn
from store import load_results, save_results, load_config
from render import write_html
from login import sign_in
import sys
import webbrowser


prompt_instructions = """Rate the priority of this email for a college CS student.

high: interview or recruiter emails, deadlines within 3 days, professors or TAs, security alerts
medium: deadlines within 1 week, class announcements, club or team logistics
low: spam, promotions, newsletters, automated notifications

Reply with JSON only, in exactly this format:
{"priority": "high|medium|low", "reason": "one short sentence"}"""


def classify(email):
    email_text = f"From: {email['from']}\nSubject: {email['subject']}\nPreview: {email['snippet']}\nBody: {email['body']}"
    prompt = prompt_instructions + "\nEmail: " + email_text

    payload = {
        "model": "gemma4:e4b",
        "keep_alive": "1m",
        "think": False,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0}
    }

    response = requests.post("http://localhost:11434/api/chat", json=payload)
    reply = response.json()
    answer = json.loads(reply["message"]["content"])
    return answer["priority"], answer["reason"]


def get_services(accounts, scheduled):
    # sign in to every account first, before the slow classification
    services, missing = {}, []
    for account, address in accounts.items():
        try:
            services[account] = get_service(account)
        except NotSignedIn:
            if scheduled:   # nobody is around to finish a browser sign-in
                missing.append(account)
                continue
            svc = sign_in(account, address)
            if svc is None:
                missing.append(account)
            else:
                services[account] = svc
    if missing:
        raise SystemExit(f"Not signed in: {', '.join(missing)}. Run: python login.py")
    return services


def run_triage(scheduled=False):
    config = load_config()
    query, limit = config["query"], config["limit"]
    services = get_services(config["accounts"], scheduled)

    results = load_results()
    if not scheduled:   # open the page once sign-ins are done
        out = write_html(results, done=False)
        webbrowser.open(out.as_uri())

    seen = {(r["account"], r["id"]) for r in results}

    for account, svc in services.items():
        for e in get_recent_emails(svc, query, limit):
            if (account, e["id"]) in seen:
                continue
            priority, reason = classify(e)
            results.append({
                "id": e["id"], "account": account, "from": e["from"],
                "subject": e["subject"], "date": e["date"],
                "priority": priority.lower(), "reason": reason,
            })
            save_results(results)
            write_html(results, done=False)

    write_html(results, done=True)


if __name__ == "__main__":
    # --scheduled: for Task Scheduler / cron (no sign-in pages, no browser)
    run_triage("--scheduled" in sys.argv)