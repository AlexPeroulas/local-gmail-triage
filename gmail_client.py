from pathlib import Path
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import base64
from html.parser import HTMLParser


SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
BASE = Path(__file__).resolve().parent
DATA = BASE / "data"


class NotSignedIn(Exception):
    pass


def token_path(account):
    return DATA / f"token_{account}.json"


def get_service(account):
    # uses the saved token only; never opens a browser (see login())
    path = token_path(account)
    if not path.exists():
        raise NotSignedIn(account)

    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if not creds.valid:
        if not (creds.expired and creds.refresh_token):
            raise NotSignedIn(account)
        try:
            creds.refresh(Request())
        except RefreshError:   # expired or revoked
            raise NotSignedIn(account)
        path.write_text(creds.to_json())

    return build("gmail", "v1", credentials = creds)


def login(account, email):
    # opens the Google sign-in page with the account's address pre-filled
    flow = InstalledAppFlow.from_client_secrets_file(str(BASE / "credentials.json"), SCOPES)
    try:
        creds = flow.run_local_server(port=0, login_hint=email, prompt="select_account",
                                      timeout_seconds=300)   # give up if the Google tab is closed
    except AttributeError:   # the library's way of saying it timed out
        raise NotSignedIn(account)
    DATA.mkdir(exist_ok=True)
    token_path(account).write_text(creds.to_json())
    return build("gmail", "v1", credentials = creds)


def is_signed_in(account):
    # quick offline check for the Settings page; a revoked token still shows up at run time
    path = token_path(account)
    if not path.exists():
        return False
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    return creds.valid or bool(creds.refresh_token)


def get_address(svc):
    return svc.users().getProfile(userId="me").execute()["emailAddress"]

def get_body(payload, mime="text/plain"):
    # Case 1: this piece has the type we want, so decode and return it
    if payload.get("mimeType") == mime:
        data = payload.get("body", {}).get("data", "")
        if data:
            data += "=" * (-len(data) % 4)   # fix missing base64 padding
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    # Case 2: this piece contains smaller pieces, so search inside them
    for part in payload.get("parts", []):
        text = get_body(part, mime)
        if text:
            return text

    # Nothing found
    return ""

class _TextOnly(HTMLParser):
    # keeps visible text, drops tags plus <style>/<script>/<head> contents
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0
    def handle_starttag(self, tag, attrs):
        self.skip += tag in ("style", "script", "head")
    def handle_endtag(self, tag):
        self.skip -= tag in ("style", "script", "head") and self.skip > 0
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

def html_to_text(html):
    p = _TextOnly()
    p.feed(html)
    return " ".join(" ".join(p.parts).split())

def get_text(payload):
    # plain text if the email has it, otherwise the HTML part with tags stripped
    return get_body(payload) or html_to_text(get_body(payload, "text/html"))

def get_recent_emails(svc, query, limit, skip=frozenset()):
    # newest matching emails not in skip, up to limit. Listing IDs is cheap, so page past
    # already-classified ones; only the new ones are downloaded.
    ids, page = [], None
    for _ in range(10):   # shortcut: stops after 5000 matches, enough unless the search spans years
        result = svc.users().messages().list(userId="me", q=query, maxResults=500, pageToken=page).execute()
        ids += [m["id"] for m in result.get("messages", []) if m["id"] not in skip]
        page = result.get("nextPageToken")
        if len(ids) >= limit or not page:
            break

    return [get_email(svc, message_id) for message_id in ids[:limit]]


def get_email(svc, message_id):
    # one email, in the shape the model sees it (body cut to 1,000 characters)
    msg = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
    h = {x["name"]: x["value"] for x in msg["payload"]["headers"]}
    return {
        "id": message_id,
        "from": h.get("From", ""),
        "subject": h.get("Subject", ""),
        "date": h.get("Date", ""),
        "snippet": msg.get("snippet", ""),
        "body": get_text(msg["payload"])[:1000],
    }


    
if __name__ == "__main__":
    svc = get_service("school")
    for e in get_recent_emails(svc, "in:inbox", 5):
        print("\n------Email------\n" + e["subject"], "| body :", e["body"])