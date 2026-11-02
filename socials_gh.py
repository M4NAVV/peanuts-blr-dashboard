"""The Socials tab's link to the social queue (2 Nov 2026).

Manav: "a socials tab on the portfolio section of our dash, where i can approve or not approve everything, its like a
social media manager page for us." The posts live in the private website repo (M4NAVV/peanuts-website, social/queue and
journal/articles). This module only READS them, through GitHub's API with a token scoped to that one repo, and asks for
changes by starting the repo's `Social action` job, which runs the same command-line tool a session would. So the rules
(the voice check, festival days, no edits to a live post) are never re-implemented here.

The token is the `GH_SOCIAL_TOKEN` secret (a fine-grained token: that repo only, Contents read, Actions read and write).
Without it the tab says so on screen rather than failing quietly. Nothing secret is in this file: this repo is public.
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor

import requests

OWNER, REPO, BRANCH = "M4NAVV", "peanuts-website", "master"
API = "https://api.github.com"
ACTION_WORKFLOW = "social-action.yml"
POSTS_WORKFLOW = "social.yml"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# what a post's status means to the person reviewing it
NEEDS_YOU = ("drafted", "awaiting", "changes", "blocked")
STATUS_WORDS = {"approved": "Approved", "drafted": "Needs you", "awaiting": "Needs you", "changes": "Changes asked",
                "blocked": "Failed the voice check", "parked": "Parked", "cancelled": "Cancelled", "published": "Gone out"}


class NotConfigured(Exception):
    """No token: the tab explains how to add one."""


def token() -> str | None:
    if os.environ.get("GH_SOCIAL_TOKEN"):
        return os.environ["GH_SOCIAL_TOKEN"]
    try:
        import streamlit as st
        return st.secrets.get("GH_SOCIAL_TOKEN")
    except Exception:
        return None


def _headers(tok, accept="application/vnd.github+json"):
    return {"Authorization": f"Bearer {tok}", "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}


def _tok():
    t = token()
    if not t:
        raise NotConfigured("GH_SOCIAL_TOKEN is not set")
    return t


def _graphql(query: str) -> dict:
    r = requests.post(f"{API}/graphql", json={"query": query}, headers=_headers(_tok()), timeout=40)
    r.raise_for_status()
    out = r.json()
    if out.get("errors"):
        raise RuntimeError("GitHub: " + "; ".join(e.get("message", "") for e in out["errors"])[:300])
    return out["data"]


# ------------------------------------------------------------------ reading the queue (one request for every post)

def parse_queue(data: dict) -> list[dict]:
    """The GraphQL answer -> one dict per post: its post.json plus the files beside it ({name: (oid, size)})."""
    out = []
    tree = (((data or {}).get("repository") or {}).get("object") or {}).get("entries") or []
    for folder in tree:
        if folder.get("type") != "tree":
            continue
        files, post = {}, None
        for f in ((folder.get("object") or {}).get("entries") or []):
            blob = f.get("object") or {}
            files[f["name"]] = (f.get("oid"), blob.get("byteSize") or 0)
            if f["name"] == "post.json" and blob.get("text"):
                try:
                    post = json.loads(blob["text"])
                except ValueError:
                    post = None
        if not post or not post.get("date"):
            continue
        post["_files"] = files
        post.setdefault("id", folder["name"])
        post["_folder"] = folder["name"]
        out.append(post)
    out.sort(key=lambda p: (p.get("date", ""), p.get("time", "")))
    return out


_NAMES_Q = """{ repository(owner: "%s", name: "%s") { object(expression: "%s:social/queue") { ... on Tree { entries {
  name type object { ... on Tree { entries { name oid } } } } } } } }"""


def load_queue() -> list[dict]:
    """Two light requests instead of one heavy one (7.3 s -> ~4 s, 2 Nov 2026): the file names first, then only the
    post.json texts. Asking for every file's details in one go made GitHub size up every picture as well."""
    names = _graphql(_NAMES_Q % (OWNER, REPO, BRANCH))
    folders = [e for e in ((((names.get("repository") or {}).get("object") or {}).get("entries")) or []) if e.get("type") == "tree"]
    texts = {}
    for k in range(0, len(folders), 80):                     # 80 a request keeps each answer well inside GitHub's limits
        chunk = folders[k:k + 80]
        parts = " ".join(f'p{i}: object(expression: "{BRANCH}:social/queue/{f["name"]}/post.json") {{ ... on Blob {{ text }} }}'
                         for i, f in enumerate(chunk))
        got = (_graphql('{ repository(owner: "%s", name: "%s") { %s } }' % (OWNER, REPO, parts)).get("repository") or {})
        for i, f in enumerate(chunk):
            texts[f["name"]] = ((got.get(f"p{i}") or {}).get("text"))
    for f in folders:                                         # the shape parse_queue reads: post.json carries its text
        for e in (((f.get("object") or {}).get("entries")) or []):
            e["object"] = {"text": texts.get(f["name"])} if e["name"] == "post.json" else {}
    return parse_queue(names)


