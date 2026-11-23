"""The month-end ANNUAL PACKS (Manav, 23 Nov 2026: "go ahead with the whole build … configure it for the end of month,
so 25th is fine. build everything in our house style").

Until now his back office printed four Excel pivot sheets to PDF by hand before each month:
  1. South Data Annual_MW            — last year, the 8 South VFL stores: the year by brand × store (from the takeover
                                       day and from 1 April), brand share, month × brand × store, and the coming month
                                       day × brand × store.
  2. VFL_Stores_East & NE Annual_MW  — the same for the East VFL stores, store rows × brand columns with contribution %.
  3. All_Stores_East & NE Annual_MW  — every East store of every brand (Peanuts Total): the year, month × store, and
                                       the coming month day × store.
  4. Y2Y-3YRS SOUTH                  — each South store, every financial year month by month, with year-on-year growth,
                                       H1 / H2, and the rest of this year's months at +10 / 15 / 20 % on last year.
The same tables, laid out in the house report style (afternoon_sale.page). Reconciled on 23 Nov 2026 against his PDFs:
South FY 25-26 ₹68,63,87,100 vs his ₹68,63,86,565 (₹535 on ₹68.6 Cr); VFL East Dec 2025 identical to the rupee.

★ BASIS = `Bill Amount` (his packs' basis), not the dashboard's net_amount (≈2.4 % lower) — printed on every page.
★ ALL STORES = the stores still OPEN at the end of the year shown (his ABP file drops exactly the stores closed before
  31 Mar 2026 per the storemaster, keeps one closed on 30 Apr 2026). Manyavar & Mohey stores are ONE row here: his ABP
  splits them (58 / 58.1) from a source we do not have; Peanuts Total carries the combined figure.
★ Y2Y history before FY 25-26 is not in our feeds: `hist` is his own daily sheet (Y2Y-3YRS SOUTH.xlsx, Sheet2), kept
  in the PRIVATE sender repo, never in this public one.
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

import afternoon_sale as A

MONTHS = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]
MNUM = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
BRANDS = ["Manyavar", "Mebaz", "Mohey", "Twamev-Men", "Twamev-Women"]
ROWS_PER_PAGE = 42


# ── periods ──────────────────────────────────────────────────────────────────────────────────────────────────────
def target_month(run: dt.date) -> dt.date:
    """The month the pack is for: the one after the run date's (run on 20 Nov → December)."""
    return (run.replace(day=1) + dt.timedelta(days=32)).replace(day=1)


def fy_start(d: dt.date) -> dt.date:
    return dt.date(d.year if d.month >= 4 else d.year - 1, 4, 1)


def fy_label(start: dt.date) -> str:
    return f"{start.year % 100:02d}-{(start.year + 1) % 100:02d}"


def ly_of(target: dt.date):
    """(last year's month, last year's FY start, FY end) for the coming month."""
    lm = target.replace(year=target.year - 1)
    s = fy_start(lm)
    return lm, s, dt.date(s.year + 1, 3, 31)


# ── data ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def amount(df: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(df["Bill Amount"], errors="coerce").fillna(0.0)


def brand5(df: pd.DataFrame) -> pd.Series:
    b = df["brand"].astype(str).str.upper()
    dv = df["Division"].astype(str).str.upper()
    return pd.Series(np.select([dv.eq("TWAMEV-WOMEN"), b.str.contains("MOHEY"), b.str.contains("TWAMEV"), b.str.contains("MEBAZ")],
                               ["Twamev-Women", "Mohey", "Twamev-Men", "Mebaz"], "Manyavar"), index=df.index)


def vfl_frame(df: pd.DataFrame, region: str, a: dt.date, b: dt.date) -> pd.DataFrame:
    d = df[(df["region"] == region) & (df["date"] >= pd.Timestamp(a)) & (df["date"] <= pd.Timestamp(b))]
    if "_provisional" in d.columns:
        d = d[~d["_provisional"].astype(bool)]
    return pd.DataFrame({"date": d["date"].dt.normalize(), "store": d["store"], "brand": brand5(d), "amt": amount(d)})


