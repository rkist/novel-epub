# Novel Translation to EPUB (pt-BR)

Scrapes "The Legendary Mechanic" from novelhi.com, translates to Brazilian Portuguese using Google Translate (free, no API key), and builds an EPUB for Kindle.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install deep-translator ebooklib beautifulsoup4 requests lxml
```

## Usage

### Full pipeline (scrape → translate → epub)

```bash
python scrape_translate_epub.py --start 1 --end 1490 --delay 2
```

### Individual steps

```bash
# Scrape only
python scrape_translate_epub.py --step scrape

# Translate only (requires scraped chapters)
python scrape_translate_epub.py --step translate

# Build EPUB only (requires translated chapters)
python scrape_translate_epub.py --step epub

# Check progress and gaps
python scrape_translate_epub.py --step status

# Retry any failed chapters
python scrape_translate_epub.py --step retry
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--start` | 1 | First chapter |
| `--end` | 1490 | Last chapter |
| `--delay` | 2.0 | Seconds between requests |
| `--step` | all | `scrape`, `translate`, `epub`, `status`, `retry`, or `all` |

## How it works

1. **Scrape** — fetches each chapter page, extracts text from `<sent>` tags inside `#showReading`
2. **Translate** — sends text to Google Translate (free) via `deep-translator`, chunking at 4500 chars to stay within limits
3. **Build EPUB** — assembles translated chapters into `o-mecanico-lendario.epub` with table of contents

## Resilience

- **Checkpoint file** (`checkpoint.json`) tracks progress — safe to interrupt and resume
- **Retries** — both scraping (3 attempts, exponential backoff) and translation (3 attempts per chunk) retry on failure
- **Gap detection** — `--step status` shows missing chapters, `--step retry` re-attempts them
- **Graceful degradation** — if translation fails after retries, keeps the original English text

## Output

```
chapters/       # raw scraped JSON (one per chapter)
translated/     # translated JSON (one per chapter)
checkpoint.json # progress tracker
o-mecanico-lendario.epub  # final EPUB
```

## Time estimate

~1490 chapters. Scraping takes ~2-3 hours. Translation takes significantly longer (~1-3 min per chapter due to Google Translate rate limits), potentially 25-50 hours total. Run scrape and translate as separate steps if needed.
