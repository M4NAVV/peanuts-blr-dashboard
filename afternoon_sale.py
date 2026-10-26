"""The afternoon sale pictures — ONE place that draws them (moved here from the WhatsApp sender, 26 Oct 2026).

Used twice: the dashboard's 🕒 Afternoon Sales tab (look + download the seven as a zip) and the WhatsApp sender
(peanuts-whatsapp-sender/afternoon.py, which imports this file from its dashboard checkout and only SENDS).
One copy, so a change to a layout shows up in both and the two can never disagree.

★ WHERE THE NUMBERS COME FROM (Manav, 26 Oct 2026). One person in the back office types every store's net sales
till 3:30 into the afternoonsales tab, plus today's target for the 20 VFL stores, then ticks SEND.

★ THE LAYOUT IS HIS, THE LOOK IS THE BRAND'S. The seven images copy the segregation of the sheets he used to
make by hand (Siliguri by mall, outstation by city, VFL ranked, store-wise by city and location, a block-wise
summary) and are drawn in the Peanuts brand: green #14532d, amber, ivory, Hanken Grotesk, the horizontal
colour-on-light lockup.

★ STOREMASTER DECIDES WHO IS OPEN ("follow the storemaster as the source of truth"). A store with a CLOSURE DATE
on or before the day is left out of every picture and every count.

★ BLANK IS NOT ZERO. A blank cell is a figure that never arrived: shown as "—", never added, never counted live,
and named in the footer. Zero is a store that sold nothing.

★ CHROME DRAWS THEM. The Docker image installs chromium for this (Dockerfile); locally the Mac's Chrome is used.

    python afternoon_sale.py               # the 25 Oct 2026 sample → out_afternoon/sample/
"""
from __future__ import annotations

import base64
import csv
import datetime as dt
import html
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUT = HERE / "out_afternoon"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

AFTERNOON_GID = "1530153030"     # the `afternoonsales` tab
STOREMASTER_GID = "1723658342"   # the `storemaster` tab

# ── who is where, in his order ─────────────────────────────────────────────────────────────────────────────────
# Codes, never names (a POS rename once stranded 13 crore of history). The names are his, as on his sheets.
SILIGURI = [   # (block, [(code, name)])
    ("CITY CENTRE MALL", [(56, "MANYAVAR"), (45, "GINI & JONY"), (37, "COLOR PLUS"), (23, "MADAME"),
                          (81, "NUMERO UNO"), (42, "SABHYATA"), (83, "MINI KLUB"), (95, "AURELIA"), (98, "TURTLE")]),
    ("COSMOS MALL", [(18, "GINI & JONY"), (22, "MADAME"), (47, "TURTLE"), (25, "BINGE"), (6, "SUCCESS"),
                     (9, "COBB"), (88, "VH")]),
    ("PLANET MALL", [(58, "MANYAVAR & MOHEY")]),
    ("ON ROAD", [(35, "CASUAL HCR"), (10005, "MANYAVAR SEVOKE ROAD")]),
    ("VEGA MALL", [(10, "CALVIN KLEIN")]),
]
OUTSTATION = [  # (city, [(code, name)])
    ("KOLKATA", [(41, "CP CITY CENTRE"), (40, "CP MANISQUARE"), (61, "MANYAVAR MANISQUARE"), (68, "TURTLE GORIA"),
                 (96, "TURTLE MANISQUARE"), (90, "MANYAVAR RAJARHAT CC2"), (101, "MANYAVAR & MOHEY FAIR FIELD")]),
    ("DURGAPUR", [(64, "SABHYATA")]),
    ("GUWAHATI", [(69, "TURTLE CITY CENTRE"), (89, "MANYAVAR CITY CENTRE"), (93, "SABHYATA CITY CENTRE")]),
    ("JAMSHEDPUR", [(54, "COLORPLUS")]),
    ("BHUBANESWAR", [(62, "SABHYATA")]),
    ("GANGTOK", [(82, "MADAME"), (104, "TURTLE")]),
    ("ROURKELA", [(74, "BINGE")]),
    ("AGARTALA", [(91, "MANYAVAR & MOHEY")]),
    ("MALDA", [(92, "MANYAVAR & MOHEY")]),
    ("JORHAT", [(97, "MANYAVAR & MOHEY")]),
    ("SILCHAR", [(105, "MANYAVAR & MOHEY")]),
    ("DIBRUGARH", [(106, "MANYAVAR & MOHEY")]),
]
SOUTH = [(107, "GRAND KAMRAJ ROAD"), (108, "COMMERCIAL STREET"), (109, "KAMRAJ ROAD"), (110, "M.G. ROAD"),
         (111, "ORION MALL"), (112, "JAYANAGAR"), (113, "CMH ROAD"), (114, "DVG ROAD")]
