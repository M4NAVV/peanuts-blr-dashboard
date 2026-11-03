"""📣 Socials — the social media manager page in the Portfolio section (2 Nov 2026).

Manav: "a socials tab on the portfolio section of our dash, where i can approve or not approve everything, its like a
social media manager page for us. and we can do all the work there." Then (v2, same day): "for the reels, it should also
play them in preview, so i can inspect them in the site only, and the overall Ui can be more professional. and also if
there are carousals, i should be able to view the whole carousal, to see all the slides of it."

Six sections: Calendar · Review · Journal · Published · Health · Requests. Every post opens in one PREVIEW window
(st.dialog): a Reel plays there, a carousel shows every slide with previous/next and a strip of all slides, and the captions
and buttons sit beside it. Heavy media is fetched only when a preview is opened, so the page itself stays light.

Every button starts the website repo's `Social action` job (socials_gh.dispatch), which runs the same command-line tool a
session uses, so a refusal (a festival moved off its day, a caption the voice check stops) comes back with its reason.
Nothing on this page posts anything: approved posts go out on their own, from the posting job.

★ OPEN BY CHOICE: Manav asked for no lock ("fully open, I accept the risk", 2 Nov 2026). Every action is written to the
post's own log with the name typed at the top of the page.
"""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import streamlit as st

import socials_gh as G

KIND = {"festival": "Festival greeting", "advisory": "Advisory", "motion": "Film", "journal": "Journal", "dyk": "Did you know?",
        "qa": "Q&A", "recognition": "Recognition", "milestone": "Milestone", "edit": "The Edit", "spotlight": "Spotlight",
        "myth": "Myth vs Fact", "checklist": "Checklist", "edu": "Retail lesson"}
# status -> (label, css class)
PILL = {"approved": ("Approved", "ok"), "published": ("Published", "live"), "drafted": ("Needs review", "rev"),
        "awaiting": ("Needs review", "rev"), "changes": ("Changes asked", "chg"), "blocked": ("Voice check failed", "bad"),
        "parked": ("Parked", "off"), "cancelled": ("Cancelled", "off")}
FORMAT = {"reel": "Reel", "carousel": "Carousel", "single": "Post"}

CSS = """<style>
.soc-head h2{margin:0 0 2px;font-weight:700;letter-spacing:-.01em}
.soc-head p{margin:0;color:#6b6b6b;font-size:.92rem}
.soc-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:14px 0 6px}
.soc-kpi{border:1px solid rgba(20,83,45,.16);border-radius:10px;padding:12px 14px;background:rgba(20,83,45,.03)}
.soc-kpi span{display:block;font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:#6b6b6b;font-weight:600}
.soc-kpi b{display:block;font-size:1.7rem;line-height:1.2;margin-top:4px;color:#14532d;font-variant-numeric:tabular-nums}
.soc-kpi.warn b{color:#a35a00}
.soc-kpi small{color:#6b6b6b}
.soc-pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:.68rem;font-weight:600;letter-spacing:.02em;white-space:nowrap}
.soc-pill.ok{background:#e3f1e8;color:#14532d}.soc-pill.live{background:#14532d;color:#fff}
.soc-pill.rev{background:#fdefd5;color:#8a5200}.soc-pill.chg{background:#ede5fa;color:#5b3a9a}
.soc-pill.bad{background:#fbe1de;color:#b3261e}.soc-pill.off{background:#ececea;color:#666}
.soc-day{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px}
.soc-day b{font-size:.95rem}.soc-day span{font-size:.72rem;color:#8a8a8a;text-transform:uppercase;letter-spacing:.06em}
.soc-day.today b{color:#14532d}
.soc-empty{font-size:.78rem;color:#a35a00;margin:6px 0}
.soc-meta{font-size:.76rem;color:#555;line-height:1.35;margin:4px 0 2px}
.soc-row-title{font-weight:600;font-size:.95rem}
.soc-sub{color:#6b6b6b;font-size:.82rem}
.soc-banner{border-left:3px solid #a35a00;background:#fff8ec;padding:8px 12px;border-radius:4px;font-size:.86rem;margin:6px 0}
.soc-banner.busy{border-color:#14532d;background:#eef6f1}
.soc-counter{text-align:center;font-size:.85rem;color:#555;padding-top:6px}
@media (prefers-color-scheme: dark){.soc-kpi{background:rgba(127,199,150,.06);border-color:rgba(127,199,150,.25)}
 .soc-kpi b{color:#8fd3a5}.soc-banner{background:#2d2414}.soc-banner.busy{background:#13261b}}
@media (max-width: 760px){.soc-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>"""


