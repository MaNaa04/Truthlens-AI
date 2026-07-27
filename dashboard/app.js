/**
 * TruthLens — Dashboard App
 * Fetches analytics from the backend and renders charts/tables.
 */

const API_BASE = window.location.origin;
let refreshInterval = null;

// ─── Init ─────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  checkBackendStatus();
  fetchAndRender();
  setupNavigation();
  setupVerify();
  setupRefresh();

  // Auto-refresh every 15s
  refreshInterval = setInterval(fetchAndRender, 15000);
});

// ─── Navigation ───────────────────────────────────────────────

function setupNavigation() {
  const navItems = document.querySelectorAll(".nav-item");
  const tabs = document.querySelectorAll(".tab-content");
  const titleMap = {
    overview: ["Overview", "Real-time analytics for AI fact-checking"],
    history: ["Verification History", "Browse past verifications"],
    verify: ["Live Verify", "Test the pipeline in real time"],
  };

  navItems.forEach((item) => {
    item.addEventListener("click", (e) => {
      e.preventDefault();
      const tab = item.dataset.tab;

      navItems.forEach((n) => n.classList.remove("active"));
      item.classList.add("active");

      tabs.forEach((t) => t.classList.remove("active"));
      document.getElementById(`tab-${tab}`).classList.add("active");

      const [title, sub] = titleMap[tab] || ["Dashboard", ""];
      document.getElementById("page-title").textContent = title;
      document.getElementById("page-subtitle").textContent = sub;

      if (tab === "history") fetchHistory();
    });
  });
}

// ─── Refresh ──────────────────────────────────────────────────

function setupRefresh() {
  document.getElementById("refresh-btn").addEventListener("click", () => {
    fetchAndRender();
  });
}

// ─── Backend Status ───────────────────────────────────────────

async function checkBackendStatus() {
  const dot = document.getElementById("sidebar-status-dot");
  const text = document.getElementById("sidebar-status-text");
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    if (res.ok) {
      dot.className = "status-dot online";
      text.textContent = "Backend online";
    } else throw new Error();
  } catch {
    dot.className = "status-dot offline";
    text.textContent = "Backend offline";
  }
}

// ─── Fetch & Render Stats ─────────────────────────────────────

async function fetchAndRender() {
  try {
    const res = await fetch(`${API_BASE}/api/analytics/stats`);
    if (!res.ok) throw new Error();
    const stats = await res.json();
    renderStats(stats);
    document.getElementById("last-updated").textContent =
      `Updated ${new Date().toLocaleTimeString()}`;
  } catch (err) {
    console.error("[Dashboard] Failed to fetch stats:", err);
  }
}

function renderStats(stats) {
  // Stat cards
  document.getElementById("stat-total").textContent =
    stats.total_verifications.toLocaleString();

  document.getElementById("stat-avg-score").textContent =
    stats.total_verifications > 0 ? `${stats.avg_score}/100` : "—";

  document.getElementById("stat-avg-time").textContent =
    stats.total_verifications > 0
      ? stats.avg_processing_time_ms < 1000
        ? `${stats.avg_processing_time_ms}ms`
        : `${(stats.avg_processing_time_ms / 1000).toFixed(1)}s`
      : "—";

  // Hallucination rate
  const hallucinationCount = stats.verdict_distribution?.hallucination || 0;
  const rate = stats.total_verifications > 0
    ? ((hallucinationCount / stats.total_verifications) * 100).toFixed(1)
    : 0;
  document.getElementById("stat-hallucination-rate").textContent =
    stats.total_verifications > 0 ? `${rate}%` : "—";

  // Charts
  renderVerdictChart(stats.verdict_distribution || {});
  renderScoreChart(stats.score_distribution || {});
  renderSourcesChart(stats.sources_distribution || {});
  renderTrendChart(stats.recent_trend || []);
}

// ─── Verdict Chart (Pill bars) ────────────────────────────────

function renderVerdictChart(distribution) {
  const container = document.getElementById("verdict-chart");
  const total = Object.values(distribution).reduce((a, b) => a + b, 0) || 1;

  const verdicts = [
    { key: "accurate", label: "Accurate", color: "var(--green)" },
    { key: "uncertain", label: "Uncertain", color: "var(--amber)" },
    { key: "hallucination", label: "Hallucination", color: "var(--red)" },
  ];

  let html = '<div class="pill-chart">';
  verdicts.forEach((v) => {
    const count = distribution[v.key] || 0;
    const pct = ((count / total) * 100).toFixed(0);
    html += `
      <div class="pill-row">
        <span class="pill-label">${v.label}</span>
        <div class="pill-bar-wrap">
          <div class="pill-bar" style="width: ${pct}%; background: ${v.color};"></div>
        </div>
        <span class="pill-count">${count}</span>
      </div>
    `;
  });
  html += "</div>";
  container.innerHTML = html;
}

