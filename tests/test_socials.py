"""The Socials tab (2 Nov 2026): how it reads the queue and what it sends. No network: GitHub's answers are written out here."""
import datetime as dt
import json

import socials_gh as G


def _post(pid, date, status="approved", **kw):
    return {"name": pid, "type": "tree", "object": {"entries": [
        {"name": "post.json", "oid": f"o-{pid}", "object": {"text": json.dumps({"id": pid, "date": date, "time": "19:00",
                                                                                  "status": status, **kw})}},
        {"name": "cover.jpg", "oid": f"c-{pid}", "object": {}},
        {"name": "reel.mp4", "oid": f"v-{pid}", "object": {}}]}}


def _answer(*folders):
    return {"repository": {"object": {"entries": list(folders) + [{"name": "README.md", "type": "blob"}]}}}


def test_the_queue_is_read_with_its_files_and_in_date_order():
    q = G.parse_queue(_answer(_post("b", "2026-11-05"), _post("a", "2026-11-03"),
                              {"name": "broken", "type": "tree", "object": {"entries": [{"name": "post.json", "oid": "x", "object": {"text": "{not json"}}]}}))
    assert [p["id"] for p in q] == ["a", "b"]                       # the broken folder is skipped, not fatal
    assert G.cover_file(q[0]) == "cover.jpg" and G.video_file(q[0]) == "reel.mp4"
    assert q[0]["_files"]["cover.jpg"][0] == "c-a"


def test_an_empty_day_is_a_day_without_an_approved_post():
    posts = [{"date": "2026-11-03", "status": "approved"}, {"date": "2026-11-04", "status": "drafted"},
             {"date": "2026-11-05", "status": "published"}, {"date": "2026-11-06", "status": "parked"}]
    gaps = G.empty_days(posts, dt.date(2026, 11, 3), days=4)
    assert gaps == [dt.date(2026, 11, 4), dt.date(2026, 11, 6)]   # a draft or a parked post does not fill a day


def test_needs_you_is_only_what_waits_for_a_yes_from_today_on():
    posts = [{"date": "2026-11-01", "status": "drafted"}, {"date": "2026-11-03", "status": "drafted"},
             {"date": "2026-11-03", "status": "changes"}, {"date": "2026-11-04", "status": "approved"},
             {"date": "2026-11-05", "status": "blocked"}]
    assert len(G.needs_you(posts, dt.date(2026, 11, 2))) == 3


def test_the_mix_counts_approved_posts_only():
    posts = [{"status": "approved", "ai_art": {"x": 1}}, {"status": "approved", "format": "reel"},
             {"status": "approved"}, {"status": "approved"}, {"status": "drafted", "ai_art": {"x": 1}}]
    m = G.mix(posts)
    assert m["n"] == 4 and m["ai"] == 0.25 and m["reels"] == 0.25 and m["designed"] == 0.5


def test_what_the_buttons_send():
    body = G.dispatch_inputs("move", "2026-11-08-fest-diwali", "2026-11-09", "09:00", by="Manav")
    assert body == {"ref": "master", "inputs": {"action": "move", "id": "2026-11-08-fest-diwali", "value": "2026-11-09",
                                                "value2": "09:00", "by": "Manav"}}
    long = G.dispatch_inputs("caption", "x", "instagram", "y" * 5000, by="z" * 200)["inputs"]
    assert len(long["value2"]) == 2500 and len(long["by"]) == 60   # trimmed to what the job accepts


def test_gone_out_carries_its_links():
    posts = [{"id": "a", "date": "2026-11-01", "status": "published",
              "published": {"instagram": {"ok": True, "url": "https://instagram.com/p/1"}, "journal": {"ok": False}}},
             {"id": "b", "date": "2026-11-02", "status": "approved"}]
    out = G.gone_out(posts)
    assert [p["id"] for p in out] == ["a"] and out[0]["_links"] == {"instagram": "https://instagram.com/p/1"}


def test_the_journal_is_read_with_its_pack():
    meta = {"slug": "s-1", "title": "T", "status": "draft", "drafted": "2026-10-30"}
    data = {"repository": {
        "arts": {"entries": [{"name": "s-1.md", "object": {"text": "---\n" + json.dumps(meta) + "\n---\nword " * 3}},
                             {"name": "notes.txt", "object": {"text": "x"}}]},
        "packs": {"entries": [{"name": "s-1", "object": {"entries": [{"name": "T - draft.pdf", "oid": "p1"}]}}]}}}
    arts = G.parse_journal(data)
    assert len(arts) == 1 and arts[0]["_pack"] == {"T - draft.pdf": "p1"}


def test_no_token_says_so_rather_than_failing_quietly(monkeypatch):
    monkeypatch.delenv("GH_SOCIAL_TOKEN", raising=False)
    monkeypatch.setattr(G, "token", lambda: None)
    try:
        G.load_queue()
    except G.NotConfigured:
        return
    raise AssertionError("expected NotConfigured")


def test_a_post_under_the_bar_is_marked_not_hidden():
    """2 Nov 2026, Manav: a draft below the quality bar is "show it to me marked"."""
    good = {"quality": {"scores": {"stop": 8, "grasp": 9, "brand": 9, "original": 8, "accurate": 10}}}
    assert G.quality(good)["marked"] is False and G.quality(good)["avg"] == 8.8
    calm = {"quality": {"scores": {"stop": 6, "grasp": 9, "brand": 9, "original": 8, "accurate": 10},
                        "notes": {"stop": "calm: small icons in big empty fields"}, "below_standard": True}}
    q = G.quality(calm)
    assert q["marked"] and "stop: calm: small icons in big empty fields" in q["why"]
    unmarked_low = {"quality": {"scores": {"stop": 6, "grasp": 9, "brand": 9, "original": 8, "accurate": 10}}}
    assert G.quality(unmarked_low)["marked"]                       # the tab does its own sum, never trusts the flag alone
    assert G.quality({})["marked"] is False and G.quality({})["scored"] is False   # old posts: no badge
    assert G.quality({"quality": {"checks": ["money / offer language: 'Flat 30%'"]}})["marked"]


def test_the_reject_form_sends_the_reason(monkeypatch):
    """2 Nov 2026: the reason boxes lived in popovers that closed while Manav typed. Now a form: pick, type, Send."""
    from streamlit.testing.v1 import AppTest

    def app():
        import streamlit as st
        import socials_gh as G
        import socials_tab as T
        sent = st.session_state.setdefault("sent", [])
        G.dispatch = lambda *a, **k: sent.append(a)
        T._feedback_form({"id": "2026-11-21-wedding-watch-01", "status": "drafted"}, "t")

    at = AppTest.from_function(app).run()
    at.multiselect(key="fbt_t").set_value(["Boring", "Lacks depth"])
    at.text_area(key="fbn_t").input("line art doesn't work as a still")
    at.radio(key="fbr_t").set_value("Reject: take it off the calendar")
    at.button[0].click().run()
    assert at.session_state["sent"] == [("cancel", "2026-11-21-wedding-watch-01",
                                         "Boring; Lacks depth. line art doesn't work as a still", "")]
    at2 = AppTest.from_function(app).run()
    at2.button[0].click().run()                                    # nothing picked, nothing written
    assert at2.session_state["sent"] == [] and at2.error
