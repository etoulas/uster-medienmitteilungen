"""SQLite database layer for storing news articles and their summaries."""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.environ.get(
    "NEWS_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "news.db")
)


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT UNIQUE NOT NULL,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            original_text TEXT NOT NULL,
            summary TEXT,
            tldr TEXT,
            relevancy INTEGER,
            background_info TEXT,
            published_date TEXT,
            fetched_at TEXT NOT NULL,
            summarized_at TEXT
        )
    """)
    # Migrate existing DBs: add columns if they don't exist
    for col, coltype in [("tldr", "TEXT"), ("relevancy", "INTEGER"), ("background_info", "TEXT"), ("traktanden_json", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE articles ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    conn.close()


def article_exists(source_id: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM articles WHERE source_id = ?", (source_id,)
    ).fetchone()
    conn.close()
    return row is not None


def insert_article(source_id: str, url: str, title: str, original_text: str, published_date: str | None = None):
    conn = get_connection()
    conn.execute(
        """INSERT OR IGNORE INTO articles (source_id, url, title, original_text, published_date, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (source_id, url, title, original_text, published_date, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_unsummarized_articles() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, source_id, url, title, original_text FROM articles WHERE summary IS NULL"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_summary(article_id: int, summary: str, tldr: str | None = None,
                  relevancy: int | None = None, background_info: str | None = None,
                  traktanden_json: str | None = None):
    conn = get_connection()
    conn.execute(
        "UPDATE articles SET summary = ?, tldr = ?, relevancy = ?, background_info = ?, traktanden_json = ?, summarized_at = ? WHERE id = ?",
        (summary, tldr, relevancy, background_info, traktanden_json, datetime.utcnow().isoformat(), article_id),
    )
    conn.commit()
    conn.close()


def get_all_articles(limit: int = 50) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, source_id, url, title, original_text, summary, tldr, relevancy, background_info,
                  traktanden_json, published_date, fetched_at, summarized_at
           FROM articles ORDER BY COALESCE(published_date, fetched_at) DESC, fetched_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
