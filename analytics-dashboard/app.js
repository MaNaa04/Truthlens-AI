/**
 * TruthLens — Deep Pipeline Insights Dashboard
 * Chart.js-powered analytics with preprocessing and pipeline views.
 */

const API_BASE = window.location.origin;
let refreshInterval = null;

// Chart instances (for proper destroy/recreate)
const charts = {};

// Chart.js global config
Chart.defaults.font.family = "'Inter', sans-serif";
Chart.defaults.color = '#8b90a8';
Chart.defaults.borderColor = 'rgba(255,255,255,0.04)';

// ─── Init ─────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  checkBackendStatus();
  fetchOverview();
  setupNavigation();
  setupVerify();
  setupRefresh();
  refreshInterval = setInterval(fetchOverview, 20000);
});

// ─── Navigation ───────────────────────────────────────────────

function setupNavigation() {
  const navItems = document.querySelectorAll('.nav-item');
  const tabs = document.querySelectorAll('.tab-content');
  const titleMap = {
    overview:       ['Overview',       'Real-time pipeline analytics'],
    preprocessing:  ['Preprocessing',  'Query classification & claim extraction insights'],
    pipeline:       ['Pipeline',       'Per-stage performance breakdown'],
    history:        ['History',        'Browse past verifications'],
    verify:         ['Live Verify',    'Test the pipeline with preprocessing breakdown'],
  };

  navItems.forEach(item => {
    item.addEventListener('click', e => {
      e.preventDefault();
      const tab = item.dataset.tab;

      navItems.forEach(n => n.classList.remove('active'));
      item.classList.add('active');

      tabs.forEach(t => t.classList.remove('active'));
      document.getElementById(`tab-${tab}`).classList.add('active');

      const [title, sub] = titleMap[tab] || ['Dashboard', ''];
      document.getElementById('page-title').textContent = title;
      document.getElementById('page-subtitle').textContent = sub;

      // Lazy-load data for tabs
      if (tab === 'preprocessing') fetchPreprocessing();
      if (tab === 'pipeline') fetchPipeline();
      if (tab === 'history') fetchHistory();
    });
  });
}

// ─── Refresh ──────────────────────────────────────────────────

function setupRefresh() {
  document.getElementById('refresh-btn').addEventListener('click', () => {
    fetchOverview();
    const activeTab = document.querySelector('.nav-item.active')?.dataset.tab;
    if (activeTab === 'preprocessing') fetchPreprocessing();
    if (activeTab === 'pipeline') fetchPipeline();
    if (activeTab === 'history') fetchHistory();
  });
}

// ─── Backend Status ───────────────────────────────────────────

async function checkBackendStatus() {
  const dot = document.getElementById('sidebar-status-dot');
  const text = document.getElementById('sidebar-status-text');
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    if (res.ok) {
      dot.className = 'status-dot online';
      text.textContent = 'Backend online';
    } else throw new Error();
  } catch {
    dot.className = 'status-dot offline';
    text.textContent = 'Backend offline';
  }
}

// ═══════════════════════════════════════════════════════════════
// OVERVIEW TAB
// ═══════════════════════════════════════════════════════════════

