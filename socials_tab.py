"""📣 Socials — the social media manager page in the Portfolio section (2 Nov 2026).

Manav: "a socials tab on the portfolio section of our dash, where i can approve or not approve everything, its like a
social media manager page for us. and we can do all the work there." Six views: This month · To review · Journal · Gone out ·
Health · Ask for a post. Every button starts the website repo's `Social action` job (socials_gh.dispatch), which runs the same
command-line tool a session uses, so a refusal (a festival moved off its day, a caption the voice check stops) comes back here
with its reason. Nothing on this page posts anything: approved posts go out on their own, from the posting job.

★ OPEN BY CHOICE: Manav asked for no lock ("fully open, I accept the risk", 2 Nov 2026), so anyone with the dashboard link
can use this tab. Every action is written to the post's own log with the name typed at the top of the tab.
"""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import streamlit as st

import socials_gh as G

KIND = {"festival": "Festival", "advisory": "Advisory", "motion": "Film", "journal": "Journal", "dyk": "Did you know?",
        "qa": "Q&A", "recognition": "Recognition", "milestone": "Milestone", "edit": "The Edit", "spotlight": "Spotlight",
        "myth": "Myth vs Fact", "checklist": "Checklist"}
DOT = {"approved": "🟢", "published": "✅", "drafted": "🟠", "awaiting": "🟠", "changes": "🟣", "blocked": "🔴",
       "parked": "⚪", "cancelled": "⚫"}


def title(p: dict) -> str:
    if p.get("kind") == "festival":
        return p.get("subject", "Festival")
    subj = str(p.get("subject", "")).split("|")[0].replace("-", " ")
    return f"{KIND.get(p.get('kind'), str(p.get('kind', '')).title())} · {subj}".strip(" ·")


# ------------------------------------------------------------------ data, cached briefly; pictures cached for good

@st.cache_data(ttl=120, show_spinner="Reading the social queue…")
def _queue():
    return G.load_queue()


@st.cache_data(ttl=120, show_spinner=False)
def _journal():
    return G.load_journal()


@st.cache_data(ttl=60, show_spinner=False)
def _actions():
    return G.recent_actions(12)


@st.cache_data(ttl=300, show_spinner=False)
def _posting_runs():
    return G.posting_runs(6)


# a blob never changes, so its picture is kept for the life of the server (bounded), outside Streamlit's cache so the
# missing ones can be fetched side by side
_PICS: dict = {}


def _thumbs(oids: list[str], width: int = 240) -> dict:
    want = [o for o in dict.fromkeys(oids) if o and (o, width) not in _PICS]
    if want:
        raw = G.many_blobs(want)
        def shrink(o):
            try:
                return o, G.thumb_from(raw[o], width)
            except Exception:
                return o, None
        with ThreadPoolExecutor(max_workers=4) as ex:
            for o, jpg in ex.map(shrink, [o for o in want if o in raw]):
                if jpg:
                    _PICS[(o, width)] = jpg
        if len(_PICS) > 600:
            for k in list(_PICS)[:200]:
                _PICS.pop(k, None)
    return {o: _PICS.get((o, width)) for o in oids if o}


def _oid(p, name):
    return (p.get("_files", {}).get(name) or (None,))[0] if name else None


def _clear():
    _queue.clear(); _journal.clear(); _actions.clear()


# ------------------------------------------------------------------ the buttons

def _send(action, pid="", value="", value2="", label=""):
    try:
        G.dispatch(action, pid, value, value2, by=st.session_state.get("soc_by") or "dashboard")
        st.session_state.setdefault("soc_sent", []).insert(0, f"{label or action} · {pid}".strip(" ·"))
        _actions.clear()
        st.toast(f"Sent: {label or action}. It takes about a minute; press Refresh to see it.", icon="📨")
    except Exception as e:
        st.error(f"Could not send it: {e}")


