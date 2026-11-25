const regions = ["Global", "USA", "India", "Nepal"];
const articleList = document.getElementById("article-list");
const searchInput = document.getElementById("article-search");
const resultCount = document.getElementById("result-count");
const toast = document.getElementById("toast");
let articles = [];
let geminiDigest = null;
let selectedRegion = "Global";
let toastTimer;
const GEMINI_TAB = "Gemini AI Education";

async function loadFragment(target) {
  const response = await fetch(target.dataset.include);
  if (!response.ok) {
    throw new Error(`Could not load ${target.dataset.include} (${response.status}).`);
  }
  target.innerHTML = await response.text();
}

const countryNames = [
  "USA", "United States", "India", "Nepal", "United Kingdom", "Canada",
  "Australia", "China", "Japan", "Germany", "France", "Singapore",
  "Finland", "Brazil", "Syria",
];
const regionalSignals = {
  USA: /\b(u\.s\.a?\.?|u\.s\.?|american|united states|new york|california|texas|washington|chicago|boston|philadelphia|seattle|los angeles)\b/i,
  India: /\b(indian|new delhi|mumbai|bengaluru|bangalore|chennai|hyderabad|kolkata|ncert|cbse|iit)\b/i,
  Nepal: /\b(nepali|nepalese|kathmandu|pokhara|lalitpur|bhaktapur|tribhuvan)\b/i,
};

function inferCountry(article) {
  const text = [
    article.title,
    article.description,
    article.publisher,
  ].join(" ");
  const textCountry = Object.entries(regionalSignals).find(([, pattern]) => pattern.test(text));
  if (textCountry) return textCountry[0];
  const publisherUrl = safeArticleUrl(article.publisher_url);
  const host = publisherUrl ? new URL(publisherUrl).hostname.toLowerCase() : "";
  if (host.endsWith(".in") || [
    "thehindu.com", "indianexpress.com", "hindustantimes.com",
    "timesofindia.indiatimes.com", "ndtv.com",
  ].some((domain) => host === domain || host.endsWith(`.${domain}`))) return "India";
  if (host.endsWith(".np") || [
    "kathmandupost.com", "risingnepaldaily.com",
    "myrepublica.nagariknetwork.com", "edusanjal.com", "techpana.com",
  ].some((domain) => host === domain || host.endsWith(`.${domain}`))) return "Nepal";
  if (host.endsWith(".us")) return "USA";
  return countryNames.find((country) => new RegExp(
    `\\b${country}\\b`, "i",
  ).test(text)) || "";
}

function inferRegion(article) {
  const country = inferCountry(article);
  if (country === "United States") return "USA";
  return ["USA", "India", "Nepal"].includes(country) ? country : "Global";
}

