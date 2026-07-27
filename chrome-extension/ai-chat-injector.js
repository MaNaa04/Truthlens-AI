/**
 * AI Chat Injector - Adds "Verify" buttons to AI chat interfaces
 * Works with: ChatGPT, Claude, Gemini, Perplexity, etc.
 * Displays results in a right-side panel (like Gemini)
 */

// Sanitize untrusted LLM output before inserting into innerHTML
function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

const API_URL = "https://truthlens-ai-1fwt.onrender.com/api/verify";
let isInjecting = false;

// Create and manage right-side panel
let rightPanel = null;

function createRightPanel() {
  if (rightPanel && document.body.contains(rightPanel)) {
    return rightPanel;
  }

  const panel = document.createElement("div");
  panel.id = "hd-right-panel";
  panel.innerHTML = `
    <div id="hd-panel-header">
      <h3 id="hd-panel-title">Fact Check Results</h3>
      <button id="hd-panel-close" aria-label="Close">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
      </button>
    </div>
    <div id="hd-panel-content"></div>
  `;

  // Panel styles
  const styles = `
    #hd-right-panel {
      position: fixed;
      right: 0;
      top: 0;
      width: 420px;
      height: 100vh;
      background: white;
      box-shadow: -2px 0 12px rgba(0, 0, 0, 0.15);
      display: flex;
      flex-direction: column;
      z-index: 9999;
      animation: hd-slide-in 0.3s ease-out;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
    }

    @keyframes hd-slide-in {
      from {
        transform: translateX(100%);
        opacity: 0;
      }
      to {
        transform: translateX(0);
        opacity: 1;
      }
    }

    @keyframes hd-slide-out {
      from {
        transform: translateX(0);
        opacity: 1;
      }
      to {
        transform: translateX(100%);
        opacity: 0;
      }
    }

    #hd-panel-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 16px;
      border-bottom: 1px solid #e5e5e5;
      background: #f8f9fa;
    }

    #hd-panel-title {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
      color: #202124;
    }

    #hd-panel-close {
      background: none;
      border: none;
      padding: 4px;
      cursor: pointer;
      color: #5f6368;
      transition: color 0.2s;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    #hd-panel-close:hover {
      color: #202124;
    }

    #hd-panel-content {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
    }

    .hd-panel-result {
      background: white;
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 16px;
      border: 1px solid #e5e5e5;
    }

    .hd-result-score {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;
    }

    .hd-result-verdict {
      font-size: 16px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 8px;
      color: #202124;
    }

    .hd-score-circle {
      width: 56px;
      height: 56px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 20px;
      color: white;
    }

    .hd-score-verified {
      background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
    }

    .hd-score-uncertain {
      background: linear-gradient(135deg, #ffc107 0%, #ff9800 100%);
    }

    .hd-score-hallucination {
      background: linear-gradient(135deg, #dc3545 0%, #c82333 100%);
    }

    .hd-result-explanation {
      font-size: 13px;
      color: #5f6368;
      line-height: 1.6;
      margin-bottom: 12px;
    }

    .hd-result-sources {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .hd-source-badge {
      display: inline-block;
      background: #f1f3f4;
      padding: 4px 10px;
      border-radius: 12px;
      font-size: 12px;
      color: #5f6368;
      border: 1px solid #dadce0;
    }

    .hd-loading {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 40px 16px;
      color: #5f6368;
    }

    .hd-spinner {
      width: 32px;
      height: 32px;
      border: 3px solid #dadce0;
      border-top: 3px solid #667eea;
      border-radius: 50%;
      animation: hd-spin 1s linear infinite;
      margin-bottom: 12px;
    }

    @keyframes hd-spin {
      0% { transform: rotate(0deg); }
      100% { transform: rotate(360deg); }
    }

    .hd-error {
      display: flex;
      align-items: center;
      gap: 12px;
      background: #ffebee;
      padding: 16px;
      border-radius: 8px;
      border: 1px solid #ef5350;
    }

    .hd-error-icon {
      color: #dc3545;
      font-size: 20px;
    }

    .hd-error-text {
      color: #5f6368;
      font-size: 13px;
    }

    .hd-dashboard-link {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      margin-top: 16px;
      padding: 10px 16px;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      text-decoration: none;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      transition: all 0.2s ease;
      cursor: pointer;
      border: none;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }

    .hd-dashboard-link:hover {
      box-shadow: 0 4px 12px rgba(102, 126, 234, 0.35);
      transform: translateY(-1px);
    }

    .hd-dashboard-links {
      display: flex;
      gap: 8px;
      margin-top: 12px;
    }

    .hd-dashboard-link-secondary {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 8px 14px;
      background: #f1f3f4;
      color: #5f6368;
      text-decoration: none;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 500;
      transition: all 0.2s ease;
      cursor: pointer;
      border: 1px solid #dadce0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      flex: 1;
      text-align: center;
    }

    .hd-dashboard-link-secondary:hover {
      background: #e8eaed;
      color: #202124;
    }

    /* Responsive for smaller screens */
    @media (max-width: 1024px) {
      #hd-right-panel {
        width: 360px;
      }
    }

    @media (max-width: 768px) {
      #hd-right-panel {
        width: 100%;
      }
    }

    /* Per-claim cards */
    .hd-claims-title {
      font-size: 12px;
      font-weight: 600;
      color: #5f6368;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin: 12px 0 8px;
      padding-top: 12px;
      border-top: 1px solid #e5e5e5;
    }

    .hd-claim-card {
      padding: 10px 12px;
      margin-bottom: 6px;
      border-radius: 8px;
      border-left: 3px solid;
      background: #f8f9fa;
    }

    .hd-claim-card.accurate {
      border-left-color: #28a745;
      background: #f6fef8;
    }

    .hd-claim-card.uncertain {
      border-left-color: #ffc107;
      background: #fffdf5;
    }

    .hd-claim-card.hallucination {
      border-left-color: #dc3545;
      background: #fff5f5;
    }

    .hd-claim-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 4px;
    }

    .hd-claim-verdict {
      font-size: 12px;
      font-weight: 600;
    }

    .hd-claim-card.accurate .hd-claim-verdict { color: #155724; }
    .hd-claim-card.uncertain .hd-claim-verdict { color: #856404; }
    .hd-claim-card.hallucination .hd-claim-verdict { color: #721c24; }

    .hd-claim-score {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      font-weight: 700;
      color: white;
      flex-shrink: 0;
    }

    .hd-claim-score.high { background: linear-gradient(135deg, #28a745, #20c997); }
    .hd-claim-score.mid { background: linear-gradient(135deg, #ffc107, #ff9800); }
    .hd-claim-score.low { background: linear-gradient(135deg, #dc3545, #c82333); }

    .hd-claim-text {
      font-size: 12px;
      color: #495057;
      line-height: 1.5;
      margin-bottom: 2px;
      font-style: italic;
    }

    .hd-claim-explanation {
      font-size: 11px;
      color: #6c757d;
      line-height: 1.4;
    }
  `;

  const styleSheet = document.createElement("style");
  styleSheet.textContent = styles;
  document.head.appendChild(styleSheet);

  document.body.appendChild(panel);

  // Close button handler
  panel.querySelector("#hd-panel-close").addEventListener("click", closeRightPanel);

  rightPanel = panel;
  return panel;
}

