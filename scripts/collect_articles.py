"""Collect education articles, optionally request short Gemini summaries, and write RSS."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from xml.etree import ElementTree

# ============================================================
# USER SETTINGS: EDIT THESE VALUES
# ============================================================

# Gemini is used only when GENERATE_SUMMARIES=true and a Gemini key is set.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GENERATE_SUMMARIES = os.getenv("GENERATE_SUMMARIES", "false").strip().lower() == "true"
SUMMARY_AUDIENCE = os.getenv("SUMMARY_AUDIENCE", "computer science education")

# Article retention and search age.
MAX_ARTICLES_ON_PAGE = 150
RECENT_DAYS = 30
OLDER_ARTICLE_LIMIT_DAYS = 365

# At most five newest articles in EACH region can have summaries.
MAX_SUMMARIES_PER_REGION = 5

# Limit source text passed to Gemini to reduce token usage.
MAX_ARTICLE_TEXT_CHARS = 3500
SECONDS_BETWEEN_SEARCH_CALLS = 1
SECONDS_BETWEEN_GEMINI_CALLS = 1

# RSS feed links. Override SITE_URL for a custom GitHub Pages domain.
SITE_URL = os.getenv(
    "SITE_URL", "https://ajayyadavmit.github.io/cs_ai_education"
).rstrip("/")

# ------------------------------------------------------------
# SEMANTIC SEARCH TERMS: ADD OR EDIT YOUR OWN TERMS HERE.
# ------------------------------------------------------------
# Google News RSS searches phrases; it is not a vector database. Add phrases
# that describe the articles you want, then tune TOPIC_KEYWORDS to score them.
# For a finance, arts, history, or politics template, replace these terms and
# the topic categories below with terms for that subject area.
SEMANTIC_SEARCH_TERMS = [
    "AI generated learning materials for school students",
    "AI tools for creating classroom quizzes and worksheets",
    "generative AI lesson plans for K-12 teachers",
    "teaching computer science with AI tools",
    "AI models for school education and student learning",
    "computational thinking activities for children",
    "coding games and programming activities for school students",
    "computer science teaching resources and classroom activities",
    "AI literacy curriculum for children and teenagers",
    "AI assisted assessment and feedback in schools",
    "learning analytics for K-12 education",
    "educational data mining and teaching analytics",
    "AI tutors and intelligent tutoring systems for school students",
    "generative AI for creating educational content",
    "computer science curriculum and programming pedagogy",
]

# Tune these phrases to change the relevance score and article tags.
TOPIC_KEYWORDS = {
    "CS Education": [
        "computer science education", "k-12 computer science",
        "computing education", "computer science curriculum",
        "programming education", "coding education", "teaching python",
        "computer science teaching", "cs education",
    ],
    "AI Learning Materials": [
        "ai generated learning materials", "ai-generated worksheets",
        "ai lesson plan", "ai lesson plans", "ai generated quiz",
        "ai-generated quiz", "ai teaching materials", "educational content",
        "generative ai for teachers", "create learning materials",
        "ai classroom resources", "ai tutor", "intelligent tutoring",
    ],
    "Student Activities and Assessment": [
        "school students", "school children", "student activities",
        "classroom activities", "coding games", "coding quiz",
        "programming quiz", "formative assessment", "student assessment",
        "interactive learning", "unplugged activities", "worksheets",
    ],
    "Computational Thinking": [
        "computational thinking", "algorithmic thinking",
        "problem solving", "bebras", "computer science concepts",
    ],
    "AI in Education": [
        "generative ai", "artificial intelligence in education",
        "ai in education", "ai literacy", "large language models",
        "responsible ai", "ai-powered learning",
    ],
    "Teaching and Learning Analytics": [
        "learning analytics", "teaching analytics", "educational data mining",
        "student data", "learning data", "adaptive learning",
    ],
    "Digital Pedagogy": [
        "digital pedagogy", "teacher professional development",
        "educational technology", "digital learning", "personalised learning",
    ],
}

# Broad and country-specific searches. Extend these lists to tune coverage.
BASE_SEARCH_QUERIES = [
    '"computer science education" (teaching OR curriculum OR classroom)',
    '"K-12 computer science" (teacher OR student OR resources)',
    '"AI in education" (school OR teacher OR classroom OR students)',
    '"generative AI" (lesson plans OR worksheets OR quizzes OR teaching)',
    '"computational thinking" (children OR school OR activities OR teaching)',
    '"learning analytics" (school OR classroom OR teaching)',
]
REGION_SEARCH_QUERIES = {
    "USA": [
        '"computer science education" school USA',
        '"AI in education" teachers United States',
    ],
    "India": [
        '"computer science education" school India',
        '"AI in education" teachers India',
    ],
    "Nepal": [
        '"computer science education" school Nepal',
        '"AI in education" teachers Nepal',
    ],
}
RESEARCH_SEARCH_QUERIES = [
    "computer science education",
    "computing education",
    "teaching programming in schools",
    "artificial intelligence education schools",
    "computational thinking education",
]
REGIONS = ("Global", "USA", "India", "Nepal")

# ============================================================
# PATHS, CLIENTS, AND LOGGING
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_FILE = DATA_DIR / "articles.json"
RSS_FILE = ROOT / "feed.xml"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
TODAY = datetime.now(timezone.utc).date()

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
session: Any | None = None


def get_session() -> Any:
    """Create the shared HTTP session only when collection is requested."""
    global session
    if session is None:
        import requests

        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (compatible; CSAIEducationDigest/1.0; "
                "+https://ajayyadav.com.np)"
            )
        })
    return session


def clean_url(url: str) -> str:
    """Remove common tracking parameters while keeping meaningful URL data."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return url
    tracking_names = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in tracking_names
    ]
    return urlunparse((
        parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"),
        parsed.params, urlencode(query, doseq=True), "",
    ))


