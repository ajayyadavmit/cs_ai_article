# Template: Education Article Digest
## This template can be used for other domains such as finance, arts etc.. to track article, news, blogs on their domain. Just change the Search_queries, Topic_keywords, and region. 

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
                    - Optional Search-grounded Gemini digest
                         /                  \
                        v                    v
             data/articles.json          feed.xml
                      |
                      v
           data/gemini_digest.json (optional)
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
| `data/gemini_digest.json` | Optional Google Search-grounded Gemini digest and its citations | Yes, only when requested |
| `feed.xml` | Public RSS 2.0 feed generated from the article records | **Yes** |
| `index.html` | Hand-maintained page structure and accessible tabs/search controls | **No** |
| `header.html` | Reusable header fragment loaded by JavaScript | **No** |
| `footer.html` | Reusable footer fragment loaded by JavaScript | **No** |
| `assets/css/styles.css` | Hand-maintained layout, responsive styling, and visual design | **No** |
| `assets/js/app.js` | Loads fragments and JSON, builds cards, tabs, search, sharing, and gist UI | **No** |
| `.github/workflows/cs-education-digest.yml` | Schedule, optional summary/digest inputs, dependency setup, and allow-listed data commits | Workflow definition |

The workflow has a collection job that publishes `data/articles.json` and `feed.xml` before a separate Gemini job starts. Gemini summaries are committed separately from the grounded digest. A Gemini failure therefore cannot block publication of the collected articles. Do not replace the explicit Git allow-lists with `git add .`; presentation files are intentionally outside the automated write path.

## Article collection settings

Edit the clearly marked settings near the top of [`scripts/collect_articles.py`](scripts/collect_articles.py):

| Setting | Purpose |
|---|---|
| `GEMINI_MODEL` | Gemini model name; may also be overridden with the `GEMINI_MODEL` environment variable. |
| `GENERATE_SUMMARIES` | Defaults to `false`; the workflow's manual-run checkbox enables it for that run only. |
| `SUMMARY_AUDIENCE` | Audience/topic phrase included in the optional Gemini gist prompt; override through the environment when adapting the template. |
| `MAX_GLOBAL_ARTICLES` | Maximum number of Global articles retained. Default: 40. |
| `REGIONAL_ARTICLE_TARGET` | Maximum number of newest USA, India, and Nepal articles retained per tab. Default: 15. |
| `OLDER_ARTICLE_LIMIT_DAYS` | Older items are retained only up to this age. |
| `MAX_SUMMARIES_PER_REGION` | Maximum number of newest records eligible for gist summaries in each of Global, USA, India, and Nepal. Default: 2. |
| `GEMINI_SEARCH_MODEL` | Gemini model used for the optional Google Search-grounded education digest. Default: `gemini-3.8-flash`. |
| `GENERATE_GEMINI_DIGEST` | Defaults to `false`; explicitly enables generation of the separate Gemini research digest. |
| `GEMINI_DIGEST_MAX_WORDS` | Maximum word count for the digest body. Source URLs are stored separately and do not count toward this limit. Default: 500. |
| `MAX_ARTICLE_TEXT_CHARS` | Upper bound on publisher text sent to Gemini. Default: 3,500 characters. |
| `SECONDS_BETWEEN_SEARCH_CALLS` | Delay between Crossref API queries. |
| `SECONDS_BETWEEN_GEMINI_CALLS` | Delay between summary requests. |
| `SITE_URL` | Base site URL included in the RSS channel; defaults to this repository's GitHub Pages URL. Override with the `SITE_URL` environment variable for a custom domain. |
| `SEARCH_QUERIES` | The shared subject searches sent to Google News RSS and Crossref. |
| `TOPIC_KEYWORDS` | Relevance scoring and topic labels; these are not search queries. |
| `REGIONS` | Region labels used when selecting the newest summary-eligible records. |

### Article collection and locations