async function fetchOverview() {
  try {
    const res = await fetch(`${API_BASE}/api/analytics/stats`);
    if (!res.ok) throw new Error();
    const stats = await res.json();
    renderOverview(stats);
    document.getElementById('last-updated').textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (err) {
    console.error('[Dashboard] Failed to fetch stats:', err);
  }
}

function renderOverview(stats) {
  // Stat cards
  document.getElementById('stat-total').textContent = stats.total_verifications.toLocaleString();
  document.getElementById('stat-avg-score').textContent =
    stats.total_verifications > 0 ? `${stats.avg_score}/100` : '—';
  document.getElementById('stat-avg-time').textContent =
    stats.total_verifications > 0
      ? stats.avg_processing_time_ms < 1000
        ? `${stats.avg_processing_time_ms}ms`
        : `${(stats.avg_processing_time_ms / 1000).toFixed(1)}s`
      : '—';

  const hallucinationCount = stats.verdict_distribution?.hallucination || 0;
  const rate = stats.total_verifications > 0
    ? ((hallucinationCount / stats.total_verifications) * 100).toFixed(1) : 0;
  document.getElementById('stat-hallucination-rate').textContent =
    stats.total_verifications > 0 ? `${rate}%` : '—';

  // Charts
  renderVerdictChart(stats.verdict_distribution || {});
  renderScoreChart(stats.score_distribution || {});
  renderSourcesChart(stats.sources_distribution || {});
  renderTrendChart(stats.recent_trend || []);
}

// ─── Verdict Donut ────────────────────────────────────────────

function renderVerdictChart(distribution) {
  const ctx = document.getElementById('verdict-chart');
  if (charts.verdict) charts.verdict.destroy();

  const labels = ['Accurate', 'Uncertain', 'Hallucination'];
  const data = [
    distribution.accurate || 0,
    distribution.uncertain || 0,
    distribution.hallucination || 0,
  ];

  if (data.every(v => v === 0)) {
    ctx.parentElement.innerHTML = '<div class="no-data"><span class="no-data-icon">📊</span>No data yet</div>';
    return;
  }

  charts.verdict = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: ['#34d399', '#fbbf24', '#f87171'],
        borderColor: 'transparent',
        borderWidth: 0,
        hoverOffset: 8,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      cutout: '65%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: { padding: 16, usePointStyle: true, pointStyleWidth: 8, font: { size: 11 } },
        },
      },
      animation: { animateRotate: true, duration: 800 },
    },
  });
}

// ─── Score Histogram ──────────────────────────────────────────

function renderScoreChart(distribution) {
  const ctx = document.getElementById('score-chart');
  if (charts.score) charts.score.destroy();

  const buckets = ['0-19', '20-39', '40-59', '60-79', '80-100'];
  const data = buckets.map(b => distribution[b] || 0);
  const colors = ['#f87171', '#fb923c', '#fbbf24', '#60a5fa', '#34d399'];

  charts.score = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: buckets,
      datasets: [{
        data,
        backgroundColor: colors.map(c => c + '99'),
        borderColor: colors,
        borderWidth: 1.5,
        borderRadius: 6,
        borderSkipped: false,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          grid: { display: false },
          ticks: { font: { size: 10 } },
        },
        y: {
          beginAtZero: true,
          ticks: { stepSize: 1, font: { size: 10 } },
          grid: { color: 'rgba(255,255,255,0.03)' },
        },
      },
      animation: { duration: 600, easing: 'easeOutQuart' },
    },
  });
}

// ─── Sources Donut ────────────────────────────────────────────

function renderSourcesChart(distribution) {
  const ctx = document.getElementById('sources-chart');
  if (charts.sources) charts.sources.destroy();

  const entries = Object.entries(distribution).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) {
    ctx.parentElement.innerHTML = '<div class="no-data"><span class="no-data-icon">🔍</span>No sources data yet</div>';
    return;
  }

  const colors = ['#667eea', '#a78bfa', '#60a5fa', '#34d399', '#fbbf24', '#f87171', '#22d3ee'];

  charts.sources = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: entries.map(e => e[0]),
      datasets: [{
        data: entries.map(e => e[1]),
        backgroundColor: colors.slice(0, entries.length),
        borderColor: 'transparent',
        borderWidth: 0,
        hoverOffset: 8,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      cutout: '55%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: { padding: 14, usePointStyle: true, pointStyleWidth: 8, font: { size: 11 } },
        },
      },
      animation: { animateRotate: true, duration: 800 },
    },
  });
}

// ─── Score Trend Line ─────────────────────────────────────────

