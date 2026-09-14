# Uster Medienmitteilungen

Scrapes news from [uster.ch/aktuellesinformationen](https://www.uster.ch/aktuellesinformationen) once a day, summarizes each article in German using Claude, and displays the summaries in a web feed.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Create a `.env` file (see `.env.example`):

```
ANTHROPIC_API_KEY=your-api-key-here
```

If the Claude API is unavailable (missing key, outage, rate limit), summarization falls
back to a local llama.cpp server via its OpenAI-compatible `/v1/chat/completions`
endpoint. It defaults to `http://100.64.0.1:11435`; override with `LLAMA_CPP_URL`
(and `LLAMA_CPP_MODEL`), or set `LLAMA_CPP_URL=` to disable the fallback.

## Run

```bash
python app.py
```

Opens a web server at **http://localhost:5000**.

- The scheduler automatically fetches new articles every day at 07:00.
- Click **"Jetzt neue Artikel abrufen"** on the web page to trigger a manual fetch.

## How it works

1. **Scraper** (`scraper.py`): Uses Playwright to load the dynamically-rendered news listing page, extracts article links, visits each article page, and stores the full text in SQLite.
2. **Summarizer** (`summarizer.py`): Sends unsummarized articles to the Claude API with a German-language summarization prompt.
3. **Web app** (`app.py`): Flask server that displays all articles with their summaries, and runs a daily background scheduler via APScheduler.
4. **Database** (`database.py`): SQLite storage in `data/news.db` — articles are deduplicated by their source ID.

## Project structure

```
├── app.py              # Flask server + scheduler
├── scraper.py          # Playwright-based news scraper
├── summarizer.py       # Claude API summarization
├── database.py         # SQLite data layer
├── templates/
│   └── feed.html       # News feed template
├── requirements.txt
├── .env.example
└── .gitignore
```