def parse_entry_date(entry: Any) -> str:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return ""
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return ""


def age_in_days(date_text: str) -> int | None:
    if not date_text:
        return None
    try:
        return (TODAY - date.fromisoformat(date_text)).days
    except ValueError:
        return None


def infer_region(*values: str) -> str:
    """Infer a region from explicit text; default non-local stories to Global."""
    text = " ".join(values).lower()
    signals = {
        "India": (
            r"\bindia\b", r"\bindian\b", r"\bnew delhi\b", r"\bmumbai\b",
            r"\bbengaluru\b", r"\bbangalore\b", r"\bchennai\b", r"\bdelhi\b",
            r"\bhyderabad\b", r"\bkolkata\b",
        ),
        "Nepal": (
            r"\bnepal\b", r"\bnepali\b", r"\bkathmandu\b", r"\bpokhara\b",
        ),
        "USA": (
            r"\busa\b", r"\bu\.s\.a\.?\b", r"\bunited states\b", r"\bu\.s\.?\b",
            r"\bamerican\b", r"\bnew york\b", r"\bcalifornia\b", r"\btexas\b",
            r"\bwashington\b", r"\bphiladelphia\b", r"\bchicago\b", r"\bboston\b",
        ),
    }
    for region in ("India", "Nepal", "USA"):
        if any(re.search(pattern, text) for pattern in signals[region]):
            return region
    return "Global"


def classify_and_score(title: str, description: str = "") -> tuple[int, list[str]]:
    """Calculate a transparent phrase-based relevance score."""
    text = f"{title} {description}".lower()
    categories = []
    score = 0
    for category, phrases in TOPIC_KEYWORDS.items():
        hits = [phrase for phrase in phrases if phrase in text]
        if hits:
            categories.append(category)
            score += min(len(hits), 4) * 3

    practical_signals = (
        "lesson plan", "worksheet", "quiz", "classroom activity",
        "learning materials", "teaching resources", "school students",
        "school children", "coding game", "student project", "teaching guide",
        "teacher guide", "assessment tool", "prompt library", "ai tool",
        "educational model",
    )
    score += sum(5 for phrase in practical_signals if phrase in text)
    education_signals = (
        "teacher", "student", "school", "classroom", "curriculum",
        "learning", "teaching", "education", "pedagogy",
    )
    score += min(sum(phrase in text for phrase in education_signals), 5)
    return score, categories or ["Education Technology"]


