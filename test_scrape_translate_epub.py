import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scrape_translate_epub import build_chapter_url, parse_chapter_html, translate_all, translate_chapter_data


class ScrapeTranslateEpubTests(unittest.TestCase):
    def test_build_chapter_url_keeps_novelhi_format(self):
        url = build_chapter_url("https://novelhi.com/novel/fantasy/the-legendary-mechanic", 12)

        self.assertEqual(url, "https://novelhi.com/novel/fantasy/the-legendary-mechanic/12")

    def test_build_chapter_url_supports_centralnovel_series_urls(self):
        url = build_chapter_url("https://centralnovel.com/series/lord-of-mysteries-20240505/", 12)

        self.assertEqual(url, "https://centralnovel.com/lord-of-mysteries-capitulo-12/")

    def test_parse_novelhi_chapter_html(self):
        html = """
        <html>
          <body>
            <h1 class="readTitle">Chapter 12</h1>
            <div id="showReading">
              <sent>First sentence.</sent><sent>Second sentence.</sent><br/>
              <sent>Next paragraph.</sent>
            </div>
          </body>
        </html>
        """

        data = parse_chapter_html(12, html)

        self.assertEqual(data["title"], "Chapter 12")
        self.assertEqual(data["text"], "First sentence. Second sentence.\n\nNext paragraph.")

    def test_parse_centralnovel_chapter_html(self):
        html = """
        <html>
          <body>
            <h1 class="entry-title">Lord of Mysteries - Capitulo 12</h1>
            <div class="epcontent entry-content">
              <p>Primeiro paragrafo.</p>
              <p>Segundo paragrafo.</p>
            </div>
          </body>
        </html>
        """

        data = parse_chapter_html(12, html)

        self.assertEqual(data["title"], "Lord of Mysteries - Capitulo 12")
        self.assertEqual(data["text"], "Primeiro paragrafo.\n\nSegundo paragrafo.")

    def test_translate_chapter_data_copies_when_translator_is_none(self):
        source = {
            "chapter_num": 12,
            "title": "Titulo",
            "text": "Texto em portugues.",
        }

        data = translate_chapter_data(source, None)

        self.assertEqual(
            data,
            {
                "chapter_num": 12,
                "title_original": "Titulo",
                "title": "Titulo",
                "text": "Texto em portugues.",
            },
        )

    def test_translate_all_does_not_delay_when_copying_same_language(self):
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                os.chdir(tmpdir)
                chapter_dir = Path("novels/book/chapters")
                chapter_dir.mkdir(parents=True)
                chapter_dir.joinpath("0001.json").write_text(json.dumps({
                    "chapter_num": 1,
                    "title": "Titulo",
                    "text": "Texto em portugues.",
                }))

                with patch("scrape_translate_epub.time.sleep") as sleep:
                    translate_all("book", 1, 1, 9.0, "pt", "pt")

                sleep.assert_not_called()
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
