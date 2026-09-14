"""Summarize articles using Claude API (in German), with a local llama.cpp fallback."""

import json
import logging
import os

import anthropic
import requests
from dotenv import load_dotenv

from database import get_unsummarized_articles, save_summary

load_dotenv()
logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-20250514"

# Fallback used when the Claude API is unavailable (no key, outage, rate limit, ...).
# Set LLAMA_CPP_URL to "" to disable the fallback entirely.
DEFAULT_LLAMA_CPP_URL = "http://100.64.0.1:11435"
LLAMA_TIMEOUT = 300

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


def _llama_cpp_url() -> str:
    """Base URL of the local llama.cpp server, or "" when the fallback is disabled."""
    url = os.getenv("LLAMA_CPP_URL", DEFAULT_LLAMA_CPP_URL)
    return url.strip().rstrip("/")


def _build_prompt(article: dict) -> tuple[str, str, int]:
    """Return (system_prompt, user_content, max_tokens) for an article."""
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

    user_content = (
        f"Analysiere und fasse diese Medienmitteilung zusammen:\n\n"
        f"Titel: {article['title']}\n\n{text}"
    )
    return system_prompt, user_content, max_tokens


def _summarize_with_claude(client, system_prompt: str, user_content: str, max_tokens: int) -> str:
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    return response.content[0].text


def _summarize_with_llama(base_url: str, system_prompt: str, user_content: str, max_tokens: int) -> str:
    """Call the local llama.cpp server via its OpenAI-compatible chat endpoint.

    `enable_thinking: false` matters: the served model may be a reasoning model, and with
    thinking on it spends the whole token budget on `reasoning_content` while `content`
    comes back empty. Local models are also wordier, hence the doubled token budget.
    """
    response = requests.post(
        f"{base_url}/v1/chat/completions",
        json={
            "model": os.getenv("LLAMA_CPP_MODEL", "local"),
            "max_tokens": max_tokens * 2,
            "temperature": 0.2,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        },
        timeout=LLAMA_TIMEOUT,
    )
    response.raise_for_status()
    choice = response.json()["choices"][0]
    content = (choice["message"].get("content") or "").strip()
    if not content:
        # Never save an empty summary — raise so the article is retried on the next run.
        raise RuntimeError(f"llama.cpp returned empty content (finish_reason={choice.get('finish_reason')})")
    return content


def summarize_articles() -> int:
    """Summarize all unsummarized articles. Returns count of newly summarized articles.

    Uses the Claude API; if it is unavailable (missing key or failing request), falls
    back to the local llama.cpp server at LLAMA_CPP_URL.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    fallback_url = _llama_cpp_url()

    client = anthropic.Anthropic(api_key=api_key) if api_key else None
    if client is None:
        if not fallback_url:
            logger.error("ANTHROPIC_API_KEY not set and no llama.cpp fallback. Skipping summarization.")
            return 0
        logger.warning("ANTHROPIC_API_KEY not set. Using llama.cpp fallback at %s", fallback_url)

    articles = get_unsummarized_articles()
    logger.info("Found %d articles to summarize", len(articles))
    count = 0

    for article in articles:
        system_prompt, user_content, max_tokens = _build_prompt(article)

        try:
            if client is not None:
                try:
                    raw = _summarize_with_claude(client, system_prompt, user_content, max_tokens)
                except Exception:
                    if not fallback_url:
                        raise
                    logger.warning(
                        "Claude API failed for article %d, falling back to llama.cpp at %s",
                        article["id"], fallback_url, exc_info=True,
                    )
                    raw = _summarize_with_llama(fallback_url, system_prompt, user_content, max_tokens)
            else:
                raw = _summarize_with_llama(fallback_url, system_prompt, user_content, max_tokens)

            parsed = _parse_structured_response(raw)
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