# ── house rendering ──────────────────────────────────────────────────────────────────────────────────────────────
def _num(v, pct=False):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    if pct:
        return f"{v:.2f}%"
    return "" if abs(v) < 0.5 else A.inr(v)


def _page(kick, title, tiles, body, note, label, width):
    h = A.page(kick, title, type("D", (), {"date": dt.date.today(), "taken": ""}), tiles, body, note)
    h = re.sub(r"<div class=dt>.*?</div></div>", f"<div class=dt><div class=l>{A.esc(label[0])}</div>"
               f"<div class=v style='font-size:26px'>{A.esc(label[1])}</div></div>", h, count=1, flags=re.S)
    css = (f".page{{width:{width}px}} table.grid td,table.grid th{{font-size:15px;padding:6px 8px;border-color:#c9ccc4;"
           "white-space:nowrap}} table.grid th{border-bottom:2px solid #101814} table.grid th.r{text-align:right}"
           f" table.grid tr.band td{{background:{A.IVORY};color:{A.MARIGOLD};font-weight:800;letter-spacing:.12em;font-size:13px}}"
           f" table.grid tr.sub td{{background:{A.STONE};font-weight:800}} table.grid tr.grand td{{background:{A.GREEN};color:#fff;font-weight:800}}"
           f" table.grid tr.gr td{{color:{A.QUIET};font-size:13px}} table.grid td.neg{{color:#b3261e}} .tiles{{grid-template-columns:repeat(4,1fr)}}")
    return h.replace("</style>", css + "</style>")


def _table(head: list[tuple[str, bool]], rows: list[tuple[str, list]]) -> str:
    """head = [(label, right-aligned)], rows = [(css class, cells)]; cells already formatted."""
    th = "".join(f"<th{' class=r' if r else ''}>{A.esc(h)}</th>" for h, r in head)
    out = []
    for cls, cells in rows:
        if cls == "band":
            out.append(f"<tr class=band><td colspan={len(head)}>{A.esc(cells[0])}</td></tr>")
            continue
        tds = []
        for (h, r), c in zip(head, cells):
            neg = " neg" if isinstance(c, str) and c.startswith(("−", "-")) and r else ""
            tds.append(f"<td class='{'r' if r else ''}{neg}'>{A.esc(c)}</td>")
        out.append(f"<tr class='{cls}'>{''.join(tds)}</tr>")
    return f"<table class=grid><tr>{th}</tr>{''.join(out)}</table>"


def _paged(kick, title, tiles, head, rows, note, label, width, per=ROWS_PER_PAGE):
    """Split a long table over pages; a band row never ends a page; the header repeats."""
    pages, chunk = [], []
    for r in rows:
        chunk.append(r)
        if len(chunk) >= per and r[0] != "band":
            pages.append(chunk); chunk = []
    if chunk:
        if pages and len(chunk) <= 3:              # a lone total row never gets a page of its own
            pages[-1] += chunk
        else:
            pages.append(chunk)
    n = len(pages)
    return [_page(kick, title + (f"  ·  {i + 1}/{n}" if n > 1 else ""), tiles if i == 0 else tiles,
                  _table(head, p), note, label, width) for i, p in enumerate(pages)]


