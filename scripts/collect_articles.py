"""Collect education articles, optionally request short Gemini summaries, and write RSS."""

from __future__ import annotations

import argparse
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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GENERATE_SUMMARIES = os.getenv("GENERATE_SUMMARIES", "false").strip().lower() == "true"
GENERATE_GEMINI_DIGEST = (
    os.getenv("GENERATE_GEMINI_DIGEST", "false").strip().lower() == "true"
)
SUMMARY_AUDIENCE = os.getenv("SUMMARY_AUDIENCE", "computer science education")
GEMINI_SEARCH_MODEL = os.getenv("GEMINI_SEARCH_MODEL", "gemini-3.8-flash")

# Article retention and search age.
MAX_GLOBAL_ARTICLES = 40
REGIONAL_ARTICLE_TARGET = 15
OLDER_ARTICLE_LIMIT_DAYS = 365

# At most two newest articles in EACH region can have summaries.
MAX_SUMMARIES_PER_REGION = 2
GEMINI_DIGEST_MAX_WORDS = 500

# Limit source text passed to Gemini to reduce token usage.
MAX_ARTICLE_TEXT_CHARS = 3500
SECONDS_BETWEEN_SEARCH_CALLS = 1
SECONDS_BETWEEN_GEMINI_CALLS = 1

# RSS feed links. Override SITE_URL for a custom GitHub Pages domain.
SITE_URL = os.getenv(
    "SITE_URL", "https://ajayyadavmit.github.io/cs_ai_education"
).rstrip("/")

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

# The same subject searches are used for news and research, then results are
# classified by country. Keep these searches independent of the region tabs.
SEARCH_QUERIES = [
    "computer science education",
    "K-12 computer science curriculum",
    "AI in education schools",
    "generative AI teaching and learning",
    "computational thinking education",
    "coding education schools",
    "learning analytics education",
    "computer science education research",
]
REGIONS = ("Global", "USA", "India", "Nepal")
NEWS_EDITION_SEARCHES = (
    ("India", "IN", "en-IN"),
    ("USA", "US", "en-US"),
)
NEPAL_NEWS_SITES = (
    "kathmandupost.com",
    "risingnepaldaily.com",
    "myrepublica.nagariknetwork.com",
    "edusanjal.com",
    "techpana.com",
)
NEPAL_SEARCH_QUERIES = (
    '"AI education" Nepal',
    '"AI in education" Nepal',
    '"computer science education" Nepal',
    '"coding education" Nepal',
    '"digital learning" Nepal',
)

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


COUNTRY_NAMES = (
    "USA", "United States", "India", "Nepal", "United Kingdom", "Canada", "Russia",
    "Australia", "China", "Japan", "Germany", "France", "Singapore",
    "Finland", "Brazil", "Syria",
)

COUNTRY_TEXT_SIGNALS = {
    "USA": (
        r"\bu\.s\.a?\.?\b", r"\bu\.s\.?\b", r"\bamerican\b",
        r"\bunited states\b", r"\bnew york\b", r"\bcalifornia\b",
        r"\btexas\b", r"\bwashington\b", r"\bchicago\b", r"\bboston\b",
        r"\bphiladelphia\b", r"\bseattle\b", r"\blos angeles\b",
    ),
    "India": (
        r"\bindian\b", r"\bnew delhi\b", r"\bmumbai\b", r"\bbengaluru\b",
        r"\bbangalore\b", r"\bchennai\b", r"\bhyderabad\b", r"\bkolkata\b",
        r"\bncert\b", r"\bcbse\b", r"\biit\b",
    ),
    "Nepal": (
        r"\bnepali\b", r"\bnepalese\b", r"\bkathmandu\b", r"\bpokhara\b",
        r"\blalitpur\b", r"\bbhaktapur\b", r"\btribhuvan\b",
    ),
}


def country_from_domain(url: str) -> str:
    """Use country-code domains as a location hint; generic .com is not a hint."""
    host = urlparse(url).hostname or ""
    host = host.lower().removeprefix("www.")
    if host.endswith((".com.np", ".org.np", ".edu.np", ".np")) or host in {
        "kathmandupost.com",
        "risingnepaldaily.com",
        "myrepublica.nagariknetwork.com",
        "edusanjal.com","ekantipur.com",
        "techpana.com","ekantipur.com",
    }:
        return "Nepal"
    if host.endswith(".in") or host in {
        "thehindu.com",
        "indianexpress.com",
        "hindustantimes.com",
        "timesofindia.indiatimes.com",
        "ndtv.com",
    }:
        return "India"
    if host.endswith(".us"):
        return "USA"
    return ""


