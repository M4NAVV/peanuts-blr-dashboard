"""One place where a date column's convention is decided, and proved.

The two feeds disagree, and always have: the VFL export writes MONTH first
(`08/12/2026` is 12 August), the portfolio sheet writes DAY first (`12/08/2026`
is the same day). Each loader used to declare its own format inside a call to
`to_datetime` and then fall back to guessing whatever failed.

★ WHY DECLARING IT IS NOT ENOUGH. Simulated on the live VFL feed, a source that
switched to day-first — a Sheets locale change, a different export setting —
produces this:

    rows                      50,000
    parsed but WRONG          17,664   (35%)
    parsed correctly          32,336
    failed to parse                0

Not one row fails. The 13th to the 31st cannot be read the wrong way round, so
they land correctly and the frame looks healthy: dates run to the 31st, the row
count is untouched, totals barely move. A third of the year quietly sits on the
wrong day. That is worse than the incident we have had, where 12 August became
8 December and at least announced itself by landing in the future.

★ SO THE CONVENTION IS READ FROM THE DATA, NOT BELIEVED. A date whose first part
is over 12 can only be day-first; whose second part is over 12, only month-first.
Individually about 40% of dates are ambiguous. As a COLUMN neither feed ever is:

    portfolio   15,983 rows prove day-first,        0 prove month-first
    VFL              0 rows prove day-first,  170,523 prove month-first

That is not a heuristic, it is a proof with a hundred and seventy thousand
witnesses — and it moves with the source, so a genuine change is something to
accept deliberately rather than absorb silently.

What this module does with that: parse using the convention the data proves,
refuse to guess when the evidence contradicts itself, and remember what happened
so the gate can say it out loud. `last(label)` is how it is read back, following
`night_fill.last_problem` and `master_lookup.last_problem`.
"""

from __future__ import annotations

import re

import pandas as pd

DAY_FIRST, MONTH_FIRST = "day", "month"

# `1/4/2026`, `01-04-2026` — the shapes that can be read two ways. An ISO date
# cannot, so it is no evidence either way and simply parses.
_AMBIGUOUS = re.compile(r"^\s*(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\s*$")

_LAST: dict = {}


def last(label: str) -> dict | None:
    """What the most recent parse of `label` found. None if it never ran."""
    return _LAST.get(label)


def evidence(series: pd.Series) -> dict:
    """Count the rows that can only be one convention or the other."""
    s = series.astype(str)
    m = s.str.match(_AMBIGUOUS)
    parts = s[m].str.strip().str.split(r"[/-]", regex=True)
    if parts.empty:
        return {"day": 0, "month": 0, "ambiguous": 0, "other": int((~m).sum())}
    first = pd.to_numeric(parts.str[0], errors="coerce")
    second = pd.to_numeric(parts.str[1], errors="coerce")
    return {
        "day": int((first > 12).sum()),          # 13/04 can only be day-first
        "month": int((second > 12).sum()),       # 04/13 can only be month-first
        "ambiguous": int(((first <= 12) & (second <= 12)).sum()),
        "other": int((~m).sum()),                # ISO, blanks, anything else
    }


def detect(series: pd.Series) -> tuple[str | None, dict]:
    """(convention, evidence). None when the column cannot prove itself.

    Both kinds of evidence at once means the column is genuinely mixed — two
    conventions in one column cannot be parsed, only guessed at, and guessing is
    the thing this module exists to stop.
    """
    e = evidence(series)
    if e["day"] and e["month"]:
        return None, e
    if e["day"]:
        return DAY_FIRST, e
    if e["month"]:
        return MONTH_FIRST, e
    return None, e


def parse(series: pd.Series, *, expect: str, label: str) -> pd.Series:
    """Parse `series` with the convention the DATA proves, not the one declared.

    `expect` is what the caller believes the feed to be. It is used only when the
    column cannot prove itself — a handful of rows, all ambiguous — and any
    disagreement between the two is recorded for the gate to refuse on. Parsing
    still proceeds on the proven convention: a feed that changed format should
    render correctly while the page says it changed.
    """
    found, e = detect(series)
    convention = found or expect
    s = series.astype(str).str.strip()

    fmt = "%d/%m/%Y" if convention == DAY_FIRST else "%m/%d/%Y"
    dt = pd.to_datetime(s, format=fmt, errors="coerce")

    # `11-08-2026` among a column of `11/08/2026` — one row of the portfolio
    # sheet was written that way once. Same convention, different separator.
    miss = dt.isna()
    if miss.any():
        dashed = s[miss].str.replace("-", "/", regex=False)
        dt.loc[miss] = pd.to_datetime(dashed, format=fmt, errors="coerce")

    # ISO, two-digit years, anything else — flexible, but on the SAME convention.
    # The old VFL fallback dropped `dayfirst` entirely, so leftovers were read by
    # a different rule from the rest of their own column.
    miss = dt.isna()
    if miss.any():
        # pandas warns that `dayfirst` is redundant for an ISO string, once per
        # call. It is right and it does not matter — but a log full of it is a
        # log nobody reads, and a real warning would sit in the middle of it.
        import warnings as _w
        with _w.catch_warnings():
            _w.simplefilter("ignore", UserWarning)
            dt.loc[miss] = pd.to_datetime(s[miss], errors="coerce",
                                          dayfirst=(convention == DAY_FIRST))

    blank = s.isin(["", "nan", "NaT", "None"])
    _LAST[label] = {
        "expected": expect,
        "found": found,
        "used": convention,
        "evidence": e,
        "rows": int(len(s)),
        "unreadable": int((dt.isna() & ~blank).sum()),
        "blank": int(blank.sum()),
    }
    return dt


def problems(label: str) -> list:
    """What the gate should refuse to serve, in its own words."""
    r = last(label)
    if not r:
        return []
    out = []
    if r["found"] is None and r["evidence"]["day"] and r["evidence"]["month"]:
        out.append(
            f"the {label} feed's dates are written BOTH ways round — "
            f"{r['evidence']['day']:,} rows can only be day-first and "
            f"{r['evidence']['month']:,} can only be month-first. One column "
            "cannot be two calendars, and the ambiguous rows between them "
            "cannot be read at all")
    elif r["found"] and r["found"] != r["expected"]:
        was = "day" if r["expected"] == DAY_FIRST else "month"
        now = "day" if r["found"] == DAY_FIRST else "month"
        out.append(
            f"the {label} feed now writes {now} first where it has always "
            f"written {was} first ({r['evidence'][r['found']]:,} rows prove it). "
            "Read the old way, about a third of the year would land on the "
            "wrong day and nothing else would look wrong")
    share = r["unreadable"] / r["rows"] if r["rows"] else 0
    if share > 0.02:
        out.append(
            f"{r['unreadable']:,} of {r['rows']:,} rows carry a date that could "
            "not be read at all — they would be dropped, and the totals would "
            "be short by whatever they held")
    return out


def warnings(label: str) -> list:
    r = last(label)
    if not r:
        return []
    out = []
    if r["unreadable"] and r["unreadable"] / max(r["rows"], 1) <= 0.02:
        out.append(f"{r['unreadable']:,} row(s) carry a date that could not be "
                   "read and were dropped")
    if r["found"] is None and not (r["evidence"]["day"] and r["evidence"]["month"]):
        out.append(
            f"nothing in the {label} feed proves which way round its dates are "
            f"written, so they were read as {r['used']}-first because that is "
            "what this feed has always been")
    return out