function closeRightPanel() {
  if (rightPanel) {
    rightPanel.style.animation = "hd-slide-out 0.3s ease-out";
    setTimeout(() => {
      if (rightPanel && document.body.contains(rightPanel)) {
        rightPanel.remove();
      }
      rightPanel = null;
    }, 300);
  }
}

// Detect which AI platform we're on
const AI_PLATFORMS = {
  chatgpt: {
    match: () => window.location.hostname.includes("chatgpt.com") || window.location.hostname.includes("chat.openai.com"),
    messageSelector: 'div[data-message-author-role="assistant"] .markdown',
    containerSelector: 'div[data-message-author-role="assistant"]',
  },
  claude: {
    match: () => window.location.hostname.includes("claude.ai"),
    messageSelector: 'div[data-is-streaming="false"] .font-claude-message',
    containerSelector: 'div[data-is-streaming="false"]',
  },
  gemini: {
    match: () => window.location.hostname.includes("gemini.google.com"),
    messageSelector: 'infinite-scroller.chat-history [aria-label*="Gemini said"]',
    containerSelector: 'infinite-scroller.chat-history',
    // Custom finder for Gemini — the only reliable method for the current Angular DOM
    customFinder: () => {
      const responses = [];
      const seen = new Set();

      // Primary: Find response turns via "Gemini said" ARIA label
      document.querySelectorAll('[aria-label*="Gemini"]').forEach(el => {
        // Walk up to find the turn-level container (direct child of chat-history / infinite-scroller)
        let turn = el;
        while (turn.parentElement && turn.parentElement.tagName !== 'INFINITE-SCROLLER' && !turn.parentElement.classList.contains('chat-history')) {
          turn = turn.parentElement;
        }
        if (turn && !seen.has(turn)) {
          seen.add(turn);
          responses.push(turn);
        }
      });

      // Fallback: Look for containers with the action buttons (Redo/Copy) that mark model responses
      if (responses.length === 0) {
        document.querySelectorAll('.icon-button[aria-label="Copy"], .icon-button[aria-label="Redo"]').forEach(btn => {
          let turn = btn;
          while (turn.parentElement && turn.parentElement.tagName !== 'INFINITE-SCROLLER' && !turn.parentElement.classList.contains('chat-history')) {
            turn = turn.parentElement;
          }
          if (turn && !seen.has(turn)) {
            seen.add(turn);
            responses.push(turn);
          }
        });
      }

      return responses;
    },
  },
  perplexity: {
    match: () => window.location.hostname.includes("perplexity.ai"),
    messageSelector: '.prose',
    containerSelector: '.answer-container',
  },
};

