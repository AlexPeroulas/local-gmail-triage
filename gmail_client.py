from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import base64


SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
BASE = Path(__file__).resolve().parent


def get_service(account):
    token_path = BASE / f"token_{account}.json"
    creds = None

    if(token_path.exists()):
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if(not creds or not creds.valid):
        if (creds and creds.expired and creds.refresh_token):
            creds.refresh(Request())

        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(BASE / "credentials.json"), SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.write_text(creds.to_json())

    

    return build("gmail", "v1", credentials = creds)

def get_body(payload):
    # Case 1: this piece is plain text, so decode and return it
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            data += "=" * (-len(data) % 4)   # fix missing base64 padding
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    # Case 2: this piece contains smaller pieces, so search inside them
    for part in payload.get("parts", []):
        text = get_body(part)
        if text:
            return text

    # Nothing found
    return ""

def get_recent_emails(svc, query, limit):

    emails = [] 
    result = svc.users().messages().list(userId = "me", q=query, maxResults = limit).execute()

    for m in result.get("messages", []):
        msg = svc.users().messages().get(
            userId="me",
            id=m["id"],
            format="full",
        ).execute()

        h = {x["name"]: x["value"] for x in msg["payload"]["headers"]}
        emails.append({
            "id": m["id"],
            "from" : h.get("From", ""),
            "subject" : h.get("Subject", ""),
            "date" : h.get("Date", ""),
            "snippet" : msg.get("snippet", ""),
            "body": get_body(msg["payload"])[:1000],
        }) 

    return emails


    
if __name__ == "__main__":
    svc = get_service("school")
    for e in get_recent_emails(svc, "in:inbox", 5):
        print("\n------Email------\n" + e["subject"], "| body :", e["body"])