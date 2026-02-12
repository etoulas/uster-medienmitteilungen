"""Tests for the database layer."""

import json

from database import (
    article_exists,
    get_all_articles,
    get_unsummarized_articles,
    insert_article,
    save_summary,
)


def test_insert_and_exists():
    assert not article_exists("123")
    insert_article("123", "https://example.com/123", "Title", "Body text")
    assert article_exists("123")


def test_insert_duplicate_is_ignored():
    insert_article("dup", "https://example.com/dup", "First", "Body 1")
    insert_article("dup", "https://example.com/dup", "Second", "Body 2")
    articles = get_all_articles()
    matching = [a for a in articles if a["source_id"] == "dup"]
    assert len(matching) == 1
    assert matching[0]["title"] == "First"


def test_get_all_articles_ordering():
    insert_article("a", "https://example.com/a", "Article A", "Text A")
    insert_article("b", "https://example.com/b", "Article B", "Text B")
    articles = get_all_articles()
    assert len(articles) == 2
    # Most recent first
    assert articles[0]["source_id"] == "b"


def test_get_all_articles_limit():
    for i in range(5):
        insert_article(str(i), f"https://example.com/{i}", f"Title {i}", f"Text {i}")
    assert len(get_all_articles(limit=3)) == 3


def test_unsummarized_articles():
    insert_article("u1", "https://example.com/u1", "Unsummarized", "Text")
    unsummarized = get_unsummarized_articles()
    assert len(unsummarized) == 1
    assert unsummarized[0]["source_id"] == "u1"


def test_save_summary():
    insert_article("s1", "https://example.com/s1", "To Summarize", "Original text")
    unsummarized = get_unsummarized_articles()
    article_id = unsummarized[0]["id"]

    save_summary(article_id, "This is a summary.")

    assert get_unsummarized_articles() == []
    articles = get_all_articles()
    assert articles[0]["summary"] == "This is a summary."
    assert articles[0]["summarized_at"] is not None


def test_save_summary_with_structured_fields():
    insert_article("s2", "https://example.com/s2", "Structured", "Original text")
    unsummarized = get_unsummarized_articles()
    article_id = unsummarized[0]["id"]

    save_summary(article_id, "Summary text.", tldr="Short.", relevancy=4,
                 background_info="Context here.")

    articles = get_all_articles()
    article = [a for a in articles if a["source_id"] == "s2"][0]
    assert article["summary"] == "Summary text."
    assert article["tldr"] == "Short."
    assert article["relevancy"] == 4
    assert article["background_info"] == "Context here."


def test_insert_with_published_date():
    insert_article("d1", "https://example.com/d1", "Dated", "Text", "2025-01-15")
    articles = get_all_articles()
    assert articles[0]["published_date"] == "2025-01-15"


def test_insert_without_published_date():
    insert_article("nd1", "https://example.com/nd1", "No Date", "Text")
    articles = get_all_articles()
    assert articles[0]["published_date"] is None


def test_traktanden_json_roundtrip():
    insert_article("tk1", "https://example.com/tk1", "Stadtratsbeschlüsse der Sitzungen", "Text")
    unsummarized = get_unsummarized_articles()
    article_id = unsummarized[0]["id"]

    traktanden = [
        {"nummer": 1, "titel": "Budget 2026", "tldr": "Budget genehmigt.", "zusammenfassung": "Das Budget wurde genehmigt.", "relevanz": 4},
        {"nummer": 2, "titel": "Personalgeschäft", "tldr": "Neue Stelle.", "zusammenfassung": "Eine neue Stelle wurde geschaffen.", "relevanz": 2},
    ]
    traktanden_json = json.dumps(traktanden, ensure_ascii=False)

    save_summary(article_id, "Zusammenfassung.", tldr="Kurz.", relevancy=4,
                 background_info=None, traktanden_json=traktanden_json)

    articles = get_all_articles()
    article = [a for a in articles if a["source_id"] == "tk1"][0]
    assert article["traktanden_json"] == traktanden_json
    parsed = json.loads(article["traktanden_json"])
    assert len(parsed) == 2
    assert parsed[0]["titel"] == "Budget 2026"


def test_traktanden_json_null_by_default():
    insert_article("tk2", "https://example.com/tk2", "Normal Article", "Text")
    unsummarized = get_unsummarized_articles()
    article_id = unsummarized[0]["id"]

    save_summary(article_id, "Summary.")

    articles = get_all_articles()
    article = [a for a in articles if a["source_id"] == "tk2"][0]
    assert article["traktanden_json"] is None