def infer_location(
    *values: str,
    publisher_url: str = "",
    edition_country: str = "",
) -> tuple[str, str]:
    """Infer a likely country and record whether text, domain, or edition signaled it."""
    text = " ".join(values).lower()
    for country, patterns in COUNTRY_TEXT_SIGNALS.items():
        if any(re.search(pattern, text) for pattern in patterns):
            return country, "article text"
    for country in COUNTRY_NAMES:
        if re.search(rf"\b{re.escape(country.lower())}\b", text):
            return ("USA" if country == "United States" else country), "article text"
    domain_country = country_from_domain(publisher_url)
    if domain_country:
        return domain_country, "publisher domain"
    if edition_country in ("USA", "India", "Nepal"):
        return edition_country, "news edition"
    return "", "unknown"


LOCATION_BASIS_PRIORITY = {
    "unknown": 0,
    "news edition": 1,
    "multiple editions": 1,
    "publisher domain": 2,
    "article text": 3,
}


def should_update_location(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    existing_basis = existing.get("location_basis", "unknown")
    candidate_basis = candidate.get("location_basis", "unknown")
    if LOCATION_BASIS_PRIORITY.get(candidate_basis, 0) != LOCATION_BASIS_PRIORITY.get(
        existing_basis, 0
    ):
        return LOCATION_BASIS_PRIORITY.get(candidate_basis, 0) > LOCATION_BASIS_PRIORITY.get(
            existing_basis, 0
        )
    return (
        candidate.get("country") == existing.get("country")
        and int(candidate.get("score", 0)) > int(existing.get("score", 0))
    )


def infer_country(*values: str, publisher_url: str = "") -> str:
    return infer_location(*values, publisher_url=publisher_url)[0]


def infer_region(
    *values: str,
    publisher_url: str = "",
    edition_country: str = "",
) -> str:
    """Map the three country tabs; other countries are shown under Global."""
    country = infer_location(
        *values,
        publisher_url=publisher_url,
        edition_country=edition_country,
    )[0]
    return country if country in ("India", "Nepal", "USA") else "Global"


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
    has_ai = re.search(r"\b(ai|artificial intelligence)\b", text)
    has_education_context = any(
        phrase in text for phrase in ("teacher", "student", "school", "classroom", "education")
    )
    if has_ai and has_education_context:
        score += 5
        if "AI in Education" not in categories:
            categories.append("AI in Education")
    return score, categories or ["Education Technology"]


def passes_news_filters(score: int, age: int | None, region_hint: str) -> bool:
    minimum_score = 3 if region_hint == "Nepal" else 6
    if age is not None and (age < 0 or age > OLDER_ARTICLE_LIMIT_DAYS):
        return False
    if age is None and score < 15:
        return False
    return score >= minimum_score


def discover_articles() -> list[dict[str, Any]]:
    """Search Google News RSS and return relevant, de-duplicated articles."""
    import feedparser
    import requests
    from bs4 import BeautifulSoup

    http = get_session()
    query_specs = [
        (query, country_code, language, region)
        for query in SEARCH_QUERIES
        for region, country_code, language in NEWS_EDITION_SEARCHES
    ]
    query_specs.extend(
        (query, "US", "en-US", "Nepal")
        for query in NEPAL_SEARCH_QUERIES
    )
    nepal_topic_query = " OR ".join(f'"{query}"' for query in SEARCH_QUERIES)
    query_specs.extend(
        (f"site:{site} ({nepal_topic_query})", "US", "en-US", "Nepal")
        for site in NEPAL_NEWS_SITES
    )
    found: dict[str, dict[str, Any]] = {}

    for query, country_code, language, edition_country in query_specs:
        edition = f"{country_code}:{language.split('-')[0]}"
        rss_url = (
            "https://news.google.com/rss/search?q="
            + requests.utils.quote(f"{query} when:{OLDER_ARTICLE_LIMIT_DAYS}d")
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
            if not passes_news_filters(score, age, edition_country):
                continue

            source = entry.get("source")
            publisher = source.get("title", "").strip() if isinstance(source, dict) else ""
            publisher_url = (
                source.get("href") or source.get("url") or ""
                if isinstance(source, dict)
                else ""
            )
            country, location_basis = infer_location(
                title,
                description,
                publisher,
                publisher_url=publisher_url,
                edition_country=edition_country,
            )
            article_url = clean_url(rss_url)
            article = {
                "title": title,
                "url": article_url,
                "rss_url": rss_url,
                "publisher": publisher,
                "publisher_url": publisher_url,
                "author": (entry.get("author") or "").strip() or "Not listed",
                "published": published,
                "year": published[:4] if published else "",
                "description": description,
                "score": score,
                "categories": categories,
                "region": country if country in ("USA", "India", "Nepal") else "Global",
                "country": country,
                "location_basis": location_basis,
                "source": "Google News",
                "content_type": "Web article",
                "summary": "",
                "summary_status": "pending",
            }
            previous = found.get(article_url)
            if (
                previous
                and previous["location_basis"] == "news edition"
                and article["location_basis"] == "news edition"
                and previous["country"] != article["country"]
            ):
                previous.update({
                    "country": "",
                    "region": "Global",
                    "location_basis": "multiple editions",
                })
            elif previous is None or should_update_location(previous, article):
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
    authors = item.get("author") or []
    affiliations = " ".join(
        affiliation.get("name", "")
        for author in authors
        for affiliation in (author.get("affiliation") or [])
        if isinstance(affiliation, dict)
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
    author_names = [
        " ".join(part for part in (person.get("given"), person.get("family")) if part)
        for person in authors[:2]
    ]
    country, location_basis = infer_location(
        title, abstract, publisher or "", affiliations
    )
    return {
        "title": title,
        "url": url,
        "rss_url": url,
        "publisher": publisher or "Research publisher",
        "author": ", ".join(author_names) or "Not listed",
        "published": published,
        "year": published[:4] if published else "",
        "description": abstract[:1200],
        "affiliations": affiliations,
        "score": score,
        "categories": categories,
        "region": country if country in ("USA", "India", "Nepal") else "Global",
        "country": country,
        "location_basis": location_basis,
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
    for query in SEARCH_QUERIES:
        params = {
            "query.bibliographic": query,
            "filter": f"from-pub-date:{start_date},until-pub-date:{TODAY.isoformat()}",
            "rows": 25,
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
    client = genai.Client(api_key=GEMINI_API_KEY)
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={"max_output_tokens": 150, "temperature": 0.2},
        )
    finally:
        client.close()
    gist = (getattr(response, "text", None) or "").strip()
    if not gist:
        raise RuntimeError("Gemini returned an empty summary.")
    return gist


def response_field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def parse_grounded_digest_response(response: Any) -> dict[str, Any]:
    """Extract a 500-word digest and source links from Gemini grounding metadata."""
    digest_text = (response_field(response, "text", "") or "").strip()
    digest_text = re.sub(r"https?://\S+", "", digest_text).strip()
    digest_text = " ".join(digest_text.split()[:GEMINI_DIGEST_MAX_WORDS])
    if not digest_text:
        raise RuntimeError("Gemini returned an empty grounded digest.")

    sources = []
    seen_urls = set()
    candidates = response_field(response, "candidates", []) or []
    for candidate in candidates:
        metadata = (
            response_field(candidate, "grounding_metadata")
            or response_field(candidate, "groundingMetadata")
        )
        chunks = (
            response_field(metadata, "grounding_chunks")
            or response_field(metadata, "groundingChunks")
            or []
        )
        for chunk in chunks:
            web = response_field(chunk, "web", {}) or {}
            url = response_field(web, "uri") or response_field(web, "url") or ""
            title = response_field(web, "title") or url
            if (
                not isinstance(url, str)
                or urlparse(url).scheme not in {"http", "https"}
                or url in seen_urls
            ):
                continue
            seen_urls.add(url)
            sources.append({"title": str(title), "url": clean_url(url)})

    if not sources:
        raise RuntimeError("Gemini returned no verifiable Google Search source links.")
    return {"text": digest_text, "sources": sources}


def generate_gemini_digest() -> dict[str, Any]:
    """Generate one opt-in research digest grounded in Google Search results."""
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Gemini digest generation was requested, but GEMINI_API_KEY is not configured."
        )
    from google import genai

    prompt = """Search the web for recent computer science education and AI in education
news, classroom experiments, and research. Summarize the most useful recent
developments in at most 500 words. Focus on what the work suggests about where
computer science education research and practice are going. Be factual, avoid
unsupported claims, and do not include URLs in the summary; source links are
collected separately from Google Search citations."""
    client = genai.Client(api_key=GEMINI_API_KEY)
    try:
        response = client.models.generate_content(
            model=GEMINI_SEARCH_MODEL,
            contents=prompt,
            config={
                "max_output_tokens": 1100,
                "temperature": 0.2,
                "tools": [{"google_search": {}}],
            },
        )
    finally:
        client.close()
    digest = parse_grounded_digest_response(response)
    digest["generated_at"] = datetime.now(timezone.utc).isoformat()
    digest["model"] = GEMINI_SEARCH_MODEL
    return digest


def save_gemini_digest(digest: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    digest_path = DATA_DIR / "gemini_digest.json"
    digest_path.write_text(
        json.dumps(digest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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
        existing_country = item.get("country", "")
        existing_region = item.get("region", "")
        saved_edition = existing_country if item.get("location_basis") == "news edition" else ""
        if not saved_edition and existing_region in ("USA", "India", "Nepal"):
            saved_edition = existing_region
        country, location_basis = infer_location(
            item.get("title", ""),
            item.get("description", ""),
            item.get("publisher", ""),
            item.get("article_text", ""),
            item.get("affiliations", ""),
            publisher_url=item.get("publisher_url", ""),
            edition_country=saved_edition,
        )
        item["country"] = country
        item["region"] = country if country in ("USA", "India", "Nepal") else "Global"
        item["location_basis"] = location_basis
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


def generate_missing_summaries(summary_candidates: list[dict[str, Any]]) -> int:
    pending = [article for article in summary_candidates if not article.get("summary")]
    processed = 0
    for article in pending:
        logging.info("Preparing optional gist for %s", article.get("title", ""))
        try:
            article_text = fetch_article_text(article)
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
    return processed


def apply_article_quotas(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep up to 40 Global articles and the configured regional count."""
    sort_articles(articles)
    retained = []
    for region, limit in (
        ("Global", MAX_GLOBAL_ARTICLES),
        ("USA", REGIONAL_ARTICLE_TARGET),
        ("India", REGIONAL_ARTICLE_TARGET),
        ("Nepal", REGIONAL_ARTICLE_TARGET),
    ):
        regional = [item for item in articles if item.get("region") == region]
        retained.extend(regional[:limit])
    sort_articles(retained)
    return retained


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


def main(digest_only: bool = False, summaries_only: bool = False) -> None:
    if (GENERATE_SUMMARIES or GENERATE_GEMINI_DIGEST) and not GEMINI_API_KEY:
        raise RuntimeError(
            "Gemini generation was requested, but GEMINI_API_KEY is not configured."
        )
    if digest_only and summaries_only:
        raise ValueError("Digest-only and summaries-only modes cannot be combined.")
    if digest_only:
        if not GEMINI_API_KEY:
            raise RuntimeError(
                "Gemini digest generation was requested, but GEMINI_API_KEY is not configured."
            )
        save_gemini_digest(generate_gemini_digest())
        logging.info("Gemini education digest saved without running article collection.")
        return

    if summaries_only:
        if not GENERATE_SUMMARIES:
            raise RuntimeError(
                "Summaries-only mode requires GENERATE_SUMMARIES=true."
            )
        retained = apply_article_quotas(list(load_database().values()))
        summary_candidates = prepare_summary_scope(retained)
        processed = generate_missing_summaries(summary_candidates)
        for article in retained:
            article["collected_at"] = TODAY.isoformat()
        save_database(retained)
        write_rss_feed(retained)
        logging.info(
            "Finished Gemini gist update: %d summaries generated, %d summaries available.",
            processed,
            sum(bool(article.get("summary")) for article in retained),
        )
        return

    database = load_database()
    discovered = discover_articles() + discover_research_papers()
    for article in discovered:
        key = clean_url(article["url"])
        if key in database:
            old = database[key]
            old["score"] = max(int(old.get("score", 0)), article["score"])
            old["categories"] = sorted(set(old.get("categories", []) + article["categories"]))
            if should_update_location(old, article):
                old["region"] = article["region"]
                old["country"] = article.get("country", "")
                old["location_basis"] = article.get("location_basis", "unknown")
                old["publisher_url"] = article.get(
                    "publisher_url", old.get("publisher_url", "")
                )
            old["source"] = article["source"]
            old["content_type"] = article["content_type"]
            if not old.get("published") and article.get("published"):
                old["published"] = article["published"]
                old["year"] = article["year"]
            if article.get("description"):
                old["description"] = article["description"]
            if article.get("affiliations"):
                old["affiliations"] = article["affiliations"]
        else:
            article["first_seen"] = TODAY.isoformat()
            database[key] = article

    retained = []
    for article in database.values():
        age = age_in_days(article.get("published", ""))
        if age is None or age <= OLDER_ARTICLE_LIMIT_DAYS:
            retained.append(article)
    sort_articles(retained)
    retained = apply_article_quotas(retained)
    summary_candidates = prepare_summary_scope(retained)

    processed = 0
    if GENERATE_SUMMARIES:
        processed = generate_missing_summaries(summary_candidates)

    for article in retained:
        article["collected_at"] = TODAY.isoformat()
    save_database(retained)
    write_rss_feed(retained)
    if GENERATE_GEMINI_DIGEST:
        save_gemini_digest(generate_gemini_digest())
    summary_count = sum(bool(article.get("summary")) for article in retained)
    logging.info(
        "Finished: %d articles, %d summaries generated this run, %d summaries available.",
        len(retained), processed, summary_count,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--digest-only",
        action="store_true",
        help="Generate the Gemini digest without collecting articles or rewriting the RSS feed.",
    )
    parser.add_argument(
        "--summaries-only",
        action="store_true",
        help="Generate eligible article gists without running article discovery.",
    )
    args = parser.parse_args()
    main(digest_only=args.digest_only, summaries_only=args.summaries_only)
