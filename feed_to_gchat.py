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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests

WEBHOOK = os.environ.get("GCHAT_WEBHOOK_URL", "")                    # default space (news)
WEBHOOK_ALERTS = os.environ.get("GCHAT_WEBHOOK_ALERTS") or WEBHOOK   # outages + security; optional
WEBHOOK_WP_PHP = os.environ.get("GCHAT_WEBHOOK_WP_PHP") or WEBHOOK   # WordPress + PHP feeds; optional
DRY_RUN = os.environ.get("DRY_RUN") == "1"          # print instead of posting, no state changes
STATE_FILE = Path(__file__).with_name("state.json")
MAX_PER_FEED = 5       # safety cap per run, avoids floods
SUMMARY_LEN = 220
TZ_NAME = os.environ.get("FEED_TZ", "Asia/Kolkata")   # timezone shown in messages
KEEP_SEEN = 5000       # seen keys kept per feed. Feeds drift in size (items drop out and return), so
                       # this must stay well above any feed's length or old items look new again
MAX_AGE_DAYS = 30      # never post items older than this, even if they look new (belt and braces)
HEALTH_FAIL_RUNS = 4   # consecutive failed runs (~1h) before a feed health warning is posted
POST_GAP = 1.1         # seconds between posts; Chat webhooks allow ~1 request/second per space
DEDUPE_KEEP = 500
TITLE_LEN = 200        # Chat rejects messages over 4096 characters; feed titles are untrusted and unbounded
GIVE_UP_AFTER = 3      # an item Chat permanently rejects (HTTP 400/413/422) is skipped after this many tries
PERMANENT_ERRORS = {400, 413, 422}
# Opt in with MENTION_ALL=1: major/critical incidents start with an @all mention in Chat.
MENTION_ALL = os.environ.get("MENTION_ALL") == "1"
MENTION_IMPACTS = {"major", "critical"}
# News items matching this go to the alerts space instead of the default one.
URGENT_RE = re.compile(
    r"(?<![\w-])(CVE-\d{4}-\d+|security|critical|vulnerabilit\w*|zero-day|remote code execution)(?![\w-])",
    re.I)

