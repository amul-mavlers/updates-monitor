import json
import sys

import catalog
import feed_to_gchat as f

STATUS = {"name": "GitHub Status", "kind": "status", "api": "x"}
CLOUDFLARE = {"name": "Cloudflare Status", "kind": "status", "api": "y", "maintenance": True}
WP = {"name": "WordPress News", "kind": "news", "label": "New post", "space": "wp_php"}
WOO = {"name": "WooCommerce Dev", "kind": "news", "label": "WooCommerce"}
FEEDS = [STATUS, CLOUDFLARE, WP, WOO]


def results():
    inc = {"id": "a", "name": "Delays", "shortlink": "https://stspg.io/x", "impact": "minor",
           "incident_updates": [{"status": "investigating", "body": "Looking.", "created_at": "2026-10-21T17:09:35.000Z"}]}
    return [
        f.api_entries({"incidents": [inc]}),
        [],                                           # no entries: skipped, not an error
        [{"id": "1", "title": "Critical PHP Security Release", "link": "https://wordpress.org/a",
          "published": "2026-10-21T10:00:00+00:00"},
         {"id": "2", "title": "WordPress 7.2 Beta", "link": "https://wordpress.org/b", "published": "2026-10-20T10:00:00+00:00"}],
        ConnectionError("down"),                      # a failed feed is skipped too
    ]


def test_build_has_live_cards_and_all_example_kinds():
    data = catalog.build(f, FEEDS, results())
    cats = {c["cat"] for c in data["cards"]}
    assert cats == {"incidents", "maintenance", "security", "news", "system"}
    live = [c for c in data["cards"] if c["live"]]
    assert {c["source"] for c in live} == {"GitHub Status", "WordPress News"}
    kinds = {c["kind"] for c in data["cards"] if not c["live"]}
    assert {"Investigating · Major impact", "Scheduled maintenance", "Maintenance in progress", "Maintenance completed",
            "Feed health warning", "Burst summary", "Workflow failed", "Test message"} <= kinds
    assert data["routing"][0] == {"source": "GitHub Status", "how": "Status page API", "space": "Downtime", "extra": ""}
    assert data["updated"].startswith("2026-10-21")


def test_spaces_follow_the_bots_real_routing():
    data = catalog.build(f, FEEDS, results())
    by_title = {c["text"].split("\n")[1]: c for c in data["cards"] if c["live"]}
    assert by_title["*Critical PHP Security Release*"]["spaces"] == ["WordPress & PHP", "Downtime"]
    assert by_title["*WordPress 7.2 Beta*"]["spaces"] == ["WordPress & PHP"]
    assert by_title["*Delays*"]["spaces"] == ["Downtime"]


def test_page_routing_matches_what_is_posted(monkeypatch):
    monkeypatch.setattr(f, "WEBHOOK", "D")
    monkeypatch.setattr(f, "WEBHOOK_ALERTS", "A")
    monkeypatch.setattr(f, "WEBHOOK_WP_PHP", "W")
    names = {"D": "default", "A": "alerts", "W": "wp_php"}
    for feed, e in [(WP, {"title": "Critical PHP Security Release"}), (WP, {"title": "WordPress 7.2"}),
                    (WOO, {"title": "Security advisory"}), (WOO, {"title": "WooCommerce 11"}),
                    (STATUS, {"title": "x"}), (CLOUDFLARE, {"title": "x", "maintenance": True})]:
        assert [names[u] for u in f.destinations(feed, e)] == f.route(feed, f.is_urgent(feed, e))


def test_output_is_stable_and_only_rewritten_when_content_changes(tmp_path):
    path = tmp_path / "catalog.json"
    assert catalog.write(f, FEEDS, results(), path) is True
    first = path.read_text(encoding="utf-8")
    assert catalog.write(f, FEEDS, results(), path) is False          # same feeds: no change, so no commit
    assert path.read_text(encoding="utf-8") == first
    changed = results()
    changed[2].append({"id": "3", "title": "Another post", "link": "https://wordpress.org/c",
                       "published": "2026-10-22T10:00:00+00:00"})
    changed[2].sort(key=lambda e: e["published"], reverse=True)
    assert catalog.write(f, FEEDS, changed, path) is True
    assert not list(tmp_path.glob("*.tmp"))


def test_examples_use_a_fixed_date_and_leave_global_state_alone():
    before = f.MENTION_ALL
    data = catalog.build(f, FEEDS, results())
    assert f.MENTION_ALL == before
    first = next(c for c in data["cards"] if c["kind"] == "Investigating · Major impact")
    assert "15 Jan 2026" in first["text"] and not first["live"]
    assert first["text"].startswith("<users/all> ")        # the one card that demonstrates the opt-in @all mention
    later = next(c for c in data["cards"] if c["kind"].startswith("Identified"))
    assert "<users/all>" not in later["text"]


def test_catalog_contains_nothing_secret(monkeypatch):
    monkeypatch.setattr(f, "WEBHOOK", "https://chat.googleapis.com/v1/spaces/X/messages?key=SECRETKEY&token=SECRETTOKEN")
    text = json.dumps(catalog.build(f, FEEDS, results()))
    assert "SECRETKEY" not in text and "SECRETTOKEN" not in text and "chat.googleapis" not in text


def test_main_writes_the_catalog_and_a_catalog_failure_never_fails_the_run(monkeypatch, tmp_path):
    monkeypatch.setattr(f, "DRY_RUN", False)
    monkeypatch.setattr(f, "WEBHOOK", "http://d")
    monkeypatch.setattr(f, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(f, "FEEDS", [WOO])
    monkeypatch.setattr(f, "fetch_entries", lambda feed: [{"id": "1", "title": "Woo 11", "link": "https://x"}])
    monkeypatch.setattr(f, "post", lambda *a, **k: True)
    assert f.main() == 0
    written = json.loads(f.CATALOG_FILE.read_text(encoding="utf-8"))
    assert any(c["source"] == "WooCommerce Dev" for c in written["cards"])

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(catalog, "write", boom)
    monkeypatch.setitem(sys.modules, "catalog", catalog)
    assert f.main() == 0                               # alerts are unaffected


def test_dry_run_does_not_write_the_catalog(monkeypatch):
    monkeypatch.setattr(f, "DRY_RUN", True)
    monkeypatch.setattr(f, "FEEDS", [WOO])
    monkeypatch.setattr(f, "fetch_entries", lambda feed: [{"id": "1", "title": "Woo 11", "link": "https://x"}])
    monkeypatch.setattr(f, "post", lambda *a, **k: True)
    f.main()
    assert not f.CATALOG_FILE.exists()
