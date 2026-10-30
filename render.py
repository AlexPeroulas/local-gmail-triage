import html
from datetime import datetime
from pathlib import Path
from store import load_actions, action_key

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
COLORS = {"high": "#e5484d", "medium": "#f5a524", "low": "#8b8d98"}


def render_html(results, done=True):
    actions = load_actions()   # hide emails marked done / ignored in the UI
    results = [r for r in results if action_key(r) not in actions]
    refresh = "" if done else "<meta http-equiv='refresh' content='3'>"
    status = "" if done else f"<p>Still running... {len(results)} emails so far</p>"
    parts = [
        f"<html><head><meta charset='utf-8'>{refresh}<title>Inbox digest</title>",
        "<style>",
        "body{font-family:sans-serif;max-width:800px;margin:2rem auto;padding:0 1rem}",
        ".email{border-left:6px solid;padding:.5rem 1rem;margin:.5rem 0;background:#f6f6f6}",
        ".meta{color:#555;font-size:.9rem}",
        "</style></head><body>",
        f"<h1>Inbox digest</h1><p>Updated {datetime.now():%Y-%m-%d %H:%M}</p>{status}",
    ]
    for level in ("high", "medium", "low"):
        level_group = [r for r in results if r["priority"] == level]
        if not level_group:
            continue
        parts.append(f"<h2>{level.upper()} ({len(level_group)})</h2>")
        for account in sorted({r["account"] for r in level_group}):
            group = [r for r in level_group if r["account"] == account]
            parts.append(f"<h3>{html.escape(account)} ({len(group)})</h3>")
            for r in group:
                parts.append(
                    f"<div class='email' style='border-color:{COLORS[level]}'>"
                    f"<b>{html.escape(r['subject'] or '(no subject)')}</b>"
                    f"<div class='meta'>{html.escape(r['from'])}</div>"
                    f"<div>{html.escape(r['reason'])}</div></div>"
                )
    parts.append("</body></html>")
    return "\n".join(parts)


def write_html(results, done=True):
    DATA.mkdir(exist_ok=True)
    out = DATA / "digest.html"
    out.write_text(render_html(results, done), encoding="utf-8")
    return out