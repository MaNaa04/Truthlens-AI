const API_BASE = "http://localhost:8000";
const API_VERIFY_URL = `${API_BASE}/api/verify`;
const API_AUTH_URL = `${API_BASE}/api/auth/google-login`;

// Your Google OAuth2 Client ID (Web application type — required for launchWebAuthFlow)
const GOOGLE_CLIENT_ID = "98951432384-4robp9v8sage20tada34r4e7utj83osq.apps.googleusercontent.com";

/**
 * Opens a real Google sign-in popup with account picker using launchWebAuthFlow.
 * The user always sees the Google account selector (prompt=select_account).
 * Returns the Google OAuth2 access token.
 */
async function getGoogleTokenViaWebFlow() {
  // The redirect URI Chrome expects for extensions using launchWebAuthFlow
  const redirectUri = `https://${chrome.runtime.id}.chromiumapp.org/`;

  const authUrl = new URL("https://accounts.google.com/o/oauth2/auth");
  authUrl.searchParams.set("client_id", GOOGLE_CLIENT_ID);
  authUrl.searchParams.set("redirect_uri", redirectUri);
  authUrl.searchParams.set("response_type", "token");  // Implicit flow — returns access_token in URL hash
  authUrl.searchParams.set("scope", "openid email profile");
  authUrl.searchParams.set("prompt", "select_account"); // Always show the account picker

  return new Promise((resolve, reject) => {
    chrome.identity.launchWebAuthFlow(
      { url: authUrl.toString(), interactive: true },
      (redirectedTo) => {
        if (chrome.runtime.lastError || !redirectedTo) {
          reject(new Error(chrome.runtime.lastError?.message || "Auth popup was closed"));
          return;
        }
        // The access_token is in the URL hash: #access_token=...&token_type=Bearer&...
        const hashParams = new URLSearchParams(new URL(redirectedTo).hash.substring(1));
        const token = hashParams.get("access_token");
        if (token) {
          resolve(token);
        } else {
          reject(new Error("No access_token found in Google response"));
        }
      }
    );
  });
}

// Sanitize untrusted LLM output before inserting into innerHTML
function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// â”€â”€ Auth helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function getStoredAuth() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["truthlens_token", "truthlens_email"], (result) => {
      resolve({
        token: result.truthlens_token || null,
        email: result.truthlens_email || null,
      });
    });
  });
}

function saveAuth(token, email, googleToken) {
  return new Promise((resolve) => {
    chrome.storage.local.set({
      truthlens_token: token,
      truthlens_email: email,
      truthlens_google_token: googleToken, // stored so logout can revoke it
    }, resolve);
  });
}

function clearAuth() {
  return new Promise((resolve) => {
    chrome.storage.local.remove(["truthlens_token", "truthlens_email", "truthlens_google_token"], resolve);
  });
}

// â”€â”€ UI state helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

const GOOGLE_BTN_HTML = `
  <svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg" style="width:18px;height:18px;flex-shrink:0">
    <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
    <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
    <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
    <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
  </svg>
  Sign in with Google`;

function showLoginScreen() {
  document.getElementById("login-screen").classList.add("active");
  document.getElementById("main-content").style.display = "none";
  document.getElementById("user-bar").classList.remove("active");
  document.getElementById("status-bar").style.display = "none";
  // Always reset the button so it's never stuck on "Signing in..."
  const btn = document.getElementById("google-login-btn");
  btn.disabled = false;
  btn.innerHTML = GOOGLE_BTN_HTML;
}

function showMainUI(email) {
  document.getElementById("login-screen").classList.remove("active");
  document.getElementById("main-content").style.display = "block";
  document.getElementById("user-bar").classList.add("active");
  document.getElementById("status-bar").style.display = "flex";
  document.getElementById("user-email").textContent = email;
  checkBackend();
}

