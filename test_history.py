import json

import feed_to_gchat as f

WP = {"name": "WordPress News", "kind": "news", "label": "New post", "space": "wp_php"}
WOO = {"name": "WooCommerce Dev", "kind": "news", "label": "WooCommerce"}


class Resp:
    def __init__(self, code=200):
        self.status_code = code


def enable(monkeypatch, url="https://worker.example/api/events", token="ingest-secret"):
    monkeypatch.setattr(f, "INGEST_URL", url)
    monkeypatch.setattr(f, "INGEST_TOKEN", token)
    monkeypatch.setattr(f, "DRY_RUN", False)
    monkeypatch.setattr(f, "WEBHOOK", "http://d")
    monkeypatch.setattr(f, "WEBHOOK_ALERTS", "http://a")
    monkeypatch.setattr(f, "WEBHOOK_WP_PHP", "http://w")
    monkeypatch.setattr(f, "post", lambda *a, **k: True)


def raises(exc):
    def _raise(*args, **kwargs):
        raise exc
    return _raise


def test_nothing_is_recorded_unless_both_settings_exist(monkeypatch):
    enable(monkeypatch, url="")
    state = {}
    assert f.announce(WOO, {"id": "1", "title": "Woo 11", "link": "https://x"}, state) is True
    assert "_outbox" not in state
    enable(monkeypatch, token="")
    assert f.announce(WOO, {"id": "1", "title": "Woo 11", "link": "https://x"}, state) is True
    assert "_outbox" not in state


def test_posted_message_is_queued_with_everything_the_history_needs(monkeypatch):
    enable(monkeypatch)
    state = {}
    e = {"id": "9", "title": "Critical PHP Security Release", "link": "https://wordpress.org/a", "summary": "x"}
    assert f.announce(WP, e, state, "9") is True
    (ev,) = state["_outbox"]
    assert ev["key"] == "WordPress News|9"
    assert ev["source"] == "WordPress News" and ev["kind"] == "New post" and ev["category"] == "security"
    assert ev["spaces"] == ["WordPress & PHP", "Downtime"]
    assert ev["title"] == "Critical PHP Security Release" and ev["link"] == "https://wordpress.org/a"
    assert ev["posted_at"].endswith("Z") and "Critical PHP Security Release" in ev["text"]


def test_unsafe_links_are_not_stored(monkeypatch):
    enable(monkeypatch)
    state = {}
    f.announce(WOO, {"id": "1", "title": "t", "link": "javascript:alert(1)"}, state)
    assert state["_outbox"][0]["link"] == ""


def test_failed_deduped_and_dry_run_posts_are_not_recorded(monkeypatch):
    enable(monkeypatch)
    state = {}
    monkeypatch.setattr(f, "post", lambda *a, **k: False)
    assert f.announce(WOO, {"id": "1", "title": "t"}, state) is False
    assert "_outbox" not in state
    monkeypatch.setattr(f, "post", lambda *a, **k: True)
    php = {"name": "PHP News", "kind": "news", "dedupe": "php"}
    state = {"_dedupe": {"php": [f.dedupe_title("PHP 8.5.12 Released!")]}}
    assert f.announce(php, {"id": "2", "title": "PHP 8.5.12 released!"}, state) is True
    assert "_outbox" not in state
    monkeypatch.setattr(f, "DRY_RUN", True)
    f.announce(WOO, {"id": "3", "title": "t"}, state)
    assert "_outbox" not in state


def test_outbox_is_capped(monkeypatch):
    enable(monkeypatch)
    state = {}
    for i in range(f.OUTBOX_MAX + 30):
        f.announce(WOO, {"id": str(i), "title": f"t{i}"}, state)
    assert len(state["_outbox"]) == f.OUTBOX_MAX
    assert state["_outbox"][-1]["key"] == f"WooCommerce Dev|{f.OUTBOX_MAX + 29}"     # newest kept


def queued(n):
    return {"_outbox": [{"key": f"k{i}", "title": "t"} for i in range(n)]}


def test_flush_sends_with_the_token_and_clears_the_outbox(monkeypatch):
    enable(monkeypatch)
    seen = []
    monkeypatch.setattr(f.requests, "post", lambda url, **k: seen.append((url, k)) or Resp(200))
    state = queued(3)
    f.flush_outbox(state)
    ((url, kw),) = seen
    assert url == "https://worker.example/api/events"
    assert kw["headers"]["Authorization"] == "Bearer ingest-secret"
    assert [e["key"] for e in kw["json"]["events"]] == ["k0", "k1", "k2"]
    assert "_outbox" not in state