function safeArticleUrl(value) {
  try {
    const url = new URL(value, window.location.href);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

function addText(parent, tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = value || "";
  parent.append(element);
  return element;
}

function createArticleCard(article) {
  const card = document.createElement("article");
  card.className = "article-card";

  const meta = document.createElement("div");
  meta.className = "article-meta";
  addText(meta, "span", "region-badge", article.region);
  addText(meta, "span", "type-badge", article.content_type || "Web article");
  if (article.published) {
    addText(meta, "span", "", new Date(`${article.published}T00:00:00`).toLocaleDateString(
      undefined, { year: "numeric", month: "short", day: "numeric" },
    ));
  }
  if (selectedRegion === "Global") {
    const country = article.country || inferCountry(article);
    if (country) addText(meta, "span", "country-badge", country);
  }
  card.append(meta);

  const title = addText(card, "h3", "", article.title || "Untitled article");
  const url = safeArticleUrl(article.url);
  if (url) {
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = article.title || "Untitled article";
    title.replaceChildren(link);
  }

  const source = [article.publisher, article.author && article.author !== "Not listed" ? article.author : ""]
    .filter(Boolean).join(" · ");
  if (source) addText(card, "p", "article-publisher", source);

  const topics = Array.isArray(article.categories) ? article.categories.slice(0, 4) : [];
  if (topics.length) {
    const topicList = document.createElement("div");
    topicList.className = "topic-list";
    topics.forEach((topic) => addText(topicList, "span", "topic-tag", topic));
    card.append(topicList);
  }

  const actions = document.createElement("div");
  actions.className = "article-actions";
  if (url) {
    const readLink = addText(actions, "a", "read-link", "Read article ↗");
    readLink.href = url;
    readLink.target = "_blank";
    readLink.rel = "noopener noreferrer";

    const share = addText(actions, "button", "share-button", "Copy link");
    share.type = "button";
    share.addEventListener("click", () => copyArticleLink(article, url));
  }
  card.append(actions);

  const gist = typeof article.summary === "string" ? article.summary.trim() : "";
  if (gist) {
    const details = document.createElement("details");
    details.className = "gist";
    addText(details, "summary", "", "View gist summary");
    addText(details, "p", "", gist);
    card.append(details);
  }
  return card;
}

function showEmptyMessage(message, isError = false) {
  const empty = document.createElement("p");
  empty.className = isError ? "error-state" : "empty-state";
  empty.textContent = message;
  articleList.replaceChildren(empty);
}

function render() {
  const queryTerms = searchInput.value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.region === selectedRegion;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    const count = tab.querySelector(`[data-count="${tab.dataset.region}"]`);
    if (count) count.textContent = String(articles.filter(
      (article) => article.region === tab.dataset.region,
    ).length);
  });
  articleList.setAttribute(
    "aria-labelledby",
    document.querySelector(`.tab[data-region="${selectedRegion}"]`).id,
  );
  if (selectedRegion === GEMINI_TAB) {
    renderGeminiDigest(queryTerms);
    return;
  }

  const sectionArticles = articles.filter((article) => article.region === selectedRegion);
  const visible = sectionArticles.filter((article) => {
    const haystack = [
      article.title,
      article.publisher,
      article.author,
      article.country,
      article.region,
      article.content_type,
      article.url,
      ...(Array.isArray(article.categories) ? article.categories : []),
      article.description,
      article.summary,
    ].join(" ").normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase();
    return queryTerms.every((term) => haystack.includes(term));
  });
  resultCount.textContent = `Showing ${visible.length} of ${sectionArticles.length} articles`;

  if (!visible.length) {
    showEmptyMessage(queryTerms.length
      ? "No articles match your search in this region. Try another term or region."
      : "No articles in this region yet. Check back after the next collection run.");
    return;
  }
  articleList.replaceChildren(...visible.map(createArticleCard));
}

function renderGeminiDigest(queryTerms) {
  articleList.replaceChildren();
  if (!geminiDigest) {
    resultCount.textContent = "Gemini digest not generated";
    showEmptyMessage(
      "No Gemini research digest yet. Enable “Generate a Google Search-grounded Gemini education digest” in a manual workflow run. Google Search grounding lets Gemini search the web and attach source links; it does not guarantee every claim is accurate.",
    );
    return;
  }

  const sources = Array.isArray(geminiDigest.sources)
    ? geminiDigest.sources.filter((source) => source && typeof source === "object")
    : [];
  const haystack = [
    geminiDigest.text,
    ...sources.flatMap((source) => [source.title, source.url]),
  ].join(" ").normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase();
  if (!queryTerms.every((term) => haystack.includes(term))) {
    resultCount.textContent = `No digest or source matches · ${sources.length} sources`;
    showEmptyMessage("No part of this Gemini digest or its sources matches your search.");
    return;
  }

  resultCount.textContent = `Gemini research scan · ${sources.length} sources`;
  const card = document.createElement("article");
  card.className = "article-card gemini-digest";
  addText(card, "p", "eyebrow", "GOOGLE SEARCH-GROUNDED");
  addText(card, "p", "gemini-digest-text", geminiDigest.text);
  if (geminiDigest.generated_at) {
    const generatedDate = new Date(geminiDigest.generated_at);
    if (!Number.isNaN(generatedDate.getTime())) {
      addText(
        card,
        "p",
        "article-publisher",
        `Generated ${generatedDate.toLocaleString()}. Gemini-selected sources; review original articles.`,
      );
    }
  }
  const sourceHeading = addText(card, "h3", "gemini-sources-heading", "Sources");
  const sourceList = document.createElement("ol");
  sourceList.className = "gemini-source-list";
  for (const source of sources) {
    if (typeof source.url !== "string") continue;
    const url = safeArticleUrl(source.url);
    if (!url) continue;
    const item = document.createElement("li");
    const link = addText(item, "a", "", source.title || url);
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    addText(item, "span", "gemini-source-url", url);
    sourceList.append(item);
  }
  card.append(sourceList);
  articleList.append(card);
}

