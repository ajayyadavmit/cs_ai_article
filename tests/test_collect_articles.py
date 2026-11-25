import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from scripts import collect_articles


class RegionClassificationTests(unittest.TestCase):
    def test_explicit_country_names_assign_expected_region(self):
        self.assertEqual(collect_articles.infer_region("A coding study in India"), "India")
        self.assertEqual(collect_articles.infer_region("Schools in Nepal"), "Nepal")
        self.assertEqual(collect_articles.infer_region("Schools in the United States"), "USA")
        self.assertEqual(collect_articles.infer_region("A coding study in Philadelphia"), "USA")

    def test_non_local_story_defaults_to_global(self):
        self.assertEqual(collect_articles.infer_region("A global learning experiment"), "Global")

    def test_country_is_detected_for_global_location_label(self):
        self.assertEqual(collect_articles.infer_country("A study published in Syria"), "Syria")
        self.assertEqual(collect_articles.infer_country("A Canadian classroom AI study"), "")

    def test_domain_and_search_edition_are_location_hints(self):
        self.assertEqual(
            collect_articles.infer_region(
                "Computer science education research",
                publisher_url="https://example.in/article",
            ),
            "India",
        )
        self.assertEqual(
            collect_articles.infer_region(
                "Computer science education research",
                publisher_url="https://example.com.np/article",
            ),
            "Nepal",
        )
        self.assertEqual(
            collect_articles.infer_region(
                "Computer science education research",
                publisher_url="https://example.com/article",
            ),
            "Global",
        )
        self.assertEqual(
            collect_articles.infer_region(
                "Computer science education research",
                edition_country="India",
            ),
            "India",
        )
        self.assertEqual(
            collect_articles.infer_region(
                "Computer science education research in the United States",
                publisher_url="https://example.in/article",
            ),
            "USA",
        )

    def test_ai_teacher_story_passes_relevance_filter(self):
        score, categories = collect_articles.classify_and_score(
            "Nepal's teachers are using AI almost blindly"
        )

        self.assertGreaterEqual(score, 6)
        self.assertIn("AI in Education", categories)

    def test_nepal_supplement_accepts_on_topic_moderate_score(self):
        score, _ = collect_articles.classify_and_score(
            "Computer Science education in Nepal: progress and challenges"
        )

        self.assertGreaterEqual(score, 3)
        self.assertTrue(collect_articles.passes_news_filters(score, 30, "Nepal"))
        self.assertFalse(collect_articles.passes_news_filters(score, 30, "USA"))
        self.assertFalse(collect_articles.passes_news_filters(score, 500, "Nepal"))


class SummaryScopeTests(unittest.TestCase):
    def test_only_newest_two_per_region_remain_summary_eligible(self):
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

        self.assertEqual(
            len(eligible),
            len(collect_articles.REGIONS) * collect_articles.MAX_SUMMARIES_PER_REGION,
        )
        for region in collect_articles.REGIONS:
            dates = [a["published"] for a in eligible if a["region"] == region]
            self.assertEqual(
                dates,
                [f"2026-03-{day:02d}" for day in range(7, 5, -1)],
            )
        excluded = [a for a in articles if a["published"].endswith(("01", "02", "03", "04", "05"))]
        self.assertTrue(all(not a["summary"] for a in excluded))
        self.assertTrue(all(a["summary_status"] == "not_requested" for a in excluded))


class ArticleQuotaTests(unittest.TestCase):
    def test_global_and_regional_article_limits(self):
        articles = []
        for region, count in (("Global", 45), ("USA", 20), ("India", 18), ("Nepal", 16)):
            articles.extend({
                "url": f"https://example.org/{region}/{index}",
                "region": region,
                "published": f"2026-03-{index:02d}",
                "score": 10,
            } for index in range(1, count + 1))

        retained = collect_articles.apply_article_quotas(articles)

        self.assertEqual(sum(a["region"] == "Global" for a in retained), 40)
        self.assertEqual(sum(a["region"] == "USA" for a in retained), 15)
        self.assertEqual(sum(a["region"] == "India" for a in retained), 15)
        self.assertEqual(sum(a["region"] == "Nepal" for a in retained), 15)


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

    def test_crossref_affiliation_can_assign_a_local_region(self):
        class Text:
            def __init__(self, value, *_args, **_kwargs):
                self.value = value

            def get_text(self, *_args, **_kwargs):
                return self.value

        fake_bs4 = SimpleNamespace(BeautifulSoup=Text)
        record = {
            "title": ["Computer science education study"],
            "abstract": "A study of classroom programming education.",
            "DOI": "10.1234/nepal",
            "URL": "https://doi.org/10.1234/nepal",
            "published": {"date-parts": [[2026, 4]]},
            "author": [{
                "given": "Sita",
                "family": "Sharma",
                "affiliation": [{"name": "Tribhuvan University, Kathmandu, Nepal"}],
            }],
            "container-title": ["Computing Education Research"],
        }
        with patch.dict("sys.modules", {"bs4": fake_bs4}):
            article = collect_articles.parse_crossref_item(record)

        self.assertIsNotNone(article)
        self.assertEqual(article["region"], "Nepal")
        self.assertEqual(article["location_basis"], "article text")


