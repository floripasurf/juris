// Isolated per-provider DOM selectors + extraction. Pure functions, unit-tested
// against a jsdom fixture — the one place to retune when Claude.ai/ChatGPT change
// their UI. content.js orchestrates; this module knows the DOM.

export const PROVIDERS = {
  "claude.ai": {
    // the chat composer (contenteditable)
    composer: 'div[contenteditable="true"]',
    // assistant message containers; the last one is the current reply
    responseBlocks: '.font-claude-message, [data-testid="assistant-message"]',
    // present only while the model is still generating
    streaming: 'button[aria-label="Stop response"], [data-testid="stop-button"]',
    // a login wall (no usable session)
    loginWall: 'a[href*="/login"], a[href*="/sign-in"], [data-testid="login-button"]',
    // the send button (preferred over Enter when present)
    sendButton: 'button[aria-label="Send message"], button[aria-label="Send Message"]',
  },
  "chatgpt.com": {
    composer: '#prompt-textarea, div[contenteditable="true"]#prompt-textarea',
    responseBlocks: 'div[data-message-author-role="assistant"]',
    streaming: 'button[data-testid="stop-button"]',
    loginWall: 'a[href*="/auth/login"], button[data-testid="login-button"]',
    sendButton: 'button[data-testid="send-button"]',
  },
};

// Usage/rate-limit messages (provider-agnostic text patterns).
const RATE_LIMIT_PATTERNS = [
  /usage limit/i,
  /reached your limit/i,
  /rate limit/i,
  /try again later/i,
  /limite de uso/i,
  /muitas mensagens/i,
];

export function providerFor(host) {
  if (host.includes("claude.ai")) return PROVIDERS["claude.ai"];
  if (host.includes("chatgpt.com") || host.includes("chat.openai.com")) return PROVIDERS["chatgpt.com"];
  return null;
}

// Canonical provider id for the wire ("claude"/"chatgpt") — the server compares
// canonical ids, never UI labels (spec 2026-07-05).
export function providerIdFor(host) {
  if (host.includes("claude.ai")) return "claude";
  if (host.includes("chatgpt.com") || host.includes("chat.openai.com")) return "chatgpt";
  return null;
}

export function findComposer(doc, provider) {
  return doc.querySelector(provider.composer);
}

export function isStreaming(doc, provider) {
  return doc.querySelector(provider.streaming) !== null;
}

// Why a completion can't proceed: "not_logged_in" | "rate_limited" | null.
// content.js turns this into a clear error instead of a partial/empty answer.
export function detectBlocker(doc, provider) {
  if (provider.loginWall && doc.querySelector(provider.loginWall)) return "not_logged_in";
  const text = doc.body ? doc.body.textContent || "" : "";
  if (RATE_LIMIT_PATTERNS.some((re) => re.test(text))) return "rate_limited";
  return null;
}

// The current assistant reply text, or null if there isn't one yet. Returning null
// (rather than "") lets content.js distinguish "still empty" from "done".
export function extractResponse(doc, provider) {
  const blocks = doc.querySelectorAll(provider.responseBlocks);
  if (!blocks.length) return null;
  const last = blocks[blocks.length - 1];
  const text = (last.textContent || "").trim();
  return text.length > 0 ? text : null;
}
