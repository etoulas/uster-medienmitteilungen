"""Tests for the summarizer module (mocked Claude API)."""

import json
from unittest.mock import MagicMock, patch

from database import insert_article, get_all_articles, get_unsummarized_articles
from summarizer import summarize_articles, _parse_structured_response, STADTRAT_SYSTEM_PROMPT, SYSTEM_PROMPT


def _make_mock_response(text):
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def _json_response(tldr="Kurz.", relevancy=3, summary="Zusammenfassung hier.", background=None):
    return json.dumps({
        "tldr": tldr,
        "relevancy": relevancy,
        "summary": summary,
        "background": background,
    })


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("summarizer.anthropic.Anthropic")
def test_summarizes_unsummarized_articles(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_mock_response(
        _json_response(tldr="Neues Projekt.", relevancy=4, summary="Die Stadt plant ein neues Projekt.")
    )
    mock_anthropic_cls.return_value = mock_client

    insert_article("sum1", "https://example.com/1", "Title 1", "Some long article text here.")

    count = summarize_articles()

    assert count == 1
    mock_client.messages.create.assert_called_once()
    articles = get_all_articles()
    assert articles[0]["summary"] == "Die Stadt plant ein neues Projekt."
    assert articles[0]["tldr"] == "Neues Projekt."
    assert articles[0]["relevancy"] == 4
    assert articles[0]["background_info"] is None


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("summarizer.anthropic.Anthropic")
def test_saves_background_info(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_mock_response(
        _json_response(background="Die Kläui-Bibliothek ist die öffentliche Bibliothek der Stadt Uster.")
    )
    mock_anthropic_cls.return_value = mock_client

    insert_article("bg1", "https://example.com/bg", "Bibliothek", "Text about Kläui-Bibliothek.")

    summarize_articles()

    articles = get_all_articles()
    assert articles[0]["background_info"] == "Die Kläui-Bibliothek ist die öffentliche Bibliothek der Stadt Uster."


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
    mock_client.messages.create.return_value = _make_mock_response(_json_response())
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


class TestParseStructuredResponse:
    def test_valid_json(self):
        resp = _json_response(tldr="Test.", relevancy=4, summary="Summary.", background="Info.")
        parsed = _parse_structured_response(resp)
        assert parsed["tldr"] == "Test."
        assert parsed["relevancy"] == 4
        assert parsed["summary"] == "Summary."
        assert parsed["background_info"] == "Info."

    def test_json_with_code_fence(self):
        resp = "```json\n" + _json_response(tldr="Test.", relevancy=2) + "\n```"
        parsed = _parse_structured_response(resp)
        assert parsed["tldr"] == "Test."
        assert parsed["relevancy"] == 2

    def test_clamps_relevancy(self):
        resp = json.dumps({"tldr": "X", "relevancy": 10, "summary": "S", "background": None})
        parsed = _parse_structured_response(resp)
        assert parsed["relevancy"] == 5

        resp = json.dumps({"tldr": "X", "relevancy": 0, "summary": "S", "background": None})
        parsed = _parse_structured_response(resp)
        assert parsed["relevancy"] == 1

    def test_fallback_on_invalid_json(self):
        parsed = _parse_structured_response("Just plain text summary.")
        assert parsed["summary"] == "Just plain text summary."
        assert parsed["tldr"] is None
        assert parsed["relevancy"] is None

    def test_null_background(self):
        resp = _json_response(background=None)
        parsed = _parse_structured_response(resp)
        assert parsed["background_info"] is None

    def test_traktanden_json_parsed(self):
        data = {
            "tldr": "Sitzung.",
            "relevancy": 4,
            "summary": "Zusammenfassung.",
            "background": None,
            "traktanden": [
                {"nummer": 1, "titel": "Budget", "tldr": "Genehmigt.", "zusammenfassung": "Budget OK.", "relevanz": 4},
                {"nummer": 2, "titel": "Personal", "tldr": "Neue Stelle.", "zusammenfassung": "Stelle geschaffen.", "relevanz": 2},
            ],
        }
        parsed = _parse_structured_response(json.dumps(data))
        assert parsed["traktanden_json"] is not None
        traktanden = json.loads(parsed["traktanden_json"])
        assert len(traktanden) == 2
        assert traktanden[0]["titel"] == "Budget"
        assert traktanden[1]["relevanz"] == 2

    def test_traktanden_json_none_when_absent(self):
        resp = _json_response()
        parsed = _parse_structured_response(resp)
        assert parsed["traktanden_json"] is None

    def test_traktanden_json_none_on_invalid(self):
        parsed = _parse_structured_response("Just plain text.")
        assert parsed["traktanden_json"] is None


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("summarizer.anthropic.Anthropic")
def test_stadtrat_uses_specialized_prompt(mock_anthropic_cls):
    mock_client = MagicMock()
    stadtrat_response = json.dumps({
        "tldr": "Wichtige Beschlüsse.",
        "relevancy": 4,
        "summary": "Der Stadtrat hat getagt.",
        "background": None,
        "traktanden": [
            {"nummer": 1, "titel": "Budget", "tldr": "OK.", "zusammenfassung": "Genehmigt.", "relevanz": 4},
        ],
    })
    mock_client.messages.create.return_value = _make_mock_response(stadtrat_response)
    mock_anthropic_cls.return_value = mock_client

    insert_article("sr1", "https://example.com/sr1",
                    "Stadtratsbeschlüsse der Sitzungen vom 3. Februar 2026", "Inhalt")

    count = summarize_articles()

    assert count == 1
    call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["system"] == STADTRAT_SYSTEM_PROMPT
    assert call_kwargs["max_tokens"] == 2000

    articles = get_all_articles()
    assert articles[0]["traktanden_json"] is not None
    traktanden = json.loads(articles[0]["traktanden_json"])
    assert len(traktanden) == 1
    assert traktanden[0]["titel"] == "Budget"


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("summarizer.anthropic.Anthropic")
def test_normal_article_uses_standard_prompt(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_mock_response(_json_response())
    mock_anthropic_cls.return_value = mock_client

    insert_article("norm1", "https://example.com/norm1", "Neue Öffnungszeiten", "Inhalt")

    summarize_articles()

    call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["system"] == SYSTEM_PROMPT
    assert call_kwargs["max_tokens"] == 800


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("summarizer.anthropic.Anthropic")
def test_stadtrat_truncation_limit(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_mock_response(
        json.dumps({"tldr": "X", "relevancy": 3, "summary": "S", "background": None, "traktanden": []})
    )
    mock_anthropic_cls.return_value = mock_client

    long_text = "A" * 50000
    insert_article("sr_long", "https://example.com/sr_long",
                    "Stadtratsbeschlüsse der Sitzungen vom 1. Januar 2026", long_text)

    summarize_articles()

    call_args = mock_client.messages.create.call_args
    user_msg = call_args[1]["messages"][0]["content"]
    assert "[Text gekürzt]" in user_msg
    # Should truncate at 40k, not 15k
    assert len(user_msg) > 20000