def title(p: dict) -> str:
    if p.get("kind") == "festival":
        return p.get("subject", "Festival")
    subj = str(p.get("subject", "")).split("|")[0].replace("-", " ").strip()
    kind = KIND.get(p.get("kind"), str(p.get("kind", "")).title())
    return f"{kind}: {subj[:1].upper() + subj[1:]}" if subj else kind


def pill(status: str) -> str:
    label, cls = PILL.get(status, (str(status).title(), "off"))
    return f"<span class='soc-pill {cls}'>{label}</span>"


def flag(p: dict) -> str:
    """★ 2 Nov 2026: a draft below the quality bar is shown MARKED, never hidden."""
    return "<span class='soc-pill bad'>Below standard</span>" if G.quality(p)["marked"] else ""


def when(p: dict) -> str:
    try:
        return f"{dt.date.fromisoformat(p['date']):%a %d %b} · {p.get('time', '')}"
    except Exception:
        return f"{p.get('date', '')} {p.get('time', '')}"


def kind_line(p: dict) -> str:
    bits = [FORMAT.get(p.get("format"), str(p.get("format", "")).title())]
    if p.get("format") == "carousel" and G.slide_files(p):
        bits[0] += f" · {len(G.slide_files(p))} slides"
    if p.get("ai_art"):
        bits.append("AI art")
    return " · ".join(b for b in bits if b)


# ------------------------------------------------------------------ data, cached briefly; media cached for good

@st.cache_data(ttl=120, show_spinner="Reading the social queue…")
def _queue():
    return G.load_queue()


@st.cache_data(ttl=120, show_spinner=False)
def _journal():
    return G.load_journal()


@st.cache_data(ttl=45, show_spinner=False)
def _actions():
    return G.recent_actions(12)


@st.cache_data(ttl=300, show_spinner=False)
def _posting_runs():
    return G.posting_runs(6)


@st.cache_data(ttl=600, show_spinner=False)
def _results():
    return G.parse_results(G.load_text("social/state/results.json"))


@st.cache_data(ttl=120, show_spinner=False)
def _requests_text():
    return G.load_text("social/requests.md")


# a blob never changes, so its picture or film is kept for the life of the server (bounded), outside Streamlit's cache
# so the missing ones can be fetched side by side
_PICS: dict = {}
_VIDS: dict = {}


def _thumbs(oids: list, width: int = 240, crop: bool = False) -> dict:
    want = [o for o in dict.fromkeys(oids) if o and (o, width, crop) not in _PICS]
    if want:
        raw = G.many_blobs(want)

        def shrink(o):
            try:
                return o, G.thumb_from(raw[o], width, crop)
            except Exception:
                return o, None
        with ThreadPoolExecutor(max_workers=4) as ex:
            for o, jpg in ex.map(shrink, [o for o in want if o in raw]):
                if jpg:
                    _PICS[(o, width, crop)] = jpg
        if len(_PICS) > 800:
            for k in list(_PICS)[:250]:
                _PICS.pop(k, None)
    return {o: _PICS.get((o, width, crop)) for o in oids if o}


def _video(oid: str) -> bytes | None:
    if oid not in _VIDS:
        _VIDS[oid] = G.blob_bytes(oid)
        while len(_VIDS) > 12:                       # a dozen Reels at ~6-10 MB each, at most
            _VIDS.pop(next(iter(_VIDS)))
    return _VIDS[oid]


def _oid(p, name):
    return (p.get("_files", {}).get(name) or (None,))[0] if name else None


def _clear():
    _queue.clear(); _journal.clear(); _actions.clear(); _requests_text.clear(); _results.clear()


# ------------------------------------------------------------------ the buttons

