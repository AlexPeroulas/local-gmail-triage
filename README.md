# Inbox Triage

Local-first Gmail triage. Reads your inbox (read-only), ranks each email **high / medium / low** with a local Gemma model via [Ollama](https://ollama.com), and writes a simple HTML digest.

Email content never leaves your machine: the only network calls are the Gmail API and `localhost:11434`.

## How it works

1. `gmail_client.py` fetches recent inbox emails for each account (`gmail.readonly` scope).
2. `triage.py` sends each email to the local model and gets back a priority and a one-line reason.
3. `store.py` saves results to `results.json` so emails aren't classified twice.
4. `render.py` builds `digest.html`, grouped by priority and account.

## Setup

**Requirements:** Python 3.10+, [Ollama](https://ollama.com)

```bash
pip install -r requirements.txt
ollama pull gemma4:e4b
```

**Gmail API credentials:**

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the **Gmail API**.
2. Configure the OAuth consent screen and add your Gmail address(es) as test users.
3. Create an **OAuth client ID** of type **Desktop app**, download it, and save it as `credentials.json` in the project folder.

On first run, a browser window opens for each account to sign in. Tokens are saved as `token_<account>.json`.

## Usage

```bash
python triage.py          # classify new emails and update digest.html
```

The digest opens in your browser and refreshes while emails are being classified.

Accounts (`work`, `personal`, `school`), the Gmail search query, and the per-account limit are set in `run_triage()` in `triage.py`.

To run it automatically, schedule `python triage.py` with Windows Task Scheduler (or cron).

## Privacy

- Gmail access is read-only.
- Classification runs entirely on your machine through Ollama.
- `credentials.json`, `token*.json`, `results.json`, `digest.html` and logs are git-ignored. Never commit them.

## Roadmap

- Flask UI (localhost only) with **Run now**, filters, and live progress
- Mark as done / correct a priority
- Error handling when Ollama is not running