function renderTrendChart(recent) {
  const ctx = document.getElementById('trend-chart');
  if (charts.trend) charts.trend.destroy();

  if (!recent || recent.length === 0) {
    ctx.parentElement.innerHTML = '<div class="no-data"><span class="no-data-icon">📈</span>No trend data yet</div>';
    return;
  }

  const labels = recent.map((_, i) => `#${i + 1}`);
  const scores = recent.map(r => r.score);
  const pointColors = scores.map(s => s >= 70 ? '#34d399' : s >= 40 ? '#fbbf24' : '#f87171');

  charts.trend = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: scores,
        borderColor: '#667eea',
        backgroundColor: 'rgba(102, 126, 234, 0.08)',
        fill: true,
        tension: 0.4,
        borderWidth: 2.5,
        pointBackgroundColor: pointColors,
        pointBorderColor: '#1a1d27',
        pointBorderWidth: 2,
        pointRadius: 5,
        pointHoverRadius: 7,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          grid: { display: false },
          ticks: { font: { size: 10 } },
        },
        y: {
          min: 0, max: 100,
          ticks: { stepSize: 25, font: { size: 10 } },
          grid: { color: 'rgba(255,255,255,0.03)' },
        },
      },
      animation: { duration: 800, easing: 'easeOutQuart' },
    },
  });
}

// ═══════════════════════════════════════════════════════════════
// PREPROCESSING TAB
// ═══════════════════════════════════════════════════════════════

async function fetchPreprocessing() {
  try {
    const res = await fetch(`${API_BASE}/api/analytics/preprocessing`);
    if (!res.ok) throw new Error();
    const data = await res.json();
    renderPreprocessing(data);
  } catch (err) {
    console.error('[Dashboard] Failed to fetch preprocessing stats:', err);
  }
}

function renderPreprocessing(data) {
  // Stat cards
  document.getElementById('pp-avg-sentences').textContent = data.avg_sentences_found || '—';
  document.getElementById('pp-avg-factual').textContent = data.avg_factual_sentences || '—';
  document.getElementById('pp-avg-claims').textContent = data.avg_claims_extracted || '—';
  document.getElementById('pp-avg-time').textContent =
    data.avg_preprocessing_time_ms !== undefined ? `${data.avg_preprocessing_time_ms}ms` : '—';

  // Query Type Distribution
  renderQueryTypeChart(data.query_type_distribution || {});

  // Funnel Chart
  renderFunnelChart(data);

  // Timeline
  renderPreprocessingTimeline(data.preprocessing_timeline || []);
}

function renderQueryTypeChart(distribution) {
  const ctx = document.getElementById('query-type-chart');
  if (charts.queryType) charts.queryType.destroy();

  const entries = Object.entries(distribution);
  if (entries.length === 0) {
    ctx.parentElement.innerHTML = '<div class="no-data"><span class="no-data-icon">🏷️</span>No query type data</div>';
    return;
  }

  const colorMap = {
    encyclopedic: '#60a5fa',
    recent_event: '#fbbf24',
    numeric_statistical: '#22d3ee',
    opinion_subjective: '#a78bfa',
    unknown: '#555a72',
  };

  charts.queryType = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: entries.map(e => e[0].replace(/_/g, ' ')),
      datasets: [{
        data: entries.map(e => e[1]),
        backgroundColor: entries.map(e => colorMap[e[0]] || '#667eea'),
        borderColor: 'transparent',
        borderWidth: 0,
        hoverOffset: 8,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      cutout: '60%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            padding: 14,
            usePointStyle: true,
            pointStyleWidth: 8,
            font: { size: 11 },
            textTransform: 'capitalize',
          },
        },
      },
      animation: { animateRotate: true, duration: 800 },
    },
  });
}