def _send(action, pid="", value="", value2="", label=""):
    try:
        G.dispatch(action, pid, value, value2, by=st.session_state.get("soc_by") or "dashboard")
        _actions.clear()
        st.toast(f"Sent: {label or action}. It takes about a minute; press Refresh to see it.", icon="📨")
    except Exception as e:
        st.error(f"Could not send it: {e}")


# ★ 2 Nov 2026 (Manav: "i am trying to enter my reason in the dropdown that comes when i reject, but the UI is not
# made properly"): the reasons lived in popovers inside the preview dialog, which close on every keystroke's rerun, so
# the send button never became clickable. Now ONE form: nothing reruns while he types; one Send. And the reason is
# not decoration — it lands in social/state/feedback.jsonl and both weekly routines read it before designing.
REASONS = ("Boring", "Lacks depth", "Line art doesn't work as a still", "Hard to read", "Off-brand",
           "Too similar to a recent post", "Wrong or doubtful fact", "Wrong tone")
THEN = {"Ask for changes": "change", "Reject: take it off the calendar": "cancel", "Park it for now": "park"}


def _feedback_form(p: dict, key: str):
    with st.form(f"fb_{key}", border=True, clear_on_submit=False):
        st.markdown("**Not right? Say why — the drafting runs learn from it.**")
        tags = st.multiselect("What's wrong", REASONS, key=f"fbt_{key}", placeholder="Pick any that apply")
        note = st.text_area("In your words", key=f"fbn_{key}", height=90,
                            placeholder="e.g. the drawings don't work as a still; show the real outfits")
        then = st.radio("Then", list(THEN), key=f"fbr_{key}", horizontal=True)
        sent = st.form_submit_button("Send", type="primary")
    if sent:
        reason = "; ".join(tags) + (". " if tags and note.strip() else "") + note.strip()
        if not reason:
            st.error("Pick a reason or write one, so the drafting runs can learn from it.")
        else:
            _send(THEN[then], p["id"], reason[:600], label=then.split(":")[0].lower())


def _actions_panel(p: dict, key: str):
    pid, status = p["id"], p.get("status")
    if status == "published":
        links = {k: v.get("url") for k, v in (p.get("published") or {}).items() if isinstance(v, dict) and v.get("url")}
        st.markdown("Published. " + " · ".join(f"[Open on {k.title()}]({u})" for k, u in links.items()))
        return
    c = st.columns(2)
    if status in G.NEEDS_YOU and status != "blocked":
        if c[0].button("Approve", key=f"ap_{key}", type="primary", use_container_width=True):
            _send("approve", pid, label="approve")
    elif status in ("parked", "cancelled", "changes"):
        if c[0].button("Back to review", key=f"rs_{key}", use_container_width=True):
            _send("restore", pid, label="back to review")
    if status not in ("parked", "cancelled"):
        if c[1].button("Park", key=f"pk_{key}", use_container_width=True, help="Hold it back; it keeps its place"):
            _send("park", pid, label="park")
    if status != "cancelled":
        _feedback_form(p, key)
    m1, m2, m3 = st.columns([2, 1, 1], vertical_alignment="bottom")
    try:
        d0 = dt.date.fromisoformat(p["date"])
    except Exception:
        d0 = G.today_ist()
    new_d = m1.date_input("Reschedule", value=max(d0, G.today_ist()), key=f"md_{key}", min_value=G.today_ist(),
                          disabled=p.get("kind") == "festival", help="A festival greeting stays on its festival day")
    new_t = m2.text_input("Time (IST)", value=p.get("time", "19:00"), key=f"mt_{key}")
    if m3.button("Move", key=f"mv_{key}", use_container_width=True) and (new_d != d0 or new_t != p.get("time")):
        _send("move", pid, new_d.isoformat(), new_t.strip(), label=f"move to {new_d:%d %b} {new_t}")


