# Education Article Digest

A GitHub Pages template for collecting recent articles, experiments, and research related to computer science and AI education. The collector stores structured article data; a separate, hand-maintained HTML/CSS/JavaScript site displays it. The same template can be adapted for other subjects such as finance, arts, history, or politics.

## Architecture

```text
                  Scheduled GitHub Actions / manual run
                                  |
                                  v
                    scripts/collect_articles.py
                    - Search Google News RSS and Crossref
                    - Score and region-tag results
                    - Optional Gemini gists
                    - Write article data and RSS
                         /                  \
                        v                    v
             data/articles.json          feed.xml
                        \                    /
                         \                  /
                          v                v
                index.html + assets/js/app.js
                    |                 |
            header.html         footer.html
                    \                 /
                     assets/css/styles.css
                              |
                              v
                    GitHub Pages website
```

### File responsibilities

| File/folder | Responsibility | Changed by Actions? |
|---|---|---|
| `scripts/collect_articles.py` | Search Google News and Crossref, relevance scoring, region/type labels, optional Gemini summaries, JSON and RSS output | No |
| `data/articles.json` | Collected article records consumed by the website | **Yes** |
| `feed.xml` | Public RSS 2.0 feed generated from the article records | **Yes** |
| `index.html` | Hand-maintained page structure and accessible tabs/search controls | **No** |
| `header.html` | Reusable header fragment loaded by JavaScript | **No** |
| `footer.html` | Reusable footer fragment loaded by JavaScript | **No** |
| `assets/css/styles.css` | Hand-maintained layout, responsive styling, and visual design | **No** |
| `assets/js/app.js` | Loads fragments and JSON, builds cards, tabs, search, sharing, and gist UI | **No** |
| `.github/workflows/cs-education-digest.yml` | Schedule, manual summary option, dependency setup, and allow-listed data commits | Workflow definition |

The workflow explicitly stages only `data/articles.json` and `feed.xml`. Do not replace that allow-list with `git add .`; presentation files are intentionally outside the automated write path.

## Article collection settings

Edit the clearly marked settings near the top of [`scripts/collect_articles.py`](scripts/collect_articles.py):

| Setting | Purpose |
|---|---|
| `GEMINI_MODEL` | Gemini model name; may also be overridden with the `GEMINI_MODEL` environment variable. |
| `GENERATE_SUMMARIES` | Defaults to `false`; the workflow's manual-run checkbox enables it for that run only. |
| `SUMMARY_AUDIENCE` | Audience/topic phrase included in the optional Gemini gist prompt; override through the environment when adapting the template. |
| `MAX_ARTICLES_ON_PAGE` | Maximum number of records kept in the JSON file and RSS feed. |
| `RECENT_DAYS` | Age threshold used to prioritize recent results. |
| `OLDER_ARTICLE_LIMIT_DAYS` | Older items are retained only up to this age. |
| `MAX_SUMMARIES_PER_REGION` | Maximum number of newest records eligible for gist summaries in each of Global, USA, India, and Nepal. Default: 5. |
| `MAX_ARTICLE_TEXT_CHARS` | Upper bound on publisher text sent to Gemini. Default: 3,500 characters. |
| `SECONDS_BETWEEN_SEARCH_CALLS` | Delay between Crossref API queries. |
| `SECONDS_BETWEEN_GEMINI_CALLS` | Delay between summary requests. |
| `SITE_URL` | Base site URL included in the RSS channel; defaults to this repository's GitHub Pages URL. Override with the `SITE_URL` environment variable for a custom domain. |
| `SEMANTIC_SEARCH_TERMS` | Phrase searches added to Google News RSS. Add or remove phrases to tune discovery. |
| `TOPIC_KEYWORDS` | Phrase-based relevance scoring and article category labels. |
| `BASE_SEARCH_QUERIES` | General search queries to run. |
| `REGION_SEARCH_QUERIES` | Additional searches aimed at the USA, India, and Nepal. |
| `RESEARCH_SEARCH_QUERIES` | Queries sent to the public Crossref Works API for recent scholarly records. |
| `REGIONS` | Region labels used when selecting the newest summary-eligible records. |

### Region assignment

Country-specific words in an article title, description, publisher, or extracted text assign `USA`, `India`, or `Nepal`. An article without a matching country signal is assigned to `Global`. `Global` means internationally relevant or not explicitly tied to one of the three country tabs; it is not a copy of every other region's results. Region matching is deliberately transparent and can be extended in `infer_region()` when adapting the template.