function renderFunnelChart(data) {
  const ctx = document.getElementById('funnel-chart');
  if (charts.funnel) charts.funnel.destroy();

  const labels = ['Sentences Found', 'Factual Sentences', 'Claims Extracted'];
  const values = [
    data.avg_sentences_found || 0,
    data.avg_factual_sentences || 0,
    data.avg_claims_extracted || 0,
  ];

  charts.funnel = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: ['rgba(96, 165, 250, 0.7)', 'rgba(52, 211, 153, 0.7)', 'rgba(251, 191, 36, 0.7)'],
        borderColor: ['#60a5fa', '#34d399', '#fbbf24'],
        borderWidth: 1.5,
        borderRadius: 8,
        borderSkipped: false,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: true,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          beginAtZero: true,
          grid: { color: 'rgba(255,255,255,0.03)' },
          ticks: { font: { size: 10 } },
        },
        y: {
          grid: { display: false },
          ticks: { font: { size: 11, weight: '500' } },
        },
      },
      animation: { duration: 600 },
    },
  });
}

function renderPreprocessingTimeline(timeline) {
  const ctx = document.getElementById('pp-timeline-chart');
  if (charts.ppTimeline) charts.ppTimeline.destroy();

  if (!timeline || timeline.length === 0) {
    ctx.parentElement.innerHTML = '<div class="no-data"><span class="no-data-icon">📋</span>No timeline data</div>';
    return;
  }

  const labels = timeline.map(t => t.request_id);

  charts.ppTimeline = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Sentences',
          data: timeline.map(t => t.sentences),
          backgroundColor: 'rgba(96, 165, 250, 0.6)',
          borderColor: '#60a5fa',
          borderWidth: 1,
          borderRadius: 4,
        },
        {
          label: 'Factual',
          data: timeline.map(t => t.factual),
          backgroundColor: 'rgba(52, 211, 153, 0.6)',
          borderColor: '#34d399',
          borderWidth: 1,
          borderRadius: 4,
        },
        {
          label: 'Claims',
          data: timeline.map(t => t.claims),
          backgroundColor: 'rgba(251, 191, 36, 0.6)',
          borderColor: '#fbbf24',
          borderWidth: 1,
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: {
          position: 'top',
          labels: { padding: 16, usePointStyle: true, pointStyleWidth: 8, font: { size: 11 } },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { font: { size: 9 }, maxRotation: 45 },
        },
        y: {
          beginAtZero: true,
          ticks: { stepSize: 1, font: { size: 10 } },
          grid: { color: 'rgba(255,255,255,0.03)' },
        },
      },
      animation: { duration: 600 },
    },
  });
}

// ═══════════════════════════════════════════════════════════════
// PIPELINE TAB
// ═══════════════════════════════════════════════════════════════

async function fetchPipeline() {
  try {
    const res = await fetch(`${API_BASE}/api/analytics/pipeline`);
    if (!res.ok) throw new Error();
    const data = await res.json();
    renderPipeline(data);
  } catch (err) {
    console.error('[Dashboard] Failed to fetch pipeline stats:', err);
  }
}

function renderPipeline(data) {
  const stages = data.stages || {};

  // Stat cards
  const fmtMs = (ms) => ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
  document.getElementById('pl-preprocess').textContent = stages.preprocessing ? fmtMs(stages.preprocessing.avg) : '—';
  document.getElementById('pl-retrieval').textContent = stages.retrieval ? fmtMs(stages.retrieval.avg) : '—';
  document.getElementById('pl-judging').textContent = stages.judging ? fmtMs(stages.judging.avg) : '—';
  document.getElementById('pl-total').textContent = stages.total ? fmtMs(stages.total.avg) : '—';

  // Waterfall chart
  renderWaterfallChart(data.pipeline_timeline || []);

  // Stage share pie
  renderStageShareChart(stages);

  // Percentile cards
  renderPercentileCards(stages);
}

