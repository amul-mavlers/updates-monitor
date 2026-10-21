#!/usr/bin/env python3
"""Post new items from status pages and RSS/Atom feeds (release news) to Google Chat."""
import calendar
import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests

WEBHOOK = os.environ.get("GCHAT_WEBHOOK_URL", "")                    # default space (news)
WEBHOOK_ALERTS = os.environ.get("GCHAT_WEBHOOK_ALERTS") or WEBHOOK   # outages + security; optional
DRY_RUN = os.environ.get("DRY_RUN") == "1"          # print instead of posting, no state changes
STATE_FILE = Path(__file__).with_name("state.json")
MAX_PER_FEED = 5       # safety cap per run, avoids floods
SUMMARY_LEN = 220
TZ_NAME = os.environ.get("FEED_TZ", "Asia/Kolkata")   # timezone shown in messages
KEEP_SEEN = 300        # minimum seen keys kept per feed (never fewer than the feed currently lists)
HEALTH_FAIL_RUNS = 4   # consecutive failed runs (~1h) before a feed health warning is posted
POST_GAP = 1.1         # seconds between posts; Chat webhooks allow ~1 request/second per space
DEDUPE_KEEP = 500
# News items matching this go to the alerts space instead of the default one.
URGENT_RE = re.compile(
    r"(?<![\w-])(CVE-\d{4}-\d+|security|critical|vulnerabilit\w*|zero-day|remote code execution)(?![\w-])",
    re.I)

# kind="status": incident feeds. "api" is a Statuspage base URL (real current status, exact update
#                times); a plain "url" RSS status feed also works but only says "Update".
# kind="news":   release/news feeds from "url". Message shows the `label`.
# "dedupe":      feeds sharing a group don't post the same story twice (matched by title).
# "maintenance": also post scheduled maintenance; "maintenance_match" limits it by title regex.
FEEDS = [
    {"name": "GitHub Status",     "api": "https://www.githubstatus.com/api/v2",     "kind": "status"},
    {"name": "Cloudflare Status", "api": "https://www.cloudflarestatus.com/api/v2", "kind": "status",
     "maintenance": True,
     # Cloudflare lists every datacenter; only post the ones near the team.
     "maintenance_match": r"\((?:Ahmedabad|Mumbai|Delhi|Chennai|Bangalore|Bengaluru|Hyderabad|Kolkata|"
                          r"Kathmandu|Dhaka|Colombo|Singapore)\b"},
    {"name": "Shopify Status",    "api": "https://www.shopifystatus.com/api/v2",    "kind": "status"},
    {"name": "WordPress News",    "url": "https://wordpress.org/news/feed/",        "kind": "news", "label": "New post"},
    {"name": "PHP News",          "url": "https://www.php.net/feed.atom",           "kind": "news", "label": "News",
     "dedupe": "php"},
    {"name": "PHP Releases",      "url": "https://www.php.net/releases/feed.php",   "kind": "news", "label": "New release",
     "dedupe": "php"},
    {"name": "Shopify Changelog", "url": "https://shopify.dev/changelog/feed.xml",  "kind": "news", "label": "Changelog"},
    # Add more here, e.g. WooCommerce, Laravel News, Node.js, Patchstack...
]

STATUS_STYLE = {
    "investigating": ("🔴", "Investigating"),
    "identified":    ("🟠", "Identified"),
    "monitoring":    ("🟡", "Monitoring"),
    "verifying":     ("🟡", "Verifying"),
    "resolved":      ("🟢", "Resolved"),
    "completed":     ("🟢", "Completed"),
    "postmortem":    ("📝", "Postmortem"),
    "scheduled":     ("🔧", "Scheduled maintenance"),
    "in progress":   ("🔧", "Maintenance in progress"),
    "update":        ("🔵", "Update"),
}
MAINTENANCE_STYLE = {
    "scheduled":   ("🔧", "Scheduled maintenance"),
    "in progress": ("🔧", "Maintenance in progress"),
    "verifying":   ("🔧", "Maintenance verifying"),
    "completed":   ("🟢", "Maintenance completed"),
}
OPEN_STATUSES = {"investigating", "identified", "monitoring", "verifying"}
STATUS_RE = re.compile(
    r"<strong>\s*(Investigating|Identified|Monitoring|Verifying|Resolved|Completed|Postmortem|"
    r"Scheduled|In progress|Update)\s*</strong>\s*-\s*(.*?)(?=<br|</p>|$)",
    re.I | re.S,
)