def _captions(p: dict, key: str):
    caps = p.get("captions") or {}
    plats = [k for k in ("instagram", "facebook", "linkedin") if k in caps] or ["instagram"]
    names = {"instagram": "Instagram", "facebook": "Facebook", "linkedin": "LinkedIn"}
    tabs = st.tabs([names[k] for k in plats])
    lint = p.get("lint") or {}
    for t, plat in zip(tabs, plats):
        with t:
            txt = st.text_area("Caption", value=caps.get(plat, ""), key=f"cap_{plat}_{key}", height=200, label_visibility="collapsed")
            notes = lint.get(plat) or {}
            if notes.get("block"):
                st.error("Voice check: " + "; ".join(notes["block"]))
            if notes.get("warn"):
                st.caption("Voice check notes: " + "; ".join(notes["warn"]))
            if txt != caps.get(plat, "") and p.get("status") != "published":
                st.caption("Saving runs the voice check first" + (" and sends an approved post back for your approval." if p.get("status") == "approved" else "."))
                if st.button(f"Save {names[plat]} caption", key=f"cps_{plat}_{key}"):
                    _send("caption", p["id"], plat, txt, label=f"{plat} caption")


# ------------------------------------------------------------------ the preview window

def _media(p: dict, key: str):
    """The post as it will appear: the Reel playing, every slide of a carousel, or the image."""
    vid, slides, cover = G.video_file(p), G.slide_files(p), G.cover_file(p)
    if vid:
        try:
            st.video(_video(_oid(p, vid)), autoplay=True, muted=True, loop=True)
            st.caption("Playing muted; use the player to turn the sound on.")
        except Exception as e:
            st.warning(f"Could not load the Reel: {e}")
        return
    if p.get("format") == "carousel" and slides:
        n = len(slides)
        k = f"slide_{key}"
        i = min(st.session_state.get(k, 0), n - 1)
        big = _thumbs([_oid(p, slides[i])], 720).get(_oid(p, slides[i]))
        if big:
            st.image(big, use_container_width=True)
        a, b, c = st.columns([1, 2, 1])
        if a.button("‹ Previous", key=f"pv_{key}", disabled=i == 0, use_container_width=True):
            st.session_state[k] = i - 1
            st.rerun(scope="fragment")
        b.markdown(f"<div class='soc-counter'>Slide {i + 1} of {n}</div>", unsafe_allow_html=True)
        if c.button("Next ›", key=f"nx_{key}", disabled=i == n - 1, use_container_width=True):
            st.session_state[k] = i + 1
            st.rerun(scope="fragment")
        strip = _thumbs([_oid(p, s) for s in slides], 160)
        per = 5
        for r in range(0, n, per):
            cols = st.columns(per)
            for j, s in enumerate(slides[r:r + per]):
                with cols[j]:
                    if strip.get(_oid(p, s)):
                        st.image(strip[_oid(p, s)], use_container_width=True)
                    if st.button(f"{r + j + 1}", key=f"go_{key}_{r + j}", use_container_width=True,
                                 type="primary" if r + j == i else "secondary"):
                        st.session_state[k] = r + j
                        st.rerun(scope="fragment")
        return
    pic = _thumbs([_oid(p, cover)], 720).get(_oid(p, cover)) if cover else None
    if pic:
        st.image(pic, use_container_width=True)
    else:
        st.caption("No picture in this post's folder.")


@st.dialog("Post preview", width="large")
def _preview(pid: str):
    p = next((x for x in _queue() if x["id"] == pid), None)
    if not p:
        st.warning("This post is no longer in the queue. Press Refresh.")
        return
    key = f"pv_{pid}"
    left, right = st.columns([5, 6], gap="large")
    with left:
        _media(p, key)
    with right:
        st.markdown(f"### {title(p)}")
        st.markdown(f"{pill(p.get('status'))} &nbsp; <span class='soc-sub'>{when(p)} IST · {kind_line(p)}</span>",
                    unsafe_allow_html=True)
        if p.get("change_note"):
            st.info(f"Change asked: {p['change_note']}")
        q = G.quality(p)
        if q["marked"]:
            st.warning("**Below our quality bar.** " + (" · ".join(q["why"]) if q["why"] else "Its scores are under the bar."))
        if q["scored"]:
            st.caption("Quality scores: " + " · ".join(f"{k} {v:g}" for k, v in q["scores"].items())
                       + f" · average {q['avg']:g} (bar: 8, none under 7)")
        _captions(p, key)
        st.markdown("")
        _actions_panel(p, key)
        if p.get("alt"):
            with st.expander("Alt text"):
                st.caption(p["alt"])
        with st.expander("History"):
            for line in (p.get("log") or [])[-10:]:
                st.caption(line if isinstance(line, str) else f"{line.get('at', '')} {line.get('note', '')}")


