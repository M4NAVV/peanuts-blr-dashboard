# Streamlit dashboard on a Hugging Face Docker Space (CPU · 16 GB RAM).
FROM python:3.11-slim

WORKDIR /app

# ★ Chromium draws the 🕒 Afternoon Sales pictures (afternoon_sale.py, 26 Oct 2026); Noto covers ₹ and anything the
# brand font (fetched from Google Fonts at draw time) does not.
RUN apt-get update && apt-get install -y --no-install-recommends chromium fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

# Python deps first (better layer caching).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code, CSVs, fonts, .streamlit/config.toml.
COPY . .

# Streamlit config for a headless, iframe-embedded Space on port 8501.
ENV STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ENABLE_CORS=false \
    STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=false \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    HOME=/app

EXPOSE 8501
CMD ["streamlit", "run", "app.py"]
