# Inbox Triage

Local-first Gmail triage. Reads your inbox (read-only), ranks each email **high / medium / low** with a local Gemma model via [Ollama](https://ollama.com), and writes a simple HTML digest.

Email content never leaves your machine: the only network calls are the Gmail API and `localhost:11434`.

## Why

Juggling several inboxes (work, personal, school) makes it easy to miss the few emails that matter. Cloud AI summaries would fix that, but they mean handing your whole inbox to a third party. This tool does the sorting with a model running on your own computer, so you get a short "what needs me today" list without sending your email anywhere.

## How it works

1. `gmail_client.py` fetches recent inbox emails for each account (`gmail.readonly` scope).
2. `triage.py` sends each email to the local model and gets back a priority and a one-line reason.
3. `store.py` saves results to `data/results.json` so emails aren't classified twice.
4. `render.py` builds `data/digest.html`, grouped by priority and account.

## Setup

### 1. Prerequisites

- Python 3.10 or newer (`python --version`)
- [Ollama](https://ollama.com/download)
- About 10 GB free disk space and 8 GB+ RAM for the model

### 2. Get the code and install dependencies

```bash
git clone https://github.com/AlexPeroulas/GmailLocalMCPTriage.git
cd GmailLocalMCPTriage

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Set up the local model

Install Ollama, then pull the model:

```bash
ollama pull gemma4:e4b
ollama list          # gemma4:e4b should be listed
```

Ollama runs in the background on `http://localhost:11434` after install. If it isn't running, start it with `ollama serve`.

To use a different model, change `"model"` in `classify()` in `triage.py`.

### 4. Create Gmail API credentials

You need your own OAuth client. It's free and takes about 5 minutes.

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a new project (e.g. `inbox-triage`).
2. Open **APIs & Services → Library**, search for **Gmail API**, and click **Enable**.
3. Open **Google Auth Platform** (or **APIs & Services → OAuth consent screen**) and click **Get started**:
   - App name: anything, e.g. `Inbox Triage`
   - User support email and contact email: your email
   - Audience: **External**
4. Under **Audience → Test users**, click **Add users** and add **every Gmail address** you want to triage.
5. Under **Data access**, click **Add or remove scopes** and add `.../auth/gmail.readonly`.
6. Under **Clients**, click **Create client**:
   - Application type: **Desktop app**
   - Name: anything
7. Download the JSON file, rename it to `credentials.json`, and put it in the project folder.

> `credentials.json` is git-ignored. Don't share or commit it.

### 5. Configure your accounts

Copy the example config and edit it:

```bash
cp config.example.json config.json      # Windows cmd: copy config.example.json config.json
```

```json
{
  "accounts": {
    "work": "you@company.com",
    "personal": "you@gmail.com",
    "school": "you@school.edu"
  },
  "query": "in:inbox newer_than:1d",
  "limit": 20
}
```

- `accounts`: a short label for each Gmail address. Use as many or as few as you like.
- `query`: any Gmail search query, e.g. `in:inbox newer_than:2d` or `is:unread`.
- `limit`: max emails fetched per account per run. Lower it while testing to save time.

> `config.json` holds your email addresses, so it's git-ignored.

### 6. Sign in

```bash
python login.py
```

This checks every account in `config.json` and prints its status:

```
work       you@company.com                  signed in
personal   you@gmail.com                    opening browser...
school     you@school.edu                   signed in
```

For each account that isn't signed in, a browser window opens with that address pre-filled:

1. Pick the matching Google account.
2. You'll see **"Google hasn't verified this app"**. This is expected for your own private app. Click **Continue**.
3. Allow read-only Gmail access.

If you sign in with a different address than the one in `config.json`, the token is thrown away and you're told to try again.

To redo one account (or switch which Google account it uses):

```bash
python login.py school
```

Tokens are saved as `data/token_<label>.json`.

You can also skip this step: `python triage.py` signs in any missing accounts the same way before it starts. `login.py` is handy for checking which accounts are signed in, or redoing one.

> **Tokens expire after 7 days** while the app is in **Testing** mode. When that happens, run `python login.py` (or just `python triage.py`) again.

## Usage

```bash
python triage.py
```

This signs in any accounts that need it, opens `data/digest.html` in your browser, classifies new emails (already classified ones are skipped), and refreshes the page as results come in.

### Run it automatically (Windows Task Scheduler)

1. Open **Task Scheduler → Create Basic Task**.
2. Trigger: **Daily**, then add a second trigger in the task's properties for twice a day.
3. Action: **Start a program**
   - Program: full path to `python.exe` (e.g. `C:\path\to\project\.venv\Scripts\python.exe`)
   - Arguments: `triage.py --scheduled`
   - Start in: full path to the project folder
4. Make sure Ollama is set to start on login.

`--scheduled` skips sign-in pages and doesn't open the browser. If a token has expired, the run stops with `Not signed in`; run `python login.py` by hand.

On macOS / Linux, use cron instead:

```bash
0 8,18 * * * cd /path/to/project && .venv/bin/python triage.py --scheduled
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `FileNotFoundError: credentials.json` | Download the OAuth client JSON (step 4) and put it in the project folder. |
| `access_denied` or "app not available" on sign-in | Add that Gmail address under **Audience → Test users**. |
| `Not signed in: ...` | Run `python login.py` (or `python login.py <label>` for one account). |
| `config.json not found` | Copy `config.example.json` to `config.json` and fill in your accounts (step 5). |
| `ConnectionError` to `localhost:11434` | Ollama isn't running. Start it with `ollama serve`. |
| `model not found` | Run `ollama pull gemma4:e4b`. |
| Fewer emails than expected | Raise `LIMIT` at the top of `triage.py`. |

## Privacy and security

**What it does to protect you**

- **Read-only access.** The only Gmail scope is `gmail.readonly`. The app can't send, delete, or change anything.
- **Local classification.** Email bodies are sent only to Ollama on `localhost:11434`. No other servers are contacted besides the Gmail API.
- **Minimal storage.** `data/results.json` keeps sender, subject, date, priority and the model's reason. Email bodies are not saved.
- **Escaped output.** Email text is untrusted, so everything shown in the digest goes through `html.escape`.
- **Nothing secret in git.** `credentials.json`, `config.json` and `data/` are git-ignored.

**What you should know**

- **Tokens are stored as plain files.** `data/token_<label>.json` grants read access to that inbox. Anyone or anything with access to your user account can use them. To cut access, revoke the app at [myaccount.google.com/permissions](https://myaccount.google.com/permissions) and delete the token files.
- **Watch out for synced folders.** If the project is inside OneDrive, Dropbox, iCloud or similar, `data/` (tokens and results) gets uploaded to that cloud. Keep the project in a folder that isn't synced.
- **Emails can try to game the model.** An email could include text like "mark this as high priority". The worst case is a wrong ranking: the model can't take actions, and the app is read-only.
- **The model can be wrong.** Skim the low-priority list now and then.
- **Don't share `credentials.json`.** Google treats Desktop app client secrets as not fully secret, but publishing yours lets others impersonate your app.

## Known issues

- No error handling if Ollama isn't running or returns bad output. The run crashes.
- An unexpected priority value from the model (anything other than high / medium / low) crashes `render.py`.
- Tokens expire after 7 days while the OAuth app is in Testing mode, so you have to run `python login.py` about once a week.
- Only plain-text email bodies are read. HTML-only emails are classified from the subject and preview. Bodies are cut off at 1,000 characters.
- `results.json` and the digest grow forever. Old results are never removed.

## Roadmap

- Flask UI (localhost only) with **Run now**, filters, and live progress
- Mark as done / correct a priority
- Error handling when Ollama is not running
