"""The afternoon sale pictures (afternoon_sale.py): the arithmetic behind the seven — no network, no Chrome."""
import datetime as dt
import re

import afternoon_sale as A


def _strip(h):
    return re.sub(r"<[^>]+>", " ", h)


def test_sample_ties_to_his_25_oct_images():
    # every total on his own hand-made sheets for 25 Oct 2026
    d = A.sample()
    assert "₹3,96,585" in A.img_siliguri(d)
    assert "₹3,76,187" in A.img_outstation(d)
    east = _strip(A.img_vfl_region(d, "EAST"))
    assert "₹4,10,467" in east and "₹32,50,000" in east and "12.6%" in east
    south = _strip(A.img_vfl_region(d, "SOUTH"))
    assert "₹10,22,470" in south and "₹61,00,000" in south and "16.8%" in south
    both = _strip(A.img_vfl_both(d))
    assert "₹14,32,937" in both and "20 / 20" in both
    s = _strip(A.img_summary(d))
    assert "₹17,95,242" in s and "14 / 20" in s and "₹19,829" in s and "₹71,647" in s


def test_indian_grouping():
    assert A.inr(1795242) == "₹17,95,242"
    assert A.inr(999) == "₹999"
    assert A.inr(100000) == "₹1,00,000"
    assert A.inr(None) == "—"


def test_blank_is_not_zero():
    d = A.sample()
    d.sale[69] = None                                     # Turtle City Centre Guwahati: figure never arrived
    s = _strip(A.img_summary(d))
    assert "18 / 21" in s                                 # still active, not live, not added
    assert "Not received" in A.img_outstation(d) and "69" in _strip(A.img_outstation(d))


def test_storemaster_closure_removes_a_store_everywhere():
    d = A.sample()
    d.closed = {54}                                       # Colorplus Jamshedpur closed
    s = _strip(A.img_summary(d))
    assert "18 / 20" in s and "40 / 48" in s
    assert "JAMSHEDPUR" not in A.img_outstation(d)


def test_achieved_is_paired_over_stores_with_a_target():
    d = A.sample()
    d.target[58] = None                                   # Planet Mall's target not typed
    east = _strip(A.img_vfl_region(d, "EAST"))
    # 2,17,720 sold where a target exists, against 27,50,000 → 7.9 %, never 4,10,467 / 27,50,000
    assert "₹27,50,000" in east and "7.9%" in east


def test_wrong_date_refuses():
    d = A.sample()
    why = A.check(d, dt.date(2026, 10, 26))
    assert why and "not today" in why[0]
    assert A.check(d, dt.date(2026, 10, 25)) == []


def test_every_listed_store_is_on_a_layout_once():
    sil = [c for _, g in A.SILIGURI for c, _ in g]
    out = [c for _, g in A.OUTSTATION for c, _ in g]
    south = [c for c, _ in A.SOUTH]
    every = sil + out + south
    assert len(every) == len(set(every)) == 49
    vfl = [c for v in A.VFL.values() for c, _, _ in v]
    assert len(vfl) == len(set(vfl)) == 20 and set(vfl) <= set(every)


def test_zip_holds_the_seven_with_whatsapp_names():
    import io
    import zipfile
    names = [A.shown_name(n, w, dt.date(2026, 10, 26)) for n, (_, w, _) in enumerate(A.IMAGES, 1)]
    z = zipfile.ZipFile(io.BytesIO(A.zip_bytes([(n, b"png") for n in names])))
    assert z.namelist() == names and names[0] == "AFT 1 · Siliguri — mall & on road · 26-10-2026.png"