# kind="status": incident feeds. "api" is a Statuspage base URL (real current status, exact update
#                times); a plain "url" RSS status feed also works but only says "Update".
# kind="news":   release/news feeds from "url". Message shows the `label`.
# "dedupe":      feeds sharing a group don't post the same story twice (matched by title).
# "maintenance": also post scheduled maintenance; "maintenance_match" limits it by title regex.
# "urgent":      post every item of this news feed to the alerts space.
# "space":       "wp_php" sends this feed to its own space (GCHAT_WEBHOOK_WP_PHP). Its security items
#                are also copied to the alerts space. Without the secret it falls back to the default.
# "track_updates": a news item is posted again when the feed marks it as updated (live incidents).
FEEDS = [
    {"name": "GitHub Status",     "api": "https://www.githubstatus.com/api/v2",     "kind": "status"},
    {"name": "Cloudflare Status", "api": "https://www.cloudflarestatus.com/api/v2", "kind": "status",
     "maintenance": True,
     # Cloudflare lists every datacenter; only post the ones near the team.
     "maintenance_match": r"\((?:Ahmedabad|Mumbai|Delhi|Chennai|Bangalore|Bengaluru|Hyderabad|Kolkata|"
                          r"Kathmandu|Dhaka|Colombo|Singapore)\b"},
    {"name": "Shopify Status",    "api": "https://www.shopifystatus.com/api/v2",    "kind": "status"},
    {"name": "WordPress News",    "url": "https://wordpress.org/news/feed/",        "kind": "news", "label": "New post",
     "space": "wp_php"},
    {"name": "PHP News",          "url": "https://www.php.net/feed.atom",           "kind": "news", "label": "News",
     "dedupe": "php", "space": "wp_php"},
    {"name": "PHP Releases",      "url": "https://www.php.net/releases/feed.php",   "kind": "news", "label": "New release",
     "dedupe": "php", "space": "wp_php"},
    {"name": "Shopify Changelog", "url": "https://shopify.dev/changelog/feed.xml",  "kind": "news", "label": "Changelog"},
    {"name": "WooCommerce Dev",    "url": "https://developer.woocommerce.com/feed/", "kind": "news", "label": "WooCommerce"},
    {"name": "Laravel News",      "url": "https://laravel-news.com/feed",           "kind": "news", "label": "Laravel"},
    {"name": "Node.js Blog",      "url": "https://nodejs.org/en/feed/blog.xml",     "kind": "news", "label": "Node.js"},
    {"name": "Patchstack",        "url": "https://patchstack.com/feed/",            "kind": "news", "label": "Security blog"},
    {"name": "Google Workspace Status", "url": "https://www.google.com/appsstatus/dashboard/feed.atom",
     "kind": "news", "label": "Incident", "urgent": True, "track_updates": True},
    # More that work: npm status {"api": "https://status.npmjs.org/api/v2", "kind": "status"},
    # Atlassian status {"api": "https://status.atlassian.com/api/v2", "kind": "status"}.
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
            "impact": (inc.get("impact") or "").lower(),
            "started": inc.get("started_at") or inc.get("created_at") or "",
            "components": [c["name"] for c in inc.get("components") or [] if c.get("name")],
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
    # content-location lets feedparser turn relative links (e.g. Node.js) into absolute ones
    entries = feedparser.parse(resp.content, response_headers={"content-location": getattr(resp, "url", feed["url"])}).entries
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
    if feed["kind"] == "status" or feed.get("track_updates"):  # incident updates change `updated`, so re-alert
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


def format_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "under a minute"
    days, rem = divmod(minutes, 1440)
    hours, mins = divmod(rem, 60)
    if days:
        return f"{days} d {hours} h"
    return f"{hours} h {mins} min" if hours else f"{mins} min"


def incident_age(e) -> float | None:
    """Seconds from the incident's start to its newest update, for 'Resolved after ...'."""
    try:
        start = datetime.fromisoformat(e["started"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(e["updated"].replace("Z", "+00:00"))
    except (KeyError, ValueError, AttributeError):
        return None
    seconds = (end - start).total_seconds()
    return seconds if seconds >= 0 else None


def build_message(feed: dict, e) -> str:
    title = safe(shorten(clean(e.get("title", "(no title)")), TITLE_LEN))
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
            if not e.get("maintenance"):
                if status == "resolved" and (age := incident_age(e)) is not None:
                    label = f"Resolved after {format_duration(age)}"
                if e.get("impact") in ("minor", "major", "critical"):
                    label += f" · {e['impact'].title()} impact"
        else:  # plain RSS status feed
            m = STATUS_RE.search(raw)
            if m:
                emoji, label = STATUS_STYLE[m.group(1).lower()]
                summary = clean(m.group(2))
            else:
                emoji, label, summary = "🔵", "Update", clean(raw)
    else:
        emoji, label, summary = "🆕", feed.get("label", "Update"), clean(raw)

    mention = ""
    if (MENTION_ALL and feed["kind"] == "status" and not e.get("maintenance")
            and e.get("impact") in MENTION_IMPACTS and e.get("status") == "investigating"):
        mention = "<users/all> "   # only on the first, 'investigating' message of a big incident
    lines = [f"{mention}{emoji} *{feed['name']}* · {label}", f"*{title}*"]
    when = entry_time(feed, e)
    if when:
        lines.append(f"🕒 {prefix}{format_time(when)}")
    comps = e.get("components") or []
    if comps:
        more = f" +{len(comps) - 4}" if len(comps) > 4 else ""
        lines.append(safe(f"Affected: {', '.join(comps[:4])}{more}"))
    if summary:
        lines.append(safe(shorten(summary)))
    if link.startswith(("http://", "https://")):
        lines.append(f"<{link.replace('|', '%7C').replace('>', '%3E')}|Read more>")
    return "\n".join(lines)


def is_urgent(feed: dict, e) -> bool:
    """Outages and security news go to the alerts space; maintenance and other news don't."""
    if feed["kind"] == "status":
        return not e.get("maintenance")
    if feed.get("urgent"):
        return True
    return bool(URGENT_RE.search(clean(e.get("title", "")) + " " + clean(e.get("summary") or "")))


def destinations(feed: dict, e) -> list:
    """Webhook URLs for one entry, first = main destination. Duplicates (unset secrets fall back to the
    same URL) are removed so nothing is posted twice to one space."""
    urgent = is_urgent(feed, e)
    base = WEBHOOK_WP_PHP if feed.get("space") == "wp_php" else WEBHOOK
    if feed["kind"] == "status":
        urls = [WEBHOOK_ALERTS] if urgent else [WEBHOOK]
    elif feed.get("space") and urgent:
        urls = [base, WEBHOOK_ALERTS]    # the feed's own space gets everything; security is copied to alerts
    else:
        urls = [WEBHOOK_ALERTS if urgent else base]
    return list(dict.fromkeys(urls))


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
_last_rejected = False   # True when the latest post() failed with a permanent HTTP error (retrying is pointless)


def post(text: str, url: str, thread: str | None = None) -> bool:
    global _last_post, _last_rejected
    _last_rejected = False
    if DRY_RUN:
        space = ("alerts" if url == WEBHOOK_ALERTS != WEBHOOK
                 else "wp-php" if url == WEBHOOK_WP_PHP != WEBHOOK else "default")
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
            _last_rejected = r.status_code in PERMANENT_ERRORS
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
    text, thread = build_message(feed, e), thread_key(feed, e)
    urls = destinations(feed, e)
    if not post(text, urls[0], thread):
        return False
    for extra in urls[1:]:   # copies are best effort: a failure here must not cause a repost in the main space
        if not post(text, extra, thread):
            print(f"[{feed['name']}] copy to second space failed", file=sys.stderr)
    if group:
        titles.insert(0, norm)
        del titles[DEDUPE_KEEP:]
    return True


def send(feed: dict, e, state: dict, key: str) -> bool:
    """announce() and, on success, remember the key so it isn't posted again.

    Chat being down must never drop an alert, so failures are retried every run. The exception is an
    item Chat permanently rejects (HTTP 400 and similar): after GIVE_UP_AFTER tries it is marked seen,
    otherwise it would be retried, and fail, on every run forever."""
    failed = state.setdefault("_failed", {})
    fkey = f"{feed['name']}|{key}"
    if not announce(feed, e, state):
        if _last_rejected:
            failed[fkey] = failed.get(fkey, 0) + 1
            if failed[fkey] >= GIVE_UP_AFTER:
                print(f"[{feed['name']}] giving up on an item Chat keeps rejecting: {clean(e.get('title', ''))[:80]}",
                      file=sys.stderr)
                failed.pop(fkey, None)
                state[feed["name"]].insert(0, key)
        return False
    failed.pop(fkey, None)
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
    base = WEBHOOK_WP_PHP if feed.get("space") == "wp_php" else WEBHOOK
    urgent = any(is_urgent(feed, e) for _, e in items)
    urls = list(dict.fromkeys([base, WEBHOOK_ALERTS] if feed.get("space") and urgent
                              else [WEBHOOK_ALERTS if urgent else base]))
    text = "\n".join(lines)
    ok = post(text, urls[0])
    for extra in urls[1:]:
        post(text, extra)
    return ok


def process_feed(feed: dict, state: dict, entries: list) -> None:
    name = feed["name"]
    if not entries:
        raise LookupError("no entries found (check URL)")

    keys = [entry_key(feed, e) for e in entries]
    keep = max(KEEP_SEEN, len(keys))

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
    # Old items that resurface (a feed re-listing history) are remembered silently, not posted.
    cutoff = datetime.now(timezone.utc).timestamp() - MAX_AGE_DAYS * 86400
    stale = [(k, e) for k, e in new if (t := entry_time(feed, e)) and t.timestamp() < cutoff]
    new = [(k, e) for k, e in new if (k, e) not in stale]
    print(f"[{name}] {len(new)} new" + (f", {len(stale)} old ignored" if stale else ""))

    if DRY_RUN:
        new = new[-2:]
    state.setdefault(name, [])
    if not DRY_RUN:
        for k, _ in stale:
            state[name].insert(0, k)
    for k, e in new[-MAX_PER_FEED:]:
        send(feed, e, state, k)
    # items beyond the cap go out as one summary message; if that fails they stay unseen
    overflow = new[:-MAX_PER_FEED]
    if overflow and (DRY_RUN or post_overflow(feed, overflow)):
        for k, _ in overflow:
            state[name].insert(0, k)
    state[name] = state[name][:keep]


def fetch_all(feeds: list) -> list:
    """Fetch every feed at once (network wait dominates); each result is entries or the exception."""
    def one(feed):
        try:
            return fetch_entries(feed)
        except Exception as ex:   # reported per feed in main(), never raised across threads
            return ex
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(one, feeds))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):   # emoji in messages break cp1252 consoles
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if not WEBHOOK and not DRY_RUN:
        print("GCHAT_WEBHOOK_URL is not set", file=sys.stderr)
        return 1

    if os.environ.get("TEST_MESSAGE") == "1":   # "Run workflow" > send test message: checks both webhooks
        targets = {"default space": WEBHOOK, "alerts space": WEBHOOK_ALERTS, "WordPress and PHP space": WEBHOOK_WP_PHP}
        sent: dict = {}
        for label, url in targets.items():
            if url and url not in sent:
                sent[url] = post(f"✅ *Feed bot* · test message to the {label}. Webhook works.", url)
        results = list(sent.values())
        if WEBHOOK_ALERTS == WEBHOOK:
            print("GCHAT_WEBHOOK_ALERTS is not set: alerts will go to the default space")
        if WEBHOOK_WP_PHP == WEBHOOK:
            print("GCHAT_WEBHOOK_WP_PHP is not set: WordPress and PHP news will go to the default space")
        return 0 if all(results) else 1

    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
        if not isinstance(state, dict):
            raise ValueError("expected a JSON object")
    except ValueError as ex:
        # Do not guess: treating it as empty would re-seed and silently skip items that arrived meanwhile.
        # Stop, leave the file untouched, and fail the job so the (throttled) failure notice goes out.
        print(f"state.json is unreadable ({type(ex).__name__}: {ex}). Run stopped without changing anything.\n"
              "Fix: restore it from git history (git log -- state.json), or delete it to re-seed from scratch.",
              file=sys.stderr)
        return 2

    for feed, fetched in zip(FEEDS, fetch_all(FEEDS)):
        name = feed["name"]
        try:
            if isinstance(fetched, Exception):
                raise fetched
            process_feed(feed, state, fetched)
        except Exception as ex:  # one broken feed or record must not stop the others
            print(f"[{name}] failed: {type(ex).__name__}: {ex}", file=sys.stderr)
            record_health(state, name, False)
        else:
            record_health(state, name, True)
        save_state(state)   # after every feed, so a later crash can't cause reposts
    return 0


if __name__ == "__main__":
    sys.exit(main())
