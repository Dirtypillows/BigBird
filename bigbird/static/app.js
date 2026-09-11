function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

async function loadProfiles() {
  const res = await fetch("/api/profiles");
  const profiles = await res.json();
  const select = document.getElementById("site-select");
  select.innerHTML = profiles
    .map((p) => `<option value="${p.site_id}">${escapeHtml(p.name)}</option>`)
    .join("");
}

async function loadStats() {
  const res = await fetch("/api/stats");
  const stats = await res.json();
  const el = document.getElementById("stats");
  el.textContent = stats.length
    ? stats.map((s) => `${s.site}: ${s.count}`).join("  |  ")
    : "no data yet";
}

async function runFetch() {
  const site_id = document.getElementById("site-select").value;
  const pages = parseInt(document.getElementById("pages-input").value, 10) || 1;
  const btn = document.getElementById("fetch-btn");
  const status = document.getElementById("fetch-status");

  btn.disabled = true;
  status.textContent = `Fetching ${pages} page(s) from ${site_id}... this can take a while.`;
  try {
    const res = await fetch("/api/fetch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ site_id, pages }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText);
    }
    const data = await res.json();
    status.textContent = `Done: fetched ${data.pages_fetched} page(s), stored ${data.listings_stored} listing(s).`;
    await loadStats();
  } catch (e) {
    status.textContent = `Error: ${e.message}`;
  } finally {
    btn.disabled = false;
  }
}

const SOLD_RE = /\bsold\b/i;
let lastResults = [];

function renderResults(results) {
  const resultsEl = document.getElementById("results");
  const hideSold = document.getElementById("hide-sold-checkbox").checked;
  const visible = hideSold ? results.filter((r) => !SOLD_RE.test(r.title)) : results;

  if (!visible.length) {
    resultsEl.innerHTML = '<p class="empty">No matches.</p>';
    return;
  }
  resultsEl.innerHTML = visible
    .map(
      (r) => `
    <div class="result">
      <div class="result-title">
        <a href="${r.url}" target="_blank" rel="noopener">${escapeHtml(r.title)}</a>
        <span class="badge">${escapeHtml(r.site)}</span>
      </div>
      <div class="result-meta">
        by ${escapeHtml(r.author)} | ${escapeHtml(r.replies)} replies | ${escapeHtml(r.views)} views | ${escapeHtml(r.last_post)}
      </div>
    </div>`
    )
    .join("");
}

async function runSearch() {
  const q = document.getElementById("search-input").value.trim();
  const resultsEl = document.getElementById("results");
  if (!q) {
    lastResults = [];
    resultsEl.innerHTML = "";
    return;
  }
  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=50`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText);
    }
    lastResults = await res.json();
    renderResults(lastResults);
  } catch (e) {
    lastResults = [];
    resultsEl.innerHTML = `<p class="empty">Error: ${escapeHtml(e.message)}</p>`;
  }
}

document.getElementById("fetch-btn").addEventListener("click", runFetch);
document.getElementById("search-btn").addEventListener("click", runSearch);
document.getElementById("search-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") runSearch();
});
document.getElementById("hide-sold-checkbox").addEventListener("change", () => renderResults(lastResults));

loadProfiles();
loadStats();
