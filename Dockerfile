FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout=120 -r requirements.txt

# Install Playwright Chromium system dependencies manually, then the browser.
# `playwright install --with-deps` fails on newer Debian because some font
# package names changed (ttf-unifont -> fonts-unifont, etc.).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdbus-1-3 \
    libdrm2 libxkbcommon0 libatspi2.0-0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    fonts-unifont fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*
RUN playwright install chromium

# Copy application files
COPY app.py wsgi.py scraper.py summarizer.py database.py ./
COPY templates/ templates/

# Create data directory
RUN mkdir -p data

EXPOSE 5001

CMD ["gunicorn", "wsgi:application", \
     "--bind", "0.0.0.0:5001", \
     "--workers", "1", \
     "--threads", "4", \
     "--worker-class", "gthread", \
     "--timeout", "300"]
