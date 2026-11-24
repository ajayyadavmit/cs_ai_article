import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import collect_articles


class RegionClassificationTests(unittest.TestCase):
    def test_explicit_country_signals_assign_expected_region(self):
        self.assertEqual(collect_articles.infer_region("A coding study in India"), "India")
        self.assertEqual(collect_articles.infer_region("Schools in Kathmandu"), "Nepal")
        self.assertEqual(collect_articles.infer_region("Philadelphia schools teach coding"), "USA")

    def test_non_local_story_defaults_to_global(self):
        self.assertEqual(collect_articles.infer_region("A global learning experiment"), "Global")


class SummaryScopeTests(unittest.TestCase):
    def test_only_newest_five_per_region_remain_summary_eligible(self):
        articles = [
            {
                "url": f"https://example.org/{region}/{day}",
                "region": region,
                "published": f"2026-03-{day:02d}",
                "summary": "Existing gist",
                "summary_status": "ok",
            }
            for region in collect_articles.REGIONS
            for day in range(1, 8)
        ]

        eligible = collect_articles.prepare_summary_scope(articles)

        self.assertEqual(len(eligible), len(collect_articles.REGIONS) * 5)
        for region in collect_articles.REGIONS:
            dates = [a["published"] for a in eligible if a["region"] == region]
            self.assertEqual(
                dates,
                [f"2026-03-{day:02d}" for day in range(7, 2, -1)],
            )
        excluded = [a for a in articles if a["published"].endswith(("01", "02"))]
        self.assertTrue(all(not a["summary"] for a in excluded))
        self.assertTrue(all(a["summary_status"] == "not_requested" for a in excluded))


class FeedTests(unittest.TestCase):
    def test_rss_contains_article_region_and_category(self):
        articles = [{
            "title": "Teaching Python in Nepal",
            "url": "https://example.org/python-nepal",
            "published": "2026-03-20",
            "description": "A classroom guide",
            "summary": "",
            "region": "Nepal",
            "content_type": "Research paper",
            "categories": ["CS Education"],
        }]
        with tempfile.TemporaryDirectory() as directory:
            feed_path = Path(directory) / "feed.xml"
            with patch.object(collect_articles, "RSS_FILE", feed_path):
                collect_articles.write_rss_feed(articles)
            root = ET.parse(feed_path).getroot()

        item = root.find("./channel/item")
        self.assertIsNotNone(item)
        self.assertEqual(item.findtext("title"), "Teaching Python in Nepal")
        self.assertEqual(item.findtext("description"), "A classroom guide")
        self.assertEqual(
            [node.text for node in item.findall("category")],
            ["Nepal", "Research paper", "CS Education"],
        )


class CrossrefTests(unittest.TestCase):
    def test_crossref_record_has_date_region_and_research_type(self):
        class Text:
            def __init__(self, value, *_args, **_kwargs):
                self.value = value

            def get_text(self, *_args, **_kwargs):
                return self.value

        fake_bs4 = SimpleNamespace(BeautifulSoup=Text)
        record = {
            "title": ["Computer science education research in India"],
            "abstract": "This study examines programming education in schools.",
            "DOI": "10.1234/example",
            "URL": "https://doi.org/10.1234/example",
            "published": {"date-parts": [[2026, 4]]},
            "author": [{"given": "Asha", "family": "Rao"}],
            "container-title": ["Journal of Computing Education"],
        }
        with patch.dict("sys.modules", {"bs4": fake_bs4}):
            article = collect_articles.parse_crossref_item(record)

        self.assertIsNotNone(article)
        self.assertEqual(article["published"], "2026-04-01")
        self.assertEqual(article["region"], "India")
        self.assertEqual(article["content_type"], "Research paper")
        self.assertEqual(article["author"], "Asha Rao")


class DatabaseTests(unittest.TestCase):
    def test_existing_records_receive_region_and_stale_error_summaries_are_cleared(self):
        records = [{
            "title": "AI classroom research in India",
            "url": "https://example.org/article",
            "summary": "Summary generation failed: an old error",
        }]
        with tempfile.TemporaryDirectory() as directory:
            data_file = Path(directory) / "articles.json"
            data_file.write_text(json.dumps(records), encoding="utf-8")
            with (
                patch.object(collect_articles, "DATA_FILE", data_file),
                patch.object(collect_articles, "DATA_DIR", Path(directory)),
            ):
                loaded = collect_articles.load_database()

        article = loaded["https://example.org/article"]
        self.assertEqual(article["region"], "India")
        self.assertEqual(article["summary"], "")
        self.assertEqual(article["summary_status"], "error")


if __name__ == "__main__":
    unittest.main()
