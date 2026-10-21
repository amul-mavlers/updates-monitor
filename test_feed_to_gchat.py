import json
from datetime import datetime, timezone

import pytest

import feed_to_gchat as f

STATUS = {"name": "GitHub Status", "kind": "status", "api": "x"}
NEWS = {"name": "PHP News", "kind": "news", "label": "News", "dedupe": "php"}


def incident(status="investigating", name="Delays", updated="2026-10-21T17:09:35.000Z", **kw):
    inc = {"id": "abc", "name": name, "shortlink": "https://stspg.io/x",
           "incident_updates": [{"status": status, "body": "We are looking.", "created_at": updated}]}
    inc.update(kw)
    return inc


def test_urgent_regex():
    assert f.URGENT_RE.search("Fixes CVE-2024-12345")
    assert f.URGENT_RE.search("Security release")
    assert not f.URGENT_RE.search("mission-critical sites")
    assert not f.URGENT_RE.search("WordPress 7.2 Beta")


def test_api_entries_latest_update_and_status():
    inc = incident("investigating")
    inc["incident_updates"].append({"status": "resolved", "body": "Fixed.", "created_at": "2026-10-21T18:00:00.000Z"})
    (e,) = f.api_entries({"incidents": [inc]})
    assert e["status"] == "resolved" and e["summary"] == "Fixed."
    msg = f.build_message(STATUS, e)
    assert msg.startswith("🟢 *GitHub Status* · Resolved")
    assert "🕒 21 Oct 2026, 23:30 IST" in msg


def test_api_entries_skips_bad_records():
    bad = [{"id": "1", "name": "x", "incident_updates": []},
           {"id": "2", "name": "y", "incident_updates": [{"status": "resolved"}]},   # no created_at
           {"name": "no id", "incident_updates": [{"created_at": "2026-01-01T00:00:00Z"}]}]
    assert f.api_entries({"incidents": bad}) == []
    assert len(f.api_entries({"incidents": bad + [incident()]})) == 1


def test_maintenance_label_start_time_and_region_filter():
    feed = {**STATUS, "maintenance": True, "maintenance_match": r"\(Ahmedabad"}
    near = incident("scheduled", "AMD (Ahmedabad) on 2026-11-02", scheduled_for="2026-11-02T21:00:00.000Z")
    far = incident("scheduled", "LAX (Los Angeles) on 2026-11-02", scheduled_for="2026-11-02T21:00:00.000Z")
    far["id"] = "other"
    entries = f.api_entries({"scheduled_maintenances": [near, far]}, feed)
    assert [e["title"] for e in entries] == ["AMD (Ahmedabad) on 2026-11-02"]
    msg = f.build_message(feed, entries[0])
    assert "Scheduled maintenance" in msg and "🕒 Starts 3 Nov 2026, 02:30 IST" in msg
    assert not f.is_urgent(feed, entries[0])


def test_maintenance_completed_uses_update_time():
    inc = incident("completed", "AMD (Ahmedabad)", scheduled_for="2026-11-02T21:00:00.000Z",
                   updated="2026-11-03T01:00:00.000Z")
    (e,) = f.api_entries({"scheduled_maintenances": [inc]})
    msg = f.build_message(STATUS, e)
    assert "Maintenance completed" in msg and "Starts" not in msg


def test_status_keys_change_per_update_and_threads_are_stable():
    a = f.api_entries({"incidents": [incident(updated="2026-10-21T10:00:00.000Z")]})[0]
    b = f.api_entries({"incidents": [incident("resolved", updated="2026-10-21T11:00:00.000Z")]})[0]
    assert f.entry_key(STATUS, a) != f.entry_key(STATUS, b)
    assert f.thread_key(STATUS, a) == f.thread_key(STATUS, b)
    assert f.thread_key(NEWS, a) is None


