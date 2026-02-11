"""Main application: Flask web server with daily news scraping and summarization."""

import logging
import threading

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


@app.route("/")
def index():
    articles = get_all_articles(limit=50)
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
    app.run(host="0.0.0.0", port=5000, debug=False)
