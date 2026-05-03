#!/usr/bin/env python3
"""
Scrape "The Legendary Mechanic" from novelhi.com,
translate to pt-BR using Google Translate (free), and build an EPUB.

Usage:
    python scrape_translate_epub.py [--start CHAPTER] [--end CHAPTER] [--delay SECONDS]

Resumes from checkpoint automatically if interrupted.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from ebooklib import epub

BASE_URL = "https://novelhi.com/novel/fantasy/the-legendary-mechanic"
CHECKPOINT_FILE = "checkpoint.json"
CHAPTERS_DIR = "chapters"
TRANSLATED_DIR = "translated"
OUTPUT_EPUB = "o-mecanico-lendario.epub"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
}

MAX_TRANSLATE_CHARS = 4500  # Google Translate free limit ~5000, leave margin


def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {"last_scraped": 0, "last_translated": 0}


def save_checkpoint(data):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(data, f)


def scrape_chapter(chapter_num: int, session: requests.Session, max_retries: int = 3) -> dict | None:
    url = f"{BASE_URL}/{chapter_num}"
    for attempt in range(max_retries):
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                print(f" [retry {attempt+1}/{max_retries-1}, wait {wait}s]", end="", flush=True)
                time.sleep(wait)
                continue
            print(f" [!] Failed after {max_retries} attempts: {e}")
            return None

    soup = BeautifulSoup(resp.text, "lxml")

    title_el = soup.select_one("h1.readTitle, .read-title h1, h1")
    title = title_el.get_text(strip=True) if title_el else f"Chapter {chapter_num}"

    reading_div = soup.find("div", id="showReading")
    if not reading_div:
        print(f"  [!] No content found for chapter {chapter_num}")
        return None

    sentences = reading_div.find_all("sent")
    if not sentences:
        text = reading_div.get_text(separator="\n", strip=True)
    else:
        paragraphs = []
        current_para = []
        for sent in sentences:
            current_para.append(sent.get_text(strip=True))
            next_sib = sent.next_sibling
            if next_sib and isinstance(next_sib, str) and next_sib.strip() == "":
                next_sib = next_sib.next_sibling if hasattr(next_sib, "next_sibling") else None
            if next_sib and getattr(next_sib, "name", None) == "br":
                paragraphs.append(" ".join(current_para))
                current_para = []
        if current_para:
            paragraphs.append(" ".join(current_para))
        text = "\n\n".join(paragraphs)

    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return {"chapter_num": chapter_num, "title": title, "text": text}


def translate_text(text: str, translator: GoogleTranslator) -> str:
    if not text.strip():
        return text

    paragraphs = text.split("\n\n")
    translated_paragraphs = []

    def _translate_chunk(chunk: str) -> str:
        for attempt in range(3):
            try:
                result = translator.translate(chunk)
                if result:
                    return result
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                print(f"    [!] Translation failed after 3 attempts: {e}")
            return chunk
        return chunk

    for para in paragraphs:
        if len(para) <= MAX_TRANSLATE_CHARS:
            translated_paragraphs.append(_translate_chunk(para))
        else:
            sentences = re.split(r"(?<=[.!?])\s+", para)
            chunks = []
            current_chunk = ""
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 1 > MAX_TRANSLATE_CHARS:
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = sentence
                else:
                    current_chunk = f"{current_chunk} {sentence}".strip()
            if current_chunk:
                chunks.append(current_chunk)

            translated_chunks = [_translate_chunk(c) for c in chunks]
            translated_paragraphs.append(" ".join(translated_chunks))

    return "\n\n".join(translated_paragraphs)


def translate_title(title: str, translator: GoogleTranslator) -> str:
    try:
        result = translator.translate(title)
        return result if result else title
    except Exception:
        return title


def format_eta(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"


def progress_line(current: int, total: int, start_time: float, label: str) -> str:
    done = current - 1
    if done <= 0:
        return f"[{label}] {current}/{total}"
    elapsed = time.time() - start_time
    avg = elapsed / done
    remaining = avg * (total - current + 1)
    pct = (done / total) * 100
    bar_width = 20
    filled = int(bar_width * done / total)
    bar = "█" * filled + "░" * (bar_width - filled)
    return f"[{bar}] {pct:5.1f}% | {current}/{total} | ETA {format_eta(remaining)} | {avg:.1f}s/ch"


def scrape_all(start: int, end: int, delay: float):
    os.makedirs(CHAPTERS_DIR, exist_ok=True)
    checkpoint = load_checkpoint()
    resume_from = max(checkpoint["last_scraped"] + 1, start)
    total = end - start + 1

    if resume_from > start:
        print(f"Resuming scraping from chapter {resume_from}")

    session = requests.Session()
    consecutive_failures = 0
    step_start = time.time()
    done_count = 0

    for ch in range(resume_from, end + 1):
        chapter_file = os.path.join(CHAPTERS_DIR, f"{ch:04d}.json")
        if os.path.exists(chapter_file):
            checkpoint["last_scraped"] = ch
            save_checkpoint(checkpoint)
            done_count += 1
            continue

        done_count += 1
        print(f"\r{progress_line(done_count, total, step_start, 'Scraping')} | ch.{ch}...", end="", flush=True)
        data = scrape_chapter(ch, session)

        if data is None:
            consecutive_failures += 1
            print(f"\r{progress_line(done_count, total, step_start, 'Scraping')} | ch.{ch} FAILED")
            if consecutive_failures >= 5:
                print(f"\n5 consecutive failures at chapter {ch}. Stopping scrape.")
                break
            time.sleep(delay)
            continue

        consecutive_failures = 0
        with open(chapter_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        checkpoint["last_scraped"] = ch
        save_checkpoint(checkpoint)
        word_count = len(data["text"].split())
        print(f"\r{progress_line(done_count, total, step_start, 'Scraping')} | ch.{ch} OK ({word_count}w)")
        time.sleep(delay)

    elapsed = time.time() - step_start
    print(f"\nScraping complete. Last chapter: {checkpoint['last_scraped']} ({format_eta(elapsed)} elapsed)")


def translate_all(start: int, end: int, delay: float):
    os.makedirs(TRANSLATED_DIR, exist_ok=True)
    checkpoint = load_checkpoint()
    resume_from = max(checkpoint["last_translated"] + 1, start)
    total = end - start + 1

    if resume_from > start:
        print(f"Resuming translation from chapter {resume_from}")

    translator = GoogleTranslator(source="en", target="pt")
    step_start = time.time()
    done_count = 0

    for ch in range(resume_from, end + 1):
        source_file = os.path.join(CHAPTERS_DIR, f"{ch:04d}.json")
        translated_file = os.path.join(TRANSLATED_DIR, f"{ch:04d}.json")

        if os.path.exists(translated_file):
            checkpoint["last_translated"] = ch
            save_checkpoint(checkpoint)
            done_count += 1
            continue

        if not os.path.exists(source_file):
            done_count += 1
            print(f"\r{progress_line(done_count, total, step_start, 'Translating')} | ch.{ch} SKIPPED (not scraped)")
            continue

        done_count += 1
        with open(source_file, encoding="utf-8") as f:
            data = json.load(f)

        print(f"\r{progress_line(done_count, total, step_start, 'Translating')} | ch.{ch}...", end="", flush=True)

        translated_title = translate_title(data["title"], translator)
        translated_text = translate_text(data["text"], translator)

        translated_data = {
            "chapter_num": data["chapter_num"],
            "title_original": data["title"],
            "title": translated_title,
            "text": translated_text,
        }

        with open(translated_file, "w", encoding="utf-8") as f:
            json.dump(translated_data, f, ensure_ascii=False, indent=2)

        checkpoint["last_translated"] = ch
        save_checkpoint(checkpoint)
        print(f"\r{progress_line(done_count, total, step_start, 'Translating')} | ch.{ch} OK")
        time.sleep(delay)

    elapsed = time.time() - step_start
    print(f"\nTranslation complete. Last chapter: {checkpoint['last_translated']} ({format_eta(elapsed)} elapsed)")


def build_epub(start: int, end: int):
    book = epub.EpubBook()
    book.set_identifier("the-legendary-mechanic-ptbr")
    book.set_title("O Mecânico Lendário")
    book.set_language("pt-BR")
    book.add_author("Qi Peijia (齐佩甲)")

    style = """
    body { font-family: Georgia, serif; line-height: 1.6; margin: 1em; }
    h1 { font-size: 1.4em; margin-bottom: 0.5em; }
    p { text-indent: 1.5em; margin: 0.3em 0; }
    """
    css = epub.EpubItem(
        uid="style", file_name="style/default.css",
        media_type="text/css", content=style.encode("utf-8"),
    )
    book.add_item(css)

    chapters = []
    spine = ["nav"]
    toc = []

    for ch in range(start, end + 1):
        translated_file = os.path.join(TRANSLATED_DIR, f"{ch:04d}.json")
        if not os.path.exists(translated_file):
            continue

        with open(translated_file, encoding="utf-8") as f:
            data = json.load(f)

        paragraphs_html = "".join(
            f"<p>{p.strip()}</p>" for p in data["text"].split("\n\n") if p.strip()
        )

        chapter_content = f"""<?xml version='1.0' encoding='utf-8'?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{data['title']}</title>