function renderWaterfallChart(timeline) {
  const ctx = document.getElementById('waterfall-chart');
  if (charts.waterfall) charts.waterfall.destroy();

  if (!timeline || timeline.length === 0) {
    ctx.parentElement.innerHTML = '<div class="no-data"><span class="no-data-icon">⚡</span>No pipeline data</div>';
    return;
  }

  const labels = timeline.map(t => t.request_id);

  charts.waterfall = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Preprocessing',
          data: timeline.map(t => t.preprocessing),
          backgroundColor: 'rgba(34, 211, 238, 0.7)',
          borderColor: '#22d3ee',
          borderWidth: 1,
          borderRadius: 3,
        },
        {
          label: 'Retrieval',
          data: timeline.map(t => t.retrieval),
          backgroundColor: 'rgba(96, 165, 250, 0.7)',
          borderColor: '#60a5fa',
          borderWidth: 1,
          borderRadius: 3,
        },
        {
          label: 'LLM Judging',
          data: timeline.map(t => t.judging),
          backgroundColor: 'rgba(167, 139, 250, 0.7)',
          borderColor: '#a78bfa',
          borderWidth: 1,
          borderRadius: 3,
        },
        {
          label: 'Other',
          data: timeline.map(t => t.other),
          backgroundColor: 'rgba(255, 255, 255, 0.08)',
          borderColor: 'rgba(255,255,255,0.15)',
          borderWidth: 1,
          borderRadius: 3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: {
          position: 'top',
          labels: { padding: 16, usePointStyle: true, pointStyleWidth: 8, font: { size: 11 } },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${ctx.raw}ms`,
          },
        },
      },
      scales: {
        x: {
          stacked: true,
          grid: { display: false },
          ticks: { font: { size: 9 }, maxRotation: 45 },
        },
        y: {
          stacked: true,
          beginAtZero: true,
          title: { display: true, text: 'ms', font: { size: 10 }, color: '#555a72' },
          ticks: { font: { size: 10 } },
          grid: { color: 'rgba(255,255,255,0.03)' },
        },
      },
      animation: { duration: 700, easing: 'easeOutQuart' },
    },
  });
}

function renderStageShareChart(stages) {
  const ctx = document.getElementById('stage-share-chart');
  if (charts.stageShare) charts.stageShare.destroy();

  const stageData = [
    { label: 'Preprocessing', avg: stages.preprocessing?.avg || 0, color: '#22d3ee' },
    { label: 'Retrieval', avg: stages.retrieval?.avg || 0, color: '#60a5fa' },
    { label: 'LLM Judging', avg: stages.judging?.avg || 0, color: '#a78bfa' },
  ];

  const totalAvg = stageData.reduce((s, d) => s + d.avg, 0);
  if (totalAvg === 0) {
    ctx.parentElement.innerHTML = '<div class="no-data"><span class="no-data-icon">🍩</span>No stage data</div>';
    return;
  }

  charts.stageShare = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: stageData.map(d => d.label),
      datasets: [{
        data: stageData.map(d => Math.round(d.avg)),
        backgroundColor: stageData.map(d => d.color + 'bb'),
        borderColor: stageData.map(d => d.color),
        borderWidth: 1.5,
        hoverOffset: 8,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      cutout: '62%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: { padding: 14, usePointStyle: true, pointStyleWidth: 8, font: { size: 11 } },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.label}: ${ctx.raw}ms avg`,
          },
        },
      },
      animation: { animateRotate: true, duration: 800 },
    },
  });
}

function renderPercentileCards(stages) {
  const container = document.getElementById('percentile-cards');
  const stageList = ['preprocessing', 'retrieval', 'judging', 'total'];
  const stageLabels = { preprocessing: 'Preprocessing', retrieval: 'Retrieval', judging: 'LLM Judging', total: 'Total Pipeline' };
  const stageColors = { preprocessing: 'cyan', retrieval: 'blue', judging: 'purple', total: 'green' };

  let html = '<div class="percentile-grid">';
  stageList.forEach(key => {
    const s = stages[key] || { avg: 0, p50: 0, min: 0, max: 0 };
    const fmtMs = (ms) => ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
    html += `
      <div class="percentile-item">
        <div class="percentile-stage">${stageLabels[key]}</div>
        <div class="percentile-value percentile-avg">${fmtMs(s.avg)}</div>
        <div class="percentile-label">avg · p50: ${fmtMs(s.p50)}</div>
        <div class="percentile-label">min: ${fmtMs(s.min)} · max: ${fmtMs(s.max)}</div>
      </div>
    `;
  });
  html += '</div>';
  container.innerHTML = html;
}