def _actions_panel(p: dict, key: str):
    pid, status = p["id"], p.get("status")
    if status == "published":
        links = {k: v.get("url") for k, v in (p.get("published") or {}).items() if isinstance(v, dict) and v.get("url")}
        st.caption("Gone out. " + " · ".join(f"[{k.title()}]({u})" for k, u in links.items()))
        return
    c = st.columns(4)
    if status in G.NEEDS_YOU and status != "blocked":
        if c[0].button("✅ Approve", key=f"ap_{key}", type="primary", use_container_width=True):
            _send("approve", pid, label="approve")
    if status in ("parked", "cancelled", "changes"):
        if c[0].button("↩️ Back for review", key=f"rs_{key}", use_container_width=True):
            _send("restore", pid, label="back for review")
    if status not in ("parked", "cancelled"):
        if c[1].button("⏸️ Park", key=f"pk_{key}", use_container_width=True, help="Hold it back; it keeps its place"):
            _send("park", pid, label="park")
    with c[2].popover("✏️ Change", use_container_width=True):
        note = st.text_area("What should change?", key=f"cn_{key}", height=90)
        if st.button("Send the note", key=f"cs_{key}", disabled=not note.strip()):
            _send("change", pid, note.strip(), label="ask for a change")
    with c[3].popover("🗑️ Cancel", use_container_width=True):
        st.caption("Takes it off the calendar for good.")
        why = st.text_input("Why (optional)", key=f"cw_{key}")
        if st.button("Yes, cancel it", key=f"cx_{key}", type="primary"):
            _send("cancel", pid, why, label="cancel")
    m1, m2, m3 = st.columns([2, 1, 1])
    try:
        d0 = dt.date.fromisoformat(p["date"])
    except Exception:
        d0 = G.today_ist()
    new_d = m1.date_input("Move to", value=d0, key=f"md_{key}", min_value=G.today_ist(),
                          disabled=p.get("kind") == "festival", help="A festival greeting stays on its festival day")
    new_t = m2.text_input("Time (IST)", value=p.get("time", "19:00"), key=f"mt_{key}")
    if m3.button("Move", key=f"mv_{key}", use_container_width=True) and (new_d != d0 or new_t != p.get("time")):
        _send("move", pid, new_d.isoformat(), new_t.strip(), label=f"move to {new_d:%d %b} {new_t}")


def _captions(p: dict, key: str):
    caps = p.get("captions") or {}
    plats = [k for k in ("instagram", "facebook", "linkedin") if k in caps] or ["instagram"]
    tabs = st.tabs([k.title() for k in plats])
    lint = p.get("lint") or {}
    for t, plat in zip(tabs, plats):
        with t:
            txt = st.text_area("Caption", value=caps.get(plat, ""), key=f"cap_{plat}_{key}", height=170, label_visibility="collapsed")
            notes = (lint.get(plat) or {})
            if notes.get("block"):
                st.error("Voice check: " + "; ".join(notes["block"]))
            if notes.get("warn"):
                st.caption("Voice check notes: " + "; ".join(notes["warn"]))
            if txt != caps.get(plat, "") and p.get("status") != "published":
                st.caption("Saving runs the voice check first" + (" and sends an approved post back for your yes." if p.get("status") == "approved" else "."))
                if st.button(f"Save the {plat.title()} caption", key=f"cps_{plat}_{key}"):
                    _send("caption", p["id"], plat, txt, label=f"{plat} caption")
    if p.get("alt"):
        st.caption(f"Alt text: {p['alt']}")


def _media(p: dict, key: str, big: int = 420):
    slides = G.slide_files(p)
    vid = G.video_file(p)
    cover = G.cover_file(p)
    if p.get("format") == "carousel" and slides:
        pics = _thumbs([_oid(p, s) for s in slides[:8]], 360)
        cols = st.columns(min(4, len(slides[:8])))
        for i, s in enumerate(slides[:8]):
            if pics.get(_oid(p, s)):
                cols[i % len(cols)].image(pics[_oid(p, s)], use_container_width=True)
        return
    pic = _thumbs([_oid(p, cover)], big).get(_oid(p, cover)) if cover else None
    if pic:
        st.image(pic, use_container_width=True)
    if vid:
        if st.button("▶️ Play the Reel", key=f"pl_{key}"):
            st.session_state[f"vid_{key}"] = True
        if st.session_state.get(f"vid_{key}"):
            try:
                st.video(G.blob_bytes(_oid(p, vid)))
            except Exception as e:
                st.caption(f"Could not load the Reel: {e}")


