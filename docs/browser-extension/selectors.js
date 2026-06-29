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
  },
  "chatgpt.com": {
    composer: '#prompt-textarea, div[contenteditable="true"]#prompt-textarea',
    responseBlocks: 'div[data-message-author-role="assistant"]',
    streaming: 'button[data-testid="stop-button"]',
  },
};

export function providerFor(host) {
  if (host.includes("claude.ai")) return PROVIDERS["claude.ai"];
  if (host.includes("chatgpt.com") || host.includes("chat.openai.com")) return PROVIDERS["chatgpt.com"];
  return null;
}

export function findComposer(doc, provider) {
  return doc.querySelector(provider.composer);
}

export function isStreaming(doc, provider) {
  return doc.querySelector(provider.streaming) !== null;
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