def test_flush_batches_and_limits_one_run(monkeypatch):
    enable(monkeypatch)
    sizes = []
    monkeypatch.setattr(f.requests, "post", lambda url, **k: sizes.append(len(k["json"]["events"])) or Resp(200))
    state = queued(120)
    f.flush_outbox(state)
    assert sizes == [50, 50, 20] and "_outbox" not in state
    sizes.clear()
    state = queued(400)
    f.flush_outbox(state)
    assert sizes == [50] * 5 and len(state["_outbox"]) == 150      # the rest waits for the next run


def test_server_errors_keep_the_events_for_the_next_run(monkeypatch, capsys):
    enable(monkeypatch)
    for code in (401, 500, 503):
        monkeypatch.setattr(f.requests, "post", lambda url, code=code, **k: Resp(code))
        state = queued(3)
        f.flush_outbox(state)
        assert len(state["_outbox"]) == 3
    leaky = f.requests.ConnectionError("https://worker.example Bearer ingest-secret")
    monkeypatch.setattr(f.requests, "post", raises(leaky))
    state = queued(3)
    f.flush_outbox(state)
    err = capsys.readouterr().err
    assert len(state["_outbox"]) == 3
    assert "ingest-secret" not in err and "worker.example" not in err


def test_a_batch_the_worker_will_never_accept_is_dropped(monkeypatch):
    enable(monkeypatch)
    monkeypatch.setattr(f.requests, "post", lambda *a, **k: Resp(400))
    state = queued(3)
    f.flush_outbox(state)
    assert "_outbox" not in state


def test_flush_does_nothing_when_disabled_or_empty(monkeypatch):
    enable(monkeypatch, url="")
    monkeypatch.setattr(f.requests, "post", raises(AssertionError("must not be called")))
    state = queued(2)
    f.flush_outbox(state)
    assert len(state["_outbox"]) == 2
    enable(monkeypatch)
    f.flush_outbox({})
    f.flush_outbox({"_outbox": []})


def run_main(monkeypatch, tmp_path, ingest_status):
    enable(monkeypatch)
    monkeypatch.setattr(f, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(f, "FEEDS", [WOO])
    data = [[{"id": "seed", "title": "seed"}]]
    monkeypatch.setattr(f, "fetch_entries", lambda feed: data[0])
    f.main()   # seed
    data[0] = [{"id": "new1", "title": "Woo 11", "link": "https://x"}] + data[0]
    calls = []
    monkeypatch.setattr(f.requests, "post", lambda url, **k: calls.append(k["json"]["events"]) or Resp(ingest_status))
    assert f.main() == 0
    return calls, json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))


def test_end_to_end_posted_items_reach_the_worker_and_the_outbox_empties(monkeypatch, tmp_path):
    calls, state = run_main(monkeypatch, tmp_path, 200)
    assert len(calls) == 1 and calls[0][0]["key"] == "WooCommerce Dev|new1"
    assert "_outbox" not in state and "new1" in state["WooCommerce Dev"]


def test_end_to_end_when_the_worker_is_down_alerts_still_go_out_and_events_wait(monkeypatch, tmp_path):
    calls, state = run_main(monkeypatch, tmp_path, 503)
    assert "new1" in state["WooCommerce Dev"]                       # the alert was posted and remembered
    assert [e["key"] for e in state["_outbox"]] == ["WooCommerce Dev|new1"]   # history waits for the next run


def test_a_crash_while_sending_history_never_breaks_the_run(monkeypatch, tmp_path):
    enable(monkeypatch)
    monkeypatch.setattr(f, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(f, "FEEDS", [WOO])
    data = [[{"id": "seed", "title": "seed"}]]
    monkeypatch.setattr(f, "fetch_entries", lambda feed: data[0])
    f.main()
    data[0] = [{"id": "n", "title": "Woo 12"}] + data[0]
    monkeypatch.setattr(f.requests, "post", raises(RuntimeError("boom")))
    assert f.main() == 0
    assert "n" in json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["WooCommerce Dev"]
