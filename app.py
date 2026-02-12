"""Main application: Flask web server with daily news scraping and summarization."""

import json
import logging
import re
import threading
from datetime import datetime

from flask import Flask, render_template, redirect, url_for
from apscheduler.schedulers.background import BackgroundScheduler

from database import init_db, get_all_articles
from scraper import scrape_news
from summarizer import summarize_articles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Lock to prevent concurrent scrape/summarize runs
_job_lock = threading.Lock()


def fetch_and_summarize():
    """Run the full pipeline: scrape new articles, then summarize them."""
    if not _job_lock.acquire(blocking=False):
        logger.info("Job already running, skipping")
        return
    try:
        logger.info("Starting fetch-and-summarize pipeline")
        new_articles = scrape_news()
        if new_articles > 0:
            summarize_articles()
        else:
            # Also summarize any previously unsummarized articles
            summarize_articles()
        logger.info("Pipeline complete")
    finally:
        _job_lock.release()


GERMAN_MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}


def _parse_display_date(published_date: str | None, fetched_at: str) -> str:
    """Extract a YYYY-MM-DD date string from published_date, falling back to fetched_at."""
    if published_date:
        # Try "DD.MM.YYYY" (e.g. "12.02.2026")
        m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", published_date)
        if m:
            return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        # Try "DD. Monat YYYY" (e.g. "12. Februar 2026")
        m = re.search(r"(\d{1,2})\.\s*([A-Za-zÄäÖöÜü]+)\s+(\d{4})", published_date)
        if m:
            month = GERMAN_MONTHS.get(m.group(2).lower())
            if month:
                return f"{m.group(3)}-{month:02d}-{int(m.group(1)):02d}"
        # Try ISO-ish "YYYY-MM-DD"
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", published_date)
        if m:
            return m.group(0)
    # Fallback: date portion of fetched_at (ISO datetime)
    return fetched_at[:10]


def _format_date_german(iso_date: str) -> str:
    """Format YYYY-MM-DD as a German display string like 'Mittwoch, 12. Februar 2026'."""
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d")
    except ValueError:
        return iso_date
    weekdays = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    months = ["Januar", "Februar", "März", "April", "Mai", "Juni",
              "Juli", "August", "September", "Oktober", "November", "Dezember"]
    return f"{weekdays[dt.weekday()]}, {dt.day}. {months[dt.month - 1]} {dt.year}"


@app.route("/")
def index():
    articles = get_all_articles(limit=50)
    for article in articles:
        article["display_date"] = _parse_display_date(article.get("published_date"), article["fetched_at"])
        article["display_date_label"] = _format_date_german(article["display_date"])
        if article.get("traktanden_json"):
            try:
                article["traktanden"] = json.loads(article["traktanden_json"])
            except (json.JSONDecodeError, TypeError):
                article["traktanden"] = None
        else:
            article["traktanden"] = None
    # Sort by display_date descending (stable sort preserves DB order within same date)
    articles.sort(key=lambda a: a["display_date"], reverse=True)
    return render_template("feed.html", articles=articles)


@app.route("/fetch")
def fetch():
    """Manually trigger a fetch-and-summarize run in a background thread."""
    thread = threading.Thread(target=fetch_and_summarize, daemon=True)
    thread.start()
    return redirect(url_for("index"))


def start_scheduler():
    """Start the daily scheduler that runs at 07:00."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(fetch_and_summarize, "cron", hour=7, minute=0, id="daily_fetch")
    scheduler.start()
    logger.info("Scheduler started: daily fetch at 07:00")


if __name__ == "__main__":
    init_db()
    start_scheduler()
    logger.info("Starting web server on http://localhost:5000")
    app.run(host="0.0.0.0", port=5001, debug=False)
