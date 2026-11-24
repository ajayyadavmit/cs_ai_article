const regions = ["Global", "USA", "India", "Nepal"];
const articleList = document.getElementById("article-list");
const searchInput = document.getElementById("article-search");
const resultCount = document.getElementById("result-count");
const toast = document.getElementById("toast");
let articles = [];
let selectedRegion = "Global";
let toastTimer;

async function loadFragment(target) {
  const response = await fetch(target.dataset.include);
  if (!response.ok) {
    throw new Error(`Could not load ${target.dataset.include} (${response.status}).`);
  }
  target.innerHTML = await response.text();
}

function inferRegion(article) {
  const text = [
    article.title,
    article.description,
    article.publisher,
    article.article_text,
  ].join(" ").toLowerCase();
  const patterns = {
    India: /\b(india|indian|new delhi|mumbai|bengaluru|bangalore|chennai|delhi|hyderabad|kolkata)\b/,
    Nepal: /\b(nepal|nepali|kathmandu|pokhara)\b/,
    USA: /\b(usa|u\.s\.a?\.?|united states|american|new york|california|texas|washington|philadelphia|chicago|boston)\b/,
  };
  for (const region of ["India", "Nepal", "USA"]) {
    if (patterns[region].test(text)) return region;
  }
  return "Global";
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
  const query = searchInput.value.trim().toLocaleLowerCase();
  const sectionArticles = articles.filter((article) => article.region === selectedRegion);
  const visible = sectionArticles.filter((article) => {
    const haystack = [
      article.title,
      article.publisher,
      article.author,
      ...(Array.isArray(article.categories) ? article.categories : []),
      article.description,
      article.summary,
    ].join(" ").toLocaleLowerCase();
    return haystack.includes(query);
  });

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
  resultCount.textContent = `Showing ${visible.length} of ${sectionArticles.length} articles`;

  if (!visible.length) {
    showEmptyMessage(query
      ? "No articles match your search in this region. Try another term or region."
      : "No articles in this region yet. Check back after the next collection run.");
    return;
  }
  articleList.replaceChildren(...visible.map(createArticleCard));
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

  const latestFiveByRegion = Object.fromEntries(regions.map((region) => [
    region,
    data.filter((article) => (article.region || inferRegion(article)) === region)
      .sort((a, b) => (b.published || "").localeCompare(a.published || ""))
      .slice(0, 5),
  ]));
  const latestArticleUrls = new Set(
    Object.values(latestFiveByRegion).flat().map((article) => article.url),
  );
  articles = data.map((article) => ({
    ...article,
    region: regions.includes(article.region) ? article.region : inferRegion(article),
    summary: latestArticleUrls.has(article.url) ? article.summary : "",
  })).sort((a, b) => (b.published || "").localeCompare(a.published || ""));

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