// Get current platform
function getCurrentPlatform() {
  for (const [name, config] of Object.entries(AI_PLATFORMS)) {
    if (config.match()) {
      return { name, ...config };
    }
  }
  return null;
}

// Initialize injector
function init() {
  const platform = getCurrentPlatform();
  if (!platform) {
    console.log("[Hallucination Detector] Not on a supported AI platform");
    return;
  }

  console.log(`[Hallucination Detector] Detected platform: ${platform.name}`);

  // Watch for new messages
  const observer = new MutationObserver(() => {
    if (!isInjecting) {
      isInjecting = true;
      setTimeout(() => {
        injectButtons(platform);
        isInjecting = false;
      }, 500);
    }
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
  });

  // Initial injection
  setTimeout(() => injectButtons(platform), 1000);
}

// Inject verify buttons
function injectButtons(platform) {
  // Use custom finder for Gemini, fallback to standard selectors
  if (platform.customFinder) {
    const containers = platform.customFinder();
    containers.forEach((container) => {
      if (container.querySelector(".hd-verify-btn")) return;
      const text = container.textContent.trim();
      if (text.length < 20) return;
      const button = createVerifyButton(text);
      insertButton(container, button, platform.name);
    });
  }

  // Also try standard selectors as fallback
  const messages = document.querySelectorAll(platform.messageSelector);
  messages.forEach((message) => {
    const container = message.closest(platform.containerSelector) || message;
    if (!container || container.querySelector(".hd-verify-btn")) {
      return;
    }
    const text = message.textContent.trim();
    if (text.length < 20) return;
    const button = createVerifyButton(text);
    insertButton(container, button, platform.name);
  });
}