def render_pdf(pages: list[str], out: Path, width: int) -> Path:
    from PIL import Image
    imgs = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, h in enumerate(pages):
            src, shot = Path(tmp) / f"p{i}.html", Path(tmp) / f"p{i}.png"
            src.write_text(h, encoding="utf-8")
            subprocess.run([A._chrome(), "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                            f"--user-data-dir={tmp}/profile", "--force-device-scale-factor=2", f"--window-size={width},4200",
                            "--virtual-time-budget=8000", f"--screenshot={shot}", src.as_uri()],
                           check=True, capture_output=True, timeout=180)
            im = Image.open(shot).convert("RGB")
            bg, px, bottom = im.getpixel((5, im.height - 5)), im.load(), im.height - 1
            while bottom > 0 and all(px[x, bottom] == bg for x in range(0, im.width, 9)):
                bottom -= 1
            imgs.append(im.crop((0, 0, im.width, min(im.height, bottom + 72))))
    out.parent.mkdir(parents=True, exist_ok=True)
    # ★ 23 Nov 2026: saved as JPEG the 34-page All Stores pack was 37.7 MB, over WhatsApp's 20 MB courtesy limit.
    # The pages are flat tables in a handful of colours, so a 64-colour palette (Flate, lossless-looking) keeps the
    # type sharp at a fraction of the size.
    imgs = [im.quantize(64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for im in imgs]
    _write_pdf(imgs, out, dpi=200)
    return out


def _write_pdf(imgs, out: Path, dpi: int) -> None:
    """Palette pages as Flate-compressed images. Pillow writes palette pages UNCOMPRESSED (a 1 GB file), and adding
    a PDF library for this is not worth it — a PDF of whole-page images is a few objects."""
    import zlib
    objs, kids = [], []
    def add(b: bytes) -> int:
        objs.append(b); return len(objs)
    pages_id = add(b"")                                    # filled in at the end
    for im in imgs:
        pal = (im.getpalette() or [])[:768]
        n = len(pal) // 3
        data = zlib.compress(im.tobytes(), 9)
        img = add(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /BitsPerComponent 8 "
                  b"/ColorSpace [/Indexed /DeviceRGB %d <%s>] /Filter /FlateDecode /Length %d >>\nstream\n"
                  % (im.width, im.height, n - 1, bytes(pal[:n * 3]).hex().encode(), len(data)) + data + b"\nendstream")
        w, h = im.width * 72 / dpi, im.height * 72 / dpi
        cs = b"q %.2f 0 0 %.2f 0 0 cm /I Do Q" % (w, h)
        c = add(b"<< /Length %d >>\nstream\n" % len(cs) + cs + b"\nendstream")
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R "
                        b"/Resources << /XObject << /I %d 0 R >> >> >>" % (pages_id, w, h, c, img)))
    objs[pages_id - 1] = (b"<< /Type /Pages /Count %d /Kids [%s] >>"
                          % (len(kids), b" ".join(b"%d 0 R" % k for k in kids)))
    cat = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    buf, offs = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(buf)); buf += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(buf)
    buf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    buf += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, cat, x)
    out.write_bytes(bytes(buf))


# ── 1 + 2 · the VFL packs (South, East & NE) ─────────────────────────────────────────────────────────────────────
def _brands_present(f):
    return [b for b in BRANDS if f.loc[f.brand == b, "amt"].abs().sum() > 0.5]