def _open(pid: str, key: str, label: str = "Preview", primary: bool = False):
    if st.button(label, key=key, use_container_width=True, type="primary" if primary else "secondary"):
        _preview(pid)


# ------------------------------------------------------------------ the sections

def _calendar(posts, today):
    start = today - dt.timedelta(days=today.weekday())
    end = today + dt.timedelta(days=31)
    by_day = {}
    for p in G.live(posts):
        if start.isoformat() <= p["date"] <= end.isoformat():
            by_day.setdefault(p["date"], []).append(p)
    pics = _thumbs([_oid(p, G.cover_file(p)) for d in by_day.values() for p in d], 260, crop=True)
    st.markdown(" ".join(pill(s) for s in ("approved", "drafted", "changes", "parked", "published"))
                + " &nbsp; <span class='soc-sub'>A day with nothing approved is marked in amber.</span>", unsafe_allow_html=True)
    heads = st.columns(7)
    for i, name in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
        heads[i].markdown(f"<div class='soc-sub' style='text-align:center'>{name}</div>", unsafe_allow_html=True)
    d = start
    while d <= end:
        cols = st.columns(7, gap="small")
        for i in range(7):
            day = d + dt.timedelta(days=i)
            ps = sorted(by_day.get(day.isoformat(), []), key=lambda x: x.get("time", ""))
            ok = any(x.get("status") in ("approved", "published") for x in ps)
            with cols[i].container(border=True, height=430):
                st.markdown(f"<div class='soc-day{' today' if day == today else ''}'><b>{day:%d %b}</b>"
                            f"<span>{'Today' if day == today else ''}</span></div>", unsafe_allow_html=True)
                if not ok and day >= today:
                    st.markdown("<div class='soc-empty'>Nothing approved yet</div>", unsafe_allow_html=True)
                for x in ps:
                    pic = pics.get(_oid(x, G.cover_file(x)))
                    if pic:
                        st.image(pic, use_container_width=True)
                    st.markdown(f"<div class='soc-meta'>{x.get('time', '')} · {title(x)[:40]}</div>{pill(x.get('status'))}",
                                unsafe_allow_html=True)
                    _open(x["id"], f"cal_{x['id']}")
        d += dt.timedelta(days=7)


def _row(p, key, pics, quick_approve=False):
    with st.container(border=True):
        c = st.columns([1, 5, 2, 2], vertical_alignment="center")
        pic = pics.get(_oid(p, G.cover_file(p)))
        if pic:
            c[0].image(pic, use_container_width=True)
        c[1].markdown(f"<div class='soc-row-title'>{title(p)}</div><div class='soc-sub'>{when(p)} IST · {kind_line(p)}</div>"
                      + (f"<div class='soc-sub'>Change asked: {p['change_note']}</div>" if p.get("change_note") else ""),
                      unsafe_allow_html=True)
        q = G.quality(p)
        c[2].markdown(pill(p.get("status")) + (f"<br>{flag(p)}" if q["marked"] else ""), unsafe_allow_html=True)
        if q["marked"] and q["why"]:
            c[1].caption("Why: " + q["why"][0][:140])
        with c[3]:
            _open(p["id"], f"row_{key}", primary=not quick_approve)
            if quick_approve and p.get("status") in G.NEEDS_YOU and p.get("status") != "blocked":
                if st.button("Approve", key=f"qa_{key}", type="primary", use_container_width=True):
                    _send("approve", p["id"], label="approve")


def _review(posts, today):
    mine = G.needs_you(posts, today)
    ahead = [p for p in posts if p.get("status") == "approved" and p["date"] >= today.isoformat()]
    held = [p for p in posts if p.get("status") == "parked" and p["date"] >= (today - dt.timedelta(days=30)).isoformat()]
    pics = _thumbs([_oid(p, G.cover_file(p)) for p in mine + ahead + held], 160, crop=True)
    st.markdown(f"#### Waiting for you ({len(mine)})")
    if not mine:
        st.success("Nothing is waiting for you. Everything coming up is approved.")
    for p in mine:
        _row(p, f"m_{p['id']}", pics, quick_approve=True)
    st.markdown(f"#### Approved and coming up ({len(ahead)})")
    st.caption("Open any post to watch it, read it, edit a caption, move it, park it or cancel it.")
    for p in ahead:
        _row(p, f"a_{p['id']}", pics)
    if held:
        st.markdown(f"#### Parked ({len(held)})")
        for p in held:
            _row(p, f"h_{p['id']}", pics)


