import requests
import json
from gmail_client import get_service, get_recent_emails
from store import load_results, save_results
from render import write_html
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


def run_triage(accounts=("work", "personal", "school"), query="in:inbox newer_than:1d", limit=1):
    results = load_results()
    seen = {(r["account"], r["id"]) for r in results}

    for account in accounts:
        svc = get_service(account)
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
    out = write_html(load_results(), done=False)   # refresh the page first
    webbrowser.open(out.as_uri())                  # open it right away
    run_triage()