VFL = {  # (region, format) -> [(code, name in the ranked tables, short name for "No. 1 store")]
    ("EAST", "MANYAVAR & MOHEY"): [(58, "MANYAVAR & MOHEY PLANET MALL", "Planet Mall"),
                                   (106, "MANYAVAR & MOHEY DIBRUGARH", "Dibrugarh"),
                                   (101, "MANYAVAR & MOHEY FAIR FIELD", "Fair Field"),
                                   (97, "MANYAVAR & MOHEY JORHAT", "Jorhat"), (92, "MANYAVAR & MOHEY MALDA", "Malda"),
                                   (91, "MANYAVAR & MOHEY AGARTALA", "Agartala"),
                                   (105, "MANYAVAR & MOHEY SILCHAR", "Silchar")],
    ("EAST", "MANYAVAR"): [(10005, "MANYAVAR SEVOKE ROAD", "Sevoke Road"),
                           (56, "MANYAVAR CITY CENTRE SILIGURI", "City Centre Siliguri"),
                           (89, "MANYAVAR CITY CENTRE GUWAHATI", "City Centre Guwahati"),
                           (90, "MANYAVAR RAJARHAT CC2", "Rajarhat CC2"), (61, "MANYAVAR MANISQUARE", "Manisquare")],
    ("SOUTH", "MANYAVAR & MOHEY"): [(107, "GRAND KAMRAJ ROAD", "Grand Kamraj Road"), (112, "JAYANAGAR", "Jayanagar"),
                                    (111, "ORION MALL", "Orion Mall"), (110, "M.G. ROAD", "M.G. Road"),
                                    (108, "COMMERCIAL STREET", "Commercial Street")],
    ("SOUTH", "MANYAVAR"): [(114, "DVG ROAD", "DVG Road"), (109, "KAMRAJ ROAD", "Kamraj Road"),
                            (113, "CMH ROAD", "CMH Road")],
}
# Image 5 (store-wise) reads city / location / brand. Storemaster's own words, except where his sheet names a
# place or a brand differently (Planet Mall is storemaster's "Sevok Road" 58; 18 and 45 trade as Gini & Jony).
STOREWISE_OVERRIDE = {
    58: ("SILIGURI", "PLANET MALL", "MANYAVAR & MOHEY"), 10005: ("SILIGURI", "SEVOKE ROAD", "MANYAVAR"),
    45: (None, None, "GINI & JONY"), 18: (None, None, "GINI & JONY"), 68: (None, "GORIA", None),
    37: (None, None, "COLOR PLUS"), 83: (None, None, "MINI KLUB"), 88: (None, None, "VH"),
    69: (None, "CITY CENTRE", None), 89: (None, "CITY CENTRE", None), 93: (None, "CITY CENTRE", None),
    82: (None, "M G MARG", None), 62: ("BHUBANESWAR", "BHUBANESWAR", None), 101: (None, "FAIR FIELD", None),
    74: (None, "ROURKELA", None),
}


# ── the data ───────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Day:
    date: dt.date
    taken: str                      # "15:30", or "" if not typed
    sale: dict[int, float | None]   # every listed store; None = blank (not received)
    target: dict[int, float | None]
    master: dict[int, dict]         # storemaster row by code
    closed: set[int]                # storemaster says closed on or before `date`