async function checkBackend() {
  const statusDot = document.getElementById("status-dot");
  const statusText = document.getElementById("status-text");
  try {
    const res = await fetch(`${API_BASE}/`, { method: "GET" });
    if (res.ok) {
      statusDot.classList.remove("offline");
      statusText.textContent = "Backend connected";
    } else {
      throw new Error();
    }
  } catch {
    statusDot.classList.add("offline");
    statusText.textContent = "Backend offline — start the server";
  }
}

// â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

document.addEventListener("DOMContentLoaded", async () => {
  // Check if the user is already logged in
  const { token, email } = await getStoredAuth();
  if (token && email) {
    showMainUI(email);
  } else {
    showLoginScreen();
  }

  // â”€â”€ Google Sign-In button â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  document.getElementById("google-login-btn").addEventListener("click", async () => {
    const btn = document.getElementById("google-login-btn");
    btn.disabled = true;
    btn.textContent = "Signing in...";

    try {
      // Step 1: Open Google account picker and get access token
      const googleToken = await getGoogleTokenViaWebFlow();

      // Step 2: Exchange Google token for TruthLens JWT via our backend
      const resp = await fetch(API_AUTH_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ google_token: googleToken }),
      });

      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || "Login failed");
      }

      const data = await resp.json();

      // Step 3: Cache the TruthLens JWT + Google token (for revocation on logout)
      await saveAuth(data.access_token, data.email, googleToken);
      showMainUI(data.email);

    } catch (err) {
      console.error("Login error:", err);
      btn.disabled = false;
      btn.innerHTML = GOOGLE_BTN_HTML;

      const errDiv = document.createElement("div");
      errDiv.style.cssText = "color:#c53030;font-size:12px;margin-top:8px;text-align:center;";
      errDiv.textContent = err.message.includes("client_id")
        ? "⚠️ Google Client ID not configured yet. See setup instructions."
        : `Sign-in failed: ${err.message}`;
      document.getElementById("login-screen").appendChild(errDiv);
      setTimeout(() => errDiv.remove(), 5000);
    }
  });

  // ── Logout button ───────────────────────────────────────────────────────────
  document.getElementById("logout-btn").addEventListener("click", async () => {
    // Revoke the stored Google token so next sign-in shows account picker cleanly
    const stored = await new Promise((resolve) =>
      chrome.storage.local.get(["truthlens_google_token"], resolve)
    );
    const googleToken = stored.truthlens_google_token;
    if (googleToken) {
      // Revoke on Google's servers (fire and forget)
      fetch(`https://oauth2.googleapis.com/revoke?token=${googleToken}`, {
        method: "POST",
      }).catch(() => {});
    }
    await clearAuth();
    showLoginScreen();
  });

  // ── Grab selected text from the active tab ────────────────────────────────────────────────
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (!tabs[0]) return;
    chrome.scripting.executeScript(
      { target: { tabId: tabs[0].id }, function: getSelectionText },
      (injectionResults) => {
        if (injectionResults && injectionResults[0]?.result) {
          document.getElementById("ai-text").value = injectionResults[0].result;
        }
      }
    );
  });

  // â”€â”€ Listen for context menu verify requests â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  chrome.runtime.onMessage.addListener((message) => {
    if (message.action === "VERIFY_TEXT" && message.text) {
      document.getElementById("ai-text").value = message.text;
      runVerification(message.text);
    }
  });

  // â”€â”€ Verify button â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  document.getElementById("verify-btn").addEventListener("click", () => {
    const text = document.getElementById("ai-text").value.trim();
    if (!text) {
      showError("Please select or paste text to verify.");
      return;
    }
    runVerification(text);
  });

  // â”€â”€ Core verification function â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  async function runVerification(text) {
    const verifyBtn = document.getElementById("verify-btn");
    const loader = document.getElementById("loader");
    const resultDiv = document.getElementById("result");
    const errorMsg = document.getElementById("error-msg");

    verifyBtn.disabled = true;
    loader.style.display = "block";
    resultDiv.style.display = "none";
    errorMsg.style.display = "none";

    try {
      const { token } = await getStoredAuth();
      if (!token) {
        await clearAuth();
        showLoginScreen();
        return;
      }

      const res = await fetch(API_VERIFY_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`,
        },
        body: JSON.stringify({ question: "General Context", answer: text }),
      });

      if (res.status === 401) {
        await clearAuth();
        showLoginScreen();
        return;
      }

      if (!res.ok) throw new Error(`Backend error: ${res.status}`);

      const data = await res.json();
      showResult(data);
    } catch (err) {
      showError("Cannot reach backend. Make sure the server is running at localhost:8000");
    } finally {
      verifyBtn.disabled = false;
      loader.style.display = "none";
    }
  }

  // â”€â”€ Result rendering â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  function showResult(data) {
    const { score, verdict, explanation, sources_used } = data;
    const resultDiv = document.getElementById("result");
    const verdictEl = document.getElementById("verdict");
    const scoreEl = document.getElementById("score");
    const scoreBadge = document.getElementById("score-badge");
    const resultHeader = document.getElementById("result-header");
    const explanationEl = document.getElementById("explanation");
    const sourcesEl = document.getElementById("sources");

    resultDiv.style.display = "block";

    const verdictMap = {
      accurate: "âœ… Likely Accurate",
      verified: "âœ… Verified",
      uncertain: "âš ï¸ Uncertain",
      unverifiable: "â“ Unverifiable",
      hallucination: "ðŸš© Hallucination Detected",
      likely_hallucination: "ðŸš© Likely Hallucination",
    };
    verdictEl.textContent = verdictMap[verdict] || "â“ Unknown";
    scoreEl.textContent = score;

    resultHeader.className = "result-header";
    scoreBadge.className = "score-badge";

    if (verdict === "accurate" || verdict === "verified") {
      resultHeader.classList.add("accurate");
      scoreBadge.classList.add("high");
    } else if (verdict === "uncertain" || verdict === "unverifiable") {
      resultHeader.classList.add("uncertain");
      scoreBadge.classList.add("mid");
    } else {
      resultHeader.classList.add("hallucination");
      scoreBadge.classList.add("low");
    }

    explanationEl.textContent = explanation;

    if (sources_used && sources_used.length > 0) {
      sourcesEl.innerHTML = sources_used.map((s) => `<span class="source-tag">${s}</span>`).join("");
    } else {
      sourcesEl.innerHTML = '<span class="source-tag">None</span>';
    }

    const claimsDiv = document.getElementById("claims-breakdown");
    if (data.claim_results && data.claim_results.length > 0) {
      const verdictLabels = {
        accurate: "âœ… Accurate",
        uncertain: "âš ï¸ Uncertain",
        hallucination: "ðŸš© Hallucination",
      };
      let claimsHTML = '<div class="claims-section"><div class="claims-title">Per-Claim Breakdown</div>';
      data.claim_results.forEach((claim) => {
        const scoreClass = claim.score >= 70 ? "high" : claim.score >= 40 ? "mid" : "low";
        const verdictLabel = verdictLabels[claim.verdict] || "â“ Unknown";
        claimsHTML += `
          <div class="claim-card ${claim.verdict}">
            <div class="claim-header">
              <span class="claim-verdict">${verdictLabel}</span>
              <div class="claim-score ${scoreClass}">${claim.score}</div>
            </div>
            <div class="claim-text">"${escapeHTML(claim.claim_text)}"</div>
            <div class="claim-explanation">${escapeHTML(claim.explanation)}</div>
          </div>`;
      });
      claimsHTML += "</div>";
      claimsDiv.innerHTML = claimsHTML;
    } else {
      claimsDiv.innerHTML = "";
    }
  }

  function showError(msg) {
    const errorMsg = document.getElementById("error-msg");
    errorMsg.textContent = msg;
    errorMsg.style.display = "block";
    setTimeout(() => { errorMsg.style.display = "none"; }, 5000);
  }
});



// Runs in context of active web page
function getSelectionText() {
  return window.getSelection().toString();
}
