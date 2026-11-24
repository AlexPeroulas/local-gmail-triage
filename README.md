# Inbox Triage

Local-first Gmail triage across several accounts. Reads your inboxes (read-only), ranks each email **high / medium / low** with a local Gemma model via [Ollama](https://ollama.com), and shows the result in a small web app that runs on your own computer. It learns from your corrections.

> **In progress:** I'm building a labelled dataset (the Dataset tab) to train a small local model that sorts emails by type (career, school, housing, money, ...) as well as priority, so the Inbox can be filtered by type.

Email content never leaves your machine: the only network calls are the Gmail API and `localhost:11434`.

## Why

Juggling several inboxes (work, personal, school) makes it easy to miss the few emails that matter. Cloud AI summaries would fix that, but they mean handing your whole inbox to a third party. This tool does the sorting with a model running on your own computer, so you get a short "what needs me today" list without sending your email anywhere.

## How it works

1. `gmail_client.py` signs in to each account (OAuth, `gmail.readonly` scope) and fetches recent emails. The model sees the sender, subject, Gmail's preview and the first 1,000 characters of the body (the plain-text part, or the HTML part with tags stripped if there is no plain text).
2. `triage.py` classifies each new email with the local model and gets back a priority and a one-line reason.
   - Senders with a **rule** skip the model.
   - Otherwise the prompt includes up to 8 of your past **corrections** as examples (same sender first, then same domain, then newest), plus your **sender instruction** if that sender has one.
3. `store.py` saves everything as JSON in `data/`, so emails are never classified twice.
4. `app.py` is a Flask app on `127.0.0.1:5000` that shows the results (`templates/index.html`), runs triage in the background, and saves your actions.
5. `render.py` also writes a static `data/digest.html` for scheduled runs.

Priority shown = your correction, else a sender rule, else the model's answer.

## Setup

### 1. Prerequisites

- Python 3.10 or newer (`python --version`)
- [Ollama](https://ollama.com/download)
- About 10 GB free disk space and 8 GB+ RAM for the model

### 2. Get the code and install dependencies

```bash
git clone https://github.com/AlexPeroulas/local-gmail-triage.git
cd local-gmail-triage

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

> On Windows PowerShell, if activating fails with "running scripts is disabled", run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

### 3. Set up the local model

Install Ollama, then pull the model:

```bash
ollama pull gemma4:e4b
ollama list          # gemma4:e4b should be listed
```

Ollama runs in the background on `http://localhost:11434` after install. If it isn't running, start it with `ollama serve`.

To use a different model, change `"model"` in `classify()` in `triage.py`. Any chat model in Ollama works; pick by your RAM:

| Model | Good for | Notes |
| --- | --- | --- |
| `gemma4:e4b` | 16 GB RAM (default) | Fast, good enough for a 3-level sort |
| `gemma4:e2b` | 8 GB RAM / older laptops | Faster, less accurate |
| `qwen3:8b` | 16 GB RAM | Slower than e4b in testing; keep thinking off (the app already sends `"think": false`) |
| `gemma3:12b` | 16 GB+ with a GPU | Larger; may be more accurate, noticeably slower |

#### Optional: run the model on your GPU

Ollama uses NVIDIA and AMD graphics cards automatically. For **Intel integrated graphics** (e.g. Intel Arc in Core Ultra laptops), it runs on the CPU by default. On a Core Ultra 7 256V, turning on the GPU made `gemma4:e4b` about 3x faster (roughly 10 → 30 tokens/s).

1. Update Ollama and your graphics driver.
2. Turn on Vulkan and allow integrated GPUs (Windows PowerShell):
   ```powershell
   [Environment]::SetEnvironmentVariable("OLLAMA_VULKAN", "1", "User")
   [Environment]::SetEnvironmentVariable("OLLAMA_IGPU_ENABLE", "1", "User")
   ```
   macOS / Linux: add `export OLLAMA_VULKAN=1 OLLAMA_IGPU_ENABLE=1` to your shell profile.
3. Quit Ollama (right-click the tray icon → Quit), close all terminals, then start it again: open a new terminal and run `ollama serve` (keep that window open), or start Ollama from the Start menu.
4. Check it:
   ```bash
   ollama run gemma4:e4b --verbose --think=false "Explain what an inbox is in 3 sentences."
   ollama ps        # PROCESSOR should say GPU, not 100% CPU
   ```
   Compare the **eval rate** with and without the GPU. The first run after starting Ollama is slower while the model loads.

To turn it off, set both variables to `$null` the same way and restart Ollama (quit it from the tray, then `ollama serve`). Vulkan support in Ollama is still marked experimental; the variable names may change between versions.

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
  "limit": 20,
  "hide_after": {"high": null, "medium": 10, "low": 2}
}
```

- `accounts`: a short label for each Gmail address. Use as many or as few as you like.
- `query`: any Gmail search query, e.g. `in:inbox newer_than:2d` or `is:unread`.
- `limit`: max new (not yet classified) emails per account per run (1-500). Lower it while testing to save time.
- `hide_after`: days before an unhandled email of that priority leaves the Inbox (`null` = never). Optional; these are the defaults.

All of these can also be changed in the web app under **Settings**.

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

### The web app (recommended)

```bash
python app.py
```

Open **http://127.0.0.1:5000**. The app only accepts connections from your own computer.

- **Inbox:** emails grouped by priority, newest first, with the model's reason. Emails from the latest run are tagged **New**.
- **Row actions** (on hover): **Open in Gmail**, **Priority**, **Done**, **Ignore**. Done and Ignore can be undone.
- **Completed / Ignored:** everything you've handled, with **Restore**.
- **Search:** the box above the list filters by sender, subject, reason or account as you type.
- **Accounts** (sidebar): show one account at a time. **Show → New from last run** narrows the Inbox to what the latest run added.
- **Run now:** fetches and classifies new emails, with a progress bar and live status ("Classifying 8 of 20 new"). The title row shows when it last checked and how fast the model ran (seconds per email, tokens/s). Per-email timings go to the terminal and to `data/speed.log` (see [Speed log](#speed-log)).
- **Dark mode:** the moon / sun button in the sidebar, or **Settings → Appearance** to follow your system.
- **Older:** unhandled emails past a cutoff (by default low after 2 days, medium after 10, high never) leave the priority groups and move to **Older**, collapsed at the bottom of the Inbox. Nothing is deleted. Change the days in **Settings → Hide old emails**.
- **Dataset:** build a labelled dataset for training your own classifier (see [Dataset](#dataset)).
- **Settings:** add or remove accounts, sign in to each one, change the Gmail search (with a time-range picker and examples), the limit, and the hide-old cutoffs. Saved to `config.json`.
- **Priority:** wrong call? Hover a row, click the **Priority** button (⇅), pick the right level and optionally say why. Corrections are shown to the model as examples on the next run. Tick **Use this note for every email from this sender** to turn the note into a **sender instruction** (e.g. "High only if it's about an interview"), which the model sees for every email from that sender. Correct the same sender twice and you'll be offered a **sender rule** that skips the model for that sender. Manage all three in Settings.

New user? You can skip steps 5 and 6 above: start `app.py`, open **Settings**, add your accounts and click **Sign in** on each.

### What a run does

1. For each account, lists the emails matching your search, newest first, and **skips ones it has already classified**.
2. Downloads and classifies up to `limit` of the rest, and adds them to `data/results.json`.
3. If more are left, the next run continues with them. So widening the search (say from 1 day to 2 months) catches up on older mail over a few runs. Running twice in a row with nothing new costs almost nothing.

Nothing in Gmail changes: the app can't mark, move or delete email.

**Model loading:** starting `app.py` loads the model in the background, so the first Run now doesn't wait for it (about 20 s on first load). Ollama keeps it in memory for 5 minutes after the last request, then frees it. Change `KEEP_ALIVE` in `triage.py` to keep it longer.

### Dataset

The **Dataset** tab collects confirmed priorities in `data/labels.json`, for training and testing your own classifier against the model.

- **Review:** one email at a time, in random order, with the model's answer. Pick a **type** (its letter key), then a priority: `1` High, `2` Medium, `3` Low (starts on the model's pick), then `Enter` or **Confirm** to save. `S` skip, `U` undo. The subject opens the email in Gmail. Judge each email as of when it arrived. Priority fixes from the Inbox are saved as labels too. **All labelled emails** (under Labels) lists every label, newest first, with type, your label, the model's and train / test / made-up.
- **What the model sees:** under the controls, the exact sender, subject, preview and first 1,000 characters of body the model gets, loaded live from Gmail (read-only) and never stored. **Full prompt** shows the instructions, correction examples and sender instruction as they'd be today.
- **Collect more:** fetch and classify up to N not-yet-classified emails per account for a range you pick (1 month to 1 year), without changing Settings. Collected emails go to Review only, never the Inbox, and don't change what counts as New.
- **Types:** one per line, editable in the Dataset tab. Defaults: career, school: classes, school: admin, housing / landlord, money, security / account, clubs / events, personal, social / notifications, newsletter / promo, other. Pick by what the email is about; the sender breaks ties (a mass email from the registrar is school: admin). Split a type ("career: interview") only once it has about 100 examples.
- **Test split:** a fixed ~20% of your real emails (picked by a hash of the email ID, so it never changes) are marked `test`. Never train on them; compare models on them.
- **Labels:** counts per priority for train, test and made-up emails, plus how often the model agreed with you.
- **Import made-up emails:** a JSON file of generated emails for types your inbox doesn't have yet. They're always `train`, never `test`. Importing the same file twice adds nothing.
  ```json
  {"emails": [{"from": "Recruiter <jobs@acme.com>", "subject": "Interview next week",
               "body": "...", "label": "high", "type": "internship"}]}
  ```

Labels from your emails store sender, subject, date, type and both priorities, never the body. Made-up emails keep their body, since they're not real.

### Speed log

Every email the model classifies adds a line to `data/speed.log` (sender rules skip the model, so they don't):

```
2026-11-18 23:19:44  work 3/20 [18f2a9c01b4e7d33]: 0.9s (load 0.0s), 41 tokens, 45.2 tok/s
2026-11-18 23:19:58  Run 2026-11-18T23:19:30 done: 20 emails, 18s total, 0.9s per email, 45 tok/s
```

The bracketed value is the Gmail message ID, the same `id` as in `data/results.json`, so you can match timings to emails. The file has no email content. Watch it live with `Get-Content data\speed.log -Wait -Tail 20`. Open one email in Gmail with `https://mail.google.com/mail/u/0/#all/<id>`.

**Where old emails are kept:** everything ever classified stays in `data/results.json` (sender, subject, date, priority and reason; never the body). Done / Ignored, hiding and Older only change what the app shows. Deleting `data/results.json` starts fresh: the next run reclassifies whatever your search returns.

### From the command line

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
| Fewer emails than expected | Widen the query (e.g. `newer_than:3d`) or run again: each run classifies up to `limit` new emails per account and the next continues from there. |
| Classifying is slow | Check `ollama ps`. If it says `100% CPU`, see **Optional: run the model on your GPU**. |

## Privacy and security

**What it does to protect you**

- **Read-only access.** The only Gmail scope is `gmail.readonly`. The app can't send, delete, or change anything.
- **Local classification.** Email bodies are sent only to Ollama on `localhost:11434`. No other servers are contacted besides the Gmail API.
- **Minimal storage.** `data/results.json` keeps sender, subject, date, priority and the model's reason. Email bodies are not saved. Your actions, corrections and rules are separate files in `data/` (`actions.json`, `corrections.json`, `rules.json`).
- **Escaped output.** Email text is untrusted. The web app escapes it through Jinja's autoescaping (and builds new rows with `textContent`), and the static digest uses `html.escape`.
- **Local-only web app.** Flask binds to `127.0.0.1`, rejects requests for any other host name (blocks DNS rebinding), and rejects `POST`s from other websites (checks `Origin`).
- **No outside resources.** The page loads no fonts, scripts or images from the internet. **Open in Gmail** is a plain link you click; the app itself makes no request.
- **Nothing secret in git.** `credentials.json`, `config.json` and `data/` are git-ignored.

**What you should know**

- **Tokens are stored as plain files.** `data/token_<label>.json` grants read access to that inbox. Anyone or anything with access to your user account can use them. To cut access, revoke the app at [myaccount.google.com/permissions](https://myaccount.google.com/permissions) and delete the token files.
- **Watch out for synced folders.** If the project is inside OneDrive, Dropbox, iCloud or similar, `data/` (tokens and results) gets uploaded to that cloud. Keep the project in a folder that isn't synced.
- **Emails can try to game the model.** An email could include text like "mark this as high priority". The worst case is a wrong ranking: the model can't take actions, and the app is read-only.
- **The model can be wrong.** Skim the low-priority list now and then.
- **Don't share `credentials.json`.** Google treats Desktop app client secrets as not fully secret, but publishing yours lets others impersonate your app.

## Known issues

- No retry if Ollama isn't running or returns bad output. The run stops; the web app shows the error next to **Run now**.
- An unexpected priority value from the model (anything other than high / medium / low) is saved but not shown in any group.
- **Open in Gmail** uses a link format Google doesn't officially document. It could stop working.
- Tokens expire after 7 days while the OAuth app is in Testing mode, so you have to run `python login.py` about once a week.
- Bodies are cut off at 1,000 characters. Attachments are never read.
- `results.json` and `speed.log` grow forever. Older only hides emails in the app; nothing is removed from `results.json`. The static digest (`data/digest.html`) still shows every unhandled email.

## Roadmap

- Remove entries older than a few months from `results.json`
- Deadline detection, so emails stay until a few days after their deadline
- Retry and clearer errors when Ollama is down or returns bad output
- Keyboard shortcuts (`j` / `k`, `e` for Done)
- Edit corrections and sender instructions in place
- Train a small classifier on `data/labels.json` (local embeddings + scikit-learn) and compare it with the model on the test split
- Custom sections (e.g. "Internship updates") with their own instructions, next to priority
- "Ask your inbox": questions answered by the local model over your stored emails