// Create styled verify button
function createVerifyButton(text) {
  const button = document.createElement("button");
  button.className = "hd-verify-btn";
  button.innerHTML = `
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
      <path d="M9 12l2 2 4-4"></path>
    </svg>
    Verify
  `;

  // Add styles — clean, minimal, unobtrusive
  Object.assign(button.style, {
    display: "inline-flex",
    alignItems: "center",
    gap: "5px",
    padding: "4px 10px",
    fontSize: "12px",
    fontWeight: "500",
    letterSpacing: "0.2px",
    color: "#5f6368",
    background: "rgba(95,99,104,0.08)",
    border: "none",
    borderRadius: "16px",
    cursor: "pointer",
    transition: "all 0.2s ease",
    marginTop: "6px",
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    lineHeight: "1",
  });

  button.addEventListener("mouseenter", () => {
    button.style.background = "#667eea";
    button.style.color = "white";
    button.style.boxShadow = "0 1px 4px rgba(102,126,234,0.3)";
  });

  button.addEventListener("mouseleave", () => {
    button.style.background = "rgba(95,99,104,0.08)";
    button.style.color = "#5f6368";
    button.style.boxShadow = "none";
  });

  button.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    verifyText(text, button);
  });

  return button;
}

// Insert button into container
function insertButton(container, button, platform) {
  if (platform === "gemini") {
    // Find Gemini's action bar (contains Redo, Copy, More Options buttons with mat-mdc classes)
    const actionBtn = container.querySelector('.icon-button[aria-label="Copy"], .icon-button[aria-label="Redo"], .more-menu-button');
    if (actionBtn) {
      // Find the parent bar that holds these action buttons
      const actionBar = actionBtn.closest('div');
      if (actionBar) {
        // Insert button as a sibling inside the action bar
        actionBar.appendChild(button);
        // Adjust styling to look inline with Gemini's native action buttons
        button.style.marginTop = "0";
        button.style.marginLeft = "8px";
      } else {
        container.appendChild(button);
      }
    } else {
      container.appendChild(button);
    }
  } else {
    container.appendChild(button);
  }
}

