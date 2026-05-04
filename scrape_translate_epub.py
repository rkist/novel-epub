#!/usr/bin/env python3
"""
Scrape a novel from novelhi.com, translate to a target language, and build an EPUB.

Usage:
    python scrape_translate_epub.py \\
        --url https://novelhi.com/novel/fantasy/the-legendary-mechanic \\
        --novel the-legendary-mechanic \\
        --title "O Mecânico Lendário" \\
        --author "Qi Peijia" \\
        --end 1490

Data is stored under novels/<novel>/. Safe to interrupt and resume.
"""

import argparse
import json
import os
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from ebooklib import epub

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
}

MAX_TRANSLATE_CHARS = 4500


# --- Path helpers ---

def novel_dir(slug: str) -> Path:
    return Path("novels") / slug

def chapters_dir(slug: str) -> Path:
    return novel_dir(slug) / "chapters"

def translated_dir(slug: str) -> Path:
    return novel_dir(slug) / "translated"

def checkpoint_file(slug: str) -> Path:
    return novel_dir(slug) / "checkpoint.json"

def output_epub(slug: str, title: str) -> Path:
    safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "-").lower()
    return novel_dir(slug) / f"{safe_title}.epub"


# --- Checkpoint ---

def load_checkpoint(slug: str) -> dict:
    path = checkpoint_file(slug)
    if path.exists():
        return json.loads(path.read_text())
    return {"last_scraped": 0, "last_translated": 0}

def save_checkpoint(slug: str, data: dict):
    checkpoint_file(slug).write_text(json.dumps(data))


# --- Scraping ---

def scrape_chapter(chapter_num: int, base_url: str, session: requests.Session, max_retries: int = 3) -> dict | None:
    url = f"{base_url}/{chapter_num}"
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

    return {"chapter_num": chapter_num, "title": title, "text": re.sub(r"\n{3,}", "\n\n", text).strip()}


# --- Translation ---

def translate_text(text: str, translator: GoogleTranslator) -> str:
    if not text.strip():
        return text

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

    translated_paragraphs = []
    for para in text.split("\n\n"):
        if len(para) <= MAX_TRANSLATE_CHARS:
            translated_paragraphs.append(_translate_chunk(para))
        else:
            sentences = re.split(r"(?<=[.!?])\s+", para)
            chunks, current_chunk = [], ""
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 1 > MAX_TRANSLATE_CHARS:
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = sentence
                else:
                    current_chunk = f"{current_chunk} {sentence}".strip()
            if current_chunk:
                chunks.append(current_chunk)
            translated_paragraphs.append(" ".join(_translate_chunk(c) for c in chunks))

    return "\n\n".join(translated_paragraphs)


def translate_title(title: str, translator: GoogleTranslator) -> str:
    try:
        result = translator.translate(title)
        return result if result else title
    except Exception:
        return title


# --- Progress display ---