def _num(s) -> float | None:
    s = str(s if s is not None else "").replace(",", "").replace("₹", "").strip()
    if s in ("", "-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _date(s) -> dt.date | None:
    s = str(s or "").strip()
    for f in ("%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d-%B-%Y", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def _csv_url(gid: str) -> str:
    """The tab's CSV export, on the same workbook the dashboard reads (derived, not another secret)."""
    base = os.environ.get("PORTFOLIO_CSV_URL", "") or os.environ.get("SHEET_CSV_URL", "")
    if not base:
        try:                                            # the dashboard: Streamlit secrets, as portfolio_loader reads them
            import portfolio_loader as PL
            base = PL._sheet_url() or ""
        except Exception:
            base = ""
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", base)
    if not m:
        raise SystemExit("PORTFOLIO_CSV_URL is not set, so the workbook cannot be found")
    return f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv&gid={gid}"


def _fetch(gid: str) -> list[list[str]]:
    import requests
    r = requests.get(_csv_url(gid), timeout=60)
    r.raise_for_status()
    return list(csv.reader(io.StringIO(r.content.decode("utf-8"))))


def parse(tab: list[list[str]], master_rows: list[list[str]]) -> Day:
    cell = lambda r, c: tab[r][c] if r < len(tab) and c < len(tab[r]) else ""
    day = _date(cell(1, 1))
    if day is None:
        raise ValueError(f"the DATE cell (B2) holds {cell(1, 1)!r}, not a date")
    head = [h.strip().upper() for h in tab[3]]
    ci = head.index("STORE CODE")
    cs = next(i for i, h in enumerate(head) if h.startswith("NET SALES"))
    ct = next((i for i, h in enumerate(head) if h.startswith("TODAY TARGET")), None)
    sale, target = {}, {}
    for row in tab[4:]:
        code = _num(row[ci] if ci < len(row) else "")
        if code is None:
            continue                                   # the TOTAL / STORES FILLED rows
        code = int(code)
        sale[code] = _num(row[cs] if cs < len(row) else "")
        target[code] = _num(row[ct]) if ct is not None and ct < len(row) else None
    mh = [h.strip().upper() for h in master_rows[0]]
    master, closed = {}, set()
    for row in master_rows[1:]:
        # ★ storemaster has TWO "LOCATION" columns (J = the place, AI = a Google Maps link); the first of a name wins
        r = {}
        for h, v in zip(mh, row):
            r.setdefault(h, v)
        c = _num(r.get("STORE CODE"))
        if c is None:
            continue
        master[int(c)] = r
        shut = _date(r.get("CLOSURE DATE"))
        if shut and shut <= day:
            closed.add(int(c))
    return Day(day, cell(1, 3).strip(), sale, target, master, closed)


def load() -> Day:
    return parse(_fetch(AFTERNOON_GID), _fetch(STOREMASTER_GID))


def check(d: Day, today: dt.date) -> list[str]:
    """Reasons not to send. Empty = go."""
    why = []
    if d.date != today:
        why.append(f"the sheet's DATE is {d.date:%d %b %Y}, not today ({today:%d %b %Y}) — yesterday's figures?")
    listed = {c for _, g in SILIGURI for c, _ in g} | {c for _, g in OUTSTATION for c, _ in g} | {c for c, _ in SOUTH}
    stray = sorted(set(d.sale) - listed)
    if stray:
        why.append(f"store code(s) {stray} are in the tab but on none of the seven layouts — add them to afternoon.py")
    missing = sorted(c for c in listed - set(d.sale) if c not in d.closed)
    if missing:
        why.append(f"open store code(s) {missing} are missing from the tab")
    if all(v is None for v in d.sale.values()):
        why.append("no sales typed at all")
    return why


# ── numbers and words ──────────────────────────────────────────────────────────────────────────────────────────
def inr(v: float | None) -> str:
    """₹ with Indian grouping: 17,95,242."""
    if v is None:
        return "—"
    n = int(round(v))
    s, neg = str(abs(n)), n < 0
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join(re.findall(r"\d{1,2}", head[::-1]))[::-1] if head else ""
        s = f"{head},{tail}"
    return ("−" if neg else "") + "₹" + s


def pct(a: float | None, b: float | None, dp: int = 0) -> str:
    return "—" if a is None or not b else f"{100 * a / b:.{dp}f}%"


def esc(s) -> str:
    return html.escape(str(s))


def _sum(vals) -> float:
    return float(sum(v for v in vals if v is not None))


# ── the look ───────────────────────────────────────────────────────────────────────────────────────────────────
GREEN, AMBER, IVORY, INK, QUIET, RULE, MARIGOLD, STONE, SAND = (
    "#14532d", "#e8a33d", "#f6f1e7", "#101814", "#7b847e", "#e2e3de", "#a8771c", "#f3f3f0", "#efe3c8")

CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700;800&display=block');
*{{box-sizing:border-box}}
html,body{{margin:0;background:{STONE};font-family:'Hanken Grotesk',-apple-system,'Segoe UI',Roboto,sans-serif;color:{INK};
  font-variant-numeric:tabular-nums}}
.page{{width:1080px;padding:36px}}
.card{{background:#fff;border-radius:22px;overflow:hidden;box-shadow:0 2px 0 {RULE}}}
.hd{{background:{GREEN};color:#fff;padding:34px 44px 30px;display:flex;justify-content:space-between;align-items:flex-end}}
.kick{{color:{AMBER};font-weight:800;letter-spacing:.2em;font-size:17px;text-transform:uppercase;margin-bottom:8px}}
.ttl{{font-weight:800;font-size:44px;line-height:1.05;letter-spacing:-.01em}}
.dt{{text-align:right}} .dt .l{{color:#cfe3d6;font-size:17px}} .dt .v{{font-weight:800;font-size:36px;margin-top:4px}}
.tiles{{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid {RULE}}}
.tile{{padding:22px 26px;border-right:1px solid {RULE}}} .tile:last-child{{border-right:0}}
.tile .k{{font-size:14px;letter-spacing:.12em;color:{QUIET};font-weight:700;text-transform:uppercase}}
.tile .v{{font-size:32px;font-weight:800;margin-top:6px;line-height:1.1}} .tile .v.hi{{color:{GREEN}}}
.body{{padding:26px 44px 10px}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:36px}}
.sec{{color:{MARIGOLD};font-weight:800;letter-spacing:.16em;font-size:15px;margin:18px 0 8px;text-transform:uppercase}}
table{{width:100%;border-collapse:collapse;font-size:21px}}
th{{text-align:left;font-size:13px;letter-spacing:.14em;color:{QUIET};font-weight:700;padding:10px 12px;border-bottom:2px solid {INK};
  text-transform:uppercase}}
th.r,td.r{{text-align:right}} th.c,td.c{{text-align:center}}
td{{padding:12px 12px;border-bottom:1px solid {RULE}}}
tr.zero td{{color:#a7aea9}}
tr.band td{{background:{IVORY};color:{MARIGOLD};font-weight:800;font-size:14px;letter-spacing:.14em;padding:9px 12px}}
tr.sub td{{background:{STONE};font-weight:800}}
tr.tot td{{background:{AMBER};font-weight:800;font-size:23px;color:{INK}}}
tr.grand td{{background:{GREEN};color:#fff;font-weight:800;font-size:23px}}
.rk{{display:inline-flex;width:34px;height:34px;border-radius:50%;align-items:center;justify-content:center;font-weight:800;
  font-size:16px;background:{STONE};color:{INK}}} .rk.top{{background:{AMBER}}}
.bar{{display:inline-block;width:110px;height:10px;border-radius:5px;background:{STONE};vertical-align:middle;position:relative}}
.bar i{{position:absolute;left:0;top:0;bottom:0;border-radius:5px;background:{GREEN}}}
.ft{{display:flex;justify-content:space-between;align-items:center;padding:20px 44px 26px;border-top:1px solid {RULE};margin-top:18px}}
.ft .n{{color:{QUIET};font-size:15px;max-width:720px;line-height:1.4}}
.ft img{{height:38px}}
table.grid td,table.grid th{{border:1px solid {RULE};font-size:17px;padding:8px 10px}}
table.grid th{{border-bottom:2px solid {INK}}}
"""


def _logo() -> str:
    b = (HERE / "assets" / "logo-horizontal.png").read_bytes()
    return "data:image/png;base64," + base64.b64encode(b).decode()


def page(kicker, title, d: Day, tiles, body, note) -> str:
    tl = "".join(f"<div class=tile><div class=k>{esc(k)}</div><div class='v{' hi' if i == 0 else ''}'>{esc(v)}</div></div>"
                 for i, (k, v) in enumerate(tiles))
    taken = f" · {esc(d.taken)}" if d.taken else ""
    return f"""<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head><body><div class=page><div class=card>
<div class=hd><div><div class=kick>{esc(kicker)}</div><div class=ttl>{esc(title)}</div></div>
<div class=dt><div class=l>Afternoon sale{taken}</div><div class=v>{d.date:%d.%m.%Y}</div></div></div>
<div class=tiles>{tl}</div><div class=body>{body}</div>
<div class=ft><div class=n>{note}</div><img src="{_logo()}"></div></div></div></body></html>"""


def _row(name, v, cls="") -> str:
    z = " zero" if (v is None or v == 0) else ""
    return f"<tr class='{cls}{z}'><td>{esc(name)}</td><td class=r>{inr(v)}</td></tr>"


def _missing_note(d: Day, codes) -> str:
    gone = [c for c in codes if c not in d.closed and d.sale.get(c) is None]
    if not gone:
        return ""
    return " · <b>Not received</b> (shown —, not counted): " + ", ".join(str(c) for c in gone)


# ── the seven ──────────────────────────────────────────────────────────────────────────────────────────────────
def img_siliguri(d: Day) -> str:
    def block(name, rows):
        rows = [(c, n) for c, n in rows if c not in d.closed]
        if not rows:
            return "", 0.0
        tot = _sum(d.sale.get(c) for c, _ in rows)
        label = {"CITY CENTRE MALL": "CITY CENTRE", "COSMOS MALL": "COSMOS"}.get(name, name)
        h = (f"<div class=sec>{esc(name)}</div><table><tr><th>Brand / store</th><th class=r>Sale</th></tr>"
             + "".join(_row(n, d.sale.get(c)) for c, n in rows)
             + f"<tr class=sub><td>{esc(label)} TOTAL</td><td class=r>{inr(tot)}</td></tr></table>")
        return h, tot
    parts = {name: block(name, rows) for name, rows in SILIGURI}
    left = "".join(parts[n][0] for n in ("CITY CENTRE MALL", "PLANET MALL"))
    right = "".join(parts[n][0] for n in ("COSMOS MALL", "ON ROAD", "VEGA MALL"))
    total = sum(t for _, t in parts.values())
    body = (f"<div class=cols><div>{left}</div><div>{right}</div></div>"
            f"<table style='margin-top:22px'><tr class=tot><td>SILIGURI STORE TOTAL</td><td class=r>{inr(total)}</td></tr></table>")
    tiles = [("Siliguri total", inr(total)), ("City Centre", inr(parts["CITY CENTRE MALL"][1])),
             ("Cosmos", inr(parts["COSMOS MALL"][1])), ("Planet Mall", inr(parts["PLANET MALL"][1]))]
    codes = [c for _, g in SILIGURI for c, _ in g]
    return page("Siliguri", "Siliguri — Mall & On Road", d, tiles, body,
                "Net sales till the afternoon cut-off" + _missing_note(d, codes))


def img_outstation(d: Day) -> str:
    rows, city_tot = [], {}
    for city, stores in OUTSTATION:
        stores = [(c, n) for c, n in stores if c not in d.closed]
        if not stores:
            continue
        t = _sum(d.sale.get(c) for c, _ in stores)
        city_tot[city] = t
        rows.append(f"<tr class=band><td>{esc(city)}</td><td class=r>{inr(t) if len(stores) > 1 else ''}</td></tr>")
        rows += [_row(n, d.sale.get(c)) for c, n in stores]
    total = sum(city_tot.values())
    top = max(city_tot, key=city_tot.get) if city_tot else "—"
    body = (f"<table><tr><th>City / store</th><th class=r>Sale</th></tr>{''.join(rows)}"
            f"<tr class=tot><td>OUTSTATION TOTAL</td><td class=r>{inr(total)}</td></tr></table>")
    tiles = [("Outstation total", inr(total)), ("Kolkata", inr(city_tot.get("KOLKATA"))),
             ("Top city", top.title()), ("Cities", str(len(city_tot)))]
    codes = [c for _, g in OUTSTATION for c, _ in g]
    return page("East · Outstation", "Outstation — City Wise", d, tiles, body,
                "All East stores outside Siliguri" + _missing_note(d, codes))


def _ranked(d: Day, stores, label) -> tuple[list[str], float, float, float]:
    """Rows of one ranked block, and its (sale, sale where a target exists, target) — a pair over the same rows."""
    stores = [s for s in stores if s[0] not in d.closed]
    order = sorted(stores, key=lambda s: -(d.sale.get(s[0]) or 0))
    out = []
    for i, (c, name, _) in enumerate(order, 1):
        s, t = d.sale.get(c), d.target.get(c)
        w = 0 if s is None or not t else max(0.0, min(1.0, s / t))
        z = " zero" if not s else ""
        out.append(f"<tr class='{z.strip()}'><td class=c><span class='rk{' top' if i <= 3 else ''}'>{i}</span></td>"
                   f"<td>{esc(name)}</td><td class=r>{inr(t)}</td><td class=r><b>{inr(s)}</b></td>"
                   f"<td class=r><span class=bar><i style='width:{w * 100:.0f}%'></i></span></td>"
                   f"<td class=r><b>{pct(s, t) if s is not None else '—'}</b></td></tr>")
    sale = _sum(d.sale.get(c) for c, _, _ in stores)
    paired = [(d.sale.get(c) or 0.0, d.target.get(c)) for c, _, _ in stores if d.target.get(c)]
    ps, pt = sum(a for a, _ in paired), sum(b for _, b in paired)
    out.append(f"<tr class=sub><td></td><td>{esc(label)} TOTAL</td><td class=r>{inr(pt or None)}</td>"
               f"<td class=r>{inr(sale)}</td><td></td><td class=r>{pct(ps, pt)}</td></tr>")
    return out, sale, ps, pt


HEAD6 = ("<tr><th class=c>#</th><th>Store</th><th class=r>Today target</th><th class=r>Afternoon sale</th>"
         "<th></th><th class=r>Achieved</th></tr>")


def _band6(t) -> str:
    return f"<tr class=band><td colspan=6>{esc(t)}</td></tr>"


def img_vfl_region(d: Day, region: str) -> str:
    rows, sale, ps, pt, best = [], 0.0, 0.0, 0.0, (None, -1)
    for fmt, label in (("MANYAVAR & MOHEY", "MANYAVAR & MOHEY"), ("MANYAVAR", "MANYAVAR")):
        stores = VFL[(region, fmt)]
        r, s, a, b = _ranked(d, stores, label)
        rows += [_band6(f"{label} STORES")] + r
        sale, ps, pt = sale + s, ps + a, pt + b
        for c, _, short in stores:
            if c not in d.closed and (d.sale.get(c) or 0) > best[1]:
                best = (short, d.sale.get(c) or 0)
    rows.append(f"<tr class=grand><td></td><td>GRAND TOTAL</td><td class=r>{inr(pt or None)}</td><td class=r>{inr(sale)}</td>"
                f"<td></td><td class=r>{pct(ps, pt)}</td></tr>")
    tiles = [("Afternoon sale", inr(sale)), ("Day target", inr(pt or None)), ("Achieved", pct(ps, pt, 1)),
             ("No. 1 store", best[0] or "—")]
    codes = [c for f in ("MANYAVAR & MOHEY", "MANYAVAR") for c, _, _ in VFL[(region, f)]]
    return page(f"{region.title()} VFL stores", f"{region.title()} VFL Stores — Rank Wise", d, tiles,
                f"<table>{HEAD6}{''.join(rows)}</table>",
                "Ranked within each block by afternoon sale · Achieved = afternoon sale vs full-day target, over stores "
                "with a target" + _missing_note(d, codes))


def img_vfl_both(d: Day) -> str:
    rows, sale, ps, pt, live, active = [], 0.0, 0.0, 0.0, 0, 0
    for region, label in (("EAST", "EAST VFL"), ("SOUTH", "SOUTH VFL")):
        stores = VFL[(region, "MANYAVAR & MOHEY")] + VFL[(region, "MANYAVAR")]
        r, s, a, b = _ranked(d, stores, label)
        rows += [_band6(f"{label} STORES")] + r
        sale, ps, pt = sale + s, ps + a, pt + b
        op = [c for c, _, _ in stores if c not in d.closed]
        active += len(op)
        live += sum(1 for c in op if (d.sale.get(c) or 0) > 0)
    rows.append(f"<tr class=tot><td></td><td>EAST + SOUTH TOTAL</td><td class=r>{inr(pt or None)}</td><td class=r>{inr(sale)}</td>"
                f"<td></td><td class=r>{pct(ps, pt)}</td></tr>")
    tiles = [("Combined sale", inr(sale)), ("Day target", inr(pt or None)), ("Achieved", pct(ps, pt, 1)),
             ("Live stores", f"{live} / {active}")]
    codes = [c for v in VFL.values() for c, _, _ in v]
    return page("East + South VFL stores", "East + South VFL — Rank Wise", d, tiles,
                f"<table>{HEAD6}{''.join(rows)}</table>",
                "Ranked within each zone by afternoon sale · Achieved = afternoon sale vs full-day target · "
                "Live = sold something today" + _missing_note(d, codes))


def _place(d: Day, code: int) -> tuple[str, str, str]:
    m = d.master.get(code, {})
    city, loc, brand = (m.get("CITY", "") or "").upper(), (m.get("LOCATION", "") or "").upper(), \
                       (m.get("STORE NAME", "") or "").upper()
    o = STOREWISE_OVERRIDE.get(code, (None, None, None))
    return (o[0] or city).strip(), (o[1] or loc).strip(), (o[2] or brand).strip()


def img_storewise(d: Day) -> str:
    east = [c for _, g in SILIGURI for c, _ in g] + [c for _, g in OUTSTATION for c, _ in g]
    south = [c for c, _ in SOUTH]
    rows, grand, region_tot, cities = [], 0.0, {}, set()
    for region, codes in (("EAST & NE", east), ("SOUTH", south)):
        codes = [c for c in codes if c not in d.closed]
        recs = sorted((_place(d, c) + (c,) for c in codes))
        rows.append(f"<tr class=band><td colspan=4>{esc(region)}</td></tr>")
        rt = 0.0
        for city in sorted({r[0] for r in recs}):
            cities.add(city)
            last_city = last_loc = None
            ct = 0.0
            for cty, loc, brand, c in [r for r in recs if r[0] == city]:
                v = d.sale.get(c)
                ct += v or 0
                z = " class=zero" if not v else ""
                rows.append(f"<tr{z}><td><b>{esc(cty) if cty != last_city else ''}</b></td>"
                            f"<td>{esc(loc) if (cty, loc) != (last_city, last_loc) else ''}</td>"
                            f"<td>{esc(brand)}</td><td class=r>{inr(v)}</td></tr>")
                last_city, last_loc = cty, loc
            rows.append(f"<tr class=sub><td colspan=3>{esc(city)} TOTAL</td><td class=r>{inr(ct)}</td></tr>")
            rt += ct
        rows.append(f"<tr class=tot><td colspan=3>{esc(region)} TOTAL</td><td class=r>{inr(rt)}</td></tr>")
        region_tot[region] = rt
        grand += rt
    rows.append(f"<tr class=grand><td colspan=3>GRAND TOTAL</td><td class=r>{inr(grand)}</td></tr>")
    body = ("<table class=grid><tr><th>City</th><th>Location</th><th>Brand</th><th class=r>Sale</th></tr>"
            + "".join(rows) + "</table>")
    tiles = [("Grand total", inr(grand)), ("East & NE", inr(region_tot["EAST & NE"])),
             ("South", inr(region_tot["SOUTH"])), ("Cities", str(len(cities)))]
    return page("All stores · Region › City › Location", "Store Wise Sale — City & Location", d, tiles, body,
                "Every open store in storemaster" + _missing_note(d, east + south))


def img_summary(d: Day) -> str:
    def line(codes):
        op = [c for c in codes if c not in d.closed]
        s = _sum(d.sale.get(c) for c in op)
        live = sum(1 for c in op if (d.sale.get(c) or 0) > 0)
        return s, live, len(op)

    def tr(label, codes, cls=""):
        s, live, act = line(codes)
        return (f"<tr class='{cls}'><td>{esc(label)}</td><td class=r>{inr(s)}</td><td class=r>{live} / {act}</td>"
                f"<td class=r>{inr(s / act) if act else '—'}</td></tr>")
    sil = [c for _, g in SILIGURI for c, _ in g]
    out = [c for _, g in OUTSTATION for c, _ in g]
    south = [c for c, _ in SOUTH]
    # ★ fixed widths, so the zone table and the VFL table line up column for column
    head = ("<colgroup><col style='width:46%'><col style='width:20%'><col style='width:16%'><col style='width:18%'></colgroup>"
            "<tr><th>Block</th><th class=r>Sale</th><th class=r>Live / active</th><th class=r>Avg / store</th></tr>")
    zone = (f"<table>{head}<tr class=band><td colspan=4>ZONE SUMMARY</td></tr>"
            + tr("SILIGURI", sil) + tr("OUTSTATION", out) + tr("EAST ZONE TOTAL", sil + out, "sub")
            + tr("SOUTH ZONE", south) + tr("GRAND TOTAL", sil + out + south, "tot") + "</table>")
    fmts = [(f"{r} · {f}", [c for c, _, _ in VFL[(r, f)]]) for r in ("EAST", "SOUTH") for f in ("MANYAVAR & MOHEY", "MANYAVAR")]
    vfl_all = [c for _, cs in fmts for c in cs]
    vfl = (f"<table style='margin-top:30px'>{head}<tr class=band><td colspan=4>VFL STORES · FORMAT WISE</td></tr>"
           + "".join(tr(l, cs) for l, cs in fmts) + tr("VFL TOTAL", vfl_all, "grand") + "</table>")
    g, live, act = line(sil + out + south)
    v, _, _ = line(vfl_all)
    tiles = [("Grand total", inr(g)), ("Live stores", f"{live} / {act}"), ("Avg / store", inr(g / act) if act else "—"),
             ("VFL total", inr(v))]
    return page("All store total", "Overall Summary — Block Wise", d, tiles, zone + vfl,
                "Live = sold something today · Active = open in storemaster · Avg / store = sale ÷ active · "
                "Siliguri mall brands counted as counters" + _missing_note(d, sil + out + south))


IMAGES = [  # (file stem, the words in the WhatsApp message, builder) — HIS ORDER
    ("1-siliguri", "Siliguri — mall & on road", img_siliguri),
    ("2-outstation", "Outstation — city wise", img_outstation),
    ("3-east-vfl", "East VFL — rank wise", lambda d: img_vfl_region(d, "EAST")),
    ("4-east-south-vfl", "East + South VFL — rank wise", img_vfl_both),
    ("5-store-wise", "Store wise — city & location", img_storewise),
    ("6-south-vfl", "South VFL — rank wise", lambda d: img_vfl_region(d, "SOUTH")),
    ("7-summary", "Overall summary — block wise", img_summary),
]


# ── HTML → PNG ─────────────────────────────────────────────────────────────────────────────────────────────────
def _chrome() -> str:
    for c in (os.environ.get("CHROME", ""), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              shutil.which("google-chrome") or "", shutil.which("google-chrome-stable") or "",
              shutil.which("chromium") or "", shutil.which("chromium-browser") or ""):
        if c and Path(c).exists():
            return c
    raise SystemExit("no Chrome found to draw the images (set CHROME)")


def render(html_text: str, out: Path) -> Path:
    """Chrome draws the page tall; the empty stone below the card is trimmed off."""
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        src, shot = Path(tmp) / "p.html", Path(tmp) / "p.png"
        src.write_text(html_text, encoding="utf-8")
        # ★ its own profile folder: on the Space HOME (/app) is not writable by the app's user, and Chrome
        # silently draws nothing without somewhere to keep a profile
        subprocess.run([_chrome(), "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                        f"--user-data-dir={tmp}/profile", "--disable-dev-shm-usage",
                        "--force-device-scale-factor=2", "--window-size=1080,3600", "--virtual-time-budget=8000",
                        f"--screenshot={shot}", src.as_uri()], check=True, capture_output=True, timeout=120)
        im = Image.open(shot).convert("RGB")
        bg = im.getpixel((5, im.height - 5))
        px = im.load()
        bottom = im.height - 1
        while bottom > 0 and all(px[x, bottom] == bg for x in range(0, im.width, 7)):
            bottom -= 1
        im = im.crop((0, 0, im.width, min(im.height, bottom + 72)))
        out.parent.mkdir(parents=True, exist_ok=True)
        im.save(out, optimize=True)
    return out


def build(d: Day, folder: Path) -> list[tuple[str, str, Path]]:
    return [(stem, words, render(fn(d), folder / f"{stem}.png")) for stem, words, fn in IMAGES]


def zip_bytes(files) -> bytes:
    """The seven PNGs in one zip, named as they arrive on WhatsApp ("AFT 1 · Siliguri — mall & on road · 26-10-2026.png")."""
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, png in files:
            z.writestr(name, png)
    return buf.getvalue()


def shown_name(n: int, words: str, day: dt.date) -> str:
    return f"AFT {n} · {words} · {day:%d-%m-%Y}.png"


def sample() -> Day:
    """25 Oct 2026, from his own images — for looking at the design, never for sending."""
    s = {56: 10046, 45: 6297, 37: 3299, 23: 2739, 81: 1199, 42: 12697, 83: 7333, 95: 0, 98: 3598,
         18: 0, 22: 4598, 47: 1699, 25: 0, 6: 0, 9: 3399, 88: 0, 58: 192747, 35: 0, 10005: 67934, 10: 79000,
         41: 73721, 40: 44413, 61: 4698, 68: 8195, 96: 5596, 90: 5798, 101: 31143, 64: 2999, 69: 0, 89: 8722,
         93: 36496, 54: 0, 62: 57032, 82: 2698, 104: 5297, 74: 0, 91: 9022, 92: 12197, 97: 16297, 105: 6497,
         106: 45366, 107: 458815, 112: 238977, 111: 106079, 110: 86309, 108: 56162, 114: 37111, 109: 25897,
         113: 13120}
    t = {58: 500000, 106: 200000, 101: 600000, 97: 200000, 92: 150000, 91: 250000, 105: 200000, 10005: 150000,
         56: 200000, 89: 200000, 90: 400000, 61: 200000, 107: 2800000, 112: 1200000, 111: 400000, 110: 500000,
         108: 500000, 114: 200000, 109: 300000, 113: 200000}
    master = {}
    for _, g in SILIGURI:
        for c, n in g:
            master[c] = {"CITY": "SILIGURI", "LOCATION": {**{x: "CITY CENTRE" for x in (56, 45, 37, 23, 81, 42, 83, 95, 98)},
                                                          **{x: "COSMOS MALL" for x in (18, 22, 47, 25, 6, 9, 88)},
                                                          35: "HILL CART ROAD", 10: "VEGA CIRCLE MALL"}.get(c, ""),
                         "STORE NAME": n}
    for city, g in OUTSTATION:
        for c, n in g:
            master[c] = {"CITY": city, "LOCATION": city, "STORE NAME": n.split(" ")[0] if n.startswith("CP") else n}
    for c, n in SOUTH:
        master[c] = {"CITY": "BENGALURU", "LOCATION": n, "STORE NAME": "MANYAVAR & MOHEY" if c in (107, 108, 110, 111, 112) else "MANYAVAR"}
    return Day(dt.date(2026, 10, 25), "15:30", {k: float(v) for k, v in s.items()},
               {k: float(v) for k, v in t.items()}, master, set())


if __name__ == "__main__":
    for _, _, p in build(sample(), OUT / "sample"):
        print(p)
