"""Tests for the scraper module (unit tests with mocked Playwright)."""

from unittest.mock import MagicMock, patch

from scraper import (
    _source_id_from_url,
    _is_stadtratsbeschluesse,
    _extract_beschluesse_links,
    _extract_pdf_text,
    _enrich_stadtratsbeschluesse,
    scrape_news,
)


class TestSourceIdFromUrl:
    def test_valid_url(self):
        assert _source_id_from_url("https://www.uster.ch/_rte/information/670055") == "670055"

    def test_relative_url(self):
        assert _source_id_from_url("/_rte/information/12345") == "12345"

    def test_no_match(self):
        assert _source_id_from_url("https://www.uster.ch/other/page") is None

    def test_non_numeric(self):
        assert _source_id_from_url("/_rte/information/abc") is None


class TestIsStadtratsbeschluesse:
    def test_matching_title(self):
        assert _is_stadtratsbeschluesse("Stadtratsbeschlüsse der Sitzungen vom 3. Februar 2026")

    def test_matching_title_lowercase(self):
        assert _is_stadtratsbeschluesse("stadtratsbeschlüsse der sitzungen vom 10. März 2026")

    def test_non_matching_title(self):
        assert not _is_stadtratsbeschluesse("Neue Öffnungszeiten der Bibliothek")

    def test_empty_title(self):
        assert not _is_stadtratsbeschluesse("")

    def test_singular_sitzung(self):
        assert _is_stadtratsbeschluesse("Stadtratsbeschlüsse der Sitzung vom 3. Februar 2026")


class TestExtractBeschluesseLinks:
    def test_extracts_links(self):
        page = MagicMock()
        page.evaluate.return_value = ["/beschluessestadtrat/123", "/beschluessestadtrat/456"]
        links = _extract_beschluesse_links(page)
        assert links == ["/beschluessestadtrat/123", "/beschluessestadtrat/456"]

    def test_no_links(self):
        page = MagicMock()
        page.evaluate.return_value = []
        assert _extract_beschluesse_links(page) == []


class TestExtractPdfText:
    @patch("scraper.fitz")
    @patch("scraper.requests.get")
    def test_extracts_text(self, mock_get, mock_fitz):
        mock_response = MagicMock()
        mock_response.content = b"pdf-bytes"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        mock_page = MagicMock()
        mock_page.get_text.return_value = "PDF content here"
        mock_doc = MagicMock()
        mock_doc.__iter__ = lambda self: iter([mock_page])
        mock_fitz.open.return_value = mock_doc

        result = _extract_pdf_text("https://example.com/doc.pdf")
        assert result == "PDF content here"
        mock_get.assert_called_once_with("https://example.com/doc.pdf", timeout=30)
        mock_fitz.open.assert_called_once_with(stream=b"pdf-bytes", filetype="pdf")

    @patch("scraper.requests.get", side_effect=Exception("Network error"))
    def test_returns_empty_on_failure(self, mock_get):
        result = _extract_pdf_text("https://example.com/broken.pdf")
        assert result == ""


class TestEnrichStadtratsbeschluesse:
    def test_enriches_with_traktanden(self):
        page = MagicMock()
        # First call: _extract_beschluesse_links
        # Second call: _extract_traktanden (after goto)
        page.evaluate.side_effect = [
            ["/beschluessestadtrat/100"],  # beschluesse links
            [  # traktanden
                {"title": "Budget", "description": "Budget 2026", "pdf_url": None},
                {"title": "Personal", "description": "Neue Stelle", "pdf_url": None},
            ],
        ]
        result = _enrich_stadtratsbeschluesse(page, "Original text")
        assert "Original text" in result
        assert "### Traktandum 1: Budget" in result
        assert "### Traktandum 2: Personal" in result
        assert "Budget 2026" in result

    def test_returns_original_when_no_links(self):
        page = MagicMock()
        page.evaluate.return_value = []  # no beschluesse links
        result = _enrich_stadtratsbeschluesse(page, "Original text")
        assert result == "Original text"

    def test_fallback_on_empty_traktanden(self):
        page = MagicMock()
        page.evaluate.side_effect = [
            ["/beschluessestadtrat/200"],  # beschluesse links
            [],  # no structured traktanden
            "Fallback page text",  # body innerText fallback
        ]
        result = _enrich_stadtratsbeschluesse(page, "Original text")
        assert "Fallback page text" in result
        assert "Traktandum 1" in result

    @patch("scraper._extract_pdf_text", return_value="PDF extracted text")
    def test_includes_pdf_content(self, mock_pdf):
        page = MagicMock()
        page.evaluate.side_effect = [
            ["/beschluessestadtrat/300"],
            [{"title": "Beschluss", "description": "Detail", "pdf_url": "/_doc/123.pdf"}],
        ]
        result = _enrich_stadtratsbeschluesse(page, "Original")
        assert "[PDF-Inhalt]" in result
        assert "PDF extracted text" in result
        mock_pdf.assert_called_once_with("https://www.uster.ch/_doc/123.pdf")