// Verify text via API
async function verifyText(text, button) {
  // Open right panel with loading state
  const panel = createRightPanel();
  const content = panel.querySelector("#hd-panel-content");

  content.innerHTML = `
    <div class="hd-loading">
      <div class="hd-spinner"></div>
      <div>Checking facts...</div>
    </div>
  `;

  button.disabled = true;
  button.style.opacity = "0.6";

  try {
    // Get the JWT token from Chrome storage
    const stored = await new Promise((resolve) =>
      chrome.storage.local.get(["truthlens_token"], resolve)
    );
    const token = stored.truthlens_token;

    if (!token) {
      throw new Error("Not logged in. Please click the TruthLens extension icon in your browser toolbar to sign in.");
    }

    const response = await fetch(API_URL, {
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

    if (response.status === 401) {
      await new Promise(resolve => chrome.storage.local.remove(["truthlens_token", "truthlens_email", "truthlens_google_token"], resolve));
      throw new Error("Session expired. Please click the TruthLens icon to sign in again.");
    }

    if (!response.ok) {
      throw new Error("Server error");
    }

    const data = await response.json();
    showResultInPanel(data);
    button.disabled = false;
    button.style.opacity = "1";
  } catch (err) {
    console.error("[Hallucination Detector] Error:", err);

    content.innerHTML = `
      <div class="hd-error">
        <div class="hd-error-icon">⚠️</div>
        <div class="hd-error-text">
          Cannot connect to server. The server may be waking up — please wait 30 seconds and try again.
        </div>
      </div>
    `;

    button.disabled = false;
    button.style.opacity = "1";
  }
}

// Show verification result in right panel
function showResultInPanel(data) {
  const { score, verdict, explanation, sources_used, claim_results } = data;
  const panel = createRightPanel();
  const content = panel.querySelector("#hd-panel-content");

  // Determine score category for styling
  let scoreClass = "hd-score-uncertain";
  if (score >= 75) scoreClass = "hd-score-verified";
  else if (score < 40) scoreClass = "hd-score-hallucination";

  // Verdict display
  const verdictText = {
    verified: "✅ Verified",
    accurate: "✅ Likely Accurate",
    uncertain: "⚠️ Uncertain",
    unverifiable: "❓ Unverifiable",
    hallucination: "🚩 Hallucination Detected",
    likely_hallucination: "🚩 Likely Hallucination",
  }[verdict] || "❓ Uncertain";

  // Build sources HTML
  let sourcesHTML = "";
  if (sources_used && sources_used.length > 0) {
    const sourceBadges = sources_used
      .map((source) => `<span class="hd-source-badge">${source}</span>`)
      .join("");
    sourcesHTML = `
      <div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid #e5e5e5;">
        <div style="font-size: 12px; color: #5f6368; font-weight: 500; margin-bottom: 8px;">Sources Used:</div>
        <div class="hd-result-sources">
          ${sourceBadges}
        </div>
      </div>
    `;
  }

  // Build per-claim HTML
  let claimsHTML = "";
  if (claim_results && claim_results.length > 0) {
    const verdictLabels = {
      accurate: "✅ Accurate",
      uncertain: "⚠️ Uncertain",
      hallucination: "🚩 Hallucination",
    };

    claimsHTML = '<div class="hd-claims-title">Per-Claim Breakdown</div>';
    claim_results.forEach((claim) => {
      const claimScoreClass = claim.score >= 70 ? "high" : claim.score >= 40 ? "mid" : "low";
      const claimVerdict = verdictLabels[claim.verdict] || "❓ Unknown";
      claimsHTML += `
        <div class="hd-claim-card ${claim.verdict}">
          <div class="hd-claim-header">
            <span class="hd-claim-verdict">${claimVerdict}</span>
            <div class="hd-claim-score ${claimScoreClass}">${claim.score}</div>
          </div>
          <div class="hd-claim-text">"${escapeHTML(claim.claim_text)}"</div>
          <div class="hd-claim-explanation">${escapeHTML(claim.explanation)}</div>
        </div>
      `;
    });
  }

  content.innerHTML = `
    <div class="hd-panel-result">
      <div class="hd-result-score">
        <div class="hd-result-verdict">${verdictText}</div>
        <div class="hd-score-circle ${scoreClass}">${score}</div>
      </div>
      <div class="hd-result-explanation">
        ${explanation}
      </div>
      ${sourcesHTML}
      ${claimsHTML}
    </div>

    <div style="padding: 0 16px; margin-top: 24px;">
      <div style="font-size: 13px; color: #5f6368; line-height: 1.6;">
        <strong>Score Interpretation:</strong><br>
        75-100: Highly reliable<br>
        50-74: Mixed reliability<br>
        0-49: Low reliability
      </div>

      <a href="https://truthlens-ai-1fwt.onrender.com/analytics" target="_blank" class="hd-dashboard-link">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"></rect><rect x="14" y="3" width="7" height="7" rx="1"></rect><rect x="3" y="14" width="7" height="7" rx="1"></rect><rect x="14" y="14" width="7" height="7" rx="1"></rect></svg>
        Open Analytics Dashboard
      </a>
      <div class="hd-dashboard-links">
        <a href="https://truthlens-ai-1fwt.onrender.com/dashboard" target="_blank" class="hd-dashboard-link-secondary">Basic Dashboard</a>
        <a href="https://truthlens-ai-1fwt.onrender.com/docs" target="_blank" class="hd-dashboard-link-secondary">API Docs</a>
      </div>
    </div>
  `;
}

// Initialize when page loads
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}

console.log("[Hallucination Detector] Content script loaded");