def _card(p: dict, key: str, media: bool = True):
    with st.container(border=True):
        left, right = st.columns([2, 3]) if media else (None, st.container())
        if media:
            with left:
                _media(p, key)
        with right:
            st.markdown(f"**{title(p)}**  \n{DOT.get(p.get('status'), '•')} {G.STATUS_WORDS.get(p.get('status'), p.get('status'))}"
                        f" · {dt.date.fromisoformat(p['date']):%a %d %b} at {p.get('time', '')} IST"
                        f" · {p.get('format', '')}{' · AI art' if p.get('ai_art') else ''}")
            if p.get("change_note"):
                st.info(f"Change asked: {p['change_note']}")
            _captions(p, key)
            _actions_panel(p, key)
            with st.expander("History"):
                for line in (p.get("log") or [])[-8:]:
                    st.caption(line if isinstance(line, str) else f"{line.get('at', '')} {line.get('note', '')}")


# ------------------------------------------------------------------ the six views

def _month(posts, today):
    start = today - dt.timedelta(days=today.weekday())
    end = today + dt.timedelta(days=31)
    by_day = {}
    for p in G.live(posts):
        by_day.setdefault(p["date"], []).append(p)
    covers = [_oid(p, G.cover_file(p)) for d in by_day.values() for p in d if start.isoformat() <= p["date"] <= end.isoformat()]
    pics = _thumbs(covers, 200)
    st.caption("🟢 approved · 🟠 needs you · 🟣 changes asked · ⚪ parked · ✅ gone out · a day with no green post is empty")
    d = start
    while d <= end:
        cols = st.columns(7)
        for i in range(7):
            day = d + dt.timedelta(days=i)
            with cols[i]:
                ps = sorted(by_day.get(day.isoformat(), []), key=lambda x: x.get("time", ""))
                ok = any(x.get("status") in ("approved", "published") for x in ps)
                past = day < today
                head = f"**{day:%a %d %b}**" + (" · today" if day == today else "")
                st.markdown(head if ok or past else head + "  \n:orange[No approved post]")
                for x in ps:
                    pic = pics.get(_oid(x, G.cover_file(x)))
                    if pic:
                        st.image(pic, use_container_width=True)
                    with st.popover(f"{DOT.get(x.get('status'), '•')} {x.get('time', '')} {title(x)[:28]}", use_container_width=True):
                        _card(x, f"m_{x['id']}", media=False)      # the picture is already above; no second download
        d += dt.timedelta(days=7)
        st.divider()


def _review(posts, today):
    mine = G.needs_you(posts, today)
    if not mine:
        st.success("Nothing is waiting for you. Everything coming up is approved.")
    for p in mine:
        _card(p, f"r_{p['id']}")
    ahead = [p for p in posts if p.get("status") == "approved" and p["date"] >= today.isoformat()]
    st.markdown(f"**Approved and coming up ({len(ahead)})** · pick one to park, move, edit or cancel it")
    # one at a time: forty open cards would rebuild forty sets of controls on every click
    pick = st.selectbox("Approved post", [None] + [p["id"] for p in ahead], key="soc_pick_ahead", label_visibility="collapsed",
                        format_func=lambda i: "Choose a post…" if i is None else next(f"{dt.date.fromisoformat(p['date']):%a %d %b} · {p.get('time', '')} · {title(p)}" for p in ahead if p["id"] == i))
    if pick:
        _card(next(p for p in ahead if p["id"] == pick), f"a_{pick}")
    held = [p for p in posts if p.get("status") in ("parked",) and p["date"] >= (today - dt.timedelta(days=30)).isoformat()]
    if held:
        hp = st.selectbox(f"Parked ({len(held)})", [None] + [p["id"] for p in held], key="soc_pick_held",
                          format_func=lambda i: "Choose a parked post…" if i is None else next(f"{p['date']} · {title(p)}" for p in held if p["id"] == i))
        if hp:
            _card(next(p for p in held if p["id"] == hp), f"h_{hp}")