// ═══════════════════════════════════════════════════════════════
// HISTORY TAB
// ═══════════════════════════════════════════════════════════════

async function fetchHistory() {
  try {
    const res = await fetch(`${API_BASE}/api/analytics/history?limit=100`);
    if (!res.ok) throw new Error();
    const data = await res.json();
    renderHistory(data.events || []);
  } catch (err) {
    console.error('[Dashboard] Failed to fetch history:', err);
  }
}

function renderHistory(events) {
  const tbody = document.getElementById('history-body');
  const search = document.getElementById('history-search');
  const filter = document.getElementById('history-filter');

  function render() {
    const searchTerm = search.value.toLowerCase();
    const verdictFilter = filter.value;

    let filtered = events;
    if (searchTerm) {
      filtered = filtered.filter(e =>
        (e.answer_preview || '').toLowerCase().includes(searchTerm) ||
        (e.question_preview || '').toLowerCase().includes(searchTerm) ||
        (e.verdict || '').toLowerCase().includes(searchTerm)
      );
    }
    if (verdictFilter) {
      filtered = filtered.filter(e => e.verdict === verdictFilter);
    }

    if (filtered.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No verifications found</td></tr>';
      return;
    }

    tbody.innerHTML = filtered.map(e => {
      const time = new Date(e.timestamp).toLocaleString(undefined, {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
      });
      const scoreClass = e.score >= 70 ? 'score-high' : e.score >= 40 ? 'score-mid' : 'score-low';
      const badgeClass = e.verdict === 'accurate' ? 'badge-accurate' : e.verdict === 'hallucination' ? 'badge-hallucination' : 'badge-uncertain';
      const qtBadge = e.query_type ? `<span class="badge-qt badge-qt-${e.query_type}">${(e.query_type || '').replace(/_/g, ' ')}</span>` : '—';
      const sources = (e.sources_used || []).map(s => `<span class="source-tag">${s}</span>`).join('');
      const latency = e.processing_time_ms < 1000 ? `${e.processing_time_ms}ms` : `${(e.processing_time_ms / 1000).toFixed(1)}s`;

      return `<tr>
        <td>${time}</td>
        <td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${e.answer_preview}</td>
        <td><span class="score-cell ${scoreClass}">${e.score}</span></td>
        <td><span class="badge ${badgeClass}">${e.verdict}</span></td>
        <td>${qtBadge}</td>
        <td style="text-align:center;">${e.claims_count || 0}</td>
        <td>${sources || '—'}</td>
        <td class="latency">${latency}</td>
      </tr>`;
    }).join('');
  }

  render();
  search.removeEventListener('input', render);
  filter.removeEventListener('change', render);
  search.addEventListener('input', render);
  filter.addEventListener('change', render);
}

// ═══════════════════════════════════════════════════════════════
// LIVE VERIFY TAB
// ═══════════════════════════════════════════════════════════════

