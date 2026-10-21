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
