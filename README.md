# Peanuts (Manyavar) — Bengaluru Sales Dashboard

A KPI dashboard over the daily Tableau sales export for the Grand Kamraj Road
store. Reads a **published Google Sheet** in production so the dashboard
**auto-updates** whenever the sheet is refreshed — one permanent link, no
redeploys.

## Daily update (≈30 seconds)

1. Download the fresh cumulative export from Tableau (as usual).
2. Open the **Google Sheet** (bookmarked): **File → Import → Upload → select the
   Excel → "Replace current sheet" → Import data.**
3. Done. The dashboard picks up the new data automatically (within its
   30-minute cache, or immediately via the **🔄 Refresh data now** button in the
   sidebar).

> The dashboard is defensive about formatting — it strips the "Grand Total"
> footer row, handles comma-formatted numbers, and re-parses dates — so the
> re-import doesn't break it.

## Local development

```bash
cd "Dashboard"
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Put the export at data/sales.xlsx, then:
streamlit run app.py
```

Data source resolution (in `loader.py`):
1. `SHEET_CSV_URL` env var, else
2. `SHEET_CSV_URL` in Streamlit secrets, else
3. local `data/sales.xlsx`.

## Hosting (one-time — free, permanent link)

**Source of truth = a published Google Sheet:**
1. Create a Google Sheet, import the Excel into it (see daily update above).
2. **File → Share → Publish to web → Entire document → CSV → Publish.**
   Copy the URL (looks like
   `https://docs.google.com/spreadsheets/d/e/…/pub?output=csv`).

**Deploy on Streamlit Community Cloud:**
1. Push this folder to a GitHub repo.
2. On [share.streamlit.io](https://share.streamlit.io) → New app → point at the
   repo / `app.py`.
3. In the app's **Settings → Secrets**, add:
   ```toml
   SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/…/pub?output=csv"
   ```
4. The app gets a permanent URL, e.g. `https://manyavar-blr.streamlit.app`.

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit dashboard (6 tabs) |
| `loader.py` | Data loading + cleaning + KPI helpers |
| `requirements.txt` | Deps for Streamlit Cloud |
| `.streamlit/config.toml` | Brand theme |
| `data/sales.xlsx` | Local dev copy (gitignored) |