def discover_articles() -> list[dict[str, Any]]:
    """Search Google News RSS and return relevant, de-duplicated articles."""
    import feedparser
    import requests
    from bs4 import BeautifulSoup

    http = get_session()
    query_specs = [
        (query, "US", "en-US") for query in BASE_SEARCH_QUERIES
    ] + [
        (f'"{term}"', "US", "en-US") for term in SEMANTIC_SEARCH_TERMS
    ]
    locale_by_region = {"USA": ("US", "en-US"), "India": ("IN", "en-IN"), "Nepal": ("NP", "en-US")}
    query_specs.extend(
        (query, *locale_by_region[region])
        for region, queries in REGION_SEARCH_QUERIES.items()
        for query in queries
    )
    found: dict[str, dict[str, Any]] = {}

    for query, country_code, language in query_specs:
        edition = f"{country_code}:{language.split('-')[0]}"
        rss_url = (
            "https://news.google.com/rss/search?q="
            + requests.utils.quote(f"{query} when:30d")
            + f"&hl={language}&gl={country_code}&ceid={edition}"
        )
        logging.info("RSS search: %s", query)
        try:
            response = http.get(rss_url, timeout=25)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except requests.RequestException as exc:
            logging.warning("RSS request failed for %r: %s", query, exc)
            continue

        for entry in feed.entries:
            title = (entry.get("title") or "").strip()
            rss_url = (entry.get("link") or "").strip()
            if not title or not rss_url:
                continue
            description = BeautifulSoup(
                entry.get("summary", ""), "html.parser"
            ).get_text(" ", strip=True)
            score, categories = classify_and_score(title, description)
            published = parse_entry_date(entry)
            age = age_in_days(published)
            if age is not None:
                if age < 0 or age > OLDER_ARTICLE_LIMIT_DAYS:
                    continue
                if age > RECENT_DAYS and score < 12:
                    continue
            elif score < 15:
                continue
            if score < 6:
                continue

            source = entry.get("source")
            publisher = source.get("title", "").strip() if isinstance(source, dict) else ""
            article_url = clean_url(rss_url)
            article = {
                "title": title,
                "url": article_url,
                "rss_url": rss_url,
                "publisher": publisher,
                "author": (entry.get("author") or "").strip() or "Not listed",
                "published": published,
                "year": published[:4] if published else "",
                "description": description,
                "score": score,
                "categories": categories,
                "region": infer_region(title, description, publisher),
                "source": "Google News",
                "content_type": "Web article",
                "summary": "",
                "summary_status": "pending",
            }
            if article_url not in found or score > found[article_url]["score"]:
                found[article_url] = article

    results = list(found.values())
    sort_articles(results)
    logging.info("Discovered %d candidate articles.", len(results))
    return results


def crossref_published_date(item: dict[str, Any]) -> str:
    """Extract a normalized publication date from a Crossref work record."""
    for field in ("published", "published-print", "published-online"):
        date_value = item.get(field)
        date_parts = (
            date_value.get("date-parts", [[]])[0]
            if isinstance(date_value, dict)
            else []
        )
        if not date_parts:
            continue
        year, *month_day = date_parts
        month = month_day[0] if month_day else 1
        day = month_day[1] if len(month_day) > 1 else 1
        try:
            return date(int(year), int(month), int(day)).isoformat()
        except (TypeError, ValueError):
            continue
    return ""


