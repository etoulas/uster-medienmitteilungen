"""Summarize articles using Claude API (in German)."""

import json
import logging
import os

import anthropic
from dotenv import load_dotenv

from database import get_unsummarized_articles, save_summary

load_dotenv()
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Du bist ein Assistent, der Medienmitteilungen der Stadt Uster analysiert und zusammenfasst.

Antworte ausschliesslich mit einem JSON-Objekt (ohne Markdown-Codeblock) mit diesen Feldern:

{
  "tldr": "Ein einzelner, sehr kurzer Satz (max 15 Wörter) als Kernaussage.",
  "relevancy": 3,
  "summary": "Zusammenfassung in 2-4 Sätzen. Sachlich und prägnant, mit den wichtigsten Fakten, Daten und Namen.",
  "background": "Kurze Erklärung oder Hintergrundinfo zu weniger bekannten Themen, Orten oder Institutionen (z.B. was ist die Kläui-Bibliothek, was ist der Stadtrat). Null falls nicht nötig."
}

Relevanz-Skala (1-5) — bewerte wie stark die Nachricht den Alltag der Ustermer Bevölkerung beeinflusst:
1 = Kaum relevant (interne Verwaltung, Protokollarisches)
2 = Wenig relevant (allgemeine Infos, Kulturhinweise)
3 = Mässig relevant (Veranstaltungen, kleinere Projekte)
4 = Relevant (Bauarbeiten, Verkehrsänderungen, Schulthemen)
5 = Sehr relevant (Notfälle, grosse Infrastrukturänderungen, Steuer-/Gebührenänderungen)

Schreibe auf Deutsch. Das "background"-Feld soll null sein (JSON null), wenn der Artikel keine erklärungsbedürftigen Begriffe enthält."""

STADTRAT_SYSTEM_PROMPT = """\
Du bist ein Assistent, der Stadtratsbeschlüsse der Stadt Uster analysiert und zusammenfasst.

Der Text enthält mehrere Traktanden (Geschäfte des Stadtrats), jeweils mit Titel und ggf. PDF-Inhalt.

Antworte ausschliesslich mit einem JSON-Objekt (ohne Markdown-Codeblock) mit diesen Feldern:

{
  "tldr": "Ein Satz, der die wichtigsten Beschlüsse dieser Sitzung zusammenfasst.",
  "relevancy": 3,
  "summary": "Überblick der Sitzung in 2-4 Sätzen.",
  "background": "Hintergrundinfos falls nötig, sonst null.",
  "traktanden": [
    {
      "nummer": 1,
      "titel": "Kurzer Titel des Traktandums",
      "tldr": "Kernaussage in einem Satz.",
      "zusammenfassung": "Zusammenfassung in 2-3 Sätzen.",
      "relevanz": 3
    }
  ]
}

Relevanz-Skala (1-5) — bewerte wie stark jedes Traktandum den Alltag der Ustermer Bevölkerung beeinflusst:
1 = Kaum relevant (interne Verwaltung, Protokollarisches)
2 = Wenig relevant (allgemeine Infos, Personalgeschäfte)
3 = Mässig relevant (kleinere Projekte, Kreditanträge)
4 = Relevant (Bauarbeiten, Verkehrsänderungen, Schulthemen)
5 = Sehr relevant (grosse Infrastrukturänderungen, Steuer-/Gebührenänderungen)

Die Gesamt-Relevanz ("relevancy") soll der höchsten Einzel-Relevanz der Traktanden entsprechen.

Schreibe auf Deutsch. Das "background"-Feld soll null sein (JSON null), wenn keine erklärungsbedürftigen Begriffe vorkommen."""


def _parse_structured_response(text: str) -> dict:
    """Parse the JSON response from Claude. Falls back to plain summary on error."""
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        data = json.loads(text)
        result = {
            "summary": data.get("summary", text),
            "tldr": data.get("tldr"),
            "relevancy": max(1, min(5, int(data["relevancy"]))) if data.get("relevancy") is not None else None,
            "background_info": data.get("background"),
            "traktanden_json": None,
        }
        if data.get("traktanden") and isinstance(data["traktanden"], list):
            result["traktanden_json"] = json.dumps(data["traktanden"], ensure_ascii=False)
        return result
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        logger.warning("Failed to parse structured response, using raw text as summary")
        return {"summary": text, "tldr": None, "relevancy": None, "background_info": None, "traktanden_json": None}


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
        is_stadtrat = article["title"].lower().startswith("stadtratsbeschlüsse der sitzung")

        if is_stadtrat:
            truncate_limit = 40000
            max_tokens = 2000
            system_prompt = STADTRAT_SYSTEM_PROMPT
        else:
            truncate_limit = 15000
            max_tokens = 800
            system_prompt = SYSTEM_PROMPT

        if len(text) > truncate_limit:
            text = text[:truncate_limit] + "\n\n[Text gekürzt]"

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": f"Analysiere und fasse diese Medienmitteilung zusammen:\n\nTitel: {article['title']}\n\n{text}",
                    }
                ],
            )
            parsed = _parse_structured_response(response.content[0].text)
            save_summary(
                article["id"],
                summary=parsed["summary"],
                tldr=parsed["tldr"],
                relevancy=parsed["relevancy"],
                background_info=parsed["background_info"],
                traktanden_json=parsed["traktanden_json"],
            )
            count += 1
            logger.info("Summarized article %d: %s (relevancy=%s)",
                        article["id"], article["title"][:60], parsed["relevancy"])
        except Exception:
            logger.exception("Error summarizing article %d", article["id"])

    logger.info("Summarization complete. %d articles summarized.", count)
    return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from database import init_db
    init_db()
    summarize_articles()
