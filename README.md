# Feed alerts to Google Chat

Posts new incidents (GitHub, Cloudflare, Shopify status) and release news (WordPress, PHP, Shopify changelog) to Google Chat. Runs every 5 minutes on GitHub Actions (free on a public repo). On a private repo use `*/30` or slower to stay inside the free minutes.

## Setup

1. Put these files in a new GitHub repo (keep `.github/workflows/feed-alerts.yml`).
2. In two Chat spaces (Space name > Apps & integrations > Webhooks) create a webhook each.
3. Repo > Settings > Secrets and variables > Actions, add:
   - `GCHAT_WEBHOOK_URL`: default space (news, maintenance).
   - `GCHAT_WEBHOOK_ALERTS`: outages and security news. Optional; if unset, everything goes to the default space.
   - `GCHAT_WEBHOOK_WP_PHP`: a separate space for WordPress News, PHP News and PHP Releases. Optional; if unset they go to the default space. Their security items are also copied to the alerts space.
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
- If `state.json` is corrupt (for example a merge conflict), the run stops without changing anything and the job fails. Restore the file from git history (`git log -- state.json`), or delete it to re-seed.
- The "workflow failed" notice is limited to the first 5 minutes of each hour, so a lasting problem does not post every 5 minutes.
- Titles are cut to 200 characters (Chat rejects messages over 4,096). An item Chat permanently rejects (HTTP 400 and similar) is skipped after 3 tries. A Chat outage never drops an alert: those are retried on every run.
- CI (`.github/workflows/ci.yml`) runs ruff, the Python tests and the Worker tests on every push and pull request.
- Dependencies are locked with hashes (`requirements.txt`, generated from `requirements.in`) and installed with `--require-hashes`, so a tampered or swapped package is refused. To update: edit `requirements.in`, then run `pip-compile --generate-hashes --allow-unsafe --strip-extras --output-file requirements.txt requirements.in`. Dependabot also opens weekly update pull requests (`.github/dependabot.yml`).
- The repo token is only available to the "Save state" step, which pulls and pushes `state.json`. The step that installs packages and the script that reads feeds run without it.

## Reliable 5-minute trigger (Cloudflare Worker)

GitHub's `schedule:` is best-effort and can run hours late. `worker/index.js` is a Cloudflare Worker whose cron trigger (`wrangler.jsonc`, every 5 minutes) starts this workflow through GitHub's `workflow_dispatch` API. The workflow's own schedule stays as a backup.

1. Create a fine-grained GitHub token (Settings > Developer settings > Fine-grained tokens): this repo only, permission **Actions: Read and write**.
2. In Cloudflare: Workers > updates-monitor > Settings > Variables and Secrets > add a **Secret** named `GH_TOKEN` with that token.
3. In the Worker's Settings > Build > Build watch paths, include only `worker/**` and `wrangler.jsonc`, so the bot's `state.json` commits don't trigger a redeploy each time.
4. Check: Workers > updates-monitor > Logs. A new "Manually run" entry appears in the Actions tab every 5 minutes. The Worker's public URL only answers `ok` or `not configured` (it deliberately shows no repo name, token state or expiry date); a missing setting is named in the Logs and in the Chat warning.
   The Worker retries a transient GitHub error (5xx or network) once before it warns; a 401, 403 or 404 is reported straight away.

5. Optional but recommended: in the Worker, add a **Secret** named `GCHAT_WEBHOOK_ALERTS` (the same Downtime-space webhook). If the Worker cannot start the workflow, for example because the token expired, it then posts a warning to Chat at most once an hour. Without it the failure is only visible in the Worker's logs.
6. Optional: set `"TOKEN_EXPIRES": "YYYY-MM-DD"` in `wrangler.jsonc` to the token's expiry date. The Worker then posts a daily reminder during the last 14 days.

Test locally with `node worker/test.mjs`.

## Message extras

- Incidents show GitHub's severity (`Minor impact`, `Major impact`, `Critical impact`), the affected components, and `Resolved after 2 h 14 min` when they close.
- Set `MENTION_ALL=1` (uncomment it in the workflow) to start major and critical incident messages with an @all mention. It is off by default so nobody is paged by accident.
- Feeds are fetched in parallel, so a run takes a few seconds.