def _journal_view(arts):
    st.caption("A new article is drafted every Wednesday for the next Monday. Approve it here and it goes live at 09:00 that Monday.")
    for a in arts[:10]:
        when_ = a.get("scheduled") or a.get("slot") or a.get("published") or a.get("drafted") or ""
        status = a.get("status", "")
        jp = {"draft": ("Needs review", "rev"), "scheduled": ("Scheduled", "ok"), "published": ("Published", "live"),
              "dropped": ("Dropped", "off")}.get(status, (status.title(), "off"))
        with st.container(border=True):
            st.markdown(f"<div class='soc-row-title'>{a.get('title', a.get('slug'))}</div>"
                        f"<span class='soc-pill {jp[1]}'>{jp[0]}</span> &nbsp;<span class='soc-sub'>{when_} · "
                        f"{a.get('_words', 0):,} words · {len(a.get('sources') or [])} sources</span>", unsafe_allow_html=True)
            if a.get("dek"):
                st.caption(a["dek"])
            if a.get("change_note"):
                st.info(f"Change asked: {a['change_note']}")
            pdf = next((n for n in a.get("_pack", {}) if n.endswith(".pdf")), None)
            c = st.columns(4)
            if pdf:
                k = f"jpdf_{a['slug']}"
                if st.session_state.get(k + "_b"):
                    c[0].download_button("Save the PDF", st.session_state[k + "_b"], file_name=pdf, mime="application/pdf",
                                         key=k + "_d", use_container_width=True)
                elif c[0].button("Get the PDF", key=k, use_container_width=True):
                    st.session_state[k + "_b"] = G.blob_bytes(a["_pack"][pdf])
                    st.rerun()
            if status == "draft":
                if c[1].button("Approve", key=f"ja_{a['slug']}", type="primary", use_container_width=True):
                    _send("journal-approve", a["slug"], label="approve the article")
                with st.form(f"jfb_{a['slug']}", border=True):          # a form: popovers lost the typing (2 Nov)
                    n = st.text_area("Not right? Say what should change, or why to drop it", key=f"jn_{a['slug']}", height=90)
                    j_then = st.radio("Then", ["Ask for changes", "Drop the article"], key=f"jr_{a['slug']}", horizontal=True)
                    j_sent = st.form_submit_button("Send")
                if j_sent:
                    if not n.strip():
                        st.error("Write what should change (or why to drop it) first.")
                    elif j_then == "Ask for changes":
                        _send("journal-note", a["slug"], n.strip()[:600], label="ask for changes")
                    else:
                        _send("journal-drop", a["slug"], n.strip()[:600], label="drop the article")
            if a.get("questions"):
                with st.expander("Questions for the director"):
                    for q in a["questions"]:
                        st.caption(f"• {q}")


def _published(posts):
    rows = G.gone_out(posts)[:80]
    if not rows:
        st.info("Nothing has been published yet.")
        return
    df = pd.DataFrame([{"Date": r["date"], "Time": r.get("time", ""), "Post": title(r), "Type": kind_line(r),
                        "Instagram": r["_links"].get("instagram"), "Facebook": r["_links"].get("facebook")} for r in rows])
    st.dataframe(df, hide_index=True, use_container_width=True, height=min(640, 38 + 35 * len(df)),
                 column_config={"Instagram": st.column_config.LinkColumn(display_text="Open"),
                                "Facebook": st.column_config.LinkColumn(display_text="Open")})


