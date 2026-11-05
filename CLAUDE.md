# CLAUDE.md

Feed alerts bot: polls status pages and news feeds and posts new items to Google Chat. See README.md for setup and operations.

## How it works

- `feed_to_gchat.py` is the whole bot. A Cloudflare Worker (`worker/index.js`) starts the GitHub Actions workflow (`.github/workflows/feed-alerts.yml`) every 5 minutes; the workflow runs the script and commits `state.json`.
- Status pages (GitHub, Cloudflare, Shopify) are read from the Statuspage JSON API (`"api"` in `FEEDS`), not RSS. News uses RSS/Atom (`"url"`) through feedparser.
- Every source is normalised into feed-like entries, keyed by `entry_key()`, and compared with `state.json`. Only unseen keys are posted. Per-feed flow is in `process_feed()`.
- Incidents go to the alerts webhook, news to the default one (`is_urgent()`); a news feed with `"urgent": True` goes to alerts; a feed with `"space": "wp_php"` goes to the WordPress/PHP space (`GCHAT_WEBHOOK_WP_PHP`) with its security items also copied to alerts (`destinations()`). Incident updates share a Chat thread (`thread_key()`). Feeds are fetched in parallel by `fetch_all()`, then processed one by one.
- The Worker also posts to the alerts space (at most hourly) when it cannot start the workflow, and reminds the team before `TOKEN_EXPIRES`. It retries a transient GitHub error once first. Its public URL only returns `ok` / `not configured` with hardening headers: never add the repo name, token state or expiry to that response (the repo is public, so disclosure helps attackers).

## Commands

```
pip install -r requirements-dev.txt
py -m pytest -q test_feed_to_gchat.py     # Python tests (use `python` on Linux/macOS)
node worker/test.mjs                      # Worker tests
node worker/history.test.mjs              # D1 history tests
DRY_RUN=1 python feed_to_gchat.py         # prints messages, posts nothing, saves no state
```

On Windows set `PYTHONIOENCODING=utf-8` if the console cannot print emoji.

## Rules that matter

- Never put webhook URLs, tokens or API keys in any file. They live only in GitHub repository secrets (`GCHAT_WEBHOOK_URL`, `GCHAT_WEBHOOK_ALERTS`, `GCHAT_WEBHOOK_WP_PHP`) and the Worker secret `GH_TOKEN`. The repository is public.
- Do not trim the seen-key list to the feed's current length. Feeds change size, and old items then look new. `KEEP_SEEN` is a fixed 5,000; `MAX_AGE_DAYS` (30) also blocks old posts.
- Changing the key format in `entry_key()` makes every item look new. Delete `state.json` only when you want a fresh seed run; the first run posts nothing except open incidents.
- State is saved after every feed (`save_state`), so one feed failing must never stop the others. Keep `process_feed` exceptions caught in `main()`.
- Feed text is untrusted. Keep `safe()` on titles and summaries, and only allow http(s) links.
- Failed posts must not be recorded as seen, so they retry on the next run. The one exception is an item Chat permanently rejects (HTTP 400/413/422), which `send()` skips after `GIVE_UP_AFTER` tries. Never give up on 5xx, 429 or timeouts: a Chat outage must not drop alerts.
- A corrupt `state.json` stops `main()` with exit code 2 and changes nothing. Do not treat it as empty: that would re-seed and silently skip items.
- Titles are capped at `TITLE_LEN` so messages stay under Chat's 4,096-character limit.
- CI runs `ruff check .` and both test suites; keep them green. Lint rules are in `ruff.toml`.
- The Worker serves a public landing page at `/` (`worker/landing.js`, data from `catalog.json`) and `/health`. `catalog.py` builds `catalog.json` from the entries already fetched; `route()` in `feed_to_gchat.py` is the single source of routing for posting and for the page. Keep `catalog.json` deterministic (fixed example dates, no timestamp of its own) or the bot will commit it every run. The page must stay free of secrets, repo names, webhook names and external resources; keep the nonce CSP and the tests in `worker/test.mjs` that enforce this. Edit JS strings in `landing.js` without apostrophes inside single-quoted strings.
- Saved history: the bot (GitHub Actions) cannot use the D1 binding, so `record_event()` queues each posted message in `state["_outbox"]` and `flush_outbox()` POSTs it to the Worker's `/api/events` (`INGEST_URL` + `INGEST_TOKEN`); the Worker writes to D1 table `posted_messages` (`migrations/`). History must never affect alerts: failures are caught, events stay queued, 400-class rejections drop the batch, the outbox is capped, and logs show error types only (never the URL or token). The endpoint must keep: constant-time token check, size and count limits, field validation, `INSERT OR IGNORE`. `INGEST_TOKEN` is a shared secret, never a Cloudflare API token. The landing page shows only title, source, status, time and spaces from D1, never full message text.
- `MENTION_ALL` (@all on major/critical incidents) is opt-in. Do not turn it on by default.
- `requirements.txt` and `requirements-dev.txt` are generated lock files with hashes, installed with `pip install --require-hashes`. Never edit them by hand. Change `requirements.in` or `requirements-dev.in`, then run `pip-compile --generate-hashes --allow-unsafe --strip-extras --output-file requirements.txt requirements.in` (and the same for the dev file). Dependabot opens weekly update pull requests.
- Keep GitHub Actions pinned to commit SHAs. The `feed-alerts.yml` checkout uses `persist-credentials: false`; only the "Save state" step receives the repo token. Do not give the script or pip step the token.

## Adding or changing things

- New source: add one line to `FEEDS` (see the comments above it), run `DRY_RUN=1` to check the output, add a test if routing or parsing changes.
- Routing or message changes: edit `URGENT_RE`, `is_urgent()` or `build_message()`, and update `test_feed_to_gchat.py`.
- The Worker only triggers the workflow. Its `REPO`, `WORKFLOW` and `REF` settings are in `wrangler.jsonc`; the Worker is named `updates-monitor`.
- Cloudflare is connected to the repo and redeploys on pushes. Build watch paths should be `worker/**` and `wrangler.jsonc` only, so the bot's `state.json` commits do not trigger builds.
