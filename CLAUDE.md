# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Scrapes news articles from uster.ch/aktuellesinformationen daily, summarizes each article in German using the Claude API, and displays them in a Flask web feed. The UI and all summarization prompts are in German.

## Package Management

Uses **uv** with a `.venv/` virtual environment. Always use `uv run` to execute commands.

## Commands

```bash
# Setup (Python 3.12)
uv venv
uv pip install -r requirements.txt
uv run playwright install chromium

# Run the app (serves on http://localhost:5001)
uv run python app.py

# Run all tests
uv run pytest tests/ -v

# Run a single test file or test
uv run pytest tests/test_database.py -v
uv run pytest tests/test_database.py::test_insert_and_exists -v
```

## Architecture

Four-module pipeline, all pure Python with SQLite storage:

- **`scraper.py`** — Playwright-based scraper. Loads the JS-rendered uster.ch listing page, extracts article links matching `/aktuellesinformationen/{id}`, visits each article page, and extracts content via JS DOM evaluation (tries several CSS selectors for i-CMS/CityWeb). Articles are deduplicated by `source_id` (the numeric ID from the URL). **Stadtratsbeschlüsse detection:** articles with titles starting "Stadtratsbeschlüsse der Sitzung" are enriched by following `/beschluessestadtrat/` links, extracting Traktanden items, and downloading linked PDFs (via `pymupdf`/`fitz`) to include their text content.

- **`summarizer.py`** — Sends unsummarized articles to Claude (`claude-sonnet-4-20250514`) with a German-language system prompt. Truncates articles >15k chars. Stores summaries back to the DB. **Stadtratsbeschlüsse** articles use a specialized prompt (`STADTRAT_SYSTEM_PROMPT`) that produces per-Traktandum summaries with individual relevancy scores, stored as `traktanden_json`. Uses higher limits: 40k char truncation and 2000 max_tokens. **Fallback:** if the Claude call raises (or `ANTHROPIC_API_KEY` is missing), the same prompt is sent to a local llama.cpp server at `LLAMA_CPP_URL` (default `http://100.64.0.1:11435`) via its OpenAI-compatible `/v1/chat/completions` endpoint, using plain `requests`. The request sends `chat_template_kwargs: {"enable_thinking": false}` and doubles `max_tokens` — the local server may serve a reasoning model, which otherwise spends the entire budget on `reasoning_content` and returns empty `content`. Empty content raises rather than saving a blank summary. Setting `LLAMA_CPP_URL=""` disables the fallback; the test suite disables it via an autouse `conftest.py` fixture so tests never hit the network.

- **`database.py`** — SQLite layer. DB lives at `data/news.db` (overridable via `NEWS_DB_PATH` env var). Single `articles` table; deduplication via `source_id UNIQUE`. Includes auto-migration for `traktanden_json TEXT` column.

- **`app.py`** — Flask server with two routes: `/` (feed display) and `/fetch` (triggers scrape+summarize in a background thread). APScheduler runs the pipeline daily at 07:00. A threading lock prevents concurrent runs.

- **`templates/feed.html`** — Single Jinja2 template, inline CSS, no JS framework.

## Testing

Tests use pytest with a `conftest.py` fixture that monkeypatches `database.DB_PATH` to a temp file for every test (autouse). No real network or API calls in tests — scraper/summarizer tests should mock external dependencies.

## Environment

Requires `ANTHROPIC_API_KEY` in `.env` (loaded via python-dotenv). Optional: `LLAMA_CPP_URL` / `LLAMA_CPP_MODEL` for the local fallback, `NEWS_DB_PATH` for the DB location. See `.env.example`.
