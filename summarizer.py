"""Summarize articles using Claude API (in German)."""

import logging
import os

import anthropic
from dotenv import load_dotenv

from database import get_unsummarized_articles, save_summary

load_dotenv()
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Du bist ein Assistent, der Medienmitteilungen der Stadt Uster zusammenfasst. "
    "Fasse den folgenden Text in 2-4 Sätzen auf Deutsch zusammen. "
    "Behalte die wichtigsten Fakten, Daten und Namen bei. "
    "Schreibe sachlich und prägnant."
)


def summarize_articles() -> int:
    """Summarize all unsummarized articles. Returns count of newly summarized articles."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set. Skipping summarization.")
        return 0

    client = anthropic.Anthropic(api_key=api_key)
    articles = get_unsummarized_articles()
    logger.info("Found %d articles to summarize", len(articles))
    count = 0

    for article in articles:
        text = article["original_text"]
        # Truncate very long texts to stay within token limits
        if len(text) > 15000:
            text = text[:15000] + "\n\n[Text gekürzt]"

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": f"Bitte fasse diese Medienmitteilung zusammen:\n\nTitel: {article['title']}\n\n{text}",
                    }
                ],
            )
            summary = response.content[0].text
            save_summary(article["id"], summary)
            count += 1
            logger.info("Summarized article %d: %s", article["id"], article["title"][:60])
        except Exception:
            logger.exception("Error summarizing article %d", article["id"])

    logger.info("Summarization complete. %d articles summarized.", count)
    return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from database import init_db
    init_db()
    summarize_articles()
