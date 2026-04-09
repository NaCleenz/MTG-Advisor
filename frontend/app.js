const API_BASE = "";

// ── State ────────────────────────────────────────────────────────────────
let currentData = null;
let currentRecFilter = "all";
let currentGemFilter = "all";

// ── Init ─────────────────────────────────────────────────────────────────
(async function init() {
  checkOllamaStatus();
})();

async function checkOllamaStatus() {
  const badge = document.getElementById("ollama-badge");
  try {
    const res = await fetch(`${API_BASE}/api/health`, { signal: AbortSignal.timeout(4000) });
    const data = await res.json();
    if (data.ai) {
      badge.className = "badge badge-online";
      badge.textContent = "✓ AI Online";
    } else {
      badge.className = "badge badge-offline";
      badge.textContent = "AI Offline (basic mode)";
    }
  } catch {
    badge.className = "badge badge-offline";
    badge.textContent = "Backend Offline";
  }
}

// ── Main Analyze ──────────────────────────────────────────────────────────
async function analyzeDeck() {
  const deckList = document.getElementById("deck-list").value.trim();
  const problem  = document.getElementById("problem").value.trim();

  if (!deckList) {
    flashError("Please paste your deck list first.");
    return;
  }

  setLoading(true);
  hideAll();
  show("loading-state");

  const loadingMsgs = [
    "Consulting the oracle...",
    "Scraping EDHRec...",
    "Querying Scryfall API...",
    "Analyzing card synergies...",
    "Hunting for hidden gems...",
    "Finalizing recommendations...",
  ];
  let msgIdx = 0;
  const msgEl = document.getElementById("loading-msg");
  const msgInterval = setInterval(() => {
    msgEl.textContent = loadingMsgs[Math.min(msgIdx++, loadingMsgs.length - 1)];
  }, 2200);

  try {
    const res = await fetch(`${API_BASE}/api/recommend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ deck_list: deckList, problem_statement: problem || null }),
      signal: AbortSignal.timeout(120_000),
    });

    clearInterval(msgInterval);

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();
    currentData = data;
    renderResults(data);
  } catch (err) {
    clearInterval(msgInterval);
    showErrorState(err.message || String(err));
  } finally {
    setLoading(false);
  }
}

// ── Render Results ────────────────────────────────────────────────────────
function renderResults(data) {
  hideAll();

  // Commander preview
  const cmd = data.commander;
  if (cmd) {
    document.getElementById("commander-img").src = cmd.image_url || "";
    document.getElementById("commander-name").textContent = cmd.name;
    renderColorPips(cmd.color_identity, document.getElementById("commander-colors"));
    const link = document.getElementById("edhrec-link");
    link.href = data.edhrec_url || "#";
    show("commander-preview");
  }

  // Analysis banner
  const banner = document.getElementById("analysis-banner");
  if (data.problem_analysis) {
    document.getElementById("analysis-text").textContent = data.problem_analysis;
    renderKeywordChips(data.oracle_keywords || []);
    banner.classList.remove("hidden");
  } else {
    banner.classList.add("hidden");
  }

  // Recommendations
  const rec = data.recommendations || {};
  renderTierGrid("budget",  rec.budget  || [], "grid-budget");
  renderTierGrid("mid",     rec.mid     || [], "grid-mid");
  renderTierGrid("premium", rec.premium || [], "grid-premium");
  renderTierGrid("luxury",  rec.luxury  || [], "grid-luxury");
  renderTierGrid("unknown", rec.unknown || [], "grid-unknown");

  // Hidden Gems
  const gems = data.hidden_gems || {};
  renderTierGrid("budget",  gems.budget  || [], "grid-gems-budget");
  renderTierGrid("mid",     gems.mid     || [], "grid-gems-mid");
  renderTierGrid("premium", gems.premium || [], "grid-gems-premium");
  renderTierGrid("luxury",  gems.luxury  || [], "grid-gems-luxury");
  renderTierGrid("unknown", gems.unknown || [], "grid-gems-unknown");

  // Hide empty sections
  ["budget","mid","premium","luxury","unknown"].forEach(tier => {
    toggleTierSection(`tier-${tier}`,       rec[tier]?.length  > 0);
    toggleTierSection(`tier-gems-${tier}`,  gems[tier]?.length > 0);
  });

  show("results");
  switchTab("recommendations", document.querySelector('.tab-btn[data-tab="recommendations"]'));
}

function renderTierGrid(tier, cards, gridId) {
  const grid = document.getElementById(gridId);
  if (!grid) return;
  grid.innerHTML = "";
  cards.forEach(card => grid.appendChild(createCardEl(card)));
}

function toggleTierSection(sectionId, hasCards) {
  const el = document.getElementById(sectionId);
  if (!el) return;
  el.classList.toggle("hidden", !hasCards);
}

// ── Card Element ──────────────────────────────────────────────────────────
function createCardEl(card) {
  const el = document.createElement("div");
  el.className = "mtg-card";
  el.onclick = () => openModal(card);

  const tier = card.price_tier || "unknown";
  const priceLabel = card.price_usd != null
    ? `$${parseFloat(card.price_usd).toFixed(2)}`
    : "N/A";

  el.innerHTML = `
    <div class="card-img-wrapper">
      ${card.image_url
        ? `<img src="${esc(card.image_url)}" alt="${esc(card.name)}" loading="lazy" />`
        : `<div class="card-img-placeholder">🃏</div>`}
      <span class="price-badge ${tier}">${esc(priceLabel)}</span>
    </div>
    <div class="card-info">
      <div class="card-name" title="${esc(card.name)}">${esc(card.name)}</div>
      <div class="card-type">${esc(shortType(card.type_line || ""))}</div>
    </div>
  `;
  return el;
}

function shortType(typeLine) {
  // "Legendary Enchantment — Saga" → "Enchantment — Saga"
  return typeLine.replace(/^(Legendary|Basic|Snow|World)\s+/i, "");
}

// ── Modal ─────────────────────────────────────────────────────────────────
function openModal(card) {
  const modal = document.getElementById("card-modal");
  document.getElementById("modal-img").src = card.image_url || "";
  document.getElementById("modal-name").textContent = card.name;
  document.getElementById("modal-type").textContent = card.type_line || "";
  document.getElementById("modal-oracle").textContent = card.oracle_text || "(no oracle text)";
  document.getElementById("modal-scryfall").href = card.scryfall_uri || "#";

  const tier = card.price_tier || "unknown";
  const priceEl = document.getElementById("modal-price");
  if (card.price_usd != null) {
    priceEl.innerHTML = `<span class="price-badge ${tier}" style="position:static;display:inline-block">$${parseFloat(card.price_usd).toFixed(2)}</span>`;
  } else {
    priceEl.innerHTML = `<span class="price-badge unknown" style="position:static;display:inline-block">Price N/A</span>`;
  }

  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

function closeModal(event) {
  if (event && event.target !== document.getElementById("card-modal") && event.type === "click") return;
  document.getElementById("card-modal").classList.add("hidden");
  document.body.style.overflow = "";
}

document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeModal();
});

// ── Tabs ──────────────────────────────────────────────────────────────────
function switchTab(tabName, btnEl) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
  document.getElementById(`tab-${tabName}`).classList.add("active");
  if (btnEl) btnEl.classList.add("active");
}

// ── Price Filters ─────────────────────────────────────────────────────────
function filterPrice(tier, btnEl) {
  currentRecFilter = tier;
  applyPriceFilter(tier, btnEl, ["budget","mid","premium","luxury","unknown"], "tier-", "filter-btn");
}

function filterGems(tier, btnEl) {
  currentGemFilter = tier;
  applyPriceFilter(tier, btnEl, ["budget","mid","premium","luxury","unknown"], "tier-gems-", "filter-btn");
}

function applyPriceFilter(tier, btnEl, tiers, sectionPrefix, btnClass) {
  // Update button active state within the same bar
  const bar = btnEl?.closest(".price-filter-bar");
  if (bar) {
    bar.querySelectorAll("." + btnClass).forEach(b => b.classList.remove("active"));
    btnEl.classList.add("active");
  }

  tiers.forEach(t => {
    const section = document.getElementById(`${sectionPrefix}${t}`);
    if (!section) return;
    if (tier === "all") {
      section.classList.remove("hidden");
    } else {
      const hasCards = section.querySelector(".card-grid")?.children.length > 0;
      section.classList.toggle("hidden", t !== tier || !hasCards);
    }
  });
}

// ── Color Pips ────────────────────────────────────────────────────────────
const COLOR_MAP = { W:"W", U:"U", B:"B", R:"R", G:"G" };

function renderColorPips(colorIdentity, container) {
  container.innerHTML = "";
  if (!colorIdentity || colorIdentity.length === 0) {
    const pip = document.createElement("span");
    pip.className = "pip pip-C";
    pip.textContent = "C";
    container.appendChild(pip);
    return;
  }
  colorIdentity.forEach(c => {
    const pip = document.createElement("span");
    pip.className = `pip pip-${c}`;
    pip.textContent = c;
    container.appendChild(pip);
  });
}

// ── Keyword Chips ─────────────────────────────────────────────────────────
function renderKeywordChips(keywords) {
  const container = document.getElementById("keyword-chips");
  container.innerHTML = "";
  keywords.forEach(kw => {
    const chip = document.createElement("span");
    chip.className = "keyword-chip";
    chip.textContent = `"${kw}"`;
    container.appendChild(chip);
  });
}

// ── UI Helpers ────────────────────────────────────────────────────────────
function show(id) { document.getElementById(id)?.classList.remove("hidden"); }
function hide(id) { document.getElementById(id)?.classList.add("hidden"); }

function hideAll() {
  ["empty-state","loading-state","error-state","results","commander-preview"].forEach(hide);
}

function setLoading(on) {
  const btn = document.getElementById("analyze-btn");
  btn.disabled = on;
  btn.querySelector(".btn-icon").textContent = on ? "⏳" : "✦";
}

function showErrorState(msg) {
  hideAll();
  document.getElementById("error-msg").textContent = msg;
  show("error-state");
}

function flashError(msg) {
  // Brief visual feedback without replacing the full layout
  const btn = document.getElementById("analyze-btn");
  const original = btn.style.borderColor;
  btn.style.borderColor = "#ef4444";
  btn.style.boxShadow = "0 0 12px rgba(239,68,68,0.4)";
  setTimeout(() => {
    btn.style.borderColor = original;
    btn.style.boxShadow = "";
  }, 1200);
  alert(msg); // simple fallback
}

function esc(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Keyboard submit ───────────────────────────────────────────────────────
document.getElementById("deck-list").addEventListener("keydown", e => {
  if (e.ctrlKey && e.key === "Enter") analyzeDeck();
});