The same `SEARCH_QUERIES` are used for every search. Google News runs them through US-English and India-English editions. Nepal also gets a small supplemental search list (`AI education Nepal`, `AI in education Nepal`, `computer science education Nepal`, `coding education Nepal`, and `digital learning Nepal`) plus searches on Nepal-focused publication domains (`kathmandupost.com`, `risingnepaldaily.com`, `myrepublica.nagariknetwork.com`, `edusanjal.com`, and `techpana.com`). The Nepal supplemental searches use a slightly lower relevance threshold so plausible local coverage is less likely to be dropped. News searches look back up to 365 days; relevant older results are retained but newer items sort first. Crossref uses the common queries for scholarly publication metadata and checks author affiliations when available, requesting up to 25 records per query. Up to 15 newest detected records are kept for each USA, India, and Nepal tab, and up to 40 for Global.

Location is an approximate signal for where computer-science education work is happening, not a verified geographic fact. The collector uses explicit country names, relevant place/institution names, recognized publication domains (including `.in`, `.np`, `.com.np`, `.us` and selected known local publishers), the Google News edition that found a result, and Crossref author affiliations when provided. Article text signals take precedence over domain and edition hints. Generic `.com` domains alone do not assign a country. If an article appears in multiple regional editions with no stronger location evidence, it remains Global rather than arbitrarily choosing one region. USA, India, and Nepal go to their tabs; other countries and records without a useful location signal remain in Global. Global cards show a detected country label.

Google News RSS and Crossref article collection run without a Gemini key. Gemini is used only for the optional article gists and the separately enabled, Google Search-grounded research scan; both require `GEMINI_API_KEY`. Crossref metadata and discovery results are public, but the linked publisher's full text may still require access; the collector does not currently verify open-access status.

### Common questions

- **Is Gemini used to find articles?** Not for `data/articles.json`: Google News RSS finds news and publication links, and Crossref finds scholarly publication metadata. Separately, the opt-in Gemini AI Education tab uses Google Search grounding to produce one research scan and citation list when enabled with an API key.
- **What is Crossref?** It is a public scholarly-publication metadata service. It supplies details such as paper titles, authors, dates, abstracts, and DOI links; it does not guarantee that the full paper is freely accessible.
- **What appears in Global?** Articles without a strong location signal, or with conflicting regional-edition hints, remain in Global. If a country can be detected, it appears as a label on the Global card.
- **Does Global mean popular worldwide?** No. The collector does not measure popularity. Articles are sorted by publication date, with relevance score used as a tie-breaker for the same date.

## Gemini summaries and grounded research digest

The daily scheduled run only collects articles and updates the RSS feed. Gemini features are separate manual-only jobs. When starting a manual workflow run, you can select either or both:

1. Add `GEMINI_API_KEY` as a GitHub Actions repository secret.
2. Open **Actions → Collect education articles → Run workflow**.
3. Check **Use Gemini for short summaries** to run the gist job, and/or **Generate a Google Search-grounded Gemini education digest with source links** to run the Gemini education job. Leave both unchecked to run article collection only.

Only the newest two articles per region are summary-eligible (up to eight articles total). Gists request 35–55 words, send at most 3,500 source characters, and cap generated output at 150 tokens. The script makes one request per eligible article that does not already have a gist; it does not retry failed API calls. Failed or unavailable summaries remain blank and do not display a Gist Summary control. Records outside the newest-two scope have their old gists cleared.

Article collection does not require the Gemini key. The collection job commits the article JSON and RSS before the separate Gemini jobs start. Gists and the grounded digest each run in their own job, so one Gemini feature failing does not prevent the collection or the other feature from being committed.

The final **Gemini AI Education** tab is a separate, optional research scan grounded in Google Search. “Grounded” means Gemini can search the web while preparing its answer and the app displays the source links returned with that answer. It is not a guarantee that every statement is correct, so readers should review the cited sources. This is separate from article collection: the collector makes one Gemini request and saves the response and citations to `data/gemini_digest.json`. The text body is capped at 500 words; source URLs are presented separately and do not count toward that limit. The digest can include public news, classroom experiments, and research. Generation may incur Gemini API and Google Search grounding usage.

