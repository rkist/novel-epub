# novel-epub

Scrapes novels from novelhi.com or centralnovel.com, translates to any language via Google Translate (free, no API key needed), and exports to EPUB for Kindle.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install deep-translator ebooklib beautifulsoup4 requests lxml
```

## Usage

```bash
python scrape_translate_epub.py \
  --url https://novelhi.com/novel/fantasy/the-legendary-mechanic \
  --novel the-legendary-mechanic \
  --title "O Mecânico Lendário" \
  --author "Qi Peijia" \
  --end 1490
```

This runs the full pipeline: scrape → translate → epub. Safe to interrupt and re-run — it resumes from where it left off.

## Options

| Flag | Required | Default | Description |
|---|---|---|---|
| `--url` | yes | — | Base novel URL on novelhi.com or centralnovel.com |
| `--novel` | yes | — | Slug used as the data folder name |
| `--title` | yes | — | EPUB title in the target language |
| `--author` | no | `Unknown` | Author name for the EPUB |
| `--start` | no | `1` | First chapter number |
| `--end` | yes | — | Last chapter number |
| `--delay` | no | `2.0` | Seconds between requests |
| `--source-lang` | no | `en` | Source language code |
| `--target-lang` | no | `pt` | Target language code. If it matches `--source-lang`, chapters are copied without translation. |
| `--step` | no | `all` | `scrape`, `translate`, `epub`, `status`, `retry`, or `all` |

## Steps

Run individual steps with `--step <name>`:

| Step | Description |
|---|---|
| `scrape` | Fetch chapter HTML and extract text |
| `translate` | Translate scraped chapters |
| `epub` | Build the EPUB from translated chapters |
| `status` | Show how many chapters are scraped/translated and list any gaps |
| `retry` | Re-attempt any failed scrapes or translations |
| `all` | Run scrape → translate → epub (default) |

## Data layout

Each novel gets its own folder under `novels/`:

```
novels/
  the-legendary-mechanic/
    chapters/         # raw scraped JSON, one file per chapter
    translated/       # translated JSON, one file per chapter
    checkpoint.json   # tracks scraping and translation progress
    o-mecanico-lendario.epub
```

## How it works

1. **Scrape** — fetches each chapter page and extracts text from `<sent>` tags inside `#showReading` on NovelHi, or `.epcontent.entry-content` on CentralNovel
2. **Translate** — sends paragraphs to Google Translate via `deep-translator`, chunking at 4500 chars to stay within the free-tier limit; retries up to 3 times with exponential backoff on failure; falls back to original text if all retries fail
3. **Build EPUB** — assembles translated chapters into a single EPUB with a table of contents

## Notes

- Google Translate is free but slow for large novels — expect scraping to take a few hours and translation significantly longer (roughly 1–3 min per chapter). Use `--step scrape` and `--step translate` as separate runs if needed.
- `--step status` is useful to check progress mid-run or after an interruption.
- `--step retry` re-scrapes and re-translates any chapters that were skipped or failed.