def south_pack(df, master, target: dt.date) -> tuple[list[str], int]:
    lm, s, e = ly_of(target)
    f = vfl_frame(df, "South", s, e)
    stores = [x for x in master.loc[master.region == "South"].sort_values("code").tableau_name if x in set(f.store)]
    tk = pd.to_datetime(master.set_index("tableau_name").loc[stores[0], "takeover_date"])
    tko = dt.date(s.year, tk.month, tk.day)                       # the takeover day, in last year's FY
    brands = _brands_present(f)
    head = [("Brand", False)] + [(x, True) for x in stores] + [("Total", True)]
    label = ("Last year", f"{fy_label(s)} · {lm:%b %Y}")
    note = (f"South VFL stores, FY {fy_label(s)} (last year), Bill Amount as in the POS sales report. "
            f"Made {dt.date.today():%d %b %Y} for {target:%B %Y}.")
    W = 1900

    def cube(g):
        t = g.pivot_table(index="brand", columns="store", values="amt", aggfunc="sum").reindex(index=brands, columns=stores).fillna(0)
        return t

    pages = []
    blocks = []
    for lab, a in ((f"From {tko:%d %b %Y} (takeover day)", tko), (f"From {s:%d %b %Y}", s)):
        t = cube(f[f.date >= pd.Timestamp(a)])
        rows = [("band", [lab])]
        rows += [("", [b] + [_num(t.loc[b, x]) for x in stores] + [_num(t.loc[b].sum())]) for b in brands]
        rows += [("grand", ["Total"] + [_num(t[x].sum()) for x in stores] + [_num(t.values.sum())])]
        sh = t / t.sum(axis=0).replace(0, np.nan) * 100
        rows += [("band", [f"{lab} · brand share"])]
        rows += [("", [b] + [_num(sh.loc[b, x], True) for x in stores] + [_num(100 * t.loc[b].sum() / t.values.sum(), True)]) for b in brands]
        blocks += rows
        if a == tko:
            tot_tko = t.values.sum()
    tfull = cube(f).values.sum()
    tiles = [(f"FY {fy_label(s)} from 1 Apr", A.inr(tfull)), ("From takeover day", A.inr(tot_tko)),
             (f"{lm:%B %Y}", A.inr(f[(f.date.dt.month == lm.month)].amt.sum())), ("Stores", str(len(stores)))]
    pages += _paged("South · annual", "The year by brand and store", tiles, head, blocks, note, label, W, per=60)

    rows = []
    for mn, mlab in zip(MNUM, MONTHS):
        g = f[f.date.dt.month == mn]
        if g.empty:
            continue
        t = cube(g)
        rows.append(("band", [f"{mlab} {(s.year if mn >= 4 else s.year + 1)}"]))
        rows += [("", [b] + [_num(t.loc[b, x]) for x in stores] + [_num(t.loc[b].sum())]) for b in brands]
        rows.append(("sub", ["Total"] + [_num(t[x].sum()) for x in stores] + [_num(t.values.sum())]))
    t = cube(f)
    rows.append(("grand", ["Year"] + [_num(t[x].sum()) for x in stores] + [_num(t.values.sum())]))
    pages += _paged("South · month-wise", "Every month by brand and store", tiles, head, rows, note, label, W)

    g = f[(f.date.dt.month == lm.month)]
    rows = []
    for d in sorted(g.date.unique()):
        x = g[g.date == d]
        t = cube(x)
        rows.append(("band", [f"{pd.Timestamp(d):%d %b %Y · %A}"]))
        rows += [("", [b] + [_num(t.loc[b, st]) for st in stores] + [_num(t.loc[b].sum())]) for b in brands if t.loc[b].abs().sum() > 0.5]
        rows.append(("sub", ["Day total"] + [_num(t[st].sum()) for st in stores] + [_num(t.values.sum())]))
    t = cube(g)
    rows.append(("grand", [f"{lm:%B}"] + [_num(t[x].sum()) for x in stores] + [_num(t.values.sum())]))
    pages += _paged(f"South · {lm:%B %Y} day by day", f"Last {lm:%B}, every day", tiles, head, rows, note, label, W, per=46)
    return pages, W


def east_vfl_pack(df, master, pf, target: dt.date) -> tuple[list[str], int]:
    lm, s, e = ly_of(target)
    f = vfl_frame(df, "East & NE", s, e)
    m = master.set_index("tableau_name")
    stores = sorted(set(f.store), key=lambda x: int(m.loc[x, "code"]))
    brands = _brands_present(f)
    info = {x: (str(m.loc[x, "code"]), str(m.loc[x, "location"]).upper(), str(m.loc[x, "city"]).upper()) for x in stores}
    label = ("Last year", f"{fy_label(s)} · {lm:%b %Y}")
    note = (f"East & NE VFL stores, FY {fy_label(s)} (last year), Bill Amount as in the POS sales report. "
            f"Made {dt.date.today():%d %b %Y} for {target:%B %Y}.")
    W = 2100
    head = [("Code", False), ("Location", False), ("City", False)]
    for b in brands:
        head += [(b, True), ("%", True)]
    head += [("Total", True), ("%", True)]

    def rows_for(g, key_cols, grand_label):
        t = g.pivot_table(index="store", columns="brand", values="amt", aggfunc="sum").reindex(columns=brands).fillna(0)
        T = t.values.sum()
        out = []
        for x in stores:
            if x not in t.index or t.loc[x].abs().sum() < 0.5:
                continue
            tot = t.loc[x].sum()
            cells = list(info[x])
            for b in brands:
                cells += [_num(t.loc[x, b]), _num(100 * t.loc[x, b] / tot, True) if tot else ""]
            cells += [_num(tot), _num(100 * tot / T, True) if T else ""]
            out.append(("", cells))
        cells = [grand_label, "", ""]
        for b in brands:
            cells += [_num(t[b].sum()), _num(100 * t[b].sum() / T, True) if T else ""]
        out.append(("grand" if grand_label != "Day" else "sub", cells + [_num(T), "100.00%" if T else ""]))
        return out

    tiles = [(f"FY {fy_label(s)}", A.inr(f.amt.sum())), (f"{lm:%B %Y}", A.inr(f[f.date.dt.month == lm.month].amt.sum())),
             ("Mohey share", f"{100 * f[f.brand == 'Mohey'].amt.sum() / f.amt.sum():.1f}%"), ("Stores", str(len(stores)))]
    pages = _paged("East & NE VFL · annual", "The year by store and brand", tiles, head,
                   rows_for(f, None, "Grand total"), note, label, W, per=40)
    rows = []
    for mn, mlab in zip(MNUM, MONTHS):
        g = f[f.date.dt.month == mn]
        if g.empty:
            continue
        rows.append(("band", [f"{mlab} {(s.year if mn >= 4 else s.year + 1)}"]))
        rows += rows_for(g, None, "Month")[:-1] + [("sub", rows_for(g, None, "Month")[-1][1])]
    pages += _paged("East & NE VFL · month-wise", "Every month by store and brand", tiles, head, rows, note, label, W)
    g = f[f.date.dt.month == lm.month]
    rows = []
    for d in sorted(g.date.unique()):
        rows.append(("band", [f"{pd.Timestamp(d):%d %b %Y · %A}"]))
        r = rows_for(g[g.date == d], None, "Day")
        rows += r
    rows += [("grand", rows_for(g, None, lm.strftime("%B"))[-1][1])]
    pages += _paged(f"East & NE VFL · {lm:%B %Y} day by day", f"Last {lm:%B}, every day", tiles, head, rows, note, label, W, per=46)
    return pages, W