function notify(message) {
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { toast.hidden = true; }, 2200);
}

async function copyArticleLink(article, url) {
  try {
    await navigator.clipboard.writeText(`${article.title || "Article"}\n${url}`);
    notify("Article link copied");
  } catch {
    window.prompt("Copy this article link:", url);
  }
}

async function loadArticles() {
  const response = await fetch("data/articles.json");
  if (!response.ok) throw new Error(`Could not load articles (${response.status}).`);
  const data = await response.json();
  if (!Array.isArray(data)) throw new Error("Article data must be a JSON array.");

  const latestSummariesByRegion = Object.fromEntries(regions.map((region) => [
    region,
    data.filter((article) => (article.region || inferRegion(article)) === region)
      .sort((a, b) => (b.published || "").localeCompare(a.published || ""))
      .slice(0, 2),
  ]));
  const latestArticleUrls = new Set(
    Object.values(latestSummariesByRegion).flat().map((article) => article.url),
  );
  articles = data.map((article) => ({
    ...article,
    region: regions.includes(article.region) ? article.region : inferRegion(article),
    country: article.country || inferCountry(article),
    summary: latestArticleUrls.has(article.url) ? article.summary : "",
  })).sort((a, b) => (b.published || "").localeCompare(a.published || ""));

  const digestResponse = await fetch("data/gemini_digest.json");
  if (digestResponse.ok) {
    geminiDigest = await digestResponse.json();
    if (typeof geminiDigest.text !== "string" || !Array.isArray(geminiDigest.sources)) {
      throw new Error("Gemini digest data has an invalid format.");
    }
  } else if (digestResponse.status !== 404) {
    throw new Error(`Could not load Gemini digest (${digestResponse.status}).`);
  }

  const collectionDate = articles.map((article) => (
    article.collected_at || article.first_seen || article.published || ""
  )).filter(Boolean).sort().at(-1);
  const updateLabel = collectionDate
    ? new Date(`${collectionDate}T00:00:00`).toLocaleDateString()
    : "date unavailable";
  document.getElementById("updated").textContent = articles.length
    ? `${articles.length} articles · Updated ${updateLabel}`
    : "No articles available yet";
  render();
}

async function startApp() {
  try {
    await Promise.all([...document.querySelectorAll("[data-include]")].map(loadFragment));
    await loadArticles();
  } catch (error) {
    console.error(error);
    showEmptyMessage("We could not load the collection. Please refresh or check the site files.", true);
    document.getElementById("updated").textContent = "Collection unavailable";
  }
}

document.querySelectorAll(".tab").forEach((tab, index, tabs) => {
  tab.addEventListener("click", () => {
    selectedRegion = tab.dataset.region;
    render();
  });
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const nextIndex = event.key === "Home" ? 0
      : event.key === "End" ? tabs.length - 1
        : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    tabs[nextIndex].focus();
    tabs[nextIndex].click();
  });
});
searchInput.addEventListener("input", render);
document.addEventListener("keydown", (event) => {
  if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
    event.preventDefault();
    searchInput.focus();
  }
});
startApp();