def parse_crossref_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a Crossref work into the shared article record schema."""
    from bs4 import BeautifulSoup

    titles = item.get("title") or []
    title = titles[0].strip() if titles and isinstance(titles[0], str) else ""
    if not title:
        return None
    abstract = BeautifulSoup(item.get("abstract", ""), "html.parser").get_text(
        " ", strip=True
    )
    score, categories = classify_and_score(title, abstract)
    if score < 6:
        return None
    published = crossref_published_date(item)
    age = age_in_days(published)
    if age is not None and (age < 0 or age > OLDER_ARTICLE_LIMIT_DAYS):
        return None

    doi = (item.get("DOI") or "").strip()
    url = clean_url(item.get("URL") or (f"https://doi.org/{doi}" if doi else ""))
    if not url:
        return None
    container = item.get("container-title") or []
    publisher = container[0].strip() if container else item.get("publisher", "")
    authors = item.get("author") or []
    author_names = [
        " ".join(part for part in (person.get("given"), person.get("family")) if part)
        for person in authors[:2]
    ]
    return {
        "title": title,
        "url": url,
        "rss_url": url,
        "publisher": publisher or "Research publisher",
        "author": ", ".join(author_names) or "Not listed",
        "published": published,
        "year": published[:4] if published else "",
        "description": abstract[:1200],
        "score": score,
        "categories": categories,
        "region": infer_region(title, abstract, publisher or ""),
        "source": "Crossref",
        "content_type": "Research paper",
        "summary": "",
        "summary_status": "pending",
    }


def discover_research_papers() -> list[dict[str, Any]]:
    """Search Crossref for recent research records matching education topics."""
    import requests

    http = get_session()
    start_date = (TODAY - timedelta(days=OLDER_ARTICLE_LIMIT_DAYS)).isoformat()
    found: dict[str, dict[str, Any]] = {}
    for query in RESEARCH_SEARCH_QUERIES:
        params = {
            "query.bibliographic": query,
            "filter": f"from-pub-date:{start_date},until-pub-date:{TODAY.isoformat()}",
            "rows": 8,
            "sort": "published",
            "order": "desc",
        }
        try:
            response = http.get(
                "https://api.crossref.org/works", params=params, timeout=25
            )
            response.raise_for_status()
            records = response.json().get("message", {}).get("items", [])
        except (requests.RequestException, ValueError) as exc:
            logging.warning("Crossref search failed for %r: %s", query, exc)
            continue

        for record in records:
            article = parse_crossref_item(record)
            if not article:
                continue
            key = article["url"]
            if key not in found or article["score"] > found[key]["score"]:
                found[key] = article
        time.sleep(SECONDS_BETWEEN_SEARCH_CALLS)

    results = list(found.values())
    sort_articles(results)
    logging.info("Discovered %d candidate research papers from Crossref.", len(results))
    return results


def fetch_article_text(article: dict[str, Any]) -> str:
    """Resolve the publisher page and extract a bounded text sample."""
    import requests
    import trafilatura

    try:
        response = get_session().get(
            article["rss_url"], timeout=25, allow_redirects=True
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logging.warning("Could not retrieve %s: %s", article.get("url"), exc)
        return ""

    article["url"] = clean_url(response.url)
    metadata = trafilatura.extract_metadata(response.text)
    if metadata:
        if metadata.author:
            article["author"] = metadata.author.strip()
        if metadata.sitename:
            article["publisher"] = metadata.sitename.strip()
        if metadata.date and not article.get("published"):
            try:
                published = datetime.fromisoformat(
                    metadata.date.replace("Z", "+00:00")
                ).date().isoformat()
                article["published"] = published
                article["year"] = published[:4]
            except ValueError:
                logging.info("Publisher returned an unrecognized date for %s", article["url"])

    text = trafilatura.extract(
        response.text, include_comments=False, include_tables=True, favor_precision=True
    ) or ""
    return text[:MAX_ARTICLE_TEXT_CHARS]


def generate_gist(article: dict[str, Any], article_text: str) -> str:
    """Request a short gist from Gemini, importing its SDK only when enabled."""
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Summary generation was requested, but GEMINI_API_KEY is not configured."
        )
    from google import genai

    source_text = article_text.strip()
    if len(source_text) < 80:
        source_text = (article.get("description") or "").strip()
    if len(source_text) < 80:
        raise ValueError("The article text or RSS description is too short to summarize.")

    prompt = f"""Write a factual 35-55 word gist for a reader interested in {SUMMARY_AUDIENCE}.