# ------------------------------------------------------------------ pictures (each blob fetched once: a blob never changes)

def blob_bytes(oid: str) -> bytes:
    r = requests.get(f"{API}/repos/{OWNER}/{REPO}/git/blobs/{oid}", headers=_headers(_tok()), timeout=60)
    r.raise_for_status()
    return base64.b64decode(r.json()["content"])


def thumb_from(raw: bytes, width: int = 240, crop: bool = False) -> bytes:
    """A JPEG `width` wide. `crop` trims it to the feed's 4:5 from the centre, so a calendar of Reel covers (9:16) and
    posts (4:5) lines up in even rows."""
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    if crop:
        w, h = im.size
        th = int(w * 5 / 4)
        if h > th:
            top = (h - th) // 2
            im = im.crop((0, top, w, top + th))
        elif h < th:
            tw = int(h * 4 / 5)
            left = (w - tw) // 2
            im = im.crop((left, 0, left + tw, h))
    im.thumbnail((width, width * 2))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def cover_file(post: dict) -> str | None:
    """The picture that stands for a post: its cover, else its image, else its first slide."""
    files = post.get("_files", {})
    for name in ("cover.jpg", "image.png", "cover.png"):
        if name in files:
            return name
    slides = sorted(n for n in files if n.lower().endswith((".png", ".jpg")) and ("slide" in n.lower() or n[:2].isdigit()))
    return slides[0] if slides else None


def slide_files(post: dict) -> list[str]:
    files = post.get("_files", {})
    return sorted(n for n in files if n.lower().endswith((".png", ".jpg")) and n not in ("cover.jpg", "image.png", "cover.png"))


def video_file(post: dict) -> str | None:
    return next((n for n in post.get("_files", {}) if n.lower().endswith(".mp4")), None)


def load_text(path: str) -> str:
    """One text file from the repo (e.g. social/requests.md), or "" when it is not there yet."""
    got = _graphql('{ repository(owner: "%s", name: "%s") { object(expression: "%s:%s") { ... on Blob { text } } } }'
                   % (OWNER, REPO, BRANCH, path))
    return (((got.get("repository") or {}).get("object") or {}).get("text")) or ""


def many_blobs(oids: list[str], fetch=None) -> dict:
    fetch = fetch or blob_bytes
    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for oid, raw in zip(oids, ex.map(lambda o: _safe(fetch, o), oids)):
            if raw is not None:
                out[oid] = raw
    return out


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:
        return None


# ------------------------------------------------------------------ the Journal

_JOURNAL_Q = """{ repository(owner: "%s", name: "%s") {
  arts: object(expression: "%s:journal/articles") { ... on Tree { entries { name object { ... on Blob { text } } } } }
  packs: object(expression: "%s:journal/packs") { ... on Tree { entries { name object { ... on Tree { entries { name oid } } } } } } } }"""


def parse_journal(data: dict) -> list[dict]:
    repo = (data or {}).get("repository") or {}
    packs = {}
    for f in (((repo.get("packs") or {}).get("entries")) or []):
        packs[f["name"]] = {e["name"]: e["oid"] for e in (((f.get("object") or {}).get("entries")) or [])}
    out = []
    for f in (((repo.get("arts") or {}).get("entries")) or []):
        text = ((f.get("object") or {}).get("text")) or ""
        if not f["name"].endswith(".md") or "---\n" not in text:
            continue
        try:
            _, meta, body = text.split("---\n", 2)
            a = json.loads(meta)
        except ValueError:
            continue
        a["_words"] = len(body.split())
        a["_pack"] = packs.get(a.get("slug", ""), {})
        out.append(a)
    out.sort(key=lambda a: a.get("slot") or a.get("scheduled") or a.get("published") or a.get("drafted") or "", reverse=True)
    return out


def load_journal() -> list[dict]:
    return parse_journal(_graphql(_JOURNAL_Q % (OWNER, REPO, BRANCH, BRANCH)))


# ------------------------------------------------------------------ asking for a change: the repo's job does it

def dispatch_inputs(action: str, pid: str = "", value: str = "", value2: str = "", by: str = "dashboard") -> dict:
    """The exact request the job receives. Shapes are checked again on GitHub before anything runs."""
    return {"ref": BRANCH, "inputs": {"action": action, "id": pid or "", "value": (value or "")[:600],
                                      "value2": (value2 or "")[:2500], "by": (by or "dashboard")[:60]}}


def dispatch(action: str, pid: str = "", value: str = "", value2: str = "", by: str = "dashboard") -> None:
    r = requests.post(f"{API}/repos/{OWNER}/{REPO}/actions/workflows/{ACTION_WORKFLOW}/dispatches",
                      json=dispatch_inputs(action, pid, value, value2, by), headers=_headers(_tok()), timeout=30)
    if r.status_code != 204:
        raise RuntimeError(f"GitHub did not take the request ({r.status_code}): {r.text[:200]}")


