"""Scraper for Stadt Uster Medienmitteilungen.

The page at https://www.uster.ch/aktuellesinformationen loads news articles
dynamically via JavaScript (i-CMS/CityWeb platform). We use Playwright to
render the page and extract article links, then visit each article page to
get the full text.
"""

import logging
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from database import article_exists, insert_article

logger = logging.getLogger(__name__)

BASE_URL = "https://www.uster.ch"
LISTING_URL = f"{BASE_URL}/aktuellesinformationen"


def _extract_article_links(page) -> list[dict]:
    """Extract article links from the listing page."""
    links = page.evaluate("""
        () => {
            const results = [];
            // Look for links that point to /aktuellesinformationen/{id}
            const anchors = document.querySelectorAll('a[href*="/aktuellesinformationen/"]');
            for (const a of anchors) {
                const href = a.getAttribute('href');
                if (href && /\\/aktuellesinformationen\\/\\d+/.test(href)) {
                    const title = a.textContent.trim();
                    if (title) {
                        results.push({href, title});
                    }
                }
            }
            return results;
        }
    """)
    return links


def _extract_article_content(page) -> dict:
    """Extract the full content from an individual article page."""
    return page.evaluate("""
        () => {
            // Try common content selectors used by i-CMS/CityWeb
            const selectors = [
                '.mod-newsdetail',
                '.mod-detail',
                'article',
                '.content-main',
                '.mod-content',
                '[class*="detail"]',
                'main',
            ];

            let contentEl = null;
            for (const sel of selectors) {
                contentEl = document.querySelector(sel);
                if (contentEl && contentEl.textContent.trim().length > 50) break;
                contentEl = null;
            }

            if (!contentEl) {
                // Fallback: grab the largest text block on the page
                const allDivs = document.querySelectorAll('div');
                let maxLen = 0;
                for (const d of allDivs) {
                    const text = d.textContent.trim();
                    if (text.length > maxLen && text.length < 50000) {
                        maxLen = text.length;
                        contentEl = d;
                    }
                }
            }

            const text = contentEl ? contentEl.innerText.trim() : document.body.innerText.trim();

            // Try to find a date
            let date = null;
            const dateEl = document.querySelector('.date, .published, time, [class*="date"]');
            if (dateEl) {
                date = dateEl.textContent.trim();
            }

            // Try to find the title
            let title = '';
            const h1 = document.querySelector('h1');
            if (h1) {
                title = h1.textContent.trim();
            }

            return {title, text, date};
        }
    """)


def _source_id_from_url(url: str) -> str | None:
    """Extract the numeric article ID from the URL."""
    match = re.search(r"/aktuellesinformationen/(\d+)", url)
    return match.group(1) if match else None


def scrape_news() -> int:
    """Scrape the Uster news page and store new articles. Returns count of new articles."""
    new_count = 0
    logger.info("Starting scrape of %s", LISTING_URL)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            page.goto(LISTING_URL, wait_until="networkidle", timeout=30000)
            # Wait for dynamic content to load
            page.wait_for_timeout(3000)
        except PlaywrightTimeout:
            logger.warning("Timeout loading listing page, proceeding with partial content")

        article_links = _extract_article_links(page)
        logger.info("Found %d article links", len(article_links))

        # Deduplicate by href
        seen = set()
        unique_links = []
        for link in article_links:
            if link["href"] not in seen:
                seen.add(link["href"])
                unique_links.append(link)

        for link in unique_links:
            href = link["href"]
            full_url = href if href.startswith("http") else BASE_URL + href
            source_id = _source_id_from_url(full_url)

            if not source_id:
                continue

            if article_exists(source_id):
                logger.debug("Article %s already exists, skipping", source_id)
                continue

            logger.info("Fetching article %s: %s", source_id, link["title"][:60])

            try:
                page.goto(full_url, wait_until="networkidle", timeout=20000)
                page.wait_for_timeout(2000)
                content = _extract_article_content(page)

                title = content.get("title") or link.get("title", "Untitled")
                text = content.get("text", "")
                date = content.get("date")

                if len(text) < 20:
                    logger.warning("Article %s has very little text, skipping", source_id)
                    continue

                insert_article(source_id, full_url, title, text, date)
                new_count += 1
                logger.info("Saved article %s: %s", source_id, title[:60])

            except PlaywrightTimeout:
                logger.warning("Timeout fetching article %s", source_id)
            except Exception:
                logger.exception("Error fetching article %s", source_id)

        browser.close()

    logger.info("Scrape complete. %d new articles saved.", new_count)
    return new_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from database import init_db
    init_db()
    scrape_news()