# ── 3 · all East stores, every brand (Peanuts Total) ─────────────────────────────────────────────────────────────
def all_east_pack(pf, closed: dict, target: dt.date) -> tuple[list[str], int]:
    lm, s, e = ly_of(target)
    p = pf[(pf.region == "East & NE") & (pf.date >= pd.Timestamp(s)) & (pf.date <= pd.Timestamp(e))].copy()
    open_at_end = [c for c in p.code.unique() if not (closed.get(int(c)) is not None and pd.Timestamp(closed[int(c)]).date() <= e)]
    dropped = sorted(int(c) for c in set(p.code.unique()) - set(open_at_end))
    p = p[p.code.isin(open_at_end)]
    p["amt"] = pd.to_numeric(p["sales"], errors="coerce").fillna(0)
    info = p.groupby("code").agg(name=("STORE NAME", "last"), loc=("LOCATION", "last"), city=("CITY", "last"))
    codes = sorted(info.index, key=lambda c: int(c))
    label = ("Last year", f"{fy_label(s)} · {lm:%b %Y}")
    note = (f"Every East & NE store open on {e:%d %b %Y}, all brands, from Peanuts Total, FY {fy_label(s)} (last year). "
            f"Not shown (closed by {e:%d %b %Y}): codes {', '.join(map(str, dropped)) or 'none'}. "
            f"Manyavar & Mohey stores are one row. Made {dt.date.today():%d %b %Y} for {target:%B %Y}.")
    W = 1300
    head = [("Code", False), ("Store", False), ("Location", False), ("City", False), ("Total", True)]

    def rows_for(g, sub_label, cls="grand"):
        t = g.groupby("code").amt.sum()
        out = [("", [str(int(c)), str(info.loc[c, "name"]), str(info.loc[c, "loc"]), str(info.loc[c, "city"]).upper(), _num(t.get(c, 0))])
               for c in codes if abs(t.get(c, 0)) > 0.5]
        return out + [(cls, [sub_label, "", "", "", _num(t.sum())])]

    tiles = [(f"FY {fy_label(s)}", A.inr(p.amt.sum())), (f"{lm:%B %Y}", A.inr(p[p.date.dt.month == lm.month].amt.sum())),
             ("Stores", str(len(codes))), ("Not shown (closed)", str(len(dropped)))]
    pages = _paged("All East & NE stores · annual", "The year, every store", tiles, head, rows_for(p, "Grand total"), note, label, W, per=60)
    rows = []
    for mn, mlab in zip(MNUM, MONTHS):
        g = p[p.date.dt.month == mn]
        if g.empty:
            continue
        rows.append(("band", [f"{mlab} {(s.year if mn >= 4 else s.year + 1)}"]))
        rows += rows_for(g, "Month", "sub")
    rows.append(("grand", ["Year", "", "", "", _num(p.amt.sum())]))
    pages += _paged("All East & NE stores · month-wise", "Every month, every store", tiles, head, rows, note, label, W, per=60)
    g = p[p.date.dt.month == lm.month]
    hd = [("Date", False), ("Day", False)] + head
    rows = []
    for d in sorted(g.date.unique()):
        ts = pd.Timestamp(d)
        rows.append(("band", [f"{ts:%d %b %Y · %A}"]))
        rows += [(c, [f"{ts:%d-%m-%Y}", f"{ts:%a}"] + v) for c, v in rows_for(g[g.date == d], "Day", "sub")]
    rows.append(("grand", [lm.strftime("%B"), "", "", "", "", "", _num(g.amt.sum())]))
    pages += _paged(f"All East & NE stores · {lm:%B %Y} day by day", f"Last {lm:%B}, every day", tiles, hd, rows, note, label, W + 200, per=60)
    return pages, W + 200