def _journal_view(arts):
    st.caption("A new article is drafted every Wednesday for the next Monday; approve it here and it goes live at 09:00 that Monday.")
    for a in arts[:10]:
        when = a.get("scheduled") or a.get("slot") or a.get("published") or a.get("drafted") or ""
        with st.container(border=True):
            st.markdown(f"**{a.get('title', a.get('slug'))}**  \n{a.get('status', '').title()} · {when} · {a.get('_words', 0):,} words · "
                        f"{len(a.get('sources') or [])} sources")
            if a.get("dek"):
                st.caption(a["dek"])
            if a.get("change_note"):
                st.info(f"Change asked: {a['change_note']}")
            pdf = next((n for n in a.get("_pack", {}) if n.endswith(".pdf")), None)
            c = st.columns(4)
            if pdf:
                k = f"jpdf_{a['slug']}"
                if c[0].button("📄 Get the PDF", key=k):
                    st.session_state[k + "_b"] = G.blob_bytes(a["_pack"][pdf])
                if st.session_state.get(k + "_b"):
                    c[0].download_button("Save the PDF", st.session_state[k + "_b"], file_name=pdf, mime="application/pdf", key=k + "_d")
            if a.get("status") == "draft":
                if c[1].button("✅ Approve", key=f"ja_{a['slug']}", type="primary"):
                    _send("journal-approve", a["slug"], label="approve the article")
                with c[2].popover("✏️ Ask for changes"):
                    n = st.text_area("What should change?", key=f"jn_{a['slug']}")
                    if st.button("Send", key=f"jns_{a['slug']}", disabled=not n.strip()):
                        _send("journal-note", a["slug"], n.strip(), label="ask for changes")
                with c[3].popover("🗑️ Drop"):
                    w = st.text_input("Why", key=f"jw_{a['slug']}")
                    if st.button("Yes, drop it", key=f"jd_{a['slug']}"):
                        _send("journal-drop", a["slug"], w or "dropped from the dashboard", label="drop the article")
            if a.get("questions"):
                with st.expander("Questions for the director"):
                    for q in a["questions"]:
                        st.caption(f"• {q}")


def _gone_out(posts):
    rows = G.gone_out(posts)[:60]
    if not rows:
        st.info("Nothing has gone out yet.")
        return
    df = pd.DataFrame([{"Date": r["date"], "Time": r.get("time", ""), "Post": title(r),
                        "Instagram": r["_links"].get("instagram"), "Facebook": r["_links"].get("facebook")} for r in rows])
    st.dataframe(df, hide_index=True, use_container_width=True,
                 column_config={"Instagram": st.column_config.LinkColumn(display_text="open"),
                                "Facebook": st.column_config.LinkColumn(display_text="open")})


def _health(posts, today):
    gaps = G.empty_days(posts, today)
    st.markdown("**Empty days in the next 31**: " + (", ".join(f"{d:%a %d %b}" for d in gaps) if gaps else "none 🎉"))
    try:
        runs = _posting_runs()
        st.markdown("**The posting job** (09:10 and 19:10 IST): " + " ".join(
            ("✅" if r["conclusion"] == "success" else "⏳" if r["status"] != "completed" else "❌") for r in runs)
            + (f" · last ran {pd.Timestamp(runs[0]['at']).tz_convert('Asia/Kolkata'):%d %b %I:%M %p}" if runs else ""))
        bad = [r for r in runs if r["conclusion"] == "failure"]
        if bad:
            st.error(f"The posting job failed at {pd.Timestamp(bad[0]['at']).tz_convert('Asia/Kolkata'):%d %b %I:%M %p}. [Open the run]({bad[0]['url']})")
    except Exception as e:
        st.warning(f"Could not read the posting job: {e}")
    st.markdown("**AI art spend** is still counted on the Mac that makes the images (the ₹400 cap lives there); it moves here when the weekly drafting run starts.")


