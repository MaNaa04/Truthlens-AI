/**
 * AI Hallucination Detector - Background Service Worker
 * Handles context menu creation and message routing
 */

// Create context menu on install
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "verifyClaimMenu",
    title: "🛡️ Verify with Hallucination Detector",
    contexts: ["selection"],
  });
});

// Handle context menu click — send to content script for inline verification
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "verifyClaimMenu" && info.selectionText) {
    // Tell the content script on that tab to run verification
    chrome.tabs.sendMessage(tab.id, {
      action: "VERIFY_SELECTION",
      text: info.selectionText,
    });
  }
});
