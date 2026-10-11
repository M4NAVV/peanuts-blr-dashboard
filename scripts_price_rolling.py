"""Build the ROLLING price-bracket report as a sample, outside the dashboard.

Manav, 11 Oct 2026: "build this separately as a sample, will get it approved and then go live".
It is NOT in the 📄 REPORTS PDF picker. Usage:  python scripts_price_rolling.py [YYYY-MM-DD]
Writes the PDF to ~/Downloads.
"""
import sys
from pathlib import Path

import pandas as pd

import category_pdf as C
import loader as L
import portfolio_loader as PL

if __name__ == "__main__":
    df = L.load_data(pf=PL.load_portfolio())
    asof = pd.Timestamp(sys.argv[1]) if len(sys.argv) > 1 else df["date"].max()
    name, pdf = C.build(df, asof, mode="rolling")
    out = Path.home() / "Downloads" / name
    out.write_bytes(pdf)
    print(out)
