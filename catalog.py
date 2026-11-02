"""Builds catalog.json: every kind of message the bot posts, for the Worker's public landing page.

Live cards are built from the entries the bot fetched this run, with the bot's own message code, so the
page always matches what Chat really shows. Example cards cover messages that only appear during an
outage or a problem; they use a fixed date so the file only changes when the live feeds do (the bot
commits it, and a file that changed on every run would mean a commit every 5 minutes).

The bot module is passed in (not imported) because the bot normally runs as a script.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

SPACE_NAMES = {"default": "News", "alerts": "Downtime", "wp_php": "WordPress & PHP"}
EXAMPLE_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)   # fixed on purpose: see module docstring


def _iso(minutes_ago: float) -> str:
    return (EXAMPLE_NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _category(bot, feed: dict, e) -> str:
    if feed["kind"] == "status":
        return "maintenance" if e.get("maintenance") else "incidents"
    if feed["name"] == "Google Workspace Status":
        return "incidents"
    return "security" if bot.is_urgent(feed, e) else "news"


def _card(bot, feed: dict, e, live: bool, note: str = "") -> dict:
    text = bot.build_message(feed, e)
    head = text.split("\n")[0]
    return {
        "cat": _category(bot, feed, e),
        "source": feed["name"],
        "kind": head.split("·", 1)[1].strip() if "·" in head else head,
        "spaces": [SPACE_NAMES[sp] for sp in bot.route(feed, bot.is_urgent(feed, e))],
        "text": text,
        "live": live,
        "note": note,
    }


def _examples(bot, feeds: list) -> list:
    cards = []
    github = next((x for x in feeds if x["name"] == "GitHub Status"), None)
    cloudflare = next((x for x in feeds if x["name"] == "Cloudflare Status"), None)

    if github:
        chain = [
            ("investigating", "We are investigating reports of degraded performance for Actions and webhook deliveries.", 95),
            ("identified", "We have identified the cause, a failing storage node, and are rolling out a fix.", 70),
            ("monitoring", "A fix has been applied and we are monitoring recovery.", 40),
            ("resolved", "This incident has been resolved. Thank you for your patience.", 12),
        ]
        old_mention = bot.MENTION_ALL
        try:
            for upto in range(1, 5):
                inc = {"id": "example-incident", "name": "Degraded performance for Actions and Webhooks",
                       "shortlink": "https://www.githubstatus.com/", "impact": "major",
                       "started_at": _iso(chain[0][2]), "components": [{"name": "Actions"}, {"name": "Webhooks"}],
                       "incident_updates": [{"status": s, "body": b, "created_at": _iso(m)} for s, b, m in chain[:upto]]}
                bot.MENTION_ALL = upto == 1
                (e,) = bot.api_entries({"incidents": [inc]})
                note = "Example. The @all mention is off unless MENTION_ALL is switched on." if upto == 1 else "Example"
                cards.append(_card(bot, github, e, False, note))
        finally:
            bot.MENTION_ALL = old_mention

    if cloudflare:
        steps = [("scheduled", "We will be performing scheduled maintenance in AMD (Ahmedabad) datacenter. "
                              "Traffic might be re-routed.", 3000),
                 ("in_progress", "Scheduled maintenance is currently in progress. We will provide updates if the schedule changes.", 20),
                 ("completed", "The scheduled maintenance has been completed.", 5)]
        start = EXAMPLE_NOW + timedelta(days=2)
        for i in range(1, 4):
            inc = {"id": "example-maintenance", "name": f"AMD (Ahmedabad) on {start:%Y-%m-%d}",
                   "shortlink": "https://www.cloudflarestatus.com/", "impact": "maintenance",
                   "scheduled_for": start.strftime("%Y-%m-%dT21:00:00.000Z"),
                   "scheduled_until": (start + timedelta(hours=4)).strftime("%Y-%m-%dT01:00:00.000Z"),
                   "incident_updates": [{"status": s, "body": b, "created_at": _iso(m)} for s, b, m in steps[:i]]}
            (e,) = bot.api_entries({"scheduled_maintenances": [inc]}, cloudflare)
            cards.append(_card(bot, cloudflare, e, False, "Example. Only nearby regions are posted."))

    burst = [(f"k{i}", {"title": f"Changelog item number {i}", "link": "https://shopify.dev/changelog"}) for i in range(8)]
    system = [
        ("Feed health warning", bot.health_text("Laravel News"), "A source returned nothing for several runs in a row."),
        ("Burst summary", bot.overflow_text({"name": "Shopify Changelog", "kind": "news"}, burst),
         "More than 5 new items in one run go out as one message."),
        ("Workflow failed", "⚠️ Feed bot workflow failed: https://github.com/",
         "Sent at most once an hour while the run keeps failing."),
        ("Timer cannot start the workflow",
         "⚠️ *Feed bot timer* · cannot start the workflow, so no feeds are being checked.\n"
         "dispatch failed: HTTP 401 (token invalid, expired or revoked)", "From the Cloudflare timer, at most once an hour."),
        ("Token expiry reminder", "⏰ *Feed bot timer* · the GitHub token expires in 7 days.",
         "Daily, during the last 14 days."),
        ("Test message", "✅ *Feed bot* · test message to the alerts space. Webhook works.",
         "Sent by the Run workflow test option."),
    ]
    for label, text, note in system:
        cards.append({"cat": "system", "source": "Feed bot", "kind": label, "spaces": ["Downtime"],
                      "text": text, "live": False, "note": note})
    return cards


def _routing(feeds: list) -> list:
    rows = []
    for feed in feeds:
        if feed.get("api"):
            how = "Status page API"
        else:
            how = "Atom feed" if feed["name"].startswith("PHP") or "Workspace" in feed["name"] else "RSS feed"
        if feed["kind"] == "status":
            space, extra = "Downtime", ("maintenance in nearby regions goes to News" if feed.get("maintenance") else "")
        elif feed.get("space") == "wp_php":
            space, extra = "WordPress & PHP", "security items are also copied to Downtime"
        elif feed.get("urgent"):
            space, extra = "Downtime", "every item"
        else:
            space, extra = "News", "security items go to Downtime"
        rows.append({"source": feed["name"], "how": how, "space": space, "extra": extra})
    return rows


def build(bot, feeds: list, results: list) -> dict:
    cards = []
    newest = ""
    for feed, entries in zip(feeds, results):
        if isinstance(entries, Exception) or not entries:
            continue
        limit = 4 if feed.get("space") == "wp_php" else 2
        picked = 0
        for e in entries:
            if feed["kind"] == "status" and e.get("maintenance"):
                continue
            cards.append(_card(bot, feed, e, True))
            when = bot.entry_time(feed, e)
            if when:
                newest = max(newest, when.strftime("%Y-%m-%dT%H:%M:%SZ"))
            picked += 1
            if picked >= limit:
                break
    cards += _examples(bot, feeds)
    return {"version": 1, "updated": newest, "cards": cards, "routing": _routing(feeds)}


def write(bot, feeds: list, results: list, path: Path) -> bool:
    """Write catalog.json if its content changed. Returns True when the file was rewritten."""
    text = json.dumps(build(bot, feeds, results), ensure_ascii=False, indent=1, sort_keys=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return True