function setupVerify() {
  const btn = document.getElementById('verify-btn');
  const answerInput = document.getElementById('verify-answer');
  const questionInput = document.getElementById('verify-question');
  const resultDiv = document.getElementById('verify-result');
  const loading = document.getElementById('verify-loading');
  const breakdown = document.getElementById('pipeline-breakdown');

  btn.addEventListener('click', async () => {
    const answer = answerInput.value.trim();
    if (!answer) return;

    const question = questionInput.value.trim() || 'Is this factually accurate?';

    btn.disabled = true;
    resultDiv.style.display = 'none';
    breakdown.style.display = 'none';
    loading.style.display = 'flex';

    try {
      const res = await fetch(`${API_BASE}/api/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, answer }),
      });

      if (!res.ok) throw new Error('Server error');
      const data = await res.json();
      renderVerifyResult(data);

      // Fetch the latest history event to get preprocessing details
      try {
        const histRes = await fetch(`${API_BASE}/api/analytics/history?limit=1`);
        if (histRes.ok) {
          const histData = await histRes.json();
          if (histData.events && histData.events.length > 0) {
            renderPipelineBreakdown(histData.events[0]);
          }
        }
      } catch (_) {}

      // Refresh stats
      setTimeout(fetchOverview, 500);
    } catch (err) {
      alert('Verification failed. Is the backend running?');
    } finally {
      btn.disabled = false;
      loading.style.display = 'none';
    }
  });
}

function renderVerifyResult(data) {
  const { score, verdict, explanation, sources_used, processing_time_ms, request_id } = data;
  const resultDiv = document.getElementById('verify-result');
  const header = document.getElementById('vr-header');
  const verdictEl = document.getElementById('vr-verdict');
  const scoreRing = document.getElementById('vr-score-ring');
  const scoreEl = document.getElementById('vr-score');
  const explanationEl = document.getElementById('vr-explanation');
  const sourcesEl = document.getElementById('vr-sources');
  const metaEl = document.getElementById('vr-meta');

  const verdictMap = {
    accurate: '✅ Likely Accurate',
    verified: '✅ Verified',
    uncertain: '⚠️ Uncertain',
    unverifiable: '❓ Unverifiable',
    hallucination: '🚩 Hallucination Detected',
    likely_hallucination: '🚩 Likely Hallucination',
  };
  verdictEl.textContent = verdictMap[verdict] || '❓ Unknown';

  scoreEl.textContent = score;
  const cls = verdict === 'accurate' || verdict === 'verified' ? 'accurate' : verdict === 'hallucination' || verdict === 'likely_hallucination' ? 'hallucination' : 'uncertain';
  header.className = `vr-header ${cls}`;
  scoreRing.className = `vr-score-ring ${score >= 70 ? 'high' : score >= 40 ? 'mid' : 'low'}`;

  explanationEl.textContent = explanation;
  sourcesEl.innerHTML = (sources_used || []).map(s => `<span class="source-tag">${s}</span>`).join('') || '<span class="source-tag">None</span>';

  const latency = processing_time_ms < 1000 ? `${processing_time_ms}ms` : `${(processing_time_ms / 1000).toFixed(1)}s`;
  metaEl.textContent = `Verified in ${latency} · ID: ${(request_id || '').slice(0, 8)}`;

  resultDiv.style.display = 'block';
}

function renderPipelineBreakdown(event) {
  const container = document.getElementById('pipeline-breakdown');
  const grid = document.getElementById('breakdown-grid');

  const fmtMs = (ms) => ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;

  const items = [
    { label: 'Query Type', value: (event.query_type || 'unknown').replace(/_/g, ' '), sub: 'Classification' },
    { label: 'Sentences Found', value: event.sentences_found || 0, sub: 'From answer text' },
    { label: 'Factual Sentences', value: event.factual_sentences || 0, sub: 'Passed filter' },
    { label: 'Claims Extracted', value: event.claims_count || 0, sub: 'Sent for verification' },
    { label: 'Preprocessing', value: fmtMs(event.preprocessing_time_ms || 0), sub: 'Layer 2 timing' },
    { label: 'Evidence Retrieval', value: fmtMs(event.retrieval_time_ms || 0), sub: 'Layer 3 timing' },
    { label: 'LLM Judging', value: fmtMs(event.judge_time_ms || 0), sub: 'Layer 4 timing' },
    { label: 'Evidence Size', value: `${(event.evidence_chars || 0).toLocaleString()} chars`, sub: 'Aggregated evidence' },
  ];

  grid.innerHTML = items.map(item => `
    <div class="breakdown-item">
      <div class="breakdown-item-label">${item.label}</div>
      <div class="breakdown-item-value">${item.value}</div>
      <div class="breakdown-item-sub">${item.sub}</div>
    </div>
  `).join('');

  container.style.display = 'block';
}