## Gemini summaries and free-tier usage

Summaries are **off by default**, including the daily scheduled run. To request summaries:

1. Add `GEMINI_API_KEY` as a GitHub Actions repository secret.
2. Open **Actions → Collect education articles → Run workflow**.
3. Check **Use Gemini for short summaries** and start the workflow.

Only the newest five articles per region are summary-eligible (up to 20 articles total). Gists request 35–55 words, send at most 3,500 source characters, and cap generated output at 150 tokens. The script makes one request per eligible article that does not already have a gist; it does not retry failed API calls. Failed or unavailable summaries remain blank and do not display a Gist Summary control. Records outside the newest-five scope have their old gists cleared.

The workflow can collect articles without a Gemini key as long as summary generation is not requested.

## Website and RSS feed

The client-side app loads `data/articles.json` and renders four tabs: **Global**, **USA**, **India**, and **Nepal**. Each tab includes a count, search is scoped to the selected tab, and cards show a gist disclosure only when summary text exists. Cards distinguish **Web article** results from **Research paper** records. Header and footer markup are loaded from their own HTML fragments at runtime.

The RSS 2.0 feed is published at [`feed.xml`](feed.xml) and includes each article's title, link, published date (when available), topic tags, region, and gist or source description. Visitors can subscribe by adding that URL to an RSS reader.

For local development, serve the repository over HTTP (the fragments and JSON use `fetch`, so opening `index.html` directly as a `file://` URL will not work):

```sh
python3 -m http.server 8000
```

Then open `http://localhost:8000`. Enable GitHub Pages for the repository using the `main` branch and root folder to publish the site.

## Adapting the template to another subject

1. Replace `SEMANTIC_SEARCH_TERMS` and `BASE_SEARCH_QUERIES` with topic-specific phrases and feeds.
2. Change `TOPIC_KEYWORDS` to represent the new subject's categories.
3. Update `REGION_SEARCH_QUERIES` and `infer_region()` if different regions or labels are needed. Keep the four values in `REGIONS`, the HTML tabs, and the JavaScript region list in sync.
4. Update the site copy in `header.html`, `footer.html`, and `index.html`.
5. Adjust `SITE_URL` for the deployment URL.

The front end is data-driven: article cards and gist text are never written into `index.html`.

## Data record

Google News RSS is used for web articles and blogs; the public Crossref Works API (no API key required) supplements it with recent scholarly works. Each item in `data/articles.json` is an object. Common fields:

| Field | Meaning |
|---|---|
| `title`, `url` | Article title and resolved publisher URL |
| `rss_url` | Original Google News RSS URL used to retrieve the item |
| `publisher`, `author` | Publisher and author, where available |
| `published`, `year`, `first_seen`, `collected_at` | Publication date, year, first discovery date, and latest collection run date |
| `description` | Short source description from the feed |
| `score`, `categories` | Phrase-based relevance score and topic labels |
| `region` | `Global`, `USA`, `India`, or `Nepal` |
| `source`, `content_type` | Discovery source (`Google News` or `Crossref`) and UI type label |
| `summary`, `summary_status` | Optional gist and its status (`pending`, `ok`, `error`, or `not_requested`) |
| `summary_error`, `summarised_at` | Diagnostic and timestamp fields when a summary was attempted |

The collector does not persist full publisher article text.

## Dependencies and workflow

Install dependencies from `requirements.txt` with `python3 -m pip install -r requirements.txt`. The daily workflow runs at 00:15 UTC. Manual runs can opt in to summaries. It commits only the generated JSON and RSS feed, preserving all manually maintained templates.

Run the focused collector tests with:

```sh
python3 -m unittest discover -s tests -v
```


# Implemented the project as a data-driven template.

* Separated presentation from collection: index.html, styles.css, and app.js render data; header.html and footer.html load as separate fragments. The Python collector no longer generates or edits the page.
* Added four region tabs, scoped search, article-type labels, collection dates, and gist controls that appear only when a summary exists.
- Updated collect_articles.py to gather web articles through Google News RSS and research records through Crossref, assign regions, write JSON and RSS, and make Gemini summaries opt-in. Summaries are limited to the newest five articles per region.
- Added feed.xml and updated the workflow to stage only the article data and feed—not the manually maintained templates—in cs-education-digest.yml.
- Expanded the architecture, settings, and adaptation instructions in README.md.
