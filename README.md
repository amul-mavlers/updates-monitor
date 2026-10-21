# Feed alerts to Google Chat

Posts new incidents (GitHub, Cloudflare, Shopify status) and release news (WordPress, PHP, Shopify changelog) to Google Chat. Runs every 5 minutes on GitHub Actions (free on a public repo). On a private repo use `*/30` or slower to stay inside the free minutes.

## Setup

1. Put these files in a new GitHub repo (keep `.github/workflows/feed-alerts.yml`).
2. In two Chat spaces (Space name > Apps & integrations > Webhooks) create a webhook each.
3. Repo > Settings > Secrets and variables > Actions, add:
   - `GCHAT_WEBHOOK_URL`: default space (news, maintenance).
   - `GCHAT_WEBHOOK_ALERTS`: outages and security news. Optional; if unset, everything goes to the default space.
4. Actions tab > "Feed alerts to Google Chat" > Run workflow once. This first run records what each feed already has and posts only incidents that are still open.

## What gets posted where

| Item | Space |
|---|---|
| Incident updates (one Chat thread per incident) | alerts |
| News mentioning CVE, security, critical, vulnerability, zero-day, remote code execution | alerts |
| Scheduled maintenance (Cloudflare, nearby regions only) and other news | default |
| Feed health warnings, job failure notice | alerts |

Every message shows the date and time of the update (Asia/Kolkata by default; set `FEED_TZ`).

## Configuration

Edit `FEEDS` in `feed_to_gchat.py`. Status pages use `"api"` (a Statuspage base URL); news uses `"url"` (RSS/Atom). Environment variables: `FEED_TZ`, `GCHAT_WEBHOOK_ALERTS`, `DRY_RUN=1`.

## Local use

```
pip install -r requirements-dev.txt
DRY_RUN=1 python feed_to_gchat.py     # prints messages, posts nothing, saves no state
pytest
```

## Reliability notes

- State lives in `state.json`, committed back by the workflow after every run. Delete it to re-seed.
- A broken feed is logged and skipped; after 4 failed runs in a row the alerts space gets one warning.
- Posts are spaced about 1.1s apart and retried on 429/5xx.
- GitHub pauses scheduled workflows after 60 days without repo activity. Re-enable from the Actions tab if that happens.