class TestScrapeNews:
    def _make_mock_page(self, article_links, article_content):
        """Create a mock Playwright page."""
        page = MagicMock()
        # First evaluate call returns article links, subsequent ones return content
        page.evaluate.side_effect = [article_links] + [article_content] * len(article_links)
        page.goto.return_value = None
        page.wait_for_timeout.return_value = None
        return page

    @patch("scraper.sync_playwright")
    @patch("scraper.article_exists", return_value=False)
    @patch("scraper.insert_article")
    def test_scrapes_new_articles(self, mock_insert, mock_exists, mock_pw):
        links = [
            {"href": "/_rte/information/111", "title": "Test Article"},
        ]
        content = {"title": "Test Article", "text": "A" * 100, "date": "2025-01-01"}

        page = self._make_mock_page(links, content)
        browser = MagicMock()
        context = MagicMock()
        context.new_page.return_value = page
        browser.new_context.return_value = context
        mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = browser

        count = scrape_news()

        assert count == 1
        mock_insert.assert_called_once()
        args = mock_insert.call_args[0]
        assert args[0] == "111"  # source_id
        assert "Test Article" in args[2]  # title

    @patch("scraper.sync_playwright")
    @patch("scraper.article_exists", return_value=True)
    @patch("scraper.insert_article")
    def test_skips_existing_articles(self, mock_insert, mock_exists, mock_pw):
        links = [
            {"href": "/_rte/information/222", "title": "Old Article"},
        ]

        page = self._make_mock_page(links, {})
        browser = MagicMock()
        context = MagicMock()
        context.new_page.return_value = page
        browser.new_context.return_value = context
        mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = browser

        count = scrape_news()

        assert count == 0
        mock_insert.assert_not_called()

    @patch("scraper.sync_playwright")
    @patch("scraper.article_exists", return_value=False)
    @patch("scraper.insert_article")
    def test_skips_short_text(self, mock_insert, mock_exists, mock_pw):
        links = [
            {"href": "/_rte/information/333", "title": "Short"},
        ]
        content = {"title": "Short", "text": "Too short", "date": None}

        page = self._make_mock_page(links, content)
        browser = MagicMock()
        context = MagicMock()
        context.new_page.return_value = page
        browser.new_context.return_value = context
        mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = browser

        count = scrape_news()

        assert count == 0
        mock_insert.assert_not_called()

    @patch("scraper.sync_playwright")
    @patch("scraper.article_exists", return_value=False)
    @patch("scraper.insert_article")
    def test_deduplicates_links(self, mock_insert, mock_exists, mock_pw):
        links = [
            {"href": "/_rte/information/444", "title": "Dup 1"},
            {"href": "/_rte/information/444", "title": "Dup 2"},
        ]
        content = {"title": "Dup 1", "text": "B" * 100, "date": None}

        page = self._make_mock_page(links, content)
        browser = MagicMock()
        context = MagicMock()
        context.new_page.return_value = page
        browser.new_context.return_value = context
        mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = browser

        count = scrape_news()

        assert count == 1
        assert mock_insert.call_count == 1