To generate or refresh the digest manually:

1. Add `GEMINI_API_KEY` as a GitHub Actions repository secret.
2. Open **Actions → Collect education articles → Run workflow**.
3. Optionally select **Use Gemini for short summaries** and independently select **Generate a Google Search-grounded Gemini education digest with source links**.
4. Start the workflow. Article collection runs first; the digest job then runs separately and commits a successful result to `data/gemini_digest.json`.

The digest runs only when its manual checkbox is selected. Scheduled runs do not use Gemini. If no digest file has been generated yet, the tab explains how to enable it. Article collection does not remove or refresh an existing digest.

For a local digest-only test, install the packages from `requirements.txt`, set `GEMINI_API_KEY` in your local terminal environment, and run:

```sh
python scripts/collect_articles.py --digest-only
```

This makes the Gemini request and writes only `data/gemini_digest.json`; it does not collect articles or rewrite `data/articles.json` or `feed.xml`. Do not paste your API key into chat or commit it to the repository. To make the digest part of the website, serve the site locally over HTTP and refresh the page.

## Website and RSS feed

The client-side app loads `data/articles.json` and renders four region tabs plus **Gemini AI Education**. Region tabs include counts, search is scoped to the selected tab, and cards show a gist disclosure only when summary text exists. The Gemini tab displays the separately generated digest and its citation URLs. Cards distinguish **Web article** results from **Research paper** records. Header and footer markup are loaded from their own HTML fragments at runtime.

The RSS 2.0 feed is published at [`feed.xml`](feed.xml). The collector generates it from the same final article records that it writes to [`data/articles.json`](data/articles.json).

### How the RSS feed is generated

When `scripts/collect_articles.py` runs, it follows this sequence:

1. Load and normalize existing records from `data/articles.json`.
2. Discover new Google News RSS and Crossref records, then merge them with existing records by cleaned article URL.
3. Keep records within `OLDER_ARTICLE_LIMIT_DAYS`, sort newest-first, and apply the configured caps: up to 40 Global records and up to `REGIONAL_ARTICLE_TARGET` records for each USA, India, and Nepal region.
4. Optionally generate summaries if explicitly enabled. Summaries are off by default and are not needed to create the RSS feed.
5. Add the collection date, write the retained records to `data/articles.json`, then pass that same in-memory list to `write_rss_feed()` to create/replace `feed.xml`.

The RSS writer creates a standard RSS 2.0 `<channel>` and one `<item>` for each retained article. Each item contains:

| RSS element | Value |
|---|---|
| `<title>` | Article or paper title |
| `<link>` and `<guid>` | Article URL; the GUID is marked as not necessarily a permalink |
| `<description>` | Generated summary when present, otherwise the source description |
| `<category>` | Region, content type, and topic categories (duplicate category labels are omitted) |
| `<pubDate>` | Publication date when it can be parsed |

The channel title, site link, description, language, and build timestamp are written by `write_rss_feed()` in `scripts/collect_articles.py`. `SITE_URL` controls the channel's site link. The output path is the repository's root `feed.xml`; do not edit it manually because each collector run replaces it.

To refresh the feed locally, run the collector from the repository root:

```sh
python scripts/collect_articles.py
```

This requires the collector's Python dependencies and internet access to Google News RSS and Crossref, but not a Gemini API key. After a successful run, review both `data/articles.json` and `feed.xml`. To preview the site and feed locally, start the HTTP server and open `http://localhost:8000` and `http://localhost:8000/feed.xml`.