def _ask():
    st.caption("Ask for a post in plain words. The weekly drafting run, or a working session, picks it up and drafts it for your approval.")
    txt = st.text_area("What should the post be about?", key="soc_req", placeholder="e.g. A Did you know? post about Kanchenjunga, on Saturday")
    if st.button("Send the request", disabled=not txt.strip(), type="primary"):
        _send("request", "", txt.strip(), label="request")


def _recent():
    try:
        acts = _actions()
    except Exception as e:
        st.caption(f"Could not read recent actions: {e}")
        return
    if not acts:
        return
    busy = any(a["status"] != "completed" for a in acts[:5])
    with st.expander("Recent actions" + (" · working…" if busy else ""), expanded=busy or any(a["conclusion"] == "failure" for a in acts[:2])):
        for a in acts[:8]:
            icon = "⏳" if a["status"] != "completed" else ("✅" if a["conclusion"] == "success" else "❌")
            when = pd.Timestamp(a["at"]).tz_convert("Asia/Kolkata").strftime("%d %b %I:%M %p") if a.get("at") else ""
            st.caption(f"{icon} {a['what']} · {when}" + (f" · **refused:** {a['why']}" if a.get("why") else ""))


def render():
    st.subheader("📣 Socials")
    if not G.token():
        st.warning("**The Socials tab is not connected yet.** It needs a GitHub token named `GH_SOCIAL_TOKEN` in this app's "
                   "secrets: a fine-grained token for the repo M4NAVV/peanuts-website only, with Contents: read and Actions: read "
                   "and write. Add it in the Space's Settings → Variables and secrets, then restart the Space.")
        return
    top = st.columns([3, 1, 1])
    top[0].text_input("Your name, for the log", key="soc_by", placeholder="dashboard")
    if top[2].button("🔄 Refresh", use_container_width=True):
        _clear()
        st.rerun()
    try:
        posts = _queue()
    except Exception as e:
        st.error(f"Could not read the social queue from GitHub: {e}")
        return
    today = G.today_ist()
    up = [p for p in posts if p["date"] >= today.isoformat()]
    gaps = G.empty_days(posts, today)
    mx = G.mix(up)
    k = st.columns(4)
    k[0].metric("Waiting for you", len(G.needs_you(posts, today)))
    k[1].metric("Approved, next 7 days", sum(1 for p in up if p.get("status") == "approved"
                                              and p["date"] < (today + dt.timedelta(days=7)).isoformat()))
    k[2].metric("Empty days, next 31", len(gaps))
    k[3].metric("AI art share", f"{mx['ai']:.0%}", help=f"Reels {mx['reels']:.0%} · designed {mx['designed']:.0%} · of {mx['n']} approved coming up. Rule: AI art at most 50%.")
    _recent()
    # one view at a time (not st.tabs, which builds every tab on every click)
    views = ["🗓️ This month", "✅ To review", "📰 Journal", "📤 Gone out", "🩺 Health", "💡 Ask for a post"]
    if "soc_view" not in st.session_state:
        st.session_state["soc_view"] = views[1] if G.needs_you(posts, today) else views[0]
    view = st.segmented_control("View", views, key="soc_view", label_visibility="collapsed") or views[0]
    if view == views[0]:
        _month(posts, today)
    elif view == views[1]:
        _review(posts, today)
    elif view == views[2]:
        try:
            _journal_view(_journal())
        except Exception as e:
            st.error(f"Could not read the Journal: {e}")
    elif view == views[3]:
        _gone_out(posts)
    elif view == views[4]:
        _health(posts, today)
    else:
        _ask()
