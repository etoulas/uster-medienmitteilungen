"""Tests for the scraper module (unit tests with mocked Playwright)."""

from unittest.mock import MagicMock, patch

from scraper import _source_id_from_url, scrape_news


class TestSourceIdFromUrl:
    def test_valid_url(self):
        assert _source_id_from_url("https://www.uster.ch/aktuellesinformationen/670055") == "670055"

    def test_relative_url(self):
        assert _source_id_from_url("/aktuellesinformationen/12345") == "12345"

    def test_no_match(self):
        assert _source_id_from_url("https://www.uster.ch/other/page") is None

    def test_non_numeric(self):
        assert _source_id_from_url("/aktuellesinformationen/abc") is None


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
            {"href": "/aktuellesinformationen/111", "title": "Test Article"},
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
            {"href": "/aktuellesinformationen/222", "title": "Old Article"},
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
            {"href": "/aktuellesinformationen/333", "title": "Short"},
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
            {"href": "/aktuellesinformationen/444", "title": "Dup 1"},
            {"href": "/aktuellesinformationen/444", "title": "Dup 2"},
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