def test_entry_key_never_empty():
    assert f.entry_key(NEWS, {"summary": "hello"}) != ""
    assert f.entry_key(NEWS, {"summary": "hello"}) != f.entry_key(NEWS, {"summary": "other"})


def test_dedupe_title_matches_php_variants():
    assert f.dedupe_title("PHP 8.5.12 Released!") == f.dedupe_title("PHP 8.5.12 released!")


def test_routing():
    assert f.is_urgent(STATUS, {"title": "x"})
    assert f.is_urgent(NEWS, {"title": "PHP security advisory"})
    assert not f.is_urgent(NEWS, {"title": "WordPress 7.2 Beta 1"})


def test_format_time_bad_zone_falls_back_to_utc(monkeypatch):
    monkeypatch.setattr(f, "TZ_NAME", "Not/AZone")
    assert f.format_time(datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)) == "21 Oct 2026, 12:00 UTC"


class Resp:
    def __init__(self, code=200, headers=None):
        self.status_code, self.headers = code, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise f.requests.HTTPError(str(self.status_code))


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(f, "DRY_RUN", False)
    monkeypatch.setattr(f.time, "sleep", lambda s: None)
    monkeypatch.setattr(f, "POST_GAP", 0)


def test_post_retries_on_429(fast, monkeypatch):
    seq = [Resp(429, {"Retry-After": "1"}), Resp(200)]
    monkeypatch.setattr(f.requests, "post", lambda *a, **k: seq.pop(0))
    assert f.post("hi", "http://x") is True and not seq


def test_post_gives_up_on_400(fast, monkeypatch):
    monkeypatch.setattr(f.requests, "post", lambda *a, **k: Resp(400))
    assert f.post("hi", "http://x") is False


def test_health_warning_once_after_threshold(fast, monkeypatch):
    sent = []
    monkeypatch.setattr(f, "post", lambda text, url, thread=None: sent.append(text) or True)
    st = {}
    for _ in range(f.HEALTH_FAIL_RUNS + 2):
        f.record_health(st, "X", False)
    assert len(sent) == 1
    f.record_health(st, "X", True)
    assert st["_health"] == {}


