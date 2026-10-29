# Inbox Triage

Local email priority tool. Reads Gmail (read-only), classifies each email with a local Gemma model via Ollama, and shows results in an HTML page. Email data must never leave this machine.

## Files
- gmail_client.py: Gmail login and fetching (get_service, get_recent_emails)
- store.py: load_results / save_results for results.json
- render.py: write_html, builds digest.html (UI work happens here)
- triage.py: classify (Ollama call) and run_triage
- Planned: app.py (Flask UI with Run now, filters, live updates)

## Privacy rules (important)
- Never read, print, open, or copy: credentials.json, token*.json, results.json, digest.html, triage.log, .env
- Do not run commands that display those files (cat, type, Get-Content, etc.)
- For UI work, use results.sample.json (fake data) instead of results.json
- Never send email content to external services or APIs
- Never add network calls other than Gmail API (in gmail_client.py) and localhost:11434 (Ollama)
- Never commit secrets; keep them listed in .gitignore

## Conventions
- Python, standard library plus requests, google-api-python-client, google-auth-oauthlib
- Escape all email text with html.escape before putting it in HTML (email content is untrusted)
- Keep the UI simple and uncluttered; Flask must bind to 127.0.0.1 only
- Keep gmail scope read-only (gmail.readonly)

## Running
- python triage.py (classify new emails, update digest.html)
- python triage.py --open (also opens the page)
- Scheduled twice a day with Windows Task Scheduler

## Working style
- Keep responses short and use minimal progress updates
- Prefer small edits over rewriting whole files