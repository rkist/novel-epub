# Novel to EPUB (pt-BR)

Scrapes novels from novelhi.com, translates to any language via Google Translate (free, no API key), and builds an EPUB for Kindle.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install deep-translator ebooklib beautifulsoup4 requests lxml
```

## Usage

### Full pipeline (scrape → translate → epub)

```bash
python scrape_translate_epub.py \
  --url https://novelhi.com/novel/fantasy/the-legendary-mechanic \
  --novel the-legendary-mechanic \
  --title "O Mecânico Lendário" \
  --author "Qi Peijia" \
  --end 1490
```

### Another novel example

```bash
python scrape_translate_epub.py \
  --url https://novelhi.com/novel/fantasy/some-other-novel \
  --novel some-other-novel \
  --title "Outro Título" \
  --author "Author Name" \
  --end 800 \
  --target-lang pt
```

### Individual steps

```bash
# Scrape only
python scrape_translate_epub.py --url ... --novel ... --title ... --end N --step scrape

# Translate only (requires scraped chapters)
python scrape_translate_epub.py --url ... --novel ... --title ... --end N --step translate

# Build EPUB only (requires translated chapters)
python scrape_translate_epub.py --url ... --novel ... --title ... --end N --step epub

# Check progress and gaps
python scrape_translate_epub.py --url ... --novel ... --title ... --end N --step status

# Retry failed chapters
python scrape_translate_epub.py --url ... --novel ... --title ... --end N --step retry
```

### All options

| Flag | Required | Default | Description |
|---|---|---|---|
| `--url` | yes | — | Base novel URL on novelhi.com |
| `--novel` | yes | — | Slug used as folder name (e.g. `the-legendary-mechanic`) |
| `--title` | yes | — | EPUB title in target language |
| `--author` | no | `Unknown` | Author name for the EPUB |
| `--start` | no | `1` | First chapter number |
| `--end` | yes | — | Last chapter number |
| `--delay` | no | `2.0` | Seconds between requests |
| `--source-lang` | no | `en` | Source language code |
| `--target-lang` | no | `pt` | Target language code |
| `--step` | no | `all` | `scrape`, `translate`, `epub`, `status`, `retry`, or `all` |

## Data layout

Each novel gets its own subdirectory:

```
novels/
  the-legendary-mechanic/
    chapters/       # raw scraped JSON (one per chapter)
    translated/     # translated JSON (one per chapter)
    checkpoint.json # progress tracker
    o-mecanico-lendario.epub  # final output
```

## How it works

1. **Scrape** — fetches each chapter page, extracts text from `<sent>` tags inside `#showReading`
2. **Translate** — sends text to Google Translate (free) via `deep-translator`, chunking at 4500 chars to stay within limits
3. **Build EPUB** — assembles translated chapters with table of contents

## Resilience

- **Checkpoint** (`checkpoint.json`) tracks progress — safe to interrupt and resume
- **Retries** — scraping (3 attempts, exponential backoff) and translation (3 attempts per chunk)
- **Gap detection** — `--step status` shows missing chapters, `--step retry` re-attempts them
- **Graceful degradation** — if translation fails after retries, keeps the original text

## Time estimate

~1490 chapters. Scraping ~2-3 hours. Translation can take 25-50 hours due to Google Translate rate limits (no cost though). Run scrape and translate as separate steps if needed.