def run_main(monkeypatch, tmp_path, feeds, entries_by_feed, posts):
    monkeypatch.setattr(f, "DRY_RUN", False)
    monkeypatch.setattr(f, "WEBHOOK", "http://default")
    monkeypatch.setattr(f, "WEBHOOK_ALERTS", "http://alerts")
    monkeypatch.setattr(f, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(f, "FEEDS", feeds)
    monkeypatch.setattr(f, "fetch_entries", lambda feed: entries_by_feed[feed["name"]]())
    monkeypatch.setattr(f, "post", lambda text, url, thread=None: posts.append((url, text)) or True)
    return f.main()


def test_first_run_announces_only_open_incidents_then_only_new(monkeypatch, tmp_path):
    current = [f.api_entries({"incidents": [incident("investigating", "Open one"),
                                            {**incident("resolved", "Old one"), "id": "old"}]})]
    posts = []
    feeds = {"GitHub Status": lambda: current[0]}
    run_main(monkeypatch, tmp_path, [STATUS], feeds, posts)
    assert len(posts) == 1 and "Open one" in posts[0][1] and posts[0][0] == "http://alerts"
    posts.clear()
    run_main(monkeypatch, tmp_path, [STATUS], feeds, posts)
    assert posts == []
    current[0] = f.api_entries({"incidents": [incident("resolved", "Open one", updated="2026-10-21T19:00:00.000Z")]})
    run_main(monkeypatch, tmp_path, [STATUS], feeds, posts)
    assert len(posts) == 1 and "Resolved" in posts[0][1]


def test_one_crashing_feed_does_not_stop_others_and_state_is_saved(monkeypatch, tmp_path):
    good = {"name": "A", "kind": "news", "url": "u"}
    bad = {"name": "B", "kind": "news", "url": "u"}

    def boom():
        raise KeyError("created_at")

    run_main(monkeypatch, tmp_path, [bad, good], {"B": boom, "A": lambda: [{"id": "1", "title": "t"}]}, [])
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["A"] == ["1"] and state["_health"] == {"B": 1}


def test_cross_feed_dedupe(monkeypatch, tmp_path):
    a = {"name": "PHP News", "kind": "news", "url": "u", "dedupe": "php"}
    b = {"name": "PHP Releases", "kind": "news", "url": "u", "dedupe": "php"}
    posts = []
    data = {"PHP News": [{"id": "seed", "title": "seed"}], "PHP Releases": [{"id": "seed", "title": "seed"}]}
    feeds = {k: (lambda k=k: data[k]) for k in data}
    run_main(monkeypatch, tmp_path, [a, b], feeds, posts)       # first run seeds
    data["PHP News"] = [{"id": "n1", "title": "PHP 8.5.12 Released!"}] + data["PHP News"]
    data["PHP Releases"] = [{"id": "r1", "title": "PHP 8.5.12 released!"}] + data["PHP Releases"]
    run_main(monkeypatch, tmp_path, [a, b], feeds, posts)
    assert len(posts) == 1 and "PHP News" in posts[0][1]


# --- QC fixes ---

def test_safe_neutralises_chat_markup():
    assert f.safe("<https://evil|Click> *bold* ~x~ `c`") == "‹https://evil|Click› bold x c"
    e = {"title": "Hi *there* <b>", "summary": "x <https://evil|go>", "link": "https://ok.example/a|b"}
    msg = f.build_message(NEWS, e)
    assert "<https://evil" not in msg and "*there*" not in msg
    assert msg.endswith("<https://ok.example/a%7Cb|Read more>")


def test_link_must_be_http():
    assert "Read more" not in f.build_message(NEWS, {"title": "t", "link": "javascript:alert(1)"})


def test_api_entries_merges_active_and_upcoming_maintenance():
    up = incident("scheduled", "AMD (Ahmedabad)", scheduled_for="2026-11-02T21:00:00.000Z",
                  updated="2026-11-01T10:00:00.000Z")
    act = incident("in_progress", "AMD (Ahmedabad)", scheduled_for="2026-11-02T21:00:00.000Z",
                   updated="2026-11-02T21:05:00.000Z")
    (e,) = f.api_entries({"scheduled_maintenances": [up, act]})
    assert e["status"] == "in progress" and "Maintenance in progress" in f.build_message(STATUS, e)


def test_fetch_fetches_active_and_survives_optional_failure(monkeypatch):
    feed = {**STATUS, "api": "https://s/api/v2", "maintenance": True}
    seen = []

    class R:
        def __init__(self, url):
            self.url = url

        def raise_for_status(self):
            if "active" in self.url:
                raise f.requests.HTTPError("503")

        def json(self):
            return {"incidents": [incident()]} if "incidents" in self.url else {"scheduled_maintenances": []}

    monkeypatch.setattr(f.requests, "get", lambda url, **k: seen.append(url) or R(url))
    assert len(f.fetch_entries(feed)) == 1
    assert any(u.endswith("upcoming.json") for u in seen) and any(u.endswith("active.json") for u in seen)


def test_news_sorted_newest_first(monkeypatch):
    xml = (b'<rss version="2.0"><channel><item><title>old</title><guid>1</guid><pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate></item>'
           b'<item><title>new</title><guid>2</guid><pubDate>Mon, 01 Jan 2026 00:00:00 +0000</pubDate></item></channel></rss>')

    class R:
        content = xml

        def raise_for_status(self):
            pass

    monkeypatch.setattr(f.requests, "get", lambda *a, **k: R())
    assert [e["title"] for e in f.fetch_entries({"name": "n", "kind": "news", "url": "u"})] == ["new", "old"]


def test_post_connection_error_retried_and_url_not_logged(fast, monkeypatch, capsys):
    calls = []

    def fake(url, **k):
        calls.append(1)
        if len(calls) == 1:
            raise f.requests.ConnectionError("failed to reach https://chat.googleapis.com/x?key=SECRET")
        return Resp(200)

    monkeypatch.setattr(f.requests, "post", fake)
    assert f.post("hi", "http://x") is True
    monkeypatch.setattr(f.requests, "post", lambda *a, **k: (_ for _ in ()).throw(f.requests.ReadTimeout("key=SECRET")))
    assert f.post("hi", "http://x") is False
    assert "SECRET" not in capsys.readouterr().err


def test_post_bad_retry_after_date_does_not_crash(fast, monkeypatch):
    seq = [Resp(429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), Resp(200)]
    monkeypatch.setattr(f.requests, "post", lambda *a, **k: seq.pop(0))
    assert f.post("hi", "http://x") is True


def test_first_run_failed_announce_keeps_other_keys_and_retries_open_incident(monkeypatch, tmp_path):
    current = f.api_entries({"incidents": [incident("investigating", "Open one"),
                                           {**incident("resolved", "Old one"), "id": "old"}]})
    posts, ok = [], [False]
    monkeypatch.setattr(f, "DRY_RUN", False)
    monkeypatch.setattr(f, "WEBHOOK", "http://d")
    monkeypatch.setattr(f, "WEBHOOK_ALERTS", "http://a")
    monkeypatch.setattr(f, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(f, "FEEDS", [STATUS])
    monkeypatch.setattr(f, "fetch_entries", lambda feed: current)
    monkeypatch.setattr(f, "post", lambda text, url, thread=None: posts.append(text) or ok[0])
    f.main()
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert len(state["GitHub Status"]) == 1 and "old|" in state["GitHub Status"][0]   # old kept, open one forgotten
    ok[0] = True
    f.main()
    assert len(posts) == 2 and "Open one" in posts[-1]   # retried next run


def test_overflow_posts_one_summary_and_marks_seen(monkeypatch, tmp_path):
    posts = []
    monkeypatch.setattr(f, "DRY_RUN", False)
    monkeypatch.setattr(f, "WEBHOOK", "http://d")
    monkeypatch.setattr(f, "WEBHOOK_ALERTS", "http://a")
    monkeypatch.setattr(f, "STATE_FILE", tmp_path / "state.json")
    feed = {"name": "N", "kind": "news", "url": "u", "label": "News"}
    monkeypatch.setattr(f, "FEEDS", [feed])
    data = [[{"id": "seed", "title": "seed"}]]
    monkeypatch.setattr(f, "fetch_entries", lambda fd: data[0])
    monkeypatch.setattr(f, "post", lambda text, url, thread=None: posts.append((url, text)) or True)
    f.main()   # seed
    data[0] = [{"id": f"n{i}", "title": f"Item {i}", "link": f"https://x/{i}"} for i in range(9, -1, -1)] + data[0]
    f.main()
    assert len(posts) == f.MAX_PER_FEED + 1
    assert "5 more updates" in posts[-1][1]   # summary goes out last
    posts.clear()
    f.main()
    assert posts == []   # everything is now seen


def test_test_message_posts_to_both_spaces(monkeypatch):
    sent = []
    monkeypatch.setenv("TEST_MESSAGE", "1")
    monkeypatch.setattr(f, "DRY_RUN", False)
    monkeypatch.setattr(f, "WEBHOOK", "http://d")
    monkeypatch.setattr(f, "WEBHOOK_ALERTS", "http://a")
    monkeypatch.setattr(f, "post", lambda text, url, thread=None: sent.append(url) or True)
    assert f.main() == 0 and sent == ["http://d", "http://a"]
    sent.clear()
    monkeypatch.setattr(f, "post", lambda text, url, thread=None: sent.append(url) or False)
    assert f.main() == 1
