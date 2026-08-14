"""Reading a Google Sheet export, and saying plainly when it cannot be read.

Both loaders used to fetch like this:

    try:
        ...gzip fetch...
    except Exception:
        return pd.read_csv(url)          # plain retry

which threw the real reason away. A sharing change (403) reported
"Connection reset by peer", a revoked link reported a 404 from the retry, and
an HTML sign-in page parsed happily into a one-column frame that failed much
later as `KeyError: 'Bill Date'`. All three are the same event to a reader —
"the sheet did not come back" — and none of them said so.

So: keep the fast path, keep the retry, but carry the FIRST failure's reason,
and check that what came back is actually the CSV we asked for before handing
it on. A `FeedError` names the cause in words a person can act on.
"""

from __future__ import annotations

import io

import pandas as pd


class FeedError(RuntimeError):
    """A data source that could not be read, with the reason in the message."""


def _as_bytes(content) -> bytes:
    """The retry path can hand back text rather than bytes, depending on what
    pandas opened. Normalise once, here, rather than guessing downstream."""
    return content.encode("utf-8", "replace") if isinstance(content, str) else content


def _looks_like_html(head: bytes) -> bool:
    s = _as_bytes(head)[:400].lstrip().lower()
    return s.startswith(b"<!doctype html") or s.startswith(b"<html") or b"<title>" in s


def _why(url: str, exc: Exception) -> str:
    """The likely cause, in the words of someone who owns the sheet."""
    code = getattr(getattr(exc, "response", None), "status_code", None)
    text = f"{type(exc).__name__}: {exc}"
    if code == 403 or "403" in text:
        return ("the sheet refused access (403) — its sharing was probably "
                "changed, or the link is no longer published")
    if code == 404 or "404" in text:
        return ("the sheet was not found (404) — the link or its gid has "
                "probably changed")
    if "timed out" in text.lower() or "timeout" in text.lower():
        return "the sheet did not answer in time"
    return f"the sheet could not be fetched ({text[:120]})"


def read_csv(url: str, *, expect: tuple[str, ...] = (), what: str = "sheet"
             ) -> pd.DataFrame:
    """The sheet as a frame of strings, or `FeedError` explaining why not.

    `expect` names columns the caller cannot work without. They are checked
    here, at the point where the cause is still known, rather than surfacing
    later as a KeyError from somewhere in the middle of a report.
    """
    first_problem = None
    content = None
    try:
        import requests
        resp = requests.get(url, headers={"Accept-Encoding": "gzip, deflate"},
                            timeout=120)
        resp.raise_for_status()
        content = resp.content
    except Exception as e:                      # keep WHY, then try the slow way
        first_problem = _why(url, e)
        try:
            with pd.io.common.get_handle(url, "rb") as h:
                content = h.handle.read()
        except Exception:
            raise FeedError(f"{what}: {first_problem}") from e

    content = _as_bytes(content)
    if not content or not content.strip():
        raise FeedError(f"{what}: the sheet returned an empty response"
                        + (f" ({first_problem})" if first_problem else ""))
    if _looks_like_html(content):
        raise FeedError(
            f"{what}: the link returned a web page, not a CSV — this is what a "
            "revoked or unpublished sheet serves (a sign-in page)")
    try:
        df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
    except Exception as e:
        raise FeedError(f"{what}: the response was not readable as CSV "
                        f"({type(e).__name__})") from e

    cols = {str(c).strip() for c in df.columns}
    missing = [c for c in expect if c not in cols]
    if missing:
        raise FeedError(
            f"{what}: the sheet has no {', '.join(missing)} column — found "
            + ", ".join(list(df.columns)[:6])
            + ". A URL without its gid serves the workbook's FIRST tab, which "
              "is the usual cause.")
    return df