def recent_actions(n: int = 12) -> list[dict]:
    """The latest button presses, newest first: what, when, and — for a refusal — why (the job's ::error:: line)."""
    r = requests.get(f"{API}/repos/{OWNER}/{REPO}/actions/workflows/{ACTION_WORKFLOW}/runs", params={"per_page": n},
                     headers=_headers(_tok()), timeout=30)
    r.raise_for_status()
    out = []
    for run in r.json().get("workflow_runs", []):
        item = {"what": run.get("display_title") or run.get("name"), "status": run.get("status"),
                "conclusion": run.get("conclusion"), "at": run.get("created_at"), "url": run.get("html_url"), "why": ""}
        if run.get("conclusion") == "failure":
            item["why"] = _why_failed(run["id"])
        out.append(item)
    return out


def _why_failed(run_id: int) -> str:
    try:
        h = _headers(_tok())
        jobs = requests.get(f"{API}/repos/{OWNER}/{REPO}/actions/runs/{run_id}/jobs", headers=h, timeout=20).json().get("jobs", [])
        for j in jobs:
            notes = requests.get(f"{API}/repos/{OWNER}/{REPO}/check-runs/{j['id']}/annotations", headers=h, timeout=20).json()
            msgs = [a.get("message", "") for a in notes if a.get("annotation_level") == "failure"
                    and not a.get("message", "").startswith("Process completed with exit code")]
            if msgs:
                return msgs[0][:300]
    except Exception:
        pass
    return "refused (open the run on GitHub for the reason)"


def posting_runs(n: int = 6) -> list[dict]:
    r = requests.get(f"{API}/repos/{OWNER}/{REPO}/actions/workflows/{POSTS_WORKFLOW}/runs", params={"per_page": n},
                     headers=_headers(_tok()), timeout=30)
    r.raise_for_status()
    return [{"status": x.get("status"), "conclusion": x.get("conclusion"), "at": x.get("created_at"), "url": x.get("html_url"),
             "event": x.get("event")} for x in r.json().get("workflow_runs", [])]


# ------------------------------------------------------------------ the month at a glance (pure: tested without GitHub)

def today_ist() -> dt.date:
    return dt.datetime.now(IST).date()


def live(posts: list[dict]) -> list[dict]:
    return [p for p in posts if p.get("status") not in ("cancelled",)]


QUALITY_SCORES = ("stop", "grasp", "brand", "original", "accurate")


def quality(p: dict) -> dict:
    """The drafter's quality record, read for the tab (2 Nov 2026, Manav: a post below the bar is "show it to me
    marked"). {"marked": bool, "why": [plain reasons], "scores": {...}, "avg": float | None, "scored": bool}."""
    q = p.get("quality") or {}
    sc = {k: q["scores"][k] for k in QUALITY_SCORES if isinstance((q.get("scores") or {}).get(k), (int, float))}
    avg = round(sum(sc.values()) / len(sc), 1) if len(sc) == len(QUALITY_SCORES) else None
    why = [str(w) for w in (q.get("why") or [])]
    notes = q.get("notes") or {}
    why += [f"{k}: {v}" for k, v in notes.items() if isinstance(v, str) and f"{k}: {v}" not in why]
    marked = bool(q.get("below_standard")) or bool(q.get("checks")) or (
        avg is not None and (avg < 8 or min(sc.values()) < 7))
    return {"marked": marked, "why": why, "scores": sc, "avg": avg, "scored": avg is not None}


def needs_you(posts: list[dict], since: dt.date) -> list[dict]:
    return [p for p in posts if p.get("status") in NEEDS_YOU and p.get("date", "") >= since.isoformat()]


def empty_days(posts: list[dict], start: dt.date, days: int = 31) -> list[dt.date]:
    """Days with no APPROVED (or already published) post: the one-a-day rule, as `social cover` reads it."""
    have = {p["date"] for p in posts if p.get("status") in ("approved", "published")}
    return [d for d in (start + dt.timedelta(k) for k in range(days)) if d.isoformat() not in have]


def mix(posts: list[dict]) -> dict:
    """What the approved posts are made of: AI art, Reels, the rest (designed). Shares of the approved count."""
    ap = [p for p in posts if p.get("status") in ("approved", "published")]
    n = len(ap) or 1
    ai = sum(1 for p in ap if p.get("ai_art"))
    reels = sum(1 for p in ap if p.get("format") == "reel" and not p.get("ai_art"))
    return {"n": len(ap), "ai": ai / n, "reels": reels / n, "designed": max(0.0, 1 - ai / n - reels / n)}


def gone_out(posts: list[dict]) -> list[dict]:
    out = []
    for p in posts:
        pub = p.get("published") or {}
        links = {k: v.get("url") for k, v in pub.items() if isinstance(v, dict) and v.get("ok") and v.get("url")}
        if p.get("status") == "published" or links:
            out.append({**p, "_links": links})
    return sorted(out, key=lambda p: (p.get("date", ""), p.get("time", "")), reverse=True)