def _health(posts, today):
    gaps = G.empty_days(posts, today)
    st.markdown("#### The calendar")
    st.markdown("Empty days in the next 31: " + (", ".join(f"**{d:%a %d %b}**" for d in gaps) if gaps else "none"))
    st.markdown("#### The posting job")
    try:
        runs = _posting_runs()
        st.caption("It runs at 09:10 and 19:10 IST and publishes whatever is approved and due.")
        df = pd.DataFrame([{"When (IST)": pd.Timestamp(r["at"]).tz_convert("Asia/Kolkata").strftime("%d %b %I:%M %p"),
                            "Result": "Succeeded" if r["conclusion"] == "success" else ("Running" if r["status"] != "completed" else "Failed"),
                            "Run": r["url"]} for r in runs])
        st.dataframe(df, hide_index=True, use_container_width=True, column_config={"Run": st.column_config.LinkColumn(display_text="Open")})
    except Exception as e:
        st.warning(f"Could not read the posting job: {e}")
    st.markdown("#### Recent actions from this page")
    try:
        acts = _actions()
        df = pd.DataFrame([{"When (IST)": pd.Timestamp(a["at"]).tz_convert("Asia/Kolkata").strftime("%d %b %I:%M %p") if a.get("at") else "",
                            "Action": a["what"],
                            "Result": "Working" if a["status"] != "completed" else ("Done" if a["conclusion"] == "success" else "Refused"),
                            "Reason": a.get("why", "")} for a in acts])
        st.dataframe(df, hide_index=True, use_container_width=True)
    except Exception as e:
        st.caption(f"Could not read recent actions: {e}")
    st.caption("AI art: ₹400 a month cap, counted in the repo (social/state/imagegen_log.jsonl) by both the Friday run and "
               "the Mac; a run that would cross it writes a brief instead.")


def _requests():
    st.caption("Ask for a post in plain words. The weekly drafting run, or a working session, picks it up and drafts it for "
               "your approval.")
    txt = st.text_area("What should the post be about?", key="soc_req",
                       placeholder="e.g. A Did you know? post about Kanchenjunga, on Saturday")
    if st.button("Send the request", disabled=not txt.strip(), type="primary"):
        _send("request", "", txt.strip(), label="request")
    try:
        done = [l[2:].strip() for l in _requests_text().splitlines() if l.startswith("- [")]
    except Exception:
        done = []
    if done:
        st.markdown("#### Asked for so far")
        for l in reversed(done[-15:]):
            st.markdown(("✅ " if l.startswith("[x]") else "◻️ ") + l[3:].strip())


def _banner():
    """One line at the top, only when an action is running or was refused in the last 15 minutes."""
    try:
        acts = _actions()
    except Exception:
        return
    now = pd.Timestamp.now(tz="UTC")
    recent = [a for a in acts if a.get("at") and now - pd.Timestamp(a["at"]) < pd.Timedelta(minutes=15)]
    busy = [a for a in recent if a["status"] != "completed"]
    bad = [a for a in recent if a["conclusion"] == "failure"]
    if busy:
        st.markdown(f"<div class='soc-banner busy'>Working on: {', '.join(a['what'] for a in busy[:3])}. Press Refresh in a minute.</div>",
                    unsafe_allow_html=True)
    for a in bad[:2]:
        st.markdown(f"<div class='soc-banner'><b>Refused:</b> {a['what']}: {a.get('why', '')}</div>", unsafe_allow_html=True)