# ── 4 · Y2Y South, every financial year ──────────────────────────────────────────────────────────────────────────
def y2y_south(df, master, hist: pd.DataFrame, run: dt.date) -> tuple[list[str], int]:
    """hist: his daily sheet (Date + one column per store, 'Peanuts-<store>'), used for the years before our feed."""
    stores = list(master.loc[master.region == "South"].sort_values("code").tableau_name)
    last_full = run.replace(day=1) - dt.timedelta(days=1)          # only complete months
    feed_from = dt.date(2025, 4, 1)
    f = vfl_frame(df, "South", feed_from, last_full)
    f["fy"] = f.date.map(lambda d: fy_label(fy_start(d.date())))
    f["m"] = f.date.dt.month
    h = hist.copy()
    h["Date"] = pd.to_datetime(h["Date"])
    h = h[h["Date"] < pd.Timestamp(feed_from)]
    long = h.melt(id_vars=["Date"], value_vars=[c for c in h.columns if c.startswith("Peanuts-")], var_name="store", value_name="amt")
    long["store"] = long["store"].str.replace("Peanuts-", "", regex=False)
    long["fy"] = long.Date.map(lambda d: fy_label(fy_start(d.date())))
    long["m"] = long.Date.dt.month
    allv = pd.concat([long[["store", "fy", "m", "amt"]], f[["store", "fy", "m", "amt"]]])
    piv = allv.groupby(["store", "fy", "m"]).amt.sum()
    fys = sorted(allv.fy.unique())
    head = [("Store", False), ("FY", False)] + [(x, True) for x in MONTHS] + [("Year", True), ("Apr–Sep", True), ("Oct–Mar", True)]

    def vals(st, fy):
        v = [piv.get((st, fy, mn), np.nan) for mn in MNUM]
        return v

    def line(v):
        v0 = [0 if np.isnan(x) else x for x in v]
        return [_num(x) if not np.isnan(x) else "" for x in v] + [_num(sum(v0)), _num(sum(v0[:6])), _num(sum(v0[6:]))]

    def growth(a, b):
        out = []
        for x, y in zip(a, b):
            out.append("" if (np.isnan(x) or np.isnan(y) or x == 0) else f"{100 * (y - x) / x:+.1f}%".replace("-", "−"))
        sa = [0 if np.isnan(x) else x for x in a]; sb = [0 if np.isnan(x) else x for x in b]
        both = [(x, y) for x, y in zip(a, b) if not np.isnan(x) and not np.isnan(y) and x]
        for rng in (range(12), range(6), range(6, 12)):
            pa = sum(a[i] for i in rng if not np.isnan(a[i]) and not np.isnan(b[i]))
            pb = sum(b[i] for i in rng if not np.isnan(a[i]) and not np.isnan(b[i]))
            out.append(f"{100 * (pb - pa) / pa:+.1f}%".replace("-", "−") if pa else "")
        return out

    rows = []
    for st in stores:
        rows.append(("band", [st]))
        prev = None
        for fy in fys:
            v = vals(st, fy)
            if all(np.isnan(x) or x == 0 for x in v):
                prev = v; continue
            rows.append(("", [st, fy] + line(v)))
            if prev is not None and not all(np.isnan(x) or x == 0 for x in prev):
                rows.append(("gr", ["", f"{fy} vs {fys[fys.index(fy) - 1]}"] + growth(prev, v)))
            prev = v
    rows.append(("band", ["All South stores"]))
    prev = None
    for fy in fys:
        v = [sum(piv.get((st, fy, mn), 0) for st in stores) for mn in MNUM]
        v = [x if x else np.nan for x in v]
        rows.append(("sub", ["South", fy] + line(v)))
        if prev is not None:
            rows.append(("gr", ["", f"{fy} vs {fys[fys.index(fy) - 1]}"] + growth(prev, v)))
        prev = v
    cur = fy_label(fy_start(last_full))
    note = (f"Bill Amount. FY 25-26 onwards from the POS feed; earlier years from the back office's daily sheet. "
            f"Complete months only (to {last_full:%d %b %Y}); growth compares the same months. Made {dt.date.today():%d %b %Y}.")
    label = ("Every year", f"to {last_full:%b %Y}")
    W = 2300
    tot = lambda fy: sum(piv.get((st, fy, mn), 0) for st in stores for mn in MNUM)
    tiles = [(f"FY {fys[-2]}", A.inr(tot(fys[-2]))), (f"FY {cur} so far", A.inr(tot(cur))),
             ("Years", f"{fys[0]} to {fys[-1]}"), ("Stores", str(len(stores)))]
    pages = _paged("Y2Y · South", "Every store, every year, month by month", tiles, head, rows, note, label, W, per=48)

    # the rest of this year at +10 / 15 / 20 % on last year (his "310826" sheet)
    ly = fys[fys.index(cur) - 1]
    rest = [(mn, ml) for mn, ml in zip(MNUM, MONTHS) if (dt.date(fy_start(last_full).year + (0 if mn >= 4 else 1), mn, 1) > last_full)]
    hd = [("Month", False)] + [(x, True) for x in stores] + [("Total", True), ("+10%", True), ("+15%", True), ("+20%", True)]
    rws = []
    for mn, ml in rest:
        v = [piv.get((st, ly, mn), 0) for st in stores]
        T = sum(v)
        rws.append(("", [f"{ml} (last year)"] + [_num(x) for x in v] + [_num(T), _num(T * 1.1), _num(T * 1.15), _num(T * 1.2)]))
    if rws:
        vv = [sum(piv.get((st, ly, mn), 0) for mn, _ in rest) for st in stores]
        T = sum(vv)
        rws.append(("grand", ["Total"] + [_num(x) for x in vv] + [_num(T), _num(T * 1.1), _num(T * 1.15), _num(T * 1.2)]))
        for up in (10, 15, 20):
            rws.append(("band", [f"At +{up}% on last year"]))
            for mn, ml in rest:
                v = [piv.get((st, ly, mn), 0) * (1 + up / 100) for st in stores]
                rws.append(("", [ml] + [_num(x) for x in v] + [_num(sum(v)), "", "", ""]))
        pages += _paged("Y2Y · South · the rest of the year", f"FY {cur}: last year's months at +10, 15, 20%",
                        tiles, hd, rws, note, label, 2000, per=60)
    return pages, W


# ── all four ─────────────────────────────────────────────────────────────────────────────────────────────────────
def build_all(df, pf, master, closed, hist, run: dt.date, outdir: Path) -> list[Path]:
    t = target_month(run)
    out = []
    for name, (pages, w) in (
            (f"South Data Annual_MW · {t:%b %Y}.pdf", south_pack(df, master, t)),
            (f"VFL Stores East & NE Annual_MW · {t:%b %Y}.pdf", east_vfl_pack(df, master, pf, t)),
            (f"All Stores East & NE Annual_MW · {t:%b %Y}.pdf", all_east_pack(pf, closed, t)),
            (f"Y2Y 3 years South · to {(run.replace(day=1) - dt.timedelta(days=1)):%b %Y}.pdf", y2y_south(df, master, hist, run))):
        out.append(render_pdf(pages, outdir / name, w))
    return out