def api_entries(data: dict, feed: dict | None = None, limit: int = 25) -> list:
    """Turn Statuspage incidents / scheduled-maintenances JSON into feed-like entries
    (one per incident, carrying its newest update)."""
    match = re.compile(feed["maintenance_match"], re.I) if feed and feed.get("maintenance_match") else None
    by_id: dict = {}
    for inc in data.get("incidents", []) + data.get("scheduled_maintenances", []):
        ups = inc.get("incident_updates") or []
        up = max(ups, key=lambda u: u.get("created_at", ""), default=None)
        if not up or not up.get("created_at") or "id" not in inc:
            continue
        is_maint = bool(inc.get("scheduled_for"))
        if is_maint and match and not match.search(inc.get("name", "")):
            continue
        status = up.get("status", "update").replace("_", " ")
        entry = {
            "id": inc["id"],
            "title": inc.get("name", "(no title)"),
            "link": inc.get("shortlink", ""),
            "updated": up["created_at"],
            "status": status,
            "maintenance": is_maint,
            "summary": up.get("body", ""),
        }
        if is_maint:
            entry["starts"] = inc["scheduled_for"]
        # a maintenance can appear in both the upcoming and active lists: keep its newest update
        if inc["id"] not in by_id or entry["updated"] > by_id[inc["id"]]["updated"]:
            by_id[inc["id"]] = entry
    return sorted(by_id.values(), key=lambda e: e["updated"], reverse=True)[:limit]


