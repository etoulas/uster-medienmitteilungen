"""Tests for the summarizer module (mocked Claude API)."""

from unittest.mock import MagicMock, patch

from database import insert_article, get_all_articles, get_unsummarized_articles
from summarizer import summarize_articles


def _make_mock_response(text):
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("summarizer.anthropic.Anthropic")
def test_summarizes_unsummarized_articles(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_mock_response("Zusammenfassung hier.")
    mock_anthropic_cls.return_value = mock_client

    insert_article("sum1", "https://example.com/1", "Title 1", "Some long article text here.")

    count = summarize_articles()

    assert count == 1
    mock_client.messages.create.assert_called_once()
    articles = get_all_articles()
    assert articles[0]["summary"] == "Zusammenfassung hier."


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("summarizer.anthropic.Anthropic")
def test_skips_already_summarized(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    # No unsummarized articles
    count = summarize_articles()

    assert count == 0
    mock_client.messages.create.assert_not_called()


@patch.dict("os.environ", {}, clear=True)
def test_returns_zero_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    insert_article("nokey", "https://example.com/nokey", "Title", "Text")

    count = summarize_articles()

    assert count == 0
    assert len(get_unsummarized_articles()) == 1


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("summarizer.anthropic.Anthropic")
def test_truncates_long_text(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_mock_response("Kurz.")
    mock_anthropic_cls.return_value = mock_client

    long_text = "A" * 20000
    insert_article("long1", "https://example.com/long", "Long Article", long_text)

    summarize_articles()

    call_args = mock_client.messages.create.call_args
    user_msg = call_args[1]["messages"][0]["content"]
    assert "[Text gekürzt]" in user_msg


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("summarizer.anthropic.Anthropic")
def test_handles_api_error_gracefully(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API error")
    mock_anthropic_cls.return_value = mock_client

    insert_article("err1", "https://example.com/err", "Error Article", "Some text here.")

    count = summarize_articles()

    assert count == 0
    assert len(get_unsummarized_articles()) == 1
