"""Scraper for Stadt Uster Medienmitteilungen.

The page at https://www.uster.ch/aktuellesinformationen loads news articles
dynamically via JavaScript (i-CMS/CityWeb platform). We use Playwright to
render the page and extract article links, then visit each article page to
get the full text.
"""

import logging
import re

import fitz  # pymupdf
import requests
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
            const anchors = document.querySelectorAll('a[href*="/_rte/information/"]');
            for (const a of anchors) {
                const href = a.getAttribute('href');
                if (href && /\\/_rte\\/information\\/\\d+/.test(href)) {
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
                '.box2',
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
    match = re.search(r"/_rte/information/(\d+)", url)
    return match.group(1) if match else None


def _is_stadtratsbeschluesse(title: str) -> bool:
    """Check if an article is a Stadtratsbeschlüsse listing."""
    return title.lower().startswith("stadtratsbeschlüsse der sitzung")


def _extract_beschluesse_links(page) -> list[str]:
    """Extract links to /beschluessestadtrat/ pages from the current page."""
    links = page.evaluate("""
        () => {
            const results = [];
            const anchors = document.querySelectorAll('a[href*="/beschluessestadtrat/"]');
            for (const a of anchors) {
                const href = a.getAttribute('href');
                if (href) results.push(href);
            }
            return [...new Set(results)];
        }
    """)
    return links


def _extract_traktanden(page) -> list[dict]:
    """Extract Traktanden items from a Beschlüsse page.

    Each item has 'title', 'description', and 'pdf_url' keys.
    Falls back to returning the full page text as a single item if
    structured extraction fails.
    """
    items = page.evaluate("""
        () => {
            const items = [];
            // Find the Traktanden heading
            const headings = document.querySelectorAll('h2, h3');
            let traktandenSection = null;
            for (const h of headings) {
                if (h.textContent.trim().toLowerCase().includes('traktand')) {
                    traktandenSection = h;
                    break;
                }
            }

            if (traktandenSection) {
                // Walk siblings after the heading, collecting items
                let el = traktandenSection.nextElementSibling;
                while (el) {
                    // Stop at the next major heading
                    if (el.tagName === 'H2') break;

                    const text = el.innerText ? el.innerText.trim() : '';
                    if (text.length > 5) {
                        // Look for PDF links in this element
                        let pdfUrl = null;
                        const pdfLink = el.querySelector('a[href*="/_doc/"]') || el.querySelector('a[href$=".pdf"]');
                        if (pdfLink) {
                            pdfUrl = pdfLink.getAttribute('href');
                        }

                        // Try to split into title and description
                        const lines = text.split('\\n').map(l => l.trim()).filter(l => l);
                        const title = lines[0] || text;
                        const description = lines.slice(1).join(' ');

                        items.push({title, description, pdf_url: pdfUrl});
                    }
                    el = el.nextElementSibling;
                }
            }

            // Fallback: if no structured items found, look for any list items
            if (items.length === 0) {
                const listItems = document.querySelectorAll('li');
                for (const li of listItems) {
                    const text = li.innerText ? li.innerText.trim() : '';
                    if (text.length > 10) {
                        let pdfUrl = null;
                        const pdfLink = li.querySelector('a[href*="/_doc/"]') || li.querySelector('a[href$=".pdf"]');
                        if (pdfLink) pdfUrl = pdfLink.getAttribute('href');
                        items.push({title: text, description: '', pdf_url: pdfUrl});
                    }
                }
            }

            return items;
        }
    """)
    return items


def _extract_pdf_text(url: str) -> str:
    """Download a PDF and extract its text content. Returns empty string on failure."""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        doc = fitz.open(stream=resp.content, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text.strip()
    except Exception:
        logger.warning("Failed to extract PDF from %s", url, exc_info=True)
        return ""


def _enrich_stadtratsbeschluesse(page, original_text: str) -> str:
    """Follow Beschlüsse links, extract Traktanden and PDF content.

    Returns enriched text with structured markers for each Traktandum.
    """
    beschluesse_links = _extract_beschluesse_links(page)
    if not beschluesse_links:
        logger.info("No beschluesse links found, keeping original text")
        return original_text

    sections = [original_text, "\n\n--- Stadtratsbeschlüsse Detail ---\n"]
    traktandum_num = 0

    for link in beschluesse_links:
        full_url = link if link.startswith("http") else BASE_URL + link
        logger.info("Following beschluesse link: %s", full_url)

        try:
            page.goto(full_url, wait_until="networkidle", timeout=20000)
            page.wait_for_timeout(2000)
        except PlaywrightTimeout:
            logger.warning("Timeout loading beschluesse page %s", full_url)
            continue
        except Exception:
            logger.warning("Error loading beschluesse page %s", full_url, exc_info=True)
            continue

        traktanden = _extract_traktanden(page)

        if not traktanden:
            # Fallback: grab whatever text is on the page
            fallback_text = page.evaluate("() => document.body.innerText.trim()")
            if fallback_text:
                traktandum_num += 1
                sections.append(f"\n### Traktandum {traktandum_num}: (Unstrukturiert)\n{fallback_text}")
            continue

        for item in traktanden:
            traktandum_num += 1
            title = item.get("title", "Ohne Titel")
            description = item.get("description", "")
            pdf_url = item.get("pdf_url")

            section_parts = [f"\n### Traktandum {traktandum_num}: {title}"]
            if description:
                section_parts.append(description)

            if pdf_url:
                pdf_full_url = pdf_url if pdf_url.startswith("http") else BASE_URL + pdf_url
                pdf_text = _extract_pdf_text(pdf_full_url)
                if pdf_text:
                    section_parts.append(f"\n[PDF-Inhalt]\n{pdf_text}")

            sections.append("\n".join(section_parts))

    if traktandum_num == 0:
        return original_text

    return "\n".join(sections)


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

                if _is_stadtratsbeschluesse(title):
                    logger.info("Detected Stadtratsbeschlüsse article, enriching: %s", title[:60])
                    text = _enrich_stadtratsbeschluesse(page, text)

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
