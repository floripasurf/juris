// Content script — runs in the Claude.ai/ChatGPT tab. Receives a (de-identified)
// CompletionRequest relayed from the native host via the background worker, drives
// the chat UI, and returns a CompletionResponse. The DOM details live in
// selectors.js so this file stays about flow + robustness.
//
// Security: the prompt arrives already de-identified (juris de-id runs before the
// bridge). We never persist it — no localStorage/sessionStorage, just a transient
// closure that is GC'd after the reply.

import { providerFor, findComposer, isStreaming, extractResponse, detectBlocker } from "./selectors.js";

const TIMEOUT_MS = 120000; // hard cap on a single completion
const POLL_MS = 400;
const SETTLE_MS = 800; // text must hold steady (no streaming) this long before we trust it

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function fail(request_id, error) {
  return { request_id, success: false, content: null, error };
}

// Resolve only when generation has stopped AND the text is non-empty and stable.
// A partial/streaming answer is NEVER returned as success.
async function waitForCompletion(provider, request_id) {
  const start = Date.now();
  let lastText = null;
  let settledSince = null;

  while (Date.now() - start < TIMEOUT_MS) {
    await sleep(POLL_MS);

    if (isStreaming(document, provider)) {
      settledSince = null;
      lastText = extractResponse(document, provider);
      continue;
    }

    const text = extractResponse(document, provider);
    if (!text) continue; // not streaming but nothing yet — keep waiting

    if (text === lastText) {
      settledSince ??= Date.now();
      if (Date.now() - settledSince >= SETTLE_MS) {
        return { request_id, success: true, content: text, error: null };
      }
    } else {
      lastText = text;
      settledSince = null;
    }
  }
  return fail(request_id, "timeout aguardando a resposta finalizar");
}

// Insert text into a (React) editor reliably: execCommand keeps the editor's own
// handling intact; the input event makes the framework register the change.
function insertPrompt(composer, text) {
  composer.focus();
  document.execCommand("insertText", false, text);
  composer.dispatchEvent(new InputEvent("input", { bubbles: true, data: text, inputType: "insertText" }));
}

// Prefer the send button (more reliable on modern UIs than a synthetic Enter).
function submit(composer, provider) {
  const btn = provider.sendButton ? document.querySelector(provider.sendButton) : null;
  if (btn && !btn.disabled) {
    btn.click();
    return;
  }
  composer.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
}

const BLOCKER_MESSAGES = {
  not_logged_in: "sessão não logada — faça login no Claude.ai/ChatGPT",
  rate_limited: "limite de uso da sessão atingido — tente mais tarde",
};

async function complete({ request_id, prompt, system }) {
  const provider = providerFor(location.host);
  if (!provider) return fail(request_id, "provedor não suportado nesta aba");

  const blocker = detectBlocker(document, provider);
  if (blocker) return fail(request_id, BLOCKER_MESSAGES[blocker]);

  const composer = findComposer(document, provider);
  if (!composer) return fail(request_id, "composer não encontrado — faça login na sessão");

  try {
    const full = system ? `${system}\n\n${prompt}` : prompt;
    insertPrompt(composer, full);
    submit(composer, provider);
    const result = await waitForCompletion(provider, request_id);
    if (!result.success) {
      // a usage limit can appear mid-generation — report it precisely
      const post = detectBlocker(document, provider);
      if (post) return fail(request_id, BLOCKER_MESSAGES[post]);
    }
    return result;
  } catch (e) {
    return fail(request_id, `falha ao injetar/extrair: ${e?.message ?? e}`);
  }
}

// Background worker relays the request here and awaits the response.
if (typeof chrome !== "undefined" && chrome.runtime?.onMessage) {
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type !== "completion") return false;
    complete(msg.request).then(sendResponse);
    return true; // async response
  });
}

// Exported for unit tests (selectors.test.js covers the DOM bits directly).
export { complete, waitForCompletion };
