"""Tests for Flask routes."""

import json
from unittest.mock import patch

import pytest

from app import app
from database import insert_article, save_summary


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_index_empty(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Noch keine Artikel vorhanden" in resp.data


def test_index_shows_articles(client):
    insert_article("r1", "https://example.com/r1", "Route Test Article", "Some text")
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Route Test Article" in resp.data
    assert b"Zusammenfassung wird erstellt" in resp.data


def test_index_shows_summary(client):
    insert_article("r2", "https://example.com/r2", "Summarized Article", "Some text")
    from database import get_unsummarized_articles
    article = get_unsummarized_articles()[0]
    save_summary(article["id"], "Dies ist eine Zusammenfassung.",
                 tldr="Kurze Info.", relevancy=4, background_info="Hintergrund hier.")

    resp = client.get("/")
    assert resp.status_code == 200
    assert "Dies ist eine Zusammenfassung.".encode() in resp.data
    assert "Kurze Info.".encode() in resp.data
    assert b"relevancy-4" in resp.data
    assert "Hintergrund hier.".encode() in resp.data


def test_index_shows_traktanden(client):
    insert_article("tk1", "https://example.com/tk1", "Stadtratsbeschlüsse der Sitzungen", "Text")
    from database import get_unsummarized_articles
    article = get_unsummarized_articles()[0]
    traktanden = [
        {"nummer": 1, "titel": "Budget 2026", "tldr": "Budget genehmigt.", "zusammenfassung": "Das Budget wurde genehmigt.", "relevanz": 4},
        {"nummer": 2, "titel": "Personalgeschäft", "tldr": "Neue Stelle.", "zusammenfassung": "Eine Stelle wurde bewilligt.", "relevanz": 2},
    ]
    save_summary(article["id"], "Zusammenfassung.", tldr="Kurz.", relevancy=4,
                 traktanden_json=json.dumps(traktanden, ensure_ascii=False))

    resp = client.get("/")
    assert resp.status_code == 200
    assert "Budget 2026".encode() in resp.data
    assert "Budget genehmigt.".encode() in resp.data
    assert "Personalgesch\u00e4ft".encode("utf-8") in resp.data
    assert b"Stadtratsbeschl" in resp.data
    assert b"rel-4" in resp.data
    assert b"rel-2" in resp.data


def test_index_no_traktanden_for_normal_article(client):
    insert_article("nt1", "https://example.com/nt1", "Normal Article", "Text")
    from database import get_unsummarized_articles
    article = get_unsummarized_articles()[0]
    save_summary(article["id"], "Summary.", tldr="Short.")

    resp = client.get("/")
    assert resp.status_code == 200
    # The "Stadtratsbeschlüsse:" label should not be rendered for normal articles
    assert b"Stadtratsbeschl&uuml;sse:" not in resp.data


@patch("app.fetch_and_summarize")
def test_fetch_redirects_to_index(mock_fetch, client):
    resp = client.get("/fetch")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