def _results_view():
    """★ 3 Nov 2026 (the outside review: "we're flying blind"): what each post did out there, read once a day."""
    snap = _results()
    if not snap:
        st.info("No results yet. The posting job reads them once a day (social/state/results.json).")
        return
    acc = snap.get("accounts") or {}
    def fol(k):
        a = acc.get(k) or {}
        v = a.get("followers_count", a.get("followers"))
        return (f"{v:,}", "followers") if v is not None else ("—", (a.get("error") or "not read")[:40])
    rows = G.result_rows(snap)
    read = [r for r in rows if r["ig_reach"] is not None]
    avg = sum(r["ig_reach"] for r in read) / len(read) if read else 0
    cells = [("Instagram", *fol("instagram")), ("Facebook", *fol("facebook")), ("LinkedIn", *fol("linkedin")),
             ("Instagram reach", f"{avg:.0f}", f"average a post · {len(read)} posts")]
    st.markdown("<div class='soc-kpis'>" + "".join(f"<div class='soc-kpi'><span>{a}</span><b>{b}</b><small>{c}</small></div>"
                                                   for a, b, c in cells) + "</div>", unsafe_allow_html=True)
    st.caption(f"Read {snap.get('at', '')[:16].replace('T', ' ')} IST. Reach = how many accounts saw a post; views count repeats.")
    for pr in snap.get("problems") or []:
        st.warning(pr)
    c1, c2 = st.columns(2)
    for col, key, label in ((c1, "format", "Format"), (c2, "kind", "Kind of post")):
        col.markdown(f"**Instagram reach by {label.lower()}**")
        col.dataframe(pd.DataFrame([{label: k, "Average reach": round(a), "Posts": n} for k, a, n in G.reach_by(rows, key)]),
                      hide_index=True, use_container_width=True)
    st.markdown("**Every post**")
    df = pd.DataFrame([{"Date": r["date"], "Post": r["hook"][:70], "Format": r["format"], "IG reach": r["ig_reach"],
                        "IG views": r["ig_views"], "Saves": r["ig_saves"], "Shares": r["ig_shares"], "Likes": r["ig_likes"],
                        "Comments": r["ig_comments"], "FB views": r["fb_views"], "LinkedIn views": r["li_views"]} for r in rows])
    st.dataframe(df, hide_index=True, use_container_width=True)


def render():
    st.markdown(CSS, unsafe_allow_html=True)
    if not G.token():
        st.warning("**The Socials page is not connected yet.** It needs a GitHub token named `GH_SOCIAL_TOKEN` in this app's "
                   "secrets: a fine-grained token for the repo M4NAVV/peanuts-website only, with Contents: read and Actions: "
                   "read and write. Add it in the Space's Settings → Variables and secrets, then restart the Space.")
        return
    try:
        posts = _queue()
    except Exception as e:
        st.error(f"Could not read the social queue from GitHub: {e}")
        return
    today = G.today_ist()
    h1, h2, h3 = st.columns([5, 2, 1], vertical_alignment="bottom")
    h1.markdown(f"<div class='soc-head'><h2>Social media</h2><p>Every post from today to "
                f"{today + dt.timedelta(days=31):%d %b}: review it, approve it, keep the calendar full.</p></div>",
                unsafe_allow_html=True)
    h2.text_input("Your name, for the log", key="soc_by", placeholder="Your name")
    if h3.button("Refresh", use_container_width=True):
        _clear()
        st.rerun()
    up = [p for p in posts if p["date"] >= today.isoformat()]
    gaps = G.empty_days(posts, today)
    mx = G.mix(up)
    waiting = len(G.needs_you(posts, today))
    week = sum(1 for p in up if p.get("status") == "approved" and p["date"] < (today + dt.timedelta(days=7)).isoformat())
    st.markdown(
        "<div class='soc-kpis'>"
        f"<div class='soc-kpi{' warn' if waiting else ''}'><span>Waiting for you</span><b>{waiting}</b><small>drafts to review</small></div>"
        f"<div class='soc-kpi'><span>Next 7 days</span><b>{week}</b><small>posts approved</small></div>"
        f"<div class='soc-kpi{' warn' if gaps else ''}'><span>Empty days</span><b>{len(gaps)}</b><small>in the next 31</small></div>"
        f"<div class='soc-kpi'><span>AI art</span><b>{mx['ai']:.0%}</b><small>of {mx['n']} approved · limit 50%</small></div>"
        "</div>", unsafe_allow_html=True)
    _banner()
    # one section at a time (not st.tabs, which builds every tab on every click)
    views = ["Calendar", "Review", "Journal", "Results", "Published", "Health", "Requests"]
    if "soc_view" not in st.session_state:
        st.session_state["soc_view"] = "Review" if waiting else "Calendar"
    view = st.segmented_control("Section", views, key="soc_view", label_visibility="collapsed") or "Calendar"
    if view == "Calendar":
        _calendar(posts, today)
    elif view == "Review":
        _review(posts, today)
    elif view == "Journal":
        try:
            _journal_view(_journal())
        except Exception as e:
            st.error(f"Could not read the Journal: {e}")
    elif view == "Results":
        _results_view()
    elif view == "Published":
        _published(posts)
    elif view == "Health":
        _health(posts, today)
    else:
        _requests()