Use only information supported by this source. Return plain text with these labels:
Main idea: ...
Classroom use: ...
Why it is useful: ...

Title: {article.get('title', '')}
Source text:
{source_text[:MAX_ARTICLE_TEXT_CHARS]}"""
    response = genai.Client(api_key=GEMINI_API_KEY).models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={"max_output_tokens": 150, "temperature": 0.2},
    )
    gist = (getattr(response, "text", None) or "").strip()
    if not gist:
        raise RuntimeError("Gemini returned an empty summary.")
    return gist


def load_database() -> dict[str, dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        return {}
    try:
        records = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not load article database {DATA_FILE}: {exc}") from exc
    if not isinstance(records, list):
        raise ValueError(f"Article database must contain a JSON list: {DATA_FILE}")

    database = {}
    for item in records:
        if not isinstance(item, dict):
            logging.warning("Skipping malformed article record: expected an object.")
            continue
        url = item.get("url", "")
        if not isinstance(url, str) or not clean_url(url):
            continue
        item["url"] = clean_url(url)
        item.setdefault("author", "Not listed")
        item.setdefault("publisher", "Publisher not listed")
        item.setdefault("year", (item.get("published", "") or "")[:4])
        item.setdefault("categories", [])
        item.setdefault("source", "Google News")
        item.setdefault("content_type", "Web article")
        item.setdefault("summary", "")
        item.setdefault("summary_status", "pending")
        item["region"] = infer_region(
            item.get("title", ""),
            item.get("description", ""),
            item.get("publisher", ""),
            item.get("article_text", ""),
        )
        for failure_text in (
            "summary generation failed",
            "the publisher did not provide enough accessible",
            "summary unavailable",
        ):
            if failure_text in item["summary"].lower():
                item["summary"] = ""
                item["summary_status"] = "error"
                break
        item.pop("article_text", None)
        database[item["url"]] = item
    return database


def sort_articles(articles: list[dict[str, Any]]) -> None:
    articles.sort(
        key=lambda item: (
            bool(item.get("published")),
            item.get("published", ""),
            int(item.get("score", 0)),
        ),
        reverse=True,
    )


def prepare_summary_scope(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only keep summaries on the newest configured count in each region."""
    sort_articles(articles)
    allowed_urls: set[str] = set()
    for region in REGIONS:
        regional = [item for item in articles if item.get("region") == region]
        sort_articles(regional)
        allowed_urls.update(
            item.get("url", "") for item in regional[:MAX_SUMMARIES_PER_REGION]
        )
    for item in articles:
        if item.get("url", "") not in allowed_urls:
            item["summary"] = ""
            item["summary_status"] = "not_requested"
            for field in (
                "summary_error", "summarised_at", "last_summarised", "summary_basis"
            ):
                item.pop(field, None)
    return [item for item in articles if item.get("url", "") in allowed_urls]