<link rel="stylesheet" type="text/css" href="../style/default.css"/></head>
<body>
<h1>Capítulo {ch} — {data['title']}</h1>
{paragraphs_html}
</body></html>"""

        epub_chapter = epub.EpubHtml(
            title=f"Capítulo {ch} — {data['title']}",
            file_name=f"chapter_{ch:04d}.xhtml",
            lang="pt-BR",
        )
        epub_chapter.set_content(chapter_content.encode("utf-8"))
        book.add_item(epub_chapter)
        chapters.append(epub_chapter)
        spine.append(epub_chapter)
        toc.append(epub.Link(f"chapter_{ch:04d}.xhtml", f"Cap. {ch} — {data['title']}", f"ch{ch}"))

    book.toc = toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine

    epub.write_epub(OUTPUT_EPUB, book, {})
    print(f"\nEPUB created: {OUTPUT_EPUB} ({len(chapters)} chapters)")


def find_gaps(start: int, end: int):
    missing_scraped = []
    missing_translated = []
    for ch in range(start, end + 1):
        if not os.path.exists(os.path.join(CHAPTERS_DIR, f"{ch:04d}.json")):
            missing_scraped.append(ch)
        elif not os.path.exists(os.path.join(TRANSLATED_DIR, f"{ch:04d}.json")):
            missing_translated.append(ch)
    return missing_scraped, missing_translated


def retry_gaps(start: int, end: int, delay: float):
    missing_scraped, missing_translated = find_gaps(start, end)

    if not missing_scraped and not missing_translated:
        print("No gaps found! All chapters scraped and translated.")
        return

    if missing_scraped:
        print(f"Found {len(missing_scraped)} chapters not scraped: {missing_scraped[:10]}{'...' if len(missing_scraped) > 10 else ''}")
        session = requests.Session()
        for i, ch in enumerate(missing_scraped):
            print(f"  Retrying scrape {i+1}/{len(missing_scraped)} — ch.{ch}...", end=" ", flush=True)
            data = scrape_chapter(ch, session)
            if data:
                with open(os.path.join(CHAPTERS_DIR, f"{ch:04d}.json"), "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print("OK")
            else:
                print("FAILED")
            time.sleep(delay)

    missing_scraped, missing_translated = find_gaps(start, end)

    if missing_translated:
        print(f"Found {len(missing_translated)} chapters not translated: {missing_translated[:10]}{'...' if len(missing_translated) > 10 else ''}")
        translator = GoogleTranslator(source="en", target="pt")
        for i, ch in enumerate(missing_translated):
            source_file = os.path.join(CHAPTERS_DIR, f"{ch:04d}.json")
            if not os.path.exists(source_file):
                continue
            with open(source_file, encoding="utf-8") as f:
                data = json.load(f)
            print(f"  Retrying translate {i+1}/{len(missing_translated)} — ch.{ch}...", end=" ", flush=True)
            translated_title = translate_title(data["title"], translator)
            translated_text = translate_text(data["text"], translator)
            translated_data = {
                "chapter_num": data["chapter_num"],
                "title_original": data["title"],
                "title": translated_title,
                "text": translated_text,
            }
            with open(os.path.join(TRANSLATED_DIR, f"{ch:04d}.json"), "w", encoding="utf-8") as f:
                json.dump(translated_data, f, ensure_ascii=False, indent=2)
            print("OK")
            time.sleep(delay)

    missing_scraped, missing_translated = find_gaps(start, end)
    total_missing = len(missing_scraped) + len(missing_translated)
    if total_missing:
        print(f"\nStill {total_missing} gaps remaining after retry.")
    else:
        print("\nAll gaps filled!")


def main():
    parser = argparse.ArgumentParser(description="Scrape, translate, and build EPUB")
    parser.add_argument("--start", type=int, default=1, help="First chapter (default: 1)")
    parser.add_argument("--end", type=int, default=1490, help="Last chapter (default: 1490)")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between requests in seconds (default: 2)")
    parser.add_argument("--step", choices=["scrape", "translate", "epub", "retry", "status", "all"], default="all",
                        help="Run a specific step (default: all)")
    args = parser.parse_args()

    print(f"=== The Legendary Mechanic → O Mecânico Lendário ===")
    print(f"Chapters {args.start}-{args.end}, delay {args.delay}s\n")

    if args.step == "status":
        missing_scraped, missing_translated = find_gaps(args.start, args.end)
        total = args.end - args.start + 1
        scraped = total - len(missing_scraped)
        translated = total - len(missing_scraped) - len(missing_translated)
        print(f"Scraped:    {scraped}/{total}")
        print(f"Translated: {translated}/{total}")
        if missing_scraped:
            print(f"Missing scrape:    {missing_scraped[:20]}{'...' if len(missing_scraped) > 20 else ''}")
        if missing_translated:
            print(f"Missing translate:  {missing_translated[:20]}{'...' if len(missing_translated) > 20 else ''}")
        return

    if args.step == "retry":
        retry_gaps(args.start, args.end, args.delay)
        return

    if args.step in ("scrape", "all"):
        print("--- STEP 1: Scraping ---")
        scrape_all(args.start, args.end, args.delay)

    if args.step in ("translate", "all"):
        print("\n--- STEP 2: Translating to pt-BR ---")
        translate_all(args.start, args.end, args.delay)

    if args.step in ("epub", "all"):
        print("\n--- STEP 3: Building EPUB ---")
        build_epub(args.start, args.end)


if __name__ == "__main__":
    main()
