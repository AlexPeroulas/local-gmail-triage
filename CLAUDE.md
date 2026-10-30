# Inbox Triage

Local email priority tool. Reads Gmail (read-only), classifies each email with a local Gemma model via Ollama, and shows results in an HTML page. Email data must never leave this machine.

## Files
- gmail_client.py: Gmail auth and fetching (get_service, login, get_address, get_recent_emails)
- login.py: sign in / check accounts from config.json (python login.py [label])
- config.json: accounts (label to address), query, limit; git-ignored, see config.example.json
- store.py: load/save results and actions, load_config
- render.py: write_html, builds the static data/digest.html (UI work now happens in templates/)
- triage.py: classify (Ollama call) and run_triage
- app.py: Flask UI on 127.0.0.1:5000 (Run now, Done / Ignore with Undo, tabs, account filter, Settings: accounts + sign-in, query, limit); Host + Origin checks on every request
- templates/index.html: the UI page (Jinja autoescapes email text)
- data/actions.json: done / ignored per "<account>:<id>", written only by app.py
- data/meta.json: last run time and number of new emails (written by run_triage)
- data/corrections.json: your priority fixes per "<account>:<id>"; up to 8 shown to the model as examples (triage.pick_examples). Written only by app.py
- data/rules.json: sender address -> priority; skips the model. Written only by app.py
- store.effective_priority: correction beats rule beats model (used by app.py and render.py)

## Privacy rules (important)
- Never read, print, open, or copy: credentials.json, anything in data/ (token*.json, results.json, digest.html), triage.log, .env
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
- python triage.py (classify new emails, update data/digest.html)
- python triage.py --scheduled (no sign-in pages, no browser; used by Task Scheduler)
- Scheduled twice a day with Windows Task Scheduler

## Working style
- Keep responses short and use minimal progress updates
- Prefer small edits over rewriting whole files