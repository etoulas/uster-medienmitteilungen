"""Tests for Flask routes."""

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
    save_summary(article["id"], "Dies ist eine Zusammenfassung.")

    resp = client.get("/")
    assert resp.status_code == 200
    assert "Dies ist eine Zusammenfassung.".encode() in resp.data


@patch("app.fetch_and_summarize")
def test_fetch_redirects_to_index(mock_fetch, client):
    resp = client.get("/fetch")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