def save_database(articles: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(articles, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_rss_feed(articles: list[dict[str, Any]]) -> None:
    """Write an RSS 2.0 feed with region and topic categories."""
    rss = ElementTree.Element("rss", {"version": "2.0"})
    channel = ElementTree.SubElement(rss, "channel")
    ElementTree.SubElement(channel, "title").text = "CS & AI Education Articles"
    ElementTree.SubElement(channel, "link").text = f"{SITE_URL}/"
    ElementTree.SubElement(channel, "description").text = (
        "Recent computer science and AI education articles grouped by region."
    )
    ElementTree.SubElement(channel, "language").text = "en"
    ElementTree.SubElement(channel, "lastBuildDate").text = format_datetime(
        datetime.now(timezone.utc)
    )

    for article in articles:
        item = ElementTree.SubElement(channel, "item")
        ElementTree.SubElement(item, "title").text = article.get("title", "")
        ElementTree.SubElement(item, "link").text = article.get("url", "")
        ElementTree.SubElement(item, "guid", {"isPermaLink": "false"}).text = (
            article.get("url", "")
        )
        ElementTree.SubElement(item, "description").text = (
            article.get("summary") or article.get("description", "")
        )
        categories = [
            article.get("region", "Global"),
            article.get("content_type", "Web article"),
            *article.get("categories", []),
        ]
        for category in dict.fromkeys(categories):
            ElementTree.SubElement(item, "category").text = category
        published = article.get("published", "")
        if published:
            try:
                published_date = datetime.fromisoformat(published).replace(
                    tzinfo=timezone.utc
                )
                ElementTree.SubElement(item, "pubDate").text = format_datetime(
                    published_date
                )
            except ValueError:
                logging.warning(
                    "Invalid published date for RSS article %r.", article.get("title")
                )

    ElementTree.ElementTree(rss).write(
        RSS_FILE, encoding="utf-8", xml_declaration=True
    )
    logging.info("RSS feed generated: %s", RSS_FILE)


def main() -> None:
    if GENERATE_SUMMARIES and not GEMINI_API_KEY:
        raise RuntimeError(
            "GENERATE_SUMMARIES is true, but GEMINI_API_KEY is not configured."
        )

    database = load_database()
    discovered = discover_articles() + discover_research_papers()
    for article in discovered:
        key = clean_url(article["url"])
        if key in database:
            old = database[key]
            old["score"] = max(int(old.get("score", 0)), article["score"])
            old["categories"] = sorted(set(old.get("categories", []) + article["categories"]))
            old["region"] = article["region"]
            old["source"] = article["source"]
            old["content_type"] = article["content_type"]
            if not old.get("published") and article.get("published"):
                old["published"] = article["published"]
                old["year"] = article["year"]
            if article.get("description"):
                old["description"] = article["description"]
        else:
            article["first_seen"] = TODAY.isoformat()
            database[key] = article

    retained = []
    for article in database.values():
        age = age_in_days(article.get("published", ""))
        if age is None or age <= OLDER_ARTICLE_LIMIT_DAYS:
            retained.append(article)
    sort_articles(retained)
    retained = retained[:MAX_ARTICLES_ON_PAGE]
    summary_candidates = prepare_summary_scope(retained)

    processed = 0
    if GENERATE_SUMMARIES:
        pending = [article for article in summary_candidates if not article.get("summary")]
        for article in pending:
            logging.info("Preparing optional gist for %s", article.get("title", ""))
            article_text = fetch_article_text(article)
            try:
                article["summary"] = generate_gist(article, article_text)
                article["summary_status"] = "ok"
                article.pop("summary_error", None)
            except Exception as exc:
                article["summary"] = ""
                article["summary_status"] = "error"
                article["summary_error"] = f"{type(exc).__name__}: {exc}"
                logging.warning(
                    "Summary failed for %r: %s", article.get("title", ""), exc
                )
            article["summarised_at"] = datetime.now(timezone.utc).isoformat()
            article.pop("article_text", None)
            processed += 1
            time.sleep(SECONDS_BETWEEN_GEMINI_CALLS)

    for article in retained:
        article["collected_at"] = TODAY.isoformat()
    save_database(retained)
    write_rss_feed(retained)
    summary_count = sum(bool(article.get("summary")) for article in retained)
    logging.info(
        "Finished: %d articles, %d summaries generated this run, %d summaries available.",
        len(retained), processed, summary_count,
    )


if __name__ == "__main__":
    main()