class GeminiDigestTests(unittest.TestCase):
    def test_grounded_digest_caps_words_and_extracts_source_urls(self):
        response = SimpleNamespace(
            text=" ".join(f"word{index}" for index in range(510)),
            candidates=[SimpleNamespace(grounding_metadata=SimpleNamespace(
                grounding_chunks=[
                    SimpleNamespace(web=SimpleNamespace(
                        title="Research article",
                        uri="https://example.org/research?utm_source=google",
                    )),
                    SimpleNamespace(web=SimpleNamespace(
                        title="Research article",
                        uri="https://example.org/research?utm_source=google",
                    )),
                ],
            ))],
        )

        digest = collect_articles.parse_grounded_digest_response(response)

        self.assertEqual(len(digest["text"].split()), 500)
        self.assertEqual(len(digest["sources"]), 1)
        self.assertEqual(digest["sources"][0]["url"], "https://example.org/research")

    def test_grounded_digest_requires_source_citations(self):
        response = SimpleNamespace(text="Recent research insights.", candidates=[])

        with self.assertRaisesRegex(RuntimeError, "no verifiable"):
            collect_articles.parse_grounded_digest_response(response)


class GeminiClientLifecycleTests(unittest.TestCase):
    def make_google_module(self, response=None, request_error=None):
        client = SimpleNamespace(closed=False)

        def generate_content(**_kwargs):
            if client.closed:
                raise AssertionError("Gemini client closed before request completed.")
            if request_error:
                raise request_error
            return response

        def close():
            client.closed = True

        client.models = SimpleNamespace(generate_content=generate_content)
        client.close = close
        google_module = ModuleType("google")
        google_module.genai = SimpleNamespace(Client=lambda **_kwargs: client)
        return google_module, client

    def test_gist_keeps_client_open_for_request_and_closes_it(self):
        google_module, client = self.make_google_module(
            response=SimpleNamespace(text="A short, useful gist.")
        )
        with (
            patch.dict("sys.modules", {"google": google_module}),
            patch.object(collect_articles, "GEMINI_API_KEY", "test-key"),
        ):
            gist = collect_articles.generate_gist(
                {"title": "AI in education"},
                "A sufficiently long source text. " * 5,
            )

        self.assertEqual(gist, "A short, useful gist.")
        self.assertTrue(client.closed)

    def test_grounded_digest_keeps_client_open_for_request_and_closes_it(self):
        response = SimpleNamespace(
            text="A research summary.",
            candidates=[SimpleNamespace(grounding_metadata=SimpleNamespace(
                grounding_chunks=[SimpleNamespace(web=SimpleNamespace(
                    title="Source",
                    uri="https://example.org/research",
                ))],
            ))],
        )
        google_module, client = self.make_google_module(response=response)
        with (
            patch.dict("sys.modules", {"google": google_module}),
            patch.object(collect_articles, "GEMINI_API_KEY", "test-key"),
        ):
            digest = collect_articles.generate_gemini_digest()

        self.assertEqual(digest["text"], "A research summary.")
        self.assertTrue(client.closed)

    def test_gemini_client_closes_when_request_fails(self):
        google_module, client = self.make_google_module(
            request_error=RuntimeError("request failed")
        )
        with (
            patch.dict("sys.modules", {"google": google_module}),
            patch.object(collect_articles, "GEMINI_API_KEY", "test-key"),
        ):
            with self.assertRaisesRegex(RuntimeError, "request failed"):
                collect_articles.generate_gist(
                    {"title": "AI in education"},
                    "A sufficiently long source text. " * 5,
                )

        self.assertTrue(client.closed)


class MainModeTests(unittest.TestCase):
    def test_digest_only_writes_digest_without_running_collection(self):
        digest = {"text": "Research summary", "sources": []}
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "data"
            with (
                patch.object(collect_articles, "DATA_DIR", data_dir),
                patch.object(collect_articles, "DATA_FILE", data_dir / "articles.json"),
                patch.object(collect_articles, "RSS_FILE", Path(directory) / "feed.xml"),
                patch.object(collect_articles, "GEMINI_API_KEY", "test-key"),
                patch.object(collect_articles, "GENERATE_SUMMARIES", False),
                patch.object(collect_articles, "GENERATE_GEMINI_DIGEST", False),
                patch.object(collect_articles, "generate_gemini_digest", return_value=digest),
                patch.object(collect_articles, "load_database", side_effect=AssertionError),
                patch.object(collect_articles, "discover_articles", side_effect=AssertionError),
                patch.object(
                    collect_articles, "discover_research_papers", side_effect=AssertionError
                ),
            ):
                collect_articles.main(digest_only=True)

            self.assertEqual(
                json.loads((data_dir / "gemini_digest.json").read_text(encoding="utf-8")),
                digest,
            )
            self.assertFalse((data_dir / "articles.json").exists())
            self.assertFalse((Path(directory) / "feed.xml").exists())

    def test_digest_only_requires_an_api_key(self):
        with (
            patch.object(collect_articles, "GEMINI_API_KEY", ""),
            patch.object(collect_articles, "GENERATE_SUMMARIES", False),
            patch.object(collect_articles, "GENERATE_GEMINI_DIGEST", False),
        ):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                collect_articles.main(digest_only=True)


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