// ─── Score Distribution Chart (Bars) ──────────────────────────

function renderScoreChart(distribution) {
  const container = document.getElementById("score-chart");
  const buckets = ["0-19", "20-39", "40-59", "60-79", "80-100"];
  const colors = ["var(--red)", "var(--red)", "var(--amber)", "var(--blue)", "var(--green)"];
  const maxVal = Math.max(...buckets.map((b) => distribution[b] || 0), 1);

  let html = "";
  buckets.forEach((bucket, i) => {
    const val = distribution[bucket] || 0;
    const height = Math.max((val / maxVal) * 140, 4);
    html += `
      <div class="bar-group">
        <span class="bar-value">${val}</span>
        <div class="bar" style="height: ${height}px; background: ${colors[i]};"></div>
        <span class="bar-label">${bucket}</span>
      </div>
    `;
  });
  container.innerHTML = html;
}

// ─── Sources Chart (Pill bars) ────────────────────────────────

function renderSourcesChart(distribution) {
  const container = document.getElementById("sources-chart");
  const entries = Object.entries(distribution).sort((a, b) => b[1] - a[1]);
  const maxVal = entries.length > 0 ? entries[0][1] : 1;

  if (entries.length === 0) {
    container.innerHTML = '<div class="pill-chart"><div class="pill-row"><span class="pill-label" style="width:auto">No data yet</span></div></div>';
    return;
  }

  const colors = ["var(--accent)", "var(--purple)", "var(--blue)", "var(--green)", "var(--amber)"];
  let html = '<div class="pill-chart">';
  entries.forEach(([source, count], i) => {
    const pct = ((count / maxVal) * 100).toFixed(0);
    html += `
      <div class="pill-row">
        <span class="pill-label">${source}</span>
        <div class="pill-bar-wrap">
          <div class="pill-bar" style="width: ${pct}%; background: ${colors[i % colors.length]};"></div>
        </div>
        <span class="pill-count">${count}</span>
      </div>
    `;
  });
  html += "</div>";
  container.innerHTML = html;
}

// ─── Trend Chart (SVG Line) ──────────────────────────────────