def fetch_entries(feed: dict) -> list:
    headers = {"User-Agent": "dev-team-feed-bot/1.0"}
    if feed.get("api"):
        # feed["api"] is the Statuspage base, e.g. https://www.githubstatus.com/api/v2
        data: dict = {}
        optional = (["scheduled-maintenances/upcoming.json", "scheduled-maintenances/active.json"]
                    if feed.get("maintenance") else [])
        for path in ["incidents.json"] + optional:
            try:
                resp = requests.get(f"{feed['api']}/{path}", timeout=20, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
            except (requests.RequestException, ValueError):
                if path == "incidents.json":
                    raise
                # maintenance is optional: keep incident alerts working if it is down
                print(f"[{feed['name']}] {path} unavailable, continuing without it", file=sys.stderr)
                continue
            for k, v in payload.items():
                if isinstance(v, list):
                    data.setdefault(k, []).extend(v)
        return api_entries(data, feed)
    resp = requests.get(feed["url"], timeout=20, headers=headers)
    resp.raise_for_status()
    entries = feedparser.parse(resp.content).entries
    # newest first, whatever order the feed uses (stable: undated entries keep their order)
    return sorted(entries, key=lambda e: calendar.timegm(e.get("published_parsed") or e.get("updated_parsed") or time.gmtime(0)),
                  reverse=True)


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def shorten(text: str, n: int = SUMMARY_LEN) -> str:
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def entry_key(feed: dict, e) -> str:
    base = e.get("id") or e.get("link") or e.get("title") or ""
    if not base:  # nothing identifying: hash the content so entries don't collapse into one key
        base = hashlib.sha1((e.get("summary") or e.get("description") or "").encode()).hexdigest()
    if feed["kind"] == "status":  # incident updates change `updated`, so re-alert
        return f"{base}|{e.get('updated', '')}"
    return base


def entry_time(feed: dict, e) -> datetime | None:
    """When the update happened (status: latest update, or window start for scheduled
    maintenance; news: publish time)."""
    if e.get("starts") and e.get("status") == "scheduled":
        order = ("starts",)
    elif feed["kind"] == "status":
        order = ("updated", "published")
    else:
        order = ("published", "updated")
    for field in order:
        parsed = e.get(field + "_parsed")
        if parsed:
            return datetime.fromtimestamp(calendar.timegm(parsed), timezone.utc)
        raw = e.get(field)
        if raw:
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return None


def format_time(dt: datetime) -> str:
    try:
        local = dt.astimezone(ZoneInfo(TZ_NAME))
    except Exception:  # unknown zone or no tzdata: fall back to UTC
        local = dt.astimezone(timezone.utc)
    return f"{local.day} {local:%b %Y, %H:%M %Z}"


def safe(text: str) -> str:
    """Stop feed text from becoming Chat markup (links via <url|text>, bold, strike, code)."""
    return text.replace("<", "‹").replace(">", "›").translate({ord("*"): None, ord("~"): None, ord("`"): None})


def build_message(feed: dict, e) -> str:
    title = safe(clean(e.get("title", "(no title)")))
    link = e.get("link", "")
    raw = e.get("summary") or e.get("description") or ""
    prefix = ""

    if feed["kind"] == "status":
        if e.get("status"):  # from the Statuspage API
            status = e["status"].lower()
            style = (MAINTENANCE_STYLE if e.get("maintenance") else STATUS_STYLE).get(status)
            emoji, label = style or ("🔵", status.title())
            summary = clean(raw)
            if e.get("maintenance") and status == "scheduled":
                prefix = "Starts "
        else:  # plain RSS status feed
            m = STATUS_RE.search(raw)
            if m:
                emoji, label = STATUS_STYLE[m.group(1).lower()]
                summary = clean(m.group(2))
            else:
                emoji, label, summary = "🔵", "Update", clean(raw)
    else:
        emoji, label, summary = "🆕", feed.get("label", "Update"), clean(raw)

    lines = [f"{emoji} *{feed['name']}* · {label}", f"*{title}*"]
    when = entry_time(feed, e)
    if when:
        lines.append(f"🕒 {prefix}{format_time(when)}")
    if summary:
        lines.append(safe(shorten(summary)))
    if link.startswith(("http://", "https://")):
        lines.append(f"<{link.replace('|', '%7C').replace('>', '%3E')}|Read more>")
    return "\n".join(lines)


def is_urgent(feed: dict, e) -> bool:
    """Outages and security news go to the alerts space; maintenance and other news don't."""
    if feed["kind"] == "status":
        return not e.get("maintenance")
    return bool(URGENT_RE.search(clean(e.get("title", "")) + " " + clean(e.get("summary") or "")))


def is_open_incident(feed: dict, e) -> bool:
    return feed["kind"] == "status" and not e.get("maintenance") and e.get("status") in OPEN_STATUSES


def thread_key(feed: dict, e) -> str | None:
    """Status updates for one incident share a Chat thread; news posts stand alone."""
    if feed["kind"] != "status":
        return None
    base = e.get("id") or e.get("link") or e.get("title", "")
    return re.sub(r"[^A-Za-z0-9_-]", "-", f"{feed['name']}-{base}")[-120:]


def dedupe_title(title: str) -> str:
    t = re.sub(r"\b(released?|announcement|announces?)\b", " ", clean(title).lower())
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


_last_post = 0.0


def post(text: str, url: str, thread: str | None = None) -> bool:
    global _last_post
    if DRY_RUN:
        space = "alerts" if url == WEBHOOK_ALERTS != WEBHOOK else "default"
        tag = f", thread {thread}" if thread else ""
        print(f"--- DRY RUN ({space}{tag}) ---\n{text}\n")
        return True
    body, params = {"text": text}, {}
    if thread:
        body["thread"] = {"threadKey": thread}
        params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
    for attempt in range(3):
        wait = POST_GAP - (time.monotonic() - _last_post)
        if wait > 0:
            time.sleep(wait)
        try:
            r = requests.post(url, json=body, params=params, timeout=15)
        except requests.ConnectionError as ex:   # never reached Chat, so retrying can't duplicate
            _last_post = time.monotonic()
            print(f"  post connection error ({type(ex).__name__}), retrying", file=sys.stderr)
            time.sleep(2 ** (attempt + 1))
            continue
        except requests.RequestException as ex:  # e.g. read timeout: Chat may have received it
            # log the type only: the exception text can contain the webhook URL with its key/token
            print(f"  post failed: {type(ex).__name__}", file=sys.stderr)
            return False
        _last_post = time.monotonic()
        if r.status_code in (429, 502, 503, 504):
            try:
                delay = min(float(r.headers.get("Retry-After", "")), 30)
            except ValueError:   # missing or an HTTP-date
                delay = 2 ** (attempt + 1)
            print(f"  post got {r.status_code}, retrying in {delay:.0f}s", file=sys.stderr)
            time.sleep(delay)
            continue
        if r.status_code >= 400:
            print(f"  post failed: HTTP {r.status_code}", file=sys.stderr)
            return False
        return True
    return False


def record_health(state: dict, name: str, ok: bool) -> None:
    """Warn the alerts space once when a feed has failed HEALTH_FAIL_RUNS runs in a row."""
    health = state.setdefault("_health", {})
    if ok:
        health.pop(name, None)
        return
    health[name] = health.get(name, 0) + 1
    if health[name] == HEALTH_FAIL_RUNS:
        post(f"⚠️ *Feed bot* · {name} has returned no data for {HEALTH_FAIL_RUNS} runs in a row. "
             "Check the feed URL or whether the source is down.", WEBHOOK_ALERTS)


def save_state(state: dict) -> None:
    if DRY_RUN:
        return
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def announce(feed: dict, e, state: dict) -> bool:
    """Post one entry unless a sibling feed already posted the same story. True = handled."""
    group = feed.get("dedupe")
    if group:
        titles = state.setdefault("_dedupe", {}).setdefault(group, [])
        norm = dedupe_title(e.get("title", ""))
        if norm in titles:
            return True
    url = WEBHOOK_ALERTS if is_urgent(feed, e) else WEBHOOK
    if not post(build_message(feed, e), url, thread_key(feed, e)):
        return False
    if group:
        titles.insert(0, norm)
        del titles[DEDUPE_KEEP:]
    return True


def send(feed: dict, e, state: dict, key: str) -> bool:
    """announce() and, on success, remember the key so it isn't posted again."""
    if not announce(feed, e, state):
        return False
    state[feed["name"]].insert(0, key)
    return True


def post_overflow(feed: dict, items: list) -> bool:
    """One summary message for items beyond MAX_PER_FEED, so none is dropped silently."""
    lines = [f"➕ *{feed['name']}* · {len(items)} more updates (too many to post one by one)"]
    for _, e in items[-10:]:
        title = safe(clean(e.get("title", "(no title)")))
        link = e.get("link", "")
        lines.append(f"• <{link}|{title}>" if link.startswith(("http://", "https://")) else f"• {title}")
    if len(items) > 10:
        lines.append(f"…and {len(items) - 10} older")
    url = WEBHOOK_ALERTS if any(is_urgent(feed, e) for _, e in items) else WEBHOOK
    return post("\n".join(lines), url)


def process_feed(feed: dict, state: dict) -> None:
    name = feed["name"]
    entries = fetch_entries(feed)
    if not entries:
        raise LookupError("no entries found (check URL)")

    keys = [entry_key(feed, e) for e in entries]
    keep = max(KEEP_SEEN, len(keys))   # never trim below what the feed itself still lists

    # First time we see a feed: remember what exists so old items aren't posted,
    # but do announce incidents that are still open right now.
    if name not in state and not DRY_RUN:
        # Record everything as seen first, so a crash or failed post below can't leave an empty
        # state that would flood the space with old items on the next run.
        state[name] = list(dict.fromkeys(keys))[:keep]
        open_now = [(k, e) for k, e in zip(keys, entries) if is_open_incident(feed, e)][:MAX_PER_FEED]
        announced = 0
        for k, e in reversed(open_now):
            if announce(feed, e, state):
                announced += 1
            else:   # not delivered: forget the key so the next run tries again
                state[name].remove(k)
        print(f"[{name}] first run, seeded {len(keys)} items, announced {announced} open")
        return

    seen = set() if DRY_RUN else set(state[name])
    new = [(k, e) for k, e in zip(keys, entries) if k not in seen]
    new.reverse()  # oldest first
    print(f"[{name}] {len(new)} new")

    if DRY_RUN:
        new = new[-2:]
    state.setdefault(name, [])
    for k, e in new[-MAX_PER_FEED:]:
        send(feed, e, state, k)
    # items beyond the cap go out as one summary message; if that fails they stay unseen
    overflow = new[:-MAX_PER_FEED]
    if overflow and (DRY_RUN or post_overflow(feed, overflow)):
        for k, _ in overflow:
            state[name].insert(0, k)
    state[name] = state[name][:keep]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):   # emoji in messages break cp1252 consoles
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if not WEBHOOK and not DRY_RUN:
        print("GCHAT_WEBHOOK_URL is not set", file=sys.stderr)
        return 1

    if os.environ.get("TEST_MESSAGE") == "1":   # "Run workflow" > send test message: checks both webhooks
        targets = {"default space": WEBHOOK, "alerts space": WEBHOOK_ALERTS}
        results = [post(f"✅ *Feed bot* · test message to the {label}. Webhook works.", url)
                   for label, url in targets.items() if url]
        if WEBHOOK_ALERTS == WEBHOOK:
            print("GCHAT_WEBHOOK_ALERTS is not set: alerts will go to the default space")
        return 0 if all(results) else 1

    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}

    for feed in FEEDS:
        name = feed["name"]
        try:
            process_feed(feed, state)
        except Exception as ex:  # one broken feed or record must not stop the others
            print(f"[{name}] failed: {type(ex).__name__}: {ex}", file=sys.stderr)
            record_health(state, name, False)
        else:
            record_health(state, name, True)
        save_state(state)   # after every feed, so a later crash can't cause reposts
    return 0


if __name__ == "__main__":
    sys.exit(main())
