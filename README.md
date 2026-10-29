# Inbox Triage

Local-first Gmail triage. Reads your inbox (read-only), ranks each email **high / medium / low** with a local Gemma model via [Ollama](https://ollama.com), and writes a simple HTML digest.

Email content never leaves your machine: the only network calls are the Gmail API and `localhost:11434`.

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

Edit the settings at the top of `triage.py`:

```python
ACCOUNTS = ("work", "personal", "school")
QUERY = "in:inbox newer_than:1d"
LIMIT = 20
```

- `ACCOUNTS`: one label per Gmail account. The labels are only names; use as many or as few as you like. For a single account, keep the trailing comma: `("personal",)`.
- `QUERY`: any Gmail search query, e.g. `in:inbox newer_than:2d` or `is:unread`.
- `LIMIT`: max emails fetched per account per run. Lower it while testing to save time.

### 6. First run and sign-in

```bash
python triage.py
```

For each account label, a browser window opens to sign in:

1. Sign in with the Gmail account that matches that label (all sign-ins happen up front, in the order listed, before any emails are classified).
2. You'll see **"Google hasn't verified this app"**. This is expected for your own private app. Click **Continue**.
3. Allow read-only Gmail access.

A token is saved as `data/token_<label>.json`, so later runs don't ask again.

> **Tokens expire after 7 days** while the app is in **Testing** mode. If you get an auth error, delete `data/token_<label>.json` and sign in again.

## Usage

```bash
python triage.py
```

This opens `data/digest.html` in your browser, classifies new emails (already classified ones are skipped), and refreshes the page as results come in.

### Run it automatically (Windows Task Scheduler)

1. Open **Task Scheduler → Create Basic Task**.
2. Trigger: **Daily**, then add a second trigger in the task's properties for twice a day.
3. Action: **Start a program**
   - Program: full path to `python.exe` (e.g. `C:\path\to\project\.venv\Scripts\python.exe`)
   - Arguments: `triage.py`
   - Start in: full path to the project folder
4. Make sure Ollama is set to start on login.

On macOS / Linux, use cron instead:

```bash
0 8,18 * * * cd /path/to/project && .venv/bin/python triage.py
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `FileNotFoundError: credentials.json` | Download the OAuth client JSON (step 4) and put it in the project folder. |
| `access_denied` or "app not available" on sign-in | Add that Gmail address under **Audience → Test users**. |
| `invalid_grant` / token errors | Delete `data/token_<label>.json` and run again. |
| `ConnectionError` to `localhost:11434` | Ollama isn't running. Start it with `ollama serve`. |
| `model not found` | Run `ollama pull gemma4:e4b`. |
| Fewer emails than expected | Raise `LIMIT` at the top of `triage.py`. |

## Privacy

- Gmail access is read-only.
- Classification runs entirely on your machine through Ollama.
- `credentials.json` and everything in `data/` (tokens, results, digest) are git-ignored. Never commit them.

## Roadmap

- Flask UI (localhost only) with **Run now**, filters, and live progress
- Mark as done / correct a priority
- Error handling when Ollama is not running