function renderTrendChart(recent) {
  const container = document.getElementById("trend-chart");

  if (!recent || recent.length === 0) {
    container.innerHTML = '<div class="pill-chart"><div class="pill-row"><span class="pill-label" style="width:auto">No data yet</span></div></div>';
    return;
  }

  const w = 400, h = 150;
  const padding = { top: 10, right: 20, bottom: 30, left: 10 };
  const plotW = w - padding.left - padding.right;
  const plotH = h - padding.top - padding.bottom;

  const scores = recent.map((r) => r.score);
  const minS = Math.min(...scores, 0);
  const maxS = Math.max(...scores, 100);

  const points = scores.map((s, i) => {
    const x = padding.left + (i / Math.max(scores.length - 1, 1)) * plotW;
    const y = padding.top + plotH - ((s - minS) / (maxS - minS || 1)) * plotH;
    return { x, y, score: s, verdict: recent[i].verdict };
  });

  const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");

  // Gradient area
  const areaD = pathD + ` L ${points[points.length - 1].x} ${h - padding.bottom} L ${points[0].x} ${h - padding.bottom} Z`;

  let svg = `<div class="trend-container">
    <svg class="trend-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <defs>
        <linearGradient id="trendGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.3"/>
          <stop offset="100%" stop-color="var(--accent)" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <!-- Grid lines -->
      <line x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${h - padding.bottom}" stroke="var(--border)" stroke-width="0.5"/>
      <line x1="${padding.left}" y1="${h - padding.bottom}" x2="${w - padding.right}" y2="${h - padding.bottom}" stroke="var(--border)" stroke-width="0.5"/>
      <!-- Area -->
      <path d="${areaD}" fill="url(#trendGrad)"/>
      <!-- Line -->
      <path d="${pathD}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
      <!-- Dots -->
      ${points.map((p) => {
        const color = p.score >= 70 ? "var(--green)" : p.score >= 40 ? "var(--amber)" : "var(--red)";
        return `<circle cx="${p.x}" cy="${p.y}" r="4" fill="${color}" stroke="var(--bg-card)" stroke-width="2"/>`;
      }).join("")}
      <!-- Labels -->
      ${points.map((p, i) => `<text x="${p.x}" y="${h - 8}" text-anchor="middle" fill="var(--text-muted)" font-size="9" font-family="var(--font)">#${i + 1}</text>`).join("")}
    </svg>
  </div>`;

  container.innerHTML = svg;
}

// ─── History ──────────────────────────────────────────────────

async function fetchHistory() {
  try {
    const res = await fetch(`${API_BASE}/api/analytics/history?limit=50`);
    if (!res.ok) throw new Error();
    const data = await res.json();
    renderHistory(data.events || []);
  } catch (err) {
    console.error("[Dashboard] Failed to fetch history:", err);
  }
}

function renderHistory(events) {
  const tbody = document.getElementById("history-body");
  const search = document.getElementById("history-search");

  function render(filter = "") {
    const filtered = filter
      ? events.filter(
          (e) =>
            e.answer_preview.toLowerCase().includes(filter) ||
            e.verdict.toLowerCase().includes(filter)
        )
      : events;

    if (filtered.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No verifications found</td></tr>';
      return;
    }

    tbody.innerHTML = filtered
      .map((e) => {
        const time = new Date(e.timestamp).toLocaleString(undefined, {
          month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
        });
        const scoreClass = e.score >= 70 ? "score-high" : e.score >= 40 ? "score-mid" : "score-low";
        const badgeClass = e.verdict === "accurate" ? "badge-accurate" : e.verdict === "hallucination" ? "badge-hallucination" : "badge-uncertain";
        const sources = (e.sources_used || []).map((s) => `<span class="source-tag">${s}</span>`).join("");
        const latency = e.processing_time_ms < 1000
          ? `${e.processing_time_ms}ms`
          : `${(e.processing_time_ms / 1000).toFixed(1)}s`;

        return `<tr>
          <td>${time}</td>
          <td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${e.answer_preview}</td>
          <td><span class="score-cell ${scoreClass}">${e.score}</span></td>
          <td><span class="badge ${badgeClass}">${e.verdict}</span></td>
          <td>${sources || "—"}</td>
          <td class="latency">${latency}</td>
        </tr>`;
      })
      .join("");
  }

  render();
  search.addEventListener("input", () => render(search.value.toLowerCase()));
}

// ─── Live Verify ──────────────────────────────────────────────

function setupVerify() {
  const btn = document.getElementById("verify-btn");
  const input = document.getElementById("verify-input");
  const resultDiv = document.getElementById("verify-result");
  const loading = document.getElementById("verify-loading");

  btn.addEventListener("click", async () => {
    const text = input.value.trim();
    if (!text) return;

    btn.disabled = true;
    resultDiv.style.display = "none";
    loading.style.display = "flex";

    try {
      const res = await fetch(`${API_BASE}/api/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: "Is this factually accurate?", answer: text }),
      });

      if (!res.ok) throw new Error("Server error");

      const data = await res.json();
      renderVerifyResult(data);

      // Refresh stats after verification
      setTimeout(fetchAndRender, 500);
    } catch (err) {
      alert("Verification failed. Is the backend running?");
    } finally {
      btn.disabled = false;
      loading.style.display = "none";
    }
  });
}

function renderVerifyResult(data) {
  const { score, verdict, explanation, sources_used, processing_time_ms, request_id } = data;
  const resultDiv = document.getElementById("verify-result");
  const header = document.getElementById("vr-header");
  const verdictEl = document.getElementById("vr-verdict");
  const scoreRing = document.getElementById("vr-score-ring");
  const scoreEl = document.getElementById("vr-score");
  const explanationEl = document.getElementById("vr-explanation");
  const sourcesEl = document.getElementById("vr-sources");
  const metaEl = document.getElementById("vr-meta");

  // Verdict
  const verdictMap = {
    accurate: "✅ Likely Accurate",
    verified: "✅ Verified",
    uncertain: "⚠️ Uncertain",
    unverifiable: "❓ Unverifiable",
    hallucination: "🚩 Hallucination Detected",
    likely_hallucination: "🚩 Likely Hallucination",
  };
  verdictEl.textContent = verdictMap[verdict] || "❓ Unknown";

  // Score
  scoreEl.textContent = score;
  const cls = verdict === "accurate" || verdict === "verified" ? "accurate" : verdict === "hallucination" || verdict === "likely_hallucination" ? "hallucination" : "uncertain";
  header.className = `vr-header ${cls}`;
  scoreRing.className = `vr-score-ring ${score >= 70 ? "high" : score >= 40 ? "mid" : "low"}`;

  // Explanation
  explanationEl.textContent = explanation;

  // Sources
  sourcesEl.innerHTML = (sources_used || []).map((s) => `<span class="source-tag">${s}</span>`).join("") || '<span class="source-tag">None</span>';

  // Meta
  const latency = processing_time_ms < 1000 ? `${processing_time_ms}ms` : `${(processing_time_ms / 1000).toFixed(1)}s`;
  metaEl.textContent = `Verified in ${latency} · ID: ${(request_id || "").slice(0, 8)}`;

  resultDiv.style.display = "block";
}