GitHub Actions runs the collector on its daily schedule or when manually started. If the generated JSON or RSS changed, the workflow commits and pushes only `data/articles.json` and `feed.xml`; GitHub Pages then serves the updated `feed.xml`. The public feed URL is [`https://ajayyadavmit.github.io/cs_ai_education/feed.xml`](https://ajayyadavmit.github.io/cs_ai_education/feed.xml).

### Run the website locally

From the repository root, start a local static web server:

```sh
python3 -m http.server 8000
```

Open [http://localhost:8000](http://localhost:8000) in a browser. Use HTTP rather than opening `index.html` as a `file://` URL because the page fetches its fragments and article JSON.

### Run article collection locally

From the repository root, install the Python dependencies and run the collector:

The collector uses those packages to fetch Google News RSS and Crossref results and parse their metadata. Gemini summaries are optional; don’t enable them for this run.

```sh
python3 --version
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install feedparser requests beautifulsoup4 trafilatura
python scripts/collect_articles.py
python3.14 -m http.server 8000
```

This performs live requests to Google News RSS and Crossref, then updates `data/articles.json` and `feed.xml`. A Gemini API key is not needed for collection. Gemini summaries are off by default; only set `GENERATE_SUMMARIES=true` and provide `GEMINI_API_KEY` if you explicitly want summaries.

The collector keeps up to 40 Global articles and up to the configured regional limit for each USA, India, and Nepal tab. It may keep fewer when searches return fewer qualifying records. Running the collector modifies generated data files, so review those changes before committing.

To publish the website, enable GitHub Pages for the repository using the `main` branch and root folder.

## Adapting the template to another subject

1. Replace `SEARCH_QUERIES` with common topic searches.
2. Change `TOPIC_KEYWORDS` to represent the new subject's categories.
3. Update `COUNTRY_NAMES` in the collector and `countryNames` in the browser if different country labels are needed. Discovery should remain based on the common searches.
4. Update the site copy in `header.html`, `footer.html`, and `index.html`.
5. Adjust `SITE_URL` for the deployment URL.

The front end is data-driven: article cards and gist text are never written into `index.html`.

### Quick visual customization

The main colors and page surfaces are CSS custom properties at the top of [`assets/css/styles.css`](assets/css/styles.css), inside `:root`. Change these to adjust the theme without editing every component:

| CSS variable | Controls |
|---|---|
| `--page` | Page background |
| `--surface` | Cards and panels |
| `--ink` | Main text |
| `--muted` | Secondary text |
| `--line` | Borders |
| `--green`, `--green-dark`, `--green-soft` | Main accent and its shades |
| `--blue-soft` | Region badge background |
| `--shadow` | Panel and card shadow |

Layout and component rules are grouped by page area in the same stylesheet (header, intro, collection, tabs, cards, and footer). Mobile adjustments are in the `max-width: 640px` media query at the end.

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

Install dependencies from `requirements.txt` with `python3 -m pip install -r requirements.txt`. The daily workflow runs article collection at 00:15 UTC. Manual runs can independently opt in to the gist-summary job and the Gemini education digest job. The workflow commits only generated data and RSS files, preserving all manually maintained templates.

Run the focused collector tests with:

```sh
python3 -m unittest discover -s tests -v
```


# Implemented the project as a data-driven template.

* Separated presentation from collection: index.html, styles.css, and app.js render data; header.html and footer.html load as separate fragments. The Python collector no longer generates or edits the page.
* Added four region tabs, scoped search, article-type labels, collection dates, and gist controls that appear only when a summary exists.
- Updated collect_articles.py to gather web articles through Google News RSS and research records through Crossref, assign regions, write JSON and RSS, and make Gemini summaries opt-in. Summaries are limited to the newest two articles per region.
- Added feed.xml and updated the workflow to stage only the article data and feed—not the manually maintained templates—in cs-education-digest.yml.
- Expanded the architecture, settings, and adaptation instructions in README.md.

## Workflow Github

Article collection is already automatic when you manually run the workflow—you don’t need to select a separate option.

In GitHub, go to Actions → Collect education articles → Run workflow. Leave both Gemini options unchecked and click Run workflow to collect articles and update the RSS feed without using Gemini.


- the scheduled run only collects articles and updates the RSS feed. Gemini now has two separate jobs, and both are manual-only:

- Select Use Gemini for short summaries to run the gist job.
- Select Generate a Google Search-grounded Gemini education digest to run the education digest job.
- Leave both unchecked to run article collection without Gemini.