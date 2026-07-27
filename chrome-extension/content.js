/**
 * AI Hallucination Detector - Content Script
 * Runs on all pages. Handles:
 *  - Text selection detection
 *  - Context menu verification (via background.js messages)
 *  - Inline result overlay display
 */

// Sanitize untrusted LLM output before inserting into innerHTML
function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

const HD_API_URL = "https://truthlens-ai-1fwt.onrender.com/api/verify";

// Listen for messages from background script or popup
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "GET_SELECTION") {
    sendResponse({ text: window.getSelection()?.toString() || "" });
  }

  if (message.action === "VERIFY_SELECTION") {
    const text = message.text || window.getSelection()?.toString();
    if (text && text.trim().length > 5) {
      verifyAndShowOverlay(text.trim());
    }
  }

  if (message.action === "SHOW_RESULT") {
    showResultOverlay(message.result);
  }

  return true;
});

/**
 * Call the API and show the result overlay
 */
async function verifyAndShowOverlay(text) {
  showLoadingOverlay();

  try {
    // Get the JWT token from Chrome storage that we saved during login
    const stored = await new Promise((resolve) =>
      chrome.storage.local.get(["truthlens_token"], resolve)
    );
    const token = stored.truthlens_token;

    if (!token) {
      showErrorOverlay("Please sign in from the TruthLens extension popup first.");
      return;
    }

    const res = await fetch(HD_API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`
      },
      body: JSON.stringify({
        question: "Is this statement factually accurate?",
        answer: text,
      }),
    });

    if (res.status === 401) {
      await new Promise(resolve => chrome.storage.local.remove(["truthlens_token", "truthlens_email", "truthlens_google_token"], resolve));
      showErrorOverlay("Session expired. Please click the TruthLens icon to sign in again.");
      return;
    }

    if (!res.ok) throw new Error("Server error");

    const data = await res.json();
    showResultOverlay(data);
  } catch (err) {
    showErrorOverlay("Cannot connect to verification server. Ensure the backend is running.");
  }
}

/**
 * Inject shared styles (idempotent)
 */
function injectOverlayStyles() {
  if (document.getElementById("hd-overlay-styles")) return;

  const style = document.createElement("style");
  style.id = "hd-overlay-styles";
  style.textContent = `
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    #hd-overlay {
      position: fixed;
      top: 16px;
      right: 16px;
      width: 340px;
      background: #ffffff;
      border-radius: 14px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.06);
      z-index: 2147483647;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 13px;
      color: #1a1a2e;
      overflow: hidden;
      animation: hdOverlayIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
      -webkit-font-smoothing: antialiased;
    }

    @keyframes hdOverlayIn {
      from {
        opacity: 0;
        transform: translateY(-8px) scale(0.97);
      }
      to {
        opacity: 1;
        transform: translateY(0) scale(1);
      }
    }

    @keyframes hdOverlayOut {
      from {
        opacity: 1;
        transform: translateY(0) scale(1);
      }
      to {
        opacity: 0;
        transform: translateY(-8px) scale(0.97);
      }
    }

    /* Header bar */
    #hd-overlay .hdo-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 14px;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    }

    #hd-overlay .hdo-header-left {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    #hd-overlay .hdo-logo {
      width: 22px;
      height: 22px;
      background: rgba(255,255,255,0.2);
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    #hd-overlay .hdo-logo svg {
      width: 13px;
      height: 13px;
      color: white;
    }

    #hd-overlay .hdo-title {
      font-size: 12px;
      font-weight: 600;
      color: white;
      letter-spacing: -0.1px;
    }

    #hd-overlay .hdo-close {
      background: rgba(255,255,255,0.15);
      border: none;
      width: 22px;
      height: 22px;
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: background 0.15s;
      color: rgba(255,255,255,0.8);
      font-size: 14px;
      line-height: 1;
      padding: 0;
    }

    #hd-overlay .hdo-close:hover {
      background: rgba(255,255,255,0.25);
      color: white;
    }

    /* Body */
    #hd-overlay .hdo-body {
      padding: 14px;
    }

    /* Verdict row */
    #hd-overlay .hdo-verdict-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;
    }

    #hd-overlay .hdo-verdict {
      font-size: 14px;
      font-weight: 600;
      letter-spacing: -0.2px;
    }

    #hd-overlay .hdo-verdict.accurate { color: #0d7a3e; }
    #hd-overlay .hdo-verdict.uncertain { color: #b8860b; }
    #hd-overlay .hdo-verdict.hallucination { color: #c53030; }

    /* Score ring */
    #hd-overlay .hdo-score {
      width: 44px;
      height: 44px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 16px;
      font-weight: 700;
      color: white;
      flex-shrink: 0;
    }

    #hd-overlay .hdo-score.high { background: linear-gradient(135deg, #0d7a3e, #28a745); }
    #hd-overlay .hdo-score.mid  { background: linear-gradient(135deg, #d4a017, #f0c040); color: #5a4800; }
    #hd-overlay .hdo-score.low  { background: linear-gradient(135deg, #c53030, #e53e3e); }

    /* Explanation */
    #hd-overlay .hdo-explanation {
      font-size: 12px;
      color: #495057;
      line-height: 1.65;
      margin-bottom: 12px;
    }

    /* Sources */
    #hd-overlay .hdo-sources {
      padding-top: 10px;
      border-top: 1px solid #f0f0f0;
    }

    #hd-overlay .hdo-sources-label {
      font-size: 10px;
      font-weight: 600;
      color: #adb5bd;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 6px;
    }

    #hd-overlay .hdo-source-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }

    #hd-overlay .hdo-tag {
      font-size: 11px;
      padding: 2px 8px;
      background: #f1f3f5;
      border: 1px solid #e9ecef;
      border-radius: 10px;
      color: #5f6368;
    }

    /* Loading state */
    #hd-overlay .hdo-loading {
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 28px 16px;
      gap: 10px;
    }

    #hd-overlay .hdo-spinner {
      width: 26px;
      height: 26px;
      border: 2.5px solid #e8ecf1;
      border-top-color: #667eea;
      border-radius: 50%;
      animation: hdSpin 0.7s linear infinite;
    }

    @keyframes hdSpin {
      to { transform: rotate(360deg); }
    }

    #hd-overlay .hdo-loading-text {
      font-size: 12px;
      color: #5f6368;
    }

    /* Error state */
    #hd-overlay .hdo-error {
      padding: 16px;
      display: flex;
      align-items: flex-start;
      gap: 10px;
    }

    #hd-overlay .hdo-error-icon {
      font-size: 16px;
      flex-shrink: 0;
      margin-top: 1px;
    }

    #hd-overlay .hdo-error-text {
      font-size: 12px;
      color: #c53030;
      line-height: 1.5;
    }

    /* Per-claim cards */
    #hd-overlay .hdo-claims-title {
      font-size: 10px;
      font-weight: 600;
      color: #adb5bd;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin: 10px 0 6px;
      padding-top: 10px;
      border-top: 1px solid #f0f0f0;
    }

    #hd-overlay .hdo-claim-card {
      padding: 8px 10px;
      margin-bottom: 4px;
      border-radius: 6px;
      border-left: 3px solid;
      background: #f8f9fa;
    }

    #hd-overlay .hdo-claim-card.accurate {
      border-left-color: #0d7a3e;
      background: #f0faf4;
    }

    #hd-overlay .hdo-claim-card.uncertain {
      border-left-color: #d4a017;
      background: #fefdf5;
    }

    #hd-overlay .hdo-claim-card.hallucination {
      border-left-color: #c53030;
      background: #fff5f5;
    }

    #hd-overlay .hdo-claim-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 3px;
    }

    #hd-overlay .hdo-claim-verdict {
      font-size: 11px;
      font-weight: 600;
    }

    #hd-overlay .hdo-claim-card.accurate .hdo-claim-verdict { color: #0d7a3e; }
    #hd-overlay .hdo-claim-card.uncertain .hdo-claim-verdict { color: #b8860b; }
    #hd-overlay .hdo-claim-card.hallucination .hdo-claim-verdict { color: #c53030; }

    #hd-overlay .hdo-claim-score {
      width: 24px;
      height: 24px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 10px;
      font-weight: 700;
      color: white;
      flex-shrink: 0;
    }

    #hd-overlay .hdo-claim-score.high { background: linear-gradient(135deg, #0d7a3e, #28a745); }
    #hd-overlay .hdo-claim-score.mid { background: linear-gradient(135deg, #d4a017, #f0c040); color: #5a4800; }
    #hd-overlay .hdo-claim-score.low { background: linear-gradient(135deg, #c53030, #e53e3e); }

    #hd-overlay .hdo-claim-text {
      font-size: 11px;
      color: #495057;
      line-height: 1.4;
      font-style: italic;
    }

    #hd-overlay .hdo-claim-explanation {
      font-size: 10px;
      color: #6c757d;
      line-height: 1.3;
    }
  `;
  document.head.appendChild(style);
}

/**
 * Remove existing overlay
 */
function removeOverlay() {
  const existing = document.getElementById("hd-overlay");
  if (existing) {
    existing.style.animation = "hdOverlayOut 0.2s ease-in forwards";
    setTimeout(() => existing.remove(), 200);
  }
}

/**
 * Create the overlay shell with header
 */
function createOverlayShell() {
  removeOverlay();
  injectOverlayStyles();

  const overlay = document.createElement("div");
  overlay.id = "hd-overlay";
  overlay.innerHTML = `
    <div class="hdo-header">
      <div class="hdo-header-left">
        <div class="hdo-logo">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
            <path d="M9 12l2 2 4-4"></path>
          </svg>
        </div>
        <span class="hdo-title">Hallucination Detector</span>
      </div>
      <button class="hdo-close" aria-label="Close">&times;</button>
    </div>
    <div class="hdo-body"></div>
  `;

  document.body.appendChild(overlay);

  overlay.querySelector(".hdo-close").addEventListener("click", removeOverlay);

  return overlay;
}

/**
 * Show loading state
 */
function showLoadingOverlay() {
  const overlay = createOverlayShell();
  overlay.querySelector(".hdo-body").innerHTML = `
    <div class="hdo-loading">
      <div class="hdo-spinner"></div>
      <span class="hdo-loading-text">Verifying claims...</span>
    </div>
  `;
}

/**
 * Show error state
 */
function showErrorOverlay(message) {
  const overlay = createOverlayShell();
  overlay.querySelector(".hdo-body").innerHTML = `
    <div class="hdo-error">
      <span class="hdo-error-icon">⚠️</span>
      <span class="hdo-error-text">${message}</span>
    </div>
  `;
  autoClose(overlay, 8000);
}

/**
 * Show the verification result
 */
function showResultOverlay(result) {
  const { score, verdict, explanation, sources_used, claim_results } = result;

  const overlay = createOverlayShell();

  // Classify
  const verdictMap = {
    accurate: { text: "✅ Likely Accurate", cls: "accurate" },
    verified: { text: "✅ Verified", cls: "accurate" },
    uncertain: { text: "⚠️ Uncertain", cls: "uncertain" },
    unverifiable: { text: "❓ Unverifiable", cls: "uncertain" },
    hallucination: { text: "🚩 Hallucination Detected", cls: "hallucination" },
    likely_hallucination: { text: "🚩 Likely Hallucination", cls: "hallucination" },
  };

  const v = verdictMap[verdict] || { text: "❓ Unknown", cls: "uncertain" };

  let scoreClass = "mid";
  if (score >= 70) scoreClass = "high";
  else if (score < 40) scoreClass = "low";

  // Sources
  const sourceTags = (sources_used && sources_used.length > 0)
    ? sources_used.map(s => `<span class="hdo-tag">${s}</span>`).join("")
    : '<span class="hdo-tag">None</span>';

  // Per-claim cards
  let claimsHTML = "";
  if (claim_results && claim_results.length > 0) {
    const verdictLabels = {
      accurate: "✅ Accurate",
      uncertain: "⚠️ Uncertain",
      hallucination: "🚩 Hallucination",
    };
    claimsHTML = '<div class="hdo-claims-title">Per-Claim Breakdown</div>';
    claim_results.forEach((claim) => {
      const claimScoreClass = claim.score >= 70 ? "high" : claim.score >= 40 ? "mid" : "low";
      const claimVerdict = verdictLabels[claim.verdict] || "❓ Unknown";
      claimsHTML += `
        <div class="hdo-claim-card ${claim.verdict}">
          <div class="hdo-claim-header">
            <span class="hdo-claim-verdict">${claimVerdict}</span>
            <div class="hdo-claim-score ${claimScoreClass}">${claim.score}</div>
          </div>
          <div class="hdo-claim-text">"${escapeHTML(claim.claim_text)}"</div>
          <div class="hdo-claim-explanation">${escapeHTML(claim.explanation)}</div>
        </div>
      `;
    });
  }

  overlay.querySelector(".hdo-body").innerHTML = `
    <div class="hdo-verdict-row">
      <span class="hdo-verdict ${v.cls}">${v.text}</span>
      <div class="hdo-score ${scoreClass}">${score}</div>
    </div>
    <p class="hdo-explanation">${explanation}</p>
    <div class="hdo-sources">
      <div class="hdo-sources-label">Sources</div>
      <div class="hdo-source-tags">${sourceTags}</div>
    </div>
    ${claimsHTML}
  `;

  autoClose(overlay, 20000);
}

/**
 * Auto-close overlay after a delay
 */
function autoClose(overlay, ms) {
  setTimeout(() => {
    if (document.getElementById("hd-overlay")) {
      removeOverlay();
    }
  }, ms);
}

// Debug log
console.log("[AI Hallucination Detector] Content script loaded");
