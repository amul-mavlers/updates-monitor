# CLAUDE.md

Feed alerts bot: polls status pages and news feeds and posts new items to Google Chat. See README.md for setup and operations.

## How it works

- `feed_to_gchat.py` is the whole bot. A Cloudflare Worker (`worker/index.js`) starts the GitHub Actions workflow (`.github/workflows/feed-alerts.yml`) every 5 minutes; the workflow runs the script and commits `state.json`.
- Status pages (GitHub, Cloudflare, Shopify) are read from the Statuspage JSON API (`"api"` in `FEEDS`), not RSS. News uses RSS/Atom (`"url"`) through feedparser.
- Every source is normalised into feed-like entries, keyed by `entry_key()`, and compared with `state.json`. Only unseen keys are posted. Per-feed flow is in `process_feed()`.
- Incidents go to the alerts webhook, news to the default one (`is_urgent()`); a news feed with `"urgent": True` goes to alerts; a feed with `"space": "wp_php"` goes to the WordPress/PHP space (`GCHAT_WEBHOOK_WP_PHP`) with its security items also copied to alerts (`destinations()`). Incident updates share a Chat thread (`thread_key()`). Feeds are fetched in parallel by `fetch_all()`, then processed one by one.
- The Worker also posts to the alerts space (at most hourly) when it cannot start the workflow, and reminds the team before `TOKEN_EXPIRES`.

## Commands

```
pip install -r requirements-dev.txt
py -m pytest -q test_feed_to_gchat.py     # Python tests (use `python` on Linux/macOS)
node worker/test.mjs                      # Worker tests
DRY_RUN=1 python feed_to_gchat.py         # prints messages, posts nothing, saves no state
```

On Windows set `PYTHONIOENCODING=utf-8` if the console cannot print emoji.

## Rules that matter

- Never put webhook URLs, tokens or API keys in any file. They live only in GitHub repository secrets (`GCHAT_WEBHOOK_URL`, `GCHAT_WEBHOOK_ALERTS`, `GCHAT_WEBHOOK_WP_PHP`) and the Worker secret `GH_TOKEN`. The repository is public.
- Do not trim the seen-key list to the feed's current length. Feeds change size, and old items then look new. `KEEP_SEEN` is a fixed 5,000; `MAX_AGE_DAYS` (30) also blocks old posts.
- Changing the key format in `entry_key()` makes every item look new. Delete `state.json` only when you want a fresh seed run; the first run posts nothing except open incidents.
- State is saved after every feed (`save_state`), so one feed failing must never stop the others. Keep `process_feed` exceptions caught in `main()`.
- Feed text is untrusted. Keep `safe()` on titles and summaries, and only allow http(s) links.
- Failed posts must not be recorded as seen, so they retry on the next run.
- `MENTION_ALL` (@all on major/critical incidents) is opt-in. Do not turn it on by default.
- Keep dependencies pinned in `requirements.txt`, and GitHub Actions pinned to commit SHAs.

## Adding or changing things

- New source: add one line to `FEEDS` (see the comments above it), run `DRY_RUN=1` to check the output, add a test if routing or parsing changes.
- Routing or message changes: edit `URGENT_RE`, `is_urgent()` or `build_message()`, and update `test_feed_to_gchat.py`.
- The Worker only triggers the workflow. Its `REPO`, `WORKFLOW` and `REF` settings are in `wrangler.jsonc`; the Worker is named `updates-monitor`.
- Cloudflare is connected to the repo and redeploys on pushes. Build watch paths should be `worker/**` and `wrangler.jsonc` only, so the bot's `state.json` commits do not trigger builds.