def format_eta(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        h, m = int(seconds // 3600), int((seconds % 3600) // 60)
        return f"{h}h {m}m"


def progress_line(current: int, total: int, start_time: float, label: str) -> str:
    done = current - 1
    if done <= 0:
        return f"[{label}] {current}/{total}"
    elapsed = time.time() - start_time
    avg = elapsed / done
    pct = (done / total) * 100
    bar = "█" * int(20 * done / total) + "░" * (20 - int(20 * done / total))
    return f"[{bar}] {pct:5.1f}% | {current}/{total} | ETA {format_eta(avg * (total - current + 1))} | {avg:.1f}s/ch"


# --- Pipeline steps ---

def scrape_all(slug: str, base_url: str, start: int, end: int, delay: float):
    chapters_dir(slug).mkdir(parents=True, exist_ok=True)
    checkpoint = load_checkpoint(slug)
    resume_from = max(checkpoint["last_scraped"] + 1, start)
    total = end - start + 1

    if resume_from > start:
        print(f"Resuming scraping from chapter {resume_from}")

    session = requests.Session()
    consecutive_failures = 0
    step_start = time.time()
    done_count = 0

    for ch in range(resume_from, end + 1):
        chapter_file = chapters_dir(slug) / f"{ch:04d}.json"
        if chapter_file.exists():
            checkpoint["last_scraped"] = ch
            save_checkpoint(slug, checkpoint)
            done_count += 1
            continue

        done_count += 1
        print(f"\r{progress_line(done_count, total, step_start, 'Scraping')} | ch.{ch}...", end="", flush=True)
        data = scrape_chapter(ch, base_url, session)

        if data is None:
            consecutive_failures += 1
            print(f"\r{progress_line(done_count, total, step_start, 'Scraping')} | ch.{ch} FAILED")
            if consecutive_failures >= 5:
                print(f"\n5 consecutive failures at chapter {ch}. Stopping scrape.")
                break
            time.sleep(delay)
            continue

        consecutive_failures = 0
        chapter_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        checkpoint["last_scraped"] = ch
        save_checkpoint(slug, checkpoint)
        print(f"\r{progress_line(done_count, total, step_start, 'Scraping')} | ch.{ch} OK ({len(data['text'].split())}w)")
        time.sleep(delay)

    print(f"\nScraping complete. Last chapter: {checkpoint['last_scraped']} ({format_eta(time.time() - step_start)} elapsed)")


def translate_all(slug: str, start: int, end: int, delay: float, source_lang: str, target_lang: str):
    translated_dir(slug).mkdir(parents=True, exist_ok=True)
    checkpoint = load_checkpoint(slug)
    resume_from = max(checkpoint["last_translated"] + 1, start)
    total = end - start + 1

    if resume_from > start:
        print(f"Resuming translation from chapter {resume_from}")

    translator = GoogleTranslator(source=source_lang, target=target_lang)
    step_start = time.time()
    done_count = 0

    for ch in range(resume_from, end + 1):
        source_file = chapters_dir(slug) / f"{ch:04d}.json"
        dest_file = translated_dir(slug) / f"{ch:04d}.json"

        if dest_file.exists():
            checkpoint["last_translated"] = ch
            save_checkpoint(slug, checkpoint)
            done_count += 1
            continue

        done_count += 1

        if not source_file.exists():
            print(f"\r{progress_line(done_count, total, step_start, 'Translating')} | ch.{ch} SKIPPED (not scraped)")
            continue

        data = json.loads(source_file.read_text())
        print(f"\r{progress_line(done_count, total, step_start, 'Translating')} | ch.{ch}...", end="", flush=True)

        translated_data = {
            "chapter_num": data["chapter_num"],
            "title_original": data["title"],
            "title": translate_title(data["title"], translator),
            "text": translate_text(data["text"], translator),
        }

        dest_file.write_text(json.dumps(translated_data, ensure_ascii=False, indent=2))
        checkpoint["last_translated"] = ch
        save_checkpoint(slug, checkpoint)
        print(f"\r{progress_line(done_count, total, step_start, 'Translating')} | ch.{ch} OK")
        time.sleep(delay)

    print(f"\nTranslation complete. Last chapter: {checkpoint['last_translated']} ({format_eta(time.time() - step_start)} elapsed)")


def build_epub(slug: str, start: int, end: int, title: str, author: str, target_lang: str):
    book = epub.EpubBook()
    book.set_identifier(f"{slug}-{target_lang}")
    book.set_title(title)
    book.set_language(target_lang)
    book.add_author(author)

    css = epub.EpubItem(
        uid="style", file_name="style/default.css", media_type="text/css",
        content=b"body{font-family:Georgia,serif;line-height:1.6;margin:1em}"
                b"h1{font-size:1.4em;margin-bottom:.5em}"
                b"p{text-indent:1.5em;margin:.3em 0}",
    )
    book.add_item(css)

    chapters_list, spine, toc = [], ["nav"], []

    for ch in range(start, end + 1):
        dest_file = translated_dir(slug) / f"{ch:04d}.json"
        if not dest_file.exists():
            continue

        data = json.loads(dest_file.read_text())
        paragraphs_html = "".join(f"<p>{p.strip()}</p>" for p in data["text"].split("\n\n") if p.strip())
        chapter_title = f"Capítulo {ch} — {data['title']}"

        content = (
            f"<?xml version='1.0' encoding='utf-8'?>"
            f"<html xmlns='http://www.w3.org/1999/xhtml'>"
            f"<head><title>{chapter_title}</title>"
            f"<link rel='stylesheet' type='text/css' href='../style/default.css'/></head>"
            f"<body><h1>{chapter_title}</h1>{paragraphs_html}</body></html>"
        )

        epub_ch = epub.EpubHtml(title=chapter_title, file_name=f"chapter_{ch:04d}.xhtml", lang=target_lang)
        epub_ch.set_content(content.encode("utf-8"))
        book.add_item(epub_ch)
        chapters_list.append(epub_ch)
        spine.append(epub_ch)
        toc.append(epub.Link(f"chapter_{ch:04d}.xhtml", chapter_title, f"ch{ch}"))

    book.toc, book.spine = toc, spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    out = output_epub(slug, title)
    epub.write_epub(str(out), book, {})
    print(f"\nEPUB created: {out} ({len(chapters_list)} chapters)")


def find_gaps(slug: str, start: int, end: int):
    missing_scraped, missing_translated = [], []
    for ch in range(start, end + 1):
        if not (chapters_dir(slug) / f"{ch:04d}.json").exists():
            missing_scraped.append(ch)
        elif not (translated_dir(slug) / f"{ch:04d}.json").exists():
            missing_translated.append(ch)
    return missing_scraped, missing_translated


def retry_gaps(slug: str, base_url: str, start: int, end: int, delay: float, source_lang: str, target_lang: str):
    missing_scraped, missing_translated = find_gaps(slug, start, end)

    if not missing_scraped and not missing_translated:
        print("No gaps found! All chapters scraped and translated.")
        return

    if missing_scraped:
        preview = missing_scraped[:10]
        suffix = "..." if len(missing_scraped) > 10 else ""
        print(f"Found {len(missing_scraped)} chapters not scraped: {preview}{suffix}")
        session = requests.Session()
        for i, ch in enumerate(missing_scraped):
            print(f"  Retrying scrape {i+1}/{len(missing_scraped)} — ch.{ch}...", end=" ", flush=True)
            data = scrape_chapter(ch, base_url, session)
            if data:
                (chapters_dir(slug) / f"{ch:04d}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
                print("OK")
            else:
                print("FAILED")
            time.sleep(delay)

    missing_scraped, missing_translated = find_gaps(slug, start, end)

    if missing_translated:
        preview = missing_translated[:10]
        suffix = "..." if len(missing_translated) > 10 else ""
        print(f"Found {len(missing_translated)} chapters not translated: {preview}{suffix}")
        translator = GoogleTranslator(source=source_lang, target=target_lang)
        for i, ch in enumerate(missing_translated):
            src = chapters_dir(slug) / f"{ch:04d}.json"
            if not src.exists():
                continue
            data = json.loads(src.read_text())
            print(f"  Retrying translate {i+1}/{len(missing_translated)} — ch.{ch}...", end=" ", flush=True)
            translated_data = {
                "chapter_num": data["chapter_num"],
                "title_original": data["title"],
                "title": translate_title(data["title"], translator),
                "text": translate_text(data["text"], translator),
            }
            (translated_dir(slug) / f"{ch:04d}.json").write_text(json.dumps(translated_data, ensure_ascii=False, indent=2))
            print("OK")
            time.sleep(delay)

    missing_scraped, missing_translated = find_gaps(slug, start, end)
    total_missing = len(missing_scraped) + len(missing_translated)
    print(f"\nStill {total_missing} gaps remaining." if total_missing else "\nAll gaps filled!")


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(
        description="Scrape a novelhi.com novel, translate it, and export to EPUB.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--url",         required=True,  help="Base novel URL, e.g. https://novelhi.com/novel/fantasy/the-legendary-mechanic")
    parser.add_argument("--novel",       required=True,  help="Novel slug used as folder name, e.g. the-legendary-mechanic")
    parser.add_argument("--title",       required=True,  help="EPUB title in target language, e.g. 'O Mecânico Lendário'")
    parser.add_argument("--author",      default="Unknown", help="Author name for the EPUB")
    parser.add_argument("--start",       type=int, default=1,    help="First chapter number")
    parser.add_argument("--end",         type=int, required=True, help="Last chapter number")
    parser.add_argument("--delay",       type=float, default=2.0, help="Seconds between requests")
    parser.add_argument("--source-lang", default="en",  help="Source language code for translation")
    parser.add_argument("--target-lang", default="pt",  help="Target language code for translation")
    parser.add_argument("--step", choices=["scrape", "translate", "epub", "retry", "status", "all"],
                        default="all", help="Which step to run")
    args = parser.parse_args()

    print(f"=== {args.title} ===")
    print(f"Novel: {args.novel} | Chapters {args.start}-{args.end} | {args.source_lang} → {args.target_lang} | delay {args.delay}s\n")

    if args.step == "status":
        missing_scraped, missing_translated = find_gaps(args.novel, args.start, args.end)
        total = args.end - args.start + 1
        print(f"Scraped:    {total - len(missing_scraped)}/{total}")
        print(f"Translated: {total - len(missing_scraped) - len(missing_translated)}/{total}")
        if missing_scraped:
            print(f"Missing scrape:     {missing_scraped[:20]}{'...' if len(missing_scraped) > 20 else ''}")
        if missing_translated:
            print(f"Missing translate:  {missing_translated[:20]}{'...' if len(missing_translated) > 20 else ''}")
        return

    if args.step == "retry":
        retry_gaps(args.novel, args.url, args.start, args.end, args.delay, args.source_lang, args.target_lang)
        return

    if args.step in ("scrape", "all"):
        print("--- STEP 1: Scraping ---")
        scrape_all(args.novel, args.url, args.start, args.end, args.delay)

    if args.step in ("translate", "all"):
        print("\n--- STEP 2: Translating ---")
        translate_all(args.novel, args.start, args.end, args.delay, args.source_lang, args.target_lang)

    if args.step in ("epub", "all"):
        print("\n--- STEP 3: Building EPUB ---")
        build_epub(args.novel, args.start, args.end, args.title, args.author, args.target_lang)


if __name__ == "__main__":
    main()
