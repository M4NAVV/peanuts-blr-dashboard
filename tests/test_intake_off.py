"""The intake form is discontinued (Manav, 13 Nov 2026): no live read, but the code still works when switched back."""
import pandas as pd

import intake_brands as IB


def test_off_means_no_live_read(monkeypatch):
    monkeypatch.setattr(IB, "IN_USE", False)
    monkeypatch.setattr(IB, "read_responses", lambda *a, **k: (_ for _ in ()).throw(AssertionError("read the form")))
    assert IB.split_map() == {}
    assert IB.for_day("2026-11-12") == {}
    assert "discontinued" in IB.last_problem()


def test_on_reads_the_form_again(monkeypatch):
    monkeypatch.setattr(IB, "IN_USE", True)
    called = []
    monkeypatch.setattr(IB, "read_responses", lambda *a, **k: called.append(1) or pd.DataFrame())
    monkeypatch.setattr(IB, "mail_map", lambda *a, **k: {})
    IB.split_map()
    assert called, "with IN_USE the form is read"


def test_given_responses_still_parse_when_off(monkeypatch):
    """Tests and any one-off check can still hand the parser a sheet."""
    monkeypatch.setattr(IB, "IN_USE", False)
    r = pd.DataFrame({"Timestamp": ["12/11/2026 22:00:00"], "Email Address": ["a@x.com"], "Date": ["12/11/2026"],
                      "MANYAVAR SALES": ["1000"], "MOHEY SALES": ["0"], "TWAMEV SALES": ["0"]})
    m = IB.split_map(r, {"a@x.com": 7})
    assert isinstance(m, dict)
