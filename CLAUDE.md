# Inbox Triage

Project rules for anyone (or any AI coding assistant) working on this code.

Local email priority tool. Reads Gmail (read-only), classifies each email with a local Gemma model via Ollama, and shows the results in a local web app. Email data must never leave this machine.

## Files
- gmail_client.py: Gmail sign-in and fetching (get_service, login, get_address, get_recent_emails)
- login.py: sign in / check accounts from config.json (`python login.py [label]`)
- triage.py: classify (Ollama call) and run_triage; skips emails already in results.json
- store.py: JSON storage (atomic writes), config, and effective_priority (correction beats rule beats model)
- app.py: Flask UI on 127.0.0.1:5000; Host + Origin checks on every request
- templates/index.html: the UI (Jinja autoescapes email text; JS builds rows with textContent, never innerHTML)
- render.py: static data/digest.html for scheduled runs
- config.json: accounts, query, limit, hide_after (days per priority before an email moves to Older; null = never). Git-ignored; see config.example.json

## Data (all in data/, git-ignored)
- results.json: one entry per classified email (sender, subject, date, priority, reason; no bodies). Written only by triage.py
- actions.json: done / ignored per "<account>:<id>". Written only by app.py
- corrections.json: priority fixes; up to 8 are shown to the model as examples (triage.pick_examples). Written only by app.py
- rules.json: sender address -> priority; skips the model. Written only by app.py
- meta.json: last run time, run id, number added, model speed. Written only by triage.py
- token_<label>.json: Google sign-in tokens

## Privacy rules
- Never read, print, open, or copy: credentials.json, anything in data/, triage.log, .env
- Do not run commands that display those files (cat, type, Get-Content, etc.)
- For UI work and tests, generate made-up emails in a temporary folder and point store / gmail_client at it; never use data/
- Never send email content to external services or APIs
- Never add network calls other than the Gmail API (in gmail_client.py) and localhost:11434 (Ollama)
- Never commit secrets; keep them listed in .gitignore

## Conventions
- Python, standard library plus requests, google-api-python-client, google-auth-oauthlib, flask
- Treat all email text as untrusted: escape it in HTML (Jinja autoescape / html.escape)
- Keep the UI simple; Flask binds to 127.0.0.1 only
- Keep the Gmail scope read-only (gmail.readonly)
- Each data file has one writer (see Data), so a background run never overwrites what the user did

## Running
- `python app.py`: the web app (Run now, Done / Ignore, corrections, Settings)
- `python triage.py`: classify new emails from the command line
- `python triage.py --scheduled`: no sign-in pages, no browser; for Task Scheduler / cron
